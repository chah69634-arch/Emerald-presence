# Spec #9 — 流式输出（Streaming Output）

> 状态：待实现  
> 难度：中-大  
> 改动范围：后端 `core/llm_client.py`、`core/pipeline.py`、`channels/desktop_ws.py`、`admin/routers/chat.py`；前端 `Emerald-client/src/shared/api/ws.ts`、`src/windows/chat/components/ChatPanel.tsx`

---

## 目标与约束

让桌宠端（desktop）的角色回复**逐 token 实时显示**，像真的在打字，而不是转圈等一整段。

**明确的设计决策（已和需求方对齐）：**

1. **token 级流式**——逐 token 推，不是句级。
2. **渲染标签边界交给前端处理**——后端原样透传 token；前端检测到 `<` 就开一个对应格式的 UI 框，检测到 `>` 收拢，再继续检测下一个标签。后端不做标签缓冲。
3. **QQ 不变**——QQ 是 IM，只能发完整消息，流式对它无意义。QQ 链路保持现状。
4. **只有 desktop（WS）走流式**——mobile 轮询、QQ 都收完整版。
5. **记忆/清洗链路不流式**——`record_assistant_turn` / `scrub` / Path B intent 解析全部依赖**完整文本**，在流结束、拿到完整字符串后再跑一遍。流式只改"可见输出"这一条路。

---

## 架构决策

桌宠现有链路（见 `docs/known-issues.md` B11）：HTTP `/desktop/chat` 触发一轮，**WS `channel_message` 是主渲染路径**，HTTP reply 仅在 WS 没到时兜底。

流式沿用这个分工：

```
HTTP /desktop/chat 触发 turn
        ↓
run_owner_chat_turn（conversation_lock 内）
        ↓
  probe → fetch_context → build_prompt
        ↓
  run_llm_stream() ──逐 token──→ desktop_ws.push_stream_delta()  ← 前端实时渲染
        ↓（流结束，拿到完整 reply）
  scrub / clean_reality_reply_text
        ↓
  desktop_ws.push_message(canonical)  ← 发"最终干净版"，前端用它替换流式临时气泡
        ↓
  record_assistant_turn(full_reply)  ← 记忆写入用完整文本（不受流式影响）
```

**关键点**：流式推的是**原始 token**，最后 `push_message` 推的是**scrub 后的干净文本**。前端在流结束时用干净版替换临时气泡。scrub 对 reality 输出改动通常很小（去工具残留 / 角色名前缀 / AI 自曝），视觉上是"流完轻微 settle 一下"，可接受。

---

## 后端实现步骤

### Step 1：`core/llm_client.py` 新增 `chat_stream`

在 `chat()` 旁边加一个 async generator，只处理**无工具的普通对话**（流式不支持 function_calling——工具探测本来就是单独一次非流式 probe，主生成这一步没有 tools）。

```python
async def chat_stream(
    messages: list[dict],
    max_tokens_override: int | None = None,
    call_category: str = "chat",
):
    """流式生成，逐 token yield 文本增量（async generator）。

    仅用于无工具的主生成。function_calling / xml_fallback / vision 不走流式。
    失败时抛异常（调用方负责降级到非流式）。
    """
    _timeout = _CALL_TIMEOUTS.get(call_category, _DEFAULT_CALL_TIMEOUT)
    messages = sanitize_messages(messages)

    cfg = get_config()["llm"]
    client = _get_client()
    model = cfg["model"]

    temperature       = float(cfg.get("temperature",       0.7))
    top_p             = float(cfg.get("top_p",             0.9))
    max_tokens        = max_tokens_override or int(cfg.get("max_tokens", 1000))
    frequency_penalty = float(cfg.get("frequency_penalty", 0.0))

    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        frequency_penalty=frequency_penalty,
        timeout=_timeout,
        stream=True,                       # ← 关键
    )
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None)
        if piece:
            yield piece
```

> 注意：OpenAI/DeepSeek SDK 的 `stream=True` 返回 async iterator，每个 chunk 的 `delta.content` 是增量。DeepSeek 兼容 OpenAI 协议，行为一致。

---

### Step 2：`core/pipeline.py` 新增 `run_llm_stream`

`run_llm()` 旁边加一个流式版，**带降级**：流式失败时回退到非流式 `run_llm`，保证永远有输出。

```python
async def run_llm_stream(self, messages: list[dict]):
    """流式生成，逐 token yield。失败时降级为非流式整段 yield 一次。"""
    from core import llm_client
    try:
        got_any = False
        async for piece in llm_client.chat_stream(messages):
            got_any = True
            yield piece
        if got_any:
            return
        # 流式没产出任何 token → 降级
    except Exception as e:
        from core.error_handler import log_error
        log_error("pipeline.run_llm_stream", e)
    # 降级：非流式整段
    full = await self.run_llm(messages)
    if full:
        yield full
```

> `run_llm` 自带 `with_retry`；流式版失败直接降级到它，不重复加 retry。

---

### Step 3：`channels/desktop_ws.py` 新增流式帧

现有 `push_message`（`channel_message`）/`push_segments`（`message_segments`）不动，新增一组流式帧。三种帧共享同一个 `msg_id`，前端凭 msg_id 把它们关联到同一条消息。

```python
async def push_stream_start(msg_id: str) -> bool:
    """流式开始。前端创建一个空的临时气泡。"""
    return await _send_json({
        "type": "message_stream_start",
        "msg_id": msg_id,
        "source": "reality",
        "ts": time.time(),
    })


async def push_stream_delta(msg_id: str, delta: str) -> bool:
    """流式增量。fire-and-forget，不等 ack。"""
    return await _send_json({
        "type": "message_stream_delta",
        "msg_id": msg_id,
        "delta": delta,
        "ts": time.time(),
    })


async def push_stream_end(msg_id: str) -> bool:
    """流式结束标记。前端停止临时气泡的'打字中'状态。

    注意：真正的 canonical 文本随后由 push_message(同 msg_id) 下发，
    前端用它替换临时气泡内容（scrub 后的干净版）。
    """
    return await _send_json({
        "type": "message_stream_end",
        "msg_id": msg_id,
        "ts": time.time(),
    })
```

`_new_msg_id()` 已存在，复用它生成共享 msg_id。

---

### Step 4：`admin/routers/chat.py` — `run_owner_chat_turn` 流式分支

当前 `run_owner_chat_turn`（line 29 起）在 `conversation_lock` 内：`probe → fetch_context → build_prompt → run_llm → clean → record_assistant_turn`。

改造：**desktop channel 且 WS 已连接**时走流式分支，其余 channel 保持原非流式逻辑。

把原来这段：
```python
        reply = await pipeline.run_llm(messages)
        if not reply:
            reply = ""
```

替换为：
```python
        from channels import desktop_ws

        _use_stream = (channel_name == "desktop") and desktop_ws.is_connected()
        if _use_stream:
            # 预生成共享 msg_id，三种流式帧 + 最终 channel_message 共用
            _stream_msg_id = desktop_ws._new_msg_id()
            await desktop_ws.push_stream_start(_stream_msg_id)
            _chunks: list[str] = []
            try:
                async for piece in pipeline.run_llm_stream(messages):
                    _chunks.append(piece)
                    await desktop_ws.push_stream_delta(_stream_msg_id, piece)
            finally:
                await desktop_ws.push_stream_end(_stream_msg_id)
            reply = "".join(_chunks)
        else:
            _stream_msg_id = None
            reply = await pipeline.run_llm(messages)
        if not reply:
            reply = ""
```

下面的 scrub（`clean_reality_reply_text`）保持不变。

**record_assistant_turn 透传 msg_id**：让最终 canonical `channel_message` 用同一个 msg_id，前端才能替换临时气泡。检查 `record_assistant_turn` 的 fanout → `desktop_ws.push_message` 链路是否能指定 msg_id；若不能，在 record 之后单独补发一帧：

```python
        # 流式路径：record 走完后，用同一 msg_id 推 canonical 干净版替换临时气泡
        if _stream_msg_id and reply:
            from core.response_processor import strip_render_tags as _strip_tags
            await desktop_ws.push_message(_strip_tags(reply) or reply, msg_id=_stream_msg_id)
```

> 如果 `record_assistant_turn` 的 fanout 已经会推 `channel_message`，要避免**重复推**：流式路径让 record 的 fanout 排除 desktop（`exclude_origin_channel="desktop"`），canonical 帧由上面这段单独发。具体看 record_assistant_turn 现有的 `exclude_origin_channel` 参数怎么用。

---

## 前端实现步骤（Emerald-client）

### Step 5：`src/shared/api/ws.ts`

**5a. EventMap 加三个事件：**
```typescript
type EventMap = {
  state: ConnectionState;
  channel_message: { content: string; msg_id: string; source?: string };
  message_segments: { content: string; segments: NarrativeSegment[]; msg_id: string; source?: string };
  action: DesktopActionPayload;
  message_stream_start: { msg_id: string };
  message_stream_delta: { msg_id: string; delta: string };
  message_stream_end: { msg_id: string };
};
```

**5b. 在 WS 消息分发处（现有 `channel_message` / `message_segments` 解析的同一个 switch/if 链）加三种类型的 emit：**
```typescript
// 找到现有处理 channel_message 的地方，平行加：
if (msg.type === 'message_stream_start') { this.emit('message_stream_start', { msg_id: msg.msg_id }); return; }
if (msg.type === 'message_stream_delta') { this.emit('message_stream_delta', { msg_id: msg.msg_id, delta: msg.delta }); return; }
if (msg.type === 'message_stream_end')   { this.emit('message_stream_end', { msg_id: msg.msg_id }); return; }
```

---

### Step 6：`src/windows/chat/components/ChatPanel.tsx` — 增量渲染 + 标签框

ChatPanel 已有 `wsClient.on('channel_message', ...)`（line 975）和 `wsClient.on('message_segments', ...)`（line 985）。加三个流式订阅：

```typescript
// 临时流式气泡状态：msg_id -> 累积文本
const streamingRef = useRef<Map<string, string>>(new Map());

useEffect(() => {
  const unsubStart = wsClient.on('message_stream_start', ({ msg_id }) => {
    streamingRef.current.set(msg_id, '');
    // 在消息列表里插入一个 isStreaming=true 的临时气泡
    appendStreamingBubble(msg_id);
  });

  const unsubDelta = wsClient.on('message_stream_delta', ({ msg_id, delta }) => {
    const prev = streamingRef.current.get(msg_id) ?? '';
    const next = prev + delta;
    streamingRef.current.set(msg_id, next);
    updateStreamingBubble(msg_id, next);   // 增量更新气泡文本
  });

  const unsubEnd = wsClient.on('message_stream_end', ({ msg_id }) => {
    markStreamingBubbleDone(msg_id);       // 去掉"打字中"光标，等 canonical 替换
    // 不删 streamingRef，等 channel_message 同 msg_id 到达时替换
  });

  return () => { unsubStart(); unsubDelta(); unsubEnd(); };
}, []);
```

**canonical 替换**：现有 `channel_message` 处理逻辑里，若 `msg_id` 命中一个 streaming 气泡，用 canonical content **替换**临时气泡内容并清掉 streaming 标记（而不是新插一条）。

```typescript
// 在现有 channel_message handler 里加判断：
const unsubMsg = wsClient.on('channel_message', (message) => {
  if (streamingRef.current.has(message.msg_id)) {
    replaceStreamingBubble(message.msg_id, message.content);  // 用干净版替换
    streamingRef.current.delete(message.msg_id);
    return;
  }
  // ...原有逻辑
});
```

**标签框渲染（你定的方案）**：在渲染流式气泡文本时，做一个**轻量状态机**逐字扫描已累积文本——

```typescript
// 渲染时：遇到 '<' 进入"标签框"模式，遇到匹配的 '>' 收拢，框内用对应 UI 样式
function renderStreamingContent(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let buf = '';
  let inTag = false;
  let tagBuf = '';
  for (const ch of text) {
    if (!inTag && ch === '<') {
      if (buf) { nodes.push(<span key={nodes.length}>{buf}</span>); buf = ''; }
      inTag = true; tagBuf = '<';
    } else if (inTag && ch === '>') {
      tagBuf += '>';
      // 一个完整标签收拢 → 渲染成对应的 UI 框
      nodes.push(<TagBox key={nodes.length} raw={tagBuf} />);
      inTag = false; tagBuf = '';
    } else if (inTag) {
      tagBuf += ch;
    } else {
      buf += ch;
    }
  }
  // 流未结束时，未闭合的 tagBuf 处于"半个标签"状态——
  // 渲染成一个"正在生成"的占位框，等 '>' 到了再收拢（你要的效果）
  if (inTag && tagBuf) nodes.push(<TagBoxPending key={nodes.length} raw={tagBuf} />);
  if (buf) nodes.push(<span key={nodes.length}>{buf}</span>);
  return nodes;
}
```

`TagBox` / `TagBoxPending` 是你按现有渲染标签语义实现的组件（沿用现有的 `<ticker>` 等标签的 UI 风格即可）。**这是你明确要的"标签交前端"逻辑**：半个标签先显示占位框，`>` 到了再收拢。

---

## 边界与注意事项

1. **工具调用不流式**。主生成这一步本来无 tools（工具探测是上游单独的非流式 probe），所以流式分支安全。若某轮先命中工具、再生成回复，回复那一步仍可流式（tool_result 已注入 prompt）。

2. **dream 不流式**。dream pipeline 完全独立、不经 `run_owner_chat_turn`，本 spec 不碰它。

3. **scrub 末尾 settle**。流式推原始 token，canonical 推 scrub 后文本，前端替换。若担心"跳变"明显，可让 scrub 尽量轻（现状已经很轻）。

4. **HTTP 返回值**。`/desktop/chat` 的 HTTP response 仍返回完整 reply（现有兜底逻辑：WS 没到才用 HTTP）。流式路径下 WS 一定先到，HTTP reply 不会被渲染，但保留以防 WS 断开。

5. **流式中途断流**。`run_llm_stream` 已有降级；若 WS 在流中途断开，`push_stream_delta` 返回 False，记忆写入仍用累积的 `reply`（可能不完整）——可接受，因为 record 用的是 `"".join(_chunks)`，断流时是"已生成部分"。若要更严谨，断流时改用非流式重生成，但通常不必要。

6. **QQ / mobile fanout 不变**。流式只在 `channel_name == "desktop"` 分支触发；QQ turn（main.py）和 mobile 完全不受影响，仍收完整 `channel_message`。

7. **record_assistant_turn 重复推问题**。务必确认 canonical 帧只推一次——要么靠 record 的 fanout，要么靠 Step 4 末尾手动补发，二选一，别两条都推（会出现重复气泡）。

---

## 验证方式

1. 桌宠端发一条消息，观察气泡是否逐字出现。
2. 让角色回复里带渲染标签（如 `<ticker>`），观察前端是否先显示半个标签占位框、`>` 到达后收拢成完整 UI 框。
3. 流结束后气泡内容应被 canonical 干净版替换（无工具残留 / 无角色名前缀）。
4. 同一轮在 QQ 端（若同时在线）应收到完整消息，不受影响。
5. 断开 WS 后发消息，确认 HTTP 兜底仍返回完整 reply。

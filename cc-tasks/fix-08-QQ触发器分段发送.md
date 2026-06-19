# FIX-08 · QQ 触发器整段发送，改为分段

> 后端，先读 `docs/channels.md` + `docs/scheduler.md`。改动小、边界清晰。

## 现象

QQ 上叶瑄主动消息（触发器）是**一整段**发出来的；正常对话回复却是分条（多气泡）发的。两条路径不一致。

## 现状（已核对，根因）

两条 QQ 出口走了不同的发送实现：

- **正常回复路径**（`main.py:474`）：`response_processor.process(raw_reply, name)` 切成 `segments` → `_qq_reality_reply_adapter` → `text_output.send(target, segments, is_group)`。
  - `core/output/text_output.py send`（:20）**逐段** `qq_adapter.send_message`，段间还有 `_SEGMENT_DELAY` 停顿，模拟真人。→ 分条。
- **触发器路径**：`core/scheduler/loop.py:257 _send(content)` → `channels.registry.broadcast(content, oid)`（`registry.py:46 channel.send(content, ...)`）→ `channels/qq.py:48 QQChannel.send` → `qq_adapter.send_message(_target, content, is_group)`。
  - **content 是整串，从不过 `response_processor.process`，一次性发完。** → 整段。

根因：触发器经 `broadcast → QQChannel.send` 直发原文，绕开了正常路径的"切段 + 逐条发"。

## 设计决策

**在哪一层补分段？**

- **方案 A（推荐）**：在 `QQChannel.send` 内对 content 做 `response_processor.process` 后逐段发（复用 `text_output.send` 的逐段+停顿逻辑）。
  - 好处：所有经 broadcast 到 QQ 的内容（触发器、其它主动消息）统一分条，一处修全覆盖。
  - 注意：`QQChannel.send` 也被 `turn_sink._fanout` 调用（见 qq.py:40 注释）——确认那条路径传入的是否已是整段、会不会被二次切分导致重复。fanout 当前 private 路由用 `user_id`，正常对话的可见发送已在 `text_output.send` 完成、fanout 传 `fanout=[]`（见 `main.py:632`），所以 QQChannel.send 的 fanout 调用主要服务非 QQ 可见态——**务必核对不要双发**。
- **方案 B**：只在 scheduler 触发发送侧（`loop.py _send` 或更上层 deliver）先 `process` 再发。
  - 好处：作用域精确锁定"触发器"，不动通用 channel.send，规避 fanout 双发风险。
  - 代价：其它走 broadcast 的主动消息不自动受益。

> 建议：先确认 `QQChannel.send` 的所有调用方（broadcast 触发器 / turn_sink fanout / 其它），若 fanout 路径不会重复发，则 **A** 一处覆盖最干净；否则取 **B** 精准改触发器路径。cc 先 grep 调用方再定。

## 实现要点

1. 选定层后，调用 `response_processor.process(content, character.name)` 切段（character 名从 `pipeline_registry` 取，参考 `loop.py:_char_name`）。
2. 逐段发送 + 段间停顿，直接复用/调用 `text_output.send(target, segments, is_group)`，不要重写一套。
3. 触发器是私聊主动消息：`is_group=False`、target=owner，确认路由正确。
4. 核对**不双发**（fanout / broadcast 任一路径都不能让同一条消息发两次）。

## 验收

- 触发器主动消息在 QQ 上分条发出（与正常回复一致），段间有停顿。
- 正常回复不受影响、不重复发送。
- 桌宠/mobile 通道行为不回归。
- `pytest`（channels / scheduler send 相关用例）。

## 备注

`text_output.send` 还有 `chat.multi_message` 配置控制是否按换行再拆（:36 `_split_by_newline`）——复用它即可自动继承这个行为，无需在触发器侧另写拆分。

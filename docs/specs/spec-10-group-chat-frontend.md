# Spec #10（前端篇）— 多角色群聊前端接入

> 配套 `spec-10-group-chat.md`（后端运行时）。本篇定义**三端协议 + Emerald-client 接入**：WS 帧、HTTP 端点、Tauri Rust 命令、React 数据契约与渲染模型。给前端/Rust 实现者 + Codex。
> 最近核对：2026-06-13

---

## 0. 全栈分层（改哪层、为什么）

```
React (src/shared/api/*, src/windows/chat/*)
   │  invoke(cmd)                         listen(native ws event)
   ▼                                        ▲
Tauri Rust (src-tauri/src/lib.rs)          │  原样转发 WS 原文
   │  HTTP 代理（authorized_request）       │
   ▼                                        │
后端 FastAPI (admin/routers/*)  +  WS (channels/desktop_ws.py)
```

**关键事实（决定工作量）**：

1. **WS 帧在 Rust 层是「透明转发原文」**——Rust 不解析帧类型，React `ws.ts:_handleMessage` 和后端各自解析。
   → **新增/扩展 WS 帧 = 只改后端 + React，Rust 不动。**
2. **HTTP 走 Tauri `#[tauri::command]` 代理**（如 `send_chat` → POST `/desktop/chat`）。
   → **新增 HTTP 端点 = 后端路由 + Rust 命令 + `backend.ts` wrapper 三处。**
3. **角色花名册/头像已有现成接口**：`/settings/prompt-assets` 返回 `characters: PromptAssetCharacter[]`（含 `id/label/avatar_url`），`get_character_avatar(charId)` 取头像。群聊 roster UI 直接复用，**不用新建角色清单接口**。

---

## 1. WS 协议扩展（后端 + React，Rust 不动）

### 1.1 给现有帧加发言人位 `char_id`（spec-10 防②）
`channel_message` / `message_segments` / `message_stream_start|delta|end` 全部增加**可选** `char_id`：

- 一对一：`char_id` 省略（或 = 当前活跃角色），旧行为不变。
- 群聊：每帧必带说话者 `char_id`。
- 旧客户端忽略未知字段 → 零成本向后兼容。

### 1.2 新增「回合生命周期」帧（让 UI 知道一轮何时开始/结束）
arbiter 一轮会推多条消息，UI 需要知道边界来开关输入框 / 显示「对方在打字」。

```ts
// 追加到 ServerMessage 联合 + ws.ts EventMap + _handleMessage switch
| { type: 'group_round_start'; round_id: string; group_id: string }
| { type: 'group_round_end';   round_id: string; group_id: string }
```

> 「谁在打字」不另设帧：`message_stream_start{char_id}` 到达即视为该角色开始说话；省一个帧类型。

### 1.3 最终 WS 帧契约（React `types.ts`）
```ts
export type ServerMessage =
  | { type: 'channel_message'; content: string; msg_id: string; source?: string; char_id?: string; round_id?: string }
  | { type: 'message_segments'; content: string; segments: NarrativeSegment[]; msg_id: string; source?: string; char_id?: string }
  | { type: 'message_stream_start'; msg_id: string; char_id?: string; round_id?: string }
  | { type: 'message_stream_delta'; msg_id: string; delta: string }
  | { type: 'message_stream_end';   msg_id: string }
  | { type: 'group_round_start'; round_id: string; group_id: string }
  | { type: 'group_round_end';   round_id: string; group_id: string }
  // …现有 hello_ack / action / ping 不变
```
> `source` 仍区分 `reality` / `dream`：梦境群聊帧打 `source:"dream"`，reality 群聊 UI 忽略 dream 帧（沿用现有隔离）。

**后端落点**：`channels/desktop_ws.py` 的 `push_message/push_segments/push_stream_*` 增加 `char_id` 参数；新增 `push_group_round_start/end`。`core/turn_sink.py` fanout 时把 speaker 的 `char_id` 传进去。

---

## 2. HTTP 端点 + Rust 命令 + backend.ts（三处同步）

> 命名沿用现有风格（`/settings/prompt-assets` → `get_prompt_assets`）。所有 Rust 命令照抄 `send_chat` 的 `authorized_request` / `safe_http_error` 模式。

| 能力 | 后端端点 | Rust 命令 | backend.ts wrapper |
|---|---|---|---|
| 列群 | `GET /group/list` | `group_list` | `listGroups()` |
| 建群 | `POST /group/create` | `group_create` | `createGroup(roster, domain, settings)` |
| 取群（roster+设置+近期 transcript） | `GET /group/{id}` | `group_get` | `getGroup(id)` |
| 发消息（触发 arbiter 一轮） | `POST /group/{id}/send` | `group_send` | `groupSend(id, message)` |
| 读历史（分页 transcript） | `GET /group/{id}/history?before=` | `group_history` | `groupHistory(id, before?)` |
| 读/改设置（N/M 等） | `GET|PATCH /group/{id}/settings` | `group_settings_get`/`group_settings_patch` | `getGroupSettings`/`patchGroupSettings` |

**`group_send` 的形态**：HTTP **立即返回** `{ round_id, status:"accepted" }`（不阻塞等整轮），整轮回复经 WS 逐条推送（每条带 `char_id`+`round_id`），以 `group_round_end{round_id}` 收尾。
理由：一轮 N..M 条消息 + 流式，阻塞式 HTTP 体验差且与现有流式渲染范式冲突。owner 自己的消息前端乐观本地上屏（与现有 1v1 一致）。

---

## 3. React 数据契约（`types.ts`）

```ts
export type GroupDomain = 'reality' | 'dream';

export interface GroupSettings {
  min_responders: number;     // N
  max_responders: number;     // M
  max_ai_chain_depth: number; // 默认 2
  addressed_exclusive: boolean;
}

export interface GroupRosterMember {
  char_id: string;
  label: string;              // 来自 PromptAssetCharacter.label
  avatar_url: string | null;  // 来自 PromptAssetCharacter.avatar_url
}

export interface GroupSummary {
  group_id: string;
  domain: GroupDomain;
  roster: GroupRosterMember[];
  title: string;
}

export interface GroupMessage {
  msg_id: string;
  speaker_id: 'owner' | string; // 'owner' 或 char_id
  content: string;
  timestamp: number;
  segments?: NarrativeSegment[];
  triggered_by?: 'user' | string;
}

export interface GroupDetail extends GroupSummary {
  settings: GroupSettings;
  recent: GroupMessage[];     // 近 K 条 transcript
}

export interface GroupSendResponse { round_id: string; status: string; }
```

---

## 4. 渲染模型（`src/windows/chat/` 新增 GroupChatPanel）

新建 `GroupChatPanel`，**复用现有 ChatPanel 的流式引擎**（msg_id→气泡列表、`splitReply` 分气泡、stream-replace 收口）。差异只在「多发言人」：

### 4.1 ChatMsg 加发言人维度
```ts
interface ChatMsg {
  // …现有字段
  speakerId?: string;   // char_id；缺省 = owner（右侧气泡）
}
```
- `message_stream_start{char_id}` 到达时，建临时气泡时写入 `speakerId = char_id`，于是流式过程中就带头像/名字。
- canonical / segments 收口沿用 §spec-10-前端已实现的 `replaceStreamingBubbleWithParts`，仅多透传 `speakerId`。

### 4.2 气泡样式（类微信群）
- `speakerId` 存在 → **左侧**气泡 + 头像 + 角色名标签（名字仅在「换人」时显示，连续同一人省略）。
- owner（无 speakerId）→ **右侧**气泡，无头像名。
- 头像/名字来源：进群时用 `getGroup(id).roster` 建一个 `Map<char_id, {label, avatar_url}>` 缓存；头像走 `get_character_avatar(charId)`（已存在）。

### 4.3 回合 → 输入框开关
- `group_round_start` → 锁输入框，显示「成员陆续回应中…」。
- 每个 `message_stream_start{char_id}` → 该成员头像处显示「正在输入」。
- `group_round_end` → 解锁输入框。
- 超时兜底：与现有 1v1 一样留一个 HTTP/计时兜底（round 长时间无 `group_round_end` 则解锁），防卡死。

### 4.4 并发说明
arbiter 串行生成（spec-10 §8），**同一时刻只有一条活跃流**，但不同消息属于不同 `char_id`。现有「msg_id→气泡」模型天然支持，无需多流并发逻辑；只需把 `char_id` 挂到气泡上。

---

## 5. 复用清单（不要重造）

| 需求 | 直接复用 |
|---|---|
| 角色清单 + 头像 | `/settings/prompt-assets` → `PromptAssetCharacter[]`、`get_character_avatar` |
| 流式分气泡渲染 | ChatPanel 的 `replaceStreamingBubbleWithParts` / `splitReply` / streaming refs |
| 串行回合锁 | 后端 `conversation_gate.conversation_lock`（spec-10 §8） |
| 梦境群聊 UI | 走现有 dream 窗口范式（`src/windows/dream/`），帧 `source:"dream"`，不进 reality GroupChatPanel |
| WS 连接/重连/心跳 | 现有 `WSClient`（只加帧类型，不动连接逻辑） |

---

## 6. 实现 checklist（按层，Codex 可逐项打勾）

**后端**
- [ ] `core/stage/`：Group 实体 + arbiter（spec-10 §8）+ 共享 transcript 存储（§6）
- [ ] `admin/routers/group.py`：§2 六个端点
- [ ] `channels/desktop_ws.py`：push 函数加 `char_id`；新增 `push_group_round_start/end`
- [ ] `core/turn_sink.py`：fanout 透传 speaker `char_id`

**Rust（src-tauri/src/lib.rs）**
- [ ] 六个 `group_*` 命令（照 `send_chat` 模式）
- [ ] 注册进 `invoke_handler!`（generate_handler 列表）
- [ ] **WS 帧无需改 Rust**（透明转发）

**React**
- [ ] `types.ts`：ServerMessage 加 `char_id`/`round_id` + 两个 round 帧；新增 §3 Group 契约
- [ ] `ws.ts`：EventMap + `_handleMessage` 处理 `group_round_start/end`，现有帧透传 `char_id`
- [ ] `backend.ts`：六个 wrapper
- [ ] `ChatMsg.speakerId` + `GroupChatPanel`（复用流式引擎）+ roster 头像缓存
- [ ] 入口：群列表 / 建群（从 `PromptAssetCharacter` 多选 roster + 选 domain + N/M 设置）

**契约测试**（仓库已有 activity 6 点同步的 contract test 范式，照搬）
- [ ] WS 帧 round-trip（后端 push 字段 ↔ React 解析）
- [ ] `group_*` 命令签名 ↔ 后端端点 schema 对齐

---

## 7. v1 范围

- ✅ **Chat 版（reality）GroupChatPanel** 先做完整：建群 / 发消息 / 多发言人流式 / 回合开关 / 历史。
- ✅ WS `char_id` + round 帧；Rust 六命令；React 契约 + 面板。
- ⏳ **梦境版群聊**：协议同构（`source:"dream"`），但 UI 挂 dream 窗口，待 reality 版稳定后接。
- ❌ proactive 群触发（与 spec-10 §11 一致，v1 不做）。

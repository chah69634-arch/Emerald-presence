# docs/interaction-event-model.md — Interaction / Event Envelope Model

> 状态：v0.1 概念设计文档（internal soak prep）。
> 本文描述三维 envelope 设计意图和 v0.1 实现边界。代码以源码为准；本文在设计意图与代码不一致时保留历史语义并在 DELTA 段注明差异。

---

## 一、三维 Envelope

每个进入系统的交互事件由三个正交维度 + meta 字段描述：

### 1.1 Realm（世界层）

| 值 | 含义 |
|---|---|
| `reality` | 现实会话（正常陪伴 pipeline，写 short_term / memory） |
| `dream` | 梦境会话（独立 dream pipeline，不写现实记忆） |

两个 realm **完全隔离**：dream 事件不经过 reality gate，reality 事件不进入 dream pipeline。
realm 在入梦时由 `dream_state.status` 决定，是系统级属性，**不由事件本身声明**。

### 1.2 Kind（事件种类）

| 值 | 含义 | v0.1 状态 |
|---|---|---|
| `message` | 用户发送的文字/图片消息 | ✅ 已实现 |
| `stimulus` | 系统主动触发（定时器、传感器、desktop wake） | ✅ 已实现（代码名 `trigger`） |
| `tool` | 工具调用结果回注 | 🚫 v0.2+，当前不作为独立 kind 处理 |
| `activity` | 活动会话生命周期事件 | 🚫 v0.2+ |

**v0.1 LLM 回复出口只产生 `message` 和 `stimulus` 两种 kind。** 任何 LLM 生成的结果通过 turn_sink 广播，不再以 event 形式回注系统。

### 1.3 Lifecycle（生命周期）

| 值 | 含义 |
|---|---|
| `oneshot` | 单次独立事件，不维持 session 状态 |
| `session` | 有明确开始/结束的会话（入梦/退梦、ActivitySession） |

v0.1 所有 reality 事件均为 `oneshot`。dream 作为整体是一个 `session`，但 dream 内部每轮 dream_turn 也是 `oneshot`。ActivitySession 为 v0.2+。

---

## 二、Meta 字段

```python
# 概念字段（对应 PerceiveEvent dataclass + trigger audit log）
event_id   : str       # 调用方提供的稳定 id；缺失时系统生成 uuid4
dedupe_key : str       # 幂等去重键；event_id 存在时直接使用，否则由 source+uid+payload 哈希生成
char_id    : str       # 活跃角色 id；None → 从 active_prompt_assets.json 解析，fail-loud
source     : str       # 来源标识（desktop_wake / qq / scheduler / sensor / ...）
trust      : str       # low_trust（外部/定时/sensor）| high_trust（管理接口直发，目前未使用）
timestamp  : float     # Unix epoch，事件生成时间
```

v0.1 这些字段的实际位置：
- `event_id / dedupe_key / source / char_id`：`PerceiveEvent` dataclass（`core/perceive_event.py`）
- `trust`：隐式由 `source` 决定，未显式字段化；所有外部来源均视为 low_trust
- `timestamp`：`PerceiveEvent` 内部使用 `time.time()`，trigger audit log 写入 ISO 时间字符串

---

## 三、当前实现边界（v0.1）

### 3.1 perceive_event 是 reality-side low-trust stimulus gate，不是完整 event bus

`core/perceive_event.py` 只做三件事：
1. **幂等去重**：90 秒 TTL 进程内字典，相同 dedupe_key 在窗口内只通过一次
2. **Dream Guard**：`DREAM_ACTIVE / DREAM_CLOSING` 时拒绝 reality 事件（`BLOCKED_DREAM`）
3. **返回 PerceiveStatus**：调用方凭此决定是否继续进入 pipeline

它**不是**事件路由器，不做 kind dispatch，不维护 session 状态，不写任何存储。

### 3.2 "trigger" vs "stimulus" 命名

| 层面 | 名称 |
|---|---|
| 概念文档（本文） | `stimulus` |
| 代码 / 文件名 / 日志 | `trigger`（v0.1 保持不变） |

代码层 `trigger` 对应概念层 `stimulus`：系统主动发起的、非用户直接输入的单次事件。v0.2 重构时再对齐命名。

### 3.3 关键约束（v0.1 不变量）

| 约束 | 说明 |
|---|---|
| **tool result never re-enters as stimulus** | 工具执行结果通过 `tool_result` prompt 层注入当前轮，不重新经过 perceive_event gate，不产生新的 kind=stimulus 事件 |
| **stimulus cannot implicitly upgrade to tool** | stimulus/trigger 事件触发 LLM 生成，但生成结果中的 desktop intent 走 intent parser，不作为 kind=tool 事件回注；tool 调用是显式的，不由 stimulus 隐式升级 |
| **dream does not go through reality gate** | `POST /dream/chat` 直接进入 dream pipeline，完全绕过 `receive_perceive_event()`；Dream Guard 反向保护现实侧，不是梦境侧的入口守卫 |
| **LLM reply outlet: kind ∈ {message, stimulus}** | 助手回复通过 `record_assistant_turn / turn_sink` 广播，归属于触发本轮的 kind；系统不从 LLM 回复中派生新的 kind=tool 或 kind=activity 事件 |

### 3.4 Trigger Audit Log（v0.1 可观测性）

每个经过 perceive_event 的 stimulus 写一条 audit 记录，含：
- `event_id`、`dedupe_key`、`gate_result`（`ACCEPTED / DUPLICATE / BLOCKED_DREAM / IGNORED / ERROR`）
- `source`、`uid`、`char_id`
- `timestamp`

**Trigger 不写 short_term**：stimulus 事件触发的助手回复通过正常 `record_assistant_turn` 写 short_term（`bypass_gate=True`），但 stimulus 事件本身不写任何 short_term 记录。

---

## 四、事件流图（v0.1 简化）

```
用户输入 (message)
  └─ perceive_event [reality gate: dedup + dream guard]
        └─ ACCEPTED → conversation_lock → Pipeline → LLM → record_assistant_turn
              └─ turn_sink → channels.broadcast (reality)

系统触发 (stimulus / trigger)
  └─ scheduler._pipeline_send / sensor / desktop_wake
        └─ perceive_event [reality gate]
              └─ ACCEPTED → conversation_lock → Pipeline → LLM → record_assistant_turn
                    └─ turn_sink → channels.broadcast (reality)

工具结果 (tool result)
  └─ 注入 prompt 层 10 (tool_result)，参与当前轮 LLM 生成
        NOT re-injected as stimulus

梦境输入 (dream message)
  └─ POST /dream/chat → dream pipeline（完全绕过 reality gate）
        └─ dream log（不写现实记忆）
```

---

## 五、v0.2+ 预留（当前不实现）

以下内容**不在 v0.1 范围内**，在此列出以防止提前实现：

- `EventEnvelope` dataclass（统一封包，目前各入口各自 PerceiveEvent / TriggerProposal）
- dispatch router（按 kind 路由到不同处理器）
- `kind=tool` 独立 event 类型（工具调用生命周期管理）
- `kind=activity` + `ActivitySession`（活动会话状态机）
- `channel_message` 结构变更
- plugin 系统
- `trust` 字段显式化 + trust-based gating（高信任来源跳过 dedup 等）
- 跨 realm event（梦境→现实的结构化事件，目前只有 afterglow 回流）

---

## 六、与其他文档的关系

| 文档 | 关系 |
|---|---|
| `docs/channels.md` | 通道层（broadcast / fanout），位于 event 处理的下游 |
| `docs/dream.md` | Dream realm 的完整规格（pipeline / prompt / 隔离合同） |
| `docs/trigger-decision-layer.md` | Stimulus 决策层设计（gating / propose / state machine） |
| `docs/scheduler.md` | 调度器触发器（stimulus 的主要生产者之一） |
| `docs/tools.md` | Tool 系统（kind=tool 的 v0.2+ 预留形态） |

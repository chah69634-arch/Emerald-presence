# Activity Session — 设计说明

## 定位

`ActivitySession` 是 **reality-side session**，不是 trigger，不是 tool result，不进入普通短期记忆。

它用于承载用户与角色之间的结构化共同活动（reading / gomoku / chess），生命周期由用户显式 API 调用控制：

```
POST /activity/start   → create_session()
GET  /activity/state   → find_active_session()
POST /activity/update  → update_state()
POST /activity/close   → close_session()
```

## 与其他系统的边界

| 系统 | 关系 |
|---|---|
| short_term / history | **不写入**。活动步骤不进对话历史 |
| event_log | **不写全文**。活动状态变更不记录事件日志 |
| user_hidden_state | **不写入**。活动不影响隐性状态 |
| perceive_event | **不接入**。不走 gate/conversation_lock 流程 |
| Dream / Scenario | **完全隔离**。Dream 期间不启动/不读取 ActivitySession |
| scheduler | **不接入**。没有定时触发 |
| trigger / stimulus | **不是** trigger。必须由用户按钮/命令显式启动 |

## 数据结构

```python
@dataclass
class ActivitySession:
    session_id: str        # uuid4().hex，全局唯一
    uid: str               # 用户 id
    char_id: str           # 角色 id
    activity_type: str     # reading | gomoku | chess
    status: str            # active | closed
    state: dict            # activity-specific 数据（P0 为空壳，由各 activity 自定义）
    created_at: str        # ISO 8601 UTC
    updated_at: str        # ISO 8601 UTC
```

## 存储路径

```
data/runtime/activity/{char_id}/{uid}/{activity_type}/{session_id}/session.json
```

- `char_id` / `uid` 双重隔离：不同角色不共享路径，不同用户不共享路径。
- `session_id` 经 `safe_user_id()` 验证，`DataPaths._p()` 沙盒检查，不允许路径逃逸。
- `activity_type` 必须在 `ALLOWED_ACTIVITY_TYPES = {"reading", "gomoku", "chess"}` 中，否则 `ValueError`。

## 单 active session 策略

同一 `(uid, char_id, activity_type)` 最多允许一个 active session。调用 `create_session()` 时若已有 active session，先将其 `close` 再创建新 session（不静默覆盖，旧 session 仍可按 session_id 查询，status = "closed"）。

## LLM 与 Activity 的关系

LLM **可以讨论**当前进行的 activity（例如棋局、阅读进度），但：

- 状态变更（落子、翻页、胜负）必须走 activity API，不由 LLM 输出决定。
- 规则合法性、胜负判断由代码执行，不由 LLM 推断。
- activity state 不通过 short_term 进入 prompt 主链；如需注入，须走专用 prompt 层（P0 未实现）。

## 模块结构

```
core/activity/
  types.py          — ActivityType / ActivityStatus / ALLOWED_ACTIVITY_TYPES
  session.py        — ActivitySession dataclass + new_session_id() + now_iso()
  store.py          — create / load / find_active / update_state / close
  activity_store.py — reading 专用存储（旧，维持兼容）
  reading_session.py — ReadingSession 模型（旧，维持兼容）
  pdf_reader.py     — PDF 文本提取（reading 专用）
```

## P0 范围

P0 只实现 session 外壳（`types.py` / `session.py` / `store.py`），不实现具体游戏规则。gomoku / chess 的 `state` 字段在 P0 为用户自由传入的 dict，不做内容校验。

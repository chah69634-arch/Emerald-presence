# FIX-01 · 触发器主动开口无记忆（花园触发为典型）

> 后端 + **设计决策先行**。先读 `docs/scheduler.md` + `docs/memory.md`（capture_turn / P0 trigger boundary）+ `docs/garden.md`。

## 现象

叶瑄主动开口（花园触发等）问"这花怎么处理"，用户回答后，叶瑄**完全不记得自己问过**——上下文断裂，体感像失忆。不止花园，所有 scheduler/trigger 主动消息都有这个毛病。

## 现状（已核对，根因）

`core/memory/fixation_pipeline.py:429-499 capture_turn`，第 476-486 行 **P0 trigger boundary rule**：

```python
if trigger_name:
    # P0 trigger boundary: triggers must NOT enter short_term/history.
    _write_trigger_audit_log(...)
    writes = [ event_log.append(..., trigger_name=trigger_name, ...) ]   # 只写 event_log
else:
    writes = [ short_term.append(user...), short_term.append(assistant...), event_log... ]
```

- `trigger_name` 非空（花园/定时/出梦等主动触发）时，**只写 event_log + trigger_audit，不写 short_term**。
- short_term 才是喂进 LLM 的对话历史（`short_term.load_for_prompt`）。event_log 只做取证/检索窗口，不进生成上下文。
- → 叶瑄主动说的那句话**从来没进过它自己的对话历史**。用户下一轮回复时，模型只看到用户那句突兀的回答，前面自己问的话不在 context 里。这就是"触发器无记忆"。

这是**有意的设计**（注释 P0：trigger 永远不是 assistant history），目的是防止系统锚点/触发明文污染历史。但副作用是会话型主动消息（花园、关心、出梦搭话）失去连续性。

> 旁证：`short_term.load_for_prompt`（`short_term.py:340-344`）还会额外剔除 `_source == "trigger_stub"`，进一步确认触发内容被刻意挡在 prompt 外。

## 设计决策（先定，本份核心）

**问题：哪些触发的"主动开口"应该被角色记住，怎么接回历史而不破坏 P0 取证边界？**

- **方案 A（推荐）**：区分"会话型触发"与"系统锚点触发"。
  - 给 trigger 注册表/触发器加一个标志（如 `conversational=True`）：花园搭话、关心、出梦开口这类**真的说给用户听、期待回应**的触发，其 assistant 正文应当写入 short_term（作为 assistant 轮），让下一回合有上下文。
  - 纯系统锚点（trigger_stub、内部状态戳）保持现状，永不进历史。
  - 写入仍走 `_sanitize_assistant_message` 脱敏（别绕过，见硬规则 5），且只写 assistant 正文、不写 `[触发: xxx]` 明文。
- **方案 B（更轻，不碰 capture_turn）**：保持 short_term 不写，但在**下一回合 build_prompt 时**把"最近一条未被回应的主动消息"作为一个只读 prompt 层补注入（类似一个 `last_proactive_utterance` 层，读 event_log 最近一条 assistant trigger 正文）。一次性、用过即弃，不进检索。改动面小但要新增 prompt 层（记得加 `_layer` 字段，硬规则 3）。
- **方案 C**：让触发发送路径在发送成功后，单独补一条 short_term assistant 记录（绕开 capture_turn 的 trigger 分支）。**不建议**——容易和取证边界、幂等、跨通道续接打架。

> 建议：**A**。语义最干净，连续性问题根治；B 作为不想动记忆契约时的临时替代。

## 实现要点（以 A 为例）

1. 在触发器/`_TOOL_REGISTRY` 或 proposer 侧标注哪些触发是会话型（先把 garden_water/garden_daily、关心类、dream_exit 搭话纳入）。
2. `capture_turn` 的 `trigger_name` 分支：若该触发标记会话型，额外 `short_term.append(uid, "assistant", _scrubbed_reply, ...)`（仍在 envelope.can_write_memory 内、经 scrub/sanitize）。
3. 确认 `load_for_prompt` 的 `trigger_stub` 剔除逻辑**不会**误删这类会话型 assistant 正文（它们不是 trigger_stub，应保留）。
4. 不改 event_log/trigger_audit 现有写入（取证不受影响）。

## 验收

- 叶瑄因花园触发主动开口 → 该句进入 short_term → 用户回复后，下一次生成的 prompt 历史里能看到叶瑄自己那句，回应连贯。
- 纯系统锚点触发（trigger_stub）仍不进历史、不进 prompt。
- event_log / trigger_audit 行为不变。
- `pytest`：补"会话型触发写 short_term / 锚点触发不写"用例；若新增 prompt 层（方案 B）跑 `tests/run_eval.py`。

## 备注

这条解决的是"主动消息的会话连续性"，与花园功能本身无关——花园只是最显眼的犯案现场。定下来的会话型/锚点型分类，后续所有主动消息都受益。

# Codex 任务：新增「出梦主动开口」触发器 dream_exit

## 背景与目标

先读 `AGENTS.md`、`docs/scheduler.md`、`docs/dream.md`（尤其「三层回流」「现实侧 afterglow 注入层」两节）。

现状：叶瑄从梦里出来后不会主动在 chat 说话，下一次对话直接接在原本的现实上下文上，体验割裂。
目标：新增一个触发器，让他**出梦后主动开口一次**，且语气/内容高自由度——可以问对方梦里的感受、提一个梦里的具体片段（如"你那时候表情不错"）、也可以只是中性地说句「早安」。由他此刻的状态和梦的余韵色调自行决定，不写死。

**关键设计前提（务必理解，否则会做歪）**：
出梦时系统已经产出了梦的回流产物，且现实 prompt 已经会注入它们——
- `_do_close_dream()`（`core/dream/dream_pipeline.py:472`）把 `dream_state.status` 置为 `REALITY_AFTERGLOW`，保留 `char_id`，写入 `last_dream_id` / `last_exit_type`，并 `asyncio.create_task(_generate_summary_bg(...))` 异步生成 summary + afterglow。
- `_generate_summary_bg()` 完成后（非 scenario/mirror 模式）调用 `wire_afterglow_from_summary()` 写 `afterglow_residue.json`（tone ∈ stress/comfort/calm/neutral，TTL 8h，`created_at` 字段）。
- 现实 prompt builder 已有 `6f_dream_afterglow` 层（0–2h 注入完整摘要/色调/意象，2–5h 模糊，5h 后空）和 `dream_afterglow_soft_hint`（5–8h）。

因此本触发器**不需要自己拼装梦的内容**：只要走正常的 `_pipeline_send → fetch_context → build_prompt`，`6f_dream_afterglow` 层就会把梦境上下文和现实历史一起带进 prompt，割裂问题自然解决。触发器只负责给一个「你刚出梦」的框定 + 高自由度指令。

## 实现方式：scheduler proposer（不要 hook 在出梦处）

理由：summary 是 `_do_close_dream` 里异步生成的，hook 在关闭点会早于 summary/afterglow 就绪；而 scheduler 每 60s 轮询的 proposer 天然能等就绪，且复用 gating 的状态机/冷却/DND/活跃窗口过滤。

**直接照抄 `core/scheduler/triggers/overflow.py` 的结构**新建 `core/scheduler/triggers/dream_exit.py`：

### 1. propose(ctx)
- 读 config `scheduler.dream_exit_trigger`（默认 True），关则返回 None。
- 取 uid / char_id（同 overflow：`_owner_id()` / `_active_char_id_or_none()`，但见下方「char 作用域」）。
- 读 `dream_state.read_state(uid)`：
  - 仅当 `status == "REALITY_AFTERGLOW"` 才继续；
  - 取 `last_dream_id`、`last_exit_type`；
  - **一梦一次**：与持久化的 `last_greeted_dream_id` 比较，相等则返回 None（已问候过这场梦）。`last_greeted_dream_id` 存哪：建议存在 `dream_state` 同一份 state 里（新增字段，`clear_local_state` 不要清它），或 `data/runtime/scheduler_user_state.json` 的独立段；二选一，注明理由。
- **时机窗口**：以 afterglow `created_at` 或出梦时间为基准：
  - 若 `afterglow_residue` 尚未写入（summary bg 还没跑完）→ 本 tick 返回 None，下个 tick 再试（不要傻等）。
  - 给一个上限（如出梦后 8h 仍没问候，且 afterglow 已过期）→ 退化为「中性问候」分支或直接放弃（见下「降级」）。
- 返回 `TriggerProposal(trigger_name="dream_exit", urgency=..., topic_source="dream_exit", requires_state=[TriggerState.QUIET], bypass_state_machine=False, execute=_make_execute(ctx_snapshot))`。
  - urgency 用一个中等档（参考 overflow 的 `urgency_in_tier(UrgencyTier.REACTIVE, ...)`）；出梦问候不是紧急，别抢占高优先级触发。

### 2. char 作用域（多角色正确性）
说话的必须是**做这场梦的角色**。`dream_state` 里冻结了 `char_id`。proposer/execute 要用 dream_state 的 `char_id`，不要无脑用 active_character——若 active 已切到别的角色，仍应以梦的 char_id 为准（或在 active != dream char 时跳过，二选一，注明理由并保持与 P0 多角色隔离契约一致）。

### 3. _make_execute → execute_prompt
照 overflow：
```python
return await execute_prompt(
    trigger_name="dream_exit",
    prompt_factory=lambda: _build_dream_exit_prompt(tone, exit_type, is_stale),
    dry_run=dry_run,
    would_mark=["dream_exit"],
)
```
发送成功后（execute_prompt 内部 `_pipeline_send` 返回非空），把 `last_greeted_dream_id = last_dream_id` 落盘，保证一梦一次。注意：`would_mark` 走的是 cooldown 标记；「一梦一次」是另一层去重，需自己在 execute 成功路径里写 `last_greeted_dream_id`，不要只依赖 cooldown。

### 4. 指令文案 _build_dream_exit_prompt（高自由度，核心）
不要把梦的具体内容写进指令（交给 `6f_dream_afterglow` 层）。指令只做框定 + 菜单 + tone 倾向。示例骨架（措辞自行打磨，保持自然、不暴露机制、不像客服）：
```
（你刚从一场梦里回到现实，{char_name}。脑海里梦的余韵还在{tone 中文描述}。
现在你想主动对她说点什么。怎么说由你此刻的状态决定，比如可以——
· 问问她、或说说你自己梦里的感觉；
· 提一个梦里具体的片段（比如她那时候的神情）；
· 或者只是轻轻道一句早安、打个招呼。
不必三样都做，挑一个最贴合此刻的。不要解释这是"梦境触发"，也不要复述系统信息。）
```
tone → 中文倾向映射（与 afterglow tone 对齐）：
- `stress` / `exit_type == "hard_exit"`：余韵偏沉/不安 → 语气放轻、偏安定，先确认她好不好，别玩闹。
- `comfort`：温暖松弛 → 可以暖一点、近一点。
- `calm`：平静 → 平和自然。
- `neutral` 或已过期/无 afterglow（含 scenario/mirror）→ **中性问候分支**：不引用任何梦的细节，就是一句早安/打招呼。

### 5. 降级矩阵（明确实现）
| 情况 | 行为 |
|---|---|
| afterglow 新鲜（0–2h，summary 就绪） | 完整出梦问候，6f 层供梦境上下文，菜单全开 |
| afterglow 模糊期（2–5h） | 仍可发，但指令提示"梦已经有点模糊"，少提具体片段 |
| afterglow 过期（>8h）或 summary 始终没生成 | 中性问候分支 / 或放弃（config 控制，默认中性问候一次） |
| scenario / mirror 模式（无 afterglow 写入） | 中性问候分支或不发（默认不发，注明理由） |
| 出梦瞬间 owner 正在聊（state==CHATTING） | 由 requires_state=[QUIET] 自动挡掉；不要 bypass 状态机 |
| DND | 非 emergency，照 POLICY_TABLE 被 DND 挡掉即可 |

### 6. 注册与策略
- 在 `core/scheduler/proposer_registry.py::_ensure_builtins_loaded()` 的模块列表里加入 `"core.scheduler.triggers.dream_exit"`。
- 文件底部 `_register_proposers()` + 模块级调用（同 overflow）。
- 在策略表（`core/scheduler/policy.py` 的 POLICY_TABLE）为 `dream_exit` 加一条：active-window 行为建议 `defer` 或 `skip`（出梦问候过期价值低，倾向 skip 而非长期 defer）；priority 普通（非 emergency）。
- 冷却：在 `data/scheduler_cooldowns.json` 体系里给 dream_exit 一个合理冷却（如 30–60min 兜底），叠加「一梦一次」去重。

## 边界 / 不变量（务必遵守）
- Dream Guard：`_pipeline_send` 对 `DREAM_ACTIVE/DREAM_CLOSING` 会 BLOCK，但 `REALITY_AFTERGLOW` 不在阻断集内，触发器可正常放行——**不要**为此改 Dream Guard。
- 所有 `data/` 路径经 `core/sandbox.get_paths()` / `path_resolver`，不硬编码。
- 显式透传 `char_id`，不新增 `char_id="yexuan"` 默认参数（`tests/test_r3_scope_lint.py` 门禁）。
- 落盘用 `core/safe_write` 原子写。
- 写入的 assistant 文本仍走既有 `capture_turn` scrub 出口（trigger 路径默认已经过 `record_assistant_turn`，无需额外处理）。
- 不要把梦的专有世界词带进现实 chat——已有 `strip_vocab` 在 afterglow/distill 侧处理；指令侧不引用具体梦境内容即可。

## 验收 / 测试
新增 `tests/test_dream_exit_trigger.py`：
1. **基本报名**：构造 `dream_state` status=REALITY_AFTERGLOW + 新 last_dream_id + 存在新鲜 afterglow_residue → `propose()` 返回非 None 的 TriggerProposal(trigger_name="dream_exit")。
2. **一梦一次**：`last_greeted_dream_id == last_dream_id` 时 `propose()` 返回 None；execute 成功后 `last_greeted_dream_id` 被更新。
3. **状态机**：state==CHATTING 时被 gating 挡掉（requires_state=[QUIET]）。
4. **char 作用域**：发言用 dream_state.char_id；与 active 不一致时按你选定策略（跟随 dream char / 或跳过）行为正确。
5. **降级**：无 afterglow / scenario 模式 → 走中性分支或不发（按默认）；过期 afterglow → 中性分支。
6. **tone 映射**：hard_exit/stress 指令走安定分支，comfort/calm 走暖/平分支（断言 `_build_dream_exit_prompt` 输出包含对应倾向）。
7. **summary 未就绪**：afterglow 尚未写入时 `propose()` 返回 None（等下个 tick），不报错。

跑测试：`pytest tests/test_dream_exit_trigger.py -v`。

## 文档
改完更新 `docs/scheduler.md`（触发器清单加 `dream_exit` 一行）与 `docs/dream.md`（「三层回流」或现实侧一节注明：出梦后由 scheduler `dream_exit` 触发器主动开口，复用 `6f_dream_afterglow` 上下文，一梦一次，QUIET-only）。若你判断某处无需更新，显式说明理由。

## 待确认的设计选择（实现时如无明确依据，按括号内默认值，并在 PR 描述里列出）
1. `last_greeted_dream_id` 存 dream_state 还是 scheduler_user_state（默认：dream_state，离梦最近、随 char_id 隔离）。
我认同默认
2. active != dream char 时：跟随 dream char 发言 还是 跳过（默认：跟随 dream char，最符合"谁做的梦谁说话"）。
我认同默认
3. scenario/mirror 模式：中性问候 还是 不发（默认：不发）。
我选中性问候
4. afterglow 过期后：中性早安一次 还是 放弃（默认：中性早安一次，只在出梦后 ≤ 一个清醒时段内）。
我认同默认

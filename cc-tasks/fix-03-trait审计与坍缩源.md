# FIX-03 · trait 系统审计 + 残留坍缩源排查与治理

> 后端**审计为主**，先查清楚再动手。先读 `docs/prompt-layers.md` + `AGENTS.md` 关键文件速查（trait/author_note 段）。
> 产出：一份"trait 效果确认 + 坍缩源清单 + 治理建议"的结论，再按结论改。

## 系统现状（已核对）

防坍缩链有两个部件：

1. **trait_tracker**（`core/memory/trait_tracker.py`）：统计角色特质关键词在近期对话的命中，维护 5 窗口滑动，输出 `underrepresented`（总命中 ≤ `UNDERREPRESENTED_THRESHOLD=2` 的特质）。
   - 触发：`core/pipeline.py:603` 每个有效回合入队 `trait_tracker_update`，handler 在 `pipeline.py:991-1021`。
   - 统计输入：`pipeline.py:1016` `short_term.load(uid)[-40:]` 的 **content（user+assistant 混在一起）**；匹配方式 `trait_tracker.py:33` 是 `keyword in line` 纯子串，**每行每特质最多记 1**（不是出现次数）。
   - 特质定义：`get_paths().yexuan_traits(char_id=)`（仓内 `data/yexuan_traits.yaml` / `content/characters/yexuan/traits.example.yaml`）。
   - 状态落盘：`data/runtime/characters/{char}/inner/trait_state.json`。

2. **author_note_rotator**（`core/author_note_rotator.py`）：每 **30 分钟**（`_SWITCH_INTERVAL_MINUTES=30`）从 `characters/{char}_author_notes.json` 加权随机选 1 条注入 prompt 层 11。
   - `underrepresented` 的唯一作用：`author_note_rotator.py:86-91`，命中 underrepresented 特质的 note 权重 **×2**。
   - 选择还受"1 天内不重复 / 15 天强制重选"约束。

## 审计清单（cc 先确认"效果"，用现有产物，别凭空判断）

1. 读 `data/runtime/characters/yexuan/inner/trait_state.json`：`windows` 是否在更新、`underrepresented` 是否长期为空或长期全量（两种都说明信号失效）。
2. 读 `data/yexuan_traits.yaml` 的 keywords：是否过于宽泛（命中率虚高→永不 underrepresented）或过窄（永远命中不了→永远 underrepresented，权重恒 ×2 等于没区分）。
3. grep `underrepresented` / `[trait_tracker]` / `[author_note_rotator]` 日志，确认链路真的在跑、note 真的在 30 分钟切换。
4. 确认 author_note 注入的 prompt 层（层 11）当前实际文本，判断它对输出风格的实际牵引力。

## 已定位的残留坍缩源（带证据，逐条给治理）

- **S1 · author_note 30 分钟窗口** → 同一会话密集对话时，**每一回合注入的 note 完全相同**，风格牵引静止。
  - 证据：`author_note_rotator.py:47-55 _should_switch`，未到 30 分钟直接返回旧 note。
  - 治理：会话密集时改为按"回合数"或"回合数+时间"双触发切换；或每回合在 note 内部做轻微变体/多 note 轮询。先确认 S1 是否是主因（看日志里同一 note id 连续命中多少回合）。

- **S2 · 短回复不脱敏，自模仿反馈** → `_sanitize_assistant_message`（`short_term.py:118-158`）**仅在 >80 字时**清理；≤80 字原样进历史。叶瑄的短口头禅/句式因此在 history 里被反复回灌，DeepSeek 自模仿 → 句式坍缩。
  - 证据：`short_term.py:128 if not content or len(content) <= 80: return content`。
  - 治理：对短回复也做"风格指纹去重"——不是删内容，而是检测 history 内近 N 条 assistant 是否高度同质（句首/句式重复），命中则在 prompt 侧加一条"避免重复前文句式"的软提示，或在选择 history 子集时降权同质条目。注意：**改截断/写入逻辑前必看 `_sanitize_assistant_message`（硬规则 5），别绕过脱敏。**

- **S3 · trait 信号粗糙** → 统计混入 user 行（用户说了关键词也算角色"表达过该特质"，信号被污染）；`keyword in line` 每行计 1，密集表达和偶尔提及无法区分；阈值固定 2。
  - 证据：`pipeline.py:1016` 用全量 history content；`trait_tracker.py:28-36`。
  - 治理：统计只数 **assistant 行**；或按出现次数计权；阈值随特质数量自适应。

- **S4 · underrepresented 杠杆太弱** → 即使识别出"某特质很久没表达"，也只是把对应 note 权重 ×2，并不强制角色去表达该特质。
  - 治理：把 underrepresented 特质做成一条**显式 prompt 提示**（"最近你很少展现 X 的一面，这轮可以自然带出"），比单纯调 note 权重直接。需新增/改 prompt 层 → 加 `_layer` 字段（硬规则 3）、跑 `tests/run_eval.py`（硬规则 4）。

## 验收

- 给出审计结论：trait 链是否在跑、underrepresented 是否有意义、author_note 是否真在轮换。
- 至少落地 S1 + S2 的治理（这两条对体感坍缩影响最大），S3/S4 视审计结论排期。
- 改了 trait 统计口径 → `pytest tests/test_r8b_trait_tracker_queue.py` 等相关用例；改了 tag/prompt 层 → `tests/run_eval.py`。
- 改写入/截断逻辑前后对照 `_sanitize_assistant_message`，确认未绕过脱敏。

## 备注

与 `fix-04`（群聊坍缩）共享 S1/S2 根因——author_note 与短回复自模仿在群聊里被多角色放大。两份可参照同一套治理，但群聊另有 per-character 注入问题，见 fix-04。

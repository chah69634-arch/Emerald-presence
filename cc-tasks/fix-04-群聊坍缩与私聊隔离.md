# FIX-04 · 群聊多人输出雷同 + 私聊不记群聊内容

> 后端，先读 `docs/stage.md` + `docs/memory.md`（projection / fixation）。
> 两个独立子问题，分别排查：A=群聊坍缩，B=私聊不记群聊。

---

## 子问题 A：多角色经常输出同几句话（群聊坍缩）

### 现状（已核对）

每个角色由 `core/stage/views.py StageCharacterView.generate` 独立生成：
- 确实**各自加载自己的角色卡 + LoreEngine + 自己的 reality scope**（`views.py:18-27, 39-44`），不是共用一张卡——所以坍缩**不是角色卡串台**（串台是 `fix-07` 梦境的问题，别混）。
- 但所有角色共享：**同一份 transcript** + **同一段写死的通用指令** `stage_instruction`（`views.py:52-60`）+ 同一个 DeepSeek 模型。

### 坍缩源（带证据）

- **A1 · 通用指令同质**：`views.py:52-60` 给每个角色注入的群聊指令完全相同、且很泛（"你可以回应其他角色…不要重复…"）。同样的输入框架 + 同一模型，倾向收敛到相似措辞（尤其附和/道歉/赞同类）。
- **A2 · 复用单聊的 author_note / 短回复自模仿**：见 `fix-03` 的 S1（30 分钟同一 note）、S2（≤80 字短回复不脱敏自模仿）。群聊里多角色密集出话，把这两个坍缩源放大。
- **A3 · 仲裁可能逼多个角色回应同一句**：`min_responders` 让多个未发言角色对**同一条 owner 消息**各回一句（`docs/stage.md` 二.3），话题锚点相同 → 回应趋同。查 `core/stage/arbiter.py` + `runner.py` Phase A 的实际 responder 选择与去重。

### 治理建议

1. **A1**：`stage_instruction` 改为**按角色差异化**——注入该角色的 author_note/特质要点，并加"以你自己的方式回应，避免与其他角色刚说的话语气雷同"。让每个角色的群聊指令带自己的风格锚。
2. **A2**：复用 `fix-03` S1/S2 的治理（note 切换更勤 + 短回复同质降权/软提示），群聊场景一并生效。
3. **A3**：审 `arbiter.py`/`runner.py`，确认 Phase B 重算时是否把"已说内容"喂回仲裁与生成做去重；必要时降低 `min_responders` 默认值或让后说的角色显式看到前者已说并被要求"补充而非复述"。

### 验收

- 同一轮多角色发言措辞明显分化，不再是同几句。
- 每个角色注入的群聊 prompt 含自己的风格锚（debug_token_log 或 prompt dump 可证）。

---

## 子问题 B：私聊完全不记得群聊内容

### 现状（已核对，关键）

投影链**看起来是接上的**：
- `core/stage/runtime.py:92` 每轮结束 `await enqueue_reality_projection(group_id)`。
- `core/stage/projection.py:37-50`：对 roster 里**每个 char_id**，把群聊 transcript 渲染后入队 `summarize_to_midterm`，**scope = `MemoryScope.reality_scope(stage.owner_uid, char_id)`**，`force_reflect=True`、`source="group:{id}"`、`memory_strength=settings.group_memory_strength`。
- 这个 scope **正是私聊读取的同一个角色记忆桶**。理论上群聊摘要应进入叶瑄的 mid_term → episodic → identity，私聊能读到。

所以"一点都不记得"说明链路某处**没真的落地**。**cc 需实测定位**，候选根因（按可能性排序）：

1. **投影内容是指令、不是事实**：`projection.py:42` 喂给 `summarize_to_midterm` 的 `reply` 是 `"请从角色 X 的视角保留这段群聊中值得记住的事实。"`——`reply` 是**指令文本而非角色真实发言**。`summarize_turn(user_msg=群聊记录, reply=指令)` 很可能产出空泛/无效摘要，被 `reflect_to_episodic` 的 neutral-skip（`fixation_pipeline.py:684` strength<0.4 且 neutral 直接丢弃）过滤掉 → 永不进 episodic。**重点查这条**。
2. **runtime 路径是否真被调用**：确认生产里桌宠群聊走的就是 `run_reality_stage_turn()`（`runtime.py`）。若群聊用的是别的入口（或 QQ 群，见 `fix-09`），projection 根本没跑。
3. **owner_uid 一致性**：群 `stage.owner_uid` 与私聊 uid 是否同一个；不一致则写进了别的桶。
4. **mid_term 12h 过期**：若摘要进了 mid_term 但没及时晋升 episodic（force_reflect 应该规避，但需确认 eager reflect 真的跑成功、没在 neutral-skip 被丢）。

### 治理建议

- 先按上面 1→4 实测定位（看 fixation_log、mid_term.json、episodic.json、`[fixation.*]` 日志）。
- 若确认是根因 1：把投影改成**喂群聊里值得记的真实内容**而非指令——例如直接用渲染后的 transcript 事实做摘要，或给 `summarize_turn` 一个专门的"群聊事实提炼" prompt，并确保产出的 strength/emotion 不被 neutral-skip 一刀切掉（group 来源可豁免或给底分）。
- 与设计意图对齐：`docs/stage.md` 五明确"原始 transcript 不进 short_term，只有摘要投影入链"——**保持这个边界**，只修"摘要没真的入链"。

### 验收

- 一段群聊（叶瑄在场，聊了具体的事）结束后，单独私聊叶瑄能提及/记得那件事。
- fixation_log 能看到 `source=group:*` 的 mid_term→episodic 晋升，没有被 neutral-skip 全部丢弃。
- `pytest tests/test_stage_p3.py` 不回归。

## 备注

- 群聊坍缩（A）与私聊不记（B）互相独立，可分别落地。
- QQ 群聊已失效是另一条（用户问题 9，第二批），本份只覆盖桌宠 Stage 群 + 私聊记忆。用户倾向"QQ 群聊别混主记忆"，故 B 的修复**仅针对桌宠 Stage**，不要顺手把 QQ 群也接进主记忆。

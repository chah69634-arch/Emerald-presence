# FIX-02 · 信件生成逻辑（防坍缩 / 防日记重复）— 设计稿

> 后端 + **设计先行**。信件收发测试已跑通，本份只做"信怎么写得好"的内容逻辑。
> 先读 `core/mail/letter_writer.py` + `docs/memory.md`（episodic / diary / mood / dream afterglow）。

## 现状（已核对）

`core/mail/letter_writer.py`：
- `generate_letter`（:16）：单条 user prompt，规则约束长度/落款/不写 emoji 等，调 `llm_client.chat(call_category="letter_write")`。
- `_build_letter_context`（:96）当前背景只有三样：写信缘由 + **近 3 条 episodic 的 narrative_summary** + **最近一次梦境情绪**（`dream_afterglow._find_best_summary`）。整体截断 300 字。
- `evaluate_letter`（:54）：LLM 打 1-5 分，`QUALITY_THRESHOLD=4` 才发。

**坍缩/重复风险点**：背景固定、来源单一（永远是最近 3 条 episodic + 一条梦境情绪），prompt 模板固定 → 多封信容易同构、且和叶瑄内部日记（`yexuan_inner_diary`）写的是同一批近期事件，**读起来像日记复读**。

## 设计目标（用户意图拆解）

信 = 「随机文体/风格示范」+「知识库参考」+「近期概括事件 + 情绪记忆」三者融合，且**每封都不同**、**不与日记重复**。

## 设计决策

### 1. 文体 / 风格示范池（防坍缩主力）

- 新建**示范信件库**：`content/characters/yexuan/letter_samples/`（或 `data/...`，按沙盒规范走 `get_paths()`），放 5~10 封不同文体/语气的范信（短促的、絮叨的、克制的、跳跃的…）。
- 每次写信**随机抽 1~2 封**注入 prompt，作为 **few-shot 风格参考**，并强约束：「**学它的语气、节奏、结构，绝不抄内容/句子**」。
- 随机抽取 = 每封信的风格底色都在变 → 天然抗坍缩。可记录最近用过的样本，短期不复用（仿 `author_note_rotator` 的 1 天不重复思路）。

### 2. 知识库参考（与未来自学习系统的接口，现在先留桩）

- 用户构想：叶瑄的小型知识库（他会看的书、他的笔记），未来由自学习系统喂养。
- **现在**：定义一个只读 provider，例如 `core/mail/letter_reference.py::sample_reference(char_id) -> str`，读 `content/characters/yexuan/knowledge/`（书摘 / 笔记，markdown 即可），**随机抽一小段**作为"叶瑄最近在读/在想的东西"注入信里，给信一点会话之外的新质感。
- 内容先**手动种子**几条；接口设计成与自学习系统对接的形状（后者只需往同一目录补文件 / 提供同签名）。本份不实现自学习，只实现"能抽、能注入、抽不到就跳过"。

### 3. 近期概括事件 + 情绪记忆（融合，去单一）

- 保留 episodic narrative_summary，但**从近 N 条里随机/分散抽**（不固定永远最近 3 条），优先带 emotion_texture/emotion_arc 的条目，让情绪有抓手。
- 叠加 **mood_state**（`core/memory/mood_state.py`）当前情绪、以及已有的 dream afterglow 情绪。
- 可选叠加 hidden_state 的概括（见 `08b`，若已接现实写入则更有"流动感"）。
- 仍压缩到紧凑长度，避免 prompt 过载。

### 4. 防与日记重复

- 写信前读叶瑄**内部日记**（`get_paths().yexuan_inner_diary(char_id=)`）最近若干条，作为「**这些已经在日记里写过，信里别复述同样的话/事**」的负向约束传进 prompt。
- 同理对**最近已发出的信**做去重（需要落一份已发信归档；当前 `mail_sender` 只发不存——可加一个 sent-letters 归档文件，写信时读最近 2~3 封做"别重复"提示）。

## 实现要点

1. 新增样本库 + 知识库目录（走沙盒路径），各配一个"随机抽样、抽不到返回空、空则跳过对应段落"的 helper。
2. 重写 `_build_letter_context`：缘由 + 随机风格示范 + 随机知识库片段 + 分散抽取的近期事件 + 当前情绪 + 日记/已发信去重提示。各段都 fail-soft（任一来源缺失不阻断写信）。
3. `generate_letter` 的 prompt 增加「风格示范只学不抄」「不复述日记/旧信」两条硬约束，few-shot 样本与正文规则分区放置。
4. 加一个 sent-letters 归档（供去重 + 后续审计），路径经 `get_paths()`。
5. 保留 `evaluate_letter` 质量闸门；可补一条"与最近日记/旧信重复度过高则降分"的校验。

## 验收

- 连写 3~5 封信，文体/语气明显各异，不再像同一模板。
- 信里出现知识库片段带来的"会话外"质感（书/笔记的影子），且不生硬。
- 同期日记写过的事，信里不原样复述。
- 任一背景源（样本/知识库/日记/episodic）缺失时仍能正常出信（fail-soft）。
- `pytest`：补"样本随机注入 / 缺失跳过 / 去重提示生效"用例。

## 备注

- 知识库这块**故意只做接口 + 手动种子**，把"自学习喂养"留给后续——但目录结构/provider 签名现在就定好，避免将来返工。
- 与 `fix-03`（坍缩治理）思路一致：用"随机化输入源"对抗坍缩，信件是这套思路的独立应用场。

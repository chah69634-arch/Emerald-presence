# Spec #10 — 多角色群聊（Multi-Character Group Chat / Stage）

> 状态：设计中（地基审计 + 方案）
> 难度：高（唯一会击穿地基的项目）
> 最近核对：2026-06-13
> 改动范围：`core/pipeline.py`、`core/memory/short_term.py`、`channels/`（三端协议）、`core/scheduler/loop.py`、`core/character_name_provider.py`，新增 `core/stage/`（Stage/Conversation 实体）

---


## 0. 一句话

存储层（S5/S6 的 `{char_id}/{uid}` 布局、per-char mood/garden/diary/记忆五层）已经为多角色准备好了；**运行时仍是二人世界假设**。群聊不是"加功能"，是把"单活跃角色热切换"换成"N 个角色同时在场"。在没准备好之前贸然接入，会在 short_term 配对、通道协议、调度冷却三处同时炸。

---

## 1. 地基审计（对照上一轮讨论的现状核对）

> 结论：上一轮的架构判断**大体仍然成立**，只有一处已被修掉（import 期角色名冻结）。

| 子项 | 上一轮判断 | 现状（2026-06） | 是否过时 |
|---|---|---|---|
| Pipeline 单活跃角色 | 单例持 `self.character`，靠 `active_prompt_assets.json` 热切换 | `pipeline.py:84 self.character`、`:92 _refresh_character_if_needed`、`:90/:345 _last_channel` 单实例变量 —— 不变 | **仍成立** |
| short_term 二元 schema | `role ∈ {user, assistant}`，turn-group 配对建立在一问一答上 | `short_term.py` entry 仍只有 `role`（无 speaker 维度）；`_group_turns:164` 仍按 user+assistant 邻接配对（或按 `_turn_id` 分组）；`_score_turn_group` / `_sanitize_assistant_message` / `load_for_prompt` 近场加权全建立在 pair 模型上 | **仍成立——最深的一刀** |
| `_char_name()` / import 期 `_CHAR` | 88 处调用、27 文件；`tool_dispatcher`/`user_profile` import 期把名字烤死成模块级常量 | **import 期冻结已消除**：改用 `core/character_name_provider.get_active_char_name()` 运行时从 `pipeline.character` 取。`tool_dispatcher.py:18`、`user_profile.py:13` 已接入。但调用面反而扩大（≈172 处 / 43 文件），且**仍是"单活跃角色"解析**，名字尚未按 speaker 流动 | **部分过时**：地雷已拆，单活跃耦合仍在 |
| 通道协议无发言人字段 | `BaseChannel.send(content, user_id)`、WS `channel_message` 只有 `source` | `channels/base.py` 签名仍是 `send(content, user_id, behavior)`；`desktop_ws` 的 `channel_message`/`message_segments` 无 `char_id`/`speaker` | **仍成立**（防护建议②未做） |
| 调度冷却无 char 维度 | `_COOLDOWNS`/`_last_trigger` 按 trigger 名全局记账 | `loop.py:35/:77` 仍按 trigger 名为 key；`_mark(name)`/`_is_ready(name)` 全局。`_pipeline_send` 已把 `char_id` 透传给 perceive_event，但**冷却记账本身仍 char-blind** | **仍成立** |

**净变化**：唯一真正动过的是 `character_name_provider` 的引入——它把"防护建议①"的前半（杀掉 import 期冻结）做掉了，并给"名字按 scope 流动"留好了唯一接缝。其余四点原样保留。

---

## 2. 设计原则

**不要做成"N 条 pipeline 各自跑然后广播"。** 那会把单活跃假设复制 N 份，short_term/调度/通道的耦合一个都解不掉，还多出 N 倍状态同步。

引入 **Stage / Conversation 作为新的第一类实体**：

1. **花名册（roster）**：当前在场的角色集合（`list[char_id]`）。二人对话 = roster 长度为 1 的退化特例。
2. **回合仲裁器（turn arbiter）**：决定"下一个谁说话"，持有 `conversation_lock`——**一个 stage turn = 一次锁**。复用现有 `core/conversation_gate.conversation_lock(uid)`（已是 per-uid 串行锁），无需新锁原语。
3. **共享 transcript（带 `speaker_id`）**：一份对话流，每条发言标注是谁说的（`user` / `char_id`）。这是群聊唯一的新数据结构。

**记忆按投影喂入（projection）**：每个角色的记忆链（mid_term / episodic / identity）**格式一律不改**。"角色 A 听到了什么 / 记住了什么"是一次从共享 transcript 到 A 的私有视图的**投影计算**。二人对话退化为"投影 = 全量"的特例。这样五层记忆纪律（per-char scope、envelope 准入、fixation pipeline 入链）原样保留，Stage 只负责"谁听到什么"，不碰记忆格式。

> 这套形状照抄你们自己已经验证过的 Dream / Activity 模式：**独立 session 对象 + 受控回流**，而不是在主 pipeline 里内联展开。

---

## 3. 防护性前置（与群聊解耦，现在就能做，纯收益）

这两项不依赖群聊落地，做完群聊做不做都是赚的，且把最贵的协议变更提前摊销。

### 防① 名字按 scope 流动，彻底拆掉"单活跃角色名"耦合

- 接缝已就位：`character_name_provider.get_active_char_name()`。
- 动作：给它加可选 `char_id` 参数（`get_char_name(char_id: str | None = None)`），传入时按指定角色解析，不传时退化为当前活跃角色（向后兼容）。调用点逐步从"隐式活跃角色"迁到"显式 scope.character_id"。
- 收益：群聊里"这句兜底文案/工具描述是谁的"立刻可表达；非群聊时也消除了最后一处单活跃隐式依赖。
- 风险：低。≈172 处调用，但绝大多数当前语义就是"活跃角色"，迁移可分批、默认行为不变。

### 防② 通道消息信封加可选 `char_id`（发言人位）

- 动作：`BaseChannel.send(content, user_id, behavior, *, char_id: str | None = None)`；WS `channel_message` / `message_segments` 增加可选 `char_id` 字段。
- **旧客户端忽略未知字段 → 零成本向后兼容**。先把协议位留出来，不要求前端立刻渲染。
- 触达面：`channels/base.py`、`channels/desktop_ws.py`、`channels/qq.py`、`channels/mobile.py`，以及前端 Emerald-client 的 Rust 层 / mobile 轮询 / QQ 适配三端的反序列化。
- 收益：协议一旦能表达"谁说的"，Stage 落地时就不必再做一次破坏性协议升级。

---

## 4. 分期实现

| 阶段 | 目标 | 关键改动 | 可独立交付 |
|---|---|---|---|
| **P0（前置）** | 拆耦合、留协议位 | 防①（名字按 scope）+ 防②（通道 `char_id` 字段） | ✓（群聊无关也该做） |
| **P1** | short_term 支持发言人 | entry 加 `speaker_id`（assistant 条目标注 char_id）；`_group_turns`/`_score_turn_group` 改为 speaker-aware；二人对话保持默认行为 | ✓ |
| **P2** | Stage/Conversation 实体 | 新增 `core/stage/`：roster + turn arbiter（建于 conversation_lock）+ 共享 transcript；pipeline 不再"单活跃热切换"，由 Stage 持有 N 个角色视图 | 群聊 MVP |
| **P3** | 记忆投影 + 调度多角色 | transcript→各角色记忆链的投影；`_COOLDOWNS`/`_last_trigger` 加 char 维度；跨通道发言人渲染 | 完整群聊 |

**落地顺序铁律**：P1 必须在 P2 之前——schema 不带 speaker 就上 Stage，多个 assistant 进同一 history 会让配对逻辑直接错乱（最深的一刀）。

---

## 5. 不变量（必须守住）

1. **记忆五层格式不改**：Stage 只决定"谁听到什么"（投影），不碰 mid_term/episodic/identity 的写入格式与准入（envelope + fixation pipeline）。
2. **一个 stage turn = 一次 `conversation_lock`**：不引入新锁原语，不在 `run_llm()` 里加 while 循环。
3. **per-char scope 不串味**：投影读写一律经 `MemoryScope.reality_scope(uid, char_id)`（`core/memory/scope.py`），禁止默认桶。
4. **协议向后兼容**：`char_id` 是可选字段，旧客户端忽略；不得做破坏性协议升级。

---

# 群聊运行时设计（Runtime — 给实现者）

> 本部分是 P2/P3 的可落地设计。两种群聊形态：**Chat 版**（reality，类微信）与**梦境版**（dream）。两者共用同一 Stage 抽象，只是挂在不同 domain，记忆走不同回流路径。

## 6. 记忆模型：三层分离

群聊的难点在于区分「群里实际说了什么」与「角色记住了什么」。三层分开，互不混淆：

### 第 1 层 · 共享群 transcript（群文件，**不是记忆层**）
原始多人聊天流，每条带 `speaker_id`。等价于群版 short_term，所有参与者读同一份。

```
data/runtime/groups/{group_id}/
  meta.json              # roster、domain、settings（见 §10）
  transcript.json        # 共享多人 live log（近 K 条）；entry 见下
  transcript_log/{date}.md   # 群事件归档（可选，类比 event_log）
```

transcript entry：
```json
{ "speaker_id": "owner" | "<char_id>", "content": "...", "timestamp": 0,
  "_turn_id": "...", "triggered_by": "user" | "<char_id>" }
```

> `speaker_id="owner"`：单用户系统里群 = {owner} ∪ roster，群里的「人类」永远是 owner。

### 第 2 层 · 每个角色的投影记忆（写进各自单人文件，格式不变）
群聊收尾 / 滚动窗口触发时，consolidation **逐 roster 角色各跑一遍**，从该角色视角把这段群聊消化进**它自己的** mid_term → episodic → identity。写入路径仍是 `MemoryScope.reality_scope(owner_uid, char_id)`（**复用现有 scope，不新增**），打 `source="group:{group_id}"` 标签，strength 乘系数。

- 原始 transcript **不混入**单人文件；只有消化后的投影进入。
- 角色 A 的 episodic 里因此同时有「与 owner 一对一」与「群聊」记忆，后者权重低一格。
- 检索时**不按来源隔离**：A 日后与 owner 一对一时能自然回忆群里那件事（它就在 A 的 episodic 里）；`source` 仅用于加权与审计。

strength 系数（建议默认，配置见 §10）：

| 来源 | 系数 |
|---|---|
| 单人一对一 | 1.0 |
| **群聊** | **0.7** |
| 触发器 | 0.4 |

复用现有 episodic 的 strength / decay 机制（`core/memory/episodic_memory.py`），无新机制。消化走 slow-queue post_process 模式（`core/post_process/`），逐角色入链必须经 fixation pipeline + envelope，**禁止直写 episodic**。

### 第 3 层 · 群 turn 的 prompt 上下文
建 prompt 时，角色 A 的上下文 = **[A 自己的记忆层]** + **[群 transcript 近场]**。长期记忆来自 A 的投影，实时上下文来自共享文件，**不重复存**。

## 7. 双版本：同一 Stage，两个 domain

Stage（roster + 仲裁器 + 共享 transcript）domain 无关。差别只在记忆回流：

- **Chat 版** → reality domain → 投影进 reality episodic（§6）。
- **梦境版** → dream domain → 走现有 dream 隔离链：`dream_scope(uid, char_id, world_id)`、dream guard、exit afterglow 受控回流（`core/dream/`）。**绝不直写 reality**。

实现上：Stage 持有 `domain` 字段，consolidation 据此选择回流路径。梦境群聊 ≈ Stage 挂 dream domain，记忆纪律由现有 dream/reality 隔离保证。

## 8. 自主回应引擎（Arbiter）

不做轮流。核心 = **want-to-speak 打分（纯规则、不调 LLM）+ 逐个生成 + 每条后重算**。

### want-to-speak 打分（廉价）
对每个非发言者计分，因子：
- 被点名 / @ → 大加成（addressed）
- 话题相关度（复用 `core/tag_rules.py` 话题打分 + 角色人设关键词）
- 对发言者 / 对 owner 的关系亲密度
- 当前 mood / state（restless 爱插话、quiet 憋着）
- **recency penalty**：刚说过话 → 递减（防单角色刷屏）
- `talkativeness` 基线（每角色配置）

### 两阶段仲裁（每条 owner 消息触发一轮）

**Phase A — 直接回应波（`triggered_by="user"`，不计 AI 跳数）**
```
candidates = roster
responders = 0
while True:
    rescore 未在本轮发言过的 candidates        # 重算：后说的人看得到先说的
    pick = argmax(score)
    if responders < N:        pass            # 强制至少 N（不够从最高分补齐）
    elif score(pick) < THRESHOLD: break       # 够 N 之后按阈值
    if responders >= M: break                 # 上限 M
    reply = generate(pick)                     # pick 看到目前为止的全部 transcript
    append(transcript, reply); responders += 1
```

**Phase B — 自主续聊（`triggered_by="<char>"`，计 AI 跳数）**
```
ai_chain_depth = 0
while ai_chain_depth < MAX_AI_CHAIN_DEPTH:    # 默认 2 → 双跳上限
    rescore candidates with SPONTANEOUS_THRESHOLD (高于 A 的阈值)
    pick = argmax(score); if score(pick) < SPONTANEOUS_THRESHOLD: break
    reply = generate(pick); append(transcript, reply)
    ai_chain_depth += 1
# 触顶或无人想说 → 停，等 owner 再开口
```

- owner 发消息 → `ai_chain_depth` 清零。
- 「回应 owner」（Phase A，N..M）与「AI 互相弹」（Phase B，≤2 跳）是两条独立的轴，互不打架。
- 锁：**一整轮（Phase A+B）= 一次 `conversation_lock(owner_uid)`**（`core/conversation_gate.py`），逐个 `generate` 串行，禁止在 `run_llm()` 内加 while 循环。

### 节奏（决定观感，必做）
回复错峰送达，不一次性 dump；分高 / 话痨者回得快，每人加随机 think-delay（复用流式气泡延迟）。允许冷场——Phase A 的 N 下限只保证 owner 不被无视，其余话题可以没人接。

### 不机械的来源
desire 选择（不同人接不同话题）+ 逐条重算（后说的接话/反驳/或决定不说）+ recency penalty + 错峰 + 有界的 AI 互弹。

## 9. 群聊 prompt 层（在场感 / 开场白）

新增 prompt 层（须带 `_layer` 字段，见 CLAUDE.md 硬规则 3；改 tag_rules 后跑 `python tests/run_eval.py`，硬规则 4）：

- **群聊开场白**（注入到该角色 system / author-note 侧）：
  > 「现在这里是群聊，在场的还有 {其他成员名}。你说的话不只 owner 看得到，{他们} 也看得到。是否提及你和 owner 私下说过的事，由你的性格决定。」
- **transcript 渲染**：把共享 transcript 以带发言人标签的形式喂入（`A：…` / `你：…`），让角色知道每句是谁说的。

**隐私**：不设硬闸。角色读的是 [自己记忆 + 群 transcript]，一对一私聊不在群 transcript 里，默认不泄漏；但角色技术上*能*在群里提自己记得的私事——是否说出口由开场白交给**性格**决定（符合产品意图）。

## 10. 配置项（`config.yaml` / 群 `meta.json`）

```yaml
group_chat:
  min_responders: 1          # N：对 owner 消息至少回应的角色数
  max_responders: 2          # M：单轮最多回应的角色数
  max_ai_chain_depth: 2      # AI 互相触发的双跳上限
  respond_threshold: 0.5     # Phase A 阈值（够 N 之后生效）
  spontaneous_threshold: 0.7 # Phase B 自主续聊阈值（更高）
  addressed_exclusive: false # @某人时是否只有他回
  memory_strength:
    solo: 1.0
    group: 0.7
    trigger: 0.4
  debug_token_log: true      # 后台记录每轮群聊 token 消耗（不设上限，仅观测）
# 每角色：talkativeness 基线放角色卡或 per-char 配置
```

- **不设单轮 token 上限**；`debug_token_log` 在后台累计每轮群聊 token，便于观测（当前仅 2 角色）。

## 11. v1 范围边界（已决策）

- ✅ Chat 版 + 梦境版（同 Stage 两 domain）。
- ✅ owner 消息 → Phase A 自主回应（N..M）。
- ✅ AI 互相触发，双跳上限。
- ✅ 群记忆按 §6 投影入各角色单人文件，权重 0.7。
- ✅ 群聊开场白 / 在场感 prompt 层；隐私交给性格。
- ❌ **proactive 群触发（无人发言时角色主动起话头）v1 不做**——避免多角色抢调度器/冷却。留到 §1 的「调度冷却加 char 维度」就绪后再开。

---

## 附：本 spec 的现状引用锚点

- `core/pipeline.py:84,90,92,345` — 单活跃角色 + `_last_channel`
- `core/memory/short_term.py:150-184`（`_group_turns`）、`:302`（`load_for_prompt`）、`:99`（`_sanitize_assistant_message`）— 二元配对
- `core/character_name_provider.py` — 名字解析唯一接缝（防①）
- `channels/base.py` — `send` 签名（防②）
- `core/scheduler/loop.py:35,77,205-213` — char-blind 冷却
- `core/conversation_gate.py` — turn arbiter 的锁基座
- `core/memory/scope.py:50` — `MemoryScope.reality_scope`（投影读写口）

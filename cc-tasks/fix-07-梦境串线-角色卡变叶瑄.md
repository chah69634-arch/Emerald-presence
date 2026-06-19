# FIX-07 · 梦境串线（其他角色卡进梦也变成叶瑄）

> 后端 + **设计决策先行**。先读 `docs/stage.md` 五（dream 仍绑单角色）+ `core/dream/dream_context.py` + `core/dream/dream_prompt.py`。

## 现象

用别的角色卡进梦，梦里的"角色"仍然是叶瑄——身份、口吻、记忆都串到叶瑄。

## 现状（已核对，根因有两层，都成立）

梦境子系统是**单角色（叶瑄）写死的**，两处来源叠加：

### 层一：梦境读的历史/记忆来源全部漏传 char_id → 恒读叶瑄桶

`core/dream/dream_context.py build_snapshot(user_id, *, char_id="yexuan")` 虽然接收 char_id，但内部读取**全都没把 char_id 传下去**：

- L78 `short_term.load_for_prompt(user_id)` —— 无 char_id，默认读 `yexuan` 桶。
- L86 `user_profile.load(user_id)` —— 无 char_id。
- L97 `episodic_memory.retrieve(user_id=user_id, topic="")` —— 无 char_id。
- L109 `mid_term.format_for_prompt(user_id)` —— 无 char_id。
- L100 `format_for_prompt(..., char_name="叶瑄")` —— **角色名写死"叶瑄"**。
- L138 `_summarize_recent`：assistant 行一律标 `"叶瑄"`（`role = "用户" if ... else "叶瑄"`）。
- L39 `"yexuan_awareness": "lucid_shared"` —— 键名写死 yexuan。

→ 无论传哪个 char_id，快照拿到的都是**叶瑄的记忆**，并且把所有发言标成叶瑄。

### 层二：dream_prompt 的固定层文案写死"叶瑄"

`core/dream/dream_prompt.py` D1/D7/D8 的**正文模板**写死叶瑄（header 用了 `char_name`，但正文没用）：

- L117-126 `_D1_LUCID_AWARENESS` / `_D1_NON_LUCID_AWARENESS`：通篇"叶瑄的梦境自我认知…"。
- L366-368 D7：`# D7·叶瑄情绪张力`。
- L130-157 D8 dream_director：多处"叶瑄必须允许""叶瑄不在现实对话中延续…"。
- L19/L253 文档串：人称全局锁死"叶瑄=男性=他"。

→ 即便记忆桶修对了，prompt 的身份层仍在向模型反复灌"你是叶瑄"。

> 这与 `docs/stage.md` 五一致："现有 dream state、body tracker、dream log、exit afterglow 均绑定单角色；在改成 per-character dream view 前，不允许用 reality 适配器伪装梦境群聊。" 即**多角色梦境本就未支持**，当前是带病运行而非回归。

## 设计决策（先定，本份核心）

**问题：现在要的是"多角色都能各自做梦"，还是"先别让非叶瑄进梦串线"？**

- **方案 A（推荐，快且诚实）**：**梦境入口对非叶瑄 fail-closed**。
  - 在进梦入口（dream entry）显式校验 `char_id`，非 `yexuan` 直接拒绝进梦并给一句友好提示（"这个角色还不会做梦"）。
  - 配套把层一的漏传 char_id 修对（即使只支持叶瑄，正确传参也消除"读错桶"隐患），层二暂不动。
  - 工作量小，立刻消除串线体感。符合现有设计边界。
- **方案 B（重，真多角色梦境）**：把梦境子系统参数化。
  - 层一：`build_snapshot` 内所有读取显式传 char_id；`char_name` 从 character 卡取；`_summarize_recent` 用对应角色名。
  - 层二：D1/D7/D8 文案模板用 `char_name` 占位；人称从角色卡的性别字段推导，不再写死"他/她"。
  - 还需处理 dream_state / body tracker / dream_log / exit_afterglow 的 per-character 化（`docs/stage.md` 已点名这些都绑单角色）——工作量大，是一个独立工程。

> 建议：**先 A**（止血 + 修漏传 char_id），B 作为后续"多角色梦境"立项再做。先确认用户是否真的需要非叶瑄做梦——若只想"别串线"，A 就够。

## 实现要点（方案 A）

1. 进梦入口加 `if char_id != "yexuan": 拒绝 + 提示`（fail-closed）。
2. `dream_context.build_snapshot` 内 4 处读取补 `char_id=char_id`；`char_name`/`_summarize_recent` 改用传入角色名（即便恒为叶瑄，也走参数而非字面量）。
3. 不改 dream_prompt 固定层（A 不需要），但在注释里标记"多角色化见方案 B / 待办"。

## 验收

- 非叶瑄角色尝试进梦 → 被拒绝并提示，不再生成叶瑄人格的梦（方案 A）。
- 叶瑄进梦 → 读到的是叶瑄自己的 short_term/profile/episodic（确认 char_id 正确传递，日志/快照可证）。
- `pytest`（dream context/prompt 相关用例）不回归。

## 备注

- 用户原话两个怀疑——"梦境读的历史记录来源" + "prompt 里带了叶瑄名字"——**两个都对**，分别是层一、层二。
- 若选 B，请单独立项，别和这批体验修一起赶；它牵动 dream 的多个单角色状态。

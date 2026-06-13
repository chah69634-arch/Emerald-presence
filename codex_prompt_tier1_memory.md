# Codex 任务：情景记忆「事件完结/取代」机制（第一档）

## 背景与根因（先读后改）

先读 `AGENTS.md`，再读 `docs/memory.md` 的「三、情景记忆（episodic_memory）」一节。

现象：用户说过的事被叶瑄反复当成进行时来问。例如：
- 「我明天考试」→ 考完后好几轮还在按「即将考试」聊；
- 「我买了个西瓜吃」→ 说了「吃完啦」之后，他仍然问吃西瓜的情景问题。

根因（已定位，全部在 `core/memory/`）：

1. **完结事件根本没进长期记忆。** `core/memory/fixation_pipeline.py::reflect_to_episodic()` 里有过滤：
   `if data.get("emotion_peak") == "neutral" and data.get("strength", 0) < 0.4: return None`（neutral skip）。
   「吃完啦/考完了」又短又中性、强度低 → 直接被丢弃。于是 episodic 里只剩「买西瓜/明天考试」这个**开启态**。
2. **没有取代/关联。** episode 之间相互独立，topic_keywords 重叠也不会让新事件去关掉旧事件。代码里没有任何 `status / resolved / supersede` 字段。
3. **注入读起来像进行时。** `core/memory/episodic_memory.py::format_for_prompt()` 把召回片段渲染成「今天，用户买了西瓜」这类现在/无状态措辞，模型无从判断它已经结束。

> 注意：`retrieve()` 读路径已用 `allow_strengthen=False`（N2-A），召回永动机在读侧已堵，**本档不要再动 strength 写回逻辑**。

## 目标

让「完结/更新型」事件能够把对应的旧开启态记忆标记为已解决，并且：
- 已解决的记忆在召回时被排除或大幅降权；
- 万一仍被召回，注入文本用过去完成式措辞，不再像进行时。

## 具体改动

### 1. episode schema 增加状态字段
文件：`core/memory/episodic_memory.py::write_episode()`（约 122–220 行的默认填充段）。
为每条 episode 增加并默认填充：
- `"status": "open"`（取值 `open` / `resolved`）
- `"resolved_at": None`（float | None）
- `"resolved_by": None`（str | None，记录是哪条 ep_id 关闭了它）

向后兼容：读取旧记忆时 `mem.get("status", "open")`，不要假设字段存在。

### 2. 让 reflect 的 LLM 产出「是否为完结/更新」信号
文件：`core/memory/fixation_pipeline.py`，`_REFLECT_PROMPT_TEMPLATE`（约 46–58 行）。
在 JSON 模板里新增两个字段，并在说明里讲清判定标准：
```
"is_closure": true/false,            // 本段对话是否结束/完成/取消/更新了某件先前提过的事（如「吃完了」「考完了」「不去了」「已经到了」）
"closure_keywords": ["西瓜", "考试"] // 若 is_closure 为 true，列出被结束的那件事的关键词；否则空数组
```
同步更新 `_validate_episode()`（约 188–200 行）：`is_closure` 缺省按 `false`，`closure_keywords` 缺省按 `[]`，类型不对要容错，**不要因为缺这两个字段就判定整条无效**（旧 prompt 行为必须仍然通过）。

### 3. 在 reflect_to_episodic 里执行「关闭旧记忆」
文件：`core/memory/fixation_pipeline.py::reflect_to_episodic()`。

关键顺序问题：当前 neutral skip 的 `return None` 在写入之前。「吃完啦」往往就是 neutral+低强度，会在这里被丢弃。
因此 **closure 处理必须放在 neutral skip 之前**，即：先判断 `data.get("is_closure")`，若为真，则无论这条 closure 自身是否会被写入 episodic，都要先去关闭匹配的旧记忆。

关闭逻辑（新增一个私有函数，例如 `_resolve_matching_open_episodes(uid, closure_keywords, new_ep_id, char_id)`）：
- 载入 `episodic_memory._load_memories(uid, char_id=char_id)`；
- 候选 = `status != "resolved"` 且 `is_core` 不为真（核心记忆不自动关闭）且 **时间近**（`now - timestamp <= 72h`，常量化，避免关掉很久以前的同词记忆）；
- 匹配：候选的 `topic_keywords + raw_facts` 文本里命中任一 `closure_keywords` 词即算匹配（复用 `retrieve()` 里同样的子串命中思路）；
- 命中则置 `status="resolved"`、`resolved_at=now`、`resolved_by=new_ep_id`；并把 `strength` 压到一个低地板（如 `min(strength, 0.2)`），让它即使未被排除也基本浮不起来；
- 用 `episodic_memory._save_memories(...)` + 重建索引落盘（参考 write_episode 的落盘方式，保持原子写与索引一致）；
- 打一条日志 `episodic_resolved uid=... closed=[ep_ids] by=new_ep_id`。

注意并发：reflect_to_episodic 已在 `locks.uid_lock(uid)` 内，关闭逻辑要在同一把锁内完成，不要另开锁。

### 4. 召回时排除/降权已解决记忆
文件：`core/memory/episodic_memory.py::retrieve()`（约 223–320 行评分段）。
- 在候选集构建或评分循环里，跳过 `mem.get("status") == "resolved"`（最简单：直接不进 `scored`）。
- 如果希望保守一点（保留极偶尔召回的可能），改为 `score *= 0.1` 而不是硬跳过。**默认按硬跳过实现，注释里写明可调成降权。**
- `retrieve_fallback()`（约 427 行起）同样排除 resolved。

### 5. 注入文本改成过去完成式
文件：`core/memory/episodic_memory.py::format_for_prompt()`（约 380–426 行）。
- 若某条 `mem.get("status") == "resolved"`，行首时间词后追加完成态提示，例如把
  `- 今天，用户在吃西瓜` 渲染成 `- 今天，用户在吃西瓜（这件事已经结束了）`。
- 措辞由你定，关键是让模型明确「这是已完成的事，不要再当进行时追问」。

## 验收 / 测试

在 `tests/` 下新增 `test_episodic_closure.py`，至少覆盖：
1. **关闭生效**：先写一条 `topic_keywords=["西瓜"]` 的 open 记忆；模拟一次 `is_closure=true, closure_keywords=["西瓜"]` 的 reflect；断言旧记忆 `status=="resolved"`、`strength<=0.2`。
2. **neutral closure 不被吞**：closure 这条本身 neutral+低强度（会触发 neutral skip），仍要成功关闭旧记忆（即顺序正确）。
3. **召回排除**：resolved 记忆不出现在 `retrieve()` 结果里。
4. **时间窗**：72h 之前的同词 open 记忆不被误关。
5. **核心记忆豁免**：`is_core=True` 的记忆不被自动关闭。
6. **向后兼容**：不带 `is_closure/closure_keywords/status` 字段的旧 LLM 输出与旧记忆仍正常处理，`_validate_episode` 不因此判失败。

跑测试：`pytest tests/test_episodic_closure.py -v`（本仓约定见 CLAUDE.md）。

## 硬性约束（务必遵守）
- 所有 `data/` 路径必须经 `core/sandbox.get_paths()` / `path_resolver`，不要硬编码。
- 所有读写显式透传 `char_id`，不要新增 `char_id="yexuan"` 默认参数（`tests/test_r3_scope_lint.py` 会拦）。
- 落盘用 `core/safe_write` 原子写，保持记忆与 index 一致。
- 改完按本仓 doc-sync 习惯更新 `docs/memory.md`「三、情景记忆」一节，补「事件完结/状态」小节；若你认为无需更新请显式说明理由。
- 不要改 `retrieve()` 的 `allow_strengthen` 永动机逻辑（已修）。

# Codex 任务：前瞻事件 TTL + 时间分辨率（第二档）

> 前置：建议先完成第一档（`codex_prompt_tier1_memory.md`，事件完结/取代）。本档让记忆**不用等用户明说「完了」也能自愈**，并修正短程时间措辞。先读 `AGENTS.md` 与 `docs/memory.md`。

## 背景与根因

第一档解决的是「用户说了完结句」的情况。但很多事不会有明确完结句：
- 「我明天考试」——到了后天，这条仍按「即将考试」被召回；
- 「周末去爬山」——周一了还在当未来事聊。

根因：记忆只有 `timestamp`（事件被记录的时间），没有 `event_time`（事件指向的时间）。`format_for_prompt()` 又把 <1 天一律标成「今天」，分辨率太粗，区分不了「上午说想吃西瓜」和「下午已吃完」。

## 目标
1. 抽取前瞻语句的指向时间，存 `event_time` / `expires_at`；过点后该记忆自动转为过去态措辞或降权，无需用户明说。
2. 近程时间分辨率细化到「今天上午 / 几小时前」级别。

## 具体改动

### 1. 抽取事件指向时间
文件：`core/memory/fixation_pipeline.py`，`_REFLECT_PROMPT_TEMPLATE`（约 46–58 行）。
JSON 模板新增（均可空，缺省不报错）：
```
"temporal_ref": "future/past/none",   // 这段对话提到的事主要指向将来、过去还是无明确时间
"event_time_hint": "明天/周末/下周三/具体日期，无则空"  // 自然语言时间线索
```
在 `reflect_to_episodic()` 写入 episode 时，把 `event_time_hint` 解析成一个 unix 时间戳存为 `event_time`（解析失败存 None）。解析建议：
- 优先用现有依赖（仓库已有的日期解析库；若无则写一个**小而保守**的相对词解析：明天/后天/N 天后/这周末/下周X），解析不了就置 None，**不要引入重依赖**。
- 同时存 `expires_at`：对 `temporal_ref=="future"` 且能解析出 `event_time` 的，取 `event_time + 1 天`（事件当天过完即视为已发生）。其余 None。

`write_episode()`（`core/memory/episodic_memory.py`）默认填充新增 `event_time=None`、`expires_at=None`、`temporal_ref="none"`；`_validate_episode()` 对新字段全部容错缺省。

### 2. 过期自动转态
两个接入点二选一或都做（推荐都做，互为兜底）：

(a) **召回时即时判断**（轻量，必做）：在 `retrieve()` 评分段和 `format_for_prompt()` 里，对 `expires_at and now > expires_at` 的记忆视为「已发生」：
   - 评分上降权（如 `score *= 0.3`），不要再当高优先级浮起；
   - 注入文本用过去态：把「用户明天要考试」渲染成「用户那天要考试（应该已经考过了）」。

(b) **调度器扫描**（可选，做持久化）：在已有的每日维护类触发器里（参考 `core/scheduler/triggers/` 下 episodic_sweep / decay 的接法）加一个轻量扫描：把 `now > expires_at` 且仍 `status=="open"` 的记忆置 `status="elapsed"`（与第一档的 `resolved` 区分：resolved=用户明说完了，elapsed=时间过了推断完了）。`retrieve()`/`format_for_prompt()` 对 `elapsed` 与 `resolved` 同样处理。

> 若第一档尚未做 `status` 字段，本档需自带该字段定义（见第一档第 1 节）。

### 3. 近程时间分辨率细化
文件：`core/memory/episodic_memory.py::format_for_prompt()`（约 399–410 行的 days 分桶）。
把 `< 1 天` 拆细，用小时数表达，例如：
- `< 1 小时` → 「刚刚」
- `< 6 小时` → 「几小时前」
- 同一日历日内更早 → 「今天早些时候 / 今天上午」（按 `local_hour` 粗分）
- 其余沿用原有「前几天 / 上周 / 大约N天前 / N个月前」。
注意用本地时区（参考仓库里既有的 local_hour / 时区获取方式，不要用裸 UTC）。

可选：`core/memory/mid_term.py::format_for_prompt()`（约 119 行）同样地，对已过 `event_time` 的前瞻事件加一句「（应该已经发生了）」，因为 12h 窗口内的「明天考试」也会有同样问题。

## 验收 / 测试
新增 `tests/test_episodic_temporal.py`：
1. **future→elapsed**：写一条 `temporal_ref="future"`、`event_time=明天`、`expires_at=后天` 的记忆；把时钟推到 expires_at 之后；断言 `retrieve()` 中它被降权、`format_for_prompt()` 用过去态措辞（若做了 2b，断言 status 变 `elapsed`）。
2. **未过期不误伤**：event_time 在未来、未过 expires_at 的记忆仍正常按未来事召回。
3. **解析失败兜底**：`event_time_hint` 解析不了时 `event_time=None`，记忆按普通记忆处理，不报错。
4. **时间措辞**：构造不同 `timestamp` 差，断言 `format_for_prompt` 输出对应的「刚刚 / 几小时前 / 今天早些时候」。
5. **向后兼容**：旧记忆（无新字段）与旧 LLM 输出（无 temporal 字段）全程不报错。

跑测试：`pytest tests/test_episodic_temporal.py -v`。

## 硬性约束（同第一档）
- `data/` 路径一律经 `core/sandbox.get_paths()` / `path_resolver`，不硬编码。
- 显式透传 `char_id`，不新增 `char_id="yexuan"` 默认参数。
- `core/safe_write` 原子写；记忆与 index 保持一致。
- 不引入重型日期解析依赖；解析保守，失败即降级为 None。
- 改完更新 `docs/memory.md`，补「前瞻事件 TTL / 时间分辨率」小节；无需更新则显式说明理由。
- 若调度器加扫描（2b），遵循 `docs/scheduler.md` 的维护型 tick 约定，且**不发言**（纯状态变更）。

# FIX-10 · 用户画像 profile 标量字段永不覆盖（interests=跑步 卡死）

> 后端。先读 `docs/memory.md`（user_profile / fixation 段）。
> ⚠ 与 `fix-11`（幻觉写入 profile）强耦合：放开覆盖前必须先做 11，否则等于放大幻觉污染。两份一起排期、11 先落。

## 现状（已核对，根因）

`core/memory/user_profile.py` `update()` 第 136-139 行：

```python
else:
    # 其他字段：只在原值为空时更新
    if not profile.get(key) and value:
        profile[key] = value
```

- `name / location / pets / interests / occupation` 五个标量字段是 **write-once**：一旦写过非空值，`not profile.get(key)` 永远为 False，后续任何新证据都进不来。
- 所以 `interests` 早期被偶然写成"跑步"后，**没有任何自动路径能覆盖它**——只有 admin 手动 `save()`（`admin/routers/users.py:97 update_user_profile` → `user_profile.save`）能改。
- 写入触发节奏：`core/pipeline.py:519-523`，每 `summary_every_n_rounds`（默认 20）轮入队一次 `user_profile_update`，handler 在 `pipeline.py:981` → `extract_and_update`。

注意区分：这里说的是 **user_profile（基本事实）**，不是 `user_identity.yaml`（8 维行为模式）。两者不同文件、不同写入链。identity 的 `_synthesize_identity` 只把 profile 当只读参考（`fixation_pipeline.py:909-917`），不回写 profile。

## 设计决策（先定）

**问题：标量字段如何从"永不覆盖"改成"可被更可信的新证据修正"，又不引入抖动/幻觉污染？**

- **方案 A（推荐）**：区分"空→填"与"非空→改"两条路径。
  - 空值：照旧直接填。
  - 非空且新值与旧值语义不同：**不立即覆盖**，写入一个"待确认覆盖"挂起项（pending override），需要**连续 N 次（建议 2）独立提取都给出同一新值**才落盘覆盖；单次新值不足以推翻旧值。这样既能纠正长期错误，又不会因一次玩笑/幻觉翻转。
  - 必须叠加 `fix-11`：提取输入只认用户自陈，角色发言不得作为证据。
- **方案 B（最轻，应急）**：只对"用户显式更正"放行。在 `extract_and_update` 的 system prompt 里增加一类输出 `corrections: {field: new_value}`，仅当用户句中出现明确更正语义（"我不喜欢X了""其实我是做Y的""把我兴趣改成Z"）时产出，命中才允许覆盖对应标量字段。非更正语义一律不覆盖。
- **方案 C（兜底，必做）**：admin 面板已有覆盖编辑（`users.py`），确认前端能改 `interests`，作为人工纠偏的逃生口。先用它把当前"跑步"清掉，别让根因修复被这条历史脏数据干扰验收。

> 建议：**先 C 清脏数据 → 做 11 → 再上 A（或先上更小的 B 验证体感）**。

## 实现要点

1. `update()` 标量分支改为：空值直填；非空值走 pending-override 计数（方案 A）或 corrections 白名单（方案 B）。
2. pending-override 状态可存进 profile 同文件的一个隐藏键（如 `_pending_overrides`），`load()` 的 `_DEFAULT_PROFILE` 合并要兼容；`check_profile`（`core/integrity_check.py:37`）的 `_PROFILE_ALLOWED_KEYS` 需放行该内部键，否则会被判非法字段拒写。
3. 覆盖发生时打 INFO 日志（旧值→新值+触发证据条数），可观测。
4. 不动 `important_facts` 分支（它本来就是去重追加+压缩，没有覆盖问题）。

## 验收

- 构造：profile.interests 预置"跑步"，喂入 2 次都明确表达新兴趣（如"我现在主要在画画"）的对话 → interests 被覆盖为新值；只喂 1 次则不覆盖（方案 A）。
- 用户一句明确更正即覆盖、闲聊提及不覆盖（方案 B）。
- 空字段首次仍能正常填入。
- `important_facts` 行为不变。
- admin 面板能手动改 interests。
- `pytest`（补 user_profile 覆盖/不覆盖用例）。

## 备注

放开覆盖会放大 `fix-11` 的幻觉风险，**11 必须先落或同批**。否则角色一句"你不是爱跑步吗"反而可能把刚纠正的值又写回去。

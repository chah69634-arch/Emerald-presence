# FIX-09 · QQ 群聊失效 + 重做（群聊只娱乐、不混主记忆）

> 后端 + **设计先行**。先读 `docs/channels.md` + `docs/stage.md`。
> 用户定调：**QQ 群聊只是娱乐，不要混乱主记忆**。本份据此设计，不要把 QQ 群接进 fixation 主链。

## 现状（已核对）

### 入口：群消息要求 @机器人，字符串匹配很脆

`core/qq_adapter.py:214-223`：
```python
if message_type == "group":
    at_tag = f"[CQ:at,qq={_self_id}]"
    if _self_id and at_tag not in raw_message:
        return None
    content = content.replace(f"@{_self_id}", "").strip()
    content = re.sub(r"\[CQ:at,[^\]]*\]", "", content).strip()
```

**失效高度可疑点**（cc 优先实测确认）：
1. **`_self_id` 是否被正确加载**。为空时 `_self_id and ...` 短路为 False → 群消息**全部放行**（另一种异常：群里啥都回）；非空但格式不符则全部 `return None`（群里完全不回 = "失效"）。
2. **`at_tag in raw_message` 依赖 CQ 字符串**。若 NapCat 当前以**消息段数组**（`message` array，含 `{type:"at", data:{qq:...}}`）下发、`raw_message` 不含 CQ 串，则 `at_tag not in raw_message` 恒真 → 即使用户确实 @ 了机器人也被丢弃。这是"群聊整体失效"的最可能根因。
3. 黑名单/owner 门控：`is_blacklisted` 之外，主流程里 `notify_owner_turn`/`mark_user_active` 只对 owner 生效，但**回复生成对任何群成员都会跑**。

### 主流程：群消息复用单角色单用户 pipeline（设计欠妥）

`main.py handle_message`：群消息 `is_group=True` 后，仍：
- `_frozen_scope = _pipeline._current_reality_scope(user_id)` —— scope 绑在**发送者 uid** 上（非 owner 的群友也会建桶）。
- `fetch_context(user_id, content, group_id, ...)` —— 把**发送者私聊记忆** + group_context 混着喂。
- 回复经 `_qq_reality_reply_adapter` → `record_assistant_turn` → **写进该 uid 的主记忆链**（capture_turn / mid_term / fixation）。

→ 即群消息会**污染主记忆**，正与用户"别混主记忆"的诉求相悖。这套是按单 owner 私聊搭的，群聊是后来硬塞进同一条管线。

## 设计决策（先定）

**QQ 群聊重做为"隔离的娱乐通道"，与主记忆解耦。**

1. **触发**：保持 @机器人 才回（合理），但把 @ 检测改成**读消息段数组**（`message` array 里找 `type=="at" && data.qq==self_id`），不再依赖 CQ 字符串；`_self_id` 解析失败要 fail-loud 记日志，别静默放行。
2. **记忆隔离**：群消息生成回复时**不写主记忆链**——
   - 不进 `record_assistant_turn` 的 reality 主链 / 不入 `capture_turn` / `summarize_to_midterm` / `user_profile` / `fixation`。
   - 仅用轻量、独立、可丢弃的群上下文（已有 `core/memory/group_context.py`，按 group_id 存近期消息流即可），生成时只读它 + 角色卡，不读 owner 私聊记忆，也不回写。
3. **scope**：群回合用一个**专用的、非 reality 主桶**的临时上下文，别给每个群友建 reality 记忆桶。
4. **人格**：群里仍用当前活跃角色卡，但定位为"轻量娱乐应答"，可简化 prompt 层（不需要 identity 固化、隐性状态等重层）。

> 与桌宠 Stage 群（`fix-04` B）区分清楚：**桌宠 Stage 群**有意把摘要投影进各角色私聊记忆（那是设计内的）；**QQ 群**则相反，要完全隔离。两者别共用记忆策略。

## 实现要点

1. 先**实测定位入口失效**：打开 NapCat 原始事件日志，确认群 @ 事件长什么样（raw_message vs message array、self_id 值），据此修 `qq_adapter` 的 @ 检测。
2. 在 `handle_message`（或更早）给 `is_group` 分叉出**独立群处理路径**：只读 group_context + 角色卡 → 生成 → `text_output.send(group_id, segments, is_group=True)`，**不调** reality 记忆写入。
3. group_context 的读写保持/完善（按 group_id、限长、可丢弃）。
4. 确认群路径不触发 scheduler 的 owner 主动消息窗口、不触发 DND、不建 reality 桶。

## 验收

- 群里 @机器人 → 正常分条回复（修好入口）。
- 群消息**不在** owner 主记忆里留下任何痕迹（无 short_term/mid_term/episodic/identity/profile 写入；日志/文件可证）。
- 私聊体验不受群聊影响。
- 非 @ 的群消息不触发回复。
- `pytest`（qq_adapter 解析 + 群路径隔离用例）。

## 备注

- 这条同时含"修失效"和"按新定位重做"两部分。建议 cc 先用 NapCat 实测把入口失效坐实（root cause 2 还是 1），再落隔离改造。
- `fix-08`（触发器分段）与本份都碰 QQ 发送，但互不冲突：08 改主动消息发送，09 改群聊接收+生成+记忆隔离。

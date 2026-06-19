# FIX-11 · 角色幻觉被当事实写入用户画像

> 后端。先读 `docs/memory.md`（user_profile 段）+ 本仓 `core/memory/user_profile.py`。
> ⚠ 是 `fix-10` 的前置：放开 profile 覆盖前必须先堵住幻觉来源。

## 现状（已核对，根因）

提取链：`core/pipeline.py:521-523` 取 `short_term.load()` 的最近若干条（**user + assistant 都在内**）放进 `_profile_recent` → `pipeline.py:595` 入队 `user_profile_update` → `pipeline.py:981 _handler_user_profile_update` → `user_profile.extract_and_update`。

`core/memory/user_profile.py:144-177` `extract_and_update`：

```python
conv_text = "\n".join(
    f"{'用户' if m['role'] == 'user' else 'AI'}: {m['content']}"
    for m in recent_messages[-10:]
)
```

- 喂给提取 LLM 的对话里**包含 `AI:`（角色叶瑄）的发言**。
- system prompt 虽写"提取用户的个人信息"，但角色的幻觉/脑补（"你不是喜欢跑步吗""你做设计的对吧"）就摆在 `AI:` 行里，提取器很容易把它当成已确认事实抽出来。
- 唯一守卫 `core/integrity_check.py:37 check_profile` **只查格式**（字段名、类型、长度、条数），**没有任何出处/真实性校验**。
- 结果：角色一句脑补 → 写进 profile → 再被 `fix-10` 的 write-once 永久锁死。

## 设计决策

**核心原则：profile 的事实只能来自用户自陈，角色发言永远不是证据。**

- **方案 A（推荐）**：提取输入**只保留用户轮**，角色轮仅作不可引用的上下文或干脆剔除。
  - 简单做法：`conv_text` 只拼 `role == "user"` 的消息；完全不给 LLM 看 AI 行。
  - 若担心丢上下文（比如用户"对啊"指代角色上一句），保留 AI 行但显式标注且在 prompt 里强约束：**只有"用户"行里用户自己说出的才算事实；"AI"行只是对话背景，其中任何关于用户的描述都不得提取**。优先用前者（直接剔除），更稳。
- **方案 B（叠加）**：复用已有的 `trusted_user_text` 机制（见 `AGENTS.md` 关键文件速查：`main.py _trusted_user_text` / `run_owner_chat_turn(trusted_user_text=)`）。把"可信用户原文"作为提取的唯一事实源传进慢任务，而不是从混合 history 里重捞。
- **方案 C（语义守卫，可选增强）**：`check_profile` 增加一道轻校验——新提取的标量值/facts 必须能在"用户轮原文"里找到支撑（关键词/子串近似命中），否则丢弃。成本低，能挡住凭空生成。

> 建议：**A 为主（只喂用户轮）**，C 作为额外保险。B 视 trusted_user_text 在慢任务侧是否易得而定。

## 实现要点

1. 改 `_profile_recent` 的来源或 `extract_and_update` 的 `conv_text` 构造，使事实提取**不可见角色发言内容**（方案 A）。
2. 若保留 AI 行作背景，system prompt 增加硬约束句并在 few-shot 里给一个"AI 提到用户爱跑步但用户没承认 → 不提取"的反例。
3. （可选 C）`check_profile` 增加 `evidence_text` 参数做子串/关键词支撑校验，无支撑则拒写。
4. 全程不改 `important_facts` 的去重压缩逻辑。

## 验收

- 构造对话：用户从没说过职业，角色脑补"你做设计的吧"，用户只回"哈哈" → 提取结果 occupation 仍为 null，不写入。
- 用户明确自陈"我是护士" → 正常提取写入。
- 角色复述用户真实信息（用户先说过）→ 仍能提取（因为用户轮里有原文支撑）。
- `pytest`：补"角色幻觉不入 profile / 用户自陈正常入 profile"两个用例。

## 备注

本份落地后再上 `fix-10` 的覆盖放开，顺序不能反。

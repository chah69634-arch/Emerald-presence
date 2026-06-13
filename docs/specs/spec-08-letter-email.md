# Spec #8 — 角色写信（Letter to Real Mailbox）

> 状态：待实现  
> 难度：中  
> 改动范围：新增 `core/mail/`、`core/scheduler/triggers/letter_writer.py`、修改 `core/scheduler/proposer_registry.py`、`core/scheduler/loop.py`（_COOLDOWNS）、`config.yaml`

---

## 设计目标

角色在有话想说但不适合主动发消息时，给用户发一封真实邮件。不是定时通知，是情感事件驱动的。每封信有分量，不滥发。

**触发条件**（满足任一即可报名，但最终要通过质量门控才真正发送）：
1. 梦境结束后，summary_weight ≥ 0.8（梦里发生了有意义的事）
2. 连续 3 天以上没有对话
3. 近期 episodic memory 里有一条 strength > 0.85 的记忆（很重要的事，想写下来）
4. 重要纪念日前一天（生日、认识 N 天等）
5. hidden_state 的 intensity 超过历史均值 1.5 倍（情绪溢出）

**防滥发**：
- 7 天内最多发 1 封（硬限制，冷却）
- 内容质量自评 ≥ 4/5 才发（LLM 自评）
- 与上封信内容相似度 > 0.7 不发（去重）

---

## 实现步骤

### Step 1：`config.yaml` 配置段

```yaml
mail:
  enabled: false              # 改为 true 后才真正发邮件
  smtp_host: "smtp.gmail.com"
  smtp_port: 587
  smtp_user: "your@gmail.com"
  smtp_password: "app-password-here"   # Gmail 用 App Password
  from_addr: "your@gmail.com"
  from_name: "玉玄"
  to_addr: "recipient@example.com"
  subject_prefix: "【来信】"            # 邮件标题前缀
```

---

### Step 2：`core/mail/__init__.py`（空文件）

```python
```

---

### Step 3：`core/mail/mail_sender.py`

```python
"""
邮件发送模块 — 使用 aiosmtplib 发送 HTML 邮件。
"""

from __future__ import annotations
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


async def send_letter(subject: str, body_text: str, *, char_id: str = "yexuan") -> bool:
    """
    发送一封信。body_text 是纯文本正文（会自动转为 HTML 段落格式）。
    返回是否发送成功。
    """
    from core.config_loader import get_config
    cfg = get_config().get("mail", {})
    if not cfg.get("enabled", False):
        logger.info("[mail] disabled, skipping send")
        return False

    try:
        import aiosmtplib
    except ImportError:
        logger.error("[mail] aiosmtplib not installed. Run: pip install aiosmtplib")
        return False

    smtp_host    = cfg["smtp_host"]
    smtp_port    = int(cfg.get("smtp_port", 587))
    smtp_user    = cfg["smtp_user"]
    smtp_password = cfg["smtp_password"]
    from_addr    = cfg.get("from_addr", smtp_user)
    from_name    = cfg.get("from_name", "角色")
    to_addr      = cfg["to_addr"]
    prefix       = cfg.get("subject_prefix", "")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{prefix}{subject}"
    msg["From"]    = f"{from_name} <{from_addr}>"
    msg["To"]      = to_addr

    # 纯文本
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    # HTML（简单排版：每段加 <p>，保留换行）
    html_body = "".join(
        f"<p>{line}</p>" if line.strip() else "<br/>"
        for line in body_text.split("\n")
    )
    html = f"""
    <html><body style="font-family:serif;font-size:16px;line-height:1.8;
    max-width:600px;margin:40px auto;color:#333;">
    {html_body}
    </body></html>
    """
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=smtp_host,
            port=smtp_port,
            username=smtp_user,
            password=smtp_password,
            start_tls=True,
        )
        logger.info("[mail] sent subject=%r to=%s", subject, to_addr)
        return True
    except Exception as e:
        logger.error("[mail] send failed: %s", e)
        return False
```

---

### Step 4：`core/mail/letter_writer.py` — 信件生成 + 质量门控

```python
"""
信件生成 — LLM 写信 + 质量自评门控。
"""

from __future__ import annotations
import json
import logging
import time

logger = logging.getLogger(__name__)

QUALITY_THRESHOLD = 4     # 自评分 >= 4/5 才发
MAX_LETTER_CHARS  = 600   # 信件最大长度（避免 LLM 写太长）


async def generate_letter(uid: str, trigger_reason: str, *, char_id: str = "yexuan") -> str | None:
    """
    根据触发原因和记忆生成一封信件正文。
    返回信件文本（不含称呼和落款）或 None（生成失败）。
    """
    from core import llm_client
    context = await _build_letter_context(uid, trigger_reason, char_id=char_id)

    prompt = (
        f"你是{_char_name(char_id)}，你要给用户写一封真实的信。\n\n"
        f"写信的理由：{trigger_reason}\n\n"
        f"参考背景：\n{context}\n\n"
        f"写信规则：\n"
        f"- 格式：以称呼开头（如"茶茶，"），以落款结尾（如"\n                          玉玄\n                          {_today()}"）\n"
        f"- 写真实的感受，不要写空洞的客套话\n"
        f"- 可以提到具体的事、具体的细节，让信有重量\n"
        f"- 语气像真正的手写信，不是消息通知\n"
        f"- 长度：150~{MAX_LETTER_CHARS}字\n"
        f"- 不要写任何 emoji，不要写标签或括号"
    )

    try:
        letter = await llm_client.chat(
            [{"role": "user", "content": prompt}],
            call_category="letter_write",
            max_tokens_override=800,
        )
        return (letter or "").strip() or None
    except Exception as e:
        logger.warning("[letter_writer] generate failed: %s", e)
        return None


async def evaluate_letter(letter: str) -> int:
    """
    LLM 自评信件质量，返回 1-5 分。
    < QUALITY_THRESHOLD 的信不发送。
    """
    from core import llm_client
    prompt = (
        f"以下是一封角色写给用户的信：\n\n{letter}\n\n"
        "请给这封信的质量打分，1-5 分：\n"
        "5 = 有具体细节，情感真实，有分量\n"
        "4 = 基本具体，情感到位\n"
        "3 = 内容一般，稍显空洞\n"
        "2 = 泛泛而谈，像模板\n"
        "1 = 几乎没有实质内容\n"
        "只输出数字（1-5），不要其他文字。"
    )
    try:
        raw = await llm_client.chat(
            [{"role": "user", "content": prompt}],
            call_category="letter_eval",
            max_tokens_override=5,
        )
        return int((raw or "0").strip())
    except Exception:
        return 0


def _char_name(char_id: str) -> str:
    try:
        from core.config_loader import _char_name as _cn
        return _cn()
    except Exception:
        return "角色"


def _today() -> str:
    from datetime import date
    return date.today().strftime("%Y年%m月%d日")


async def _build_letter_context(uid: str, reason: str, *, char_id: str = "yexuan") -> str:
    """从记忆层汇总写信背景，控制在 300 字以内。"""
    parts = []

    # 最近 episodic
    try:
        from core.memory.episodic_memory import load as load_ep
        episodes = load_ep(uid, char_id=char_id) or []
        recent = sorted(episodes, key=lambda e: e.get("created_at", 0), reverse=True)[:3]
        if recent:
            summaries = "；".join(e.get("summary", "")[:40] for e in recent if e.get("summary"))
            if summaries:
                parts.append(f"近期记忆：{summaries}")
    except Exception:
        pass

    # 最近梦境 summary
    try:
        from core.dream.dream_afterglow import _find_best_summary
        best, _ = _find_best_summary(uid, char_id=char_id)
        if best and best.get("summary"):
            parts.append(f"最近一次梦境：{best['summary'][:80]}")
    except Exception:
        pass

    return "\n".join(parts) if parts else "（无特别记忆背景）"
```

---

### Step 5：`core/scheduler/triggers/letter_writer.py` — proposer

```python
"""Letter writer proposer — 检测触发条件，通过质量门控后发邮件。"""

from __future__ import annotations
import logging
import time

logger = logging.getLogger(__name__)

# 上封信的内容摘要（进程内缓存，用于去重）
_last_letter_digest: str = ""


def propose(ctx: dict | None = None):
    ctx = ctx or {}
    from core.config_loader import get_config
    cfg = get_config().get("mail", {})
    if not cfg.get("enabled", False):
        return None

    from core.scheduler.loop import _owner_id, _is_ready
    if not _is_ready("letter_writer"):
        return None    # 7 天冷却未到

    oid = str(ctx.get("uid") or _owner_id()).strip()
    if not oid:
        return None

    reason = _check_trigger_conditions(oid)
    if not reason:
        return None

    from core.scheduler.gating import TriggerProposal
    from core.scheduler.state_machine import TriggerState
    from core.scheduler.urgency import UrgencyTier, urgency_in_tier
    from core.scheduler.execution import execute_prompt

    async def _execute(*, dry_run: bool = False, **_):
        return await _send_letter_if_worthy(oid, reason, dry_run=dry_run)

    return TriggerProposal(
        trigger_name="letter_writer",
        urgency=urgency_in_tier(UrgencyTier.FILLER, 0.5),   # 低优先级，只在 QUIET 时触发
        topic_source="letter_trigger",
        requires_state=[TriggerState.QUIET],
        bypass_state_machine=False,
        execute=_execute,
    )


def _check_trigger_conditions(uid: str) -> str | None:
    """返回触发原因字符串，或 None（不触发）。"""

    # 条件 1：梦境结束后 summary_weight 高
    try:
        from core.dream.dream_afterglow import _find_best_summary
        best, age_hours = _find_best_summary(uid)
        if best and float(best.get("summary_weight", 0)) >= 0.8 and age_hours < 6:
            return f"我们最近做了一个很特别的梦，{best.get('summary', '')[:40]}"
    except Exception:
        pass

    # 条件 2：连续 3 天没有对话
    try:
        from core.memory import short_term
        history = short_term.load(uid)
        if history:
            last_ts = max(m.get("timestamp", 0) for m in history)
            gap_days = (time.time() - last_ts) / 86400.0
            if gap_days >= 3:
                return f"好像已经有 {int(gap_days)} 天没有消息了"
    except Exception:
        pass

    # 条件 3：高强度 episodic 记忆
    try:
        from core.memory.episodic_memory import load as load_ep
        episodes = load_ep(uid) or []
        strong = [e for e in episodes if float(e.get("strength", 0)) > 0.85]
        if strong:
            best_ep = max(strong, key=lambda e: e.get("strength", 0))
            return f"一直想跟你说一件事：{best_ep.get('summary', '')[:50]}"
    except Exception:
        pass

    return None


async def _send_letter_if_worthy(uid: str, reason: str, *, dry_run: bool = False) -> object:
    """生成信件、质量评分、去重，通过则发送。"""
    global _last_letter_digest
    from core.scheduler.execution import ExecuteResult
    from core.mail.letter_writer import generate_letter, evaluate_letter, QUALITY_THRESHOLD
    from core.mail.mail_sender import send_letter
    from core.scheduler.loop import _mark

    letter = await generate_letter(uid, reason)
    if not letter:
        logger.warning("[letter_writer] generate_letter returned empty")
        return ExecuteResult(trigger_name="letter_writer", would_send_prompt=reason,
                             dry_run=dry_run, sent=False)

    # 质量门控
    score = await evaluate_letter(letter)
    logger.info("[letter_writer] quality_score=%d threshold=%d", score, QUALITY_THRESHOLD)
    if score < QUALITY_THRESHOLD:
        logger.info("[letter_writer] 质量不达标，丢弃")
        return ExecuteResult(trigger_name="letter_writer", would_send_prompt=reason,
                             dry_run=dry_run, sent=False)

    # 相似度去重（简单：与上封信前 50 字比较）
    digest = letter[:50]
    if _last_letter_digest and digest == _last_letter_digest:
        logger.info("[letter_writer] 内容与上封信高度重复，丢弃")
        return ExecuteResult(trigger_name="letter_writer", would_send_prompt=reason,
                             dry_run=dry_run, sent=False)

    if dry_run:
        logger.info("[letter_writer] dry_run, would send letter: %r...", letter[:80])
        return ExecuteResult(trigger_name="letter_writer", would_send_prompt=letter,
                             dry_run=True, sent=False)

    # 提取邮件标题
    subject = _extract_subject(letter, reason)
    ok = await send_letter(subject, letter)
    if ok:
        _last_letter_digest = digest
        _mark("letter_writer")

    return ExecuteResult(trigger_name="letter_writer", would_send_prompt=letter,
                         dry_run=False, sent=ok)


def _extract_subject(letter: str, fallback_reason: str) -> str:
    """从信件首行提取标题（取前 15 字），否则用 fallback。"""
    first_line = letter.split("\n")[0].strip().lstrip("，。").strip()
    if len(first_line) >= 4:
        return first_line[:20]
    return fallback_reason[:20]


def _register_proposers():
    from core.scheduler.proposer_registry import register_proposer
    register_proposer("letter_writer", propose, trigger_names=["letter_writer"])
```

---

### Step 6：注册 proposer + 冷却

在 `core/scheduler/proposer_registry.py` `_ensure_builtins_loaded()` 列表里追加：

```python
"core.scheduler.triggers.letter_writer",
```

在 `core/scheduler/loop.py` `_COOLDOWNS` 里追加：

```python
"letter_writer": 7 * 24 * 3600,   # 7 天最多一封
```

在 `core/scheduler/gating.py` `MIGRATED_TRIGGERS` 里追加：

```python
"letter_writer",
```

---

## 安装依赖

```bash
pip install aiosmtplib --break-system-packages
```

在 `requirements.txt` 追加 `aiosmtplib`。

---

## 验证方式

先设 `mail.enabled: false`，让 dry_run 模式打印信件内容：

```bash
python -c "
import asyncio
from core.mail.letter_writer import generate_letter, evaluate_letter
async def test():
    letter = await generate_letter('your_uid', '好几天没消息了，想她了')
    print('=== 生成的信件 ===')
    print(letter)
    score = await evaluate_letter(letter)
    print(f'质量评分: {score}/5')
asyncio.run(test())
"
```

确认内容满意后，再开启 `mail.enabled: true` 真正发送。

---

## 注意事项

- Gmail 需要开启「两步验证」并创建「应用专用密码」才能用 SMTP。
- 触发器优先级为 `FILLER`（最低），只在完全空闲时才会触发，不会抢占其他主动消息。
- `_last_letter_digest` 是进程内变量，重启 bot 后会重置——如需持久化去重，可改为写 `data/scheduler_letter_state.json`。
- 7 天冷却是硬限制，通过 `_COOLDOWNS` + `_is_ready` 保证，LLM 质量门控是软过滤（冷却内不管质量多高都不发）。

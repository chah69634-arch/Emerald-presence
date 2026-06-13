"""Generate a character letter and evaluate whether it has enough substance."""

from __future__ import annotations

from datetime import date
import logging
import re

logger = logging.getLogger(__name__)

QUALITY_THRESHOLD = 4
MIN_LETTER_CHARS = 150
MAX_LETTER_CHARS = 600


async def generate_letter(uid: str, trigger_reason: str, *, char_id: str) -> str | None:
    """Generate a complete letter, including salutation, signature, and date."""
    from core import llm_client

    context = await _build_letter_context(uid, trigger_reason, char_id=char_id)
    char_name = _char_name()
    prompt = (
        f"你是{char_name}，你要给用户写一封会真正寄到邮箱里的信。\n\n"
        f"写信的理由：{trigger_reason}\n\n"
        f"参考背景：\n{context}\n\n"
        "写信规则：\n"
        "- 以自然的称呼开头，以角色名和日期落款\n"
        "- 写真实感受，不写空洞客套话或通知式内容\n"
        "- 至少提到一个参考背景里的具体细节，让信有重量\n"
        "- 语气像真正的手写信，不解释触发机制\n"
        f"- 正文总长度控制在 {MIN_LETTER_CHARS}~{MAX_LETTER_CHARS} 字\n"
        "- 不写 emoji、标签、Markdown 或括号动作描写\n"
        f"- 落款日期写作：{_today()}"
    )
    try:
        letter = await llm_client.chat(
            [{"role": "user", "content": prompt}],
            call_category="letter_write",
            max_tokens_override=800,
        )
    except Exception as exc:
        logger.warning("[letter_writer] generate failed: %s", exc)
        return None

    cleaned = str(letter or "").strip()
    if not cleaned:
        return None
    if len(cleaned) > MAX_LETTER_CHARS:
        logger.info("[letter_writer] generated letter too long: %d", len(cleaned))
        return None
    return cleaned


async def evaluate_letter(letter: str) -> int:
    """Return an LLM quality score from 1 to 5; malformed scores become zero."""
    if len(letter.strip()) < MIN_LETTER_CHARS or len(letter.strip()) > MAX_LETTER_CHARS:
        return 0

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
        match = re.search(r"[1-5]", str(raw or ""))
        return int(match.group(0)) if match else 0
    except Exception:
        return 0


def _char_name() -> str:
    try:
        from core.config_loader import _char_name as configured_name

        return configured_name()
    except Exception:
        return "角色"


def _today() -> str:
    return date.today().strftime("%Y年%m月%d日")


async def _build_letter_context(uid: str, reason: str, *, char_id: str) -> str:
    """Build a compact, read-only context from recent episodic and dream memory."""
    parts = [f"此刻写信的缘由：{reason[:80]}"]

    try:
        from core.memory.episodic_memory import _load_memories

        episodes = sorted(
            _load_memories(uid, char_id=char_id),
            key=lambda item: float(item.get("timestamp") or 0),
            reverse=True,
        )[:3]
        summaries = [
            str(item.get("narrative_summary") or item.get("summary") or "")[:60]
            for item in episodes
        ]
        summaries = [item for item in summaries if item]
        if summaries:
            parts.append("近期记忆：" + "；".join(summaries))
    except Exception:
        pass

    try:
        from core.dream.dream_afterglow import _find_best_summary

        best, _ = _find_best_summary(uid, char_id=char_id)
        if best and best.get("summary"):
            parts.append(f"最近一次梦境留下的情绪：{str(best['summary'])[:80]}")
    except Exception:
        pass

    context = "\n".join(parts)
    return context[:300] if context else "（没有额外背景，只按写信缘由落笔。）"

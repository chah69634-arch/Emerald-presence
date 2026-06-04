"""
Impression loader — the only reader of data/dreams/{char_id}/impressions/{uid}.json.

Provides formatted text for reality prompt layer 6g_dream_impression.

Injection strategy: ambient (newest-first, up to _MAX_INJECT unexpired entries).
No relevance retrieve — see FUTURE F1.
Framing: explicit non-reality marker + 叶瑄 self-narration "我好像在梦里……" (C3).
"""

import logging

logger = logging.getLogger(__name__)

_MAX_INJECT = 3

_NON_REALITY_FRAME = "（模糊的梦境印象，非现实发生的事）"
_CONFABULATION_GUARD = "不要在现实里复述或编造梦的具体场景，只带那点情绪余味。"


def load_impression_text(uid: str, *, char_id: str = "yexuan") -> str:
    """
    Return formatted impression block for 6g injection.
    Empty string when no active impressions exist.
    """
    try:
        from core.dream.impression_store import get_active_impressions

        active = get_active_impressions(uid, char_id=char_id)
        if not active:
            return ""

        lines: list[str] = [_NON_REALITY_FRAME, _CONFABULATION_GUARD]
        for imp in active[:_MAX_INJECT]:
            text = (imp.get("impression_text") or "").strip()
            if text:
                lines.append(text)

        if len(lines) <= 1:
            return ""

        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"[impression_loader] uid={uid}: {e}")
        return ""

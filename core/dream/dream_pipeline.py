"""
Dream session pipeline — fully isolated from core/pipeline.py.

Isolation contract (BY CONSTRUCTION):
- Never calls mood_state.update / detect_emotion / yandere check
- Never calls capture_turn / summarize_to_midterm / reflect_to_episodic
- Never writes author_note_extra
- Never calls notify_owner_turn
- Never calls any scheduler / gating / proposer
- Only reads the frozen context_snapshot; never calls fetch_context / retrieve /
  user_identity.load / mood_state.get during a dream turn
- Only writes to current_dream.jsonl via dream_log
"""

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Pre-LLM hard-exit keyword (never enters RP, never reaches LLM)
HARD_EXIT_KEYWORD = "/stop"

# Marker that LLM emits when it accepts a soft-exit request
_SOFT_EXIT_ACCEPT_MARKER = "[[EXIT_DREAM_ACCEPT]]"

# Stub placeholder returned while real LLM is not yet wired
_LLM_STUB_REPLY = "__DREAM_LLM_STUB__"


async def dream_turn(
    uid: str,
    user_msg: str,
) -> dict[str, Any]:
    """
    Process one dream conversation turn.

    Returns:
      {
        "reply":         str,
        "exit_accepted": bool,   # True if LLM soft-accepted waking up
        "force_exited":  bool,   # True if hard exit was triggered pre-LLM
        "error":         str,    # set only when not in dream state
      }
    """
    from core.dream.dream_state import read_state, write_state, DreamStatus

    state = read_state(uid)
    status = state.get("status")
    if status not in (DreamStatus.DREAM_ACTIVE.value, DreamStatus.DREAM_CLOSING.value):
        return {
            "reply": "",
            "exit_accepted": False,
            "force_exited": False,
            "error": "not_in_dream",
        }

    # ── Hard exit pre-LLM intercept ───────────────────────────────────────────
    if user_msg.strip().lower() == HARD_EXIT_KEYWORD:
        await force_exit_dream(uid)
        return {
            "reply": "（梦境已关闭）",
            "exit_accepted": False,
            "force_exited": True,
        }

    dream_id = state.get("dream_id") or _ensure_dream_id(uid, state)

    from core.dream.dream_state import get_local_state
    local_state = get_local_state(state)
    context_snapshot = state.get("context_snapshot", {})

    # ── Stub LLM placeholder (replaced in MVP1-5) ────────────────────────────
    reply = _LLM_STUB_REPLY

    # ── Write to dream log (never to any reality store) ──────────────────────
    from core.dream.dream_log import append_turn
    append_turn(uid, dream_id, "user", user_msg)
    append_turn(uid, dream_id, "assistant", reply)

    return {
        "reply": reply,
        "exit_accepted": False,
        "force_exited": False,
    }


async def force_exit_dream(uid: str) -> None:
    """
    Hard exit — unconditional, immediate, penetrates all state.
    Must be called BEFORE any LLM invocation.
    Cannot be disabled by config or role behavior (invariant D).
    """
    from core.dream.dream_state import read_state, write_state, DreamStatus

    state = read_state(uid)
    dream_id = state.get("dream_id", "")
    state["status"] = DreamStatus.DREAM_CLOSING.value
    write_state(uid, state)

    logger.info(f"[dream_pipeline] force_exit uid={uid} dream_id={dream_id}")
    await _do_close_dream(uid, dream_id, exit_type="hard_exit")


async def enter_dream(uid: str, entry_reason: str = "") -> dict[str, Any]:
    """
    Transition uid into DREAM_ACTIVE.

    Builds the frozen context snapshot, assigns a dream_id,
    and writes the new state. Called by the /dream/enter endpoint.
    """
    from core.dream.dream_state import read_state, write_state, DreamStatus
    from core.dream.dream_context import build_snapshot

    state = read_state(uid)
    # Allow re-entry only from reality states
    allowed = {
        DreamStatus.REALITY_CHAT.value,
        DreamStatus.DREAM_ENTRANCE_AVAILABLE.value,
        DreamStatus.REALITY_AFTERGLOW.value,
    }
    if state.get("status") not in allowed:
        return {"ok": False, "error": f"cannot enter dream from status={state.get('status')}"}

    dream_id = f"dream_{uid}_{int(time.time())}"
    snapshot = await build_snapshot(uid, entry_reason=entry_reason)

    state["status"] = DreamStatus.DREAM_ACTIVE.value
    state["dream_id"] = dream_id
    state["context_snapshot"] = snapshot
    state.pop("emotional_tension", None)
    state.pop("scene_state", None)
    state.pop("symbolic_anchors", None)
    write_state(uid, state)

    logger.info(f"[dream_pipeline] entered dream uid={uid} dream_id={dream_id}")
    return {"ok": True, "dream_id": dream_id}


async def _do_close_dream(uid: str, dream_id: str, exit_type: str) -> None:
    """Archive log, schedule summary generation, transition to REALITY_AFTERGLOW."""
    from core.dream.dream_state import read_state, write_state, DreamStatus, clear_local_state
    from core.dream.dream_log import archive_current

    if dream_id:
        archive_current(uid, dream_id)

    # summary runs in background — does not block the response path
    asyncio.create_task(_generate_summary_bg(uid, dream_id, exit_type))

    state = read_state(uid)
    state = clear_local_state(state)
    state["status"] = DreamStatus.REALITY_AFTERGLOW.value
    state["last_dream_id"] = dream_id
    state["last_exit_type"] = exit_type
    write_state(uid, state)

    logger.info(f"[dream_pipeline] closed dream uid={uid} exit_type={exit_type}")


async def _generate_summary_bg(uid: str, dream_id: str, exit_type: str) -> None:
    try:
        from core.dream.dream_summary import generate_summary
        await generate_summary(uid, dream_id, exit_type)
    except Exception as e:
        logger.error(f"[dream_pipeline] summary failed uid={uid}: {e}")


def _ensure_dream_id(uid: str, state: dict) -> str:
    """Assign a new dream_id if absent, persist it immediately."""
    from core.dream.dream_state import write_state
    dream_id = f"dream_{uid}_{int(time.time())}"
    state["dream_id"] = dream_id
    write_state(uid, state)
    return dream_id


def _looks_like_exit_request(msg: str) -> bool:
    exit_words = ["醒来", "结束梦", "想醒", "离开梦", "退出梦", "结束这个梦", "我要醒"]
    return any(w in msg for w in exit_words)

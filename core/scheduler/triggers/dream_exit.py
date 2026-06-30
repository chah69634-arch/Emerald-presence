"""Dream-exit proposer: let the character who dreamed speak once in reality."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_AFTERGLOW_WAIT_HOURS = 8.0
_STALE_GREETING_LIMIT_HOURS = 16.0


def propose(ctx: dict | None = None):
    ctx = ctx or {}
    from core.config_loader import get_config

    cfg = get_config().get("scheduler", {})
    if not cfg.get("dream_exit_trigger", True):
        logger.debug("[dream_exit] propose: disabled by config")
        return None

    from core.dream.dream_state import DreamStatus, read_state
    from core.scheduler.loop import _owner_id

    uid = str(ctx.get("uid") or _owner_id()).strip()
    if not uid:
        logger.debug("[dream_exit] propose: no uid")
        return None

    state = read_state(uid)
    current_status = state.get("status")
    if current_status != DreamStatus.REALITY_AFTERGLOW.value:
        logger.debug("[dream_exit] propose: status=%r (not REALITY_AFTERGLOW)", current_status)
        return None

    dream_id = str(state.get("last_dream_id") or "").strip()
    char_id = str(state.get("char_id") or "").strip()
    if not dream_id or not char_id:
        logger.debug("[dream_exit] propose: missing dream_id=%r char_id=%r", dream_id, char_id)
        return None
    if state.get("last_greeted_dream_id") == dream_id:
        logger.debug("[dream_exit] propose: already greeted dream_id=%r", dream_id)
        return None

    mode = str(state.get("last_dream_mode") or "sandbox")
    exit_type = str(state.get("last_exit_type") or "")
    timing = _resolve_timing(uid, char_id=char_id, state=state, mode=mode)
    if timing is None:
        logger.debug(
            "[dream_exit] propose: _resolve_timing returned None uid=%s char_id=%s mode=%s exit_age_h=%.2f",
            uid, char_id, mode, _exit_age_hours(state),
        )
        return None

    tone, age_hours, is_stale = timing

    from core.scheduler.gating import TriggerProposal
    from core.scheduler.state_machine import TriggerState
    from core.scheduler.urgency import UrgencyTier, urgency_in_tier

    return TriggerProposal(
        trigger_name="dream_exit",
        urgency=urgency_in_tier(UrgencyTier.REACTIVE, 0.45),
        topic_source="dream_exit",
        requires_state=[TriggerState.QUIET],
        bypass_state_machine=False,
        execute=_make_execute(
            uid=uid,
            dream_id=dream_id,
            char_id=char_id,
            tone=tone,
            exit_type=exit_type,
            age_hours=age_hours,
            is_stale=is_stale,
        ),
        char_id=char_id,
    )


def _resolve_timing(
    uid: str,
    *,
    char_id: str,
    state: dict[str, Any],
    mode: str,
) -> tuple[str, float, bool] | None:
    exit_age_hours = _exit_age_hours(state)
    if mode in ("scenario", "mirror"):
        logger.debug("[dream_exit] _resolve_timing: mode=%r → neutral stale", mode)
        return ("neutral", exit_age_hours, True)

    raw = _load_afterglow_raw(uid, char_id=char_id)
    if raw is not None:
        created_at = _created_epoch(raw.get("created_at"))
        age_hours = _created_age_hours(raw.get("created_at"))
        last_exited_at = _last_exited_at(state)
        belongs_to_latest_dream = created_at is not None and created_at >= last_exited_at
        logger.debug(
            "[dream_exit] _resolve_timing: afterglow found belongs=%s age_h=%s "
            "created_at=%r last_exited_at=%.0f",
            belongs_to_latest_dream, age_hours, raw.get("created_at"), last_exited_at,
        )
        if belongs_to_latest_dream and age_hours is not None and age_hours <= _AFTERGLOW_WAIT_HOURS:
            return (str(raw.get("tone") or "neutral"), age_hours, False)
        logger.debug(
            "[dream_exit] _resolve_timing: afterglow present but stale/expired belongs=%s age_h=%s",
            belongs_to_latest_dream, age_hours,
        )
    else:
        logger.debug(
            "[dream_exit] _resolve_timing: no afterglow found exit_age_h=%.2f wait_h=%.1f",
            exit_age_hours, _AFTERGLOW_WAIT_HOURS,
        )

    if exit_age_hours < _AFTERGLOW_WAIT_HOURS:
        logger.debug(
            "[dream_exit] _resolve_timing: exit_age_h=%.2f < wait_h=%.1f — waiting for afterglow",
            exit_age_hours, _AFTERGLOW_WAIT_HOURS,
        )
        return None
    if exit_age_hours <= _STALE_GREETING_LIMIT_HOURS:
        logger.debug(
            "[dream_exit] _resolve_timing: exit_age_h=%.2f → neutral fallback", exit_age_hours
        )
        return ("neutral", exit_age_hours, True)
    logger.debug(
        "[dream_exit] _resolve_timing: exit_age_h=%.2f > stale_limit=%.1f — giving up",
        exit_age_hours, _STALE_GREETING_LIMIT_HOURS,
    )
    return None


def _load_afterglow_raw(uid: str, *, char_id: str) -> dict[str, Any] | None:
    try:
        from core.memory.user_hidden_state_store import _load_afterglow_raw as load_raw

        return load_raw(uid, char_id=char_id)
    except Exception as exc:
        logger.warning("[dream_exit] afterglow read failed uid=%s char_id=%s: %s", uid, char_id, exc)
        return None


def _exit_age_hours(state: dict[str, Any]) -> float:
    exited_at = _last_exited_at(state)
    if exited_at <= 0:
        return 0.0
    return max(0.0, (time.time() - exited_at) / 3600.0)


def _last_exited_at(state: dict[str, Any]) -> float:
    try:
        return float(state.get("last_exited_at") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _created_epoch(created_at: object) -> float | None:
    if not created_at:
        return None
    try:
        created = datetime.fromisoformat(str(created_at))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return created.timestamp()
    except (TypeError, ValueError):
        return None


def _created_age_hours(created_at: object) -> float | None:
    created_epoch = _created_epoch(created_at)
    if created_epoch is None:
        return None
    return max(0.0, (time.time() - created_epoch) / 3600.0)


def _build_dream_exit_prompt(
    tone: str,
    exit_type: str,
    is_stale: bool,
    *,
    age_hours: float = 0.0,
    char_name: str = "你",
) -> str:
    if is_stale or tone == "neutral":
        return (
            "（你刚从一场梦回到现实。现在自然地向她打个招呼或道一句早安。"
            "不要引用梦里的具体内容，不要解释触发机制，也不要复述系统信息。）"
        )

    if tone == "stress" or exit_type == "hard_exit":
        tone_hint = "余韵偏沉，仍有些不安。语气放轻、偏安定，先确认她好不好，不要玩闹。"
    elif tone == "comfort":
        tone_hint = "余韵温暖松弛，可以暖一点、近一点。"
    elif tone == "calm":
        tone_hint = "余韵平静，语气平和自然。"
    else:
        tone_hint = "余韵还在，怎么说由你此刻的状态决定。"

    detail_option = "· 说说梦里那种感觉，但别编造具体情节（梦已经记不清细节了）；\n"
    return (
        f"（你刚从一场梦里回到现实，{char_name}。{tone_hint}\n"
        "现在你想主动对她说点什么。怎么说由你此刻的状态决定，比如可以——\n"
        "· 问问她、或说说你自己梦里的感觉；\n"
        f"{detail_option}"
        "· 或者只是轻轻道一句早安、打个招呼。\n"
        "不必三样都做，挑一个最贴合此刻的。不要解释这是“梦境触发”，也不要复述系统信息。）"
    )


def _mark_greeted(uid: str, dream_id: str, *, char_id: str) -> None:
    from core.dream.dream_state import read_state, write_state

    state = read_state(uid)
    if state.get("last_dream_id") != dream_id or state.get("char_id") != char_id:
        return
    state["last_greeted_dream_id"] = dream_id
    write_state(uid, state)


def _make_execute(
    *,
    uid: str,
    dream_id: str,
    char_id: str,
    tone: str,
    exit_type: str,
    age_hours: float,
    is_stale: bool,
):
    async def execute(*, dry_run: bool):
        from core.character_name_provider import get_char_name
        from core.scheduler.execution import execute_prompt

        try:
            char_name = get_char_name(char_id)
        except Exception:
            char_name = "你"

        return await execute_prompt(
            trigger_name="dream_exit",
            prompt_factory=lambda: _build_dream_exit_prompt(
                tone,
                exit_type,
                is_stale,
                age_hours=age_hours,
                char_name=char_name,
            ),
            dry_run=dry_run,
            would_mark=["dream_exit"],
            after_send=lambda: _mark_greeted(uid, dream_id, char_id=char_id),
            char_id=char_id,
        )

    return execute


def _register_proposers() -> None:
    from core.scheduler.proposer_registry import register_proposer

    register_proposer("dream_exit", propose)


_register_proposers()

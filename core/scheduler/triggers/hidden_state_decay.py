"""hidden_state_decay — 用户隐性状态时间衰减 + 基线收敛调度触发器。

触发器:
  _check_hidden_state_decay       12小时冷却，对 owner uid 运行 apply_time_decay
  _check_hidden_state_consolidate 7天冷却，运行 consolidate_baselines

均不发言、不影响 mood、不入 pipeline。
WriteEnvelope: stamp_trigger()（can_write_memory=True）。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def _check_hidden_state_decay() -> None:
    """12-hour tick: apply_time_decay for the configured owner uid."""
    from core.memory.user_hidden_state import apply_time_decay
    from core.memory.user_hidden_state_store import load_hidden_state, save_hidden_state
    from core.scheduler.loop import _is_ready, _mark, _owner_id
    from core.write_envelope import stamp_trigger

    if not _is_ready("hidden_state_decay"):
        return
    _mark("hidden_state_decay")

    uid = _owner_id()
    if not uid:
        logger.warning("[hidden_state_decay] owner_id not configured — skipping")
        return

    now = _utcnow_iso()
    _envelope = stamp_trigger()  # noqa: F841 — documents caller authority

    state = load_hidden_state(uid)
    state = apply_time_decay(state, now)

    if not save_hidden_state(uid, state):
        logger.error("[hidden_state_decay] save failed for uid=%s", uid)


async def _check_hidden_state_consolidate() -> None:
    """7-day tick: consolidate_baselines for the configured owner uid."""
    from core.memory.user_hidden_state import consolidate_baselines
    from core.memory.user_hidden_state_store import load_hidden_state, save_hidden_state
    from core.scheduler.loop import _is_ready, _mark, _owner_id
    from core.write_envelope import stamp_trigger

    if not _is_ready("hidden_state_consolidate"):
        return
    _mark("hidden_state_consolidate")

    uid = _owner_id()
    if not uid:
        logger.warning("[hidden_state_consolidate] owner_id not configured — skipping")
        return

    now = _utcnow_iso()
    _envelope = stamp_trigger()  # noqa: F841 — documents caller authority

    state = load_hidden_state(uid)
    state = consolidate_baselines(state, now)

    if not save_hidden_state(uid, state):
        logger.error("[hidden_state_consolidate] save failed for uid=%s", uid)

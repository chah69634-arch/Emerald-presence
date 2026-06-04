"""hidden_state_decay — 用户隐性状态时间衰减 + 基线收敛调度触发器。

触发器:
  _check_hidden_state_decay       12小时冷却，对 owner uid 运行 apply_time_decay
  _check_hidden_state_consolidate 7天冷却，运行 consolidate_baselines

均不发言、不影响 mood、不入 pipeline。
WriteEnvelope: stamp_trigger()（can_write_memory=True）。

P0 char_id 策略: 读取 active_prompt_assets.json 中的 active_character。
如果无法确定 char_id 则 WARN + skip，不静默写 yexuan。
P1 TODO: 遍历所有角色，对每个 (char_id, uid) 做 decay。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _active_char_id() -> str | None:
    """Read current active_character from active_prompt_assets.json.

    Returns None if the file is missing, unreadable, or active_character is empty.
    Callers must treat None as 'cannot determine char_id' and skip rather than
    falling back silently to yexuan.
    """
    import json as _json
    from core.sandbox import get_paths
    try:
        p = get_paths().active_prompt_assets()
        data = _json.loads(p.read_text(encoding="utf-8"))
        char_id = (data.get("active_character") or "").strip()
        if not char_id:
            logger.warning(
                "[hidden_state_decay] active_prompt_assets.json has empty active_character"
            )
            return None
        return char_id
    except Exception as exc:
        logger.warning(
            "[hidden_state_decay] cannot read active_prompt_assets: %s", exc
        )
        return None


async def _check_hidden_state_decay() -> None:
    """12-hour tick: apply_time_decay for the configured owner uid.

    P0: runs for the single active char_id only.
    P1 TODO: iterate all registered char_ids so multi-character decay runs for each.
    """
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

    char_id = _active_char_id()
    if not char_id:
        logger.warning(
            "[hidden_state_decay] cannot determine active char_id — skipping "
            "(P0 limitation: multi-char decay loop is a P1 TODO)"
        )
        return

    now = _utcnow_iso()
    _envelope = stamp_trigger()  # noqa: F841 — documents caller authority

    state = load_hidden_state(uid, char_id=char_id)
    state = apply_time_decay(state, now)

    if not save_hidden_state(uid, state, char_id=char_id):
        logger.error("[hidden_state_decay] save failed for uid=%s char_id=%s", uid, char_id)


async def _check_hidden_state_consolidate() -> None:
    """7-day tick: consolidate_baselines for the configured owner uid.

    P0: runs for the single active char_id only.
    P1 TODO: iterate all registered char_ids so multi-character consolidation runs for each.
    """
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

    char_id = _active_char_id()
    if not char_id:
        logger.warning(
            "[hidden_state_consolidate] cannot determine active char_id — skipping "
            "(P0 limitation: multi-char consolidate loop is a P1 TODO)"
        )
        return

    now = _utcnow_iso()
    _envelope = stamp_trigger()  # noqa: F841 — documents caller authority

    state = load_hidden_state(uid, char_id=char_id)
    state = consolidate_baselines(state, now)

    if not save_hidden_state(uid, state, char_id=char_id):
        logger.error("[hidden_state_consolidate] save failed for uid=%s char_id=%s", uid, char_id)

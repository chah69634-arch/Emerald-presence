"""hidden_state_decay — 用户隐性状态时间衰减 + 基线收敛调度触发器。

触发器:
  _check_hidden_state_decay       12小时冷却，遍历所有注册角色下存在 hidden_state 的 uid，运行 apply_time_decay
  _check_hidden_state_consolidate 7天冷却，运行 consolidate_baselines

均不发言、不影响 mood、不入 pipeline。
WriteEnvelope: stamp_trigger()（can_write_memory=True）。

P1: 遍历所有注册角色，对每个 (char_id, uid) 做 decay。不依赖 active_character。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def _check_hidden_state_decay() -> None:
    """12-hour tick: apply_time_decay for all registered chars × uids with hidden_state.json."""
    from core.memory.user_hidden_state import apply_time_decay
    from core.memory.user_hidden_state_store import load_hidden_state, save_hidden_state
    from core.scheduler.loop import _is_ready, _mark
    from core.write_envelope import stamp_trigger
    from core.asset_registry import get_registry
    from core.sandbox import get_paths

    if not _is_ready("hidden_state_decay"):
        return
    _mark("hidden_state_decay")

    char_ids = [e.id for e in get_registry().list_all("character")]
    if not char_ids:
        logger.warning("[hidden_state_decay] 无已注册角色，跳过")
        return

    now = _utcnow_iso()
    _envelope = stamp_trigger()  # noqa: F841 — documents caller authority

    for char_id in char_ids:
        char_root = get_paths().memory_char_root(char_id=char_id)
        if not char_root.exists():
            continue
        uids = [
            d.name for d in char_root.iterdir()
            if d.is_dir() and (d / "hidden_state.json").exists()
        ]
        for uid in uids:
            try:
                state = load_hidden_state(uid, char_id=char_id)
                state = apply_time_decay(state, now)
                if not save_hidden_state(uid, state, char_id=char_id):
                    logger.error(
                        "[hidden_state_decay] save failed uid=%s char_id=%s", uid, char_id
                    )
            except Exception as exc:
                logger.error(
                    "[hidden_state_decay] error uid=%s char_id=%s: %s", uid, char_id, exc
                )


async def _check_hidden_state_consolidate() -> None:
    """7-day tick: consolidate_baselines for all registered chars × uids with hidden_state.json."""
    from core.memory.user_hidden_state import consolidate_baselines
    from core.memory.user_hidden_state_store import load_hidden_state, save_hidden_state
    from core.scheduler.loop import _is_ready, _mark
    from core.write_envelope import stamp_trigger
    from core.asset_registry import get_registry
    from core.sandbox import get_paths

    if not _is_ready("hidden_state_consolidate"):
        return
    _mark("hidden_state_consolidate")

    char_ids = [e.id for e in get_registry().list_all("character")]
    if not char_ids:
        logger.warning("[hidden_state_consolidate] 无已注册角色，跳过")
        return

    now = _utcnow_iso()
    _envelope = stamp_trigger()  # noqa: F841 — documents caller authority

    for char_id in char_ids:
        char_root = get_paths().memory_char_root(char_id=char_id)
        if not char_root.exists():
            continue
        uids = [
            d.name for d in char_root.iterdir()
            if d.is_dir() and (d / "hidden_state.json").exists()
        ]
        for uid in uids:
            try:
                state = load_hidden_state(uid, char_id=char_id)
                state = consolidate_baselines(state, now)
                if not save_hidden_state(uid, state, char_id=char_id):
                    logger.error(
                        "[hidden_state_consolidate] save failed uid=%s char_id=%s", uid, char_id
                    )
            except Exception as exc:
                logger.error(
                    "[hidden_state_consolidate] error uid=%s char_id=%s: %s", uid, char_id, exc
                )

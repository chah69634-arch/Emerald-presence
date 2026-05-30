"""
episodic_sweep 触发器 — 扫描所有 uid 的 mid_term，
找出 age > 11h 且 promoted_to_episodic_id 为 null 的条目，批量触发 reflect_to_episodic。
冷却 30 分钟，触发类型 "sweep"。
"""

import logging
import time

from core.error_handler import log_error
from core.sandbox import get_paths

logger = logging.getLogger(__name__)


async def _check_episodic_sweep() -> None:
    from core.scheduler.loop import _is_ready, _mark

    if not _is_ready("episodic_sweep"):
        return

    _mark("episodic_sweep")

    uids: set[str] = set()

    # v1 布局：memory/{char_id}/ 下有 mid_term.json 的子目录
    char_root = get_paths().memory_char_root()
    if char_root.exists():
        uids.update(
            d.name for d in char_root.iterdir()
            if d.is_dir() and (d / "mid_term.json").exists()
        )

    # legacy 布局：data/mid_term/{uid}.json
    mid_term_dir = get_paths().mid_term()
    if mid_term_dir.exists():
        uids.update(f.stem for f in mid_term_dir.glob("*.json"))

    if not uids:
        return

    logger.debug(f"[scheduler.episodic_sweep] 扫描 {len(uids)} 个 uid")

    for uid in uids:
        try:
            await _sweep_uid(uid)
        except Exception as e:
            log_error(f"scheduler.episodic_sweep.sweep_uid.{uid}", e)


async def _sweep_uid(uid: str) -> None:
    from core.memory import mid_term as _mt
    from core.post_process import slow_queue

    events = _mt.load(uid)
    now = time.time()

    aged_ids = [
        e["mid_id"]
        for e in events
        if e.get("mid_id")
        and (now - e.get("ts", 0)) > 11 * 3600
        and not e.get("promoted_to_episodic_id")
    ]

    if not aged_ids:
        return

    slow_queue.enqueue("reflect_to_episodic", {
        "uid": uid,
        "mid_ids": aged_ids,
        "trigger": "sweep",
    })
    logger.info(
        f"[scheduler.episodic_sweep] uid={uid} 入队 reflect_to_episodic sweep "
        f"mid_ids={aged_ids}"
    )

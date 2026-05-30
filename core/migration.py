"""
S5/S6 迁移读降级辅助函数。
迁移完成后此模块可整体删除。
"""

import json as _json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_fallback_hit_count: int = 0
_first_nonzero_at: str | None = None
_fallback_recent_hits: list[dict] = []
_FALLBACK_RECENT_MAX = 20


def _record_fallback(new: Path, old: Path) -> None:
    global _first_nonzero_at, _fallback_recent_hits
    ts = datetime.now().isoformat(timespec="seconds")
    if _first_nonzero_at is None:
        _first_nonzero_at = ts
    if len(_fallback_recent_hits) < _FALLBACK_RECENT_MAX:
        _fallback_recent_hits.append({"ts": ts, "new": str(new), "old": str(old)})


def for_read(new: Path, old: Path) -> Path:
    """S5/S6 迁移读降级：new 存在且内容非空可解析时返回 new，否则 fallback 到 old。"""
    global _fallback_hit_count
    if not new.exists():
        _fallback_hit_count += 1
        _record_fallback(new, old)
        logger.debug("[for_read] fallback(missing new) → %s", old)
        return old
    try:
        raw = new.read_bytes()
        if not raw.strip():
            _fallback_hit_count += 1
            _record_fallback(new, old)
            logger.warning("[for_read] empty file, fallback to old: %s", new)
            return old
        ext = new.suffix.lower()
        if ext == ".json":
            _json.loads(raw)
        elif ext in (".yaml", ".yml"):
            import yaml as _yaml
            _yaml.safe_load(raw)
        elif ext == ".jsonl":
            first_line = raw.strip().split(b"\n", 1)[0]
            _json.loads(first_line)
    except Exception:
        _fallback_hit_count += 1
        _record_fallback(new, old)
        logger.warning("[for_read] parse failed, fallback to old: %s", new)
        return old
    return new


def get_fallback_hit_count() -> int:
    """存根：迁移完成后此值应趋零；等待后续删除。"""
    return _fallback_hit_count


def get_fallback_stats() -> dict:
    """返回迁移 fallback 命中的完整观测快照，供 soak 期可观测接口使用。"""
    return {
        "hit_count": _fallback_hit_count,
        "any_nonzero": _fallback_hit_count > 0,
        "first_nonzero_at": _first_nonzero_at,
        "recent_hits": list(_fallback_recent_hits),
    }


def reset_fallback_hit_count() -> None:
    global _fallback_hit_count, _first_nonzero_at, _fallback_recent_hits
    _fallback_hit_count = 0
    _first_nonzero_at = None
    _fallback_recent_hits = []

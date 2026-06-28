"""
core/memory/provenance_log.py
Append-only JSONL log that records why each memory write happened (G3).

Schema per record:
  {ts, turn_id, artifact, field, before_gist, after_gist, trigger_signal, origin}

Two query views:
  View A — query(uid, char_id, artifact=, field=) — "what changed this field"
  View B — query(uid, char_id, scope_yexuan_self=True) — Yexuan-self drift entries
            (currently: artifact in {"trait_state", "author_note_state"})

append() is fire-and-forget — swallows all exceptions so it never blocks writers.
"""
from __future__ import annotations

import json
import logging
import time

from core.memory.path_resolver import resolve_path
from core.memory.scope import MemoryScope, require_character_id
from core.safe_write import safe_append_jsonl, rotate_jsonl_if_needed

logger = logging.getLogger(__name__)

_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per user
_KEEP_N = 3

# Artifacts considered "Yexuan-self" drift (View B)
_YEXUAN_SELF_ARTIFACTS: frozenset[str] = frozenset({
    "trait_state",
    "author_note_state",
})


def _log_path(uid: str, char_id: str):
    require_character_id(char_id)
    scope = MemoryScope.reality_scope(str(uid), char_id)
    p = resolve_path(scope, "provenance_log")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def append(
    uid: str,
    char_id: str,
    *,
    artifact: str,
    field: str = "",
    before_gist: str = "",
    after_gist: str = "",
    trigger_signal: str = "",
    turn_id: str = "",
    origin: dict | None = None,
) -> None:
    """Append one provenance record.  Never raises — must not block the write path."""
    try:
        if origin is None:
            from core.observe.prompt_capture import _capture_origin
            origin = _capture_origin.get()
        record = {
            "ts": time.time(),
            "turn_id": turn_id,
            "artifact": artifact,
            "field": field,
            "before_gist": before_gist[:120] if before_gist else "",
            "after_gist": after_gist[:120] if after_gist else "",
            "trigger_signal": trigger_signal[:120] if trigger_signal else "",
            "origin": origin,
        }
        path = _log_path(uid, char_id)
        safe_append_jsonl(path, record)
        rotate_jsonl_if_needed(path, max_bytes=_MAX_BYTES, keep_n=_KEEP_N)
    except Exception as exc:
        logger.debug(
            "[provenance_log] append suppressed (uid=%s artifact=%s): %s",
            uid, artifact, exc,
        )


def query(
    uid: str,
    char_id: str,
    *,
    artifact: str = "",
    field: str = "",
    scope_yexuan_self: bool = False,
    limit: int = 200,
) -> list[dict]:
    """Return provenance records newest-first, with optional filters."""
    try:
        require_character_id(char_id)
        scope = MemoryScope.reality_scope(str(uid), char_id)
        path = resolve_path(scope, "provenance_log")
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        records: list[dict] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if scope_yexuan_self and rec.get("artifact") not in _YEXUAN_SELF_ARTIFACTS:
                continue
            if artifact and rec.get("artifact") != artifact:
                continue
            if field and rec.get("field") != field:
                continue
            records.append(rec)
        records.reverse()  # newest-first
        return records[:limit]
    except Exception as exc:
        logger.warning("[provenance_log] query failed uid=%s: %s", uid, exc)
        return []

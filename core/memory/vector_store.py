"""
core/memory/vector_store.py
===========================
Per-user sqlite-vec semantic index. Derived data — JSON/MD files are the source of truth;
this DB can be deleted and rebuilt at any time via rebuild().

Fail-open contract: every public function swallows exceptions and logs them.
The main reply path is never blocked by vector store failures.
"""
from __future__ import annotations

import logging
import struct
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── internals ────────────────────────────────────────────────────────────────

def _configured_dim() -> int:
    try:
        from core.config_loader import get_config
        return int(get_config().get("embedding", {}).get("dim", 1024))
    except Exception:
        return 1024


def _db_path(uid: str, char_id: str) -> Path:
    from core.sandbox import get_paths, safe_user_id
    return get_paths().user_memory_root(safe_user_id(uid), char_id=char_id) / "vector_store.db"


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _open_db(uid: str, char_id: str):
    """Open sqlite connection with vec0 extension. Returns None (never raises) on failure."""
    import sqlite3
    try:
        import sqlite_vec
    except ImportError:
        logger.debug("[vector_store] sqlite_vec not installed; semantic recall disabled")
        return None

    path = _db_path(uid, char_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(path))
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
        return db
    except Exception as e:
        logger.warning("[vector_store] cannot open db uid=%s: %s", uid, e)
        return None


def _ensure_tables(db, dim: int) -> None:
    db.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_items USING vec0(embedding float[{dim}])"
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS vec_meta (
            rowid    INTEGER PRIMARY KEY,
            source   TEXT,
            source_id TEXT,
            ts       REAL,
            text_preview TEXT
        )"""
    )
    db.commit()


# ── public API ────────────────────────────────────────────────────────────────

async def upsert(
    uid: str,
    char_id: str,
    source: str,
    source_id: str,
    ts: float,
    text: str,
) -> None:
    """Embed text and store in the vector DB. Fail-open: log and return on any error."""
    from core.memory.embedding import embed, EmbeddingUnavailable

    dim = _configured_dim()
    try:
        vecs = await embed([text])
        vec = vecs[0]
    except EmbeddingUnavailable as e:
        logger.debug(
            "[vector_store] embedding unavailable, skip upsert source_id=%s: %s", source_id, e
        )
        return
    except Exception as e:
        logger.warning("[vector_store] embed error source_id=%s: %s", source_id, e)
        return

    if len(vec) != dim:
        logger.warning(
            "[vector_store] dim mismatch: got %d expected %d; skip upsert (check embedding.dim in config)",
            len(vec), dim,
        )
        return

    db = _open_db(uid, char_id)
    if db is None:
        return
    try:
        _ensure_tables(db, dim)
        row = db.execute(
            "SELECT rowid FROM vec_meta WHERE source=? AND source_id=?",
            (source, source_id),
        ).fetchone()
        blob = _pack(vec)
        if row:
            rowid = row[0]
            db.execute("DELETE FROM vec_items WHERE rowid=?", (rowid,))
            db.execute(
                "INSERT INTO vec_items(rowid, embedding) VALUES (?, ?)", (rowid, blob)
            )
            db.execute(
                "UPDATE vec_meta SET ts=?, text_preview=? WHERE rowid=?",
                (ts, text[:200], rowid),
            )
        else:
            cur = db.execute(
                "INSERT INTO vec_meta(source, source_id, ts, text_preview) VALUES (?, ?, ?, ?)",
                (source, source_id, ts, text[:200]),
            )
            rowid = cur.lastrowid
            db.execute(
                "INSERT INTO vec_items(rowid, embedding) VALUES (?, ?)", (rowid, blob)
            )
        db.commit()
        logger.debug(
            "[vector_store] upsert ok source=%s source_id=%s uid=%s", source, source_id, uid
        )
    except Exception as e:
        logger.warning(
            "[vector_store] db write error uid=%s source_id=%s: %s", uid, source_id, e
        )
    finally:
        db.close()


def query(
    uid: str,
    char_id: str,
    query_vec: list[float],
    k: int,
    *,
    sources: Optional[list[str]] = None,
    since_ts: Optional[float] = None,
) -> list[tuple[str, float, float]]:
    """
    Return top-k nearest neighbours as (source_id, distance, ts).
    Fail-open: return [] on any error.
    recency filter: pass since_ts to restrict results to ts >= since_ts.
    source filter: pass sources=['episodic'] to restrict by source kind.
    """
    dim = _configured_dim()
    if len(query_vec) != dim:
        logger.warning(
            "[vector_store] query dim mismatch: got %d expected %d", len(query_vec), dim
        )
        return []

    db = _open_db(uid, char_id)
    if db is None:
        return []
    try:
        _ensure_tables(db, dim)
        # Over-fetch to allow post-filter by source / since_ts.
        fetch_k = k * 4 if (sources or since_ts is not None) else k
        rows = db.execute(
            "SELECT vi.rowid, vi.distance"
            " FROM vec_items vi"
            " WHERE vi.embedding MATCH ? AND vi.k = ?",
            (_pack(query_vec), fetch_k),
        ).fetchall()

        if not rows:
            return []

        rowids = [r[0] for r in rows]
        dist_map = {r[0]: r[1] for r in rows}

        placeholders = ",".join("?" * len(rowids))
        meta_rows = db.execute(
            f"SELECT rowid, source, source_id, ts FROM vec_meta WHERE rowid IN ({placeholders})",
            rowids,
        ).fetchall()

        results: list[tuple[str, float, float]] = []
        for rowid, src, src_id, ts in meta_rows:
            if sources is not None and src not in sources:
                continue
            if since_ts is not None and ts < since_ts:
                continue
            results.append((src_id, dist_map[rowid], ts))

        results.sort(key=lambda x: x[1])
        return results[:k]
    except Exception as e:
        logger.warning("[vector_store] query error uid=%s: %s", uid, e)
        return []
    finally:
        db.close()


async def rebuild(uid: str, char_id: str) -> int:
    """
    Drop and rebuild the entire vector DB from episodic.json and recent event_log.
    Idempotent. Returns the number of items inserted.
    """
    path = _db_path(uid, char_id)
    if path.exists():
        try:
            path.unlink()
            logger.info("[vector_store] rebuild: dropped old db uid=%s", uid)
        except Exception as e:
            logger.warning("[vector_store] rebuild: cannot remove old db: %s", e)

    count = 0
    try:
        from core.memory.episodic_memory import _load_memories
        memories = _load_memories(uid, char_id=char_id)
        for ep in memories:
            ep_id = str(ep.get("id", ""))
            ts = float(ep.get("timestamp") or ep.get("occurred_at") or 0)
            text = (
                ep.get("narrative_summary")
                or ep.get("summary")
                or " ".join(ep.get("raw_facts") or [])
            ).strip()
            if not text or not ep_id:
                continue
            await upsert(uid, char_id, "episodic", ep_id, ts, text)
            count += 1

        from core.memory.event_log import get_recent_days as _get_recent
        import time as _time
        recent_text = _get_recent(uid, days=30, char_id=char_id)
        if recent_text:
            await upsert(
                uid, char_id, "event_log", f"recent_{uid}",
                _time.time(), recent_text[:2000],
            )
            count += 1
    except Exception as e:
        logger.warning("[vector_store] rebuild error uid=%s: %s", uid, e)

    logger.info("[vector_store] rebuild complete uid=%s count=%d", uid, count)
    return count


def query_with_preview(
    uid: str,
    char_id: str,
    query_vec: list[float],
    k: int,
    *,
    sources: Optional[list[str]] = None,
) -> list[tuple[str, str, float]]:
    """
    Return top-k nearest neighbours as (source_id, text_preview, distance).
    Useful for web recall where display text is needed alongside the URL.
    Fail-open: return [] on any error.
    source filter: pass sources=['web'] to restrict by source kind.
    """
    dim = _configured_dim()
    if len(query_vec) != dim:
        logger.warning(
            "[vector_store] query_with_preview dim mismatch: got %d expected %d", len(query_vec), dim
        )
        return []

    db = _open_db(uid, char_id)
    if db is None:
        return []
    try:
        _ensure_tables(db, dim)
        fetch_k = k * 4 if sources else k
        rows = db.execute(
            "SELECT vi.rowid, vi.distance"
            " FROM vec_items vi"
            " WHERE vi.embedding MATCH ? AND vi.k = ?",
            (_pack(query_vec), fetch_k),
        ).fetchall()

        if not rows:
            return []

        rowids = [r[0] for r in rows]
        dist_map = {r[0]: r[1] for r in rows}

        placeholders = ",".join("?" * len(rowids))
        meta_rows = db.execute(
            f"SELECT rowid, source, source_id, text_preview"
            f" FROM vec_meta WHERE rowid IN ({placeholders})",
            rowids,
        ).fetchall()

        results: list[tuple[str, str, float]] = []
        for rowid, src, src_id, preview in meta_rows:
            if sources is not None and src not in sources:
                continue
            results.append((src_id, preview or "", dist_map[rowid]))

        results.sort(key=lambda x: x[2])
        return results[:k]
    except Exception as e:
        logger.warning("[vector_store] query_with_preview error uid=%s: %s", uid, e)
        return []
    finally:
        db.close()


def delete(uid: str, char_id: str, source: str, source_id: str) -> bool:
    """Delete a single vector entry by (source, source_id). Fail-open: returns False on error."""
    db = _open_db(uid, char_id)
    if db is None:
        return False
    try:
        _ensure_tables(db, _configured_dim())
        row = db.execute(
            "SELECT rowid FROM vec_meta WHERE source=? AND source_id=?",
            (source, source_id),
        ).fetchone()
        if row is None:
            return False
        rowid = row[0]
        db.execute("DELETE FROM vec_items WHERE rowid=?", (rowid,))
        db.execute("DELETE FROM vec_meta WHERE rowid=?", (rowid,))
        db.commit()
        logger.debug(
            "[vector_store] delete ok source=%s source_id=%s uid=%s", source, source_id, uid
        )
        return True
    except Exception as e:
        logger.warning(
            "[vector_store] delete error uid=%s source_id=%s: %s", uid, source_id, e
        )
        return False
    finally:
        db.close()


def dist_to_sim(dist: float) -> float:
    """Convert L2 distance to similarity ∈ (0, 1]. Smaller distance → larger similarity."""
    return 1.0 / (1.0 + dist)


def _recall_weights() -> tuple[float, float, float]:
    try:
        from core.config_loader import get_config
        w = get_config().get("recall", {}).get("weights", {})
        return (
            float(w.get("sem", 0.4)),
            float(w.get("kw", 0.3)),
            float(w.get("strength", 0.3)),
        )
    except Exception:
        return 0.4, 0.3, 0.3


def score_recall(
    semantic_sim: float,
    keyword_relevance: float,
    strength: float = 0.5,
    decay: float = 1.0,
) -> float:
    """
    Fused recall score: w_sem*semantic_sim + w_kw*keyword_relevance + w_str*(strength*decay).
    Weights from config recall.weights.{sem,kw,strength} (defaults 0.4/0.3/0.3).
    When embedding is unavailable, pass semantic_sim=0.0 — the w_sem term drops out
    and the formula degrades gracefully to keyword + strength (fail-open).
    """
    w_sem, w_kw, w_str = _recall_weights()
    return w_sem * semantic_sim + w_kw * keyword_relevance + w_str * (strength * decay)

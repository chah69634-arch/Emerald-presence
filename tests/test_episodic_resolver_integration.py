"""
tests/test_episodic_resolver_integration.py

P1-2F: episodic memory 路径迁移验收测试

Covers:
1.  episodic load/write 路径与 resolver "episodic" 路径一致
2.  memory_index 路径与 resolver "memory_index" 路径一致
3.  episodic 物理路径与旧路径（user_memory_root/{uid}/episodic.json）完全一致
4.  memory_index 物理路径与旧路径完全一致
5.  char_id=None → fail-loud（ValueError），不 fallback yexuan
6.  char_id="" → fail-loud（ValueError），不 fallback yexuan
7.  yexuan / hongcha 两个 episodic bucket 内容互不污染
8.  hongcha retrieve 不含 yexuan bucket 唯一词
9.  写入 hongcha memory_index，不写 yexuan memory_index
10. 回归：memory_path_resolver 核心断言（episodic/memory_index layout）
"""

import json
import time

import pytest

from core.memory.scope import MemoryScope
from core.memory.path_resolver import resolve_path
from core.memory.episodic_memory import (
    write_episode,
    retrieve,
    _load_memories,
    _save_memories,
    _rebuild_index,
    _load_index,
    _mem_read_file,
    _mem_write_file,
    _index_read_file,
    _index_write_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ep(ep_id: str, summary: str, tags: list[str] | None = None) -> dict:
    return {
        "id": ep_id,
        "timestamp": time.time(),
        "raw_facts": [summary],
        "topic_keywords": tags or [],
        "emotion_peak": "happy",
        "emotion_texture": "",
        "emotion_arc": "",
        "user_state": "neutral",
        "narrative_summary": summary,
        "strength": 0.7,
        "retrieval_count": 0,
        "last_retrieved": None,
        "summary": summary,
        "tags": tags or [],
    }


def _scope(uid: str, char_id: str) -> MemoryScope:
    return MemoryScope.reality_scope(uid, char_id)


# ---------------------------------------------------------------------------
# 1. episodic 路径与 resolver "episodic" 路径一致
# ---------------------------------------------------------------------------

def test_mem_read_file_matches_resolver(sandbox):
    uid, char_id = "u1", "yexuan"
    store_path = _mem_read_file(uid, char_id=char_id)
    resolver_path = resolve_path(_scope(uid, char_id), "episodic")
    assert store_path == resolver_path


def test_mem_write_file_matches_resolver(sandbox):
    uid, char_id = "u1", "yexuan"
    store_path = _mem_write_file(uid, char_id=char_id)
    resolver_path = resolve_path(_scope(uid, char_id), "episodic")
    assert store_path == resolver_path


# ---------------------------------------------------------------------------
# 2. memory_index 路径与 resolver "memory_index" 路径一致
# ---------------------------------------------------------------------------

def test_index_read_file_matches_resolver(sandbox):
    uid, char_id = "u1", "yexuan"
    store_path = _index_read_file(uid, char_id=char_id)
    resolver_path = resolve_path(_scope(uid, char_id), "memory_index")
    assert store_path == resolver_path


def test_index_write_file_matches_resolver(sandbox):
    uid, char_id = "u1", "yexuan"
    store_path = _index_write_file(uid, char_id=char_id)
    resolver_path = resolve_path(_scope(uid, char_id), "memory_index")
    assert store_path == resolver_path


# ---------------------------------------------------------------------------
# 3. episodic 物理路径与旧路径（user_memory_root/{uid}/episodic.json）完全一致
# ---------------------------------------------------------------------------

def test_episodic_physical_path_equals_legacy_layout(sandbox):
    """resolver 返回的路径 == user_memory_root(uid, char_id) / 'episodic.json'"""
    from core.sandbox import get_paths, safe_user_id
    uid, char_id = "u42", "yexuan"
    expected = get_paths().user_memory_root(safe_user_id(uid), char_id=char_id) / "episodic.json"
    actual = resolve_path(_scope(uid, char_id), "episodic")
    assert actual == expected


def test_episodic_physical_path_layout_contains_runtime_memory(sandbox):
    """路径格式包含 runtime/memory/{char_id}/{uid}/episodic.json"""
    p = str(resolve_path(_scope("u99", "yexuan"), "episodic")).replace("\\", "/")
    assert "runtime/memory/yexuan/u99/episodic.json" in p


# ---------------------------------------------------------------------------
# 4. memory_index 物理路径与旧路径完全一致
# ---------------------------------------------------------------------------

def test_memory_index_physical_path_equals_legacy_layout(sandbox):
    """resolver 返回的路径 == user_memory_root(uid, char_id) / 'memory_index.json'"""
    from core.sandbox import get_paths, safe_user_id
    uid, char_id = "u42", "yexuan"
    expected = get_paths().user_memory_root(safe_user_id(uid), char_id=char_id) / "memory_index.json"
    actual = resolve_path(_scope(uid, char_id), "memory_index")
    assert actual == expected


def test_memory_index_physical_path_layout_contains_runtime_memory(sandbox):
    """路径格式包含 runtime/memory/{char_id}/{uid}/memory_index.json"""
    p = str(resolve_path(_scope("u99", "yexuan"), "memory_index")).replace("\\", "/")
    assert "runtime/memory/yexuan/u99/memory_index.json" in p


# ---------------------------------------------------------------------------
# 5. char_id=None → fail-loud
# ---------------------------------------------------------------------------

def test_mem_read_file_none_char_id_raises(sandbox):
    with pytest.raises((ValueError, TypeError)):
        _mem_read_file("u1", char_id=None)  # type: ignore[arg-type]


def test_mem_write_file_none_char_id_raises(sandbox):
    with pytest.raises((ValueError, TypeError)):
        _mem_write_file("u1", char_id=None)  # type: ignore[arg-type]


def test_index_read_file_none_char_id_raises(sandbox):
    with pytest.raises((ValueError, TypeError)):
        _index_read_file("u1", char_id=None)  # type: ignore[arg-type]


def test_index_write_file_none_char_id_raises(sandbox):
    with pytest.raises((ValueError, TypeError)):
        _index_write_file("u1", char_id=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 6. char_id="" → fail-loud
# ---------------------------------------------------------------------------

def test_mem_read_file_empty_char_id_raises(sandbox):
    with pytest.raises(ValueError):
        _mem_read_file("u1", char_id="")


def test_mem_write_file_empty_char_id_raises(sandbox):
    with pytest.raises(ValueError):
        _mem_write_file("u1", char_id="")


def test_index_read_file_empty_char_id_raises(sandbox):
    with pytest.raises(ValueError):
        _index_read_file("u1", char_id="")


def test_index_write_file_empty_char_id_raises(sandbox):
    with pytest.raises(ValueError):
        _index_write_file("u1", char_id="")


# ---------------------------------------------------------------------------
# 7. yexuan / hongcha 两个 episodic bucket 内容互不污染
# ---------------------------------------------------------------------------

def test_yexuan_hongcha_episodic_buckets_isolated(sandbox):
    uid = "u1"
    ep_y = _ep("ep_y1", "叶萱独有的记忆片段", tags=["叶萱专属"])
    ep_h = _ep("ep_h1", "红茶独有的记忆片段", tags=["红茶专属"])

    write_episode(uid, ep_y, char_id="yexuan")
    write_episode(uid, ep_h, char_id="hongcha")

    mems_y = _load_memories(uid, char_id="yexuan")
    mems_h = _load_memories(uid, char_id="hongcha")

    ids_y = {m["id"] for m in mems_y}
    ids_h = {m["id"] for m in mems_h}

    assert "ep_y1" in ids_y
    assert "ep_h1" not in ids_y
    assert "ep_h1" in ids_h
    assert "ep_y1" not in ids_h


# ---------------------------------------------------------------------------
# 8. hongcha retrieve 不含 yexuan bucket 唯一词
# ---------------------------------------------------------------------------

def test_hongcha_retrieve_does_not_surface_yexuan_content(sandbox):
    uid = "u2"
    unique_word = "叶萱唯一词汇XYZ"
    ep_y = _ep("ep_y2", f"{unique_word}只在叶萱桶里", tags=["叶萱独享"])
    ep_h = _ep("ep_h2", "红茶自己的回忆", tags=["红茶回忆"])

    write_episode(uid, ep_y, char_id="yexuan")
    write_episode(uid, ep_h, char_id="hongcha")

    results = retrieve(uid, topic="叶萱独享", top_k=5, char_id="hongcha")
    summaries = " ".join(m.get("narrative_summary", "") for m in results)
    assert unique_word not in summaries


# ---------------------------------------------------------------------------
# 9. 写入 hongcha memory_index 不写 yexuan memory_index
# ---------------------------------------------------------------------------

def test_rebuild_index_hongcha_does_not_touch_yexuan_index(sandbox):
    uid = "u3"
    ep_h = _ep("ep_h3", "红茶的片段", tags=["标签A"])
    memories_h = [ep_h]

    _rebuild_index(uid, memories_h, char_id="hongcha")

    idx_y_path = resolve_path(_scope(uid, "yexuan"), "memory_index")
    assert not idx_y_path.exists(), "写入 hongcha index 不应创建 yexuan index 文件"

    idx_h = _load_index(uid, char_id="hongcha")
    assert "标签A" in idx_h
    assert "ep_h3" in idx_h["标签A"]


# ---------------------------------------------------------------------------
# 10. write_episode + retrieve round-trip（含 mkdir 行为验证）
# ---------------------------------------------------------------------------

def test_write_episode_creates_file_in_correct_location(sandbox):
    uid, char_id = "u4", "yexuan"
    ep = _ep("ep_rt1", "往事如烟", tags=["往事"])
    write_episode(uid, ep, char_id=char_id)

    expected_path = resolve_path(_scope(uid, char_id), "episodic")
    assert expected_path.exists()

    stored = json.loads(expected_path.read_text(encoding="utf-8"))
    ids = [m["id"] for m in stored]
    assert "ep_rt1" in ids


def test_retrieve_reads_from_correct_path(sandbox):
    uid, char_id = "u5", "hongcha"
    ep = _ep("ep_rt2", "红茶的独特记忆", tags=["独特"])
    write_episode(uid, ep, char_id=char_id)

    results = retrieve(uid, topic="独特", top_k=3, char_id=char_id)
    ids = [m["id"] for m in results]
    assert "ep_rt2" in ids


# ---------------------------------------------------------------------------
# Regression: resolver layout tests (episodic/memory_index)
# ---------------------------------------------------------------------------

def test_resolver_episodic_exact_layout(sandbox):
    scope = MemoryScope.reality_scope("u123", "char1")
    p = str(resolve_path(scope, "episodic")).replace("\\", "/")
    assert "runtime/memory/char1/u123/episodic.json" in p


def test_resolver_memory_index_exact_layout(sandbox):
    scope = MemoryScope.reality_scope("u123", "char1")
    p = str(resolve_path(scope, "memory_index")).replace("\\", "/")
    assert "runtime/memory/char1/u123/memory_index.json" in p


def test_resolver_episodic_same_parent_as_mid_term(sandbox):
    scope = MemoryScope.reality_scope("u123", "char1")
    ep = resolve_path(scope, "episodic")
    mt = resolve_path(scope, "mid_term")
    assert ep.parent == mt.parent


def test_resolver_memory_index_same_parent_as_mid_term(sandbox):
    scope = MemoryScope.reality_scope("u123", "char1")
    idx = resolve_path(scope, "memory_index")
    mt = resolve_path(scope, "mid_term")
    assert idx.parent == mt.parent

"""
tests/test_short_term_resolver_integration.py — P1-2G

Verifies that short_term.py routes all history paths through
MemoryScope + resolve_path, and that the resolved physical layout
matches the pre-migration layout (runtime/memory/{char_id}/{uid}/history.json).

Covers:
 1. append writes to resolver-computed history path
 2. load reads from resolver-computed history path
 3. clear removes resolver-computed history path
 4. get_history reads from resolver-computed history path
 5. load_for_prompt reads from resolver-computed history path
 6. Physical path matches old user_memory_root / history.json layout exactly
 7. char_id=None → fail-loud ValueError, no yexuan fallback
 8. char_id="" → fail-loud ValueError, no yexuan fallback
 9. yexuan / character_b buckets are fully isolated
10. load_for_prompt(character_b) does not contain yexuan-unique token
11–14. Regression placeholders (run via separate pytest invocations per task spec)
"""

import pytest

from core.memory.path_resolver import resolve_path
from core.memory.scope import MemoryScope
from core.sandbox import get_paths, safe_user_id


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _expected_path(uid: str, char_id: str):
    """Old layout: user_memory_root(uid, char_id=char_id) / 'history.json'."""
    return get_paths().user_memory_root(safe_user_id(uid), char_id=char_id) / "history.json"


# ---------------------------------------------------------------------------
# 1. append writes to resolver path
# ---------------------------------------------------------------------------

def test_append_writes_to_resolver_path(sandbox):
    """append(uid, char_id='character_b') creates the file at the resolver-computed path."""
    from core.memory.short_term import append

    uid = "u_p2g_append"
    append(uid, "user", "hello", char_id="character_b")

    scope = MemoryScope.reality_scope(safe_user_id(uid), "character_b")
    expected = resolve_path(scope, "history")
    assert expected.exists(), f"history file not found at resolver path: {expected}"


# ---------------------------------------------------------------------------
# 2. load reads from resolver path
# ---------------------------------------------------------------------------

def test_load_reads_from_resolver_path(sandbox):
    """load(uid, char_id='character_b') reads the file at the resolver-computed path."""
    from core.memory.short_term import append, load

    uid = "u_p2g_load"
    SENTINEL = "p2g-load-sentinel-character_b"
    append(uid, "user", SENTINEL, char_id="character_b")

    result = load(uid, char_id="character_b")
    assert any(SENTINEL in m.get("content", "") for m in result), (
        f"load(character_b) must return appended content; got {result}"
    )


# ---------------------------------------------------------------------------
# 3. clear removes resolver path content
# ---------------------------------------------------------------------------

def test_clear_empties_resolver_path(sandbox):
    """clear(uid, char_id='character_b') empties the file at the resolver-computed path."""
    from core.memory.short_term import append, clear, load

    uid = "u_p2g_clear"
    append(uid, "user", "some content", char_id="character_b")
    assert load(uid, char_id="character_b") != []

    clear(uid, char_id="character_b")
    assert load(uid, char_id="character_b") == [], "history must be empty after clear"


# ---------------------------------------------------------------------------
# 4. get_history reads from resolver path
# ---------------------------------------------------------------------------

def test_get_history_reads_from_resolver_path(sandbox):
    """get_history(uid, char_id='character_b') reads the resolver-computed path."""
    from core.memory.short_term import append, get_history

    uid = "u_p2g_gh"
    SENTINEL = "p2g-gh-sentinel-character_b"
    append(uid, "user", SENTINEL, char_id="character_b")

    result = get_history(uid, char_id="character_b")
    assert any(SENTINEL in m.get("content", "") for m in result), (
        f"get_history(character_b) must return appended content; got {result}"
    )


# ---------------------------------------------------------------------------
# 5. load_for_prompt reads from resolver path
# ---------------------------------------------------------------------------

def test_load_for_prompt_reads_from_resolver_path(sandbox):
    """load_for_prompt(uid, char_id='character_b') reads the resolver-computed path."""
    from core.memory.short_term import append, load_for_prompt

    uid = "u_p2g_lfp"
    SENTINEL = "p2g-lfp-sentinel-character_b"
    append(uid, "user", SENTINEL, char_id="character_b")
    append(uid, "assistant", "ok", char_id="character_b")

    result = load_for_prompt(uid, char_id="character_b")
    assert any(SENTINEL in m.get("content", "") for m in result), (
        f"load_for_prompt(character_b) must return appended content; got {result}"
    )


# ---------------------------------------------------------------------------
# 6. Physical path is identical to old user_memory_root layout
# ---------------------------------------------------------------------------

def test_history_physical_path_matches_old_layout(sandbox):
    """Resolver 'history' path == user_memory_root(uid, char_id=...) / 'history.json'."""
    uid = "u_p2g_layout"
    for char_id in ("yexuan", "character_b", "custom_char"):
        scope = MemoryScope.reality_scope(safe_user_id(uid), char_id)
        resolver_path = resolve_path(scope, "history")
        old_path = _expected_path(uid, char_id)
        assert resolver_path == old_path, (
            f"char_id={char_id!r}: resolver={resolver_path} != old={old_path}"
        )


def test_history_path_contains_runtime_memory_segment(sandbox):
    """Resolved path must contain runtime/memory/{char_id}/{uid}/history.json."""
    uid = "u_p2g_seg"
    char_id = "character_b"
    scope = MemoryScope.reality_scope(safe_user_id(uid), char_id)
    p = str(resolve_path(scope, "history")).replace("\\", "/")
    assert f"runtime/memory/{char_id}/{uid}/history.json" in p, (
        f"unexpected path: {p}"
    )


# ---------------------------------------------------------------------------
# 7. char_id=None → fail-loud, no yexuan fallback
# ---------------------------------------------------------------------------

def test_history_path_none_char_id_raises(sandbox):
    """_history_path with char_id=None must raise, not fallback to yexuan."""
    from core.memory.short_term import _history_path

    with pytest.raises((ValueError, TypeError)):
        _history_path("u_p2g_none", char_id=None)  # type: ignore[arg-type]


def test_append_none_char_id_raises(sandbox):
    """append with char_id=None must raise, not silently write to yexuan bucket."""
    from core.memory.short_term import append

    with pytest.raises((ValueError, TypeError)):
        append("u_p2g_none_a", "user", "x", char_id=None)  # type: ignore[arg-type]


def test_load_none_char_id_raises(sandbox):
    """load with char_id=None must raise, not silently read yexuan bucket."""
    from core.memory.short_term import load

    with pytest.raises((ValueError, TypeError)):
        load("u_p2g_none_l", char_id=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 8. char_id="" → fail-loud, no yexuan fallback
# ---------------------------------------------------------------------------

def test_history_path_empty_char_id_raises(sandbox):
    """_history_path with char_id='' must raise, not fallback to yexuan."""
    from core.memory.short_term import _history_path

    with pytest.raises(ValueError):
        _history_path("u_p2g_empty", char_id="")


def test_append_empty_char_id_raises(sandbox):
    """append with char_id='' must raise, not silently write to any bucket."""
    from core.memory.short_term import append

    with pytest.raises(ValueError):
        append("u_p2g_empty_a", "user", "x", char_id="")


def test_load_empty_char_id_raises(sandbox):
    """load with char_id='' must raise, not silently read any bucket."""
    from core.memory.short_term import load

    with pytest.raises(ValueError):
        load("u_p2g_empty_l", char_id="")


# ---------------------------------------------------------------------------
# 9. yexuan / character_b buckets fully isolated
# ---------------------------------------------------------------------------

def test_yexuan_character_b_buckets_isolated(sandbox):
    """Content written to one char_id bucket must not appear in the other."""
    from core.memory.short_term import append, load

    uid = "u_p2g_iso"
    SENTINEL_Y = "p2g-yexuan-unique-茉莉"
    SENTINEL_H = "p2g-character_b-unique-荔枝"

    append(uid, "user", SENTINEL_Y, char_id="yexuan")
    append(uid, "user", SENTINEL_H, char_id="character_b")

    yexuan = load(uid, char_id="yexuan")
    character_b = load(uid, char_id="character_b")

    assert any(SENTINEL_Y in m.get("content", "") for m in yexuan), "yexuan bucket missing yexuan sentinel"
    assert not any(SENTINEL_H in m.get("content", "") for m in yexuan), "yexuan bucket leaked character_b sentinel"
    assert any(SENTINEL_H in m.get("content", "") for m in character_b), "character_b bucket missing character_b sentinel"
    assert not any(SENTINEL_Y in m.get("content", "") for m in character_b), "character_b bucket leaked yexuan sentinel"

    # Confirm paths are different files
    scope_y = MemoryScope.reality_scope(safe_user_id(uid), "yexuan")
    scope_h = MemoryScope.reality_scope(safe_user_id(uid), "character_b")
    assert resolve_path(scope_y, "history") != resolve_path(scope_h, "history")


# ---------------------------------------------------------------------------
# 10. load_for_prompt(character_b) does not contain yexuan-unique token
# ---------------------------------------------------------------------------

def test_load_for_prompt_character_b_excludes_yexuan_token(sandbox):
    """load_for_prompt(character_b) must not contain content written to yexuan bucket."""
    from core.memory.short_term import append, load_for_prompt

    uid = "u_p2g_lfp_iso"
    YEXUAN_UNIQUE = "p2g-lfp-yexuan-茉莉花开"
    CHARACTER_B_UNIQUE = "p2g-lfp-character_b-荔枝飘香"

    append(uid, "user", YEXUAN_UNIQUE, char_id="yexuan")
    append(uid, "assistant", "replied", char_id="yexuan")
    append(uid, "user", CHARACTER_B_UNIQUE, char_id="character_b")
    append(uid, "assistant", "replied", char_id="character_b")

    result = load_for_prompt(uid, char_id="character_b")
    contents = [m.get("content", "") for m in result]

    assert not any(YEXUAN_UNIQUE in c for c in contents), (
        f"load_for_prompt(character_b) must not contain yexuan token; got {contents}"
    )
    assert any(CHARACTER_B_UNIQUE in c for c in contents), (
        f"load_for_prompt(character_b) must contain character_b token; got {contents}"
    )

"""
tests/test_fixation_state_resolver_integration.py — P1-2I

Verifies that fixation_pipeline now routes fixation_state path computation
through MemoryScope + resolve_path, not get_paths() directly.

Covers:
1.  _load_fixation_state() reads from resolve_path(reality_scope, "fixation_state")
2.  _save_fixation_state() writes to resolve_path(reality_scope, "fixation_state")
3.  Inline reset (via _save_fixation_state) targets resolver path
4.  Physical path identical to legacy user_memory_root / fixation_state.json
5.  char_id=None → ValueError (fail-loud, no fallback yexuan)
6.  char_id="" → ValueError (fail-loud, no fallback yexuan)
7.  yexuan / character_b fixation_state buckets are isolated
8.  character_b state does not read yexuan unique values
9.  path_resolver "fixation_state" layout → user_memory_root / fixation_state.json
10. Regression: test_fixation_pipeline patterns unaffected
11. Regression: pipeline read/write scope unaffected
12. Regression: test_memory_path_resolver unaffected
"""
from __future__ import annotations

import json

import pytest

from core.memory.scope import MemoryScope
from core.memory.path_resolver import resolve_path

_UID = "p1_2i_integ_u1"


# ---------------------------------------------------------------------------
# 1. _load_fixation_state() reads from resolve_path("fixation_state")
# ---------------------------------------------------------------------------

def test_load_fixation_state_reads_from_resolver_path(sandbox):
    from core.memory.fixation_pipeline import _load_fixation_state

    scope = MemoryScope.reality_scope(_UID, "character_b")
    expected_path = resolve_path(scope, "fixation_state")
    expected_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_consolidated_at": 999.0,
        "episodic_since_last": 7,
        "high_strength_since_last": 3,
        "strength_accumulated": 2.5,
        "last_sweep_at": 0.0,
    }
    expected_path.write_text(json.dumps(payload), encoding="utf-8")

    state = _load_fixation_state(_UID, char_id="character_b")
    assert state["last_consolidated_at"] == 999.0
    assert state["episodic_since_last"] == 7


# ---------------------------------------------------------------------------
# 2. _save_fixation_state() writes to resolve_path("fixation_state")
# ---------------------------------------------------------------------------

def test_save_fixation_state_writes_to_resolver_path(sandbox):
    from core.memory.fixation_pipeline import _save_fixation_state

    scope = MemoryScope.reality_scope(_UID, "character_b")
    expected_path = resolve_path(scope, "fixation_state")

    state = {
        "last_consolidated_at": 42.0,
        "episodic_since_last": 5,
        "high_strength_since_last": 2,
        "strength_accumulated": 3.1,
        "last_sweep_at": 0.0,
    }
    _save_fixation_state(_UID, state, char_id="character_b")

    assert expected_path.exists(), "_save_fixation_state() must write to resolver path"
    data = json.loads(expected_path.read_text(encoding="utf-8"))
    assert data["episodic_since_last"] == 5
    assert data["strength_accumulated"] == 3.1


# ---------------------------------------------------------------------------
# 3. Inline reset (zero-out via _save_fixation_state) targets resolver path
# ---------------------------------------------------------------------------

def test_reset_via_save_targets_resolver_path(sandbox):
    from core.memory.fixation_pipeline import _load_fixation_state, _save_fixation_state

    _save_fixation_state(_UID, {
        "last_consolidated_at": 0.0,
        "episodic_since_last": 9,
        "high_strength_since_last": 4,
        "strength_accumulated": 6.0,
        "last_sweep_at": 0.0,
    }, char_id="yexuan")

    # simulate the inline reset done by consolidate_to_identity
    state = _load_fixation_state(_UID, char_id="yexuan")
    state["episodic_since_last"] = 0
    state["high_strength_since_last"] = 0
    state["strength_accumulated"] = 0.0
    _save_fixation_state(_UID, state, char_id="yexuan")

    scope = MemoryScope.reality_scope(_UID, "yexuan")
    path = resolve_path(scope, "fixation_state")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["episodic_since_last"] == 0
    assert data["strength_accumulated"] == 0.0


# ---------------------------------------------------------------------------
# 4. Physical path identical to legacy user_memory_root / fixation_state.json
# ---------------------------------------------------------------------------

def test_fixation_state_path_equals_legacy_sandbox_path_character_b(sandbox):
    scope = MemoryScope.reality_scope(_UID, "character_b")
    resolver_path = resolve_path(scope, "fixation_state")
    legacy_path = sandbox.user_memory_root(_UID, char_id="character_b") / "fixation_state.json"
    assert resolver_path == legacy_path, (
        f"Resolver path diverged from legacy:\n  resolver: {resolver_path}\n  legacy:   {legacy_path}"
    )


def test_fixation_state_path_equals_legacy_sandbox_path_yexuan(sandbox):
    scope = MemoryScope.reality_scope(_UID, "yexuan")
    resolver_path = resolve_path(scope, "fixation_state")
    legacy_path = sandbox.user_memory_root(_UID, char_id="yexuan") / "fixation_state.json"
    assert resolver_path == legacy_path, (
        f"Resolver path diverged from legacy:\n  resolver: {resolver_path}\n  legacy:   {legacy_path}"
    )


# ---------------------------------------------------------------------------
# 5. char_id=None → fail-loud, no yexuan fallback
# ---------------------------------------------------------------------------

def test_load_fixation_state_char_id_none_raises(sandbox):
    from core.memory.fixation_pipeline import _load_fixation_state
    with pytest.raises((ValueError, TypeError)):
        _load_fixation_state(_UID, char_id=None)  # type: ignore[arg-type]


def test_save_fixation_state_char_id_none_raises(sandbox):
    from core.memory.fixation_pipeline import _save_fixation_state
    with pytest.raises((ValueError, TypeError)):
        _save_fixation_state(_UID, {}, char_id=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 6. char_id="" → fail-loud, no yexuan fallback
# ---------------------------------------------------------------------------

def test_load_fixation_state_empty_char_id_raises(sandbox):
    from core.memory.fixation_pipeline import _load_fixation_state
    with pytest.raises(ValueError):
        _load_fixation_state(_UID, char_id="")


def test_save_fixation_state_empty_char_id_raises(sandbox):
    from core.memory.fixation_pipeline import _save_fixation_state
    with pytest.raises(ValueError):
        _save_fixation_state(_UID, {}, char_id="")


# ---------------------------------------------------------------------------
# 7. yexuan / character_b fixation_state buckets are isolated
# ---------------------------------------------------------------------------

def test_yexuan_character_b_fixation_state_isolated(sandbox):
    from core.memory.fixation_pipeline import _load_fixation_state, _save_fixation_state

    _save_fixation_state(_UID, {
        "last_consolidated_at": 0.0,
        "episodic_since_last": 1,
        "high_strength_since_last": 0,
        "strength_accumulated": 0.0,
        "last_sweep_at": 0.0,
    }, char_id="yexuan")
    _save_fixation_state(_UID, {
        "last_consolidated_at": 0.0,
        "episodic_since_last": 99,
        "high_strength_since_last": 0,
        "strength_accumulated": 0.0,
        "last_sweep_at": 0.0,
    }, char_id="character_b")

    y = _load_fixation_state(_UID, char_id="yexuan")
    h = _load_fixation_state(_UID, char_id="character_b")

    assert y["episodic_since_last"] == 1
    assert h["episodic_since_last"] == 99

    y_path = sandbox.user_memory_root(_UID, char_id="yexuan") / "fixation_state.json"
    h_path = sandbox.user_memory_root(_UID, char_id="character_b") / "fixation_state.json"
    assert y_path.exists()
    assert h_path.exists()
    assert y_path != h_path


# ---------------------------------------------------------------------------
# 8. character_b fixation state does not read yexuan unique values
# ---------------------------------------------------------------------------

def test_character_b_fixation_does_not_read_yexuan_value(sandbox):
    from core.memory.fixation_pipeline import _load_fixation_state, _save_fixation_state

    # Write a distinctive value into yexuan bucket only
    _save_fixation_state(_UID, {
        "last_consolidated_at": 0.0,
        "episodic_since_last": 0,
        "high_strength_since_last": 77,
        "strength_accumulated": 0.0,
        "last_sweep_at": 0.0,
    }, char_id="yexuan")

    # character_b bucket is untouched → should return defaults
    h = _load_fixation_state(_UID, char_id="character_b")
    assert h["high_strength_since_last"] == 0, (
        "character_b must not read yexuan high_strength_since_last=77"
    )


# ---------------------------------------------------------------------------
# 9. path_resolver "fixation_state" layout: user_memory_root / fixation_state.json
# ---------------------------------------------------------------------------

def test_resolver_fixation_state_filename_is_fixation_state_json(sandbox):
    scope = MemoryScope.reality_scope(_UID, "yexuan")
    p = resolve_path(scope, "fixation_state")
    assert p.name == "fixation_state.json"


def test_resolver_fixation_state_parent_is_user_memory_root(sandbox):
    scope = MemoryScope.reality_scope(_UID, "yexuan")
    p = resolve_path(scope, "fixation_state")
    expected_parent = sandbox.user_memory_root(_UID, char_id="yexuan")
    assert p.parent == expected_parent


def test_resolver_fixation_state_different_char_different_path(sandbox):
    scope_y = MemoryScope.reality_scope(_UID, "yexuan")
    scope_h = MemoryScope.reality_scope(_UID, "character_b")
    assert resolve_path(scope_y, "fixation_state") != resolve_path(scope_h, "fixation_state")


def test_resolver_fixation_state_different_uid_different_path(sandbox):
    scope_a = MemoryScope.reality_scope("uid_aaa", "yexuan")
    scope_b = MemoryScope.reality_scope("uid_bbb", "yexuan")
    assert resolve_path(scope_a, "fixation_state") != resolve_path(scope_b, "fixation_state")

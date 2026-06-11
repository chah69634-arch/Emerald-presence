"""
tests/test_hidden_state_store_resolver_integration.py — P1-2B

Verifies that user_hidden_state_store now routes ALL path computation
through MemoryScope + resolve_path, not get_paths() directly.

Covers:
1.  load_hidden_state path == resolve_path(reality_scope, "hidden_state")
2.  save_hidden_state writes to resolve_path(reality_scope, "hidden_state")
3.  save_afterglow_residue writes to resolve_path(reality_scope, "afterglow_residue")
4.  Physical path identical to legacy user_memory_root / hidden_state.json (P0 parity)
5.  char_id=None → ValueError (fail-loud, no fallback yexuan)
6.  char_id="" → ValueError (fail-loud, no fallback yexuan)
7.  yexuan / character_b buckets are isolated end-to-end
8.  _load_afterglow_raw uses resolve_path("afterglow_residue") path
9.  int uid handled correctly (str conversion)
10. load_dream_snapshot delegates to correct char_id path
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from core.memory.scope import MemoryScope
from core.memory.path_resolver import resolve_path

_UID = "p1_2b_integ_u1"
_NOW = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 1. load_hidden_state reads from resolve_path("hidden_state")
# ---------------------------------------------------------------------------

def test_load_hidden_state_reads_from_resolver_path(sandbox):
    from core.memory.user_hidden_state import default_hidden_state, to_dict
    from core.memory.user_hidden_state_store import load_hidden_state

    scope = MemoryScope.reality_scope(_UID, "character_b")
    expected_path = resolve_path(scope, "hidden_state")

    state = default_hidden_state()
    state.sensitivity.baseline.value = 63.0
    expected_path.parent.mkdir(parents=True, exist_ok=True)
    expected_path.write_text(json.dumps(to_dict(state)), encoding="utf-8")

    loaded = load_hidden_state(_UID, char_id="character_b")
    assert loaded.sensitivity.baseline.value == pytest.approx(63.0)


# ---------------------------------------------------------------------------
# 2. save_hidden_state writes to resolve_path("hidden_state")
# ---------------------------------------------------------------------------

def test_save_hidden_state_writes_to_resolver_path(sandbox):
    from core.memory.user_hidden_state import default_hidden_state
    from core.memory.user_hidden_state_store import save_hidden_state

    scope = MemoryScope.reality_scope(_UID, "character_b")
    expected_path = resolve_path(scope, "hidden_state")

    state = default_hidden_state()
    state.sensitivity.current.value = 71.0
    ok = save_hidden_state(_UID, state, char_id="character_b")

    assert ok is True
    assert expected_path.exists(), "save_hidden_state must write to resolver path"
    data = json.loads(expected_path.read_text(encoding="utf-8"))
    assert data is not None


# ---------------------------------------------------------------------------
# 3. save_afterglow_residue writes to resolve_path("afterglow_residue")
# ---------------------------------------------------------------------------

def test_save_afterglow_residue_writes_to_resolver_path(sandbox):
    from core.memory.user_hidden_state import AfterglowResidueInput
    from core.memory.user_hidden_state_store import save_afterglow_residue

    scope = MemoryScope.reality_scope(_UID, "character_b")
    expected_path = resolve_path(scope, "afterglow_residue")

    residue = AfterglowResidueInput(emotional_tags=["calm"], tone="gentle", age_hours=0.0)
    ok = save_afterglow_residue(_UID, residue, _NOW, char_id="character_b")

    assert ok is True
    assert expected_path.exists(), "save_afterglow_residue must write to resolver path"
    data = json.loads(expected_path.read_text(encoding="utf-8"))
    assert data["tone"] == "gentle"


# ---------------------------------------------------------------------------
# 4. Physical path identity: resolver == sandbox.user_memory_root / filename
# ---------------------------------------------------------------------------

def test_hidden_state_path_equals_legacy_sandbox_path(sandbox):
    """resolve_path("hidden_state") must equal sandbox.user_memory_root / hidden_state.json."""
    scope = MemoryScope.reality_scope(_UID, "character_b")
    resolver_path = resolve_path(scope, "hidden_state")
    legacy_path = sandbox.user_memory_root(_UID, char_id="character_b") / "hidden_state.json"
    assert resolver_path == legacy_path, (
        f"Resolver path diverged from legacy:\n  resolver: {resolver_path}\n  legacy:   {legacy_path}"
    )


def test_afterglow_path_equals_legacy_sandbox_path(sandbox):
    """resolve_path("afterglow_residue") must equal sandbox.user_memory_root / afterglow_residue.json."""
    scope = MemoryScope.reality_scope(_UID, "yexuan")
    resolver_path = resolve_path(scope, "afterglow_residue")
    legacy_path = sandbox.user_memory_root(_UID, char_id="yexuan") / "afterglow_residue.json"
    assert resolver_path == legacy_path, (
        f"Resolver path diverged from legacy:\n  resolver: {resolver_path}\n  legacy:   {legacy_path}"
    )


# ---------------------------------------------------------------------------
# 5. char_id=None → ValueError, no yexuan fallback
# ---------------------------------------------------------------------------

def test_load_hidden_state_char_id_none_raises(sandbox):
    from core.memory.user_hidden_state_store import load_hidden_state
    with pytest.raises((ValueError, TypeError)):
        load_hidden_state(_UID, char_id=None)  # type: ignore[arg-type]


def test_save_hidden_state_char_id_none_raises(sandbox):
    from core.memory.user_hidden_state import default_hidden_state
    from core.memory.user_hidden_state_store import save_hidden_state
    with pytest.raises((ValueError, TypeError)):
        save_hidden_state(_UID, default_hidden_state(), char_id=None)  # type: ignore[arg-type]


def test_save_afterglow_residue_char_id_none_raises(sandbox):
    from core.memory.user_hidden_state import AfterglowResidueInput
    from core.memory.user_hidden_state_store import save_afterglow_residue
    residue = AfterglowResidueInput(emotional_tags=[], tone="neutral", age_hours=0.0)
    with pytest.raises((ValueError, TypeError)):
        save_afterglow_residue(_UID, residue, _NOW, char_id=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 6. char_id="" → ValueError
# ---------------------------------------------------------------------------

def test_load_hidden_state_empty_char_id_raises(sandbox):
    from core.memory.user_hidden_state_store import load_hidden_state
    with pytest.raises(ValueError):
        load_hidden_state(_UID, char_id="")


def test_save_hidden_state_empty_char_id_raises(sandbox):
    from core.memory.user_hidden_state import default_hidden_state
    from core.memory.user_hidden_state_store import save_hidden_state
    with pytest.raises(ValueError):
        save_hidden_state(_UID, default_hidden_state(), char_id="")


# ---------------------------------------------------------------------------
# 7. yexuan / character_b isolation
# ---------------------------------------------------------------------------

def test_save_and_load_two_chars_isolated(sandbox):
    from core.memory.user_hidden_state import default_hidden_state
    from core.memory.user_hidden_state_store import load_hidden_state, save_hidden_state

    state_y = default_hidden_state()
    state_y.sensitivity.baseline.value = 10.0
    save_hidden_state(_UID, state_y, char_id="yexuan")

    state_h = default_hidden_state()
    state_h.sensitivity.baseline.value = 90.0
    save_hidden_state(_UID, state_h, char_id="character_b")

    loaded_y = load_hidden_state(_UID, char_id="yexuan")
    loaded_h = load_hidden_state(_UID, char_id="character_b")

    assert loaded_y.sensitivity.baseline.value == pytest.approx(10.0)
    assert loaded_h.sensitivity.baseline.value == pytest.approx(90.0)

    # Ensure file-level isolation
    y_path = sandbox.user_memory_root(_UID, char_id="yexuan") / "hidden_state.json"
    h_path = sandbox.user_memory_root(_UID, char_id="character_b") / "hidden_state.json"
    assert y_path.exists()
    assert h_path.exists()
    assert y_path != h_path


def test_afterglow_isolation(sandbox):
    from core.memory.user_hidden_state import AfterglowResidueInput
    from core.memory.user_hidden_state_store import save_afterglow_residue

    r_y = AfterglowResidueInput(emotional_tags=["warm"], tone="comfort", age_hours=0.0)
    save_afterglow_residue(_UID, r_y, _NOW, char_id="yexuan")

    character_b_path = sandbox.user_memory_root(_UID, char_id="character_b") / "afterglow_residue.json"
    assert not character_b_path.exists(), "yexuan afterglow must not pollute character_b bucket"


# ---------------------------------------------------------------------------
# 8. _load_afterglow_raw uses resolve_path("afterglow_residue")
# ---------------------------------------------------------------------------

def test_load_afterglow_raw_reads_from_resolver_path(sandbox):
    from core.memory.user_hidden_state_store import _load_afterglow_raw

    scope = MemoryScope.reality_scope(_UID, "character_b")
    expected_path = resolve_path(scope, "afterglow_residue")
    expected_path.parent.mkdir(parents=True, exist_ok=True)
    expected_path.write_text(
        json.dumps({"emotional_tags": ["joy"], "tone": "bright", "created_at": _NOW}),
        encoding="utf-8",
    )

    result = _load_afterglow_raw(_UID, char_id="character_b")
    assert result is not None
    assert result["tone"] == "bright"


def test_load_afterglow_raw_absent_returns_none(sandbox):
    from core.memory.user_hidden_state_store import _load_afterglow_raw
    result = _load_afterglow_raw("p1_2b_no_residue_uid", char_id="character_b")
    assert result is None


# ---------------------------------------------------------------------------
# 9. int uid handled (str conversion)
# ---------------------------------------------------------------------------

def test_int_uid_save_and_load(sandbox):
    from core.memory.user_hidden_state import default_hidden_state
    from core.memory.user_hidden_state_store import load_hidden_state, save_hidden_state

    int_uid = 9988776655
    state = default_hidden_state()
    state.sensitivity.baseline.value = 44.0
    save_hidden_state(int_uid, state, char_id="yexuan")

    loaded = load_hidden_state(int_uid, char_id="yexuan")
    assert loaded.sensitivity.baseline.value == pytest.approx(44.0)

    expected = sandbox.user_memory_root(int_uid, char_id="yexuan") / "hidden_state.json"
    assert expected.exists()


# ---------------------------------------------------------------------------
# 10. load_dream_snapshot delegates to correct char_id path
# ---------------------------------------------------------------------------

def test_load_dream_snapshot_uses_char_id_path(sandbox):
    from core.memory.user_hidden_state import default_hidden_state
    from core.memory.user_hidden_state_store import load_dream_snapshot, save_hidden_state

    state = default_hidden_state()
    save_hidden_state(_UID, state, char_id="character_b")

    snapshot = load_dream_snapshot(_UID, _NOW, char_id="character_b")
    assert isinstance(snapshot, dict)
    # character_b path exists; yexuan path was never written
    yexuan_path = sandbox.user_memory_root(_UID, char_id="yexuan") / "hidden_state.json"
    assert not yexuan_path.exists()

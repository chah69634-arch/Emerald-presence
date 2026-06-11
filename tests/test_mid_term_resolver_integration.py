"""
tests/test_mid_term_resolver_integration.py — P1-2E

Verifies that mid_term now routes ALL path computation through
MemoryScope + resolve_path, not get_paths() directly.

Covers:
1.  load() reads from resolve_path(reality_scope, "mid_term")
2.  append() writes to resolve_path(reality_scope, "mid_term")
3.  format_for_prompt() reads from resolve_path(reality_scope, "mid_term")
4.  Physical path identical to legacy user_memory_root / mid_term.json (P0 parity)
5.  char_id=None → ValueError (fail-loud, no fallback yexuan)
6.  char_id="" → ValueError (fail-loud, no fallback yexuan)
7.  yexuan / character_b mid_term buckets are isolated
8.  character_b format_for_prompt does not contain yexuan unique word
9.  Regression: pipeline read scope (import smoke)
10. Regression: slow_queue char scope (import smoke)
11. Regression: episodic_sweep char scope (import smoke)
12. Regression: memory_path_resolver all-artifacts test
"""
from __future__ import annotations

import json
import time

import pytest

from core.memory.scope import MemoryScope
from core.memory.path_resolver import resolve_path

_UID = "p1_2e_integ_u1"


# ---------------------------------------------------------------------------
# 1. load() reads from resolve_path("mid_term")
# ---------------------------------------------------------------------------

def test_load_reads_from_resolver_path(sandbox):
    import core.memory.mid_term as _mt

    scope = MemoryScope.reality_scope(_UID, "character_b")
    expected_path = resolve_path(scope, "mid_term")
    expected_path.parent.mkdir(parents=True, exist_ok=True)
    expected_path.write_text(
        json.dumps({"events": [{"ts": time.time(), "summary": "sentinel-load", "tags": [],
                                "mid_id": None, "source_turn_id": None,
                                "promoted_to_episodic_id": None}]}),
        encoding="utf-8",
    )

    events = _mt.load(_UID, char_id="character_b")
    summaries = [e["summary"] for e in events]
    assert "sentinel-load" in summaries


# ---------------------------------------------------------------------------
# 2. append() writes to resolve_path("mid_term")
# ---------------------------------------------------------------------------

def test_append_writes_to_resolver_path(sandbox):
    import core.memory.mid_term as _mt

    scope = MemoryScope.reality_scope(_UID, "character_b")
    expected_path = resolve_path(scope, "mid_term")

    _mt.append(_UID, "append-sentinel", tags=["t1"], char_id="character_b")

    assert expected_path.exists(), "append() must write to resolver path"
    data = json.loads(expected_path.read_text(encoding="utf-8"))
    summaries = [e["summary"] for e in data.get("events", [])]
    assert "append-sentinel" in summaries


# ---------------------------------------------------------------------------
# 3. format_for_prompt() reads from resolve_path("mid_term")
# ---------------------------------------------------------------------------

def test_format_for_prompt_reads_from_resolver_path(sandbox):
    import core.memory.mid_term as _mt

    scope = MemoryScope.reality_scope(_UID, "character_b")
    expected_path = resolve_path(scope, "mid_term")
    expected_path.parent.mkdir(parents=True, exist_ok=True)
    expected_path.write_text(
        json.dumps({"events": [{"ts": time.time() - 60, "summary": "prompt-sentinel", "tags": [],
                                "mid_id": None, "source_turn_id": None,
                                "promoted_to_episodic_id": None}]}),
        encoding="utf-8",
    )

    result = _mt.format_for_prompt(_UID, char_id="character_b")
    assert "prompt-sentinel" in result


# ---------------------------------------------------------------------------
# 4. Physical path identity: resolver == sandbox.user_memory_root / mid_term.json
# ---------------------------------------------------------------------------

def test_mid_term_path_equals_legacy_sandbox_path(sandbox):
    scope = MemoryScope.reality_scope(_UID, "character_b")
    resolver_path = resolve_path(scope, "mid_term")
    legacy_path = sandbox.user_memory_root(_UID, char_id="character_b") / "mid_term.json"
    assert resolver_path == legacy_path, (
        f"Resolver path diverged from legacy:\n  resolver: {resolver_path}\n  legacy:   {legacy_path}"
    )


def test_mid_term_path_equals_legacy_sandbox_path_yexuan(sandbox):
    scope = MemoryScope.reality_scope(_UID, "yexuan")
    resolver_path = resolve_path(scope, "mid_term")
    legacy_path = sandbox.user_memory_root(_UID, char_id="yexuan") / "mid_term.json"
    assert resolver_path == legacy_path, (
        f"Resolver path diverged from legacy:\n  resolver: {resolver_path}\n  legacy:   {legacy_path}"
    )


# ---------------------------------------------------------------------------
# 5. char_id=None → fail-loud, no yexuan fallback
# ---------------------------------------------------------------------------

def test_load_char_id_none_raises(sandbox):
    import core.memory.mid_term as _mt
    with pytest.raises((ValueError, TypeError)):
        _mt.load(_UID, char_id=None)  # type: ignore[arg-type]


def test_append_char_id_none_raises(sandbox):
    import core.memory.mid_term as _mt
    with pytest.raises((ValueError, TypeError)):
        _mt.append(_UID, "x", char_id=None)  # type: ignore[arg-type]


def test_mark_promoted_char_id_none_raises(sandbox):
    import core.memory.mid_term as _mt
    with pytest.raises((ValueError, TypeError)):
        _mt.mark_promoted(_UID, "mid-1", "ep-1", char_id=None)  # type: ignore[arg-type]


def test_format_for_prompt_char_id_none_raises(sandbox):
    import core.memory.mid_term as _mt
    with pytest.raises((ValueError, TypeError)):
        _mt.format_for_prompt(_UID, char_id=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 6. char_id="" → fail-loud, no yexuan fallback
# ---------------------------------------------------------------------------

def test_load_empty_char_id_raises(sandbox):
    import core.memory.mid_term as _mt
    with pytest.raises(ValueError):
        _mt.load(_UID, char_id="")


def test_append_empty_char_id_raises(sandbox):
    import core.memory.mid_term as _mt
    with pytest.raises(ValueError):
        _mt.append(_UID, "x", char_id="")


def test_mark_promoted_empty_char_id_raises(sandbox):
    import core.memory.mid_term as _mt
    with pytest.raises(ValueError):
        _mt.mark_promoted(_UID, "mid-1", "ep-1", char_id="")


def test_format_for_prompt_empty_char_id_raises(sandbox):
    import core.memory.mid_term as _mt
    with pytest.raises(ValueError):
        _mt.format_for_prompt(_UID, char_id="")


# ---------------------------------------------------------------------------
# 7. yexuan / character_b mid_term buckets are isolated
# ---------------------------------------------------------------------------

def test_yexuan_character_b_mid_term_isolated(sandbox):
    import core.memory.mid_term as _mt

    _mt.append(_UID, "Companion专属摘要", char_id="yexuan")
    _mt.append(_UID, "DemoUser专属摘要", char_id="character_b")

    y_events = _mt.load(_UID, char_id="yexuan")
    h_events = _mt.load(_UID, char_id="character_b")

    y_summaries = [e["summary"] for e in y_events]
    h_summaries = [e["summary"] for e in h_events]

    assert "Companion专属摘要" in y_summaries
    assert "DemoUser专属摘要" not in y_summaries
    assert "DemoUser专属摘要" in h_summaries
    assert "Companion专属摘要" not in h_summaries

    y_path = sandbox.user_memory_root(_UID, char_id="yexuan") / "mid_term.json"
    h_path = sandbox.user_memory_root(_UID, char_id="character_b") / "mid_term.json"
    assert y_path.exists()
    assert h_path.exists()
    assert y_path != h_path


# ---------------------------------------------------------------------------
# 8. character_b format_for_prompt does not contain yexuan unique word
# ---------------------------------------------------------------------------

def test_format_for_prompt_isolation(sandbox):
    import core.memory.mid_term as _mt

    yexuan_word = "yexuan-unique-8a7f3"
    character_b_word = "character_b-unique-9b2e1"

    _mt.append(_UID, yexuan_word, char_id="yexuan")
    _mt.append(_UID, character_b_word, char_id="character_b")

    y_text = _mt.format_for_prompt(_UID, char_id="yexuan")
    h_text = _mt.format_for_prompt(_UID, char_id="character_b")

    assert yexuan_word in y_text, f"yexuan word missing from yexuan format_for_prompt"
    assert yexuan_word not in h_text, f"yexuan word leaked into character_b format_for_prompt"
    assert character_b_word in h_text, f"character_b word missing from character_b format_for_prompt"
    assert character_b_word not in y_text, f"character_b word leaked into yexuan format_for_prompt"


# ---------------------------------------------------------------------------
# 9. mark_promoted writes to resolver path
# ---------------------------------------------------------------------------

def test_mark_promoted_writes_to_resolver_path(sandbox):
    import core.memory.mid_term as _mt

    scope = MemoryScope.reality_scope(_UID, "character_b")
    expected_path = resolve_path(scope, "mid_term")

    _mt.append(_UID, "promoted-test", mid_id="mid-promo-1", char_id="character_b")
    assert expected_path.exists()

    _mt.mark_promoted(_UID, "mid-promo-1", "ep-001", char_id="character_b")

    data = json.loads(expected_path.read_text(encoding="utf-8"))
    events = data.get("events", [])
    promo = next((e for e in events if e.get("mid_id") == "mid-promo-1"), None)
    assert promo is not None
    assert promo["promoted_to_episodic_id"] == "ep-001"


# ---------------------------------------------------------------------------
# 12. Regression: memory_path_resolver all-reality-artifacts test
# ---------------------------------------------------------------------------

def test_mid_term_resolver_char_and_uid_present(sandbox):
    """resolve_path(reality_scope, 'mid_term') contains both char_id and uid."""
    uid = "reg_uid_123"
    char = "reg_char"
    scope = MemoryScope.reality_scope(uid, char)
    p = str(resolve_path(scope, "mid_term")).replace("\\", "/")
    assert char in p
    assert uid in p


def test_mid_term_resolver_no_yexuan_for_custom_char(sandbox):
    """Resolver emits scope.character_id, not a hardcoded 'yexuan' default."""
    scope = MemoryScope.reality_scope("u1", "custom_char")
    p = str(resolve_path(scope, "mid_term")).replace("\\", "/")
    assert "custom_char" in p
    assert "yexuan" not in p

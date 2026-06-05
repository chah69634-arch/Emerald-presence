"""Unit tests for core/memory/scope.py — MemoryScope dataclass."""

import pytest

from core.memory.scope import MemoryScope


# ---------------------------------------------------------------------------
# global scope
# ---------------------------------------------------------------------------

def test_global_scope_valid():
    s = MemoryScope(uid="u1", domain="global")
    assert s.uid == "u1"
    assert s.domain == "global"
    assert s.character_id is None
    assert s.world_id is None


def test_global_scope_constructor():
    s = MemoryScope.global_scope("u1")
    assert s.domain == "global"
    assert s.character_id is None
    assert s.world_id is None


def test_global_scope_with_character_id_raises():
    with pytest.raises(ValueError, match="character_id"):
        MemoryScope(uid="u1", domain="global", character_id="char1")


def test_global_scope_with_world_id_raises():
    with pytest.raises(ValueError, match="world_id"):
        MemoryScope(uid="u1", domain="global", world_id="w1")


# ---------------------------------------------------------------------------
# reality scope
# ---------------------------------------------------------------------------

def test_reality_scope_valid():
    s = MemoryScope(uid="u1", domain="reality", character_id="char1")
    assert s.uid == "u1"
    assert s.domain == "reality"
    assert s.character_id == "char1"
    assert s.world_id is None


def test_reality_scope_constructor():
    s = MemoryScope.reality_scope("u1", "char1")
    assert s.domain == "reality"
    assert s.character_id == "char1"
    assert s.world_id is None


def test_reality_scope_missing_character_id_raises():
    with pytest.raises(ValueError, match="character_id"):
        MemoryScope(uid="u1", domain="reality")


def test_reality_scope_empty_character_id_raises():
    with pytest.raises(ValueError, match="character_id"):
        MemoryScope(uid="u1", domain="reality", character_id="")


def test_reality_scope_with_world_id_raises():
    with pytest.raises(ValueError, match="world_id"):
        MemoryScope(uid="u1", domain="reality", character_id="char1", world_id="w1")


# ---------------------------------------------------------------------------
# dream scope
# ---------------------------------------------------------------------------

def test_dream_scope_valid():
    s = MemoryScope(uid="u1", domain="dream", character_id="char1", world_id="w1")
    assert s.uid == "u1"
    assert s.domain == "dream"
    assert s.character_id == "char1"
    assert s.world_id == "w1"


def test_dream_scope_constructor():
    s = MemoryScope.dream_scope("u1", "char1", "w1")
    assert s.domain == "dream"
    assert s.character_id == "char1"
    assert s.world_id == "w1"


def test_dream_scope_missing_character_id_raises():
    with pytest.raises(ValueError, match="character_id"):
        MemoryScope(uid="u1", domain="dream", world_id="w1")


def test_dream_scope_empty_character_id_raises():
    with pytest.raises(ValueError, match="character_id"):
        MemoryScope(uid="u1", domain="dream", character_id="", world_id="w1")


def test_dream_scope_missing_world_id_raises():
    with pytest.raises(ValueError, match="world_id"):
        MemoryScope(uid="u1", domain="dream", character_id="char1")


def test_dream_scope_empty_world_id_raises():
    with pytest.raises(ValueError, match="world_id"):
        MemoryScope(uid="u1", domain="dream", character_id="char1", world_id="")


# ---------------------------------------------------------------------------
# uid / domain validation
# ---------------------------------------------------------------------------

def test_empty_uid_raises():
    with pytest.raises(ValueError, match="uid"):
        MemoryScope(uid="", domain="global")


def test_non_string_uid_raises():
    with pytest.raises(ValueError, match="uid"):
        MemoryScope(uid=123, domain="global")  # type: ignore[arg-type]


def test_none_uid_raises():
    with pytest.raises(ValueError, match="uid"):
        MemoryScope(uid=None, domain="global")  # type: ignore[arg-type]


def test_invalid_domain_raises():
    with pytest.raises(ValueError, match="domain"):
        MemoryScope(uid="u1", domain="unknown")  # type: ignore[arg-type]


def test_invalid_domain_case_sensitive_raises():
    with pytest.raises(ValueError, match="domain"):
        MemoryScope(uid="u1", domain="Global")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# frozen (immutable)
# ---------------------------------------------------------------------------

def test_frozen_cannot_set_uid():
    s = MemoryScope.global_scope("u1")
    with pytest.raises((AttributeError, TypeError)):
        s.uid = "u2"  # type: ignore[misc]


def test_frozen_cannot_set_domain():
    s = MemoryScope.global_scope("u1")
    with pytest.raises((AttributeError, TypeError)):
        s.domain = "reality"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# to_payload / from_payload roundtrip
# ---------------------------------------------------------------------------

def test_roundtrip_global():
    s = MemoryScope.global_scope("u1")
    payload = s.to_payload()
    assert payload == {"uid": "u1", "domain": "global", "character_id": None, "world_id": None}
    assert MemoryScope.from_payload(payload) == s


def test_roundtrip_reality():
    s = MemoryScope.reality_scope("u1", "char1")
    payload = s.to_payload()
    assert payload == {"uid": "u1", "domain": "reality", "character_id": "char1", "world_id": None}
    assert MemoryScope.from_payload(payload) == s


def test_roundtrip_dream():
    s = MemoryScope.dream_scope("u1", "char1", "w1")
    payload = s.to_payload()
    assert payload == {"uid": "u1", "domain": "dream", "character_id": "char1", "world_id": "w1"}
    assert MemoryScope.from_payload(payload) == s


def test_to_payload_is_json_serializable():
    import json
    for scope in (
        MemoryScope.global_scope("u1"),
        MemoryScope.reality_scope("u1", "char1"),
        MemoryScope.dream_scope("u1", "char1", "w1"),
    ):
        json.dumps(scope.to_payload())  # must not raise


# ---------------------------------------------------------------------------
# from_payload validation
# ---------------------------------------------------------------------------

def test_from_payload_missing_uid_raises():
    with pytest.raises(ValueError, match="uid"):
        MemoryScope.from_payload({"domain": "global"})


def test_from_payload_missing_domain_raises():
    with pytest.raises(ValueError, match="domain"):
        MemoryScope.from_payload({"uid": "u1"})


def test_from_payload_non_dict_raises():
    with pytest.raises(TypeError):
        MemoryScope.from_payload("not a dict")  # type: ignore[arg-type]


def test_from_payload_bad_domain_raises():
    with pytest.raises(ValueError):
        MemoryScope.from_payload({"uid": "u1", "domain": "invalid"})


def test_from_payload_no_yexuan_fallback():
    """from_payload must not silently inject a default character_id."""
    payload = {"uid": "u1", "domain": "reality"}  # character_id absent
    with pytest.raises(ValueError, match="character_id"):
        MemoryScope.from_payload(payload)


def test_from_payload_no_yexuan_fallback_dream():
    """from_payload must not silently inject a default character_id for dream."""
    payload = {"uid": "u1", "domain": "dream", "world_id": "w1"}
    with pytest.raises(ValueError, match="character_id"):
        MemoryScope.from_payload(payload)


# ---------------------------------------------------------------------------
# import / circular dependency smoke test
# ---------------------------------------------------------------------------

def test_import_does_not_raise():
    import importlib
    importlib.import_module("core.memory.scope")


def test_equality_and_hash():
    a = MemoryScope.reality_scope("u1", "char1")
    b = MemoryScope.reality_scope("u1", "char1")
    c = MemoryScope.reality_scope("u1", "char2")
    assert a == b
    assert a != c
    assert hash(a) == hash(b)
    assert hash(a) != hash(c)
    # usable as dict key / set element
    d = {a: "found"}
    assert d[b] == "found"

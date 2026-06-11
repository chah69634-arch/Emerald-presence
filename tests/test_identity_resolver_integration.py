"""
tests/test_identity_resolver_integration.py — P1-2D

Verifies that user_identity now routes ALL path computation through
MemoryScope + resolve_path, not get_paths() directly.

Covers:
1.  load() reads from resolve_path(reality_scope, "identity")
2.  save() writes to resolve_path(reality_scope, "identity")
3.  format_for_prompt() reads from resolve_path(reality_scope, "identity")
4.  Physical path identical to legacy user_memory_root / identity.yaml (P0 parity)
5.  .bak backup path consistent with original logic
6.  char_id=None → ValueError (fail-loud, no fallback yexuan)
7.  char_id="" → ValueError (fail-loud, no fallback yexuan)
8.  yexuan / character_b identity buckets are isolated
9.  format_for_prompt reads character_b bucket, not yexuan bucket
"""
from __future__ import annotations

import pytest
import yaml

from core.memory.scope import MemoryScope
from core.memory.path_resolver import resolve_path

_UID = "p1_2d_integ_u1"

_CHARACTER_B_DIM = {
    "trust_pattern": {
        "text": "DemoUser-专属-信任模式",
        "confidence": 0.8,
        "evidence_count": 5,
        "last_updated": "2026-06-01T00:00:00",
    }
}

_YEXUAN_DIM = {
    "trust_pattern": {
        "text": "Companion-专属-信任模式",
        "confidence": 0.9,
        "evidence_count": 8,
        "last_updated": "2026-06-01T00:00:00",
    }
}


# ---------------------------------------------------------------------------
# 1. load() reads from resolve_path("identity")
# ---------------------------------------------------------------------------

async def test_load_identity_reads_from_resolver_path(sandbox):
    import core.memory.user_identity as _ui

    scope = MemoryScope.reality_scope(_UID, "character_b")
    expected_path = resolve_path(scope, "identity")
    expected_path.parent.mkdir(parents=True, exist_ok=True)
    expected_path.write_text(
        yaml.dump(_CHARACTER_B_DIM, allow_unicode=True),
        encoding="utf-8",
    )

    result = await _ui.load(_UID, char_id="character_b")
    assert "trust_pattern" in result
    assert result["trust_pattern"]["text"] == "DemoUser-专属-信任模式"


# ---------------------------------------------------------------------------
# 2. save() writes to resolve_path("identity")
# ---------------------------------------------------------------------------

async def test_save_identity_writes_to_resolver_path(sandbox):
    import core.memory.user_identity as _ui

    scope = MemoryScope.reality_scope(_UID, "character_b")
    expected_path = resolve_path(scope, "identity")

    ok = await _ui.save(_UID, _CHARACTER_B_DIM, char_id="character_b")

    assert ok is True
    assert expected_path.exists(), "save() must write to resolver path"
    raw = yaml.safe_load(expected_path.read_text(encoding="utf-8")) or {}
    assert raw["trust_pattern"]["text"] == "DemoUser-专属-信任模式"


# ---------------------------------------------------------------------------
# 3. format_for_prompt() reads from resolver path
# ---------------------------------------------------------------------------

async def test_format_for_prompt_reads_from_resolver_path(sandbox):
    import core.memory.user_identity as _ui

    scope = MemoryScope.reality_scope(_UID, "character_b")
    expected_path = resolve_path(scope, "identity")
    expected_path.parent.mkdir(parents=True, exist_ok=True)
    expected_path.write_text(
        yaml.dump(_CHARACTER_B_DIM, allow_unicode=True),
        encoding="utf-8",
    )

    result = await _ui.format_for_prompt(_UID, char_id="character_b")
    assert "DemoUser-专属-信任模式" in result


# ---------------------------------------------------------------------------
# 4. Physical path: resolver == sandbox.user_memory_root / identity.yaml
# ---------------------------------------------------------------------------

def test_identity_path_equals_legacy_sandbox_path_character_b(sandbox):
    scope = MemoryScope.reality_scope(_UID, "character_b")
    resolver_path = resolve_path(scope, "identity")
    legacy_path = sandbox.user_memory_root(_UID, char_id="character_b") / "identity.yaml"
    assert resolver_path == legacy_path, (
        f"Resolver path diverged from legacy:\n  resolver: {resolver_path}\n  legacy:   {legacy_path}"
    )


def test_identity_path_equals_legacy_sandbox_path_yexuan(sandbox):
    scope = MemoryScope.reality_scope(_UID, "yexuan")
    resolver_path = resolve_path(scope, "identity")
    legacy_path = sandbox.user_memory_root(_UID, char_id="yexuan") / "identity.yaml"
    assert resolver_path == legacy_path, (
        f"Resolver path diverged from legacy:\n  resolver: {resolver_path}\n  legacy:   {legacy_path}"
    )


# ---------------------------------------------------------------------------
# 5. .bak backup path consistent with original logic
# ---------------------------------------------------------------------------

async def test_save_creates_bak_at_correct_path(sandbox):
    import core.memory.user_identity as _ui

    scope = MemoryScope.reality_scope(_UID, "character_b")
    identity_path = resolve_path(scope, "identity")
    expected_bak = identity_path.parent / (identity_path.name + ".bak")

    # first save creates the file
    await _ui.save(_UID, _CHARACTER_B_DIM, char_id="character_b")
    assert not expected_bak.exists(), ".bak must not exist before second save"

    # second save triggers backup of existing file
    dim2 = dict(_CHARACTER_B_DIM)
    dim2["trust_pattern"] = {**_CHARACTER_B_DIM["trust_pattern"], "text": "DemoUser-更新-信任模式"}
    await _ui.save(_UID, dim2, char_id="character_b")

    assert expected_bak.exists(), ".bak must exist after overwriting an existing identity file"
    bak_raw = yaml.safe_load(expected_bak.read_text(encoding="utf-8")) or {}
    assert bak_raw["trust_pattern"]["text"] == "DemoUser-专属-信任模式", ".bak must contain previous content"


# ---------------------------------------------------------------------------
# 6. char_id=None → fail-loud, no yexuan fallback
# ---------------------------------------------------------------------------

async def test_load_identity_char_id_none_raises(sandbox):
    import core.memory.user_identity as _ui
    with pytest.raises((ValueError, TypeError)):
        await _ui.load(_UID, char_id=None)  # type: ignore[arg-type]


async def test_save_identity_char_id_none_raises(sandbox):
    import core.memory.user_identity as _ui
    with pytest.raises((ValueError, TypeError)):
        await _ui.save(_UID, _CHARACTER_B_DIM, char_id=None)  # type: ignore[arg-type]


async def test_format_for_prompt_char_id_none_raises(sandbox):
    import core.memory.user_identity as _ui
    with pytest.raises((ValueError, TypeError)):
        await _ui.format_for_prompt(_UID, char_id=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 7. char_id="" → fail-loud, no yexuan fallback
# ---------------------------------------------------------------------------

async def test_load_identity_empty_char_id_raises(sandbox):
    import core.memory.user_identity as _ui
    with pytest.raises(ValueError):
        await _ui.load(_UID, char_id="")


async def test_save_identity_empty_char_id_raises(sandbox):
    import core.memory.user_identity as _ui
    with pytest.raises(ValueError):
        await _ui.save(_UID, _CHARACTER_B_DIM, char_id="")


# ---------------------------------------------------------------------------
# 8. yexuan / character_b identity buckets are isolated
# ---------------------------------------------------------------------------

async def test_yexuan_character_b_identity_isolated(sandbox):
    import core.memory.user_identity as _ui

    await _ui.save(_UID, _YEXUAN_DIM, char_id="yexuan")
    await _ui.save(_UID, _CHARACTER_B_DIM, char_id="character_b")

    y = await _ui.load(_UID, char_id="yexuan")
    h = await _ui.load(_UID, char_id="character_b")

    assert y["trust_pattern"]["text"] == "Companion-专属-信任模式"
    assert h["trust_pattern"]["text"] == "DemoUser-专属-信任模式"

    y_path = sandbox.user_memory_root(_UID, char_id="yexuan") / "identity.yaml"
    h_path = sandbox.user_memory_root(_UID, char_id="character_b") / "identity.yaml"
    assert y_path.exists()
    assert h_path.exists()
    assert y_path != h_path


async def test_save_character_b_does_not_pollute_yexuan_bucket(sandbox):
    import core.memory.user_identity as _ui

    await _ui.save(_UID, _CHARACTER_B_DIM, char_id="character_b")

    yexuan_path = sandbox.user_memory_root(_UID, char_id="yexuan") / "identity.yaml"
    assert not yexuan_path.exists(), "writing character_b identity must not create yexuan bucket file"


# ---------------------------------------------------------------------------
# 9. format_for_prompt reads character_b bucket, not yexuan bucket
# ---------------------------------------------------------------------------

async def test_format_for_prompt_character_b_no_yexuan_text(sandbox):
    import core.memory.user_identity as _ui

    await _ui.save(_UID, _YEXUAN_DIM, char_id="yexuan")
    await _ui.save(_UID, _CHARACTER_B_DIM, char_id="character_b")

    h_text = await _ui.format_for_prompt(_UID, char_id="character_b")
    y_text = await _ui.format_for_prompt(_UID, char_id="yexuan")

    assert "DemoUser-专属-信任模式" in h_text
    assert "Companion-专属-信任模式" not in h_text
    assert "Companion-专属-信任模式" in y_text
    assert "DemoUser-专属-信任模式" not in y_text

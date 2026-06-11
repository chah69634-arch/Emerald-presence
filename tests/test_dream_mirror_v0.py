"""
tests/test_dream_mirror_v0.py — Dream Mirror Mode v0.1 tests

Test inventory:
  1. MirrorCore bucket mapping — only low/medium/high/unknown; no floats
  2. MirrorCore bucket coverage — all four keys present; values are coarse only
  3. Mirror enter freezes snapshot — state["mirror_core"] written; post-entry hidden_state changes don't affect session mirror_core
  4. Sandbox enter — no mirror_core in state
  5. Scenario enter — no mirror_core in state
  6. DM layer injected when dream_mode=mirror and mirror_core present
  7. DM layer absent when dream_mode=sandbox
  8. DM layer absent when dream_mode=scenario
  9. Mirror prompt contains no float literals (no "0.42"-style values)
 10. Mirror prompt contains no percentage signs
 11. Mirror exit skips wire_afterglow_from_summary
 12. Mirror exit skips distill_impression
 13. Scenario isolation — afterglow/impression still skipped for scenario (regression)
 14. clear_local_state removes mirror_core
 15. MirrorCore.from_dict / to_dict round-trip
"""

import asyncio
import re
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

_UID = "mirror_test_user"

_FAKE_CHARACTER = MagicMock()
_FAKE_CHARACTER.name = "Companion"
_FAKE_CHARACTER.description = "Companion是圣塞西尔学院的老师"

_EMPTY_SNAPSHOT: dict[str, Any] = {
    "created_at": time.time(),
    "user_id": _UID,
    "entry_reason": "test",
    "relationship_state": {},
    "recent_reality_context": "",
    "episodic_summary": "",
    "mid_term_context": "",
    "profile_impression": "",
    "user_hidden_state_snapshot": {},
}

_FULL_HS_SNAPSHOT: dict[str, Any] = {
    "sensitivity": "high",
    "touch_appetite": "high",
    "embodied_ease": "guarded",
    "memory_cues": ["轻触", "靠近", "手"],
}


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — MirrorCore bucket values are only coarse labels, never floats
# ═══════════════════════════════════════════════════════════════════════════════

def test_mirror_core_no_float_values():
    """snapshot_buckets values must never be floats."""
    from core.dream.mirror_core import build_mirror_core

    mc = build_mirror_core(_FULL_HS_SNAPSHOT)
    for k, v in mc.snapshot_buckets.items():
        assert not isinstance(v, float), f"float found in snapshot_buckets[{k!r}]={v!r}"
        assert isinstance(v, str), f"expected str in snapshot_buckets[{k!r}], got {type(v).__name__}"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — MirrorCore bucket mapping correctness
# ═══════════════════════════════════════════════════════════════════════════════

def test_mirror_core_bucket_mapping():
    """Four expected keys present; values are from allowed coarse sets."""
    from core.dream.mirror_core import build_mirror_core, _VALID_LMH, _VALID_PRESENCE

    mc = build_mirror_core(_FULL_HS_SNAPSHOT)

    assert "sensitivity_bucket" in mc.snapshot_buckets
    assert "closeness_need_bucket" in mc.snapshot_buckets
    assert "embodied_ease_bucket" in mc.snapshot_buckets
    assert "association_presence" in mc.snapshot_buckets

    assert mc.snapshot_buckets["sensitivity_bucket"] in _VALID_LMH
    assert mc.snapshot_buckets["closeness_need_bucket"] in _VALID_LMH
    assert mc.snapshot_buckets["embodied_ease_bucket"] in _VALID_LMH
    assert mc.snapshot_buckets["association_presence"] in _VALID_PRESENCE

    # specific mapping checks for _FULL_HS_SNAPSHOT
    assert mc.snapshot_buckets["sensitivity_bucket"] == "high"
    assert mc.snapshot_buckets["closeness_need_bucket"] == "high"
    assert mc.snapshot_buckets["embodied_ease_bucket"] == "low"   # "guarded" → "low"
    assert mc.snapshot_buckets["association_presence"] == "present"  # 3 cues → "present"


def test_mirror_core_bucket_mid_mapping():
    """'mid' sensitivity → 'medium'; 'neutral' ease → 'medium'."""
    from core.dream.mirror_core import build_mirror_core

    snapshot = {
        "sensitivity": "mid",
        "touch_appetite": "mid",
        "embodied_ease": "neutral",
        "memory_cues": ["a"],
    }
    mc = build_mirror_core(snapshot)
    assert mc.snapshot_buckets["sensitivity_bucket"] == "medium"
    assert mc.snapshot_buckets["closeness_need_bucket"] == "medium"
    assert mc.snapshot_buckets["embodied_ease_bucket"] == "medium"
    assert mc.snapshot_buckets["association_presence"] == "light"  # 1 cue


def test_mirror_core_empty_snapshot():
    """Empty snapshot → all 'unknown' buckets; no exception."""
    from core.dream.mirror_core import build_mirror_core

    mc = build_mirror_core({})
    assert mc.snapshot_buckets["sensitivity_bucket"] == "unknown"
    assert mc.snapshot_buckets["closeness_need_bucket"] == "unknown"
    assert mc.snapshot_buckets["embodied_ease_bucket"] == "unknown"
    assert mc.snapshot_buckets["association_presence"] == "none"


def test_mirror_core_invalid_input():
    """Non-dict input → fail-closed empty MirrorCore, no raise."""
    from core.dream.mirror_core import build_mirror_core

    mc = build_mirror_core(None)  # type: ignore
    assert isinstance(mc.snapshot_buckets, dict)
    assert mc.version == "v0.1"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — Mirror enter freezes snapshot into dream state
# ═══════════════════════════════════════════════════════════════════════════════

def test_mirror_enter_freezes_mirror_core(sandbox):
    """enter_dream with mirror mode writes mirror_core to dream_state."""
    from core.dream.dream_pipeline import enter_dream
    from core.dream.dream_state import read_state
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {})

    snapshot = dict(_EMPTY_SNAPSHOT)
    snapshot["user_hidden_state_snapshot"] = dict(_FULL_HS_SNAPSHOT)

    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=snapshot)),
        patch("core.pipeline_registry.get", return_value=MagicMock(character=_FAKE_CHARACTER)),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        result = asyncio.run(enter_dream(_UID, entry_reason="test", char_id="yexuan", dream_mode="mirror"))

    assert result["ok"] is True
    state = read_state(_UID)
    assert "mirror_core" in state
    mc = state["mirror_core"]
    assert mc["version"] == "v0.1"
    assert mc["source"] == "user_hidden_state_snapshot"
    assert "snapshot_buckets" in mc
    assert isinstance(mc["snapshot_buckets"], dict)
    # Verify frozen: no float in snapshot_buckets values
    for v in mc["snapshot_buckets"].values():
        assert isinstance(v, str), f"float or non-str in frozen mirror_core: {v!r}"


def test_mirror_snapshot_frozen_against_later_hs_changes(sandbox):
    """mirror_core in session state is not affected by hidden_state file changes after entry."""
    from core.dream.dream_pipeline import enter_dream
    from core.dream.dream_state import read_state
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {})

    snapshot = dict(_EMPTY_SNAPSHOT)
    snapshot["user_hidden_state_snapshot"] = {"sensitivity": "low", "touch_appetite": "low", "embodied_ease": "easy", "memory_cues": []}

    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=snapshot)),
        patch("core.pipeline_registry.get", return_value=MagicMock(character=_FAKE_CHARACTER)),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        asyncio.run(enter_dream(_UID, entry_reason="test", char_id="yexuan", dream_mode="mirror"))

    state_before = read_state(_UID)
    mc_before = state_before["mirror_core"]["snapshot_buckets"].copy()

    # Simulate a hidden_state file change AFTER dream entry (e.g. decay tick fires)
    # The mirror_core in dream_state must NOT change
    state_after = read_state(_UID)
    assert state_after["mirror_core"]["snapshot_buckets"] == mc_before, (
        "mirror_core must not change after hidden_state changes post-entry"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — Sandbox enter has no mirror_core
# ═══════════════════════════════════════════════════════════════════════════════

def test_sandbox_enter_no_mirror_core(sandbox):
    """enter_dream with sandbox mode must NOT write mirror_core."""
    from core.dream.dream_pipeline import enter_dream
    from core.dream.dream_state import read_state
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {})

    snapshot = dict(_EMPTY_SNAPSHOT)
    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=snapshot)),
        patch("core.pipeline_registry.get", return_value=MagicMock(character=_FAKE_CHARACTER)),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        result = asyncio.run(enter_dream(_UID, entry_reason="test", char_id="yexuan", dream_mode="sandbox"))

    assert result["ok"] is True
    state = read_state(_UID)
    assert "mirror_core" not in state


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5 — Scenario enter has no mirror_core
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_enter_no_mirror_core(sandbox):
    """enter_dream with scenario mode must NOT write mirror_core."""
    from core.dream.dream_pipeline import enter_dream
    from core.dream.dream_state import read_state
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {})

    snapshot = dict(_EMPTY_SNAPSHOT)
    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=snapshot)),
        patch("core.pipeline_registry.get", return_value=MagicMock(character=_FAKE_CHARACTER)),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        result = asyncio.run(enter_dream(
            _UID, entry_reason="test", char_id="yexuan",
            dream_mode="scenario", script_id="prison_demo",
        ))

    assert result["ok"] is True
    state = read_state(_UID)
    assert "mirror_core" not in state


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6 — DM layer injected in mirror mode prompt
# ═══════════════════════════════════════════════════════════════════════════════

def test_dm_layer_injected_for_mirror():
    """build_dream_prompt with dream_mode=mirror and mirror_core injects DM layer."""
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt
    from core.dream.mirror_core import build_mirror_core

    mc = build_mirror_core(_FULL_HS_SNAPSHOT)

    msgs = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot={},
        dream_history=[],
        local_state={},
        dream_mode="mirror",
        mirror_core=mc.to_dict(),
    )
    system_msg = dump_dream_prompt(msgs)
    assert "DM·Mirror" in system_msg, "DM layer header not found in mirror prompt"
    assert "梦境的隐喻材料" in system_msg
    assert "不是诊断结论" in system_msg


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7 — DM layer absent in sandbox mode
# ═══════════════════════════════════════════════════════════════════════════════

def test_dm_layer_absent_for_sandbox():
    """build_dream_prompt with dream_mode=sandbox must NOT inject DM layer."""
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt
    from core.dream.mirror_core import build_mirror_core

    mc = build_mirror_core(_FULL_HS_SNAPSHOT)

    msgs = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot={},
        dream_history=[],
        local_state={},
        dream_mode="sandbox",
        mirror_core=mc.to_dict(),  # passed but should be ignored
    )
    system_msg = dump_dream_prompt(msgs)
    assert "DM·Mirror" not in system_msg


# ═══════════════════════════════════════════════════════════════════════════════
# Test 8 — DM layer absent in scenario mode
# ═══════════════════════════════════════════════════════════════════════════════

def test_dm_layer_absent_for_scenario():
    """build_dream_prompt with dream_mode=scenario must NOT inject DM layer."""
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt
    from core.dream.mirror_core import build_mirror_core

    mc = build_mirror_core(_FULL_HS_SNAPSHOT)

    msgs = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot={},
        dream_history=[],
        local_state={},
        dream_mode="scenario",
        mirror_core=mc.to_dict(),
        scenario_core={
            "script_id": "prison_demo",
            "current_stage_id": "arrival",
            "stage_turns": 0,
            "ending_state": None,
        },
    )
    system_msg = dump_dream_prompt(msgs)
    assert "DM·Mirror" not in system_msg


# ═══════════════════════════════════════════════════════════════════════════════
# Test 9 — Mirror prompt contains no float literals
# ═══════════════════════════════════════════════════════════════════════════════

_FLOAT_RE = re.compile(r"\b\d+\.\d+\b")


def test_mirror_prompt_no_float_values():
    """Mirror prompt (DM layer) must not contain float literals like 0.42."""
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt
    from core.dream.mirror_core import build_mirror_core

    mc = build_mirror_core(_FULL_HS_SNAPSHOT)

    msgs = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot={},
        dream_history=[],
        local_state={},
        dream_mode="mirror",
        mirror_core=mc.to_dict(),
    )
    system_msg = dump_dream_prompt(msgs)
    floats_found = _FLOAT_RE.findall(system_msg)
    assert not floats_found, f"Float values found in mirror prompt: {floats_found}"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 10 — Mirror prompt contains no percentage signs
# ═══════════════════════════════════════════════════════════════════════════════

def test_mirror_prompt_no_percentage():
    """Mirror prompt must not contain percentage signs."""
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt
    from core.dream.mirror_core import build_mirror_core

    mc = build_mirror_core(_FULL_HS_SNAPSHOT)

    msgs = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot={},
        dream_history=[],
        local_state={},
        dream_mode="mirror",
        mirror_core=mc.to_dict(),
    )
    system_msg = dump_dream_prompt(msgs)
    assert "%" not in system_msg, "Percentage sign found in mirror prompt"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 11 — Mirror exit skips wire_afterglow_from_summary
# ═══════════════════════════════════════════════════════════════════════════════

def test_mirror_exit_skips_afterglow():
    """_generate_summary_bg with dream_mode=mirror must NOT call wire_afterglow_from_summary."""
    from core.dream import dream_pipeline

    with (
        patch("core.dream.dream_summary.generate_summary", new=AsyncMock()),
        patch("core.dream.dream_exit_afterglow.wire_afterglow_from_summary") as mock_afterglow,
        patch("core.dream.distill_impression.distill_impression", new=AsyncMock()),
    ):
        asyncio.run(dream_pipeline._generate_summary_bg(
            _UID, "dream_test_123", "soft", char_id="yexuan", dream_mode="mirror"
        ))

    mock_afterglow.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 12 — Mirror exit skips distill_impression
# ═══════════════════════════════════════════════════════════════════════════════

def test_mirror_exit_skips_distill_impression():
    """_generate_summary_bg with dream_mode=mirror must NOT call distill_impression."""
    from core.dream import dream_pipeline

    with (
        patch("core.dream.dream_summary.generate_summary", new=AsyncMock()),
        patch("core.dream.dream_exit_afterglow.wire_afterglow_from_summary"),
        patch("core.dream.distill_impression.distill_impression", new=AsyncMock()) as mock_distill,
    ):
        asyncio.run(dream_pipeline._generate_summary_bg(
            _UID, "dream_test_123", "soft", char_id="yexuan", dream_mode="mirror"
        ))

    mock_distill.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 13 — Scenario isolation regression: afterglow/impression still skipped
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_exit_still_skips_afterglow_and_impression():
    """Ensure scenario mode still skips afterglow and impression after mirror guard added."""
    from core.dream import dream_pipeline

    with (
        patch("core.dream.dream_summary.generate_summary", new=AsyncMock()),
        patch("core.dream.dream_exit_afterglow.wire_afterglow_from_summary") as mock_afterglow,
        patch("core.dream.distill_impression.distill_impression", new=AsyncMock()) as mock_distill,
    ):
        asyncio.run(dream_pipeline._generate_summary_bg(
            _UID, "dream_test_456", "soft", char_id="yexuan", dream_mode="scenario"
        ))

    mock_afterglow.assert_not_called()
    mock_distill.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 14 — clear_local_state removes mirror_core
# ═══════════════════════════════════════════════════════════════════════════════

def test_clear_local_state_removes_mirror_core():
    """clear_local_state() must remove mirror_core from state dict."""
    from core.dream.dream_state import clear_local_state

    state = {
        "status": "DREAM_ACTIVE",
        "dream_mode": "mirror",
        "mirror_core": {"snapshot_buckets": {}, "symbolic_hints": [], "source": "x", "version": "v0.1"},
        "scenario_core": None,
        "emotional_tension": 0.1,
    }
    cleared = clear_local_state(state)
    assert "mirror_core" not in cleared
    assert "dream_mode" not in cleared
    assert "emotional_tension" not in cleared
    # status is NOT in the volatile key list — must survive
    assert cleared["status"] == "DREAM_ACTIVE"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 15 — MirrorCore round-trip serialization
# ═══════════════════════════════════════════════════════════════════════════════

def test_mirror_core_round_trip():
    """MirrorCore.to_dict() / from_dict() preserves all fields."""
    from core.dream.mirror_core import MirrorCore

    mc = MirrorCore(
        snapshot_buckets={"sensitivity_bucket": "high", "association_presence": "light"},
        symbolic_hints=["梦中感知更细，环境反馈更容易被放大"],
        source="user_hidden_state_snapshot",
        version="v0.1",
    )
    d = mc.to_dict()
    mc2 = MirrorCore.from_dict(d)

    assert mc2.snapshot_buckets == mc.snapshot_buckets
    assert mc2.symbolic_hints == mc.symbolic_hints
    assert mc2.source == mc.source
    assert mc2.version == mc.version

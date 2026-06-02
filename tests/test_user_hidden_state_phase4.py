"""
tests/test_user_hidden_state_phase4.py
=======================================
Phase 4 — Dream Snapshot read-only context injection.

Tests cover:
  A  tag gate                      (4)   TG-01–TG-04
  B  snapshot content guarantees   (6)   SC-01–SC-06
  C  prompt layer priority         (4)   PL-01–PL-04
  D  fail-closed paths             (4)   FC-01–FC-04
  E  write isolation               (5)   WI-01–WI-05
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from core.dream.dream_prompt import (
    _HIDDEN_STATE_TRIGGER_TAGS,
    _collect_scene_tags,
    _format_hidden_state_snapshot,
    _should_inject_hidden_state_snapshot,
    build_dream_prompt,
)
from core.memory.user_hidden_state import (
    BodyMemory,
    BodyMemoryEntry,
    default_hidden_state,
    to_dream_snapshot,
)

# ─────────────────────────────────────────────────────────────────────────────
# Shared fixtures / constants
# ─────────────────────────────────────────────────────────────────────────────

NOW = "2026-06-03T00:00:00Z"

_FAKE_CHARACTER = MagicMock()
_FAKE_CHARACTER.name = "叶瑄"
_FAKE_CHARACTER.description = "叶瑄是圣塞西尔学院的老师"

_NEUTRAL_SNAPSHOT: dict[str, Any] = {
    "sensitivity": "mid",
    "touch_appetite": "mid",
    "embodied_ease": "neutral",
    "memory_cues": [],
}

_HIGH_SNAPSHOT: dict[str, Any] = {
    "sensitivity": "high",
    "touch_appetite": "high",
    "embodied_ease": "easy",
    "memory_cues": ["voice_low", "quiet_room"],
}


def _make_context_snapshot(hs_data: dict[str, Any] | None = None) -> dict[str, Any]:
    snap: dict[str, Any] = {
        "created_at": 0.0,
        "user_id": "p4_test_user",
        "yexuan_awareness": "lucid_shared",
        "boundary": "dream_only",
        "entry_reason": "test",
        "memory_access": "relationship_summary",
        "relationship_state": {},
        "recent_reality_context": "",
        "episodic_summary": "",
        "mid_term_context": "",
        "profile_impression": "",
    }
    if hs_data is not None:
        snap["user_hidden_state_snapshot"] = hs_data
    return snap


def _make_local_state(scene_state: str | None = None, anchors: list[str] | None = None) -> dict[str, Any]:
    return {
        "emotional_tension": 0.0,
        "scene_state": scene_state,
        "symbolic_anchors": anchors or [],
        "body_state": {},
    }


def _build_prompt_with_state(
    context_snapshot: dict[str, Any],
    local_state: dict[str, Any],
) -> list[dict[str, str]]:
    """Call build_dream_prompt with minimal required params."""
    return build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id="p4_test_user",
        user_message="测试消息",
        context_snapshot=context_snapshot,
        dream_history=[],
        local_state=local_state,
        jailbreak_text="",
        body_projection_text="",
        yexuan_tension=0.0,
        world_id="reality_derived",
        lucid_mode="lucid_shared",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# A. Tag gate
# ═══════════════════════════════════════════════════════════════════════════════

class TestTagGate:
    """TG-01–TG-04: tag gate correctly enables / disables injection."""

    def test_TG01_no_tag_returns_false(self):
        """TG-01: no matching tag → gate returns False."""
        local = _make_local_state(scene_state="stable")
        ctx = _make_context_snapshot()
        assert _should_inject_hidden_state_snapshot(local, ctx) is False

    def test_TG02_body_intimate_triggers(self):
        """TG-02: scene_state = body_intimate → gate returns True."""
        local = _make_local_state(scene_state="body_intimate")
        ctx = _make_context_snapshot()
        assert _should_inject_hidden_state_snapshot(local, ctx) is True

    def test_TG03_physical_closeness_triggers(self):
        """TG-03: scene_state = physical_closeness → gate returns True."""
        local = _make_local_state(scene_state="physical_closeness")
        ctx = _make_context_snapshot()
        assert _should_inject_hidden_state_snapshot(local, ctx) is True

    def test_TG04_gate_exception_returns_false(self):
        """TG-04: tag collection raises → gate returns False (fail-closed)."""
        with patch(
            "core.dream.dream_prompt._collect_scene_tags",
            side_effect=RuntimeError("tag explosion"),
        ):
            result = _should_inject_hidden_state_snapshot({}, {})
        assert result is False


# ═══════════════════════════════════════════════════════════════════════════════
# B. Snapshot content guarantees
# ═══════════════════════════════════════════════════════════════════════════════

class TestSnapshotContentGuarantees:
    """SC-01–SC-06: formatted output contains only allowed fields, no sensitive data."""

    def test_SC01_no_float_values(self):
        """SC-01: formatted snapshot never contains float values."""
        state = default_hidden_state()
        state.sensitivity.current.value = 77.5
        state.touch_need.deficit.value = 82.0
        state.embodied_ease.value = 30.0
        snap = to_dream_snapshot(state, NOW)
        text = _format_hidden_state_snapshot(snap)
        assert text, "should produce non-empty output"
        for token in text.split():
            try:
                float(token.rstrip(","))
                pytest.fail(f"float found in output: {token!r}")
            except ValueError:
                pass  # expected — no floats

    def test_SC02_no_uid_in_output(self):
        """SC-02: formatted snapshot never contains uid."""
        snap = dict(_HIGH_SNAPSHOT)
        text = _format_hidden_state_snapshot(snap)
        assert "p4_test_user" not in text
        assert "uid" not in text.lower()

    def test_SC03_no_timestamp_in_output(self):
        """SC-03: formatted snapshot never contains timestamps."""
        snap = dict(_HIGH_SNAPSHOT)
        text = _format_hidden_state_snapshot(snap)
        assert "last_updated" not in text
        assert "2026" not in text

    def test_SC04_no_weight_in_output(self):
        """SC-04: formatted snapshot never contains raw body_memory weights."""
        state = default_hidden_state()
        state.body_memory.entries = [
            BodyMemoryEntry(cue="warm_touch", response_tag="relax", weight=0.85,
                            created_at=NOW, last_reinforced=NOW),
        ]
        snap = to_dream_snapshot(state, NOW)
        text = _format_hidden_state_snapshot(snap)
        assert "0.85" not in text
        assert "weight" not in text.lower()

    def test_SC05_empty_memory_cues_no_cues_line(self):
        """SC-05: memory_cues=[] → no memory_cues line in output."""
        snap = dict(_NEUTRAL_SNAPSHOT)
        snap["memory_cues"] = []
        text = _format_hidden_state_snapshot(snap)
        assert text, "should still produce output for non-cue fields"
        assert "memory_cues" not in text

    def test_SC06_nonempty_cues_appear(self):
        """SC-06 (positive control): non-empty cues appear in output."""
        snap = dict(_HIGH_SNAPSHOT)
        text = _format_hidden_state_snapshot(snap)
        assert "memory_cues:" in text
        assert "voice_low" in text
        assert "quiet_room" in text


# ═══════════════════════════════════════════════════════════════════════════════
# C. Prompt layer priority
# ═══════════════════════════════════════════════════════════════════════════════

class TestPromptLayerPriority:
    """PL-01–PL-04: layer naming, ordering, and pruning position."""

    def test_PL01_layer_marker_name(self):
        """PL-01: formatted snapshot starts with [user_hidden_state_snapshot] marker."""
        text = _format_hidden_state_snapshot(_NEUTRAL_SNAPSHOT)
        assert text.startswith("[user_hidden_state_snapshot]")

    def test_PL02_d45_disabled_when_no_tag(self):
        """PL-02: no trigger tag → D4.5 layer is DISABLED in records log."""
        ctx = _make_context_snapshot(_NEUTRAL_SNAPSHOT)
        local = _make_local_state(scene_state="stable")
        messages = _build_prompt_with_state(ctx, local)
        system_content = messages[0]["content"]
        # D4.5 section must not appear in system message
        assert "D4.5" not in system_content
        assert "user_hidden_state_snapshot" not in system_content

    def test_PL03_d45_injected_when_tag_present(self):
        """PL-03: trigger tag present → D4.5 content appears in system message."""
        ctx = _make_context_snapshot(_HIGH_SNAPSHOT)
        local = _make_local_state(scene_state="body_intimate")
        messages = _build_prompt_with_state(ctx, local)
        system_content = messages[0]["content"]
        assert "D4.5" in system_content
        assert "user_hidden_state_snapshot" in system_content
        assert "sensitivity: high" in system_content

    def test_PL04_d45_appears_after_d4_in_system(self):
        """PL-04: D4.5 section appears after D4 section in system content (lower priority)."""
        ctx = _make_context_snapshot(_HIGH_SNAPSHOT)
        ctx["recent_reality_context"] = "some reality context"
        local = _make_local_state(scene_state="physical_closeness")
        messages = _build_prompt_with_state(ctx, local)
        system_content = messages[0]["content"]
        d4_pos = system_content.find("D4·")
        d45_pos = system_content.find("D4.5·")
        assert d4_pos != -1, "D4 must appear in system content"
        assert d45_pos != -1, "D4.5 must appear in system content when tag present"
        assert d45_pos > d4_pos, "D4.5 must come after D4 (lower priority)"


# ═══════════════════════════════════════════════════════════════════════════════
# D. Fail-closed paths
# ═══════════════════════════════════════════════════════════════════════════════

class TestFailClosed:
    """FC-01–FC-04: any failure in snapshot loading/formatting never blocks Dream."""

    def test_FC01_empty_snapshot_dict_not_injected(self):
        """FC-01: empty snapshot dict (e.g. load failure) → no injection."""
        ctx = _make_context_snapshot({})          # empty hidden state
        local = _make_local_state(scene_state="body_intimate")
        messages = _build_prompt_with_state(ctx, local)
        system_content = messages[0]["content"]
        assert "D4.5·" not in system_content
        assert "user_hidden_state_snapshot" not in system_content

    def test_FC02_malformed_snapshot_missing_key_not_injected(self):
        """FC-02: snapshot missing required key → no injection."""
        bad_snap = {"sensitivity": "mid"}          # missing touch_appetite + embodied_ease
        ctx = _make_context_snapshot(bad_snap)
        local = _make_local_state(scene_state="body_intimate")
        messages = _build_prompt_with_state(ctx, local)
        system_content = messages[0]["content"]
        assert "D4.5·" not in system_content

    def test_FC03_snapshot_with_float_value_not_injected(self):
        """FC-03: snapshot with float value (malformed) → formatter returns '' → not injected."""
        bad_snap = {
            "sensitivity": 0.7,           # float, not str — malformed
            "touch_appetite": "mid",
            "embodied_ease": "neutral",
            "memory_cues": [],
        }
        result = _format_hidden_state_snapshot(bad_snap)
        assert result == "", "formatter must return '' for non-str bucket value"

    def test_FC04_dream_prompt_builds_without_snapshot(self):
        """FC-04: Dream prompt builds normally even when snapshot key is absent."""
        ctx = _make_context_snapshot()  # no user_hidden_state_snapshot key
        local = _make_local_state(scene_state="stable")
        messages = _build_prompt_with_state(ctx, local)
        assert len(messages) >= 2
        system = messages[0]
        assert system["role"] == "system"
        assert system["content"]


# ═══════════════════════════════════════════════════════════════════════════════
# E. Write isolation
# ═══════════════════════════════════════════════════════════════════════════════

class TestWriteIsolation:
    """WI-01–WI-05: Dream context path calls no hidden-state write functions."""

    _FORBIDDEN_WRITE_NAMES = [
        "save_hidden_state",
        "integrate_event",
        "integrate_impression",
        "integrate_body_cue",
        "integrate_event_and_save",
        "integrate_impression_and_save",
        "integrate_body_cue_and_save",
        "apply_time_decay",
        "consolidate_baselines",
    ]

    def test_WI01_dream_prompt_module_does_not_import_write_functions(self):
        """WI-01: dream_prompt module does not directly import any write function."""
        import core.dream.dream_prompt as _dpm
        source = _dpm.__file__
        with open(source, encoding="utf-8") as f:
            text = f.read()
        for name in self._FORBIDDEN_WRITE_NAMES:
            assert name not in text, (
                f"dream_prompt.py must not reference write function: {name}"
            )

    def test_WI02_dream_context_module_does_not_import_write_functions(self):
        """WI-02: dream_context module does not directly import any write function."""
        import core.dream.dream_context as _dmc
        source = _dmc.__file__
        with open(source, encoding="utf-8") as f:
            text = f.read()
        for name in self._FORBIDDEN_WRITE_NAMES:
            assert name not in text, (
                f"dream_context.py must not reference write function: {name}"
            )

    def test_WI03_build_snapshot_calls_no_hidden_state_save(self, monkeypatch):
        """WI-03: build_snapshot() does not call save_hidden_state."""
        calls: list[str] = []

        def _fake_save(*a, **kw):
            calls.append("save_hidden_state")
            return True

        monkeypatch.setattr(
            "core.memory.user_hidden_state_store.save_hidden_state", _fake_save
        )

        import asyncio
        import core.dream.dream_context as _dmc
        asyncio.run(_dmc.build_snapshot("wi_test_uid", entry_reason="test"))
        assert not calls, f"save_hidden_state must not be called: {calls}"

    def test_WI04_build_dream_prompt_calls_no_hidden_state_save(self, monkeypatch):
        """WI-04: build_dream_prompt() does not call save_hidden_state."""
        calls: list[str] = []

        def _fake_save(*a, **kw):
            calls.append("save_hidden_state")
            return True

        monkeypatch.setattr(
            "core.memory.user_hidden_state_store.save_hidden_state", _fake_save
        )

        ctx = _make_context_snapshot(_HIGH_SNAPSHOT)
        local = _make_local_state(scene_state="body_intimate")
        _build_prompt_with_state(ctx, local)
        assert not calls, f"save_hidden_state must not be called: {calls}"

    def test_WI05_dream_direct_writable_is_empty(self):
        """WI-05: DREAM_DIRECT_WRITABLE frozenset is empty — no field writable from Dream."""
        from core.memory.user_hidden_state import DREAM_DIRECT_WRITABLE
        assert DREAM_DIRECT_WRITABLE == frozenset(), (
            "DREAM_DIRECT_WRITABLE must be empty — Dream cannot write any hidden-state field"
        )

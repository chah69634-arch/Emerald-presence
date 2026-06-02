"""
tests/test_user_hidden_state_phase2.py
=======================================
Phase 2 MVP — to_dream_snapshot / integrate_*_and_save / load_dream_snapshot

Verification checklist:
  A. to_dream_snapshot — bucket mapping
      1.  sensitivity.current < 35  → "low"
      2.  sensitivity.current = 50  → "mid"
      3.  sensitivity.current > 65  → "high"
      4.  boundary: current = 35    → "mid"
      5.  boundary: current = 65    → "mid"
      6.  touch_need.deficit < 35   → touch_appetite "low"
      7.  touch_need.deficit = 50   → touch_appetite "mid"
      8.  touch_need.deficit > 65   → touch_appetite "high"
      9.  embodied_ease < 35        → "guarded"
      10. embodied_ease = 50        → "neutral"
      11. embodied_ease > 65        → "easy"

  B. to_dream_snapshot — memory_cues
      12. empty body_memory → []
      13. entries sorted by weight descending; top-5 returned
      14. entries with empty cue string filtered out

  C. to_dream_snapshot — security / read-only guarantees
      15. state object is NOT mutated
      16. output contains no float values (all strings or lists of strings)
      17. snapshot keys match exact expected shape
      18. long-term baseline values are absent from output
      19. snapshot is a new dict (not a reference to state internals)

  D. integrate_event_and_save — disk wiring
      20. event accepted + open envelope → state written to disk
      21. loaded state after save has updated touch_need.deficit
      22. rejected envelope → disk NOT written
      23. long-term fields unchanged after save round-trip

  E. integrate_impression_and_save — disk wiring
      24. impression accepted → state written to disk
      25. loaded state after save has updated sensitivity.current
      26. rejected impression (no envelope) → disk NOT written
      27. out-of-gate weight → disk NOT written

  F. load_dream_snapshot — end-to-end read
      28. returns dict with exact expected keys
      29. missing file → returns neutral bucket snapshot (no raise)
      30. output values are strings / list-of-strings (no raw floats)
      31. modifying snapshot dict does not affect persisted state
"""
from __future__ import annotations

import pytest

from core.memory.user_hidden_state import (
    BodyMemory,
    BodyMemoryEntry,
    DREAM_GATE_MAX,
    DREAM_GATE_MIN,
    SCALAR_CENTER,
    ImpressionInput,
    UpdateSource,
    default_hidden_state,
    to_dream_snapshot,
)
from core.memory.user_hidden_state_integrator import (
    RealityEventType,
    integrate_event_and_save,
    integrate_impression_and_save,
)
from core.memory.user_hidden_state_store import (
    HIDDEN_STATE_FILENAME,
    load_dream_snapshot,
    load_hidden_state,
    save_hidden_state,
)
from core.write_envelope import WriteEnvelope, stamp_user_chat

NOW = "2026-06-02T00:00:00Z"
TEST_UID = "user_p2_test"

_EXPECTED_KEYS = frozenset({"sensitivity", "touch_appetite", "embodied_ease", "memory_cues"})


def _open_envelope() -> WriteEnvelope:
    return stamp_user_chat()


# ═══════════════════════════════════════════════════════════════════════════════
# A. to_dream_snapshot — bucket mapping
# ═══════════════════════════════════════════════════════════════════════════════

class TestToDreamSnapshotBuckets:
    def test_sensitivity_low(self):
        state = default_hidden_state()
        state.sensitivity.current.value = 20.0
        snap = to_dream_snapshot(state, NOW)
        assert snap["sensitivity"] == "low"

    def test_sensitivity_mid(self):
        state = default_hidden_state()
        state.sensitivity.current.value = 50.0
        snap = to_dream_snapshot(state, NOW)
        assert snap["sensitivity"] == "mid"

    def test_sensitivity_high(self):
        state = default_hidden_state()
        state.sensitivity.current.value = 80.0
        snap = to_dream_snapshot(state, NOW)
        assert snap["sensitivity"] == "high"

    def test_sensitivity_boundary_35_is_mid(self):
        state = default_hidden_state()
        state.sensitivity.current.value = 35.0
        snap = to_dream_snapshot(state, NOW)
        assert snap["sensitivity"] == "mid"

    def test_sensitivity_boundary_65_is_mid(self):
        state = default_hidden_state()
        state.sensitivity.current.value = 65.0
        snap = to_dream_snapshot(state, NOW)
        assert snap["sensitivity"] == "mid"

    def test_touch_appetite_low(self):
        state = default_hidden_state()
        state.touch_need.deficit.value = 10.0
        snap = to_dream_snapshot(state, NOW)
        assert snap["touch_appetite"] == "low"

    def test_touch_appetite_mid(self):
        state = default_hidden_state()
        state.touch_need.deficit.value = 50.0
        snap = to_dream_snapshot(state, NOW)
        assert snap["touch_appetite"] == "mid"

    def test_touch_appetite_high(self):
        state = default_hidden_state()
        state.touch_need.deficit.value = 90.0
        snap = to_dream_snapshot(state, NOW)
        assert snap["touch_appetite"] == "high"

    def test_embodied_ease_guarded(self):
        state = default_hidden_state()
        state.embodied_ease.value = 20.0
        snap = to_dream_snapshot(state, NOW)
        assert snap["embodied_ease"] == "guarded"

    def test_embodied_ease_neutral(self):
        state = default_hidden_state()
        state.embodied_ease.value = SCALAR_CENTER
        snap = to_dream_snapshot(state, NOW)
        assert snap["embodied_ease"] == "neutral"

    def test_embodied_ease_easy(self):
        state = default_hidden_state()
        state.embodied_ease.value = 80.0
        snap = to_dream_snapshot(state, NOW)
        assert snap["embodied_ease"] == "easy"


# ═══════════════════════════════════════════════════════════════════════════════
# B. to_dream_snapshot — memory_cues
# ═══════════════════════════════════════════════════════════════════════════════

class TestToDreamSnapshotMemoryCues:
    def test_empty_body_memory_returns_empty_list(self):
        state = default_hidden_state()
        snap = to_dream_snapshot(state, NOW)
        assert snap["memory_cues"] == []

    def test_cues_sorted_by_weight_descending(self):
        state = default_hidden_state()
        state.body_memory = BodyMemory(
            entries=[
                BodyMemoryEntry(cue="c", weight=0.3, response_tag="r", created_at=NOW, last_reinforced=NOW),
                BodyMemoryEntry(cue="a", weight=0.9, response_tag="r", created_at=NOW, last_reinforced=NOW),
                BodyMemoryEntry(cue="b", weight=0.6, response_tag="r", created_at=NOW, last_reinforced=NOW),
            ],
            max_entries=32,
        )
        snap = to_dream_snapshot(state, NOW)
        assert snap["memory_cues"] == ["a", "b", "c"]

    def test_top_5_cues_returned(self):
        state = default_hidden_state()
        state.body_memory = BodyMemory(
            entries=[
                BodyMemoryEntry(cue=f"cue_{i}", weight=float(i) / 10, response_tag="r",
                                created_at=NOW, last_reinforced=NOW)
                for i in range(10, 0, -1)
            ],
            max_entries=32,
        )
        snap = to_dream_snapshot(state, NOW)
        assert len(snap["memory_cues"]) == 5
        assert snap["memory_cues"][0] == "cue_10"

    def test_empty_cue_strings_filtered_out(self):
        state = default_hidden_state()
        state.body_memory = BodyMemory(
            entries=[
                BodyMemoryEntry(cue="", weight=0.9, response_tag="r", created_at=NOW, last_reinforced=NOW),
                BodyMemoryEntry(cue="real_cue", weight=0.5, response_tag="r", created_at=NOW, last_reinforced=NOW),
            ],
            max_entries=32,
        )
        snap = to_dream_snapshot(state, NOW)
        assert "" not in snap["memory_cues"]
        assert "real_cue" in snap["memory_cues"]


# ═══════════════════════════════════════════════════════════════════════════════
# C. to_dream_snapshot — security / read-only guarantees
# ═══════════════════════════════════════════════════════════════════════════════

class TestToDreamSnapshotSecurity:
    def test_state_not_mutated(self):
        state = default_hidden_state()
        original_sens = state.sensitivity.current.value
        original_deficit = state.touch_need.deficit.value
        original_ease = state.embodied_ease.value
        to_dream_snapshot(state, NOW)
        assert state.sensitivity.current.value == original_sens
        assert state.touch_need.deficit.value == original_deficit
        assert state.embodied_ease.value == original_ease

    def test_output_contains_no_float_values(self):
        state = default_hidden_state()
        snap = to_dream_snapshot(state, NOW)
        for key, val in snap.items():
            if key == "memory_cues":
                for cue in val:
                    assert isinstance(cue, str), f"memory_cues entry is not str: {cue!r}"
            else:
                assert isinstance(val, str), f"key {key!r} has non-string value: {val!r}"

    def test_snapshot_keys_match_expected_shape(self):
        state = default_hidden_state()
        snap = to_dream_snapshot(state, NOW)
        assert set(snap.keys()) == _EXPECTED_KEYS

    def test_long_term_baselines_absent_from_output(self):
        """Raw baseline values must not appear in the snapshot at all."""
        state = default_hidden_state()
        state.sensitivity.baseline.value = 77.7
        state.touch_need.baseline.value = 33.3
        snap = to_dream_snapshot(state, NOW)
        # Verify no float value leaks anywhere in the snapshot
        import json
        snap_json = json.dumps(snap)
        assert "77.7" not in snap_json
        assert "33.3" not in snap_json

    def test_snapshot_is_new_dict(self):
        """Snapshot must not be a reference to any state field."""
        state = default_hidden_state()
        snap = to_dream_snapshot(state, NOW)
        snap["sensitivity"] = "INJECTED"
        assert state.sensitivity.current.value == SCALAR_CENTER


# ═══════════════════════════════════════════════════════════════════════════════
# D. integrate_event_and_save — disk wiring
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntegrateEventAndSave:
    def test_accepted_event_writes_to_disk(self, sandbox):
        initial = default_hidden_state()
        initial.touch_need.deficit.value = 50.0
        save_hidden_state(TEST_UID, initial)

        envelope = _open_envelope()
        integrate_event_and_save(TEST_UID, RealityEventType.SEEK_COMPANIONSHIP, envelope, NOW)

        loaded = load_hidden_state(TEST_UID)
        assert loaded.touch_need.deficit.value < 50.0

    def test_loaded_state_reflects_deficit_change(self, sandbox):
        initial = default_hidden_state()
        initial.touch_need.deficit.value = 40.0
        save_hidden_state(TEST_UID, initial)

        integrate_event_and_save(TEST_UID, RealityEventType.SEEK_COMPANIONSHIP, _open_envelope(), NOW)

        loaded = load_hidden_state(TEST_UID)
        assert loaded.touch_need.deficit.value < 40.0

    def test_rejected_envelope_does_not_write(self, sandbox):
        initial = default_hidden_state()
        initial.touch_need.deficit.value = 60.0
        save_hidden_state(TEST_UID, initial)

        integrate_event_and_save(
            TEST_UID, RealityEventType.SEEK_COMPANIONSHIP, WriteEnvelope(), NOW
        )

        loaded = load_hidden_state(TEST_UID)
        assert loaded.touch_need.deficit.value == pytest.approx(60.0)

    def test_long_term_fields_unchanged_after_save(self, sandbox):
        initial = default_hidden_state()
        initial.sensitivity.baseline.value = 55.0
        initial.touch_need.baseline.value = 45.0
        initial.embodied_ease.value = 60.0
        save_hidden_state(TEST_UID, initial)

        integrate_event_and_save(TEST_UID, RealityEventType.NO_INTERACTION, _open_envelope(), NOW)

        loaded = load_hidden_state(TEST_UID)
        assert loaded.sensitivity.baseline.value == pytest.approx(55.0)
        assert loaded.touch_need.baseline.value == pytest.approx(45.0)
        assert loaded.embodied_ease.value == pytest.approx(60.0)

    def test_missing_file_creates_default_and_saves(self, sandbox):
        state, result = integrate_event_and_save(
            TEST_UID, RealityEventType.SEEK_COMPANIONSHIP, _open_envelope(), NOW
        )
        assert result.accepted
        path = sandbox.user_memory_root(TEST_UID) / HIDDEN_STATE_FILENAME
        assert path.exists()


# ═══════════════════════════════════════════════════════════════════════════════
# E. integrate_impression_and_save — disk wiring
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntegrateImpressionAndSave:
    def test_accepted_impression_writes_to_disk(self, sandbox):
        initial = default_hidden_state()
        initial.sensitivity.current.value = 50.0
        save_hidden_state(TEST_UID, initial)

        mid_weight = (DREAM_GATE_MIN + DREAM_GATE_MAX) / 2
        imp = ImpressionInput(weight=mid_weight)
        integrate_impression_and_save(TEST_UID, imp, _open_envelope(), NOW)

        loaded = load_hidden_state(TEST_UID)
        assert loaded.sensitivity.current.value > 50.0

    def test_loaded_sensitivity_reflects_impression(self, sandbox):
        initial = default_hidden_state()
        initial.sensitivity.current.value = 55.0
        save_hidden_state(TEST_UID, initial)

        imp = ImpressionInput(weight=DREAM_GATE_MAX)
        integrate_impression_and_save(TEST_UID, imp, _open_envelope(), NOW)

        loaded = load_hidden_state(TEST_UID)
        assert loaded.sensitivity.current.value > 55.0

    def test_rejected_no_envelope_does_not_write(self, sandbox):
        initial = default_hidden_state()
        initial.sensitivity.current.value = 50.0
        save_hidden_state(TEST_UID, initial)

        mid_weight = (DREAM_GATE_MIN + DREAM_GATE_MAX) / 2
        imp = ImpressionInput(weight=mid_weight)
        integrate_impression_and_save(TEST_UID, imp, WriteEnvelope(), NOW)

        loaded = load_hidden_state(TEST_UID)
        assert loaded.sensitivity.current.value == pytest.approx(50.0)

    def test_out_of_gate_weight_does_not_write(self, sandbox):
        initial = default_hidden_state()
        initial.sensitivity.current.value = 50.0
        save_hidden_state(TEST_UID, initial)

        imp = ImpressionInput(weight=DREAM_GATE_MAX + 0.1)
        integrate_impression_and_save(TEST_UID, imp, _open_envelope(), NOW)

        loaded = load_hidden_state(TEST_UID)
        assert loaded.sensitivity.current.value == pytest.approx(50.0)


# ═══════════════════════════════════════════════════════════════════════════════
# F. load_dream_snapshot — end-to-end read
# ═══════════════════════════════════════════════════════════════════════════════

class TestLoadDreamSnapshot:
    def test_returns_dict_with_expected_keys(self, sandbox):
        snap = load_dream_snapshot(TEST_UID, NOW)
        assert set(snap.keys()) == _EXPECTED_KEYS

    def test_missing_file_returns_neutral_snapshot(self, sandbox):
        snap = load_dream_snapshot("nonexistent_uid_p2", NOW)
        assert snap["sensitivity"] == "mid"
        assert snap["touch_appetite"] == "low"   # deficit=0 → low
        assert snap["embodied_ease"] == "neutral"
        assert snap["memory_cues"] == []

    def test_output_has_no_raw_float_values(self, sandbox):
        state = default_hidden_state()
        save_hidden_state(TEST_UID, state)
        snap = load_dream_snapshot(TEST_UID, NOW)
        for key, val in snap.items():
            if key == "memory_cues":
                for cue in val:
                    assert isinstance(cue, str)
            else:
                assert isinstance(val, str)

    def test_modifying_snapshot_does_not_affect_disk(self, sandbox):
        state = default_hidden_state()
        state.sensitivity.current.value = 20.0  # → "low"
        save_hidden_state(TEST_UID, state)

        snap = load_dream_snapshot(TEST_UID, NOW)
        assert snap["sensitivity"] == "low"

        snap["sensitivity"] = "INJECTED"

        snap2 = load_dream_snapshot(TEST_UID, NOW)
        assert snap2["sensitivity"] == "low"

    def test_reflects_persisted_sensitivity_bucket(self, sandbox):
        state = default_hidden_state()
        state.sensitivity.current.value = 80.0
        save_hidden_state(TEST_UID, state)

        snap = load_dream_snapshot(TEST_UID, NOW)
        assert snap["sensitivity"] == "high"

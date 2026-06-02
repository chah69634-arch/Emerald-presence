"""
tests/test_user_hidden_state_edge_cases.py
==========================================
Phase 1 + Phase 1.5 + Phase 2 假绿 (false-positive) safety-boundary tests.

24 edge-case test cases that verify the security perimeter holds even when
inputs are malformed, bursty, outlier, or sourced from untrusted paths.

Coverage map
─────────────────────────────────────────────────────────────────────────────
Group 1 — Single false-positive Dream / hallucination / sensor misreport (5)
  EC-01  Null impression weight (0.0) → below gate                  fail-closed
  EC-02  Borderline sub-gate weight (DREAM_GATE_MIN − ε) → rejected fail-closed
  EC-03  stamp_sensor_watch blocks Reality event                     fail-closed
  EC-04  stamp_sensor_watch blocks impression                        fail-closed
  EC-05  Overweight impression (0.99) → rejected                     fail-closed

Group 2 — Long pure chat / consecutive / high-freq no body contact (4)
  EC-06  50 × NO_INTERACTION: deficit capped at SCALAR_MAX           clamp
  EC-07  100 × SEEK_COMPANIONSHIP from high deficit: floored at 0    clamp
  EC-08  20 mixed events: all four long-term fields unchanged         long-term guard
  EC-09  NO_INTERACTION: last_update_source == REALITY_BEHAVIOR       audit

Group 3 — High-volatility / outlier Reality Event (4)
  EC-10  Discharge from 0: deficit stays 0                           clamp
  EC-11  Accrue from SCALAR_MAX: deficit stays at 100                clamp
  EC-12  Max-gate impression delta == IMPRESSION_MAX_NUDGE exactly    nudge cap
  EC-13  sensitivity.current at SCALAR_MAX: impression does not overflow  clamp

Group 4 — Missing or closed envelope (5)
  EC-14  stamp_test() forces can_write_memory=False → rejected        fail-closed
  EC-15  stamp_debug() forces can_write_memory=False → rejected       fail-closed
  EC-16  stamp_sensor_watch() has can_write_memory == False           envelope check
  EC-17  WriteEnvelope() + event_and_save: no file created on disk    fail-closed disk
  EC-18  Rejected event: last_update_source stays INIT (unchanged)    audit

Group 5 — Dream directly attempts to write long-term fields (4)
  EC-19  Dream impression leaves sensitivity.baseline unchanged        long-term guard
  EC-20  Dream impression leaves embodied_ease unchanged               long-term guard
  EC-21  Dream impression leaves body_memory unchanged                 long-term guard
  EC-22  Dream impression leaves touch_need.baseline unchanged         long-term guard

Group 6 — afterglow / impression bounded: small push only (2)
  EC-23  Mid-gate impression nudge < IMPRESSION_MAX_NUDGE (weak evidence)  weak evidence
  EC-24  5 successive impressions: only sensitivity.current moves     long-term guard
─────────────────────────────────────────────────────────────────────────────

Design invariants verified by this suite:
  • 中期层 fields (sensitivity.current, touch_need.deficit) CAN be moved by
    legal events / impressions with an open envelope.
  • 长期层 fields (sensitivity.baseline, touch_need.baseline, embodied_ease,
    body_memory) are NEVER touched by any of the above paths.
  • All illegal or under-qualified events fail-closed (state unchanged,
    disk unchanged, rejected_reasons populated).
  • False-positive events do NOT modify persistent fields.
  • last_update_source is auditable: rejected calls leave it at INIT;
    accepted calls stamp it with the correct source.
"""
from __future__ import annotations

import pytest

from core.memory.user_hidden_state import (
    BodyMemory,
    BodyMemoryEntry,
    DREAM_GATE_MAX,
    DREAM_GATE_MIN,
    MAX_NUDGE_PER_EVENT,
    SCALAR_MAX,
    SCALAR_CENTER,
    ImpressionInput,
    UpdateSource,
    default_hidden_state,
)
from core.memory.user_hidden_state_integrator import (
    DEFICIT_ACCRUE_AMOUNT,
    DEFICIT_DISCHARGE_AMOUNT,
    IMPRESSION_MAX_NUDGE,
    IntegratorResult,
    RealityEventType,
    integrate_event,
    integrate_impression,
    integrate_event_and_save,
)
from core.memory.user_hidden_state_store import (
    HIDDEN_STATE_FILENAME,
    load_hidden_state,
    save_hidden_state,
)
from core.write_envelope import (
    WriteEnvelope,
    stamp_debug,
    stamp_sensor_watch,
    stamp_test,
    stamp_user_chat,
)

NOW = "2026-06-02T12:00:00Z"
TEST_UID = "user_edge_case"


def _open() -> WriteEnvelope:
    return stamp_user_chat()


def _long_term_snapshot(state):
    """Capture all four long-term field values for before/after comparison."""
    return (
        state.sensitivity.baseline.value,
        state.touch_need.baseline.value,
        state.embodied_ease.value,
        [e.cue for e in state.body_memory.entries],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Group 1 — Single false-positive Dream / hallucination / sensor misreport
# ═══════════════════════════════════════════════════════════════════════════════

class TestFalsePositiveEvents:
    """EC-01 – EC-05: Single random bad inputs must all fail-closed."""

    def test_ec01_null_impression_weight_rejected(self):
        """EC-01 fail-closed: weight=0.0 is a hallucinated null dream → below gate."""
        state = default_hidden_state()
        imp = ImpressionInput(weight=0.0)
        _, result = integrate_impression(imp, state, _open(), NOW)

        assert result.rejected, "null weight must be rejected"
        assert not result.accepted
        assert any("gate" in r for r in result.rejected_reasons)
        # State must be unchanged
        assert state.sensitivity.current.value == SCALAR_CENTER

    def test_ec02_borderline_subgate_weight_rejected(self):
        """EC-02 fail-closed: weight just below DREAM_GATE_MIN (sensor borderline false-report)."""
        state = default_hidden_state()
        subgate = DREAM_GATE_MIN - 0.001
        imp = ImpressionInput(weight=subgate)
        _, result = integrate_impression(imp, state, _open(), NOW)

        assert result.rejected, f"weight {subgate:.4f} is below gate, must be rejected"
        assert state.sensitivity.current.value == SCALAR_CENTER

    def test_ec03_sensor_watch_blocks_reality_event(self):
        """EC-03 fail-closed: stamp_sensor_watch() has can_write_memory=False → event blocked."""
        state = default_hidden_state()
        state.touch_need.deficit.value = 50.0
        watch_envelope = stamp_sensor_watch()

        _, result = integrate_event(RealityEventType.SEEK_COMPANIONSHIP, state, watch_envelope, NOW)

        assert result.rejected
        assert state.touch_need.deficit.value == pytest.approx(50.0), \
            "sensor_watch envelope must not discharge deficit"

    def test_ec04_sensor_watch_blocks_impression(self):
        """EC-04 fail-closed: stamp_sensor_watch() → impression blocked."""
        state = default_hidden_state()
        original_sens = state.sensitivity.current.value
        watch_envelope = stamp_sensor_watch()
        mid_weight = (DREAM_GATE_MIN + DREAM_GATE_MAX) / 2

        imp = ImpressionInput(weight=mid_weight)
        _, result = integrate_impression(imp, state, watch_envelope, NOW)

        assert result.rejected
        assert state.sensitivity.current.value == pytest.approx(original_sens), \
            "sensor_watch envelope must not nudge sensitivity"

    def test_ec05_overweight_hallucination_rejected(self):
        """EC-05 fail-closed: weight=0.99 (far above DREAM_GATE_MAX) → rejected."""
        state = default_hidden_state()
        imp = ImpressionInput(weight=0.99)
        _, result = integrate_impression(imp, state, _open(), NOW)

        assert result.rejected, "weight 0.99 is far above DREAM_GATE_MAX, must be rejected"
        assert state.sensitivity.current.value == SCALAR_CENTER


# ═══════════════════════════════════════════════════════════════════════════════
# Group 2 — Long pure chat / consecutive / high-freq no body contact
# ═══════════════════════════════════════════════════════════════════════════════

class TestHighFrequencyNoBodyContact:
    """EC-06 – EC-09: Bursty events must not corrupt state."""

    def test_ec06_50_no_interaction_deficit_capped_at_scalar_max(self):
        """EC-06 clamp: 50 × NO_INTERACTION — deficit is capped at SCALAR_MAX."""
        state = default_hidden_state()
        state.touch_need.deficit.value = 0.0
        envelope = _open()

        for _ in range(50):
            state, _ = integrate_event(RealityEventType.NO_INTERACTION, state, envelope, NOW)

        assert state.touch_need.deficit.value <= SCALAR_MAX
        assert state.touch_need.deficit.value == pytest.approx(SCALAR_MAX), \
            "50 × accrue should saturate deficit at SCALAR_MAX"

    def test_ec07_100_seek_companionship_floored_at_zero(self):
        """EC-07 clamp: 100 × SEEK_COMPANIONSHIP from high deficit — never goes negative."""
        state = default_hidden_state()
        state.touch_need.deficit.value = 80.0
        envelope = _open()

        for _ in range(100):
            state, _ = integrate_event(RealityEventType.SEEK_COMPANIONSHIP, state, envelope, NOW)

        assert state.touch_need.deficit.value >= 0.0
        assert state.touch_need.deficit.value == pytest.approx(0.0), \
            "repeated discharge must floor deficit at 0"

    def test_ec08_consecutive_events_long_term_fields_never_touched(self):
        """EC-08 long-term guard: 20 mixed Reality events — all four long-term fields unchanged."""
        state = default_hidden_state()
        state.sensitivity.baseline.value = 55.0
        state.touch_need.baseline.value = 45.0
        state.embodied_ease.value = 60.0
        state.body_memory = BodyMemory(
            entries=[BodyMemoryEntry(cue="cue_a", weight=0.7, response_tag="r",
                                     created_at=NOW, last_reinforced=NOW)],
            max_entries=32,
        )
        baseline_before = _long_term_snapshot(state)
        envelope = _open()

        event_sequence = (
            [RealityEventType.SEEK_COMPANIONSHIP] * 7
            + [RealityEventType.NO_INTERACTION] * 7
            + [RealityEventType.RECEIVED_COMFORT] * 6
        )
        for event in event_sequence:
            state, _ = integrate_event(event, state, envelope, NOW)

        assert _long_term_snapshot(state) == baseline_before, \
            "20 mixed Reality events must not touch any long-term field"

    def test_ec09_no_interaction_audit_source_is_reality_behavior(self):
        """EC-09 audit: NO_INTERACTION sets last_update_source = REALITY_BEHAVIOR."""
        state = default_hidden_state()
        state.touch_need.deficit.value = 10.0

        state, result = integrate_event(RealityEventType.NO_INTERACTION, state, _open(), NOW)

        assert result.accepted
        assert state.touch_need.deficit.last_update_source == UpdateSource.REALITY_BEHAVIOR
        assert state.touch_need.deficit.last_updated == NOW


# ═══════════════════════════════════════════════════════════════════════════════
# Group 3 — High-volatility / outlier Reality Event
# ═══════════════════════════════════════════════════════════════════════════════

class TestOutlierRealityEvent:
    """EC-10 – EC-13: Extreme initial states must not break clamping guarantees."""

    def test_ec10_discharge_from_zero_stays_at_zero(self):
        """EC-10 clamp: deficit=0 + SEEK_COMPANIONSHIP → deficit stays at 0 (no underflow)."""
        state = default_hidden_state()
        state.touch_need.deficit.value = 0.0

        state, result = integrate_event(RealityEventType.SEEK_COMPANIONSHIP, state, _open(), NOW)

        assert result.accepted
        assert state.touch_need.deficit.value == pytest.approx(0.0), \
            "discharging from 0 must not produce negative deficit"

    def test_ec11_accrue_from_scalar_max_stays_at_max(self):
        """EC-11 clamp: deficit=100 + NO_INTERACTION → deficit stays at SCALAR_MAX (no overflow)."""
        state = default_hidden_state()
        state.touch_need.deficit.value = SCALAR_MAX

        state, result = integrate_event(RealityEventType.NO_INTERACTION, state, _open(), NOW)

        assert result.accepted
        assert state.touch_need.deficit.value == pytest.approx(SCALAR_MAX), \
            "accruing at SCALAR_MAX must not exceed 100"

    def test_ec12_max_gate_impression_delta_equals_impression_max_nudge(self):
        """EC-12 nudge cap: weight=DREAM_GATE_MAX → delta exactly equals IMPRESSION_MAX_NUDGE."""
        state = default_hidden_state()
        state.sensitivity.current.value = 50.0

        imp = ImpressionInput(weight=DREAM_GATE_MAX)
        state, result = integrate_impression(imp, state, _open(), NOW)

        delta = result.touched_fields[0].new_value - result.touched_fields[0].old_value
        assert result.accepted
        assert delta == pytest.approx(IMPRESSION_MAX_NUDGE), \
            "max-gate impression must produce exactly IMPRESSION_MAX_NUDGE delta"
        assert delta <= MAX_NUDGE_PER_EVENT, \
            "delta must always stay within global MAX_NUDGE_PER_EVENT cap"

    def test_ec13_sensitivity_at_scalar_max_does_not_overflow(self):
        """EC-13 clamp: sensitivity.current=100 + impression → stays at SCALAR_MAX."""
        state = default_hidden_state()
        state.sensitivity.current.value = SCALAR_MAX

        imp = ImpressionInput(weight=DREAM_GATE_MAX)
        state, result = integrate_impression(imp, state, _open(), NOW)

        assert result.accepted
        assert state.sensitivity.current.value == pytest.approx(SCALAR_MAX), \
            "sensitivity.current must not exceed SCALAR_MAX"


# ═══════════════════════════════════════════════════════════════════════════════
# Group 4 — Missing or closed envelope
# ═══════════════════════════════════════════════════════════════════════════════

class TestMissingOrClosedEnvelope:
    """EC-14 – EC-18: Any path that lacks can_write_memory=True must fail-closed."""

    def test_ec14_stamp_test_envelope_rejected(self):
        """EC-14 fail-closed: stamp_test() forces can_write_memory=False → event rejected."""
        state = default_hidden_state()
        state.touch_need.deficit.value = 30.0
        test_envelope = stamp_test()

        assert test_envelope.can_write_memory is False, \
            "stamp_test must auto-close can_write_memory"

        _, result = integrate_event(RealityEventType.SEEK_COMPANIONSHIP, state, test_envelope, NOW)
        assert result.rejected
        assert state.touch_need.deficit.value == pytest.approx(30.0)

    def test_ec15_stamp_debug_envelope_rejected(self):
        """EC-15 fail-closed: stamp_debug() forces can_write_memory=False → impression rejected."""
        state = default_hidden_state()
        debug_envelope = stamp_debug()

        assert debug_envelope.can_write_memory is False, \
            "stamp_debug must auto-close can_write_memory"

        mid_weight = (DREAM_GATE_MIN + DREAM_GATE_MAX) / 2
        imp = ImpressionInput(weight=mid_weight)
        _, result = integrate_impression(imp, state, debug_envelope, NOW)
        assert result.rejected

    def test_ec16_stamp_sensor_watch_has_can_write_memory_false(self):
        """EC-16 envelope check: stamp_sensor_watch() envelope property is can_write_memory=False."""
        env = stamp_sensor_watch()
        assert env.can_write_memory is False, \
            "stamp_sensor_watch must hard-close can_write_memory"
        assert env.can_affect_mood is False

    def test_ec17_null_envelope_event_and_save_no_disk_write(self, sandbox):
        """EC-17 fail-closed disk: WriteEnvelope() zero-value + event_and_save → file not created."""
        null_envelope = WriteEnvelope()  # zero-value, most restrictive
        _, result = integrate_event_and_save(
            TEST_UID, RealityEventType.SEEK_COMPANIONSHIP, null_envelope, NOW
        )

        assert result.rejected
        path = sandbox.user_memory_root(TEST_UID) / HIDDEN_STATE_FILENAME
        assert not path.exists(), \
            "rejected event_and_save must not create hidden_state.json on disk"

    def test_ec18_rejected_event_last_update_source_stays_init(self):
        """EC-18 audit: rejected event must not stamp last_update_source (stays INIT)."""
        state = default_hidden_state()
        # Confirm initial source is INIT
        assert state.touch_need.deficit.last_update_source == UpdateSource.INIT

        closed_envelope = WriteEnvelope(can_write_memory=False)
        state, result = integrate_event(RealityEventType.NO_INTERACTION, state, closed_envelope, NOW)

        assert result.rejected
        assert state.touch_need.deficit.last_update_source == UpdateSource.INIT, \
            "rejected call must not overwrite last_update_source"
        assert state.touch_need.deficit.last_updated is None, \
            "rejected call must not stamp last_updated"


# ═══════════════════════════════════════════════════════════════════════════════
# Group 5 — Dream directly attempts to write long-term fields
# ═══════════════════════════════════════════════════════════════════════════════

class TestDreamDirectLongTermWrite:
    """EC-19 – EC-22: Dream-derived impressions must only touch sensitivity.current."""

    def _apply_impressions(self, n: int = 5):
        """Run n valid Dream impressions against a fresh state; return final state."""
        state = default_hidden_state()
        envelope = _open()
        mid_weight = (DREAM_GATE_MIN + DREAM_GATE_MAX) / 2
        imp = ImpressionInput(
            weight=mid_weight,
            emotional_tags=["warm"],
            impression_text="a close moment",
        )
        for _ in range(n):
            state, _ = integrate_impression(imp, state, envelope, NOW)
        return state

    def test_ec19_dream_impression_leaves_sensitivity_baseline_unchanged(self):
        """EC-19 long-term guard: Dream impression must not alter sensitivity.baseline."""
        original = default_hidden_state().sensitivity.baseline.value
        state = self._apply_impressions(5)
        assert state.sensitivity.baseline.value == pytest.approx(original), \
            "sensitivity.baseline is a long-term field; Dream impression must not touch it"

    def test_ec20_dream_impression_leaves_embodied_ease_unchanged(self):
        """EC-20 long-term guard: Dream impression must not alter embodied_ease."""
        original = default_hidden_state().embodied_ease.value
        state = self._apply_impressions(5)
        assert state.embodied_ease.value == pytest.approx(original), \
            "embodied_ease is a long-term constitution field; Dream impression must not touch it"

    def test_ec21_dream_impression_leaves_body_memory_unchanged(self):
        """EC-21 long-term guard: Dream impression must not add entries to body_memory."""
        state = self._apply_impressions(5)
        assert state.body_memory.entries == [], \
            "body_memory requires Reality corroboration (Phase 3+); Dream impression must not write it"

    def test_ec22_dream_impression_leaves_touch_need_baseline_unchanged(self):
        """EC-22 long-term guard: Dream impression must not alter touch_need.baseline."""
        original = default_hidden_state().touch_need.baseline.value
        state = self._apply_impressions(5)
        assert state.touch_need.baseline.value == pytest.approx(original), \
            "touch_need.baseline is a long-term field; Dream impression must not touch it"


# ═══════════════════════════════════════════════════════════════════════════════
# Group 6 — afterglow / impression bounded: small push only
# ═══════════════════════════════════════════════════════════════════════════════

class TestAfterglowImpressionBounded:
    """EC-23 – EC-24: Weak evidence produces weak nudge; long-term fields immune."""

    def test_ec23_mid_gate_impression_nudge_smaller_than_max(self):
        """EC-23 weak evidence: mid-gate weight gives proportionally small delta (< IMPRESSION_MAX_NUDGE).

        At weight=0.3 (mid of [0.2, 0.4]):
          ratio = (0.3 − 0.2) / (0.4 − 0.2) = 0.5
          delta = 0.5 × IMPRESSION_MAX_NUDGE = 1.5  (NOT the full 3.0)

        This verifies that weak dream evidence only weakly pushes mid-term state.
        """
        state = default_hidden_state()
        state.sensitivity.current.value = 50.0
        mid_weight = (DREAM_GATE_MIN + DREAM_GATE_MAX) / 2  # 0.3

        imp = ImpressionInput(weight=mid_weight)
        state, result = integrate_impression(imp, state, _open(), NOW)

        assert result.accepted
        delta = result.touched_fields[0].new_value - result.touched_fields[0].old_value
        expected_delta = ((mid_weight - DREAM_GATE_MIN) / (DREAM_GATE_MAX - DREAM_GATE_MIN)) * IMPRESSION_MAX_NUDGE
        assert delta == pytest.approx(expected_delta, abs=1e-6), \
            f"mid-gate nudge must be {expected_delta:.3f}, not the full {IMPRESSION_MAX_NUDGE}"
        assert delta < IMPRESSION_MAX_NUDGE, \
            "mid-gate impression must give less than IMPRESSION_MAX_NUDGE"

    def test_ec24_multiple_impressions_only_move_sensitivity_current(self):
        """EC-24 long-term guard: 5 valid Dream impressions accumulate in sensitivity.current only.

        Verifies:
          - sensitivity.current increases (mid-term layer is responsive)
          - All four long-term fields remain at default values
          - touch_need.deficit is unaffected (cross-field isolation)
        """
        state = default_hidden_state()
        long_term_before = _long_term_snapshot(state)
        original_deficit = state.touch_need.deficit.value
        envelope = _open()
        max_weight = DREAM_GATE_MAX
        imp = ImpressionInput(weight=max_weight)

        for _ in range(5):
            state, result = integrate_impression(imp, state, envelope, NOW)
            assert result.accepted

        # 中期层: sensitivity.current should have increased
        assert state.sensitivity.current.value > SCALAR_CENTER, \
            "sensitivity.current (中期层) must accumulate across repeated impressions"
        assert state.sensitivity.current.value <= SCALAR_MAX

        # 中期层: touch_need.deficit must be untouched by impression
        assert state.touch_need.deficit.value == pytest.approx(original_deficit), \
            "impression must not affect touch_need.deficit"

        # 长期层: all four long-term fields unchanged
        assert _long_term_snapshot(state) == long_term_before, \
            "5 Dream impressions must not touch any long-term field"

        # Audit: update source on sensitivity.current is DREAM_IMPRESSION
        assert state.sensitivity.current.last_update_source == UpdateSource.DREAM_IMPRESSION

"""
core/memory/user_hidden_state_integrator.py
==========================================
Phase 1 MVP + Phase 2 save wiring

Entry points (pure, in-memory):
  integrate_event(event_type, hidden_state, write_envelope, now)
  integrate_impression(impression, hidden_state, write_envelope, now)

Entry points (Phase 2 — load → integrate → save):
  integrate_event_and_save(uid, event_type, write_envelope, now)
  integrate_impression_and_save(uid, impression, write_envelope, now)

Writable fields (中期层 only):
  - touch_need.deficit
  - sensitivity.current

Protected fields (长期层 — zero writes, always):
  - sensitivity.baseline
  - touch_need.baseline
  - embodied_ease
  - body_memory

Fail-closed contract:
  All mutations require write_envelope.can_write_memory == True.
  If the envelope gate is closed, the state is returned unchanged and
  IntegratorResult.rejected_reasons is populated.
  The _and_save variants only persist when the envelope is open AND the
  result is accepted; rejected calls never touch disk.

Not implemented (Phase 3+):
  - consolidate / baseline promotion
  - body_memory reinforcement
  - embodied_ease updates
  - afterglow processing
  - dream_body_event processing
  - sensor integration
  - build_snapshot
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from core.memory.user_hidden_state import (
    DREAM_GATE_MAX,
    DREAM_GATE_MIN,
    MAX_NUDGE_PER_EVENT,
    ImpressionInput,
    UpdateSource,
    UserHiddenState,
    _clamp,
    discharge_touch_deficit,
    nudge_current_sensitivity,
)
from core.memory.user_hidden_state_store import load_hidden_state, save_hidden_state
from core.write_envelope import WriteEnvelope

logger = logging.getLogger(__name__)

# ── Module-level event deltas ─────────────────────────────────────────────────

DEFICIT_DISCHARGE_AMOUNT: float = 8.0
"""Points removed from touch_need.deficit per comfort / companionship event."""

DEFICIT_ACCRUE_AMOUNT: float = 4.0
"""Points added to touch_need.deficit per no-interaction event."""

IMPRESSION_MAX_NUDGE: float = 3.0
"""Max sensitivity.current increase per impression (before MAX_NUDGE_PER_EVENT cap)."""

# Long-term field names guarded against any write from this module.
_LONG_TERM_FIELDS: frozenset[str] = frozenset({
    "sensitivity.baseline",
    "touch_need.baseline",
    "embodied_ease",
    "body_memory",
})


# ── A. RealityEventType ───────────────────────────────────────────────────────


class RealityEventType(str, Enum):
    SEEK_COMPANIONSHIP = "seek_companionship"
    """User actively seeks companionship — discharges touch deficit."""

    NO_INTERACTION = "no_interaction"
    """Long period without interaction — accrues touch deficit."""

    RECEIVED_COMFORT = "received_comfort"
    """User was soothed / comforted — discharges touch deficit."""


# ── B. Audit types ────────────────────────────────────────────────────────────


@dataclass
class FieldDelta:
    """Audit record for a single field mutation."""

    field: str
    old_value: float
    new_value: float
    source: str


@dataclass
class IntegratorResult:
    """Audit record returned by every integrator call.

    touched_fields — list of mutations that were applied.
    rejected_reasons — list of reasons mutations were blocked.
    source — originating event or source identifier.
    timestamp — ISO-8601 UTC string passed in as `now`.
    """

    touched_fields: list[FieldDelta] = field(default_factory=list)
    rejected_reasons: list[str] = field(default_factory=list)
    source: str = ""
    timestamp: str = ""

    @property
    def accepted(self) -> bool:
        return bool(self.touched_fields)

    @property
    def rejected(self) -> bool:
        return bool(self.rejected_reasons) and not self.touched_fields


# ── C. integrate_event ────────────────────────────────────────────────────────


def integrate_event(
    event_type: RealityEventType,
    hidden_state: UserHiddenState,
    write_envelope: WriteEnvelope,
    now: str,
) -> tuple[UserHiddenState, IntegratorResult]:
    """Apply a Reality event to the 中期层 fields of hidden_state.

    Rules:
      SEEK_COMPANIONSHIP  → touch_need.deficit discharge (−DEFICIT_DISCHARGE_AMOUNT)
      RECEIVED_COMFORT    → touch_need.deficit discharge (−DEFICIT_DISCHARGE_AMOUNT)
      NO_INTERACTION      → touch_need.deficit accrue   (+DEFICIT_ACCRUE_AMOUNT)

    All mutations require write_envelope.can_write_memory == True.
    Long-term fields (sensitivity.baseline, touch_need.baseline,
    embodied_ease, body_memory) are never touched.

    Returns:
        (updated_state, IntegratorResult)
        On rejection, state is returned unchanged.
    """
    result = IntegratorResult(source=event_type.value, timestamp=now)

    if not write_envelope.can_write_memory:
        reason = f"write_envelope.can_write_memory=False [event={event_type.value}]"
        result.rejected_reasons.append(reason)
        logger.warning("integrator rejected: %s", reason)
        return hidden_state, result

    deficit = hidden_state.touch_need.deficit

    if event_type in (RealityEventType.SEEK_COMPANIONSHIP, RealityEventType.RECEIVED_COMFORT):
        old_val = deficit.value
        discharge_touch_deficit(hidden_state, DEFICIT_DISCHARGE_AMOUNT, UpdateSource.REALITY_BEHAVIOR, now)
        new_val = deficit.value
        result.touched_fields.append(FieldDelta(
            field="touch_need.deficit",
            old_value=old_val,
            new_value=new_val,
            source=event_type.value,
        ))
        logger.info(
            "integrator: touch_need.deficit %.2f → %.2f [source=%s]",
            old_val, new_val, event_type.value,
        )

    elif event_type == RealityEventType.NO_INTERACTION:
        old_val = deficit.value
        new_val = _clamp(old_val + DEFICIT_ACCRUE_AMOUNT)
        hidden_state.touch_need.deficit.value = new_val
        hidden_state.touch_need.deficit.last_updated = now
        hidden_state.touch_need.deficit.last_update_source = UpdateSource.REALITY_BEHAVIOR
        result.touched_fields.append(FieldDelta(
            field="touch_need.deficit",
            old_value=old_val,
            new_value=new_val,
            source=event_type.value,
        ))
        logger.info(
            "integrator: touch_need.deficit %.2f → %.2f [source=%s]",
            old_val, new_val, event_type.value,
        )

    return hidden_state, result


# ── D. integrate_impression ───────────────────────────────────────────────────


def integrate_impression(
    impression: ImpressionInput,
    hidden_state: UserHiddenState,
    write_envelope: WriteEnvelope,
    now: str,
) -> tuple[UserHiddenState, IntegratorResult]:
    """Apply a Dream-derived impression to sensitivity.current (increase only).

    Gate rules:
      1. write_envelope.can_write_memory must be True.
      2. impression.weight must be in [DREAM_GATE_MIN, DREAM_GATE_MAX].
         Values outside this range are rejected.
      3. Delta is always positive (increases only).
      4. Delta is capped at min(IMPRESSION_MAX_NUDGE, MAX_NUDGE_PER_EVENT).

    Long-term fields are never touched by this function.

    Returns:
        (updated_state, IntegratorResult)
        On rejection, state is returned unchanged.
    """
    result = IntegratorResult(source=UpdateSource.DREAM_IMPRESSION.value, timestamp=now)

    if not write_envelope.can_write_memory:
        reason = "write_envelope.can_write_memory=False [impression]"
        result.rejected_reasons.append(reason)
        logger.warning("integrator rejected impression: %s", reason)
        return hidden_state, result

    weight = impression.weight
    if weight < DREAM_GATE_MIN or weight > DREAM_GATE_MAX:
        reason = (
            f"impression.weight={weight:.3f} outside gate "
            f"[{DREAM_GATE_MIN}, {DREAM_GATE_MAX}]"
        )
        result.rejected_reasons.append(reason)
        logger.warning("integrator rejected impression: %s", reason)
        return hidden_state, result

    gate_span = DREAM_GATE_MAX - DREAM_GATE_MIN
    ratio = (weight - DREAM_GATE_MIN) / gate_span if gate_span > 0 else 1.0
    delta = min(ratio * IMPRESSION_MAX_NUDGE, MAX_NUDGE_PER_EVENT)

    old_val = hidden_state.sensitivity.current.value
    nudge_current_sensitivity(hidden_state, delta, UpdateSource.DREAM_IMPRESSION, now)
    new_val = hidden_state.sensitivity.current.value
    result.touched_fields.append(FieldDelta(
        field="sensitivity.current",
        old_value=old_val,
        new_value=new_val,
        source=UpdateSource.DREAM_IMPRESSION.value,
    ))
    logger.info(
        "integrator: sensitivity.current %.2f → %.2f [weight=%.3f]",
        old_val, new_val, weight,
    )

    return hidden_state, result


# ── E. Disk-wired entry points (Phase 2) ─────────────────────────────────────


def integrate_event_and_save(
    uid: str | int,
    event_type: RealityEventType,
    write_envelope: WriteEnvelope,
    now: str,
) -> tuple[UserHiddenState, IntegratorResult]:
    """Load hidden state, apply a Reality event, and persist if permitted.

    Steps:
      1. Load UserHiddenState from store (or default if absent/corrupt).
      2. Call integrate_event() — 中期层 mutation only.
      3. If write_envelope.can_write_memory AND result.accepted: atomic save.
         Otherwise: state is returned unchanged, nothing is written to disk.

    Long-term fields (sensitivity.baseline, touch_need.baseline, embodied_ease,
    body_memory) are never touched — guaranteed by integrate_event().

    Fail-closed: a rejected envelope or any I/O error leaves disk untouched.
    The atomic write guarantee comes from safe_write_json inside save_hidden_state.

    Returns:
        (state_after_mutation, IntegratorResult)
    """
    state = load_hidden_state(uid)
    state, result = integrate_event(event_type, state, write_envelope, now)
    if write_envelope.can_write_memory and result.accepted:
        ok = save_hidden_state(uid, state)
        if not ok:
            logger.error(
                "integrate_event_and_save: save failed [uid=%s event=%s]",
                uid, event_type.value,
            )
    return state, result


def integrate_impression_and_save(
    uid: str | int,
    impression: ImpressionInput,
    write_envelope: WriteEnvelope,
    now: str,
) -> tuple[UserHiddenState, IntegratorResult]:
    """Load hidden state, apply a Dream-derived impression, and persist if permitted.

    Steps:
      1. Load UserHiddenState from store (or default if absent/corrupt).
      2. Call integrate_impression() — sensitivity.current mutation only.
      3. If write_envelope.can_write_memory AND result.accepted: atomic save.
         Otherwise: state is returned unchanged, nothing is written to disk.

    Long-term fields are never touched — guaranteed by integrate_impression().
    Dream-derived inputs must only be supplied at Dream exit by the Reality-side
    caller; never from within an active Dream turn.

    Fail-closed: rejected envelope, out-of-gate weight, or I/O error → no write.
    The atomic write guarantee comes from safe_write_json inside save_hidden_state.

    Returns:
        (state_after_mutation, IntegratorResult)
    """
    state = load_hidden_state(uid)
    state, result = integrate_impression(impression, state, write_envelope, now)
    if write_envelope.can_write_memory and result.accepted:
        ok = save_hidden_state(uid, state)
        if not ok:
            logger.error(
                "integrate_impression_and_save: save failed [uid=%s]", uid,
            )
    return state, result

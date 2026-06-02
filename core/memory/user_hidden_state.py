"""
core/memory/user_hidden_state.py
================================
Phase 0 schema stub — User Hidden State System

=== SECURITY BOUNDARIES (MUST READ BEFORE EXTENDING) ===

  Phase 0 scope:
    - Data structures, constants, function signatures, docstrings only.
    - No pipeline wiring.
    - No disk I/O.
    - No Dream writeback of any kind.
    - No WriteEnvelope stamp emitted here.
    - No direct memory / mood / profile / event_log writes.

  Write permissions:
    - DREAM_DIRECT_WRITABLE   = frozenset()   # Dream cannot directly mutate any field.
    - DIRECT_MEMORY_WRITABLE  = frozenset()   # This module does not write memory.
    - DIRECT_MOOD_WRITABLE    = frozenset()   # This module does not write mood.
    - DIRECT_PROFILE_WRITABLE = frozenset()   # This module does not write profile.
    - DIRECT_EVENT_LOG_WRITABLE = frozenset() # This module does not write event_log.

  Future persistence path:
    - All persistent writes must flow through the Reality-side integrator,
      which must obtain a WriteEnvelope with can_write_memory=True before
      calling any mutating function defined here.
    - Dream-derived update sources (DREAM_AFTERGLOW, DREAM_IMPRESSION,
      DREAM_BODY_EVENT) may only enter via the Reality-side integrator at
      Dream exit — never from within a live Dream turn.

  Sensor / Watch:
    - SENSOR_SIGNAL is defined as an UpdateSource for future extensibility.
    - In Phase 0 and until an explicit WriteEnvelope with can_write_memory=True
      is granted, sensor/watch raw signals must NOT affect long-term state.
    - Do not assume heart-rate, screen text, or activity data auto-enters
      persistent state.

  Render tags:
    - <say> / <thought> / <narration> are desktop render structures.
    - This module must not use render tags as evidence for hidden-state updates.
    - Only stripped plain-text or structured events should be used.

  QQ channel isolation:
    - DREAM_ACTIVE / DREAM_CLOSING: QQ owner messages are rejected upstream.
    - No logic in this module may depend on "QQ补消息 during Dream."

  data/chars retirement:
    - This module must not reference data/chars/{char_id}.
    - Future path access must use user_memory_root(...) — not wired in Phase 0.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

# ── A. UpdateSource ────────────────────────────────────────────────────────────


class UpdateSource(str, Enum):
    """Origin of a state-mutation event.

    SENSOR_SIGNAL is defined for future extensibility only.
    Phase 0 rule: sensor signals are untrusted by default and must not
    directly write long-term state without an explicit WriteEnvelope grant.
    """

    INIT = "init"
    """Initial value at construction — no external influence."""

    REALITY_BEHAVIOR = "reality_behavior"
    """Observed behavior during a Reality (non-Dream) turn."""

    DREAM_AFTERGLOW = "dream_afterglow"
    """Emotional residue computed after Dream exit.
    Must enter via Reality-side integrator only."""

    DREAM_IMPRESSION = "dream_impression"
    """Distilled impression extracted from Dream transcript.
    Must enter via Reality-side integrator only."""

    DREAM_BODY_EVENT = "dream_body_event"
    """Body-state event that occurred during Dream session.
    Must enter via Reality-side integrator only."""

    SENSOR_SIGNAL = "sensor_signal"
    """Raw sensor / watch signal (heart-rate, screen text, activity, etc.).

    UNTRUSTED by default.  Writing long-term state from this source
    requires an explicit WriteEnvelope with can_write_memory=True,
    granted by the Reality-side integrator — never auto-granted.
    """

    TIME_DECAY = "time_decay"
    """Passive decay applied by the scheduler tick."""

    CONSOLIDATION = "consolidation"
    """Baseline consolidation pass (Reality-side only)."""


# ── B. Dataclasses ─────────────────────────────────────────────────────────────


@dataclass
class ScalarState:
    """A single clamped scalar with provenance metadata.

    value is kept in [SCALAR_MIN, SCALAR_MAX] (0.0–100.0).
    last_updated is an ISO-8601 UTC string or None if never updated.
    """

    value: float = 0.0
    last_updated: Optional[str] = None
    last_update_source: UpdateSource = UpdateSource.INIT


@dataclass
class BodyMemoryEntry:
    """One conditioned body-cue → response association.

    weight is in [WEIGHT_MIN, WEIGHT_MAX] (0.0–1.0).
    Entries below MEMORY_EVICT_EPS are eligible for eviction.
    """

    cue: str = ""
    response_tag: str = ""
    weight: float = 0.0
    created_at: str = ""
    last_reinforced: str = ""


@dataclass
class SensitivityState:
    """Physical sensitivity expressed as two scalars.

    baseline — slow-moving population-level norm.
    current  — fast-moving session-level value that regresses toward baseline.
    """

    baseline: ScalarState = field(default_factory=ScalarState)
    current: ScalarState = field(default_factory=ScalarState)


@dataclass
class TouchNeedState:
    """Affective touch-need state.

    baseline — individual touch-appetite set-point.
    deficit  — accumulated unmet touch need; decays with time.
    """

    baseline: ScalarState = field(default_factory=ScalarState)
    deficit: ScalarState = field(default_factory=ScalarState)


@dataclass
class BodyMemory:
    """Collection of conditioned body-cue entries with a fixed capacity.

    When entries exceed max_entries, the lowest-weight entry is evicted.
    """

    entries: list[BodyMemoryEntry] = field(default_factory=list)
    max_entries: int = 32


@dataclass
class UserHiddenState:
    """Top-level container for all user hidden state.

    schema_version must be bumped on any breaking field change.
    last_decay_tick is an ISO-8601 UTC string of the most recent
    time-decay pass, or None if decay has never run.

    Immutability contract for Phase 0:
      No field in this object may be written directly by Dream turns,
      sensor signals, render-tag parsers, or QQ message handlers.
      All mutations must go through the Reality-side integrator with
      an explicit WriteEnvelope grant.
    """

    sensitivity: SensitivityState = field(default_factory=SensitivityState)
    touch_need: TouchNeedState = field(default_factory=TouchNeedState)
    body_familiarity: ScalarState = field(default_factory=ScalarState)
    body_memory: BodyMemory = field(default_factory=BodyMemory)
    last_decay_tick: Optional[str] = None
    schema_version: int = 1


# ── C. Constants ───────────────────────────────────────────────────────────────

# Scalar range
SCALAR_MIN: float = 0.0
SCALAR_MAX: float = 100.0
SCALAR_CENTER: float = 50.0

# Weight range for body-memory entries
WEIGHT_MIN: float = 0.0
WEIGHT_MAX: float = 1.0

# Half-life constants (days)
CURRENT_SENS_REGRESS_HL_DAYS: float = 5.0      # current sensitivity → baseline
SENS_BASELINE_CENTER_HL_DAYS: float = 180.0    # sensitivity baseline → center
TOUCH_DEFICIT_DECAY_HL_DAYS: float = 10.0      # touch deficit → 0
TOUCH_BASELINE_CENTER_HL_DAYS: float = 180.0   # touch baseline → center
FAMILIARITY_COLD_HL_DAYS: float = 90.0         # familiarity → 0 (cold)
MEMORY_EXTINCTION_HL_DAYS: float = 45.0        # body-memory weight decay

# Learning / nudge limits
BASELINE_LEARN_RATE: float = 0.02              # fraction moved per event
MAX_NUDGE_PER_EVENT: float = 6.0               # max single-event delta on any scalar
DREAM_GATE_MIN: float = 0.2                    # minimum Dream-derived update gate
DREAM_GATE_MAX: float = 0.4                    # maximum Dream-derived update gate

# Body memory capacity
BODY_MEMORY_MAX_ENTRIES: int = 32
MEMORY_EVICT_EPS: float = 0.05                 # weight threshold for eviction eligibility

# Write-permission frozensets (all empty — this module has no write authority)
DREAM_DIRECT_WRITABLE: frozenset[str] = frozenset()
"""No field may be written directly from a live Dream turn."""

DIRECT_MEMORY_WRITABLE: frozenset[str] = frozenset()
"""This module does not write to the memory subsystem."""

DIRECT_MOOD_WRITABLE: frozenset[str] = frozenset()
"""This module does not write to mood_state."""

DIRECT_PROFILE_WRITABLE: frozenset[str] = frozenset()
"""This module does not write to user_profile."""

DIRECT_EVENT_LOG_WRITABLE: frozenset[str] = frozenset()
"""This module does not write to event_log."""


# ── D. Default constructor ─────────────────────────────────────────────────────


def default_hidden_state() -> UserHiddenState:
    """Return a zero/center UserHiddenState with no provenance.

    Default values:
      sensitivity.baseline  = 50  (SCALAR_CENTER)
      sensitivity.current   = 50
      touch_need.baseline   = 50
      touch_need.deficit    = 0
      body_familiarity      = 0
      body_memory           = empty, max_entries=BODY_MEMORY_MAX_ENTRIES

    This function does not write memory, mood, profile, or event_log.
    It emits no WriteEnvelope stamp.
    """
    return UserHiddenState(
        sensitivity=SensitivityState(
            baseline=ScalarState(value=SCALAR_CENTER, last_update_source=UpdateSource.INIT),
            current=ScalarState(value=SCALAR_CENTER, last_update_source=UpdateSource.INIT),
        ),
        touch_need=TouchNeedState(
            baseline=ScalarState(value=SCALAR_CENTER, last_update_source=UpdateSource.INIT),
            deficit=ScalarState(value=0.0, last_update_source=UpdateSource.INIT),
        ),
        body_familiarity=ScalarState(value=0.0, last_update_source=UpdateSource.INIT),
        body_memory=BodyMemory(entries=[], max_entries=BODY_MEMORY_MAX_ENTRIES),
        last_decay_tick=None,
        schema_version=1,
    )


# ── E. Primitive helpers ───────────────────────────────────────────────────────


def _clamp(value: float, lo: float = SCALAR_MIN, hi: float = SCALAR_MAX) -> float:
    """Return value clamped to [lo, hi].

    Pure function.  No state mutation.  No I/O.
    """
    return max(lo, min(hi, value))


def _half_life_factor(elapsed_days: float, half_life_days: float) -> float:
    """Return the fraction of original magnitude remaining after elapsed_days.

    Uses: factor = 0.5 ^ (elapsed_days / half_life_days)
    Returns 1.0 if half_life_days <= 0 (no decay).
    Returns 1.0 if elapsed_days < 0 (negative time is ignored).
    Pure function.  No state mutation.  No I/O.
    """
    if half_life_days <= 0.0 or elapsed_days <= 0.0:
        return 1.0
    return math.pow(0.5, elapsed_days / half_life_days)


def _regress(
    current: float,
    target: float,
    elapsed_days: float,
    half_life_days: float,
) -> float:
    """Move current toward target using exponential half-life decay.

    Returns current + (target - current) * (1 - half_life_factor).
    Pure function.  No state mutation.  No I/O.
    """
    factor = _half_life_factor(elapsed_days, half_life_days)
    return current + (target - current) * (1.0 - factor)


def _logistic_step(x: float, center: float = SCALAR_CENTER, steepness: float = 0.1) -> float:
    """Map x through a logistic sigmoid centered at `center`.

    Returns a value in (0, 1).
    Used for gate calculations (e.g., DREAM_GATE_MIN/MAX scaling).
    Pure function.  No state mutation.  No I/O.
    """
    return 1.0 / (1.0 + math.exp(-steepness * (x - center)))


# ── F. Update function stubs ───────────────────────────────────────────────────


def apply_time_decay(state: UserHiddenState, now: str) -> UserHiddenState:
    """Apply passive time-based decay to all scalar fields.

    Phase 1 requirement:
      Caller MUST hold a WriteEnvelope with can_write_memory=True before
      invoking this function and persisting the returned state.
      This function itself does not emit a WriteEnvelope stamp.
      It does not write memory, mood, profile, or event_log.

    Dream-derived sources must not call this directly;
    decay is applied by the Reality-side scheduler tick only.

    Raises:
        NotImplementedError: Phase 0 — implementation deferred to Phase 1.
    """
    raise NotImplementedError("apply_time_decay: Phase 0 stub — implement in Phase 1")


def nudge_current_sensitivity(
    state: UserHiddenState,
    delta: float,
    source: UpdateSource,
    now: str,
) -> UserHiddenState:
    """Nudge sensitivity.current by delta, clamped to scalar range.

    Phase 1 requirement:
      Caller MUST hold a WriteEnvelope with can_write_memory=True.
      This function does not emit a WriteEnvelope stamp.
      It does not write memory, mood, profile, or event_log.

    Dream-derived sources (DREAM_AFTERGLOW, DREAM_IMPRESSION,
    DREAM_BODY_EVENT) must only enter via the Reality-side integrator
    at Dream exit — never from a live Dream turn.

    SENSOR_SIGNAL source is accepted as an argument type but must NOT
    be passed unless the caller's WriteEnvelope explicitly grants
    can_write_memory=True for sensor paths.

    Raises:
        NotImplementedError: Phase 0 — implementation deferred to Phase 1.
    """
    raise NotImplementedError("nudge_current_sensitivity: Phase 0 stub")


def accrue_touch_deficit(
    state: UserHiddenState,
    elapsed_days: float,
    now: str,
) -> UserHiddenState:
    """Increase touch deficit based on elapsed time without touch contact.

    Phase 1 requirement:
      Caller MUST hold a WriteEnvelope with can_write_memory=True.
      This function does not emit a WriteEnvelope stamp.
      It does not write memory, mood, profile, or event_log.

    Raises:
        NotImplementedError: Phase 0 — implementation deferred to Phase 1.
    """
    raise NotImplementedError("accrue_touch_deficit: Phase 0 stub")


def discharge_touch_deficit(
    state: UserHiddenState,
    amount: float,
    source: UpdateSource,
    now: str,
) -> UserHiddenState:
    """Reduce touch deficit by amount (positive means deficit decreases).

    Phase 1 requirement:
      Caller MUST hold a WriteEnvelope with can_write_memory=True.
      This function does not emit a WriteEnvelope stamp.
      It does not write memory, mood, profile, or event_log.

    Raises:
        NotImplementedError: Phase 0 — implementation deferred to Phase 1.
    """
    raise NotImplementedError("discharge_touch_deficit: Phase 0 stub")


def reinforce_familiarity(
    state: UserHiddenState,
    exposure: float,
    source: UpdateSource,
    now: str,
) -> UserHiddenState:
    """Increase body_familiarity by exposure * learning_rate, clamped.

    Phase 1 requirement:
      Caller MUST hold a WriteEnvelope with can_write_memory=True.
      This function does not emit a WriteEnvelope stamp.
      It does not write memory, mood, profile, or event_log.

    Dream-derived sources must only enter via Reality-side integrator.

    Raises:
        NotImplementedError: Phase 0 — implementation deferred to Phase 1.
    """
    raise NotImplementedError("reinforce_familiarity: Phase 0 stub")


def reinforce_body_memory(
    state: UserHiddenState,
    cue: str,
    response_tag: str,
    strength: float,
    source: UpdateSource,
    now: str,
) -> UserHiddenState:
    """Upsert a body-memory entry and reinforce its weight.

    If cue already exists, updates weight and last_reinforced.
    If cue is new and body_memory is full, evicts the lowest-weight entry
    that is below MEMORY_EVICT_EPS; if none qualifies, the new entry is dropped.

    Phase 1 requirement:
      Caller MUST hold a WriteEnvelope with can_write_memory=True.
      This function does not emit a WriteEnvelope stamp.
      It does not write memory, mood, profile, or event_log.

    Dream-derived sources must only enter via Reality-side integrator at exit.
    SENSOR_SIGNAL must not be passed without explicit WriteEnvelope grant.

    Raises:
        NotImplementedError: Phase 0 — implementation deferred to Phase 1.
    """
    raise NotImplementedError("reinforce_body_memory: Phase 0 stub")


def consolidate_baselines(
    state: UserHiddenState,
    now: str,
) -> UserHiddenState:
    """Nudge sensitivity and touch baselines toward SCALAR_CENTER.

    Intended for infrequent consolidation runs (weekly/monthly).

    Phase 1 requirement:
      Caller MUST hold a WriteEnvelope with can_write_memory=True.
      This function does not emit a WriteEnvelope stamp.
      It does not write memory, mood, profile, or event_log.
      Must not be triggered from within a Dream turn.

    Raises:
        NotImplementedError: Phase 0 — implementation deferred to Phase 1.
    """
    raise NotImplementedError("consolidate_baselines: Phase 0 stub")


def to_dict(state: UserHiddenState) -> dict[str, Any]:
    """Serialize UserHiddenState to a JSON-compatible dict.

    Does NOT write to disk.  Does NOT write memory, mood, profile, or event_log.
    Caller is responsible for persistence via WriteEnvelope-gated path.

    Raises:
        NotImplementedError: Phase 0 — implementation deferred to Phase 1.
    """
    raise NotImplementedError("to_dict: Phase 0 stub")


def from_dict(data: dict[str, Any]) -> UserHiddenState:
    """Deserialize a dict (from to_dict) back to UserHiddenState.

    Does NOT read from disk.  Does NOT write memory, mood, profile, or event_log.
    Unknown keys are ignored; missing keys fall back to default_hidden_state values.

    Raises:
        NotImplementedError: Phase 0 — implementation deferred to Phase 1.
    """
    raise NotImplementedError("from_dict: Phase 0 stub")


# ── G. Input event dataclasses ─────────────────────────────────────────────────


@dataclass
class DreamBodyStateEvent:
    """Body-state snapshot captured during a Dream session.

    All fields are raw Dream-internal measurements.
    This dataclass must NOT be consumed directly by any write path.
    It must pass through the Reality-side integrator at Dream exit,
    which is responsible for gating with WriteEnvelope.

    No direct write authority — DREAM_DIRECT_WRITABLE = frozenset().
    """

    heat: float = 0.0
    sensitivity: float = 0.0
    tension: float = 0.0
    arousal: float = 0.0
    duration_min: float = 0.0


@dataclass
class AfterglowResidueInput:
    """Emotional afterglow residue computed after Dream session ends.

    Must enter hidden-state update pipeline only via Reality-side integrator.
    Must not be applied during an active or closing Dream turn.
    """

    emotional_tags: list[str] = field(default_factory=list)
    tone: str = ""
    age_hours: float = 0.0


@dataclass
class ImpressionInput:
    """Distilled impression from a Dream transcript.

    Must enter hidden-state update pipeline only via Reality-side integrator.
    impression_text is stripped plain-text — render tags must be removed upstream.
    """

    impression_text: str = ""
    emotional_tags: list[str] = field(default_factory=list)
    weight: float = 0.0


@dataclass
class SensorSignalInput:
    """Raw sensor / watch signal.

    UNTRUSTED BY DEFAULT.
    This dataclass defines structure only.
    It is NOT wired to any write path in Phase 0.

    Phase 1+ rule: consuming code must hold a WriteEnvelope with
    can_write_memory=True (sensor-granted) before passing this to any
    mutating function.  sensor/watch raw signals may NEVER auto-enter
    long-term state without explicit envelope approval.
    """

    signal_type: str = ""
    value: float = 0.0
    confidence: float = 0.0
    age_seconds: float = 0.0


@dataclass
class IntegratorInput:
    """Aggregated input bundle for the Reality-side integrator.

    The Reality-side integrator is the only authorised entry point for
    turning these inputs into hidden-state mutations.  It is responsible
    for validating and stamping a WriteEnvelope before calling any
    mutating function in this module.

    All Dream-derived fields (body_event, afterglow, impression) must
    only be populated at Dream exit — never during an active Dream turn.
    sensor_signal must be treated as untrusted unless the integrator's
    WriteEnvelope explicitly grants can_write_memory=True.
    reality_signals is a free-form dict for future Reality-turn data.
    now is an ISO-8601 UTC timestamp string.
    """

    body_event: Optional[DreamBodyStateEvent] = None
    afterglow: Optional[AfterglowResidueInput] = None
    impression: Optional[ImpressionInput] = None
    sensor_signal: Optional[SensorSignalInput] = None
    reality_signals: dict[str, Any] = field(default_factory=dict)
    now: str = ""


# ── H. Reader / projection stubs ───────────────────────────────────────────────


def read_afterglow_residue(uid: str, now: str) -> Optional[AfterglowResidueInput]:
    """Return the most recent unprocessed afterglow residue for uid, if any.

    Interface only — Phase 0 stub.
    Does NOT create any new persistent field.
    Does NOT read from disk or any real file.
    Does NOT write memory, mood, profile, or event_log.

    Future implementation must use user_memory_root(uid) path system,
    never data/chars/{char_id}.

    Returns:
        None in Phase 0 always.

    Raises:
        NotImplementedError: Phase 0 — implementation deferred to Phase 1.
    """
    raise NotImplementedError("read_afterglow_residue: Phase 0 stub — no I/O in Phase 0")


def to_dream_snapshot(state: UserHiddenState, now: str) -> dict[str, Any]:
    """Return a coarse-grained bucket snapshot suitable for Dream context injection.

    Contract:
      - Returns low-resolution buckets only (no precise scalar values exposed).
      - Does NOT modify state.
      - Does NOT connect to build_snapshot.
      - Does NOT write memory, mood, profile, or event_log.
      - Does NOT emit a WriteEnvelope stamp.

    Return shape::

        {
            "sensitivity":     "low" | "mid" | "high",
            "touch_appetite":  "low" | "mid" | "high",
            "familiarity":     "new" | "warming" | "familiar",
            "memory_cues":     [str, ...],   # top cue strings by weight
        }

    Bucket thresholds (provisional):
      sensitivity / touch_appetite:
        low   < 35
        mid   35 – 65
        high  > 65
      familiarity:
        new      < 20
        warming  20 – 60
        familiar > 60

    Raises:
        NotImplementedError: Phase 0 — implementation deferred to Phase 1.
    """
    raise NotImplementedError("to_dream_snapshot: Phase 0 stub")

"""
Mirror Mode v0.1 — read-only User Hidden State snapshot kernel.

Read-only contract (ABSOLUTE):
  - Built once at dream entry from load_dream_snapshot() output.
  - Frozen into dream_state["mirror_core"] for session lifetime.
  - Never writes hidden_state — DREAM_DIRECT_WRITABLE = frozenset().
  - Never calls integrate_afterglow_and_save / integrate_impression_and_save.
  - snapshot_buckets contain only coarse labels: low / medium / high / unknown.
  - association_presence: none / light / present.
  - No float values are ever stored or forwarded to prompt.
  - No uid, timestamp, weight, baseline, update_source forwarded to prompt.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Allowed coarse bucket values for snapshot_buckets entries.
# association_presence uses its own set (none/light/present).
_VALID_LMH: frozenset[str] = frozenset({"low", "medium", "high", "unknown"})
_VALID_PRESENCE: frozenset[str] = frozenset({"none", "light", "present"})


@dataclass
class MirrorCore:
    """Session-frozen snapshot of User Hidden State in coarse buckets.

    Built once at dream entry (mirror mode only). Never mutated during session.
    Never written back to hidden_state. Cleared at dream close via clear_local_state().

    snapshot_buckets keys and allowed values:
      sensitivity_bucket    — low / medium / high / unknown
      closeness_need_bucket — low / medium / high / unknown
      embodied_ease_bucket  — low / medium / high / unknown
      association_presence  — none / light / present

    symbolic_hints are lightweight tendency descriptions injected into DM prompt.
    No psychological diagnosis. No exact values. No percentage.

    DREAM_DIRECT_WRITABLE = frozenset() — no field may be written from Dream.
    """

    snapshot_buckets: dict[str, str] = field(default_factory=dict)
    symbolic_hints: list[str] = field(default_factory=list)
    source: str = "user_hidden_state_snapshot"
    version: str = "v0.1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_buckets": dict(self.snapshot_buckets),
            "symbolic_hints": list(self.symbolic_hints),
            "source": self.source,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MirrorCore":
        if not isinstance(data, dict):
            return cls()
        return cls(
            snapshot_buckets=dict(data.get("snapshot_buckets") or {}),
            symbolic_hints=list(data.get("symbolic_hints") or []),
            source=str(data.get("source", "user_hidden_state_snapshot")),
            version=str(data.get("version", "v0.1")),
        )


# ── Bucket translators ────────────────────────────────────────────────────────


def _lmh_to_bucket(value: str) -> str:
    """Translate to_dream_snapshot() low/mid/high label to low/medium/high."""
    if value == "low":
        return "low"
    if value == "mid":
        return "medium"
    if value == "high":
        return "high"
    return "unknown"


def _ease_to_bucket(value: str) -> str:
    """Translate guarded/neutral/easy embodied_ease label to low/medium/high."""
    if value == "guarded":
        return "low"
    if value == "neutral":
        return "medium"
    if value == "easy":
        return "high"
    return "unknown"


def _cues_to_presence(cues: list) -> str:
    """Translate body_memory cue list to coarse association_presence label."""
    if not cues:
        return "none"
    if len(cues) <= 2:
        return "light"
    return "present"


# ── Symbolic hint generator ───────────────────────────────────────────────────

# Mapping from bucket state to lightweight tendency text.
# Rules: non-diagnostic, metaphorical, no exact values, no "诊断用户".
_HINT_RULES: list[tuple[str, str, str]] = [
    # (bucket_key, bucket_value, hint_text)
    ("sensitivity_bucket", "high", "梦中感知更细，环境反馈更容易被放大"),
    ("closeness_need_bucket", "high", "更容易出现靠近、等待、确认在场的母题"),
    ("embodied_ease_bucket", "low", "梦境节奏更慢，信任建立更谨慎"),
]
_PRESENCE_HINT = "允许出现重复意象，但不要解释成确定心理结论"


def _build_symbolic_hints(buckets: dict[str, str]) -> list[str]:
    """Generate lightweight tendency hints from snapshot buckets.

    Never: diagnosis, exact values, "你潜意识里", "用户心理", percentages.
    """
    hints: list[str] = []
    for key, val, hint in _HINT_RULES:
        if buckets.get(key) == val:
            hints.append(hint)
    presence = buckets.get("association_presence", "none")
    if presence in ("light", "present"):
        hints.append(_PRESENCE_HINT)
    return hints


# ── Public builder ────────────────────────────────────────────────────────────


def build_mirror_core(snapshot: dict[str, Any]) -> MirrorCore:
    """Build a MirrorCore from a to_dream_snapshot() output dict.

    Fail-closed: any error or malformed input returns a minimal unknown-bucket
    MirrorCore so Dream entry is never blocked.

    Never calls save, never writes hidden_state, never modifies snapshot.

    Expected snapshot keys (from to_dream_snapshot()):
      sensitivity    — "low" | "mid" | "high"
      touch_appetite — "low" | "mid" | "high"
      embodied_ease  — "guarded" | "neutral" | "easy"
      memory_cues    — list[str]
    """
    try:
        if not isinstance(snapshot, dict):
            return MirrorCore()

        sens_b = _lmh_to_bucket(str(snapshot.get("sensitivity", "")))
        close_b = _lmh_to_bucket(str(snapshot.get("touch_appetite", "")))
        ease_b = _ease_to_bucket(str(snapshot.get("embodied_ease", "")))
        raw_cues = snapshot.get("memory_cues")
        presence = _cues_to_presence(raw_cues if isinstance(raw_cues, list) else [])

        buckets: dict[str, str] = {
            "sensitivity_bucket": sens_b,
            "closeness_need_bucket": close_b,
            "embodied_ease_bucket": ease_b,
            "association_presence": presence,
        }

        hints = _build_symbolic_hints(buckets)

        return MirrorCore(snapshot_buckets=buckets, symbolic_hints=hints)
    except Exception as exc:
        logger.warning("[mirror_core] build_mirror_core failed: %s", exc)
        return MirrorCore()

"""
Her cyber body state — dream-local, never persists beyond dream close.

Three axes 0–100:
  heat        — warmth/arousal level
  sensitivity — perceptual sensitivity
  tension     — physical/psychological tension

Suppression caps keep axes below 100 by default (seam for threshold_break, off).
A fourth axis slot is reserved (seam, not implemented).

Storage: in dream_state["body_state"] as a plain dict (dream-local volatile).
Cleared by clear_local_state() at dream close — never survives to reality.

★ Naming is completely separate from data/garden/ and core/garden/*.
  Never write to data/garden/. This is her cyber body, not a flower.
"""

from typing import Any

_DEFAULT_HEAT_CAP: float = 80.0
_DEFAULT_SENSITIVITY_CAP: float = 80.0
_DEFAULT_TENSION_CAP: float = 90.0

# Seam: reserved 4th axis and threshold_break hook (default off, not implemented)
# _AXIS_4_DEFAULT: float = 0.0
# _THRESHOLD_BREAK_ENABLED: bool = False


class BodyState:
    __slots__ = ("heat", "sensitivity", "tension", "heat_cap", "sensitivity_cap", "tension_cap")

    def __init__(
        self,
        heat: float = 0.0,
        sensitivity: float = 0.0,
        tension: float = 0.0,
        heat_cap: float = _DEFAULT_HEAT_CAP,
        sensitivity_cap: float = _DEFAULT_SENSITIVITY_CAP,
        tension_cap: float = _DEFAULT_TENSION_CAP,
    ) -> None:
        self.heat = heat
        self.sensitivity = sensitivity
        self.tension = tension
        self.heat_cap = heat_cap
        self.sensitivity_cap = sensitivity_cap
        self.tension_cap = tension_cap

    def clamp(self) -> "BodyState":
        """Enforce axis bounds and suppression caps, return new instance."""
        return BodyState(
            heat=max(0.0, min(self.heat_cap, self.heat)),
            sensitivity=max(0.0, min(self.sensitivity_cap, self.sensitivity)),
            tension=max(0.0, min(self.tension_cap, self.tension)),
            heat_cap=self.heat_cap,
            sensitivity_cap=self.sensitivity_cap,
            tension_cap=self.tension_cap,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "heat": round(self.heat, 2),
            "sensitivity": round(self.sensitivity, 2),
            "tension": round(self.tension, 2),
            "heat_cap": self.heat_cap,
            "sensitivity_cap": self.sensitivity_cap,
            "tension_cap": self.tension_cap,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "BodyState":
        if not d:
            return cls()
        return cls(
            heat=float(d.get("heat", 0.0)),
            sensitivity=float(d.get("sensitivity", 0.0)),
            tension=float(d.get("tension", 0.0)),
            heat_cap=float(d.get("heat_cap", _DEFAULT_HEAT_CAP)),
            sensitivity_cap=float(d.get("sensitivity_cap", _DEFAULT_SENSITIVITY_CAP)),
            tension_cap=float(d.get("tension_cap", _DEFAULT_TENSION_CAP)),
        )

    @classmethod
    def default(cls) -> "BodyState":
        return cls()

    def __repr__(self) -> str:
        return (
            f"BodyState(heat={self.heat:.1f}, sensitivity={self.sensitivity:.1f}, "
            f"tension={self.tension:.1f})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BodyState):
            return NotImplemented
        return (
            self.heat == other.heat
            and self.sensitivity == other.sensitivity
            and self.tension == other.tension
        )

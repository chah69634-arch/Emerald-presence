from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MemoryDomain = Literal["global", "reality", "dream"]
_VALID_DOMAINS = {"global", "reality", "dream"}


@dataclass(frozen=True)
class MemoryScope:
    uid: str
    domain: MemoryDomain
    character_id: str | None = None
    world_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.uid, str) or not self.uid:
            raise ValueError(f"uid must be a non-empty string, got {self.uid!r}")
        if self.domain not in _VALID_DOMAINS:
            raise ValueError(f"domain must be one of {_VALID_DOMAINS}, got {self.domain!r}")

        if self.domain == "global":
            if self.character_id is not None:
                raise ValueError("global scope must not have character_id")
            if self.world_id is not None:
                raise ValueError("global scope must not have world_id")

        elif self.domain == "reality":
            if not isinstance(self.character_id, str) or not self.character_id:
                raise ValueError("reality scope requires a non-empty character_id")
            if self.world_id is not None:
                raise ValueError("reality scope must not have world_id")

        elif self.domain == "dream":
            if not isinstance(self.character_id, str) or not self.character_id:
                raise ValueError("dream scope requires a non-empty character_id")
            if not isinstance(self.world_id, str) or not self.world_id:
                raise ValueError("dream scope requires a non-empty world_id")

    # ------------------------------------------------------------------
    # Convenience constructors
    # ------------------------------------------------------------------

    @classmethod
    def global_scope(cls, uid: str) -> "MemoryScope":
        return cls(uid=uid, domain="global")

    @classmethod
    def reality_scope(cls, uid: str, character_id: str) -> "MemoryScope":
        return cls(uid=uid, domain="reality", character_id=character_id)

    @classmethod
    def dream_scope(cls, uid: str, character_id: str, world_id: str) -> "MemoryScope":
        return cls(uid=uid, domain="dream", character_id=character_id, world_id=world_id)

    # ------------------------------------------------------------------
    # Serialization helpers for slow_queue payloads
    # ------------------------------------------------------------------

    def to_payload(self) -> dict:
        return {
            "uid": self.uid,
            "domain": self.domain,
            "character_id": self.character_id,
            "world_id": self.world_id,
        }

    @classmethod
    def from_payload(cls, payload: dict) -> "MemoryScope":
        if not isinstance(payload, dict):
            raise TypeError(f"payload must be a dict, got {type(payload)!r}")
        for required in ("uid", "domain"):
            if required not in payload:
                raise ValueError(f"payload missing required field: {required!r}")
        return cls(
            uid=payload["uid"],
            domain=payload["domain"],
            character_id=payload.get("character_id"),
            world_id=payload.get("world_id"),
        )

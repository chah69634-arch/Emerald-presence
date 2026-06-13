"""Typed models for a multi-character Stage session."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from core.sandbox import safe_user_id

StageDomain = Literal["reality", "dream"]
StageStatus = Literal["active", "closed"]
TriggerSpeaker = str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class StageSettings:
    min_responders: int = 1
    max_responders: int = 2
    max_ai_chain_depth: int = 2
    respond_threshold: float = 0.5
    spontaneous_threshold: float = 0.7
    addressed_exclusive: bool = False
    transcript_limit: int = 200
    group_memory_strength: float = 0.7
    debug_token_log: bool = True
    talkativeness: dict[str, float] = field(default_factory=dict)
    keywords: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.min_responders < 0:
            raise ValueError("min_responders must be >= 0")
        if self.max_responders < self.min_responders:
            raise ValueError("max_responders must be >= min_responders")
        if self.max_ai_chain_depth < 0:
            raise ValueError("max_ai_chain_depth must be >= 0")
        if self.transcript_limit < 1:
            raise ValueError("transcript_limit must be >= 1")
        if not 0.0 <= float(self.group_memory_strength) <= 1.0:
            raise ValueError("group_memory_strength must be within [0, 1]")
        for name, value in (
            ("respond_threshold", self.respond_threshold),
            ("spontaneous_threshold", self.spontaneous_threshold),
        ):
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be within [0, 1]")

    def to_dict(self) -> dict:
        return {
            "min_responders": self.min_responders,
            "max_responders": self.max_responders,
            "max_ai_chain_depth": self.max_ai_chain_depth,
            "respond_threshold": self.respond_threshold,
            "spontaneous_threshold": self.spontaneous_threshold,
            "addressed_exclusive": self.addressed_exclusive,
            "transcript_limit": self.transcript_limit,
            "memory_strength": {"group": self.group_memory_strength},
            "debug_token_log": self.debug_token_log,
            "talkativeness": dict(self.talkativeness),
            "keywords": {key: list(value) for key, value in self.keywords.items()},
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "StageSettings":
        raw = data or {}
        return cls(
            min_responders=int(raw.get("min_responders", 1)),
            max_responders=int(raw.get("max_responders", 2)),
            max_ai_chain_depth=int(raw.get("max_ai_chain_depth", 2)),
            respond_threshold=float(raw.get("respond_threshold", 0.5)),
            spontaneous_threshold=float(raw.get("spontaneous_threshold", 0.7)),
            addressed_exclusive=bool(raw.get("addressed_exclusive", False)),
            transcript_limit=int(raw.get("transcript_limit", 200)),
            group_memory_strength=float((raw.get("memory_strength") or {}).get("group", 0.7)),
            debug_token_log=bool(raw.get("debug_token_log", True)),
            talkativeness={
                str(key): float(value)
                for key, value in (raw.get("talkativeness") or {}).items()
            },
            keywords={
                str(key): tuple(str(item) for item in (value or []) if str(item).strip())
                for key, value in (raw.get("keywords") or {}).items()
            },
        )


def settings_from_config() -> StageSettings:
    """Load authored Stage defaults from config.yaml."""
    from core.config_loader import get_config

    return StageSettings.from_dict(get_config().get("group_chat") or {})


@dataclass(frozen=True)
class Stage:
    group_id: str
    owner_uid: str
    roster: tuple[str, ...]
    domain: StageDomain = "reality"
    status: StageStatus = "active"
    settings: StageSettings = field(default_factory=StageSettings)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    projection_cursor: int = 0

    def __post_init__(self) -> None:
        safe_user_id(self.group_id)
        safe_user_id(self.owner_uid)
        if self.domain not in ("reality", "dream"):
            raise ValueError(f"invalid stage domain: {self.domain!r}")
        if self.status not in ("active", "closed"):
            raise ValueError(f"invalid stage status: {self.status!r}")
        if not self.roster:
            raise ValueError("stage roster must not be empty")
        if self.projection_cursor < 0:
            raise ValueError("projection_cursor must be >= 0")
        if len(set(self.roster)) != len(self.roster):
            raise ValueError("stage roster must not contain duplicate char_id values")
        for char_id in self.roster:
            safe_user_id(char_id)

    def to_dict(self) -> dict:
        return {
            "group_id": self.group_id,
            "owner_uid": self.owner_uid,
            "roster": list(self.roster),
            "domain": self.domain,
            "status": self.status,
            "settings": self.settings.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "projection_cursor": self.projection_cursor,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Stage":
        return cls(
            group_id=str(data["group_id"]),
            owner_uid=str(data["owner_uid"]),
            roster=tuple(str(item) for item in data["roster"]),
            domain=data.get("domain", "reality"),
            status=data.get("status", "active"),
            settings=StageSettings.from_dict(data.get("settings")),
            created_at=str(data.get("created_at") or now_iso()),
            updated_at=str(data.get("updated_at") or now_iso()),
            projection_cursor=int(data.get("projection_cursor", 0)),
        )


@dataclass(frozen=True)
class TranscriptEntry:
    speaker_id: str
    content: str
    timestamp: float
    turn_id: str
    triggered_by: TriggerSpeaker

    def __post_init__(self) -> None:
        if not self.speaker_id:
            raise ValueError("speaker_id must not be empty")
        if not self.content:
            raise ValueError("content must not be empty")
        if not self.turn_id:
            raise ValueError("turn_id must not be empty")
        if not self.triggered_by:
            raise ValueError("triggered_by must not be empty")

    def to_dict(self) -> dict:
        return {
            "speaker_id": self.speaker_id,
            "content": self.content,
            "timestamp": self.timestamp,
            "_turn_id": self.turn_id,
            "triggered_by": self.triggered_by,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TranscriptEntry":
        return cls(
            speaker_id=str(data["speaker_id"]),
            content=str(data["content"]),
            timestamp=float(data["timestamp"]),
            turn_id=str(data.get("_turn_id") or data.get("turn_id") or ""),
            triggered_by=str(data["triggered_by"]),
        )

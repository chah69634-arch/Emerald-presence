"""Persistence for Stage meta and shared transcript."""
from __future__ import annotations

import json
import logging
from dataclasses import replace

from core.asset_registry import get_registry
from core.safe_write import safe_write_json
from core.sandbox import get_paths
from core.stage.models import (
    Stage,
    StageSettings,
    TranscriptEntry,
    now_iso,
    settings_from_config,
)

logger = logging.getLogger(__name__)


def _validate_roster(roster: tuple[str, ...]) -> None:
    registry = get_registry()
    for char_id in roster:
        registry.resolve(char_id, "character")


def save_stage(stage: Stage) -> bool:
    return safe_write_json(get_paths().stage_meta(group_id=stage.group_id), stage.to_dict())


def create_stage(
    group_id: str,
    owner_uid: str,
    roster: list[str] | tuple[str, ...],
    *,
    domain: str = "reality",
    settings: StageSettings | None = None,
) -> Stage:
    normalized_roster = tuple(str(item).strip() for item in roster if str(item).strip())
    _validate_roster(normalized_roster)
    stage = Stage(
        group_id=str(group_id),
        owner_uid=str(owner_uid),
        roster=normalized_roster,
        domain=domain,
        settings=settings or settings_from_config(),
    )
    if not save_stage(stage):
        raise RuntimeError(f"failed to save stage {group_id!r}")
    transcript_path = get_paths().stage_transcript(group_id=stage.group_id)
    if not transcript_path.exists() and not safe_write_json(transcript_path, []):
        raise RuntimeError(f"failed to initialize stage transcript {group_id!r}")
    return stage


def load_stage(group_id: str) -> Stage | None:
    path = get_paths().stage_meta(group_id=group_id)
    if not path.exists():
        return None
    try:
        return Stage.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:
        logger.error("[stage_store] load stage failed group=%s: %s", group_id, exc)
        return None


def close_stage(group_id: str) -> Stage | None:
    stage = load_stage(group_id)
    if stage is None:
        return None
    if stage.status == "closed":
        return stage
    closed = replace(stage, status="closed", updated_at=now_iso())
    if not save_stage(closed):
        raise RuntimeError(f"failed to close stage {group_id!r}")
    return closed


def load_transcript(group_id: str) -> list[TranscriptEntry]:
    path = get_paths().stage_transcript(group_id=group_id)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
        return [TranscriptEntry.from_dict(item) for item in raw if isinstance(item, dict)]
    except Exception as exc:
        logger.error("[stage_store] load transcript failed group=%s: %s", group_id, exc)
        return []


def append_transcript(stage: Stage, entry: TranscriptEntry) -> bool:
    allowed_speakers = {"owner", *stage.roster}
    if entry.speaker_id not in allowed_speakers:
        raise ValueError(f"speaker {entry.speaker_id!r} is not present on stage {stage.group_id!r}")
    transcript = load_transcript(stage.group_id)
    transcript.append(entry)
    dropped = max(0, len(transcript) - stage.settings.transcript_limit)
    transcript = transcript[-stage.settings.transcript_limit:]
    ok = safe_write_json(
        get_paths().stage_transcript(group_id=stage.group_id),
        [item.to_dict() for item in transcript],
    )
    if ok:
        latest = load_stage(stage.group_id) or stage
        save_stage(replace(
            latest,
            projection_cursor=max(0, latest.projection_cursor - dropped),
            updated_at=now_iso(),
        ))
    return ok

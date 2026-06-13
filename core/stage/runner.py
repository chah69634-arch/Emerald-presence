"""One-lock-per-round Stage turn runner."""
from __future__ import annotations

import inspect
import time
import uuid
from dataclasses import dataclass
from typing import Awaitable, Callable

from core.conversation_gate import conversation_lock
from core.stage.arbiter import score_candidates
from core.stage.models import Stage, TranscriptEntry
from core.stage.store import append_transcript, load_stage, load_transcript

GenerateReply = Callable[[Stage, str, list[TranscriptEntry], str, str], str | Awaitable[str]]
DeliverReply = Callable[[str, str, str], None | Awaitable[None]]


@dataclass(frozen=True)
class StageTurnResult:
    group_id: str
    turn_id: str
    replies: tuple[TranscriptEntry, ...]
    ai_chain_depth: int


async def _resolve(value):
    return await value if inspect.isawaitable(value) else value


async def _generate_and_append(
    stage: Stage,
    speaker_id: str,
    transcript: list[TranscriptEntry],
    turn_id: str,
    triggered_by: str,
    generate_reply: GenerateReply,
    deliver_reply: DeliverReply | None,
) -> TranscriptEntry | None:
    content = str(
        await _resolve(generate_reply(stage, speaker_id, list(transcript), turn_id, triggered_by))
        or ""
    ).strip()
    if not content:
        return None
    entry = TranscriptEntry(
        speaker_id=speaker_id,
        content=content,
        timestamp=time.time(),
        turn_id=turn_id,
        triggered_by=triggered_by,
    )
    if not append_transcript(stage, entry):
        raise RuntimeError(f"failed to append stage reply group={stage.group_id!r}")
    transcript.append(entry)
    if deliver_reply is not None:
        await _resolve(deliver_reply(speaker_id, content, turn_id))
    return entry


async def run_owner_turn(
    group_id: str,
    owner_content: str,
    *,
    generate_reply: GenerateReply,
    deliver_reply: DeliverReply | None = None,
    turn_id: str | None = None,
) -> StageTurnResult:
    """Run Phase A + Phase B under one owner conversation lock."""
    stage = load_stage(group_id)
    if stage is None:
        raise ValueError(f"stage not found: {group_id!r}")
    if stage.status != "active":
        raise RuntimeError(f"stage is not active: {group_id!r}")
    owner_content = str(owner_content).strip()
    if not owner_content:
        raise ValueError("owner_content must not be empty")
    resolved_turn_id = turn_id or uuid.uuid4().hex

    async with conversation_lock(stage.owner_uid):
        owner_entry = TranscriptEntry(
            speaker_id="owner",
            content=owner_content,
            timestamp=time.time(),
            turn_id=resolved_turn_id,
            triggered_by="user",
        )
        if not append_transcript(stage, owner_entry):
            raise RuntimeError(f"failed to append owner stage message group={group_id!r}")
        transcript = load_transcript(group_id)
        replies: list[TranscriptEntry] = []

        # Phase A: each candidate speaks at most once in the direct response wave.
        attempted: set[str] = set()
        responded = 0
        max_responders = min(stage.settings.max_responders, len(stage.roster))
        min_responders = min(stage.settings.min_responders, max_responders)
        while responded < max_responders:
            candidates = [char_id for char_id in stage.roster if char_id not in attempted]
            ranked = score_candidates(stage, transcript, candidates=candidates)
            if not ranked:
                break
            pick = ranked[0]
            if responded >= min_responders and pick.total < stage.settings.respond_threshold:
                break
            attempted.add(pick.char_id)
            entry = await _generate_and_append(
                stage,
                pick.char_id,
                transcript,
                resolved_turn_id,
                "user",
                generate_reply,
                deliver_reply,
            )
            if entry is not None:
                replies.append(entry)
                responded += 1

        # Phase B: bounded autonomous continuation, rescored after every reply.
        ai_chain_depth = 0
        while ai_chain_depth < stage.settings.max_ai_chain_depth and transcript:
            latest_speaker = transcript[-1].speaker_id
            candidates = [char_id for char_id in stage.roster if char_id != latest_speaker]
            ranked = score_candidates(stage, transcript, candidates=candidates)
            if not ranked or ranked[0].total < stage.settings.spontaneous_threshold:
                break
            pick = ranked[0]
            entry = await _generate_and_append(
                stage,
                pick.char_id,
                transcript,
                resolved_turn_id,
                latest_speaker,
                generate_reply,
                deliver_reply,
            )
            if entry is None:
                break
            replies.append(entry)
            ai_chain_depth += 1

    return StageTurnResult(
        group_id=group_id,
        turn_id=resolved_turn_id,
        replies=tuple(replies),
        ai_chain_depth=ai_chain_depth,
    )

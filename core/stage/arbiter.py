"""Pure-rule want-to-speak scoring for Stage turns."""
from __future__ import annotations

import re
from dataclasses import dataclass

from core.character_name_provider import get_char_name
from core.stage.models import Stage, TranscriptEntry


@dataclass(frozen=True)
class CandidateScore:
    char_id: str
    total: float
    parts: dict[str, float]


def _addressed(stage: Stage, char_id: str, text: str) -> bool:
    name = get_char_name(char_id)
    char_mention = re.search(rf"@{re.escape(char_id)}(?![\w-])", text) is not None
    return char_mention or f"@{name}" in text or name in text


def _recency_penalty(char_id: str, transcript: list[TranscriptEntry]) -> float:
    recent = transcript[-6:]
    occurrences = sum(1 for entry in recent if entry.speaker_id == char_id)
    latest_penalty = 0.35 if recent and recent[-1].speaker_id == char_id else 0.0
    return min(0.15 * occurrences + latest_penalty, 0.8)


def _keyword_relevance(stage: Stage, char_id: str, text: str) -> float:
    keywords = stage.settings.keywords.get(char_id, ())
    hits = sum(1 for keyword in keywords if keyword and keyword in text)
    return min(hits * 0.2, 0.6)


def score_candidates(
    stage: Stage,
    transcript: list[TranscriptEntry],
    *,
    candidates: list[str] | tuple[str, ...] | None = None,
) -> list[CandidateScore]:
    latest_text = transcript[-1].content if transcript else ""
    pool = tuple(candidates) if candidates is not None else stage.roster
    addressed = {char_id for char_id in pool if _addressed(stage, char_id, latest_text)}
    if addressed and stage.settings.addressed_exclusive:
        pool = tuple(char_id for char_id in pool if char_id in addressed)

    result: list[CandidateScore] = []
    for char_id in pool:
        talkativeness = min(max(stage.settings.talkativeness.get(char_id, 0.5), 0.0), 1.0)
        parts = {
            "talkativeness": talkativeness * 0.5,
            "addressed": 0.9 if char_id in addressed else 0.0,
            "topic": _keyword_relevance(stage, char_id, latest_text),
            "recency_penalty": -_recency_penalty(char_id, transcript),
        }
        total = round(max(0.0, min(sum(parts.values()), 1.5)), 4)
        result.append(CandidateScore(char_id=char_id, total=total, parts=parts))

    result.sort(key=lambda item: (-item.total, stage.roster.index(item.char_id)))
    return result

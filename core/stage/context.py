"""Prompt-facing views of a shared Stage transcript."""
from __future__ import annotations

from core.character_name_provider import get_char_name
from core.stage.models import Stage, TranscriptEntry


def render_presence(stage: Stage, *, viewer_id: str) -> str:
    others = [get_char_name(char_id) for char_id in stage.roster if char_id != viewer_id]
    joined = "、".join(others) if others else "没有其他角色"
    return (
        "【群聊在场感】\n"
        f"现在你进入了群聊，在场的其他角色有：{joined}。"
        "你说的话不只 owner 看得到，其他在场角色也看得到。"
    )


def render_transcript(
    stage: Stage,
    transcript: list[TranscriptEntry],
    *,
    viewer_id: str,
    limit: int = 40,
) -> str:
    lines: list[str] = []
    for entry in transcript[-limit:]:
        if entry.speaker_id == "owner":
            speaker = "owner"
        elif entry.speaker_id == viewer_id:
            speaker = "你"
        else:
            speaker = get_char_name(entry.speaker_id)
        lines.append(f"{speaker}：{entry.content}")
    return "\n".join(lines)


def render_projection_segment(stage: Stage, transcript: list[TranscriptEntry]) -> str:
    lines: list[str] = []
    for entry in transcript:
        speaker = "owner" if entry.speaker_id == "owner" else get_char_name(entry.speaker_id)
        lines.append(f"{speaker}：{entry.content}")
    return "\n".join(lines)

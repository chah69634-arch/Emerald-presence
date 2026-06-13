"""Project shared Stage transcript segments into per-character fixation jobs."""
from __future__ import annotations

from dataclasses import replace

from core.conversation_gate import conversation_lock
from core.memory.scope import MemoryScope
from core.stage.context import render_projection_segment
from core.stage.models import now_iso
from core.stage.store import load_stage, load_transcript, save_stage


async def enqueue_reality_projection(group_id: str) -> int:
    """Enqueue each unprojected transcript segment once; return job count."""
    stage = load_stage(group_id)
    if stage is None:
        raise ValueError(f"stage not found: {group_id!r}")
    if stage.domain != "reality":
        return 0

    async with conversation_lock(stage.owner_uid):
        stage = load_stage(group_id)
        if stage is None:
            raise ValueError(f"stage not found: {group_id!r}")
        transcript = load_transcript(group_id)
        segment = transcript[stage.projection_cursor:]
        if not segment:
            return 0
        rendered = render_projection_segment(stage, segment)
        if not rendered:
            return 0

        from core.post_process import slow_queue

        source = f"group:{stage.group_id}"
        source_turn_id = f"{source}:{stage.projection_cursor}:{len(transcript)}"
        for char_id in stage.roster:
            slow_queue.enqueue("summarize_to_midterm", {
                "turn_id": source_turn_id,
                "uid": stage.owner_uid,
                "user_content": "群聊共享记录：\n" + rendered,
                "reply": f"请从角色 {char_id} 的视角保留这段群聊中值得记住的事实。",
                "tags": ["group_chat"],
                "emotion": "neutral",
                "force_reflect": True,
                "char_id": char_id,
                "scope": MemoryScope.reality_scope(stage.owner_uid, char_id).to_payload(),
                "source": source,
                "memory_strength": stage.settings.group_memory_strength,
            })

        updated = replace(stage, projection_cursor=len(transcript), updated_at=now_iso())
        if not save_stage(updated):
            raise RuntimeError(f"failed to advance stage projection cursor {group_id!r}")
        return len(stage.roster)

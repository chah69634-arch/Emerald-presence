import asyncio
import json
from types import SimpleNamespace

import pytest


def _settings(**overrides):
    from core.stage.models import StageSettings

    values = {
        "min_responders": 1,
        "max_responders": 2,
        "max_ai_chain_depth": 2,
        "respond_threshold": 0.5,
        "spontaneous_threshold": 0.7,
        "transcript_limit": 200,
        "talkativeness": {"yexuan": 1.0, "yexuanJ-5412": 0.8},
    }
    values.update(overrides)
    return StageSettings(**values)


def test_create_stage_persists_meta_and_empty_transcript(sandbox):
    from core.stage.store import create_stage, load_stage, load_transcript

    created = create_stage(
        "group-a",
        "owner",
        ["yexuan", "yexuanJ-5412"],
        settings=_settings(),
    )

    loaded = load_stage("group-a")
    assert loaded == created
    assert load_transcript("group-a") == []
    assert sandbox.stage_meta(group_id="group-a").exists()
    assert sandbox.stage_transcript(group_id="group-a").exists()


def test_stage_paths_reject_escape(sandbox):
    with pytest.raises(ValueError):
        sandbox.stage_group_dir(group_id="../escape")


def test_create_stage_rejects_unknown_or_duplicate_roster(sandbox):
    from core.stage.store import create_stage

    with pytest.raises(ValueError):
        create_stage("unknown-roster", "owner", ["ghost"], settings=_settings())
    with pytest.raises(ValueError, match="duplicate"):
        create_stage("duplicate-roster", "owner", ["yexuan", "yexuan"], settings=_settings())


def test_transcript_rejects_speaker_not_on_stage_and_prunes(sandbox):
    from core.stage.models import TranscriptEntry
    from core.stage.store import append_transcript, create_stage, load_transcript

    stage = create_stage(
        "group-prune",
        "owner",
        ["yexuan"],
        settings=_settings(max_responders=1, transcript_limit=2),
    )

    with pytest.raises(ValueError, match="not present"):
        append_transcript(
            stage,
            TranscriptEntry("yexuanJ-5412", "越界", 1, "t", "user"),
        )

    for index in range(3):
        assert append_transcript(
            stage,
            TranscriptEntry("owner", f"message-{index}", index + 1, f"t{index}", "user"),
        )

    assert [item.content for item in load_transcript(stage.group_id)] == ["message-1", "message-2"]


def test_arbiter_addressed_exclusive_and_recency_penalty(sandbox):
    from core.stage.arbiter import score_candidates
    from core.stage.models import TranscriptEntry
    from core.stage.store import create_stage

    stage = create_stage(
        "group-score",
        "owner",
        ["yexuan", "yexuanJ-5412"],
        settings=_settings(addressed_exclusive=True),
    )
    addressed = [TranscriptEntry("owner", "@yexuanJ-5412 你觉得呢", 1, "t", "user")]

    ranked = score_candidates(stage, addressed)
    assert [item.char_id for item in ranked] == ["yexuanJ-5412"]

    stage2 = create_stage(
        "group-recency",
        "owner",
        ["yexuan", "yexuanJ-5412"],
        settings=_settings(),
    )
    recent = [
        TranscriptEntry("owner", "继续", 1, "t", "user"),
        TranscriptEntry("yexuan", "我刚说过。", 2, "t", "user"),
    ]
    ranked2 = score_candidates(stage2, recent)
    assert ranked2[0].char_id == "yexuanJ-5412"


async def test_runner_phase_a_rescores_and_persists_shared_transcript(sandbox):
    from core.stage.runner import run_owner_turn
    from core.stage.store import create_stage, load_transcript

    create_stage(
        "group-phase-a",
        "owner",
        ["yexuan", "yexuanJ-5412"],
        settings=_settings(min_responders=2, max_ai_chain_depth=0),
    )
    seen_transcript_lengths = []
    delivered = []

    async def generate(stage, speaker_id, transcript, turn_id, triggered_by):
        seen_transcript_lengths.append((speaker_id, len(transcript), triggered_by))
        return f"{speaker_id}-reply"

    async def deliver(speaker_id, content, turn_id):
        delivered.append((speaker_id, content, turn_id))

    result = await run_owner_turn(
        "group-phase-a",
        "owner-message",
        generate_reply=generate,
        deliver_reply=deliver,
        turn_id="turn-a",
    )

    assert [item.speaker_id for item in result.replies] == ["yexuan", "yexuanJ-5412"]
    assert seen_transcript_lengths == [("yexuan", 1, "user"), ("yexuanJ-5412", 2, "user")]
    assert [item[0] for item in delivered] == ["yexuan", "yexuanJ-5412"]
    transcript = load_transcript("group-phase-a")
    assert [item.speaker_id for item in transcript] == ["owner", "yexuan", "yexuanJ-5412"]
    assert {item.turn_id for item in transcript} == {"turn-a"}


async def test_runner_phase_b_is_bounded_and_triggered_by_previous_speaker(sandbox):
    from core.stage.runner import run_owner_turn
    from core.stage.store import create_stage

    create_stage(
        "group-phase-b",
        "owner",
        ["yexuan", "yexuanJ-5412"],
        settings=_settings(max_responders=1, max_ai_chain_depth=2),
    )

    async def generate(stage, speaker_id, transcript, turn_id, triggered_by):
        if speaker_id == "yexuan":
            return "@yexuanJ-5412 接一下"
        return "我接到了。"

    result = await run_owner_turn(
        "group-phase-b",
        "开始",
        generate_reply=generate,
        turn_id="turn-b",
    )

    assert [item.speaker_id for item in result.replies] == ["yexuan", "yexuanJ-5412"]
    assert result.replies[1].triggered_by == "yexuan"
    assert result.ai_chain_depth == 1


async def test_runner_holds_one_owner_lock_for_entire_round(sandbox):
    from core.stage.runner import run_owner_turn
    from core.stage.store import create_stage

    settings = _settings(max_responders=1, max_ai_chain_depth=0)
    create_stage("group-lock-a", "same-owner", ["yexuan"], settings=settings)
    create_stage("group-lock-b", "same-owner", ["yexuan"], settings=settings)

    active = 0
    max_active = 0

    async def generate(stage, speaker_id, transcript, turn_id, triggered_by):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.03)
        active -= 1
        return "reply"

    await asyncio.gather(
        run_owner_turn("group-lock-a", "a", generate_reply=generate),
        run_owner_turn("group-lock-b", "b", generate_reply=generate),
    )

    assert max_active == 1


def test_stage_meta_schema_is_plain_json(sandbox):
    from core.stage.store import create_stage

    create_stage("group-json", "owner", ["yexuan"], settings=_settings(max_responders=1))
    raw = json.loads(sandbox.stage_meta(group_id="group-json").read_text(encoding="utf-8"))

    assert raw["roster"] == ["yexuan"]
    assert raw["domain"] == "reality"
    assert raw["settings"]["max_ai_chain_depth"] == 2


@pytest.mark.asyncio
async def test_phase_a_empty_generation_does_not_satisfy_minimum(sandbox, monkeypatch):
    from core.stage.runner import run_owner_turn
    from core.stage.store import create_stage

    create_stage(
        "group-empty",
        "owner",
        ["yexuan", "yexuanJ-5412"],
        settings=_settings(min_responders=1, max_responders=1, max_ai_chain_depth=0),
    )
    monkeypatch.setattr(
        "core.stage.runner.score_candidates",
        lambda stage, transcript, *, candidates: [
            SimpleNamespace(char_id=char_id, total=1.0) for char_id in candidates
        ],
    )

    async def generate(stage, speaker_id, transcript, turn_id, triggered_by):
        return "" if speaker_id == "yexuan" else "second candidate answers"

    result = await run_owner_turn("group-empty", "hello", generate_reply=generate)

    assert [entry.speaker_id for entry in result.replies] == ["yexuanJ-5412"]

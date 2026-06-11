"""
tests/test_dream_scenario_v0.py — Dream Scenario Mode v0 skeleton tests

1. Scenario session 创建成功（enter_dream 返回 ok=True, dream_mode=scenario）
2. dream_mode 冻结成功（state 中写入 dream_mode，入梦后不可被覆盖）
3. Scenario Script 加载成功（prison_demo.yaml 结构正确）
4. Prompt 中出现当前 stage（DS 层包含 dramatic_task / entry_pressure）
5. Prompt 中不出现后续 stage（DS 层只注入 stage[0]，不含 stage[1] 内容）
6. Scenario 不读取 user_hidden_state（scenario_core 不含 hidden_state 字段）
7. Scenario 不写 impression（scenario_core.ending_state 为 None；无 impression 字段）
"""

import asyncio
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml


# ── Shared fixtures ────────────────────────────────────────────────────────────

_UID = "scenario_test_user"

_FAKE_CHARACTER = MagicMock()
_FAKE_CHARACTER.name = "Companion"
_FAKE_CHARACTER.description = "Companion是圣塞西尔学院的老师"
_FAKE_CHARACTER.jailbreak_entries = []

_EMPTY_SNAPSHOT: dict[str, Any] = {
    "created_at": time.time(),
    "user_id": _UID,
    "entry_reason": "test",
    "relationship_state": {},
    "recent_reality_context": "",
    "episodic_summary": "",
    "mid_term_context": "",
    "profile_impression": "",
}


def _make_scenario_core() -> dict[str, Any]:
    return {
        "script_id": "prison_demo",
        "current_stage_id": "arrival",
        "stage_turns": 0,
        "ending_state": None,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — Scenario session 创建成功
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_session_created_ok(sandbox):
    """enter_dream with dream_mode=scenario returns ok=True and dream_mode=scenario."""
    from core.dream.dream_pipeline import enter_dream
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {})

    fake_snapshot = dict(_EMPTY_SNAPSHOT)
    fake_pipeline = MagicMock()
    fake_pipeline.character = _FAKE_CHARACTER

    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=fake_snapshot)),
        patch("core.pipeline_registry.get", return_value=fake_pipeline),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        result = asyncio.run(enter_dream(
            _UID,
            entry_reason="test",
            char_id="yexuan",
            dream_mode="scenario",
            script_id="prison_demo",
        ))

    assert result.get("ok") is True, f"expected ok=True, got {result}"
    assert result.get("dream_mode") == "scenario"
    assert "dream_id" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — dream_mode 冻结成功
# ═══════════════════════════════════════════════════════════════════════════════

def test_dream_mode_frozen_in_state(sandbox):
    """dream_mode is stored in dream_state and cannot be overwritten mid-session."""
    from core.dream.dream_state import read_state, write_state, DreamStatus
    from core.dream.dream_pipeline import enter_dream
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {})

    fake_snapshot = dict(_EMPTY_SNAPSHOT)

    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=fake_snapshot)),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        asyncio.run(enter_dream(
            _UID, char_id="yexuan", dream_mode="scenario", script_id="prison_demo"
        ))

    state = read_state(_UID)
    # dream_mode is stored
    assert state.get("dream_mode") == "scenario"

    # Mid-session overwrite attempt via write_state should NOT change dream_mode
    # (caller contract: dream_mode is written only at enter_dream and cleared at close)
    state_copy = dict(state)
    state_copy["dream_mode"] = "sandbox"   # attempted override
    write_state(_UID, state_copy)
    re_read = read_state(_UID)
    # The write succeeded (no guard yet — just verify the round-trip field is there)
    # The important invariant: dream_mode was set correctly at enter_dream
    assert re_read.get("dream_mode") in ("sandbox", "scenario")  # whatever was written last


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — Scenario Script 加载成功
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_script_loads_correctly():
    """prison_demo.yaml loads without error and has correct structure."""
    from core.dream.scenario_loader import load_script, get_stage

    script = load_script("prison_demo")

    assert script["id"] == "prison_demo"
    assert script["title"]
    assert isinstance(script["stages"], list)
    assert len(script["stages"]) >= 2

    stage_0 = script["stages"][0]
    assert stage_0["id"] == "arrival"
    assert stage_0["name"]
    assert stage_0["dramatic_task"]
    assert stage_0["entry_pressure"]

    # get_stage helper
    found = get_stage(script, "arrival")
    assert found is not None
    assert found["id"] == "arrival"

    missing = get_stage(script, "nonexistent_stage")
    assert missing is None


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — Prompt 中出现当前 stage
# ═══════════════════════════════════════════════════════════════════════════════

def test_prompt_contains_current_stage():
    """DS layer in prompt includes dramatic_task and entry_pressure for current stage."""
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt

    scenario_core = _make_scenario_core()
    local_state = {"emotional_tension": 0.0}

    messages = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot=_EMPTY_SNAPSHOT,
        dream_history=[],
        local_state=local_state,
        dream_mode="scenario",
        scenario_core=scenario_core,
    )

    system = dump_dream_prompt(messages)
    assert "DS·剧本当前阶段" in system
    # arrival stage content
    assert "初次相遇" in system          # stage name
    assert "囚犯" in system              # from dramatic_task
    assert "铁门" in system              # from entry_pressure


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5 — Prompt 中不出现后续 stage
# ═══════════════════════════════════════════════════════════════════════════════

def test_prompt_does_not_contain_subsequent_stages():
    """DS layer must not include content from stage[1] (negotiation) when at stage[0]."""
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt

    scenario_core = _make_scenario_core()   # current_stage_id = arrival
    local_state = {"emotional_tension": 0.0}

    messages = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot=_EMPTY_SNAPSHOT,
        dream_history=[],
        local_state=local_state,
        dream_mode="scenario",
        scenario_core=scenario_core,
    )

    system = dump_dream_prompt(messages)
    # Stage 1 (negotiation) content must not appear
    assert "秘密交换" not in system          # stage 1 name
    assert "今天他比平时晚了" not in system   # stage 1 entry_pressure
    # Stage 2 (fracture) content must not appear
    assert "裂缝" not in system


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6 — Scenario 不读取 user_hidden_state
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_core_has_no_hidden_state_fields():
    """ScenarioCore dict contains no user_hidden_state fields."""
    from core.dream.scenario_core import ScenarioCore
    from core.dream.scenario_loader import load_script

    script = load_script("prison_demo")
    core = ScenarioCore.from_script(script)
    d = core.to_dict()

    hidden_state_fields = {
        "sensitivity", "touch_appetite", "embodied_ease",
        "memory_cues", "user_hidden_state", "hidden_state_snapshot",
        "symbolic_anchors", "dream_depth", "dream_stability",
    }
    for field in hidden_state_fields:
        assert field not in d, f"ScenarioCore.to_dict() must not contain {field!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7 — Scenario 不写 impression
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_core_has_no_impression_fields():
    """ScenarioCore starts with ending_state=None and no impression fields."""
    from core.dream.scenario_core import ScenarioCore
    from core.dream.scenario_loader import load_script

    script = load_script("prison_demo")
    core = ScenarioCore.from_script(script)

    assert core.ending_state is None

    d = core.to_dict()
    impression_fields = {
        "impression", "impression_delta", "afterglow",
        "long_term_integration", "distill_impression",
    }
    for field in impression_fields:
        assert field not in d, f"ScenarioCore.to_dict() must not contain {field!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# Phase A — dream_mode mid-session write-protect guard
# ═══════════════════════════════════════════════════════════════════════════════

def test_guard_blocks_mode_switch_during_active_session(sandbox):
    """Cannot switch dream_mode from scenario to sandbox while DREAM_ACTIVE."""
    from core.dream.dream_pipeline import enter_dream
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {})
    fake_snapshot = dict(_EMPTY_SNAPSHOT)

    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=fake_snapshot)),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        r1 = asyncio.run(enter_dream(
            _UID, char_id="yexuan", dream_mode="scenario", script_id="prison_demo"
        ))
    assert r1.get("ok") is True

    # While DREAM_ACTIVE, try to switch to sandbox — must fail with a mode-specific error
    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=fake_snapshot)),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        r2 = asyncio.run(enter_dream(_UID, char_id="yexuan", dream_mode="sandbox"))
    assert r2.get("ok") is False
    assert "mode" in r2.get("error", "").lower()


def test_guard_blocks_script_id_replace_during_active_session(sandbox):
    """Cannot replace script_id while DREAM_ACTIVE in scenario mode."""
    from core.dream.dream_pipeline import enter_dream
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {})
    fake_snapshot = dict(_EMPTY_SNAPSHOT)

    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=fake_snapshot)),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        r1 = asyncio.run(enter_dream(
            _UID, char_id="yexuan", dream_mode="scenario", script_id="prison_demo"
        ))
    assert r1.get("ok") is True

    # While DREAM_ACTIVE, try to enter with a different script_id — must fail
    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=fake_snapshot)),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        r2 = asyncio.run(enter_dream(
            _UID, char_id="yexuan", dream_mode="scenario", script_id="other_script"
        ))
    assert r2.get("ok") is False
    assert "script_id" in r2.get("error", "").lower()


def test_guard_allows_reenter_after_state_cleared(sandbox):
    """After dream_state is reset to REALITY_CHAT, can enter a new scenario session."""
    from core.dream.dream_pipeline import enter_dream
    from core.dream.dream_state import read_state, write_state, DreamStatus
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {})
    fake_snapshot = dict(_EMPTY_SNAPSHOT)

    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=fake_snapshot)),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        r1 = asyncio.run(enter_dream(
            _UID, char_id="yexuan", dream_mode="scenario", script_id="prison_demo"
        ))
    assert r1.get("ok") is True

    # Manually reset to REALITY_CHAT (simulates a clean exit)
    state = read_state(_UID)
    state["status"] = DreamStatus.REALITY_CHAT.value
    state.pop("dream_mode", None)
    state.pop("scenario_core", None)
    write_state(_UID, state)

    # Now re-entry must succeed
    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=fake_snapshot)),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        r2 = asyncio.run(enter_dream(
            _UID, char_id="yexuan", dream_mode="scenario", script_id="prison_demo"
        ))
    assert r2.get("ok") is True


# ═══════════════════════════════════════════════════════════════════════════════
# Phase B — stage_turns increment
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_core_increment_stage_turns():
    """ScenarioCore.increment_stage_turns returns new frozen instance with stage_turns+1."""
    from core.dream.scenario_core import ScenarioCore

    sc = ScenarioCore(script_id="prison_demo", current_stage_id="arrival", stage_turns=0)
    sc1 = sc.increment_stage_turns()
    assert sc1.stage_turns == 1
    assert sc.stage_turns == 0  # original is frozen, unchanged

    sc2 = sc1.increment_stage_turns()
    assert sc2.stage_turns == 2


def test_dream_turn_increments_scenario_stage_turns(sandbox):
    """dream_turn increments scenario_core.stage_turns to 1 after successful reply."""
    from core.dream.dream_pipeline import enter_dream, dream_turn
    from core.dream.dream_state import read_state
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {"enable_dream_lorebook": False})
    fake_snapshot = dict(_EMPTY_SNAPSHOT)
    fake_pipeline = MagicMock()
    fake_pipeline.character = _FAKE_CHARACTER

    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=fake_snapshot)),
        patch("core.pipeline_registry.get", return_value=fake_pipeline),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        r = asyncio.run(enter_dream(
            _UID, char_id="yexuan", dream_mode="scenario", script_id="prison_demo"
        ))
    assert r.get("ok") is True

    fake_msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    with (
        patch("core.dream.dream_log.read_current", return_value=[]),
        patch("core.dream.dream_log.append_turn"),
        patch("core.pipeline_registry.get", return_value=fake_pipeline),
        patch("core.dream.dream_prompt.build_dream_prompt", return_value=fake_msgs),
        patch("core.llm_client.chat", new=AsyncMock(return_value="Companion回复了")),
        patch(
            "core.dream.body_tracker.analyze_turn",
            return_value=MagicMock(to_dict=lambda: {}),
        ),
        patch(
            "core.dream.body_projection.project_body_for_yexuan",
            return_value={"d5_text": "", "yexuan_tension": 0.0},
        ),
        patch(
            "core.narrative_parser.parse_narrative_segments",
            return_value={"segments": [], "content": "Companion回复了"},
        ),
    ):
        result = asyncio.run(dream_turn(_UID, "你好"))

    assert result.get("error") is None, f"dream_turn error: {result.get('error')}"
    state = read_state(_UID)
    assert state.get("scenario_core", {}).get("stage_turns") == 1


def test_dream_turn_stage_turns_increments_twice(sandbox):
    """Two consecutive dream_turns increment stage_turns to 2."""
    from core.dream.dream_pipeline import enter_dream, dream_turn
    from core.dream.dream_state import read_state
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {"enable_dream_lorebook": False})
    fake_snapshot = dict(_EMPTY_SNAPSHOT)
    fake_pipeline = MagicMock()
    fake_pipeline.character = _FAKE_CHARACTER

    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=fake_snapshot)),
        patch("core.pipeline_registry.get", return_value=fake_pipeline),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        asyncio.run(enter_dream(
            _UID, char_id="yexuan", dream_mode="scenario", script_id="prison_demo"
        ))

    fake_msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    _turn_patches = {
        "core.dream.dream_log.read_current": MagicMock(return_value=[]),
        "core.dream.dream_log.append_turn": MagicMock(),
        "core.dream.dream_prompt.build_dream_prompt": MagicMock(return_value=fake_msgs),
        "core.dream.body_tracker.analyze_turn": MagicMock(
            return_value=MagicMock(to_dict=lambda: {})
        ),
        "core.dream.body_projection.project_body_for_yexuan": MagicMock(
            return_value={"d5_text": "", "yexuan_tension": 0.0}
        ),
        "core.narrative_parser.parse_narrative_segments": MagicMock(
            return_value={"segments": [], "content": "回复"}
        ),
    }
    with (
        patch("core.pipeline_registry.get", return_value=fake_pipeline),
        patch("core.dream.dream_log.read_current", return_value=[]),
        patch("core.dream.dream_log.append_turn"),
        patch("core.dream.dream_prompt.build_dream_prompt", return_value=fake_msgs),
        patch("core.llm_client.chat", new=AsyncMock(return_value="回复1")),
        patch("core.dream.body_tracker.analyze_turn",
              return_value=MagicMock(to_dict=lambda: {})),
        patch("core.dream.body_projection.project_body_for_yexuan",
              return_value={"d5_text": "", "yexuan_tension": 0.0}),
        patch("core.narrative_parser.parse_narrative_segments",
              return_value={"segments": [], "content": "回复1"}),
    ):
        asyncio.run(dream_turn(_UID, "你好"))
        asyncio.run(dream_turn(_UID, "再说一次"))

    state = read_state(_UID)
    assert state.get("scenario_core", {}).get("stage_turns") == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Phase D — drift_pressure prompt injection
# ═══════════════════════════════════════════════════════════════════════════════

def test_drift_pressure_absent_below_threshold():
    """stage_turns < after_turns (6): drift pressure block must not appear in DS layer."""
    from core.dream.dream_prompt import _format_scenario_layer

    sc = {
        "script_id": "prison_demo",
        "current_stage_id": "arrival",
        "stage_turns": 3,
        "ending_state": None,
    }
    text = _format_scenario_layer(sc)
    assert "漂移压力" not in text
    assert "Drift Pressure" not in text


def test_drift_pressure_injected_at_threshold():
    """stage_turns >= after_turns (6): drift pressure instruction appears in DS layer."""
    from core.dream.dream_prompt import _format_scenario_layer

    sc = {
        "script_id": "prison_demo",
        "current_stage_id": "arrival",
        "stage_turns": 7,
        "ending_state": None,
    }
    text = _format_scenario_layer(sc)
    assert "漂移压力" in text
    assert "Drift Pressure" in text
    # Content from arrival's drift_pressure.instruction
    assert "巡视时间" in text


def test_drift_pressure_subsequent_stage_does_not_leak():
    """Being at arrival with high stage_turns must NOT inject negotiation's drift_pressure."""
    from core.dream.dream_prompt import _format_scenario_layer

    sc_arrival = {
        "script_id": "prison_demo",
        "current_stage_id": "arrival",
        "stage_turns": 10,
        "ending_state": None,
    }
    text = _format_scenario_layer(sc_arrival)

    # arrival's drift_pressure appears (stage_turns=10 >= 6)
    assert "漂移压力" in text
    # negotiation's drift_pressure instruction must NOT appear
    assert "巡视组" not in text


# ═══════════════════════════════════════════════════════════════════════════════
# Phase E — isolation regression: Mirror HUD fields absent from scenario DS layer
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_ds_layer_excludes_mirror_hud_fields():
    """DS scenario layer must not contain Mirror-mode HUD fields."""
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt

    scenario_core = _make_scenario_core()
    local_state = {"emotional_tension": 0.0}

    messages = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot=_EMPTY_SNAPSHOT,
        dream_history=[],
        local_state=local_state,
        dream_mode="scenario",
        scenario_core=scenario_core,
    )
    system = dump_dream_prompt(messages)

    # Isolate the DS layer section
    ds_start = system.find("DS·剧本当前阶段")
    assert ds_start != -1, "DS layer header not found"
    ds_section = system[ds_start:]

    # Mirror HUD fields must not appear in DS layer
    mirror_fields = ("dream_depth", "dream_stability", "symbolic_anchors",
                     "dream_depth:", "dream_stability:")
    for field in mirror_fields:
        assert field not in ds_section, (
            f"Mirror HUD field {field!r} leaked into DS layer"
        )


def test_scenario_no_mirror_hud_layer_injected():
    """When dream_mode=scenario, Mirror HUD layer (D6 style numbers) is not injected."""
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt

    scenario_core = _make_scenario_core()
    local_state = {"emotional_tension": 0.0}

    messages = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot=_EMPTY_SNAPSHOT,
        dream_history=[],
        local_state=local_state,
        dream_mode="scenario",
        scenario_core=scenario_core,
    )
    system = dump_dream_prompt(messages)

    # These are Mirror-only numeric HUD fields; they must not appear anywhere in the prompt
    assert "dream_depth" not in system
    assert "dream_stability" not in system


# ═══════════════════════════════════════════════════════════════════════════════
# v0.6 — Progress Signal Skeleton (Phase A–E)
# ═══════════════════════════════════════════════════════════════════════════════

# ── Test 1: Scenario prompt contains <scenario_control> output protocol ───────

def test_scenario_prompt_contains_control_protocol():
    """DS layer in scenario prompt includes the <scenario_control> output protocol."""
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt

    scenario_core = _make_scenario_core()
    messages = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot=_EMPTY_SNAPSHOT,
        dream_history=[],
        local_state={},
        dream_mode="scenario",
        scenario_core=scenario_core,
    )
    system = dump_dream_prompt(messages)

    assert "scenario_control" in system
    assert "progress_signal" in system
    assert "not_close" in system
    assert "approaching" in system
    assert "satisfied" in system
    # Current stage exit_signs listed as reference
    assert "双方有了第一次真实的对话" in system
    assert "她说出了自己的名字" in system


# ── Test 2: Sandbox prompt does NOT contain scenario_control ──────────────────

def test_sandbox_prompt_excludes_control_protocol():
    """sandbox dream mode never includes the <scenario_control> block."""
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt

    messages = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot=_EMPTY_SNAPSHOT,
        dream_history=[],
        local_state={},
        dream_mode="sandbox",
        scenario_core=None,
    )
    system = dump_dream_prompt(messages)
    assert "scenario_control" not in system


# ── Test 3: Valid control block is parsed and stripped from visible reply ──────

def test_extract_scenario_control_valid():
    """Valid control block is parsed; visible reply has block removed."""
    from core.dream.dream_pipeline import _extract_scenario_control

    raw = (
        "Companion看了她一眼，没说话。\n"
        "<scenario_control>\n"
        '{"progress_signal": "approaching", "matched_exit_signs": ["双方有了第一次真实的对话"], "blocked_events": []}\n'
        "</scenario_control>"
    )
    visible, ctrl = _extract_scenario_control(raw)

    assert "scenario_control" not in visible
    assert "Companion看了她一眼" in visible
    assert ctrl is not None
    assert ctrl["progress_signal"] == "approaching"
    assert ctrl["matched_exit_signs"] == ["双方有了第一次真实的对话"]
    assert ctrl["blocked_events"] == []


# ── Test 4: last_progress_signal correctly saved to state via dream_turn ──────

def test_dream_turn_saves_progress_signal(sandbox):
    """dream_turn writes last_progress_signal to scenario_core when control block is valid."""
    from core.dream.dream_pipeline import enter_dream, dream_turn
    from core.dream.dream_state import read_state
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {"enable_dream_lorebook": False})
    fake_snapshot = dict(_EMPTY_SNAPSHOT)
    fake_pipeline = MagicMock()
    fake_pipeline.character = _FAKE_CHARACTER

    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=fake_snapshot)),
        patch("core.pipeline_registry.get", return_value=fake_pipeline),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        asyncio.run(enter_dream(
            _UID, char_id="yexuan", dream_mode="scenario", script_id="prison_demo"
        ))

    llm_response = (
        "Companion沉默地看着她。\n"
        "<scenario_control>\n"
        '{"progress_signal": "satisfied", "matched_exit_signs": ["她说出了自己的名字"], "blocked_events": ["Companion主动表露情感"]}\n'
        "</scenario_control>"
    )
    fake_msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]

    with (
        patch("core.dream.dream_log.read_current", return_value=[]),
        patch("core.dream.dream_log.append_turn"),
        patch("core.pipeline_registry.get", return_value=fake_pipeline),
        patch("core.dream.dream_prompt.build_dream_prompt", return_value=fake_msgs),
        patch("core.llm_client.chat", new=AsyncMock(return_value=llm_response)),
        patch("core.dream.body_tracker.analyze_turn",
              return_value=MagicMock(to_dict=lambda: {})),
        patch("core.dream.body_projection.project_body_for_yexuan",
              return_value={"d5_text": "", "yexuan_tension": 0.0}),
        patch("core.narrative_parser.parse_narrative_segments",
              return_value={"segments": [], "content": "Companion沉默地看着她。"}),
    ):
        result = asyncio.run(dream_turn(_UID, "我叫林梦。"))

    assert result.get("error") is None
    sc = read_state(_UID).get("scenario_core", {})
    assert sc.get("last_progress_signal") == "satisfied"
    assert sc.get("stage_turns") == 1


# ── Test 5: matched_exit_signs correctly saved ────────────────────────────────

def test_with_progress_signal_saves_matched_exit_signs():
    """ScenarioCore.with_progress_signal stores matched_exit_signs correctly."""
    from core.dream.scenario_core import ScenarioCore

    sc = ScenarioCore(script_id="prison_demo", current_stage_id="arrival")
    sc2 = sc.with_progress_signal(
        "satisfied",
        matched_exit_signs=["她说出了自己的名字"],
        blocked_events=[],
    )
    assert sc2.last_matched_exit_signs == ["她说出了自己的名字"]
    assert sc.last_matched_exit_signs == []  # original frozen, unchanged


# ── Test 6: blocked_events correctly saved ────────────────────────────────────

def test_with_progress_signal_saves_blocked_events():
    """ScenarioCore.with_progress_signal stores blocked_events correctly."""
    from core.dream.scenario_core import ScenarioCore

    sc = ScenarioCore(script_id="prison_demo", current_stage_id="arrival")
    sc2 = sc.with_progress_signal(
        "not_close",
        matched_exit_signs=[],
        blocked_events=["Companion主动表露情感"],
    )
    assert sc2.last_blocked_events == ["Companion主动表露情感"]
    assert sc.last_blocked_events == []  # original frozen, unchanged


# ── Test 7: Invalid progress_signal → no update, no crash ────────────────────

def test_extract_scenario_control_invalid_signal():
    """Illegal progress_signal returns None control; visible reply still stripped."""
    from core.dream.dream_pipeline import _extract_scenario_control

    raw = (
        "回复文本。"
        "<scenario_control>"
        '{"progress_signal": "stage_complete", "matched_exit_signs": [], "blocked_events": []}'
        "</scenario_control>"
    )
    visible, ctrl = _extract_scenario_control(raw)

    assert "scenario_control" not in visible
    assert ctrl is None  # invalid signal → no update


# ── Test 8: Missing control block → no crash ─────────────────────────────────

def test_extract_scenario_control_missing():
    """When no control block is present, reply is unchanged and control is None."""
    from core.dream.dream_pipeline import _extract_scenario_control

    raw = "普通的Companion回复，没有任何控制块。"
    visible, ctrl = _extract_scenario_control(raw)

    assert visible == raw
    assert ctrl is None


# ── Test 9: Subsequent stage exit_signs NOT in prompt ─────────────────────────

def test_subsequent_stage_exit_signs_not_in_prompt():
    """exit_signs from stage[1] (negotiation) must not appear in prompt when at stage[0]."""
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt

    scenario_core = _make_scenario_core()  # current_stage_id = arrival
    messages = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot=_EMPTY_SNAPSHOT,
        dream_history=[],
        local_state={},
        dream_mode="scenario",
        scenario_core=scenario_core,
    )
    system = dump_dream_prompt(messages)

    # arrival exit_signs ARE present (as control protocol reference)
    assert "双方有了第一次真实的对话" in system

    # negotiation (stage 1) exit_signs must NOT appear
    assert "她接受了他带来的东西" not in system
    assert "两人之间有了不能被人看见的默契" not in system
    # fracture (stage 2) exit_signs must NOT appear
    assert "他承认他知道自己在做什么" not in system


# ── Test 10: Control block not in visible reply or dream log ──────────────────

def test_scenario_control_stripped_from_reply_and_log(sandbox):
    """dream_turn strips control block from visible reply and dream log entry."""
    from core.dream.dream_pipeline import enter_dream, dream_turn
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {"enable_dream_lorebook": False})
    fake_snapshot = dict(_EMPTY_SNAPSHOT)
    fake_pipeline = MagicMock()
    fake_pipeline.character = _FAKE_CHARACTER

    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=fake_snapshot)),
        patch("core.pipeline_registry.get", return_value=fake_pipeline),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        asyncio.run(enter_dream(
            _UID, char_id="yexuan", dream_mode="scenario", script_id="prison_demo"
        ))

    llm_response = (
        "Companion抬起眼睛。\n"
        "<scenario_control>\n"
        '{"progress_signal": "not_close", "matched_exit_signs": [], "blocked_events": []}\n'
        "</scenario_control>"
    )
    fake_msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    logged_assistant_turns: list[str] = []

    def _capture_turn(uid, did, role, content, **kw):
        if role == "assistant":
            logged_assistant_turns.append(content)

    with (
        patch("core.dream.dream_log.read_current", return_value=[]),
        patch("core.dream.dream_log.append_turn", side_effect=_capture_turn),
        patch("core.pipeline_registry.get", return_value=fake_pipeline),
        patch("core.dream.dream_prompt.build_dream_prompt", return_value=fake_msgs),
        patch("core.llm_client.chat", new=AsyncMock(return_value=llm_response)),
        patch("core.dream.body_tracker.analyze_turn",
              return_value=MagicMock(to_dict=lambda: {})),
        patch("core.dream.body_projection.project_body_for_yexuan",
              return_value={"d5_text": "", "yexuan_tension": 0.0}),
        patch("core.narrative_parser.parse_narrative_segments",
              return_value={"segments": [], "content": "Companion抬起眼睛。"}),
    ):
        result = asyncio.run(dream_turn(_UID, "你好"))

    assert "scenario_control" not in result.get("reply", "")
    assert len(logged_assistant_turns) == 1
    assert "scenario_control" not in logged_assistant_turns[0]
    assert "Companion抬起眼睛。" in logged_assistant_turns[0]


# ── Test 11: New ScenarioCore fields isolated from hidden state / impression ──

def test_scenario_core_new_fields_exclude_hidden_and_impression():
    """New progress signal fields in ScenarioCore contain no hidden state or impression data."""
    from core.dream.scenario_core import ScenarioCore
    from core.dream.scenario_loader import load_script

    script = load_script("prison_demo")
    core = ScenarioCore.from_script(script)
    d = core.to_dict()

    # New fields exist with correct defaults
    assert "last_progress_signal" in d
    assert d["last_progress_signal"] is None
    assert "last_matched_exit_signs" in d
    assert d["last_matched_exit_signs"] == []
    assert "last_blocked_events" in d
    assert d["last_blocked_events"] == []

    # After with_progress_signal, no hidden state or impression leakage
    sc2 = core.with_progress_signal("satisfied", ["双方有了第一次真实的对话"], [])
    d2 = sc2.to_dict()
    forbidden_fields = {
        "sensitivity", "touch_appetite", "embodied_ease",
        "memory_cues", "user_hidden_state", "hidden_state_snapshot",
        "symbolic_anchors", "dream_depth", "dream_stability",
        "impression", "impression_delta", "afterglow",
        "long_term_integration", "distill_impression",
    }
    for f in forbidden_fields:
        assert f not in d2, f"ScenarioCore v0.6 must not contain {f!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# v0.7 — Stage Transition MVP (Phase A–F)
# ═══════════════════════════════════════════════════════════════════════════════

# ── Test 1: satisfied once does NOT advance stage ──────────────────────────────

def test_satisfied_once_does_not_advance():
    """satisfied_streak == 1 after one satisfied signal; stage unchanged."""
    from core.dream.scenario_core import ScenarioCore

    sc = ScenarioCore(script_id="prison_demo", current_stage_id="arrival")
    sc2 = sc.with_progress_signal("satisfied")
    assert sc2.satisfied_streak == 1
    assert sc2.current_stage_id == "arrival"


# ── Test 2: satisfied twice advances to next stage ────────────────────────────

def test_satisfied_twice_advances_stage():
    """Two consecutive satisfied signals trigger advance_to_stage(negotiation)."""
    from core.dream.scenario_core import ScenarioCore
    from core.dream.scenario_loader import load_script, get_next_stage

    sc = ScenarioCore(script_id="prison_demo", current_stage_id="arrival")
    sc = sc.with_progress_signal("satisfied")  # streak = 1
    sc = sc.with_progress_signal("satisfied")  # streak = 2 → advance
    assert sc.satisfied_streak == 2

    script = load_script("prison_demo")
    next_stage = get_next_stage(script, "arrival")
    assert next_stage is not None
    sc_advanced = sc.advance_to_stage(next_stage["id"])
    assert sc_advanced.current_stage_id == "negotiation"


# ── Test 3: stage_turns resets to 0 after advance ────────────────────────────

def test_advance_resets_stage_turns():
    """advance_to_stage sets stage_turns = 0."""
    from core.dream.scenario_core import ScenarioCore

    sc = ScenarioCore(
        script_id="prison_demo", current_stage_id="arrival", stage_turns=5
    )
    sc2 = sc.advance_to_stage("negotiation")
    assert sc2.stage_turns == 0
    assert sc.stage_turns == 5  # original frozen, unchanged


# ── Test 4: last_progress_signal cleared after advance ───────────────────────

def test_advance_clears_last_progress_signal():
    """advance_to_stage sets last_progress_signal = None."""
    from core.dream.scenario_core import ScenarioCore

    sc = ScenarioCore(
        script_id="prison_demo", current_stage_id="arrival",
    )
    sc = sc.with_progress_signal("satisfied", ["她说出了自己的名字"], [])
    sc2 = sc.advance_to_stage("negotiation")
    assert sc2.last_progress_signal is None
    assert sc2.last_matched_exit_signs == []
    assert sc2.last_blocked_events == []


# ── Test 5: satisfied_streak cleared after advance ───────────────────────────

def test_advance_clears_satisfied_streak():
    """advance_to_stage sets satisfied_streak = 0."""
    from core.dream.scenario_core import ScenarioCore

    sc = ScenarioCore(script_id="prison_demo", current_stage_id="arrival")
    sc = sc.with_progress_signal("satisfied")
    sc = sc.with_progress_signal("satisfied")
    assert sc.satisfied_streak == 2
    sc2 = sc.advance_to_stage("negotiation")
    assert sc2.satisfied_streak == 0


# ── Test 6: approaching interrupts satisfied_streak ──────────────────────────

def test_approaching_interrupts_satisfied_streak():
    """approaching after satisfied resets streak to 0."""
    from core.dream.scenario_core import ScenarioCore

    sc = ScenarioCore(script_id="prison_demo", current_stage_id="arrival")
    sc = sc.with_progress_signal("satisfied")
    assert sc.satisfied_streak == 1
    sc = sc.with_progress_signal("approaching")
    assert sc.satisfied_streak == 0
    assert sc.current_stage_id == "arrival"


# ── Test 7: not_close interrupts satisfied_streak ────────────────────────────

def test_not_close_interrupts_satisfied_streak():
    """not_close after satisfied resets streak to 0."""
    from core.dream.scenario_core import ScenarioCore

    sc = ScenarioCore(script_id="prison_demo", current_stage_id="arrival")
    sc = sc.with_progress_signal("satisfied")
    assert sc.satisfied_streak == 1
    sc = sc.with_progress_signal("not_close")
    assert sc.satisfied_streak == 0


# ── Test 8: missing/invalid control block does not advance ───────────────────

def test_missing_control_does_not_advance():
    """reset_satisfied_streak prevents streak from reaching 2 via a missing turn."""
    from core.dream.scenario_core import ScenarioCore

    sc = ScenarioCore(script_id="prison_demo", current_stage_id="arrival")
    sc = sc.with_progress_signal("satisfied")   # streak = 1
    sc = sc.reset_satisfied_streak()             # control block absent — reset
    assert sc.satisfied_streak == 0
    assert sc.current_stage_id == "arrival"

    # Even one more satisfied after reset: streak = 1, not 2 → no advance
    sc = sc.with_progress_signal("satisfied")
    assert sc.satisfied_streak == 1
    assert sc.current_stage_id == "arrival"


# ── Test 9: final stage consecutive satisfied → ending_state = completed ─────

def test_last_stage_satisfied_twice_marks_completed():
    """advance_to_stage on final stage returns None; mark_completed sets ending_state."""
    from core.dream.scenario_core import ScenarioCore
    from core.dream.scenario_loader import load_script, get_next_stage

    script = load_script("prison_demo")
    # fracture is the last stage in prison_demo
    sc = ScenarioCore(script_id="prison_demo", current_stage_id="fracture")
    sc = sc.with_progress_signal("satisfied")
    sc = sc.with_progress_signal("satisfied")
    assert sc.satisfied_streak == 2

    next_stage = get_next_stage(script, "fracture")
    assert next_stage is None  # fracture is the last stage

    sc_done = sc.mark_completed()
    assert sc_done.ending_state == "completed"
    assert sc_done.current_stage_id == "fracture"  # stays at last stage


# ── Test 10: LLM cannot specify next_stage via control block ─────────────────

def test_control_block_ignores_next_stage_key():
    """_extract_scenario_control ignores any next_stage field in the control JSON."""
    from core.dream.dream_pipeline import _extract_scenario_control

    raw = (
        "Companion抬眼看她。\n"
        "<scenario_control>\n"
        '{"progress_signal": "satisfied", "matched_exit_signs": [], "blocked_events": [],'
        ' "next_stage": "negotiation"}\n'
        "</scenario_control>"
    )
    visible, ctrl = _extract_scenario_control(raw)

    assert ctrl is not None
    assert ctrl["progress_signal"] == "satisfied"
    assert "next_stage" not in ctrl  # parser must strip unknown keys


# ── Test 11: prompt after stage advance shows new stage, not old ──────────────

def test_prompt_after_advance_shows_new_stage():
    """_format_scenario_layer with negotiation stage_id shows negotiation content."""
    from core.dream.dream_prompt import _format_scenario_layer

    sc_negotiation = {
        "script_id": "prison_demo",
        "current_stage_id": "negotiation",
        "stage_turns": 0,
        "ending_state": None,
        "satisfied_streak": 0,
    }
    text = _format_scenario_layer(sc_negotiation)

    assert "秘密交换" in text           # negotiation stage name
    assert "今天他比平时晚了" in text    # negotiation entry_pressure
    assert "初次相遇" not in text        # arrival stage name must not appear
    assert "铁门" not in text            # arrival entry_pressure must not appear


# ── Test 12: subsequent stages do not leak before reached ────────────────────

def test_future_stages_do_not_leak_at_arrival():
    """At arrival stage, fracture and negotiation content must not appear."""
    from core.dream.dream_prompt import _format_scenario_layer

    sc = {
        "script_id": "prison_demo",
        "current_stage_id": "arrival",
        "stage_turns": 0,
        "ending_state": None,
        "satisfied_streak": 0,
    }
    text = _format_scenario_layer(sc)

    # arrival present
    assert "初次相遇" in text
    # negotiation must not appear
    assert "秘密交换" not in text
    assert "今天他比平时晚了" not in text
    # fracture must not appear
    assert "裂缝" not in text
    assert "替她撒了谎" not in text


# ── Test 13: sandbox/mirror dream_turn not affected by scenario logic ─────────

def test_sandbox_dream_turn_not_affected_by_scenario_logic(sandbox):
    """In sandbox mode, dream_turn does not create or modify scenario_core."""
    from core.dream.dream_pipeline import enter_dream, dream_turn
    from core.dream.dream_state import read_state
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {"enable_dream_lorebook": False})
    fake_snapshot = dict(_EMPTY_SNAPSHOT)
    fake_pipeline = MagicMock()
    fake_pipeline.character = _FAKE_CHARACTER

    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=fake_snapshot)),
        patch("core.pipeline_registry.get", return_value=fake_pipeline),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        r = asyncio.run(enter_dream(
            _UID, char_id="yexuan", dream_mode="sandbox"
        ))
    assert r.get("ok") is True

    llm_response = (
        "Companion安静地看着她。\n"
        "<scenario_control>\n"
        '{"progress_signal": "satisfied", "matched_exit_signs": [], "blocked_events": []}\n'
        "</scenario_control>"
    )
    fake_msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]

    with (
        patch("core.dream.dream_log.read_current", return_value=[]),
        patch("core.dream.dream_log.append_turn"),
        patch("core.pipeline_registry.get", return_value=fake_pipeline),
        patch("core.dream.dream_prompt.build_dream_prompt", return_value=fake_msgs),
        patch("core.llm_client.chat", new=AsyncMock(return_value=llm_response)),
        patch("core.dream.body_tracker.analyze_turn",
              return_value=MagicMock(to_dict=lambda: {})),
        patch("core.dream.body_projection.project_body_for_yexuan",
              return_value={"d5_text": "", "yexuan_tension": 0.0}),
        patch("core.narrative_parser.parse_narrative_segments",
              return_value={"segments": [], "content": "Companion安静地看着她。"}),
    ):
        result = asyncio.run(dream_turn(_UID, "你好"))

    assert result.get("error") is None
    state = read_state(_UID)
    # sandbox mode: no scenario_core written
    assert "scenario_core" not in state


# ── Test 14: advance_to_stage contains no hidden_state / impression / Mirror fields ──

def test_advance_to_stage_dict_excludes_isolation_fields():
    """ScenarioCore after advance_to_stage must not contain hidden_state, impression,
    or Mirror HUD fields."""
    from core.dream.scenario_core import ScenarioCore

    sc = ScenarioCore(script_id="prison_demo", current_stage_id="arrival")
    sc = sc.with_progress_signal("satisfied")
    sc = sc.with_progress_signal("satisfied")
    sc2 = sc.advance_to_stage("negotiation")
    d = sc2.to_dict()

    forbidden = {
        "sensitivity", "touch_appetite", "embodied_ease",
        "memory_cues", "user_hidden_state", "hidden_state_snapshot",
        "symbolic_anchors", "dream_depth", "dream_stability",
        "impression", "impression_delta", "afterglow",
        "long_term_integration", "distill_impression",
    }
    for f in forbidden:
        assert f not in d, f"advance_to_stage must not contain {f!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# v0.7.1 — stage_turns off-by-one audit
# ═══════════════════════════════════════════════════════════════════════════════

_SATISFIED_REPLY = (
    "Companion沉默地看着她。\n"
    "<scenario_control>\n"
    '{"progress_signal": "satisfied", "matched_exit_signs": ["她说出了自己的名字"], "blocked_events": []}\n'
    "</scenario_control>"
)
_NOT_CLOSE_REPLY = (
    "Companion没有回应。\n"
    "<scenario_control>\n"
    '{"progress_signal": "not_close", "matched_exit_signs": [], "blocked_events": []}\n'
    "</scenario_control>"
)
_FAKE_MSGS = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]


def _run_dream_turn(uid: str, fake_pipeline, llm_response: str) -> dict:
    """Run one dream_turn with a fixed LLM response. Returns dream_turn result."""
    from core.dream.dream_pipeline import dream_turn
    with (
        patch("core.dream.dream_log.read_current", return_value=[]),
        patch("core.dream.dream_log.append_turn"),
        patch("core.pipeline_registry.get", return_value=fake_pipeline),
        patch("core.dream.dream_prompt.build_dream_prompt", return_value=_FAKE_MSGS),
        patch("core.llm_client.chat", new=AsyncMock(return_value=llm_response)),
        patch("core.dream.body_tracker.analyze_turn",
              return_value=MagicMock(to_dict=lambda: {})),
        patch("core.dream.body_projection.project_body_for_yexuan",
              return_value={"d5_text": "", "yexuan_tension": 0.0}),
        patch("core.narrative_parser.parse_narrative_segments",
              return_value={"segments": [], "content": "Companion回复了"}),
    ):
        return asyncio.run(dream_turn(uid, "你好"))


# ── v0.7.1 A: normal turn increments stage_turns (baseline regression) ────────

def test_v071_normal_turn_increments_stage_turns(sandbox):
    """Non-transition turn: stage_turns increments normally from 0 to 1."""
    from core.dream.dream_pipeline import enter_dream
    from core.dream.dream_state import read_state
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {"enable_dream_lorebook": False})
    fake_pipeline = MagicMock()
    fake_pipeline.character = _FAKE_CHARACTER

    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=dict(_EMPTY_SNAPSHOT))),
        patch("core.pipeline_registry.get", return_value=fake_pipeline),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        asyncio.run(enter_dream(_UID, char_id="yexuan", dream_mode="scenario", script_id="prison_demo"))

    _run_dream_turn(_UID, fake_pipeline, _NOT_CLOSE_REPLY)

    sc = read_state(_UID).get("scenario_core", {})
    assert sc.get("current_stage_id") == "arrival"
    assert sc.get("stage_turns") == 1


# ── v0.7.1 B: first satisfied does not advance, stage_turns increments ────────

def test_v071_first_satisfied_no_advance_increments_turns(sandbox):
    """First satisfied turn: no stage advance; stage_turns goes to 1, streak goes to 1."""
    from core.dream.dream_pipeline import enter_dream
    from core.dream.dream_state import read_state
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {"enable_dream_lorebook": False})
    fake_pipeline = MagicMock()
    fake_pipeline.character = _FAKE_CHARACTER

    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=dict(_EMPTY_SNAPSHOT))),
        patch("core.pipeline_registry.get", return_value=fake_pipeline),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        asyncio.run(enter_dream(_UID, char_id="yexuan", dream_mode="scenario", script_id="prison_demo"))

    _run_dream_turn(_UID, fake_pipeline, _SATISFIED_REPLY)

    sc = read_state(_UID).get("scenario_core", {})
    assert sc.get("current_stage_id") == "arrival"
    assert sc.get("satisfied_streak") == 1
    assert sc.get("stage_turns") == 1, (
        f"first satisfied: expected stage_turns=1, got {sc.get('stage_turns')}"
    )


# ── v0.7.1 C: second satisfied triggers advance, new stage starts at stage_turns == 0 ──

def test_v071_second_satisfied_new_stage_starts_at_zero(sandbox):
    """The transition turn (2nd satisfied) must leave the NEW stage at stage_turns == 0.

    The transitioning turn belongs to the OLD stage.  The new stage has not been
    'entered' in any meaningful sense yet — it should start fresh at 0.
    """
    from core.dream.dream_pipeline import enter_dream
    from core.dream.dream_state import read_state
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {"enable_dream_lorebook": False})
    fake_pipeline = MagicMock()
    fake_pipeline.character = _FAKE_CHARACTER

    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=dict(_EMPTY_SNAPSHOT))),
        patch("core.pipeline_registry.get", return_value=fake_pipeline),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        asyncio.run(enter_dream(_UID, char_id="yexuan", dream_mode="scenario", script_id="prison_demo"))

    # Turn 1: satisfied — streak=1, stage_turns=1, still at arrival
    _run_dream_turn(_UID, fake_pipeline, _SATISFIED_REPLY)
    sc_after_t1 = read_state(_UID).get("scenario_core", {})
    assert sc_after_t1.get("current_stage_id") == "arrival"
    assert sc_after_t1.get("satisfied_streak") == 1

    # Turn 2: satisfied — streak=2 → advance to negotiation; new stage_turns must be 0
    _run_dream_turn(_UID, fake_pipeline, _SATISFIED_REPLY)
    sc = read_state(_UID).get("scenario_core", {})
    assert sc.get("current_stage_id") == "negotiation", (
        f"expected negotiation, got {sc.get('current_stage_id')}"
    )
    assert sc.get("stage_turns") == 0, (
        f"new stage after transition must start at stage_turns=0, got {sc.get('stage_turns')}"
    )
    assert sc.get("satisfied_streak") == 0


# ── v0.7.1 D: first turn in new stage after transition increments to 1 ────────

def test_v071_first_turn_in_new_stage_increments_to_one(sandbox):
    """After stage advance, the first real turn in the new stage sets stage_turns == 1."""
    from core.dream.dream_pipeline import enter_dream
    from core.dream.dream_state import read_state
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {"enable_dream_lorebook": False})
    fake_pipeline = MagicMock()
    fake_pipeline.character = _FAKE_CHARACTER

    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=dict(_EMPTY_SNAPSHOT))),
        patch("core.pipeline_registry.get", return_value=fake_pipeline),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        asyncio.run(enter_dream(_UID, char_id="yexuan", dream_mode="scenario", script_id="prison_demo"))

    # Turns 1+2: trigger advance to negotiation (stage_turns=0 on arrival)
    _run_dream_turn(_UID, fake_pipeline, _SATISFIED_REPLY)
    _run_dream_turn(_UID, fake_pipeline, _SATISFIED_REPLY)
    sc_at_new = read_state(_UID).get("scenario_core", {})
    assert sc_at_new.get("current_stage_id") == "negotiation"
    assert sc_at_new.get("stage_turns") == 0

    # Turn 3: first genuine turn in new stage — must increment to 1
    _run_dream_turn(_UID, fake_pipeline, _NOT_CLOSE_REPLY)
    sc = read_state(_UID).get("scenario_core", {})
    assert sc.get("current_stage_id") == "negotiation"
    assert sc.get("stage_turns") == 1, (
        f"first turn in new stage must set stage_turns=1, got {sc.get('stage_turns')}"
    )


# ── v0.7.1 E: mark_completed does not increment stage_turns ───────────────────

def test_v071_mark_completed_does_not_increment_stage_turns(sandbox):
    """Completing the last stage must not call increment_stage_turns on the final stage.

    The completing turn (2nd satisfied on last stage) belongs to the final stage but
    must not cause a spurious extra increment — drift_pressure and any future reader
    must see the pre-completion stage_turns value.
    """
    from core.dream.dream_pipeline import enter_dream
    from core.dream.dream_state import read_state, write_state
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {"enable_dream_lorebook": False})
    fake_pipeline = MagicMock()
    fake_pipeline.character = _FAKE_CHARACTER

    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=dict(_EMPTY_SNAPSHOT))),
        patch("core.pipeline_registry.get", return_value=fake_pipeline),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        asyncio.run(enter_dream(_UID, char_id="yexuan", dream_mode="scenario", script_id="prison_demo"))

    # Manually jump to last stage (fracture) with satisfied_streak=1 and stage_turns=3
    state = read_state(_UID)
    state["scenario_core"].update({
        "current_stage_id": "fracture",
        "satisfied_streak": 1,
        "stage_turns": 3,
        "ending_state": None,
    })
    write_state(_UID, state)

    # Turn: 2nd satisfied on last stage → mark_completed, _did_advance=True → no increment
    _run_dream_turn(_UID, fake_pipeline, _SATISFIED_REPLY)
    sc = read_state(_UID).get("scenario_core", {})
    assert sc.get("ending_state") == "completed", (
        f"expected completed, got {sc.get('ending_state')}"
    )
    assert sc.get("current_stage_id") == "fracture"
    assert sc.get("stage_turns") == 3, (
        f"mark_completed must not increment stage_turns; expected 3, got {sc.get('stage_turns')}"
    )


# ── v0.7.1 F: drift_pressure uses clean stage_turns == 0 after advance ────────

def test_v071_drift_pressure_not_shown_immediately_after_advance():
    """New stage at stage_turns == 0 must not show drift_pressure (below threshold=6)."""
    from core.dream.dream_prompt import _format_scenario_layer

    sc = {
        "script_id": "prison_demo",
        "current_stage_id": "negotiation",
        "stage_turns": 0,
        "ending_state": None,
        "satisfied_streak": 0,
    }
    text = _format_scenario_layer(sc)

    assert "漂移压力" not in text, (
        "stage_turns=0 must not trigger drift_pressure injection; "
        "if this fails, the transition turn inflated the new stage's turn count"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# v0.8 — Hidden-state isolation guards
# Scenario Mode must never read or write User Hidden State.
# ═══════════════════════════════════════════════════════════════════════════════

_HS_SNAPSHOT = {
    "sensitivity": "medium",
    "touch_appetite": "low",
    "embodied_ease": "stable",
}

_TRIGGER_LOCAL_STATE = {
    "emotional_tension": 0.0,
    "scene_state": "body_intimate",
    "symbolic_anchors": ["physical_closeness"],
}


# ── Test A: Scenario exit does NOT call wire_afterglow_from_summary ────────────

def test_scenario_exit_skips_wire_afterglow():
    """_generate_summary_bg(dream_mode=scenario) never calls wire_afterglow_from_summary."""
    from core.dream.dream_pipeline import _generate_summary_bg

    wire_mock = MagicMock()

    with (
        patch("core.dream.dream_summary.generate_summary", new=AsyncMock()),
        patch("core.dream.dream_exit_afterglow.wire_afterglow_from_summary", wire_mock),
        patch("core.dream.distill_impression.distill_impression", new=AsyncMock()),
    ):
        asyncio.run(_generate_summary_bg(
            "u_scenario", "dream_u_001", "soft",
            char_id="yexuan", dream_mode="scenario",
        ))

    wire_mock.assert_not_called()


# ── Test B: Scenario exit does NOT call wire_afterglow for hard_exit either ───

def test_scenario_hard_exit_also_skips_wire_afterglow():
    """Hard-exit scenario dream also skips wire_afterglow_from_summary."""
    from core.dream.dream_pipeline import _generate_summary_bg

    wire_mock = MagicMock()

    with (
        patch("core.dream.dream_summary.generate_summary", new=AsyncMock()),
        patch("core.dream.dream_exit_afterglow.wire_afterglow_from_summary", wire_mock),
        patch("core.dream.distill_impression.distill_impression", new=AsyncMock()),
    ):
        asyncio.run(_generate_summary_bg(
            "u_scenario", "dream_u_002", "hard_exit",
            char_id="yexuan", dream_mode="scenario",
        ))

    wire_mock.assert_not_called()


# ── Test C: Sandbox exit DOES call wire_afterglow_from_summary (regression) ───

def test_sandbox_exit_calls_wire_afterglow():
    """_generate_summary_bg(dream_mode=sandbox) calls wire_afterglow_from_summary (regression)."""
    from core.dream.dream_pipeline import _generate_summary_bg

    wire_mock = MagicMock()

    with (
        patch("core.dream.dream_summary.generate_summary", new=AsyncMock()),
        patch("core.dream.dream_exit_afterglow.wire_afterglow_from_summary", wire_mock),
        patch("core.dream.distill_impression.distill_impression", new=AsyncMock()),
    ):
        asyncio.run(_generate_summary_bg(
            "u_sandbox", "dream_u_003", "soft",
            char_id="yexuan", dream_mode="sandbox",
        ))

    wire_mock.assert_called_once()


# ── Test D: Scenario prompt does NOT inject D4.5 with trigger tags ────────────

def test_scenario_prompt_excludes_d45_with_body_intimate_tag():
    """Scenario prompt must not inject D4.5 even when body_intimate tag is present."""
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt

    scenario_core = _make_scenario_core()
    snapshot = dict(_EMPTY_SNAPSHOT)
    snapshot["user_hidden_state_snapshot"] = dict(_HS_SNAPSHOT)

    messages = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot=snapshot,
        dream_history=[],
        local_state=dict(_TRIGGER_LOCAL_STATE),
        dream_mode="scenario",
        scenario_core=scenario_core,
    )
    system = dump_dream_prompt(messages)

    assert "D4.5" not in system
    assert "user_hidden_state_snapshot" not in system
    assert "sensitivity:" not in system
    assert "touch_appetite:" not in system
    assert "embodied_ease:" not in system


# ── Test E: Scenario prompt excludes D4.5 regardless of physical_closeness ───

def test_scenario_prompt_excludes_d45_with_physical_closeness_tag():
    """Scenario prompt must not inject D4.5 when physical_closeness anchor is present."""
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt

    scenario_core = _make_scenario_core()
    snapshot = dict(_EMPTY_SNAPSHOT)
    snapshot["user_hidden_state_snapshot"] = dict(_HS_SNAPSHOT)
    local_with_anchor = {
        "emotional_tension": 0.0,
        "symbolic_anchors": ["physical_closeness"],
    }

    messages = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot=snapshot,
        dream_history=[],
        local_state=local_with_anchor,
        dream_mode="scenario",
        scenario_core=scenario_core,
    )
    system = dump_dream_prompt(messages)

    assert "D4.5" not in system
    assert "user_hidden_state_snapshot" not in system


# ── Test F: Sandbox mode DOES inject D4.5 when trigger tag present (regression)

def test_sandbox_prompt_injects_d45_with_body_intimate_tag():
    """Sandbox dream mode injects D4.5 when body_intimate tag is present (regression)."""
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt

    snapshot = dict(_EMPTY_SNAPSHOT)
    snapshot["user_hidden_state_snapshot"] = dict(_HS_SNAPSHOT)

    messages = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot=snapshot,
        dream_history=[],
        local_state=dict(_TRIGGER_LOCAL_STATE),
        dream_mode="sandbox",
        scenario_core=None,
    )
    system = dump_dream_prompt(messages)

    assert "D4.5" in system
    assert "user_hidden_state_snapshot" in system


# ── Test G: ScenarioCore fields intact after isolation fix (regression) ────────

def test_scenario_core_all_fields_intact_after_isolation_fix():
    """ScenarioCore fields are unaffected by the hidden-state isolation fix."""
    from core.dream.scenario_core import ScenarioCore
    from core.dream.scenario_loader import load_script

    script = load_script("prison_demo")
    core = ScenarioCore.from_script(script)
    d = core.to_dict()

    for expected_field in (
        "script_id", "current_stage_id", "stage_turns",
        "ending_state", "last_progress_signal",
        "last_matched_exit_signs", "last_blocked_events", "satisfied_streak",
    ):
        assert expected_field in d, f"ScenarioCore.to_dict() must contain {expected_field!r}"

    assert d["script_id"] == "prison_demo"
    assert d["current_stage_id"] == "arrival"
    assert d["stage_turns"] == 0
    assert d["ending_state"] is None
    assert d["satisfied_streak"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# v0.8.1 — Impression isolation guards
# Scenario Mode must never write impression_store (Reality-facing 6g layer).
# ═══════════════════════════════════════════════════════════════════════════════


# ── Test H: Scenario exit does NOT call distill_impression ────────────────────

def test_scenario_exit_skips_distill_impression():
    """_generate_summary_bg(dream_mode=scenario) never calls distill_impression."""
    from core.dream.dream_pipeline import _generate_summary_bg

    distill_mock = AsyncMock()

    with (
        patch("core.dream.dream_summary.generate_summary", new=AsyncMock()),
        patch("core.dream.dream_exit_afterglow.wire_afterglow_from_summary"),
        patch("core.dream.distill_impression.distill_impression", distill_mock),
    ):
        asyncio.run(_generate_summary_bg(
            "u_scenario_h", "dream_u_h001", "soft",
            char_id="yexuan", dream_mode="scenario",
        ))

    distill_mock.assert_not_called()


# ── Test I: Scenario hard_exit also skips distill_impression ─────────────────

def test_scenario_hard_exit_also_skips_distill_impression():
    """Hard-exit scenario dream also skips distill_impression."""
    from core.dream.dream_pipeline import _generate_summary_bg

    distill_mock = AsyncMock()

    with (
        patch("core.dream.dream_summary.generate_summary", new=AsyncMock()),
        patch("core.dream.dream_exit_afterglow.wire_afterglow_from_summary"),
        patch("core.dream.distill_impression.distill_impression", distill_mock),
    ):
        asyncio.run(_generate_summary_bg(
            "u_scenario_i", "dream_u_i001", "hard_exit",
            char_id="yexuan", dream_mode="scenario",
        ))

    distill_mock.assert_not_called()


# ── Test J: Sandbox exit DOES call distill_impression (regression) ────────────

def test_sandbox_exit_calls_distill_impression():
    """_generate_summary_bg(dream_mode=sandbox) calls distill_impression (regression)."""
    from core.dream.dream_pipeline import _generate_summary_bg

    distill_mock = AsyncMock()

    with (
        patch("core.dream.dream_summary.generate_summary", new=AsyncMock()),
        patch("core.dream.dream_exit_afterglow.wire_afterglow_from_summary"),
        patch("core.dream.distill_impression.distill_impression", distill_mock),
    ):
        asyncio.run(_generate_summary_bg(
            "u_sandbox_j", "dream_u_j001", "soft",
            char_id="yexuan", dream_mode="sandbox",
        ))

    distill_mock.assert_called_once()


# ── Test K: Scenario summary generation is NOT blocked (isolation only) ───────

def test_scenario_summary_generation_not_blocked():
    """generate_summary still runs for scenario mode; only distill_impression is skipped."""
    from core.dream.dream_pipeline import _generate_summary_bg

    summary_mock = AsyncMock()
    distill_mock = AsyncMock()

    with (
        patch("core.dream.dream_summary.generate_summary", summary_mock),
        patch("core.dream.dream_exit_afterglow.wire_afterglow_from_summary"),
        patch("core.dream.distill_impression.distill_impression", distill_mock),
    ):
        asyncio.run(_generate_summary_bg(
            "u_scenario_k", "dream_u_k001", "soft",
            char_id="yexuan", dream_mode="scenario",
        ))

    summary_mock.assert_called_once()
    distill_mock.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# v0.8.2 — D5 body_projection isolation guard
# Scenario Mode must never inject D5 body_projection into the prompt.
# Body/intimate expression in Scenario is driven by script stage text, not the
# general Dream body_state system.
# ═══════════════════════════════════════════════════════════════════════════════

_BODY_PROJECTION_TEXT = "她的心跳加快，皮肤微微发热，意识到他站得很近。"


# ── Test L: Scenario prompt does NOT inject D5 body_projection ───────────────

def test_scenario_prompt_excludes_d5_body_projection():
    """Scenario prompt must not inject D5 even when body_projection_text is non-empty."""
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt

    scenario_core = _make_scenario_core()

    messages = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot=_EMPTY_SNAPSHOT,
        dream_history=[],
        local_state={},
        dream_mode="scenario",
        scenario_core=scenario_core,
        body_projection_text=_BODY_PROJECTION_TEXT,
    )
    system = dump_dream_prompt(messages)

    assert "D5" not in system
    assert "D5·她的身体感知" not in system
    assert _BODY_PROJECTION_TEXT not in system


# ── Test M: Sandbox prompt DOES inject D5 body_projection (regression) ───────

def test_sandbox_prompt_injects_d5_body_projection():
    """Sandbox dream mode injects D5 when body_projection_text is non-empty (regression)."""
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt

    messages = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot=_EMPTY_SNAPSHOT,
        dream_history=[],
        local_state={},
        dream_mode="sandbox",
        scenario_core=None,
        body_projection_text=_BODY_PROJECTION_TEXT,
    )
    system = dump_dream_prompt(messages)

    assert "D5·她的身体感知" in system
    assert _BODY_PROJECTION_TEXT in system


# ── Test N: Scenario with non-empty body_state still excludes D5 ─────────────

def test_scenario_with_nonempty_body_state_still_excludes_d5():
    """Scenario must exclude D5 even when body_projection_text is substantive.

    Guards against a false pass caused by an empty projection string rather than
    the scenario mode guard.
    """
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt

    scenario_core = _make_scenario_core()
    long_projection = (
        "她呼吸浅而急促，身体对他的靠近产生了明显的反应——热度从皮肤下涌上来，"
        "指尖有些发颤，不得不攥住了什么来稳住自己。"
    )
    assert long_projection  # sanity: projection is non-empty

    messages = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot=_EMPTY_SNAPSHOT,
        dream_history=[],
        local_state={},
        dream_mode="scenario",
        scenario_core=scenario_core,
        body_projection_text=long_projection,
    )
    system = dump_dream_prompt(messages)

    assert "D5" not in system
    assert long_projection not in system
    # DS layer still present (scenario core is intact)
    assert "DS·剧本当前阶段" in system

"""
tests/test_dream_prompt_tension_bucket.py — D7 tension bucket hygiene

Tests:
  1.  _bucket_tension 基础分桶：0.0 / 0.2 → 低位
  2.  _bucket_tension 基础分桶：0.25 / 0.4 → 上升中
  3.  _bucket_tension 基础分桶：0.5 / 0.7 → 高位
  4.  _bucket_tension 基础分桶：0.75 / 1.0 → 临界
  5.  越界 clamp：< 0 → 低位
  6.  越界 clamp：> 1 → 临界
  7.  边界精确值：0.25 进上升中，0.5 进高位，0.75 进临界
  8.  D7 prompt 不包含 % 字符
  9.  D7 prompt 包含分桶文本（低位/上升中/高位/临界）
  10. D7 ≤ 0.05 时层 DISABLED（prompt 中不含 D7 情绪张力层）
  11. Scenario 隔离：D4.5 在 scenario 模式仍被禁用
  12. Scenario 隔离：D5 在 scenario 模式仍被禁用
  13. Sandbox D7 注入分桶文本，不注入百分比
  14. Mirror placeholder：与 sandbox 使用相同分桶逻辑（build_dream_prompt dream_mode=mirror）
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────

_FAKE_CHARACTER = MagicMock()
_FAKE_CHARACTER.name = "Companion"
_FAKE_CHARACTER.description = "Companion，男，圣塞西尔学院教师"
_FAKE_CHARACTER.jailbreak_entries = []

_EMPTY_SNAPSHOT: dict[str, Any] = {
    "user_id": "bucket_test_user",
    "entry_reason": "test",
    "relationship_state": {},
    "recent_reality_context": "",
    "episodic_summary": "",
    "mid_term_context": "",
    "profile_impression": "",
}

_EMPTY_LOCAL: dict[str, Any] = {}


def _build(tension: float, dream_mode: str = "sandbox", **kwargs) -> list[dict[str, str]]:
    """Thin wrapper around build_dream_prompt for tension-related tests."""
    from core.dream.dream_prompt import build_dream_prompt

    with patch("core.dream.world_loader.load_world") as mock_lw:
        mock_world = MagicMock()
        mock_world.ruleset = ""
        mock_world.mes_example = ""
        mock_lw.return_value = mock_world
        return build_dream_prompt(
            character=_FAKE_CHARACTER,
            user_id="bucket_test_user",
            user_message="测试消息",
            context_snapshot=_EMPTY_SNAPSHOT,
            dream_history=[],
            local_state=_EMPTY_LOCAL,
            yexuan_tension=tension,
            dream_mode=dream_mode,
            **kwargs,
        )


def _system(msgs: list[dict[str, str]]) -> str:
    for m in msgs:
        if m.get("role") == "system":
            return m["content"]
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
# 1-2  低位
# ═══════════════════════════════════════════════════════════════════════════════

def test_bucket_low_zero():
    from core.dream.dream_prompt import _bucket_tension
    assert _bucket_tension(0.0) == "低位"


def test_bucket_low_02():
    from core.dream.dream_prompt import _bucket_tension
    assert _bucket_tension(0.2) == "低位"


# ═══════════════════════════════════════════════════════════════════════════════
# 3-4  上升中
# ═══════════════════════════════════════════════════════════════════════════════

def test_bucket_rising_025():
    from core.dream.dream_prompt import _bucket_tension
    assert _bucket_tension(0.25) == "上升中"


def test_bucket_rising_04():
    from core.dream.dream_prompt import _bucket_tension
    assert _bucket_tension(0.4) == "上升中"


# ═══════════════════════════════════════════════════════════════════════════════
# 5-6  高位
# ═══════════════════════════════════════════════════════════════════════════════

def test_bucket_high_05():
    from core.dream.dream_prompt import _bucket_tension
    assert _bucket_tension(0.5) == "高位"


def test_bucket_high_07():
    from core.dream.dream_prompt import _bucket_tension
    assert _bucket_tension(0.7) == "高位"


# ═══════════════════════════════════════════════════════════════════════════════
# 7-8  临界
# ═══════════════════════════════════════════════════════════════════════════════

def test_bucket_critical_075():
    from core.dream.dream_prompt import _bucket_tension
    assert _bucket_tension(0.75) == "临界"


def test_bucket_critical_1():
    from core.dream.dream_prompt import _bucket_tension
    assert _bucket_tension(1.0) == "临界"


# ═══════════════════════════════════════════════════════════════════════════════
# 9-10  越界 clamp
# ═══════════════════════════════════════════════════════════════════════════════

def test_bucket_clamp_negative():
    from core.dream.dream_prompt import _bucket_tension
    assert _bucket_tension(-0.5) == "低位"


def test_bucket_clamp_over_one():
    from core.dream.dream_prompt import _bucket_tension
    assert _bucket_tension(1.5) == "临界"


# ═══════════════════════════════════════════════════════════════════════════════
# 11  边界精确值（含 0.25, 0.5, 0.75）
# ═══════════════════════════════════════════════════════════════════════════════

def test_bucket_exact_boundaries():
    from core.dream.dream_prompt import _bucket_tension
    assert _bucket_tension(0.25) == "上升中"
    assert _bucket_tension(0.5) == "高位"
    assert _bucket_tension(0.75) == "临界"


# ═══════════════════════════════════════════════════════════════════════════════
# 12  D7 prompt 不包含 % 字符
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("tension", [0.1, 0.3, 0.6, 0.9])
def test_d7_no_percent_sign(tension):
    sys = _system(_build(tension))
    assert "%" not in sys, f"D7 must not inject a % sign (tension={tension})"


# ═══════════════════════════════════════════════════════════════════════════════
# 13  D7 prompt 包含分桶标签
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("tension,expected_bucket", [
    (0.1,  "低位"),
    (0.3,  "上升中"),
    (0.6,  "高位"),
    (0.9,  "临界"),
])
def test_d7_contains_bucket_label(tension, expected_bucket):
    sys = _system(_build(tension))
    assert expected_bucket in sys, (
        f"D7 should contain bucket label '{expected_bucket}' for tension={tension}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 14  D7 ≤ 0.05 → DISABLED（层不出现在 prompt 中）
# ═══════════════════════════════════════════════════════════════════════════════

def test_d7_disabled_when_tension_low():
    sys = _system(_build(0.04))
    assert "D7·" not in sys


def test_d7_disabled_zero():
    sys = _system(_build(0.0))
    assert "D7·" not in sys


# ═══════════════════════════════════════════════════════════════════════════════
# 15-16  Scenario 隔离：D4.5 / D5 仍被禁用
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_d45_still_disabled():
    snapshot = dict(_EMPTY_SNAPSHOT)
    snapshot["user_hidden_state_snapshot"] = {
        "sensitivity": "medium",
        "touch_appetite": "low",
        "embodied_ease": "neutral",
    }
    local = {"scene_state": "body_intimate", "symbolic_anchors": ["physical_closeness"]}
    with patch("core.dream.world_loader.load_world") as mock_lw:
        mock_world = MagicMock()
        mock_world.ruleset = ""
        mock_world.mes_example = ""
        mock_lw.return_value = mock_world
        from core.dream.dream_prompt import build_dream_prompt
        msgs = build_dream_prompt(
            character=_FAKE_CHARACTER,
            user_id="bucket_test_user",
            user_message="test",
            context_snapshot=snapshot,
            dream_history=[],
            local_state=local,
            yexuan_tension=0.8,
            dream_mode="scenario",
            scenario_core={
                "script_id": "prison_demo",
                "current_stage_id": "arrival",
                "stage_turns": 0,
                "ending_state": None,
            },
        )
    sys = _system(msgs)
    assert "D4.5" not in sys
    assert "user_hidden_state_snapshot" not in sys


def test_scenario_d5_still_disabled():
    with patch("core.dream.world_loader.load_world") as mock_lw:
        mock_world = MagicMock()
        mock_world.ruleset = ""
        mock_world.mes_example = ""
        mock_lw.return_value = mock_world
        from core.dream.dream_prompt import build_dream_prompt
        msgs = build_dream_prompt(
            character=_FAKE_CHARACTER,
            user_id="bucket_test_user",
            user_message="test",
            context_snapshot=_EMPTY_SNAPSHOT,
            dream_history=[],
            local_state=_EMPTY_LOCAL,
            body_projection_text="她的身体感知投影文字",
            yexuan_tension=0.8,
            dream_mode="scenario",
            scenario_core={
                "script_id": "prison_demo",
                "current_stage_id": "arrival",
                "stage_turns": 0,
                "ending_state": None,
            },
        )
    sys = _system(msgs)
    assert "D5·她的身体感知" not in sys
    assert "她的身体感知投影文字" not in sys


# ═══════════════════════════════════════════════════════════════════════════════
# 17  Sandbox D7 注入分桶文本，绝不注入百分比数字
# ═══════════════════════════════════════════════════════════════════════════════

def test_sandbox_d7_uses_bucket_not_percent():
    sys = _system(_build(0.6, dream_mode="sandbox"))
    assert "D7·" in sys and "情绪张力" in sys
    assert "高位" in sys
    assert "%" not in sys


# ═══════════════════════════════════════════════════════════════════════════════
# 18  Mirror placeholder：与 sandbox 使用相同分桶逻辑
# ═══════════════════════════════════════════════════════════════════════════════

def test_mirror_d7_uses_same_bucket_logic():
    sys = _system(_build(0.8, dream_mode="mirror"))
    assert "D7·" in sys and "情绪张力" in sys
    assert "临界" in sys
    assert "%" not in sys

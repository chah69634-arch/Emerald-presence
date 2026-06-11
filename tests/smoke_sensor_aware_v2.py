"""
Smoke test for core.scheduler.triggers.sensor_aware (三层架构版)
Run from project root: python -X utf8 tests/smoke_sensor_aware_v2.py

场景 A — tick() 返回 [] → 静默 return
场景 B — score=20 (< passive_speak 阈值 35) → BehaviorPlanner 返回 None，不调 LLM
场景 C — LONG_FOCUS, score=40 → passive_speak，只推 channel_message，无 action
场景 D — LATE_NIGHT_ACTIVE, score=85 → direct_act，推 channel_message + execute action
场景 E — PRESENCE_RETURNED, score=70 → 封顶 soft_hint，推 channel_message + pet_emote
场景 F — 全局冷却内 (get_last_proactive_at 返回 5 分钟前) → 静默 return，不调 LLM
"""
import asyncio
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import core.scheduler.triggers.sensor_aware as sa


# ── 共用 fixture 数据 ─────────────────────────────────────────────────────────

def _mk_event(event_type: str, **ctx_overrides) -> dict:
    ctx = {
        "local_hour": 15,
        "presence": "active",
        "focus_app": "Code.exe",
        "focus_title_hint": "ChatPanel.tsx",
        "continuous_at_desk_seconds": 5400,
        "minutes_since_last_chat": 70,
        "keystroke_density": "一般",
        **ctx_overrides,
    }
    narratives = {
        "LONG_FOCUS":        "她已经在 Code.exe 里连续工作了 26 分钟。",
        "LATE_NIGHT_ACTIVE": "已经凌晨 2 点了，她还醒着。",
        "PRESENCE_RETURNED": "她回来了，刚离开了 8 分钟。",
        "GENERIC":           "她的状态发生了变化。",
    }
    return {
        "type": event_type,
        "narrative": narratives.get(event_type, narratives["GENERIC"]),
        "context": ctx,
    }


def _mk_judge(score: int) -> dict:
    def _tier(s: int) -> str:
        if s < 41: return "drop"
        if s <= 55: return "weak"
        if s <= 70: return "medium"
        if s <= 85: return "strong"
        return "must"
    return {"score": score, "reason": "smoke-test", "intent_tier": _tier(score)}


def ok(cond: bool, label: str):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")


# ── 场景 A ────────────────────────────────────────────────────────────────────

async def scene_a():
    print("\n=== 场景 A: tick() 返回 [] → 静默 return ===")

    with (
        patch("core.scheduler.sensor_events.tick", return_value=[]),
        patch(
            "core.scheduler.triggers.sensor_aware._pipeline_send",
            new_callable=AsyncMock,
        ) as mock_send,
        patch("channels.desktop_ws.push_message", new_callable=AsyncMock) as mock_msg,
    ):
        await sa.handle_tick()

    ok(mock_send.call_count == 0, "_pipeline_send 未被调用")
    ok(mock_msg.call_count == 0,  "push_message 未被调用")


# ── 场景 B ────────────────────────────────────────────────────────────────────

async def scene_b():
    print("\n=== 场景 B: score=20 < 35 → BehaviorPlanner.plan() 返回 None，不调 LLM ===")
    ev = _mk_event("LONG_FOCUS")

    with (
        patch("core.scheduler.sensor_events.tick", return_value=[ev]),
        patch(
            "core.scheduler.sensor_judge.judge",
            new_callable=AsyncMock,
            return_value=_mk_judge(20),
        ),
        patch(
            "core.scheduler.sensor_events.get_last_proactive_at",
            return_value=None,
        ),
        patch(
            "core.scheduler.triggers.sensor_aware._pipeline_send",
            new_callable=AsyncMock,
        ) as mock_send,
        patch("channels.desktop_ws.push_message", new_callable=AsyncMock) as mock_msg,
    ):
        await sa.handle_tick()

    ok(mock_send.call_count == 0, "_pipeline_send 未被调用")
    ok(mock_msg.call_count == 0,  "push_message 未被调用")
    # BehaviorPlanner 直接丢弃，不走冷却检查
    plan_result = sa.plan(ev, 20)
    ok(plan_result is None, "plan(score=20) 返回 None")


# ── 场景 C ────────────────────────────────────────────────────────────────────

async def scene_c():
    print("\n=== 场景 C: LONG_FOCUS score=40 → passive_speak，只推 channel_message ===")
    ev = _mk_event("LONG_FOCUS")
    _REPLY = "去休息一会儿吧。"

    with (
        patch("core.scheduler.sensor_events.tick", return_value=[ev]),
        patch(
            "core.scheduler.sensor_judge.judge",
            new_callable=AsyncMock,
            return_value=_mk_judge(40),
        ),
        patch(
            "core.scheduler.sensor_events.get_last_proactive_at",
            return_value=None,
        ),
        patch(
            "core.scheduler.triggers.sensor_aware._pipeline_send",
            new_callable=AsyncMock,
            return_value=_REPLY,
        ) as mock_send,
        patch(
            "channels.desktop_ws.push_message",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_msg,
        patch(
            "channels.desktop_ws.push_action_and_wait",
            new_callable=AsyncMock,
            return_value=(True, None),
        ) as mock_action,
        patch("core.scheduler.sensor_events.mark_proactive_sent") as mock_mark,
        patch("core.scheduler.triggers.sensor_aware._char_name", return_value="Companion"),
    ):
        await sa.handle_tick()

    ok(mock_send.call_count == 1,   "_pipeline_send 被调用一次")
    ok(mock_msg.call_count == 1,    "push_message 被调用一次")
    ok(mock_msg.call_args[0][0] == _REPLY, f"push_message 内容正确 ({_REPLY!r})")
    ok(mock_action.call_count == 0, "push_action_and_wait 未调用（passive_speak）")
    ok(mock_mark.call_count == 1,   "mark_proactive_sent 被调用")

    # 验证 behavior 映射
    behavior = sa.plan(ev, 40)
    ok(behavior is not None and behavior["level"] == "passive_speak",
       "plan(LONG_FOCUS, 40) → passive_speak")
    ok(behavior is not None and behavior["behavior_id"] == "casual_check_in",
       'behavior_id = "casual_check_in"')


# ── 场景 D ────────────────────────────────────────────────────────────────────

async def scene_d():
    print("\n=== 场景 D: LATE_NIGHT_ACTIVE score=85 → direct_act，推 execute action ===")
    ev = _mk_event(
        "LATE_NIGHT_ACTIVE",
        local_hour=2,
        continuous_at_desk_seconds=7500,
        minutes_since_last_chat=90,
    )
    _REPLY = "已经很晚了。"

    with (
        patch("core.scheduler.sensor_events.tick", return_value=[ev]),
        patch(
            "core.scheduler.sensor_judge.judge",
            new_callable=AsyncMock,
            return_value=_mk_judge(85),
        ),
        patch(
            "core.scheduler.sensor_events.get_last_proactive_at",
            return_value=None,
        ),
        patch(
            "core.scheduler.triggers.sensor_aware._pipeline_send",
            new_callable=AsyncMock,
            return_value=_REPLY,
        ) as mock_send,
        patch(
            "channels.desktop_ws.push_message",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_msg,
        patch(
            "channels.desktop_ws.push_action_and_wait",
            new_callable=AsyncMock,
            return_value=(True, None),
        ) as mock_action,
        patch("core.scheduler.sensor_events.mark_proactive_sent"),
        patch("core.scheduler.triggers.sensor_aware._char_name", return_value="Companion"),
    ):
        await sa.handle_tick()

    ok(mock_send.call_count == 1,   "_pipeline_send 被调用一次")
    ok(mock_msg.call_count == 1,    "push_message 被调用一次")
    ok(mock_action.call_count == 1, "push_action_and_wait 被调用一次")

    if mock_action.call_count == 1:
        action_arg = mock_action.call_args[0][0]  # 第一个位置参数
        ok(action_arg.get("action_type") == "execute",
           'action_type = "execute"')
        ok(action_arg.get("params", {}).get("behavior_id") == "late_night_lock_hint",
           'behavior_id = "late_night_lock_hint"')

    # 验证 behavior 映射
    behavior = sa.plan(ev, 85)
    ok(behavior is not None and behavior["level"] == "direct_act",
       "plan(LATE_NIGHT_ACTIVE, 85) → direct_act")


# ── 场景 E ────────────────────────────────────────────────────────────────────

async def scene_e():
    print("\n=== 场景 E: PRESENCE_RETURNED score=70 → 封顶 soft_hint → pet_emote ===")
    # score=70 在全局阈值表里应该是 attention_grab，但 PRESENCE_RETURNED 封顶 soft_hint
    ev = _mk_event("PRESENCE_RETURNED")
    _REPLY = "回来了。"

    with (
        patch("core.scheduler.sensor_events.tick", return_value=[ev]),
        patch(
            "core.scheduler.sensor_judge.judge",
            new_callable=AsyncMock,
            return_value=_mk_judge(70),
        ),
        patch(
            "core.scheduler.sensor_events.get_last_proactive_at",
            return_value=None,
        ),
        patch(
            "core.scheduler.triggers.sensor_aware._pipeline_send",
            new_callable=AsyncMock,
            return_value=_REPLY,
        ),
        patch(
            "channels.desktop_ws.push_message",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "channels.desktop_ws.push_action_and_wait",
            new_callable=AsyncMock,
            return_value=(True, None),
        ) as mock_action,
        patch("core.scheduler.sensor_events.mark_proactive_sent"),
        patch("core.scheduler.triggers.sensor_aware._char_name", return_value="Companion"),
    ):
        await sa.handle_tick()

    if mock_action.call_count == 1:
        action_arg = mock_action.call_args[0][0]
        ok(action_arg.get("action_type") == "pet_emote",
           'action_type = "pet_emote"（不是 "notify"）')
    else:
        ok(False, f"push_action_and_wait 应被调用一次，实际 {mock_action.call_count} 次")

    # 验证 behavior 映射
    behavior = sa.plan(ev, 70)
    ok(behavior is not None and behavior["level"] == "soft_hint",
       "plan(PRESENCE_RETURNED, 70) → soft_hint（不升级到 attention_grab）")


# ── 场景 F ────────────────────────────────────────────────────────────────────

async def scene_f():
    print("\n=== 场景 F: 全局冷却内（5 分钟前主动发过）→ 静默 return ===")
    ev = _mk_event("LONG_FOCUS")
    five_min_ago = time.time() - 5 * 60  # 5 min < 8 min cooldown

    with (
        patch("core.scheduler.sensor_events.tick", return_value=[ev]),
        patch(
            "core.scheduler.sensor_judge.judge",
            new_callable=AsyncMock,
            return_value=_mk_judge(60),
        ),
        patch(
            "core.scheduler.sensor_events.get_last_proactive_at",
            return_value=five_min_ago,
        ),
        patch(
            "core.scheduler.triggers.sensor_aware._pipeline_send",
            new_callable=AsyncMock,
        ) as mock_send,
        patch("channels.desktop_ws.push_message", new_callable=AsyncMock) as mock_msg,
    ):
        await sa.handle_tick()

    ok(mock_send.call_count == 0, "_pipeline_send 未被调用（冷却拦截）")
    ok(mock_msg.call_count == 0,  "push_message 未被调用")


# ── 入口 ──────────────────────────────────────────────────────────────────────

async def main():
    await scene_a()
    await scene_b()
    await scene_c()
    await scene_d()
    await scene_e()
    await scene_f()
    print("\n=== Smoke 完成 ===\n")


if __name__ == "__main__":
    asyncio.run(main())

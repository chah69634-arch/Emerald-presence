from datetime import date, datetime


def test_hr_critical_propose_absent_when_heart_rate_normal():
    from core.scheduler.triggers import watch

    proposal = watch.propose({
        "now_ts": 1_000.0,
        "heart_rate_event": {"value": 85, "hour": 14, "received_at": 990.0},
    })

    assert proposal is None


def test_hr_critical_propose_uses_must_not_miss_tier_when_over_threshold():
    from core.scheduler.triggers import watch

    proposal = watch.propose({
        "now_ts": 1_000.0,
        "heart_rate_event": {"value": 140, "hour": 14, "received_at": 990.0},
    })

    assert proposal.trigger_name == "hr_critical"
    assert 0.90 <= proposal.urgency <= 1.00
    assert proposal.bypass_state_machine is True


def test_birthday_propose_preserves_four_time_windows(monkeypatch):
    from core.scheduler.triggers import birthday

    monkeypatch.setattr(birthday, "_cfg", lambda: {"owner_birthday": "04-24"})

    cases = [
        (datetime(2026, 4, 23, 20, 0), "birthday_eve"),
        (datetime(2026, 4, 24, 0, 4), "birthday_midnight"),
        (datetime(2026, 4, 24, 14, 0), "birthday_afternoon"),
        (datetime(2026, 4, 24, 21, 0), "birthday_night"),
    ]
    for now_dt, trigger_name in cases:
        proposal = birthday.propose({"now_dt": now_dt})
        assert proposal.trigger_name == trigger_name
        assert 0.90 <= proposal.urgency <= 1.00
        assert proposal.bypass_state_machine is True

    assert birthday.propose({"now_dt": datetime(2026, 4, 24, 8, 0)}) is None


def test_period_propose_uses_real_windows(monkeypatch):
    from core.scheduler.triggers import period

    monkeypatch.setattr(period, "_days_elapsed", lambda uid, today=None: today.day)

    in_period = period.propose({"uid": "u1", "today": date(2026, 5, 3)})
    upcoming = period.propose({"uid": "u1", "today": date(2026, 5, 29)})
    outside = period.propose({"uid": "u1", "today": date(2026, 5, 12)})

    assert in_period.trigger_name == "period_reminder"
    assert upcoming.trigger_name == "period_reminder"
    assert 0.70 <= in_period.urgency <= 0.89
    assert 0.70 <= upcoming.urgency <= 0.89
    assert in_period.bypass_state_machine is True
    assert outside is None


def test_gating_shadow_collects_native_from_registry(monkeypatch):
    from core.scheduler import gating
    from core.scheduler import proposer_registry
    from core.scheduler.gating import TriggerProposal
    from core.scheduler.state_machine import TriggerState

    native = TriggerProposal(
        trigger_name="period_reminder",
        urgency=0.8,
        topic_source="mood_match",
        requires_state=[TriggerState.CHATTING, TriggerState.QUIET, TriggerState.RESTLESS],
        bypass_state_machine=True,
    )

    proposer_registry._reset_for_tests()
    monkeypatch.setattr(proposer_registry, "_BUILTINS_LOADED", True)
    proposer_registry.register_proposer("period_reminder", lambda ctx: native)

    proposals = gating._collect_native_proposals({"uid": "u1"})

    assert [p.trigger_name for p in proposals] == ["period_reminder"]
    proposer_registry._reset_for_tests()


def test_window_event_proposals_use_window_tier(monkeypatch):
    from core.scheduler.triggers import festival, timenode

    monkeypatch.setattr(timenode, "_cfg", lambda: {"timenode": True})
    monkeypatch.setattr(timenode, "_owner_id", lambda: "u1")
    monkeypatch.setattr(timenode, "_get_timenode", lambda today=None: "monday")
    t = timenode.propose({"now_dt": datetime(2026, 5, 25, 18, 0)})

    monkeypatch.setattr(festival, "_cfg", lambda: {"festival": True, "holiday_boost": True})
    monkeypatch.setattr(festival, "_owner_id", lambda: "u1")
    monkeypatch.setattr(festival, "_get_today_festival", lambda today=None: ("x", "prompt"))
    f = festival.propose_festival({"now_dt": datetime(2026, 5, 25, 18, 0)})

    assert 0.70 <= t.urgency <= 0.89
    assert 0.70 <= f.urgency <= 0.89


def test_weather_heavy_propose_uses_window_event_tier(monkeypatch):
    from core.scheduler.triggers import time_based

    monkeypatch.setattr(time_based, "_cfg", lambda: {"enabled": True})
    detail = {
        "temp_c": 31,
        "humidity": 50,
        "precip_mm": 0.0,
        "cloud_cover": 50,
        "wind_kmph": 10,
        "desc": "晴",
        "is_day": True,
        "uv_index": 3,
        "received_at": datetime(2026, 5, 25, 12, 0).timestamp(),
    }

    proposal = time_based.propose_weather_alert({
        "now_dt": datetime(2026, 5, 25, 12, 0),
        "now_ts": datetime(2026, 5, 25, 12, 0).timestamp(),
        "weather_detail": detail,
    })

    assert proposal.trigger_name == "weather_alert"
    assert 0.70 <= proposal.urgency <= 0.89


def test_reminders_propose_bypasses_state_machine(monkeypatch):
    from core.scheduler.triggers import reminders

    monkeypatch.setattr("core.scheduler.loop._owner_id", lambda: "u1")
    proposal = reminders.propose({
        "now_dt": datetime(2026, 5, 25, 12, 30),
        "due_reminders": [{"id": "r1", "content": "x", "remind_at": "2026-05-25 12:00"}],
    })

    assert proposal.trigger_name == "reminders"
    assert proposal.bypass_state_machine is True
    assert 0.70 <= proposal.urgency <= 0.89


def test_reactive_watch_proposals_use_recent_events():
    from core.scheduler.triggers import watch

    hr = watch.propose_hr_high({
        "now_ts": 1_000.0,
        "heart_rate_event": {"value": 110, "hour": 14, "received_at": 990.0},
    })
    sleep = watch.propose_sleep_end({
        "now_ts": 1_000.0,
        "sleep_end_event": {"duration_minutes": 420, "received_at": 990.0},
    })

    assert hr.trigger_name == "hr_high"
    assert sleep.trigger_name == "sleep_end"
    assert 0.30 <= hr.urgency <= 0.49
    assert 0.30 <= sleep.urgency <= 0.49


def test_topic_followup_propose_uses_growth_unfollowed_topic(monkeypatch):
    from core.scheduler.triggers import memory

    monkeypatch.setattr(memory, "_cfg", lambda: {"topic_followup": True})
    monkeypatch.setattr(memory, "_owner_id", lambda: "u1")
    growth = "## 未跟进话题\n- 实习: 她说还没定\n"

    proposal = memory.propose({
        "now_dt": datetime(2026, 5, 25, 16, 0),
        "character_growth": growth,
    })

    assert proposal.trigger_name == "topic_followup"
    assert 0.30 <= proposal.urgency <= 0.49


def test_garden_reactive_proposals_use_cached_events():
    from core.scheduler.triggers import garden_daily, garden_water

    bloom = garden_water.propose_garden_bloom({
        "now_ts": 1_000.0,
        "garden_bloom_events": [{"type": "bloom", "name": "雏菊", "received_at": 990.0}],
    })
    ask = garden_daily.propose_garden_handle_ask({
        "now_ts": 1_000.0,
        "garden_daily_events": [
            {"type": "harvest_handle", "handle_action": "ask", "name": "雏菊", "received_at": 990.0}
        ],
    })

    assert bloom.trigger_name == "garden_bloom"
    assert ask.trigger_name == "garden_handle_ask"
    assert 0.30 <= bloom.urgency <= 0.49
    assert 0.30 <= ask.urgency <= 0.49


def test_weather_light_propose_uses_reactive_tier(monkeypatch):
    from core.scheduler.triggers import time_based

    monkeypatch.setattr(time_based, "_cfg", lambda: {"enabled": True})
    now = datetime(2026, 5, 25, 12, 0)
    detail = {
        "temp_c": 22,
        "humidity": 50,
        "precip_mm": 1.0,
        "cloud_cover": 50,
        "wind_kmph": 10,
        "desc": "小雨",
        "is_day": True,
        "uv_index": 3,
        "received_at": now.timestamp(),
    }

    proposal = time_based.propose_weather_alert_light({
        "now_dt": now,
        "now_ts": now.timestamp(),
        "weather_detail": detail,
    })

    assert proposal.trigger_name == "weather_alert"
    assert 0.30 <= proposal.urgency <= 0.49


def test_filler_proposals_use_silence_ratio(monkeypatch):
    from core.scheduler.triggers import time_based

    now = datetime(2026, 5, 25, 15, 0)
    monkeypatch.setattr(time_based, "_cfg", lambda: {"random_message": True})
    monkeypatch.setattr(time_based, "_owner_id", lambda: "u1")
    monkeypatch.setattr("core.scheduler.rhythm.silence_ratio", lambda uid, now_ts=None: 1.0)
    monkeypatch.setattr("core.memory.episodic_memory._load_memories", lambda uid: [{"strength": 0.8}])

    random_message = time_based.propose_random_message({"now_dt": now, "now_ts": now.timestamp()})
    recall = time_based.propose_spontaneous_recall({"now_dt": now, "now_ts": now.timestamp()})

    assert random_message.trigger_name == "random_message"
    assert recall.trigger_name == "spontaneous_recall"
    assert 0.10 <= random_message.urgency <= 0.29
    assert 0.10 <= recall.urgency <= 0.29

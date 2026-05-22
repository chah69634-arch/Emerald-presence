import logging
import time
from datetime import datetime

from core.scheduler.loop import _is_ready, _mark, _owner_id, _pipeline_send, _cfg, _char_name

logger = logging.getLogger(__name__)

HR_HIGH_THRESHOLD = 100
HR_CRITICAL_THRESHOLD = 120
HEART_RATE_PROPOSAL_TTL_SECONDS = 10 * 60

_LAST_HEART_RATE_EVENT: dict | None = None


def _remember_heart_rate(hr: int, hour: int) -> None:
    global _LAST_HEART_RATE_EVENT
    _LAST_HEART_RATE_EVENT = {
        "value": hr,
        "hour": hour,
        "received_at": time.time(),
    }


def get_last_heart_rate_event() -> dict | None:
    return dict(_LAST_HEART_RATE_EVENT) if _LAST_HEART_RATE_EVENT else None


def propose(ctx: dict | None = None):
    ctx = ctx or {}
    event = ctx.get("heart_rate_event") or get_last_heart_rate_event()
    if not event:
        return None
    now_ts = float(ctx.get("now_ts") or time.time())
    received_at = float(event.get("received_at") or 0)
    if now_ts - received_at > HEART_RATE_PROPOSAL_TTL_SECONDS:
        return None
    hr = int(event.get("value") or 0)
    hour = int(event.get("hour", datetime.now().hour))
    if 6 <= hour < 8:
        return None
    if hr <= HR_CRITICAL_THRESHOLD:
        return None

    from core.scheduler.gating import TriggerProposal
    from core.scheduler.state_machine import TriggerState
    from core.scheduler.urgency import UrgencyTier, urgency_in_tier

    ratio = (hr - HR_CRITICAL_THRESHOLD) / 40
    return TriggerProposal(
        trigger_name="hr_critical",
        urgency=urgency_in_tier(UrgencyTier.MUST_NOT_MISS, ratio),
        topic_source="mood_match",
        requires_state=[TriggerState.CHATTING, TriggerState.QUIET, TriggerState.RESTLESS],
        bypass_state_machine=True,
    )


async def on_watch_event(event_type: str, data: dict):
    """
    接收 Watch 事件并触发主动行为。

    event_type:
        "heart_rate"  — data = {"value": int}
        "sleep_end"   — data = {"duration_minutes": float, "sleep_start": str, ...}
    """
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return
    if not _owner_id():
        return

    if event_type == "heart_rate":
        hr = int(data.get("value", 0))
        now_hour = datetime.now().hour
        _remember_heart_rate(hr, now_hour)

        # 06-08点跳过，可能晨跑
        if 6 <= now_hour < 8:
            logger.info(f"[scheduler] 心率数据在早晨，跳过触发 hr={hr}")
            return

        # 深夜(22-06点)降低阈值，>100就关心
        in_night = now_hour >= 22 or now_hour < 6
        if in_night:
            if hr > HR_CRITICAL_THRESHOLD and _is_ready("hr_critical"):
                await _pipeline_send(f"（深夜，{_char_name()}看到你的心率{hr}）", trigger_name="hr_critical")
                _mark("hr_critical")
                logger.info(f"[scheduler] 深夜心率危急触发 hr={hr}")
            elif hr > HR_HIGH_THRESHOLD and _is_ready("hr_high"):
                await _pipeline_send(f"（深夜，{_char_name()}注意到你的心率{hr}）", trigger_name="hr_high")
                _mark("hr_high")
                logger.info(f"[scheduler] 深夜心率偏高触发 hr={hr}")
        else:
            if hr > HR_CRITICAL_THRESHOLD and _is_ready("hr_critical"):
                await _pipeline_send(f"（{_char_name()}看到你的心率{hr}，皱了皱眉）", trigger_name="hr_critical")
                _mark("hr_critical")
                logger.info(f"[scheduler] 心率危急触发 hr={hr}")
            elif hr > HR_HIGH_THRESHOLD and _is_ready("hr_high"):
                await _pipeline_send(f"（{_char_name()}看到你的心率有点高，{hr}）", trigger_name="hr_high")
                _mark("hr_high")
                logger.info(f"[scheduler] 心率偏高触发 hr={hr}")

    elif event_type == "sleep_end":
        if not _is_ready("sleep_end"):
            return
        prompt = str(data.get("prompt") or "").strip()
        if not prompt:
            duration = float(data.get("duration_minutes", 0) or 0)
            hours = int(duration // 60)
            minutes = int(duration % 60)
            prompt = f"（{_char_name()}看到你醒了，睡了{hours}小时{minutes}分钟）"
        _mark("sleep_end")
        _mark("morning_greeting")
        await _pipeline_send(prompt, trigger_name="sleep_end")
        logger.info("[scheduler] 睡醒关心已触发")

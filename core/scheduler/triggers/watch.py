import logging

from core.scheduler.loop import _is_ready, _mark, _owner_id, _pipeline_send, _cfg, _char_name

logger = logging.getLogger(__name__)


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
        now_hour = __import__("datetime").datetime.now().hour

        # 06-08点跳过，可能晨跑
        if 6 <= now_hour < 8:
            logger.info(f"[scheduler] 心率数据在早晨，跳过触发 hr={hr}")
            return

        # 深夜(22-06点)降低阈值，>100就关心
        in_night = now_hour >= 22 or now_hour < 6
        if in_night:
            if hr > 120 and _is_ready("hr_critical"):
                await _pipeline_send(f"（深夜，{_char_name()}看到你的心率{hr}）", trigger_name="hr_critical")
                _mark("hr_critical")
                logger.info(f"[scheduler] 深夜心率危急触发 hr={hr}")
            elif hr > 100 and _is_ready("hr_high"):
                await _pipeline_send(f"（深夜，{_char_name()}注意到你的心率{hr}）", trigger_name="hr_high")
                _mark("hr_high")
                logger.info(f"[scheduler] 深夜心率偏高触发 hr={hr}")
        else:
            if hr > 120 and _is_ready("hr_critical"):
                await _pipeline_send(f"（{_char_name()}看到你的心率{hr}，皱了皱眉）", trigger_name="hr_critical")
                _mark("hr_critical")
                logger.info(f"[scheduler] 心率危急触发 hr={hr}")
            elif hr > 100 and _is_ready("hr_high"):
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

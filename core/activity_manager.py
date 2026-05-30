"""
activity_manager — 角色当前活动状态管理。
每15-45分钟（随机）切换一次 activity，受 daily_arc 时段约束。
activity_pool.yaml 是手写配置，定义角色会做的事。
"""
import json
import logging
import random
import time
from datetime import datetime
from pathlib import Path

import yaml

from core.sandbox import get_paths, _TRANSITION_CHARACTER_INNER

logger = logging.getLogger(__name__)

# 时段定义（小时列表）
ARCS = {
    "deep_night":   [23, 0, 1, 2, 3, 4, 5],
    "morning":      [5, 6, 7, 8, 9],
    "late_morning": [9, 10, 11, 12],
    "afternoon":    [12, 13, 14, 15, 16, 17],
    "evening":      [17, 18, 19, 20, 21, 22, 23],
}

def _get_current_arc() -> str:
    hour = datetime.now().hour
    for arc, hours in ARCS.items():
        if hour in hours:
            return arc
    return "afternoon"

def _load_pool() -> list:
    try:
        pool_path = get_paths().activity_pool()
        with open(pool_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("activities", [])
    except Exception as e:
        logger.warning(f"[activity] 加载activity_pool失败: {e}")
        return []

def _load_state() -> dict:
    try:
        return json.loads(get_paths().activity_state().read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_state(state: dict) -> None:
    p = get_paths().activity_state()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    if _TRANSITION_CHARACTER_INNER:
        old = get_paths()._p("yexuan_inner", "activity_state.json")
        old.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def _load_thinking_about(uid: str = "") -> str:
    """
    从 episodic_memory 抽一条具体事件作为 thinking_about。
    按 strength 加权随机，只取最近30天、strength>0.4、有 summary 的记忆。
    """
    if not uid:
        try:
            from core.config_loader import get_config
            uid = get_config().get("default_user_id", "")
        except Exception:
            return ""
    if not uid:
        return ""

    try:
        from core.memory.episodic_memory import _load_memories
        memories = _load_memories(uid)
        if not memories:
            return ""

        now = time.time()
        candidates = [
            m for m in memories
            if (now - m.get("timestamp", 0)) < 30 * 86400
            and m.get("strength", 0) > 0.4
            and m.get("summary", "")
        ]
        if not candidates:
            return ""

        total = sum(m.get("strength", 0.5) for m in candidates)
        r = random.uniform(0, total)
        acc = 0
        chosen = candidates[0]
        for m in candidates:
            acc += m.get("strength", 0.5)
            if r <= acc:
                chosen = m
                break

        summary = chosen.get("summary", "")
        anchor = chosen.get("id", "")
        if not summary or not anchor:
            return ""

        return summary

    except Exception as e:
        logger.warning(f"[activity] 读取thinking_about失败: {e}")
        return ""

def _pick_activity(arc: str) -> dict:
    """按当前时段随机抽一个activity。"""
    pool = _load_pool()
    eligible = [a for a in pool if arc in a.get("arcs", [])]
    if not eligible:
        eligible = pool
    if not eligible:
        return {"id": "thinking", "text": "在思考"}
    chosen = random.choice(eligible)
    # 处理reading的book占位符
    text = chosen.get("text", "在思考")
    if "{book}" in text:
        books = chosen.get("books", ["一本书"])
        text = text.replace("{book}", random.choice(books))
    return {**chosen, "text": text}

def should_switch() -> bool:
    """判断是否需要切换activity（距上次切换超过15-45分钟随机值）。"""
    state = _load_state()
    if not state:
        return True
    expected_until = state.get("expected_until_ts", 0)
    return time.time() > expected_until

def switch_activity() -> dict:
    """切换到新activity，返回新状态。"""
    arc = _get_current_arc()
    activity = _pick_activity(arc)
    now = datetime.now()
    # 随机持续15-45分钟
    duration_min = random.randint(15, 45)
    expected_until_ts = time.time() + duration_min * 60

    thinking_about = ""
    if activity.get("thinking_about_eligible"):
        try:
            from core.config_loader import get_config
            _uid = get_config().get("default_user_id", "")
        except Exception:
            _uid = ""
        thinking_about = _load_thinking_about(_uid)

    state = {
        "current": activity["text"],
        "started_at": now.isoformat(),
        "expected_until_ts": expected_until_ts,
        "thinking_about": thinking_about,
        "arc": arc,
    }
    _save_state(state)
    logger.info(f"[activity] 切换: {activity['text']} (arc={arc}, {duration_min}分钟)")
    return state

def get_current() -> dict:
    """获取当前activity状态，必要时自动切换。"""
    if should_switch():
        return switch_activity()
    return _load_state()

_PATTERN_WORDS = ["每次", "总是", "一直", "从来", "每天", "每周"]

def get_prompt_fragment() -> str:
    """返回注入prompt的文本片段，50字以内。"""
    state = get_current()
    current = state.get("current", "")
    thinking = state.get("thinking_about", "")
    if not current:
        return ""
    if thinking:
        if any(w in thinking for w in _PATTERN_WORDS):
            thinking = f"好像{thinking}"
        return f"{current}，想着：{thinking}"
    return current

"""
core/memory/tool_read_log.py
============================
P2: 工具已读指纹日志，防止 persist=True 工具在同一 uid/char 重复触发同一文件。

存储路径：data/runtime/memory/{char_id}/{uid}/tool_read_log.json
格式：{"fingerprints": ["fp1", "fp2", ...]}  (最近 _MAX_LOG 条，FIFO)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from core.sandbox import get_paths, safe_user_id
from core.safe_write import safe_write_json

logger = logging.getLogger(__name__)

_MAX_LOG = 30


def _log_path(uid: str, char_id: str) -> Path:
    return get_paths().user_memory_root(safe_user_id(uid), char_id=char_id) / "tool_read_log.json"


def build_fingerprint(tool_name: str, tool_args: dict) -> str | None:
    """根据工具名和参数构建来源指纹。仅限 persist=True 工具，其余返回 None。"""
    if tool_name == "read_diary":
        date = (tool_args.get("date") or "").strip()
        if not date:
            from datetime import date as _date
            date = _date.today().strftime("%Y-%m-%d")
        return f"diary:{date}"
    if tool_name == "read_toy_file":
        return f"toy:{tool_args.get('file_key', '')}"
    if tool_name == "read_watch":
        query = (tool_args.get("query") or "").strip() or "summary"
        from datetime import date as _date
        return f"watch:{_date.today().strftime('%Y-%m-%d')}:{query}"
    if tool_name == "search_diary":
        query = (tool_args.get("query") or "").strip()
        return f"search_diary:{query}"
    return None


def is_recently_read(uid: str, char_id: str, fingerprint: str) -> bool:
    """检查该指纹是否已在最近已读集合中。"""
    path = _log_path(uid, char_id)
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return fingerprint in data.get("fingerprints", [])
    except Exception as e:
        logger.debug("[tool_read_log] is_recently_read error: %s", e)
    return False


def record_read(uid: str, char_id: str, fingerprint: str) -> None:
    """记录一条已读指纹，超出上限时按 FIFO 丢弃最旧的。"""
    path = _log_path(uid, char_id)
    try:
        data: dict = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        fps: list = data.get("fingerprints", [])
        if fingerprint not in fps:
            fps.append(fingerprint)
        fps = fps[-_MAX_LOG:]
        path.parent.mkdir(parents=True, exist_ok=True)
        safe_write_json(path, {"fingerprints": fps})
    except Exception as e:
        logger.warning("[tool_read_log] record_read failed: %s", e)


def format_read_memo(tool_name: str, tool_args: dict) -> str:
    """生成叶瑄视角的"读了《X》"一句（作为 assistant 条目写入 short_term）。"""
    if tool_name == "read_diary":
        date = (tool_args.get("date") or "").strip()
        if date:
            return f"把你{date}的日记读了一遍。"
        return "把你今天的日记读了一遍。"
    if tool_name == "read_toy_file":
        label_map = {"diary": "思考笔记", "wishlist": "愿望清单", "doodle": "涂鸦板"}
        label = label_map.get(str(tool_args.get("file_key", "")), "文件")
        return f"把{label}翻了翻。"
    if tool_name == "read_watch":
        return "看了一眼你最近的身体数据。"
    if tool_name == "search_diary":
        q = (tool_args.get("query") or "").strip()
        if q:
            return f"在你的日记里搜了一下「{q}」。"
        return "在你的日记里翻了翻。"
    return ""

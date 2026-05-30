"""
日记上下文独立存储
日记内容不写入 event_log，单独存储，只注入 prompt 不参与检索。
"""
from pathlib import Path
from core.error_handler import log_error
from core.sandbox import get_paths, safe_user_id


def _diary_context_read_path(user_id: str, *, char_id: str = "yexuan") -> Path:
    uid = safe_user_id(user_id)
    return get_paths().user_memory_root(uid, char_id=char_id) / "diary_context.txt"


def _diary_context_write_path(user_id: str, *, char_id: str = "yexuan") -> Path:
    """写路径：始终写新布局。"""
    uid = safe_user_id(user_id)
    p = get_paths().user_memory_root(uid, char_id=char_id) / "diary_context.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def save(user_id: str, text: str, *, char_id: str = "yexuan"):
    try:
        _diary_context_write_path(user_id, char_id=char_id).write_text(text, encoding="utf-8")
    except Exception as e:
        log_error("diary_context.save", e)


def load(user_id: str, *, char_id: str = "yexuan") -> str:
    try:
        p = _diary_context_read_path(user_id, char_id=char_id)
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    except Exception as e:
        log_error("diary_context.load", e)
    return ""
import json
import logging
from enum import Enum
from typing import Any

from core.safe_write import safe_write_json
from core.sandbox import get_paths, safe_user_id

logger = logging.getLogger(__name__)


class DreamStatus(str, Enum):
    REALITY_CHAT = "REALITY_CHAT"
    DREAM_ENTRANCE_AVAILABLE = "DREAM_ENTRANCE_AVAILABLE"
    DREAM_ACTIVE = "DREAM_ACTIVE"
    DREAM_EXIT_REQUESTED = "DREAM_EXIT_REQUESTED"
    DREAM_LOCKED = "DREAM_LOCKED"
    DREAM_CLOSING = "DREAM_CLOSING"
    REALITY_AFTERGLOW = "REALITY_AFTERGLOW"


def default_state(user_id: str | int) -> dict[str, Any]:
    return {
        "user_id": safe_user_id(user_id),
        "status": DreamStatus.REALITY_CHAT.value,
    }


def read_state(user_id: str | int) -> dict[str, Any]:
    path = get_paths().dream_state_path(user_id)
    if not path.exists():
        return default_state(user_id)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[dream_state] read failed uid={user_id}: {e}")
        return default_state(user_id)

    if not isinstance(data, dict):
        logger.warning(f"[dream_state] invalid state shape uid={user_id}")
        return default_state(user_id)

    status = data.get("status")
    if status not in {item.value for item in DreamStatus}:
        logger.warning(f"[dream_state] unknown status uid={user_id}: {status!r}")
        return default_state(user_id)

    data.setdefault("user_id", safe_user_id(user_id))
    return data


def write_state(user_id: str | int, state: dict[str, Any]) -> bool:
    if not isinstance(state, dict):
        raise TypeError("dream state must be a dict")

    status = state.get("status")
    if isinstance(status, DreamStatus):
        state = {**state, "status": status.value}
        status = state["status"]
    if status not in {item.value for item in DreamStatus}:
        raise ValueError(f"unknown dream status: {status!r}")

    payload = {**state, "user_id": safe_user_id(user_id)}
    return safe_write_json(get_paths().dream_state_path(user_id), payload)

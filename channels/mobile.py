"""
channels/mobile - mobile polling channel.

The mobile client does not use the desktop WebSocket. Scheduler broadcasts to
the active mobile channel are written into data/mobile_queue.json, and the
mobile client reads them through /mobile/poll.
"""

import asyncio
import json
import logging
import time
from uuid import uuid4

from channels.base import BaseChannel
from core.sandbox import get_paths
from core.safe_write import safe_write_json

logger = logging.getLogger(__name__)

_queue_condition = asyncio.Condition()
_ACTIVE_TTL_SECONDS = 120


class MobileChannel(BaseChannel):
    def __init__(self):
        self._active = False
        self._last_seen = 0.0

    @property
    def name(self) -> str:
        return "mobile"

    @property
    def is_active(self) -> bool:
        if not self._active:
            return False
        return time.time() - self._last_seen <= _ACTIVE_TTL_SECONDS

    def set_active(self, active: bool) -> None:
        self._active = active
        if active:
            self._last_seen = time.time()
        logger.info(f"[mobile_channel] active={active}")

    def touch(self) -> None:
        self.set_active(True)

    async def send(self, content: str, user_id: str, behavior: dict | None = None) -> None:
        await self._write_to_queue(content, user_id, behavior=behavior)

    async def send_with_behavior(self, content: str, user_id: str, behavior: dict) -> None:
        await self._write_to_queue(content, user_id, behavior=behavior)

    async def poll(self, limit: int = 20, wait_seconds: float = 0) -> list[dict]:
        self.touch()
        limit = max(1, min(int(limit), 50))
        wait_seconds = max(0.0, min(float(wait_seconds), 60.0))
        deadline = time.monotonic() + wait_seconds

        async with _queue_condition:
            while True:
                messages = self._take_from_queue(limit)
                if messages:
                    return messages

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []

                try:
                    await asyncio.wait_for(_queue_condition.wait(), timeout=remaining)
                except asyncio.TimeoutError:
                    return []

    async def _write_to_queue(self, content: str, user_id: str, behavior: dict | None = None) -> None:
        try:
            async with _queue_condition:
                q_file = get_paths().mobile_queue()
                q_file.parent.mkdir(parents=True, exist_ok=True)
                queue = []
                if q_file.exists():
                    queue = json.loads(q_file.read_text(encoding="utf-8"))
                    if not isinstance(queue, list):
                        queue = []
                item = {
                    "id": uuid4().hex,
                    "content": content,
                    "user_id": str(user_id),
                    "timestamp": time.time(),
                }
                if behavior:
                    item["behavior"] = behavior
                queue.append(item)
                safe_write_json(q_file, queue)
                _queue_condition.notify_all()
        except Exception as e:
            logger.warning(f"[mobile_channel] write queue failed: {e}")

    def _take_from_queue(self, limit: int) -> list[dict]:
        q_file = get_paths().mobile_queue()
        if not q_file.exists():
            return []
        try:
            queue = json.loads(q_file.read_text(encoding="utf-8"))
            if not isinstance(queue, list):
                queue = []
        except Exception:
            logger.warning("[mobile_channel] read queue failed; reset")
            queue = []

        messages = queue[:limit]
        remaining = queue[limit:]
        safe_write_json(q_file, remaining)
        return messages

"""
channels/qq — QQ通道，通过NapCat发消息。
qq.enabled=false 或 standalone_mode=true 时不加载此通道。
"""

from channels.base import BaseChannel
import logging

logger = logging.getLogger(__name__)


class QQChannel(BaseChannel):
    def __init__(self, user_id: str):
        self._user_id = user_id
        self._active = True

    @property
    def name(self) -> str:
        return "qq"

    @property
    def is_active(self) -> bool:
        return self._active

    def set_active(self, active: bool) -> None:
        self._active = active

    async def send(
        self,
        content: str,
        user_id: str,
        behavior: dict | None = None,
        *,
        char_id: str | None = None,
        target_id: str | None = None,
        is_group: bool = False,
    ) -> None:
        """发送 QQ 消息。

        从 turn_sink._fanout 调用时，user_id 为 owner UID（私聊）；target_id /
        is_group 不传，默认走私聊路由（行为正确）。群聊路由由 main.py
        _qq_reality_reply_adapter 直接调用 text_output.send(target_id, ...,
        is_group) 处理，不经过本方法。
        """
        try:
            from core import qq_adapter
            _target = target_id if target_id is not None else user_id
            await qq_adapter.send_message(_target, content, is_group)
        except Exception as e:
            logger.warning(f"[qq_channel] 发送失败: {e}")

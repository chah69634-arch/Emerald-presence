"""Dry-run light output adapter.

The light adapter is a transport endpoint only. It does not know about
embodiment, perception, memory, prompts, schedulers, LLMs, or data files.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.hardware.base import OutputDevice


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LightCommand:
    on: bool
    brightness: float
    color_rgb: tuple[int, int, int]
    fade_ms: int

    def __post_init__(self) -> None:
        if not isinstance(self.on, bool):
            raise ValueError("on must be a bool")
        if not isinstance(self.brightness, (int, float)) or not 0.0 <= float(self.brightness) <= 1.0:
            raise ValueError("brightness must be between 0.0 and 1.0")
        if len(self.color_rgb) != 3:
            raise ValueError("color_rgb must contain exactly three values")
        for value in self.color_rgb:
            if not isinstance(value, int) or not 0 <= value <= 255:
                raise ValueError("color_rgb values must be integers between 0 and 255")
        if not isinstance(self.fade_ms, int) or self.fade_ms < 0:
            raise ValueError("fade_ms must be a non-negative integer")


class LightDevice(OutputDevice):
    def __init__(self, device_id: str = "light.default", *, dry_run: bool = True) -> None:
        self._device_id = device_id
        self.dry_run = dry_run

    @property
    def device_id(self) -> str:
        return self._device_id

    @property
    def modality(self) -> str:
        return "light"

    @property
    def dangerous(self) -> bool:
        return False

    async def send_command(self, command: object) -> None:
        if not isinstance(command, LightCommand):
            raise TypeError("command must be a LightCommand")
        self.accept(command)

    def accept(self, command: LightCommand, *, dry_run: bool | None = None) -> None:
        if not isinstance(command, LightCommand):
            raise TypeError("command must be a LightCommand")
        effective_dry_run = self.dry_run if dry_run is None else dry_run
        if effective_dry_run:
            logger.info("would set light: %s", command)
            return
        logger.info("light adapter has no real IO implementation: %s", command)

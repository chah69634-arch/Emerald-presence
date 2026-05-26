"""Embodiment light gate.

This file is the future permission layer insertion point. Phase 1 only exposes
the MVP safety gates: an explicit enabled switch and dry-run forwarding.
"""

from __future__ import annotations

from core import config_loader
from core.hardware.adapters.light import LightDevice

from .mapper import map_state_to_light


def apply(mood: str, activity: str | None) -> None:
    light_config = config_loader.get_config().get("embodiment", {}).get("light", {})
    if not light_config.get("enabled", False):
        return

    dry_run = light_config.get("dry_run", True)
    command = map_state_to_light(mood, activity)
    if command is None:
        return

    device = LightDevice(dry_run=dry_run)
    device.accept(command, dry_run=dry_run)

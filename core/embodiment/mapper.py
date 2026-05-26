"""Pure state-to-light mapping for output embodiment."""

from __future__ import annotations

from core.hardware.adapters.light import LightCommand


DEFAULT_LIGHT_MAPPINGS: dict[str, LightCommand] = {
    "neutral": LightCommand(on=True, brightness=0.35, color_rgb=(220, 220, 210), fade_ms=600),
    "happy": LightCommand(on=True, brightness=0.72, color_rgb=(255, 210, 120), fade_ms=450),
    "sad": LightCommand(on=True, brightness=0.22, color_rgb=(80, 120, 220), fade_ms=900),
    "gentle": LightCommand(on=True, brightness=0.42, color_rgb=(255, 185, 190), fade_ms=800),
    "surprised": LightCommand(on=True, brightness=0.85, color_rgb=(170, 235, 255), fade_ms=180),
    "angry": LightCommand(on=True, brightness=0.65, color_rgb=(255, 80, 55), fade_ms=260),
    "thinking": LightCommand(on=True, brightness=0.30, color_rgb=(155, 170, 255), fade_ms=1000),
    "sleepy": LightCommand(on=True, brightness=0.12, color_rgb=(120, 90, 180), fade_ms=1200),
    "yandere": LightCommand(on=True, brightness=0.55, color_rgb=(210, 40, 95), fade_ms=700),
}


def map_state_to_light(mood: str, activity: str | None) -> LightCommand | None:
    del activity
    command = DEFAULT_LIGHT_MAPPINGS.get(mood)
    if command is None:
        return None
    return LightCommand(
        on=command.on,
        brightness=command.brightness,
        color_rgb=command.color_rgb,
        fade_ms=command.fade_ms,
    )

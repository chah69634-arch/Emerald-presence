"""Owner-triggered hardware actuator tools."""

from __future__ import annotations


_PATTERNS: dict[str, list[tuple[float, int]]] = {
    "gentle": [(0.3, 400), (0.0, 200), (0.3, 400), (0.0, 200), (0.4, 600)],
    "pulse": [(0.6, 200), (0.0, 150), (0.6, 200), (0.0, 150), (0.6, 200)],
    "wave": [(0.2, 300), (0.5, 300), (0.8, 300), (0.5, 300), (0.2, 300)],
    "long": [(0.5, 2000)],
}


async def toy_vibrate(
    intensity: float = 0.5,
    duration_ms: int = 1000,
    device_index: int | None = None,
) -> str:
    from core.hardware.buttplug_client import vibrate

    ok = await vibrate(
        device_index=device_index,
        intensity=intensity,
        duration_ms=duration_ms,
    )
    return "振动完成" if ok else "设备未连接或操作失败"


async def toy_stop(device_index: int | None = None) -> str:
    from core.hardware.buttplug_client import stop

    ok = await stop(device_index=device_index)
    return "已停止" if ok else "设备未连接或操作失败"


async def toy_pattern(
    pattern_name: str = "gentle",
    device_index: int | None = None,
) -> str:
    from core.hardware.buttplug_client import pattern

    selected = pattern_name if pattern_name in _PATTERNS else "gentle"
    ok = await pattern(device_index=device_index, steps=_PATTERNS[selected])
    return f"模式 {selected} 完成" if ok else "设备未连接或操作失败"


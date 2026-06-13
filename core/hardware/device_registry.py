"""Process-local registry for devices discovered through Intiface Central."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ButtplugDevice:
    index: int
    name: str
    display_name: str
    message_timing_gap: int
    scalar_actuators: tuple[dict, ...]

    @property
    def can_vibrate(self) -> bool:
        return bool(self.vibration_indices)

    @property
    def vibration_indices(self) -> tuple[int, ...]:
        return tuple(
            index
            for index, actuator in enumerate(self.scalar_actuators)
            if actuator.get("ActuatorType") == "Vibrate"
        )

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "name": self.name,
            "display_name": self.display_name,
            "connected": True,
            "can_vibrate": self.can_vibrate,
        }


_DEVICES: dict[int, ButtplugDevice] = {}


def upsert_from_message(payload: dict) -> ButtplugDevice:
    index = int(payload["DeviceIndex"])
    messages = payload.get("DeviceMessages") or {}
    device = ButtplugDevice(
        index=index,
        name=str(payload.get("DeviceName") or f"Device {index}"),
        display_name=str(payload.get("DeviceDisplayName") or ""),
        message_timing_gap=int(payload.get("DeviceMessageTimingGap") or 0),
        scalar_actuators=tuple(messages.get("ScalarCmd") or ()),
    )
    _DEVICES[index] = device
    return device


def remove(index: int) -> None:
    _DEVICES.pop(int(index), None)


def clear() -> None:
    _DEVICES.clear()


def get(index: int | None = None, *, require_vibrate: bool = False) -> ButtplugDevice | None:
    if index is not None:
        device = _DEVICES.get(int(index))
        if device is None or (require_vibrate and not device.can_vibrate):
            return None
        return device
    return next(
        (
            device
            for device in _DEVICES.values()
            if not require_vibrate or device.can_vibrate
        ),
        None,
    )


def list_devices() -> list[dict]:
    return [device.as_dict() for device in _DEVICES.values()]

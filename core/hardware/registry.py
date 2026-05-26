"""In-memory registry for declared hardware devices."""

from .base import HardwareDevice


_DEVICES: dict[str, HardwareDevice] = {}


def register(device: HardwareDevice) -> HardwareDevice:
    if not isinstance(device, HardwareDevice):
        raise TypeError("device must be a HardwareDevice")
    if not device.device_id:
        raise ValueError("device_id is required")
    if device.device_id in _DEVICES:
        raise ValueError(f"device already registered: {device.device_id}")
    _DEVICES[device.device_id] = device
    return device


def list_devices() -> list[HardwareDevice]:
    return list(_DEVICES.values())


def get(device_id: str) -> HardwareDevice | None:
    return _DEVICES.get(device_id)


def _clear_for_tests() -> None:
    _DEVICES.clear()

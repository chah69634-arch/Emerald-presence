"""Async Buttplug v3 client for a locally running Intiface Central server."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import suppress
from typing import Any

import aiohttp

from core.config_loader import get_config
from core.hardware import device_registry


logger = logging.getLogger(__name__)

_DEFAULT_WS_URL = "ws://127.0.0.1:12345"
_RECONNECT_COOLDOWN = 30.0
_REQUEST_TIMEOUT = 5.0
_SCAN_SECONDS = 1.0
_MAX_DURATION_MS = 30_000
_MAX_PATTERN_STEPS = 32

_session: aiohttp.ClientSession | None = None
_websocket: aiohttp.ClientWebSocketResponse | None = None
_reader_task: asyncio.Task | None = None
_pending: dict[int, asyncio.Future] = {}
_next_id = 1
_last_connect_attempt = 0.0
_connect_lock = asyncio.Lock()
_command_lock = asyncio.Lock()


def _hardware_config() -> dict:
    return get_config().get("hardware", {})


def is_connected() -> bool:
    return _websocket is not None and not _websocket.closed


def get_devices() -> list[dict]:
    return device_registry.list_devices()


async def ensure_connected() -> bool:
    """Connect and scan once when needed. Fail closed while hardware is disabled."""
    global _last_connect_attempt

    if not _hardware_config().get("enabled", False):
        return False
    if is_connected():
        return True

    async with _connect_lock:
        if is_connected():
            return True
        now = time.monotonic()
        if now - _last_connect_attempt < _RECONNECT_COOLDOWN:
            return False
        _last_connect_attempt = now
        try:
            await _connect()
            await _request("StartScanning", {})
            await asyncio.sleep(_SCAN_SECONDS)
            await _request("StopScanning", {})
            logger.info("[buttplug] connected, devices=%d", len(get_devices()))
            return True
        except Exception as exc:
            logger.warning("[buttplug] connection failed: %s", exc)
            await disconnect()
            return False


async def disconnect() -> None:
    global _session, _websocket, _reader_task

    websocket, session, reader = _websocket, _session, _reader_task
    _websocket = None
    _session = None
    _reader_task = None
    device_registry.clear()
    _reject_pending(ConnectionError("Buttplug connection closed"))

    if reader is not None and reader is not asyncio.current_task():
        reader.cancel()
        with suppress(asyncio.CancelledError):
            await reader
    if websocket is not None and not websocket.closed:
        await websocket.close()
    if session is not None and not session.closed:
        await session.close()


async def vibrate(
    device_index: int | None = None,
    intensity: float = 0.5,
    duration_ms: int = 1000,
) -> bool:
    intensity = _clamp_intensity(intensity)
    duration_ms = _clamp_duration(duration_ms)
    if not await ensure_connected():
        return False
    device = device_registry.get(device_index, require_vibrate=True)
    if device is None:
        return False

    async with _command_lock:
        try:
            await _send_scalar(device.index, device.vibration_indices[0], intensity)
            await asyncio.sleep(duration_ms / 1000.0)
            return True
        except Exception as exc:
            logger.warning("[buttplug] vibrate failed: %s", exc)
            return False
        finally:
            await _best_effort_stop(device.index)


async def stop(device_index: int | None = None) -> bool:
    if not await ensure_connected():
        return False
    device = device_registry.get(device_index)
    if device is None:
        return False
    async with _command_lock:
        try:
            await _request("StopDeviceCmd", {"DeviceIndex": device.index})
            return True
        except Exception as exc:
            logger.warning("[buttplug] stop failed: %s", exc)
            return False


async def pattern(
    device_index: int | None = None,
    steps: list[tuple[float, int]] | None = None,
) -> bool:
    normalized = _normalize_steps(steps)
    if not await ensure_connected():
        return False
    device = device_registry.get(device_index, require_vibrate=True)
    if device is None:
        return False

    async with _command_lock:
        try:
            for intensity, duration_ms in normalized:
                await _send_scalar(device.index, device.vibration_indices[0], intensity)
                await asyncio.sleep(duration_ms / 1000.0)
            return True
        except Exception as exc:
            logger.warning("[buttplug] pattern failed: %s", exc)
            return False
        finally:
            await _best_effort_stop(device.index)


async def _connect() -> None:
    global _session, _websocket, _reader_task

    timeout = aiohttp.ClientTimeout(total=None, connect=_REQUEST_TIMEOUT)
    _session = aiohttp.ClientSession(timeout=timeout, trust_env=False)
    _websocket = await _session.ws_connect(
        str(_hardware_config().get("buttplug_ws") or _DEFAULT_WS_URL),
        autoping=True,
        heartbeat=20,
        max_msg_size=1024 * 1024,
    )
    _reader_task = asyncio.create_task(_reader_loop(), name="buttplug-reader")
    await _request(
        "RequestServerInfo",
        {"ClientName": "qq-st-bot", "MessageVersion": 3},
    )


async def _request(message_type: str, payload: dict[str, Any]) -> dict:
    global _next_id

    websocket = _websocket
    if websocket is None or websocket.closed:
        raise ConnectionError("Buttplug is not connected")
    request_id = _next_id
    _next_id += 1
    future = asyncio.get_running_loop().create_future()
    _pending[request_id] = future
    try:
        await websocket.send_str(json.dumps([{message_type: {**payload, "Id": request_id}}]))
        return await asyncio.wait_for(future, timeout=_REQUEST_TIMEOUT)
    finally:
        _pending.pop(request_id, None)


async def _reader_loop() -> None:
    try:
        assert _websocket is not None
        async for message in _websocket:
            if message.type == aiohttp.WSMsgType.TEXT:
                for envelope in json.loads(message.data):
                    _handle_message(envelope)
            elif message.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.ERROR,
            ):
                break
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("[buttplug] reader stopped: %s", exc)
    finally:
        asyncio.create_task(disconnect())


def _handle_message(envelope: dict) -> None:
    if not isinstance(envelope, dict) or len(envelope) != 1:
        return
    message_type, payload = next(iter(envelope.items()))
    if not isinstance(payload, dict):
        return
    if message_type == "DeviceAdded":
        device_registry.upsert_from_message(payload)
        return
    if message_type == "DeviceRemoved":
        device_registry.remove(int(payload["DeviceIndex"]))
        return

    future = _pending.get(int(payload.get("Id") or 0))
    if future is None or future.done():
        return
    if message_type == "Error":
        future.set_exception(RuntimeError(str(payload.get("ErrorMessage") or "Buttplug error")))
    else:
        future.set_result(payload)


async def _send_scalar(device_index: int, actuator_index: int, intensity: float) -> None:
    await _request(
        "ScalarCmd",
        {
            "DeviceIndex": device_index,
            "Scalars": [
                {"Index": actuator_index, "Scalar": intensity, "ActuatorType": "Vibrate"},
            ],
        },
    )


async def _best_effort_stop(device_index: int) -> None:
    if not is_connected():
        return
    try:
        await _request("StopDeviceCmd", {"DeviceIndex": device_index})
    except Exception as exc:
        logger.warning("[buttplug] final stop failed: %s", exc)


def _reject_pending(exc: Exception) -> None:
    for future in tuple(_pending.values()):
        if not future.done():
            future.set_exception(exc)
    _pending.clear()


def _clamp_intensity(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _clamp_duration(value: int) -> int:
    return min(_MAX_DURATION_MS, max(0, int(value)))


def _normalize_steps(steps: list[tuple[float, int]] | None) -> list[tuple[float, int]]:
    raw_steps = steps or [(0.5, 500), (0.0, 300), (0.5, 500)]
    return [
        (_clamp_intensity(intensity), _clamp_duration(duration_ms))
        for intensity, duration_ms in raw_steps[:_MAX_PATTERN_STEPS]
    ]


async def _reset_for_tests() -> None:
    global _last_connect_attempt, _next_id
    await disconnect()
    _last_connect_attempt = 0.0
    _next_id = 1

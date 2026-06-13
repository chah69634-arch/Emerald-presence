# Spec #6 — Buttplug 硬件集成层

> 状态：已实现  
> 难度：中  
> 改动范围：新增 `core/hardware/`、`core/tools/hardware_tools.py`、`admin/routers/hardware.py`、修改 `core/tool_dispatcher.py`、`admin/admin_server.py`

> 实现注记：采用项目已有 `aiohttp` 手写 Buttplug v3 WebSocket 协议，没有新增
> `buttplug-py` 依赖。额外增加 owner 私聊门控、无代理连接、动作串行化、时长/步数上限与
> `finally` best-effort stop。

---

## 架构概览

```
Intiface Central（本机跑，WebSocket :12345）
        ↕ WebSocket（buttplug-py 或 手写协议）
core/hardware/buttplug_client.py   — 连接管理 + 指令发送
core/hardware/device_registry.py   — 设备列表 + 状态维护
core/tools/hardware_tools.py       — 工具实现（toy_vibrate / toy_stop / toy_pattern）
core/tool_dispatcher.py            — 注册工具到 _TOOL_REGISTRY
admin/routers/hardware.py          — 设备状态 API（GET /hardware/devices）
admin/admin_server.py              — 路由注册
```

---

## 实现步骤

### Step 1：安装依赖

```bash
pip install buttplug-py    # 或 pip install buttplug
```

在 `requirements.txt` 追加 `buttplug-py`。

如果 buttplug-py 包依赖问题多，可以改用手写 WebSocket 直连 Intiface 的 JSON 协议（Buttplug v3 协议，文档见 https://buttplug-spec.docs.buttplug.io/）。

---

### Step 2：`core/hardware/buttplug_client.py`

```python
"""
Buttplug WebSocket 客户端 — 连接 Intiface Central，管理设备和指令。

依赖：buttplug-py 或手写 WebSocket 协议。
Intiface Central 默认 WebSocket 端口：12345。
"""

from __future__ import annotations
import asyncio
import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_WS_URL = "ws://localhost:12345"
_client = None              # buttplug.Client 实例（buttplug-py 提供）
_devices: dict = {}         # device_index → device 对象
_connected = False
_last_connect_attempt = 0.0
_RECONNECT_COOLDOWN = 30.0  # 连接失败后 30s 内不重试


async def ensure_connected() -> bool:
    """确保已连接 Intiface Central。返回是否连接成功。"""
    global _client, _connected, _last_connect_attempt, _devices
    if _connected and _client:
        return True
    now = time.time()
    if now - _last_connect_attempt < _RECONNECT_COOLDOWN:
        return False
    _last_connect_attempt = now
    try:
        from buttplug import Client, WebsocketConnector, ProtocolSpec
        from core.config_loader import get_config
        ws_url = get_config().get("hardware", {}).get("buttplug_ws", _DEFAULT_WS_URL)
        connector = WebsocketConnector(ws_url, logger=logger)
        _client = Client("qq-st-bot", ProtocolSpec.v3)
        await _client.connect(connector)
        await _client.start_scanning()
        await asyncio.sleep(1.0)    # 给扫描时间
        await _client.stop_scanning()
        _devices = {d.index: d for d in _client.devices.values()}
        _connected = True
        logger.info("[buttplug] 连接成功，发现设备数=%d", len(_devices))
        return True
    except Exception as e:
        logger.warning("[buttplug] 连接失败: %s", e)
        _connected = False
        _client = None
        return False


async def vibrate(device_index: Optional[int] = None, intensity: float = 0.5, duration_ms: int = 1000) -> bool:
    """
    振动指令。device_index=None 时控制第一个可用设备。
    intensity: 0.0 ~ 1.0
    duration_ms: 持续毫秒数（发指令后等待再停止）
    """
    if not await ensure_connected():
        return False
    intensity = min(1.0, max(0.0, float(intensity)))
    try:
        device = _get_device(device_index)
        if device is None:
            return False
        await device.actuators[0].command(intensity)
        await asyncio.sleep(duration_ms / 1000.0)
        await device.actuators[0].command(0.0)
        return True
    except Exception as e:
        logger.warning("[buttplug] vibrate failed: %s", e)
        return False


async def stop(device_index: Optional[int] = None) -> bool:
    """立即停止设备。"""
    if not await ensure_connected():
        return False
    try:
        device = _get_device(device_index)
        if device is None:
            return False
        await device.stop()
        return True
    except Exception as e:
        logger.warning("[buttplug] stop failed: %s", e)
        return False


async def pattern(
    device_index: Optional[int] = None,
    steps: list[tuple[float, int]] | None = None
) -> bool:
    """
    序列振动。steps = [(intensity, duration_ms), ...]
    例：[(0.5, 500), (0.0, 200), (0.8, 300)]
    """
    if not await ensure_connected():
        return False
    steps = steps or [(0.5, 500), (0.0, 300), (0.5, 500)]
    try:
        device = _get_device(device_index)
        if device is None:
            return False
        for intensity, ms in steps:
            await device.actuators[0].command(min(1.0, max(0.0, float(intensity))))
            await asyncio.sleep(ms / 1000.0)
        await device.actuators[0].command(0.0)
        return True
    except Exception as e:
        logger.warning("[buttplug] pattern failed: %s", e)
        return False


def get_devices() -> list[dict]:
    """返回当前已发现设备列表（供 API 使用）。"""
    return [
        {"index": idx, "name": getattr(d, "name", str(d)), "connected": True}
        for idx, d in _devices.items()
    ]


def is_connected() -> bool:
    return _connected


def _get_device(index: Optional[int]):
    if not _devices:
        return None
    if index is not None and index in _devices:
        return _devices[index]
    return next(iter(_devices.values()), None)
```

---

### Step 3：`core/tools/hardware_tools.py`

```python
"""硬件控制工具实现（注册到 _TOOL_REGISTRY）。"""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def toy_vibrate(intensity: float = 0.5, duration_ms: int = 1000, device_index: int | None = None) -> str:
    from core.hardware.buttplug_client import vibrate
    ok = await vibrate(device_index=device_index, intensity=intensity, duration_ms=duration_ms)
    return "振动完成" if ok else "设备未连接或操作失败"


async def toy_stop(device_index: int | None = None) -> str:
    from core.hardware.buttplug_client import stop
    ok = await stop(device_index=device_index)
    return "已停止" if ok else "设备未连接或操作失败"


async def toy_pattern(pattern_name: str = "gentle") -> str:
    from core.hardware.buttplug_client import pattern
    patterns = {
        "gentle":  [(0.3, 400), (0.0, 200), (0.3, 400), (0.0, 200), (0.4, 600)],
        "pulse":   [(0.6, 200), (0.0, 150), (0.6, 200), (0.0, 150), (0.6, 200)],
        "wave":    [(0.2, 300), (0.5, 300), (0.8, 300), (0.5, 300), (0.2, 300)],
        "long":    [(0.5, 2000)],
    }
    steps = patterns.get(pattern_name, patterns["gentle"])
    ok = await pattern(steps=steps)
    return f"模式 {pattern_name} 完成" if ok else "设备未连接或操作失败"
```

---

### Step 4：在 `core/tool_dispatcher.py` 注册工具

在 `_TOOL_REGISTRY` 字典里追加（在文件已有注册条目后面）：

```python
"toy_vibrate": {
    "category": "desktop",
    "description": "控制连接的蓝牙玩具振动，intensity 0.0~1.0，duration_ms 毫秒数",
    "examples": ["振动一下", "强一点", "轻轻地"],
    "parameters": {
        "type": "object",
        "properties": {
            "intensity":   {"type": "number", "description": "振动强度 0.0~1.0"},
            "duration_ms": {"type": "integer", "description": "持续毫秒数"},
        },
        "required": [],
    },
    "has_side_effect": True,
},
"toy_stop": {
    "category": "desktop",
    "description": "立即停止蓝牙玩具",
    "examples": ["停", "别了", "停下"],
    "parameters": {"type": "object", "properties": {}, "required": []},
    "has_side_effect": True,
},
"toy_pattern": {
    "category": "desktop",
    "description": "以预设模式振动（gentle/pulse/wave/long）",
    "examples": ["来个波浪模式", "轻柔一些"],
    "parameters": {
        "type": "object",
        "properties": {
            "pattern_name": {"type": "string", "enum": ["gentle", "pulse", "wave", "long"]},
        },
        "required": [],
    },
    "has_side_effect": True,
},
```

在 `execute()` 函数里，在现有工具的 dispatch 逻辑中加入对这三个工具的分发：

```python
# 在 execute() 函数的 dispatch 块里（找到类似 if tool_name == "..." 的位置）
elif tool_name == "toy_vibrate":
    from core.tools.hardware_tools import toy_vibrate
    result = await toy_vibrate(
        intensity=float(tool_args.get("intensity", 0.5)),
        duration_ms=int(tool_args.get("duration_ms", 1000)),
    )
    return result, None
elif tool_name == "toy_stop":
    from core.tools.hardware_tools import toy_stop
    result = await toy_stop()
    return result, None
elif tool_name == "toy_pattern":
    from core.tools.hardware_tools import toy_pattern
    result = await toy_pattern(pattern_name=tool_args.get("pattern_name", "gentle"))
    return result, None
```

---

### Step 5：`admin/routers/hardware.py`

```python
from fastapi import APIRouter, Depends
from admin.auth import verify_token

router = APIRouter()


@router.get("/devices")
async def list_devices(auth=Depends(verify_token)):
    from core.hardware.buttplug_client import get_devices, is_connected
    return {
        "connected": is_connected(),
        "devices": get_devices(),
    }


@router.post("/connect")
async def connect(auth=Depends(verify_token)):
    from core.hardware.buttplug_client import ensure_connected
    ok = await ensure_connected()
    return {"success": ok}
```

在 `admin/admin_server.py` 注册路由：

```python
from admin.routers import hardware as _hardware_router
app.include_router(_hardware_router.router, prefix="/hardware", tags=["hardware"])
```

---

### Step 6：`config.yaml` 配置段

```yaml
hardware:
  buttplug_ws: "ws://localhost:12345"   # Intiface Central WebSocket 地址
  enabled: true                          # false 时跳过连接
```

在 `buttplug_client.ensure_connected()` 里加 enabled 检查：

```python
if not get_config().get("hardware", {}).get("enabled", False):
    return False
```

---

## 安全边界

- `toy_*` 工具的 `category` 为 `"desktop"`，只允许 `assistant_intent` origin 调用（由 `_EXECUTE_ALLOWED_ORIGINS` 保证）。
- 不需要加到 `_INTENT_DANGEROUS_ACTIONS`，但 `has_side_effect: True` 会让工具在必要时走二次确认流程。
- 玩具指令不经过 dream pipeline——dream 里如果需要联动，需要单独设计（v2 可考虑）。
- 不在 trigger/scheduler 路径里调用玩具指令，只在真实 owner turn 里可触发（Path B 守卫自然保证）。

---

## 注意事项

- buttplug-py 库的 API 因版本不同有差异，上述代码基于 buttplug-py 0.x。安装后先用 `python -c "import buttplug; print(buttplug.__version__)"` 确认版本再对齐 API。
- Intiface Central 必须在本机跑（免费开源桌面应用）。
- 如果 buttplug-py 依赖解析有问题，可以改用 `websockets` 库手写 JSON 协议（Buttplug v3 JSON spec 很简单）。
- `_devices` 是进程内缓存，重启 bot 后需要重新扫描设备。

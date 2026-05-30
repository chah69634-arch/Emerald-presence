"""
杂项设置接口：工具开关、上下文轮数、破限预设、TTS 配置
"""

from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from admin.auth import verify_token
from core.config_loader import get_config

router = APIRouter()
CONFIG_FILE = Path("config.yaml")

# ─── 工具开关 ──────────────────────────────────────────────────────────────────

_TOOL_CONFIG_KEYS = {
    "weather":         "weather",
    "device_shutdown": "device_control",
    "device_sleep":    "device_control",
    "set_timer":       "timer",
    "web_search":      "web_search",
}


@router.get("/tools", summary="获取所有工具启用状态")
async def get_tools(auth=Depends(verify_token)):
    tools_cfg = get_config().get("tools", {})
    return {
        name: tools_cfg.get(group, {}).get("enabled", True)
        for name, group in _TOOL_CONFIG_KEYS.items()
    }


class ToolUpdate(BaseModel):
    enabled: bool


@router.put("/tools/{name}", summary="修改工具启用状态并热重载")
async def update_tool(name: str, body: ToolUpdate, auth=Depends(verify_token)):
    if name not in _TOOL_CONFIG_KEYS:
        raise HTTPException(status_code=404, detail=f"未知工具：{name}")

    group = _TOOL_CONFIG_KEYS[name]
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            full_cfg = yaml.safe_load(f) or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取配置文件失败: {e}")

    full_cfg.setdefault("tools", {}).setdefault(group, {})["enabled"] = body.enabled

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(full_cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入配置文件失败: {e}")

    from core import config_loader
    config_loader.reload_config()
    return {"tool": name, "enabled": body.enabled, "message": f"工具 {name} 已{'启用' if body.enabled else '禁用'}"}


# ─── 上下文轮数 ────────────────────────────────────────────────────────────────

class ContextConfigUpdate(BaseModel):
    max_turns: int


@router.get("/context-config", summary="获取上下文轮数配置")
async def get_context_config(auth=Depends(verify_token)):
    cfg = get_config()
    max_turns = (
        cfg.get("context", {}).get("max_turns")
        or cfg.get("memory", {}).get("short_term_rounds", 20)
    )
    return {"max_turns": max_turns}


@router.put("/context-config", summary="修改上下文轮数并热重载")
async def update_context_config(body: ContextConfigUpdate, auth=Depends(verify_token)):
    if not (1 <= body.max_turns <= 200):
        raise HTTPException(status_code=422, detail="max_turns 必须在 1~200 之间")

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            full_cfg = yaml.safe_load(f) or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取配置文件失败: {e}")

    full_cfg.setdefault("context", {})["max_turns"] = body.max_turns

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(full_cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入配置文件失败: {e}")

    from core import config_loader
    config_loader.reload_config()
    return {"message": "上下文轮数已更新", "max_turns": body.max_turns}


# ─── TTS 配置 ──────────────────────────────────────────────────────────────────

class TtsConfigUpdate(BaseModel):
    enabled:         Optional[bool]  = None
    api_url:         Optional[str]   = None
    ref_audio:       Optional[str]   = None
    prompt_text:     Optional[str]   = None
    speed:           Optional[float] = None
    emotion_enabled: Optional[bool]  = None
    emotions:        Optional[dict]  = None


@router.get("/tts-config", summary="获取 TTS 配置")
async def get_tts_config(auth=Depends(verify_token)):
    cfg = get_config().get("tts", {})
    return {
        "enabled":         cfg.get("enabled",         False),
        "api_url":         cfg.get("api_url",         "http://127.0.0.1:9880"),
        "ref_audio":       cfg.get("ref_audio",       ""),
        "prompt_text":     cfg.get("prompt_text",     ""),
        "speed":           float(cfg.get("speed",     1.0)),
        "emotion_enabled": cfg.get("emotion_enabled", False),
        "emotions":        cfg.get("emotions",        {}),
    }


@router.put("/tts-config", summary="修改 TTS 配置并热重载")
async def update_tts_config(body: TtsConfigUpdate, auth=Depends(verify_token)):
    if body.speed is not None and not (0.5 <= body.speed <= 2.0):
        raise HTTPException(status_code=422, detail="speed 必须在 0.5~2.0 之间")

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            full_cfg = yaml.safe_load(f) or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取配置文件失败: {e}")

    tts_cfg = full_cfg.setdefault("tts", {})
    if body.enabled is not None:
        tts_cfg["enabled"] = body.enabled
    if body.api_url is not None:
        tts_cfg["api_url"] = body.api_url
    if body.ref_audio is not None:
        tts_cfg["ref_audio"] = body.ref_audio
    if body.prompt_text is not None:
        tts_cfg["prompt_text"] = body.prompt_text
    if body.speed is not None:
        tts_cfg["speed"] = body.speed
    if body.emotion_enabled is not None:
        tts_cfg["emotion_enabled"] = body.emotion_enabled
    if body.emotions is not None:
        tts_cfg["emotions"] = body.emotions

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(full_cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入配置文件失败: {e}")

    from core import config_loader
    config_loader.reload_config()
    return {"message": "TTS 配置已更新", "tts": tts_cfg}


# ─── 聊天模式 ──────────────────────────────────────────────────────────────────

_VALID_MODES = {"chat", "roleplay"}


class ChatModeUpdate(BaseModel):
    mode: str


@router.get("/chat-mode", summary="获取当前聊天模式")
async def get_chat_mode(auth=Depends(verify_token)):
    mode = get_config().get("chat", {}).get("mode", "chat")
    return {"mode": mode}


@router.put("/chat-mode", summary="切换聊天模式（chat / roleplay）")
async def update_chat_mode(body: ChatModeUpdate, auth=Depends(verify_token)):
    if body.mode not in _VALID_MODES:
        raise HTTPException(status_code=422, detail="mode 只接受 'chat' 或 'roleplay'")

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            full_cfg = yaml.safe_load(f) or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取配置文件失败: {e}")

    full_cfg.setdefault("chat", {})["mode"] = body.mode

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(full_cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入配置文件失败: {e}")

    from core import config_loader
    config_loader.reload_config()
    return {"message": f"聊天模式已切换为 {body.mode}", "mode": body.mode}


# ─── 对话风格（chat.style）────────────────────────────────────────────────────

_VALID_STYLES = {"chat", "roleplay"}


class ChatStyleUpdate(BaseModel):
    style: str


@router.get("/chat-style", summary="获取当前对话风格")
async def get_chat_style(auth=Depends(verify_token)):
    style = get_config().get("chat", {}).get("style", "roleplay")
    return {"style": style}


@router.put("/chat-style", summary="切换对话风格（chat=沉浸式对话 / roleplay=沉浸式角色扮演）")
async def update_chat_style(body: ChatStyleUpdate, auth=Depends(verify_token)):
    if body.style not in _VALID_STYLES:
        raise HTTPException(status_code=422, detail="style 只接受 'chat' 或 'roleplay'")

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            full_cfg = yaml.safe_load(f) or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取配置文件失败: {e}")

    full_cfg.setdefault("chat", {})["style"] = body.style

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(full_cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入配置文件失败: {e}")

    from core import config_loader
    config_loader.reload_config()
    return {"message": f"对话风格已切换为 {body.style}", "style": body.style}


# ─── 分条发送开关 ──────────────────────────────────────────────────────────────

@router.get("/chat-multi-message", summary="获取分条发送开关状态")
async def get_multi_message(auth=Depends(verify_token)):
    enabled = get_config().get("chat", {}).get("multi_message", False)
    return {"multi_message": enabled}


@router.put("/chat-multi-message", summary="切换分条发送开关")
async def update_multi_message(body: dict, auth=Depends(verify_token)):
    enabled = bool(body.get("enabled", False))
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            full_cfg = yaml.safe_load(f) or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取配置文件失败: {e}")

    full_cfg.setdefault("chat", {})["multi_message"] = enabled

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(full_cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入配置文件失败: {e}")

    from core import config_loader
    config_loader.reload_config()
    return {"message": f"分条发送已{'启用' if enabled else '禁用'}", "multi_message": enabled}

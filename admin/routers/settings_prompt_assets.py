"""
Prompt Asset 配置 API
GET  /settings/prompt-assets  — 读取可用资产列表 + 当前激活配置
PATCH /settings/prompt-assets — 部分更新激活配置，并热重载 lore_engine

Asset identity contract:
- All values in active config and PATCH bodies are IDs (file stems, ASCII).
- Labels, filenames, and Chinese names must NOT appear in config or PATCH bodies.
- Hidden/template/example assets are excluded from UI lists.
- PATCH with a label or filename will be rejected with a clear error.
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from admin.auth import verify_token
from core.asset_registry import get_registry, reload_registry
from core.sandbox import get_paths

router = APIRouter()


def _validate_id(value: str, kind: str, field: str):
    """Validate that value is a known, non-hidden asset id.

    Rejects path separators, dots (extensions / traversal), and unknown ids.
    Also rejects if value looks like a label or filename (contains Chinese, dots).
    """
    if "/" in value or "\\" in value or "." in value:
        raise HTTPException(
            status_code=422,
            detail=f"{field}: 不接受路径分隔符或扩展名——请提交 id 而非 filename（拒绝：{value!r}）",
        )
    reg = get_registry()
    try:
        reg.resolve(value, kind)
    except ValueError:
        valid = sorted(e.id for e in reg.list_all(kind))
        raise HTTPException(
            status_code=422,
            detail=f"{field}: {value!r} 不在可用列表中（可用：{valid}）",
        )


def _read_active() -> dict:
    p = get_paths().active_prompt_assets()
    return json.loads(p.read_text(encoding="utf-8"))


def _write_active(data: dict):
    p = get_paths().active_prompt_assets()
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _reload_lore_engine():
    try:
        from core.pipeline_registry import get as _get_pipeline
        pipeline = _get_pipeline()
        if pipeline is not None and hasattr(pipeline, "lore_engine"):
            pipeline.lore_engine.load()
    except Exception:
        pass


@router.get("/settings/prompt-assets", summary="获取 Prompt 资产列表与激活配置")
async def get_prompt_assets(auth=Depends(verify_token)):
    """Returns all UI-visible (non-hidden) assets and the current active config.

    Response shape:
      {
        "characters":    [{"id": "yexuan", "label": "叶瑄", "kind": "character"}, ...],
        "lorebooks":     [{"id": "base",   "label": "base",  "kind": "reality_lorebook"}, ...],
        "jailbreaks":    [{"id": "base",   "label": "base",  "kind": "reality_jailbreak"}, ...],
        "dream_presets": [{"id": "default","label": "default","kind": "dream_preset"}, ...],
        "active": {
          "active_character":   "yexuan",
          "enabled_lorebooks":  ["base"],
          "enabled_jailbreaks": ["base", "anti_assistant", "style"],
          "active_dream_preset": null
        }
      }
    """
    reg = get_registry()
    return {
        "characters":    [e.as_ui_dict() for e in reg.list_ui("character")],
        "lorebooks":     [e.as_ui_dict() for e in reg.list_ui("reality_lorebook")],
        "jailbreaks":    [e.as_ui_dict() for e in reg.list_ui("reality_jailbreak")],
        "dream_presets": [e.as_ui_dict() for e in reg.list_ui("dream_preset")],
        "active":        _read_active(),
    }


class PromptAssetsUpdate(BaseModel):
    active_character:    Optional[str]       = None
    enabled_lorebooks:   Optional[list[str]] = None
    enabled_jailbreaks:  Optional[list[str]] = None
    active_dream_preset: Optional[str]       = None


@router.patch("/settings/prompt-assets", summary="部分更新 Prompt 资产激活配置")
async def patch_prompt_assets(body: PromptAssetsUpdate, auth=Depends(verify_token)):
    """Partial update for active prompt-asset config. All values must be asset ids.

    Rejects labels ("叶瑄"), filenames ("yexuan.json"), and unknown ids.
    """
    if all(v is None for v in (
        body.active_character,
        body.enabled_lorebooks,
        body.enabled_jailbreaks,
        body.active_dream_preset,
    )):
        raise HTTPException(status_code=422, detail="至少提供一个更新字段")

    if body.active_character is not None:
        _validate_id(body.active_character, "character", "active_character")

    if body.enabled_lorebooks is not None:
        for stem in body.enabled_lorebooks:
            _validate_id(stem, "reality_lorebook", "enabled_lorebooks")

    if body.enabled_jailbreaks is not None:
        for stem in body.enabled_jailbreaks:
            _validate_id(stem, "reality_jailbreak", "enabled_jailbreaks")

    if body.active_dream_preset is not None:
        _validate_id(body.active_dream_preset, "dream_preset", "active_dream_preset")

    active = _read_active()
    if body.active_character is not None:
        active["active_character"] = body.active_character
    if body.enabled_lorebooks is not None:
        active["enabled_lorebooks"] = body.enabled_lorebooks
    if body.enabled_jailbreaks is not None:
        active["enabled_jailbreaks"] = body.enabled_jailbreaks
    if body.active_dream_preset is not None:
        active["active_dream_preset"] = body.active_dream_preset

    _write_active(active)

    if body.enabled_lorebooks is not None:
        _reload_lore_engine()
    if body.active_character is not None:
        reload_registry()

    return {"message": "已更新", "active": active}

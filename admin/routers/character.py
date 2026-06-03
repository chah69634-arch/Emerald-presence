"""
角色卡管理接口
提供角色卡 JSON 文件的列表、读取、保存、上传和切换。

接口列表：
  GET  /characters          — 列出所有 .json 文件，返回当前活跃角色名
  GET  /characters/{name}   — 读取角色卡内容
  PUT  /characters/active   — 切换当前活跃角色（写入 config.yaml）
  POST /characters/upload   — 上传新角色卡 .json 文件
  PUT  /characters/{name}   — 保存编辑后的角色卡并热重载
"""

import json
from pathlib import Path
from typing import Any, Dict

import yaml
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from admin.auth import verify_token
from core.asset_registry import get_registry, reload_registry
from core.config_loader import get_config

router = APIRouter()

CHARACTERS_DIR = Path("characters")
CONFIG_FILE = Path("config.yaml")


# ─── 工具函数 ──────────────────────────────────────────────────────────────────

def _safe_path(name: str) -> Path:
    """返回安全路径，防止路径穿越攻击"""
    resolved = (CHARACTERS_DIR / name).resolve()
    base = CHARACTERS_DIR.resolve()
    if not str(resolved).startswith(str(base)):
        raise HTTPException(status_code=400, detail="非法文件名")
    return resolved


def _active_character_id() -> str:
    """Return the current active character id from config.yaml (normalized)."""
    raw = get_config().get("character", {}).get("default", "")
    if not raw:
        return ""
    # Normalize: strip extension if present (legacy compat: "yexuan.json" -> "yexuan")
    return Path(raw).stem if "." in raw else raw


def _reload_character():
    """热重载 main.py 中的角色实例和世界书引擎。

    只吞掉 "admin 单独运行时 main 未初始化" 这一种情况；
    角色加载失败（id 不存在、文件缺失、JSON 损坏）会直接向上抛。
    """
    try:
        import main as _main
    except Exception:
        return  # admin 单独运行时 main.py 未初始化，跳过
    if not hasattr(_main, "_character"):
        return

    from core import character_loader
    cfg = get_config()
    char_ref = cfg.get("character", {}).get("default", "")
    if not char_ref:
        raise ValueError(
            "[character_loader] config.yaml 缺少 character.default，无法热重载角色"
        )
    # load() 现在 fail-loud：id 不存在 → ValueError，文件缺失 → FileNotFoundError
    _main._character = character_loader.load(char_ref)
    if hasattr(_main, "_lore_engine") and _main._lore_engine is not None:
        _main._lore_engine.load()
        if _main._character.world_book:
            _main._lore_engine.load_entries(_main._character.world_book)


# ─── 路由（注意：精确路由必须在参数路由之前声明）────────────────────────────────

@router.get("/characters", summary="列出所有角色卡文件")
async def list_characters(auth=Depends(verify_token)):
    """返回 characters/ 顶层目录下的角色卡资产列表（不含 hidden/template/author_notes 资产）。

    Response shape:
      {
        "characters": [{"id": "yexuan", "label": "叶瑄", "filename": "yexuan.json"}, ...],
        "active_id": "yexuan"
      }
    """
    CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)
    reg = get_registry()
    # list_ui excludes hidden; include both hidden=False and hidden=True here so editors can
    # still open all files — but mark hidden ones so the frontend can omit them from the
    # "set active" picker.
    entries = reg.list_all("character")
    chars = [
        {"id": e.id, "label": e.label, "filename": e.filename, "hidden": e.hidden}
        for e in sorted(entries, key=lambda e: e.id)
    ]
    return {"characters": chars, "active_id": _active_character_id()}


@router.put("/characters/active", summary="切换当前活跃角色卡")
async def set_active_character(body: Dict[str, Any], auth=Depends(verify_token)):
    """将 config.yaml 中的 character.default 更新为指定角色 id，并热重载。

    Request body: {"id": "yexuan"}
    Legacy compat: {"name": "yexuan.json"} is also accepted and normalized to id.

    Rejects: label strings ("叶瑄") and unknown ids — fail-loud.
    """
    # Accept both "id" (new) and "name" (legacy filename form)
    raw = (body.get("id") or body.get("name") or "").strip()
    if not raw:
        raise HTTPException(status_code=422, detail="id 不能为空")

    reg = get_registry()
    # Normalize legacy filename to id ("yexuan.json" → "yexuan")
    char_id = reg.normalize_legacy(raw, "character")

    # Validate: id must be known, and must not be a hidden template/example
    try:
        entry = reg.resolve(char_id, "character")
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"未知角色 id {char_id!r}。如果提交了 label 或 filename，请改为提交 id。",
        )

    if entry.hidden:
        raise HTTPException(
            status_code=422,
            detail=f"角色 {char_id!r} 是 template/example 资产，不能设为活跃角色。",
        )

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            full_cfg = yaml.safe_load(f) or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取配置失败: {e}")

    # Write id (not filename) to config
    full_cfg.setdefault("character", {})["default"] = char_id

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(full_cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入配置失败: {e}")

    from core import config_loader
    config_loader.reload_config()
    _reload_character()
    reload_registry()
    return {"message": f"当前角色已切换为 {char_id}", "active_id": char_id, "label": entry.label}


@router.post("/characters/upload", summary="上传新角色卡（.json / .txt / .md）")
async def upload_character(file: UploadFile = File(...), auth=Depends(verify_token)):
    """接收 .json / .txt / .md 文件并保存到 characters/ 目录"""
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in (".json", ".txt", ".md"):
        raise HTTPException(status_code=422, detail="只接受 .json / .txt / .md 文件")
    CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)
    # 只取文件名部分，防止路径穿越
    safe_name = Path(filename).name
    dest = _safe_path(safe_name)
    content = await file.read()
    # JSON 文件额外验证合法性
    if suffix == ".json":
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=422, detail=f"JSON 解析失败: {e}")
    try:
        dest.write_bytes(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存失败: {e}")
    return {"message": f"角色卡 {safe_name} 已上传", "filename": safe_name}


@router.get("/characters/{name}/export", summary="导出角色卡文件")
async def export_character(name: str, auth=Depends(verify_token)):
    from fastapi.responses import Response as _Resp
    from urllib.parse import quote
    path = _safe_path(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"角色卡 {name} 不存在")
    content = path.read_bytes()
    media = "application/json" if path.suffix.lower() == ".json" else "text/plain"
    encoded_name = quote(name)
    return _Resp(content=content, media_type=media,
                 headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"})


@router.get("/characters/{name}", summary="读取角色卡内容")
async def get_character(name: str, auth=Depends(verify_token)):
    """返回指定角色卡内容：
    - .txt/.md → {"filename": name, "type": "text", "content": "..."}
    - .json    → 原始 JSON 对象 + "type": "json"
    """
    path = _safe_path(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"角色卡 {name} 不存在")
    suffix = path.suffix.lower()
    try:
        if suffix in (".txt", ".md"):
            return {
                "filename": name,
                "type":     "text",
                "content":  path.read_text(encoding="utf-8"),
            }
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["type"] = "json"
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取失败: {e}")


@router.put("/characters/{name}", summary="保存角色卡并热重载")
async def save_character(name: str, request: Request, _auth=Depends(verify_token)):
    """接收编辑后的角色卡内容，写回文件并热重载角色。
    - .txt/.md：raw body 作为 UTF-8 文本直接写入
    - .json：解析 JSON body 再写入
    """
    path = _safe_path(name)
    CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    try:
        raw = await request.body()
        if suffix in (".txt", ".md"):
            path.write_text(raw.decode("utf-8"), encoding="utf-8")
        else:
            body: Dict[str, Any] = json.loads(raw)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(body, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存失败: {e}")
    _reload_character()
    return {"message": f"角色卡 {name} 已保存并热重载"}



@router.post("/characters/{name}/rename", summary="重命名角色卡")
async def rename_character(name: str, body: Dict[str, Any], auth=Depends(verify_token)):
    new_name = (body.get("new_name") or "").strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="new_name 不能为空")
    src = _safe_path(name)
    dst = _safe_path(new_name)
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"角色卡 {name} 不存在")
    if dst.exists():
        raise HTTPException(status_code=409, detail=f"角色卡 {new_name} 已存在")
    src.rename(dst)
    # 如果是当前活跃角色，同步更新 config.yaml（写新 id，不写 filename）
    new_id = Path(new_name).stem
    current_id = _active_character_id()
    old_id = Path(name).stem
    if current_id == old_id:
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                full_cfg = yaml.safe_load(f) or {}
            full_cfg.setdefault("character", {})["default"] = new_id
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                yaml.dump(full_cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            from core import config_loader
            config_loader.reload_config()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"更新配置失败: {e}")
    reload_registry()
    return {"message": f"已重命名为 {new_name}", "new_name": new_name, "new_id": new_id}

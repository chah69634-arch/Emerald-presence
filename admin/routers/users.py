"""
用户管理路由
"""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from admin.auth import verify_token

router = APIRouter()


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def _get_known_users() -> list[str]:
    """扫描 history/ / profiles/（legacy）和 memory/{char_id}/（v1）目录，收集所有已知用户 ID。"""
    from core.sandbox import get_paths
    user_ids: set[str] = set()

    # legacy 扫描（含过渡期仍存在旧文件的情况）
    history_dir = get_paths().history()
    if history_dir.exists():
        user_ids.update(f.stem for f in history_dir.glob("*.json"))

    profiles_dir = get_paths().profiles()
    if profiles_dir.exists():
        user_ids.update(f.stem for f in profiles_dir.glob("*.json"))

    # v1 扫描：memory/{char_id}/ 下每个子目录名即为 uid
    char_root = get_paths().memory_char_root()
    if char_root.exists():
        user_ids.update(d.name for d in char_root.iterdir() if d.is_dir())

    return sorted(user_ids)


# ── 接口 ─────────────────────────────────────────────────────────────────────

@router.get("/", summary="获取所有用户列表")
async def get_users(auth=Depends(verify_token)):
    """返回所有有对话记录或画像的用户 ID 列表"""
    user_ids = _get_known_users()
    return {"users": user_ids, "total": len(user_ids)}


@router.get("/{user_id}/profile", summary="获取用户画像")
async def get_user_profile(user_id: str, auth=Depends(verify_token)):
    """返回指定用户的画像 JSON"""
    from core.memory import user_profile
    profile = user_profile.load(user_id)
    return {"user_id": user_id, "profile": profile}


@router.put("/{user_id}/profile", summary="更新用户画像")
async def update_user_profile(user_id: str, body: dict[str, Any], auth=Depends(verify_token)):
    """直接覆盖更新用户画像字段（admin 直接编辑，不走 LLM 提取）"""
    from core.memory import user_profile
    profile = user_profile.load(user_id)
    # 允许直接覆盖所有字段（包括未来新增字段）
    for k, v in body.items():
        profile[k] = v
    user_profile.save(user_id, profile)
    return {"message": f"用户 {user_id} 画像已更新", "profile": profile}


@router.delete("/{user_id}/memory", summary="清除用户所有记忆")
async def delete_user_memory(user_id: str, auth=Depends(verify_token)):
    """清除用户的短期历史、画像和长期 RAG 记忆（冻结）"""
    from core.memory import short_term, user_profile, long_term_rag

    short_term.clear(user_id)
    user_profile.clear(user_id)
    await long_term_rag.delete_user_memory(user_id)

    return {"message": f"用户 {user_id} 的所有记忆已清除"}

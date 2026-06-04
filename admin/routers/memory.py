"""
记忆管理路由
"""

import json as _json

from fastapi import APIRouter, Depends, HTTPException

from admin.auth import verify_token

router = APIRouter()


def _resolve_char_id(char_id: str | None) -> str:
    """Resolve and validate a char_id for memory operations.

    If char_id is None, reads active_character from active_prompt_assets.json.
    Raises HTTP 503 if active_character is missing or empty.
    Raises HTTP 422 if the resolved or supplied char_id is not a known character.
    Never falls back to a hardcoded character.
    """
    from core.sandbox import get_paths
    from core.asset_registry import get_registry

    if char_id is None:
        try:
            data = _json.loads(get_paths().active_prompt_assets().read_text(encoding="utf-8"))
            char_id = (data.get("active_character") or "").strip()
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"读取 active_prompt_assets.json 失败: {e}")
        if not char_id:
            raise HTTPException(
                status_code=503,
                detail="active_prompt_assets.json 中 active_character 为空，请先设置活跃角色",
            )

    try:
        get_registry().resolve(char_id, "character")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return char_id


# ── 短期记忆 ──────────────────────────────────────────────────────────────────

@router.get("/{user_id}/short-term", summary="获取短期记忆")
async def get_short_term(
    user_id: str,
    char_id: str | None = None,
    auth=Depends(verify_token),
):
    """返回用户最近的对话历史（滚动窗口内的全部消息）。

    char_id 为空时使用当前 active_character；非法 char_id 返回错误，不默认 yexuan。
    """
    from core.memory import short_term
    resolved = _resolve_char_id(char_id)
    history = short_term.load(user_id, char_id=resolved)
    return {"user_id": user_id, "char_id": resolved, "history": history, "count": len(history)}


@router.delete("/{user_id}/short-term", summary="清除短期记忆")
async def clear_short_term(
    user_id: str,
    char_id: str | None = None,
    auth=Depends(verify_token),
):
    """清空用户短期对话历史（写入空列表）。

    char_id 为空时使用当前 active_character；非法 char_id 返回错误，不跨角色清理。
    """
    from core.memory import short_term
    resolved = _resolve_char_id(char_id)
    short_term.clear(user_id, char_id=resolved)
    return {"message": f"用户 {user_id} 角色 {resolved} 短期记忆已清除", "char_id": resolved}


# TODO(Step 8): GET /fixation/status?uid=...
#   返回该 uid 的 fixation_state + 最近 20 条 fixation.jsonl 日志。
#   实现要点：
#     from core.memory.fixation_pipeline import _load_fixation_state, _should_consolidate
#     from core.sandbox import get_paths
#     log_path = get_paths().fixation_log()
#     lines = log_path.read_text(encoding="utf-8").splitlines()[-20:] if log_path.exists() else []
#     records = [json.loads(l) for l in lines if f'"uid": "{uid}"' in l]
#     return {"fixation_state": _load_fixation_state(uid), "recent_logs": records}

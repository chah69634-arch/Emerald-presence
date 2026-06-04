"""
情绪状态路由
"""
import json

from fastapi import APIRouter, Depends

from admin.auth import verify_token
from core.memory import mood_state

router = APIRouter()


@router.get("/state", summary="获取情绪状态")
async def get_mood_state(auth=Depends(verify_token)):
    from core.sandbox import get_paths as _gp
    try:
        _raw = json.loads(_gp().active_prompt_assets().read_text(encoding="utf-8"))
        _char_id = (_raw.get("active_character") or "").strip()
    except Exception:
        _char_id = ""
    return mood_state.load(char_id=_char_id if _char_id else "yexuan")

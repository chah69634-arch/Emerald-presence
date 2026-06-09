"""
活动状态路由

GET /activity/current  — 当前角色活动状态（activity_manager 维护的内部状态机）
GET /activity/list     — 所有已启用 reality activity 元信息（由 registry 驱动）
"""

from datetime import datetime

from fastapi import APIRouter, Depends

from admin.auth import verify_token
from core import activity_manager
from core.activity.registry import list_enabled_activities

router = APIRouter()


@router.get("/list", summary="获取所有已启用 Activity 元信息")
async def get_activity_list(auth=Depends(verify_token)):
    return [
        {
            "id": m.id,
            "label": m.label,
            "kind": m.kind,
            "enabled": m.enabled,
            "route_prefix": m.route_prefix,
            "frontend_key": m.frontend_key,
            "memory_policy": {
                "transcript": m.memory_policy.transcript,
                "summary_threshold": m.memory_policy.summary_threshold,
                "main_memory": m.memory_policy.main_memory,
            },
            "has_companion_chat": m.has_companion_chat,
        }
        for m in list_enabled_activities()
    ]


@router.get("/current", summary="获取当前活动状态")
async def get_activity_state(auth=Depends(verify_token)):
    state = activity_manager.get_current()

    started_at = None
    raw = state.get("started_at")
    if raw:
        try:
            started_at = datetime.fromisoformat(raw).timestamp()
        except Exception:
            pass

    return {
        "id": None,
        "text": state.get("current"),
        "arc": state.get("arc"),
        "started_at": started_at,
        "next_switch_at": state.get("expected_until_ts"),
        "thinking_about_eligible": bool(state.get("thinking_about")),
    }

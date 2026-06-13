"""Authenticated Intiface hardware status and connection endpoints."""

from fastapi import APIRouter, Depends

from admin.auth import verify_token


router = APIRouter()


@router.get("/devices")
async def list_devices(auth=Depends(verify_token)):
    from core.hardware.buttplug_client import get_devices, is_connected

    return {"connected": is_connected(), "devices": get_devices()}


@router.post("/connect")
async def connect(auth=Depends(verify_token)):
    from core.hardware.buttplug_client import ensure_connected

    return {"success": await ensure_connected()}


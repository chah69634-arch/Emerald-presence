"""
tests/test_garden_active_char_fail_loud.py

P1-0F.1: garden active char_id fail-loud 验收测试

Covers:
1.  garden_water active 缺失时 skip，不调用 auto_water_tick
2.  garden_water active 非法时 skip，不调用 auto_water_tick
3.  garden_daily active 缺失时 skip，不调用 daily_check
4.  garden_daily active 非法时 skip，不调用 daily_check
5.  garden_tools active 缺失时返回错误字符串，不调用 force_water
6.  garden_tools active 非法时返回错误字符串，不调用 force_water
7.  admin garden active 缺失时 HTTP 503，不调用 get_state
8.  admin garden active 读取失败时 HTTP 503，不调用 get_state
9.  admin garden active 非法时 HTTP 422，不调用 get_state
10. 所有失败场景不 fallback yexuan
11. active=character_b 时正常透传 char_id="character_b"
"""

import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from core.garden import manager as garden_manager


# ── helpers ───────────────────────────────────────────────────────────────────

def _write_active(sandbox, char_id: str) -> None:
    p = sandbox.active_prompt_assets()
    p.write_text(
        json.dumps({"active_character": char_id, "enabled_lorebooks": [], "enabled_jailbreaks": []}),
        encoding="utf-8",
    )


def _write_active_empty(sandbox) -> None:
    p = sandbox.active_prompt_assets()
    p.write_text(
        json.dumps({"active_character": "", "enabled_lorebooks": [], "enabled_jailbreaks": []}),
        encoding="utf-8",
    )


# ── 1 & 2. garden_water skip on missing / invalid active ─────────────────────

@pytest.mark.asyncio
async def test_garden_water_empty_active_skips_tick(sandbox):
    """_check_garden_water with empty active_character must not call auto_water_tick."""
    _write_active_empty(sandbox)

    called = []

    with (
        patch("core.scheduler.triggers.garden_water._is_ready", return_value=True),
        patch("core.scheduler.triggers.garden_water._mark"),
        patch("core.scheduler.execution.legacy_tick_should_send", return_value=False),
        patch.object(garden_manager, "auto_water_tick", side_effect=lambda **kw: called.append(kw)),
    ):
        from core.scheduler.triggers.garden_water import _check_garden_water
        await _check_garden_water()

    assert called == [], "auto_water_tick must not be called when active_character is empty"


@pytest.mark.asyncio
async def test_garden_water_invalid_active_skips_tick(sandbox):
    """_check_garden_water with unknown active_character must not call auto_water_tick."""
    _write_active(sandbox, "ghost_char_xyz")

    called = []

    with (
        patch("core.scheduler.triggers.garden_water._is_ready", return_value=True),
        patch("core.scheduler.triggers.garden_water._mark"),
        patch("core.scheduler.execution.legacy_tick_should_send", return_value=False),
        patch.object(garden_manager, "auto_water_tick", side_effect=lambda **kw: called.append(kw)),
    ):
        from core.scheduler.triggers.garden_water import _check_garden_water
        await _check_garden_water()

    assert called == [], "auto_water_tick must not be called when active_character is unknown"


# ── 3 & 4. garden_daily skip on missing / invalid active ─────────────────────

@pytest.mark.asyncio
async def test_garden_daily_empty_active_skips_tick(sandbox):
    """_check_garden_daily with empty active_character must not call daily_check."""
    _write_active_empty(sandbox)

    called = []

    with (
        patch("core.scheduler.triggers.garden_daily._is_ready", return_value=True),
        patch("core.scheduler.triggers.garden_daily._mark"),
        patch("core.scheduler.execution.legacy_tick_should_send", return_value=False),
        patch.object(garden_manager, "daily_check", side_effect=lambda **kw: called.append(kw) or []),
    ):
        from core.scheduler.triggers.garden_daily import _check_garden_daily
        await _check_garden_daily()

    assert called == [], "daily_check must not be called when active_character is empty"


@pytest.mark.asyncio
async def test_garden_daily_invalid_active_skips_tick(sandbox):
    """_check_garden_daily with unknown active_character must not call daily_check."""
    _write_active(sandbox, "ghost_char_xyz")

    called = []

    with (
        patch("core.scheduler.triggers.garden_daily._is_ready", return_value=True),
        patch("core.scheduler.triggers.garden_daily._mark"),
        patch("core.scheduler.execution.legacy_tick_should_send", return_value=False),
        patch.object(garden_manager, "daily_check", side_effect=lambda **kw: called.append(kw) or []),
    ):
        from core.scheduler.triggers.garden_daily import _check_garden_daily
        await _check_garden_daily()

    assert called == [], "daily_check must not be called when active_character is unknown"


# ── 5 & 6. garden_tools error on missing / invalid active ────────────────────

@pytest.mark.asyncio
async def test_garden_tools_empty_active_returns_error(sandbox):
    """water_garden with empty active_character must return error string, not call force_water."""
    _write_active_empty(sandbox)

    called = []

    with patch.object(garden_manager, "force_water", side_effect=lambda **kw: called.append(kw)):
        from core.tools.garden_tools import water_garden
        result = await water_garden()

    assert called == [], "force_water must not be called when active_character is empty"
    assert isinstance(result, str), "water_garden must return a string"
    assert result  # non-empty


@pytest.mark.asyncio
async def test_garden_tools_invalid_active_returns_error(sandbox):
    """water_garden with unknown active_character must return error string, not call force_water."""
    _write_active(sandbox, "ghost_char_xyz")

    called = []

    with patch.object(garden_manager, "force_water", side_effect=lambda **kw: called.append(kw)):
        from core.tools.garden_tools import water_garden
        result = await water_garden()

    assert called == [], "force_water must not be called when active_character is unknown"
    assert isinstance(result, str)


# ── 7 & 8 & 9. admin router 503 / 503 / 422 ─────────────────────────────────

def test_admin_garden_empty_active_raises_503(sandbox):
    """admin _active_char_id with empty active_character must raise HTTPException 503."""
    _write_active_empty(sandbox)

    called = []
    with patch.object(garden_manager, "get_state", side_effect=lambda **kw: called.append(kw)):
        from admin.routers.garden import _active_char_id
        with pytest.raises(HTTPException) as exc_info:
            _active_char_id()

    assert exc_info.value.status_code == 503
    assert called == [], "get_state must not be called when active_character is empty"


def test_admin_garden_read_failure_raises_503(sandbox, monkeypatch):
    """admin _active_char_id when read_text raises must return HTTP 503."""
    import admin.routers.garden as _garden_router

    mock_path_obj = type("_P", (), {"read_text": lambda *a, **k: (_ for _ in ()).throw(OSError("fail"))})()

    def _bad_get_paths():
        obj = type("_G", (), {"active_prompt_assets": lambda self: mock_path_obj})()
        return obj

    monkeypatch.setattr(_garden_router, "_get_paths", _bad_get_paths)

    called = []
    with patch.object(garden_manager, "get_state", side_effect=lambda **kw: called.append(kw)):
        from admin.routers.garden import _active_char_id
        with pytest.raises(HTTPException) as exc_info:
            _active_char_id()

    assert exc_info.value.status_code == 503
    assert called == []


def test_admin_garden_invalid_active_raises_422(sandbox):
    """admin _active_char_id with unknown char_id must raise HTTPException 422."""
    _write_active(sandbox, "ghost_char_xyz")

    called = []
    with patch.object(garden_manager, "get_state", side_effect=lambda **kw: called.append(kw)):
        from admin.routers.garden import _active_char_id
        with pytest.raises(HTTPException) as exc_info:
            _active_char_id()

    assert exc_info.value.status_code == 422
    assert called == [], "get_state must not be called when active_character is invalid"


# ── 10. no yexuan fallback in failure paths ───────────────────────────────────

@pytest.mark.asyncio
async def test_no_yexuan_fallback_garden_water(sandbox):
    """garden_water failure path must never call auto_water_tick(char_id='yexuan') as fallback."""
    _write_active_empty(sandbox)

    yexuan_calls = []

    def spy_tick(**kw):
        if kw.get("char_id") == "yexuan":
            yexuan_calls.append(kw)
        return {"ok": False}

    with (
        patch("core.scheduler.triggers.garden_water._is_ready", return_value=True),
        patch("core.scheduler.triggers.garden_water._mark"),
        patch("core.scheduler.execution.legacy_tick_should_send", return_value=False),
        patch.object(garden_manager, "auto_water_tick", side_effect=spy_tick),
    ):
        from core.scheduler.triggers.garden_water import _check_garden_water
        await _check_garden_water()

    assert yexuan_calls == [], "auto_water_tick must never fallback to char_id='yexuan'"


@pytest.mark.asyncio
async def test_no_yexuan_fallback_garden_tools(sandbox):
    """garden_tools failure path must never call force_water(char_id='yexuan') as fallback."""
    _write_active_empty(sandbox)

    yexuan_calls = []

    def spy_force(**kw):
        if kw.get("char_id") == "yexuan":
            yexuan_calls.append(kw)
        return {"ok": False, "reason": "test"}

    with patch.object(garden_manager, "force_water", side_effect=spy_force):
        from core.tools.garden_tools import water_garden
        await water_garden()

    assert yexuan_calls == [], "force_water must never fallback to char_id='yexuan'"


def test_no_yexuan_fallback_admin_garden(sandbox):
    """admin garden failure path must raise, not fallback to yexuan."""
    _write_active_empty(sandbox)

    yexuan_calls = []

    def spy_state(**kw):
        if kw.get("char_id") == "yexuan":
            yexuan_calls.append(kw)
        return {}

    with patch.object(garden_manager, "get_state", side_effect=spy_state):
        from admin.routers.garden import _active_char_id
        with pytest.raises(HTTPException):
            _active_char_id()

    assert yexuan_calls == [], "get_state must never be called with fallback char_id='yexuan'"


# ── 11. active=character_b passes character_b correctly ───────────────────────────────

@pytest.mark.asyncio
async def test_garden_water_character_b_passes_character_b(sandbox):
    """_check_garden_water with active=character_b must call auto_water_tick(char_id='character_b')."""
    _write_active(sandbox, "character_b")

    called = []

    def spy_tick(**kw):
        called.append(kw.get("char_id"))
        return {"ok": False}

    with (
        patch("core.scheduler.triggers.garden_water._is_ready", return_value=True),
        patch("core.scheduler.triggers.garden_water._mark"),
        patch("core.scheduler.execution.legacy_tick_should_send", return_value=False),
        patch.object(garden_manager, "auto_water_tick", side_effect=spy_tick),
    ):
        from core.scheduler.triggers.garden_water import _check_garden_water
        await _check_garden_water()

    assert called == ["character_b"], f"expected char_id='character_b', got {called}"


@pytest.mark.asyncio
async def test_garden_tools_character_b_passes_character_b(sandbox):
    """water_garden with active=character_b must call force_water(char_id='character_b')."""
    _write_active(sandbox, "character_b")

    called = []

    def spy_force(**kw):
        called.append(kw.get("char_id"))
        return {"ok": False, "reason": "no_slot_for_mood", "mood": "neutral"}

    with patch.object(garden_manager, "force_water", side_effect=spy_force):
        from core.tools.garden_tools import water_garden
        await water_garden()

    assert called == ["character_b"], f"expected char_id='character_b', got {called}"


def test_admin_garden_character_b_returns_character_b(sandbox):
    """admin _active_char_id with active=character_b must return 'character_b' without exception."""
    _write_active(sandbox, "character_b")

    from admin.routers.garden import _active_char_id
    result = _active_char_id()
    assert result == "character_b", f"expected 'character_b', got {result!r}"

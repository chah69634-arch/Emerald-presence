"""
tests/test_group_router_p4.py — group chat HTTP endpoint + WS frame contracts

Covers:
  - WS: push_group_round_start/end carry correct fields
  - WS: push_stream_start accepts char_id + round_id
  - WS: push_message accepts round_id
  - HTTP: GET /group/list
  - HTTP: POST /group/create (valid + invalid)
  - HTTP: GET /group/{id} (200 + 404)
  - HTTP: POST /group/{id}/send (202 accepted + 404 + 422)
  - HTTP: GET /group/{id}/history (basic + before filter)
  - HTTP: GET /group/{id}/settings
  - HTTP: PATCH /group/{id}/settings
  - HTTP: auth guard on all routes
"""

from __future__ import annotations

import asyncio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── WS frame tests ────────────────────────────────────────────────────────────

async def test_push_group_round_start_frame_shape(monkeypatch):
    from channels import desktop_ws

    sent = []

    async def fake_send(payload):
        sent.append(payload)
        return True

    monkeypatch.setattr(desktop_ws, "_send_json", fake_send)
    await desktop_ws.push_group_round_start("round-001", "group-abc")

    assert len(sent) == 1
    frame = sent[0]
    assert frame["type"] == "group_round_start"
    assert frame["round_id"] == "round-001"
    assert frame["group_id"] == "group-abc"


async def test_push_group_round_end_frame_shape(monkeypatch):
    from channels import desktop_ws

    sent = []

    async def fake_send(payload):
        sent.append(payload)
        return True

    monkeypatch.setattr(desktop_ws, "_send_json", fake_send)
    await desktop_ws.push_group_round_end("round-001", "group-abc")

    assert len(sent) == 1
    frame = sent[0]
    assert frame["type"] == "group_round_end"
    assert frame["round_id"] == "round-001"
    assert frame["group_id"] == "group-abc"


async def test_push_stream_start_includes_char_id_and_round_id(monkeypatch):
    from channels import desktop_ws

    sent = []

    async def fake_send(payload):
        sent.append(payload)
        return True

    monkeypatch.setattr(desktop_ws, "_send_json", fake_send)
    await desktop_ws.push_stream_start("msg-1", char_id="yexuan", round_id="round-001")

    frame = sent[0]
    assert frame["type"] == "message_stream_start"
    assert frame["msg_id"] == "msg-1"
    assert frame["char_id"] == "yexuan"
    assert frame["round_id"] == "round-001"


async def test_push_stream_start_omits_optional_fields_when_not_set(monkeypatch):
    from channels import desktop_ws

    sent = []

    async def fake_send(payload):
        sent.append(payload)
        return True

    monkeypatch.setattr(desktop_ws, "_send_json", fake_send)
    await desktop_ws.push_stream_start("msg-2")

    frame = sent[0]
    assert "char_id" not in frame
    assert "round_id" not in frame


async def test_push_message_includes_round_id(monkeypatch):
    from channels import desktop_ws

    sent = []

    async def fake_send(payload):
        sent.append(payload)
        return True

    monkeypatch.setattr(desktop_ws, "_send_json", fake_send)
    await desktop_ws.push_message("hello", msg_id="msg-1", char_id="yexuan", round_id="round-001")

    frame = sent[0]
    assert frame["type"] == "channel_message"
    assert frame["char_id"] == "yexuan"
    assert frame["round_id"] == "round-001"


async def test_push_message_omits_round_id_when_not_set(monkeypatch):
    from channels import desktop_ws

    sent = []

    async def fake_send(payload):
        sent.append(payload)
        return True

    monkeypatch.setattr(desktop_ws, "_send_json", fake_send)
    await desktop_ws.push_message("hello", msg_id="msg-1")

    frame = sent[0]
    assert "round_id" not in frame


# ── HTTP endpoint contracts ───────────────────────────────────────────────────

VALID_TOKEN = "group-router-test-secret"

_app = FastAPI()

from admin.routers.group import router as _group_router
from admin.auth import verify_token

_app.include_router(_group_router, prefix="/group")


@pytest.fixture(autouse=True)
def _patch_secret(monkeypatch):
    monkeypatch.setattr("admin.auth.get_admin_secret", lambda: VALID_TOKEN)


@pytest.fixture()
def client(sandbox):
    return TestClient(_app, raise_server_exceptions=True)


def _auth():
    return {"Authorization": f"Bearer {VALID_TOKEN}"}


def _stage(sandbox, group_id="grp-test", roster=("yexuan",)):
    from core.stage.store import create_stage
    return create_stage(group_id, "owner", list(roster))


# ── list ─────────────────────────────────────────────────────────────────────

def test_list_groups_empty(client):
    r = client.get("/group/list", headers=_auth())
    assert r.status_code == 200
    assert r.json() == []


def test_list_groups_returns_created_stages(client, sandbox):
    _stage(sandbox, "grp-list-1")
    _stage(sandbox, "grp-list-2")
    r = client.get("/group/list", headers=_auth())
    assert r.status_code == 200
    ids = [item["group_id"] for item in r.json()]
    assert "grp-list-1" in ids
    assert "grp-list-2" in ids


def test_list_groups_requires_auth(client):
    r = client.get("/group/list")
    assert r.status_code in (401, 403)


# ── create ───────────────────────────────────────────────────────────────────

def test_create_group_returns_detail(client):
    r = client.post(
        "/group/create",
        json={"group_id": "grp-create", "roster": ["yexuan"]},
        headers=_auth(),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["group_id"] == "grp-create"
    assert data["domain"] == "reality"
    assert len(data["roster"]) == 1
    assert data["roster"][0]["char_id"] == "yexuan"
    assert "settings" in data
    assert "recent" in data


def test_create_group_empty_roster_422(client):
    r = client.post(
        "/group/create",
        json={"group_id": "grp-empty", "roster": []},
        headers=_auth(),
    )
    assert r.status_code == 422


def test_create_group_dream_domain_rejected(client):
    r = client.post(
        "/group/create",
        json={"group_id": "grp-dream", "roster": ["yexuan"], "domain": "dream"},
        headers=_auth(),
    )
    assert r.status_code == 422


def test_create_group_unknown_roster_422(client):
    r = client.post(
        "/group/create",
        json={"group_id": "grp-ghost", "roster": ["nonexistent-char"]},
        headers=_auth(),
    )
    assert r.status_code == 422


def test_create_group_requires_auth(client):
    r = client.post("/group/create", json={"roster": ["yexuan"]})
    assert r.status_code in (401, 403)


# ── get detail ───────────────────────────────────────────────────────────────

def test_get_group_200(client, sandbox):
    _stage(sandbox, "grp-get")
    r = client.get("/group/grp-get", headers=_auth())
    assert r.status_code == 200
    data = r.json()
    assert data["group_id"] == "grp-get"
    assert "settings" in data
    assert "recent" in data
    assert isinstance(data["roster"], list)


def test_get_group_404(client, sandbox):
    r = client.get("/group/nonexistent", headers=_auth())
    assert r.status_code == 404


def test_get_group_requires_auth(client, sandbox):
    _stage(sandbox, "grp-auth-check")
    r = client.get("/group/grp-auth-check")
    assert r.status_code in (401, 403)


# ── send ─────────────────────────────────────────────────────────────────────

def test_group_send_returns_round_id(client, sandbox, monkeypatch):
    _stage(sandbox, "grp-send")

    async def _noop(*a, **kw):
        pass

    monkeypatch.setattr("core.stage.runtime.run_reality_stage_turn", _noop)

    r = client.post(
        "/group/grp-send/send",
        json={"message": "你好"},
        headers=_auth(),
    )
    assert r.status_code == 200
    data = r.json()
    assert "round_id" in data
    assert data["status"] == "accepted"


def test_group_send_404_for_nonexistent(client, sandbox):
    r = client.post(
        "/group/no-such-group/send",
        json={"message": "test"},
        headers=_auth(),
    )
    assert r.status_code == 404


def test_group_send_422_for_empty_message(client, sandbox):
    _stage(sandbox, "grp-send-empty")
    r = client.post(
        "/group/grp-send-empty/send",
        json={"message": ""},
        headers=_auth(),
    )
    assert r.status_code == 422


def test_group_send_requires_auth(client, sandbox):
    _stage(sandbox, "grp-send-noauth")
    r = client.post("/group/grp-send-noauth/send", json={"message": "hi"})
    assert r.status_code in (401, 403)


# ── history ──────────────────────────────────────────────────────────────────

def test_group_history_empty(client, sandbox):
    _stage(sandbox, "grp-hist")
    r = client.get("/group/grp-hist/history", headers=_auth())
    assert r.status_code == 200
    assert r.json() == []


def test_group_history_with_entries(client, sandbox):
    import time
    from core.stage.models import TranscriptEntry
    from core.stage.store import append_transcript

    stage = _stage(sandbox, "grp-hist-full")
    for i in range(3):
        append_transcript(
            stage,
            TranscriptEntry("owner", f"msg-{i}", float(i + 1), f"tid-{i}", "user"),
        )

    r = client.get("/group/grp-hist-full/history", headers=_auth())
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 3
    assert data[0]["speaker_id"] == "owner"
    assert data[0]["content"] == "msg-0"


def test_group_history_before_filter(client, sandbox):
    from core.stage.models import TranscriptEntry
    from core.stage.store import append_transcript

    stage = _stage(sandbox, "grp-hist-before")
    for i in range(4):
        append_transcript(
            stage,
            TranscriptEntry("owner", f"msg-{i}", float(i + 10), f"tid-{i}", "user"),
        )

    r = client.get("/group/grp-hist-before/history?before=12.0", headers=_auth())
    assert r.status_code == 200
    data = r.json()
    assert all(entry["timestamp"] < 12.0 for entry in data)
    assert len(data) == 2  # timestamps 10 and 11


def test_group_history_requires_auth(client, sandbox):
    _stage(sandbox, "grp-hist-auth")
    r = client.get("/group/grp-hist-auth/history")
    assert r.status_code in (401, 403)


# ── settings get ─────────────────────────────────────────────────────────────

def test_get_group_settings_200(client, sandbox):
    _stage(sandbox, "grp-settings-get")
    r = client.get("/group/grp-settings-get/settings", headers=_auth())
    assert r.status_code == 200
    data = r.json()
    assert "min_responders" in data
    assert "max_responders" in data
    assert "max_ai_chain_depth" in data


def test_get_group_settings_404(client, sandbox):
    r = client.get("/group/no-such/settings", headers=_auth())
    assert r.status_code == 404


# ── settings patch ────────────────────────────────────────────────────────────

def test_patch_group_settings_updates_field(client, sandbox):
    _stage(sandbox, "grp-settings-patch")
    r = client.patch(
        "/group/grp-settings-patch/settings",
        json={"min_responders": 2, "max_responders": 3},
        headers=_auth(),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["min_responders"] == 2
    assert data["max_responders"] == 3


def test_patch_group_settings_invalid_value_422(client, sandbox):
    _stage(sandbox, "grp-settings-bad")
    r = client.patch(
        "/group/grp-settings-bad/settings",
        json={"min_responders": 99, "max_responders": 1},  # min > max
        headers=_auth(),
    )
    assert r.status_code == 422


def test_patch_group_settings_404(client, sandbox):
    r = client.patch("/group/missing/settings", json={}, headers=_auth())
    assert r.status_code == 404


def test_patch_group_settings_requires_auth(client, sandbox):
    _stage(sandbox, "grp-settings-noauth")
    r = client.patch("/group/grp-settings-noauth/settings", json={})
    assert r.status_code in (401, 403)


# ── runtime WS round lifecycle ────────────────────────────────────────────────

async def test_runtime_pushes_round_start_and_end(sandbox, monkeypatch):
    """run_reality_stage_turn pushes group_round_start before and group_round_end after."""
    from core.stage.store import create_stage
    from core.stage.runtime import run_reality_stage_turn

    create_stage("grp-lifecycle", "owner", ["yexuan"])

    ws_frames = []

    async def fake_send(payload):
        ws_frames.append(payload)
        return True

    monkeypatch.setattr("channels.desktop_ws._send_json", fake_send)
    monkeypatch.setattr("channels.desktop_ws._current_ws", object())

    async def fake_generate(stage, speaker_id, transcript, turn_id, triggered_by):
        return "hello from char"

    monkeypatch.setattr("core.stage.views.StageCharacterView.generate", fake_generate)

    # Stub out slow_queue.enqueue so projection doesn't run
    monkeypatch.setattr(
        "core.post_process.slow_queue.enqueue", lambda *a, **kw: None
    )

    await run_reality_stage_turn(
        "grp-lifecycle", "owner message", fanout=True, round_id="round-xyz"
    )

    types = [f["type"] for f in ws_frames]
    assert "group_round_start" in types
    assert "group_round_end" in types
    # start before end
    assert types.index("group_round_start") < types.index("group_round_end")
    # round_id matches
    start = next(f for f in ws_frames if f["type"] == "group_round_start")
    end = next(f for f in ws_frames if f["type"] == "group_round_end")
    assert start["round_id"] == "round-xyz"
    assert end["round_id"] == "round-xyz"
    assert start["group_id"] == "grp-lifecycle"

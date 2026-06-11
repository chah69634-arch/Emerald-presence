"""
tests/test_prompt_builder_period_scope.py

P1-0H.1: prompt_builder.build() passes char_id to get_period_info

Covers:
1. Source scan: get_period_info call in prompt_builder.py includes char_id=char_id
2. Signature: get_period_info accepts char_id kwarg (default "yexuan")
3. Backward compat: get_period_info(uid) without char_id still works
4. Data isolation: different char_ids read different profile buckets
5. Build spy: build() with char_id="character_b" calls get_period_info(char_id="character_b")
6. Content isolation: character_b build() does not inject yexuan period data
"""

import datetime
import inspect
import json
import pathlib
from unittest.mock import MagicMock

import pytest

ROOT = pathlib.Path(__file__).parent.parent

import core.memory.user_profile  # noqa: F401  ensure module-level init runs at project root
import core.prompt_builder       # noqa: F401


def _read_src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Source scan
# ─────────────────────────────────────────────────────────────────────────────

def test_prompt_builder_period_call_includes_char_id():
    """prompt_builder.py の get_period_info 呼び出しが char_id=char_id を含む (T1 fix)."""
    src = _read_src("core/prompt_builder.py")
    call_lines = [
        line.strip()
        for line in src.splitlines()
        if "get_period_info(" in line and not line.strip().startswith("#")
    ]
    assert call_lines, "prompt_builder.py に get_period_info 呼び出しが見つからない"
    for line in call_lines:
        assert "char_id=char_id" in line, (
            f"prompt_builder.py の get_period_info 呼び出しに char_id= がない: {line!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Signature
# ─────────────────────────────────────────────────────────────────────────────

def test_get_period_info_signature_accepts_char_id():
    """get_period_info の関数シグネチャに char_id がある."""
    from core.memory.user_profile import get_period_info
    sig = inspect.signature(get_period_info)
    assert "char_id" in sig.parameters, (
        f"get_period_info に char_id パラメータがない: {list(sig.parameters.keys())}"
    )
    assert sig.parameters["char_id"].default == "yexuan", (
        f"char_id default は 'yexuan' であるべき: {sig.parameters['char_id'].default!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Backward compat (no char_id arg → default yexuan)
# ─────────────────────────────────────────────────────────────────────────────

def test_get_period_info_default_char_id(sandbox):
    """char_id 省略時は 'yexuan' バケットを読む (後方互換)."""
    uid = "u999"
    path = sandbox.user_memory_root(uid, char_id="yexuan") / "profile.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"last_period_date": "2026-01-15"}), encoding="utf-8"
    )

    import core.memory.user_profile as _up
    result = _up.get_period_info(uid)
    assert result == {"last_period_date": "2026-01-15"}


# ─────────────────────────────────────────────────────────────────────────────
# 4. Data isolation: different char_ids → different buckets
# ─────────────────────────────────────────────────────────────────────────────

def test_get_period_info_char_id_isolation(sandbox):
    """char_id="yexuan" vs "character_b" で異なる生理期データを読む."""
    uid = "u1"
    for char, date in [("yexuan", "2026-06-01"), ("character_b", "2026-06-15")]:
        path = sandbox.user_memory_root(uid, char_id=char) / "profile.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"last_period_date": date}), encoding="utf-8"
        )

    import core.memory.user_profile as _up
    yexuan_info = _up.get_period_info(uid, char_id="yexuan")
    character_b_info = _up.get_period_info(uid, char_id="character_b")

    assert yexuan_info == {"last_period_date": "2026-06-01"}
    assert character_b_info == {"last_period_date": "2026-06-15"}
    assert yexuan_info != character_b_info


# ─────────────────────────────────────────────────────────────────────────────
# 5. Build spy: build() passes char_id through to get_period_info
# ─────────────────────────────────────────────────────────────────────────────

def _apply_build_stubs(monkeypatch):
    """Stub all filesystem-touching helpers so build() can run in tests."""
    import core.prompt_builder as _pb
    import core.presence as _pres
    import core.author_note_rotator as _anr
    import core.config_loader as _cl

    monkeypatch.setattr(_pb, "_load_jailbreak", lambda layer=None: "")
    monkeypatch.setattr(_pb, "_load_style_hint", lambda *, char_id="": "")
    monkeypatch.setattr(_pb, "_load_activity_snapshot", lambda *, char_id="": "")
    monkeypatch.setattr(_pb, "_format_afterglow_soft_hint", lambda uid, char_id="yexuan": "")
    monkeypatch.setattr(_pres, "get_last_seen_text", lambda uid: "")
    monkeypatch.setattr(_anr, "get_current_note", lambda paths=None, char_id=None: "")
    monkeypatch.setattr(_cl, "get_config", lambda: {"chat": {}})


def test_build_passes_char_id_to_get_period_info(monkeypatch):
    """build() が period trigger tag と char_id="character_b" で呼ばれたとき、
    get_period_info(uid, char_id="character_b") が呼ばれる."""
    _apply_build_stubs(monkeypatch)

    import core.memory.user_profile as _up
    import core.prompt_builder as _pb
    from core.character_loader import Character

    period_calls: list[dict] = []

    def _spy(uid, *, char_id="yexuan"):
        period_calls.append({"uid": uid, "char_id": char_id})
        return {}

    monkeypatch.setattr(_up, "get_period_info", _spy)

    char = Character(name="DemoUser")
    _pb.build(
        character=char,
        user_id="u1",
        user_message="肚子好痛",
        history=[{"role": "user", "content": "hi", "_layer": "9_history"}],
        relation={"role": "friend"},
        profile={},
        group_context=[],
        tags={"topic.body"},
        char_id="character_b",
    )

    assert period_calls, "get_period_info が呼ばれていない"
    assert period_calls[0]["char_id"] == "character_b", (
        f"char_id='character_b' が渡されるべき, 実際: {period_calls[0]['char_id']!r}"
    )


def test_build_passes_char_id_yexuan(monkeypatch):
    """char_id="yexuan" で build() したとき get_period_info に yexuan が渡る."""
    _apply_build_stubs(monkeypatch)

    import core.memory.user_profile as _up
    import core.prompt_builder as _pb
    from core.character_loader import Character

    period_calls: list[dict] = []

    def _spy(uid, *, char_id="yexuan"):
        period_calls.append({"uid": uid, "char_id": char_id})
        return {}

    monkeypatch.setattr(_up, "get_period_info", _spy)

    char = Character(name="Companion")
    _pb.build(
        character=char,
        user_id="u2",
        user_message="今天很难受",
        history=[{"role": "user", "content": "hi", "_layer": "9_history"}],
        relation={"role": "friend"},
        profile={},
        group_context=[],
        tags={"emotion.physical_discomfort"},
        char_id="yexuan",
    )

    assert period_calls, "get_period_info が呼ばれていない"
    assert period_calls[0]["char_id"] == "yexuan"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Content isolation: character_b build() must not inject yexuan period text
# ─────────────────────────────────────────────────────────────────────────────

def test_build_character_b_excludes_yexuan_period_data(sandbox, monkeypatch):
    """yexuan は生理期データあり, character_b はなし → character_b build() に生理期層が入らない."""
    uid = "u1"
    today = datetime.date.today().isoformat()

    for char, date in [("yexuan", today), ("character_b", None)]:
        path = sandbox.user_memory_root(uid, char_id=char) / "profile.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"last_period_date": date}), encoding="utf-8"
        )

    import core.prompt_builder as _pb
    from core.character_loader import Character

    _apply_build_stubs(monkeypatch)

    char = Character(name="DemoUser")
    messages, _ = _pb.build(
        character=char,
        user_id=uid,
        user_message="肚子好痛",
        history=[{"role": "user", "content": "hi", "_layer": "9_history"}],
        relation={"role": "friend"},
        profile={},
        group_context=[],
        tags={"topic.body"},
        char_id="character_b",
    )

    layers = [m.get("_layer") for m in messages]
    assert "3.5_period" not in layers, (
        "character_b に yexuan の生理期バケットが混入: layers=" + str(layers)
    )

    full_text = " ".join(m.get("content", "") for m in messages)
    assert "生理期" not in full_text, (
        "character_b build() の出力に '生理期' が含まれている (yexuan データ漏洩)"
    )

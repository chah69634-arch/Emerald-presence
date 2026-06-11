"""
tests/test_episodic_sweep_char_scope.py

P1-0D: episodic_sweep char_id plumbing 验收测试

Covers:
1. _sweep_uid 调用 _mt.load 时显式传 char_id="character_b"
2. _sweep_uid enqueue reflect_to_episodic payload 包含 char_id="character_b"
3. yexuan 与 character_b 各有 mid_term 时两边都被 sweep，不只扫 yexuan
4. sweep character_b 时不读取 yexuan mid_term bucket
5. 角色 runtime 目录不存在时不报错
6. 不在注册表的 char_id 目录不被 sweep，不生成 fallback yexuan payload
"""

import time
from unittest.mock import MagicMock, patch

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_char_entry(char_id: str) -> MagicMock:
    e = MagicMock()
    e.id = char_id
    e.kind = "character"
    return e


def _make_registry(*char_ids: str) -> MagicMock:
    reg = MagicMock()
    reg.list_all.return_value = [_make_char_entry(cid) for cid in char_ids]
    return reg


def _aged_event(mid_id: str) -> dict:
    return {
        "mid_id": mid_id,
        "ts": time.time() - 12 * 3600,
        "promoted_to_episodic_id": None,
        "summary": "test",
    }


# ── Test 1: _sweep_uid 调用 _mt.load 时必须传 char_id ─────────────────────────

@pytest.mark.asyncio
async def test_sweep_uid_loads_mt_with_explicit_char_id(sandbox):
    """_sweep_uid(uid, char_id='character_b') 必须以 char_id='character_b' 调用 _mt.load。"""
    import core.memory.mid_term as _mt
    import core.post_process.slow_queue as sq
    from core.scheduler.triggers.episodic_sweep import _sweep_uid

    captured: list[tuple[str, str]] = []

    def _spy_load(uid, *, char_id="yexuan"):
        captured.append((uid, char_id))
        return []

    with (
        patch.object(_mt, "load", side_effect=_spy_load),
        patch.object(sq, "enqueue", return_value=None),
    ):
        await _sweep_uid("u1", char_id="character_b")

    assert len(captured) == 1
    assert captured[0] == ("u1", "character_b"), (
        f"_mt.load 应以 char_id='character_b' 被调用，实际: {captured[0]!r}"
    )


# ── Test 2: enqueue payload 包含 char_id ──────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_uid_enqueue_payload_contains_char_id(sandbox):
    """_sweep_uid enqueue 的 reflect_to_episodic payload 必须包含 char_id='character_b'。"""
    import core.memory.mid_term as _mt
    import core.post_process.slow_queue as sq
    from core.scheduler.triggers.episodic_sweep import _sweep_uid

    enqueued: list[tuple[str, dict]] = []

    with (
        patch.object(_mt, "load", return_value=[_aged_event("mt_x")]),
        patch.object(sq, "enqueue", side_effect=lambda t, p: enqueued.append((t, p))),
    ):
        await _sweep_uid("u1", char_id="character_b")

    assert len(enqueued) == 1
    task_type, payload = enqueued[0]
    assert task_type == "reflect_to_episodic"
    assert payload.get("char_id") == "character_b", (
        f"payload 必须含 char_id='character_b'，实际: {payload!r}"
    )
    assert payload.get("uid") == "u1"
    assert "mt_x" in payload.get("mid_ids", [])
    assert payload.get("trigger") == "sweep"


# ── Test 3: 两个角色都被 sweep ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_sweep_covers_both_chars(sandbox):
    """_check_episodic_sweep 必须遍历所有注册角色，不只扫 yexuan。"""
    import core.memory.mid_term as _mt
    import core.post_process.slow_queue as sq
    from core.scheduler.triggers.episodic_sweep import _check_episodic_sweep

    # 为 yexuan 和 character_b 各创建一个用户目录及 mid_term.json
    for char_id in ("yexuan", "character_b"):
        uid_dir = sandbox.memory_char_root(char_id=char_id) / "u1"
        uid_dir.mkdir(parents=True, exist_ok=True)
        (uid_dir / "mid_term.json").write_text("{}", encoding="utf-8")

    loaded_calls: list[tuple[str, str]] = []
    enqueued: list[tuple[str, dict]] = []

    def _spy_load(uid, *, char_id="yexuan"):
        loaded_calls.append((uid, char_id))
        return [_aged_event(f"mt_{char_id}")]

    with (
        patch("core.asset_registry.get_registry", return_value=_make_registry("yexuan", "character_b")),
        patch.object(_mt, "load", side_effect=_spy_load),
        patch.object(sq, "enqueue", side_effect=lambda t, p: enqueued.append((t, p))),
        patch("core.scheduler.loop._is_ready", return_value=True),
        patch("core.scheduler.loop._mark"),
    ):
        await _check_episodic_sweep()

    loaded_char_ids = {c for _, c in loaded_calls}
    assert "yexuan" in loaded_char_ids, "yexuan 的 mid_term 应被加载"
    assert "character_b" in loaded_char_ids, "character_b 的 mid_term 应被加载"

    enqueued_char_ids = {p.get("char_id") for _, p in enqueued}
    assert "yexuan" in enqueued_char_ids, "yexuan 任务应入队"
    assert "character_b" in enqueued_char_ids, "character_b 任务应入队"


# ── Test 4: sweep character_b 时不读取 yexuan bucket ──────────────────────────────

@pytest.mark.asyncio
async def test_sweep_character_b_does_not_read_yexuan_bucket(sandbox):
    """sweep character_b 时，_mt.load 不应以 char_id='yexuan' 被调用。"""
    import core.memory.mid_term as _mt
    import core.post_process.slow_queue as sq
    from core.scheduler.triggers.episodic_sweep import _check_episodic_sweep

    # 只创建 character_b 目录
    uid_dir = sandbox.memory_char_root(char_id="character_b") / "u2"
    uid_dir.mkdir(parents=True, exist_ok=True)
    (uid_dir / "mid_term.json").write_text("{}", encoding="utf-8")

    loaded_calls: list[tuple[str, str]] = []

    def _spy_load(uid, *, char_id="yexuan"):
        loaded_calls.append((uid, char_id))
        return []

    with (
        patch("core.asset_registry.get_registry", return_value=_make_registry("character_b")),
        patch.object(_mt, "load", side_effect=_spy_load),
        patch.object(sq, "enqueue", return_value=None),
        patch("core.scheduler.loop._is_ready", return_value=True),
        patch("core.scheduler.loop._mark"),
    ):
        await _check_episodic_sweep()

    for uid, char_id in loaded_calls:
        assert char_id == "character_b", (
            f"sweep character_b 时 _mt.load 不应使用 char_id='yexuan'，实际: (uid={uid!r}, char_id={char_id!r})"
        )
    assert loaded_calls, "_mt.load 应被调用至少一次"


# ── Test 5: runtime 目录不存在不报错 ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_nonexistent_char_dir_no_error(sandbox):
    """注册了角色但 runtime 目录不存在时，sweep 不应抛异常，也不应入队任何任务。"""
    import core.post_process.slow_queue as sq
    from core.scheduler.triggers.episodic_sweep import _check_episodic_sweep

    enqueued: list = []

    with (
        patch("core.asset_registry.get_registry", return_value=_make_registry("yexuan", "character_b")),
        patch.object(sq, "enqueue", side_effect=lambda t, p: enqueued.append((t, p))),
        patch("core.scheduler.loop._is_ready", return_value=True),
        patch("core.scheduler.loop._mark"),
    ):
        await _check_episodic_sweep()  # 不应抛异常

    assert enqueued == [], "目录不存在时不应入队任何任务"


# ── Test 6: 不在注册表的角色目录不被扫描，不生成 yexuan fallback ───────────────

@pytest.mark.asyncio
async def test_unregistered_char_dir_not_swept_no_yexuan_fallback(sandbox):
    """
    yexuan 目录存在但不在 registry 中时，yexuan 不被扫描，
    不会生成任何 char_id='yexuan' 的 payload。
    """
    import core.memory.mid_term as _mt
    import core.post_process.slow_queue as sq
    from core.scheduler.triggers.episodic_sweep import _check_episodic_sweep

    # 创建 yexuan 和 character_b 目录，但 registry 只含 character_b
    for char_id in ("yexuan", "character_b"):
        uid_dir = sandbox.memory_char_root(char_id=char_id) / "u3"
        uid_dir.mkdir(parents=True, exist_ok=True)
        (uid_dir / "mid_term.json").write_text("{}", encoding="utf-8")

    enqueued: list[tuple[str, dict]] = []

    def _spy_load(uid, *, char_id="yexuan"):
        return [_aged_event(f"mt_{char_id}_x")]

    with (
        patch("core.asset_registry.get_registry", return_value=_make_registry("character_b")),
        patch.object(_mt, "load", side_effect=_spy_load),
        patch.object(sq, "enqueue", side_effect=lambda t, p: enqueued.append((t, p))),
        patch("core.scheduler.loop._is_ready", return_value=True),
        patch("core.scheduler.loop._mark"),
    ):
        await _check_episodic_sweep()

    for _, payload in enqueued:
        assert payload.get("char_id") != "yexuan", (
            f"yexuan 不在 registry 中，不应生成 char_id='yexuan' payload，实际: {payload!r}"
        )
    assert all(p.get("char_id") == "character_b" for _, p in enqueued), (
        f"所有入队 payload 应有 char_id='character_b'，实际: {[p for _, p in enqueued]!r}"
    )
    assert enqueued, "character_b 应有入队任务"

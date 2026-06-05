"""
tests/test_hidden_state_decay_all_chars.py — P1-0G: hidden_state_decay 多角色遍历验收

Covers:
1.  decay 遍历 registry 中的 yexuan 和 hongcha，两边都被处理
2.  yexuan/hongcha 各有 hidden_state 时两边都被 decay（load+save 各触发一次）
3.  hongcha decay 调用 store 时收到 char_id="hongcha"，不混用 yexuan
4.  active_character 缺失/非法不影响 decay 遍历所有注册角色
5.  某角色 runtime 目录不存在时跳过，不报错
6.  注册表为空时 warning + return，不触发任何 load/save
7.  yexuan hidden_state 不会被用于 hongcha decay（桶隔离）
8.  新逻辑不触碰 legacy uid-only hidden_state 路径
9.  consolidate 也遍历所有注册角色（_check_hidden_state_consolidate）
"""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock, patch

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_registry(*char_ids: str) -> MagicMock:
    reg = MagicMock()
    entries = []
    for cid in char_ids:
        e = MagicMock()
        e.id = cid
        entries.append(e)
    reg.list_all.return_value = entries
    return reg


def _make_default_state():
    from core.memory.user_hidden_state import default_hidden_state
    return default_hidden_state()


# ── Test 1: decay 遍历 registry 中的 yexuan 和 hongcha ───────────────────────

def test_decay_covers_both_registered_chars(sandbox):
    """_check_hidden_state_decay 必须遍历所有注册角色，不只处理 yexuan。"""
    from core.scheduler.triggers import hidden_state_decay as _hsd

    for char_id in ("yexuan", "hongcha"):
        uid_dir = sandbox.memory_char_root(char_id=char_id) / "u1"
        uid_dir.mkdir(parents=True, exist_ok=True)
        (uid_dir / "hidden_state.json").write_text("{}", encoding="utf-8")

    load_char_ids: list[str] = []
    save_char_ids: list[str] = []

    def _spy_load(uid, *, char_id="yexuan"):
        load_char_ids.append(char_id)
        return _make_default_state()

    def _spy_save(uid, state, *, char_id="yexuan"):
        save_char_ids.append(char_id)
        return True

    with patch("core.scheduler.loop._is_ready", return_value=True), \
         patch("core.scheduler.loop._mark"), \
         patch("core.asset_registry.get_registry",
               return_value=_make_registry("yexuan", "hongcha")), \
         patch("core.memory.user_hidden_state_store.load_hidden_state", _spy_load), \
         patch("core.memory.user_hidden_state_store.save_hidden_state", _spy_save), \
         patch("core.memory.user_hidden_state.apply_time_decay",
               side_effect=lambda s, _n: s):
        asyncio.run(_hsd._check_hidden_state_decay())

    assert "yexuan" in load_char_ids, "yexuan must be processed"
    assert "hongcha" in load_char_ids, "hongcha must be processed"
    assert "yexuan" in save_char_ids
    assert "hongcha" in save_char_ids


# ── Test 2: 两边都被 decay（load+save 各触发一次）────────────────────────────

def test_decay_calls_load_and_save_for_each_char(sandbox):
    """每个 (char_id, uid) 对都触发一次 load + save，不多不少。"""
    from core.scheduler.triggers import hidden_state_decay as _hsd

    for char_id in ("yexuan", "hongcha"):
        uid_dir = sandbox.memory_char_root(char_id=char_id) / "u1"
        uid_dir.mkdir(parents=True, exist_ok=True)
        (uid_dir / "hidden_state.json").write_text("{}", encoding="utf-8")

    load_calls: list[tuple[str, str]] = []
    save_calls: list[tuple[str, str]] = []

    def _spy_load(uid, *, char_id="yexuan"):
        load_calls.append((uid, char_id))
        return _make_default_state()

    def _spy_save(uid, state, *, char_id="yexuan"):
        save_calls.append((uid, char_id))
        return True

    with patch("core.scheduler.loop._is_ready", return_value=True), \
         patch("core.scheduler.loop._mark"), \
         patch("core.asset_registry.get_registry",
               return_value=_make_registry("yexuan", "hongcha")), \
         patch("core.memory.user_hidden_state_store.load_hidden_state", _spy_load), \
         patch("core.memory.user_hidden_state_store.save_hidden_state", _spy_save), \
         patch("core.memory.user_hidden_state.apply_time_decay",
               side_effect=lambda s, _n: s):
        asyncio.run(_hsd._check_hidden_state_decay())

    assert len(load_calls) == 2, f"expected 2 load calls, got {load_calls}"
    assert len(save_calls) == 2, f"expected 2 save calls, got {save_calls}"
    assert ("u1", "yexuan") in load_calls
    assert ("u1", "hongcha") in load_calls


# ── Test 3: hongcha decay 调用 store 时收到 char_id="hongcha" ────────────────

def test_decay_passes_correct_char_id_to_store(sandbox):
    """store 调用时 char_id 必须与当前角色一致，不能混用 yexuan 默认值。"""
    from core.scheduler.triggers import hidden_state_decay as _hsd

    uid_dir = sandbox.memory_char_root(char_id="hongcha") / "u2"
    uid_dir.mkdir(parents=True, exist_ok=True)
    (uid_dir / "hidden_state.json").write_text("{}", encoding="utf-8")

    received: list[dict] = []

    def _spy_load(uid, *, char_id="yexuan"):
        received.append({"op": "load", "uid": uid, "char_id": char_id})
        return _make_default_state()

    def _spy_save(uid, state, *, char_id="yexuan"):
        received.append({"op": "save", "uid": uid, "char_id": char_id})
        return True

    with patch("core.scheduler.loop._is_ready", return_value=True), \
         patch("core.scheduler.loop._mark"), \
         patch("core.asset_registry.get_registry",
               return_value=_make_registry("hongcha")), \
         patch("core.memory.user_hidden_state_store.load_hidden_state", _spy_load), \
         patch("core.memory.user_hidden_state_store.save_hidden_state", _spy_save), \
         patch("core.memory.user_hidden_state.apply_time_decay",
               side_effect=lambda s, _n: s):
        asyncio.run(_hsd._check_hidden_state_decay())

    load_rec = next((r for r in received if r["op"] == "load"), None)
    save_rec = next((r for r in received if r["op"] == "save"), None)
    assert load_rec is not None, "load must be called"
    assert load_rec["char_id"] == "hongcha", \
        f"load char_id must be 'hongcha', got {load_rec['char_id']!r}"
    assert save_rec is not None, "save must be called"
    assert save_rec["char_id"] == "hongcha", \
        f"save char_id must be 'hongcha', got {save_rec['char_id']!r}"


# ── Test 4: active 缺失/非法不影响 decay ──────────────────────────────────────

def test_decay_not_blocked_by_missing_active_character(sandbox):
    """active_prompt_assets.json 缺失或 active_character 为空不影响多角色 decay。"""
    from core.scheduler.triggers import hidden_state_decay as _hsd

    uid_dir = sandbox.memory_char_root(char_id="yexuan") / "u_active_test"
    uid_dir.mkdir(parents=True, exist_ok=True)
    (uid_dir / "hidden_state.json").write_text("{}", encoding="utf-8")

    save_called = []

    def _spy_save(uid, state, *, char_id="yexuan"):
        save_called.append(char_id)
        return True

    with patch("core.scheduler.loop._is_ready", return_value=True), \
         patch("core.scheduler.loop._mark"), \
         patch("core.asset_registry.get_registry",
               return_value=_make_registry("yexuan")), \
         patch("core.memory.user_hidden_state_store.load_hidden_state",
               return_value=_make_default_state()), \
         patch("core.memory.user_hidden_state_store.save_hidden_state", _spy_save), \
         patch("core.memory.user_hidden_state.apply_time_decay",
               side_effect=lambda s, _n: s):
        asyncio.run(_hsd._check_hidden_state_decay())

    assert save_called, "decay MUST run even when active_character is unavailable"
    assert save_called[0] == "yexuan"


# ── Test 5: 某角色 runtime 目录不存在时跳过，不报错 ──────────────────────────

def test_decay_skips_missing_char_dir_without_error(sandbox):
    """某角色的 memory_char_root 不存在时静默跳过，不抛异常，不影响其他角色。"""
    from core.scheduler.triggers import hidden_state_decay as _hsd

    # 只创建 yexuan 目录，hongcha 目录不创建
    uid_dir = sandbox.memory_char_root(char_id="yexuan") / "u1"
    uid_dir.mkdir(parents=True, exist_ok=True)
    (uid_dir / "hidden_state.json").write_text("{}", encoding="utf-8")

    save_char_ids: list[str] = []

    def _spy_save(uid, state, *, char_id="yexuan"):
        save_char_ids.append(char_id)
        return True

    with patch("core.scheduler.loop._is_ready", return_value=True), \
         patch("core.scheduler.loop._mark"), \
         patch("core.asset_registry.get_registry",
               return_value=_make_registry("yexuan", "hongcha")), \
         patch("core.memory.user_hidden_state_store.load_hidden_state",
               return_value=_make_default_state()), \
         patch("core.memory.user_hidden_state_store.save_hidden_state", _spy_save), \
         patch("core.memory.user_hidden_state.apply_time_decay",
               side_effect=lambda s, _n: s):
        asyncio.run(_hsd._check_hidden_state_decay())

    assert save_char_ids == ["yexuan"], \
        f"only yexuan should be processed (hongcha dir absent), got {save_char_ids}"


# ── Test 6: 注册表为空时 warning + return，不触发 load/save ──────────────────

def test_decay_empty_registry_warns_and_skips(caplog):
    """registry 返回空列表时 WARN + 直接 return，不触发任何 load/save。"""
    from core.scheduler.triggers import hidden_state_decay as _hsd

    load_called = []
    save_called = []

    with patch("core.scheduler.loop._is_ready", return_value=True), \
         patch("core.scheduler.loop._mark"), \
         patch("core.asset_registry.get_registry", return_value=_make_registry()), \
         patch("core.memory.user_hidden_state_store.load_hidden_state",
               side_effect=lambda uid, **kw: load_called.append(uid)), \
         patch("core.memory.user_hidden_state_store.save_hidden_state",
               side_effect=lambda uid, state, **kw: save_called.append(uid)), \
         caplog.at_level(logging.WARNING,
                         logger="core.scheduler.triggers.hidden_state_decay"):
        asyncio.run(_hsd._check_hidden_state_decay())

    assert not load_called, "load must NOT be called when registry is empty"
    assert not save_called, "save must NOT be called when registry is empty"
    assert caplog.text, "a WARNING must be emitted when registry is empty"


# ── Test 7: yexuan hidden_state 不会被用于 hongcha decay ─────────────────────

def test_decay_yexuan_state_not_applied_to_hongcha(sandbox):
    """yexuan 和 hongcha 各自只读各自的 hidden_state，不跨桶。"""
    from core.scheduler.triggers import hidden_state_decay as _hsd
    from core.memory.user_hidden_state import default_hidden_state
    from core.memory.user_hidden_state_store import save_hidden_state, load_hidden_state

    # 预置 yexuan baseline=10, hongcha baseline=20
    state_y = default_hidden_state()
    state_y.sensitivity.baseline.value = 10.0
    save_hidden_state("u1", state_y, char_id="yexuan")

    state_h = default_hidden_state()
    state_h.sensitivity.baseline.value = 20.0
    save_hidden_state("u1", state_h, char_id="hongcha")

    loaded_for_char: dict[str, float] = {}

    real_load = load_hidden_state

    def _spy_load(uid, *, char_id="yexuan"):
        state = real_load(uid, char_id=char_id)
        loaded_for_char[char_id] = state.sensitivity.baseline.value
        return state

    with patch("core.scheduler.loop._is_ready", return_value=True), \
         patch("core.scheduler.loop._mark"), \
         patch("core.asset_registry.get_registry",
               return_value=_make_registry("yexuan", "hongcha")), \
         patch("core.memory.user_hidden_state_store.load_hidden_state", _spy_load), \
         patch("core.memory.user_hidden_state_store.save_hidden_state",
               return_value=True), \
         patch("core.memory.user_hidden_state.apply_time_decay",
               side_effect=lambda s, _n: s):
        asyncio.run(_hsd._check_hidden_state_decay())

    assert loaded_for_char.get("yexuan") == pytest.approx(10.0), \
        "yexuan decay must load from yexuan bucket (baseline=10)"
    assert loaded_for_char.get("hongcha") == pytest.approx(20.0), \
        "hongcha decay must load from hongcha bucket (baseline=20), not yexuan's"


# ── Test 8: 新逻辑不触碰 legacy uid-only hidden_state 路径 ───────────────────

def test_decay_does_not_touch_legacy_uid_only_path(sandbox):
    """新 decay 只扫描 memory/{char_id}/{uid}/，不扫描 legacy memory/{uid}/ 路径。"""
    from core.scheduler.triggers import hidden_state_decay as _hsd

    # 在 sandbox 的 runtime/memory/ 下创建一个看起来像"uid"的目录（legacy 路径模拟）
    legacy_uid_dir = sandbox._p("runtime", "memory", "legacy_uid_as_char")
    legacy_uid_dir.mkdir(parents=True, exist_ok=True)
    (legacy_uid_dir / "hidden_state.json").write_text("{}", encoding="utf-8")

    # Registry 只注册 yexuan，不包含 "legacy_uid_as_char"
    # 如果新代码只按 registry char_ids 扫，legacy 路径永远不会被访问
    uid_dir = sandbox.memory_char_root(char_id="yexuan") / "u1"
    uid_dir.mkdir(parents=True, exist_ok=True)
    (uid_dir / "hidden_state.json").write_text("{}", encoding="utf-8")

    processed_char_ids: list[str] = []

    def _spy_load(uid, *, char_id="yexuan"):
        processed_char_ids.append(char_id)
        return _make_default_state()

    with patch("core.scheduler.loop._is_ready", return_value=True), \
         patch("core.scheduler.loop._mark"), \
         patch("core.asset_registry.get_registry",
               return_value=_make_registry("yexuan")), \
         patch("core.memory.user_hidden_state_store.load_hidden_state", _spy_load), \
         patch("core.memory.user_hidden_state_store.save_hidden_state",
               return_value=True), \
         patch("core.memory.user_hidden_state.apply_time_decay",
               side_effect=lambda s, _n: s):
        asyncio.run(_hsd._check_hidden_state_decay())

    assert processed_char_ids == ["yexuan"], \
        f"must only process registered char_ids, got {processed_char_ids}"
    assert "legacy_uid_as_char" not in processed_char_ids, \
        "legacy uid-only path must not be processed"


# ── Test 9: consolidate 也遍历所有注册角色 ────────────────────────────────────

def test_consolidate_covers_both_registered_chars(sandbox):
    """_check_hidden_state_consolidate 也必须遍历所有注册角色，与 decay 行为一致。"""
    from core.scheduler.triggers import hidden_state_decay as _hsd

    for char_id in ("yexuan", "hongcha"):
        uid_dir = sandbox.memory_char_root(char_id=char_id) / "u1"
        uid_dir.mkdir(parents=True, exist_ok=True)
        (uid_dir / "hidden_state.json").write_text("{}", encoding="utf-8")

    save_char_ids: list[str] = []

    def _spy_save(uid, state, *, char_id="yexuan"):
        save_char_ids.append(char_id)
        return True

    with patch("core.scheduler.loop._is_ready", return_value=True), \
         patch("core.scheduler.loop._mark"), \
         patch("core.asset_registry.get_registry",
               return_value=_make_registry("yexuan", "hongcha")), \
         patch("core.memory.user_hidden_state_store.load_hidden_state",
               return_value=_make_default_state()), \
         patch("core.memory.user_hidden_state_store.save_hidden_state", _spy_save), \
         patch("core.memory.user_hidden_state.consolidate_baselines",
               side_effect=lambda s, _n: s):
        asyncio.run(_hsd._check_hidden_state_consolidate())

    assert "yexuan" in save_char_ids, "yexuan must be consolidated"
    assert "hongcha" in save_char_ids, "hongcha must be consolidated"


# ── Test 10: 冷却未到时不运行 ─────────────────────────────────────────────────

def test_decay_skips_when_not_ready():
    """_is_ready 返回 False 时直接 return，不触发任何 load/save。"""
    from core.scheduler.triggers import hidden_state_decay as _hsd

    load_called = []
    with patch("core.scheduler.loop._is_ready", return_value=False), \
         patch("core.memory.user_hidden_state_store.load_hidden_state",
               side_effect=lambda uid, **kw: load_called.append(uid)):
        asyncio.run(_hsd._check_hidden_state_decay())

    assert not load_called, "load must not be called when cooldown has not elapsed"

"""
V1.5 三处修复验证测试

修1: for_read 空文件/损坏判定 — new 为空或损坏时必须 fallback 到 old
修2: trait_state 对称链路 — for_read 读旧窗口，写到新路径
修3: dream_settings for_read fallback — flip 后仍读到旧配置
"""

import json
import pytest


# ── 修1: for_read 空文件/损坏判定 ─────────────────────────────────────────────

def test_for_read_json_empty_fallback(tmp_path):
    """new 存在但为 0 字节，应回退到 old"""
    from core.sandbox import for_read
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text('{"x": 1}', encoding="utf-8")
    new.write_bytes(b"")
    assert for_read(new, old) == old


def test_for_read_json_corrupt_fallback(tmp_path):
    """new 存在但 JSON 损坏，应回退到 old"""
    from core.sandbox import for_read
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text('{"x": 1}', encoding="utf-8")
    new.write_text("{corrupt!!!", encoding="utf-8")
    assert for_read(new, old) == old


def test_for_read_json_valid_returns_new(tmp_path):
    """new 存在且 JSON 正常，应返回 new"""
    from core.sandbox import for_read
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text('{"x": 1}', encoding="utf-8")
    new.write_text('{"x": 2}', encoding="utf-8")
    assert for_read(new, old) == new


def test_for_read_jsonl_empty_fallback(tmp_path):
    """new 为空 .jsonl，应回退到 old"""
    from core.sandbox import for_read
    old = tmp_path / "obs.jsonl"
    new = tmp_path / "obs_new.jsonl"
    old.write_text('{"text": "obs"}\n', encoding="utf-8")
    new.write_bytes(b"")
    assert for_read(new, old) == old


def test_for_read_jsonl_corrupt_fallback(tmp_path):
    """new 首行不是合法 JSON 的 .jsonl，应回退到 old"""
    from core.sandbox import for_read
    old = tmp_path / "obs.jsonl"
    new = tmp_path / "obs_new.jsonl"
    old.write_text('{"text": "obs"}\n', encoding="utf-8")
    new.write_text("not-valid-json\n", encoding="utf-8")
    assert for_read(new, old) == old


def test_for_read_jsonl_valid_returns_new(tmp_path):
    """new 为正常 .jsonl，应返回 new"""
    from core.sandbox import for_read
    old = tmp_path / "obs.jsonl"
    new = tmp_path / "obs_new.jsonl"
    old.write_text('{"text": "old"}\n', encoding="utf-8")
    new.write_text('{"text": "new"}\n', encoding="utf-8")
    assert for_read(new, old) == new


def test_for_read_no_new_returns_old(tmp_path):
    """new 不存在，应返回 old"""
    from core.sandbox import for_read
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text('{"x": 1}', encoding="utf-8")
    assert for_read(new, old) == old


# ── 修2: trait_state 走对称链路 ──────────────────────────────────────────────

def test_trait_state_reads_old_writes_new(tmp_path):
    """旧路径有窗口数据，新路径不存在时：应读旧窗口，合并后写到新路径，不碰旧路径"""
    from core.memory.trait_tracker import update_trait_state
    from core.sandbox import for_read

    old_path = tmp_path / "yexuan_inner" / "trait_state.json"
    new_path = tmp_path / "characters" / "yexuan" / "inner" / "trait_state.json"
    old_path.parent.mkdir(parents=True, exist_ok=True)
    new_path.parent.mkdir(parents=True, exist_ok=True)

    old_state = {
        "windows": [
            {"timestamp": "2026-01-01T00:00:00", "counts": {"trait_a": 3, "trait_b": 1}}
        ],
        "underrepresented": [],
    }
    old_path.write_text(json.dumps(old_state), encoding="utf-8")

    # new 不存在，for_read 回退到 old
    read_path = for_read(new_path, old_path)
    assert read_path == old_path

    new_counts = {"trait_a": 0, "trait_b": 5, "trait_c": 0}
    update_trait_state(new_counts, read_path, write_path=new_path)

    # 新路径已写入
    assert new_path.exists(), "新路径应被写入"
    result = json.loads(new_path.read_text(encoding="utf-8"))

    # 应有 2 个窗口：本轮 + 旧窗口
    assert len(result["windows"]) == 2, f"应有2个窗口，实际: {result['windows']}"
    # 旧窗口数据被保留
    old_window = result["windows"][1]
    assert old_window["counts"]["trait_a"] == 3

    # 旧路径内容不变
    old_on_disk = json.loads(old_path.read_text(encoding="utf-8"))
    assert old_on_disk == old_state, "旧路径不应被写入"


# ── 修3: dream_settings for_read fallback ─────────────────────────────────────

def test_dream_settings_fallback_to_legacy(tmp_path, monkeypatch):
    """v1 新路径不存在，legacy 旧路径有配置：load 应回退读旧配置而非返回默认值"""
    import core.sandbox as _sandbox
    import core.dream.dream_settings as ds

    paths = _sandbox.DataPaths(mode="test", test_session_id="pytest_unit")
    paths._base = tmp_path
    monkeypatch.setattr(_sandbox, "_instance", paths)

    uid = "123456"

    # 写入 legacy 路径：dreams/settings/{uid}.json
    old_path = tmp_path / "dreams" / "settings" / f"{uid}.json"
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_settings = {
        "enable_dream_lorebook": False,
        "memory_access": "full_snapshot",
        "boundary_level": "numbers_visible",
        "world_layer": "custom",
        "lucid_mode": "lucid_solo",
        "jailbreak_preset": "custom_preset",
    }
    old_path.write_text(json.dumps(old_settings), encoding="utf-8")

    # v1 新路径不存在：dreams/yexuan/settings/{uid}.json
    new_path = tmp_path / "dreams" / "yexuan" / "settings" / f"{uid}.json"
    assert not new_path.exists()

    loaded = ds.load(uid)
    assert loaded["memory_access"] == "full_snapshot", f"应读到旧配置，实际: {loaded}"
    assert loaded["enable_dream_lorebook"] is False
    assert loaded["boundary_level"] == "numbers_visible"

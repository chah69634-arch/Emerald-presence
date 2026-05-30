"""
V7 soak 可观测性验证

- fallback 命中时 hit_count/first_nonzero_at/recent_hits 均更新
- 正常命中（new 有效）时计数不变
- reset 后所有字段归零
"""

import json
import pytest


@pytest.fixture(autouse=True)
def reset_counters():
    """每个测试前后都 reset，避免模块级状态污染"""
    from core.sandbox import reset_fallback_hit_count
    reset_fallback_hit_count()
    yield
    reset_fallback_hit_count()


def test_fallback_hit_increments_stats(tmp_path):
    """新路径不存在 → hit_count +1，first_nonzero_at 有值，recent_hits 有记录"""
    from core.sandbox import for_read, get_fallback_stats

    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text('{"x": 1}', encoding="utf-8")
    # new 不存在 → fallback

    before = get_fallback_stats()
    assert before["hit_count"] == 0
    assert before["any_nonzero"] is False
    assert before["first_nonzero_at"] is None
    assert before["recent_hits"] == []

    result = for_read(new, old)
    assert result == old

    after = get_fallback_stats()
    assert after["hit_count"] == 1
    assert after["any_nonzero"] is True
    assert after["first_nonzero_at"] is not None
    assert len(after["recent_hits"]) == 1
    hit = after["recent_hits"][0]
    assert str(new) in hit["new"]
    assert str(old) in hit["old"]
    assert "T" in hit["ts"]  # ISO timestamp


def test_normal_read_no_increment(tmp_path):
    """新路径存在且有效 → 返回 new，计数不变"""
    from core.sandbox import for_read, get_fallback_stats

    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text('{"x": 1}', encoding="utf-8")
    new.write_text('{"x": 2}', encoding="utf-8")

    result = for_read(new, old)
    assert result == new

    stats = get_fallback_stats()
    assert stats["hit_count"] == 0
    assert stats["any_nonzero"] is False
    assert stats["first_nonzero_at"] is None


def test_reset_clears_all_fields(tmp_path):
    """命中后 reset → 全部归零"""
    from core.sandbox import for_read, get_fallback_stats, reset_fallback_hit_count

    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text('{"x": 1}', encoding="utf-8")

    for_read(new, old)
    assert get_fallback_stats()["hit_count"] == 1

    reset_fallback_hit_count()
    s = get_fallback_stats()
    assert s["hit_count"] == 0
    assert s["any_nonzero"] is False
    assert s["first_nonzero_at"] is None
    assert s["recent_hits"] == []


def test_recent_hits_capped(tmp_path):
    """recent_hits 最多保留 _FALLBACK_RECENT_MAX 条"""
    from core.sandbox import for_read, get_fallback_stats, _FALLBACK_RECENT_MAX

    old = tmp_path / "old.json"
    old.write_text('{"x": 1}', encoding="utf-8")

    for i in range(_FALLBACK_RECENT_MAX + 5):
        new = tmp_path / f"new_{i}.json"
        for_read(new, old)

    s = get_fallback_stats()
    assert s["hit_count"] == _FALLBACK_RECENT_MAX + 5
    assert len(s["recent_hits"]) == _FALLBACK_RECENT_MAX


def test_diary_dir_is_dir_no_fallback(tmp_path):
    """新 diary 目录存在时，is_dir() 逻辑不增加 fallback_hit_count，且能读到日记内容。
    回归：旧的 for_read(new_dir, old_dir) 在 Windows 上对目录调用 read_bytes() 会抛
    PermissionError，触发假阳性 fallback；改为 is_dir() 后不再命中。
    """
    from core.sandbox import for_read, get_fallback_stats

    new_dir = tmp_path / "new_diary"
    old_dir = tmp_path / "old_diary"
    new_dir.mkdir()
    old_dir.mkdir()

    yesterday = "2026-05-29"
    (new_dir / f"{yesterday}.md").write_text("新路径日记内容", encoding="utf-8")
    (old_dir / f"{yesterday}.md").write_text("旧路径日记内容", encoding="utf-8")

    before = get_fallback_stats()["hit_count"]

    # 修复后的逻辑：is_dir() 检查，不经过 for_read
    diary_dir = new_dir if new_dir.is_dir() else old_dir

    assert diary_dir == new_dir, "新目录存在时应选用新路径"
    assert get_fallback_stats()["hit_count"] == before, "is_dir() 路径不应增加 fallback 计数"
    assert (diary_dir / f"{yesterday}.md").read_text(encoding="utf-8") == "新路径日记内容"

    # 对照：for_read(directory, ...) 会命中 fallback（Windows: PermissionError；Linux: IsADirectoryError）
    for_read(new_dir, old_dir)
    assert get_fallback_stats()["hit_count"] == before + 1, "for_read 对目录路径应触发 fallback（旧行为）"

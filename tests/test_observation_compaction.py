"""
tests/test_observation_compaction.py
compact_observations 行为验证：
  - 条数 ≤ max_raw 时不压缩
  - 超出时精确去重、weight 累加、唯一 text 全量保留
  - 压缩后文件首行仍是合法 JSON（for_read 验证用）
  - 不存在的文件返回 0
"""
import json
from pathlib import Path

import pytest

from core.memory.observation_compaction import compact_observations


def _write_obs(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
        encoding="utf-8",
    )


def _read_obs(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ── 基础功能 ──────────────────────────────────────────────────────────────────

def test_no_compaction_when_under_limit(tmp_path):
    p = tmp_path / "observations.jsonl"
    entries = [{"text": f"obs{i}", "weight": 1} for i in range(5)]
    _write_obs(p, entries)
    result = compact_observations(p, max_raw=10)
    assert result == 0
    assert _read_obs(p) == entries  # 文件未修改


def test_no_compaction_at_exact_limit(tmp_path):
    p = tmp_path / "observations.jsonl"
    entries = [{"text": f"obs{i}", "weight": 1} for i in range(10)]
    _write_obs(p, entries)
    result = compact_observations(p, max_raw=10)
    assert result == 0


def test_compaction_removes_duplicates(tmp_path):
    """100 条中有 50 条文本重复 → compact 消除重复，唯一 text 全部保留。"""
    p = tmp_path / "observations.jsonl"
    # 50 条唯一 text + 50 条重复（前 50 的副本）
    unique = [{"text": f"unique_{i}", "weight": 1, "inserted_at": f"2026-01-{i+1:02d}T00:00:00"} for i in range(50)]
    dups = [{"text": f"unique_{i}", "weight": 1, "inserted_at": f"2025-01-{i+1:02d}T00:00:00"} for i in range(50)]
    _write_obs(p, unique + dups)  # 100 total

    eliminated = compact_observations(p, max_raw=60)

    out = _read_obs(p)
    texts = [e["text"] for e in out]
    # 50 unique texts 全保留
    for i in range(50):
        assert f"unique_{i}" in texts, f"unique_{i} 被错误删除"
    # 重复条目被合并 → 条数 < 100
    assert len(out) < 100
    assert eliminated > 0


def test_compaction_weight_accumulation(tmp_path):
    """重复条目的 weight 应累加。"""
    p = tmp_path / "observations.jsonl"
    entries = [{"text": "same_obs", "weight": 1, "inserted_at": f"2025-0{i+1}-01T00:00:00"} for i in range(5)]
    # 加 3 条唯一的填满 max_raw
    for j in range(3):
        entries.append({"text": f"other_{j}", "weight": 1, "inserted_at": "2026-01-01T00:00:00"})
    _write_obs(p, entries)

    compact_observations(p, max_raw=3)

    out = _read_obs(p)
    same_entries = [e for e in out if e.get("text") == "same_obs"]
    assert len(same_entries) == 1, "重复 text 应合并为一条"
    assert same_entries[0]["weight"] >= 2, "合并后 weight 应累加"


def test_all_unique_texts_preserved(tmp_path):
    """超出 max_raw 后，旧条目中所有唯一 text 不丢失。"""
    p = tmp_path / "observations.jsonl"
    entries = [
        {"text": f"obs_{i}", "weight": 1, "inserted_at": f"2025-01-{(i%28)+1:02d}T00:00:00"}
        for i in range(150)
    ]
    _write_obs(p, entries)

    compact_observations(p, max_raw=100)

    out = _read_obs(p)
    texts_out = {e["text"] for e in out}
    for i in range(150):
        assert f"obs_{i}" in texts_out, f"obs_{i} 唯一 text 被丢弃"


def test_first_line_valid_json_after_compaction(tmp_path):
    """压缩后文件首行必须是合法 JSON（供 for_read 验证用）。"""
    p = tmp_path / "observations.jsonl"
    entries = [{"text": f"obs{i}", "weight": 1, "inserted_at": f"2025-01-01T00:00:0{i}"} for i in range(10)]
    dups = [{"text": f"obs{i}", "weight": 1, "inserted_at": "2024-01-01T00:00:00"} for i in range(10)]
    _write_obs(p, entries + dups)

    compact_observations(p, max_raw=5)

    first_line = p.read_text(encoding="utf-8").splitlines()[0]
    parsed = json.loads(first_line)  # 不应抛异常
    assert "text" in parsed


def test_nonexistent_file_returns_zero(tmp_path):
    result = compact_observations(tmp_path / "nonexistent.jsonl")
    assert result == 0


def test_empty_file_returns_zero(tmp_path):
    p = tmp_path / "observations.jsonl"
    p.write_text("", encoding="utf-8")
    result = compact_observations(p, max_raw=5)
    assert result == 0

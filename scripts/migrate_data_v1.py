#!/usr/bin/env python3
"""
scripts/migrate_data_v1.py
S8 离线迁移：把历史旧布局文件搬到新布局，可回滚、可验证，绝不在主流程里搬。

从项目根目录运行：
  python scripts/migrate_data_v1.py --dry-run
  python scripts/migrate_data_v1.py --backup --copy
  python scripts/migrate_data_v1.py --verify
  python scripts/migrate_data_v1.py --verify --commit

完整迁移 Runbook（V6）：
  0. [独立冷备，脚本外手动执行]
       cp -r data/ data_cold_$(date +%Y%m%d_%H%M%S)/
     或 Windows：
       xcopy data data_cold_%date:~0,10% /E /I /H /Y
     这是 data/ 的手动快照，与脚本内 --backup 分开保存。

  1. --dry-run          只打印 old→new 计划，不动盘
  2. --backup --copy    打 tar 备份后非破坏式复制 old→new（保留 old）
                        copy 按数据类别执行不同语义（见下）
  3. --verify           逐文件比对 count/checksum
  4. --semantic-snapshot  迁移前后语义快照，断言后 ⊇ 前
  5. --verify --commit  verify 全通过后删 old

copy 语义说明：
  类别A 累积型快照（identity/profile/episodic/mid_term/memory_index/
        history/reminders/fixation_state/garden/char_growth/inner_diary 等）：
        新文件不存在 → 直接复制；
        新文件已存在 → 按各类型自身 load+合并取并集后写入，
                       不可合并时停下报告该 uid+路径，不静默 skip。
  类别B append 日志（event_log）：merge-by-line，按 turn_id 去重，
        不处理 .gz 归档（只处理 YYYY-MM-DD.md）。
  类别C 全量重建型（observations.jsonl）：简单 copy（或 skip），
        因为 extract_observations.py 是全量 "w" 重建，下次重建即覆盖。
  类别D dream（archive/summaries/impressions/tmp/state/settings）：
        简单 copy/copytree，不在现实读取层加 dream fallback。

勿在 bot 进程运行时执行本脚本。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

os.chdir(_ROOT)

import core.data_paths as _sb
from core.data_paths import DataPaths, safe_user_id

_DATA_ROOT = _ROOT / "data"
_BACKUP_ROOT = _ROOT / "data_backup"
_DEFAULT_CHAR = "yexuan"

_DATE_MD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
_TURN_ID_RE = re.compile(r"turn_id:(\S+)")


# ── 布局切换 ──────────────────────────────────────────────────────────────────

@contextmanager
def _layout(ci: str, re_: str, dr: str):
    """临时覆盖 core.sandbox 中的模块级布局开关，退出时自动还原。"""
    saved = (_sb._LAYOUT_CHARACTER_INNER, _sb._LAYOUT_REALITY, _sb._LAYOUT_DREAM)
    _sb._LAYOUT_CHARACTER_INNER = ci
    _sb._LAYOUT_REALITY = re_
    _sb._LAYOUT_DREAM = dr
    try:
        yield
    finally:
        _sb._LAYOUT_CHARACTER_INNER, _sb._LAYOUT_REALITY, _sb._LAYOUT_DREAM = saved


def _dp() -> DataPaths:
    return DataPaths(mode="production")


def _abs(p: Path) -> Path:
    """DataPaths 返回的相对路径 → 以 _ROOT 为基准的绝对路径。"""
    return _ROOT / p


# ── 迁移计划 ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Entry:
    old: Path    # 绝对路径
    new: Path    # 绝对路径
    is_dir: bool = False
    # A=累积型快照  B=append日志  C=全量重建  D=dream
    category: str = "A"


def _collect_uids() -> list[str]:
    """扫描旧布局 per-user 平铺目录，取并集，返回排序后的 uid 列表。"""
    uids: set[str] = set()
    scan_dirs = [
        "history", "episodic_memory", "mid_term", "profiles",
        "user_identity", "reminders", "diary_context",
        "event_log", "fixation_state", "memory_index",
    ]
    for dname in scan_dirs:
        d = _DATA_ROOT / dname
        if not d.exists():
            continue
        for entry in d.iterdir():
            stem = entry.stem if entry.is_file() else entry.name
            if stem.endswith(".yaml"):
                stem = stem[:-5]
            try:
                uids.add(safe_user_id(stem))
            except ValueError:
                pass
    return sorted(uids)


def build_plan(char_id: str = _DEFAULT_CHAR) -> list[Entry]:
    """构建迁移计划，返回 old 已存在的 Entry 列表。"""
    entries: list[Entry] = []

    # ── character_inner: legacy → v1 ─────────────────────────────────────────
    with _layout("legacy", "v1", "v1"):
        dp_ci_old = _dp()
        ci_old: dict[str, tuple[Path, bool]] = {
            "mood_state":         (_abs(dp_ci_old.mood_state(char_id=char_id)),                       False),
            "activity_state":     (_abs(dp_ci_old.activity_state()),                   False),
            "trait_state":        (_abs(dp_ci_old.trait_state()),                      False),
            "author_note_state":  (_abs(dp_ci_old.author_note_state()),                False),
            "presence":           (_abs(dp_ci_old.presence()),                         False),
            "observations":       (_abs(dp_ci_old.observations(char_id=char_id)),                     False),
            "pet_file":           (_abs(dp_ci_old.pet_file()),                         False),
            "activity_snapshot":  (_abs(dp_ci_old.activity_snapshot(char_id=char_id)),                False),
            "garden":             (_abs(dp_ci_old.garden(char_id=char_id)),            True),
            "character_growth":   (_abs(dp_ci_old.character_growth(char_id=char_id)), True),
            "yexuan_inner_diary": (_abs(dp_ci_old.yexuan_inner_diary(char_id=char_id)), True),
        }

    dp_ci_new = _dp()
    ci_new: dict[str, tuple[Path, bool]] = {
        "mood_state":         (_abs(dp_ci_new.mood_state(char_id=char_id)),                       False),
        "activity_state":     (_abs(dp_ci_new.activity_state()),                   False),
        "trait_state":        (_abs(dp_ci_new.trait_state()),                      False),
        "author_note_state":  (_abs(dp_ci_new.author_note_state()),                False),
        "presence":           (_abs(dp_ci_new.presence()),                         False),
        "observations":       (_abs(dp_ci_new.observations(char_id=char_id)),                     False),
        "pet_file":           (_abs(dp_ci_new.pet_file()),                         False),
        "activity_snapshot":  (_abs(dp_ci_new.activity_snapshot(char_id=char_id)),                False),
        "garden":             (_abs(dp_ci_new.garden(char_id=char_id)),            True),
        "character_growth":   (_abs(dp_ci_new.character_growth(char_id=char_id)), True),
        "yexuan_inner_diary": (_abs(dp_ci_new.yexuan_inner_diary(char_id=char_id)), True),
    }

    # observations → C（全量重建型）；其余 → A
    CI_CATEGORY: dict[str, str] = {"observations": "C"}

    for key in ci_old:
        old_p, is_dir = ci_old[key]
        new_p, _ = ci_new[key]
        if old_p != new_p and old_p.exists():
            cat = CI_CATEGORY.get(key, "A")
            entries.append(Entry(old_p, new_p, is_dir, category=cat))

    # ── dream: legacy → v1 ───────────────────────────────────────────────────
    with _layout("v1", "v1", "legacy"):
        dp_dr_old = _dp()
        dr_old: dict[str, Path] = {
            "archive":     _abs(dp_dr_old.dreams_archive_dir(char_id=char_id)),
            "summaries":   _abs(dp_dr_old.dreams_summaries_dir(char_id=char_id)),
            "impressions": _abs(dp_dr_old.dreams_impressions_dir(char_id=char_id)),
            "tmp":         _abs(dp_dr_old.dreams_tmp_dir(char_id=char_id)),
            "state":       _abs(dp_dr_old._p("dreams", "state")),
            "settings":    _abs(dp_dr_old._p("dreams", "settings")),
        }

    dp_dr_new = _dp()
    dr_new: dict[str, Path] = {
        "archive":     _abs(dp_dr_new.dreams_archive_dir(char_id=char_id)),
        "summaries":   _abs(dp_dr_new.dreams_summaries_dir(char_id=char_id)),
        "impressions": _abs(dp_dr_new.dreams_impressions_dir(char_id=char_id)),
        "tmp":         _abs(dp_dr_new.dreams_tmp_dir(char_id=char_id)),
        "state":       _abs(dp_dr_new._p("dreams", char_id, "state")),
        "settings":    _abs(dp_dr_new._p("dreams", char_id, "settings")),
    }

    for key in dr_old:
        old_p = dr_old[key]
        new_p = dr_new[key]
        if old_p != new_p and old_p.exists():
            entries.append(Entry(old_p, new_p, is_dir=True, category="D"))

    # ── reality: per_user → per_char_user ─────────────────────────────────────
    PER_USER_FILES: list[tuple[str, str, str]] = [
        ("history",         "{uid}.json",     "history.json"),
        ("episodic_memory", "{uid}.json",     "episodic.json"),
        ("memory_index",    "{uid}.json",     "memory_index.json"),
        ("mid_term",        "{uid}.json",     "mid_term.json"),
        ("profiles",        "{uid}.json",     "profile.json"),
        ("user_identity",   "{uid}.yaml",     "identity.yaml"),
        ("user_identity",   "{uid}.yaml.bak", "identity.yaml.bak"),
        ("reminders",       "{uid}.json",     "reminders.json"),
        ("diary_context",   "{uid}.txt",      "diary_context.txt"),
        ("fixation_state",  "{uid}.json",     "fixation_state.json"),
    ]
    PER_USER_DIRS: list[tuple[str, str, str]] = [
        ("event_log", "{uid}", "event_log"),
    ]

    dp_re = _dp()
    for uid in _collect_uids():
        mem_root = _abs(dp_re.user_memory_root(uid, char_id=char_id))
        for legacy_dir, old_tpl, new_name in PER_USER_FILES:
            old_f = _DATA_ROOT / legacy_dir / old_tpl.format(uid=uid)
            if old_f.exists():
                entries.append(Entry(old_f, mem_root / new_name, is_dir=False, category="A"))
        for legacy_dir, old_tpl, new_name in PER_USER_DIRS:
            old_d = _DATA_ROOT / legacy_dir / old_tpl.format(uid=uid)
            if old_d.exists():
                entries.append(Entry(old_d, mem_root / new_name, is_dir=True, category="B"))

    return entries


# ── 合并辅助函数 ──────────────────────────────────────────────────────────────

def _union_arrays_by_id(old_items: list, new_items: list, id_field: str) -> list:
    """两个 JSON 数组按 id_field 取并集，new 项优先（相同 id 时保留 new 版本）。"""
    seen: dict[Any, int] = {}  # id → index in result
    result: list = list(new_items)
    for item in new_items:
        key = item.get(id_field)
        if key is not None:
            seen[key] = 1
    for item in old_items:
        key = item.get(id_field)
        if key is None or key not in seen:
            result.append(item)
            if key is not None:
                seen[key] = 1
    return result


def _union_memory_index(old_idx: dict, new_idx: dict) -> dict:
    """memory_index 格式 {tag: [ep_id, ...]}：两者并集。"""
    merged = {k: list(v) for k, v in new_idx.items()}  # deep-copy lists to avoid mutation
    for tag, ep_ids in old_idx.items():
        if tag not in merged:
            merged[tag] = list(ep_ids)
        else:
            existing = set(merged[tag])
            for eid in ep_ids:
                if eid not in existing:
                    merged[tag].append(eid)
                    existing.add(eid)
    return merged


def _merge_profile(old_data: dict, new_data: dict) -> dict:
    """profile.json 合并：new 优先，important_facts 取并集。"""
    merged = dict(new_data)
    old_facts = old_data.get("important_facts") or []
    new_facts = new_data.get("important_facts") or []
    seen_facts = set(new_facts)
    extra_facts = [f for f in old_facts if f not in seen_facts]
    merged["important_facts"] = list(new_facts) + extra_facts
    # 其他字段：new 为 None/缺失时用 old 补
    for key, val in old_data.items():
        if key == "important_facts":
            continue
        if val is not None and (key not in merged or merged[key] is None):
            merged[key] = val
    return merged


def _split_event_log_blocks(content: str) -> list[str]:
    """按 '\\n---\\n' 分割事件日志块，返回非空块列表。"""
    blocks = re.split(r"\n---\n", content)
    return [b.strip() for b in blocks if b.strip()]


def _block_key(block: str) -> str:
    """提取 turn_id 作为去重 key；无 turn_id 则用完整 block 内容。"""
    m = _TURN_ID_RE.search(block)
    return m.group(1) if m else block


def _merge_event_log_day(old_content: str, new_content: str) -> str:
    """合并同一天的两个事件日志文件内容，按 turn_id 去重。"""
    new_blocks = _split_event_log_blocks(new_content)
    old_blocks = _split_event_log_blocks(old_content)

    new_keys: set[str] = {_block_key(b) for b in new_blocks}
    extra = [b for b in old_blocks if _block_key(b) not in new_keys]

    if not extra:
        return new_content
    all_blocks = new_blocks + extra
    return "\n\n---\n\n".join(all_blocks) + "\n\n---\n"


# ── copy 分发 ─────────────────────────────────────────────────────────────────

def _copy_entry_d(entry: Entry) -> str:
    """类别D dream：简单 copy/copytree。new 已存在时，补入 old 中新增的文件。"""
    if not entry.new.exists():
        entry.new.parent.mkdir(parents=True, exist_ok=True)
        if entry.is_dir:
            shutil.copytree(str(entry.old), str(entry.new))
        else:
            shutil.copy2(str(entry.old), str(entry.new))
        return "copied"
    if entry.is_dir:
        added = 0
        for old_f in _list_files(entry.old):
            rel = old_f.relative_to(entry.old)
            new_f = entry.new / rel
            if not new_f.exists():
                new_f.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(old_f), str(new_f))
                added += 1
        return f"dir_supplemented({added})" if added else "skip_new_exists"
    return "skip_new_exists"


def _copy_entry_c(entry: Entry) -> str:
    """类别C 全量重建型（observations.jsonl）：简单 copy，注明"重建型"。"""
    if not entry.new.exists():
        entry.new.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(entry.old), str(entry.new))
        return "copied(rebuild-type)"
    return "skip_new_exists(rebuild-type)"


def _copy_entry_b(entry: Entry) -> str:
    """类别B event_log 目录：merge-by-line，按 turn_id 去重，只处理 YYYY-MM-DD.md。"""
    if not entry.is_dir:
        return "ERROR: category B must be a dir"
    entry.new.mkdir(parents=True, exist_ok=True)
    copied = merged = 0
    for old_f in sorted(entry.old.iterdir()):
        if not old_f.is_file():
            continue
        if not _DATE_MD_RE.match(old_f.name):
            continue  # skip full_log.md and any .gz archives
        new_f = entry.new / old_f.name
        if not new_f.exists():
            shutil.copy2(str(old_f), str(new_f))
            copied += 1
        else:
            old_txt = old_f.read_text(encoding="utf-8", errors="replace")
            new_txt = new_f.read_text(encoding="utf-8", errors="replace")
            result = _merge_event_log_day(old_txt, new_txt)
            if result != new_txt:
                new_f.write_text(result, encoding="utf-8")
                merged += 1
    return f"event_log copied={copied} merged={merged}"


def _copy_entry_a_file(entry: Entry) -> str:
    """类别A 单文件：new 不存在时复制；存在时按文件名做类型感知合并。"""
    if not entry.new.exists():
        entry.new.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(entry.old), str(entry.new))
        return "copied"

    # new 已存在 —— 按文件名路由合并
    name = entry.new.name
    ext = entry.new.suffix.lower()

    # 状态快照型：new 更新，保持不动（但若无法证明 new > old 则应 merge；
    # 此类文件 new 是 bot 在 v1 下写入的最新状态，旧文件的"当前值"已过期）
    STATE_ONLY = {
        "mood_state.json", "activity_state.json", "author_note_state.json",
        "presence.json", "pet.json", "activity_snapshot.json",
        "trait_state.json", "diary_context.txt", "identity.yaml.bak",
    }
    if name in STATE_ONLY:
        return "skip_new_is_current_state"

    # fixation_state.json：状态快照，new 优先
    if name == "fixation_state.json":
        return "skip_new_is_current_state"

    try:
        if ext == ".json":
            return _merge_json_a(entry, name)
        elif ext == ".yaml" and not name.endswith(".bak"):
            return _merge_yaml_a(entry)
        else:
            return "skip_new_exists"
    except Exception as exc:
        return f"ERROR: {exc}"


def _merge_json_a(entry: Entry, name: str) -> str:
    """JSON 类别A 合并，返回 action 字符串；异常往外抛（调用方捕获为 ERROR）。"""
    old_data = json.loads(entry.old.read_text(encoding="utf-8"))
    new_data = json.loads(entry.new.read_text(encoding="utf-8"))

    if name == "episodic.json":
        if not isinstance(old_data, list) or not isinstance(new_data, list):
            raise ValueError("episodic.json 结构不兼容（非 list）")
        merged = _union_arrays_by_id(old_data, new_data, "id")
        action = f"merged_episodic old={len(old_data)} new={len(new_data)} result={len(merged)}"
    elif name == "history.json":
        if not isinstance(old_data, list) or not isinstance(new_data, list):
            raise ValueError("history.json 结构不兼容（非 list）")
        merged = _union_arrays_by_id(old_data, new_data, "_turn_id")
        action = f"merged_history old={len(old_data)} new={len(new_data)} result={len(merged)}"
    elif name == "reminders.json":
        if not isinstance(old_data, list) or not isinstance(new_data, list):
            raise ValueError("reminders.json 结构不兼容（非 list）")
        merged = _union_arrays_by_id(old_data, new_data, "id")
        action = f"merged_reminders old={len(old_data)} new={len(new_data)} result={len(merged)}"
    elif name == "mid_term.json":
        if not isinstance(old_data, dict) or not isinstance(new_data, dict):
            raise ValueError("mid_term.json 结构不兼容（非 dict）")
        old_evts = old_data.get("events") or []
        new_evts = new_data.get("events") or []
        merged_evts = _union_arrays_by_id(old_evts, new_evts, "mid_id")
        merged = dict(new_data)
        merged["events"] = merged_evts
        action = f"merged_mid_term old={len(old_evts)} new={len(new_evts)} result={len(merged_evts)}"
    elif name == "memory_index.json":
        if not isinstance(old_data, dict) or not isinstance(new_data, dict):
            raise ValueError("memory_index.json 结构不兼容（非 dict）")
        merged = _union_memory_index(old_data, new_data)
        action = f"merged_index tags_old={len(old_data)} tags_new={len(new_data)} tags_result={len(merged)}"
    elif name == "profile.json":
        if not isinstance(old_data, dict) or not isinstance(new_data, dict):
            raise ValueError("profile.json 结构不兼容（非 dict）")
        merged = _merge_profile(old_data, new_data)
        old_fc = len((old_data.get("important_facts") or []))
        new_fc = len((new_data.get("important_facts") or []))
        res_fc = len((merged.get("important_facts") or []))
        action = f"merged_profile facts old={old_fc} new={new_fc} result={res_fc}"
    else:
        # 其余 JSON（如 fixation_state 已被过滤，不会到这里）：new 优先，old 补充缺失 key
        if isinstance(old_data, dict) and isinstance(new_data, dict):
            merged = dict(old_data)
            merged.update(new_data)
            action = "merged_dict_union"
        else:
            return "skip_new_exists(unknown_json_type)"

    # 若合并结果与 new 完全相同，不重写
    if merged == new_data:
        return f"skip_identical ({action})"

    entry.new.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return action


def _merge_yaml_a(entry: Entry) -> str:
    """YAML 类别A 合并（identity.yaml）：per-key 取并集，new key 优先。"""
    import yaml
    old_data = yaml.safe_load(entry.old.read_text(encoding="utf-8")) or {}
    new_data = yaml.safe_load(entry.new.read_text(encoding="utf-8")) or {}

    if not isinstance(old_data, dict) or not isinstance(new_data, dict):
        raise ValueError("identity.yaml 结构不兼容（非 dict）")

    # new 优先，但把 old 里 new 没有的维度补进去
    merged = dict(old_data)
    merged.update(new_data)

    if merged == new_data:
        return "skip_identical(identity_yaml)"

    text = __import__("yaml").dump(
        merged, allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    entry.new.write_text(text, encoding="utf-8")
    return f"merged_identity old_dims={len(old_data)} new_dims={len(new_data)} result={len(merged)}"


def _copy_entry_a_dir(entry: Entry) -> str:
    """类别A 目录（garden/character_growth/inner_diary）：
    new 不存在 → copytree；
    new 已存在 → 把 old 中 new 缺失的文件逐一补入（不覆盖 new 已有文件）。
    """
    if not entry.new.exists():
        entry.new.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(entry.old), str(entry.new))
        return "copytree"
    added = 0
    for old_f in _list_files(entry.old):
        rel = old_f.relative_to(entry.old)
        new_f = entry.new / rel
        if not new_f.exists():
            new_f.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(old_f), str(new_f))
            added += 1
    return f"dir_supplemented({added})" if added else "skip_all_present"


def _copy_entry_a(entry: Entry) -> str:
    if entry.is_dir:
        return _copy_entry_a_dir(entry)
    return _copy_entry_a_file(entry)


# ── 操作实现 ──────────────────────────────────────────────────────────────────

def do_backup() -> None:
    if not _DATA_ROOT.exists():
        print("[backup] data/ 不存在，跳过")
        return
    _BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tar_path = _BACKUP_ROOT / f"{ts}.tar"
    print(f"[backup] 打包 data/ → {tar_path} ...")
    skipped = 0

    def _filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
        nonlocal skipped
        try:
            p = _ROOT / tarinfo.name
            if p.exists():
                p.stat()
        except (PermissionError, OSError):
            skipped += 1
            return None
        return tarinfo

    with tarfile.open(tar_path, "w") as tf:
        try:
            tf.add(_DATA_ROOT, arcname="data", filter=_filter)
        except (PermissionError, OSError) as exc:
            print(f"[backup] 警告：打包时跳过不可访问路径：{exc}")
    size_mb = tar_path.stat().st_size / 1024 / 1024
    if skipped:
        print(f"[backup] 完成（{size_mb:.1f} MB，跳过 {skipped} 个不可访问项）")
    else:
        print(f"[backup] 完成（{size_mb:.1f} MB）")


def do_dry_run(entries: list[Entry]) -> None:
    if not entries:
        print("[dry-run] 无需迁移")
        return
    for e in entries:
        tag = f"[{e.category}]{'DIR ' if e.is_dir else 'FILE'}"
        old_rel = e.old.relative_to(_ROOT)
        new_rel = e.new.relative_to(_ROOT)
        print(f"[dry-run] {tag}  {old_rel}  →  {new_rel}")
    print(f"[dry-run] 合计 {len(entries)} 条")


def do_copy(entries: list[Entry]) -> None:
    """按类别分发执行复制/合并，记录 ERROR 条目并最终汇报。"""
    errors: list[str] = []
    counts: dict[str, int] = {}

    for e in entries:
        if not e.old.exists():
            print(f"[copy] SKIP（源已消失）: {e.old.relative_to(_ROOT)}")
            continue

        if e.category == "D":
            action = _copy_entry_d(e)
        elif e.category == "C":
            action = _copy_entry_c(e)
        elif e.category == "B":
            action = _copy_entry_b(e)
        else:  # A
            action = _copy_entry_a(e)

        old_rel = str(e.old.relative_to(_ROOT))
        if action.startswith("ERROR"):
            msg = f"[copy] ERROR [{e.category}] {old_rel}: {action}"
            print(msg, file=sys.stderr)
            errors.append(msg)
        else:
            print(f"[copy] [{e.category}] {old_rel} → {action}")

        bucket = action.split("(")[0].split(" ")[0]
        counts[bucket] = counts.get(bucket, 0) + 1

    print(f"[copy] 完成 {len(entries)} 条：{counts}")
    if errors:
        print(f"[copy] !! {len(errors)} 条 ERROR，请检查后再执行 --commit !!",
              file=sys.stderr)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _list_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def do_verify(entries: list[Entry]) -> list[str]:
    """逐文件比对 count/checksum，返回不一致描述列表（空 = 全通过）。"""
    mismatches: list[str] = []
    total_files = 0

    for e in entries:
        if not e.new.exists():
            mismatches.append(f"MISSING new: {e.new.relative_to(_ROOT)}")
            continue
        if not e.old.exists():
            continue

        if e.is_dir:
            old_files = {p.relative_to(e.old): p for p in _list_files(e.old)}
            new_files = {p.relative_to(e.new): p for p in _list_files(e.new)}
            total_files += len(old_files)
            for rel in sorted(old_files):
                if e.category == "B" and not _DATE_MD_RE.match(rel.name):
                    continue  # B 类只校验 YYYY-MM-DD.md
                if rel not in new_files:
                    mismatches.append(
                        f"MISSING in new dir {e.new.relative_to(_ROOT)}: {rel}"
                    )
                elif e.category not in ("B",):
                    # B 类 merge 后 checksum 必然不同，不做 checksum 校验
                    if _sha256(old_files[rel]) != _sha256(new_files[rel]):
                        mismatches.append(
                            f"CHECKSUM MISMATCH: {(e.new / rel).relative_to(_ROOT)}"
                        )
        else:
            total_files += 1
            if e.category not in ("A",) or e.new.name not in (
                "episodic.json", "history.json", "reminders.json",
                "mid_term.json", "memory_index.json", "profile.json",
                "identity.yaml",
            ):
                if _sha256(e.old) != _sha256(e.new):
                    mismatches.append(
                        f"CHECKSUM MISMATCH: {e.old.relative_to(_ROOT)}"
                    )

    if mismatches:
        print(f"[verify] FAIL — {len(mismatches)} 处不一致：")
        for m in mismatches:
            print(f"  {m}")
    else:
        print(f"[verify] OK — {len(entries)} 条，{total_files} 个文件，全部匹配")
    return mismatches


def do_commit(entries: list[Entry]) -> None:
    """删除旧路径（仅在 verify 全通过后调用）。"""
    removed = 0
    for e in entries:
        if not e.old.exists():
            print(f"[commit] SKIP（已消失）: {e.old.relative_to(_ROOT)}")
            continue
        if e.is_dir:
            shutil.rmtree(str(e.old))
        else:
            e.old.unlink()
        removed += 1
    print(f"[commit] 完成（删除 {removed}/{len(entries)} 条旧路径）")


# ── 语义快照与校验 ────────────────────────────────────────────────────────────

def _read_json_safe(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_yaml_safe(path: Path) -> Any:
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _event_log_30d_blocks(log_dir: Path) -> int:
    """计算该 event_log 目录最近 30 天的 MD 块数（按 '---' 分隔）。"""
    if not log_dir.exists():
        return 0
    cutoff = datetime.now() - timedelta(days=30)
    total = 0
    for f in sorted(log_dir.iterdir()):
        if not f.is_file() or not _DATE_MD_RE.match(f.name):
            continue
        try:
            file_date = datetime.strptime(f.name[:-3], "%Y-%m-%d")
        except ValueError:
            continue
        if file_date < cutoff:
            continue
        content = f.read_text(encoding="utf-8", errors="replace")
        # count '---' separator lines as proxy for blocks
        total += content.count("\n---\n") + (1 if content.strip() else 0)
    return total


def _uid_snap(uid: str, char_id: str, new_only: bool) -> dict:
    """取单个 uid 的语义快照。new_only=True 时只读新路径（post-migration 校验用）。"""
    dp = DataPaths(mode="production")
    mem_root = _abs(dp.user_memory_root(uid, char_id=char_id))

    def _pick(new_rel: str, old_dir: str, old_fname: str) -> Path:
        new_p = mem_root / new_rel
        if new_only:
            return new_p
        old_p = _DATA_ROOT / old_dir / old_fname
        return new_p if new_p.exists() else old_p

    snap: dict[str, Any] = {"uid": uid}

    # identity
    id_path = _pick("identity.yaml", "user_identity", f"{uid}.yaml")
    id_data = _read_yaml_safe(id_path) or {}
    snap["identity_dims"] = len(id_data) if isinstance(id_data, dict) else 0

    # profile
    prof_path = _pick("profile.json", "profiles", f"{uid}.json")
    prof_data = _read_json_safe(prof_path) or {}
    snap["profile_name"] = prof_data.get("name") if isinstance(prof_data, dict) else None
    snap["profile_facts"] = len(prof_data.get("important_facts") or []) \
        if isinstance(prof_data, dict) else 0

    # episodic
    ep_path = _pick("episodic.json", "episodic_memory", f"{uid}.json")
    ep_data = _read_json_safe(ep_path)
    snap["episodic_count"] = len(ep_data) if isinstance(ep_data, list) else 0

    # mid_term
    mt_path = _pick("mid_term.json", "mid_term", f"{uid}.json")
    mt_data = _read_json_safe(mt_path)
    snap["mid_term_count"] = len((mt_data or {}).get("events") or []) \
        if isinstance(mt_data, dict) else 0

    # event_log 近 30 天块数
    new_el = mem_root / "event_log"
    old_el = _DATA_ROOT / "event_log" / uid
    el_dir = new_el if (new_only or new_el.exists()) else old_el
    snap["event_log_30d_blocks"] = _event_log_30d_blocks(el_dir)

    return snap


def do_semantic_snapshot(char_id: str, uids: list[str], new_only: bool = False) -> dict:
    """为所有 uid 生成语义快照，返回 {uid: snap_dict}。"""
    label = "post(new-only)" if new_only else "pre(with-fallback)"
    print(f"[semantic-snapshot] 开始 {label}，共 {len(uids)} 个 uid")
    result: dict[str, dict] = {}
    for uid in uids:
        snap = _uid_snap(uid, char_id, new_only)
        result[uid] = snap
        print(f"  {uid}: identity_dims={snap['identity_dims']}"
              f" episodic={snap['episodic_count']}"
              f" mid_term={snap['mid_term_count']}"
              f" el_30d={snap['event_log_30d_blocks']}"
              f" profile_facts={snap['profile_facts']}")
    return result


def do_semantic_verify(pre: dict, post: dict) -> list[str]:
    """断言 post ⊇ pre：计数不减、关键字段不丢。返回违规列表（空 = 全通过）。"""
    violations: list[str] = []
    count_fields = ["identity_dims", "episodic_count", "mid_term_count",
                    "event_log_30d_blocks", "profile_facts"]

    for uid, pre_snap in pre.items():
        post_snap = post.get(uid, {})
        for fld in count_fields:
            pre_val = pre_snap.get(fld, 0)
            post_val = post_snap.get(fld, 0)
            if post_val < pre_val:
                violations.append(
                    f"uid={uid} {fld}: pre={pre_val} > post={post_val} [REGRESSION]"
                )
        # profile_name 不应消失
        pre_name = pre_snap.get("profile_name")
        post_name = post_snap.get("profile_name")
        if pre_name and not post_name:
            violations.append(f"uid={uid} profile_name lost: was {pre_name!r}")

    if violations:
        print(f"[semantic-verify] FAIL — {len(violations)} 处语义回退：")
        for v in violations:
            print(f"  {v}")
    else:
        print(f"[semantic-verify] OK — {len(pre)} 个 uid，语义等价校验全通过")
    return violations


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="S8 离线迁移：旧布局 → v1 布局（从项目根目录运行）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--char-id", default=_DEFAULT_CHAR,
                    help=f"角色 id（默认 {_DEFAULT_CHAR}）")
    ap.add_argument("--backup",  action="store_true",
                    help="备份 data/ → data_backup/{ts}.tar")
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印计划，不动盘")
    ap.add_argument("--copy",    action="store_true",
                    help="非破坏式复制/合并 old→new（保留 old）")
    ap.add_argument("--verify",  action="store_true",
                    help="逐文件比对 count/checksum")
    ap.add_argument("--semantic-snapshot", action="store_true",
                    help="迁移前后语义快照并断言 post ⊇ pre（需 --copy 已完成）")
    ap.add_argument("--commit",  action="store_true",
                    help="verify 通过后删 old（需同时指定 --verify）")
    args = ap.parse_args()

    if args.commit and not args.verify:
        ap.error("--commit 需要同时指定 --verify")

    if not any([args.backup, args.dry_run, args.copy, args.verify, args.semantic_snapshot]):
        ap.print_help()
        return 0

    if args.backup or args.copy or args.commit:
        do_backup()

    plan = build_plan(char_id=args.char_id)

    if args.dry_run:
        do_dry_run(plan)

    uids = _collect_uids()

    pre_snap: dict = {}
    if args.semantic_snapshot:
        pre_snap = do_semantic_snapshot(args.char_id, uids, new_only=False)

    if args.copy:
        do_copy(plan)

    mismatches: list[str] = []
    if args.verify:
        mismatches = do_verify(plan)

    if args.semantic_snapshot and args.copy:
        post_snap = do_semantic_snapshot(args.char_id, uids, new_only=True)
        sem_violations = do_semantic_verify(pre_snap, post_snap)
        if sem_violations:
            print("[semantic-verify] ABORTED — 语义回退，请检查后再执行 --commit",
                  file=sys.stderr)
            return 1

    if args.commit:
        if mismatches:
            print(
                f"[commit] ABORTED — verify 发现 {len(mismatches)} 处不一致，拒绝删除",
                file=sys.stderr,
            )
            return 1
        do_commit(plan)

    return 0


if __name__ == "__main__":
    sys.exit(main())

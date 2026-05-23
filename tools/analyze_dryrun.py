"""Analyze scheduler gating shadow and execute dry-run logs.

Read-only. This script does not print full prompts; suspicious prompt samples are
trimmed to 30 characters.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).parent.parent))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                rows.append({"_bad_json": True, "_line": lineno})
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _ts(row: dict[str, Any]) -> float | None:
    try:
        return float(row.get("ts"))
    except (TypeError, ValueError):
        return None


def _fmt_ts(ts: float | None) -> str:
    if ts is None:
        return "n/a"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _pct(part: int, total: int) -> str:
    if total <= 0:
        return "0.0%"
    return f"{part / total * 100:.1f}%"


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.median(values))


def _prompt_len(text: Any) -> int:
    return len(str(text or "").strip())


def _short_prompt(text: Any) -> str:
    s = str(text or "").strip().replace("\n", " ")
    return s[:30]


def _picked_name(row: dict[str, Any]) -> str | None:
    val = row.get("would_pick")
    if val is None:
        val = row.get("picked")
    return str(val) if val else None


def _candidate_urgency(row: dict[str, Any], trigger_name: str) -> float | None:
    candidates = row.get("candidates") or []
    if not isinstance(candidates, list):
        return None
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        if cand.get("trigger_name") != trigger_name:
            continue
        try:
            return float(cand.get("urgency"))
        except (TypeError, ValueError):
            return None
    return None


def _nearest_shadow(
    execute_ts: float,
    shadows: list[dict[str, Any]],
    *,
    window_sec: float,
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_delta = window_sec + 1
    for row in shadows:
        sts = _ts(row)
        if sts is None:
            continue
        delta = abs(execute_ts - sts)
        if delta <= window_sec and delta < best_delta:
            best = row
            best_delta = delta
    return best


def _print_fields(executions: list[dict[str, Any]], shadows: list[dict[str, Any]]) -> None:
    exec_fields = sorted({k for row in executions[:20] for k in row.keys()})
    shadow_fields = sorted({k for row in shadows[:20] for k in row.keys()})
    candidate_fields = sorted({
        k
        for row in shadows[:20]
        for cand in (row.get("candidates") or [])
        if isinstance(cand, dict)
        for k in cand.keys()
    })
    print("Fields")
    print(f"  execute_dryrun: {', '.join(exec_fields) if exec_fields else '(none)'}")
    print(f"  gating_shadow: {', '.join(shadow_fields) if shadow_fields else '(none)'}")
    print(f"  gating_shadow.candidates[]: {', '.join(candidate_fields) if candidate_fields else '(none)'}")


def _print_time_summary(executions: list[dict[str, Any]], shadows: list[dict[str, Any]]) -> None:
    all_ts = [_ts(r) for r in executions + shadows]
    all_ts = [x for x in all_ts if x is not None]
    total_ticks = len(shadows)
    picked = sum(1 for row in shadows if _picked_name(row))
    silent = total_ticks - picked
    print("\nRange")
    print(f"  start: {_fmt_ts(min(all_ts) if all_ts else None)}")
    print(f"  end:   {_fmt_ts(max(all_ts) if all_ts else None)}")
    print(f"  ticks: {total_ticks}")
    print(f"  picked ticks: {picked} ({_pct(picked, total_ticks)})")
    print(f"  silent ticks: {silent} ({_pct(silent, total_ticks)})")
    print(f"  execute dry-runs: {len(executions)}")


def _print_trigger_summary(shadows: list[dict[str, Any]]) -> None:
    picked_rows = [row for row in shadows if _picked_name(row)]
    total = len(picked_rows)
    by_trigger: dict[str, list[float]] = defaultdict(list)
    for row in picked_rows:
        name = _picked_name(row)
        if not name:
            continue
        urgency = _candidate_urgency(row, name)
        if urgency is not None:
            by_trigger[name].append(urgency)
        else:
            by_trigger[name].append(0.0)

    print("\nPicked Triggers")
    if not by_trigger:
        print("  (none)")
        return
    for name, urgencies in sorted(by_trigger.items(), key=lambda item: (-len(item[1]), item[0])):
        print(
            f"  {name}: count={len(urgencies)}, share={_pct(len(urgencies), total)}, "
            f"urgency=min {min(urgencies):.3f} / med {_median(urgencies):.3f} / max {max(urgencies):.3f}"
        )


def _print_consistency(
    executions: list[dict[str, Any]],
    shadows: list[dict[str, Any]],
    *,
    window_sec: float,
) -> None:
    mismatches: list[str] = []
    matched_shadow_ids: set[int] = set()
    for exe in executions:
        ets = _ts(exe)
        if ets is None:
            continue
        shadow = _nearest_shadow(ets, shadows, window_sec=window_sec)
        actual = str(exe.get("trigger_name") or "")
        if shadow is None:
            mismatches.append(f"execute@{_fmt_ts(ets)} actual={actual} shadow=(none)")
            continue
        matched_shadow_ids.add(id(shadow))
        expected = _picked_name(shadow)
        if expected != actual:
            mismatches.append(
                f"execute@{_fmt_ts(ets)} shadow@{_fmt_ts(_ts(shadow))} "
                f"expected={expected} actual={actual}"
            )

    picked_shadows = [row for row in shadows if _picked_name(row)]
    missing_exec = [
        row for row in picked_shadows
        if id(row) not in matched_shadow_ids
    ]

    print("\nDecide / Execute Consistency")
    print(f"  match window: +/- {window_sec:.1f}s")
    print(f"  execute mismatches: {len(mismatches)}")
    for item in mismatches[:10]:
        print(f"    - {item}")
    if len(mismatches) > 10:
        print(f"    ... {len(mismatches) - 10} more")
    print(f"  picked shadow ticks without matched execute: {len(missing_exec)}")
    for row in missing_exec[:10]:
        print(f"    - shadow@{_fmt_ts(_ts(row))} picked={_picked_name(row)} reason={row.get('reason')}")
    if len(missing_exec) > 10:
        print(f"    ... {len(missing_exec) - 10} more")


def _print_suspicious_prompts(executions: list[dict[str, Any]]) -> None:
    suspicious: dict[str, list[str]] = defaultdict(list)
    for row in executions:
        prompt = row.get("would_send_prompt")
        if _prompt_len(prompt) < 8:
            name = str(row.get("trigger_name") or "(unknown)")
            suspicious[name].append(_short_prompt(prompt))
    print("\nSuspicious Prompts (<8 chars)")
    if not suspicious:
        print("  none")
        return
    for name, samples in sorted(suspicious.items(), key=lambda item: (-len(item[1]), item[0])):
        sample = samples[0] if samples else ""
        print(f"  {name}: count={len(samples)}, sample='{sample}'")


def _print_cache_summary(executions: list[dict[str, Any]]) -> None:
    counts = Counter(
        str(row.get("trigger_name") or "(unknown)")
        for row in executions
        if row.get("reads_cache_ok") is False
    )
    print("\nCache Miss Signals (reads_cache_ok=false)")
    if not counts:
        print("  none")
        return
    for name, count in counts.most_common():
        print(f"  {name}: {count}")


def _print_mark_checks(executions: list[dict[str, Any]]) -> None:
    sleep_rows = [row for row in executions if row.get("trigger_name") == "sleep_end"]
    missing = [
        row for row in sleep_rows
        if "morning_greeting" not in set(row.get("would_mark") or [])
    ]
    print("\nMark Completeness")
    print(f"  sleep_end rows: {len(sleep_rows)}")
    print(f"  sleep_end missing morning_greeting mark: {len(missing)}")


def _print_frequency_health(shadows: list[dict[str, Any]]) -> None:
    picked_rows = [row for row in shadows if _picked_name(row)]
    picked_counts = Counter(_picked_name(row) for row in picked_rows)
    candidate_counts: Counter[str] = Counter()
    for row in shadows:
        for cand in row.get("candidates") or []:
            if isinstance(cand, dict) and cand.get("trigger_name"):
                candidate_counts[str(cand["trigger_name"])] += 1

    total_picked = len(picked_rows)
    print("\nFrequency Health")
    if total_picked == 0:
        print("  no picked ticks")
        return
    dominant = [
        (name, count) for name, count in picked_counts.items()
        if total_picked >= 5 and count / total_picked >= 0.8
    ]
    starved = [
        name for name, seen in candidate_counts.items()
        if seen >= 5 and picked_counts.get(name, 0) == 0
    ]
    if dominant:
        for name, count in sorted(dominant, key=lambda item: (-item[1], item[0])):
            print(f"  dominant: {name} picked {count}/{total_picked} ({_pct(count, total_picked)})")
    else:
        print("  dominant: none")
    if starved:
        print(f"  never picked despite >=5 candidacies: {', '.join(sorted(starved)[:20])}")
        if len(starved) > 20:
            print(f"    ... {len(starved) - 20} more")
    else:
        print("  never picked despite >=5 candidacies: none")


def main() -> int:
    from core.sandbox import get_paths

    paths = get_paths()
    parser = argparse.ArgumentParser(description="Analyze scheduler dry-run logs.")
    parser.add_argument("--execute-log", type=Path, default=paths.execute_dryrun_log())
    parser.add_argument("--shadow-log", type=Path, default=paths.gating_shadow_log())
    parser.add_argument("--match-window-sec", type=float, default=5.0)
    args = parser.parse_args()

    executions = _load_jsonl(args.execute_log)
    shadows = _load_jsonl(args.shadow_log)
    executions.sort(key=lambda row: _ts(row) or 0)
    shadows.sort(key=lambda row: _ts(row) or 0)

    print("Scheduler Dry-Run Analysis")
    print(f"  execute log: {args.execute_log}")
    print(f"  shadow log:  {args.shadow_log}")
    _print_fields(executions, shadows)
    _print_time_summary(executions, shadows)
    _print_trigger_summary(shadows)
    _print_consistency(executions, shadows, window_sec=args.match_window_sec)
    _print_suspicious_prompts(executions)
    _print_cache_summary(executions)
    _print_mark_checks(executions)
    _print_frequency_health(shadows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

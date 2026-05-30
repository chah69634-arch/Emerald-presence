"""
observations.jsonl 紧凑化（compaction）维护。

策略：保留最近 max_raw 条（按 inserted_at 降序；无 inserted_at 视作最旧），
超出部分按文本精确去重后合并（weight 累加）。所有唯一 text 全部保留，不丢语义。

区别于 forensic rotation：
  - forensic rotation 按时间/大小滚动日志，超出部分直接删除（业务可丢）。
  - 本函数为 canonical 数据的 compaction：不删除任何唯一语义条目，
    仅消除重复文本冗余，写回同一文件，确保 observations 不无限增长。

由 core/scheduler/loop.py:_check_log_maintenance 每 24 小时调度一次。
"""
import json
import logging
from pathlib import Path

from core.safe_write import safe_write_text

logger = logging.getLogger(__name__)

_DEFAULT_MAX_RAW = 100


def compact_observations(path: Path, *, max_raw: int = _DEFAULT_MAX_RAW) -> int:
    """
    紧凑化 observations.jsonl。

    返回被合并消除的重复条目数（0 = 无需压缩或文件不存在）。
    写入失败时记录错误并返回 0，不抛异常。
    """
    if not path.exists():
        return 0

    try:
        raw_text = path.read_text(encoding="utf-8").strip()
    except Exception as e:
        logger.warning("[obs_compact] 读取失败 %s: %s", path, e)
        return 0

    if not raw_text:
        return 0

    entries: list[dict] = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            continue

    if len(entries) <= max_raw:
        return 0

    # 按 inserted_at 降序排序（最新在前）；无 inserted_at 的旧条目排到末尾
    entries.sort(key=lambda e: e.get("inserted_at") or "", reverse=True)

    keep = entries[:max_raw]    # 最新 max_raw 条，原样保留
    old = entries[max_raw:]     # 更早条目，文本去重合并

    # keep 中已有的 text 集合：old 中相同 text 已被语义覆盖，无需重复保留
    keep_texts = {e.get("text", "").strip() for e in keep}

    # 文本精确去重：相同 text 合并为一条，weight 累加；keep 已覆盖的跳过
    merged: dict[str, dict] = {}
    for entry in old:
        text = entry.get("text", "").strip()
        if not text or text in keep_texts:
            continue
        if text in merged:
            merged[text]["weight"] = merged[text].get("weight", 1) + 1
        else:
            merged[text] = {**entry, "weight": entry.get("weight", 1)}

    compacted_old = list(merged.values())
    eliminated = len(old) - len(compacted_old)

    # 输出顺序：合并后旧条目在前，最新原始条目在后（后置便于 for_read 首行验证）
    all_out = compacted_old + list(reversed(keep))
    content = "\n".join(json.dumps(e, ensure_ascii=False) for e in all_out) + "\n"

    if not safe_write_text(path, content):
        logger.error("[obs_compact] 写回失败: %s", path)
        return 0

    logger.info(
        "[obs_compact] %s: %d → %d 条 (合并重复 %d)",
        path.name, len(entries), len(all_out), eliminated,
    )
    return eliminated

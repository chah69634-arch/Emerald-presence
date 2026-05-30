"""
S7 Dream chain 烟测

链路：dream_log.append_turn → archive_current → distill_impression → impression_store
     → afterglow（load_afterglow）→ 回流现实 prompt（impression_loader）

验证：
  1. 入梦日志 → archive 落新路径
  2. impression_store 读-改-写往返，sentinels 齐全
  3. distill_impression（mock LLM）→ 写入 impression_store
  4. load_afterglow：TTL 内摘要 → 返回余韵文本
  5. impression_loader.load_impression_text → 读到活跃印象
  6. S1 护栏：impression_loader 是现实侧唯一接触 impression 的入口
     （静态扫描已由 test_dream_isolation_guard.py 覆盖；此处加正向断言：
      load_impression_text 可读到，而 episodic/event_log/short_term 读不到。）
"""

import json
import time
from unittest.mock import AsyncMock, patch

import pytest


_UID = "s7_dream_uid"
_DREAM_ID = "dream_smoke_001"


# ═══════════════════════════════════════════════════════════════════════════════
# 1. dream_log: append_turn → archive_current
# ═══════════════════════════════════════════════════════════════════════════════

def test_dream_log_archive_chain(sandbox):
    """append_turn × 2 → archive_current → 新路径 archive 文件存在，tmp 文件消失。"""
    from core.dream.dream_log import append_turn, archive_current, read_current

    append_turn(_UID, _DREAM_ID, "user", "梦里的你好")
    append_turn(_UID, _DREAM_ID, "assistant", "（轻声）你来了")

    turns = read_current(_UID)
    assert len(turns) == 2
    for t in turns:
        # 每条记录都应带 sentinel 字段
        assert t.get("never_retrieve") is True
        assert t.get("reality_boundary") == "dream_only"

    ok = archive_current(_UID, _DREAM_ID)
    assert ok

    # archive 落新路径
    archive_file = sandbox.dreams_archive_dir() / f"dream_{_DREAM_ID}.jsonl"
    assert archive_file.exists(), f"archive 文件应存在: {archive_file}"

    # tmp 文件被清除
    tmp_dir = sandbox.dreams_tmp_dir()
    tmp_file = tmp_dir / f"current_dream_{_UID}.jsonl"
    assert not tmp_file.exists(), "archive 后 tmp 文件应被删除"

    # archive 内容可读，包含原始对话
    lines = [json.loads(l) for l in archive_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any("梦里的你好" in l.get("content", "") for l in lines)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. impression_store 读-改-写往返
# ═══════════════════════════════════════════════════════════════════════════════

def test_impression_store_roundtrip_with_sentinels(sandbox):
    """append_impression → load_impressions 返回完整条目且 sentinels 齐全。"""
    from core.dream.impression_store import append_impression, load_impressions

    entry = {
        "dream_id": _DREAM_ID,
        "ts": time.time(),
        "last_decay_ts": time.time(),
        "impression_text": "我好像在梦里漂浮着",
        "weight": 0.3,
        "emotional_tags": ["漂浮", "温柔"],
        "exit_type": "soft_exit",
        "decay_after": time.time() + 30 * 86400,
        "marked": True,
    }
    append_impression(_UID, entry)

    loaded = load_impressions(_UID)
    assert len(loaded) == 1

    imp = loaded[0]
    assert imp["impression_text"] == "我好像在梦里漂浮着"
    # sentinels 必须存在
    assert imp.get("never_retrieve") is True
    assert imp.get("not_memory_source") is True
    assert imp.get("reality_boundary") == "dream_only"

    # 文件落新路径
    imp_dir = sandbox.dreams_impressions_dir()
    imp_file = imp_dir / f"{_UID}.json"
    assert imp_file.exists(), f"impression 文件应在新路径: {imp_file}"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. distill_impression（mock LLM）→ 写入 impression_store
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_distill_impression_writes_store(sandbox):
    """distill_impression 读 archive → mock LLM → impression_store 有新条目。"""
    from core.dream.dream_log import append_turn, archive_current
    from core.dream.impression_store import load_impressions

    uid = "s7_distill_uid"
    dream_id = "distill_dream_001"

    # 先建 archive
    append_turn(uid, dream_id, "user", "你握着我的手")
    append_turn(uid, dream_id, "assistant", "不想醒来")
    archive_current(uid, dream_id)

    mock_result = {
        "impression_text": "我好像在梦里被温柔握住",
        "emotional_tags": ["温柔", "依恋"],
        "weight": 0.35,
    }
    # 直接 patch 模块内 _llm_distill，避免 core.llm_client 包属性缓存问题
    from core.dream.distill_impression import distill_impression
    with patch("core.dream.distill_impression._llm_distill", new=AsyncMock(return_value=mock_result)):
        await distill_impression(uid, dream_id, "soft_exit")

    entries = load_impressions(uid)
    assert len(entries) >= 1
    texts = [e.get("impression_text", "") for e in entries]
    assert any("温柔" in t for t in texts), f"impression 应包含'温柔': {texts}"
    # sentinel 应存在
    for e in entries:
        assert e.get("never_retrieve") is True


# ═══════════════════════════════════════════════════════════════════════════════
# 4. afterglow：TTL 内摘要 → load_afterglow 返回余韵文本
# ═══════════════════════════════════════════════════════════════════════════════

def test_afterglow_loads_from_recent_summary(sandbox):
    """在 summaries 目录写入 TTL 内的摘要 → load_afterglow 返回非空文本。"""
    from core.dream.dream_afterglow import load_afterglow

    summaries_dir = sandbox.dreams_summaries_dir()
    summaries_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "uid": _UID,
        "dream_id": _DREAM_ID,
        "created_at": time.time() - 3600,  # 1 小时前，在 8h TTL 内
        "afterglow": "gentle_residue",
        "summary": "梦里有一种漂浮的温柔",
        "emotional_tags": ["温柔", "漂浮"],
        "symbolic_fragments": ["某种光"],
    }
    (summaries_dir / f"dream_{_DREAM_ID}.summary.json").write_text(
        json.dumps(summary, ensure_ascii=False), encoding="utf-8"
    )

    text = load_afterglow(_UID)
    assert text, "TTL 内的摘要应返回非空 afterglow 文本"
    assert "梦的余韵" in text
    assert "漂浮" in text or "温柔" in text


def test_afterglow_expired_summary_returns_empty(sandbox):
    """超过 8h TTL 的摘要 → load_afterglow 返回空字符串。"""
    from core.dream.dream_afterglow import load_afterglow

    summaries_dir = sandbox.dreams_summaries_dir()
    summaries_dir.mkdir(parents=True, exist_ok=True)

    uid = "s7_expired_uid"
    dream_id = "expired_dream"
    summary = {
        "uid": uid,
        "dream_id": dream_id,
        "created_at": time.time() - 9 * 3600,  # 9 小时前，超过 TTL
        "afterglow": "gentle_residue",
        "summary": "已过期的梦",
        "emotional_tags": [],
    }
    (summaries_dir / f"dream_{dream_id}.summary.json").write_text(
        json.dumps(summary, ensure_ascii=False), encoding="utf-8"
    )

    text = load_afterglow(uid)
    assert text == "", f"已过期摘要应返回空字符串，实际: {text!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. impression_loader：唯一现实侧读取通道（正向 + 负向断言）
# ═══════════════════════════════════════════════════════════════════════════════

def test_impression_loader_returns_active_impression(sandbox):
    """向 impression_store 写活跃条目 → load_impression_text 返回格式化文本。"""
    from core.dream.impression_store import append_impression
    from core.dream.impression_loader import load_impression_text

    uid = "s7_loader_uid"
    entry = {
        "dream_id": "loader_dream",
        "ts": time.time(),
        "last_decay_ts": time.time(),
        "impression_text": "我好像在梦里感到很轻",
        "weight": 0.3,
        "emotional_tags": ["轻盈"],
        "exit_type": "soft_exit",
        "decay_after": time.time() + 30 * 86400,  # 30 天后才过期
        "marked": True,
    }
    append_impression(uid, entry)

    text = load_impression_text(uid)
    assert text, "impression_loader 应返回非空文本"
    assert "感到很轻" in text
    # 必须有非现实提示框架
    assert "梦境" in text or "非现实" in text


@pytest.mark.asyncio
async def test_s1_guard_impression_not_visible_to_reality_loaders(sandbox):
    """
    S1 护栏正向 + 负向验证：
    - impression_loader.load_impression_text 能读到印象（正向）
    - event_log.search / short_term.load / episodic_memory.retrieve 看不到印象内容（负向）
    """
    from core.dream.impression_store import append_impression
    from core.dream.impression_loader import load_impression_text
    from core.memory import event_log, short_term
    from core.memory.episodic_memory import retrieve

    uid = "s1_guard_uid"
    sentinel_text = "DREAM_S1_GUARD_SENTINEL__unique_marker_9x7q"

    entry = {
        "dream_id": "s1_dream",
        "ts": time.time(),
        "last_decay_ts": time.time(),
        "impression_text": f"我好像在梦里{sentinel_text}",
        "weight": 0.3,
        "emotional_tags": [],
        "exit_type": "soft_exit",
        "decay_after": time.time() + 30 * 86400,
        "marked": True,
    }
    append_impression(uid, entry)

    # 正向：impression_loader 能读到
    loader_text = load_impression_text(uid)
    assert sentinel_text in loader_text, "impression_loader 应能读到 sentinel"

    # 负向：现实侧 loaders 读不到
    el_result = await event_log.search(uid, sentinel_text)
    st_result = json.dumps(short_term.load_for_prompt(uid))
    ep_result = json.dumps(retrieve(uid, topic=sentinel_text, top_k=5))
    assert sentinel_text not in el_result, "event_log.search 不应看到 dream impression"
    assert sentinel_text not in st_result, "short_term 不应看到 dream impression"
    assert sentinel_text not in ep_result, "episodic_memory.retrieve 不应看到 dream impression"

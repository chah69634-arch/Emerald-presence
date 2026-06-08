"""
tests/test_activity_session.py

ActivitySession P0 骨架验收测试

覆盖：
1.  创建 reading session 成功
2.  创建 gomoku session 成功
3.  创建 chess session 成功
4.  uid + char_id 路径隔离
5.  active session 可读取
6.  close 后不再是 active
7.  同类型重复 start 关闭旧 session，仅新 session 为 active
8.  不写 short_term / history / user_hidden_state
9.  非法 activity_type 拒绝
10. session_id 不允许路径逃逸
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.activity import store as activity_store
from core.activity.session import ActivitySession, new_session_id, now_iso
from core.activity.types import ALLOWED_ACTIVITY_TYPES


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 创建 reading session 成功
# ═══════════════════════════════════════════════════════════════════════════════

def test_create_reading_session(sandbox):
    s = activity_store.create_session("user1", "yexuan", "reading")
    assert s.activity_type == "reading"
    assert s.status == "active"
    assert s.uid == "user1"
    assert s.char_id == "yexuan"
    assert s.session_id
    assert s.created_at
    assert s.updated_at

    loaded = activity_store.load_session("yexuan", "user1", "reading", s.session_id)
    assert loaded is not None
    assert loaded.session_id == s.session_id
    assert loaded.status == "active"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 创建 gomoku session 成功
# ═══════════════════════════════════════════════════════════════════════════════

def test_create_gomoku_session(sandbox):
    s = activity_store.create_session("user1", "yexuan", "gomoku", {"board": []})
    assert s.activity_type == "gomoku"
    assert s.status == "active"
    assert s.state == {"board": []}

    loaded = activity_store.load_session("yexuan", "user1", "gomoku", s.session_id)
    assert loaded is not None
    assert loaded.state == {"board": []}


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 创建 chess session 成功
# ═══════════════════════════════════════════════════════════════════════════════

def test_create_chess_session(sandbox):
    s = activity_store.create_session("user1", "yexuan", "chess", {"fen": "startpos"})
    assert s.activity_type == "chess"
    assert s.status == "active"
    assert s.state == {"fen": "startpos"}

    loaded = activity_store.load_session("yexuan", "user1", "chess", s.session_id)
    assert loaded is not None
    assert loaded.state["fen"] == "startpos"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. uid + char_id 路径隔离
# ═══════════════════════════════════════════════════════════════════════════════

def test_uid_char_id_path_isolation(sandbox):
    s1 = activity_store.create_session("user1", "yexuan", "gomoku")
    s2 = activity_store.create_session("user2", "yexuan", "gomoku")
    s3 = activity_store.create_session("user1", "hongcha", "gomoku")

    d1 = sandbox.activity_session_dir(char_id="yexuan", uid="user1", activity_type="gomoku", session_id=s1.session_id)
    d2 = sandbox.activity_session_dir(char_id="yexuan", uid="user2", activity_type="gomoku", session_id=s2.session_id)
    d3 = sandbox.activity_session_dir(char_id="hongcha", uid="user1", activity_type="gomoku", session_id=s3.session_id)

    assert d1 != d2 != d3
    assert "yexuan" in str(d1)
    assert "hongcha" in str(d3)
    assert "user1" in str(d1)
    assert "user2" in str(d2)

    # 跨 char_id 不可见
    yexuan_active = activity_store.find_active_session("yexuan", "user1", "gomoku")
    hongcha_active = activity_store.find_active_session("hongcha", "user1", "gomoku")
    assert yexuan_active is not None
    assert hongcha_active is not None
    assert yexuan_active.session_id != hongcha_active.session_id
    assert yexuan_active.char_id == "yexuan"
    assert hongcha_active.char_id == "hongcha"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. active session 可读取
# ═══════════════════════════════════════════════════════════════════════════════

def test_find_active_session(sandbox):
    s = activity_store.create_session("owner", "yexuan", "chess")
    found = activity_store.find_active_session("yexuan", "owner", "chess")
    assert found is not None
    assert found.session_id == s.session_id
    assert found.status == "active"


def test_update_state_and_reload(sandbox):
    s = activity_store.create_session("owner", "yexuan", "gomoku", {"moves": []})
    updated = activity_store.update_state("yexuan", "owner", "gomoku", s.session_id, {"moves": [1, 2, 3]})
    assert updated is not None
    assert updated.state["moves"] == [1, 2, 3]

    reloaded = activity_store.load_session("yexuan", "owner", "gomoku", s.session_id)
    assert reloaded is not None
    assert reloaded.state["moves"] == [1, 2, 3]


# ═══════════════════════════════════════════════════════════════════════════════
# 6. close 后不再是 active
# ═══════════════════════════════════════════════════════════════════════════════

def test_close_session_not_active(sandbox):
    s = activity_store.create_session("user1", "yexuan", "gomoku")
    activity_store.close_session("yexuan", "user1", "gomoku", s.session_id)

    found = activity_store.find_active_session("yexuan", "user1", "gomoku")
    assert found is None

    loaded = activity_store.load_session("yexuan", "user1", "gomoku", s.session_id)
    assert loaded is not None
    assert loaded.status == "closed"


def test_close_session_is_idempotent(sandbox):
    s = activity_store.create_session("user1", "yexuan", "chess")
    r1 = activity_store.close_session("yexuan", "user1", "chess", s.session_id)
    r2 = activity_store.close_session("yexuan", "user1", "chess", s.session_id)
    assert r1 is not None and r1.status == "closed"
    assert r2 is not None and r2.status == "closed"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. 同类型重复 start 关闭旧 session，仅新 session 为 active
# ═══════════════════════════════════════════════════════════════════════════════

def test_duplicate_start_closes_old_session(sandbox):
    old = activity_store.create_session("user1", "yexuan", "chess")
    new = activity_store.create_session("user1", "yexuan", "chess")

    assert new.session_id != old.session_id
    assert new.status == "active"

    old_loaded = activity_store.load_session("yexuan", "user1", "chess", old.session_id)
    assert old_loaded is not None
    assert old_loaded.status == "closed"

    active = activity_store.find_active_session("yexuan", "user1", "chess")
    assert active is not None
    assert active.session_id == new.session_id


def test_duplicate_start_different_types_independent(sandbox):
    """不同 activity_type 互不影响。"""
    chess = activity_store.create_session("user1", "yexuan", "chess")
    gomoku = activity_store.create_session("user1", "yexuan", "gomoku")

    assert activity_store.find_active_session("yexuan", "user1", "chess").session_id == chess.session_id
    assert activity_store.find_active_session("yexuan", "user1", "gomoku").session_id == gomoku.session_id


# ═══════════════════════════════════════════════════════════════════════════════
# 8. 不写 short_term / history / user_hidden_state
# ═══════════════════════════════════════════════════════════════════════════════

def test_no_short_term_or_hidden_state_write(sandbox):
    activity_store.create_session("user1", "yexuan", "reading", {"page": 1})
    activity_store.create_session("user1", "yexuan", "gomoku", {"board": []})
    activity_store.create_session("user1", "yexuan", "chess", {})

    # history ディレクトリが作られていないこと
    history_dir = sandbox._p("history")
    chars_history = sandbox._p("chars", "yexuan", "history")
    for p in (history_dir, chars_history):
        if p.exists():
            assert list(p.iterdir()) == [], f"unexpected write in {p}"

    # user_hidden_state.json が書かれていないこと
    hidden = sandbox._p("runtime", "memory", "yexuan", "user1", "user_hidden_state.json")
    assert not hidden.exists()


# ═══════════════════════════════════════════════════════════════════════════════
# 9. 非法 activity_type 拒绝
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("bad_type", ["mahjong", "unknown", "", "READING", "Chess"])
def test_invalid_activity_type_rejected_on_create(sandbox, bad_type):
    with pytest.raises(ValueError):
        activity_store.create_session("user1", "yexuan", bad_type)


@pytest.mark.parametrize("bad_type", ["mahjong", "unknown", "", "GOMOKU"])
def test_invalid_activity_type_rejected_on_find(sandbox, bad_type):
    with pytest.raises(ValueError):
        activity_store.find_active_session("yexuan", "user1", bad_type)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. session_id 不允许路径逃逸
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("evil_id", [
    "../evil",
    "../../etc/passwd",
    "/abs/path",
    "a/b",
    "a\\b",
])
def test_session_id_no_path_traversal(sandbox, evil_id):
    with pytest.raises((ValueError, Exception)):
        sandbox.activity_session_dir(
            char_id="yexuan", uid="user1", activity_type="chess", session_id=evil_id
        )


def test_session_id_valid_hex_accepted(sandbox):
    """正常的 hex session_id 不应报错。"""
    sid = "a1b2c3d4e5f6789012345678abcdef01"
    p = sandbox.activity_session_dir(
        char_id="yexuan", uid="user1", activity_type="chess", session_id=sid
    )
    assert sid in str(p)
    assert str(p).startswith(str(sandbox._base))

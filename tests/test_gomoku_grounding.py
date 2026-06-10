"""
tests/test_gomoku_grounding.py

Gomoku Grounding P0 验收测试（11 用例）

覆盖：
T1.  build_gomoku_grounding_facts 不包含 board / move_history 字段
T2.  last_user_move_facts 识别中心区域 (is_center_area=True)
T3.  last_user_move_facts 识别边缘区域 (is_edge_area=True)
T4.  last_user_move_facts 识别邻接棋子数量
T5.  last_user_move_facts 识别连子链长度 (created_chain)
T6.  last_ai_move_facts 识别 AI win (purpose="win")
T7.  last_ai_move_facts 识别 block_win (purpose="block_win")
T8.  board_facts 给出黑白最长链
T9.  空棋盘 → 基础字段可正常返回，不抛出
T10. did_hold_back=True 当且仅当 ai_style="gentle"
T11. 非AI模式下 last_ai_move 为 None
"""
from __future__ import annotations

import pytest

from core.activity.gomoku_grounding import build_gomoku_grounding_facts, _compute_board_facts


# ── Helpers ────────────────────────────────────────────────────────────────────

def _empty_state(board_size: int = 15, opponent: str = "yexuan_ai", ai_style: str = "balanced") -> dict:
    board = [[None] * board_size for _ in range(board_size)]
    return {
        "board_size": board_size,
        "board": board,
        "current_turn": "black",
        "move_history": [],
        "status": "active",
        "winner": None,
        "last_move": None,
        "opponent": opponent,
        "ai_player": "white",
        "ai_style": ai_style,
    }


def _place(state: dict, x: int, y: int, player: str, source: str = "human") -> dict:
    """Place a stone and update move_history/last_move (helper for test setup)."""
    board = state["board"]
    board[y][x] = player
    move_no = len(state["move_history"]) + 1
    move: dict = {"x": x, "y": y, "player": player, "move_no": move_no}
    if source == "ai":
        move["source"] = "ai"
    state["move_history"].append(move)
    state["last_move"] = move
    return state


# ── T1: output does not include full board / move_history ───────────────────────

def test_grounding_no_board_or_move_history():
    state = _empty_state()
    _place(state, 7, 7, "black")
    facts = build_gomoku_grounding_facts(state)

    assert "board" not in facts, "grounding must not expose full board"
    assert "move_history" not in facts, "grounding must not expose full move_history"


# ── T2: is_center_area detected ────────────────────────────────────────────────

def test_user_move_center_area():
    state = _empty_state()
    _place(state, 7, 7, "black")  # center cell
    facts = build_gomoku_grounding_facts(state)
    uf = facts["last_user_move_facts"]
    assert uf["is_center_area"] is True


# ── T3: is_edge_area detected ──────────────────────────────────────────────────

def test_user_move_edge_area():
    state = _empty_state()
    _place(state, 0, 0, "black")  # corner cell
    facts = build_gomoku_grounding_facts(state)
    uf = facts["last_user_move_facts"]
    assert uf["is_edge_area"] is True
    assert uf["is_center_area"] is False


# ── T4: adjacent_stones count ─────────────────────────────────────────────────

def test_user_move_adjacent_stones():
    state = _empty_state()
    # Place AI stone at (7, 7), then user at (7, 8) — adjacent
    _place(state, 7, 7, "white", source="ai")
    _place(state, 7, 8, "black")
    facts = build_gomoku_grounding_facts(state)
    uf = facts["last_user_move_facts"]
    # (7, 8) has at least the white stone at (7, 7) as an 8-neighbor
    assert uf["adjacent_stones"] >= 1


# ── T5: created_chain length ──────────────────────────────────────────────────

def test_user_move_created_chain():
    state = _empty_state()
    # User plays a horizontal 3-chain: (5,7), (6,7), (7,7)
    _place(state, 5, 7, "black")
    _place(state, 6, 7, "black")
    _place(state, 7, 7, "black")  # last user move
    facts = build_gomoku_grounding_facts(state)
    uf = facts["last_user_move_facts"]
    assert uf["created_chain"] == 3


# ── T6: AI win detection ──────────────────────────────────────────────────────

def test_ai_move_purpose_win():
    """AI completes a 5-chain → purpose should be 'win'."""
    state = _empty_state()
    # Place 4 white stones, then AI plays the 5th
    for i in range(4):
        _place(state, i, 0, "white", source="ai")
    _place(state, 4, 0, "white", source="ai")  # 5th white stone → win
    # Mark as completed
    state["status"] = "completed"
    state["winner"] = "white"
    facts = build_gomoku_grounding_facts(state)
    af = facts["last_ai_move_facts"]
    assert af["purpose"] == "win"
    assert af["created_chain"] == 5


# ── T7: block_win detection ───────────────────────────────────────────────────

def test_ai_move_purpose_block_win():
    """AI blocks user's 5th stone → purpose should be 'block_win'."""
    state = _empty_state()
    # User has 4 black stones in a row: (0,0)–(3,0)
    for i in range(4):
        _place(state, i, 0, "black")
    # AI blocks at (4, 0)
    _place(state, 4, 0, "white", source="ai")
    facts = build_gomoku_grounding_facts(state)
    af = facts["last_ai_move_facts"]
    assert af["purpose"] == "block_win"


# ── T8: board_facts longest chains ────────────────────────────────────────────

def test_board_facts_longest_chain():
    state = _empty_state()
    # Place 3 black in a row at row 0
    for i in range(3):
        _place(state, i, 0, "black")
    # Place 2 white in a row at row 1
    for i in range(2):
        _place(state, i, 1, "white", source="ai")
    facts = build_gomoku_grounding_facts(state)
    bf = facts["board_facts"]
    assert bf["black_longest_chain"] == 3
    assert bf["white_longest_chain"] == 2


# ── T9: empty board doesn't raise ─────────────────────────────────────────────

def test_empty_board_no_error():
    state = _empty_state()
    facts = build_gomoku_grounding_facts(state)
    assert facts["move_count"] == 0
    assert facts["last_user_move"] is None
    assert facts["last_ai_move"] is None
    assert facts["last_user_move_facts"]["summary"] == "暂无落子"
    assert facts["last_ai_move_facts"]["summary"] == "暂无AI落子"
    assert facts["board_facts"]["black_longest_chain"] == 0
    assert facts["board_facts"]["white_longest_chain"] == 0


# ── T10: did_hold_back only True for gentle style ─────────────────────────────

def test_did_hold_back_gentle_only():
    state_gentle = _empty_state(ai_style="gentle")
    facts_gentle = build_gomoku_grounding_facts(state_gentle)
    assert facts_gentle["did_hold_back"] is True

    for style in ("balanced", "serious", "teaching", None):
        state = _empty_state(ai_style=style)
        facts = build_gomoku_grounding_facts(state)
        assert facts["did_hold_back"] is False, f"did_hold_back should be False for ai_style={style!r}"


# ── T11: non-AI mode has no last_ai_move ──────────────────────────────────────

def test_non_ai_mode_no_last_ai_move():
    state = _empty_state(opponent="human")
    _place(state, 7, 7, "black")
    facts = build_gomoku_grounding_facts(state)
    assert facts["last_ai_move"] is None
    assert facts["last_ai_move_facts"]["summary"] == "非AI模式"


# ── board_facts open_three / has_four ─────────────────────────────────────────

def test_board_facts_open_three_and_four():
    state = _empty_state()
    size = 15
    board = state["board"]
    move_history = state["move_history"]

    # Build an open-three for black at row 2: (3,2)–(4,2)–(5,2), both ends open
    for i, x in enumerate([3, 4, 5]):
        board[2][x] = "black"
        move_history.append({"x": x, "y": 2, "player": "black", "move_no": i + 1})

    # Build a four for white at row 3: (0,3)–(3,3)
    for i, x in enumerate(range(4)):
        board[3][x] = "white"
        move_history.append({"x": x, "y": 3, "player": "white", "move_no": i + 4, "source": "ai"})

    state["last_move"] = move_history[-1]
    facts = build_gomoku_grounding_facts(state)
    bf = facts["board_facts"]

    assert bf["black_has_open_three"] is True
    assert bf["white_has_four"] is True

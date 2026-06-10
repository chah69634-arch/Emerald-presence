"""
Gomoku Grounding — deterministic game facts for companion LLM grounding (P0).

Provides build_gomoku_grounding_facts(state: dict) -> dict.

Rules:
- Output does NOT include full board or full move_history — only derived facts.
- Returns "unknown" rather than guessing when analysis is unclear.
- Designed to be injected into companion LLM prompt as <game_facts>.
- No LLM calls, no external I/O, pure computation.
"""
from __future__ import annotations

from core.activity.gomoku_ai import _DIRS, _count_line_info

_BOARD_SIZE = 15
_CENTER = 7  # default center for 15×15 board


# ── Board helpers ──────────────────────────────────────────────────────────────

def _make_empty_board(size: int) -> list[list]:
    return [[None] * size for _ in range(size)]


def _replay_board(move_history: list[dict], until_move_no: int, board_size: int) -> list[list]:
    """Replay move_history for all moves with move_no < until_move_no."""
    board = _make_empty_board(board_size)
    for move in move_history:
        if move.get("move_no", 0) < until_move_no:
            x, y = move["x"], move["y"]
            board[y][x] = move["player"]
    return board


def _max_chain(board: list[list], x: int, y: int, player: str, board_size: int) -> int:
    """Max chain length through (x, y) for player. Stone must already be placed at (x, y)."""
    best = 1
    for dx, dy in _DIRS:
        count, _ = _count_line_info(board, x, y, player, dx, dy, board_size)
        if count > best:
            best = count
    return best


def _count_adjacent(board: list[list], x: int, y: int, board_size: int) -> int:
    """Count occupied 8-connected neighbors of (x, y), excluding the cell itself."""
    count = 0
    for ddx in (-1, 0, 1):
        for ddy in (-1, 0, 1):
            if ddx == 0 and ddy == 0:
                continue
            nx, ny = x + ddx, y + ddy
            if 0 <= nx < board_size and 0 <= ny < board_size and board[ny][nx] is not None:
                count += 1
    return count


# ── Move finders ───────────────────────────────────────────────────────────────

def _get_user_ai_colors(state: dict) -> tuple[str, str]:
    """Returns (user_color, ai_color). Defaults: user=black, ai=white."""
    ai_color = state.get("ai_player", "white")
    user_color = "black" if ai_color == "white" else "white"
    return user_color, ai_color


def _find_last_by_player(move_history: list[dict], player: str) -> dict | None:
    for move in reversed(move_history):
        if move.get("player") == player:
            return move
    return None


def _find_last_ai_move(move_history: list[dict]) -> dict | None:
    for move in reversed(move_history):
        if move.get("source") == "ai":
            return move
    return None


# ── Fact computers ─────────────────────────────────────────────────────────────

def _compute_user_move_facts(
    board: list[list],
    move_history: list[dict],
    last_move: dict | None,
    user_color: str,
    ai_color: str,
    board_size: int,
) -> dict:
    if last_move is None:
        return {
            "created_chain": None,
            "blocked_opponent_chain": None,
            "is_center_area": False,
            "is_edge_area": False,
            "adjacent_stones": 0,
            "summary": "暂无落子",
        }

    x, y = last_move["x"], last_move["y"]
    center = board_size // 2

    # Stone is already on the board — compute chain through it
    created_chain = _max_chain(board, x, y, user_color, board_size)

    # What chain would AI have if it played here? (board before this move)
    move_no = last_move.get("move_no", 1)
    pre = _replay_board(move_history, move_no, board_size)
    pre[y][x] = ai_color
    raw_blocked = _max_chain(pre, x, y, ai_color, board_size)
    blocked_opponent_chain = raw_blocked if raw_blocked >= 2 else None

    is_center_area = max(abs(x - center), abs(y - center)) <= 4
    is_edge_area = x <= 1 or x >= board_size - 2 or y <= 1 or y >= board_size - 2
    adjacent_stones = _count_adjacent(board, x, y, board_size)

    parts: list[str] = []
    if created_chain >= 5:
        parts.append("形成五连（获胜）")
    elif created_chain == 4:
        parts.append("形成四连")
    elif created_chain == 3:
        parts.append("形成三连")

    if blocked_opponent_chain and blocked_opponent_chain >= 3:
        parts.append(f"封堵对方{blocked_opponent_chain}连")

    if not parts:
        if is_center_area:
            parts.append("中心区域落子")
        elif is_edge_area:
            parts.append("边缘区域落子")
        else:
            parts.append("普通落子")

    return {
        "created_chain": created_chain,
        "blocked_opponent_chain": blocked_opponent_chain,
        "is_center_area": is_center_area,
        "is_edge_area": is_edge_area,
        "adjacent_stones": adjacent_stones,
        "summary": "；".join(parts),
    }


def _compute_ai_move_facts(
    board: list[list],
    move_history: list[dict],
    last_move: dict | None,
    ai_color: str,
    user_color: str,
    board_size: int,
) -> dict:
    if last_move is None:
        return {
            "purpose": "unknown",
            "created_chain": None,
            "blocked_user_chain": None,
            "summary": "暂无AI落子",
        }

    x, y = last_move["x"], last_move["y"]
    center = board_size // 2

    created_chain = _max_chain(board, x, y, ai_color, board_size)

    # What user chain would have been if user played here?
    move_no = last_move.get("move_no", 1)
    pre = _replay_board(move_history, move_no, board_size)
    pre[y][x] = user_color
    raw_blocked_user = _max_chain(pre, x, y, user_color, board_size)

    blocked_user_chain = raw_blocked_user if raw_blocked_user >= 2 else None

    # Conservative purpose detection (priority order)
    if created_chain >= 5:
        purpose = "win"
    elif raw_blocked_user >= 5:
        purpose = "block_win"
    elif created_chain >= 4:
        purpose = "attack"
    elif raw_blocked_user >= 4:
        purpose = "defend"
    elif raw_blocked_user >= 3:
        purpose = "defend"
    elif created_chain >= 3:
        purpose = "attack"
    elif max(abs(x - center), abs(y - center)) <= 3:
        purpose = "center"
    else:
        adj = _count_adjacent(board, x, y, board_size)
        purpose = "develop" if adj >= 1 else "unknown"

    summary_map: dict[str, str] = {
        "win": "AI形成五连（获胜）",
        "block_win": f"AI封堵用户{raw_blocked_user}连（阻止获胜）",
        "attack": f"AI形成{created_chain}连进攻",
        "defend": f"AI封堵用户{raw_blocked_user}连",
        "center": "AI中心落子发展",
        "develop": "AI发展棋形",
        "unknown": "AI落子（原因未知）",
    }

    return {
        "purpose": purpose,
        "created_chain": created_chain,
        "blocked_user_chain": blocked_user_chain,
        "summary": summary_map.get(purpose, "unknown"),
    }


def _compute_board_facts(board: list[list], board_size: int) -> dict:
    black_longest = 0
    white_longest = 0
    black_open_three = False
    white_open_three = False
    black_four = False
    white_four = False

    for y in range(board_size):
        for x in range(board_size):
            player = board[y][x]
            if player is None:
                continue
            for dx, dy in _DIRS:
                count, open_ends = _count_line_info(board, x, y, player, dx, dy, board_size)
                if player == "black":
                    if count > black_longest:
                        black_longest = count
                    if count == 3 and open_ends == 2:
                        black_open_three = True
                    if count >= 4:
                        black_four = True
                else:
                    if count > white_longest:
                        white_longest = count
                    if count == 3 and open_ends == 2:
                        white_open_three = True
                    if count >= 4:
                        white_four = True

    return {
        "black_longest_chain": black_longest,
        "white_longest_chain": white_longest,
        "black_has_open_three": black_open_three,
        "white_has_open_three": white_open_three,
        "black_has_four": black_four,
        "white_has_four": white_four,
    }


# ── Public API ─────────────────────────────────────────────────────────────────

def build_gomoku_grounding_facts(state: dict) -> dict:
    """
    Build deterministic, conservative grounding facts from gomoku game state.

    Output does NOT include full board or full move_history — only derived facts.
    Returns "unknown" rather than guessing when analysis is unclear.
    Safe to call on any valid state dict (empty board, completed game, etc.).
    """
    move_history: list[dict] = state.get("move_history", [])
    board: list[list] = state.get("board", [])
    board_size: int = state.get("board_size", _BOARD_SIZE)
    status: str = state.get("status", "active")
    winner = state.get("winner")
    current_turn: str = state.get("current_turn", "black")
    opponent: str = state.get("opponent", "human")
    ai_style = state.get("ai_style")

    user_color, ai_color = _get_user_ai_colors(state)
    last_move = state.get("last_move")
    is_ai_mode = opponent == "yexuan_ai"

    last_user_move = _find_last_by_player(move_history, user_color)
    last_ai_move = _find_last_ai_move(move_history) if is_ai_mode else None

    user_facts = _compute_user_move_facts(
        board, move_history, last_user_move, user_color, ai_color, board_size
    )
    ai_facts = (
        _compute_ai_move_facts(board, move_history, last_ai_move, ai_color, user_color, board_size)
        if is_ai_mode
        else {
            "purpose": "unknown",
            "created_chain": None,
            "blocked_user_chain": None,
            "summary": "非AI模式",
        }
    )
    board_f = _compute_board_facts(board, board_size)

    # did_hold_back: True when last AI move used gentle style (from tilt or session ai_style)
    if last_ai_move and (last_ai_move.get("did_hold_back") or last_ai_move.get("style") == "gentle"):
        did_hold_back = True
    else:
        did_hold_back = ai_style == "gentle"

    return {
        "move_count": len(move_history),
        "status": status,
        "winner": winner,
        "current_turn": current_turn,
        "opponent": opponent,
        "ai_style": ai_style,
        "did_hold_back": did_hold_back,
        "last_move": last_move,
        "last_user_move": last_user_move,
        "last_ai_move": last_ai_move,
        "last_user_move_facts": user_facts,
        "last_ai_move_facts": ai_facts,
        "board_facts": board_f,
    }

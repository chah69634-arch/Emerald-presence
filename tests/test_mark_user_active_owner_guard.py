"""
tests/test_mark_user_active_owner_guard.py — N5 回归测试

验证 mark_user_active() 只在确认是 owner 之后才调用，
非 owner 消息不更新 active window。
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# ── 确保项目根在 sys.path ────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── 辅助：构造最小 message dict ─────────────────────────────────────────────

def _msg(user_id: str) -> dict:
    return {
        "user_id": user_id,
        "content": "hello",
        "sender_name": user_id,
        "timestamp": 0,
        "group_id": None,
    }


# ── 核心：检查 handle_message 里 mark_user_active 的调用位置 ─────────────────

def test_main_py_mark_user_active_not_at_top():
    """main.py 函数体第一个可执行语句不得是 mark_user_active()。"""
    import ast
    src = (_ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    handle_func = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "handle_message"),
        None,
    )
    assert handle_func is not None, "handle_message 函数未找到"

    # 取函数体第一条真正的语句（跳过 docstring）
    body = handle_func.body
    first_stmt = body[0]
    if isinstance(first_stmt, ast.Expr) and isinstance(first_stmt.value, ast.Constant):
        first_stmt = body[1]  # 跳过 docstring

    # 第一条不得是 mark_user_active() 调用
    def _is_mark_call(node: ast.stmt) -> bool:
        """检查是否是 mark_user_active() 或导入 + 立刻调用的模式。"""
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Name) and func.id == "mark_user_active":
                return True
            if isinstance(func, ast.Attribute) and func.attr == "mark_user_active":
                return True
        return False

    assert not _is_mark_call(first_stmt), (
        "handle_message 函数体开头仍是 mark_user_active()，"
        "非 owner 消息会错误地重置主动消息窗口。"
    )


def test_mark_user_active_inside_owner_block():
    """mark_user_active 必须在 owner 判定块内部调用。"""
    import ast
    src = (_ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    handle_func = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "handle_message"),
        None,
    )
    assert handle_func is not None

    # 找所有 mark_user_active 调用节点及其父节点
    call_lines: list[int] = []
    for node in ast.walk(handle_func):
        if isinstance(node, ast.Call):
            func = node.func
            name = (func.id if isinstance(func, ast.Name) else
                    func.attr if isinstance(func, ast.Attribute) else "")
            if name == "mark_user_active":
                call_lines.append(node.lineno)

    assert call_lines, "handle_message 中未找到任何 mark_user_active() 调用"

    # 找到 owner_id 比较的 if 块（"str(user_id) == owner_id"）
    owner_if_lines: list[tuple[int, int]] = []  # (start, end)
    for node in ast.walk(handle_func):
        if isinstance(node, ast.If):
            cond_src = ast.unparse(node.test)
            if "owner_id" in cond_src and "user_id" in cond_src:
                end = max(
                    (getattr(n, "lineno", node.lineno) for n in ast.walk(node)),
                    default=node.lineno,
                )
                owner_if_lines.append((node.lineno, end))

    assert owner_if_lines, "handle_message 中未找到 owner_id 判定块"

    # 每个 mark_user_active 调用都应落在某个 owner_if 块内
    for call_line in call_lines:
        in_owner_block = any(start <= call_line <= end for start, end in owner_if_lines)
        assert in_owner_block, (
            f"mark_user_active() 在第 {call_line} 行的调用不在 owner_id 判定块内，"
            "非 owner 消息可能仍会触发 active window 更新。"
        )

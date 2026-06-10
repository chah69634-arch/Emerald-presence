"""
tests/test_no_hardcoded_qq_number.py — N6 回归测试

生产代码（core/ + admin/ + main.py）中不得出现真实 QQ 号字面量 1043484516。
测试 fixture 允许使用明显假号（如 1234567890）。
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).parent.parent

# 生产代码目录：仅扫描这些位置
_PROD_DIRS = [
    _ROOT / "core",
    _ROOT / "admin",
]
_PROD_FILES = [
    _ROOT / "main.py",
]

_FORBIDDEN_NUMBER = "1043484516"


def _iter_prod_py_files():
    for d in _PROD_DIRS:
        yield from d.rglob("*.py")
    yield from _PROD_FILES


def test_no_hardcoded_qq_in_production_code():
    """生产代码中不得出现字面量 1043484516。"""
    violations: list[str] = []
    for path in _iter_prod_py_files():
        if "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _FORBIDDEN_NUMBER in text:
            for i, line in enumerate(text.splitlines(), 1):
                if _FORBIDDEN_NUMBER in line:
                    violations.append(f"{path.relative_to(_ROOT)}:{i}: {line.strip()}")

    assert not violations, (
        f"生产代码中发现硬编码 QQ 号 {_FORBIDDEN_NUMBER}:\n"
        + "\n".join(violations)
    )

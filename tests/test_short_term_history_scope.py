"""
tests/test_short_term_history_scope.py — P1-0C.5: get_history / module-level load char_id scope

Covers:
1.  Module-level short_term.load(uid, char_id="character_b") reads character_b bucket only.
2.  get_history(uid, char_id="character_b") reads character_b bucket only.
3.  get_history(uid, char_id="character_b") does not expose yexuan-bucket content.
4.  ShortTermMemory.get_history(uid, char_id="character_b") reads character_b bucket only.
5.  get_history respects max_turns truncation when char_id is supplied.
6.  Production caller audit: no file outside short_term.py calls get_history() at module level
    with an implicit yexuan default — at time of writing there are zero production callers.
"""

import ast
import textwrap
from pathlib import Path

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

# `sandbox` is provided by conftest.py and redirects DataPaths._base to tmp_path.


# ── 1. Module-level load reads character_b bucket ─────────────────────────────────

def test_module_load_reads_character_b_bucket(sandbox):
    """short_term.load(uid, char_id='character_b') returns only character_b content."""
    from core.memory.short_term import append, load

    uid = "u_hist_load"
    SENTINEL_H = "荔枝DemoUser-load-character_b"
    SENTINEL_Y = "茉莉Companion-load-yexuan"

    append(uid, "user", SENTINEL_H, char_id="character_b")
    append(uid, "user", SENTINEL_Y, char_id="yexuan")

    character_b = load(uid, char_id="character_b")
    yexuan = load(uid, char_id="yexuan")

    assert any(SENTINEL_H in m.get("content", "") for m in character_b), (
        f"character_b bucket must contain sentinel; got {character_b}"
    )
    assert not any(SENTINEL_H in m.get("content", "") for m in yexuan), (
        f"yexuan bucket must not contain character_b sentinel; got {yexuan}"
    )
    assert not any(SENTINEL_Y in m.get("content", "") for m in character_b), (
        f"character_b bucket must not contain yexuan sentinel; got {character_b}"
    )


# ── 2. get_history reads character_b bucket ───────────────────────────────────────

def test_get_history_reads_character_b_bucket(sandbox):
    """get_history(uid, char_id='character_b') returns character_b bucket content."""
    from core.memory.short_term import append, get_history

    uid = "u_hist_gh"
    SENTINEL_H = "荔枝DemoUser-gh-character_b"

    append(uid, "user", SENTINEL_H, char_id="character_b")

    result = get_history(uid, char_id="character_b")
    assert any(SENTINEL_H in m.get("content", "") for m in result), (
        f"get_history with char_id='character_b' must return character_b content; got {result}"
    )


# ── 3. get_history does not expose yexuan content when reading character_b ────────

def test_get_history_excludes_cross_bucket_content(sandbox):
    """get_history with char_id='character_b' must not contain yexuan-only content."""
    from core.memory.short_term import append, get_history

    uid = "u_hist_cross"
    SENTINEL_Y = "茉莉Companion-cross-yexuan"
    SENTINEL_H = "荔枝DemoUser-cross-character_b"

    append(uid, "user", SENTINEL_Y, char_id="yexuan")
    append(uid, "user", SENTINEL_H, char_id="character_b")

    result = get_history(uid, char_id="character_b")

    assert not any(SENTINEL_Y in m.get("content", "") for m in result), (
        f"get_history(character_b) must not leak yexuan sentinel; got {result}"
    )
    assert any(SENTINEL_H in m.get("content", "") for m in result), (
        f"get_history(character_b) must still return character_b content; got {result}"
    )


# ── 4. ShortTermMemory.get_history class method char_id ───────────────────────

def test_stm_get_history_class_method_reads_character_b_bucket(sandbox):
    """ShortTermMemory.get_history(uid, char_id='character_b') reads character_b bucket."""
    from core.memory.short_term import ShortTermMemory, append

    uid = "u_hist_stm"
    SENTINEL_H = "荔枝DemoUser-stm-gh-character_b"
    SENTINEL_Y = "茉莉Companion-stm-gh-yexuan"

    append(uid, "user", SENTINEL_H, char_id="character_b")
    append(uid, "user", SENTINEL_Y, char_id="yexuan")

    stm = ShortTermMemory()
    character_b = stm.get_history(uid, char_id="character_b")
    yexuan = stm.get_history(uid, char_id="yexuan")

    assert any(SENTINEL_H in m.get("content", "") for m in character_b), (
        f"ShortTermMemory.get_history(character_b) must return character_b content; got {character_b}"
    )
    assert not any(SENTINEL_H in m.get("content", "") for m in yexuan), (
        f"ShortTermMemory.get_history(yexuan) must not see character_b sentinel; got {yexuan}"
    )


# ── 5. get_history respects max_turns when char_id supplied ───────────────────

def test_get_history_max_turns_with_char_id(sandbox):
    """get_history honours max_turns when char_id is given."""
    from core.memory.short_term import append, get_history

    uid = "u_hist_mt"
    for i in range(6):
        append(uid, "user",      f"msg {i}", char_id="character_b")
        append(uid, "assistant", f"rep {i}", char_id="character_b")

    result = get_history(uid, max_turns=2, char_id="character_b")
    assert len(result) <= 4, (
        f"max_turns=2 should return at most 4 messages; got {len(result)}"
    )


# ── 6. Production caller audit ────────────────────────────────────────────────

def _collect_get_history_calls(root: Path) -> list[tuple[str, int]]:
    """
    Walk all .py files under root, parse AST, find calls to get_history()
    that are NOT inside core/memory/short_term.py itself.

    Returns list of (relpath, lineno) for each match.
    """
    hits = []
    short_term_path = root / "core" / "memory" / "short_term.py"

    for py_file in root.rglob("*.py"):
        if py_file == short_term_path:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # Direct call: get_history(...)
                if isinstance(func, ast.Name) and func.id == "get_history":
                    hits.append((str(py_file.relative_to(root)), node.lineno))
                # Attribute call: something.get_history(...)
                elif isinstance(func, ast.Attribute) and func.attr == "get_history":
                    hits.append((str(py_file.relative_to(root)), node.lineno))
    return hits


def test_no_external_get_history_calls_without_char_id():
    """
    Structural audit: no file outside short_term.py calls get_history() at
    module level in production code (only ShortTermMemory.get_history class
    wrapper exists, and it now forwards char_id correctly).

    If new callers are added they MUST pass char_id explicitly; this test
    documents the current zero-caller baseline so regressions are visible.
    """
    root = Path(__file__).parent.parent

    # These are all the expected callers — currently only the class wrapper
    # inside short_term.py itself, which we exclude from the scan above.
    hits = _collect_get_history_calls(root)

    # Tests are allowed to call get_history with an explicit char_id or rely
    # on the default (legacy test compatibility).  Exclude tests/ directory.
    production_hits = [
        (f, ln) for (f, ln) in hits
        if not f.startswith("tests" + str(Path("/"))) and not f.startswith("tests\\")
    ]

    assert production_hits == [], (
        "Found production callers of get_history() outside short_term.py. "
        "Each caller MUST pass char_id explicitly:\n"
        + "\n".join(f"  {f}:{ln}" for f, ln in production_hits)
    )

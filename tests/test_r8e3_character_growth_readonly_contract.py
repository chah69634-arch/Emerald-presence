"""
R8-E3 read-only contract tests for character_growth.

Asserts that character_growth.py is a read-only legacy surface:
- No write methods (update / should_update) exist in the source.
- No write imports (safe_write_text / safe_write_json) exist.
- No write calls (write_text / safe_write) exist.
- Module and load() docstrings contain read-only / retired / R8-E2 keywords.
- get_growth tool description signals read-only / legacy / snapshot.
- get_growth still calls character_growth.load() (functional contract).
"""

import ast
import importlib
import types
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_SRC = Path(__file__).parent.parent / "core" / "memory" / "character_growth.py"
_SRC_TEXT = _SRC.read_text(encoding="utf-8")


# ── 1. No update() method ──────────────────────────────────────────────────────

def test_no_def_update():
    """character_growth.py must not define update() or async update()."""
    tree = ast.parse(_SRC_TEXT)
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "update" not in names, (
        "update() found in character_growth.py — write path must stay retired (R8-E2)"
    )


# ── 2. No should_update() method ───────────────────────────────────────────────

def test_no_def_should_update():
    """character_growth.py must not define should_update()."""
    tree = ast.parse(_SRC_TEXT)
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "should_update" not in names, (
        "should_update() found in character_growth.py — must stay retired (R8-E2)"
    )


# ── 3. No write imports ─────────────────────────────────────────────────────────

def test_no_safe_write_imports():
    """character_growth.py must not import safe_write_text or safe_write_json."""
    assert "safe_write_text" not in _SRC_TEXT, (
        "safe_write_text import found — character_growth is read-only"
    )
    assert "safe_write_json" not in _SRC_TEXT, (
        "safe_write_json import found — character_growth is read-only"
    )


# ── 4. No write calls ──────────────────────────────────────────────────────────

def test_no_write_calls():
    """character_growth.py must not call write_text or safe_write."""
    assert "write_text" not in _SRC_TEXT, (
        "write_text call found — character_growth must not write files"
    )
    assert "safe_write" not in _SRC_TEXT, (
        "safe_write call found — character_growth must not write files"
    )


# ── 5. Module docstring signals read-only / R8-E2 ──────────────────────────────

def test_module_docstring_readonly_keywords():
    """Module docstring must contain read-only / retired / R8-E2 keywords."""
    tree = ast.parse(_SRC_TEXT)
    module_doc = ast.get_docstring(tree) or ""
    doc_lower = module_doc.lower()
    has_readonly = "read-only" in doc_lower or "read only" in doc_lower
    has_retired = "retired" in doc_lower or "r8-e2" in doc_lower.replace(" ", "")
    assert has_readonly, f"Module docstring missing 'read-only' keyword: {module_doc!r}"
    assert has_retired, f"Module docstring missing 'retired' or 'R8-E2' keyword: {module_doc!r}"


# ── 6. get_growth description signals read-only / legacy / snapshot ────────────

def test_get_growth_description_readonly_keywords():
    """get_growth tool description must contain read-only / legacy / snapshot keywords."""
    # We read tool_dispatcher source to check description at definition time,
    # avoiding full import of heavy module dependencies.
    dispatcher_src = (
        Path(__file__).parent.parent / "core" / "tool_dispatcher.py"
    ).read_text(encoding="utf-8")

    # Extract the get_growth description string heuristically
    # Find lines after _TOOL_REGISTRY["get_growth"] that contain "description"
    lines = dispatcher_src.splitlines()
    in_block = False
    description_line = ""
    for line in lines:
        if '_TOOL_REGISTRY["get_growth"]' in line:
            in_block = True
        if in_block and '"description"' in line:
            description_line = line
            break

    assert description_line, "Could not find get_growth description line in tool_dispatcher.py"

    desc_lower = description_line.lower()
    has_signal = (
        "legacy" in desc_lower
        or "snapshot" in desc_lower
        or "只读" in description_line
        or "read-only" in desc_lower
        or "历史" in description_line
    )
    assert has_signal, (
        f"get_growth description does not signal read-only/legacy/snapshot: {description_line.strip()!r}"
    )


# ── 7. get_growth still calls character_growth.load() (functional) ─────────────

def test_get_growth_calls_character_growth_load():
    """get_growth wrapper must still invoke character_growth.load()."""
    load_calls: list[tuple] = []

    real_load = None

    def fake_load(character_name: str, user_id: str) -> str:
        load_calls.append((character_name, user_id))
        return "legacy snapshot content"

    import sys
    # Import character_growth to get module reference before patching
    import core.memory.character_growth as cg_module
    real_load = cg_module.load

    with patch.object(cg_module, "load", side_effect=fake_load):
        import core.tool_dispatcher as td

        # Re-import to get fresh reference to the wrapper
        # The wrapper is a closure that imports character_growth at call time
        import asyncio

        # Patch config_loader.get_config
        mock_config = MagicMock()
        mock_config.character.name = "Companion"
        with patch("core.config_loader.get_config", return_value=mock_config):
            # Call through the registry
            wrapper = td._TOOL_REGISTRY["get_growth"]["func"]
            result = asyncio.get_event_loop().run_until_complete(
                wrapper(user_id="test_uid_r8e3")
            )

    assert load_calls, (
        "character_growth.load() was not called by get_growth — functional contract broken"
    )
    assert load_calls[0][1] == "test_uid_r8e3", (
        f"Expected user_id 'test_uid_r8e3', got {load_calls[0][1]!r}"
    )

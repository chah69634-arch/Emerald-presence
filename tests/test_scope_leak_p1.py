"""
tests/test_scope_leak_p1.py

Scope Leak P1 — static / TypeError hardening assertions

Verifies that the three data_paths methods hardened in P1 are keyword-only
with no default, so that unscoped callers fail loud at call time rather than
silently routing to yexuan.
"""

import pytest


def test_mood_state_requires_char_id(sandbox):
    """get_paths().mood_state() with no arg must raise TypeError."""
    with pytest.raises(TypeError):
        sandbox.mood_state()


def test_activity_snapshot_requires_char_id(sandbox):
    """get_paths().activity_snapshot() with no arg must raise TypeError."""
    with pytest.raises(TypeError):
        sandbox.activity_snapshot()


def test_observations_requires_char_id(sandbox):
    """get_paths().observations() with no arg must raise TypeError."""
    with pytest.raises(TypeError):
        sandbox.observations()


def test_mood_state_accepts_explicit_char_id(sandbox):
    """mood_state(char_id=...) must not raise."""
    p = sandbox.mood_state(char_id="yexuan")
    assert "yexuan" in str(p)


def test_activity_snapshot_accepts_explicit_char_id(sandbox):
    """activity_snapshot(char_id=...) must not raise."""
    p = sandbox.activity_snapshot(char_id="yexuan")
    assert "yexuan" in str(p)


def test_observations_accepts_explicit_char_id(sandbox):
    """observations(char_id=...) must not raise."""
    p = sandbox.observations(char_id="yexuan")
    assert "yexuan" in str(p)

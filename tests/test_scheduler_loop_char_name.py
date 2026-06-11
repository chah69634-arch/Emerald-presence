"""
tests/test_scheduler_loop_char_name.py

Contract tests for the scheduler/loop._char_name() fix.

Rules verified:
- When pipeline is registered with a character, _char_name() returns card name.
- When pipeline is NOT registered, _char_name() raises RuntimeError (fail-loud).
- _char_name() does NOT read config.character.name.
- Hot-swap: switching the active character changes what _char_name() returns.
"""

import pytest
from unittest.mock import MagicMock, patch


def _make_pipeline(char_name: str):
    char = MagicMock()
    char.name = char_name
    pl = MagicMock()
    pl.character = char
    return pl


class TestSchedulerLoopCharName:
    def test_returns_card_name_from_pipeline(self):
        from core.scheduler.loop import _char_name
        pl = _make_pipeline("叶瑄")
        with patch("core.pipeline_registry.get", return_value=pl):
            assert _char_name() == "叶瑄"

    def test_hotswap_returns_new_card_name(self):
        from core.scheduler.loop import _char_name
        pl_a = _make_pipeline("叶瑄")
        pl_b = _make_pipeline("红茶")
        with patch("core.pipeline_registry.get", return_value=pl_a):
            assert _char_name() == "叶瑄"
        with patch("core.pipeline_registry.get", return_value=pl_b):
            assert _char_name() == "红茶"

    def test_raises_when_pipeline_not_registered(self):
        from core.scheduler.loop import _char_name
        with patch("core.pipeline_registry.get", return_value=None):
            with pytest.raises(RuntimeError, match="pipeline"):
                _char_name()

    def test_raises_when_character_is_none(self):
        from core.scheduler.loop import _char_name
        pl = MagicMock()
        pl.character = None
        with patch("core.pipeline_registry.get", return_value=pl):
            with pytest.raises(RuntimeError, match="pipeline"):
                _char_name()

    def test_does_not_read_config(self):
        """_char_name() must never fall back to config.character.name."""
        from core.scheduler.loop import _char_name
        with patch("core.pipeline_registry.get", return_value=None):
            with patch("core.config_loader.get_config") as mock_cfg:
                with pytest.raises(RuntimeError):
                    _char_name()
                # config must not have been consulted
                mock_cfg.assert_not_called()

    def test_card_name_not_config_name(self):
        """Even if config has a different name, card name wins."""
        from core.scheduler.loop import _char_name
        pl = _make_pipeline("红茶")
        with patch("core.pipeline_registry.get", return_value=pl):
            with patch("core.config_loader.get_config", return_value={"character": {"name": "叶瑄"}}):
                assert _char_name() == "红茶"

from unittest.mock import Mock

from core.embodiment import runner


def test_apply_disabled_does_not_accept(monkeypatch):
    light_device = Mock()

    monkeypatch.setattr(
        runner.config_loader,
        "get_config",
        lambda: {"embodiment": {"light": {"enabled": False, "dry_run": True}}},
    )
    monkeypatch.setattr(runner, "LightDevice", light_device)

    runner.apply("happy", None)

    light_device.assert_not_called()


def test_apply_enabled_dry_run_accepts_without_real_io(monkeypatch):
    device = Mock()
    light_device = Mock(return_value=device)

    monkeypatch.setattr(
        runner.config_loader,
        "get_config",
        lambda: {"embodiment": {"light": {"enabled": True, "dry_run": True}}},
    )
    monkeypatch.setattr(runner, "LightDevice", light_device)

    runner.apply("happy", None)

    light_device.assert_called_once_with(dry_run=True)
    device.accept.assert_called_once()
    _, kwargs = device.accept.call_args
    assert kwargs == {"dry_run": True}

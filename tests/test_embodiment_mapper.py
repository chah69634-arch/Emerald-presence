from core.embodiment.mapper import DEFAULT_LIGHT_MAPPINGS, map_state_to_light
from core.hardware.adapters.light import LightCommand


def test_known_moods_return_valid_light_commands():
    expected_moods = {
        "neutral",
        "happy",
        "sad",
        "gentle",
        "surprised",
        "angry",
        "thinking",
        "sleepy",
        "yandere",
    }
    assert set(DEFAULT_LIGHT_MAPPINGS) == expected_moods

    for mood in expected_moods:
        command = map_state_to_light(mood, activity=None)

        assert isinstance(command, LightCommand)
        assert 0.0 <= command.brightness <= 1.0
        assert len(command.color_rgb) == 3
        assert all(isinstance(value, int) and 0 <= value <= 255 for value in command.color_rgb)


def test_unknown_mood_returns_none():
    assert map_state_to_light("unmapped", activity=None) is None

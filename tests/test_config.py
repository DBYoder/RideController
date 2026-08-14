import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

from ridecontroller.config import (
    DEFAULT_ANALOG_MAP,
    DEFAULT_BUTTON_MAP,
    DEFAULT_CONFIG_TEXT,
    Config,
    ConfigError,
    default_config_path,
    load_config,
    parse_config,
    write_default_config,
)
from ridecontroller.constants import RIDE_BUTTON_NAMES


def test_defaults_cover_every_button():
    assert set(DEFAULT_BUTTON_MAP) == set(RIDE_BUTTON_NAMES)


def test_shipped_config_text_parses_and_matches_the_built_in_defaults():
    config = parse_config(tomllib.loads(DEFAULT_CONFIG_TEXT))
    assert config.buttons == DEFAULT_BUTTON_MAP
    assert config.analog == DEFAULT_ANALOG_MAP
    assert config.output.backend == "xbox360"
    assert config.protocol.analog_encoding == "zigzag"


def test_partial_config_keeps_defaults_for_everything_else():
    config = parse_config({"buttons": {"a": "start"}})
    assert config.buttons["a"] == "START"
    assert config.buttons["b"] == DEFAULT_BUTTON_MAP["b"]
    assert config.analog == DEFAULT_ANALOG_MAP


def test_analog_overrides_merge_with_defaults():
    config = parse_config({"analog": {"left_paddle": {"deadzone": 25}}})
    assert config.analog["left_paddle"].deadzone == 25
    assert config.analog["left_paddle"].output == "LT"
    assert config.analog["right_paddle"] == DEFAULT_ANALOG_MAP["right_paddle"]


def test_device_section():
    config = parse_config(
        {"device": {"names": "Zwift Ride", "max_devices": 1, "reconnect": False}}
    )
    assert config.device.names == ["Zwift Ride"]
    assert config.device.max_devices == 1
    assert config.device.reconnect is False


@pytest.mark.parametrize(
    "raw",
    [
        {"buttons": {"nope": "A"}},
        {"buttons": {"a": "TRIANGLE"}},
        {"buttons": {"a": 3}},
        {"analog": {"left_paddle": "LT"}},
        {"analog": {"nope": {"output": "LT"}}},
        {"analog": {"left_paddle": {"output": "LSTICK_Z"}}},
        {"analog": {"left_paddle": {"deadzone": -1}}},
        {"analog": {"left_paddle": {"full_scale": 0}}},
        {"protocol": {"analog_encoding": "rot13"}},
        {"device": {"max_devices": 0}},
        {"device": {"scan_timeout": -5}},
        {"device": {"reconnect": "yes"}},
        {"device": {"names": [1, 2]}},
        {"device": "nope"},
    ],
)
def test_invalid_configs_are_rejected(raw):
    with pytest.raises(ConfigError):
        parse_config(raw)


def test_mapper_is_built_from_config():
    config = parse_config({"output": {"dpad_drives_left_stick": False}})
    mapper = config.mapper()
    assert mapper.dpad_drives_left_stick is False
    assert mapper.outputs_for("a") == "A"


def test_load_config_returns_defaults_when_the_file_is_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("APPDATA", raising=False)
    config = load_config()
    assert config == Config()
    assert config.source_path is None


def test_load_config_errors_when_an_explicit_path_is_missing(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.toml")


def test_load_config_reports_syntax_errors(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("this is not toml", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_write_and_load_round_trip(tmp_path):
    path = write_default_config(tmp_path / "sub" / "config.toml")
    config = load_config(path)
    assert config.source_path == path
    assert config.buttons == DEFAULT_BUTTON_MAP


def test_write_default_config_refuses_to_clobber(tmp_path):
    path = write_default_config(tmp_path / "config.toml")
    with pytest.raises(ConfigError):
        write_default_config(path)
    assert write_default_config(path, overwrite=True) == path


def test_default_config_path_prefers_appdata_on_windows(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert default_config_path() == tmp_path / "RideController" / "config.toml"

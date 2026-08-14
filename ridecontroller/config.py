"""Configuration loading for the Zwift Ride -> Xbox gamepad bridge."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - older interpreters
    import tomli as tomllib  # type: ignore[no-redef]

from .constants import RIDE_ANALOG_NAMES, RIDE_BUTTON_NAMES
from .mapping import AnalogSpec, Mapper
from .protocol import ANALOG_ENCODINGS

CONFIG_FILENAME = "config.toml"
APP_DIRNAME = "RideController"

DEFAULT_BUTTON_MAP: dict[str, str] = {
    "dpad_up": "DPAD_UP",
    "dpad_down": "DPAD_DOWN",
    "dpad_left": "DPAD_LEFT",
    "dpad_right": "DPAD_RIGHT",
    "a": "A",
    "b": "B",
    "y": "Y",
    "z": "X",
    "shift_up_left": "LB",
    "shift_down_left": "LS",
    "shift_up_right": "RB",
    "shift_down_right": "RS",
    "powerup_left": "BACK",
    "powerup_right": "START",
    # The power buttons also sleep the controller when held, so the left one is
    # unmapped by default and the right one opens the Steam overlay.
    "onoff_left": "NONE",
    "onoff_right": "GUIDE",
}

DEFAULT_ANALOG_MAP: dict[str, AnalogSpec] = {
    "left_paddle": AnalogSpec(output="LT", deadzone=10, full_scale=100),
    "right_paddle": AnalogSpec(output="RT", deadzone=10, full_scale=100),
}


class ConfigError(ValueError):
    """Raised for an invalid configuration file."""


@dataclass
class DeviceConfig:
    """Which controllers to connect to."""

    #: Case-insensitive substrings matched against the advertised name. Empty
    #: means "any Zwift Ride".
    names: list[str] = field(default_factory=list)
    #: Exact BLE addresses. Empty means "any".
    addresses: list[str] = field(default_factory=list)
    #: Zwift Ride halves advertise separately; connect to at most this many.
    max_devices: int = 2
    scan_timeout: float = 12.0
    reconnect: bool = True
    #: Also accept Play/Click-style advertisements (128-bit ZAP service).
    accept_any_zwift_device: bool = False


@dataclass
class OutputConfig:
    backend: str = "xbox360"
    dpad_drives_left_stick: bool = True


@dataclass
class ProtocolConfig:
    analog_encoding: str = "zigzag"


@dataclass
class Config:
    device: DeviceConfig = field(default_factory=DeviceConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    protocol: ProtocolConfig = field(default_factory=ProtocolConfig)
    buttons: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_BUTTON_MAP))
    analog: dict[str, AnalogSpec] = field(
        default_factory=lambda: dict(DEFAULT_ANALOG_MAP)
    )
    source_path: Path | None = None

    def mapper(self) -> Mapper:
        return Mapper(
            buttons=dict(self.buttons),
            analog=dict(self.analog),
            dpad_drives_left_stick=self.output.dpad_drives_left_stick,
        )


def default_config_path() -> Path:
    """Where the config lives when the user does not pass ``--config``."""
    appdata = os.environ.get("APPDATA")
    if appdata:  # Windows
        return Path(appdata) / APP_DIRNAME / CONFIG_FILENAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / APP_DIRNAME.lower() / CONFIG_FILENAME


def load_config(path: Path | None = None) -> Config:
    """Load configuration, falling back to built-in defaults.

    An explicit *path* must exist; the default path is optional.
    """
    explicit = path is not None
    path = path or default_config_path()
    if not path.exists():
        if explicit:
            raise ConfigError(f"config file not found: {path}")
        return Config()

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc

    config = parse_config(raw)
    config.source_path = path
    return config


def parse_config(raw: dict) -> Config:
    """Build a :class:`Config` from parsed TOML, validating as we go."""
    config = Config()

    device = _section(raw, "device")
    config.device = DeviceConfig(
        names=_string_list(device, "names"),
        addresses=_string_list(device, "addresses"),
        max_devices=_int(device, "max_devices", DeviceConfig.max_devices, minimum=1),
        scan_timeout=_float(device, "scan_timeout", DeviceConfig.scan_timeout),
        reconnect=_bool(device, "reconnect", DeviceConfig.reconnect),
        accept_any_zwift_device=_bool(
            device, "accept_any_zwift_device", DeviceConfig.accept_any_zwift_device
        ),
    )

    output = _section(raw, "output")
    config.output = OutputConfig(
        backend=str(output.get("backend", OutputConfig.backend)),
        dpad_drives_left_stick=_bool(
            output, "dpad_drives_left_stick", OutputConfig.dpad_drives_left_stick
        ),
    )

    protocol = _section(raw, "protocol")
    encoding = str(protocol.get("analog_encoding", ProtocolConfig.analog_encoding))
    if encoding not in ANALOG_ENCODINGS:
        raise ConfigError(
            f"protocol.analog_encoding must be one of {list(ANALOG_ENCODINGS)}, "
            f"got {encoding!r}"
        )
    config.protocol = ProtocolConfig(analog_encoding=encoding)

    buttons = dict(DEFAULT_BUTTON_MAP)
    for name, value in _section(raw, "buttons").items():
        if name not in RIDE_BUTTON_NAMES:
            raise ConfigError(
                f"unknown button {name!r}; valid names: {', '.join(RIDE_BUTTON_NAMES)}"
            )
        if not isinstance(value, str):
            raise ConfigError(f"buttons.{name} must be a string")
        buttons[name] = value.upper()
    config.buttons = buttons

    analog = dict(DEFAULT_ANALOG_MAP)
    for name, value in _section(raw, "analog").items():
        if name not in RIDE_ANALOG_NAMES:
            raise ConfigError(
                f"unknown analog input {name!r}; valid names: "
                f"{', '.join(RIDE_ANALOG_NAMES)}"
            )
        if not isinstance(value, dict):
            raise ConfigError(f"analog.{name} must be a table, e.g. {{ output = 'LT' }}")
        base = analog.get(name, AnalogSpec())
        analog[name] = AnalogSpec(
            output=str(value.get("output", base.output)).upper(),
            deadzone=_int(value, "deadzone", base.deadzone, minimum=0),
            full_scale=_int(value, "full_scale", base.full_scale, minimum=1),
            invert=_bool(value, "invert", base.invert),
        )
    config.analog = analog

    # Surfaces bad output names as a ConfigError at load time.
    try:
        config.mapper()
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc

    return config


def write_default_config(path: Path, *, overwrite: bool = False) -> Path:
    """Write the annotated starter config, returning the path written."""
    if path.exists() and not overwrite:
        raise ConfigError(f"{path} already exists (use --force to overwrite)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    return path


def _section(raw: dict, name: str) -> dict:
    value = raw.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] must be a table")
    return value


def _string_list(section: dict, key: str) -> list[str]:
    value = section.get(key, [])
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{key} must be a list of strings")
    return list(value)


def _bool(section: dict, key: str, default: bool) -> bool:
    value = section.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be true or false")
    return value


def _int(section: dict, key: str, default: int, *, minimum: int | None = None) -> int:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key} must be an integer")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{key} must be >= {minimum}")
    return value


def _float(section: dict, key: str, default: float) -> float:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{key} must be a number")
    if value <= 0:
        raise ConfigError(f"{key} must be positive")
    return float(value)


DEFAULT_CONFIG_TEXT = """\
# RideController - Zwift Ride as an Xbox gamepad for Steam
#
# Every setting below is optional; delete anything you do not want to change.
# Run `ridecontroller monitor` to see input names as you press them, and
# `ridecontroller outputs` for the list of valid outputs.

[output]
# "xbox360" = virtual Xbox 360 pad (needs ViGEmBus). "debug" = print only.
backend = "xbox360"
# Make the D-pad move the left stick as well, so games that only read the
# analog stick still respond to it.
dpad_drives_left_stick = true

[device]
# Substrings matched against the advertised BLE name. Empty = any Zwift Ride.
names = []
# Exact BLE addresses, if you want to pin specific hardware.
addresses = []
# The Ride's halves can advertise separately; connect to at most this many.
max_devices = 2
scan_timeout = 12.0
reconnect = true
# Set true to also connect to Zwift Play/Click hardware (untested; their button
# layout differs, so expect to remap).
accept_any_zwift_device = false

[protocol]
# How the analog paddle value is encoded. "zigzag" is the default; switch to
# "varint" if `monitor --raw` shows paddle values that look halved or negative.
analog_encoding = "zigzag"

# ---------------------------------------------------------------------------
# Buttons. Valid outputs: A B X Y LB RB LS RS BACK START GUIDE
#   DPAD_UP DPAD_DOWN DPAD_LEFT DPAD_RIGHT LT RT
#   LSTICK_UP LSTICK_DOWN LSTICK_LEFT LSTICK_RIGHT
#   RSTICK_UP RSTICK_DOWN RSTICK_LEFT RSTICK_RIGHT NONE
# ---------------------------------------------------------------------------
[buttons]
dpad_up = "DPAD_UP"
dpad_down = "DPAD_DOWN"
dpad_left = "DPAD_LEFT"
dpad_right = "DPAD_RIGHT"
a = "A"
b = "B"
y = "Y"
z = "X"
shift_up_left = "LB"
shift_down_left = "LS"
shift_up_right = "RB"
shift_down_right = "RS"
powerup_left = "BACK"
powerup_right = "START"
# Holding a power button sleeps the controller, so the left one is unmapped.
onoff_left = "NONE"
onoff_right = "GUIDE"

# ---------------------------------------------------------------------------
# Analog brake paddles. Valid outputs: LT RT LSTICK_X LSTICK_Y RSTICK_X
#   RSTICK_Y NONE
# ---------------------------------------------------------------------------
[analog.left_paddle]
output = "LT"
deadzone = 10
full_scale = 100
invert = false

[analog.right_paddle]
output = "RT"
deadzone = 10
full_scale = 100
invert = false
"""

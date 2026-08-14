"""Translation from Zwift Ride inputs to virtual Xbox 360 controller state."""

from __future__ import annotations

from dataclasses import dataclass, field

from .protocol import ControllerInput

#: Digital outputs that exist as real buttons on an Xbox 360 pad.
GAMEPAD_BUTTONS = (
    "A",
    "B",
    "X",
    "Y",
    "LB",
    "RB",
    "LS",
    "RS",
    "BACK",
    "START",
    "GUIDE",
    "DPAD_UP",
    "DPAD_DOWN",
    "DPAD_LEFT",
    "DPAD_RIGHT",
)

#: Analog outputs a *digital* input can drive (fully deflected while held).
TRIGGER_OUTPUTS = ("LT", "RT")
STICK_DIRECTIONS = {
    "LSTICK_UP": ("left", "y", 1),
    "LSTICK_DOWN": ("left", "y", -1),
    "LSTICK_LEFT": ("left", "x", -1),
    "LSTICK_RIGHT": ("left", "x", 1),
    "RSTICK_UP": ("right", "y", 1),
    "RSTICK_DOWN": ("right", "y", -1),
    "RSTICK_LEFT": ("right", "x", -1),
    "RSTICK_RIGHT": ("right", "x", 1),
}

#: Everything a button may be mapped to.
BUTTON_OUTPUTS = ("NONE",) + GAMEPAD_BUTTONS + TRIGGER_OUTPUTS + tuple(STICK_DIRECTIONS)

#: Everything an analog paddle may be mapped to.
STICK_AXES = ("LSTICK_X", "LSTICK_Y", "RSTICK_X", "RSTICK_Y")
ANALOG_OUTPUTS = ("NONE",) + TRIGGER_OUTPUTS + STICK_AXES

STICK_MAX = 32767
STICK_MIN = -32768
TRIGGER_MAX = 255

#: Which stick axis each D-pad output drives when the D-pad also moves the
#: left stick (games that only read the analog stick for movement).
DPAD_TO_STICK = {
    "DPAD_UP": ("y", 1),
    "DPAD_DOWN": ("y", -1),
    "DPAD_LEFT": ("x", -1),
    "DPAD_RIGHT": ("x", 1),
}


@dataclass(frozen=True)
class AnalogSpec:
    """How one analog paddle drives one output."""

    output: str = "NONE"
    #: Ignore magnitudes below this, in raw controller units (0-100).
    deadzone: int = 10
    #: Raw magnitude treated as fully pressed.
    full_scale: int = 100
    invert: bool = False

    def scaled(self, value: int) -> float:
        """Map a raw paddle reading to -1.0 .. 1.0 with deadzone applied."""
        if self.full_scale <= 0:
            return 0.0
        magnitude = abs(value)
        if magnitude <= self.deadzone:
            return 0.0
        span = self.full_scale - self.deadzone
        if span <= 0:
            fraction = 1.0
        else:
            fraction = min((magnitude - self.deadzone) / span, 1.0)
        if value < 0:
            fraction = -fraction
        return -fraction if self.invert else fraction


@dataclass(frozen=True)
class OutputState:
    """The complete state to push to the virtual gamepad."""

    buttons: frozenset[str] = frozenset()
    left_trigger: int = 0
    right_trigger: int = 0
    left_stick: tuple[int, int] = (0, 0)
    right_stick: tuple[int, int] = (0, 0)

    def describe(self) -> str:
        parts = [" ".join(sorted(self.buttons)) or "-"]
        if self.left_trigger:
            parts.append(f"LT={self.left_trigger}")
        if self.right_trigger:
            parts.append(f"RT={self.right_trigger}")
        if self.left_stick != (0, 0):
            parts.append("LS=%d,%d" % self.left_stick)
        if self.right_stick != (0, 0):
            parts.append("RS=%d,%d" % self.right_stick)
        return " ".join(parts)


NEUTRAL = OutputState()


class MappingError(ValueError):
    """Raised for an unusable button/analog mapping."""


@dataclass
class Mapper:
    """Applies a button/analog mapping to controller snapshots."""

    buttons: dict[str, str] = field(default_factory=dict)
    analog: dict[str, AnalogSpec] = field(default_factory=dict)
    dpad_drives_left_stick: bool = False

    def __post_init__(self) -> None:
        for name, output in self.buttons.items():
            if output.upper() not in BUTTON_OUTPUTS:
                raise MappingError(
                    f"button {name!r} is mapped to unknown output {output!r}"
                )
        for name, spec in self.analog.items():
            if spec.output.upper() not in ANALOG_OUTPUTS:
                raise MappingError(
                    f"analog input {name!r} is mapped to unknown output {spec.output!r}"
                )

    def apply(self, controller_input: ControllerInput) -> OutputState:
        pressed_outputs = {
            self.buttons.get(name, "NONE").upper()
            for name in controller_input.buttons
        }
        pressed_outputs.discard("NONE")

        buttons = {out for out in pressed_outputs if out in GAMEPAD_BUTTONS}
        triggers = {"LT": 0, "RT": 0}
        axes = {"left": {"x": 0.0, "y": 0.0}, "right": {"x": 0.0, "y": 0.0}}

        for out in pressed_outputs:
            if out in TRIGGER_OUTPUTS:
                triggers[out] = TRIGGER_MAX
            elif out in STICK_DIRECTIONS:
                stick, axis, sign = STICK_DIRECTIONS[out]
                axes[stick][axis] = _combine(axes[stick][axis], float(sign))

        if self.dpad_drives_left_stick:
            for out in pressed_outputs & set(DPAD_TO_STICK):
                axis, sign = DPAD_TO_STICK[out]
                axes["left"][axis] = _combine(axes["left"][axis], float(sign))

        for name, value in controller_input.analog.items():
            spec = self.analog.get(name)
            if spec is None:
                continue
            output = spec.output.upper()
            if output == "NONE":
                continue
            fraction = spec.scaled(value)
            if output in TRIGGER_OUTPUTS:
                triggers[output] = max(
                    triggers[output], int(round(abs(fraction) * TRIGGER_MAX))
                )
            elif output in STICK_AXES:
                stick = "left" if output.startswith("LSTICK") else "right"
                axis = output[-1].lower()
                axes[stick][axis] = _combine(axes[stick][axis], fraction)

        return OutputState(
            buttons=frozenset(buttons),
            left_trigger=triggers["LT"],
            right_trigger=triggers["RT"],
            left_stick=_stick_to_int(axes["left"]),
            right_stick=_stick_to_int(axes["right"]),
        )

    def outputs_for(self, input_name: str) -> str:
        """The configured output for an input name, for display purposes."""
        if input_name in self.analog:
            return self.analog[input_name].output.upper()
        return self.buttons.get(input_name, "NONE").upper()


def _combine(current: float, addition: float) -> float:
    """Sum two axis contributions, clamped to -1..1 (opposite presses cancel)."""
    return max(-1.0, min(1.0, current + addition))


def _stick_to_int(axis: dict[str, float]) -> tuple[int, int]:
    return (_axis_to_int(axis["x"]), _axis_to_int(axis["y"]))


def _axis_to_int(value: float) -> int:
    scaled = int(round(value * (STICK_MAX if value >= 0 else -STICK_MIN)))
    return max(STICK_MIN, min(STICK_MAX, scaled))

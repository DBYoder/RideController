"""Virtual Xbox 360 controller output, backed by ViGEmBus via ``vgamepad``.

Windows only. Steam sees the result as an ordinary XInput pad, so per-game
bindings and Steam Input configuration work exactly as they do for a real one.
"""

from __future__ import annotations

from ..mapping import OutputState
from .base import GamepadOutput, OutputError

#: Our output token -> vgamepad button attribute name.
_BUTTON_ATTRS = {
    "A": "XUSB_GAMEPAD_A",
    "B": "XUSB_GAMEPAD_B",
    "X": "XUSB_GAMEPAD_X",
    "Y": "XUSB_GAMEPAD_Y",
    "LB": "XUSB_GAMEPAD_LEFT_SHOULDER",
    "RB": "XUSB_GAMEPAD_RIGHT_SHOULDER",
    "LS": "XUSB_GAMEPAD_LEFT_THUMB",
    "RS": "XUSB_GAMEPAD_RIGHT_THUMB",
    "BACK": "XUSB_GAMEPAD_BACK",
    "START": "XUSB_GAMEPAD_START",
    "GUIDE": "XUSB_GAMEPAD_GUIDE",
    "DPAD_UP": "XUSB_GAMEPAD_DPAD_UP",
    "DPAD_DOWN": "XUSB_GAMEPAD_DPAD_DOWN",
    "DPAD_LEFT": "XUSB_GAMEPAD_DPAD_LEFT",
    "DPAD_RIGHT": "XUSB_GAMEPAD_DPAD_RIGHT",
}

_INSTALL_HINT = (
    "The virtual gamepad needs the ViGEmBus driver and the vgamepad package.\n"
    "  1. pip install vgamepad\n"
    "  2. Install ViGEmBus if the installer did not run automatically:\n"
    "     https://github.com/nefarius/ViGEmBus/releases\n"
    "  3. Reboot if the driver was just installed.\n"
    "Or run with --backend debug to test the mapping without a virtual pad."
)


class Xbox360Output(GamepadOutput):
    name = "xbox360"

    def __init__(self) -> None:
        self._gamepad = None
        self._buttons: dict[str, object] = {}
        self._last: OutputState | None = None

    def open(self) -> None:
        if self._gamepad is not None:
            return
        try:
            import vgamepad
        except ImportError as exc:  # pragma: no cover - platform dependent
            raise OutputError(f"vgamepad is not installed.\n{_INSTALL_HINT}") from exc
        except Exception as exc:  # pragma: no cover - driver dependent
            # vgamepad connects to ViGEmBus while it is still importing, and
            # raises a bare Exception("VIGEM_ERROR_BUS_NOT_FOUND") when the
            # driver is missing. Catching only ImportError above let that
            # escape as a traceback.
            raise OutputError(
                f"could not reach the ViGEmBus driver: {exc}\n{_INSTALL_HINT}"
            ) from exc

        try:
            self._gamepad = vgamepad.VX360Gamepad()
        except Exception as exc:  # pragma: no cover - driver dependent
            raise OutputError(
                f"could not create a virtual Xbox 360 pad: {exc}\n{_INSTALL_HINT}"
            ) from exc

        self._buttons = {
            token: getattr(vgamepad.XUSB_BUTTON, attr)
            for token, attr in _BUTTON_ATTRS.items()
        }

    def apply(self, state: OutputState) -> None:
        if self._gamepad is None:
            self.open()
        assert self._gamepad is not None
        if state == self._last:
            return

        previous = self._last.buttons if self._last else frozenset()
        for token in state.buttons - previous:
            self._gamepad.press_button(button=self._buttons[token])
        for token in previous - state.buttons:
            self._gamepad.release_button(button=self._buttons[token])

        self._gamepad.left_trigger(value=state.left_trigger)
        self._gamepad.right_trigger(value=state.right_trigger)
        self._gamepad.left_joystick(
            x_value=state.left_stick[0], y_value=state.left_stick[1]
        )
        self._gamepad.right_joystick(
            x_value=state.right_stick[0], y_value=state.right_stick[1]
        )
        self._gamepad.update()
        self._last = state

    def reset(self) -> None:
        if self._gamepad is None:
            return
        self._gamepad.reset()
        self._gamepad.update()
        self._last = None

    def close(self) -> None:
        # vgamepad tears the device down when the object is collected.
        self._gamepad = None
        self._last = None

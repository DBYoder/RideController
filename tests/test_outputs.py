import io

import pytest

from ridecontroller.mapping import GAMEPAD_BUTTONS, OutputState
from ridecontroller.outputs import BACKENDS, DebugOutput, NullOutput, OutputError, create_output
from ridecontroller.outputs.xbox360 import _BUTTON_ATTRS, Xbox360Output


def test_every_gamepad_button_has_a_vgamepad_equivalent():
    assert set(_BUTTON_ATTRS) == set(GAMEPAD_BUTTONS)
    assert all(attr.startswith("XUSB_GAMEPAD_") for attr in _BUTTON_ATTRS.values())


def test_factory_builds_each_backend():
    assert isinstance(create_output("debug"), DebugOutput)
    assert isinstance(create_output("null"), NullOutput)
    assert isinstance(create_output(" XBOX360 "), Xbox360Output)
    assert set(BACKENDS) == {"xbox360", "debug", "null"}


def test_factory_rejects_unknown_backends():
    with pytest.raises(OutputError):
        create_output("dualshock")


def test_xbox360_backend_reports_a_missing_driver_clearly(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "vgamepad", None)
    with pytest.raises(OutputError) as excinfo:
        Xbox360Output().open()
    assert "vgamepad" in str(excinfo.value)


def test_debug_backend_only_prints_changes():
    stream = io.StringIO()
    output = DebugOutput(stream=stream)
    pressed = OutputState(buttons=frozenset({"A"}))
    output.apply(pressed)
    output.apply(pressed)
    output.apply(OutputState())
    lines = stream.getvalue().strip().splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("A")
    assert lines[1].endswith("-")


def test_null_backend_accepts_everything():
    output = NullOutput()
    output.open()
    output.apply(OutputState(buttons=frozenset({"A"})))
    output.reset()
    output.close()

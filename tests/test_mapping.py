import pytest

from ridecontroller.config import DEFAULT_ANALOG_MAP, DEFAULT_BUTTON_MAP
from ridecontroller.mapping import AnalogSpec, Mapper, MappingError, OutputState
from ridecontroller.protocol import ControllerInput


def default_mapper(**kwargs) -> Mapper:
    options = dict(
        buttons=dict(DEFAULT_BUTTON_MAP),
        analog=dict(DEFAULT_ANALOG_MAP),
        dpad_drives_left_stick=False,
    )
    options.update(kwargs)
    return Mapper(**options)


def test_face_buttons_map_to_xbox_buttons():
    mapper = default_mapper()
    state = mapper.apply(ControllerInput(buttons=frozenset({"a", "b", "y", "z"})))
    assert state.buttons == frozenset({"A", "B", "Y", "X"})


def test_unmapped_buttons_produce_nothing():
    mapper = default_mapper()
    state = mapper.apply(ControllerInput(buttons=frozenset({"onoff_left"})))
    assert state == OutputState()


def test_button_can_drive_a_trigger():
    mapper = default_mapper(buttons={"a": "RT"})
    state = mapper.apply(ControllerInput(buttons=frozenset({"a"})))
    assert state.right_trigger == 255
    assert state.buttons == frozenset()


def test_button_can_drive_a_stick_direction():
    mapper = default_mapper(buttons={"dpad_up": "RSTICK_UP"})
    state = mapper.apply(ControllerInput(buttons=frozenset({"dpad_up"})))
    assert state.right_stick == (0, 32767)


def test_opposite_stick_directions_cancel():
    mapper = default_mapper(
        buttons={"dpad_left": "LSTICK_LEFT", "dpad_right": "LSTICK_RIGHT"}
    )
    state = mapper.apply(ControllerInput(buttons=frozenset({"dpad_left", "dpad_right"})))
    assert state.left_stick == (0, 0)


def test_dpad_can_also_drive_the_left_stick():
    mapper = default_mapper(dpad_drives_left_stick=True)
    state = mapper.apply(ControllerInput(buttons=frozenset({"dpad_up"})))
    assert "DPAD_UP" in state.buttons
    assert state.left_stick == (0, 32767)

    down = mapper.apply(ControllerInput(buttons=frozenset({"dpad_down"})))
    assert down.left_stick == (0, -32768)


def test_dpad_does_not_touch_the_stick_when_disabled():
    state = default_mapper().apply(ControllerInput(buttons=frozenset({"dpad_left"})))
    assert state.left_stick == (0, 0)


def test_analog_paddle_drives_a_trigger():
    mapper = default_mapper()
    assert mapper.apply(ControllerInput(analog={"left_paddle": 100})).left_trigger == 255
    assert mapper.apply(ControllerInput(analog={"right_paddle": 100})).right_trigger == 255


def test_analog_deadzone_suppresses_small_values():
    mapper = default_mapper()
    assert mapper.apply(ControllerInput(analog={"left_paddle": 10})).left_trigger == 0
    assert mapper.apply(ControllerInput(analog={"left_paddle": 11})).left_trigger > 0


def test_analog_scaling_is_linear_above_the_deadzone():
    spec = AnalogSpec(output="LT", deadzone=10, full_scale=100)
    assert spec.scaled(55) == pytest.approx(0.5)
    assert spec.scaled(-55) == pytest.approx(-0.5)
    assert spec.scaled(200) == pytest.approx(1.0)


def test_analog_full_scale_can_be_lowered_for_a_shorter_throw():
    spec = AnalogSpec(output="LT", deadzone=0, full_scale=50)
    assert spec.scaled(50) == pytest.approx(1.0)
    assert spec.scaled(25) == pytest.approx(0.5)


def test_analog_invert():
    spec = AnalogSpec(output="LSTICK_X", deadzone=0, full_scale=100, invert=True)
    assert spec.scaled(100) == pytest.approx(-1.0)


def test_analog_can_drive_a_stick_axis():
    mapper = default_mapper(
        analog={"left_paddle": AnalogSpec(output="LSTICK_X", deadzone=0)}
    )
    state = mapper.apply(ControllerInput(analog={"left_paddle": -100}))
    assert state.left_stick == (-32768, 0)


def test_analog_input_without_a_mapping_is_ignored():
    mapper = default_mapper(analog={})
    assert mapper.apply(ControllerInput(analog={"left_paddle": 100})) == OutputState()


def test_button_and_analog_share_a_trigger_taking_the_larger():
    mapper = default_mapper(buttons={"a": "LT"})
    state = mapper.apply(
        ControllerInput(buttons=frozenset({"a"}), analog={"left_paddle": 30})
    )
    assert state.left_trigger == 255


def test_invalid_button_output_is_rejected_at_construction():
    with pytest.raises(MappingError):
        Mapper(buttons={"a": "TRIANGLE"})


def test_invalid_analog_output_is_rejected_at_construction():
    with pytest.raises(MappingError):
        Mapper(analog={"left_paddle": AnalogSpec(output="LSTICK_Z")})


def test_outputs_for_reports_the_configured_target():
    mapper = default_mapper()
    assert mapper.outputs_for("z") == "X"
    assert mapper.outputs_for("left_paddle") == "LT"
    assert mapper.outputs_for("nonexistent") == "NONE"


def test_describe_summarises_state():
    state = OutputState(
        buttons=frozenset({"A"}), left_trigger=128, left_stick=(100, -100)
    )
    assert state.describe() == "A LT=128 LS=100,-100"

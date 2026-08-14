from ridecontroller.bridge import Bridge, InputMerger
from ridecontroller.config import Config
from ridecontroller.mapping import NEUTRAL, OutputState
from ridecontroller.outputs.base import GamepadOutput
from ridecontroller.protocol import BatteryLevel, ControllerInput, Idle, UnknownMessage


class RecordingOutput(GamepadOutput):
    name = "recording"

    def __init__(self):
        self.states: list[OutputState] = []
        self.opened = False
        self.closed = False

    def open(self):
        self.opened = True

    def apply(self, state):
        self.states.append(state)

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, address="AA:BB", name="left"):
        self.address = address
        self.name = name


def test_merger_unions_buttons_from_both_halves():
    merger = InputMerger()
    merger.update("left", ControllerInput(buttons=frozenset({"dpad_up"})))
    merged = merger.update("right", ControllerInput(buttons=frozenset({"a"})))
    assert merged.buttons == frozenset({"dpad_up", "a"})


def test_merger_keeps_the_strongest_analog_reading():
    merger = InputMerger()
    merger.update("left", ControllerInput(analog={"left_paddle": 20}))
    merged = merger.update("right", ControllerInput(analog={"left_paddle": -80}))
    assert merged.analog == {"left_paddle": -80}


def test_merger_replaces_a_devices_previous_state():
    merger = InputMerger()
    merger.update("left", ControllerInput(buttons=frozenset({"a"})))
    merged = merger.update("left", ControllerInput(buttons=frozenset({"b"})))
    assert merged.buttons == frozenset({"b"})


def test_forgetting_a_device_releases_its_buttons():
    merger = InputMerger()
    merger.update("left", ControllerInput(buttons=frozenset({"a"})))
    merger.update("right", ControllerInput(buttons=frozenset({"b"})))
    assert merger.forget("left").buttons == frozenset({"b"})
    assert merger.forget("right").buttons == frozenset()


def make_bridge():
    output = RecordingOutput()
    return Bridge(Config(), output), output


def test_controller_input_reaches_the_output():
    bridge, output = make_bridge()
    bridge._handle_message(FakeConnection(), ControllerInput(buttons=frozenset({"a"})))
    assert output.states[-1].buttons == frozenset({"A"})


def test_identical_states_are_not_re_sent():
    bridge, output = make_bridge()
    for _ in range(3):
        bridge._handle_message(
            FakeConnection(), ControllerInput(buttons=frozenset({"a"}))
        )
    assert len(output.states) == 1


def test_disconnect_releases_that_devices_buttons():
    bridge, output = make_bridge()
    left, right = FakeConnection("AA", "left"), FakeConnection("BB", "right")
    bridge._handle_message(left, ControllerInput(buttons=frozenset({"dpad_up"})))
    bridge._handle_message(right, ControllerInput(buttons=frozenset({"a"})))
    bridge._handle_connection_state(left, connected=False)
    assert output.states[-1].buttons == frozenset({"A"})


def test_input_listener_is_notified():
    seen = []
    bridge = Bridge(Config(), RecordingOutput(), on_input=lambda name, i: seen.append(name))
    bridge._handle_message(FakeConnection(name="left"), ControllerInput())
    assert seen == ["left"]


def test_battery_updates_are_tracked():
    bridge, _ = make_bridge()
    connection = FakeConnection()
    bridge._handle_message(connection, BatteryLevel(percent=63))
    assert bridge.battery[connection.address] == 63


def test_non_input_messages_do_not_touch_the_output():
    bridge, output = make_bridge()
    bridge._handle_message(FakeConnection(), Idle())
    bridge._handle_message(FakeConnection(), UnknownMessage(0x42, b"\x01"))
    assert output.states == []


def test_context_manager_resets_and_closes():
    output = RecordingOutput()
    with output:
        output.apply(OutputState(buttons=frozenset({"A"})))
    assert output.opened and output.closed
    assert output.states[-1] == NEUTRAL

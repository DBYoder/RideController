import pytest

from ridecontroller import protobuf, protocol
from ridecontroller.constants import (
    MSG_BATTERY_LEVEL,
    MSG_DISCONNECT,
    MSG_IDLE,
    MSG_RIDE_CONTROLLER_NOTIFICATION,
    RIDE_BUTTON_MASKS,
)


def keypad_packet(button_map: int, analog: bytes = b"") -> bytes:
    body = protobuf.encode_varint_field(1, button_map) + analog
    return bytes([MSG_RIDE_CONTROLLER_NOTIFICATION]) + body


def analog_entry(location: int, value: int, *, zigzag: bool = True) -> bytes:
    wire = protobuf.zigzag_encode(value) if zigzag else value
    press = protobuf.encode_varint_field(1, location) + protobuf.encode_varint_field(2, wire)
    return protobuf.encode_bytes_field(3, press)


ALL_RELEASED = 0xFFFF


def test_nothing_pressed_when_every_bit_is_high():
    message = protocol.decode_packet(keypad_packet(ALL_RELEASED))
    assert isinstance(message, protocol.ControllerInput)
    assert message.buttons == frozenset()
    assert message.analog == {}


@pytest.mark.parametrize("name,mask", sorted(RIDE_BUTTON_MASKS.items()))
def test_each_button_is_active_low(name, mask):
    message = protocol.decode_packet(keypad_packet(ALL_RELEASED & ~mask))
    assert message.buttons == frozenset({name})
    assert message.raw_button_map == ALL_RELEASED & ~mask


def test_multiple_buttons_at_once():
    mask = RIDE_BUTTON_MASKS["a"] | RIDE_BUTTON_MASKS["dpad_up"]
    message = protocol.decode_packet(keypad_packet(ALL_RELEASED & ~mask))
    assert message.buttons == frozenset({"a", "dpad_up"})


def test_unknown_high_bits_are_ignored():
    message = protocol.decode_packet(keypad_packet(0x1FFFF))
    assert message.buttons == frozenset()


def test_missing_button_map_is_rejected_rather_than_read_as_all_pressed():
    packet = bytes([MSG_RIDE_CONTROLLER_NOTIFICATION])
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_packet(packet)


def test_malformed_protobuf_raises_protocol_error():
    packet = bytes([MSG_RIDE_CONTROLLER_NOTIFICATION]) + b"\x08"
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_packet(packet)


def test_analog_paddles_are_decoded():
    packet = keypad_packet(ALL_RELEASED, analog_entry(0, 75) + analog_entry(1, -40))
    message = protocol.decode_packet(packet)
    assert message.analog == {"left_paddle": 75, "right_paddle": -40}


def test_analog_encoding_can_be_switched_to_plain_varint():
    packet = keypad_packet(ALL_RELEASED, analog_entry(0, 100, zigzag=False))
    assert protocol.decode_packet(packet).analog == {"left_paddle": 50}
    plain = protocol.decode_packet(packet, analog_encoding="varint")
    assert plain.analog == {"left_paddle": 100}


def test_unknown_analog_location_is_kept_under_a_generic_name():
    packet = keypad_packet(ALL_RELEASED, analog_entry(9, 12))
    assert protocol.decode_packet(packet).analog == {"analog_9": 12}


def test_analog_entry_without_a_value_is_skipped():
    press = protobuf.encode_bytes_field(3, protobuf.encode_varint_field(1, 0))
    message = protocol.decode_packet(keypad_packet(ALL_RELEASED, press))
    assert message.analog == {}


def test_bad_analog_encoding_name_is_rejected():
    with pytest.raises(ValueError):
        protocol.decode_keypad_status(b"\x08\xff\xff\x03", analog_encoding="rot13")


def test_idle_and_disconnect_and_empty():
    assert isinstance(protocol.decode_packet(bytes([MSG_IDLE])), protocol.Idle)
    assert isinstance(protocol.decode_packet(bytes([MSG_DISCONNECT])), protocol.Disconnect)
    assert protocol.decode_packet(b"") is None


def test_battery_level():
    packet = bytes([MSG_BATTERY_LEVEL]) + protobuf.encode_varint_field(1, 84)
    message = protocol.decode_packet(packet)
    assert isinstance(message, protocol.BatteryLevel)
    assert message.percent == 84


def test_implausible_battery_level_falls_back_to_unknown():
    packet = bytes([MSG_BATTERY_LEVEL]) + protobuf.encode_varint_field(1, 900)
    assert isinstance(protocol.decode_packet(packet), protocol.UnknownMessage)


def test_handshake_response_carries_the_public_key():
    packet = b"RideOn" + bytes([0x01, 0x03]) + b"\xaa\xbb\xcc"
    message = protocol.decode_packet(packet)
    assert isinstance(message, protocol.HandshakeResponse)
    assert message.public_key == b"\xaa\xbb\xcc"


def test_unrecognised_message_type_is_reported_not_raised():
    message = protocol.decode_packet(bytes([0x42, 0x01]))
    assert isinstance(message, protocol.UnknownMessage)
    assert message.message_type == 0x42
    assert message.payload == b"\x01"


@pytest.mark.parametrize("encoding", ["zigzag", "varint"])
def test_encode_decode_round_trip(encoding):
    pressed = {"a", "shift_up_right", "dpad_left"}
    analog = {"left_paddle": 61, "right_paddle": 0}
    packet = protocol.encode_keypad_status(pressed, analog, analog_encoding=encoding)
    message = protocol.decode_packet(packet, analog_encoding=encoding)
    assert message.buttons == frozenset(pressed)
    assert message.analog == analog


def test_describe_is_readable():
    message = protocol.decode_packet(
        keypad_packet(ALL_RELEASED & ~RIDE_BUTTON_MASKS["b"], analog_entry(1, 30))
    )
    assert message.describe() == "[b] right_paddle=30"

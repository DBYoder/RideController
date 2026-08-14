import pytest

from ridecontroller import protobuf


@pytest.mark.parametrize("value", [0, 1, 127, 128, 300, 65535, 2**31 - 1])
def test_varint_round_trip(value):
    encoded = protobuf.write_varint(value)
    decoded, pos = protobuf.read_varint(encoded)
    assert decoded == value
    assert pos == len(encoded)


@pytest.mark.parametrize("value", [0, 1, -1, 50, -50, 100, -100])
def test_zigzag_round_trip(value):
    assert protobuf.zigzag_decode(protobuf.zigzag_encode(value)) == value


def test_zigzag_uses_the_documented_encoding():
    # Known protobuf test vectors.
    assert protobuf.zigzag_encode(-1) == 1
    assert protobuf.zigzag_encode(1) == 2
    assert protobuf.zigzag_decode(200) == 100


def test_decode_message_mixed_wire_types():
    data = (
        protobuf.encode_varint_field(1, 65535)
        + protobuf.encode_bytes_field(3, b"\x08\x01")
        + protobuf.encode_bytes_field(3, b"\x08\x02")
    )
    fields = protobuf.decode_message(data)
    assert protobuf.get_varint(fields, 1) == 65535
    assert protobuf.get_submessages(fields, 3) == [b"\x08\x01", b"\x08\x02"]


def test_decode_message_keeps_unknown_fields_without_failing():
    data = protobuf.encode_varint_field(1, 7) + protobuf.encode_varint_field(99, 1)
    fields = protobuf.decode_message(data)
    assert protobuf.get_varint(fields, 99) == 1


def test_decode_message_handles_fixed_width_fields():
    data = bytes([5 << 3 | protobuf.WIRE_32BIT]) + (7).to_bytes(4, "little")
    data += bytes([6 << 3 | protobuf.WIRE_64BIT]) + (9).to_bytes(8, "little")
    fields = protobuf.decode_message(data)
    assert protobuf.get_varint(fields, 5) == 7
    assert protobuf.get_varint(fields, 6) == 9


def test_missing_field_returns_none():
    assert protobuf.get_varint({}, 1) is None
    assert protobuf.get_submessages({}, 3) == []


@pytest.mark.parametrize(
    "data",
    [
        b"\x08",  # truncated varint
        b"\x1a\x05ab",  # length-delimited field claims more bytes than exist
        b"\x0c",  # wire type 4 (group end) is not supported
        b"\x00\x01",  # field number 0
    ],
)
def test_invalid_buffers_raise(data):
    with pytest.raises(protobuf.ProtobufError):
        protobuf.decode_message(data)


def test_write_varint_rejects_negative():
    with pytest.raises(ValueError):
        protobuf.write_varint(-1)

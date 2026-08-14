"""A tiny protobuf wire-format reader.

Zwift's messages are protobuf, but the ``.proto`` definitions are not public --
they were recovered by reverse engineering. Rather than pull in the protobuf
runtime plus generated code for two small messages, we walk the wire format
directly and interpret the fields we know about (see ``protocol.py``).

Only the wire format is implemented here, so this stays valid even if Zwift
adds fields we do not know about: unknown fields simply show up in the result
dict and are ignored by the callers.
"""

from __future__ import annotations

from typing import Union

WIRE_VARINT = 0
WIRE_64BIT = 1
WIRE_LENGTH_DELIMITED = 2
WIRE_32BIT = 5

#: A decoded field value: an int for varint/fixed-width fields, bytes for
#: length-delimited ones (strings, nested messages, packed repeated fields).
FieldValue = Union[int, bytes]

#: Field number -> every value seen for it, in wire order. Protobuf allows a
#: field to repeat, so values always come back as a list.
Message = dict[int, list[FieldValue]]


class ProtobufError(ValueError):
    """Raised when a buffer is not valid protobuf wire format."""


def read_varint(data: bytes, pos: int = 0) -> tuple[int, int]:
    """Read a base-128 varint at *pos*. Returns ``(value, next_pos)``."""
    result = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise ProtobufError("truncated varint")
        if shift > 63:
            raise ProtobufError("varint too long")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def zigzag_decode(value: int) -> int:
    """Decode a protobuf ``sint32``/``sint64`` zigzag-encoded varint."""
    return (value >> 1) ^ -(value & 1)


def decode_message(data: bytes) -> Message:
    """Decode a protobuf message into ``{field_number: [values]}``."""
    fields: Message = {}
    pos = 0
    end = len(data)
    while pos < end:
        key, pos = read_varint(data, pos)
        field_number = key >> 3
        wire_type = key & 0x07
        if field_number == 0:
            raise ProtobufError("invalid field number 0")

        if wire_type == WIRE_VARINT:
            value, pos = read_varint(data, pos)
        elif wire_type == WIRE_64BIT:
            if pos + 8 > end:
                raise ProtobufError("truncated 64-bit field")
            value = int.from_bytes(data[pos : pos + 8], "little")
            pos += 8
        elif wire_type == WIRE_LENGTH_DELIMITED:
            length, pos = read_varint(data, pos)
            if pos + length > end:
                raise ProtobufError("truncated length-delimited field")
            value = data[pos : pos + length]
            pos += length
        elif wire_type == WIRE_32BIT:
            if pos + 4 > end:
                raise ProtobufError("truncated 32-bit field")
            value = int.from_bytes(data[pos : pos + 4], "little")
            pos += 4
        else:
            raise ProtobufError(f"unsupported wire type {wire_type}")

        fields.setdefault(field_number, []).append(value)
    return fields


def get_varint(fields: Message, field_number: int) -> int | None:
    """Return the last varint value for *field_number*, or None if absent."""
    values = fields.get(field_number)
    if not values:
        return None
    value = values[-1]
    if not isinstance(value, int):
        return None
    return value


def get_submessages(fields: Message, field_number: int) -> list[bytes]:
    """Return every length-delimited value for *field_number*."""
    return [v for v in fields.get(field_number, []) if isinstance(v, bytes)]


# --------------------------------------------------------------------------
# Encoding -- only needed by the tests and the fake-device simulator.
# --------------------------------------------------------------------------


def write_varint(value: int) -> bytes:
    """Encode a non-negative integer as a base-128 varint."""
    if value < 0:
        raise ValueError("varint values must be non-negative; zigzag first")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def zigzag_encode(value: int) -> int:
    """Zigzag-encode a signed integer for a protobuf ``sint32`` field."""
    return (value << 1) ^ (value >> 63)


def encode_varint_field(field_number: int, value: int) -> bytes:
    return write_varint(field_number << 3 | WIRE_VARINT) + write_varint(value)


def encode_bytes_field(field_number: int, value: bytes) -> bytes:
    return (
        write_varint(field_number << 3 | WIRE_LENGTH_DELIMITED)
        + write_varint(len(value))
        + value
    )

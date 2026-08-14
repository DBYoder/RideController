"""Decoding of Zwift Ride controller notifications.

The controller pushes ``RideKeyPadStatus`` messages over the ASYNC
characteristic. Each notification is one type byte followed by a protobuf
message::

    0x23  <RideKeyPadStatus>

    RideKeyPadStatus {
        1: uint32 button_map              // active LOW: 0 bit == pressed
        3: repeated RideAnalogKeyPress {
               1: enum  location          // 0 = left paddle, 1 = right paddle
               2: sint32 analog_value     // roughly -100..100
           }
    }

See docs/PROTOCOL.md for provenance and for how to check these assumptions
against your own hardware with ``ridecontroller monitor --raw``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import protobuf
from .constants import (
    HANDSHAKE_RESPONSE_PREFIX,
    MSG_BATTERY_LEVEL,
    MSG_BATTERY_STATUS,
    MSG_DISCONNECT,
    MSG_IDLE,
    MSG_RIDE_CONTROLLER_NOTIFICATION,
    RIDE_ANALOG_LOCATIONS,
    RIDE_BUTTON_MASKS,
)

#: How ``RideAnalogKeyPress.analog_value`` is encoded on the wire. The field is
#: believed to be a protobuf ``sint32`` (zigzag), but the definition is
#: reverse-engineered, so this is switchable from the config file.
ANALOG_ENCODINGS = ("zigzag", "varint")


@dataclass(frozen=True)
class ControllerInput:
    """A full snapshot of the controller's inputs at one instant."""

    buttons: frozenset[str] = frozenset()
    analog: dict[str, int] = field(default_factory=dict)
    raw_button_map: int = 0

    def describe(self) -> str:
        buttons = " ".join(sorted(self.buttons)) or "-"
        analog = " ".join(f"{k}={v}" for k, v in sorted(self.analog.items()))
        return f"[{buttons}] {analog}".strip()


@dataclass(frozen=True)
class BatteryLevel:
    percent: int


@dataclass(frozen=True)
class Idle:
    """Sent periodically while nothing is happening."""


@dataclass(frozen=True)
class HandshakeResponse:
    """Reply to our ``RideOn``; carries the device's (unused) public key."""

    public_key: bytes


@dataclass(frozen=True)
class Disconnect:
    """The controller is dropping the session (e.g. Zwift took it over)."""


@dataclass(frozen=True)
class UnknownMessage:
    message_type: int
    payload: bytes


Message = (
    ControllerInput
    | BatteryLevel
    | Idle
    | HandshakeResponse
    | Disconnect
    | UnknownMessage
)


class ProtocolError(ValueError):
    """Raised when a notification cannot be decoded."""


def decode_packet(data: bytes, *, analog_encoding: str = "zigzag") -> Message | None:
    """Decode one BLE notification payload.

    Returns ``None`` for empty packets. Malformed protobuf raises
    :class:`ProtocolError`; unrecognised message types come back as
    :class:`UnknownMessage` so callers can log them without failing.
    """
    if not data:
        return None

    if data.startswith(HANDSHAKE_RESPONSE_PREFIX):
        # RideOn + 2 status bytes + public key
        return HandshakeResponse(public_key=bytes(data[len(HANDSHAKE_RESPONSE_PREFIX) + 2 :]))

    message_type = data[0]
    payload = bytes(data[1:])

    if message_type == MSG_IDLE:
        return Idle()
    if message_type == MSG_DISCONNECT:
        return Disconnect()
    if message_type == MSG_RIDE_CONTROLLER_NOTIFICATION:
        return decode_keypad_status(payload, analog_encoding=analog_encoding)
    if message_type in (MSG_BATTERY_LEVEL, MSG_BATTERY_STATUS):
        return _decode_battery(payload)
    return UnknownMessage(message_type=message_type, payload=payload)


def decode_keypad_status(
    payload: bytes, *, analog_encoding: str = "zigzag"
) -> ControllerInput:
    """Decode a ``RideKeyPadStatus`` protobuf body into a :class:`ControllerInput`."""
    if analog_encoding not in ANALOG_ENCODINGS:
        raise ValueError(f"unknown analog encoding {analog_encoding!r}")

    try:
        fields = protobuf.decode_message(payload)
    except protobuf.ProtobufError as exc:
        raise ProtocolError(f"bad RideKeyPadStatus: {exc}") from exc

    button_map = protobuf.get_varint(fields, 1)
    if button_map is None:
        # The mask is active low, so a missing field would decode to "every
        # button held". Refuse to guess.
        raise ProtocolError("RideKeyPadStatus has no button map")

    buttons = frozenset(
        name for name, mask in RIDE_BUTTON_MASKS.items() if not button_map & mask
    )

    analog: dict[str, int] = {}
    for raw in protobuf.get_submessages(fields, 3):
        try:
            press = protobuf.decode_message(raw)
        except protobuf.ProtobufError:
            continue
        location = protobuf.get_varint(press, 1) or 0
        value = protobuf.get_varint(press, 2)
        if value is None:
            continue
        if analog_encoding == "zigzag":
            value = protobuf.zigzag_decode(value)
        name = RIDE_ANALOG_LOCATIONS.get(location, f"analog_{location}")
        analog[name] = value

    return ControllerInput(buttons=buttons, analog=analog, raw_button_map=button_map)


def _decode_battery(payload: bytes) -> Message:
    try:
        fields = protobuf.decode_message(payload)
    except protobuf.ProtobufError:
        return UnknownMessage(message_type=MSG_BATTERY_LEVEL, payload=payload)
    percent = protobuf.get_varint(fields, 1)
    if percent is None or not 0 <= percent <= 100:
        return UnknownMessage(message_type=MSG_BATTERY_LEVEL, payload=payload)
    return BatteryLevel(percent=percent)


# --------------------------------------------------------------------------
# Encoding -- used by the tests and by ``ridecontroller simulate``.
# --------------------------------------------------------------------------


def encode_keypad_status(
    pressed: frozenset[str] | set[str] | tuple[str, ...] = (),
    analog: dict[str, int] | None = None,
    *,
    analog_encoding: str = "zigzag",
) -> bytes:
    """Build a notification payload equivalent to what a controller sends."""
    button_map = 0
    for name, mask in RIDE_BUTTON_MASKS.items():
        if name not in pressed:
            button_map |= mask  # active low: 1 == released

    body = protobuf.encode_varint_field(1, button_map)
    locations = {name: loc for loc, name in RIDE_ANALOG_LOCATIONS.items()}
    for name, value in (analog or {}).items():
        wire_value = (
            protobuf.zigzag_encode(value) if analog_encoding == "zigzag" else value
        )
        press = protobuf.encode_varint_field(1, locations[name])
        press += protobuf.encode_varint_field(2, wire_value)
        body += protobuf.encode_bytes_field(3, press)

    return bytes([MSG_RIDE_CONTROLLER_NOTIFICATION]) + body

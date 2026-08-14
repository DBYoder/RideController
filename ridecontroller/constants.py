"""Constants for the Zwift Accessory Protocol (ZAP) as used by Zwift Ride.

Everything in here was derived from public reverse-engineering work; see
docs/PROTOCOL.md for the sources and for how to verify these values against
your own hardware.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# BLE identifiers
# --------------------------------------------------------------------------

#: Zwift Ride advertises/exposes the custom service as a 16-bit UUID.
ZWIFT_RIDE_SERVICE_UUID = "0000fc82-0000-1000-8000-00805f9b34fb"

#: Zwift Play / Click use this 128-bit service UUID for the same protocol.
ZWIFT_ZAP_SERVICE_UUID = "00000001-19ca-4651-86e5-fa29dcdd09d1"

CUSTOM_SERVICE_UUIDS = (ZWIFT_RIDE_SERVICE_UUID, ZWIFT_ZAP_SERVICE_UUID)

#: Unsolicited controller state arrives here (notify).
ASYNC_CHARACTERISTIC_UUID = "00000002-19ca-4651-86e5-fa29dcdd09d1"
#: Host -> device commands, including the handshake (write / write-no-response).
SYNC_RX_CHARACTERISTIC_UUID = "00000003-19ca-4651-86e5-fa29dcdd09d1"
#: Device -> host command responses (indicate).
SYNC_TX_CHARACTERISTIC_UUID = "00000004-19ca-4651-86e5-fa29dcdd09d1"

#: Bluetooth SIG company identifier for Zwift, Inc.
ZWIFT_COMPANY_ID = 2378  # 0x094A

# --------------------------------------------------------------------------
# Handshake
# --------------------------------------------------------------------------

#: Written to SYNC_RX to start a session. Sending the bare "RideOn" (without a
#: public key) keeps the device in unencrypted mode, which is all we need.
RIDE_ON = b"RideOn"

#: The device answers on SYNC_TX with RIDE_ON + two bytes + its public key.
HANDSHAKE_RESPONSE_PREFIX = RIDE_ON

# --------------------------------------------------------------------------
# Device types (first byte of the Zwift manufacturer-specific advertising data)
# --------------------------------------------------------------------------

DEVICE_TYPES = {
    0x02: "play_right",
    0x03: "play_left",
    0x07: "ride_right",
    0x08: "ride_left",
    0x09: "click",
    0x0A: "click_v2_right",
    0x0B: "click_v2_left",
    0x0E: "play_fw2",
}

RIDE_DEVICE_TYPES = frozenset({"ride_left", "ride_right"})

# --------------------------------------------------------------------------
# Message type bytes (first byte of each notification payload)
# --------------------------------------------------------------------------

MSG_PLAY_CONTROLLER_NOTIFICATION = 0x07
MSG_IDLE = 0x15  # 21 - sent while nothing is happening
MSG_BATTERY_LEVEL = 0x19  # 25
MSG_BATTERY_STATUS = 0x1A  # 26
MSG_RIDE_CONTROLLER_NOTIFICATION = 0x23  # 35
MSG_CLICK_CONTROLLER_NOTIFICATION = 0x37  # 55
MSG_DISCONNECT = 0xFE

# --------------------------------------------------------------------------
# Zwift Ride button bitmask (field 1 of RideKeyPadStatus)
#
# The mask is ACTIVE LOW: a bit that reads 0 means the button is held down.
# --------------------------------------------------------------------------

RIDE_BUTTON_MASKS: dict[str, int] = {
    "dpad_left": 0x0001,
    "dpad_up": 0x0002,
    "dpad_right": 0x0004,
    "dpad_down": 0x0008,
    "a": 0x0010,
    "b": 0x0020,
    "y": 0x0040,
    "z": 0x0080,
    "shift_up_left": 0x0100,
    "shift_down_left": 0x0200,
    "powerup_left": 0x0400,
    "onoff_left": 0x0800,
    "shift_up_right": 0x1000,
    "shift_down_right": 0x2000,
    "powerup_right": 0x4000,
    "onoff_right": 0x8000,
}

#: Analog inputs, keyed by the "location" enum in RideAnalogKeyPress.
RIDE_ANALOG_LOCATIONS: dict[int, str] = {
    0: "left_paddle",
    1: "right_paddle",
    2: "analog_up",
    3: "analog_down",
}

#: Every input name the Zwift Ride can report, in a stable display order.
RIDE_BUTTON_NAMES = tuple(RIDE_BUTTON_MASKS)
RIDE_ANALOG_NAMES = ("left_paddle", "right_paddle")

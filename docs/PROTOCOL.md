# Zwift Ride BLE protocol

What RideController implements, and how to check it against your own hardware.
Zwift does not publish this protocol; everything below comes from public
reverse-engineering work (see [Sources](#sources)) and is reimplemented here
from those findings.

## Connection

| Item | Value |
| --- | --- |
| Service (Zwift Ride) | `0000fc82-0000-1000-8000-00805f9b34fb` (16-bit `0xFC82`) |
| Service (Play / Click) | `00000001-19ca-4651-86e5-fa29dcdd09d1` |
| `ASYNC` characteristic | `00000002-19ca-4651-86e5-fa29dcdd09d1` — notify, controller state |
| `SYNC_RX` characteristic | `00000003-19ca-4651-86e5-fa29dcdd09d1` — write, host → device |
| `SYNC_TX` characteristic | `00000004-19ca-4651-86e5-fa29dcdd09d1` — indicate, device → host |
| Manufacturer ID | `2378` (`0x094A`, Zwift, Inc.) |

The first byte of the Zwift manufacturer-specific advertising data identifies
the model:

| Byte | Model |
| --- | --- |
| `0x02` / `0x03` | Zwift Play right / left |
| `0x07` / `0x08` | Zwift Ride right / left |
| `0x09` | Zwift Click |
| `0x0A` / `0x0B` | Zwift Click v2 right / left |
| `0x0E` | Zwift Play, firmware 2 |

### Handshake

1. Subscribe to `ASYNC` (notify) and `SYNC_TX` (indicate).
2. Write the six ASCII bytes `RideOn` (`52 69 64 65 4f 6e`) to `SYNC_RX`.
3. The device answers on `SYNC_TX` with `RideOn` + two status bytes + its public
   key.

Sending a public key of our own would start Zwift's encrypted mode (AES-GCM over
a key exchange). Sending the bare `RideOn` leaves the session unencrypted, which
is all a controller bridge needs, so RideController ignores the returned key.

There is no keepalive: the controller pushes state on its own and the link stays
up until one side drops it.

## Notifications

Every notification is one type byte followed by a protobuf message.

| Type | Meaning |
| --- | --- |
| `0x07` | Play controller state (`PlayKeyPadStatus`) |
| `0x15` | Idle — nothing is happening |
| `0x19` / `0x1A` | Battery level / status |
| `0x23` | **Ride controller state (`RideKeyPadStatus`)** |
| `0x37` | Click controller state |
| `0xFE` | The device is ending the session |

### RideKeyPadStatus (`0x23`)

```proto
message RideKeyPadStatus {
  uint32 button_map = 1;                     // ACTIVE LOW: a 0 bit is pressed
  repeated RideAnalogKeyPress paddles = 3;
}

message RideAnalogKeyPress {
  Location location = 1;                     // 0 left paddle, 1 right paddle
  sint32   analog_value = 2;                 // about -100..100
}
```

The button map is **active low** — an idle controller sends `0xFFFF` and each
pressed button clears its bit:

| Bit | Input | Bit | Input |
| --- | --- | --- | --- |
| `0x0001` | `dpad_left` | `0x0100` | `shift_up_left` |
| `0x0002` | `dpad_up` | `0x0200` | `shift_down_left` |
| `0x0004` | `dpad_right` | `0x0400` | `powerup_left` |
| `0x0008` | `dpad_down` | `0x0800` | `onoff_left` |
| `0x0010` | `a` | `0x1000` | `shift_up_right` |
| `0x0020` | `b` | `0x2000` | `shift_down_right` |
| `0x0040` | `y` | `0x4000` | `powerup_right` |
| `0x0080` | `z` | `0x8000` | `onoff_right` |

Because the mask is active low, a message that omits field 1 would decode as
"every button held". RideController rejects such a message instead of guessing
(`ProtocolError`), and ignores bits above `0xFFFF`.

Both halves of the controller report the full 16-bit map, with bits for buttons
they do not own reading as released, so merging two connected halves is a plain
union of the pressed sets.

## Checking these assumptions against your hardware

Two details are inferred rather than observed, and both are switchable:

**1. Button bit assignments.** Run:

```powershell
ridecontroller monitor --raw
```

Each line shows the decoded input names plus `button_map=0x….` Press one button
at a time: exactly one bit should clear, and the name should match the table
above. If a bit maps to the wrong name, remap it in the config rather than
editing code — unless the bit itself is different, in which case
`ridecontroller/constants.py` holds `RIDE_BUTTON_MASKS`.

**2. Analog paddle encoding.** `analog_value` is treated as a protobuf `sint32`
(zigzag). If the paddles read about half of what you expect, or flip sign
strangely, the field is a plain varint on your firmware:

```toml
[protocol]
analog_encoding = "varint"
```

Squeeze a paddle fully under `monitor` and check the value approaches 100 in one
of the two modes.

Raw packets are printed with `--log-level debug`.

## Sources

- [ajchellew/zwiftplay](https://github.com/ajchellew/zwiftplay) — service and
  characteristic UUIDs, the `RideOn` handshake, message types, and the original
  discovery that the payloads are protobuf.
- [Makinolo](https://www.makinolo.com/blog/2024/07/26/zwift-ride-protocol/) —
  write-ups of the Play, Ride and Trainer protocols, including the encrypted
  mode we deliberately avoid.
- [OpenBikeControl / SwiftControl](https://github.com/jonasbark/swiftcontrol) —
  the Ride button bitmask and analog paddle layout.

RideController reimplements these findings; no source from those projects is
included.

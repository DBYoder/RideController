# RideController

Use a **Zwift Ride** controller as a **virtual Xbox gamepad** on Windows, so Steam
games see it as an ordinary controller.

The Zwift Ride talks a private Bluetooth LE protocol, not the standard HID
gamepad profile — Windows and Steam cannot use it directly, and no firmware
change can be made to it from the outside. RideController closes that gap on the
PC side: it connects to the controller over BLE, decodes its button and paddle
messages, and drives a virtual Xbox 360 pad through the
[ViGEmBus](https://github.com/nefarius/ViGEmBus) driver.

```
Zwift Ride  --BLE-->  RideController  --ViGEmBus-->  virtual Xbox 360 pad  -->  Steam
```

Steam treats that virtual pad exactly like real hardware, so Steam Input,
per-game bindings and controller glyphs all work normally.

## Requirements

- Windows 10 or 11
- Python 3.10 or newer
- A Bluetooth LE adapter (built-in or USB)
- [ViGEmBus](https://github.com/nefarius/ViGEmBus/releases) — the `vgamepad`
  package installs it for you on first use if it is missing
- A Zwift Ride controller **not currently connected to Zwift or the Zwift
  Companion app** (BLE controllers only talk to one host at a time)

## Install

```powershell
git clone https://github.com/DBYoder/RideController.git
cd RideController
py -m pip install -e .
```

On Windows that also pulls in `vgamepad`. If ViGEmBus is not installed yet, the
first run pops up its installer; reboot afterwards if it asks you to.

## Quick start

```powershell
# 1. Check the environment, the driver and that the controller is visible
ridecontroller doctor

# 2. See what is nearby
ridecontroller scan

# 3. Verify the virtual pad works, without touching the controller
#    (Windows: open "Set up USB game controllers" and watch it move)
ridecontroller simulate

# 4. Watch real button presses decode, without creating a virtual pad
ridecontroller monitor

# 5. Run the bridge — leave this window open while you play
ridecontroller run
```

Start `ridecontroller run` **before** launching the game so Steam picks the pad
up at startup. Press `Ctrl+C` to stop; all buttons are released on exit.

## Default mapping

| Zwift Ride input | Xbox output | Notes |
| --- | --- | --- |
| D-pad up/down/left/right | D-pad (and left stick) | `dpad_drives_left_stick` also deflects the stick, for games that only read the stick |
| A | A | |
| B | B | |
| Y | Y | |
| Z | X | |
| Left shift up | LB | |
| Left shift down | LS (stick click) | |
| Right shift up | RB | |
| Right shift down | RS (stick click) | |
| Left powerup | Back / View | |
| Right powerup | Start / Menu | |
| Left brake paddle (analog) | Left trigger | Analog, with a deadzone |
| Right brake paddle (analog) | Right trigger | Analog, with a deadzone |
| Left on/off | *unmapped* | Holding it sleeps the controller |
| Right on/off | Guide | Opens the Steam overlay |

`ridecontroller outputs` prints the live mapping and every valid output name.

## Configuration

```powershell
ridecontroller init-config     # writes %APPDATA%\RideController\config.toml
notepad %APPDATA%\RideController\config.toml
```

Everything in the file is optional — anything you leave out keeps its default.
Remap a button by naming an output:

```toml
[buttons]
z = "RSTICK_UP"          # any of: A B X Y LB RB LS RS BACK START GUIDE
powerup_left = "NONE"    # DPAD_* LT RT LSTICK_* RSTICK_* NONE

[analog.left_paddle]
output = "LSTICK_X"      # or LT / RT / LSTICK_Y / RSTICK_X / RSTICK_Y / NONE
deadzone = 15            # ignore paddle movement below this (raw units, 0-100)
full_scale = 80          # raw value treated as fully pressed — a shorter throw
invert = false
```

Use a different file with `ridecontroller --config path\to\config.toml run`, so
you can keep one profile per game.

## Steam notes

- The pad shows up as an **Xbox 360 Controller**. In Steam → Settings →
  Controller, leave "Xbox Extended Feature Support" alone; ViGEm needs nothing
  special.
- If a game ignores it, open Steam Input for that game and confirm the pad is
  detected; Big Picture usually finds it immediately.
- Games that only read the analog stick still work: the D-pad drives the left
  stick as well by default.
- Steam sometimes only enumerates controllers present at launch. If the game
  cannot see the pad, start `ridecontroller run` first, then Steam.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `No Zwift Ride controller found` | Press a button to wake the controller. Close Zwift and the Companion app — they hold the BLE connection. Try `ridecontroller scan --all`. |
| `no Zwift service found` | Update the controller firmware in the Zwift Companion app. |
| `could not create a virtual Xbox 360 pad` | Install ViGEmBus and reboot: <https://github.com/nefarius/ViGEmBus/releases> |
| Buttons land on the wrong outputs | Run `ridecontroller monitor` to see the input names, then remap them in the config. |
| Paddles feel half-scale or read negative | Set `analog_encoding = "varint"` under `[protocol]`. See [docs/PROTOCOL.md](docs/PROTOCOL.md). |
| Controller drops out mid-session | Reconnection is automatic (`device.reconnect`); check the battery with `--log-level debug`. |
| Nothing happens in-game | Confirm the pad itself works with `ridecontroller simulate`, then check Steam Input bindings. |

`--log-level debug` prints every raw BLE packet, which is the fastest way to see
what the controller is actually sending.

## How it works

| Module | Responsibility |
| --- | --- |
| `ridecontroller/ble.py` | Scanning, connection, the `RideOn` handshake, reconnection |
| `ridecontroller/protobuf.py` | A ~120-line protobuf wire reader (no codegen, no runtime dependency) |
| `ridecontroller/protocol.py` | Zwift message decoding → `ControllerInput` snapshots |
| `ridecontroller/mapping.py` | `ControllerInput` → `OutputState` (buttons, triggers, sticks) |
| `ridecontroller/outputs/` | `xbox360` (ViGEmBus via vgamepad) and `debug` backends |
| `ridecontroller/bridge.py` | Merges both controller halves and pushes state to a backend |
| `ridecontroller/config.py` | TOML config, validation, the annotated starter file |
| `ridecontroller/cli.py` | `scan`, `monitor`, `run`, `simulate`, `doctor`, … |

The controller pushes complete state snapshots rather than press/release events,
so the bridge is stateless: decode → merge → map → apply. If one half of the
controller disconnects, only its buttons are released.

The protocol itself is documented in [docs/PROTOCOL.md](docs/PROTOCOL.md).

## Development

```bash
pip install -e ".[dev]"
pytest
```

The tests cover the wire format, the message decoding (including the active-low
button mask), the mapping engine, the config loader, the CLI, and the connection
state machine against a fake BLE backend — so everything except the ViGEmBus
call itself runs without hardware. Use `--backend debug` to run the bridge on a
machine with no virtual-gamepad driver.

## Not included

- Zwift Play and Zwift Click. They speak the same protocol with a different
  button layout; `accept_any_zwift_device = true` will connect, but the mapping
  is not written for them.
- Haptics — the Ride can buzz, but nothing here sends the command.
- Keyboard/mouse emulation, a GUI, and a packaged `.exe`.

## Credits

The protocol is not published by Zwift. This implementation is written from
public reverse-engineering write-ups — chiefly
[ajchellew/zwiftplay](https://github.com/ajchellew/zwiftplay), the
[Makinolo](https://www.makinolo.com/blog/2024/07/26/zwift-ride-protocol/)
protocol posts, and [OpenBikeControl/SwiftControl](https://github.com/jonasbark/swiftcontrol).
No code from those projects is used here.

Not affiliated with or endorsed by Zwift. "Zwift" and "Zwift Ride" are
trademarks of Zwift, Inc.

## License

MIT — see [LICENSE](LICENSE).

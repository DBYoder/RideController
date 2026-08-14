"""Command line interface for RideController."""

from __future__ import annotations

import argparse
import asyncio
import logging
import platform
import sys
import time
from pathlib import Path

from . import __version__
from .ble import BleError, scan
from .bridge import Bridge
from .config import (
    Config,
    ConfigError,
    default_config_path,
    load_config,
    write_default_config,
)
from .constants import RIDE_ANALOG_NAMES, RIDE_BUTTON_NAMES
from .driver import (
    VIGEMBUS_RELEASES,
    describe_exit_code,
    find_installer,
    run_installer,
)
from .mapping import ANALOG_OUTPUTS, BUTTON_OUTPUTS
from .outputs import BACKENDS, OutputError, create_output
from .protocol import ControllerInput

log = logging.getLogger("ridecontroller")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ridecontroller",
        description="Use a Zwift Ride controller as an Xbox gamepad for Steam games.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"config file to load (default: {default_config_path()})",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=("debug", "info", "warning", "error"),
        help="logging verbosity (default: info)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="list nearby Zwift controllers")
    scan_parser.add_argument(
        "--seconds", type=float, default=None, help="scan duration (default: from config)"
    )
    scan_parser.add_argument(
        "--all",
        action="store_true",
        help="include Zwift Play/Click devices, not just Ride hardware",
    )
    scan_parser.set_defaults(func=cmd_scan)

    monitor_parser = subparsers.add_parser(
        "monitor", help="connect and print inputs without creating a virtual gamepad"
    )
    monitor_parser.add_argument(
        "--raw",
        action="store_true",
        help="also print the raw button bitmask and BLE packets",
    )
    monitor_parser.set_defaults(func=cmd_monitor)

    run_parser = subparsers.add_parser("run", help="run the controller bridge")
    run_parser.add_argument(
        "--backend",
        choices=BACKENDS,
        default=None,
        help="override the configured output backend",
    )
    run_parser.set_defaults(func=cmd_run)

    simulate_parser = subparsers.add_parser(
        "simulate",
        help="exercise the virtual gamepad with fake input (no controller needed)",
    )
    simulate_parser.add_argument(
        "--backend", choices=BACKENDS, default=None, help="output backend to test"
    )
    simulate_parser.add_argument(
        "--hold", type=float, default=0.7, help="seconds to hold each input"
    )
    simulate_parser.set_defaults(func=cmd_simulate)

    init_parser = subparsers.add_parser(
        "init-config", help="write a starter config file you can edit"
    )
    init_parser.add_argument("--path", type=Path, default=None)
    init_parser.add_argument("--force", action="store_true", help="overwrite an existing file")
    init_parser.set_defaults(func=cmd_init_config)

    outputs_parser = subparsers.add_parser(
        "outputs", help="show the current mapping and every valid output name"
    )
    outputs_parser.set_defaults(func=cmd_outputs)

    doctor_parser = subparsers.add_parser(
        "doctor", help="check that Bluetooth and the virtual gamepad driver work"
    )
    doctor_parser.set_defaults(func=cmd_doctor)

    driver_parser = subparsers.add_parser(
        "install-driver", help="install the bundled ViGEmBus driver"
    )
    driver_parser.add_argument(
        "--quiet", action="store_true", help="install without the installer UI"
    )
    driver_parser.set_defaults(func=cmd_install_driver)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        return args.func(args, config)
    except KeyboardInterrupt:
        print()
        log.info("stopped")
        return 0
    except (BleError, OutputError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_scan(args: argparse.Namespace, config: Config) -> int:
    timeout = args.seconds or config.device.scan_timeout
    print(f"Scanning for {timeout:.0f}s...")
    found = asyncio.run(
        scan(
            timeout=timeout,
            names=config.device.names,
            addresses=config.device.addresses,
            ride_only=not (args.all or config.device.accept_any_zwift_device),
        )
    )
    if not found:
        print("No Zwift controllers found.")
        print("Press a button to wake the controller, and make sure Zwift is not")
        print("already connected to it. Use --all to include Play/Click hardware.")
        return 1
    for controller in found:
        print(f"  {controller.label()}")
    return 0


def cmd_monitor(args: argparse.Namespace, config: Config) -> int:
    if args.raw:
        logging.getLogger("ridecontroller.ble").setLevel(logging.DEBUG)
        logging.getLogger().setLevel(logging.DEBUG)

    mapper = config.mapper()

    def on_input(device_name: str, controller_input: ControllerInput) -> None:
        pressed = " ".join(sorted(controller_input.buttons)) or "-"
        mapped = " ".join(
            sorted(
                out
                for out in (mapper.outputs_for(b) for b in controller_input.buttons)
                if out != "NONE"
            )
        )
        line = f"{device_name}: {pressed}"
        if controller_input.analog:
            analog = " ".join(
                f"{k}={v}" for k, v in sorted(controller_input.analog.items())
            )
            line += f" | {analog}"
        if mapped:
            line += f" -> {mapped}"
        if args.raw:
            line += f" | button_map=0x{controller_input.raw_button_map:04x}"
        print(line, flush=True)

    bridge = Bridge(config, create_output("null"), mapper=mapper, on_input=on_input)
    print("Connecting... press Ctrl+C to stop.")
    asyncio.run(bridge.run())
    return 0


def cmd_run(args: argparse.Namespace, config: Config) -> int:
    backend = args.backend or config.output.backend
    output = create_output(backend)
    bridge = Bridge(config, output)
    if config.source_path:
        log.info("config: %s", config.source_path)
    else:
        log.info("config: built-in defaults (run `ridecontroller init-config` to change)")
    log.info("output backend: %s", backend)
    asyncio.run(bridge.run())
    return 0


def cmd_simulate(args: argparse.Namespace, config: Config) -> int:
    backend = args.backend or config.output.backend
    mapper = config.mapper()
    output = create_output(backend)
    output.open()
    print(f"Driving the {backend} backend with fake input. Ctrl+C to stop.")
    try:
        for name in RIDE_BUTTON_NAMES:
            target = mapper.outputs_for(name)
            if target == "NONE":
                print(f"  {name:<18} -> (unmapped)")
                continue
            print(f"  {name:<18} -> {target}")
            output.apply(mapper.apply(ControllerInput(buttons=frozenset({name}))))
            time.sleep(args.hold)
            output.apply(mapper.apply(ControllerInput()))
            time.sleep(0.1)

        for name in RIDE_ANALOG_NAMES:
            target = mapper.outputs_for(name)
            if target == "NONE":
                print(f"  {name:<18} -> (unmapped)")
                continue
            print(f"  {name:<18} -> {target} (ramp)")
            for value in list(range(0, 101, 10)) + list(range(100, -1, -10)):
                output.apply(mapper.apply(ControllerInput(analog={name: value})))
                time.sleep(args.hold / 20)
            output.apply(mapper.apply(ControllerInput()))
    finally:
        output.reset()
        output.close()
    print("Done. On Windows, watch the pad move in 'Set up USB game controllers'.")
    return 0


def cmd_init_config(args: argparse.Namespace, config: Config) -> int:
    path = args.path or args.config or default_config_path()
    written = write_default_config(path, overwrite=args.force)
    print(f"Wrote {written}")
    print("Edit it, then run: ridecontroller run")
    return 0


def cmd_outputs(args: argparse.Namespace, config: Config) -> int:
    mapper = config.mapper()
    print("Current mapping")
    print("---------------")
    for name in RIDE_BUTTON_NAMES:
        print(f"  {name:<18} -> {mapper.outputs_for(name)}")
    for name in RIDE_ANALOG_NAMES:
        spec = config.analog.get(name)
        detail = ""
        if spec is not None:
            detail = f"  (deadzone={spec.deadzone} full_scale={spec.full_scale}"
            detail += " inverted)" if spec.invert else ")"
        print(f"  {name:<18} -> {mapper.outputs_for(name)}{detail}")
    print()
    print("Valid button outputs:")
    print("  " + " ".join(BUTTON_OUTPUTS))
    print("Valid analog outputs:")
    print("  " + " ".join(ANALOG_OUTPUTS))
    if config.output.dpad_drives_left_stick:
        print()
        print("The D-pad also drives the left stick (output.dpad_drives_left_stick).")
    return 0


def cmd_doctor(args: argparse.Namespace, config: Config) -> int:
    ok = True
    print(f"RideController {__version__} on {platform.platform()}")
    print(f"Python {sys.version.split()[0]}")

    try:
        import importlib.metadata

        import bleak  # noqa: F401

        try:
            version = importlib.metadata.version("bleak")
        except importlib.metadata.PackageNotFoundError:  # pragma: no cover
            version = "unknown version"
        print(f"  [ok]   bleak {version}")
    except ImportError:
        ok = False
        print("  [FAIL] bleak is not installed  ->  pip install -e .")

    if config.output.backend == "xbox360" or platform.system() == "Windows":
        try:
            import vgamepad  # noqa: F401
        except ImportError:
            ok = False
            print("  [FAIL] vgamepad is not installed  ->  pip install vgamepad")
        except Exception as exc:
            # vgamepad talks to ViGEmBus during import and raises a bare
            # Exception when the driver is absent, so this cannot narrow to
            # ImportError - doing so crashed the very check meant to report it.
            ok = False
            print(f"  [FAIL] vgamepad cannot reach ViGEmBus: {exc}")
            print("         The driver is missing. Install it with:")
            print("           ridecontroller install-driver")
        else:
            print("  [ok]   vgamepad is installed")
            try:
                output = create_output("xbox360")
                output.open()
                output.reset()
                output.close()
                print("  [ok]   virtual Xbox 360 pad created (ViGEmBus is working)")
            except OutputError as exc:
                ok = False
                print(f"  [FAIL] {exc}")
    else:
        print("  [skip] virtual gamepad checks (backend is not xbox360)")

    if platform.system() != "Windows" and config.output.backend == "xbox360":
        print("  [warn] the xbox360 backend needs Windows; use --backend debug here")

    try:
        found = asyncio.run(scan(timeout=min(config.device.scan_timeout, 8.0)))
        if found:
            print(f"  [ok]   found {len(found)} Zwift Ride controller(s):")
            for controller in found:
                print(f"           {controller.label()}")
        else:
            print("  [warn] no Zwift Ride controllers found (is it awake?)")
    except BleError as exc:
        ok = False
        print(f"  [FAIL] {exc}")

    print()
    print("All good." if ok else "Some checks failed - see above.")
    return 0 if ok else 1


def cmd_install_driver(args: argparse.Namespace, config: Config) -> int:
    if platform.system() != "Windows":
        print("error: ViGEmBus is a Windows driver.", file=sys.stderr)
        return 2

    msi = find_installer()
    if msi is None:
        print("Could not find a bundled ViGEmBus installer.", file=sys.stderr)
        print(f"Download and run it from {VIGEMBUS_RELEASES}", file=sys.stderr)
        return 1

    print(f"Installing ViGEmBus from {msi.name}")
    print("Windows will ask for administrator permission.")
    print()

    succeeded, message = describe_exit_code(run_installer(msi, quiet=args.quiet))
    print(message)
    if succeeded:
        print("Check it with: ridecontroller doctor")
        return 0

    print(f"Install it by hand instead: {VIGEMBUS_RELEASES}", file=sys.stderr)
    return 1

"""Wiring: controllers in, merged state out, virtual gamepad updated."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from .ble import BleError, DiscoveredController, RideConnection, scan
from .config import Config
from .mapping import Mapper, OutputState
from .outputs import GamepadOutput
from .protocol import (
    BatteryLevel,
    ControllerInput,
    Disconnect,
    HandshakeResponse,
    Idle,
    Message,
    UnknownMessage,
)

log = logging.getLogger(__name__)

InputListener = Callable[[str, ControllerInput], None]


class InputMerger:
    """Combines snapshots from the Ride's two halves into one state.

    Each half reports the full button map, with bits for buttons it does not
    own reading as "released", so a union across devices is exactly right.
    """

    def __init__(self) -> None:
        self._per_device: dict[str, ControllerInput] = {}

    def update(self, address: str, controller_input: ControllerInput) -> ControllerInput:
        self._per_device[address] = controller_input
        return self.merged()

    def forget(self, address: str) -> ControllerInput:
        self._per_device.pop(address, None)
        return self.merged()

    def merged(self) -> ControllerInput:
        buttons: set[str] = set()
        analog: dict[str, int] = {}
        for state in self._per_device.values():
            buttons |= state.buttons
            for name, value in state.analog.items():
                if abs(value) > abs(analog.get(name, 0)):
                    analog[name] = value
        return ControllerInput(buttons=frozenset(buttons), analog=analog)


class Bridge:
    """Connects to the controllers and drives a gamepad backend."""

    def __init__(
        self,
        config: Config,
        output: GamepadOutput,
        *,
        mapper: Mapper | None = None,
        on_input: InputListener | None = None,
    ) -> None:
        self.config = config
        self.output = output
        self.mapper = mapper if mapper is not None else config.mapper()
        self.on_input = on_input
        self.merger = InputMerger()
        self.battery: dict[str, int] = {}
        self._last_output: OutputState | None = None

    async def discover(self) -> list[DiscoveredController]:
        device_cfg = self.config.device
        found = await scan(
            timeout=device_cfg.scan_timeout,
            names=device_cfg.names,
            addresses=device_cfg.addresses,
            ride_only=not device_cfg.accept_any_zwift_device,
        )
        if not found:
            raise BleError(
                "No Zwift Ride controller found. Check that:\n"
                "  - the controller is awake (press a button) and charged\n"
                "  - the Zwift app or Companion is not already connected to it\n"
                "  - Bluetooth is on and this machine has a BLE adapter\n"
                "Run `ridecontroller scan --all` to see every Zwift device nearby."
            )
        return found[: device_cfg.max_devices]

    async def run(self, stop: asyncio.Event | None = None) -> None:
        """Scan, connect, and pump input until *stop* is set."""
        stop = stop if stop is not None else asyncio.Event()
        controllers = await self.discover()
        for controller in controllers:
            log.info("using %s", controller.label())

        self.output.open()
        self._apply(self.merger.merged())

        connections = [
            RideConnection(
                controller,
                self._handle_message,
                analog_encoding=self.config.protocol.analog_encoding,
                reconnect=self.config.device.reconnect,
                on_state_change=self._handle_connection_state,
            )
            for controller in controllers
        ]

        tasks = [asyncio.ensure_future(c.run(stop)) for c in connections]
        try:
            await asyncio.gather(*tasks)
        finally:
            # One failing half must not leave the other running, or its buttons
            # stuck down on a gamepad nobody is updating any more.
            stop.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                self.output.reset()
            finally:
                self.output.close()

    # -- callbacks ---------------------------------------------------------

    def _handle_message(self, connection: RideConnection, message: Message) -> None:
        if isinstance(message, ControllerInput):
            if self.on_input is not None:
                self.on_input(connection.name, message)
            self._apply(self.merger.update(connection.address, message))
        elif isinstance(message, BatteryLevel):
            if self.battery.get(connection.address) != message.percent:
                self.battery[connection.address] = message.percent
                log.info("%s: battery %d%%", connection.name, message.percent)
        elif isinstance(message, HandshakeResponse):
            log.debug("%s: handshake complete", connection.name)
        elif isinstance(message, Disconnect):
            log.warning(
                "%s: controller ended the session (did Zwift take it over?)",
                connection.name,
            )
        elif isinstance(message, UnknownMessage):
            log.debug(
                "%s: unhandled message type 0x%02x (%s)",
                connection.name,
                message.message_type,
                message.payload.hex(" "),
            )
        elif isinstance(message, Idle):
            pass

    def _handle_connection_state(
        self, connection: RideConnection, connected: bool
    ) -> None:
        if not connected:
            # Never leave a button stuck down because a half dropped out.
            self._apply(self.merger.forget(connection.address))

    def _apply(self, merged: ControllerInput) -> None:
        state = self.mapper.apply(merged)
        if state == self._last_output:
            return
        self._last_output = state
        self.output.apply(state)

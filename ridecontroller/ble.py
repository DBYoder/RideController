"""BLE scanning and connection handling for Zwift Ride controllers.

``bleak`` is imported lazily so that the protocol and mapping layers (and their
tests) work on machines without a Bluetooth stack.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable

from .constants import (
    ASYNC_CHARACTERISTIC_UUID,
    CUSTOM_SERVICE_UUIDS,
    DEVICE_TYPES,
    RIDE_DEVICE_TYPES,
    RIDE_ON,
    SYNC_RX_CHARACTERISTIC_UUID,
    SYNC_TX_CHARACTERISTIC_UUID,
    ZWIFT_COMPANY_ID,
)
from .protocol import Message, ProtocolError, decode_packet

log = logging.getLogger(__name__)

MessageHandler = Callable[["RideConnection", Message], None | Awaitable[None]]


class BleError(RuntimeError):
    """Raised when the Bluetooth stack is unusable or a device cannot be reached."""


def _import_bleak() -> Any:
    try:
        import bleak
    except ImportError as exc:  # pragma: no cover - depends on install
        raise BleError(
            "bleak is not installed. Install the project dependencies with "
            "`pip install -e .` (or `pip install bleak`)."
        ) from exc
    return bleak


@dataclass(frozen=True)
class DiscoveredController:
    """A Zwift controller seen during a scan."""

    address: str
    name: str
    device_type: str | None = None
    rssi: int | None = None
    ble_device: Any = field(default=None, compare=False, repr=False)

    @property
    def is_ride(self) -> bool:
        return self.device_type in RIDE_DEVICE_TYPES

    def label(self) -> str:
        kind = self.device_type or "unknown"
        rssi = f"{self.rssi} dBm" if self.rssi is not None else "?"
        return f"{self.name or '(unnamed)'} [{self.address}] type={kind} rssi={rssi}"


def classify_advertisement(name: str, manufacturer_data: dict, service_uuids: Iterable[str]):
    """Work out whether an advertisement is a Zwift controller, and which one.

    Returns ``(is_zwift, device_type)``. ``device_type`` may be ``None`` when a
    device is recognisable as Zwift hardware but does not tell us its model.
    """
    uuids = {str(u).lower() for u in service_uuids or ()}
    has_service = bool(uuids & {u.lower() for u in CUSTOM_SERVICE_UUIDS})

    device_type = None
    payload = (manufacturer_data or {}).get(ZWIFT_COMPANY_ID)
    if payload:
        device_type = DEVICE_TYPES.get(payload[0])

    lowered = (name or "").lower()
    name_looks_zwift = "zwift" in lowered
    if device_type is None and name_looks_zwift and "ride" in lowered:
        device_type = "ride_left"  # good enough to attempt a connection

    is_zwift = has_service or payload is not None or name_looks_zwift
    return is_zwift, device_type


async def scan(
    *,
    timeout: float = 12.0,
    names: Iterable[str] = (),
    addresses: Iterable[str] = (),
    ride_only: bool = True,
) -> list[DiscoveredController]:
    """Scan for Zwift controllers.

    *names* are case-insensitive substrings; *addresses* are exact matches.
    When *ride_only* is set, Play/Click hardware is filtered out.
    """
    bleak = _import_bleak()
    name_filters = [n.lower() for n in names if n]
    address_filters = {a.lower() for a in addresses if a}

    try:
        # Deliberately unfiltered: some adapters only surface the Zwift service
        # UUID in the scan response, so we match on manufacturer data and name
        # as well (see classify_advertisement).
        found = await bleak.BleakScanner.discover(timeout=timeout, return_adv=True)
    except Exception as exc:  # pragma: no cover - hardware dependent
        raise BleError(f"Bluetooth scan failed: {exc}") from exc

    results: list[DiscoveredController] = []
    for device, adv in found.values():
        name = adv.local_name or device.name or ""
        is_zwift, device_type = classify_advertisement(
            name, adv.manufacturer_data, adv.service_uuids
        )
        if not is_zwift:
            continue
        if ride_only and device_type not in RIDE_DEVICE_TYPES:
            continue
        if address_filters and device.address.lower() not in address_filters:
            continue
        if name_filters and not any(f in name.lower() for f in name_filters):
            continue
        results.append(
            DiscoveredController(
                address=device.address,
                name=name,
                device_type=device_type,
                rssi=adv.rssi,
                ble_device=device,
            )
        )

    results.sort(key=lambda c: (-(c.rssi or -999), c.address))
    return results


class RideConnection:
    """One connected controller: handshake, notifications, reconnection."""

    def __init__(
        self,
        controller: DiscoveredController,
        handler: MessageHandler,
        *,
        analog_encoding: str = "zigzag",
        reconnect: bool = True,
        on_state_change: Callable[["RideConnection", bool], None] | None = None,
    ) -> None:
        self.controller = controller
        self.handler = handler
        self.analog_encoding = analog_encoding
        self.reconnect = reconnect
        self.on_state_change = on_state_change
        self.connected = False
        self._disconnected = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._first_session = True

    @property
    def address(self) -> str:
        return self.controller.address

    @property
    def name(self) -> str:
        return self.controller.name or self.controller.address

    async def run(self, stop: asyncio.Event) -> None:
        """Stay connected until *stop* is set, reconnecting as configured."""
        backoff = 1.0
        while not stop.is_set():
            try:
                await self._session(stop)
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("%s: %s", self.name, exc)
            finally:
                self._set_connected(False)

            if stop.is_set() or not self.reconnect:
                return
            log.info("%s: reconnecting in %.0fs", self.name, backoff)
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff)
                return  # stop was set while waiting
            except asyncio.TimeoutError:
                backoff = min(backoff * 2, 30.0)

    async def _session(self, stop: asyncio.Event) -> None:
        bleak = _import_bleak()
        self._loop = asyncio.get_running_loop()
        self._disconnected = asyncio.Event()

        target = self.controller.ble_device or self.controller.address
        if self.controller.ble_device is None or not self._first_session:
            # The BLEDevice from the original scan goes stale once the link has
            # dropped, so re-resolve it before every reconnect.
            found = await bleak.BleakScanner.find_device_by_address(
                self.controller.address, timeout=10.0
            )
            if found is not None:
                target = found
        self._first_session = False

        log.info("%s: connecting", self.name)
        async with bleak.BleakClient(
            target, disconnected_callback=self._on_disconnect
        ) as client:
            service = self._find_service(client)
            chars = {
                key: service.get_characteristic(uuid)
                for key, uuid in (
                    ("async", ASYNC_CHARACTERISTIC_UUID),
                    ("sync_rx", SYNC_RX_CHARACTERISTIC_UUID),
                    ("sync_tx", SYNC_TX_CHARACTERISTIC_UUID),
                )
            }
            missing = [key for key, char in chars.items() if char is None]
            if missing:
                raise BleError(
                    f"{self.name}: controller is missing characteristics {missing}. "
                    "Update the controller firmware in the Zwift Companion app."
                )

            await client.start_notify(chars["async"], self._on_notify)
            await client.start_notify(chars["sync_tx"], self._on_notify)
            await client.write_gatt_char(chars["sync_rx"], RIDE_ON, response=False)

            self._set_connected(True)
            log.info("%s: connected", self.name)

            stop_task = asyncio.ensure_future(stop.wait())
            disconnect_task = asyncio.ensure_future(self._disconnected.wait())
            try:
                await asyncio.wait(
                    {stop_task, disconnect_task}, return_when=asyncio.FIRST_COMPLETED
                )
            finally:
                for task in (stop_task, disconnect_task):
                    task.cancel()

            if stop.is_set():
                try:
                    await client.stop_notify(chars["async"])
                    await client.stop_notify(chars["sync_tx"])
                except Exception:  # pragma: no cover - best effort on shutdown
                    pass

    def _find_service(self, client: Any) -> Any:
        for uuid in CUSTOM_SERVICE_UUIDS:
            service = client.services.get_service(uuid)
            if service is not None:
                return service
        raise BleError(
            f"{self.name}: no Zwift service found. If this is a Zwift Ride, update "
            "its firmware in the Zwift Companion app, and make sure the Zwift app "
            "is not already connected to it."
        )

    def _on_disconnect(self, _client: Any) -> None:
        log.info("%s: disconnected", self.name)
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._disconnected.set)
        else:  # pragma: no cover - defensive
            self._disconnected.set()

    def _on_notify(self, _characteristic: Any, data: bytearray) -> None:
        if log.isEnabledFor(logging.DEBUG):
            log.debug("%s: rx %s", self.name, bytes(data).hex(" "))
        try:
            message = decode_packet(bytes(data), analog_encoding=self.analog_encoding)
        except ProtocolError as exc:
            log.debug("%s: %s (%s)", self.name, exc, bytes(data).hex(" "))
            return
        if message is None:
            return
        result = self.handler(self, message)
        if asyncio.iscoroutine(result):
            asyncio.ensure_future(result)

    def _set_connected(self, connected: bool) -> None:
        if connected == self.connected:
            return
        self.connected = connected
        if self.on_state_change is not None:
            self.on_state_change(self, connected)

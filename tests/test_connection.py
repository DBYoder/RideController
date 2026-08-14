"""Integration tests for RideConnection against a fake bleak backend."""

from __future__ import annotations

import asyncio
import types

import pytest

from ridecontroller import ble
from ridecontroller import bridge as bridge_module
from ridecontroller.ble import BleError, DiscoveredController, RideConnection
from ridecontroller.bridge import Bridge
from ridecontroller.config import Config
from ridecontroller.mapping import NEUTRAL
from ridecontroller.outputs.base import GamepadOutput
from ridecontroller.constants import (
    ASYNC_CHARACTERISTIC_UUID,
    RIDE_ON,
    SYNC_RX_CHARACTERISTIC_UUID,
    SYNC_TX_CHARACTERISTIC_UUID,
    ZWIFT_RIDE_SERVICE_UUID,
)
from ridecontroller.protocol import ControllerInput, encode_keypad_status


class FakeCharacteristic:
    def __init__(self, uuid: str):
        self.uuid = uuid


class FakeService:
    def __init__(self, uuid: str, characteristics: list[str]):
        self.uuid = uuid
        self._characteristics = {c.lower(): FakeCharacteristic(c) for c in characteristics}

    def get_characteristic(self, uuid: str):
        return self._characteristics.get(str(uuid).lower())


class FakeServiceCollection:
    def __init__(self, services: list[FakeService]):
        self._services = {s.uuid.lower(): s for s in services}

    def get_service(self, uuid: str):
        return self._services.get(str(uuid).lower())


class FakeClient:
    """Records what the connection does and lets tests push notifications."""

    instances: list["FakeClient"] = []

    services_template: list[FakeService] = []

    def __init__(self, target, disconnected_callback=None, **kwargs):
        self.target = target
        self.disconnected_callback = disconnected_callback
        self.services = FakeServiceCollection(list(self.services_template))
        self.notify_callbacks: dict[str, object] = {}
        self.writes: list[tuple[str, bytes]] = []
        self.stopped: list[str] = []
        self.connected = False
        self.handshake_done = asyncio.Event()
        FakeClient.instances.append(self)

    async def __aenter__(self):
        self.connected = True
        return self

    async def __aexit__(self, *exc_info):
        self.connected = False

    async def start_notify(self, characteristic, callback):
        self.notify_callbacks[characteristic.uuid.lower()] = callback

    async def stop_notify(self, characteristic):
        self.stopped.append(characteristic.uuid.lower())

    async def write_gatt_char(self, characteristic, data, response=False):
        self.writes.append((characteristic.uuid.lower(), bytes(data)))
        if bytes(data) == RIDE_ON:
            self.handshake_done.set()

    def push(self, payload: bytes, characteristic: str = ASYNC_CHARACTERISTIC_UUID):
        callback = self.notify_callbacks[characteristic.lower()]
        callback(FakeCharacteristic(characteristic), bytearray(payload))

    def drop(self):
        if self.disconnected_callback is not None:
            self.disconnected_callback(self)


def ride_services() -> list[FakeService]:
    return [
        FakeService(
            ZWIFT_RIDE_SERVICE_UUID,
            [
                ASYNC_CHARACTERISTIC_UUID,
                SYNC_RX_CHARACTERISTIC_UUID,
                SYNC_TX_CHARACTERISTIC_UUID,
            ],
        )
    ]


class FakeScanner:
    """Re-resolution on reconnect finds nothing, so the cached device is reused."""

    lookups: list[str] = []

    @staticmethod
    async def find_device_by_address(address, timeout=10.0):
        FakeScanner.lookups.append(address)
        return None


@pytest.fixture
def fake_bleak(monkeypatch):
    FakeClient.instances = []
    FakeClient.services_template = ride_services()
    FakeScanner.lookups = []
    module = types.SimpleNamespace(BleakClient=FakeClient, BleakScanner=FakeScanner)
    monkeypatch.setattr(ble, "_import_bleak", lambda: module)
    return module


def make_connection(handler, **kwargs) -> RideConnection:
    controller = DiscoveredController(
        address="AA:BB:CC:DD:EE:FF",
        name="Zwift Ride",
        device_type="ride_left",
        ble_device=object(),
    )
    return RideConnection(controller, handler, **kwargs)


async def wait_for(predicate, timeout=2.0):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), timeout)


@pytest.mark.asyncio
async def test_session_handshakes_subscribes_and_decodes_input(fake_bleak):
    received = []
    states = []
    connection = make_connection(
        lambda conn, msg: received.append(msg),
        on_state_change=lambda conn, up: states.append(up),
    )
    stop = asyncio.Event()
    task = asyncio.ensure_future(connection.run(stop))

    await wait_for(lambda: FakeClient.instances and FakeClient.instances[0].connected)
    client = FakeClient.instances[0]
    await asyncio.wait_for(client.handshake_done.wait(), 2.0)

    # Handshake goes to SYNC_RX, notifications are enabled on ASYNC and SYNC_TX.
    assert client.writes == [(SYNC_RX_CHARACTERISTIC_UUID.lower(), RIDE_ON)]
    assert set(client.notify_callbacks) == {
        ASYNC_CHARACTERISTIC_UUID.lower(),
        SYNC_TX_CHARACTERISTIC_UUID.lower(),
    }
    assert connection.connected and states == [True]

    client.push(encode_keypad_status({"a", "dpad_up"}, {"left_paddle": 80}))
    await wait_for(lambda: received)
    message = received[-1]
    assert isinstance(message, ControllerInput)
    assert message.buttons == frozenset({"a", "dpad_up"})
    assert message.analog == {"left_paddle": 80}

    stop.set()
    await asyncio.wait_for(task, 2.0)
    assert connection.connected is False
    assert states == [True, False]
    assert len(client.stopped) == 2


@pytest.mark.asyncio
async def test_handshake_response_on_the_indicate_characteristic(fake_bleak):
    received = []
    connection = make_connection(lambda conn, msg: received.append(msg))
    stop = asyncio.Event()
    task = asyncio.ensure_future(connection.run(stop))

    await wait_for(lambda: FakeClient.instances and FakeClient.instances[0].connected)
    client = FakeClient.instances[0]
    await asyncio.wait_for(client.handshake_done.wait(), 2.0)
    client.push(RIDE_ON + b"\x01\x03" + b"\x11\x22", SYNC_TX_CHARACTERISTIC_UUID)
    await wait_for(lambda: received)
    assert received[-1].public_key == b"\x11\x22"

    stop.set()
    await asyncio.wait_for(task, 2.0)


@pytest.mark.asyncio
async def test_undecodable_notifications_are_dropped_not_raised(fake_bleak):
    received = []
    connection = make_connection(lambda conn, msg: received.append(msg))
    stop = asyncio.Event()
    task = asyncio.ensure_future(connection.run(stop))

    await wait_for(lambda: FakeClient.instances and FakeClient.instances[0].connected)
    client = FakeClient.instances[0]
    await asyncio.wait_for(client.handshake_done.wait(), 2.0)

    client.push(b"\x23")  # keypad status with no button map
    client.push(encode_keypad_status({"b"}))
    await wait_for(lambda: received)
    assert [m.buttons for m in received] == [frozenset({"b"})]

    stop.set()
    await asyncio.wait_for(task, 2.0)


@pytest.mark.asyncio
async def test_a_dropped_link_reconnects(fake_bleak):
    connection = make_connection(lambda conn, msg: None, reconnect=True)
    stop = asyncio.Event()
    task = asyncio.ensure_future(connection.run(stop))

    await wait_for(lambda: FakeClient.instances and FakeClient.instances[0].connected)
    FakeClient.instances[0].drop()

    await wait_for(lambda: len(FakeClient.instances) == 2, timeout=5.0)
    await wait_for(lambda: FakeClient.instances[1].connected)
    # The stale BLEDevice is re-resolved before the second attempt.
    assert FakeScanner.lookups == ["AA:BB:CC:DD:EE:FF"]

    stop.set()
    await asyncio.wait_for(task, 3.0)


@pytest.mark.asyncio
async def test_without_reconnect_a_dropped_link_ends_the_task(fake_bleak):
    connection = make_connection(lambda conn, msg: None, reconnect=False)
    stop = asyncio.Event()
    task = asyncio.ensure_future(connection.run(stop))

    await wait_for(lambda: FakeClient.instances and FakeClient.instances[0].connected)
    FakeClient.instances[0].drop()

    await asyncio.wait_for(task, 2.0)
    assert len(FakeClient.instances) == 1


@pytest.mark.asyncio
async def test_missing_zwift_service_is_reported(fake_bleak):
    FakeClient.services_template = [FakeService("0000180f-0000-1000-8000-00805f9b34fb", [])]
    connection = make_connection(lambda conn, msg: None, reconnect=False)
    with pytest.raises(BleError, match="no Zwift service"):
        await connection._session(asyncio.Event())


@pytest.mark.asyncio
async def test_missing_characteristics_are_reported(fake_bleak):
    FakeClient.services_template = [
        FakeService(ZWIFT_RIDE_SERVICE_UUID, [ASYNC_CHARACTERISTIC_UUID])
    ]
    connection = make_connection(lambda conn, msg: None, reconnect=False)
    with pytest.raises(BleError, match="missing characteristics"):
        await connection._session(asyncio.Event())


@pytest.mark.asyncio
async def test_run_swallows_session_errors(fake_bleak):
    FakeClient.services_template = []
    connection = make_connection(lambda conn, msg: None, reconnect=False)
    await asyncio.wait_for(connection.run(asyncio.Event()), 2.0)
    assert connection.connected is False


class RecordingOutput(GamepadOutput):
    name = "recording"

    def __init__(self):
        self.states = []
        self.closed = False

    def apply(self, state):
        self.states.append(state)

    def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_bridge_drives_the_gamepad_from_a_connected_controller(
    fake_bleak, monkeypatch
):
    """Scan -> connect -> handshake -> decode -> mapped gamepad state."""
    controller = DiscoveredController(
        address="AA:BB", name="Zwift Ride", device_type="ride_left", ble_device=object()
    )

    async def fake_scan(**kwargs):
        return [controller]

    monkeypatch.setattr(bridge_module, "scan", fake_scan)

    output = RecordingOutput()
    bridge = Bridge(Config(), output)
    stop = asyncio.Event()
    task = asyncio.ensure_future(bridge.run(stop))

    await wait_for(lambda: FakeClient.instances and FakeClient.instances[0].connected)
    client = FakeClient.instances[0]
    await asyncio.wait_for(client.handshake_done.wait(), 2.0)

    client.push(encode_keypad_status({"a"}, {"right_paddle": 100}))
    await wait_for(lambda: output.states[-1].buttons == frozenset({"A"}))
    assert output.states[-1].right_trigger == 255

    client.push(encode_keypad_status(set()))
    await wait_for(lambda: output.states[-1] == NEUTRAL)

    stop.set()
    await asyncio.wait_for(task, 2.0)
    assert output.states[-1] == NEUTRAL
    assert output.closed


@pytest.mark.asyncio
async def test_bridge_reports_when_nothing_is_found(fake_bleak, monkeypatch):
    async def fake_scan(**kwargs):
        return []

    monkeypatch.setattr(bridge_module, "scan", fake_scan)
    with pytest.raises(BleError, match="No Zwift Ride controller found"):
        await Bridge(Config(), RecordingOutput()).run(asyncio.Event())

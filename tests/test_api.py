"""Tests for the Alpicool BLE protocol and connection handling."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from bleak.exc import BleakError
import pytest

from custom_components.alpicool_ble import api as api_module
from custom_components.alpicool_ble.api import FridgeApi
from custom_components.alpicool_ble.const import (
    FRIDGE_RW_CHARACTERISTIC_UUID,
    Request,
)

ADDRESS = "AA:BB:CC:DD:EE:FF"

# A single zone status payload as sent by the fridge (18 bytes).
SINGLE_ZONE_PAYLOAD = bytes(
    [
        0,  # locked
        1,  # powered_on
        0,  # run_mode
        2,  # bat_saver
        0xFB,  # left_target -5
        20,  # temp_max
        0xEC,  # temp_min -20
        1,  # left_ret_diff
        0,  # start_delay
        0,  # unit -> Celsius
        0,
        0,
        0,
        0,  # tc_*
        0xFD,  # left_current -3
        87,  # bat_percent
        12,  # bat_vol_int
        6,  # bat_vol_dec
    ]
)

# A dual zone payload adds 10 more bytes.
DUAL_ZONE_PAYLOAD = SINGLE_ZONE_PAYLOAD + bytes(
    [
        0xF6,  # right_target -10
        0,
        0,
        1,  # right_ret_diff
        0,
        0,
        0,
        0,  # right tc_*
        0xF8,  # right_current -8
        1,  # running_status
    ]
)


class FakeClient:
    """Minimal stand-in for a connected BleakClient."""

    def __init__(self, mtu_size: int = 23, is_connected: bool = True) -> None:
        """Record what gets written instead of touching a real adapter."""
        self.mtu_size = mtu_size
        self.is_connected = is_connected
        self.writes: list[bytes] = []
        self.write_order: list[str] = []

    async def write_gatt_char(self, uuid, data, response=False):
        """Record one GATT write."""
        assert uuid == FRIDGE_RW_CHARACTERISTIC_UUID
        self.writes.append(bytes(data))


@pytest.fixture
def fridge() -> FridgeApi:
    """Return an API instance that is not bound to a real hass or adapter."""
    return FridgeApi(MagicMock(), ADDRESS)


@pytest.fixture(autouse=True)
def _no_chunk_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the inter-chunk pause out of the test runtime."""
    monkeypatch.setattr(api_module, "WRITE_CHUNK_DELAY", 0)


# --- Packet building -------------------------------------------------------


def test_bind_and_query_packets_are_fixed(fridge: FridgeApi) -> None:
    """The two handshake packets are sent verbatim."""
    assert fridge._build_packet(Request.BIND, b"\x01") == b"\xfe\xfe\x03\x00\x01\xff"
    assert fridge._build_packet(Request.QUERY, b"\x02") == b"\xfe\xfe\x03\x01\x02\x00"


def test_built_packet_carries_length_and_checksum(fridge: FridgeApi) -> None:
    """Dynamic packets get a length byte and a big endian checksum."""
    packet = fridge._build_packet(Request.SET_LEFT, bytes([0xFB]))

    assert packet[:2] == b"\xfe\xfe"
    assert packet[2] == len(packet) - 3
    assert packet[3] == Request.SET_LEFT
    assert int.from_bytes(packet[-2:], "big") == sum(packet[:-2]) & 0xFFFF


async def test_set_temperature_encodes_negative_values(fridge: FridgeApi) -> None:
    """A negative target is sent as an unsigned byte."""
    fridge._client = FakeClient(mtu_size=247)

    await fridge.async_set_temperature("left", -5)

    assert fridge._client.writes[0][3] == Request.SET_LEFT
    assert fridge._client.writes[0][4] == 0xFB


# --- Status decoding -------------------------------------------------------


def test_decode_single_zone_status(fridge: FridgeApi) -> None:
    """Signed fields survive the round trip and no right zone is invented."""
    fridge._decode_status(SINGLE_ZONE_PAYLOAD)

    assert fridge.status["left_target"] == -5
    assert fridge.status["left_current"] == -3
    assert fridge.status["temp_min"] == -20
    assert fridge.status["bat_percent"] == 87
    assert "right_current" not in fridge.status


def test_decode_dual_zone_status(fridge: FridgeApi) -> None:
    """The second zone is decoded when the payload is long enough."""
    fridge._decode_status(DUAL_ZONE_PAYLOAD)

    assert fridge.status["right_target"] == -10
    assert fridge.status["right_current"] == -8


def test_decode_short_payload_does_not_raise(fridge: FridgeApi) -> None:
    """A truncated payload is ignored rather than crashing the handler."""
    fridge._decode_status(b"\x00\x01")

    assert "left_target" not in fridge.status


def test_notification_handler_reassembles_fragments(fridge: FridgeApi) -> None:
    """A status split across two notifications is parsed once complete."""
    packet = bytearray(b"\xfe\xfe")
    packet.append(len(SINGLE_ZONE_PAYLOAD) + 1)
    packet.append(Request.QUERY)
    packet.extend(SINGLE_ZONE_PAYLOAD)

    fridge._notification_handler(None, bytearray(packet[:10]))
    assert fridge.status == {}

    fridge._notification_handler(None, bytearray(packet[10:]))
    assert fridge.status["left_target"] == -5
    assert fridge._notification_buffer == b""


def test_notification_handler_skips_preamble(fridge: FridgeApi) -> None:
    """Bytes before the header are discarded instead of shifting the payload."""
    packet = bytearray(b"\x00\x99\xfe\xfe")
    packet.append(len(SINGLE_ZONE_PAYLOAD) + 1)
    packet.append(Request.QUERY)
    packet.extend(SINGLE_ZONE_PAYLOAD)

    fridge._notification_handler(None, bytearray(packet))

    assert fridge.status["left_target"] == -5


# --- Fahrenheit ------------------------------------------------------------


def test_is_fahrenheit_follows_unit_byte(fridge: FridgeApi) -> None:
    """The unit byte decides, and Celsius is assumed when it is missing."""
    assert fridge.is_fahrenheit is False

    fridge.status["unit"] = 1
    assert fridge.is_fahrenheit is True

    fridge.status["unit"] = 0
    assert fridge.is_fahrenheit is False


# --- Chunked writes (issue #20) -------------------------------------------


async def test_long_packet_is_split_at_the_default_att_size(
    fridge: FridgeApi,
) -> None:
    """With an unnegotiated MTU a long packet goes out in 20 byte chunks."""
    fridge._client = FakeClient(mtu_size=23)
    packet = bytes(range(32))

    await fridge._send_raw(packet)

    assert fridge._client.writes == [packet[:20], packet[20:]]


async def test_long_packet_uses_the_negotiated_mtu(fridge: FridgeApi) -> None:
    """A larger MTU means the packet still goes out in one write."""
    fridge._client = FakeClient(mtu_size=247)
    packet = bytes(range(32))

    await fridge._send_raw(packet)

    assert fridge._client.writes == [packet]


async def test_short_packet_is_written_once(fridge: FridgeApi) -> None:
    """Packets that fit are not touched."""
    fridge._client = FakeClient(mtu_size=23)

    await fridge._send_raw(b"\xfe\xfe\x03\x01\x02\x00")

    assert fridge._client.writes == [b"\xfe\xfe\x03\x01\x02\x00"]


async def test_unknown_mtu_falls_back_to_the_safe_size(fridge: FridgeApi) -> None:
    """Backends that do not expose an MTU get the conservative 20 bytes."""
    client = FakeClient()
    client.mtu_size = None
    fridge._client = client

    await fridge._send_raw(bytes(range(25)))

    assert [len(w) for w in client.writes] == [20, 5]


async def test_set_values_is_chunked_for_dual_zone_fridges(
    fridge: FridgeApi,
) -> None:
    """The SET packet that failed in issue #20 now goes out as two writes."""
    fridge._decode_status(DUAL_ZONE_PAYLOAD)
    fridge._client = FakeClient(mtu_size=23)

    await fridge.async_set_values({"powered_on": False})

    assert len(fridge._client.writes) == 2
    rebuilt = b"".join(fridge._client.writes)
    assert len(rebuilt) > 20
    assert rebuilt[:2] == b"\xfe\xfe"
    assert int.from_bytes(rebuilt[-2:], "big") == sum(rebuilt[:-2]) & 0xFFFF
    # powered_on is the second payload byte after header, length and command.
    assert rebuilt[5] == 0


async def test_send_raw_is_serialised(fridge: FridgeApi) -> None:
    """Two concurrent sends do not interleave their chunks."""
    client = FakeClient(mtu_size=23)
    fridge._client = client

    original = client.write_gatt_char

    async def slow_write(uuid, data, response=False):
        await asyncio.sleep(0)
        await original(uuid, data, response)

    client.write_gatt_char = slow_write

    first = bytes([1] * 40)
    second = bytes([2] * 40)
    await asyncio.gather(fridge._send_raw(first), fridge._send_raw(second))

    assert b"".join(client.writes) in (first + second, second + first)


async def test_send_raw_does_nothing_while_disconnected(fridge: FridgeApi) -> None:
    """Nothing is written when there is no connection."""
    fridge._client = FakeClient(is_connected=False)

    await fridge._send_raw(b"\xfe\xfe\x03\x01\x02\x00")

    assert fridge._client.writes == []


async def test_send_raw_without_a_client_is_a_noop(fridge: FridgeApi) -> None:
    """A never-connected API does not raise on send."""
    await fridge._send_raw(b"\xfe\xfe\x03\x01\x02\x00")

    assert fridge.is_connected is False


# --- Connection handling (issues #16 and #19) ------------------------------


async def test_connect_waits_for_a_ble_device(fridge: FridgeApi) -> None:
    """Without a BLEDevice from Home Assistant no connection is attempted."""
    with (
        patch.object(
            api_module.bluetooth, "async_ble_device_from_address", return_value=None
        ),
        patch.object(api_module, "establish_connection") as establish,
    ):
        assert await fridge.connect() is False

    establish.assert_not_called()


async def test_connect_uses_establish_connection_with_a_fresh_device(
    fridge: FridgeApi,
) -> None:
    """A freshly resolved BLEDevice is handed to bleak_retry_connector."""
    device = MagicMock(name="BLEDevice")
    client = MagicMock()
    client.is_connected = True
    client.start_notify = AsyncMock()
    char = MagicMock()
    char.uuid = FRIDGE_RW_CHARACTERISTIC_UUID
    char.properties = ["write-without-response"]
    service = MagicMock()
    service.characteristics = [char]
    client.services = [service]

    with (
        patch.object(
            api_module.bluetooth, "async_ble_device_from_address", return_value=device
        ),
        patch.object(
            api_module, "establish_connection", AsyncMock(return_value=client)
        ) as establish,
    ):
        assert await fridge.connect(is_reconnect=True) is True

    assert establish.await_args.args[1] is device
    assert fridge._client is client
    assert fridge._write_requires_response is False
    client.start_notify.assert_awaited_once()


def _connected_client() -> MagicMock:
    """Return a client mock that passes the characteristic discovery."""
    client = MagicMock()
    client.is_connected = True
    client.start_notify = AsyncMock()
    char = MagicMock()
    char.uuid = FRIDGE_RW_CHARACTERISTIC_UUID
    char.properties = ["write-without-response"]
    service = MagicMock()
    service.characteristics = [char]
    client.services = [service]
    return client


async def test_retries_re_resolve_the_ble_device(fridge: FridgeApi) -> None:
    """Issue #19: a retry must not reuse the BLEDevice that just failed."""
    stale = MagicMock(name="stale")
    fresh = MagicMock(name="fresh")

    with (
        patch.object(
            api_module.bluetooth,
            "async_ble_device_from_address",
            side_effect=[stale, fresh],
        ),
        patch.object(
            api_module,
            "establish_connection",
            AsyncMock(return_value=_connected_client()),
        ) as establish,
    ):
        assert await fridge.connect(is_reconnect=True) is True
        refresh = establish.await_args.kwargs["ble_device_callback"]

        assert refresh() is fresh


async def test_device_refresh_falls_back_to_the_known_device(
    fridge: FridgeApi,
) -> None:
    """The refresh callback never hands bleak_retry_connector a None device."""
    device = MagicMock(name="device")

    with (
        patch.object(
            api_module.bluetooth,
            "async_ble_device_from_address",
            side_effect=[device, None],
        ),
        patch.object(
            api_module,
            "establish_connection",
            AsyncMock(return_value=_connected_client()),
        ) as establish,
    ):
        assert await fridge.connect(is_reconnect=True) is True

        assert establish.await_args.kwargs["ble_device_callback"]() is device


async def test_connect_reports_failure_instead_of_raising(fridge: FridgeApi) -> None:
    """A refused connection is reported, not propagated."""
    with (
        patch.object(
            api_module.bluetooth,
            "async_ble_device_from_address",
            return_value=MagicMock(),
        ),
        patch.object(
            api_module,
            "establish_connection",
            AsyncMock(side_effect=BleakError("no slot")),
        ),
    ):
        assert await fridge.connect() is False

    assert fridge._client is None


async def test_connect_picks_write_with_response_when_needed(
    fridge: FridgeApi,
) -> None:
    """Devices that only offer plain writes get response=True."""
    client = MagicMock()
    client.is_connected = True
    client.start_notify = AsyncMock()
    char = MagicMock()
    char.uuid = FRIDGE_RW_CHARACTERISTIC_UUID.upper()
    char.properties = ["write"]
    service = MagicMock()
    service.characteristics = [char]
    client.services = [service]

    with (
        patch.object(
            api_module.bluetooth,
            "async_ble_device_from_address",
            return_value=MagicMock(),
        ),
        patch.object(
            api_module, "establish_connection", AsyncMock(return_value=client)
        ),
    ):
        assert await fridge.connect(is_reconnect=True) is True

    assert fridge._write_requires_response is True


async def test_advertisement_wakes_the_reconnect_wait(
    fridge: FridgeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seeing the fridge again cuts the reconnect backoff short."""
    monkeypatch.setattr(api_module, "RECONNECT_BACKOFF", 0)
    monkeypatch.setattr(api_module, "RECONNECT_INTERVAL", 3600)

    waiter = asyncio.create_task(fridge._async_wait_for_advertisement())
    await asyncio.sleep(0.01)
    assert not waiter.done()

    fridge._advertisement_event.set()
    await asyncio.wait_for(waiter, timeout=1)


async def test_reconnect_wait_times_out_without_advertisements(
    fridge: FridgeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without an advertisement the wait ends after the reconnect interval."""
    monkeypatch.setattr(api_module, "RECONNECT_BACKOFF", 0)
    monkeypatch.setattr(api_module, "RECONNECT_INTERVAL", 0.05)

    await asyncio.wait_for(fridge._async_wait_for_advertisement(), timeout=1)


async def test_advertisement_callback_sets_the_event(fridge: FridgeApi) -> None:
    """The registered Bluetooth callback is what wakes the polling loop."""
    with patch.object(api_module.bluetooth, "async_register_callback") as register:
        fridge.async_register_advertisement_callback()

    handler = register.call_args.args[1]
    matcher = register.call_args.args[2]
    assert matcher["address"] == ADDRESS

    handler(MagicMock(), MagicMock())
    assert fridge._advertisement_event.is_set()


async def test_advertisement_callback_ignores_adverts_while_connected(
    fridge: FridgeApi,
) -> None:
    """No pointless wakeups while the connection is healthy."""
    fridge._client = FakeClient()

    with patch.object(api_module.bluetooth, "async_register_callback") as register:
        fridge.async_register_advertisement_callback()

    register.call_args.args[1](MagicMock(), MagicMock())
    assert not fridge._advertisement_event.is_set()


async def test_disconnect_drops_the_client(fridge: FridgeApi) -> None:
    """After disconnecting no stale client is kept around."""
    client = MagicMock()
    client.is_connected = True
    client.disconnect = AsyncMock()
    fridge._client = client

    await fridge.disconnect()

    client.disconnect.assert_awaited_once()
    assert fridge._client is None
    assert fridge.is_connected is False

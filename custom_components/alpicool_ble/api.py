"""API for Alpicool fridges based on modern BLE protocol."""

import asyncio
from collections.abc import Callable
import logging

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.match import BluetoothCallbackMatcher
from homeassistant.core import HomeAssistant, callback

from .const import (
    DEFAULT_MAX_WRITE_SIZE,
    FRIDGE_NOTIFY_UUID,
    FRIDGE_RW_CHARACTERISTIC_UUID,
    POLL_INTERVAL,
    RECONNECT_BACKOFF,
    RECONNECT_INTERVAL,
    UNAVAILABLE_AFTER,
    UNIT_FAHRENHEIT,
    WRITE_CHUNK_DELAY,
    Request,
)

_LOGGER = logging.getLogger(__name__)


def _to_signed_byte(b: int) -> int:
    """Convert an unsigned byte (0-255) to a signed byte (-128-127)."""
    return b - 256 if b > 127 else b


class FridgeApi:
    """A class to interact with the fridge."""

    def __init__(self, hass: HomeAssistant, address: str) -> None:
        """Initialize the API."""
        self._lock = asyncio.Lock()
        self.status = {}
        self._status_updated_event = asyncio.Event()
        self._bind_event = asyncio.Event()
        self._advertisement_event = asyncio.Event()
        self._hass = hass
        self._address = address
        # A client is only created for an actual connection attempt, from a
        # BLEDevice that Home Assistant has just seen. Holding on to one across
        # reconnects is what kept the fridge unreachable until a reload.
        self._client: BleakClient | None = None
        self._write_requires_response = False
        # Buffer for reassembling fragmented packets
        self._notification_buffer = bytearray()
        self.is_available: bool = True
        self._last_successful_update_time: float = 0.0

    @property
    def is_connected(self) -> bool:
        """Return True if there is a live connection to the fridge."""
        return self._client is not None and self._client.is_connected

    @property
    def is_fahrenheit(self) -> bool:
        """Return True if the fridge reports and expects Fahrenheit values."""
        return self.status.get("unit") == UNIT_FAHRENHEIT

    def set_initial_timestamp(self) -> None:
        """Set the initial timestamp after a successful setup."""
        self._last_successful_update_time = asyncio.get_running_loop().time()

    def _checksum(self, data: bytes) -> int:
        """Calculate 2-byte big endian checksum."""
        return sum(data) & 0xFFFF

    def _build_set_other_payload(self, new_values: dict) -> bytes:
        """Build the complete payload for the setOther command."""
        current_status = self.status.copy()
        current_status.update(new_values)

        def to_unsigned_byte(x: int) -> int:
            return x & 0xFF

        data = bytearray(
            [
                int(current_status.get("locked", 0)),
                int(current_status.get("powered_on", 1)),
                int(current_status.get("run_mode", 0)),
                int(current_status.get("bat_saver", 0)),
                to_unsigned_byte(current_status.get("left_target", 0)),
                to_unsigned_byte(current_status.get("temp_max", 20)),
                to_unsigned_byte(current_status.get("temp_min", -30)),
                to_unsigned_byte(current_status.get("left_ret_diff", 1)),
                int(current_status.get("start_delay", 0)),
                int(current_status.get("unit", 0)),
                to_unsigned_byte(current_status.get("left_tc_hot", 0)),
                to_unsigned_byte(current_status.get("left_tc_mid", 0)),
                to_unsigned_byte(current_status.get("left_tc_cold", 0)),
                to_unsigned_byte(current_status.get("left_tc_halt", 0)),
            ]
        )

        if "right_current" in current_status:
            right_zone_data = bytearray(
                [
                    to_unsigned_byte(current_status.get("right_target", 0)),
                    0,
                    0,
                    to_unsigned_byte(current_status.get("right_ret_diff", 1)),
                    to_unsigned_byte(current_status.get("right_tc_hot", 0)),
                    to_unsigned_byte(current_status.get("right_tc_mid", 0)),
                    to_unsigned_byte(current_status.get("right_tc_cold", 0)),
                    to_unsigned_byte(current_status.get("right_tc_halt", 0)),
                    0,
                    0,
                    0,
                ]
            )
            data.extend(right_zone_data)

        return data

    async def async_set_values(self, new_values: dict) -> None:
        """Public method to set configuration values."""
        if not self.status:
            _LOGGER.debug("Cannot set values, status is not available")
            return

        payload = self._build_set_other_payload(new_values)
        packet = self._build_packet(Request.SET, payload)
        await self._send_raw(packet)

    def _build_packet(self, cmd: int, data: bytes = b"") -> bytes:
        """Build a BLE command packet based on known working examples and protocol quirks."""
        if cmd == Request.BIND:
            return b"\xfe\xfe\x03\x00\x01\xff"
        if cmd == Request.QUERY:
            return b"\xfe\xfe\x03\x01\x02\x00"

        _LOGGER.debug("Using dynamic builder for cmd %s", cmd)

        header = b"\xfe\xfe"
        payload = bytearray([cmd])
        payload.extend(data)

        length = len(payload) + 2

        packet = bytearray(header)
        packet.append(length)
        packet.extend(payload)

        checksum = self._checksum(packet)
        packet.extend(checksum.to_bytes(2, "big"))

        _LOGGER.debug("Dynamically built packet for cmd %s: %s", cmd, packet.hex())
        return bytes(packet)

    async def async_set_temperature(self, zone: str, temp: int) -> None:
        """Public method to set the target temperature for a specific zone."""
        cmd = Request.SET_LEFT if zone == "left" else Request.SET_RIGHT
        payload = bytes([temp & 0xFF])

        packet = self._build_packet(cmd, payload)
        await self._send_raw(packet)

    def _decode_status(self, payload: bytes):
        """Decode query response payload for single or dual zone fridges."""
        try:
            base_status = {
                "locked": bool(payload[0]),
                "powered_on": bool(payload[1]),
                "run_mode": payload[2],
                "bat_saver": payload[3],
                "left_target": _to_signed_byte(payload[4]),
                "temp_max": _to_signed_byte(payload[5]),
                "temp_min": _to_signed_byte(payload[6]),
                "left_ret_diff": _to_signed_byte(payload[7]),
                "start_delay": payload[8],
                "unit": payload[9],
                "left_tc_hot": _to_signed_byte(payload[10]),
                "left_tc_mid": _to_signed_byte(payload[11]),
                "left_tc_cold": _to_signed_byte(payload[12]),
                "left_tc_halt": _to_signed_byte(payload[13]),
                "left_current": _to_signed_byte(payload[14]),
                "bat_percent": payload[15],
                "bat_vol_int": payload[16],
                "bat_vol_dec": payload[17],
            }
            self.status.update(base_status)
            if len(payload) >= 28:
                dual_zone_status = {
                    "right_target": _to_signed_byte(payload[18]),
                    "unknown_19": payload[19],
                    "unknown_20": payload[20],
                    "right_ret_diff": _to_signed_byte(payload[21]),
                    "right_tc_hot": _to_signed_byte(payload[22]),
                    "right_tc_mid": _to_signed_byte(payload[23]),
                    "right_tc_cold": _to_signed_byte(payload[24]),
                    "right_tc_halt": _to_signed_byte(payload[25]),
                    "right_current": _to_signed_byte(payload[26]),
                    "running_status": payload[27],
                }
                self.status.update(dual_zone_status)

            # Check for extra unknown fields at the end
            if len(payload) >= 31:
                extra_unknown_status = {
                    "unknown_28": payload[28],
                    "unknown_29": payload[29],
                    "unknown_30": payload[30],
                }
                self.status.update(extra_unknown_status)

            _LOGGER.debug("Decoded status: %s", self.status)
        except IndexError as e:
            _LOGGER.debug(
                "Failed to decode status payload (length %s): %s", len(payload), e
            )

    def _notification_handler(self, sender, data: bytearray):
        """Handle notifications, reassembling fragmented packets before parsing."""
        self._notification_buffer.extend(data)

        while self._notification_buffer:
            start_index = self._notification_buffer.find(b"\xfe\xfe")
            if start_index == -1:
                _LOGGER.debug(
                    "No packet header in buffer, clearing: %s",
                    self._notification_buffer.hex(),
                )
                self._notification_buffer.clear()
                return

            if start_index > 0:
                _LOGGER.debug(
                    "Discarding preamble: %s",
                    self._notification_buffer[:start_index].hex(),
                )
                self._notification_buffer = self._notification_buffer[start_index:]

            if len(self._notification_buffer) < 3:
                _LOGGER.debug("Buffer too short for length byte, waiting for more data")
                return

            packet_len_byte = self._notification_buffer[2]
            expected_total_len = 3 + packet_len_byte

            if len(self._notification_buffer) < expected_total_len:
                _LOGGER.debug(
                    "Incomplete packet. Have %s, need %s. Waiting for more data",
                    len(self._notification_buffer),
                    expected_total_len,
                )
                return

            current_packet = self._notification_buffer[:expected_total_len]
            self._notification_buffer = self._notification_buffer[expected_total_len:]

            _LOGGER.debug("<-- RECEIVED from %s: %s", sender, current_packet.hex())

            cmd = current_packet[3]
            payload = current_packet[4:]

            if cmd in [Request.QUERY]:
                self._decode_status(payload)
                self._status_updated_event.set()
            elif cmd == Request.BIND:
                self._bind_event.set()
            elif cmd in [Request.SET_LEFT, Request.SET_RIGHT, Request.SET]:
                _LOGGER.debug("Ignoring echo for SET command")
            else:
                _LOGGER.debug("Unhandled command in notification: %s", cmd)

    @callback
    def _async_ble_device(self) -> BLEDevice | None:
        """Return the BLEDevice as last seen by any adapter or ESPHome proxy."""
        return bluetooth.async_ble_device_from_address(
            self._hass, self._address, connectable=True
        )

    @callback
    def _async_on_disconnect(self, client: BleakClient) -> None:
        """Handle the fridge or the proxy dropping the connection."""
        _LOGGER.debug("Disconnected from %s", self._address)
        self._notification_buffer.clear()

    @callback
    def async_register_advertisement_callback(self) -> Callable[[], None]:
        """Reconnect as soon as the fridge is on air again.

        Without this the polling loop would keep sleeping for up to a minute
        after the fridge (or its Bluetooth proxy) is powered back on.
        """

        @callback
        def _async_on_advertisement(
            service_info: bluetooth.BluetoothServiceInfoBleak,
            change: bluetooth.BluetoothChange,
        ) -> None:
            if not self.is_connected:
                _LOGGER.debug("%s is advertising again", self._address)
                self._advertisement_event.set()

        return bluetooth.async_register_callback(
            self._hass,
            _async_on_advertisement,
            BluetoothCallbackMatcher(address=self._address, connectable=True),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )

    async def _async_wait_for_advertisement(self) -> None:
        """Back off before the next connection attempt, cut short by a new advert."""
        self._advertisement_event.clear()
        await asyncio.sleep(RECONNECT_BACKOFF)
        try:
            async with asyncio.timeout(RECONNECT_INTERVAL - RECONNECT_BACKOFF):
                await self._advertisement_event.wait()
        except TimeoutError:
            return

    async def _async_establish_connection(self) -> bool:
        """Open a connection using a freshly resolved BLEDevice."""
        device = self._async_ble_device()
        if device is None:
            _LOGGER.debug(
                "No adapter or proxy has seen %s yet, not connecting", self._address
            )
            return False

        try:
            self._client = await establish_connection(
                BleakClient,
                device,
                self._address,
                self._async_on_disconnect,
                use_services_cache=True,
                ble_device_callback=lambda: self._async_ble_device() or device,
            )
        except (BleakError, TimeoutError) as e:
            _LOGGER.debug("Failed to establish base BLE connection: %s", e)
            self._client = None
            return False
        return True

    async def connect(self, is_reconnect: bool = False) -> bool:
        """Connect to the fridge and try to bind, with a fallback."""
        _LOGGER.debug("Attempting to connect")
        if self.is_connected:
            return True

        if not await self._async_establish_connection():
            return False

        try:
            _LOGGER.debug("Discovering services and characteristics")
            write_char = None
            for service in self._client.services:
                for char in service.characteristics:
                    if char.uuid.lower() == FRIDGE_RW_CHARACTERISTIC_UUID.lower():
                        write_char = char
                        break
                if write_char:
                    break

            if not write_char:
                _LOGGER.error(
                    "Write characteristic %s not found!", FRIDGE_RW_CHARACTERISTIC_UUID
                )
                await self.disconnect()
                return False

            if "write-without-response" in write_char.properties:
                self._write_requires_response = False
                _LOGGER.debug("Using 'write-without-response' for commands")
            elif "write" in write_char.properties:
                self._write_requires_response = True
                _LOGGER.debug(
                    "Device requires response for writes. Using 'write' for commands"
                )
            else:
                _LOGGER.error(
                    "Write characteristic %s has no usable write properties",
                    write_char.uuid,
                )
                await self.disconnect()
                return False

            await self._client.start_notify(
                FRIDGE_NOTIFY_UUID, self._notification_handler
            )

        except BleakError as e:
            _LOGGER.error("Failed to set up the BLE connection: %s", e)
            await self.disconnect()
            return False
        if not is_reconnect:
            _LOGGER.debug("Base BLE connection successful. Attempting to bind")
            try:
                self._bind_event.clear()
                bind_packet = self._build_packet(Request.BIND, b"\x01")
                await self._send_raw(bind_packet)

                await asyncio.wait_for(self._bind_event.wait(), timeout=20)
                _LOGGER.debug("Bind successful")
            except TimeoutError:
                _LOGGER.debug(
                    "Bind command timed out. Proceeding without binding. This may work for some models"
                )
            except BleakError as e:
                _LOGGER.debug(
                    "An error occurred during bind, proceeding without it: %s", e
                )
        else:
            _LOGGER.debug("Skipping bind process for reconnect")

        if self.is_connected:
            return True

        _LOGGER.debug("Connection is not active after connect attempt")
        return False

    async def disconnect(self):
        """Disconnect from the fridge."""
        client, self._client = self._client, None
        if client and client.is_connected:
            await client.disconnect()

    def _max_write_size(self) -> int:
        """Return the largest payload the current connection accepts in one write."""
        mtu = getattr(self._client, "mtu_size", None)
        if not isinstance(mtu, int) or mtu < DEFAULT_MAX_WRITE_SIZE + 3:
            # MTU not negotiated (yet) or smaller than the default: stay safe.
            return DEFAULT_MAX_WRITE_SIZE
        return mtu - 3

    def _split_packet(self, packet: bytes) -> list[bytes]:
        """Split a packet into chunks the adapter is willing to write."""
        size = self._max_write_size()
        if len(packet) <= size:
            return [packet]
        return [packet[i : i + size] for i in range(0, len(packet), size)]

    async def _send_raw(self, packet: bytes):
        """Send raw packet to fridge, adapting write method."""
        async with self._lock:
            if not self.is_connected:
                _LOGGER.debug("Cannot send, not connected")
                return
            _LOGGER.debug("--> SENDING: %s", packet.hex())
            chunks = self._split_packet(packet)
            if len(chunks) > 1:
                _LOGGER.debug(
                    "Packet exceeds %s bytes, sending as %s chunks",
                    self._max_write_size(),
                    len(chunks),
                )
            for index, chunk in enumerate(chunks):
                if index:
                    await asyncio.sleep(WRITE_CHUNK_DELAY)
                await self._client.write_gatt_char(
                    FRIDGE_RW_CHARACTERISTIC_UUID,
                    chunk,
                    response=self._write_requires_response,
                )

    async def update_status(self) -> bool:
        """Request status and wait for notification. Returns True on success, False on timeout."""
        if not self.is_connected:
            _LOGGER.debug("Cannot update status, not connected")
            return False

        self._status_updated_event.clear()
        await self._send_raw(self._build_packet(Request.QUERY, b"\x02"))
        try:
            await asyncio.wait_for(self._status_updated_event.wait(), timeout=5)
        except TimeoutError:
            _LOGGER.debug("Timeout waiting for status update")
            return False
        else:
            return True

    async def start_polling(self, update_callback):
        """Start polling for status updates in the background."""
        _LOGGER.debug("Starting background polling")
        if self._last_successful_update_time == 0.0:
            self._last_successful_update_time = asyncio.get_running_loop().time()
        while True:
            try:
                if not self.is_connected:
                    _LOGGER.debug("Device disconnected, attempting to reconnect")
                    if await self.connect(is_reconnect=True):
                        _LOGGER.debug("Successfully reconnected to device")
                        self.is_available = True
                        self._last_successful_update_time = (
                            asyncio.get_running_loop().time()
                        )
                    else:
                        _LOGGER.debug("Reconnect failed. Will retry later")
                if self.is_connected and await self.update_status():
                    self._last_successful_update_time = (
                        asyncio.get_running_loop().time()
                    )
                    if not self.is_available:
                        _LOGGER.debug("Device communication restored")
                        self.is_available = True
                time_since_success = (
                    asyncio.get_running_loop().time()
                    - self._last_successful_update_time
                )
                if time_since_success > UNAVAILABLE_AFTER and self.is_available:
                    _LOGGER.debug(
                        "Device has been unreachable for over %s seconds. "
                        "Marking as unavailable",
                        UNAVAILABLE_AFTER,
                    )
                    self.is_available = False
                    self.status.clear()
                update_callback()

                # --- Sleep ---
                if self.is_connected:
                    await asyncio.sleep(POLL_INTERVAL)
                else:
                    await self._async_wait_for_advertisement()

            except asyncio.CancelledError:
                _LOGGER.debug("Polling task cancelled")
                self.is_available = False
                break
            except BleakError as e:
                _LOGGER.debug("An unexpected BLE error occurred during polling: %s", e)
                self.is_available = False
                await self._async_wait_for_advertisement()

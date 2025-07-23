"""Stateless API for Alpicool fridges based on modern BLE protocol."""

import asyncio
import logging

from bleak import BleakClient, BleakError

from .const import FRIDGE_NOTIFY_UUID, FRIDGE_RW_CHARACTERISTIC_UUID, Request

_LOGGER = logging.getLogger(__name__)


# --- Custom Exceptions for robust error handling ---
class AlpicoolApiError(Exception):
    """Base exception for all API-related errors."""


class AlpicoolConnectionError(AlpicoolApiError):
    """Exception for Bluetooth connection-related errors."""


def _to_signed_byte(b: int) -> int:
    """Convert an unsigned byte (0-255) to a signed byte (-128-127)."""
    return b - 256 if b > 127 else b


class AlpicoolApi:
    """A stateless class to interact with the fridge.

    This class does not manage the connection state. It is the responsibility
    of the caller (the DataUpdateCoordinator) to establish and manage the
    BleakClient connection.
    """

    def __init__(self) -> None:
        """Initialize the API."""
        self._notification_buffer = bytearray()
        self._status_updated_event = asyncio.Event()
        self._last_payload: bytes | None = None
        self._bind_event = asyncio.Event()
        self._write_requires_response = False

    def _checksum(self, data: bytes) -> int:
        """Calculate 2-byte big endian checksum."""
        return sum(data) & 0xFFFF

    def _build_packet(self, cmd: int, data: bytes = b"") -> bytes:
        """Build a BLE command packet."""
        if cmd == Request.BIND:
            return b"\xfe\xfe\x03\x00\x01\xff"
        if cmd == Request.QUERY:
            return b"\xfe\xfe\x03\x01\x02\x00"
        header = b"\xfe\xfe"
        payload = bytearray([cmd])
        payload.extend(data)
        length = len(payload) + 2
        packet = bytearray(header)
        packet.append(length)
        packet.extend(payload)
        checksum = self._checksum(packet)
        packet.extend(checksum.to_bytes(2, "big"))
        return bytes(packet)

    def _build_set_other_payload(self, current_status: dict, new_values: dict) -> bytes:
        """Build the complete payload for the setOther command."""
        status = current_status.copy()
        status.update(new_values)

        def to_unsigned_byte(x: int) -> int:
            return x & 0xFF

        data = bytearray(
            [
                int(status.get("locked", 0)),
                int(status.get("powered_on", 1)),
                int(status.get("run_mode", 0)),
                int(status.get("bat_saver", 0)),
                to_unsigned_byte(status.get("left_target", 0)),
                to_unsigned_byte(status.get("temp_max", 20)),
                to_unsigned_byte(status.get("temp_min", -20)),
                to_unsigned_byte(status.get("left_ret_diff", 1)),
                int(status.get("start_delay", 0)),
                int(status.get("unit", 0)),
                to_unsigned_byte(status.get("left_tc_hot", 0)),
                to_unsigned_byte(status.get("left_tc_mid", 0)),
                to_unsigned_byte(status.get("left_tc_cold", 0)),
                to_unsigned_byte(status.get("left_tc_halt", 0)),
            ]
        )
        if "right_current" in status:
            data.extend(
                [
                    to_unsigned_byte(status.get("right_target", 0)),
                    0,
                    0,
                    to_unsigned_byte(status.get("right_ret_diff", 1)),
                    to_unsigned_byte(status.get("right_tc_hot", 0)),
                    to_unsigned_byte(status.get("right_tc_mid", 0)),
                    to_unsigned_byte(status.get("right_tc_cold", 0)),
                    to_unsigned_byte(status.get("right_tc_halt", 0)),
                    0,
                    0,
                    0,
                ]
            )
        return data

    def _decode_status(self, payload: bytes) -> dict:
        """Decode query response payload."""
        try:
            status = {
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
            if len(payload) >= 28:
                status.update(
                    {
                        "right_target": _to_signed_byte(payload[18]),
                        "right_ret_diff": _to_signed_byte(payload[21]),
                        "right_tc_hot": _to_signed_byte(payload[22]),
                        "right_tc_mid": _to_signed_byte(payload[23]),
                        "right_tc_cold": _to_signed_byte(payload[24]),
                        "right_tc_halt": _to_signed_byte(payload[25]),
                        "right_current": _to_signed_byte(payload[26]),
                    }
                )
            return status
        except IndexError as e:
            raise AlpicoolApiError(f"Failed to decode status payload: {e}") from e

    def _notification_handler(self, sender, data: bytearray):
        """Handle incoming notifications."""
        self._notification_buffer.extend(data)
        while self._notification_buffer:
            if len(self._notification_buffer) < 3:
                return
            packet_len = self._notification_buffer[2]
            if len(self._notification_buffer) < packet_len + 3:
                return
            packet = self._notification_buffer[: packet_len + 3]
            self._notification_buffer = self._notification_buffer[packet_len + 3 :]
            _LOGGER.debug("<-- RECEIVED from %s: %s", sender, packet.hex())
            cmd = packet[3]
            if cmd == Request.QUERY:
                self._last_payload = packet[4:]
                self._status_updated_event.set()
            elif cmd == Request.BIND:
                self._bind_event.set()

    async def _send_raw(self, client: BleakClient, packet: bytes):
        """Send raw packet to fridge."""
        _LOGGER.debug("--> SENDING: %s", packet.hex())
        try:
            await client.write_gatt_char(
                FRIDGE_RW_CHARACTERISTIC_UUID,
                packet,
                response=self._write_requires_response,
            )
        except BleakError as e:
            raise AlpicoolConnectionError(f"Error sending command: {e}") from e

    async def async_start_notifications(self, client: BleakClient):
        """Start listening for notifications."""
        await client.start_notify(FRIDGE_NOTIFY_UUID, self._notification_handler)

    async def async_send_bind(self, client: BleakClient):
        """Send the bind command and wait for a response."""
        self._bind_event.clear()
        await self._send_raw(client, self._build_packet(Request.BIND))
        try:
            await asyncio.wait_for(self._bind_event.wait(), timeout=20)
            _LOGGER.debug("Bind successful")
        except asyncio.TimeoutError:
            _LOGGER.debug("Bind timed out, proceeding without it")

    async def get_status(self, client: BleakClient) -> dict:
        """Get the latest status from the device."""
        self._status_updated_event.clear()
        self._last_payload = None
        await self._send_raw(client, self._build_packet(Request.QUERY))
        try:
            await asyncio.wait_for(self._status_updated_event.wait(), timeout=20)
            if self._last_payload is None:
                raise AlpicoolApiError("No payload received after status request")
            return self._decode_status(self._last_payload)
        except TimeoutError as e:
            raise AlpicoolApiError("Timeout waiting for status update") from e

    async def async_set_values(
        self, client: BleakClient, current_status: dict, new_values: dict
    ) -> None:
        """Public method to set configuration values."""
        payload = self._build_set_other_payload(current_status, new_values)
        packet = self._build_packet(Request.SET, payload)
        await self._send_raw(client, packet)

    async def async_set_temperature(
        self, client: BleakClient, zone: str, temp: int
    ) -> None:
        """Public method to set the target temperature for a specific zone."""
        cmd = Request.SET_LEFT if zone == "left" else Request.SET_RIGHT
        payload = bytes([temp & 0xFF])
        packet = self._build_packet(cmd, payload)
        await self._send_raw(client, packet)

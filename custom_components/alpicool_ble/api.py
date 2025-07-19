"""
API for Alpicool fridges using ActiveBluetoothDataUpdateCoordinator.
"""
import asyncio
import logging
from typing import Any

from bleak import BleakClient

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.components.bluetooth.active_update_coordinator import (
    ActiveBluetoothDataUpdateCoordinator,
)
from homeassistant.core import callback

from .const import (
    FRIDGE_RW_CHARACTERISTIC_UUID,
    FRIDGE_NOTIFY_UUID,
    Request,
)

_LOGGER = logging.getLogger(__name__)

class FridgeCoordinator(ActiveBluetoothDataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to manage connection and data fetching for an Alpicool fridge."""

    def __init__(self, hass, logger, address: str, mode: str, update_interval):
        """Initialize the coordinator."""
        super().__init__(
            hass=hass,
            logger=logger,
            address=address,
            mode=mode,
            connectable=True,
            needs_poll_method=self._needs_poll_method,
        )
        self.update_interval = update_interval

        self._notification_buffer = bytearray()
        self._status_updated_event = asyncio.Event()
        self._write_requires_response = False
        self.data = {}

    @callback
    def _needs_poll_method(self, service_info: BluetoothServiceInfoBleak, last_poll_successful: bool) -> bool:
        """Return if the device needs polling."""
        return True

    def _notification_handler(self, sender, data: bytearray):
        """Handle incoming notifications from the device."""
        self._notification_buffer.extend(data)
        while self._notification_buffer:
            start_index = self._notification_buffer.find(b'\xfe\xfe')
            if start_index == -1: return
            if start_index > 0: self._notification_buffer = self._notification_buffer[start_index:]
            if len(self._notification_buffer) < 3: return
            packet_len_byte = self._notification_buffer[2]
            expected_total_len = 3 + packet_len_byte
            if len(self._notification_buffer) < expected_total_len: return
            current_packet = self._notification_buffer[:expected_total_len]
            self._notification_buffer = self._notification_buffer[expected_total_len:]
            cmd = current_packet[3]
            payload = current_packet[4:]
            if cmd == Request.QUERY:
                decoded_status = self._decode_status(payload)
                if decoded_status: self.async_set_updated_data(decoded_status)
                self._status_updated_event.set()

    async def async_send_command(self, packet: bytes) -> None:
        """Send a command to the device."""
        try:
            await self.client.write_gatt_char(FRIDGE_RW_CHARACTERISTIC_UUID, packet, response=self._write_requires_response)
            await self.async_request_refresh()
        except Exception as e:
            _LOGGER.error(f"Failed to send command: {e}")

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the device."""
        client = self.client
        if not hasattr(self, '_write_char_checked'):
            char = client.services.get_characteristic(FRIDGE_RW_CHARACTERISTIC_UUID)
            self._write_requires_response = not (char and 'write-without-response' in char.properties)
            setattr(self, '_write_char_checked', True)
        try:
            await client.start_notify(FRIDGE_NOTIFY_UUID, self._notification_handler)
            self._status_updated_event.clear()
            query_packet = self._build_packet(Request.QUERY)
            await client.write_gatt_char(FRIDGE_RW_CHARACTERISTIC_UUID, query_packet, self._write_requires_response)
            await asyncio.wait_for(self._status_updated_event.wait(), timeout=10)
        except asyncio.TimeoutError:
            _LOGGER.warning("Timeout waiting for status update.")
            raise TimeoutError("No response from fridge.")
        finally:
            await client.stop_notify(FRIDGE_NOTIFY_UUID)
        return self.data

    def _checksum(self, data: bytes) -> int: return sum(data) & 0xFFFF

    def _build_packet(self, cmd: int, data: bytes = b"") -> bytes:
        if cmd == Request.QUERY: return b"\xFE\xFE\x03\x01\x02\x00"
        header = b"\xFE\xFE"; payload = bytearray([cmd]); payload.extend(data)
        length = len(payload) + 2; packet = bytearray(header); packet.append(length); packet.extend(payload)
        checksum = self._checksum(packet); packet.extend(checksum.to_bytes(2, "big"))
        return bytes(packet)
    
    @staticmethod
    def _to_signed_byte(b: int) -> int:
        """Convert an unsigned byte (0-255) to a signed byte (-128-127)."""
        return b - 256 if b > 127 else b

    def _decode_status(self, payload: bytes) -> dict[str, Any]:
        try:
            s_byte = FridgeCoordinator._to_signed_byte
            decoded_data = {"locked": bool(payload[0]), "powered_on": bool(payload[1]), "run_mode": payload[2], "bat_saver": payload[3], "left_target": s_byte(payload[4]), "temp_max": s_byte(payload[5]), "temp_min": s_byte(payload[6]), "left_ret_diff": s_byte(payload[7]), "start_delay": payload[8], "unit": payload[9], "left_tc_hot": s_byte(payload[10]), "left_tc_mid": s_byte(payload[11]), "left_tc_cold": s_byte(payload[12]), "left_tc_halt": s_byte(payload[13]), "left_current": s_byte(payload[14]), "bat_percent": payload[15], "bat_vol_int": payload[16], "bat_vol_dec": payload[17]}
            if len(payload) >= 28: decoded_data.update({"right_target": s_byte(payload[18]), "right_ret_diff": s_byte(payload[21]), "right_tc_hot": s_byte(payload[22]), "right_tc_mid": s_byte(payload[23]), "right_tc_cold": s_byte(payload[24]), "right_tc_halt": s_byte(payload[25]), "right_current": s_byte(payload[26]), "running_status": payload[27]})
            return decoded_data
        except IndexError as e:
            _LOGGER.error(f"Failed to decode status payload (length {len(payload)}): {e}")
            return {}
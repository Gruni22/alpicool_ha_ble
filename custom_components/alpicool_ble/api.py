"""API for Alpicool fridges based on modern BLE protocol."""
import asyncio
import logging
from bleak import BleakClient, BleakError

from .const import (
    FRIDGE_RW_CHARACTERISTIC_UUID,
    FRIDGE_NOTIFY_UUID,
    Request,
)

_LOGGER = logging.getLogger(__name__)

def _to_signed_byte(b: int) -> int:
    """Convert an unsigned byte (0-255) to a signed byte (-128-127)."""
    return b - 256 if b > 127 else b

class FridgeApi:
    """A class to interact with the fridge."""

    def __init__(self, address: str) -> None:
        """Initialize the API."""
        self._lock = asyncio.Lock()
        self.status = {}
        self._status_updated_event = asyncio.Event()
        self._bind_event = asyncio.Event()
        self._poll_task = None
        self._address = address
        self._client = BleakClient(self._address, timeout=30.0)
        self._write_requires_response = False
        # Buffer for reassembling fragmented packets
        self._notification_buffer = bytearray()
        self.is_available: bool = True
        self._last_successful_update_time: float = 0.0

    def _checksum(self, data: bytes) -> int:
        """Calculate 2-byte big endian checksum."""
        return sum(data) & 0xFFFF
    
    def _build_packet(self, cmd: int, data: bytes = b"") -> bytes:
        """Build a BLE command packet based on known working examples and protocol quirks."""
        if cmd == Request.BIND:
            return b"\xFE\xFE\x03\x00\x01\xFF"
        if cmd == Request.QUERY:
            return b"\xFE\xFE\x03\x01\x02\x00"
        
        _LOGGER.debug(f"Using dynamic builder for cmd {cmd}")
        
        header = b"\xFE\xFE"
        payload = bytearray([cmd])
        payload.extend(data)
        
        length = len(payload) + 2
        
        packet = bytearray(header)
        packet.append(length)
        packet.extend(payload)
        
        checksum = self._checksum(packet)
        packet.extend(checksum.to_bytes(2, "big"))
        
        _LOGGER.debug(f"Dynamically built packet for cmd {cmd}: {packet.hex()}")
        return bytes(packet)

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

            _LOGGER.debug(f"Decoded status: {self.status}")
        except IndexError as e:
            _LOGGER.error(f"Failed to decode status payload (length {len(payload)}): {e}")

    def _notification_handler(self, sender, data: bytearray):
        """Handle notifications, reassembling fragmented packets before parsing."""
        self._notification_buffer.extend(data)

        while self._notification_buffer:
            start_index = self._notification_buffer.find(b'\xfe\xfe')
            if start_index == -1:
                _LOGGER.warning(f"No packet header in buffer, clearing: {self._notification_buffer.hex()}")
                self._notification_buffer.clear()
                return

            if start_index > 0:
                _LOGGER.debug(f"Discarding preamble: {self._notification_buffer[:start_index].hex()}")
                self._notification_buffer = self._notification_buffer[start_index:]

            if len(self._notification_buffer) < 3:
                _LOGGER.debug("Buffer too short for length byte, waiting for more data.")
                return

            # The length byte is the length of the rest of the packet (cmd + payload + checksum)
            packet_len_byte = self._notification_buffer[2]
            expected_total_len = 3 + packet_len_byte

            if len(self._notification_buffer) < expected_total_len:
                _LOGGER.debug(f"Incomplete packet. Have {len(self._notification_buffer)}, need {expected_total_len}. Waiting for more data.")
                return

            # We have a full packet
            current_packet = self._notification_buffer[:expected_total_len]
            self._notification_buffer = self._notification_buffer[expected_total_len:]

            _LOGGER.debug(f"<-- RECEIVED from {sender}: {current_packet.hex()}")

            cmd = current_packet[3]
            # The payload is everything after the command byte.
            # The length of the checksum is inconsistent, so we let the decoders handle the payload.
            payload = current_packet[4:]

            if cmd in [Request.QUERY]:
                self._decode_status(payload)
                self._status_updated_event.set()
            elif cmd == Request.BIND:
                self._bind_event.set()
            elif cmd in [Request.SET_LEFT, Request.SET_RIGHT, Request.SET]:
                _LOGGER.debug(f"Ignoring echo for SET command.")
            else:
                _LOGGER.debug(f"Unhandled command in notification: {cmd}")

    async def connect(self, is_reconnect: bool = False) -> bool:
        """Connect to the fridge and try to bind, with a fallback."""
        _LOGGER.debug("Attempting to connect...")
        try:
            if not self._client.is_connected:
                await self._client.connect()

            _LOGGER.debug("Discovering services and characteristics...")
            write_char = None
            for service in self._client.services:
                for char in service.characteristics:
                    if char.uuid.lower() == FRIDGE_RW_CHARACTERISTIC_UUID.lower():
                        write_char = char
                        break
                if write_char:
                    break

            if not write_char:
                _LOGGER.error(f"Write characteristic {FRIDGE_RW_CHARACTERISTIC_UUID} not found!")
                await self.disconnect()
                return False

            if 'write-without-response' in write_char.properties:
                self._write_requires_response = False
                _LOGGER.debug("Using 'write-without-response' for commands.")
            elif 'write' in write_char.properties:
                self._write_requires_response = True
                _LOGGER.info("Device requires response for writes. Using 'write' for commands.")
            else:
                _LOGGER.error(f"Write characteristic {write_char.uuid} has no usable write properties.")
                await self.disconnect()
                return False

            await self._client.start_notify(FRIDGE_NOTIFY_UUID, self._notification_handler)

        except Exception as e:
            _LOGGER.error(f"Failed to establish base BLE connection: {e}")
            await self.disconnect()
            return False
        if not is_reconnect:
            _LOGGER.debug("Base BLE connection successful. Attempting to bind...")
            try:
                self._bind_event.clear()
                bind_packet = self._build_packet(Request.BIND, b"\x01")
                await self._send_raw(bind_packet)

                await asyncio.wait_for(self._bind_event.wait(), timeout=20)
                _LOGGER.debug("Bind successful.")
            except asyncio.TimeoutError:
                _LOGGER.debug("Bind command timed out. Proceeding without binding. This may work for some models.")
            except Exception as e:
                _LOGGER.debug(f"An error occurred during bind, proceeding without it: {e}")
        else:
            _LOGGER.debug("Skipping bind process for reconnect.")

        if self._client.is_connected:
            return True
        else:
            _LOGGER.debug("Connection is not active after connect attempt.")
            return False

    async def disconnect(self):
        """Disconnect from the fridge."""
        if self._poll_task: self._poll_task.cancel()
        if self._client and self._client.is_connected:
            await self._client.disconnect()

    async def _send_raw(self, packet: bytes):
        """Send raw packet to fridge, adapting write method."""
        if not self._client.is_connected:
            _LOGGER.error("Cannot send, not connected")
            return
        _LOGGER.debug(f"--> SENDING: {packet.hex()}")
        await self._client.write_gatt_char(FRIDGE_RW_CHARACTERISTIC_UUID, packet, response=self._write_requires_response)

    async def update_status(self) -> bool:
        """Request status and wait for notification. Returns True on success, False on timeout."""
        if not self._client.is_connected:
            _LOGGER.warning("Cannot update status, not connected")
            return False
            
        self._status_updated_event.clear()
        await self._send_raw(self._build_packet(Request.QUERY, b"\x02"))
        try:
            await asyncio.wait_for(self._status_updated_event.wait(), timeout=5)
            return True
        except asyncio.TimeoutError:
            _LOGGER.warning("Timeout waiting for status update")
            return False

    async def start_polling(self, update_callback):
        """Start polling for status updates in the background."""
        _LOGGER.debug("Starting background polling.")
        if self._last_successful_update_time == 0.0:
            self._last_successful_update_time = asyncio.get_running_loop().time()
        while True:
            try:
                if not self._client.is_connected:
                    _LOGGER.info("Device disconnected, attempting to reconnect.")
                    if await self.connect(is_reconnect=True):
                        _LOGGER.info("Successfully reconnected to device")
                        self.is_available = True
                        self._last_successful_update_time = asyncio.get_running_loop().time()
                    else:
                        _LOGGER.warning("Reconnect failed. Will retry later")
                if self._client.is_connected:
                    if await self.update_status():
                        self._last_successful_update_time = asyncio.get_running_loop().time()
                        if not self.is_available:
                            _LOGGER.info("Device communication restored.")
                            self.is_available = True
                time_since_success = asyncio.get_running_loop().time() - self._last_successful_update_time
                if time_since_success > 300: # 5 minutes
                    if self.is_available:
                        _LOGGER.warning("Device has been unreachable for over 5 minutes. Marking as unavailable")
                        self.is_available = False
                        self.status.clear()
                update_callback()

                # --- Sleep ---
                sleep_duration = 30 if self._client.is_connected else 60
                await asyncio.sleep(sleep_duration)

            except asyncio.CancelledError:
                _LOGGER.debug("Polling task cancelled")
                self.is_available = False
                break
            except Exception as e:
                _LOGGER.error(f"An unexpected error occurred during polling: {e}")
                self.is_available = False
                await asyncio.sleep(60)

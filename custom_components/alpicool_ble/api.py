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
        self._client = BleakClient(self._address, timeout=20.0)

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
                "locked": bool(payload[0]), "powered_on": bool(payload[1]), "run_mode": payload[2], "bat_saver": payload[3],
                "left_target": _to_signed_byte(payload[4]), "temp_max": _to_signed_byte(payload[5]),
                "temp_min": _to_signed_byte(payload[6]), "left_ret_diff": _to_signed_byte(payload[7]),
                "start_delay": payload[8], "unit": payload[9], "left_tc_hot": _to_signed_byte(payload[10]),
                "left_tc_mid": _to_signed_byte(payload[11]), "left_tc_cold": _to_signed_byte(payload[12]),
                "left_tc_halt": _to_signed_byte(payload[13]), "left_current": _to_signed_byte(payload[14]),
                "bat_percent": payload[15], "bat_vol_int": payload[16], "bat_vol_dec": payload[17],
            }
            self.status.update(base_status)
            if len(payload) >= 28:
                dual_zone_status = {
                    "right_target": _to_signed_byte(payload[18]), "right_ret_diff": _to_signed_byte(payload[21]),
                    "right_tc_hot": _to_signed_byte(payload[22]), "right_tc_mid": _to_signed_byte(payload[23]),
                    "right_tc_cold": _to_signed_byte(payload[24]), "right_tc_halt": _to_signed_byte(payload[25]),
                    "right_current": _to_signed_byte(payload[26]), "running_status": payload[27]
                }
                self.status.update(dual_zone_status)
            _LOGGER.debug(f"Decoded status: {self.status}")
        except IndexError as e:
            _LOGGER.error(f"Failed to decode status payload (length {len(payload)}): {e}")

    def _notification_handler(self, sender, data: bytearray):
        """Handle notifications, capable of parsing multiple concatenated packets."""
        _LOGGER.debug(f"<-- RECEIVED RAW from {sender}: {data.hex()}")
        buffer = data
        while buffer:
            start_index = buffer.find(b'\xfe\xfe')
            if start_index == -1: return
            if start_index > 0: buffer = buffer[start_index:]
            if len(buffer) < 4: return
            end_index = -1
            try: end_index = buffer.index(b'\xfe\xfe', 2)
            except ValueError: pass
            current_packet = buffer[:end_index] if end_index != -1 else buffer
            buffer = buffer[end_index:] if end_index != -1 else bytearray()
            _LOGGER.debug(f"Processing single packet: {current_packet.hex()}")
            packet_len_byte = current_packet[2]
            if len(current_packet) < packet_len_byte + 3: continue
            cmd = current_packet[3]
            if cmd == Request.QUERY:
                payload = current_packet[4:-2 if packet_len_byte > 3 else -1]
                self._decode_status(payload)
                self._status_updated_event.set()
            elif cmd == Request.BIND:
                self._bind_event.set()
            elif cmd in [Request.SET_LEFT, Request.SET_RIGHT, Request.SET_OTHER]:
                _LOGGER.debug(f"Ignoring echo for SET command.")
            else:
                _LOGGER.debug(f"Unhandled command in notification: {cmd}")

    async def connect(self) -> bool:
        """Connect to the fridge and try to bind, with a fallback."""
        _LOGGER.debug("Attempting to connect...")
        try:
            # Step 1: Establish base connection. This must succeed.
            if not self._client.is_connected:
                await self._client.connect()
            
            # Step 1a: UUID Parser - Discover and validate services and characteristics
            _LOGGER.debug("Discovering services and characteristics...")
            discovered_char_uuids = {char.uuid.lower() for service in self._client.services for char in service.characteristics}
            for service in self._client.services:
                _LOGGER.debug(f"  [Service] {service.uuid}")
                for char in service.characteristics:
                    _LOGGER.debug(f"    [Characteristic] {char.uuid} | Properties: {char.properties}")

            required_uuids = {FRIDGE_RW_CHARACTERISTIC_UUID.lower(), FRIDGE_NOTIFY_UUID.lower()}
            if not required_uuids.issubset(discovered_char_uuids):
                _LOGGER.error(
                    "Device is missing required characteristics. "
                    f"Found: {discovered_char_uuids}. Required: {required_uuids}"
                )
                await self.disconnect()
                return False
            _LOGGER.debug("All required characteristics found.")
            
            # Step 1b: Try to start notifications.
            _LOGGER.debug(f"Attempting to start notifications on {FRIDGE_NOTIFY_UUID}...")
            try:
                await self._client.start_notify(FRIDGE_NOTIFY_UUID, self._notification_handler)
                _LOGGER.debug("Successfully started notifications.")
            except Exception as e:
                _LOGGER.error(f"Failed to start notifications: {e}. This may be a permissions issue or the characteristic may not exist.")
                await self.disconnect()
                return False

        except Exception as e:
            _LOGGER.error(f"Failed to establish base BLE connection: {e}")
            await self.disconnect()
            return False

        _LOGGER.debug("Base BLE connection successful. Attempting to bind...")

        # Step 2: Try to bind. This is optional and can fail.
        try:
            self._bind_event.clear()
            await self._send_raw(self._build_packet(Request.BIND, b"\x01"))
            await asyncio.wait_for(self._bind_event.wait(), timeout=20)
            _LOGGER.debug("Bind successful.")
        except asyncio.TimeoutError:
            _LOGGER.warning("Bind command timed out. Proceeding without binding. This may work for some models.")
        except Exception as e:
            _LOGGER.warning(f"An error occurred during bind, proceeding without it: {e}")

        # Step 3: Final check. No matter what happened during bind, is the client still connected?
        if self._client.is_connected:
            return True
        else:
            _LOGGER.error("Connection is not active after connect attempt.")
            return False

    async def disconnect(self):
        """Disconnect from the fridge."""
        if self._poll_task: self._poll_task.cancel()
        if self._client and self._client.is_connected:
            await self._client.disconnect()

    async def _send_raw(self, packet: bytes):
        """Send raw packet to fridge."""
        if not self._client.is_connected:
            _LOGGER.error("Cannot send, not connected")
            return
        _LOGGER.debug(f"--> SENDING: {packet.hex()}")
        await self._client.write_gatt_char(FRIDGE_RW_CHARACTERISTIC_UUID, packet, response=False)

    async def update_status(self):
        """Request status and wait for notification."""
        self._status_updated_event.clear()
        await self._send_raw(self._build_packet(Request.QUERY, b"\x02"))
        try: await asyncio.wait_for(self._status_updated_event.wait(), timeout=3)
        except asyncio.TimeoutError: _LOGGER.warning("Timeout waiting for status")

    async def start_polling(self, update_callback):
        """Start polling for status updates in the background."""
        _LOGGER.debug("Starting background polling.")
        while True:
            try:
                if not self._client.is_connected:
                    _LOGGER.info("Device disconnected, attempting to reconnect.")
                    if not await self.connect():
                         await asyncio.sleep(60)
                         continue
                
                await self.update_status()
                update_callback()
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                _LOGGER.debug("Polling task cancelled.")
                break
            except Exception as e:
                _LOGGER.error(f"Error during polling: {e}")
                await asyncio.sleep(60)

"""API for Alpicool fridges based on modern BLE protocol."""
import asyncio
import logging
from bleak import BleakClient, BleakError

from .const import (
    FRIDGE_RW_CHARACTERISTIC_UUID,
    FRIDGE_NOTIFY_UUID,
    Request,
)

def _to_signed_byte(b: int) -> int:
    """Convert an unsigned byte (0-255) to a signed byte (-128-127)."""
    return b - 256 if b > 127 else b

_LOGGER = logging.getLogger(__name__)


class FridgeApi:
    """A class to interact with the fridge."""

    def __init__(self, address: str, disconnected_callback) -> None:
        self._lock = asyncio.Lock()
        self.status = {}
        self._status_updated_event = asyncio.Event()
        self._bind_event = asyncio.Event()

        self._address = address
        self._client = BleakClient(self._address, disconnected_callback=disconnected_callback, timeout=20.0)

    def _checksum(self, data: bytes) -> int:
        """Calculate 2-byte big endian checksum."""
        return sum(data) & 0xFFFF
    
    def _build_packet(self, cmd: int, data: bytes = b"") -> bytes:
        """Build a BLE command packet based on known working examples and educated guesses."""

        # BIND and QUERY are special cases with a fixed structure and a 1-byte checksum.
        if cmd == Request.BIND:
            return b"\xFE\xFE\x03\x00\x01\xFF"
        if cmd == Request.QUERY:
            return b"\xFE\xFE\x03\x01\x02\x00"

    # For all other commands (like SET_LEFT, SET_OTHER), it seems they use a
    # standard 2-byte checksum, but the length field is inconsistent.
    # We will build these dynamically but with careful construction.

        header = b"\xFE\xFE"
    
    # Combine command and data into the payload
        payload = bytearray([cmd])
        payload.extend(data)
    
    # The length field appears to be the length of the payload (cmd + data)
    # plus the length of the checksum itself (2 bytes).
    # This is an unusual but observed behavior from the SET_OTHER example.
        length = len(payload) + 2 

        packet = bytearray(header)
        packet.append(length)
        packet.extend(payload)
    
    # The checksum for SET commands seems to be a standard sum over
    # all bytes before it.
        checksum = self._checksum(packet)
        packet.extend(checksum.to_bytes(2, "big"))
    
        _LOGGER.debug(f"Dynamically built packet for cmd {cmd}: {packet.hex()}")
        return bytes(packet)

    def _decode_status(self, payload: bytes):
        """Decode query response payload."""
        try:
            self.status = {
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
            _LOGGER.debug(f"Decoded status: {self.status}")
        except IndexError as e:
            _LOGGER.error(f"Failed to decode status: {e}")

    def _notification_handler(self, sender, data: bytearray):
        """Handle notifications, capable of parsing multiple concatenated packets."""
        _LOGGER.debug(f"<-- RECEIVED RAW: {data.hex()}")
        buffer = data
    
        while buffer:
            # Find the start of a packet
            start_index = buffer.find(b'\xfe\xfe')
            if start_index == -1:
                _LOGGER.warning(f"No packet header found in remaining buffer: {buffer.hex()}")
                return

            # Discard any data before the header
            if start_index > 0:
                _LOGGER.debug(f"Discarding preamble: {buffer[:start_index].hex()}")
                buffer = buffer[start_index:]

            # Check for minimum length (header + len byte)
            if len(buffer) < 3:
                return # Not enough data for a full packet yet

            # Find the start of the NEXT packet to determine the end of the current one
            end_index = -1
            if len(buffer) > 2:
                try:
                    end_index = buffer.index(b'\xfe\xfe', 2)
                except ValueError:
                    end_index = -1 # Not found

            if end_index != -1:
                current_packet = buffer[:end_index]
                buffer = buffer[end_index:]
            else:
                current_packet = buffer
                buffer = bytearray() # No more data left

            _LOGGER.debug(f"Processing single packet: {current_packet.hex()}")

            # --- Single Packet Parsing Logic ---
            # A simple sanity check for packet length vs the length byte
            packet_len_byte = current_packet[2]
            # This check is tricky due to inconsistent checksum lengths, so we keep it simple
            if len(current_packet) < packet_len_byte + 2:
                _LOGGER.warning(f"Packet seems truncated: {current_packet.hex()}")
                continue # Skip to next fragment in buffer

            cmd = current_packet[3]
            payload = current_packet[4:-2] # Assume 2-byte checksum for SET/QUERY responses

            # We now handle packets based on their command
            if cmd == Request.QUERY:
                self._decode_status(payload)
                self._status_updated_event.set()
            elif cmd == Request.BIND:
                _LOGGER.debug("Bind response received")
                self._bind_event.set()
            elif cmd == Request.SET_LEFT or cmd == Request.SET_OTHER:
                _LOGGER.debug(f"Ignoring echo for SET command: {current_packet.hex()}")
                # This is an echo, we do nothing with it.
                pass
            else:
                _LOGGER.debug(f"Unhandled command in notification: {cmd}")

    async def connect(self) -> bool:
        """Connect and start notifications."""
        _LOGGER.debug("Starting connection...")
        async with self._lock:
            try:
                if not self._client.is_connected:
                    await self._client.connect() # WENN NICHT CONNECTED, STARTE VON NEUEM????
                    await self._client.start_notify(FRIDGE_NOTIFY_UUID, self._notification_handler) # WO IST DIE START_NOTIFY METHODE?!?

                    # Send bind command and wait for confirmation
                    self._bind_event.clear()
                    await self._send_raw(self._build_packet(Request.BIND, b"\x01"))
                    _LOGGER.debug("Sent bind command, waiting for confirmation...")
                    await asyncio.wait_for(self._bind_event.wait(), timeout=20) # Warte 10s
                    _LOGGER.debug("Bind successful.")

                return self._client.is_connected
            except (BleakError, asyncio.TimeoutError) as e:
                _LOGGER.error(f"Failed to connect or bind: {e}")
                await self.disconnect() # Verbindung trennen bei Fehler
                return False

    async def disconnect(self):
        """Disconnect."""
        async with self._lock:
            if self._client.is_connected:
                try:
                    await self._client.stop_notify(FRIDGE_NOTIFY_UUID)
                    await self._client.disconnect()
                except BleakError as e:
                    _LOGGER.error(f"Failed to disconnect: {e}")

    async def _send_raw(self, packet: bytes):
        """Send raw packet to fridge."""
        
        _LOGGER.debug(f"--> SENDING: {packet.hex()}")

        try:
            await self._client.write_gatt_char(FRIDGE_RW_CHARACTERISTIC_UUID, packet, response=False)
        except BleakError as e:
            _LOGGER.error(f"Failed to write: {e}")

    async def update_status(self):
        """Request status and wait for notification."""
        self._status_updated_event.clear()
        packet = self._build_packet(Request.QUERY, b"\x02")
        _LOGGER.debug(f"--> SENDING: {packet.hex()}")
        try:
            await self._client.write_gatt_char(FRIDGE_RW_CHARACTERISTIC_UUID, packet, response=False)
            _LOGGER.debug("Sent query command")

            try:
                await asyncio.wait_for(self._status_updated_event.wait(), timeout=3)
            except asyncio.TimeoutError:
                _LOGGER.warning("Timeout waiting for status")
        except BleakError as e:
            _LOGGER.error(f"Failed to write query: {e}")

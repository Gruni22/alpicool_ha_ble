"""API for Alpicool fridges based on modern BLE protocol."""
import asyncio
import logging
from bleak import BleakClient, BleakError
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.dispatcher import async_dispatcher_send


from .const import (
    DOMAIN,
    FRIDGE_RW_CHARACTERISTIC_UUID,
    FRIDGE_NOTIFY_UUID,
    Request,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Alpicool BLE from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    address = entry.data["address"]
    
    # Create and store the API object
    api = FridgeApi(address)
    hass.data[DOMAIN][entry.entry_id] = api

    # Connect and get initial status to determine device type (single/dual zone)
    try:
        if not await api.connect():
            raise ConfigEntryNotReady(f"Could not connect to Alpicool device at {address}")
        await api.update_status()
    except Exception as e:
        await api.disconnect()
        raise ConfigEntryNotReady(f"Failed to initialize Alpicool device at {address}: {e}") from e

    # Forward setup to all platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Start background polling task
    entry.async_on_unload(
        hass.loop.create_task(api.start_polling(
            lambda: async_dispatcher_send(hass, f"{DOMAIN}_{address}_update")
        )).cancel
    )

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    api: FridgeApi = hass.data[DOMAIN].pop(entry.entry_id)
    await api.disconnect()
    
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

def _to_signed_byte(b: int) -> int:
    """Convert an unsigned byte (0-255) to a signed byte (-128-127)."""
    return b - 256 if b > 127 else b

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
        """Build a BLE command packet based on known working examples and protocol quirks."""
        
        # --- Handle all known special cases with a 1-byte checksum ---
        if cmd in [Request.BIND, Request.QUERY, Request.SET_LEFT, Request.SET_RIGHT]:
            # This logic is based on the working BIND/QUERY commands
            header = b"\xFE\xFE"
            # The length byte for these simple commands appears to be consistently 3
            length = 3
            
            packet = bytearray(header)
            packet.append(length)
            packet.append(cmd)
            packet.extend(data)
            
            # These commands use a simple 1-byte checksum over the whole packet so far
            checksum = sum(packet) & 0xFF
            packet.append(checksum)
            
            _LOGGER.debug(f"Built special-case packet for cmd {cmd}: {packet.hex()}")
            return bytes(packet)

        # --- Fallback for complex commands like SET_OTHER ---
        _LOGGER.debug(f"Using dynamic builder for complex cmd {cmd}")
        header = b"\xFE\xFE"
        payload = bytearray([cmd])
        payload.extend(data)
        
        # The length for complex commands seems to include the checksum length
        length = len(payload) + 2
        
        packet = bytearray(header)
        packet.append(length)
        packet.extend(payload)
        
        # These commands use a 2-byte checksum
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

            # Try to decode dual-zone fields if payload is long enough
            if len(payload) >= 27:
                dual_zone_status = {
                    "right_target": _to_signed_byte(payload[18]),
                    "right_ret_diff": _to_signed_byte(payload[21]),
                    "right_tc_hot": _to_signed_byte(payload[22]),
                    "right_tc_mid": _to_signed_byte(payload[23]),
                    "right_tc_cold": _to_signed_byte(payload[24]),
                    "right_tc_halt": _to_signed_byte(payload[25]),
                    "right_current": _to_signed_byte(payload[26]),
                    "running_status": payload[27]
                }
                self.status.update(dual_zone_status)
            
            _LOGGER.debug(f"Decoded status: {self.status}")
        except IndexError as e:
            _LOGGER.error(f"Failed to decode status payload (length {len(payload)}): {e}")


    def _notification_handler(self, sender, data: bytearray):
        """Handle notifications, capable of parsing multiple concatenated packets."""
        _LOGGER.debug(f"<-- RECEIVED RAW: {data.hex()}")
        buffer = data
        
        while buffer:
            start_index = buffer.find(b'\xfe\xfe')
            if start_index == -1:
                _LOGGER.warning(f"No packet header found in remaining buffer: {buffer.hex()}")
                return

            if start_index > 0:
                _LOGGER.debug(f"Discarding preamble: {buffer[:start_index].hex()}")
                buffer = buffer[start_index:]

            if len(buffer) < 3:
                return

            # Find the start of the NEXT packet to determine the end of the current one
            end_index = -1
            if len(buffer) > 2:
                try:
                    end_index = buffer.index(b'\xfe\xfe', 2)
                except ValueError:
                    end_index = -1

            if end_index != -1:
                current_packet = buffer[:end_index]
                buffer = buffer[end_index:]
            else:
                current_packet = buffer
                buffer = bytearray()

            _LOGGER.debug(f"Processing single packet: {current_packet.hex()}")

            packet_len_byte = current_packet[2]
            if len(current_packet) < packet_len_byte + 2:
                 _LOGGER.warning(f"Packet seems truncated: {current_packet.hex()}")
                 continue

            cmd = current_packet[3]
            
            if cmd == Request.QUERY:
                payload = current_packet[4:-2] if packet_len_byte > 3 else current_packet[4:-1]
                self._decode_status(payload)
                self._status_updated_event.set()
            elif cmd == Request.BIND:
                _LOGGER.debug("Bind response received")
                self._bind_event.set()
            elif cmd in [Request.SET_LEFT, Request.SET_RIGHT, Request.SET_OTHER]:
                _LOGGER.debug(f"Ignoring echo for SET command: {current_packet.hex()}")
                pass
            else:
                _LOGGER.debug(f"Unhandled command in notification: {cmd}")

    async def connect(self) -> bool:
        """Connect and start notifications."""
        _LOGGER.debug("Starting connection...")
        async with self._lock:
            try:
                if not self._client.is_connected:
                    await self._client.connect()
                    await self._client.start_notify(FRIDGE_NOTIFY_UUID, self._notification_handler)
                    self._bind_event.clear()
                    await self._send_raw(self._build_packet(Request.BIND, b"\x01"))
                    _LOGGER.debug("Sent bind command, waiting for confirmation...")
                    await asyncio.wait_for(self._bind_event.wait(), timeout=20)
                    _LOGGER.debug("Bind successful.")
                return self._client.is_connected
            except (BleakError, asyncio.TimeoutError) as e:
                _LOGGER.error(f"Failed to connect or bind: {e}")
                await self.disconnect()
                return False

    async def disconnect(self):
        """Disconnect."""
        async with self._lock:
            if self._client and self._client.is_connected:
                try:
                    await self._client.stop_notify(FRIDGE_NOTIFY_UUID)
                    await self._client.disconnect()
                except BleakError as e:
                    _LOGGER.error(f"Failed to disconnect: {e}")

    async def _send_raw(self, packet: bytes):
        """Send raw packet to fridge."""
        if not self._client.is_connected:
            _LOGGER.error("Cannot send, not connected")
            return
        
        _LOGGER.debug(f"--> SENDING: {packet.hex()}")
        try:
            await self._client.write_gatt_char(FRIDGE_RW_CHARACTERISTIC_UUID, packet, response=False)
        except BleakError as e:
            _LOGGER.error(f"Failed to write: {e}")

    async def update_status(self):
        """Request status and wait for notification."""
        self._status_updated_event.clear()
        packet = self._build_packet(Request.QUERY, b"\x02")
        await self._send_raw(packet)
        _LOGGER.debug("Sent query command")
        try:
            await asyncio.wait_for(self._status_updated_event.wait(), timeout=3)
        except asyncio.TimeoutError:
            _LOGGER.warning("Timeout waiting for status")
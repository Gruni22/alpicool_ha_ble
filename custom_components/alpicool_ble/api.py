"""API for Alpicool fridges based on klightspeed's BrassMonkeyFridgeMonitor."""
import asyncio
import logging
from bleak import BleakClient, BleakError
from .const import FRIDGE_RW_CHARACTERISTIC_UUID, Request, Response

_LOGGER = logging.getLogger(__name__)

class FridgeApi:
    """A class to interact with the fridge."""

    def __init__(self, address: str, disconnected_callback) -> None:
        self._address = address
        self._client = BleakClient(self._address, disconnected_callback=disconnected_callback)
        self.status = {}
        self._lock = asyncio.Lock()

    def _checksum(self, data: bytes) -> int:
        """Calculate the checksum for a given command."""
        return sum(data) & 0xFF

    def _encode_request(self, code: Request, value: int = 0) -> bytearray:
        """Encode a request to send to the fridge."""
        if code in [Request.SET_BATT_PROT]:
            data = bytes([0x08, 0x04, int(code), 0x01, value])
        else:
            data = bytes([0x01, 0x00, 0x08, 0x04, int(code), 0x01, value])
        
        encoded = bytearray(b"\x55\xaa" + data)
        encoded.append(self._checksum(data))
        return encoded

    def _decode_status(self, data: bytearray):
        """Decode a status response from the fridge."""
        if data[2] != Response.STATUS or data[3] != 0x1c:
            _LOGGER.debug(f"Ignoring unknown status message: {data.hex()}")
            return
        
        self.status = {
            "power": bool(data[4]),
            "lock": bool(data[6]),
            "temp_set": int.from_bytes(data[5:6], signed=True),
            "temp_left": int.from_bytes(data[13:14], signed=True),
            "eco_mode": bool(data[18]),
            "voltage": int.from_bytes(data[11:13], signed=False) / 100,
            "battery_protection": ["low", "medium", "high"][data[20]],
        }
        _LOGGER.debug(f"Decoded status: {self.status}")

    def _notification_handler(self, sender, data: bytearray):
        """Handle incoming notifications."""
        if data[0] != 0x55 or data[1] != 0xaa:
            _LOGGER.debug(f"Ignoring unknown message: {data.hex()}")
            return
        
        if self._checksum(data[2:-1]) != data[-1]:
            _LOGGER.warning("Checksum mismatch!")
            return

        self._decode_status(data)

    async def connect(self) -> bool:
        """Connect to the fridge."""
        async with self._lock:
            try:
                if not self._client.is_connected:
                    await self._client.connect()
                    await self._client.start_notify(FRIDGE_RW_CHARACTERISTIC_UUID, self._notification_handler)
                return self._client.is_connected
            except (BleakError, asyncio.TimeoutError) as e:
                _LOGGER.error(f"Failed to connect to fridge: {e}")
                return False

    async def disconnect(self):
        """Disconnect from the fridge."""
        async with self._lock:
            if self._client.is_connected:
                try:
                    await self._client.stop_notify(FRIDGE_RW_CHARACTERISTIC_UUID)
                    await self._client.disconnect()
                except BleakError as e:
                    _LOGGER.error(f"Failed to disconnect cleanly: {e}")
    
    async def send_command(self, code: Request, value: int = 0):
        """Send a command to the fridge."""
        if not await self.connect():
            _LOGGER.error("Cannot send command, not connected.")
            return

        command = self._encode_request(code, value)
        try:
            async with self._lock:
                await self._client.write_gatt_char(FRIDGE_RW_CHARACTERISTIC_UUID, command, response=True)
        except BleakError as e:
            _LOGGER.error(f"Failed to send command: {e}")
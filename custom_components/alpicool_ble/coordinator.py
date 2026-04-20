"""DataUpdateCoordinator for the Alpicool BLE integration."""

import asyncio
from collections.abc import Callable, Coroutine
from datetime import timedelta
import logging
from typing import Any

from bleak import BleakClient, BleakError

from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AlpicoolApi, AlpicoolApiError, AlpicoolConnectionError

_LOGGER = logging.getLogger(__name__)


class AlpicoolDeviceUpdateCoordinator(DataUpdateCoordinator[dict]):
    """Manages fetching data and sending commands to the Alpicool device."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        device_name: str,
        poll_interval: int,
    ) -> None:
        """Initialize the data update coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"Alpicool {address}",
            update_interval=timedelta(seconds=poll_interval),
        )
        self.address = address
        self.device_name = device_name
        self.api = AlpicoolApi()
        self._is_bound_this_session = False

    async def _async_update_data(self) -> dict:
        """Fetch data from the device."""
        ble_device = async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if not ble_device:
            raise UpdateFailed(f"Device with address {self.address} not found")

        client = BleakClient(ble_device)
        try:
            await client.connect()
            await self.api.async_start_notifications(client)
            if not self._is_bound_this_session:
                # BIND is not required by this device. The flag prevents
                # _execute_command from attempting it on subsequent connections.
                self._is_bound_this_session = True
            return await self.api.get_status(client)
        except (AlpicoolConnectionError, BleakError) as e:
            raise UpdateFailed(f"Connection Error: {e}") from e
        except AlpicoolApiError as e:
            raise UpdateFailed(f"API Error: {e}") from e
        finally:
            if client.is_connected:
                await client.disconnect()

    async def _execute_command(
        self,
        api_method: Callable[..., Coroutine[Any, Any, None]],
        *args: Any,
    ) -> None:
        """Connect to device, execute api_method, then fetch updated status."""
        if self.data is None:
            _LOGGER.warning("Cannot send command, no valid data available yet")
            return

        ble_device = async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if not ble_device:
            _LOGGER.error("Cannot send command, device not found: %s", self.address)
            return

        client = BleakClient(ble_device)
        try:
            await client.connect()
            await self.api.async_start_notifications(client)
            await api_method(client, *args)
            await asyncio.sleep(0.5)
            new_status = await self.api.get_status(client)
            self.async_set_updated_data(new_status)
        except (AlpicoolApiError, BleakError) as e:
            _LOGGER.error("Error during command to %s: %s", self.address, e)
            await self.async_request_refresh()
        finally:
            if client.is_connected:
                await client.disconnect()

    async def async_set_values(self, new_values: dict) -> None:
        """Set configuration values on the device."""
        await self._execute_command(self.api.async_set_values, self.data, new_values)

    async def async_set_temperature(self, zone: str, temp: int) -> None:
        """Set the target temperature for a zone."""
        await self._execute_command(self.api.async_set_temperature, zone, temp)

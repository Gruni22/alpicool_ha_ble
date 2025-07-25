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

    def __init__(self, hass: HomeAssistant, address: str, poll_interval: int) -> None:
        """Initialize the data update coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"Alpicool {address}",
            update_interval=timedelta(seconds=poll_interval),
        )
        self.address = address
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
                # Optional: BIND only on the first connection after HA start
                # await self.api.async_send_bind(client)
                self._is_bound_this_session = True
            return await self.api.get_status(client)
        except (AlpicoolConnectionError, BleakError) as e:
            raise UpdateFailed(f"Connection Error: {e}") from e
        except AlpicoolApiError as e:
            raise UpdateFailed(f"API Error: {e}") from e
        finally:
            if client.is_connected:
                await client.disconnect()

    async def send_command(
        self,
        api_method: Callable[..., Coroutine[Any, Any, None]],
        *args: Any,
    ) -> None:
        """Send a command to the device and schedule a refresh."""
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
            # Ensure BIND is performed if it's the first action in the session
            if not self._is_bound_this_session:
                await self.api.async_send_bind(client)
                self._is_bound_this_session = True

            # Send the actual command
            if api_method.__name__ == "async_set_values":
                await api_method(client, self.data, *args)
            else:
                await api_method(client, *args)

            _LOGGER.debug(
                "Command sent successfully to %s, now fetching new status",
                self.address,
            )

            # Give the device a moment to process the command
            await asyncio.sleep(0.5)

            # Get the new status on the same connection to confirm the change
            new_status = await self.api.get_status(client)

            # Update the coordinator's data directly with the confirmed new state
            self.async_set_updated_data(new_status)

        except (AlpicoolApiError, BleakError) as e:
            _LOGGER.error("Error during send_command to %s: %s", self.address, e)
            # Trigger a full refresh to attempt recovery
            await self.async_request_refresh()
        finally:
            if client.is_connected:
                await client.disconnect()

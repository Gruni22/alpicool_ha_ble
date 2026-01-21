"""The Alpicool BLE integration."""

import logging

from bleak.exc import BleakError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .api import FridgeApi
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Alpicool BLE from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    address = entry.data["address"]

    api = FridgeApi(address)
    hass.data[DOMAIN][entry.entry_id] = api

    try:
        if not await api.connect():
            raise ConfigEntryNotReady(
                f"Could not connect to Alpicool device at {address}"
            )
        if not await api.update_status():
            raise ConfigEntryNotReady(
                f"Could not get initial status from Alpicool device at {address}"
            )
    except BleakError as e:
        await api.disconnect()
        raise ConfigEntryNotReady(
            f"Failed to initialize Alpicool device at {address}: {e}"
        ) from e

    api.set_initial_timestamp()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_create_background_task(
        hass,
        api.start_polling(
            lambda: async_dispatcher_send(hass, f"{DOMAIN}_{address}_update")
        ),
        name="alpicool_ble_poll",
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    api: FridgeApi = hass.data[DOMAIN].pop(entry.entry_id)
    await api.disconnect()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

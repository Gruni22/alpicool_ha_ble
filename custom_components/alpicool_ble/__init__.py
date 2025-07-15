"""The Alpicool BLE integration."""
import asyncio
import logging

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
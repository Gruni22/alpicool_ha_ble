"""The Alpicool BLE integration."""
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import Platform

from .api import FridgeCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Alpicool BLE from a config entry."""
    address = entry.unique_id
    assert address is not None

    update_interval = entry.options.get("interval", 60)

    coordinator = FridgeCoordinator(
        hass=hass,
        logger=_LOGGER,
        address=address,
        mode="active",
        update_interval=timedelta(seconds=update_interval)
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await coordinator.async_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(options_update_listener))

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

async def options_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)

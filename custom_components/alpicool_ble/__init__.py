"""The Alpicool BLE integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, Platform
from homeassistant.core import HomeAssistant

from .const import CONF_DUAL_MODE_FRIDGE, CONF_POLL_INTERVAL, DOMAIN
from .coordinator import AlpicoolDeviceUpdateCoordinator

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
    address = entry.data["address"]
    device_name = entry.data.get(CONF_NAME, "Alpicool Fridge")
    poll_interval = entry.options.get(
        CONF_POLL_INTERVAL, entry.data.get(CONF_POLL_INTERVAL, 30)
    )

    coordinator = AlpicoolDeviceUpdateCoordinator(
        hass, address, device_name, poll_interval
    )

    # This will do the first fetch and raise ConfigEntryNotReady if it fails
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

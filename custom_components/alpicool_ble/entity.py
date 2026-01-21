"""Models for the Alpicool BLE integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.device_registry import DeviceInfo

from .api import FridgeApi
from .const import DOMAIN


class AlpicoolEntity(Entity):
    """Base class for Alpicool entities."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, api: FridgeApi) -> None:
        """Initialize the entity."""
        self.api = api
        self._address = entry.data["address"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            name=entry.data["name"],
            manufacturer="Alpicool",
        )

    @property
    def available(self) -> bool:
        """Return True if the device is available."""
        return self.api.is_available

    async def async_added_to_hass(self) -> None:
        """Connect to events."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"{DOMAIN}_{self._address}_update", self.async_write_ha_state
            )
        )

"""Switch platform for the Alpicool BLE integration."""
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import FridgeCoordinator
from .const import DOMAIN, Request
from .models import AlpicoolEntity, build_set_other_payload

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the Alpicool switch entity."""
    api: FridgeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AlpicoolLockSwitch(entry, api)])


class AlpicoolLockSwitch(AlpicoolEntity, SwitchEntity):
    """Representation of the Alpicool lock switch."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, api: FridgeCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(entry, api)
        self._attr_unique_id = f"{self._address}_lock"
        self._attr_name = f"{entry.title} Lock"

    @property
    def is_on(self) -> bool | None:
        """Return true if the lock is on."""
        if not self.available:
            return None
        return self.api.data.get("locked", False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the lock on."""
        payload = build_set_other_payload(self.api.data, {"locked": True})
        await self.api.async_send_command(self.api._build_packet(Request.SET, payload))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the lock off."""
        payload = build_set_other_payload(self.api.data, {"locked": False})
        await self.api.async_send_command(self.api._build_packet(Request.SET, payload))
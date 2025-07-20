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
    coordinator: FridgeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AlpicoolLockSwitch(entry, coordinator)])


class AlpicoolLockSwitch(AlpicoolEntity, SwitchEntity):
    """Representation of the Alpicool lock switch."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, coordinator: FridgeCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(entry, coordinator)
        self._attr_unique_id = f"{self._address}_lock"
        self._attr_name = f"{entry.title} Lock"

    @property
    def is_on(self) -> bool | None:
        """Return true if the lock is on."""
        if not self.available:
            return None
        return self.coordinator.data.get("locked", False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the lock on."""
        payload = build_set_other_payload(self.coordinator.data, {"locked": True})
        await self.coordinator.async_send_command(self.coordinator._build_packet(Request.SET, payload))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the lock off."""
        payload = build_set_other_payload(self.coordinator.data, {"locked": False})
        await self.coordinator.async_send_command(self.coordinator._build_packet(Request.SET, payload))
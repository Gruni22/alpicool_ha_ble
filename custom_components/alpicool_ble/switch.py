"""Switch platform for the Alpicool BLE integration."""

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import AlpicoolDeviceUpdateCoordinator
from .entity import AlpicoolEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Alpicool switch entity."""
    coordinator: AlpicoolDeviceUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AlpicoolLockSwitch(coordinator, entry)])


class AlpicoolLockSwitch(AlpicoolEntity, SwitchEntity):
    """Representation of the Alpicool lock switch."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: AlpicoolDeviceUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._address}_lock"
        # Use the name from the config entry for consistency
        self._attr_name = f"{entry.data['name']} Lock"

    @property
    def is_on(self) -> bool | None:
        """Return true if the lock is on."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("locked", False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the lock on."""
        await self.coordinator.send_command(
            self.coordinator.api.async_set_values, {"locked": True}
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the lock off."""
        await self.coordinator.send_command(
            self.coordinator.api.async_set_values, {"locked": False}
        )

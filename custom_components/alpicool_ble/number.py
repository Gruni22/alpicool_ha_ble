"""Number platform for the Alpicool BLE integration."""

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import AlpicoolDeviceUpdateCoordinator
from .entity import AlpicoolEntity

_LOGGER = logging.getLogger(__name__)

NUMBERS = {
    "left_ret_diff": {
        "name": "Hysteresis",
        "min": 1,
        "max": 10,
        "step": 1,
        "mode": NumberMode.SLIDER,
        "unit": "°C",
    },
    "start_delay": {
        "name": "Start Delay",
        "min": 0,
        "max": 10,
        "step": 1,
        "mode": NumberMode.SLIDER,
        "unit": "min",
    },
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Alpicool number entities."""
    coordinator: AlpicoolDeviceUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        AlpicoolNumber(coordinator, entry, number_key, number_def)
        for number_key, number_def in NUMBERS.items()
    ]
    async_add_entities(entities)


class AlpicoolNumber(AlpicoolEntity, NumberEntity):
    """Representation of an Alpicool Number entity."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: AlpicoolDeviceUpdateCoordinator,
        entry: ConfigEntry,
        number_key: str,
        number_def: dict,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._number_key = number_key

        self._attr_unique_id = f"{self._address}_{self._number_key}"
        self._attr_name = f"{entry.data['name']} {number_def['name']}"
        self._attr_native_min_value = number_def["min"]
        self._attr_native_max_value = number_def["max"]
        self._attr_native_step = number_def["step"]
        self._attr_mode = number_def["mode"]
        self._attr_native_unit_of_measurement = number_def.get("unit")

    @property
    def native_value(self) -> float | None:
        """Return the state of the number entity."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._number_key)

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        await self.coordinator.send_command(
            self.coordinator.api.async_set_values, {self._number_key: int(value)}
        )

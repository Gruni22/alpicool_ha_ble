"""Number platform for the Alpicool BLE integration."""
import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import FridgeApi
from .const import DOMAIN
from .models import AlpicoolEntity, build_set_other_payload

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

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the Alpicool number entities."""
    api: FridgeApi = hass.data[DOMAIN][entry.entry_id]

    entities = [
        AlpicoolNumber(entry, api, number_key, number_def)
        for number_key, number_def in NUMBERS.items()
    ]
    async_add_entities(entities)


class AlpicoolNumber(AlpicoolEntity, NumberEntity):
    """Representation of an Alpicool Number entity."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, api: FridgeApi, number_key: str, number_def: dict) -> None:
        """Initialize the number entity."""
        super().__init__(entry, api)
        self._number_key = number_key
        self._number_def = number_def

        self._attr_unique_id = f"{self._address}_{self._number_key}"
        self._attr_name = f"{entry.data['name']} {self._number_def['name']}"
        self._attr_native_min_value = self._number_def["min"]
        self._attr_native_max_value = self._number_def["max"]
        self._attr_native_step = self._number_def["step"]
        self._attr_mode = self._number_def["mode"]
        self._attr_native_unit_of_measurement = self._number_def.get("unit")

    @property
    def native_value(self) -> float | None:
        """Return the state of the number entity."""
        if not self.available:
            return None
        return self.api.status.get(self._number_key)

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        payload = build_set_other_payload(self.api.status, {self._number_key: int(value)})
        await self.api._send_raw(self.api._build_packet(self.api.Request.SET_OTHER, payload))
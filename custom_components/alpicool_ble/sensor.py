"""Sensor platform for the Alpicool BLE integration."""

from collections.abc import Callable
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfElectricPotential
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import FridgeApi
from .const import DOMAIN
from .entity import AlpicoolEntity

_LOGGER = logging.getLogger(__name__)

SENSORS = {
    "battery_percent": {
        "name": "Battery",
        "unit": PERCENTAGE,
        "device_class": SensorDeviceClass.BATTERY,
        "state_class": SensorStateClass.MEASUREMENT,
        "entity_category": EntityCategory.DIAGNOSTIC,
        "value_fn": lambda status: status.get("bat_percent"),
    },
    "battery_voltage": {
        "name": "Battery Voltage",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": SensorDeviceClass.VOLTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "entity_category": EntityCategory.DIAGNOSTIC,
        "value_fn": lambda status: float(
            f"{status.get('bat_vol_int', 0)}.{status.get('bat_vol_dec', 0)}"
        ),
    },
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Alpicool sensor entities."""
    api: FridgeApi = hass.data[DOMAIN][entry.entry_id]

    entities = [
        AlpicoolSensor(entry, api, sensor_key, sensor_def)
        for sensor_key, sensor_def in SENSORS.items()
    ]
    async_add_entities(entities)


class AlpicoolSensor(AlpicoolEntity, SensorEntity):
    """Representation of an Alpicool Sensor."""

    def __init__(
        self, entry: ConfigEntry, api: FridgeApi, sensor_key: str, sensor_def: dict
    ) -> None:
        """Initialize the sensor."""
        super().__init__(entry, api)
        self._sensor_key = sensor_key
        self._sensor_def = sensor_def

        self._attr_unique_id = f"{self._address}_{self._sensor_key}"
        self._attr_name = f"{entry.data['name']} {self._sensor_def['name']}"
        self._attr_device_class = self._sensor_def.get("device_class")
        self._attr_native_unit_of_measurement = self._sensor_def.get("unit")
        self._attr_state_class = self._sensor_def.get("state_class")
        self._attr_entity_category = self._sensor_def.get("entity_category")

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if not self.available or not self.api.status:
            return None

        value_fn: Callable = self._sensor_def["value_fn"]
        return value_fn(self.api.status)

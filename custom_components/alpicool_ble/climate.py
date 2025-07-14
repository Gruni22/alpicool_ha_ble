"""Climate platform for the Alpicool BLE integration."""
import logging
from typing import Any

from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import FridgeApi
from .const import DOMAIN, Request

_LOGGER = logging.getLogger(__name__)

PRESET_ECO = "Eco"
PRESET_MAX = "Max"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the Alpicool climate entity."""
    address = entry.data["address"]
    ble_device = async_ble_device_from_address(hass, address.upper(), connectable=True)
    if not ble_device:
        _LOGGER.error(f"Device with address {address} not found")
        return

    api = FridgeApi(ble_device.address, None)
    async_add_entities([AlpicoolClimateEntity(entry, api)])


class AlpicoolClimateEntity(ClimateEntity):
    """Representation of an Alpicool refrigerator as a Climate entity."""

    _attr_hvac_modes = [HVACMode.COOL, HVACMode.OFF]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = -20
    _attr_max_temp = 20
    _attr_preset_modes = [PRESET_ECO, PRESET_MAX]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    )
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, api: FridgeApi) -> None:
        """Initialize the climate entity."""
        self.api = api
        self._address = entry.data["address"]
        self._attr_unique_id = self._address
        self._attr_name = entry.data["name"]
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._address)},
            "name": self._attr_name,
            "manufacturer": "Alpicool/Brass Monkey",
        }

    async def async_added_to_hass(self) -> None:
        """Run when entity is added."""
        await self.api.connect()

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity is removed."""
        await self.api.disconnect()

    @property
    def available(self) -> bool:
        """Return True if the device is available."""
        return self.api.status != {}

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return hvac operation."""
        if not self.available:
            return None
        return HVACMode.COOL if self.api.status.get("power") else HVACMode.OFF

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self.api.status.get("temp_left")

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        return self.api.status.get("temp_set")

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        if not self.available:
            return None
        return PRESET_ECO if self.api.status.get("eco_mode") else PRESET_MAX

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the extra state attributes."""
        if not self.available:
            return {}
        return {
            "voltage": self.api.status.get("voltage"),
            "lock": self.api.status.get("lock"),
            "battery_protection": self.api.status.get("battery_protection"),
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        is_on = hvac_mode == HVACMode.COOL
        await self.api.send_command(Request.SET_POWER, int(is_on))

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temp = int(kwargs.get(ATTR_TEMPERATURE, self.target_temperature))
        await self.api.send_command(Request.SET_TEMP, temp)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        is_eco = preset_mode == PRESET_ECO
        await self.api.send_command(Request.SET_ECO, int(is_eco))

    async def async_update(self) -> None:
        """Update the entity. Data is pushed via notifications."""
        # We connect here to ensure the connection is alive
        await self.api.connect()
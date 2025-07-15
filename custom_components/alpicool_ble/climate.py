"""Climate platform for the Alpicool BLE integration."""
import logging
import asyncio
from typing import Any

from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import FridgeApi
from .const import DOMAIN, Request
from .models import AlpicoolEntity, build_set_other_payload

_LOGGER = logging.getLogger(__name__)

PRESET_ECO = "Eco"
PRESET_MAX = "Max"

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the Alpicool climate entities."""
    address = entry.data["address"]
    ble_device = async_ble_device_from_address(hass, address.upper(), connectable=True)
    if not ble_device:
        _LOGGER.error(f"Device with address {address} not found")
        return

    api = FridgeApi(ble_device.address, None)
    hass.data[DOMAIN][entry.entry_id] = api
    
    # Create entities for both left and right zones.
    # The right zone entity will only become available if the device reports data for it.
    entities = [
        AlpicoolClimateZone(entry, api, "left"),
        AlpicoolClimateZone(entry, api, "right"),
    ]
    async_add_entities(entities)

class AlpicoolClimateZone(AlpicoolEntity, ClimateEntity):
    """Representation of an Alpicool refrigerator zone as a Climate entity."""

    _attr_hvac_modes = [HVACMode.COOL, HVACMode.OFF]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1.0
    _attr_min_temp = -20
    _attr_max_temp = 20
    _attr_preset_modes = [PRESET_ECO, PRESET_MAX]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    )
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, api: FridgeApi, zone: str) -> None:
        """Initialize the climate entity for a specific zone."""
        super().__init__(entry, api)
        self._zone = zone
        self._attr_unique_id = f"{self._address}_{self._zone}"
        self._attr_name = f"{entry.data['name']} {self._zone.capitalize()}"

    @property
    def available(self) -> bool:
        """Return True if the device and this specific zone are available."""
        # The right zone is only available if 'right_current' key exists in the status
        if self._zone == "right" and "right_current" not in self.api.status:
            return False
        return super().available

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return hvac operation."""
        if not self.available:
            return None
        return HVACMode.COOL if self.api.status.get("powered_on") else HVACMode.OFF

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature for this zone."""
        return self.api.status.get(f"{self._zone}_current")

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature for this zone."""
        return self.api.status.get(f"{self._zone}_target")

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        if not self.available:
            return None
        return PRESET_ECO if self.api.status.get("run_mode") == 1 else PRESET_MAX

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        is_on = hvac_mode == HVACMode.COOL
        payload = build_set_other_payload(self.api.status, {"powered_on": is_on})
        await self.api._send_raw(self.api._build_packet(Request.SET_OTHER, payload))

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature for this zone."""
        if ATTR_TEMPERATURE in kwargs:
            temp = int(kwargs[ATTR_TEMPERATURE])
            cmd = Request.SET_LEFT if self._zone == "left" else Request.SET_RIGHT
            packet = self.api._build_packet(cmd, bytes([temp & 0xFF]))
            await self.api._send_raw(packet)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        is_eco = preset_mode == PRESET_ECO
        payload = build_set_other_payload(self.api.status, {"run_mode": 1 if is_eco else 0})
        await self.api._send_raw(self.api._build_packet(Request.SET_OTHER, payload))

    async def async_update(self) -> None:
        """Update entity by querying latest state."""
        if self._zone == "left":
            _LOGGER.debug("Alpicool: async_update called by left zone")
            await self.api.update_status()
            _LOGGER.debug("Alpicool: after update, status = %s", self.api.status)
            async_dispatcher_send(self.hass, f"{DOMAIN}_{self._address}_update")
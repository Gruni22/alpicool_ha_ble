"""Climate platform for the Alpicool BLE integration."""
import logging
import asyncio
from typing import Any

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
from .const import (
    DOMAIN,
    Request,
    PRESET_ECO,
    PRESET_MAX,
    PRESET_FRIDGE,
    PRESET_FREEZER,
    CONF_DUAL_ZONE_MODES,
)
from .models import AlpicoolEntity, build_set_other_payload

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the Alpicool climate entities based on initial status."""
    api: FridgeApi = hass.data[DOMAIN][entry.entry_id]
    
    entities = [AlpicoolClimateZone(entry, api, "left")]
    
    if "right_current" in api.status:
        _LOGGER.info("Dual-zone fridge detected, adding right zone entity")
        entities.append(AlpicoolClimateZone(entry, api, "right"))
        
    async_add_entities(entities)

class AlpicoolClimateZone(AlpicoolEntity, ClimateEntity):
    """Representation of an Alpicool refrigerator zone."""

    _attr_hvac_modes = [HVACMode.COOL, HVACMode.OFF]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1.0
    _attr_min_temp = -20
    _attr_max_temp = 20
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    )

    def __init__(self, entry: ConfigEntry, api: FridgeApi, zone: str) -> None:
        """Initialize the climate entity for a specific zone."""
        super().__init__(entry, api)
        self._zone = zone
        # Read the configuration option selected by the user
        self._has_fridge_freezer_mode = entry.data.get(CONF_DUAL_ZONE_MODES, False)
        
        self._attr_unique_id = f"{self._address}_{self._zone}"
        self._attr_name = f"{self._zone.capitalize()}"

    @property
    def _is_dual_zone(self) -> bool:
        """Helper to check if this is a dual-zone model."""
        return "right_current" in self.api.status

    @property
    def preset_modes(self) -> list[str] | None:
        """Return a list of available preset modes based on user configuration."""
        if self._is_dual_zone and self._has_fridge_freezer_mode:
            return [PRESET_FRIDGE, PRESET_FREEZER]
        return [PRESET_MAX, PRESET_ECO]

    @property
    def available(self) -> bool:
        """Return True if the device and this specific zone are available."""
        if not super().available:
            return False
        
        # For configured dual-zone models, the right zone is only available in Freezer mode
        if self._is_dual_zone and self._has_fridge_freezer_mode and self._zone == "right":
            # run_mode 0 is Fridge, 1 is Freezer
            if self.api.status.get("run_mode") == 0:
                return False
        
        return True

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return hvac operation."""
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
        """Return the current preset mode, adapted for user configuration."""
        run_mode = self.api.status.get("run_mode")
        if self._is_dual_zone and self._has_fridge_freezer_mode:
            return PRESET_FREEZER if run_mode == 1 else PRESET_FRIDGE
        return PRESET_ECO if run_mode == 1 else PRESET_MAX

    async def _send_and_update(self, packet: bytes):
        """Send a command, wait briefly, and trigger a status update for all entities."""
        await self.api._send_raw(packet)
        # Give the fridge a moment to process the command before querying its new state
        await asyncio.sleep(0.5)
        await self.api.update_status()
        # Tell all related entities to update their state from the new api.status
        async_dispatcher_send(self.hass, f"{DOMAIN}_{self._address}_update")

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        is_on = hvac_mode == HVACMode.COOL
        payload = build_set_other_payload(self.api.status, {"powered_on": is_on})
        packet = self.api._build_packet(Request.SET, payload)
        await self._send_and_update(packet)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature for this zone."""
        if ATTR_TEMPERATURE in kwargs:
            temp = int(kwargs[ATTR_TEMPERATURE])
            cmd = Request.SET_LEFT if self._zone == "left" else Request.SET_RIGHT
            packet = self.api._build_packet(cmd, bytes([temp & 0xFF]))
            await self._send_and_update(packet)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        is_mode_1 = preset_mode in [PRESET_ECO, PRESET_FREEZER]
        payload = build_set_other_payload(self.api.status, {"run_mode": 1 if is_mode_1 else 0})
        packet = self.api._build_packet(Request.SET, payload)
        await self._send_and_update(packet)
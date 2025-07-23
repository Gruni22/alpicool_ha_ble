"""Climate platform for the Alpicool BLE integration."""

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_DUAL_MODE_FRIDGE,
    DOMAIN,
    PRESET_ECO,
    PRESET_FREEZER,
    PRESET_FRIDGE,
    PRESET_MAX,
)
from .coordinator import AlpicoolDeviceUpdateCoordinator
from .entity import AlpicoolEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Alpicool climate entities based on initial status."""
    coordinator: AlpicoolDeviceUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # We need the initial data to know if it's a dual-zone model
    if coordinator.data is None:
        _LOGGER.warning(
            "No initial data from coordinator, climate entity setup deferred"
        )
        return

    entities = [AlpicoolClimateZone(coordinator, entry, "left")]

    if "right_current" in coordinator.data:
        _LOGGER.debug("Dual-mode fridge detected, adding right zone entity")
        entities.append(AlpicoolClimateZone(coordinator, entry, "right"))

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

    def __init__(
        self,
        coordinator: AlpicoolDeviceUpdateCoordinator,
        entry: ConfigEntry,
        zone: str,
    ) -> None:
        """Initialize the climate entity for a specific zone."""
        super().__init__(coordinator)
        self._zone = zone
        self._entry = entry
        self._has_fridge_freezer_mode = entry.data.get(CONF_DUAL_MODE_FRIDGE, False)

        self._attr_unique_id = f"{self._address}_{self._zone}"
        self._attr_name = f"{entry.data['name']} {self._zone.capitalize()}"

    @property
    def _is_dual_zone(self) -> bool:
        """Helper to check if this is a dual-zone model."""
        return (
            self.coordinator.data is not None
            and "right_current" in self.coordinator.data
        )

    @property
    def preset_modes(self) -> list[str] | None:
        """Return a list of available preset modes based on user configuration."""
        if self._is_dual_zone and self._has_fridge_freezer_mode:
            return [PRESET_FRIDGE, PRESET_FREEZER]
        return [PRESET_MAX, PRESET_ECO]

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return hvac operation."""
        if self.coordinator.data is None:
            return None
        return (
            HVACMode.COOL if self.coordinator.data.get("powered_on") else HVACMode.OFF
        )

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature for this zone."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(f"{self._zone}_current")

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature for this zone."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(f"{self._zone}_target")

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode, adapted for user configuration."""
        if self.coordinator.data is None:
            return None
        run_mode = self.coordinator.data.get("run_mode")
        if self._is_dual_zone and self._has_fridge_freezer_mode:
            return PRESET_FREEZER if run_mode == 1 else PRESET_FRIDGE
        return PRESET_ECO if run_mode == 1 else PRESET_MAX

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        is_on = hvac_mode == HVACMode.COOL
        await self.coordinator.send_command(
            self.coordinator.api.async_set_values, {"powered_on": is_on}
        )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature for this zone."""
        if ATTR_TEMPERATURE in kwargs:
            temp = int(kwargs[ATTR_TEMPERATURE])
            await self.coordinator.send_command(
                self.coordinator.api.async_set_temperature, self._zone, temp
            )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        is_mode_1 = preset_mode in [PRESET_ECO, PRESET_FREEZER]
        run_mode_value = 1 if is_mode_1 else 0
        await self.coordinator.send_command(
            self.coordinator.api.async_set_values, {"run_mode": run_mode_value}
        )

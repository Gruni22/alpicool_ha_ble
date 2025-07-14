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
    _attr_target_temperature_step = 1.0
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
            "manufacturer": "Alpicool",
        }

    async def async_added_to_hass(self) -> None:
        """Run when entity is added."""
        _LOGGER.debug("Alpicool: async_added_to_hass - trying to connect")
        connected = await self.api.connect()
        if connected:
            _LOGGER.debug("Initial connection successful. The entity will now be updated by Home Assistant.")
        else:
            _LOGGER.warning("Initial connection to Alpicool failed. The entity will be unavailable and retry later.")

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity is removed."""
        await self.api.disconnect()

    @property
    def available(self) -> bool:
        """Return True if the device is available."""
        _LOGGER.debug("Checking availability, api.status = %s", self.api.status)
        return bool(self.api.status)

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return hvac operation."""
        if not self.available:
            return None
        return HVACMode.COOL if self.api.status.get("powered_on") else HVACMode.OFF

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self.api.status.get("left_current")

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        return self.api.status.get("left_target")

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        if not self.available:
            return None
        return PRESET_ECO if self.api.status.get("run_mode") == 1 else PRESET_MAX

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the extra state attributes."""
        if not self.available:
            return {}
        return {
            "battery_percent": self.api.status.get("bat_percent"),
            "battery_voltage": f"{self.api.status.get('bat_vol_int', 0)}.{self.api.status.get('bat_vol_dec', 0)}",
            "locked": self.api.status.get("locked"),
            "start_delay": self.api.status.get("start_delay"),
            "hysteresis": self.api.status.get("left_ret_diff"),
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.COOL:
            new_status = self.api.status.copy()
            new_status["powered_on"] = True
        else:
            new_status = self.api.status.copy()
            new_status["powered_on"] = False

        # Compose full set payload
        payload = self._build_set_payload(new_status)
        await self.api._send_raw(payload)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if ATTR_TEMPERATURE in kwargs:
            temp = int(kwargs[ATTR_TEMPERATURE])
            packet = self.api._build_packet(Request.SET_LEFT, bytes([temp]))
            await self.api._send_raw(packet)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        new_status = self.api.status.copy()
        new_status["run_mode"] = 1 if preset_mode == PRESET_ECO else 0

        payload = self._build_set_payload(new_status)
        await self.api._send_raw(payload)

    async def async_update(self) -> None:
        """Update entity by querying latest state."""
        _LOGGER.debug("Alpicool: async_update called")
        await self.api.update_status()
        _LOGGER.debug("Alpicool: after update, status = %s", self.api.status)

    def _build_set_payload(self, status: dict) -> bytes:
        """Build the payload for setOther command."""
        def to_unsigned_byte(x: int) -> int:
            """Convert a signed int (-128 to 127) to its unsigned byte value (0-255)."""
            return x & 0xFF

        data = bytearray([
            int(status.get("locked", 0)),
            int(status.get("powered_on", 1)),
            int(status.get("run_mode", 0)),
            int(status.get("bat_saver", 0)),
            to_unsigned_byte(status.get("left_target", 0)),
            to_unsigned_byte(status.get("temp_max", 20)),
            to_unsigned_byte(status.get("temp_min", -20)),
            to_unsigned_byte(status.get("left_ret_diff", 1)),
            int(status.get("start_delay", 0)),
            int(status.get("unit", 0)),
            to_unsigned_byte(status.get("left_tc_hot", 0)),
            to_unsigned_byte(status.get("left_tc_mid", 0)),
            to_unsigned_byte(status.get("left_tc_cold", 0)),
            to_unsigned_byte(status.get("left_tc_halt", 0)),
        ])
        return self.api._build_packet(Request.SET_OTHER, data)

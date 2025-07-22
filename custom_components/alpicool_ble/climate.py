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
    """Set up the Alpicool climate entities."""
    address = entry.data["address"]
    ble_device = async_ble_device_from_address(hass, address.upper(), connectable=True)
    if not ble_device:
        _LOGGER.error(f"Device with address {address} not found")
        return

    api = FridgeApi(ble_device.address, None)
    
    # Create entities for both left and right zones.
    # The right zone entity will only become available if the device reports data for it.
    entities = [
        AlpicoolClimateEntity(entry, api, "left"),
        AlpicoolClimateEntity(entry, api, "right"),
    ]
    async_add_entities(entities)

class AlpicoolClimateEntity(ClimateEntity):
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
        self.api = api
        self._zone = zone
        self._address = entry.data["address"]
        
        self._attr_unique_id = f"{self._address}_{self._zone}"
        self._attr_name = f"{entry.data['name']} {self._zone.capitalize()}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._address)},
            "name": entry.data["name"],
            "manufacturer": "Alpicool",
        }

    async def async_added_to_hass(self) -> None:
        """Run when entity is added."""
        # Only have the 'left' entity handle the initial connection
        if self._zone == "left":
            _LOGGER.debug("Alpicool: async_added_to_hass - trying to connect")
            connected = await self.api.connect()
            if connected:
                _LOGGER.debug("Initial connection successful. The entity will now be updated by Home Assistant.")
            else:
                _LOGGER.warning("Initial connection to Alpicool failed. The entity will be unavailable and retry later.")

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity is removed."""
        # Only have the 'left' entity handle the disconnection
        if self._zone == "left":
            await self.api.disconnect()

    @property
    def available(self) -> bool:
        """Return True if the device and this specific zone are available."""
        # The right zone is only available if 'right_current' key exists in the status
        if self._zone == "right" and "right_current" not in self.api.status:
            return False
        return bool(self.api.status)

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
        """Return the current preset mode (same for both zones)."""
        if not self.available:
            return None
        return PRESET_ECO if self.api.status.get("run_mode") == 1 else PRESET_MAX

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the extra state attributes."""
        if not self.available:
            return {}
        
        # Base attributes are shown for both entities
        attrs = {
            "battery_percent": self.api.status.get("bat_percent"),
            "battery_voltage": f"{self.api.status.get('bat_vol_int', 0)}.{self.api.status.get('bat_vol_dec', 0)}",
            "locked": self.api.status.get("locked"),
        }
        # Hysteresis is zone-specific
        attrs["hysteresis"] = self.api.status.get(f"{self._zone}_ret_diff")
        return attrs

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.COOL:
            await self._send_set_command({"powered_on": True})
        else:
            await self._send_set_command({"powered_on": False})

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature for this zone."""
        if ATTR_TEMPERATURE in kwargs:
            temp = int(kwargs[ATTR_TEMPERATURE])
            cmd = Request.SET_LEFT if self._zone == "left" else Request.SET_RIGHT
            packet = self.api._build_packet(cmd, bytes([temp & 0xFF]))
            await self.api._send_raw(packet)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        await self._send_set_command({"run_mode": 1 if preset_mode == PRESET_ECO else 0})

    async def async_update(self) -> None:
        """Update entity by querying latest state."""
        # Only have the 'left' entity trigger the update to avoid duplicate calls
        if self._zone == "left":
            _LOGGER.debug("Alpicool: async_update called by left zone")
            await self.api.update_status()
            _LOGGER.debug("Alpicool: after update, status = %s", self.api.status)

    def _build_set_other_payload(self, new_values: dict) -> bytes:
        """Build the complete payload for the setOther command."""
        status = self.api.status.copy()
        status.update(new_values)

        def to_unsigned_byte(x: int) -> int:
            return x & 0xFF

        # Build payload for both zones, using defaults if not available
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
            # Dual-zone SET payload starts here
            to_unsigned_byte(status.get("right_target", 0)),
            0, # Always zero
            0, # Always zero
            to_unsigned_byte(status.get("right_ret_diff", 1)),
            to_unsigned_byte(status.get("right_tc_hot", 0)),
            to_unsigned_byte(status.get("right_tc_mid", 0)),
            to_unsigned_byte(status.get("right_tc_cold", 0)),
            to_unsigned_byte(status.get("right_tc_halt", 0)),
            0, # Always zero
            0, # Always zero
            0, # Always zero
        ])
        return self.api._build_packet(Request.SET_OTHER, data)

    async def _send_set_command(self, new_values: dict):
        """Helper to send a SET_OTHER command."""
        payload = self._build_set_other_payload(new_values)
        await self.api._send_raw(payload)
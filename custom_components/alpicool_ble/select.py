"""Select platform for the Alpicool BLE integration."""
import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import FridgeCoordinator
from .const import DOMAIN, Request, BatteryProtection
from .models import AlpicoolEntity, build_set_other_payload

_LOGGER = logging.getLogger(__name__)

BATTERY_SAVER_OPTIONS = [level.name.capitalize() for level in BatteryProtection]
BATTERY_SAVER_MAP = {level.name.capitalize(): level.value for level in BatteryProtection}
BATTERY_SAVER_MAP_REV = {v: k for k, v in BATTERY_SAVER_MAP.items()}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the Alpicool select entities."""
    api: FridgeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AlpicoolBatterySaverSelect(entry, api)])


class AlpicoolBatterySaverSelect(AlpicoolEntity, SelectEntity):
    """Representation of the Alpicool Battery Saver select entity."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = BATTERY_SAVER_OPTIONS

    def __init__(self, entry: ConfigEntry, api: FridgeCoordinator) -> None:
        """Initialize the select entity."""
        super().__init__(entry, api)
        self._attr_unique_id = f"{self._address}_battery_saver"
        self._attr_name = "Battery Saver"

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option."""
        if not self.available:
            return None
        
        bat_saver_value = self.api.data.get("bat_saver")
        # Map the numeric value (0, 1, 2) to the string ("Low", "Medium", "High")
        return BATTERY_SAVER_MAP_REV.get(bat_saver_value)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option not in self.options:
            _LOGGER.warning(f"Invalid option selected: {option}")
            return
            
        # Map the string ("Low", "Medium", "High") back to the numeric value
        bat_saver_value = BATTERY_SAVER_MAP.get(option)
        
        payload = build_set_other_payload(self.api.data, {"bat_saver": bat_saver_value})
        packet = self.api._build_packet(Request.SET, payload)
        await self.api.async_send_command(packet)

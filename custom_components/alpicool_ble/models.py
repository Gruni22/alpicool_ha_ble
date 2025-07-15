"""Models for the Alpicool BLE integration."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo, Entity

from .api import FridgeApi
from .const import DOMAIN


class AlpicoolEntity(Entity):
    """Base class for Alpicool entities."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, api: FridgeApi) -> None:
        """Initialize the entity."""
        self.api = api
        self._address = entry.data["address"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            name=entry.data["name"],
            manufacturer="Alpicool",
        )

    @property
    def available(self) -> bool:
        """Return True if the device is available."""
        return bool(self.api.status)

    async def async_added_to_hass(self) -> None:
        """Connect to events."""
        self.async_on_remove(
            self.hass.helpers.dispatcher.async_dispatcher_connect(
                f"{DOMAIN}_{self._address}_update", self.async_write_ha_state
            )
        )

def build_set_other_payload(status: dict, new_values: dict) -> bytes:
    """Build the complete payload for the setOther command."""
    current_status = status.copy()
    current_status.update(new_values)

    def to_unsigned_byte(x: int) -> int:
        return x & 0xFF

    data = bytearray([
        int(current_status.get("locked", 0)),
        int(current_status.get("powered_on", 1)),
        int(current_status.get("run_mode", 0)),
        int(current_status.get("bat_saver", 0)),
        to_unsigned_byte(current_status.get("left_target", 0)),
        to_unsigned_byte(current_status.get("temp_max", 20)),
        to_unsigned_byte(current_status.get("temp_min", -20)),
        to_unsigned_byte(current_status.get("left_ret_diff", 1)),
        int(current_status.get("start_delay", 0)),
        int(current_status.get("unit", 0)),
        to_unsigned_byte(current_status.get("left_tc_hot", 0)),
        to_unsigned_byte(current_status.get("left_tc_mid", 0)),
        to_unsigned_byte(current_status.get("left_tc_cold", 0)),
        to_unsigned_byte(current_status.get("left_tc_halt", 0)),
    ])

    if "right_current" in current_status:
        right_zone_data = bytearray([
            to_unsigned_byte(current_status.get("right_target", 0)),
            0, 0,
            to_unsigned_byte(current_status.get("right_ret_diff", 1)),
            to_unsigned_byte(current_status.get("right_tc_hot", 0)),
            to_unsigned_byte(current_status.get("right_tc_mid", 0)),
            to_unsigned_byte(current_status.get("right_tc_cold", 0)),
            to_unsigned_byte(current_status.get("right_tc_halt", 0)),
            0, 0, 0,
        ])
        data.extend(right_zone_data)

    return data
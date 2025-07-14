"""Config flow for Alpicool BLE."""
import voluptuous as vol
from typing import Any

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, FRIDGE_SERVICE_UUID


class AlpicoolConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Alpicool BLE."""
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the user step to select a device."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input["name"], data={CONF_ADDRESS: address}
            )

        current_addresses = self._async_current_ids()
        discovered_devices = {}
        for discovery_info in async_discovered_service_info(self.hass):
            address = discovery_info.address
            if address in current_addresses or FRIDGE_SERVICE_UUID not in discovery_info.service_uuids:
                continue
            discovered_devices[address] = discovery_info.name

        if not discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ADDRESS): vol.In(discovered_devices),
                vol.Required("name", default=list(discovered_devices.values())[0]): str
            }),
        )
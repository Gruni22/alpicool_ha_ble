"""Config flow for Alpicool BLE."""
from __future__ import annotations
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
)
from homeassistant.config_entries import ConfigFlow, ConfigEntry, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_DUAL_ZONE_MODES

_LOGGER = logging.getLogger(__name__)

CONF_NAME = "name"


class AlpicoolConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Alpicool BLE."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle discovery via Bluetooth."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        return self.async_show_form(step_id="user")

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the user step to optionally enter a MAC address."""
        errors = {}
        if self._discovery_info:
            return self.async_create_entry(
                title=self._discovery_info.name, 
                data={"address": self._discovery_info.address}
            )

        if user_input is not None:
            address = user_input["address"]
            if ble_device := async_ble_device_from_address(self.hass, address.upper(), True):
                await self.async_set_unique_id(ble_device.address, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=ble_device.name or address, 
                    data={"address": ble_device.address}
                )
            
            errors["base"] = "cannot_find_device"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("address"): str,
            }),
            errors=errors,
            description_placeholders={"docs_url": "https://www.home-assistant.io/integrations/bluetooth/"}
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return AlpicoolOptionsFlow(config_entry)


class AlpicoolOptionsFlow(OptionsFlow):
    """Handle an options flow for Alpicool BLE."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get("interval", 60)
        current_dual_mode = self.config_entry.options.get(CONF_DUAL_ZONE_MODES, False)

        return self.async_show_form(
            step_id="init",
             data_schema=vol.Schema({
                vol.Required("interval", default=current_interval): vol.All(vol.Coerce(int), vol.Range(min=10)),
                vol.Optional(CONF_DUAL_ZONE_MODES, default=current_dual_mode): bool,
            }),
            description_placeholders={"device_name": self.config_entry.title}
        )

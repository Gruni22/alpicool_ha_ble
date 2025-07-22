"""Config flow for Alpicool BLE."""
from __future__ import annotations
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
)
from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN

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
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the user step to finish setup."""
        if not self._discovery_info:
            return self.async_abort(reason="no_devices_found")

        if user_input is None:
            data_schema = vol.Schema({
                vol.Optional(CONF_NAME, default=self._discovery_info.name): str,
            })

            return self.async_show_form(
                step_id="user",
                description_placeholders=self.context.get("title_placeholders"),
                data_schema=data_schema,
            )

        name = user_input.get(CONF_NAME, self._discovery_info.name)

        return self.async_create_entry(
            title=name,
            data={
                CONF_ADDRESS: self._discovery_info.address,
                CONF_NAME: name,
            },
        )

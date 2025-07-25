"""Config flow for Alpicool BLE."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS, CONF_NAME

from .const import CONF_DUAL_MODE_FRIDGE, CONF_POLL_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


def normalize_ble_address(addr: str) -> str | None:
    """Normalize BLE address to format XX:XX:XX:XX:XX:XX or return None if invalid."""
    addr = addr.replace("-", "").replace(":", "").lower()
    if len(addr) != 12 or not all(c in "0123456789abcdef" for c in addr):
        return None
    return ":".join(addr[i : i + 2] for i in range(0, 12, 2)).upper()


class AlpicoolConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Alpicool BLE."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle discovery via Bluetooth."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user step to finish setup."""
        errors = {}

        if user_input is not None:
            raw_address = user_input.get(CONF_ADDRESS)
            normalized_address = normalize_ble_address(raw_address)

            if not normalized_address:
                errors["base"] = "invalid_address"
            else:
                name = user_input.get(CONF_NAME, normalized_address)
                await self.async_set_unique_id(normalized_address)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_ADDRESS: normalized_address,
                        CONF_NAME: name,
                        CONF_DUAL_MODE_FRIDGE: user_input.get(
                            CONF_DUAL_MODE_FRIDGE, False
                        ),
                        CONF_POLL_INTERVAL: user_input.get(CONF_POLL_INTERVAL, 30),
                    },
                )

        default_name = (
            self._discovery_info.name if self._discovery_info else "Alpicool Fridge"
        )
        default_address = self._discovery_info.address if self._discovery_info else ""

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS, default=default_address): str,
                vol.Optional(CONF_NAME, default=default_name): str,
                vol.Optional(CONF_DUAL_MODE_FRIDGE, default=False): bool,
                vol.Optional(CONF_POLL_INTERVAL, default=30): int,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

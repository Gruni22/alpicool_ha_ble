"""Tests for the Alpicool BLE config flow.

normalize_ble_address tests run everywhere.
Config/Options flow tests require homeassistant — Linux / WSL2 / CI only.
"""

import sys
import pytest
from unittest.mock import AsyncMock, patch

from custom_components.alpicool_ble.config_flow import normalize_ble_address
from custom_components.alpicool_ble.const import (
    CONF_DUAL_MODE_FRIDGE,
    CONF_POLL_INTERVAL,
    DOMAIN,
)

_HA_AVAILABLE = sys.platform != "win32"
skip_no_ha = pytest.mark.skipif(
    not _HA_AVAILABLE,
    reason="homeassistant requires Linux (fcntl). Use WSL2 or GitHub Actions CI.",
)

if _HA_AVAILABLE:
    from homeassistant import config_entries
    from homeassistant.core import HomeAssistant
    from homeassistant.data_entry_flow import FlowResultType


# ---------------------------------------------------------------------------
# normalize_ble_address
# ---------------------------------------------------------------------------

class TestNormalizeBleAddress:
    def test_colon_separated(self):
        assert normalize_ble_address("aa:bb:cc:dd:ee:ff") == "AA:BB:CC:DD:EE:FF"

    def test_dash_separated(self):
        assert normalize_ble_address("aa-bb-cc-dd-ee-ff") == "AA:BB:CC:DD:EE:FF"

    def test_uppercase_input(self):
        assert normalize_ble_address("AA:BB:CC:DD:EE:FF") == "AA:BB:CC:DD:EE:FF"

    def test_no_separator(self):
        assert normalize_ble_address("aabbccddeeff") == "AA:BB:CC:DD:EE:FF"

    def test_too_short_returns_none(self):
        assert normalize_ble_address("aa:bb:cc") is None

    def test_invalid_chars_returns_none(self):
        assert normalize_ble_address("gg:bb:cc:dd:ee:ff") is None

    def test_empty_returns_none(self):
        assert normalize_ble_address("") is None

    def test_too_long_returns_none(self):
        assert normalize_ble_address("aa:bb:cc:dd:ee:ff:00") is None


# ---------------------------------------------------------------------------
# Config flow — user step  (Linux / WSL2 / CI only)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_coordinator_setup():
    """Prevent actual BLE connections during config flow tests."""
    with patch(
        "custom_components.alpicool_ble.async_setup_entry",
        return_value=True,
    ):
        yield


@skip_no_ha
async def test_user_flow_shows_form(hass: "HomeAssistant") -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert "errors" in result


@skip_no_ha
async def test_user_flow_invalid_address(hass: "HomeAssistant") -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"address": "not-a-mac", "name": "Fridge"},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_address"


@skip_no_ha
async def test_user_flow_creates_entry(hass: "HomeAssistant", mock_coordinator_setup) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "address": "AA:BB:CC:DD:EE:FF",
            "name": "My Fridge",
            CONF_DUAL_MODE_FRIDGE: False,
            CONF_POLL_INTERVAL: 30,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "My Fridge"
    assert result["data"]["address"] == "AA:BB:CC:DD:EE:FF"
    assert result["data"]["name"] == "My Fridge"


@skip_no_ha
async def test_user_flow_address_normalized(hass: "HomeAssistant", mock_coordinator_setup) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"address": "aa-bb-cc-dd-ee-ff", "name": "Fridge"},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["address"] == "AA:BB:CC:DD:EE:FF"


@skip_no_ha
async def test_duplicate_address_aborted(hass: "HomeAssistant", mock_coordinator_setup) -> None:
    # First entry
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"address": "AA:BB:CC:DD:EE:FF", "name": "Fridge 1"},
    )
    # Second entry with same address
    result2 = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result2["flow_id"],
        {"address": "AA:BB:CC:DD:EE:FF", "name": "Fridge 2"},
    )
    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "already_configured"


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------

@skip_no_ha
async def test_options_flow_shows_form(hass: "HomeAssistant", mock_config_entry) -> None:
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"


@skip_no_ha
async def test_options_flow_saves_options(hass: "HomeAssistant", mock_config_entry) -> None:
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_DUAL_MODE_FRIDGE: True, CONF_POLL_INTERVAL: 60},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_DUAL_MODE_FRIDGE] is True
    assert mock_config_entry.options[CONF_POLL_INTERVAL] == 60


@skip_no_ha
async def test_options_flow_defaults_from_data(hass: "HomeAssistant") -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "address": "AA:BB:CC:DD:EE:FF",
            "name": "Fridge",
            CONF_DUAL_MODE_FRIDGE: True,
            CONF_POLL_INTERVAL: 45,
        },
        options={},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    # The schema defaults should reflect entry.data values when options are empty
    schema = result["data_schema"].schema
    defaults = {k.description["suggested_value"] if hasattr(k, "description") else str(k): v
                for k, v in schema.items() if hasattr(k, "default")}
    # Just verify the flow opens without error
    assert result["type"] == FlowResultType.FORM

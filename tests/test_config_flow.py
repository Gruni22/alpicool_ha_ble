"""Tests for the Alpicool BLE config and options flow."""

import pytest
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.alpicool_ble.config_flow import normalize_ble_address
from custom_components.alpicool_ble.const import (
    CONF_DUAL_ZONE_MODES,
    CONF_LEFT_NAME,
    CONF_RIGHT_NAME,
    DOMAIN,
)

ADDRESS = "AA:BB:CC:DD:EE:FF"


# --- Address normalisation (issue #22) ------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "AA:BB:CC:DD:EE:FF",
        "aa:bb:cc:dd:ee:ff",
        "aa-bb-cc-dd-ee-ff",
        "AABBCCDDEEFF",
        "aabbccddeeff",
    ],
)
def test_addresses_normalise_to_one_form(raw: str) -> None:
    """Casing and separators must not decide whether the fridge is reachable."""
    assert normalize_ble_address(raw) == ADDRESS


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "AA:BB:CC:DD:EE",
        "AA:BB:CC:DD:EE:FF:00",
        "ZZ:BB:CC:DD:EE:FF",
        "not an address",
    ],
)
def test_invalid_addresses_are_rejected(raw: str) -> None:
    """Anything that is not twelve hex digits is refused."""
    assert normalize_ble_address(raw) is None


# --- User flow ------------------------------------------------------------


async def test_user_flow_creates_a_normalised_entry(
    hass: HomeAssistant, enable_bluetooth: None
) -> None:
    """A lowercase address typed by hand ends up in the canonical form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_ADDRESS: "aa-bb-cc-dd-ee-ff", CONF_NAME: "Cool Box"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ADDRESS] == ADDRESS
    assert result["title"] == "Cool Box"


async def test_invalid_address_shows_the_form_again(
    hass: HomeAssistant, enable_bluetooth: None
) -> None:
    """A bad address must not create an entry or blow up the flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: "nonsense", CONF_NAME: "Cool Box"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_address"}
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_the_form_can_be_corrected(
    hass: HomeAssistant, enable_bluetooth: None
) -> None:
    """After the error the user can fix the address in the same flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: "nonsense"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: ADDRESS, CONF_NAME: "Cool Box"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ADDRESS] == ADDRESS


async def test_the_same_fridge_cannot_be_added_twice(
    hass: HomeAssistant, enable_bluetooth: None
) -> None:
    """Differently cased input still matches the existing entry."""
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDRESS,
        data={CONF_ADDRESS: ADDRESS, CONF_NAME: "Fridge"},
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: "aa:bb:cc:dd:ee:ff"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# --- Options flow (issues #15 and #21) ------------------------------------


async def test_options_flow_stores_zone_names(
    hass: HomeAssistant, enable_bluetooth: None
) -> None:
    """Zone names and the fridge/freezer mode are editable after setup."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDRESS,
        data={CONF_ADDRESS: ADDRESS, CONF_NAME: "Fridge"},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_DUAL_ZONE_MODES: True,
            CONF_LEFT_NAME: "Top",
            CONF_RIGHT_NAME: "Bottom",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_LEFT_NAME] == "Top"
    assert entry.options[CONF_DUAL_ZONE_MODES] is True

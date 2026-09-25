"""Tests for the Alpicool sensor entities."""

from unittest.mock import AsyncMock, MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.alpicool_ble.const import DOMAIN
from custom_components.alpicool_ble.sensor import SENSORS, AlpicoolSensor


ADDRESS = "AA:BB:CC:DD:EE:FF"


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, data={"address": ADDRESS, "name": "Fridge"}, options={}
    )


def _api(**status) -> MagicMock:
    api = MagicMock()
    api.status = status
    api.is_available = True
    api.is_fahrenheit = False
    api.async_set_values = AsyncMock()
    api.update_status = AsyncMock(return_value=True)
    return api


# --- Voltage keeps its tenth ----------------------------------------------


def test_battery_voltage_is_shown_with_one_decimal() -> None:
    """The fridge reports 14.6 V; the UI must not round it to 15 V."""
    sensor = AlpicoolSensor(
        _entry(),
        _api(bat_vol_int=14, bat_vol_dec=6),
        "battery_voltage",
        SENSORS["battery_voltage"],
    )
    assert sensor.native_value == 14.6
    assert sensor.suggested_display_precision == 1

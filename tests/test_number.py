"""Tests for the Alpicool number entities."""

from unittest.mock import MagicMock

from homeassistant.const import UnitOfTemperature
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.alpicool_ble.const import DOMAIN
from custom_components.alpicool_ble.number import NUMBERS, AlpicoolNumber

ADDRESS = "AA:BB:CC:DD:EE:FF"


def make_number(key: str, **status) -> AlpicoolNumber:
    """Return a number entity wired to a fake API."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={"address": ADDRESS, "name": "Fridge"}, options={}
    )
    api = MagicMock()
    api.status = status
    api.is_available = True
    api.is_fahrenheit = status.get("unit") == 1
    return AlpicoolNumber(entry, api, key, NUMBERS[key])


def test_hysteresis_unit_follows_the_fridge() -> None:
    """A temperature difference must not be labelled °C on a Fahrenheit fridge."""
    assert (
        make_number("left_ret_diff", unit=1).native_unit_of_measurement
        == UnitOfTemperature.FAHRENHEIT
    )
    assert (
        make_number("left_ret_diff", unit=0).native_unit_of_measurement
        == UnitOfTemperature.CELSIUS
    )


def test_hysteresis_defaults_to_celsius() -> None:
    """Before the first status arrives Celsius is assumed."""
    assert (
        make_number("left_ret_diff").native_unit_of_measurement
        == UnitOfTemperature.CELSIUS
    )


def test_non_temperature_numbers_keep_their_unit() -> None:
    """The start delay stays in minutes regardless of the fridge setting."""
    assert make_number("start_delay", unit=1).native_unit_of_measurement == "min"


def test_value_is_read_from_status() -> None:
    """The entity reports what the fridge sent."""
    assert make_number("left_ret_diff", left_ret_diff=3).native_value == 3

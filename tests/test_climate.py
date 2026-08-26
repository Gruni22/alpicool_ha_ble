"""Tests for the Alpicool climate entities."""

from unittest.mock import MagicMock

from homeassistant.components.climate.const import HVACMode
from homeassistant.const import UnitOfTemperature
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.alpicool_ble.climate import AlpicoolClimateZone
from custom_components.alpicool_ble.const import (
    CONF_DUAL_ZONE_MODES,
    CONF_LEFT_NAME,
    CONF_RIGHT_NAME,
    DOMAIN,
    PRESET_ECO,
    PRESET_FREEZER,
    PRESET_FRIDGE,
    PRESET_MAX,
)

ADDRESS = "AA:BB:CC:DD:EE:FF"


def make_entry(**options) -> MockConfigEntry:
    """Return a config entry for a fridge, with optional user options."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={"address": ADDRESS, "name": "Fridge"},
        options=options,
    )


def make_api(**status) -> MagicMock:
    """Return an API stand-in exposing a given status dict."""
    api = MagicMock()
    api.status = status
    api.is_available = True
    api.is_fahrenheit = status.get("unit") == 1
    return api


def make_zone(zone: str = "left", entry=None, **status) -> AlpicoolClimateZone:
    """Return a climate entity wired to a fake API."""
    return AlpicoolClimateZone(entry or make_entry(), make_api(**status), zone)


# --- Temperature unit (issues #15, #18, #21) -------------------------------


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        (0, UnitOfTemperature.CELSIUS),
        (1, UnitOfTemperature.FAHRENHEIT),
    ],
)
def test_temperature_unit_follows_the_fridge(unit: int, expected: str) -> None:
    """The fridge's own unit setting is mirrored to Home Assistant."""
    assert make_zone(unit=unit).temperature_unit == expected


def test_temperature_unit_defaults_to_celsius() -> None:
    """Before the first status arrives Celsius is assumed."""
    assert make_zone().temperature_unit == UnitOfTemperature.CELSIUS


def test_limits_come_from_the_fridge() -> None:
    """The fridge reports its own selectable range and it is used as is."""
    zone = make_zone(unit=1, temp_min=-4, temp_max=68)

    assert (zone.min_temp, zone.max_temp) == (-4, 68)


def test_limits_fall_back_per_unit() -> None:
    """Without a usable range the fallback matches the reported unit."""
    assert (make_zone(unit=1).min_temp, make_zone(unit=1).max_temp) == (-22, 68)
    assert (make_zone(unit=0).min_temp, make_zone(unit=0).max_temp) == (-30, 20)


def test_implausible_limits_are_ignored() -> None:
    """A fridge that reports min >= max does not lock the slider up."""
    zone = make_zone(unit=0, temp_min=0, temp_max=0)

    assert (zone.min_temp, zone.max_temp) == (-30, 20)


def test_temperatures_are_passed_through_unconverted() -> None:
    """Values on the wire are already in the fridge's unit."""
    zone = make_zone(unit=1, left_current=34, left_target=38)

    assert zone.current_temperature == 34
    assert zone.target_temperature == 38


# --- Zone naming (issue #21) ----------------------------------------------


def test_zones_are_named_left_and_right_by_default() -> None:
    """Default names are unchanged."""
    assert make_zone("left").name == "Left"
    assert make_zone("right").name == "Right"


def test_zone_names_can_be_overridden() -> None:
    """Fridges with a top and a bottom zone can say so."""
    entry = make_entry(**{CONF_LEFT_NAME: "Fridge", CONF_RIGHT_NAME: "Freezer"})

    assert make_zone("left", entry).name == "Fridge"
    assert make_zone("right", entry).name == "Freezer"


def test_blank_zone_name_falls_back_to_the_default() -> None:
    """An empty text field does not produce a nameless entity."""
    entry = make_entry(**{CONF_LEFT_NAME: ""})

    assert make_zone("left", entry).name == "Left"


def test_unique_ids_are_stable_across_renames() -> None:
    """Renaming a zone must not orphan its entity."""
    entry = make_entry(**{CONF_LEFT_NAME: "Top"})

    assert make_zone("left", entry).unique_id == f"{ADDRESS}_left"


# --- Presets and availability (issue #15) ---------------------------------


def test_presets_default_to_max_and_eco() -> None:
    """Without the fridge/freezer option the presets are Max and Eco."""
    assert make_zone().preset_modes == [PRESET_MAX, PRESET_ECO]


def test_presets_switch_to_fridge_and_freezer_when_configured() -> None:
    """The option only changes the preset names, on dual zone models."""
    entry = make_entry(**{CONF_DUAL_ZONE_MODES: True})
    zone = make_zone("left", entry, right_current=-8)

    assert zone.preset_modes == [PRESET_FRIDGE, PRESET_FREEZER]


def test_option_alone_does_not_change_presets_on_single_zone() -> None:
    """A single zone fridge keeps Max/Eco even with the option enabled."""
    entry = make_entry(**{CONF_DUAL_ZONE_MODES: True})

    assert make_zone("left", entry).preset_modes == [PRESET_MAX, PRESET_ECO]


def test_option_is_read_from_options_not_only_setup_data() -> None:
    """Changing the setting later takes effect without re-adding the fridge."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"address": ADDRESS, "name": "Fridge", CONF_DUAL_ZONE_MODES: False},
        options={CONF_DUAL_ZONE_MODES: True},
    )
    zone = make_zone("left", entry, right_current=-8)

    assert zone.preset_modes == [PRESET_FRIDGE, PRESET_FREEZER]


def test_right_zone_is_hidden_in_fridge_mode() -> None:
    """This is the behaviour that made the option look inverted in issue #15."""
    entry = make_entry(**{CONF_DUAL_ZONE_MODES: True})

    assert make_zone("right", entry, right_current=-8, run_mode=0).available is False
    assert make_zone("right", entry, right_current=-8, run_mode=1).available is True


def test_right_zone_stays_available_without_the_option() -> None:
    """A plain dual zone fridge shows both zones at all times."""
    assert make_zone("right", right_current=-8, run_mode=0).available is True


def test_preset_mode_maps_run_mode() -> None:
    """run_mode 1 is the second preset in both naming schemes."""
    assert make_zone(run_mode=1).preset_mode == PRESET_ECO
    assert make_zone(run_mode=0).preset_mode == PRESET_MAX

    entry = make_entry(**{CONF_DUAL_ZONE_MODES: True})
    assert make_zone("left", entry, right_current=-8, run_mode=1).preset_mode == (
        PRESET_FREEZER
    )


def test_hvac_mode_follows_power_state() -> None:
    """Powered off reports OFF rather than an unknown state."""
    assert make_zone(powered_on=True).hvac_mode == HVACMode.COOL
    assert make_zone(powered_on=False).hvac_mode == HVACMode.OFF

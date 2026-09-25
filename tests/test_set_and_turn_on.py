"""Tests for SET answers carrying a status and climate turn_on/turn_off."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.climate import ClimateEntityFeature
from homeassistant.components.climate.const import HVACMode
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.alpicool_ble.api import FridgeApi
from custom_components.alpicool_ble.climate import AlpicoolClimateZone
from custom_components.alpicool_ble.const import DOMAIN, Request

from test_api import DUAL_ZONE_PAYLOAD, SINGLE_ZONE_PAYLOAD

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


def _frame(cmd: int, payload: bytes, checksum: bool = True) -> bytearray:
    """Build a frame; real fridges append a two byte checksum."""
    frame = bytearray(b"\xfe\xfe")
    frame.append(len(payload) + 1 + (2 if checksum else 0))
    frame.append(cmd)
    frame.extend(payload)
    if checksum:
        frame.extend((sum(frame) & 0xFFFF).to_bytes(2, "big"))
    return frame


# --- SET answer carries the new status ------------------------------------


def test_set_answer_with_status_is_decoded() -> None:
    """The fridge answers SET with its full status; use it."""
    fridge = FridgeApi(MagicMock(), ADDRESS)
    fridge._notification_handler(None, _frame(Request.SET, SINGLE_ZONE_PAYLOAD))
    assert fridge.status["left_target"] == -5
    assert fridge._status_updated_event.is_set()


def test_set_echo_and_status_in_one_notification() -> None:
    """An echo of the SET command is skipped, the status after it is used."""
    fridge = FridgeApi(MagicMock(), ADDRESS)
    echo = _frame(Request.SET, SINGLE_ZONE_PAYLOAD[:14])
    fridge._notification_handler(None, echo + _frame(Request.SET, DUAL_ZONE_PAYLOAD))
    assert fridge.status["right_target"] == -10


def test_set_echo_alone_is_not_status() -> None:
    """A 14 or 25 byte echo must not be decoded as status."""
    fridge = FridgeApi(MagicMock(), ADDRESS)
    fridge._notification_handler(None, _frame(Request.SET, DUAL_ZONE_PAYLOAD[:25]))
    fridge._notification_handler(
        None, _frame(Request.SET, SINGLE_ZONE_PAYLOAD[:14], checksum=False)
    )
    assert fridge.status == {}
    assert not fridge._status_updated_event.is_set()


# --- climate.turn_on / turn_off -------------------------------------------


async def test_climate_supports_turn_on_and_off() -> None:
    """turn_on/turn_off are advertised and map to the hvac mode."""
    zone = AlpicoolClimateZone(_entry(), _api(powered_on=False), "left")
    assert zone.supported_features & ClimateEntityFeature.TURN_ON
    assert zone.supported_features & ClimateEntityFeature.TURN_OFF
    with patch.object(zone, "async_set_hvac_mode", AsyncMock()) as set_mode:
        await zone.async_turn_on()
        set_mode.assert_awaited_once_with(HVACMode.COOL)
        await zone.async_turn_off()
        set_mode.assert_awaited_with(HVACMode.OFF)

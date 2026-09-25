"""Tests for single zone fridges that send a long status (MAENTUM ICECUBE X 50)."""

from unittest.mock import AsyncMock, MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.alpicool_ble.api import FridgeApi
from custom_components.alpicool_ble.climate import async_setup_entry
from custom_components.alpicool_ble.const import DOMAIN, Request

from test_api import DUAL_ZONE_PAYLOAD

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


# --- MAENTUM IceCubeX: long single-zone status --------------------------------

# Query answer of a MAENTUM ICECUBE X 50, captured with nRF Connect on
# 2026-09-25 (three notifications of 20 + 20 + 8 bytes).
ICECUBEX_NOTIFICATIONS = [
    bytes.fromhex("FEFE2D01000101020414EC020000FDFD00000564"),
    bytes.fromhex("0E06000000000000000080000A00000000000000"),
    bytes.fromhex("0000000000000635"),
]


def _icecubex_api() -> FridgeApi:
    fridge = FridgeApi(MagicMock(), ADDRESS)
    for chunk in ICECUBEX_NOTIFICATIONS:
        fridge._notification_handler(None, bytearray(chunk))
    return fridge


def test_icecubex_status_is_decoded() -> None:
    """The fragmented 48 byte frame is reassembled and decoded."""
    status = _icecubex_api().status
    assert status["powered_on"] is True
    assert status["locked"] is False
    assert status["run_mode"] == 1
    assert status["bat_saver"] == 2
    assert status["left_target"] == 4
    assert status["left_current"] == 5
    assert (status["temp_min"], status["temp_max"]) == (-20, 20)
    assert status["bat_percent"] == 100
    assert (status["bat_vol_int"], status["bat_vol_dec"]) == (14, 6)
    assert status["right_current"] == -128


async def test_icecubex_gets_no_second_zone() -> None:
    """A long status with -128 in the second zone is a single-zone fridge."""
    fridge = _icecubex_api()
    added: list = []
    hass = MagicMock()
    entry = _entry()
    hass.data = {DOMAIN: {entry.entry_id: fridge}}

    await async_setup_entry(hass, entry, added.extend)
    assert [e._zone for e in added] == ["left"]
    assert added[0]._is_dual_zone is False


async def test_real_dual_zone_keeps_second_zone() -> None:
    """A fridge with a real second zone still gets both climate entities."""
    fridge = FridgeApi(MagicMock(), ADDRESS)
    fridge._notification_handler(None, _frame(Request.QUERY, DUAL_ZONE_PAYLOAD))
    added: list = []
    hass = MagicMock()
    entry = _entry()
    hass.data = {DOMAIN: {entry.entry_id: fridge}}

    await async_setup_entry(hass, entry, added.extend)
    assert [e._zone for e in added] == ["left", "right"]

"""Setup tests driving the real protocol code against a simulated fridge."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.alpicool_ble import api as api_module
from custom_components.alpicool_ble.const import (
    CONF_DUAL_ZONE_MODES,
    CONF_LEFT_NAME,
    DOMAIN,
    FRIDGE_RW_CHARACTERISTIC_UUID,
    Request,
)

ADDRESS = "AA:BB:CC:DD:EE:FF"


class FakeFridge:
    """A BleakClient stand-in that speaks the fridge protocol back at us."""

    def __init__(
        self,
        *,
        dual_zone: bool = False,
        unit: int = 0,
        current: int = -3,
        target: int = -5,
        mtu_size: int = 23,
    ):
        """Set up the simulated fridge state."""
        self.is_connected = True
        self.mtu_size = mtu_size
        self.dual_zone = dual_zone
        self.received: list[bytes] = []
        self._notify = None
        self._buffer = bytearray()
        self.state = bytearray(
            [
                0,
                1,
                0,
                2,
                target & 0xFF,
                20,
                0xEC,
                1,
                0,
                unit,
                0,
                0,
                0,
                0,
                current & 0xFF,
                87,
                12,
                6,
            ]
        )
        if dual_zone:
            self.state += bytearray([0xF6, 0, 0, 1, 0, 0, 0, 0, 0xF8, 1])

        char = MagicMock()
        char.uuid = FRIDGE_RW_CHARACTERISTIC_UUID
        char.properties = ["write-without-response"]
        service = MagicMock()
        service.characteristics = [char]
        self.services = [service]

    async def start_notify(self, uuid, handler) -> None:
        """Register the integration's notification handler."""
        self._notify = handler

    async def disconnect(self) -> None:
        """Drop the connection."""
        self.is_connected = False

    def _reply(self, cmd: int, payload: bytes) -> None:
        packet = bytearray(b"\xfe\xfe")
        packet.append(len(payload) + 1)
        packet.append(cmd)
        packet.extend(payload)
        self._notify(None, bytearray(packet))

    async def write_gatt_char(self, uuid, data, response=False) -> None:
        """Reassemble chunked writes and answer complete commands."""
        assert len(data) <= self.mtu_size - 3
        self._buffer.extend(data)

        while len(self._buffer) >= 3:
            total = 3 + self._buffer[2]
            if len(self._buffer) < total:
                return
            packet = bytes(self._buffer[:total])
            self._buffer = self._buffer[total:]
            self.received.append(packet)
            self._handle(packet)

    def _handle(self, packet: bytes) -> None:
        cmd = packet[3]
        if cmd == Request.BIND:
            self._reply(Request.BIND, b"\x01")
        elif cmd == Request.QUERY:
            self._reply(Request.QUERY, bytes(self.state))
        elif cmd == Request.SET:
            body = packet[4:-2]
            self.state[: len(body)] = body
            self._reply(Request.SET, b"")
        elif cmd == Request.SET_LEFT:
            self.state[4] = packet[4]
            self._reply(Request.SET_LEFT, b"")
        elif cmd == Request.SET_RIGHT:
            self.state[18] = packet[4]
            self._reply(Request.SET_RIGHT, b"")


@pytest.fixture
def fake_fridge() -> FakeFridge:
    """Return a single zone Celsius fridge."""
    return FakeFridge()


async def setup_entry(
    hass: HomeAssistant, fridge: FakeFridge, **entry_kwargs
) -> MockConfigEntry:
    """Set up the integration against a simulated fridge."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDRESS,
        data={CONF_ADDRESS: ADDRESS, CONF_NAME: "Fridge"},
        **entry_kwargs,
    )
    entry.add_to_hass(hass)

    with (
        patch.object(
            api_module.bluetooth,
            "async_ble_device_from_address",
            return_value=MagicMock(),
        ),
        patch.object(
            api_module, "establish_connection", AsyncMock(return_value=fridge)
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return entry


async def test_setup_creates_the_zone(
    hass: HomeAssistant, enable_bluetooth: None, fake_fridge: FakeFridge
) -> None:
    """A single zone fridge yields one climate entity with live values."""
    entry = await setup_entry(hass, fake_fridge)

    assert entry.state is ConfigEntryState.LOADED

    state = hass.states.get("climate.fridge_left")
    assert state is not None
    assert state.attributes["current_temperature"] == -3
    assert state.attributes["temperature"] == -5
    assert hass.states.get("climate.fridge_right") is None


async def test_dual_zone_fridge_gets_two_zones(
    hass: HomeAssistant, enable_bluetooth: None
) -> None:
    """The second zone is detected from the status payload, not from an option."""
    await setup_entry(hass, FakeFridge(dual_zone=True))

    assert hass.states.get("climate.fridge_left") is not None
    assert hass.states.get("climate.fridge_right") is not None


async def test_fahrenheit_fridge_is_not_read_as_celsius(
    hass: HomeAssistant, enable_bluetooth: None
) -> None:
    """Issue #15/#18/#21: a chilled fridge must not show up as 34 degrees C."""
    await setup_entry(hass, FakeFridge(unit=1, current=34, target=38))

    state = hass.states.get("climate.fridge_left")
    # Home Assistant is metric here, so 34 F is converted for display.
    assert state.attributes["current_temperature"] == pytest.approx(1.1, abs=0.1)
    assert state.attributes["temperature"] == pytest.approx(3.3, abs=0.1)


async def test_fahrenheit_fridge_keeps_its_numbers_in_an_imperial_setup(
    hass: HomeAssistant, enable_bluetooth: None
) -> None:
    """With Fahrenheit as the display unit the values pass through untouched."""
    hass.config.units = US_CUSTOMARY_SYSTEM
    await setup_entry(hass, FakeFridge(unit=1, current=34, target=38))

    state = hass.states.get("climate.fridge_left")
    assert state.attributes["current_temperature"] == 34
    assert state.attributes["temperature"] == 38


async def test_celsius_fridge_is_unaffected(
    hass: HomeAssistant, enable_bluetooth: None, fake_fridge: FakeFridge
) -> None:
    """The existing Celsius behaviour is unchanged."""
    await setup_entry(hass, fake_fridge)

    state = hass.states.get("climate.fridge_left")
    assert state.attributes["current_temperature"] == -3
    assert state.attributes["min_temp"] == -20
    assert state.attributes["max_temp"] == 20


async def test_zone_name_option_is_applied(
    hass: HomeAssistant, enable_bluetooth: None, fake_fridge: FakeFridge
) -> None:
    """Issue #21: zones can be renamed without editing the code."""
    await setup_entry(hass, fake_fridge, options={CONF_LEFT_NAME: "Cellar"})

    assert hass.states.get("climate.fridge_cellar") is not None


async def test_turning_off_uses_a_chunked_set_packet(
    hass: HomeAssistant, enable_bluetooth: None
) -> None:
    """Issue #20: the long SET packet is accepted and actually takes effect."""
    fridge = FakeFridge(dual_zone=True)
    await setup_entry(hass, fridge)

    await hass.services.async_call(
        "climate",
        "set_hvac_mode",
        {"entity_id": "climate.fridge_left", "hvac_mode": "off"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert fridge.state[1] == 0
    assert hass.states.get("climate.fridge_left").state == "off"


async def test_setting_a_temperature_reaches_the_fridge(
    hass: HomeAssistant, enable_bluetooth: None, fake_fridge: FakeFridge
) -> None:
    """A new target is written and read back."""
    await setup_entry(hass, fake_fridge)

    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": "climate.fridge_left", "temperature": -12},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert hass.states.get("climate.fridge_left").attributes["temperature"] == -12


async def test_setup_registers_an_advertisement_callback(
    hass: HomeAssistant, enable_bluetooth: None, fake_fridge: FakeFridge
) -> None:
    """Issue #16: the fridge coming back on air must not need a manual reload."""
    with patch.object(api_module.bluetooth, "async_register_callback") as register:
        await setup_entry(hass, fake_fridge)

    assert register.called
    assert register.call_args.args[2]["address"] == ADDRESS


async def test_setup_retries_when_the_fridge_is_not_around(
    hass: HomeAssistant, enable_bluetooth: None
) -> None:
    """Issue #19: an unreachable fridge is a retry, not a hard failure."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDRESS,
        data={CONF_ADDRESS: ADDRESS, CONF_NAME: "Fridge"},
    )
    entry.add_to_hass(hass)

    with patch.object(
        api_module.bluetooth, "async_ble_device_from_address", return_value=None
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_changing_options_reloads_the_entry(
    hass: HomeAssistant, enable_bluetooth: None, fake_fridge: FakeFridge
) -> None:
    """Issue #15: the fridge/freezer setting is changeable after setup."""
    entry = await setup_entry(hass, fake_fridge)

    with (
        patch.object(
            api_module.bluetooth,
            "async_ble_device_from_address",
            return_value=MagicMock(),
        ),
        patch.object(
            api_module,
            "establish_connection",
            AsyncMock(return_value=FakeFridge(dual_zone=True)),
        ),
    ):
        hass.config_entries.async_update_entry(
            entry, options={CONF_DUAL_ZONE_MODES: True}
        )
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("climate.fridge_right") is not None


async def test_unload_disconnects(
    hass: HomeAssistant, enable_bluetooth: None, fake_fridge: FakeFridge
) -> None:
    """Unloading closes the connection and removes the entities."""
    entry = await setup_entry(hass, fake_fridge)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert fake_fridge.is_connected is False
    assert hass.states.get("climate.fridge_left").state == "unavailable"

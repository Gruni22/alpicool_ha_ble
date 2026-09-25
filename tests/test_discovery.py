"""Tests that Bluetooth discovery only offers devices with the fridge service."""

from unittest.mock import AsyncMock, MagicMock, patch


from custom_components.alpicool_ble.const import DOMAIN


ADDRESS = "AA:BB:CC:DD:EE:FF"


# --- Discovery only offers devices with the fridge service -----------------


def _discovery(uuids: list[str]):
    from bleak.backends.device import BLEDevice
    from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

    return BluetoothServiceInfoBleak(
        name="Some device",
        address=ADDRESS,
        rssi=-60,
        manufacturer_data={},
        service_data={},
        service_uuids=uuids,
        source="local",
        device=BLEDevice(ADDRESS, "Some device", {}),
        advertisement=None,
        connectable=True,
        time=0,
        tx_power=None,
    )


FFF0 = "0000fff0-0000-1000-8000-00805f9b34fb"


def _gatt_client(has_chars: bool) -> MagicMock:
    client = MagicMock()
    client.services.get_characteristic.side_effect = (
        lambda uuid: MagicMock() if has_chars else None
    )
    client.disconnect = AsyncMock()
    return client


async def _discover(hass, info, connect):
    with patch(
        "custom_components.alpicool_ble.config_flow.establish_connection", connect
    ):
        return await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "bluetooth"}, data=info
        )


async def test_discovery_with_advertised_service_needs_no_connect(
    hass, enable_bluetooth
) -> None:
    """0x1234 in the advertisement is enough."""
    connect = AsyncMock()
    result = await _discover(
        hass, _discovery(["00001234-0000-1000-8000-00805f9b34fb"]), connect
    )
    assert result["type"] == "form"
    connect.assert_not_awaited()


async def test_discovery_fff0_device_with_fridge_service_is_offered(
    hass, enable_bluetooth
) -> None:
    """A 0xFFF0 device that has the fridge characteristics is offered."""
    client = _gatt_client(True)
    result = await _discover(hass, _discovery([FFF0]), AsyncMock(return_value=client))
    assert result["type"] == "form"
    client.disconnect.assert_awaited_once()


async def test_discovery_fff0_device_without_fridge_service_is_ignored(
    hass, enable_bluetooth
) -> None:
    """Other 0xFFF0 gadgets are not offered as fridges."""
    client = _gatt_client(False)
    result = await _discover(hass, _discovery([FFF0]), AsyncMock(return_value=client))
    assert result["type"] == "abort"
    assert result["reason"] == "not_supported"
    client.disconnect.assert_awaited_once()


async def test_discovery_unreachable_device_is_still_offered(
    hass, enable_bluetooth
) -> None:
    """If the check cannot connect (e.g. phone app connected), offer it anyway."""
    from bleak.exc import BleakError

    result = await _discover(
        hass, _discovery([FFF0]), AsyncMock(side_effect=BleakError("busy"))
    )
    assert result["type"] == "form"

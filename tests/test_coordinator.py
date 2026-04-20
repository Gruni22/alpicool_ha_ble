"""Tests for the Alpicool BLE DataUpdateCoordinator.

Requires homeassistant — Linux / WSL2 / CI only.
On Windows run: pytest tests/test_api.py
"""

import asyncio
import sys
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="homeassistant requires Linux (fcntl). Use WSL2 or GitHub Actions CI.",
)

from bleak import BleakError  # noqa: E402

from homeassistant.core import HomeAssistant  # noqa: E402

from custom_components.alpicool_ble.api import AlpicoolApiError  # noqa: E402
from custom_components.alpicool_ble.coordinator import AlpicoolDeviceUpdateCoordinator  # noqa: E402
from custom_components.alpicool_ble.const import Request  # noqa: E402

from .conftest import make_response_packet  # noqa: E402


ADDRESS = "AA:BB:CC:DD:EE:FF"
DEVICE_NAME = "Test Fridge"


def make_coordinator(hass: HomeAssistant, poll_interval: int = 30):
    return AlpicoolDeviceUpdateCoordinator(hass, ADDRESS, DEVICE_NAME, poll_interval)


# ---------------------------------------------------------------------------
# Coordinator init
# ---------------------------------------------------------------------------

class TestCoordinatorInit:
    def test_address_stored(self, hass: HomeAssistant):
        coord = make_coordinator(hass)
        assert coord.address == ADDRESS

    def test_device_name_stored(self, hass: HomeAssistant):
        coord = make_coordinator(hass)
        assert coord.device_name == DEVICE_NAME

    def test_poll_interval(self, hass: HomeAssistant):
        coord = make_coordinator(hass, poll_interval=60)
        assert coord.update_interval == timedelta(seconds=60)

    def test_api_created(self, hass: HomeAssistant):
        coord = make_coordinator(hass)
        assert coord.api is not None


# ---------------------------------------------------------------------------
# _async_update_data
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_ble_device():
    return MagicMock()


@pytest.fixture
def mock_bleak_client(single_zone_status):
    """Mock BleakClient that returns a valid status on get_status."""
    client = AsyncMock()
    client.is_connected = True
    return client


async def test_update_data_success(hass: HomeAssistant, single_zone_status):
    coord = make_coordinator(hass)
    mock_device = MagicMock()

    with (
        patch(
            "custom_components.alpicool_ble.coordinator.async_ble_device_from_address",
            return_value=mock_device,
        ),
        patch(
            "custom_components.alpicool_ble.coordinator.BleakClient"
        ) as MockClient,
        patch.object(coord.api, "async_start_notifications", new=AsyncMock()),
        patch.object(coord.api, "get_status", new=AsyncMock(return_value=single_zone_status)),
    ):
        instance = AsyncMock()
        instance.is_connected = True
        instance.connect = AsyncMock()
        instance.disconnect = AsyncMock()
        MockClient.return_value = instance

        data = await coord._async_update_data()

    assert data == single_zone_status


async def test_update_data_device_not_found(hass: HomeAssistant):
    from homeassistant.helpers.update_coordinator import UpdateFailed

    coord = make_coordinator(hass)

    with patch(
        "custom_components.alpicool_ble.coordinator.async_ble_device_from_address",
        return_value=None,
    ):
        with pytest.raises(UpdateFailed, match="not found"):
            await coord._async_update_data()


async def test_update_data_ble_error(hass: HomeAssistant):
    from homeassistant.helpers.update_coordinator import UpdateFailed

    coord = make_coordinator(hass)
    mock_device = MagicMock()

    with (
        patch(
            "custom_components.alpicool_ble.coordinator.async_ble_device_from_address",
            return_value=mock_device,
        ),
        patch(
            "custom_components.alpicool_ble.coordinator.BleakClient"
        ) as MockClient,
    ):
        instance = AsyncMock()
        instance.is_connected = False
        instance.connect = AsyncMock(side_effect=BleakError("Connection refused"))
        MockClient.return_value = instance

        with pytest.raises(UpdateFailed, match="Connection Error"):
            await coord._async_update_data()


async def test_update_data_api_error(hass: HomeAssistant):
    from homeassistant.helpers.update_coordinator import UpdateFailed

    coord = make_coordinator(hass)
    mock_device = MagicMock()

    with (
        patch(
            "custom_components.alpicool_ble.coordinator.async_ble_device_from_address",
            return_value=mock_device,
        ),
        patch(
            "custom_components.alpicool_ble.coordinator.BleakClient"
        ) as MockClient,
        patch.object(coord.api, "async_start_notifications", new=AsyncMock()),
        patch.object(
            coord.api, "get_status", new=AsyncMock(side_effect=AlpicoolApiError("Timeout"))
        ),
    ):
        instance = AsyncMock()
        instance.is_connected = True
        instance.connect = AsyncMock()
        instance.disconnect = AsyncMock()
        MockClient.return_value = instance

        with pytest.raises(UpdateFailed, match="API Error"):
            await coord._async_update_data()


async def test_update_data_sets_bound_flag(hass: HomeAssistant, single_zone_status):
    coord = make_coordinator(hass)
    assert coord._is_bound_this_session is False

    mock_device = MagicMock()
    with (
        patch(
            "custom_components.alpicool_ble.coordinator.async_ble_device_from_address",
            return_value=mock_device,
        ),
        patch("custom_components.alpicool_ble.coordinator.BleakClient") as MockClient,
        patch.object(coord.api, "async_start_notifications", new=AsyncMock()),
        patch.object(coord.api, "get_status", new=AsyncMock(return_value=single_zone_status)),
    ):
        instance = AsyncMock()
        instance.is_connected = True
        instance.connect = AsyncMock()
        instance.disconnect = AsyncMock()
        MockClient.return_value = instance
        await coord._async_update_data()

    assert coord._is_bound_this_session is True


# ---------------------------------------------------------------------------
# async_set_values
# ---------------------------------------------------------------------------

async def test_async_set_values_sends_command(hass: HomeAssistant, single_zone_status):
    coord = make_coordinator(hass)
    coord.data = single_zone_status
    mock_device = MagicMock()

    with (
        patch(
            "custom_components.alpicool_ble.coordinator.async_ble_device_from_address",
            return_value=mock_device,
        ),
        patch("custom_components.alpicool_ble.coordinator.BleakClient") as MockClient,
        patch.object(coord.api, "async_start_notifications", new=AsyncMock()),
        patch.object(coord.api, "async_set_values", new=AsyncMock()) as mock_set,
        patch.object(coord.api, "get_status", new=AsyncMock(return_value=single_zone_status)),
        patch("custom_components.alpicool_ble.coordinator.asyncio.sleep", new=AsyncMock()),
    ):
        instance = AsyncMock()
        instance.is_connected = True
        instance.connect = AsyncMock()
        instance.disconnect = AsyncMock()
        MockClient.return_value = instance

        await coord.async_set_values({"locked": True})

    mock_set.assert_called_once()
    call_args = mock_set.call_args[0]
    # First arg is client, second is current_status, third is new_values
    assert call_args[1] == single_zone_status
    assert call_args[2] == {"locked": True}


async def test_async_set_values_no_data_skips(hass: HomeAssistant):
    coord = make_coordinator(hass)
    coord.data = None

    with patch.object(coord, "_execute_command", new=AsyncMock()) as mock_exec:
        await coord.async_set_values({"locked": True})

    mock_exec.assert_not_called()


# ---------------------------------------------------------------------------
# async_set_temperature
# ---------------------------------------------------------------------------

async def test_async_set_temperature_sends_command(hass: HomeAssistant, single_zone_status):
    coord = make_coordinator(hass)
    coord.data = single_zone_status
    mock_device = MagicMock()

    with (
        patch(
            "custom_components.alpicool_ble.coordinator.async_ble_device_from_address",
            return_value=mock_device,
        ),
        patch("custom_components.alpicool_ble.coordinator.BleakClient") as MockClient,
        patch.object(coord.api, "async_start_notifications", new=AsyncMock()),
        patch.object(coord.api, "async_set_temperature", new=AsyncMock()) as mock_temp,
        patch.object(coord.api, "get_status", new=AsyncMock(return_value=single_zone_status)),
        patch("custom_components.alpicool_ble.coordinator.asyncio.sleep", new=AsyncMock()),
    ):
        instance = AsyncMock()
        instance.is_connected = True
        instance.connect = AsyncMock()
        instance.disconnect = AsyncMock()
        MockClient.return_value = instance

        await coord.async_set_temperature("left", -5)

    mock_temp.assert_called_once()
    call_args = mock_temp.call_args[0]
    assert call_args[1] == "left"
    assert call_args[2] == -5


# ---------------------------------------------------------------------------
# _execute_command — error recovery
# ---------------------------------------------------------------------------

async def test_execute_command_error_triggers_refresh(hass: HomeAssistant, single_zone_status):
    coord = make_coordinator(hass)
    coord.data = single_zone_status
    mock_device = MagicMock()

    with (
        patch(
            "custom_components.alpicool_ble.coordinator.async_ble_device_from_address",
            return_value=mock_device,
        ),
        patch("custom_components.alpicool_ble.coordinator.BleakClient") as MockClient,
        patch.object(coord.api, "async_start_notifications", new=AsyncMock()),
        patch.object(
            coord.api, "async_set_values", new=AsyncMock(side_effect=AlpicoolApiError("fail"))
        ),
        patch.object(coord, "async_request_refresh", new=AsyncMock()) as mock_refresh,
    ):
        instance = AsyncMock()
        instance.is_connected = True
        instance.connect = AsyncMock()
        instance.disconnect = AsyncMock()
        MockClient.return_value = instance

        await coord.async_set_values({"locked": True})

    mock_refresh.assert_called_once()


async def test_execute_command_device_not_found_skips(hass: HomeAssistant, single_zone_status):
    coord = make_coordinator(hass)
    coord.data = single_zone_status

    with patch(
        "custom_components.alpicool_ble.coordinator.async_ble_device_from_address",
        return_value=None,
    ):
        # Should not raise, just log and return
        await coord.async_set_values({"locked": True})

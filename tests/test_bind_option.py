"""Tests for the Pair on start-up (Bind) option."""

from unittest.mock import AsyncMock, MagicMock, patch


from custom_components.alpicool_ble.api import FridgeApi
from custom_components.alpicool_ble.const import DOMAIN, Request


ADDRESS = "AA:BB:CC:DD:EE:FF"


# --- Bind on start is an option -------------------------------------------


async def _connect_with(bind: bool) -> AsyncMock:
    from custom_components.alpicool_ble import api as api_module
    from test_api import _connected_client

    fridge = FridgeApi(MagicMock(), ADDRESS)
    client = _connected_client()
    send = AsyncMock()
    with (
        patch.object(
            api_module.bluetooth,
            "async_ble_device_from_address",
            return_value=MagicMock(),
        ),
        patch.object(
            api_module, "establish_connection", AsyncMock(return_value=client)
        ),
        patch.object(fridge, "_send_raw", send),
        patch.object(
            api_module.asyncio,
            "wait_for",
            AsyncMock(side_effect=lambda coro, timeout: coro.close()),
        ),
    ):
        assert await fridge.connect(bind=bind) is True
    return send


async def test_bind_is_sent_by_default() -> None:
    """With the option on (default) the fridge is asked to pair."""
    send = await _connect_with(True)
    send.assert_awaited_once()
    assert send.await_args.args[0][3] == Request.BIND


async def test_bind_can_be_switched_off() -> None:
    """With the option off no Bind is sent and setup does not wait."""
    send = await _connect_with(False)
    send.assert_not_awaited()


async def test_user_flow_stores_bind_option(hass, enable_bluetooth) -> None:
    """The checkbox on the setup form ends up in the entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"address": ADDRESS, "name": "Box", "bind_on_start": False},
    )
    assert result["type"] == "create_entry"
    assert result["data"]["bind_on_start"] is False

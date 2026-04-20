"""Shared test fixtures for Alpicool BLE tests.

On Windows: HA modules are stubbed so test_api.py can run without homeassistant.
On Linux / WSL2 / CI: full HA integration tests run via pytest-homeassistant-custom-component.

Stubs MUST be registered in sys.modules before any custom_components import happens,
so this block is unconditionally at the top of the file.
"""

import sys
from unittest.mock import MagicMock
import pytest


# ---------------------------------------------------------------------------
# Minimal HA stubs — registered before any custom_components import
# ---------------------------------------------------------------------------

if sys.platform == "win32":

    class _DataUpdateCoordinator:
        """Minimal base class stub for DataUpdateCoordinator."""

        def __class_getitem__(cls, item):
            return cls

        def __init__(self, hass, logger, *, name=None, update_interval=None, **kw):
            self.hass = hass
            self.data = None
            self.last_update_success = True
            self.update_interval = update_interval

        def async_set_updated_data(self, data):
            self.data = data
            self.last_update_success = True

        async def async_config_entry_first_refresh(self):
            self.data = await self._async_update_data()

        async def async_request_refresh(self):
            pass

    class _UpdateFailed(Exception):
        pass

    _coordinator_mod = MagicMock()
    _coordinator_mod.DataUpdateCoordinator = _DataUpdateCoordinator
    _coordinator_mod.UpdateFailed = _UpdateFailed

    for _name, _mod in {
        "homeassistant": MagicMock(),
        "homeassistant.config_entries": MagicMock(),
        "homeassistant.const": MagicMock(),
        "homeassistant.core": MagicMock(),
        "homeassistant.helpers": MagicMock(),
        "homeassistant.helpers.update_coordinator": _coordinator_mod,
        "homeassistant.helpers.entity": MagicMock(),
        "homeassistant.helpers.entity_platform": MagicMock(),
        "homeassistant.components": MagicMock(),
        "homeassistant.components.bluetooth": MagicMock(),
        "homeassistant.components.climate": MagicMock(),
        "homeassistant.components.sensor": MagicMock(),
        "homeassistant.components.switch": MagicMock(),
        "homeassistant.components.number": MagicMock(),
        "homeassistant.components.select": MagicMock(),
    }.items():
        sys.modules.setdefault(_name, _mod)

else:
    pytest_plugins = ["pytest_homeassistant_custom_component"]


# ---------------------------------------------------------------------------
# Platform guard helper
# ---------------------------------------------------------------------------

skip_on_windows = pytest.mark.skipif(
    sys.platform == "win32",
    reason="homeassistant requires Linux (fcntl). Use WSL2 or GitHub Actions CI.",
)


# ---------------------------------------------------------------------------
# Platform-independent fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def single_zone_status() -> dict:
    """Typical single-zone device status dict."""
    return {
        "locked": False,
        "powered_on": True,
        "run_mode": 0,
        "bat_saver": 0,
        "left_target": 5,
        "temp_max": 20,
        "temp_min": -20,
        "left_ret_diff": 2,
        "start_delay": 0,
        "unit": 0,
        "left_tc_hot": 0,
        "left_tc_mid": 0,
        "left_tc_cold": 0,
        "left_tc_halt": 0,
        "left_current": 7,
        "bat_percent": 85,
        "bat_vol_int": 12,
        "bat_vol_dec": 6,
    }


@pytest.fixture
def dual_zone_status(single_zone_status) -> dict:
    """Typical dual-zone device status dict."""
    return {
        **single_zone_status,
        "right_target": 10,
        "right_ret_diff": 3,
        "right_tc_hot": 0,
        "right_tc_mid": 0,
        "right_tc_cold": 0,
        "right_tc_halt": 0,
        "right_current": 8,
    }


# ---------------------------------------------------------------------------
# HA-only fixtures (Linux / WSL2 / CI)
# ---------------------------------------------------------------------------

if sys.platform != "win32":
    from custom_components.alpicool_ble.const import (  # noqa: E402
        CONF_DUAL_MODE_FRIDGE,
        CONF_POLL_INTERVAL,
        DOMAIN,
    )

    @pytest.fixture
    def mock_config_entry():
        from pytest_homeassistant_custom_component.common import MockConfigEntry

        return MockConfigEntry(
            domain=DOMAIN,
            data={
                "address": "AA:BB:CC:DD:EE:FF",
                "name": "Test Fridge",
                CONF_DUAL_MODE_FRIDGE: False,
                CONF_POLL_INTERVAL: 30,
            },
            options={},
        )


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def make_response_packet(cmd: int, data: bytes) -> bytes:
    """Build a minimal parseable BLE response packet.

    The notification handler does not validate the checksum, so this omits it.
    """
    content = bytes([cmd]) + data
    return b"\xfe\xfe" + bytes([len(content)]) + content

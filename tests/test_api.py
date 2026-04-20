"""Tests for the Alpicool BLE API layer (protocol codec)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.alpicool_ble.api import (
    AlpicoolApi,
    AlpicoolApiError,
    AlpicoolConnectionError,
    _to_signed_byte,
)
from custom_components.alpicool_ble.const import Request

from .conftest import make_response_packet


# ---------------------------------------------------------------------------
# _to_signed_byte
# ---------------------------------------------------------------------------

class TestToSignedByte:
    def test_zero(self):
        assert _to_signed_byte(0) == 0

    def test_positive_unchanged(self):
        assert _to_signed_byte(127) == 127

    def test_boundary_negative(self):
        assert _to_signed_byte(128) == -128

    def test_minus_one(self):
        assert _to_signed_byte(255) == -1

    def test_minus_twenty(self):
        assert _to_signed_byte(236) == -20

    def test_minus_twelve(self):
        assert _to_signed_byte(244) == -12


# ---------------------------------------------------------------------------
# AlpicoolApi._build_packet
# ---------------------------------------------------------------------------

class TestBuildPacket:
    def setup_method(self):
        self.api = AlpicoolApi()

    def test_bind_is_hardcoded(self):
        assert self.api._build_packet(Request.BIND) == b"\xfe\xfe\x03\x00\x01\xff"

    def test_query_is_hardcoded(self):
        assert self.api._build_packet(Request.QUERY) == b"\xfe\xfe\x03\x01\x02\x00"

    def test_set_left_structure(self):
        packet = self.api._build_packet(Request.SET_LEFT, bytes([5]))
        assert packet[:2] == b"\xfe\xfe"
        assert packet[3] == Request.SET_LEFT
        assert packet[4] == 5

    def test_set_right_negative_temp(self):
        packet = self.api._build_packet(Request.SET_RIGHT, bytes([0xEC]))
        assert packet[3] == Request.SET_RIGHT
        assert packet[4] == 0xEC

    def test_packet_ends_with_2_byte_checksum(self):
        packet = self.api._build_packet(Request.SET_LEFT, bytes([5]))
        # header(2) + length(1) + cmd(1) + data(1) + checksum(2) = 7 bytes
        assert len(packet) == 7

    def test_checksum_matches(self):
        packet = self.api._build_packet(Request.SET_LEFT, bytes([5]))
        body = packet[:-2]
        expected_checksum = sum(body) & 0xFFFF
        actual_checksum = int.from_bytes(packet[-2:], "big")
        assert actual_checksum == expected_checksum


# ---------------------------------------------------------------------------
# AlpicoolApi._decode_status
# ---------------------------------------------------------------------------

def make_single_zone_payload() -> bytes:
    return bytes([
        0,    # locked
        1,    # powered_on
        0,    # run_mode (MAX)
        1,    # bat_saver (MEDIUM)
        5,    # left_target (5°C)
        20,   # temp_max
        236,  # temp_min (-20°C)
        2,    # left_ret_diff
        0,    # start_delay
        0,    # unit (Celsius)
        0, 0, 0, 0,  # left_tc_*
        7,    # left_current (7°C)
        85,   # bat_percent
        12,   # bat_vol_int
        6,    # bat_vol_dec
    ])


class TestDecodeStatus:
    def setup_method(self):
        self.api = AlpicoolApi()

    def test_single_zone_fields(self):
        status = self.api._decode_status(make_single_zone_payload())
        assert status["locked"] is False
        assert status["powered_on"] is True
        assert status["run_mode"] == 0
        assert status["bat_saver"] == 1
        assert status["left_target"] == 5
        assert status["temp_max"] == 20
        assert status["temp_min"] == -20
        assert status["left_ret_diff"] == 2
        assert status["left_current"] == 7
        assert status["bat_percent"] == 85
        assert status["bat_vol_int"] == 12
        assert status["bat_vol_dec"] == 6

    def test_no_right_zone_in_single_zone(self):
        status = self.api._decode_status(make_single_zone_payload())
        assert "right_current" not in status

    def test_dual_zone_fields(self):
        right = bytes([
            10,  # right_target (10°C) [18]
            0, 0,            # [19-20] reserved
            3,               # right_ret_diff [21]
            0, 0, 0, 0,      # right_tc_* [22-25]
            8,               # right_current (8°C) [26]
            0,               # [27] reserved
        ])
        status = self.api._decode_status(make_single_zone_payload() + right)
        assert status["right_target"] == 10
        assert status["right_ret_diff"] == 3
        assert status["right_current"] == 8

    def test_negative_temperatures(self):
        payload = bytearray(make_single_zone_payload())
        payload[4] = 0xEC   # left_target = -20°C
        payload[14] = 0xF4  # left_current = -12°C
        status = self.api._decode_status(bytes(payload))
        assert status["left_target"] == -20
        assert status["left_current"] == -12

    def test_too_short_raises(self):
        with pytest.raises(AlpicoolApiError):
            self.api._decode_status(b"\x00" * 5)

    def test_empty_raises(self):
        with pytest.raises(AlpicoolApiError):
            self.api._decode_status(b"")

    def test_locked_state(self):
        payload = bytearray(make_single_zone_payload())
        payload[0] = 1
        status = self.api._decode_status(bytes(payload))
        assert status["locked"] is True

    def test_powered_off(self):
        payload = bytearray(make_single_zone_payload())
        payload[1] = 0
        status = self.api._decode_status(bytes(payload))
        assert status["powered_on"] is False


# ---------------------------------------------------------------------------
# AlpicoolApi._build_set_other_payload
# ---------------------------------------------------------------------------

class TestBuildSetOtherPayload:
    def setup_method(self):
        self.api = AlpicoolApi()
        self.base = {
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
        }

    def test_single_zone_length(self):
        assert len(self.api._build_set_other_payload(self.base, {})) == 14

    def test_dual_zone_length(self):
        dual = {**self.base, "right_current": 8, "right_target": 10}
        assert len(self.api._build_set_other_payload(dual, {})) == 25

    def test_new_values_override_status(self):
        payload = self.api._build_set_other_payload(self.base, {"left_target": -10})
        assert payload[4] == (-10 & 0xFF)  # 246

    def test_lock_on(self):
        payload = self.api._build_set_other_payload(self.base, {"locked": True})
        assert payload[0] == 1

    def test_power_off(self):
        payload = self.api._build_set_other_payload(self.base, {"powered_on": False})
        assert payload[1] == 0

    def test_run_mode_eco(self):
        payload = self.api._build_set_other_payload(self.base, {"run_mode": 1})
        assert payload[2] == 1

    def test_negative_temp_unsigned_encoding(self):
        payload = self.api._build_set_other_payload(self.base, {"left_target": -20})
        assert payload[4] == 236  # 0xEC

    def test_does_not_mutate_input_status(self):
        original = dict(self.base)
        self.api._build_set_other_payload(self.base, {"locked": True})
        assert self.base == original


# ---------------------------------------------------------------------------
# AlpicoolApi._notification_handler
# ---------------------------------------------------------------------------

class TestNotificationHandler:
    def setup_method(self):
        self.api = AlpicoolApi()

    def test_complete_query_packet_sets_event(self):
        packet = make_response_packet(Request.QUERY, make_single_zone_payload())
        self.api._notification_handler(None, bytearray(packet))
        assert self.api._status_updated_event.is_set()
        assert self.api._last_payload is not None

    def test_payload_content_correct(self):
        data = make_single_zone_payload()
        packet = make_response_packet(Request.QUERY, data)
        self.api._notification_handler(None, bytearray(packet))
        # packet[4:] = data (the notification handler stores packet[4:])
        assert self.api._last_payload[:len(data)] == data

    def test_bind_response_sets_bind_event(self):
        packet = make_response_packet(Request.BIND, b"")
        self.api._notification_handler(None, bytearray(packet))
        assert self.api._bind_event.is_set()
        assert not self.api._status_updated_event.is_set()

    def test_fragmented_first_half_waits(self):
        packet = make_response_packet(Request.QUERY, make_single_zone_payload())
        self.api._notification_handler(None, bytearray(packet[:5]))
        assert not self.api._status_updated_event.is_set()
        assert len(self.api._notification_buffer) == 5

    def test_fragmented_reassembly(self):
        packet = make_response_packet(Request.QUERY, make_single_zone_payload())
        self.api._notification_handler(None, bytearray(packet[:5]))
        self.api._notification_handler(None, bytearray(packet[5:]))
        assert self.api._status_updated_event.is_set()

    def test_partial_header_buffered(self):
        self.api._notification_handler(None, bytearray(b"\xfe"))
        assert not self.api._status_updated_event.is_set()
        assert len(self.api._notification_buffer) == 1

    def test_two_concatenated_packets_both_parsed(self):
        p1 = make_response_packet(Request.BIND, b"")
        data = make_single_zone_payload()
        p2 = make_response_packet(Request.QUERY, data)
        self.api._notification_handler(None, bytearray(p1 + p2))
        assert self.api._bind_event.is_set()
        assert self.api._status_updated_event.is_set()

    def test_buffer_cleared_after_parsing(self):
        packet = make_response_packet(Request.QUERY, make_single_zone_payload())
        self.api._notification_handler(None, bytearray(packet))
        assert len(self.api._notification_buffer) == 0

    def test_unknown_cmd_does_not_set_events(self):
        packet = make_response_packet(0x42, bytes(10))
        self.api._notification_handler(None, bytearray(packet))
        assert not self.api._status_updated_event.is_set()
        assert not self.api._bind_event.is_set()


# ---------------------------------------------------------------------------
# AlpicoolApi.async_start_notifications
# ---------------------------------------------------------------------------

class TestAsyncStartNotifications:
    @pytest.mark.asyncio
    async def test_clears_buffer_and_events(self):
        api = AlpicoolApi()
        api._notification_buffer.extend(b"\x01\x02\x03")
        api._status_updated_event.set()
        api._bind_event.set()

        mock_client = AsyncMock()
        await api.async_start_notifications(mock_client)

        assert len(api._notification_buffer) == 0
        assert not api._status_updated_event.is_set()
        assert not api._bind_event.is_set()
        mock_client.start_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_registers_notification_handler(self):
        api = AlpicoolApi()
        mock_client = AsyncMock()
        await api.async_start_notifications(mock_client)

        call_args = mock_client.start_notify.call_args
        assert call_args is not None
        assert call_args[0][1] == api._notification_handler


# ---------------------------------------------------------------------------
# AlpicoolApi.get_status  (integration-style with mock BleakClient)
# ---------------------------------------------------------------------------

class TestGetStatus:
    @pytest.mark.asyncio
    async def test_returns_decoded_status(self):
        api = AlpicoolApi()
        mock_client = AsyncMock()

        response = make_response_packet(Request.QUERY, make_single_zone_payload())

        async def inject_notification(char, data, response=False):
            api._notification_handler(None, bytearray(response))

        mock_client.write_gatt_char.side_effect = lambda char, data, response=False: (
            api._notification_handler(None, bytearray(
                make_response_packet(Request.QUERY, make_single_zone_payload())
            )) or asyncio.coroutines.coroutine(lambda: None)()
        )

        # Simpler approach: use a real coroutine side_effect
        async def write_side_effect(char, data, response=False):
            api._notification_handler(
                None,
                bytearray(make_response_packet(Request.QUERY, make_single_zone_payload())),
            )

        mock_client.write_gatt_char = AsyncMock(side_effect=write_side_effect)

        await api.async_start_notifications(mock_client)
        status = await api.get_status(mock_client)

        assert status["powered_on"] is True
        assert status["left_target"] == 5
        assert status["left_current"] == 7
        assert status["bat_percent"] == 85

    @pytest.mark.asyncio
    async def test_timeout_raises_api_error(self):
        api = AlpicoolApi()
        mock_client = AsyncMock()
        # Simulate the internal asyncio.wait_for timing out directly
        with patch(
            "custom_components.alpicool_ble.api.asyncio.wait_for",
            side_effect=asyncio.TimeoutError,
        ):
            with pytest.raises(AlpicoolApiError, match="Timeout"):
                await api.get_status(mock_client)


# ---------------------------------------------------------------------------
# AlpicoolApi.async_set_temperature
# ---------------------------------------------------------------------------

class TestAsyncSetTemperature:
    @pytest.mark.asyncio
    async def test_left_zone_uses_set_left(self):
        api = AlpicoolApi()
        mock_client = AsyncMock()
        await api.async_set_temperature(mock_client, "left", 5)
        packet = mock_client.write_gatt_char.call_args[0][1]
        assert packet[3] == Request.SET_LEFT
        assert packet[4] == 5

    @pytest.mark.asyncio
    async def test_right_zone_uses_set_right(self):
        api = AlpicoolApi()
        mock_client = AsyncMock()
        await api.async_set_temperature(mock_client, "right", -10)
        packet = mock_client.write_gatt_char.call_args[0][1]
        assert packet[3] == Request.SET_RIGHT
        assert packet[4] == (-10 & 0xFF)

    @pytest.mark.asyncio
    async def test_negative_temp_unsigned_encoding(self):
        api = AlpicoolApi()
        mock_client = AsyncMock()
        await api.async_set_temperature(mock_client, "left", -20)
        packet = mock_client.write_gatt_char.call_args[0][1]
        assert packet[4] == 236  # -20 & 0xFF

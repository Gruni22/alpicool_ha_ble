"""Tests for the frame codec.

Vectors marked BM are copied from the captured traffic in the README of
klightspeed/BrassMonkeyFridgeMonitor ("App Command flow"). Vectors marked NE
come from neftaly/esphome-alpicool docs/protocol.md ("Test Vectors").
Vectors marked SYN are synthetic and only test our own code paths.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import pytest

from alpicool_protocol import (
    ChecksumState,
    Command,
    FrameReader,
    build_bind,
    build_frame,
    build_query,
    build_set,
    build_set_target,
    checksum,
    is_status_frame,
    parse_status,
)

H = bytes.fromhex

# BM: status answer to a Query
BM_STATUS_1 = H(
    "fe fe 15 01 00 01 00 00 f1 14 ec 02 00 00 00 00 00 00 f3 64 0c 03 05 6c"
)
# BM: status answer before the Set example (battery unknown, 0x7f)
BM_STATUS_2 = H(
    "fe fe 15 01 00 01 00 00 ec 14 ec 02 00 00 00 00 00 00 f7 7f 0b 01 05 83"
)
# BM: Set command sent by the app (battery saver changed to High)
BM_SET = H("fe fe 11 02 00 01 00 02 ec 14 ec 02 00 00 00 00 00 00 04 00")
# BM: status answer to that Set command (command byte 0x02)
BM_SET_ANSWER = H(
    "fe fe 15 02 00 01 00 02 ec 14 ec 02 00 00 00 00 00 00 f7 7f 0b 01 05 86"
)


def _dual_payload() -> bytes:
    """SYN: 28 byte status of a dual-zone fridge."""
    single = bytearray(parse_status(BM_STATUS_1[4:-2]).raw)
    single += bytes(
        [0x04, 0, 0, 0x01, 0, 0, 0, 0, 0x06, 0x01]
    )  # zone 2: target 4, current 6
    return bytes(single)


# --- building ---------------------------------------------------------------


def test_query_frame() -> None:
    """BM + NE: the Query command."""
    assert build_query() == H("fefe03010200")


def test_bind_frame() -> None:
    """BM: the Bind command."""
    assert build_bind() == H("fefe030001ff")


def test_set_target_frame() -> None:
    """NE: set zone 1 to -18."""
    assert build_set_target(1, -18) == H("fefe0405ee02f3")


def test_set_target_zone2_uses_command_6() -> None:
    """SYN: zone 2 uses command 0x06."""
    frame = build_set_target(2, 3)
    assert frame[3] == Command.SET_ZONE2_TARGET
    assert frame[4] == 3


def test_set_target_matches_bm_checksum() -> None:
    """BM logs 'fe fe 03 05 ec 02 f1' for -20.

    The checksum 02f1 only fits a length byte of 04, so the 03 in that log is
    most likely a typo. We build 04, like fridge.py in the same repository.
    """
    assert build_set_target(1, -20) == H("fefe0405ec02f1")


@pytest.mark.parametrize(("zone", "temp"), [(0, 4), (3, 4), (1, 128), (1, -129)])
def test_set_target_rejects_bad_input(zone: int, temp: int) -> None:
    """SYN: invalid zone or temperature."""
    with pytest.raises(ValueError):
        build_set_target(zone, temp)


def test_set_frame_reproduces_app() -> None:
    """BM: the app copies all settings and changes only the battery saver."""
    status = parse_status(BM_STATUS_2[4:-2])
    assert build_set(status, battery_saver=2) == BM_SET


def test_set_frame_dual_zone_length() -> None:
    """SYN: dual-zone Set carries 25 data bytes."""
    status = parse_status(_dual_payload())
    frame = build_set(status, powered_on=False)
    assert frame[2] == 1 + 25 + 2
    assert frame[5] == 0  # powered_on
    assert frame[4 + 14] == 4  # zone 2 target


def test_build_frame_length_limit() -> None:
    """SYN: the length byte cannot exceed 255."""
    with pytest.raises(ValueError):
        build_frame(Command.SET, bytes(253))


# --- parsing ----------------------------------------------------------------


def test_parse_status_vector() -> None:
    """NE: -15 target, -13 current, 12.3 V, 100 %."""
    status = parse_status(BM_STATUS_1[4:-2])
    assert status.locked is False
    assert status.powered_on is True
    assert status.run_mode == 0
    assert status.battery_saver == 0
    assert status.zone1.target_temperature == -15
    assert status.temp_max == 20
    assert status.temp_min == -20
    assert status.zone1.hysteresis == 2
    assert status.start_delay == 0
    assert status.is_fahrenheit is False
    assert status.zone1.current_temperature == -13
    assert status.battery_percent == 100
    assert status.battery_voltage == 12.3
    assert status.is_dual_zone is False
    assert status.running_status is None


def test_parse_status_unknown_battery() -> None:
    """BM: 0x7f means the percentage is unknown."""
    status = parse_status(BM_STATUS_2[4:-2])
    assert status.battery_percent_known is False
    assert status.battery_voltage == 11.1
    assert status.zone1.current_temperature == -9


def test_parse_status_dual_zone() -> None:
    """SYN: second zone is decoded from offset 18."""
    status = parse_status(_dual_payload())
    assert status.is_dual_zone
    assert status.zone2 is not None
    assert status.zone2.target_temperature == 4
    assert status.zone2.hysteresis == 1
    assert status.zone2.current_temperature == 6
    assert status.running_status == 1


def test_parse_status_too_short() -> None:
    """SYN: fewer than 18 bytes is an error."""
    with pytest.raises(ValueError):
        parse_status(bytes(17))


@pytest.mark.parametrize(
    ("byte", "value"), [(0x7F, 127), (0x80, -128), (0xFF, -1), (0x00, 0)]
)
def test_signed_temperatures(byte: int, value: int) -> None:
    """SYN: int8 boundaries."""
    payload = bytearray(BM_STATUS_1[4:-2])
    payload[14] = byte
    assert parse_status(bytes(payload)).zone1.current_temperature == value


# --- stream reassembly ------------------------------------------------------


def test_reader_single_frame() -> None:
    """BM: one notification, one frame."""
    frames = FrameReader().feed(BM_STATUS_1)
    assert len(frames) == 1
    assert frames[0].command == Command.QUERY
    assert frames[0].checksum is ChecksumState.VALID
    assert is_status_frame(frames[0])


@pytest.mark.parametrize("cut", range(1, len(BM_STATUS_1)))
def test_reader_split_everywhere(cut: int) -> None:
    """BM: a frame split at any byte is reassembled."""
    reader = FrameReader()
    assert reader.feed(BM_STATUS_1[:cut]) == []
    frames = reader.feed(BM_STATUS_1[cut:])
    assert [f.raw for f in frames] == [BM_STATUS_1]


def test_reader_mtu_fragments() -> None:
    """NE: query answers arrive as 20 + 4 bytes at the default MTU."""
    reader = FrameReader()
    assert reader.feed(BM_STATUS_1[:20]) == []
    assert len(reader.feed(BM_STATUS_1[20:])) == 1


def test_reader_echo_and_status_in_one_notification() -> None:
    """Set echo followed by status in one notification (reported by Gruni22/alpicool_ha_ble)."""
    frames = FrameReader().feed(BM_SET + BM_SET_ANSWER)
    assert [f.command for f in frames] == [Command.SET, Command.SET]
    assert not is_status_frame(frames[0])  # 14 byte echo
    assert is_status_frame(frames[1])  # 18 byte status


def test_dual_zone_set_echo_is_not_status() -> None:
    """SYN: a 25 byte Set echo must not be parsed as status."""
    frame = FrameReader().feed(build_set(parse_status(_dual_payload())))[0]
    assert len(frame.payload) == 25
    assert not is_status_frame(frame)


def test_reader_garbage_before_header() -> None:
    """SYN: leading junk is skipped."""
    frames = FrameReader().feed(b"\x00\x11\xfe" + BM_STATUS_1)
    assert [f.raw for f in frames] == [BM_STATUS_1]


def test_reader_keeps_trailing_fe() -> None:
    """SYN: a lone 0xFE at the end may start the next header."""
    reader = FrameReader()
    assert reader.feed(b"\x00\xfe") == []
    assert [f.raw for f in reader.feed(BM_STATUS_1[1:])] == [BM_STATUS_1]


def test_reader_invalid_length_resyncs() -> None:
    """SYN: a header with an impossible length is skipped."""
    frames = FrameReader().feed(b"\xfe\xfe\x01" + BM_STATUS_1)
    assert [f.raw for f in frames] == [BM_STATUS_1]


def test_reader_doubled_checksum() -> None:
    """BM fridge.py and NE accept a doubled checksum."""
    body = BM_STATUS_1[:-2]
    frame = body + ((checksum(body) * 2) & 0xFFFF).to_bytes(2, "big")
    assert FrameReader().feed(frame)[0].checksum is ChecksumState.DOUBLED


def test_reader_mismatched_checksum_is_accepted() -> None:
    """NE note 1: some fridges send other data in the checksum bytes."""
    frame = BM_STATUS_1[:-2] + b"\x12\x34"
    frames = FrameReader().feed(frame)
    assert frames[0].checksum is ChecksumState.MISMATCH
    assert parse_status(frames[0].payload).zone1.target_temperature == -15


def test_reader_reset() -> None:
    """SYN: reset drops partial data."""
    reader = FrameReader()
    reader.feed(BM_STATUS_1[:10])
    reader.reset()
    assert reader.feed(BM_STATUS_1[10:]) == []


def test_bind_answer_is_not_status() -> None:
    """BM: bind answer 'fe fe 04 00 01 02 01'."""
    frame = FrameReader().feed(H("fefe0400010201"))[0]
    assert frame.command == Command.BIND
    assert frame.payload == b"\x01"
    assert frame.checksum is ChecksumState.VALID
    assert not is_status_frame(frame)


def test_icecubex_status_capture() -> None:
    """Query answer of a MAENTUM ICECUBE X 50 (nRF Connect, 2026-09-25)."""
    raw = bytes.fromhex(
        "FEFE2D01000101020414EC020000FDFD00000564"
        "0E06000000000000000080000A00000000000000"
        "0000000000000635"
    )
    frames = FrameReader().feed(raw)
    assert len(frames) == 1
    frame = frames[0]
    assert frame.checksum is ChecksumState.VALID
    assert is_status_frame(frame)
    status = parse_status(frame.payload)
    assert status.powered_on and not status.locked
    assert status.zone1.target_temperature == 4
    assert status.zone1.current_temperature == 5
    assert status.battery_voltage == 14.6
    assert status.zone2 is None
    assert status.running_status == 0

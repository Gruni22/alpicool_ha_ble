"""Frame encoding and decoding for Alpicool-compatible fridges.

Pure Python without Home Assistant or Bluetooth imports, so it can be unit
tested on its own and reused in a Home Assistant integration.

Sources for every protocol detail in this file (see docs/PROTOCOL.md):

* klightspeed/BrassMonkeyFridgeMonitor, README "Technical" section and
  fridge.py (MIT licence), reverse engineered from the Alpicool
  "CAR FRIDGE FREEZER" Android app.
* neftaly/esphome-alpicool, docs/protocol.md (test vectors, checksum and
  fragmentation notes).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
import logging

_LOGGER = logging.getLogger(__name__)

FRAME_HEADER = b"\xfe\xfe"

# Offsets inside the status payload (the bytes after the command byte).
STATUS_LEN_SINGLE_ZONE = 18
STATUS_LEN_DUAL_ZONE = 28

# The Set command sends 14 bytes for single-zone and 25 bytes for dual-zone
# fridges. The fridge may echo them back, so those lengths are never status.
SET_LEN_SINGLE_ZONE = 14
SET_LEN_DUAL_ZONE = 25

# Upper bound for the length byte we accept. The longest documented frame is a
# dual-zone status (length 31); some fridges append a few unknown bytes. The
# limit is our own sanity check, not part of the protocol, and lets the reader
# resync when a stray 0xFE precedes the real header.
MAX_LENGTH = 64

# Battery percentage reported when the fridge does not know it.
BATTERY_PERCENT_UNKNOWN = 0x7F


class Command(IntEnum):
    """Command and response codes."""

    BIND = 0x00
    QUERY = 0x01
    SET = 0x02
    RESET = 0x04
    SET_ZONE1_TARGET = 0x05
    SET_ZONE2_TARGET = 0x06


class RunMode(IntEnum):
    """Compressor run mode."""

    MAX = 0
    ECO = 1


class BatterySaver(IntEnum):
    """Low voltage cut-out level."""

    LOW = 0
    MID = 1
    HIGH = 2


class TemperatureUnit(IntEnum):
    """Unit the fridge uses for every temperature field."""

    CELSIUS = 0
    FAHRENHEIT = 1


class ChecksumState(IntEnum):
    """How the trailing two bytes of a frame relate to the computed sum."""

    VALID = 0
    DOUBLED = 1
    MISMATCH = 2


@dataclass(frozen=True, slots=True)
class Frame:
    """A decoded frame."""

    command: int
    payload: bytes
    checksum: ChecksumState
    raw: bytes


@dataclass(frozen=True, slots=True)
class ZoneStatus:
    """Settings and readings of one cooling zone."""

    target_temperature: int
    hysteresis: int
    tc_hot: int
    tc_mid: int
    tc_cold: int
    tc_halt: int
    current_temperature: int


@dataclass(frozen=True, slots=True)
class FridgeStatus:
    """Decoded status payload of a Query (or Set) response."""

    locked: bool
    powered_on: bool
    run_mode: int
    battery_saver: int
    temp_max: int
    temp_min: int
    start_delay: int
    unit: int
    battery_percent: int
    battery_voltage: float
    zone1: ZoneStatus
    zone2: ZoneStatus | None = None
    running_status: int | None = None
    raw: bytes = field(default=b"", compare=False, repr=False)

    @property
    def is_dual_zone(self) -> bool:
        """Return True if the fridge reported a second zone."""
        return self.zone2 is not None

    @property
    def is_fahrenheit(self) -> bool:
        """Return True if temperatures are in degrees Fahrenheit."""
        return self.unit == TemperatureUnit.FAHRENHEIT

    @property
    def battery_percent_known(self) -> bool:
        """Return True if the battery percentage is a real value."""
        return self.battery_percent != BATTERY_PERCENT_UNKNOWN


def _s8(value: int) -> int:
    """Interpret an unsigned byte as a signed 8 bit integer."""
    return value - 256 if value > 127 else value


def _u8(value: int) -> int:
    """Encode a signed or unsigned integer as one byte."""
    if not -128 <= value <= 255:
        raise ValueError(f"value {value} does not fit into one byte")
    return value & 0xFF


def checksum(data: bytes) -> int:
    """Return the 16 bit sum over all bytes."""
    return sum(data) & 0xFFFF


def build_frame(command: int, data: bytes = b"") -> bytes:
    """Build a frame: FE FE <len> <cmd> <data...> <sum hi> <sum lo>.

    ``len`` counts every byte after itself, i.e. command, data and the two
    checksum bytes.
    """
    length = 1 + len(data) + 2
    if length > 0xFF:
        raise ValueError("frame too long")
    frame = bytearray(FRAME_HEADER)
    frame.append(length)
    frame.append(command & 0xFF)
    frame.extend(data)
    frame.extend(checksum(frame).to_bytes(2, "big"))
    return bytes(frame)


def build_bind() -> bytes:
    """Build a Bind command. The fridge shows "APP" until a button is pressed."""
    return build_frame(Command.BIND)


def build_query() -> bytes:
    """Build a Query command."""
    return build_frame(Command.QUERY)


def build_set_target(zone: int, temperature: int) -> bytes:
    """Build a command that sets the target temperature of zone 1 or 2.

    ``temperature`` is in the unit the fridge is configured for.
    """
    if zone == 1:
        command = Command.SET_ZONE1_TARGET
    elif zone == 2:
        command = Command.SET_ZONE2_TARGET
    else:
        raise ValueError(f"invalid zone {zone}")
    if not -128 <= temperature <= 127:
        raise ValueError(f"temperature {temperature} out of range")
    return build_frame(command, bytes([_u8(temperature)]))


def build_set(
    status: FridgeStatus,
    *,
    locked: bool | None = None,
    powered_on: bool | None = None,
    run_mode: int | None = None,
    battery_saver: int | None = None,
) -> bytes:
    """Build a Set command.

    The fridge expects every setting in one frame, so all values not passed
    here are copied from the last known ``status``. That is also what the
    original app does.
    """
    z1 = status.zone1
    data = bytearray(
        [
            int(status.locked if locked is None else locked),
            int(status.powered_on if powered_on is None else powered_on),
            _u8(status.run_mode if run_mode is None else run_mode),
            _u8(status.battery_saver if battery_saver is None else battery_saver),
            _u8(z1.target_temperature),
            _u8(status.temp_max),
            _u8(status.temp_min),
            _u8(z1.hysteresis),
            _u8(status.start_delay),
            _u8(status.unit),
            _u8(z1.tc_hot),
            _u8(z1.tc_mid),
            _u8(z1.tc_cold),
            _u8(z1.tc_halt),
        ]
    )
    if (z2 := status.zone2) is not None:
        data.extend(
            [
                _u8(z2.target_temperature),
                0,
                0,
                _u8(z2.hysteresis),
                _u8(z2.tc_hot),
                _u8(z2.tc_mid),
                _u8(z2.tc_cold),
                _u8(z2.tc_halt),
                0,
                0,
                0,
            ]
        )
    return build_frame(Command.SET, bytes(data))


def _checksum_state(frame: bytes) -> ChecksumState:
    received = int.from_bytes(frame[-2:], "big")
    expected = checksum(frame[:-2])
    if received == expected:
        return ChecksumState.VALID
    if received == (expected * 2) & 0xFFFF:
        return ChecksumState.DOUBLED
    return ChecksumState.MISMATCH


def parse_status(payload: bytes) -> FridgeStatus:
    """Decode the status payload of a Query response.

    Raises ValueError if the payload is too short.
    """
    if len(payload) < STATUS_LEN_SINGLE_ZONE:
        raise ValueError(f"status payload too short: {len(payload)} bytes")
    p = payload
    zone1 = ZoneStatus(
        target_temperature=_s8(p[4]),
        hysteresis=_s8(p[7]),
        tc_hot=_s8(p[10]),
        tc_mid=_s8(p[11]),
        tc_cold=_s8(p[12]),
        tc_halt=_s8(p[13]),
        current_temperature=_s8(p[14]),
    )
    zone2 = None
    running_status = None
    if len(p) >= STATUS_LEN_DUAL_ZONE:
        running_status = p[27]
    # A MAENTUM IceCubeX (single zone) sends a long status with 0x80 (-128)
    # as the temperature of the zone it does not have.
    if len(p) >= STATUS_LEN_DUAL_ZONE and p[26] != 0x80:
        zone2 = ZoneStatus(
            target_temperature=_s8(p[18]),
            hysteresis=_s8(p[21]),
            tc_hot=_s8(p[22]),
            tc_mid=_s8(p[23]),
            tc_cold=_s8(p[24]),
            tc_halt=_s8(p[25]),
            current_temperature=_s8(p[26]),
        )
    return FridgeStatus(
        locked=bool(p[0]),
        powered_on=bool(p[1]),
        run_mode=p[2],
        battery_saver=p[3],
        temp_max=_s8(p[5]),
        temp_min=_s8(p[6]),
        start_delay=p[8],
        unit=p[9],
        battery_percent=p[15],
        battery_voltage=round(p[16] + p[17] / 10, 1),
        zone1=zone1,
        zone2=zone2,
        running_status=running_status,
        raw=bytes(p),
    )


def is_status_frame(frame: Frame) -> bool:
    """Return True if the frame carries a full status payload.

    Query and Reset answer with a status. A Set is answered with a status
    too, but the fridge may also echo the Set frame itself, whose payload is
    14 or 25 bytes long and must not be mistaken for a status.
    """
    size = len(frame.payload)
    if frame.command in (Command.QUERY, Command.RESET):
        return size >= STATUS_LEN_SINGLE_ZONE
    if frame.command == Command.SET:
        return size == STATUS_LEN_SINGLE_ZONE or size >= STATUS_LEN_DUAL_ZONE
    return False


class FrameReader:
    """Reassemble frames from a stream of BLE notifications.

    A notification can hold part of a frame (responses longer than the ATT
    payload arrive split) or more than one frame (some fridges send the echo
    of a Set command and the new status in one notification).

    Frames are validated by header and length. A checksum that is neither the
    plain nor the doubled sum is logged but accepted, because at least one
    fridge model is reported to send other data in those bytes
    (neftaly/esphome-alpicool, docs/protocol.md, note 1).
    """

    _MAX_BUFFER = 4 * (3 + MAX_LENGTH)

    def __init__(self) -> None:
        """Initialise an empty buffer."""
        self._buffer = bytearray()

    def reset(self) -> None:
        """Drop any partial data, e.g. after a disconnect."""
        self._buffer.clear()

    def feed(self, data: bytes) -> list[Frame]:
        """Add received bytes and return all complete frames."""
        self._buffer.extend(data)
        frames: list[Frame] = []
        while True:
            start = self._buffer.find(FRAME_HEADER)
            if start < 0:
                # Keep a trailing 0xFE, it may be the first header byte.
                keep = 1 if self._buffer.endswith(b"\xfe") else 0
                if len(self._buffer) > keep:
                    _LOGGER.debug(
                        "Dropping bytes without header: %s", self._buffer.hex()
                    )
                del self._buffer[: len(self._buffer) - keep]
                break
            if start:
                _LOGGER.debug(
                    "Dropping bytes before header: %s", self._buffer[:start].hex()
                )
                del self._buffer[:start]
            if len(self._buffer) < 3:
                break
            length = self._buffer[2]
            if not 3 <= length <= MAX_LENGTH:
                # Cannot be a real frame: skip one byte and look again, so that
                # "FE FE FE <len>" still finds the header at offset 1.
                _LOGGER.debug("Implausible length byte %d, resyncing", length)
                del self._buffer[:1]
                continue
            total = 3 + length
            if len(self._buffer) < total:
                break
            raw = bytes(self._buffer[:total])
            del self._buffer[:total]
            state = _checksum_state(raw)
            if state is ChecksumState.MISMATCH:
                _LOGGER.debug(
                    "Checksum mismatch, accepting frame anyway: %s", raw.hex()
                )
            frames.append(
                Frame(command=raw[3], payload=raw[4:-2], checksum=state, raw=raw)
            )
        if len(self._buffer) > self._MAX_BUFFER:
            self._buffer.clear()
        return frames

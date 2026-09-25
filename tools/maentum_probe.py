"""Command line probe: does a cooler box speak the Alpicool BLE protocol?

Needs Python 3.11+ and ``pip install bleak``. Run from the repository root::

    python tools/maentum_probe.py scan
    python tools/maentum_probe.py services AA:BB:CC:DD:EE:FF
    python tools/maentum_probe.py query AA:BB:CC:DD:EE:FF
    python tools/maentum_probe.py query AA:BB:CC:DD:EE:FF --bind --loop 10
    python tools/maentum_probe.py set-target AA:BB:CC:DD:EE:FF --temp 4

``scan``, ``services`` and ``query`` only read. ``set-target`` changes the
target temperature and must be called explicitly.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
import logging
from pathlib import Path
import sys
from typing import Any

# Works when started as "python tools/maentum_probe.py" from any directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from alpicool_protocol import (
    Command,
    Frame,
    FrameReader,
    FridgeStatus,
    build_bind,
    build_query,
    build_set_target,
    is_status_frame,
    parse_status,
)

SERVICE_UUID = "00001234-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "00001235-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "00001236-0000-1000-8000-00805f9b34fb"

# Name prefixes the Alpicool app looks for (BrassMonkeyFridgeMonitor README).
KNOWN_NAME_PREFIXES = ("WT-", "A1-", "AK1-", "AK2-", "AK3-")

# Default ATT MTU of 23 bytes minus the 3 byte ATT header.
DEFAULT_WRITE_CHUNK = 20

_LOGGER = logging.getLogger("maentum_probe")


def status_to_dict(status: FridgeStatus) -> dict[str, Any]:
    """Return a JSON friendly view of a status."""
    data = asdict(status)
    data["raw"] = status.raw.hex(" ")
    data["unit"] = "F" if status.is_fahrenheit else "C"
    data["dual_zone"] = status.is_dual_zone
    if not status.battery_percent_known:
        data["battery_percent"] = None
    return data


def looks_like_fridge(name: str | None, service_uuids: list[str]) -> bool:
    """Return True if advertisement data hints at an Alpicool-type fridge."""
    if SERVICE_UUID in (u.lower() for u in service_uuids):
        return True
    return bool(name) and name.upper().startswith(KNOWN_NAME_PREFIXES)


class Probe:
    """Minimal BLE session with one fridge."""

    def __init__(self, address: str, verbose: bool) -> None:
        """Store the target."""
        self._address = address
        self._verbose = verbose
        self._reader = FrameReader()
        self._frames: asyncio.Queue[Frame] = asyncio.Queue()
        self._client: Any = None
        self._chunk = DEFAULT_WRITE_CHUNK
        self._with_response = True

    def _on_notify(self, _sender: Any, data: bytearray) -> None:
        if self._verbose:
            print(f"<- {bytes(data).hex(' ')}", file=sys.stderr)
        for frame in self._reader.feed(bytes(data)):
            self._frames.put_nowait(frame)

    async def __aenter__(self) -> Probe:
        """Connect and subscribe to notifications."""
        from bleak import BleakClient, BleakScanner  # noqa: PLC0415

        device = await BleakScanner.find_device_by_address(self._address, timeout=20)
        if device is None:
            raise SystemExit(
                f"{self._address} not found. Is the box on, in range and not "
                "connected to a phone? A connected box stops advertising."
            )
        self._client = BleakClient(device)
        await self._client.connect()
        write_char = self._client.services.get_characteristic(WRITE_UUID)
        notify_char = self._client.services.get_characteristic(NOTIFY_UUID)
        if write_char is None or notify_char is None:
            uuids = [s.uuid for s in self._client.services]
            await self._client.disconnect()
            raise SystemExit(
                "Characteristics 0x1235/0x1236 not found. This box probably does "
                f"not use the Alpicool protocol. Services seen: {uuids}"
            )
        self._with_response = "write" in write_char.properties
        mtu = getattr(self._client, "mtu_size", None)
        if isinstance(mtu, int) and mtu > DEFAULT_WRITE_CHUNK + 3:
            self._chunk = mtu - 3
        await self._client.start_notify(notify_char, self._on_notify)
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Disconnect."""
        if self._client is not None:
            await self._client.disconnect()

    async def send(self, packet: bytes) -> None:
        """Write a packet, split into chunks the link accepts."""
        if self._verbose:
            print(f"-> {packet.hex(' ')}", file=sys.stderr)
        for start in range(0, len(packet), self._chunk):
            if start:
                await asyncio.sleep(0.15)
            await self._client.write_gatt_char(
                WRITE_UUID,
                packet[start : start + self._chunk],
                response=self._with_response,
            )

    async def wait_for(self, commands: set[int], timeout: float) -> Frame:
        """Return the next frame with one of the given command codes."""
        async with asyncio.timeout(timeout):
            while True:
                frame = await self._frames.get()
                if frame.command in commands:
                    return frame
                _LOGGER.debug("Ignoring frame %s", frame.raw.hex())

    async def query(self, timeout: float = 5) -> tuple[FridgeStatus, Frame]:
        """Send a Query and return the decoded answer."""
        await self.send(build_query())
        while True:
            frame = await self.wait_for({Command.QUERY}, timeout)
            if is_status_frame(frame):
                return parse_status(frame.payload), frame


async def _scan(timeout: float, show_all: bool) -> int:
    from bleak import BleakScanner  # noqa: PLC0415

    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    rows = []
    for device, adv in found.values():
        hint = looks_like_fridge(adv.local_name or device.name, adv.service_uuids)
        if hint or show_all:
            rows.append(
                (
                    not hint,
                    device.address,
                    adv.local_name or device.name or "",
                    adv.rssi,
                    hint,
                )
            )
    for _, address, name, rssi, hint in sorted(rows):
        flag = "fridge?" if hint else ""
        print(f"{address}  {rssi:>4} dBm  {name:<20} {flag}")
    if not rows:
        print("No matching devices. Try --all, the name of your box may be unknown.")
    return 0


async def _services(address: str) -> int:
    from bleak import BleakClient, BleakScanner  # noqa: PLC0415

    device = await BleakScanner.find_device_by_address(address, timeout=20)
    if device is None:
        print(f"{address} not found.", file=sys.stderr)
        return 1
    async with BleakClient(device) as client:
        for service in client.services:
            print(f"service {service.uuid}  {service.description}")
            for char in service.characteristics:
                print(f"  char {char.uuid}  [{', '.join(char.properties)}]")
        ok = (
            client.services.get_characteristic(WRITE_UUID) is not None
            and client.services.get_characteristic(NOTIFY_UUID) is not None
        )
    print(
        "\nAlpicool characteristics 0x1235/0x1236: "
        + ("present. Next step: 'query'." if ok else "NOT present, different protocol.")
    )
    return 0 if ok else 3


async def _query(address: str, bind: bool, loop: float | None, verbose: bool) -> int:
    async with Probe(address, verbose) as probe:
        if bind:
            print(
                "Bind sent. Press the button on the box when it shows 'APP'.",
                file=sys.stderr,
            )
            await probe.send(build_bind())
            try:
                await probe.wait_for({Command.BIND}, 30)
                print("Bind confirmed.", file=sys.stderr)
            except TimeoutError:
                print("No bind confirmation, continuing anyway.", file=sys.stderr)
        while True:
            try:
                status, frame = await probe.query()
            except TimeoutError:
                print("No answer to Query within 5 s.", file=sys.stderr)
                if loop is None:
                    return 1
            else:
                out = status_to_dict(status)
                out["checksum"] = frame.checksum.name
                print(json.dumps(out, ensure_ascii=False))
            if loop is None:
                return 0
            await asyncio.sleep(loop)


async def _set_target(address: str, zone: int, temp: int, verbose: bool) -> int:
    async with Probe(address, verbose) as probe:
        status, _ = await probe.query()
        if not status.temp_min <= temp <= status.temp_max:
            print(
                f"{temp} is outside the range the box reports "
                f"({status.temp_min}..{status.temp_max}).",
                file=sys.stderr,
            )
            return 2
        if zone == 2 and not status.is_dual_zone:
            print("The box reports only one zone.", file=sys.stderr)
            return 2
        await probe.send(build_set_target(zone, temp))
        status, _ = await probe.query()
        zone_status = status.zone1 if zone == 1 else status.zone2
        assert zone_status is not None
        print(json.dumps(status_to_dict(status), ensure_ascii=False))
        return 0 if zone_status.target_temperature == temp else 1


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        prog="maentum_probe.py", description=__doc__.split("\n")[0]
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="print raw frames")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="list nearby boxes")
    p_scan.add_argument("--timeout", type=float, default=10)
    p_scan.add_argument("--all", action="store_true", help="list every BLE device")

    p_services = sub.add_parser("services", help="list GATT services (read only)")
    p_services.add_argument("address")

    p_query = sub.add_parser("query", help="read and decode the status (read only)")
    p_query.add_argument("address")
    p_query.add_argument("--bind", action="store_true", help="send Bind first")
    p_query.add_argument("--loop", type=float, metavar="SECONDS", help="repeat")

    p_set = sub.add_parser("set-target", help="set a target temperature (writes!)")
    p_set.add_argument("address")
    p_set.add_argument("--zone", type=int, choices=(1, 2), default=1)
    p_set.add_argument("--temp", type=int, required=True, help="in the unit of the box")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)

    try:
        if args.cmd == "scan":
            return asyncio.run(_scan(args.timeout, args.all))
        if args.cmd == "services":
            return asyncio.run(_services(args.address))
        if args.cmd == "query":
            return asyncio.run(_query(args.address, args.bind, args.loop, args.verbose))
        return asyncio.run(
            _set_target(args.address, args.zone, args.temp, args.verbose)
        )
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

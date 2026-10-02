"""Tests for the command line probe's pure helpers."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import importlib.util

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "maentum_probe.py"


@pytest.fixture(scope="module")
def probe():
    """Load tools/maentum_probe.py as a module."""
    spec = importlib.util.spec_from_file_location("maentum_probe_tool", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_looks_like_fridge(probe) -> None:
    """Known names and the service UUID are recognised."""
    assert probe.looks_like_fridge("WT-0001", [])
    assert probe.looks_like_fridge(None, ["00001234-0000-1000-8000-00805F9B34FB"])
    # Brevia 24240 advertises 0xAF30.
    assert probe.looks_like_fridge(None, ["0000af30-0000-1000-8000-00805f9b34fb"])


def test_find_characteristic_with_duplicate_services(probe) -> None:
    """Brevia 24240 lists 0x1234 twice; pick the first usable characteristic."""

    class Char:
        def __init__(self, uuid: str, properties: list[str]) -> None:
            self.uuid = uuid
            self.properties = properties

    class Service:
        def __init__(self, *chars: Char) -> None:
            self.characteristics = list(chars)

    read_only = Char(probe.NOTIFY_UUID, ["read"])
    notify = Char(probe.NOTIFY_UUID, ["notify"])
    write = Char(probe.WRITE_UUID, ["write-without-response"])
    services = [
        Service(write, read_only, notify),
        Service(Char(probe.NOTIFY_UUID, ["read", "notify"])),
    ]

    assert probe.find_characteristic(services, probe.NOTIFY_UUID, ("notify",)) is notify
    assert probe.find_characteristic(services, probe.WRITE_UUID, ("write",)) is write
    assert probe.find_characteristic([Service(read_only)], probe.NOTIFY_UUID, ("notify",)) is None
    assert not probe.looks_like_fridge("Phone", [])


def test_status_to_dict(probe) -> None:
    """The JSON view marks unknown battery and unit."""
    payload = bytes.fromhex("00 01 00 00 ec 14 ec 02 00 01 00 00 00 00 f7 7f 0b 01")
    data = probe.status_to_dict(probe.parse_status(payload))
    assert data["unit"] == "F"
    assert data["battery_percent"] is None
    assert data["battery_voltage"] == 11.1
    assert data["raw"].startswith("00 01")


def test_help(probe, capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI parses and prints help."""
    with pytest.raises(SystemExit):
        probe.main(["--help"])
    assert "services" in capsys.readouterr().out

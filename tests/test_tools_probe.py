"""Tests for the command line probe's pure helpers."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import importlib.util
from pathlib import Path
import sys

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

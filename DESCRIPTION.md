# Alpicool BLE — DESCRIPTION.md

## Project Overview

Home Assistant Custom Component to control Alpicool/BrassMonkey/Ocean Comfort portable fridges via BLE.
- Domain: `alpicool_ble`
- Current version: `3.1.7` (coordinator branch)
- IoT class: `local_polling` via BLE

## Architecture

```
config_flow.py  →  __init__.py  →  AlpicoolDeviceUpdateCoordinator
                                        ├── AlpicoolApi (stateful per instance)
                                        ├── BleakClient (new per poll/command)
                                        └── coordinator.data (cached status dict)
                                    ↓
                     CoordinatorEntity subclasses (climate, sensor, switch, number, select)
```

**Key Pattern:** Each poll and each command opens a fresh `BleakClient` connection, fetches status, then disconnects. The coordinator's `data` dict is the single source of truth for all entities.

## File Map

| File | Purpose |
|------|---------|
| `api.py` | BLE packet codec + protocol. Stateful (buffer/events per instance). |
| `coordinator.py` | DataUpdateCoordinator — polling, command dispatch, error handling |
| `config_flow.py` | Setup UI, Bluetooth discovery, address normalization |
| `entity.py` | Base CoordinatorEntity with device_info and availability |
| `climate.py` | Climate zones (left/right), presets, HVAC on/off |
| `sensor.py` | Battery % and voltage (diagnostic) |
| `switch.py` | Panel lock switch (only available when powered on) |
| `number.py` | Hysteresis + start delay sliders (config category) |
| `select.py` | Battery saver level (Low/Medium/High) |
| `const.py` | Protocol constants, UUIDs, enums |

## BLE Protocol

**Packet format:** `\xfe\xfe [length] [cmd] [data...] [checksum:2 big-endian]`

Special hardcoded packets (no checksum logic applies):
- BIND `0x00`: `fe fe 03 00 01 ff`
- QUERY `0x01`: `fe fe 03 01 02 00`

Normal commands (SET, SET_LEFT, SET_RIGHT) use `_build_packet()`.

**Status payload** (minimum 18 bytes, 28+ bytes for dual-zone):
- `[0]` locked, `[1]` powered_on, `[2]` run_mode (0=MAX/FRIDGE, 1=ECO/FREEZER)
- `[4]` left_target, `[14]` left_current — **signed bytes** (use `_to_signed_byte()`)
- `[15]` bat_percent, `[16]` bat_vol_int, `[17]` bat_vol_dec
- `[18..27]` right zone (if dual-zone)

Temperature values are signed bytes transmitted as unsigned (e.g., -20°C → `0xEC`).

**Response quirk:** SET command response = echo of command + full status concatenated in one notification. `_notification_handler` buffers and parses this correctly.

## BIND Command

BIND (`0x00`) is **intentionally never sent** in normal operation. It caused problems when called too often. The `_is_bound_this_session` flag in the coordinator exists to prevent `send_command` from sending it too. The `async_send_bind` method in api.py is kept for protocol completeness only.

If a device shows "APP" on the display, the user must press the pairing button manually.

## Dual-Zone Detection

Dual-zone is detected at runtime: if the status payload is ≥ 28 bytes, `right_current` and other right zone fields are added to the status dict. The `climate.py` setup checks for `"right_current" in coordinator.data` to decide whether to add a right zone entity.

## Command Dispatch

Entities call coordinator methods directly — they never reference `coordinator.api`:

```python
await coordinator.async_set_values({"locked": True, "run_mode": 0, ...})
await coordinator.async_set_temperature("left", -5)
```

Internally, both delegate to `_execute_command(api_method, *args)` which:
1. Opens a BleakClient connection
2. Calls `api_method(client, *args)`
3. Waits 0.5s for the device to process
4. Fetches fresh status on the same connection
5. Calls `async_set_updated_data(new_status)` to push to all entities

On error, `async_request_refresh()` is triggered for recovery.

## Adding New Entities

1. Add field key to status dict in `api.py → _decode_status()` (and `_build_set_other_payload` if writable)
2. Add constant to `const.py` if needed
3. Create or extend platform file following existing dict-driven pattern (see `sensor.py`, `number.py`)
4. Register platform in `__init__.py → PLATFORMS` if new platform type

## Testing

```
pip install -r requirements_test.txt
pytest
```

Tests live in `tests/`:
- `test_api.py` — Pure Python; covers packet codec, decode, notification handling
- `test_config_flow.py` — HA integration; config and options flows
- `test_coordinator.py` — HA integration; poll, command dispatch, error recovery

## Known Limitations

- Battery voltage format: `f"{bat_vol_int}.{bat_vol_dec}"` — assumes single-digit decimal part
- `right_ret_diff` entity only added when dual-zone is detected on first poll

## Development Notes

- Python 3.12+ type hints used throughout
- All BLE calls are async; never block
- HA's `DataUpdateCoordinator` handles retry/backoff automatically on `UpdateFailed`
- `AlpicoolApi` instance is reused across connections — `async_start_notifications` resets buffer/events each time
- Config entry data keys: `address`, `name`, `dual_mode_fridge`, `poll_interval`
- Mutable options (`poll_interval`, `dual_mode_fridge`) stored in `entry.options`; code falls back to `entry.data` for existing installs
- Changing options triggers full entry reload via `_async_update_listener`
- Device name shown in HA device registry comes from `coordinator.device_name` (set from `entry.data["name"]`)

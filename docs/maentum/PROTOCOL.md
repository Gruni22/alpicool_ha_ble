# Alpicool BLE protocol (summary with sources)

Abbreviations: **BM** = [BrassMonkeyFridgeMonitor](https://github.com/klightspeed/BrassMonkeyFridgeMonitor) (README "Technical" and `fridge.py`, MIT), **NE** = [neftaly/esphome-alpicool](https://github.com/neftaly/esphome-alpicool) `docs/protocol.md`, **GR** = [Gruni22/alpicool_ha_ble](https://github.com/Gruni22/alpicool_ha_ble) README. Our own conclusions are marked as *inferred*.

The corresponding code is [`tools/alpicool_protocol.py`](../../tools/alpicool_protocol.py), tested in [`tests/test_tools_protocol.py`](../../tests/test_tools_protocol.py) with the captures from BM and NE.

## GATT

| Role | UUID | Source |
|---|---|---|
| Service | `0x1234` = `00001234-0000-1000-8000-00805f9b34fb` | BM |
| Commands (Write) | `0x1235` = `00001235-0000-1000-8000-00805f9b34fb` | BM |
| Responses (Notify) | `0x1236` = `00001236-0000-1000-8000-00805f9b34fb` | BM |

- No authentication, no pairing, no PIN (BM).
- One connection locks out all other clients; the box then sends no advertisements (BM). Home Assistant and the phone app are therefore mutually exclusive.
- Known device names: `WT-0001`, prefixes `A1-`, `AK1-`, `AK2-`, `AK3-` (BM). smarthomeundmore.de mentions `W1001` for a Plug In Festivals box (reported).
- The state cannot be read passively from advertisements; you have to connect and query (NE).

## Frame

```
FE FE <len> <cmd> <data ...> <sum_hi> <sum_lo>
```

- `len` counts all bytes after itself: command + data + 2 checksum bytes (BM, `create_packet`).
- Checksum: 16-bit sum of all preceding bytes including the header, big endian (BM).
- Some firmwares send double the sum; BM and NE accept both.
- On one A1-4X the last two bytes matched neither variant; NE therefore only checks header and length (NE, note 1). Our code accepts such frames and logs them.
- Responses longer than 20 bytes arrive in chunks at the default MTU (e.g. 20 + 4) and must be reassembled (NE). A SET echo and the new status can be contained in one notification (GR).
- *Inferred*: The BM capture `fe fe 03 05 ec 02 f1` (target temperature −20) probably has a typo in the length byte. The checksum `02 f1` only matches `04`, and BM's own code produces `04`. NE confirms the pattern with `FE FE 04 05 EE 02 F3` for −18.

## Commands

| Code | Name | Data | Response | Source |
|---|---|---|---|---|
| `0x00` | Bind | – | box shows "APP", responds after a button press | BM |
| `0x01` | Query | – | status (see below) | BM |
| `0x02` | Set | all settings, 14 bytes (1 zone) / 25 bytes (2 zones) | status with cmd `0x02` | BM |
| `0x04` | Reset | – | status | BM |
| `0x05` | Target zone 1 | int8 in the box's unit | echo | BM |
| `0x06` | Target zone 2 | int8 | echo | BM |

Bind is optional; the box also accepts commands without it (BM).

Set always transmits all values; the app fills unchanged values from the last status (BM, capture).

## Status (payload after the command byte)

All temperatures are int8 in the configured unit (BM).

| Offset | Field | Meaning |
|---|---|---|
| 0x00 | locked | button lock 0/1 |
| 0x01 | poweredOn | on/off |
| 0x02 | runMode | 0 = Max, 1 = Eco |
| 0x03 | batSaver | low-voltage protection 0 = low, 1 = medium, 2 = high |
| 0x04 | leftTarget | target zone 1 |
| 0x05 | tempMax | highest selectable target value |
| 0x06 | tempMin | lowest selectable target value |
| 0x07 | leftRetDiff | hysteresis zone 1 |
| 0x08 | startDelay | start delay in minutes |
| 0x09 | unit | 0 = °C, 1 = °F |
| 0x0A–0x0D | leftTC* | temperature corrections zone 1 |
| 0x0E | leftCurrent | current zone 1 |
| 0x0F | batPercent | battery in %, `0x7F` = unknown |
| 0x10 | batVolInt | voltage, whole volts |
| 0x11 | batVolDec | voltage, tenths |
| 0x12 | rightTarget | target zone 2 (dual zone only) |
| 0x15 | rightRetDiff | hysteresis zone 2 |
| 0x16–0x19 | rightTC* | corrections zone 2 |
| 0x1A | rightCurrent | current zone 2 |
| 0x1B | runningStatus | meaning unknown (BM) |

Dual zone is recognised by a payload of 28 bytes or more (NE).

## Test vectors (from the sources)

```
Query           fe fe 03 01 02 00                                   (BM, NE)
Bind            fe fe 03 00 01 ff                                   (BM)
Bind response   fe fe 04 00 01 02 01                                (BM)
Status          fe fe 15 01 00 01 00 00 f1 14 ec 02 00 00 00 00 00 00 f3 64 0c 03 05 6c   (BM, NE)
                → on, Max, target −15, range −20..20, current −13, 100 %, 12.3 V
Target −18      fe fe 04 05 ee 02 f3                                (NE)
Set (protection high) fe fe 11 02 00 01 00 02 ec 14 ec 02 00 00 00 00 00 00 04 00          (BM)
```

# Research: MAENTUM cooler boxes via Bluetooth in Home Assistant

As of: 2026-09-25. Every statement is assigned to a source and rated by reliability.

| Level | Meaning |
|---|---|
| **confirmed** | stated as such in a source's code or capture |
| **reported** | user report, not verified by us |
| **inferred** | our own conclusion from confirmed data |
| **unknown** | no reliable source found |

## 1. Manufacturer and models

| Statement | Level | Source |
|---|---|---|
| Plug In Festivals is now called MAENTUM | confirmed | [maentum.de](https://maentum.de/) |
| Current cooler boxes: IceCube (40 L), IceCube DUAL (two zones), IceCube X (50 L) | confirmed | [maentum.de cooler box comparison](https://maentum.de/pages/kuehlboxen-vergleich) |
| The IceCubeX can be controlled via Bluetooth through the "MAENTUM App" (temperature, minimum voltage) | confirmed | [techtest.org review of the IceCubeX](https://techtest.org/maentum-icecubex-die-effizienteste-kompressor-kuehlbox-im-test/) |
| The app "MAENTUM IceCubeX" is published by Plug-in Festivals GmbH, package `com.maentum`, v1.0 of 2024-11-11, v1.0.4 of 2025-09-16 | confirmed | [App Store](https://apps.apple.com/de/app/maentum-icecubex/id6737261611), [Google Play](https://play.google.com/store/apps/details?id=com.maentum) |
| The IceCubeX speaks the Alpicool protocol: name `A1-…`, service 0x1234 with 0x1235 (Write Without Response) and 0x1236 (Notify); query `FEFE03010200` is answered with a 48-byte status frame (checksum correct) | **confirmed on one device** | own test with nRF Connect on an ICECUBE X 50, 2026-09-25 (section 5) |

## 2. Indications that (older) Plug In Festivals boxes speak the Alpicool protocol

| Statement | Level | Source |
|---|---|---|
| Pekaway forum: user "moe.camp" suspects the same protocol as Alpicool/Vevor, recommends testing with the app "Car Fridge Freezer" and uses an MQTT bridge script based on BrassMonkeyFridgeMonitor. He reports that the Bluetooth connection "dies every now and then" (handled by a systemd restart). The exact model is not named. | reported | [Pekaway forum, thread 2302](https://forum.pekaway.de/t/maentum-pluginfestival-kuhlboxen-per-bluetooth-einbinden-und-steuern/2302) |
| smarthomeundmore.de integrates an older Plug In Festivals box via ESPHome using the component `neftaly/esphome-alpicool`; dual zone not yet tested according to the author | reported | [smarthomeundmore.de](https://smarthomeundmore.de/home-assistant-kuehlbox-smart-bluetooth-esphome/) |

Note: From the research environment the Pekaway forum could only be read through a summary, not verbatim. The details above come from targeted follow-up questions to that summary.

**Conclusion (inferred):** For older Plug In Festivals boxes there are two independent user reports of the Alpicool protocol. For the IceCubeX it was confirmed on the device on 2026-09-25 (see above). For other models the probe script `tools/maentum_probe.py` settles this in one minute.

## 3. The protocol

Fully described in [PROTOCOL.md](PROTOCOL.md). Main sources:

| Source | License | Contents |
|---|---|---|
| [klightspeed/BrassMonkeyFridgeMonitor](https://github.com/klightspeed/BrassMonkeyFridgeMonitor) | MIT | Reconstructed from a capture and the JavaScript of the Alpicool app "CAR FRIDGE FREEZER" v2.0.0. UUIDs, frame format, commands, field tables, captures |
| [neftaly/esphome-alpicool](https://github.com/neftaly/esphome-alpicool) `docs/protocol.md` | no license file | Test vectors, fragmentation, deviating checksums on an A1-4X |
| [Gruni22/alpicool_ha_ble](https://github.com/Gruni22/alpicool_ha_ble) | MIT (since 2026-09-25) | Practice: SET echo and status arrive in one notification, write with response required |

## 4. Existing projects

| Project | Type | Status | License | Assessment |
|---|---|---|---|---|
| [Gruni22/alpicool_ha_ble](https://github.com/Gruni22/alpicool_ha_ble) | HACS integration | active, last commit 2026-09-25 | MIT (since 2026-09-25) | most complete HA solution |
| [neftaly/esphome-alpicool](https://github.com/neftaly/esphome-alpicool) | ESPHome component | last commit 2026-02-24 | **none** | climate, sensors, switches, selects; tested on CX40 |
| [klightspeed/BrassMonkeyFridgeMonitor](https://github.com/klightspeed/BrassMonkeyFridgeMonitor) | Python CLI + MQTT | last commit 2026-07-12 | MIT | reference for the protocol |
| [jakub-hajek/alpicool-esp32-mqtt](https://github.com/jakub-hajek/alpicool-esp32-mqtt) | ESP32 → MQTT (PlatformIO) | last commit 2025-08-01 | MIT | alternative without ESPHome |
| [johnelliott/alpicoold](https://github.com/johnelliott/alpicoold) | Go, HomeKit | 2021 | not checked | older project |
| [danfulton72/amps_fridge_ble_ha](https://github.com/danfulton72/amps_fridge_ble_ha) | HA component (AMPS) | not checked | not checked | only found, not evaluated |
| [esphome/feature-requests #1375](https://github.com/esphome/feature-requests/issues/1375) | feature request | open | – | no official ESPHome support |

## 5. Open questions

1. **Protocol of the IceCubeX** (the tested ICECUBE X 50): **resolved** on 2026-09-25 with nRF Connect. Response to the query (three notifications, 20 + 20 + 8 bytes):
   ```
   FEFE2D01000101020414EC020000FDFD00000564
   0E06000000000000000080000A00000000000000
   0000000000000635
   ```
   Decoded: on, lock off, Eco, battery protection high, target 4 °C, current 5 °C, range −20..20 °C, hysteresis 2, °C, battery 100 %, 14.6 V. The payload is 42 bytes instead of 18/28; the temperature of the second zone is 0x80 (−128), *inferred*: no second zone. Bytes 28–41 are unknown. Setting the target temperature with `FEFE040505020A` (command 0x05, 5 °C) works according to the display. Open: the remaining settings via command 0x02.
2. Valid value ranges for hysteresis and start delay: not documented in any source.
3. Meaning of the byte `running_status` (dual zone, offset 0x1B): unknown according to BrassMonkey.
4. Purpose of the additional characteristic `0xFFF1`: unknown according to neftaly; subscribing to it can drop the connection on some firmwares.

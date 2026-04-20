# Alpicool, BrassMonkey, Ocean Comfort, ... 12V/24V BLE Fridge Integration for Home Assistant

A Home Assistant Custom Component to control Alpicool, BrassMonkey, Ocean Comfort, or other compatible portable fridges via Bluetooth Low Energy (BLE).

This integration creates multiple entities in Home Assistant, allowing you to monitor and control all known aspects of your fridge.

This component was inspired by the prior work done by klightspeed's [BrassMonkeyFridgeMonitor](https://github.com/klightspeed/BrassMonkeyFridgeMonitor).

---

## Features & Supported Entities

| Platform | Entity | Description |
|----------|--------|-------------|
| **Climate** | `Left` / `Right` zone | Set target temperature (−20 °C to +20 °C, 1 °C steps), switch Max/Eco preset, turn on/off |
| **Sensor** | Battery | Battery charge percentage |
| **Sensor** | Battery Voltage | Current battery voltage in Volts |
| **Switch** | Lock | Enable / disable the fridge's control panel lock |
| **Number** | Hysteresis | Compressor return-difference / hysteresis (1–10 °C) |
| **Number** | Start Delay | Compressor start delay (0–10 min) |
| **Select** | Battery Saver | Battery protection level (Low / Medium / High) |

---

## Dual-Zone Support

This integration supports **both single and dual-zone fridges**.

- **Dual-zone models**: Creates two `climate` entities (`… Left` and `… Right`), both available.
- **Single-zone models**: Creates two `climate` entities, but `… Right` stays permanently `unavailable` since the device reports no data for it. You can disable or hide this entity in Home Assistant.

Dual-zone is detected automatically at runtime from the BLE status payload — no manual configuration needed.

> **Note:** Dual-zone support is currently untested. Feedback welcome via [GitHub Issues](https://github.com/Gruni22/alpicool_ha_ble/issues).

---

## Installation

### Method 1: HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Gruni22&repository=alpicool_ha_ble&category=integration)

1. Click the badge above or search for **"Alpicool BLE"** in HACS.
2. Click **Install**.
3. Restart Home Assistant.

### Method 2: Manual Installation

1. Download the latest release from this repository.
2. Copy the `alpicool_ble` directory into the `custom_components` directory of your Home Assistant instance.
3. Restart Home Assistant.

---

## Configuration

Configuration is done entirely via the Home Assistant UI.

1. Navigate to **Settings → Devices & Services**.
2. Home Assistant should automatically discover your fridge if it is powered on and in range. Click **Configure** on the discovered device card.
3. If not discovered automatically, click **Add Integration**, search for **"Alpicool BLE"**, and enter the device's Bluetooth address manually.
4. Complete the setup form:

| Option | Default | Description |
|--------|---------|-------------|
| **Bluetooth Address** | *(auto or manual)* | MAC address in `XX:XX:XX:XX:XX:XX` format |
| **Device Name** | `Alpicool Fridge` | Display name used for all entities |
| **Dual Zone Modes** | `Off` | Enable **Fridge / Freezer** presets instead of **Max / Eco** for dual-zone devices with a dedicated freezer mode |
| **Poll Interval** | `30` s | How often the integration queries the fridge for fresh data |

> **Tip:** If your fridge displays `APP` on the screen, press the pairing button on the device before or during setup.

---

## Troubleshooting

**Fridge not discovered automatically**
- Make sure the fridge is powered on and Bluetooth is enabled on your HA host.
- Try adding it manually via **Add Integration → Alpicool BLE** using the Bluetooth address from the fridge's manual or a BLE scanner app.

**Entities show "Unavailable"**
- The integration could not connect to the fridge. Check that it is powered on and within BLE range.
- Increase the **Poll Interval** if the fridge is at the edge of BLE range to reduce connection pressure.

**`APP` shown on the fridge display**
- The fridge is in pairing mode. Press the pairing button on the device, then try reconnecting.

**Wrong temperature display (Fahrenheit)**
- The integration currently always displays in Celsius, even if the fridge is set to Fahrenheit internally. This is a known limitation.

---

## Technical Details & Protocol Quirks

The development of this integration revealed several quirks in the Alpicool BLE protocol:

- **Inconsistent Protocol:** The rules for calculating packet length and checksums differ across commands. `BIND` and `QUERY` use hardcoded packets; `SET`, `SET_LEFT`, and `SET_RIGHT` use the normal framing.
- **Concatenated BLE Responses:** The fridge responds to `SET` commands with two packets concatenated in a single BLE notification — first an echo of the sent command, then a full status update. The notification handler buffers and re-parses this stream correctly.
- **Signed Byte Conversion:** Temperature values are transmitted as signed 8-bit integers. The code correctly converts negative temperatures (e.g., −20 °C) to their unsigned byte representation (e.g., `0xEC`) and back.
- **Dual-Zone Detection:** If the status payload is ≥ 28 bytes, the device is treated as dual-zone. Right-zone entities are added once during setup based on the first successful poll.
- **Per-Request Connections:** Each status poll and each command opens a new BLE connection, reads data, then disconnects. This avoids stale connection state but adds latency proportional to the poll interval.

---

## Changelog (recent)

| Version | Notes |
|---------|-------|
| 3.1.7 | Coordinator-based architecture, configurable poll interval, stateless API layer |
| 3.x | Refactoring, dual-zone improvements |

---

## Credits

- Inspired by [BrassMonkeyFridgeMonitor](https://github.com/klightspeed/BrassMonkeyFridgeMonitor) by klightspeed.
- Built with [bleak](https://github.com/hbldh/bleak) and [Home Assistant's DataUpdateCoordinator](https://developers.home-assistant.io/docs/integration_fetching_data/).

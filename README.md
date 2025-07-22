# Alpicool, BrassMonkey, Ocean Comfort, ... 12V/24V BLE Fridge Integration for Home Assistant

This is a Home Assistant Custom Component to control Alpicool, BrassMonkey, Ocean Comfort, or other compatible portable fridges via Bluetooth Low Energy (BLE).

This integration creates multiple entities in Home Assistant, allowing you to monitor and control all aspects of your fridge.

This component was inspired by the prior work done by klightspeed's [BrassMonkeyFridgeMonitor](https://github.com/klightspeed/BrassMonkeyFridgeMonitor).

## Features & Supported Entities

* **Climate:** A central `climate` entity for each cooling zone to:
    * Turn the fridge on and off.
    * Set the target temperature (in 1°C increments).
    * Switch between `Max` and `Eco` preset modes.
    * Display the current temperature.
* **Sensor:** Separate `sensor` entities for diagnostic data:
    * Battery charge percentage.
    * Battery voltage.
* **Switch:** A `switch` entity to enable or disable the fridge's control panel lock.
* **Number:** `number` entities to configure advanced settings directly from the UI:
    * Compressor start delay (in minutes).
    * Temperature hysteresis (return difference).
* **Select:** `select` entities to configure advanced settings directly from the UI:
    * Battery saver

## Dual-Zone Support
This integration supports !!!untested!!! **both single and dual-zone fridges**. 

* For **dual-zone** models, it will create two `climate` entities (`... Left` and `... Right`), which will both become available.
* For **single-zone** models, it will also create two `climate` entities, but the `... Right` entity will remain permanently `unavailable` as the fridge does not report data for it. You can disable or hide this second entity in Home Assistant.

***
## Installation

Easiest install is via [HACS](https://hacs.xyz/):

### Method 1: HACS (Recommended)
1.  [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Gruni22&repository=https%3A%2F%2Fgithub.com%2FGruni22%2Falpicool_ha_ble&category=integration)
4.  Search for "Alpicool BLE" and click "Install".
5.  Restart Home Assistant.

### Method 2: Manual Installation
1.  Download the latest release from this repository.
2.  Copy the `alpicool_ble` directory into the `custom_components` directory of your Home Assistant instance.
3.  Restart Home Assistant.

***
## Configuration

Configuration is done via the Home Assistant UI.

1.  Navigate to **Settings > Devices & Services**.
2.  Home Assistant should automatically discover your fridge if it is powered on and nearby. If so, click **Configure** on the discovered device card.
3.  If it's not discovered automatically, click **Add Integration**, search for "Alpicool BLE", and follow the prompts to select your device.
4.  Press the pairing button on the fridge, if "APP" is written on the display.

***
## Technical Details & Protocol Quirks

The development of this integration revealed several quirks in the Alpicool BLE protocol that required specific workarounds in the code.

* **Inconsistent Protocol:** The rules for calculating packet length and checksums are not consistent across all commands.
* **Special Command Handling:** `BIND`, `QUERY`, `SET_LEFT`, and `SET_RIGHT` commands are treated as special cases with a different packet structure than more complex commands like `SET`.
* **Concatenated BLE Responses:** The fridge responds to `SET` commands by sending two packets concatenated into a single BLE notification: first an echo of the sent command, followed by a full status update. The notification handler was specifically rewritten to parse this data stream correctly and ignore the echo.
* **Signed Byte Conversion:** Temperature values are transmitted as signed 8-bit integers. The code correctly converts between negative temperature values (e.g., -20°C) and their unsigned byte representation (e.g., 236) for both sending and receiving data.
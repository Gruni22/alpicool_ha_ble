# Alpicool BLE Integration for Home Assistant

This is a Home Assistant Custom Component to control Alpicool portable fridges via Bluetooth Low Energy (BLE).

This integration creates a `climate` entity in Home Assistant, allowing you to monitor and control your fridge.

This component was inspired by the prior work done by klightspeed's [BrassMonkeyFridgeMonitor](https://github.com/klightspeed/BrassMonkeyFridgeMonitor).

## Features & Limitations

### Features
* Turn the fridge on and off.
* Set the target temperature (in 1°C increments).
* Switch between `Max` and `Eco` preset modes.
* Displays the current temperature.
* Displays battery status (voltage and percentage).

### ⚠️ Important Limitation
This integration has been developed and tested **exclusively for single-compartment Alpicool fridges**. Commands for a second compartment (e.g., `SET_RIGHT`) are not implemented and will not work.

***
## Installation

### Method 1: HACS (Recommended)
1.  In HACS, go to the "Integrations" section.
2.  Click the three dots in the top right and select "Custom repositories".
3.  Add the URL to this GitHub repository and select the category "Integration".
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

***
## Technical Details & Protocol Quirks

The development of this integration revealed several quirks in the Alpicool BLE protocol that required specific workarounds in the code.

* **Inconsistent Protocol:** The rules for calculating packet length and checksums are not consistent across all commands.
* **Special Command Handling:** The `BIND` and `QUERY` commands follow a different packet structure than the `SET` commands. They are treated as special cases in the code to ensure reliability.
* **Concatenated BLE Responses:** The fridge responds to `SET` commands by sending two packets concatenated into a single BLE notification: first an echo of the sent command, followed by a full status update. The notification handler was specifically rewritten to parse this data stream correctly and ignore the echo.
* **Signed Byte Conversion:** Temperature values are transmitted as signed 8-bit integers. The code correctly converts between negative temperature values (e.g., -20°C) and their unsigned byte representation (e.g., 236) for both sending and receiving data.

"""Constants for the Alpicool BLE integration."""
from enum import IntEnum

DOMAIN = "alpicool_ble"

FRIDGE_RW_CHARACTERISTIC_UUID = "00001235-0000-1000-8000-00805f9b34fb"
FRIDGE_NOTIFY_UUID = '00001236-0000-1000-8000-00805f9b34fb'

# --- Configuration Options ---
CONF_DUAL_ZONE_MODES = "dual_zone_modes"

# --- Presets ---
PRESET_ECO = "Eco"
PRESET_MAX = "Max"
PRESET_FRIDGE = "Fridge"
PRESET_FREEZER = "Freezer"

class Request:
    BIND = 0x00
    QUERY = 0x01
    SET = 0x02
    RESET = 0x04
    SET_LEFT = 0x05
    SET_RIGHT = 0x06

# Response codes
class Response(IntEnum):
    STATUS = 0x01
    BATTERY = 0x02

# Battery protection levels
class BatteryProtection(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2

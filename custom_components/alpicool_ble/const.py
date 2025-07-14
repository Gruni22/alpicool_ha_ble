"""Constants for the Alpicool BLE integration."""
from enum import IntEnum

DOMAIN = "alpicool_ble"

FRIDGE_SERVICE_UUID = "0000fee7-0000-1000-8000-00805f9b34fb"
FRIDGE_RW_CHARACTERISTIC_UUID = "0000fec8-0000-1000-8000-00805f9b34fb"

# Request codes
class Request(IntEnum):
    SET_TEMP = 0x01
    SET_LOCK = 0x04
    SET_POWER = 0x05
    SET_ECO = 0x06
    SET_MAX = 0x07 # Eco/Max mode
    SET_BATT_PROT = 0x08

# Response codes
class Response(IntEnum):
    STATUS = 0x01
    BATTERY = 0x02

# Battery protection levels
class BatteryProtection(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2
"""Constants for the Alpicool BLE integration."""

from enum import IntEnum

DOMAIN = "alpicool_ble"

FRIDGE_RW_CHARACTERISTIC_UUID = "00001235-0000-1000-8000-00805f9b34fb"
FRIDGE_NOTIFY_UUID = "00001236-0000-1000-8000-00805f9b34fb"

# --- BLE writes ---
# Usable ATT payload for the default MTU of 23 bytes (MTU minus the 3 byte
# ATT header). Some adapters reject a single write that exceeds it, so longer
# packets are split into chunks of at most this size.
DEFAULT_MAX_WRITE_SIZE = 20
# Pause between the chunks of a split packet so the fridge can reassemble them.
WRITE_CHUNK_DELAY = 0.15

# --- Polling / reconnect ---
# Seconds between status queries while connected.
POLL_INTERVAL = 30
# Minimum pause after a failed connection attempt, so a fridge that advertises
# constantly cannot turn the reconnect loop into a busy loop.
RECONNECT_BACKOFF = 10
# Longest pause between connection attempts. A new advertisement cuts it short.
RECONNECT_INTERVAL = 60
# After this long without a successful status update the device goes unavailable.
UNAVAILABLE_AFTER = 300

# Value of the "unit" status byte when the fridge is set to Fahrenheit (0 is Celsius).
UNIT_FAHRENHEIT = 1

# Fallback target temperature range, used when the fridge does not report a
# usable range of its own in "temp_min"/"temp_max".
DEFAULT_MIN_TEMP_C = -30
DEFAULT_MAX_TEMP_C = 20
DEFAULT_MIN_TEMP_F = -22
DEFAULT_MAX_TEMP_F = 68

# --- Configuration Options ---
CONF_DUAL_ZONE_MODES = "dual_zone_modes"
CONF_LEFT_NAME = "left_name"
CONF_RIGHT_NAME = "right_name"

DEFAULT_LEFT_NAME = "Left"
DEFAULT_RIGHT_NAME = "Right"

# --- Presets ---
PRESET_ECO = "Eco"
PRESET_MAX = "Max"
PRESET_FRIDGE = "Fridge"
PRESET_FREEZER = "Freezer"


class Request:
    """Possible Commands."""

    BIND = 0x00
    QUERY = 0x01
    SET = 0x02
    RESET = 0x04
    SET_LEFT = 0x05
    SET_RIGHT = 0x06


# Battery protection levels
class BatteryProtection(IntEnum):
    """Battery Protection Levels."""

    LOW = 0
    MEDIUM = 1
    HIGH = 2

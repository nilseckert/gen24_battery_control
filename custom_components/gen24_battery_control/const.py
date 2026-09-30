"""Constants for Gen24 Battery Control."""

from __future__ import annotations

from .registers import ControlMode

DOMAIN = "gen24_battery_control"

CONF_UNIT_ID = "unit_id"
CONF_STORAGE_BASE = "storage_base"
CONF_MANUFACTURER = "manufacturer"
CONF_MODEL = "model"
CONF_SERIAL = "serial"
CONF_SW_VERSION = "sw_version"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_ENFORCE = "enforce"

DEFAULT_PORT = 502
DEFAULT_UNIT_ID = 1
DEFAULT_SCAN_INTERVAL = 5
DEFAULT_ENFORCE = False

# Seconds to wait before reading back written setpoints
VERIFY_DELAY = 1.0

# Keepalive is sent after this fraction of the revert timeout has elapsed
KEEPALIVE_FRACTION = 1 / 3
KEEPALIVE_MIN_SECONDS = 5

CONTROL_MODE_OPTIONS: dict[str, ControlMode] = {
    "auto": ControlMode.AUTO,
    "limit_charge": ControlMode.LIMIT_CHARGE,
    "limit_discharge": ControlMode.LIMIT_DISCHARGE,
    "limit_both": ControlMode.LIMIT_BOTH,
}
CONTROL_MODE_NAMES: dict[int, str] = {v: k for k, v in CONTROL_MODE_OPTIONS.items()}

SERVICE_SET_SETPOINTS = "set_setpoints"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_CONTROL_MODE = "control_mode"
ATTR_DISCHARGE_LIMIT = "discharge_limit"
ATTR_CHARGE_LIMIT = "charge_limit"
ATTR_MIN_RESERVE = "min_reserve"
ATTR_REVERT_TIMEOUT = "revert_timeout"
ATTR_GRID_CHARGING = "grid_charging"

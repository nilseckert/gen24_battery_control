"""Load the HA-independent modules without importing Home Assistant."""

from __future__ import annotations

import pathlib
import sys
import types

PKG_DIR = pathlib.Path(__file__).parent.parent / "custom_components" / "gen24_battery_control"

pkg = types.ModuleType("g24")
pkg.__path__ = [str(PKG_DIR)]
sys.modules["g24"] = pkg

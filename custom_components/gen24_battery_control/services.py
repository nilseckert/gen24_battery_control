"""Service to change several setpoints in one ordered, verified write."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_CHARGE_LIMIT,
    ATTR_CHARGE_POWER_LIMIT,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_CONTROL_MODE,
    ATTR_DISCHARGE_LIMIT,
    ATTR_DISCHARGE_POWER_LIMIT,
    ATTR_GRID_CHARGE_POWER,
    ATTR_GRID_CHARGING,
    ATTR_GRID_DISCHARGE_POWER,
    ATTR_MIN_RESERVE,
    ATTR_REVERT_TIMEOUT,
    CONTROL_MODE_OPTIONS,
    DOMAIN,
    SERVICE_SET_SETPOINTS,
)
from .coordinator import Gen24Coordinator

_PCT = vol.All(vol.Coerce(float), vol.Range(min=0, max=100))
_WATT = vol.All(vol.Coerce(float), vol.Range(min=0))

# Only one value per register: each group maps to OutWRte or InWRte
_DISCHARGE = "discharge side (discharge_limit, discharge_power_limit, grid_charge_power)"
_CHARGE = "charge side (charge_limit, charge_power_limit, grid_discharge_power)"

SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_CONTROL_MODE): vol.In(list(CONTROL_MODE_OPTIONS)),
        vol.Exclusive(ATTR_DISCHARGE_LIMIT, _DISCHARGE): _PCT,
        vol.Exclusive(ATTR_DISCHARGE_POWER_LIMIT, _DISCHARGE): _WATT,
        vol.Exclusive(ATTR_GRID_CHARGE_POWER, _DISCHARGE): _WATT,
        vol.Exclusive(ATTR_CHARGE_LIMIT, _CHARGE): _PCT,
        vol.Exclusive(ATTR_CHARGE_POWER_LIMIT, _CHARGE): _WATT,
        vol.Exclusive(ATTR_GRID_DISCHARGE_POWER, _CHARGE): _WATT,
        vol.Optional(ATTR_MIN_RESERVE): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
        vol.Optional(ATTR_REVERT_TIMEOUT): vol.All(vol.Coerce(int), vol.Range(min=0, max=65534)),
        vol.Optional(ATTR_GRID_CHARGING): cv.boolean,
    }
)


def _coordinator(hass: HomeAssistant, entry_id: str | None) -> Gen24Coordinator:
    entries = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.state is ConfigEntryState.LOADED and (entry_id is None or e.entry_id == entry_id)
    ]
    if len(entries) != 1:
        raise ServiceValidationError(
            "config_entry_id is required when zero or several inverters are loaded"
            if entry_id is None
            else f"no loaded entry {entry_id}"
        )
    return entries[0].runtime_data


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register integration services."""

    async def set_setpoints(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        data = call.data
        c = coordinator
        if data.get(ATTR_GRID_CHARGE_POWER, 0) > 0 and data.get(ATTR_GRID_DISCHARGE_POWER, 0) > 0:
            raise ServiceValidationError(
                "grid_charge_power and grid_discharge_power cannot both be active"
            )
        if (
            data.get(ATTR_GRID_CHARGE_POWER, 0) > 0
            and data.get(ATTR_CONTROL_MODE, "limit_discharge") != "limit_discharge"
        ):
            raise ServiceValidationError(
                "grid_charge_power needs control_mode limit_discharge (or no control_mode)"
            )
        changes: dict[str, Any] = {}
        # Discharge side (OutWRte)
        if ATTR_DISCHARGE_LIMIT in data:
            changes |= c.discharge_limit_changes(c.pct_to_rate(data[ATTR_DISCHARGE_LIMIT]))
        if ATTR_DISCHARGE_POWER_LIMIT in data:
            changes |= c.discharge_limit_changes(c.watt_to_rate(data[ATTR_DISCHARGE_POWER_LIMIT]))
        if ATTR_GRID_CHARGE_POWER in data:
            changes |= c.grid_charge_changes(data[ATTR_GRID_CHARGE_POWER])
        # Charge side (InWRte)
        if ATTR_CHARGE_LIMIT in data:
            changes |= c.charge_limit_changes(c.pct_to_rate(data[ATTR_CHARGE_LIMIT]))
        if ATTR_CHARGE_POWER_LIMIT in data:
            changes |= c.charge_limit_changes(c.watt_to_rate(data[ATTR_CHARGE_POWER_LIMIT]))
        if ATTR_GRID_DISCHARGE_POWER in data:
            changes |= c.grid_discharge_changes(data[ATTR_GRID_DISCHARGE_POWER])
        # An explicit control mode wins over the one implied by the fields above
        if ATTR_CONTROL_MODE in data:
            changes["control_mode"] = CONTROL_MODE_OPTIONS[data[ATTR_CONTROL_MODE]]
        if ATTR_MIN_RESERVE in call.data:
            changes["min_reserve"] = coordinator.pct_to_reserve(call.data[ATTR_MIN_RESERVE])
        if ATTR_REVERT_TIMEOUT in call.data:
            changes["revert_timeout"] = call.data[ATTR_REVERT_TIMEOUT]
        if ATTR_GRID_CHARGING in call.data:
            changes["grid_charging"] = int(call.data[ATTR_GRID_CHARGING])
        await coordinator.async_set_target(**changes)

    hass.services.async_register(DOMAIN, SERVICE_SET_SETPOINTS, set_setpoints, schema=SCHEMA)

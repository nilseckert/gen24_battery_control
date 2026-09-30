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
    ATTR_CONFIG_ENTRY_ID,
    ATTR_CONTROL_MODE,
    ATTR_DISCHARGE_LIMIT,
    ATTR_GRID_CHARGING,
    ATTR_MIN_RESERVE,
    ATTR_REVERT_TIMEOUT,
    CONTROL_MODE_OPTIONS,
    DOMAIN,
    SERVICE_SET_SETPOINTS,
)
from .coordinator import Gen24Coordinator

_PCT = vol.All(vol.Coerce(float), vol.Range(min=-100, max=100))

SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_CONTROL_MODE): vol.In(list(CONTROL_MODE_OPTIONS)),
        vol.Optional(ATTR_DISCHARGE_LIMIT): _PCT,
        vol.Optional(ATTR_CHARGE_LIMIT): _PCT,
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
        changes: dict[str, Any] = {}
        if ATTR_CONTROL_MODE in call.data:
            changes["control_mode"] = CONTROL_MODE_OPTIONS[call.data[ATTR_CONTROL_MODE]]
        if ATTR_DISCHARGE_LIMIT in call.data:
            changes["discharge_rate"] = coordinator.pct_to_rate(call.data[ATTR_DISCHARGE_LIMIT])
        if ATTR_CHARGE_LIMIT in call.data:
            changes["charge_rate"] = coordinator.pct_to_rate(call.data[ATTR_CHARGE_LIMIT])
        if ATTR_MIN_RESERVE in call.data:
            changes["min_reserve"] = coordinator.pct_to_reserve(call.data[ATTR_MIN_RESERVE])
        if ATTR_REVERT_TIMEOUT in call.data:
            changes["revert_timeout"] = call.data[ATTR_REVERT_TIMEOUT]
        if ATTR_GRID_CHARGING in call.data:
            changes["grid_charging"] = int(call.data[ATTR_GRID_CHARGING])
        await coordinator.async_set_target(**changes)

    hass.services.async_register(DOMAIN, SERVICE_SET_SETPOINTS, set_setpoints, schema=SCHEMA)

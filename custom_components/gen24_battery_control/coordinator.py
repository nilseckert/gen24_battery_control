"""Coordinator holding the requested setpoints and the inverter state."""

from __future__ import annotations

import logging
from time import monotonic
from dataclasses import replace
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ENFORCE,
    CONF_SCAN_INTERVAL,
    DEFAULT_ENFORCE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    KEEPALIVE_FRACTION,
    KEEPALIVE_MIN_SECONDS,
)
from .controller import SetpointsNotApplied, StorageController
from .registers import (
    ControlMode,
    InvalidSetpoints,
    Setpoints,
    StorageState,
    pct_to_raw,
    raw_to_pct,
)
from .transport import ModbusTcpTransport, TransportError

_LOGGER = logging.getLogger(__name__)

type Gen24ConfigEntry = ConfigEntry[Gen24Coordinator]


class Gen24Coordinator(DataUpdateCoordinator[StorageState]):
    """Polls model 124, keeps the watchdog alive and applies setpoints.

    ``target`` is what Home Assistant wants, ``data`` is what the inverter
    reports. Without "enforce", changes made by other Modbus clients are
    adopted as the new target; with it, they are overwritten.
    """

    config_entry: Gen24ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: Gen24ConfigEntry,
        controller: StorageController,
        transport: ModbusTcpTransport,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.controller = controller
        self.transport = transport
        self.enforce: bool = entry.options.get(CONF_ENFORCE, DEFAULT_ENFORCE)
        self.target: Setpoints | None = None
        self.in_sync = True
        self._last_write: float | None = None

    @property
    def _issue_id(self) -> str:
        return f"setpoints_not_applied_{self.config_entry.entry_id}"

    def pct_to_rate(self, pct: float) -> int:
        return pct_to_raw(pct, self.data.rate_sf)

    def rate_to_pct(self, raw: int) -> float:
        return raw_to_pct(raw, self.data.rate_sf)

    def pct_to_reserve(self, pct: float) -> int:
        return pct_to_raw(pct, self.data.min_reserve_sf)

    def reserve_to_pct(self, raw: int) -> float:
        return raw_to_pct(raw, self.data.min_reserve_sf)

    async def _async_update_data(self) -> StorageState:
        try:
            state = await self.controller.read_state()
            if self.target is None:
                self.target = state.setpoints
                return state
            if state.setpoints != self.target:
                if self.in_sync and not self.enforce:
                    _LOGGER.info("Adopting setpoints changed by another client: %s", state.setpoints)
                    self.target = state.setpoints
                    return state
                return await self._apply(self.target)
            if self._keepalive_due():
                return await self._apply(self.target, keepalive=True)
        except TransportError as err:
            raise UpdateFailed(f"Communication with inverter failed: {err}") from err
        self._set_sync(True)
        return state

    def _keepalive_due(self) -> bool:
        assert self.target is not None
        if self.target.control_mode == ControlMode.AUTO or not self.target.revert_timeout:
            return False
        if self._last_write is None:
            return True
        interval = max(self.target.revert_timeout * KEEPALIVE_FRACTION, KEEPALIVE_MIN_SECONDS)
        return monotonic() - self._last_write >= interval

    async def _apply(self, target: Setpoints, *, keepalive: bool = False) -> StorageState:
        try:
            state = await self.controller.apply(target, keepalive=keepalive)
        except SetpointsNotApplied as err:
            _LOGGER.error("Inverter did not accept setpoints: %s", err)
            self._set_sync(False, err)
            return await self.controller.read_state()
        self._last_write = monotonic()
        self._set_sync(True)
        return state

    async def async_set_target(self, **changes: Any) -> None:
        """Request new setpoints (partial update) and apply them immediately."""
        target = replace(self.target or self.data.setpoints, **changes)
        try:
            target.validate()
        except InvalidSetpoints as err:
            raise ServiceValidationError(str(err)) from err
        self.target = target
        try:
            state = await self._apply(target)
        except TransportError as err:
            raise HomeAssistantError(f"Communication with inverter failed: {err}") from err
        self.async_set_updated_data(state)
        if not self.in_sync:
            raise HomeAssistantError(
                f"Inverter did not accept the setpoints, it reports {state.setpoints}"
            )

    def _set_sync(self, ok: bool, err: SetpointsNotApplied | None = None) -> None:
        if ok and not self.in_sync:
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)
        elif not ok and err is not None:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="setpoints_not_applied",
                translation_placeholders={
                    "title": self.config_entry.title,
                    "target": str(err.target),
                    "actual": str(err.actual),
                },
            )
        self.in_sync = ok

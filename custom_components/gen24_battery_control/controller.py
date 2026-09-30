"""Storage controller: ordered writes with read-back verification.

No Home Assistant imports so it can be unit tested with a fake transport.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

from .errors import WriteRejected
from .registers import (
    MODEL_COMMON,
    MODEL_END,
    MODEL_STORAGE,
    MODEL_STORAGE_LEN,
    SUNSPEC_BASE,
    SUNSPEC_MARKER,
    Setpoints,
    StorageState,
    decode_storage,
    decode_string,
    plan_writes,
)

_LOGGER = logging.getLogger(__name__)

MAX_MODELS = 50


class Transport(Protocol):
    """Minimal Modbus transport."""

    async def read(self, address: int, count: int) -> list[int]:
        """Read holding registers."""

    async def write(self, address: int, value: int) -> None:
        """Write a single holding register."""


class NotSunSpecError(Exception):
    """Device does not expose a SunSpec map."""


class ModelNotFoundError(Exception):
    """Model 124 is not present (no battery or wrong device id)."""


class SetpointsNotApplied(Exception):
    """The inverter did not accept the requested setpoints."""

    def __init__(self, target: Setpoints, actual: Setpoints) -> None:
        super().__init__(f"requested {target}, inverter reports {actual}")
        self.target = target
        self.actual = actual


@dataclass(frozen=True)
class DeviceInfo:
    """Common model (1) information."""

    manufacturer: str
    model: str
    version: str
    serial: str


async def find_models(transport: Transport) -> dict[int, int]:
    """Walk the SunSpec model chain; return {model id: data start address}."""
    if tuple(await transport.read(SUNSPEC_BASE, 2)) != SUNSPEC_MARKER:
        raise NotSunSpecError
    models: dict[int, int] = {}
    address = SUNSPEC_BASE + 2
    for _ in range(MAX_MODELS):
        model_id, length = await transport.read(address, 2)
        if model_id == MODEL_END:
            break
        models.setdefault(model_id, address + 2)
        address += 2 + length
    return models


async def read_device_info(transport: Transport, common_base: int) -> DeviceInfo:
    """Read manufacturer, model, version and serial from model 1."""
    regs = await transport.read(common_base, 64)
    return DeviceInfo(
        manufacturer=decode_string(regs[0:16]),
        model=decode_string(regs[16:32]),
        version=decode_string(regs[40:48]),
        serial=decode_string(regs[48:64]),
    )


async def discover(transport: Transport) -> tuple[int, DeviceInfo]:
    """Return the model 124 base address and device info."""
    models = await find_models(transport)
    if MODEL_STORAGE not in models:
        raise ModelNotFoundError
    info = await read_device_info(transport, models[MODEL_COMMON]) if MODEL_COMMON in models else DeviceInfo("Fronius", "Gen24", "", "")
    return models[MODEL_STORAGE], info


class StorageController:
    """Reads model 124 and applies setpoints safely."""

    def __init__(
        self,
        transport: Transport,
        base: int,
        *,
        attempts: int = 3,
        verify_delay: float = 1.0,
    ) -> None:
        self._transport = transport
        self._base = base
        self._attempts = attempts
        self._verify_delay = verify_delay
        self._lock = asyncio.Lock()

    async def read_state(self) -> StorageState:
        """Read and decode the model 124 block."""
        async with self._lock:
            return await self._read()

    async def _read(self) -> StorageState:
        return decode_storage(await self._transport.read(self._base, MODEL_STORAGE_LEN))

    async def apply(self, target: Setpoints, *, keepalive: bool = False) -> StorageState:
        """Write target, verify by reading back, retry on mismatch.

        Raises SetpointsNotApplied if the inverter still reports different
        values after all attempts.
        """
        target.validate()
        async with self._lock:
            state = await self._read()
            for attempt in range(1, self._attempts + 1):
                writes = plan_writes(state.setpoints, target, self._base, keepalive=keepalive)
                for address, value in writes:
                    _LOGGER.debug("write %s = %s", address, value)
                    try:
                        await self._transport.write(address, value)
                    except WriteRejected as err:
                        # Stop this attempt; the read-back below decides what happened
                        _LOGGER.warning("Attempt %s/%s: %s", attempt, self._attempts, err)
                        break
                if writes and self._verify_delay:
                    await asyncio.sleep(self._verify_delay)
                state = await self._read()
                if state.setpoints == target:
                    return state
                _LOGGER.warning(
                    "Attempt %s/%s: inverter reports %s, expected %s",
                    attempt,
                    self._attempts,
                    state.setpoints,
                    target,
                )
                keepalive = False
            raise SetpointsNotApplied(target, state.setpoints)

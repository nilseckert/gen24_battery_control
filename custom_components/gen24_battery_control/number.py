"""Numbers for the requested limits and grid operation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import Gen24ConfigEntry, Gen24Coordinator
from .entity import Gen24Entity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class Gen24NumberDescription(NumberEntityDescription):
    value_fn: Callable[[Gen24Coordinator], float | None]
    changes_fn: Callable[[Gen24Coordinator, float], dict[str, Any]]
    # Maximum derived from the inverter (WChaMax), overrides native_max_value
    max_fn: Callable[[Gen24Coordinator], float | None] | None = None


def _power(key: str, value_fn, changes_fn) -> Gen24NumberDescription:
    return Gen24NumberDescription(
        key=key,
        translation_key=key,
        device_class=NumberDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=0,
        native_step=1,
        mode=NumberMode.BOX,
        max_fn=lambda c: c.max_power,
        value_fn=value_fn,
        changes_fn=changes_fn,
    )


NUMBERS: tuple[Gen24NumberDescription, ...] = (
    Gen24NumberDescription(
        key="discharge_limit",
        translation_key="discharge_limit",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.BOX,
        value_fn=lambda c: c.rate_to_pct(c.limit_part(c.target.discharge_rate)),
        changes_fn=lambda c, v: c.discharge_limit_changes(c.pct_to_rate(v)),
    ),
    Gen24NumberDescription(
        key="charge_limit",
        translation_key="charge_limit",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.BOX,
        value_fn=lambda c: c.rate_to_pct(c.limit_part(c.target.charge_rate)),
        changes_fn=lambda c, v: c.charge_limit_changes(c.pct_to_rate(v)),
    ),
    _power(
        "discharge_power_limit",
        lambda c: c.rate_to_watt(c.limit_part(c.target.discharge_rate)),
        lambda c, v: c.discharge_limit_changes(c.watt_to_rate(v)),
    ),
    _power(
        "charge_power_limit",
        lambda c: c.rate_to_watt(c.limit_part(c.target.charge_rate)),
        lambda c, v: c.charge_limit_changes(c.watt_to_rate(v)),
    ),
    _power(
        "grid_charge_power",
        lambda c: c.rate_to_watt(c.grid_part(c.target.discharge_rate)),
        lambda c, v: c.grid_charge_changes(v),
    ),
    _power(
        "grid_discharge_power",
        lambda c: c.rate_to_watt(c.grid_part(c.target.charge_rate)),
        lambda c, v: c.grid_discharge_changes(v),
    ),
    Gen24NumberDescription(
        key="min_reserve",
        translation_key="min_reserve",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.BOX,
        value_fn=lambda c: c.reserve_to_pct(c.target.min_reserve),
        changes_fn=lambda c, v: {"min_reserve": c.pct_to_reserve(v)},
    ),
    Gen24NumberDescription(
        key="revert_timeout",
        translation_key="revert_timeout",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        native_min_value=0,
        native_max_value=3600,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda c: c.target.revert_timeout,
        changes_fn=lambda c, v: {"revert_timeout": int(v)},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Gen24ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(Gen24Number(coordinator, d) for d in NUMBERS)


class Gen24Number(Gen24Entity, NumberEntity):
    entity_description: Gen24NumberDescription

    @property
    def native_value(self) -> float | None:
        return self.entity_description.value_fn(self.coordinator)

    @property
    def native_max_value(self) -> float:
        if (fn := self.entity_description.max_fn) and (limit := fn(self.coordinator)):
            return limit
        return super().native_max_value

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_target(
            **self.entity_description.changes_fn(self.coordinator, value)
        )

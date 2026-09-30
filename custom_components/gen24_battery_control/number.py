"""Numbers for the requested limits."""

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
    # Symmetric range derived from the inverter (e.g. WChaMax), overrides min/max
    range_fn: Callable[[Gen24Coordinator], float | None] | None = None


NUMBERS: tuple[Gen24NumberDescription, ...] = (
    Gen24NumberDescription(
        key="discharge_limit",
        translation_key="discharge_limit",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=-100,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.BOX,
        value_fn=lambda c: c.rate_to_pct(c.target.discharge_rate),
        changes_fn=lambda c, v: {"discharge_rate": c.pct_to_rate(v)},
    ),
    Gen24NumberDescription(
        key="charge_limit",
        translation_key="charge_limit",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=-100,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.BOX,
        value_fn=lambda c: c.rate_to_pct(c.target.charge_rate),
        changes_fn=lambda c, v: {"charge_rate": c.pct_to_rate(v)},
    ),
    Gen24NumberDescription(
        key="discharge_power_limit",
        translation_key="discharge_power_limit",
        device_class=NumberDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        native_step=0.01,
        mode=NumberMode.BOX,
        range_fn=lambda c: c.max_power_kw,
        value_fn=lambda c: c.rate_to_kw(c.target.discharge_rate),
        changes_fn=lambda c, v: {"discharge_rate": c.kw_to_rate(v)},
    ),
    Gen24NumberDescription(
        key="charge_power_limit",
        translation_key="charge_power_limit",
        device_class=NumberDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        native_step=0.01,
        mode=NumberMode.BOX,
        range_fn=lambda c: c.max_power_kw,
        value_fn=lambda c: c.rate_to_kw(c.target.charge_rate),
        changes_fn=lambda c, v: {"charge_rate": c.kw_to_rate(v)},
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
    def native_min_value(self) -> float:
        if (fn := self.entity_description.range_fn) and (limit := fn(self.coordinator)):
            return -limit
        return super().native_min_value

    @property
    def native_max_value(self) -> float:
        if (fn := self.entity_description.range_fn) and (limit := fn(self.coordinator)):
            return limit
        return super().native_max_value

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_target(
            **self.entity_description.changes_fn(self.coordinator, value)
        )

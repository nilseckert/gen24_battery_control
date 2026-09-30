"""Switch for charging the battery from the grid (ChaGriSet)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import Gen24ConfigEntry
from .entity import Gen24Entity

PARALLEL_UPDATES = 1

DESCRIPTION = SwitchEntityDescription(
    key="grid_charging",
    translation_key="grid_charging",
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Gen24ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([Gen24GridChargingSwitch(entry.runtime_data, DESCRIPTION)])


class Gen24GridChargingSwitch(Gen24Entity, SwitchEntity):
    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.target.grid_charging)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_target(grid_charging=1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_target(grid_charging=0)

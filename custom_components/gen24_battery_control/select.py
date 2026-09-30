"""Select for the requested storage control mode."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONTROL_MODE_NAMES, CONTROL_MODE_OPTIONS
from .coordinator import Gen24ConfigEntry
from .entity import Gen24Entity

PARALLEL_UPDATES = 1

DESCRIPTION = SelectEntityDescription(
    key="control_mode",
    translation_key="control_mode",
    options=list(CONTROL_MODE_OPTIONS),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Gen24ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([Gen24ControlModeSelect(entry.runtime_data, DESCRIPTION)])


class Gen24ControlModeSelect(Gen24Entity, SelectEntity):
    @property
    def current_option(self) -> str | None:
        return CONTROL_MODE_NAMES.get(self.coordinator.target.control_mode)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_target(control_mode=CONTROL_MODE_OPTIONS[option])

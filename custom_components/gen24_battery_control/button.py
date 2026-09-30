"""Button returning battery control to the inverter."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import Gen24ConfigEntry
from .entity import Gen24Entity
from .registers import ControlMode

PARALLEL_UPDATES = 1

DESCRIPTION = ButtonEntityDescription(key="reset", translation_key="reset")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Gen24ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([Gen24ResetButton(entry.runtime_data, DESCRIPTION)])


class Gen24ResetButton(Gen24Entity, ButtonEntity):
    """Set AUTO mode and 100 % / 100 % rates."""

    async def async_press(self) -> None:
        c = self.coordinator
        await c.async_set_target(
            control_mode=ControlMode.AUTO,
            discharge_rate=c.pct_to_rate(100),
            charge_rate=c.pct_to_rate(100),
        )

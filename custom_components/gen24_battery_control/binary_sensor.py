"""Binary sensor signalling that the inverter did not accept the setpoints."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import Gen24ConfigEntry
from .entity import Gen24Entity

PARALLEL_UPDATES = 0

DESCRIPTION = BinarySensorEntityDescription(
    key="setpoints_not_applied",
    translation_key="setpoints_not_applied",
    device_class=BinarySensorDeviceClass.PROBLEM,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Gen24ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([Gen24SyncSensor(entry.runtime_data, DESCRIPTION)])


class Gen24SyncSensor(Gen24Entity, BinarySensorEntity):
    @property
    def is_on(self) -> bool:
        return not self.coordinator.in_sync

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {
            "requested": str(self.coordinator.target),
            "reported": str(self.coordinator.data.setpoints),
        }

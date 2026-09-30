"""Base entity."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MANUFACTURER, CONF_MODEL, CONF_SERIAL, CONF_SW_VERSION, DOMAIN
from .coordinator import Gen24Coordinator


class Gen24Entity(CoordinatorEntity[Gen24Coordinator]):
    """Entity bound to one Gen24 config entry."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: Gen24Coordinator, description: EntityDescription) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name=entry.title,
            manufacturer=entry.data.get(CONF_MANUFACTURER) or "Fronius",
            model=entry.data.get(CONF_MODEL) or "Gen24",
            serial_number=entry.data.get(CONF_SERIAL) or None,
            sw_version=entry.data.get(CONF_SW_VERSION) or None,
        )

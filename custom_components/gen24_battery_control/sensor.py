"""Sensors reporting what the inverter actually does."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONTROL_MODE_NAMES
from .coordinator import Gen24ConfigEntry
from .entity import Gen24Entity
from .registers import ChargeStatus, StorageState

PARALLEL_UPDATES = 0

CHARGE_STATUS_OPTIONS = [s.name.lower() for s in ChargeStatus]


@dataclass(frozen=True, kw_only=True)
class Gen24SensorDescription(SensorEntityDescription):
    value_fn: Callable[[StorageState], float | str | None]


def _charge_status(state: StorageState) -> str | None:
    try:
        return ChargeStatus(state.charge_status).name.lower()
    except ValueError:
        return None


SENSORS: tuple[Gen24SensorDescription, ...] = (
    Gen24SensorDescription(
        key="state_of_charge",
        translation_key="state_of_charge",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda s: s.soc_pct,
    ),
    Gen24SensorDescription(
        key="charge_status",
        translation_key="charge_status",
        device_class=SensorDeviceClass.ENUM,
        options=CHARGE_STATUS_OPTIONS,
        value_fn=_charge_status,
    ),
    Gen24SensorDescription(
        key="active_control_mode",
        translation_key="active_control_mode",
        device_class=SensorDeviceClass.ENUM,
        options=list(CONTROL_MODE_NAMES.values()),
        value_fn=lambda s: CONTROL_MODE_NAMES.get(s.control_mode),
    ),
    Gen24SensorDescription(
        key="active_discharge_rate",
        translation_key="active_discharge_rate",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.discharge_rate_pct,
    ),
    Gen24SensorDescription(
        key="active_charge_rate",
        translation_key="active_charge_rate",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.charge_rate_pct,
    ),
    Gen24SensorDescription(
        key="active_discharge_power_limit",
        translation_key="active_discharge_power_limit",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.rate_to_watt(s.discharge_rate_pct),
    ),
    Gen24SensorDescription(
        key="active_charge_power_limit",
        translation_key="active_charge_power_limit",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.rate_to_watt(s.charge_rate_pct),
    ),
    Gen24SensorDescription(
        key="max_charge_power",
        translation_key="max_charge_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.max_charge_power,
    ),
    Gen24SensorDescription(
        key="active_min_reserve",
        translation_key="active_min_reserve",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.min_reserve_pct,
    ),
    Gen24SensorDescription(
        key="active_revert_timeout",
        translation_key="active_revert_timeout",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.revert_timeout,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Gen24ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(Gen24Sensor(coordinator, d) for d in SENSORS)


class Gen24Sensor(Gen24Entity, SensorEntity):
    entity_description: Gen24SensorDescription

    @property
    def native_value(self) -> float | str | None:
        return self.entity_description.value_fn(self.coordinator.data)

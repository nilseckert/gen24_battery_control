"""Home Assistant integration tests with a simulated Gen24."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import voluptuous as vol
from fake_gen24 import BASE, FakeGen24
from g24.registers import CHAGRISET, INWRTE, OUTWRTE, STORCTL_MOD, to_int16
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

# Import before the hass fixture mounts its own config dir as custom_components
import custom_components.gen24_battery_control.config_flow  # noqa: F401
from custom_components.gen24_battery_control.errors import WriteRejected

DOMAIN = "gen24_battery_control"
PKG = "custom_components.gen24_battery_control"
SERIAL = "12345678"


class FakeTransport(FakeGen24):
    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def device():
    dev = FakeTransport()
    with (
        patch(f"{PKG}.ModbusTcpTransport", return_value=dev),
        patch(f"{PKG}.config_flow.ModbusTcpTransport", return_value=dev),
        patch(f"{PKG}.VERIFY_DELAY", 0),
    ):
        yield dev


async def setup(hass: HomeAssistant, options: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Gen24",
        unique_id=SERIAL,
        data={"host": "1.2.3.4", "port": 502, "unit_id": 1, "storage_base": BASE, "serial": SERIAL},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def eid(hass: HomeAssistant, platform: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{SERIAL}_{key}")
    assert entity_id, key
    return entity_id


async def test_config_flow(hass: HomeAssistant, device) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "1.2.3.4", "port": 502, "unit_id": 1}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Primo GEN24 6.0"
    assert result["data"]["storage_base"] == BASE
    assert result["result"].unique_id == SERIAL


async def test_config_flow_no_storage(hass: HomeAssistant, device) -> None:
    device.regs[40343] = 0xFFFF
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "1.2.3.4", "port": 502, "unit_id": 1}
    )
    assert result["errors"] == {"base": "no_storage"}


async def test_entities(hass: HomeAssistant, device) -> None:
    await setup(hass)
    assert hass.states.get(eid(hass, "sensor", "state_of_charge")).state == "80.3"
    assert hass.states.get(eid(hass, "sensor", "charge_status")).state == "holding"
    assert hass.states.get(eid(hass, "sensor", "active_charge_power_limit")).state == "0"
    assert hass.states.get(eid(hass, "select", "control_mode")).state == "limit_both"
    assert hass.states.get(eid(hass, "number", "discharge_limit")).state == "100.0"
    assert hass.states.get(eid(hass, "number", "charge_limit")).state == "0.0"
    assert hass.states.get(eid(hass, "switch", "grid_charging")).state == "on"
    assert hass.states.get(eid(hass, "binary_sensor", "setpoints_not_applied")).state == "off"
    assert device.writes == []


async def test_service_swaps_rates_in_safe_order(hass: HomeAssistant, device) -> None:
    await setup(hass)
    device.writes.clear()
    await hass.services.async_call(
        DOMAIN, "set_setpoints", {"discharge_limit": 0, "charge_limit": 100}, blocking=True
    )
    assert device.writes == [(BASE + INWRTE, 10000), (BASE + OUTWRTE, 0)]
    assert hass.states.get(eid(hass, "sensor", "active_discharge_rate")).state == "0.0"
    assert hass.states.get(eid(hass, "sensor", "active_charge_rate")).state == "100.0"


async def test_zero_zero_accepted(hass: HomeAssistant, device) -> None:
    await setup(hass)
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": eid(hass, "number", "discharge_limit"), "value": 0},
        blocking=True,
    )
    assert (device.regs[BASE + OUTWRTE], device.regs[BASE + INWRTE]) == (0, 0)
    assert hass.states.get(eid(hass, "binary_sensor", "setpoints_not_applied")).state == "off"


async def test_zero_zero_rejected_by_firmware(hass: HomeAssistant, device) -> None:
    entry = await setup(hass)
    device.reject_zero_zero = True
    device.reject_exc = WriteRejected
    with pytest.raises(HomeAssistantError, match="did not accept"):
        await hass.services.async_call(
            "number", "set_value",
            {"entity_id": eid(hass, "number", "discharge_limit"), "value": 0},
            blocking=True,
        )
    assert device.regs[BASE + OUTWRTE] == 10000
    assert hass.states.get(eid(hass, "binary_sensor", "setpoints_not_applied")).state == "on"
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"setpoints_not_applied_{entry.entry_id}")


async def test_not_applied_creates_issue_and_recovers(hass: HomeAssistant, device) -> None:
    entry = await setup(hass)
    device.ignore_writes_to.add(BASE + OUTWRTE)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "number", "set_value",
            {"entity_id": eid(hass, "number", "discharge_limit"), "value": 50},
            blocking=True,
        )
    assert hass.states.get(eid(hass, "binary_sensor", "setpoints_not_applied")).state == "on"
    issue_id = f"setpoints_not_applied_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id)

    # Target is kept and retried on the next poll, not replaced by the actual value
    device.ignore_writes_to.clear()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(eid(hass, "sensor", "active_discharge_rate")).state == "50.0"
    assert hass.states.get(eid(hass, "binary_sensor", "setpoints_not_applied")).state == "off"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_external_change_adopted_without_enforce(hass: HomeAssistant, device) -> None:
    entry = await setup(hass)
    device.regs[BASE + INWRTE] = 5000
    device.writes.clear()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(eid(hass, "number", "charge_limit")).state == "50.0"
    assert (BASE + INWRTE, 0) not in device.writes


async def test_external_change_overwritten_with_enforce(hass: HomeAssistant, device) -> None:
    entry = await setup(hass, {"enforce": True, "scan_interval": 5})
    device.regs[BASE + INWRTE] = 5000
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert device.regs[BASE + INWRTE] == 0
    assert hass.states.get(eid(hass, "number", "charge_limit")).state == "0.0"


async def test_keepalive_rewrites_rates(hass: HomeAssistant, device) -> None:
    entry = await setup(hass)
    # host booted recently: monotonic clock is still smaller than the interval
    with patch(f"{PKG}.coordinator.monotonic", return_value=10.0):
        device.writes.clear()
        await entry.runtime_data.async_refresh()
        assert [a - BASE for a, _ in device.writes] == [OUTWRTE, INWRTE, STORCTL_MOD]
        # not due again right away
        device.writes.clear()
        await entry.runtime_data.async_refresh()
        assert device.writes == []
    # due again after a third of the revert timeout (600 s)
    with patch(f"{PKG}.coordinator.monotonic", return_value=210.0):
        await entry.runtime_data.async_refresh()
        assert [a - BASE for a, _ in device.writes] == [OUTWRTE, INWRTE, STORCTL_MOD]


async def test_reset_button(hass: HomeAssistant, device) -> None:
    await setup(hass)
    await hass.services.async_call(
        "button", "press", {"entity_id": eid(hass, "button", "reset")}, blocking=True
    )
    assert device.regs[BASE + STORCTL_MOD] == 0
    assert device.regs[BASE + OUTWRTE] == 10000
    assert device.regs[BASE + INWRTE] == 10000
    assert hass.states.get(eid(hass, "select", "control_mode")).state == "auto"


async def test_unload(hass: HomeAssistant, device) -> None:
    entry = await setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_power_limit_entities(hass: HomeAssistant, device) -> None:
    await setup(hass)
    state = hass.states.get(eid(hass, "number", "discharge_power_limit"))
    assert state.state == "12800"
    assert state.attributes["unit_of_measurement"] == "W"
    assert state.attributes["min"] == 0
    assert state.attributes["max"] == 12800
    assert hass.states.get(eid(hass, "number", "charge_power_limit")).state == "0"
    assert hass.states.get(eid(hass, "number", "grid_charge_power")).state == "0"
    assert hass.states.get(eid(hass, "number", "grid_discharge_power")).state == "0"


async def test_set_power_limit_via_number(hass: HomeAssistant, device) -> None:
    await setup(hass)
    await set_number(hass, "charge_power_limit", 3200)
    assert device.regs[BASE + INWRTE] == 2500  # 3200 W of 12800 W = 25 %
    assert hass.states.get(eid(hass, "number", "charge_limit")).state == "25.0"


async def test_set_power_limit_via_service(hass: HomeAssistant, device) -> None:
    await setup(hass)
    await hass.services.async_call(
        DOMAIN, "set_setpoints",
        {"discharge_power_limit": 6400, "charge_power_limit": 1280},
        blocking=True,
    )
    assert device.regs[BASE + OUTWRTE] == 5000
    assert device.regs[BASE + INWRTE] == 1000
    assert hass.states.get(eid(hass, "sensor", "active_discharge_power_limit")).state == "6400"


async def test_power_limit_above_max_rejected(hass: HomeAssistant, device) -> None:
    await setup(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "set_setpoints", {"discharge_power_limit": 13000}, blocking=True
        )
    assert device.writes == []


@pytest.mark.parametrize(
    "data",
    [
        {"discharge_limit": 50, "discharge_power_limit": 6400},
        {"discharge_limit": 50, "grid_charge_power": 2000},
        {"charge_power_limit": 1000, "grid_discharge_power": 2000},
    ],
)
async def test_one_value_per_side(hass: HomeAssistant, device, data) -> None:
    await setup(hass)
    with pytest.raises((vol.Invalid, ServiceValidationError)):
        await hass.services.async_call(DOMAIN, "set_setpoints", data, blocking=True)


async def test_negative_percent_rejected(hass: HomeAssistant, device) -> None:
    await setup(hass)
    with pytest.raises((vol.Invalid, ServiceValidationError)):
        await hass.services.async_call(DOMAIN, "set_setpoints", {"charge_limit": -25}, blocking=True)


async def set_number(hass: HomeAssistant, key: str, value: float) -> None:
    await hass.services.async_call(
        "number", "set_value", {"entity_id": eid(hass, "number", key), "value": value}, blocking=True
    )


def num(hass: HomeAssistant, key: str) -> str:
    return hass.states.get(eid(hass, "number", key)).state


async def test_grid_discharge(hass: HomeAssistant, device) -> None:
    await setup(hass)
    await set_number(hass, "grid_discharge_power", 2000)
    assert to_int16(device.regs[BASE + INWRTE]) == -1562  # 2000 W of 12800 W
    assert device.regs[BASE + STORCTL_MOD] == 3
    # charge limit shows 0, the grid power shows the forced discharge
    assert num(hass, "charge_limit") == "0.0"
    assert num(hass, "charge_power_limit") == "0"
    assert num(hass, "grid_discharge_power") == "1999"
    assert hass.states.get(eid(hass, "sensor", "active_grid_discharge_power")).state == "1999"
    assert hass.states.get(eid(hass, "sensor", "active_charge_power_limit")).state == "0"
    # 0 ends it: charging is allowed again
    await set_number(hass, "grid_discharge_power", 0)
    assert device.regs[BASE + INWRTE] == 10000
    assert num(hass, "grid_discharge_power") == "0"


async def test_grid_charge_switches_mode_first(hass: HomeAssistant, device) -> None:
    await setup(hass)
    device.writes.clear()
    await set_number(hass, "grid_charge_power", 3000)
    # mode 2 before the negative discharge rate (rejected in mode 3)
    assert device.writes[0] == (BASE + STORCTL_MOD, 2)
    assert to_int16(device.regs[BASE + OUTWRTE]) == -2344
    assert device.regs[BASE + CHAGRISET] == 1
    assert num(hass, "discharge_limit") == "0.0"
    assert num(hass, "discharge_power_limit") == "0"
    assert num(hass, "grid_charge_power") == "3000"
    assert hass.states.get(eid(hass, "select", "control_mode")).state == "limit_discharge"
    # ending it restores discharging and both limits
    await set_number(hass, "grid_charge_power", 0)
    assert device.regs[BASE + OUTWRTE] == 10000
    assert device.regs[BASE + STORCTL_MOD] == 3


async def test_grid_modes_are_exclusive(hass: HomeAssistant, device) -> None:
    await setup(hass)
    await set_number(hass, "grid_charge_power", 3000)
    await set_number(hass, "grid_discharge_power", 2000)
    assert num(hass, "grid_charge_power") == "0"
    assert num(hass, "grid_discharge_power") == "1999"
    assert device.regs[BASE + STORCTL_MOD] == 3
    assert device.regs[BASE + OUTWRTE] == 10000
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "set_setpoints",
            {"grid_charge_power": 1000, "grid_discharge_power": 1000},
            blocking=True,
        )


async def test_discharge_limit_ends_grid_charge(hass: HomeAssistant, device) -> None:
    await setup(hass)
    await set_number(hass, "grid_charge_power", 3000)
    await set_number(hass, "discharge_limit", 50)
    assert device.regs[BASE + OUTWRTE] == 5000
    assert device.regs[BASE + STORCTL_MOD] == 3
    assert num(hass, "grid_charge_power") == "0"


async def test_grid_charge_service_rejects_conflicting_mode(hass: HomeAssistant, device) -> None:
    await setup(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "set_setpoints",
            {"control_mode": "limit_both", "grid_charge_power": 1000},
            blocking=True,
        )
    assert device.writes == []

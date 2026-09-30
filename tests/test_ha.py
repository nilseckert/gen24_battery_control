"""Home Assistant integration tests with a simulated Gen24."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fake_gen24 import BASE, FakeGen24
from g24.registers import INWRTE, OUTWRTE, STORCTL_MOD, from_int16
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

# Import before the hass fixture mounts its own config dir as custom_components
import custom_components.gen24_battery_control.config_flow  # noqa: F401

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


async def test_zero_zero_rejected(hass: HomeAssistant, device) -> None:
    await setup(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "number", "set_value",
            {"entity_id": eid(hass, "number", "discharge_limit"), "value": 0},
            blocking=True,
        )
    assert device.writes == []


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


async def test_negative_charge_limit(hass: HomeAssistant, device) -> None:
    await setup(hass)
    await hass.services.async_call(
        DOMAIN, "set_setpoints", {"charge_limit": -25}, blocking=True
    )
    assert device.regs[BASE + INWRTE] == from_int16(-2500)


async def test_unload(hass: HomeAssistant, device) -> None:
    entry = await setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)

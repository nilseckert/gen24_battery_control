"""Tests for discovery and verified writes."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from fake_gen24 import BASE, FakeGen24
from g24.controller import (
    ModelNotFoundError,
    NotSunSpecError,
    SetpointsNotApplied,
    StorageController,
    discover,
)
from g24.registers import INWRTE, OUTWRTE, ControlMode


def run(coro):
    return asyncio.run(coro)


def test_discover() -> None:
    base, info = run(discover(FakeGen24()))
    assert base == BASE
    assert info.manufacturer == "Fronius"
    assert info.model == "Primo GEN24 6.0"
    assert info.version == "1.38.6-1"
    assert info.serial == "12345678"


def test_discover_not_sunspec() -> None:
    dev = FakeGen24()
    dev.regs[40000] = 0
    with pytest.raises(NotSunSpecError):
        run(discover(dev))


def test_discover_without_battery() -> None:
    dev = FakeGen24()
    dev.regs[40343] = 0xFFFF  # chain ends before model 124
    with pytest.raises(ModelNotFoundError):
        run(discover(dev))


def test_apply_transition_accepted_by_firmware() -> None:
    dev = FakeGen24()
    ctl = StorageController(dev, BASE, verify_delay=0)
    current = run(ctl.read_state()).setpoints
    # (100 %, 0 %) -> (0 %, 100 %) would fail with a naive write order
    state = run(ctl.apply(replace(current, discharge_rate=0, charge_rate=10000)))
    assert state.discharge_rate_pct == 0
    assert state.charge_rate_pct == 100
    assert dev.writes == [(BASE + INWRTE, 10000), (BASE + OUTWRTE, 0)]


def test_apply_noop_does_not_write() -> None:
    dev = FakeGen24()
    ctl = StorageController(dev, BASE, verify_delay=0)
    run(ctl.apply(run(ctl.read_state()).setpoints))
    assert dev.writes == []


def test_apply_raises_when_inverter_ignores_write() -> None:
    dev = FakeGen24()
    dev.ignore_writes_to.add(BASE + OUTWRTE)
    ctl = StorageController(dev, BASE, attempts=3, verify_delay=0)
    target = replace(run(ctl.read_state()).setpoints, discharge_rate=2000)
    with pytest.raises(SetpointsNotApplied) as err:
        run(ctl.apply(target))
    assert err.value.actual.discharge_rate == 10000
    assert dev.writes == [(BASE + OUTWRTE, 2000)] * 3


def test_reset_to_auto() -> None:
    dev = FakeGen24()
    ctl = StorageController(dev, BASE, verify_delay=0)
    current = run(ctl.read_state()).setpoints
    target = replace(current, control_mode=ControlMode.AUTO, discharge_rate=10000, charge_rate=10000)
    state = run(ctl.apply(target))
    assert state.control_mode == ControlMode.AUTO
    assert state.charge_rate_pct == 100

"""Tests for register decoding and write planning."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fake_gen24 import BASE, SNAPSHOT
from g24.registers import (
    CHAGRISET,
    INWRTE,
    MINRSVPCT,
    OUTWRTE,
    RVRTTMS,
    STORCTL_MOD,
    ChargeStatus,
    ControlMode,
    InvalidSetpoints,
    Setpoints,
    decode_storage,
    from_int16,
    pct_to_raw,
    plan_writes,
    raw_to_pct,
    to_int16,
)


def sp(dis: int, chg: int, mode: int = ControlMode.LIMIT_BOTH, **kw) -> Setpoints:
    base = dict(min_reserve=500, revert_timeout=600, grid_charging=1)
    base.update(kw)
    return Setpoints(control_mode=mode, discharge_rate=dis, charge_rate=chg, **base)


def test_decode_snapshot() -> None:
    state = decode_storage(SNAPSHOT)
    assert state.max_charge_power == 12800
    assert state.control_mode == ControlMode.LIMIT_BOTH
    assert state.min_reserve_pct == 5.0
    assert state.soc_pct == 80.3
    assert state.charge_status == ChargeStatus.HOLDING
    assert state.discharge_rate_pct == 100.0
    assert state.charge_rate_pct == 0.0
    assert state.revert_timeout == 600
    assert state.grid_charging is True
    assert state.rate_sf == -2
    assert state.rate_to_watt(50) == 6400
    assert state.setpoints == sp(10000, 0)


def test_decode_negative_rate() -> None:
    regs = list(SNAPSHOT)
    regs[INWRTE] = from_int16(-5000)
    assert decode_storage(regs).charge_rate_pct == -50.0


def test_int16_roundtrip() -> None:
    for value in (-32768, -1, 0, 1, 32767):
        assert to_int16(from_int16(value)) == value
    with pytest.raises(InvalidSetpoints):
        from_int16(40000)


def test_pct_conversion() -> None:
    assert pct_to_raw(100, -2) == 10000
    assert pct_to_raw(12.345, -2) == 1234
    assert raw_to_pct(1234, -2) == 12.34


def test_zero_zero_target_allowed() -> None:
    assert plan_writes(sp(10000, 0), sp(0, 0), BASE) == [(BASE + OUTWRTE, 0)]


def test_zero_zero_target_reached_without_zero_zero_intermediate() -> None:
    # (0 %, 50 %) -> (0 %, 0 %) only needs one write; (50 %, 50 %) -> (0, 0)
    # must not pass through a state that is already 0/0 before the last write
    writes = plan_writes(sp(5000, 5000), sp(0, 0), BASE)
    assert [a - BASE for a, _ in writes] == [OUTWRTE, INWRTE]


@pytest.mark.parametrize(
    ("current", "target", "expected_order"),
    [
        # (100 % dis, 0 % chg) -> (0 %, 100 %): charge must be raised first
        ((10000, 0), (0, 10000), [INWRTE, OUTWRTE]),
        # mirror image
        ((0, 10000), (10000, 0), [OUTWRTE, INWRTE]),
        # both non-zero: discharge first
        ((5000, 5000), (2000, 3000), [OUTWRTE, INWRTE]),
    ],
)
def test_rate_order_never_zero_zero(current, target, expected_order) -> None:
    writes = plan_writes(sp(*current), sp(*target), BASE)
    assert [a - BASE for a, _ in writes] == expected_order
    # simulate intermediate states
    dis, chg = current
    for address, value in writes:
        if address == BASE + OUTWRTE:
            dis = to_int16(value)
        else:
            chg = to_int16(value)
        assert (dis, chg) != (0, 0)


def test_only_changed_registers_written() -> None:
    assert plan_writes(sp(10000, 0), sp(10000, 0), BASE) == []
    assert plan_writes(sp(10000, 0), sp(10000, 500), BASE) == [(BASE + INWRTE, 500)]


def test_enter_limit_mode_writes_rates_before_mode() -> None:
    writes = plan_writes(sp(10000, 10000, ControlMode.AUTO), sp(2000, 0), BASE)
    assert [a - BASE for a, _ in writes] == [OUTWRTE, INWRTE, STORCTL_MOD]


def test_return_to_auto_writes_mode_first() -> None:
    writes = plan_writes(sp(2000, 0), sp(10000, 10000, ControlMode.AUTO), BASE)
    assert [a - BASE for a, _ in writes] == [STORCTL_MOD, OUTWRTE, INWRTE]


def test_revert_timeout_first_other_settings_last() -> None:
    current = sp(10000, 10000, ControlMode.AUTO, revert_timeout=0, min_reserve=500, grid_charging=0)
    target = replace(sp(2000, 10000), revert_timeout=120, min_reserve=1000, grid_charging=1)
    writes = plan_writes(current, target, BASE)
    assert [a - BASE for a, _ in writes] == [RVRTTMS, OUTWRTE, STORCTL_MOD, MINRSVPCT, CHAGRISET]


def test_keepalive_rewrites_rates_and_mode() -> None:
    writes = plan_writes(sp(2000, 0), sp(2000, 0), BASE, keepalive=True)
    assert [a - BASE for a, _ in writes] == [OUTWRTE, INWRTE, STORCTL_MOD]


def test_negative_rate_encoded_as_uint16() -> None:
    writes = plan_writes(sp(10000, 0), sp(10000, -5000), BASE)
    assert writes == [(BASE + INWRTE, 0x10000 - 5000)]


def test_grid_charge_writes_mode_before_negative_discharge_rate() -> None:
    writes = plan_writes(sp(10000, 0), sp(-2000, 10000, ControlMode.LIMIT_DISCHARGE), BASE)
    assert [a - BASE for a, _ in writes] == [STORCTL_MOD, OUTWRTE, INWRTE]


def test_leaving_grid_charge_writes_rates_before_mode() -> None:
    writes = plan_writes(sp(-2000, 10000, ControlMode.LIMIT_DISCHARGE), sp(10000, 0), BASE)
    assert [a - BASE for a, _ in writes] == [OUTWRTE, INWRTE, STORCTL_MOD]

"""SunSpec model 124 (basic storage control) for Fronius Gen24.

Pure logic without Home Assistant imports so it can be unit tested.
Addresses are Modbus PDU addresses as used by pymodbus / the HA modbus
integration (e.g. model 124 data starts at 40345 on a Gen24 in "int + SF" mode).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

SUNSPEC_BASE = 40000
SUNSPEC_MARKER = (0x5375, 0x6E53)  # "SunS"
MODEL_COMMON = 1
MODEL_STORAGE = 124
MODEL_STORAGE_LEN = 24
MODEL_END = 0xFFFF

UINT16_NAN = 0xFFFF
INT16_NAN = 0x8000

# Offsets relative to the first data register of model 124
WCHAMAX = 0
STORCTL_MOD = 3
MINRSVPCT = 5
CHASTATE = 6
CHAST = 9
OUTWRTE = 10
INWRTE = 11
RVRTTMS = 13
CHAGRISET = 15
WCHAMAX_SF = 16
MINRSVPCT_SF = 19
CHASTATE_SF = 20
INOUTWRTE_SF = 23

# Default scale factors of a Gen24 if the device reports NaN
DEFAULT_PCT_SF = -2


class ControlMode(IntEnum):
    """StorCtl_Mod bitfield: bit 0 = charge limit, bit 1 = discharge limit."""

    AUTO = 0
    LIMIT_CHARGE = 1
    LIMIT_DISCHARGE = 2
    LIMIT_BOTH = 3


class ChargeStatus(IntEnum):
    """ChaSt enumeration."""

    OFF = 1
    EMPTY = 2
    DISCHARGING = 3
    CHARGING = 4
    FULL = 5
    HOLDING = 6
    TESTING = 7


class InvalidSetpoints(ValueError):
    """Raised for setpoints the inverter would reject."""


def to_int16(value: int) -> int:
    """Convert a raw uint16 register value to a signed int16."""
    return value - 0x10000 if value >= 0x8000 else value


def from_int16(value: int) -> int:
    """Convert a signed int16 to its raw uint16 register representation."""
    if not -0x8000 <= value <= 0x7FFF:
        raise InvalidSetpoints(f"{value} does not fit into int16")
    return value & 0xFFFF


def scale_factor(raw: int, default: int = 0) -> int:
    """Decode a sunssf register, falling back to default on NaN."""
    return default if raw == INT16_NAN else to_int16(raw)


def pct_to_raw(pct: float, sf: int) -> int:
    """Convert a percentage to the raw register value for scale factor sf."""
    return round(pct / 10**sf)


def raw_to_pct(raw: int, sf: int) -> float:
    """Convert a raw register value to a percentage for scale factor sf."""
    return round(raw * 10**sf, max(0, -sf))


def decode_string(registers: list[int]) -> str:
    """Decode a SunSpec string (two ASCII chars per register)."""
    data = b"".join(r.to_bytes(2, "big") for r in registers)
    return data.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()


@dataclass(frozen=True)
class Setpoints:
    """Writable part of model 124 as raw register values.

    Rates are signed (int16) raw values, e.g. 10000 = 100 % with SF -2.
    """

    control_mode: int
    discharge_rate: int  # OutWRte
    charge_rate: int  # InWRte
    min_reserve: int  # MinRsvPct
    revert_timeout: int  # InOutWRte_RvrtTms in seconds, 0 = disabled
    grid_charging: int  # ChaGriSet, 0 = PV only, 1 = grid allowed

    def validate(self) -> None:
        """Raise InvalidSetpoints for values outside the register ranges."""
        if self.control_mode not in tuple(ControlMode):
            raise InvalidSetpoints(f"invalid control mode {self.control_mode}")
        for name in ("discharge_rate", "charge_rate"):
            from_int16(getattr(self, name))
        for name in ("min_reserve", "revert_timeout"):
            if not 0 <= getattr(self, name) < UINT16_NAN:
                raise InvalidSetpoints(f"{name} out of range")
        if self.grid_charging not in (0, 1):
            raise InvalidSetpoints("grid_charging must be 0 or 1")


def is_zero_zero(discharge_rate: int, charge_rate: int) -> bool:
    """Both rates at 0.

    Some firmware reportedly rejects writes that produce this state
    (callifo/fronius_modbus#126). A Symo GEN24 10.0 with firmware 1.41.11-1
    accepts it, so it is allowed as a target but avoided as an intermediate.
    """
    return discharge_rate == 0 and charge_rate == 0


@dataclass(frozen=True)
class StorageState:
    """Decoded model 124 block."""

    raw: tuple[int, ...]
    max_charge_power: float | None
    control_mode: int
    min_reserve_pct: float | None
    soc_pct: float | None
    charge_status: int | None
    discharge_rate_pct: float
    charge_rate_pct: float
    revert_timeout: int | None
    grid_charging: bool | None
    rate_sf: int
    min_reserve_sf: int

    @property
    def setpoints(self) -> Setpoints:
        """Current writable values as raw setpoints."""
        return Setpoints(
            control_mode=self.raw[STORCTL_MOD],
            discharge_rate=to_int16(self.raw[OUTWRTE]),
            charge_rate=to_int16(self.raw[INWRTE]),
            min_reserve=self.raw[MINRSVPCT],
            revert_timeout=0 if self.raw[RVRTTMS] == UINT16_NAN else self.raw[RVRTTMS],
            grid_charging=self.raw[CHAGRISET],
        )

    def rate_to_watt(self, pct: float) -> float | None:
        """Convert a rate percentage into watt based on WChaMax."""
        if self.max_charge_power is None:
            return None
        return round(self.max_charge_power * pct / 100)


def decode_storage(registers: list[int]) -> StorageState:
    """Decode the 24 data registers of model 124."""
    if len(registers) < MODEL_STORAGE_LEN:
        raise ValueError(f"expected {MODEL_STORAGE_LEN} registers, got {len(registers)}")
    r = tuple(registers[:MODEL_STORAGE_LEN])

    def uint(offset: int, sf_offset: int | None = None, default_sf: int = 0) -> float | None:
        if r[offset] == UINT16_NAN:
            return None
        sf = default_sf if sf_offset is None else scale_factor(r[sf_offset], default_sf)
        return raw_to_pct(r[offset], sf)

    rate_sf = scale_factor(r[INOUTWRTE_SF], DEFAULT_PCT_SF)
    min_reserve_sf = scale_factor(r[MINRSVPCT_SF], DEFAULT_PCT_SF)
    return StorageState(
        raw=r,
        max_charge_power=uint(WCHAMAX, WCHAMAX_SF),
        control_mode=r[STORCTL_MOD],
        min_reserve_pct=uint(MINRSVPCT, MINRSVPCT_SF, DEFAULT_PCT_SF),
        soc_pct=uint(CHASTATE, CHASTATE_SF, DEFAULT_PCT_SF),
        charge_status=None if r[CHAST] == UINT16_NAN else r[CHAST],
        discharge_rate_pct=raw_to_pct(to_int16(r[OUTWRTE]), rate_sf),
        charge_rate_pct=raw_to_pct(to_int16(r[INWRTE]), rate_sf),
        revert_timeout=None if r[RVRTTMS] == UINT16_NAN else r[RVRTTMS],
        grid_charging=None if r[CHAGRISET] == UINT16_NAN else bool(r[CHAGRISET]),
        rate_sf=rate_sf,
        min_reserve_sf=min_reserve_sf,
    )


def plan_writes(
    current: Setpoints, target: Setpoints, base: int, *, keepalive: bool = False
) -> list[tuple[int, int]]:
    """Return the ordered (address, raw value) writes to reach target.

    Ordering rules:
    * The revert timeout is written first so the watchdog is armed before
      any limit becomes active.
    * The rates are written in the order that never produces the
      intermediate state discharge=0 / charge=0 unless it is the target
      (see is_zero_zero).
    * Entering a limiting mode: rates before StorCtl_Mod, so the mode never
      activates with stale rates. Returning to AUTO: StorCtl_Mod first.
    * keepalive rewrites the rates even if unchanged, which restarts the
      inverter's revert timer.
    """
    target.validate()
    writes: list[tuple[int, int]] = []

    if target.revert_timeout != current.revert_timeout:
        writes.append((base + RVRTTMS, target.revert_timeout))

    rate_writes = _plan_rates(current, target, base, keepalive=keepalive)
    mode_changed = target.control_mode != current.control_mode
    mode_write = [(base + STORCTL_MOD, target.control_mode)] if mode_changed or keepalive else []

    if target.control_mode == ControlMode.AUTO:
        writes += mode_write + rate_writes
    else:
        writes += rate_writes + mode_write

    if target.min_reserve != current.min_reserve:
        writes.append((base + MINRSVPCT, target.min_reserve))
    if target.grid_charging != current.grid_charging:
        writes.append((base + CHAGRISET, target.grid_charging))
    return writes


def _plan_rates(
    current: Setpoints, target: Setpoints, base: int, *, keepalive: bool
) -> list[tuple[int, int]]:
    dis = (base + OUTWRTE, from_int16(target.discharge_rate))
    chg = (base + INWRTE, from_int16(target.charge_rate))
    dis_changed = keepalive or target.discharge_rate != current.discharge_rate
    chg_changed = keepalive or target.charge_rate != current.charge_rate

    if dis_changed and chg_changed:
        # Intermediate state after the first write: (new discharge, old charge)
        if not is_zero_zero(target.discharge_rate, current.charge_rate):
            return [dis, chg]
        return [chg, dis]
    if dis_changed:
        return [dis]
    if chg_changed:
        return [chg]
    return []

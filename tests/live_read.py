"""Read-only smoke test against a real inverter: python tests/live_read.py <host>"""

import asyncio
import pathlib
import sys
import types

pkg = types.ModuleType("g24")
pkg.__path__ = [str(pathlib.Path(__file__).parent.parent / "custom_components" / "gen24_battery_control")]
sys.modules["g24"] = pkg

from g24.controller import StorageController, discover  # noqa: E402
from g24.transport import ModbusTcpTransport  # noqa: E402


async def main(host: str) -> None:
    transport = ModbusTcpTransport(host, 502, 1)
    try:
        base, info = await discover(transport)
        print("model 124 base:", base)
        print("device:", info)
        state = await StorageController(transport, base).read_state()
        for field in ("max_charge_power", "control_mode", "soc_pct", "charge_status",
                      "discharge_rate_pct", "charge_rate_pct", "min_reserve_pct",
                      "revert_timeout", "grid_charging"):
            print(f"  {field}: {getattr(state, field)}")
        print("setpoints:", state.setpoints)
    finally:
        transport.close()


asyncio.run(main(sys.argv[1]))

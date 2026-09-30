"""In-memory Gen24 simulating the relevant firmware behaviour."""

from __future__ import annotations

from g24.registers import INWRTE, OUTWRTE, to_int16

BASE = 40345

# Real snapshot of a Gen24 + BYD HVS (model 124 data, 2026-09-30)
SNAPSHOT = [
    12800, 100, 100, 3, 65535, 500, 8030, 65535, 65535, 6, 10000, 0,
    65535, 600, 65535, 1, 0, 0, 32768, 65534, 65534, 32768, 32768, 65534,
]  # fmt: skip


class RejectedWrite(Exception):
    """Simulates ExceptionResponse(3)."""


class FakeGen24:
    """Holds registers; rejects writes that leave both rates at 0."""

    def __init__(self, storage: list[int] | None = None) -> None:
        self.regs: dict[int, int] = {}
        # SunSpec chain: marker, model 1 (len 65), model 124 (len 24), end
        self._put(40000, [0x5375, 0x6E53])
        self._put(40002, [1, 65])
        common = [0] * 65
        for offset, text in ((0, "Fronius"), (16, "Primo GEN24 6.0"), (40, "1.38.6-1"), (48, "12345678")):
            data = text.encode().ljust(32 if offset != 40 else 16, b"\x00")
            for i in range(0, len(data), 2):
                common[offset + i // 2] = int.from_bytes(data[i : i + 2], "big")
        self._put(40004, common)
        self._put(40069, [160, 272])  # some other model in between
        self._put(40071, [0] * 272)
        self._put(40343, [124, 24])
        self._put(BASE, storage or SNAPSHOT)
        self._put(BASE + 24, [0xFFFF, 0])
        self.writes: list[tuple[int, int]] = []
        self.ignore_writes_to: set[int] = set()

    def _put(self, address: int, values: list[int]) -> None:
        for i, value in enumerate(values):
            self.regs[address + i] = value

    async def read(self, address: int, count: int) -> list[int]:
        return [self.regs.get(address + i, 0) for i in range(count)]

    async def write(self, address: int, value: int) -> None:
        self.writes.append((address, value))
        if address in self.ignore_writes_to:
            return
        after = dict(self.regs)
        after[address] = value
        if to_int16(after[BASE + OUTWRTE]) == 0 and to_int16(after[BASE + INWRTE]) == 0:
            raise RejectedWrite(address)
        self.regs = after

"""pymodbus based Modbus TCP transport."""

from __future__ import annotations

import asyncio
import inspect

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

from .errors import TransportError, WriteRejected

__all__ = ["ModbusTcpTransport", "TransportError", "WriteRejected"]


class ModbusTcpTransport:
    """Single shared Modbus TCP connection with automatic reconnect."""

    def __init__(self, host: str, port: int, device_id: int, timeout: float = 5) -> None:
        self._client = AsyncModbusTcpClient(host, port=port, timeout=timeout)
        self._device_id = device_id
        self._lock = asyncio.Lock()
        # pymodbus renamed "slave" to "device_id" in 3.10
        params = inspect.signature(self._client.read_holding_registers).parameters
        self._unit_kw = "device_id" if "device_id" in params else "slave"

    async def _ensure_connected(self) -> None:
        if not self._client.connected and not await self._client.connect():
            raise TransportError("unable to connect")

    async def read(self, address: int, count: int) -> list[int]:
        """Read holding registers."""
        async with self._lock:
            try:
                await self._ensure_connected()
                result = await self._client.read_holding_registers(
                    address, count=count, **{self._unit_kw: self._device_id}
                )
            except (ModbusException, OSError, TimeoutError) as err:
                raise TransportError(str(err)) from err
            if result.isError():
                raise TransportError(f"read {address}+{count} failed: {result}")
            return list(result.registers)

    async def write(self, address: int, value: int) -> None:
        """Write a single holding register (function code 6)."""
        async with self._lock:
            try:
                await self._ensure_connected()
                result = await self._client.write_register(
                    address, value, **{self._unit_kw: self._device_id}
                )
            except (ModbusException, OSError, TimeoutError) as err:
                raise TransportError(str(err)) from err
            if result.isError():
                raise WriteRejected(f"write {address}={value} rejected: {result}")

    def close(self) -> None:
        """Close the connection."""
        self._client.close()

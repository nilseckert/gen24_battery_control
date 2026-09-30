"""Gen24 Battery Control: safe battery control for Fronius Gen24 via SunSpec Modbus."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CONF_STORAGE_BASE, CONF_UNIT_ID, DOMAIN, VERIFY_DELAY
from .controller import StorageController
from .coordinator import Gen24ConfigEntry, Gen24Coordinator
from .services import async_setup_services
from .transport import ModbusTcpTransport

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: Gen24ConfigEntry) -> bool:
    """Set up a Gen24 from a config entry."""
    transport = ModbusTcpTransport(
        entry.data[CONF_HOST], entry.data[CONF_PORT], entry.data[CONF_UNIT_ID]
    )
    controller = StorageController(
        transport, entry.data[CONF_STORAGE_BASE], verify_delay=VERIFY_DELAY
    )
    coordinator = Gen24Coordinator(hass, entry, controller, transport)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        transport.close()
        raise
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: Gen24ConfigEntry) -> bool:
    """Unload a config entry."""
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        entry.runtime_data.transport.close()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: Gen24ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)

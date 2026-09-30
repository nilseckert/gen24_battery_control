"""Config flow for Gen24 Battery Control."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback

from .const import (
    CONF_ENFORCE,
    CONF_MANUFACTURER,
    CONF_MODEL,
    CONF_SCAN_INTERVAL,
    CONF_SERIAL,
    CONF_STORAGE_BASE,
    CONF_SW_VERSION,
    CONF_UNIT_ID,
    DEFAULT_ENFORCE,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNIT_ID,
    DOMAIN,
)
from .controller import ModelNotFoundError, NotSunSpecError, discover
from .transport import ModbusTcpTransport, TransportError

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(vol.Coerce(int), vol.Range(1, 65535)),
        vol.Required(CONF_UNIT_ID, default=DEFAULT_UNIT_ID): vol.All(vol.Coerce(int), vol.Range(0, 247)),
    }
)


class Gen24ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            transport = ModbusTcpTransport(
                user_input[CONF_HOST], user_input[CONF_PORT], user_input[CONF_UNIT_ID]
            )
            try:
                base, info = await discover(transport)
            except TransportError:
                errors["base"] = "cannot_connect"
            except NotSunSpecError:
                errors["base"] = "not_sunspec"
            except ModelNotFoundError:
                errors["base"] = "no_storage"
            except Exception:
                _LOGGER.exception("Unexpected error during discovery")
                errors["base"] = "unknown"
            finally:
                transport.close()

            if not errors:
                unique_id = info.serial or f"{user_input[CONF_HOST]}:{user_input[CONF_UNIT_ID]}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured(updates={CONF_HOST: user_input[CONF_HOST]})
                return self.async_create_entry(
                    title=info.model or "Gen24",
                    data={
                        **user_input,
                        CONF_STORAGE_BASE: base,
                        CONF_MANUFACTURER: info.manufacturer,
                        CONF_MODEL: info.model,
                        CONF_SERIAL: info.serial,
                        CONF_SW_VERSION: info.version,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return Gen24OptionsFlow()


class Gen24OptionsFlow(OptionsFlow):
    """Polling interval and enforce mode."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(2, 300)),
                vol.Required(
                    CONF_ENFORCE, default=options.get(CONF_ENFORCE, DEFAULT_ENFORCE)
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

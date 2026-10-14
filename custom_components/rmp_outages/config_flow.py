"""Config and options flow for the RMP outage integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    ALERT_RADIUS_MAX,
    CONF_ALERT_RADIUS,
    CONF_INCLUDE_PLANNED,
    CONF_RADIUS,
    CONF_STATE,
    CONF_ZIP,
    DEFAULT_ALERT_RADIUS,
    DEFAULT_INCLUDE_PLANNED,
    DEFAULT_RADIUS,
    DEFAULT_STATE,
    DOMAIN,
    NAME,
    RADIUS_MAX,
    RADIUS_MIN,
    STATES,
)


def _schema(current: dict[str, Any]) -> vol.Schema:
    """Build the settings schema, pre-filled from the current options."""
    return vol.Schema(
        {
            vol.Required(CONF_STATE, default=current.get(CONF_STATE, DEFAULT_STATE)): vol.In(STATES),
            vol.Optional(
                CONF_RADIUS, default=current.get(CONF_RADIUS, DEFAULT_RADIUS)
            ): vol.All(vol.Coerce(float), vol.Range(min=RADIUS_MIN, max=RADIUS_MAX)),
            vol.Optional(
                CONF_INCLUDE_PLANNED,
                default=current.get(CONF_INCLUDE_PLANNED, DEFAULT_INCLUDE_PLANNED),
            ): bool,
            vol.Optional(
                CONF_ALERT_RADIUS,
                default=current.get(CONF_ALERT_RADIUS, DEFAULT_ALERT_RADIUS),
            ): vol.All(vol.Coerce(float), vol.Range(min=0, max=ALERT_RADIUS_MAX)),
            vol.Optional(CONF_ZIP, default=current.get(CONF_ZIP, "")): str,
        }
    )


class RmpOutagesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Ask for the state and the radius that matters."""
        if user_input is not None:
            await self.async_set_unique_id(
                f"{user_input.get(CONF_STATE, DEFAULT_STATE)}_{user_input.get(CONF_RADIUS, DEFAULT_RADIUS)}"
            )
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"{NAME} ({user_input.get(CONF_STATE, DEFAULT_STATE)})",
                data=user_input,
            )
        return self.async_show_form(step_id="user", data_schema=_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return RmpOutagesOptionsFlow()


class RmpOutagesOptionsFlow(OptionsFlow):
    """Allow the settings to be changed later."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Show and store the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_schema(current))

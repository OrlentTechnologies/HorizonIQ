from __future__ import annotations

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.core import callback

from .config_data import (
    build_config_schema,
    default_config_data,
    merged_config_data,
    normalize_config_input,
    validate_config_data,
)
from .const import DEFAULT_TITLE, DOMAIN


class MeshSolarConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle Mesh Solar config and options flows."""

    # Home Assistant config-entry schema version, not the integration release version.
    # HACS and release automation use the version in manifest.json.
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, object] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial user step."""
        errors: dict[str, str] = {}
        config_data = default_config_data()

        if user_input is not None:
            config_data = normalize_config_input(user_input)
            errors = validate_config_data(config_data)
            if not errors:
                return self.async_create_entry(title=DEFAULT_TITLE, data=config_data)

        return self.async_show_form(
            step_id="user",
            data_schema=build_config_schema(config_data=config_data),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "MeshSolarOptionsFlow":
        """Return the options flow handler."""
        return MeshSolarOptionsFlow()


class MeshSolarOptionsFlow(config_entries.OptionsFlow):
    """Handle Mesh Solar options."""

    async def async_step_init(
        self, user_input: dict[str, object] | None = None
    ) -> ConfigFlowResult:
        """Manage Mesh Solar options."""
        errors: dict[str, str] = {}
        config_data = merged_config_data(self.config_entry)

        if user_input is not None:
            config_data = normalize_config_input(user_input)
            errors = validate_config_data(config_data)
            if not errors:
                updated_options = dict(self.config_entry.options)
                for key in config_data:
                    updated_options.pop(key, None)

                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=dict(config_data),
                    options=updated_options,
                )
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=build_config_schema(config_data=config_data),
            errors=errors,
        )

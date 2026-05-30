"""Tests for config and options flows."""

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import selector
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mesh_solar.config_data import merged_config_data
from custom_components.mesh_solar.const import (
    CONF_API_KEY,
    CONF_BATTERY_CAPACITY_SENSOR,
    CONF_ENVIRONMENT,
    CONF_FORECAST_DEVICE_ID,
    CONF_FORECAST_DEVICE_TOKEN,
    CONF_GX_DEVICE_ID,
    CONF_HOME_ASSISTANT_INSTALLATION_ID,
    CONF_HASH,
    CONF_REGISTRATION_DATA,
    CONF_URL,
    DEFAULT_ENVIRONMENT,
    DEFAULT_ENVIRONMENT_LABEL,
    DOMAIN,
    SANDBOX_ENVIRONMENT,
    UNAVAILABLE_HOME_ASSISTANT_INSTALLATION_ID,
)


async def test_user_flow_creates_entry_with_normalized_data(hass) -> None:
    """The user flow trims inputs and stores Live as the empty environment."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    assert result["type"] == FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_URL: " https://example.com/api/Forecast_Get?code=user-code ",
            CONF_API_KEY: " api-key ",
            CONF_BATTERY_CAPACITY_SENSOR: " sensor.battery_capacity ",
            CONF_ENVIRONMENT: DEFAULT_ENVIRONMENT_LABEL,
            CONF_HASH: " hash-value ",
            CONF_REGISTRATION_DATA: " reg-value ",
            CONF_FORECAST_DEVICE_ID: " gx-device-1 ",
            CONF_FORECAST_DEVICE_TOKEN: " trial-token ",
            CONF_HOME_ASSISTANT_INSTALLATION_ID: "tampered-installation-id",
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Mesh Solar"
    assert result["data"] == {
        CONF_URL: "https://example.com/api/Forecast_Get?code=user-code",
        CONF_API_KEY: "api-key",
        CONF_BATTERY_CAPACITY_SENSOR: "sensor.battery_capacity",
        CONF_ENVIRONMENT: DEFAULT_ENVIRONMENT,
        CONF_HASH: " hash-value ",
        CONF_REGISTRATION_DATA: " reg-value ",
        CONF_FORECAST_DEVICE_ID: "gx-device-1",
        CONF_FORECAST_DEVICE_TOKEN: "trial-token",
    }
    assert CONF_HOME_ASSISTANT_INSTALLATION_ID not in result["data"]


async def test_options_flow_updates_entry_data_and_clears_duplicate_options(hass) -> None:
    """Options flow writes authoritative values back into entry.data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Mesh Solar",
        data={
            CONF_URL: "https://example.com/original",
            CONF_API_KEY: "original-key",
            CONF_BATTERY_CAPACITY_SENSOR: "sensor.original_capacity",
            CONF_ENVIRONMENT: DEFAULT_ENVIRONMENT,
            CONF_HASH: "",
            CONF_REGISTRATION_DATA: "",
            CONF_FORECAST_DEVICE_ID: "",
            CONF_FORECAST_DEVICE_TOKEN: "",
        },
        options={
            CONF_URL: "https://example.com/legacy-option",
            CONF_API_KEY: "legacy-option-key",
        },
        entry_id="options-entry",
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.mesh_solar.config_flow.instance_id.async_get",
        AsyncMock(return_value="ha-installation-options"),
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    defaults = result["data_schema"]({})
    assert defaults[CONF_HOME_ASSISTANT_INSTALLATION_ID] == "ha-installation-options"
    installation_id_selector = _schema_validator(
        result["data_schema"], CONF_HOME_ASSISTANT_INSTALLATION_ID
    )
    assert isinstance(installation_id_selector, selector.TextSelector)
    assert installation_id_selector.config["read_only"] is True

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_URL: "https://example.com/updated",
            CONF_API_KEY: "updated-key",
            CONF_BATTERY_CAPACITY_SENSOR: "sensor.updated_capacity",
            CONF_ENVIRONMENT: SANDBOX_ENVIRONMENT,
            CONF_HASH: "new-hash",
            CONF_REGISTRATION_DATA: "new-registration",
            CONF_FORECAST_DEVICE_ID: "gx-device-2",
            CONF_FORECAST_DEVICE_TOKEN: "new-trial-token",
            CONF_HOME_ASSISTANT_INSTALLATION_ID: "tampered-installation-id",
        },
    )
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.data == {
        CONF_URL: "https://example.com/updated",
        CONF_API_KEY: "updated-key",
        CONF_BATTERY_CAPACITY_SENSOR: "sensor.updated_capacity",
        CONF_ENVIRONMENT: SANDBOX_ENVIRONMENT,
        CONF_HASH: "new-hash",
        CONF_REGISTRATION_DATA: "new-registration",
        CONF_FORECAST_DEVICE_ID: "gx-device-2",
        CONF_FORECAST_DEVICE_TOKEN: "new-trial-token",
    }
    assert CONF_HOME_ASSISTANT_INSTALLATION_ID not in entry.data
    assert entry.options == {}


async def test_user_flow_shows_read_only_installation_id(hass) -> None:
    """The config form displays the HA installation ID as read-only metadata."""
    with patch(
        "custom_components.mesh_solar.config_flow.instance_id.async_get",
        AsyncMock(return_value="ha-installation-1"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )

    assert result["type"] == FlowResultType.FORM
    defaults = result["data_schema"]({})
    assert defaults[CONF_HOME_ASSISTANT_INSTALLATION_ID] == "ha-installation-1"
    installation_id_selector = _schema_validator(
        result["data_schema"], CONF_HOME_ASSISTANT_INSTALLATION_ID
    )
    assert isinstance(installation_id_selector, selector.TextSelector)
    assert installation_id_selector.config["read_only"] is True


async def test_user_flow_shows_unavailable_when_installation_id_fails(hass) -> None:
    """The config form remains usable when the HA installation ID is unavailable."""
    with patch(
        "custom_components.mesh_solar.config_flow.instance_id.async_get",
        AsyncMock(side_effect=RuntimeError("storage unavailable")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )

    assert result["type"] == FlowResultType.FORM
    defaults = result["data_schema"]({})
    assert (
        defaults[CONF_HOME_ASSISTANT_INSTALLATION_ID]
        == UNAVAILABLE_HOME_ASSISTANT_INSTALLATION_ID
    )


def test_merged_config_data_defaults_forecast_device_id_from_gx_device_id() -> None:
    """Legacy GX device ID data seeds the forecast device ID when unset."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Mesh Solar",
        data={
            CONF_URL: "https://example.com/forecast",
            CONF_API_KEY: "api-key",
            CONF_BATTERY_CAPACITY_SENSOR: "sensor.battery_capacity",
            CONF_ENVIRONMENT: DEFAULT_ENVIRONMENT,
            CONF_HASH: "",
            CONF_REGISTRATION_DATA: "",
            CONF_GX_DEVICE_ID: "gx-device-legacy",
        },
        entry_id="gx-entry",
    )

    assert merged_config_data(entry)[CONF_FORECAST_DEVICE_ID] == "gx-device-legacy"


def _schema_validator(schema, field: str):
    for key, validator in schema.schema.items():
        if getattr(key, "schema", None) == field:
            return validator
    raise AssertionError(f"Schema field {field} not found")


async def test_user_flow_rejects_invalid_url(hass) -> None:
    """The user flow validates forecast URLs."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_URL: "not-a-url",
            CONF_API_KEY: "api-key",
            CONF_BATTERY_CAPACITY_SENSOR: "sensor.battery_capacity",
            CONF_ENVIRONMENT: DEFAULT_ENVIRONMENT_LABEL,
            CONF_HASH: "",
            CONF_REGISTRATION_DATA: "",
            CONF_FORECAST_DEVICE_ID: "",
            CONF_FORECAST_DEVICE_TOKEN: "",
        },
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_URL: "invalid_url"}


async def test_user_flow_rejects_invalid_entity_id(hass) -> None:
    """The user flow validates the battery capacity entity ID."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_URL: "https://example.com/api/Forecast_Get?code=user-code",
            CONF_API_KEY: "api-key",
            CONF_BATTERY_CAPACITY_SENSOR: "not an entity",
            CONF_ENVIRONMENT: DEFAULT_ENVIRONMENT_LABEL,
            CONF_HASH: "",
            CONF_REGISTRATION_DATA: "",
            CONF_FORECAST_DEVICE_ID: "",
            CONF_FORECAST_DEVICE_TOKEN: "",
        },
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_BATTERY_CAPACITY_SENSOR: "invalid_entity_id"}

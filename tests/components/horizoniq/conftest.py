"""Shared fixtures for HorizonIQ tests."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.horizoniq.const import (
    CONF_API_KEY,
    CONF_BATTERY_CAPACITY_SENSOR,
    CONF_ENVIRONMENT,
    CONF_FORECAST_DEVICE_ID,
    CONF_FORECAST_DEVICE_TOKEN,
    CONF_HASH,
    CONF_REGISTRATION_DATA,
    CONF_URL,
    DOMAIN,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom integrations from this repository."""


@pytest.fixture(name="entry_data")
def entry_data_fixture() -> dict[str, str]:
    """Return a valid config entry payload."""
    return {
        CONF_URL: "https://example.com/api/Forecast_Get?code=test-code",
        CONF_API_KEY: "test-api-key",
        CONF_BATTERY_CAPACITY_SENSOR: "sensor.battery_capacity",
        CONF_ENVIRONMENT: "",
        CONF_HASH: "",
        CONF_REGISTRATION_DATA: "",
        CONF_FORECAST_DEVICE_ID: "",
        CONF_FORECAST_DEVICE_TOKEN: "",
    }


@pytest.fixture(name="mock_config_entry")
def mock_config_entry_fixture(hass, entry_data: dict[str, str]) -> MockConfigEntry:
    """Create a HorizonIQ config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HorizonIQ",
        data=entry_data,
        entry_id="test-entry",
    )
    entry.add_to_hass(hass)
    return entry

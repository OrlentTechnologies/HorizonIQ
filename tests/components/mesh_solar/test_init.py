"""Tests for integration setup."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mesh_solar import async_setup_entry
from custom_components.mesh_solar.const import (
    CONF_API_KEY,
    CONF_BATTERY_CAPACITY_SENSOR,
    CONF_ENVIRONMENT,
    CONF_HASH,
    CONF_REGISTRATION_DATA,
    CONF_URL,
    DEFAULT_ENVIRONMENT,
    DOMAIN,
    PLATFORMS,
)
from custom_components.mesh_solar.entity_helpers import build_unique_id


async def test_async_setup_entry_creates_coordinator_and_forwards_platforms(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
) -> None:
    """A valid entry creates the coordinator and forwards platform setup."""
    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()

    with (
        patch("custom_components.mesh_solar._ensure_local_docs", AsyncMock()) as mock_docs,
        patch(
            "custom_components.mesh_solar.MeshSolarCoordinator",
            return_value=coordinator,
        ) as mock_coordinator_class,
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            AsyncMock(return_value=True),
        ) as mock_forward,
    ):
        result = await async_setup_entry(hass, mock_config_entry)

    assert result is True
    assert hass.data[DOMAIN][mock_config_entry.entry_id] is coordinator
    mock_docs.assert_awaited_once()
    mock_coordinator_class.assert_called_once_with(
        hass=hass,
        entry=mock_config_entry,
        url=entry_data[CONF_URL],
        api_key=entry_data[CONF_API_KEY],
        battery_capacity_sensor=entry_data[CONF_BATTERY_CAPACITY_SENSOR],
        environment=DEFAULT_ENVIRONMENT,
        initial_hash="",
        initial_registration="",
    )
    mock_forward.assert_awaited_once_with(mock_config_entry, PLATFORMS)


async def test_async_setup_entry_sets_cadence_sensor_from_forecast_payload(
    hass,
    entry_data: dict[str, str],
) -> None:
    """Forecast responses update cadence without duplicating encrypted registration data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Mesh Solar",
        data={
            **entry_data,
            CONF_ENVIRONMENT: DEFAULT_ENVIRONMENT,
            CONF_REGISTRATION_DATA: "encrypted-registration-data-old",
        },
        entry_id="cadence-entry",
    )
    entry.add_to_hass(hass)
    hass.states.async_set(entry_data[CONF_BATTERY_CAPACITY_SENSOR], "53")

    payload = {
        "id": "d7e9984f-d87c-a23f-01a6-8b2488547d9f",
        "registrationId": "61677385-f8e4-4337-8ccd-fd2d558bf5c0",
        "date": "2026-04-03T09:08:38.2671273Z",
        "calculatedOnUtc": "2026-04-03T09:08:38.2671273Z",
        "hash": "37bd35b771d5f931bf4ff547c03f6c7af2e704ebceb88fa167cba82d9c9854ec",
        "periods": [
            {
                "id": "7becc6a3-d881-420a-ab17-5c150044f008",
                "period": 18,
                "date": "2026-04-03T09:00:00Z",
                "price": 0.1386,
                "shouldImport": False,
                "amount": 0,
                "imported": 0,
                "exported": 0,
                "estimatedGeneration": 322.564985772249,
                "used": 418,
                "battery": 8464,
                "batteryManagementSystemState": 0,
                "history": [],
            }
        ],
        "currentCapacity": 9216,
        "minCapacity": 5760,
        "targetCapacity": 5760,
        "lowPrice": 0.05,
        "mediumPrice": 0.1,
        "batteryManagementSystemState": 0,
        "shouldImport": False,
        "cloudUpdateEnabled": False,
        "forecastCadenceMinutes": 1,
        "registrationData": "encrypted-registration-data-new",
        "totalCost": 1.340718750000001,
        "chargingCost": 0.40609296,
        "saving": 0.9346257900000011,
    }

    with (
        patch("custom_components.mesh_solar._ensure_local_docs", AsyncMock()),
        patch(
            "custom_components.mesh_solar.coordinator.MeshSolarCoordinator._fetch_payload",
            new=AsyncMock(return_value=payload),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    cadence_state = hass.states.get("sensor.mesh_solar_forecast_cadence")
    assert cadence_state is not None
    assert cadence_state.state == "1"
    assert cadence_state.attributes["effective_poll_interval_minutes"] == 1

    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.forecast_cadence_minutes == 1
    assert coordinator.effective_forecast_cadence_minutes == 1
    assert coordinator.update_interval == timedelta(minutes=1)
    assert entry.data[CONF_REGISTRATION_DATA] == "encrypted-registration-data-new"

    diagnostics_state = hass.states.get("sensor.mesh_solar_forecast_diagnostics")
    assert diagnostics_state is not None
    assert diagnostics_state.state == "1"
    assert diagnostics_state.attributes["environment"] == "Live"
    assert diagnostics_state.attributes["period_count"] == 1
    forecast_attributes = diagnostics_state.attributes["forecast"]
    assert forecast_attributes["calculated_on_utc"] == "2026-04-03T09:08:38.2671273Z"
    assert forecast_attributes["low_price"] == 0.05
    assert forecast_attributes["medium_price"] == 0.1
    assert diagnostics_state.attributes["forecast"]["forecast_cadence_minutes"] == 1
    assert (
        diagnostics_state.attributes["forecast"]["registration_data"]
        == "encrypted-registration-data-new"
    )
    assert forecast_attributes["periods"] == [
        {
            "id": "7becc6a3-d881-420a-ab17-5c150044f008",
            "period": 18,
            "date": "2026-04-03T09:00:00Z",
            "price": 0.1386,
            "should_import": False,
            "amount": 0.0,
            "imported": 0.0,
            "exported": 0.0,
            "estimated_generation": 322.564985772249,
            "used": 418.0,
            "battery": 8464.0,
            "battery_management_system_state": "0",
        }
    ]
    assert "registration" not in diagnostics_state.attributes
    assert "forecast_hash" not in diagnostics_state.attributes
    assert "forecast_date" not in diagnostics_state.attributes
    assert "target_capacity" not in diagnostics_state.attributes
    assert "forecast_cadence_minutes" not in diagnostics_state.attributes


async def test_async_setup_entry_raises_for_missing_required_values(hass) -> None:
    """Missing required configuration blocks entry setup."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Mesh Solar",
        data={
            CONF_URL: "",
            CONF_API_KEY: "api-key",
            CONF_BATTERY_CAPACITY_SENSOR: "sensor.battery_capacity",
            CONF_ENVIRONMENT: DEFAULT_ENVIRONMENT,
            CONF_HASH: "",
            CONF_REGISTRATION_DATA: "",
        },
        entry_id="missing-url",
    )
    entry.add_to_hass(hass)

    with patch("custom_components.mesh_solar._ensure_local_docs", AsyncMock()):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, entry)


async def test_async_setup_entry_migrates_legacy_live_unique_ids(
    hass,
    mock_config_entry,
) -> None:
    """Legacy live unique IDs are migrated and duplicate replacement entries removed."""
    registry = er.async_get(hass)
    legacy_sensor = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "mesh_solar_bms_state",
        config_entry=mock_config_entry,
        suggested_object_id="mesh_solar_bms_state",
    )
    duplicate_sensor = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "mesh_solar_test-entry_bms_state",
        config_entry=mock_config_entry,
        suggested_object_id="mesh_solar_bms_state",
    )
    legacy_button = registry.async_get_or_create(
        "button",
        DOMAIN,
        "mesh_solar_clear_registration",
        config_entry=mock_config_entry,
        suggested_object_id="mesh_solar_clear_registration",
    )

    assert legacy_sensor.entity_id == "sensor.mesh_solar_bms_state"
    assert duplicate_sensor.entity_id == "sensor.mesh_solar_bms_state_2"
    assert legacy_button.entity_id == "button.mesh_solar_clear_registration"

    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()

    with (
        patch("custom_components.mesh_solar._ensure_local_docs", AsyncMock()),
        patch(
            "custom_components.mesh_solar.MeshSolarCoordinator",
            return_value=coordinator,
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            AsyncMock(return_value=True),
        ),
    ):
        result = await async_setup_entry(hass, mock_config_entry)

    assert result is True
    assert "sensor.mesh_solar_bms_state_2" not in registry.entities
    assert (
        registry.entities["sensor.mesh_solar_bms_state"].unique_id
        == build_unique_id(DEFAULT_ENVIRONMENT, mock_config_entry.entry_id, "bms_state")
    )
    assert (
        registry.entities["button.mesh_solar_clear_registration"].unique_id
        == build_unique_id(
            DEFAULT_ENVIRONMENT,
            mock_config_entry.entry_id,
            "clear_registration",
        )
    )


async def test_async_setup_entry_migrates_legacy_live_unique_ids_from_stale_entry(
    hass,
    mock_config_entry,
) -> None:
    """Legacy live IDs attached to a stale entry are adopted by the active entry."""
    stale_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Mesh Solar Stale",
        data=dict(mock_config_entry.data),
        entry_id="stale-entry",
    )
    stale_entry.add_to_hass(hass)

    registry = er.async_get(hass)
    legacy_sensor = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "mesh_solar_forecast_diagnostics",
        config_entry=stale_entry,
        suggested_object_id="mesh_solar_forecast_diagnostics",
    )
    duplicate_sensor = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "mesh_solar_test-entry_forecast_diagnostics",
        config_entry=mock_config_entry,
        suggested_object_id="mesh_solar_forecast_diagnostics",
    )

    assert legacy_sensor.entity_id == "sensor.mesh_solar_forecast_diagnostics"
    assert duplicate_sensor.entity_id == "sensor.mesh_solar_forecast_diagnostics_2"

    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()

    with (
        patch("custom_components.mesh_solar._ensure_local_docs", AsyncMock()),
        patch(
            "custom_components.mesh_solar.MeshSolarCoordinator",
            return_value=coordinator,
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            AsyncMock(return_value=True),
        ),
    ):
        result = await async_setup_entry(hass, mock_config_entry)

    assert result is True
    assert "sensor.mesh_solar_forecast_diagnostics_2" not in registry.entities
    migrated_entry = registry.entities["sensor.mesh_solar_forecast_diagnostics"]
    assert migrated_entry.unique_id == build_unique_id(
        DEFAULT_ENVIRONMENT,
        mock_config_entry.entry_id,
        "forecast_diagnostics",
    )
    assert migrated_entry.config_entry_id == mock_config_entry.entry_id


async def test_async_setup_entry_renames_current_duplicate_entity_id_when_legacy_missing(
    hass,
    mock_config_entry,
) -> None:
    """Current live unique IDs are renamed back from _2 when the canonical slot is free."""
    registry = er.async_get(hass)
    conflict_entry = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "mesh_solar_temporary_conflict",
        config_entry=mock_config_entry,
        suggested_object_id="mesh_solar_forecast_diagnostics",
    )
    current_entry = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "mesh_solar_test-entry_forecast_diagnostics",
        config_entry=mock_config_entry,
        suggested_object_id="mesh_solar_forecast_diagnostics",
    )

    assert conflict_entry.entity_id == "sensor.mesh_solar_forecast_diagnostics"
    assert current_entry.entity_id == "sensor.mesh_solar_forecast_diagnostics_2"

    registry.async_remove(conflict_entry.entity_id)
    registry.deleted_entities.pop(
        (
            conflict_entry.domain,
            conflict_entry.platform,
            conflict_entry.unique_id,
        ),
        None,
    )

    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()

    with (
        patch("custom_components.mesh_solar._ensure_local_docs", AsyncMock()),
        patch(
            "custom_components.mesh_solar.MeshSolarCoordinator",
            return_value=coordinator,
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            AsyncMock(return_value=True),
        ),
    ):
        result = await async_setup_entry(hass, mock_config_entry)

    assert result is True
    assert "sensor.mesh_solar_forecast_diagnostics_2" not in registry.entities
    renamed_entry = registry.entities["sensor.mesh_solar_forecast_diagnostics"]
    assert renamed_entry.unique_id == build_unique_id(
        DEFAULT_ENVIRONMENT,
        mock_config_entry.entry_id,
        "forecast_diagnostics",
    )


async def test_async_setup_entry_collapses_stale_live_entry_id_family(
    hass,
    mock_config_entry,
) -> None:
    """Canonical live entity IDs are reclaimed even from stale per-entry unique IDs."""
    stale_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Mesh Solar Old Live",
        data=dict(mock_config_entry.data),
        entry_id="old-live-entry",
    )
    stale_entry.add_to_hass(hass)

    registry = er.async_get(hass)
    stale_entry_registry = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "mesh_solar_old-live-entry_forecast_diagnostics",
        config_entry=stale_entry,
        suggested_object_id="mesh_solar_forecast_diagnostics",
    )
    current_entry_registry = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "mesh_solar_test-entry_forecast_diagnostics",
        config_entry=mock_config_entry,
        suggested_object_id="mesh_solar_forecast_diagnostics",
    )

    assert stale_entry_registry.entity_id == "sensor.mesh_solar_forecast_diagnostics"
    assert current_entry_registry.entity_id == "sensor.mesh_solar_forecast_diagnostics_2"

    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()

    with (
        patch("custom_components.mesh_solar._ensure_local_docs", AsyncMock()),
        patch(
            "custom_components.mesh_solar.MeshSolarCoordinator",
            return_value=coordinator,
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            AsyncMock(return_value=True),
        ),
    ):
        result = await async_setup_entry(hass, mock_config_entry)

    assert result is True
    assert "sensor.mesh_solar_forecast_diagnostics_2" not in registry.entities
    migrated_entry = registry.entities["sensor.mesh_solar_forecast_diagnostics"]
    assert migrated_entry.unique_id == build_unique_id(
        DEFAULT_ENVIRONMENT,
        mock_config_entry.entry_id,
        "forecast_diagnostics",
    )
    assert migrated_entry.config_entry_id == mock_config_entry.entry_id

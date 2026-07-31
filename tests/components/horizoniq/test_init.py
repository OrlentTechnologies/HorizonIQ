"""Tests for integration setup."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.horizoniq import (
    async_migrate_entry,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.horizoniq.const import (
    CONF_API_KEY,
    CONF_BATTERY_CAPACITY_SENSOR,
    CONF_CAPACITY_SOURCE,
    CONF_CAN_FORECAST,
    CONF_ENVIRONMENT,
    CONF_FORECAST_DEVICE_ID,
    CONF_FORECAST_DEVICE_TOKEN,
    CONF_GX_DEVICE_ID,
    CONF_HASH,
    CONF_REGISTRATION_DATA,
    CONF_REGISTRATION_CONFIG,
    CONF_REGISTRATION_ID,
    CONF_SUBSCRIPTION_STATUS,
    CONF_URL,
    DEFAULT_ENVIRONMENT,
    CAPACITY_SOURCE_VIRTUAL_BATTERY,
    DOMAIN,
    PLATFORMS,
    SANDBOX_ENVIRONMENT,
    SUBSCRIPTION_STATUS_NO_SUBSCRIPTION,
)
from custom_components.horizoniq.entry_data import CONF_OAUTH_RUNTIME
from custom_components.horizoniq.entity_helpers import build_unique_id
from custom_components.horizoniq.sandbox_runtime import pretend_gx_id


async def test_manifest_requires_home_assistant_mqtt(hass) -> None:
    """HorizonIQ's manifest makes MQTT available before entry setup runs."""
    integration = await async_get_integration(hass, DOMAIN)

    assert integration.manifest["dependencies"] == ["mqtt"]


async def test_async_migrate_entry_upgrades_v1_manual_entry(hass) -> None:
    """Version 1 manual forecast entries are upgraded to the current schema."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HorizonIQ",
        data={
            CONF_URL: "https://example.com/api/Forecast_Get?code=test-code",
            CONF_API_KEY: "test-api-key",
            CONF_BATTERY_CAPACITY_SENSOR: "sensor.battery_capacity",
            CONF_ENVIRONMENT: "Live",
            CONF_HASH: "existing-hash",
            CONF_REGISTRATION_DATA: "existing-registration",
            CONF_GX_DEVICE_ID: "legacy-gx-device",
        },
        options={
            CONF_URL: "https://example.com/legacy-option",
            CONF_API_KEY: "legacy-option-key",
            "unrelated_option": "kept",
        },
        entry_id="legacy-entry",
        version=1,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    assert entry.version == 3
    assert entry.data["capacity_source"] == "external_entity"
    assert entry.data[CONF_URL] == "https://example.com/api/Forecast_Get?code=test-code"
    assert entry.data[CONF_API_KEY] == "test-api-key"
    assert entry.data[CONF_ENVIRONMENT] == DEFAULT_ENVIRONMENT
    assert entry.data[CONF_HASH] == "existing-hash"
    assert entry.data[CONF_REGISTRATION_DATA] == "existing-registration"
    assert entry.data[CONF_FORECAST_DEVICE_ID] == "legacy-gx-device"
    assert entry.data[CONF_FORECAST_DEVICE_TOKEN] == ""
    assert entry.data[CONF_GX_DEVICE_ID] == "legacy-gx-device"
    assert entry.options == {"unrelated_option": "kept"}


@pytest.mark.parametrize("version, source, expected", [(2, None, "external_entity"), (2, "bad", "external_entity"), (3, "bad", "external_entity"), (3, "external_entity", "external_entity"), (3, "virtual_battery", "virtual_battery")])
async def test_async_migrate_entry_normalizes_capacity_source(hass, version, source, expected) -> None:
    data = {CONF_URL: "https://example.com/api/Forecast_Get", CONF_API_KEY: "key", CONF_BATTERY_CAPACITY_SENSOR: "sensor.capacity", CONF_ENVIRONMENT: SANDBOX_ENVIRONMENT if source == "virtual_battery" else DEFAULT_ENVIRONMENT, CONF_HASH: "", CONF_REGISTRATION_DATA: "", "unrelated": "kept"}
    if source is not None:
        data["capacity_source"] = source
    entry = MockConfigEntry(domain=DOMAIN, data=data, options={"unrelated_option": "kept"}, version=version)
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry)
    assert entry.version == 3
    assert entry.data["capacity_source"] == expected
    assert entry.data["unrelated"] == "kept"
    before_data, before_options, before_version = dict(entry.data), dict(entry.options), entry.version
    assert await async_migrate_entry(hass, entry)
    assert dict(entry.data) == before_data
    assert dict(entry.options) == before_options
    assert entry.version == before_version


async def test_async_migrate_entry_rejects_future_version(hass) -> None:
    """Entries from a newer integration version are left untouched."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HorizonIQ",
        data={},
        entry_id="future-entry",
        version=99,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is False
    assert entry.version == 99


async def test_async_setup_entry_creates_coordinator_and_forwards_platforms(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
) -> None:
    """A valid entry creates the coordinator and forwards platform setup."""
    coordinator = MagicMock()
    coordinator.async_refresh = AsyncMock()

    with (
        patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()) as mock_docs,
        patch(
            "custom_components.horizoniq.HorizonIQCoordinator",
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
    assert hass.data[DOMAIN][mock_config_entry.entry_id].coordinator is coordinator
    mock_docs.assert_awaited_once()
    mock_coordinator_class.assert_called_once_with(
        hass=hass,
        entry=mock_config_entry,
        url=entry_data[CONF_URL],
        api_key=entry_data[CONF_API_KEY],
        battery_capacity_sensor=entry_data[CONF_BATTERY_CAPACITY_SENSOR],
        environment=DEFAULT_ENVIRONMENT,
        forecast_device_id="",
        forecast_device_token="",
        forecast_function_key="",
        initial_hash="",
        initial_registration="",
        credential_refresh=None,
    )
    mock_forward.assert_awaited_once_with(mock_config_entry, PLATFORMS)


async def test_async_setup_entry_completes_when_initial_refresh_fails(
    hass,
    mock_config_entry,
) -> None:
    """Initial refresh failures leave unavailable entities and load the entry."""
    coordinator = MagicMock()
    coordinator.async_refresh = AsyncMock()

    with (
        patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()),
        patch(
            "custom_components.horizoniq.HorizonIQCoordinator",
            return_value=coordinator,
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            AsyncMock(return_value=True),
        ) as mock_forward,
    ):
        result = await async_setup_entry(hass, mock_config_entry)

    assert result is True
    coordinator.async_refresh.assert_awaited_once()
    mock_forward.assert_awaited_once_with(mock_config_entry, PLATFORMS)
    assert hass.data[DOMAIN][mock_config_entry.entry_id].coordinator is coordinator


async def test_async_setup_entry_creates_inactive_virtual_device_from_options_config(
    hass,
    entry_data: dict[str, str],
) -> None:
    """A persisted Sandbox virtual-battery entry creates its inactive device."""
    registration_id = "11111111-1111-4111-8111-111111111111"
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HorizonIQ (Sandbox)",
        data={
            **entry_data,
            CONF_ENVIRONMENT: SANDBOX_ENVIRONMENT,
            CONF_REGISTRATION_ID: registration_id,
            CONF_REGISTRATION_CONFIG: {
                "ChargeEfficiency": 0.95,
                "DischargeEfficiency": 0.9,
                "EquipmentProfile": {
                    "BatteryCapacityWh": 10_000,
                    "MinimumCapacityPercentage": 0.2,
                    "MaximumBatteryChargePowerWatts": 2_000,
                    "MaximumBatteryDischargePowerWatts": 2_000,
                },
            },
        },
        options={CONF_CAPACITY_SOURCE: CAPACITY_SOURCE_VIRTUAL_BATTERY},
        entry_id="sandbox-options-entry",
        version=3,
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()),
        patch(
            "custom_components.horizoniq.coordinator.HorizonIQCoordinator.async_refresh",
            AsyncMock(),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    runtime = hass.data[DOMAIN][entry.entry_id]
    assert runtime.is_sandbox_configured
    assert entry.data[CONF_CAPACITY_SOURCE] == CAPACITY_SOURCE_VIRTUAL_BATTERY
    assert CONF_CAPACITY_SOURCE not in entry.options

    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, pretend_gx_id(registration_id))}
    )
    assert device is not None
    assert device.config_entries == {entry.entry_id}

    entity_registry = er.async_get(hass)
    enable_entity_id = entity_registry.async_get_entity_id(
        "switch",
        DOMAIN,
        build_unique_id(SANDBOX_ENVIRONMENT, entry.entry_id, "simulation"),
    )
    assert enable_entity_id is not None
    assert hass.states.get(enable_entity_id).state == "off"

    load_entity_id = entity_registry.async_get_entity_id(
        "number",
        DOMAIN,
        build_unique_id(SANDBOX_ENVIRONMENT, entry.entry_id, "load_w"),
    )
    assert load_entity_id is not None
    assert hass.states.get(load_entity_id).state == "unavailable"

    sandbox_entities = [
        registry_entry
        for registry_entry in entity_registry.entities.values()
        if registry_entry.config_entry_id == entry.entry_id
        and registry_entry.unique_id.startswith(
            f"{DOMAIN}_{entry.entry_id}_sandbox_"
        )
    ]
    assert sandbox_entities
    assert {registry_entry.device_id for registry_entry in sandbox_entities} == {
        device.id
    }


async def test_sandbox_devices_are_entry_scoped_and_persist_across_unload(
    hass,
    entry_data: dict[str, str],
) -> None:
    """Configured sandbox devices remain one-per-entry across a reload."""
    first_registration_id = "11111111-1111-4111-8111-111111111111"
    second_registration_id = "22222222-2222-4222-8222-222222222222"

    def sandbox_data(registration_id: str) -> dict[str, object]:
        return {
            **entry_data,
            CONF_ENVIRONMENT: SANDBOX_ENVIRONMENT,
            CONF_CAPACITY_SOURCE: CAPACITY_SOURCE_VIRTUAL_BATTERY,
            CONF_REGISTRATION_ID: registration_id,
            CONF_REGISTRATION_CONFIG: {
                "ChargeEfficiency": 0.95,
                "DischargeEfficiency": 0.9,
                "EquipmentProfile": {
                    "BatteryCapacityWh": 10_000,
                    "MinimumCapacityPercentage": 0.2,
                    "MaximumBatteryChargePowerWatts": 2_000,
                    "MaximumBatteryDischargePowerWatts": 2_000,
                },
            },
        }

    first = MockConfigEntry(
        domain=DOMAIN,
        data=sandbox_data(first_registration_id),
        entry_id="sandbox-device-one",
        version=3,
    )
    second = MockConfigEntry(
        domain=DOMAIN,
        data=sandbox_data(second_registration_id),
        entry_id="sandbox-device-two",
        version=3,
    )
    first.add_to_hass(hass)
    second.add_to_hass(hass)

    coordinator = MagicMock()
    coordinator.async_refresh = AsyncMock()
    with (
        patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()),
        patch(
            "custom_components.horizoniq.HorizonIQCoordinator",
            return_value=coordinator,
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            AsyncMock(return_value=True),
        ),
    ):
        assert await async_setup_entry(hass, first)
        assert await async_setup_entry(hass, second)

    device_registry = dr.async_get(hass)
    first_device = device_registry.async_get_device(
        identifiers={(DOMAIN, pretend_gx_id(first_registration_id))}
    )
    second_device = device_registry.async_get_device(
        identifiers={(DOMAIN, pretend_gx_id(second_registration_id))}
    )
    assert first_device is not None
    assert second_device is not None
    assert first_device.id != second_device.id
    assert first_device.config_entries == {first.entry_id}
    assert second_device.config_entries == {second.entry_id}

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        AsyncMock(return_value=True),
    ):
        assert await async_unload_entry(hass, first)
    assert device_registry.async_get(first_device.id) is not None

    with (
        patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()),
        patch(
            "custom_components.horizoniq.HorizonIQCoordinator",
            return_value=coordinator,
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            AsyncMock(return_value=True),
        ),
    ):
        assert await async_setup_entry(hass, first)

    reloaded_device = device_registry.async_get_device(
        identifiers={(DOMAIN, pretend_gx_id(first_registration_id))}
    )
    assert reloaded_device is not None
    assert reloaded_device.id == first_device.id
    assert len(
        [
            device
            for device in device_registry.devices.values()
            if (DOMAIN, pretend_gx_id(first_registration_id)) in device.identifiers
        ]
    ) == 1


async def test_async_setup_entry_rejects_duplicate_canonical_registration_id(
    hass,
    entry_data: dict[str, str],
) -> None:
    """Entries with the same registration UUID cannot share a simulator identity."""
    registration_id = "11111111-1111-4111-8111-111111111111"
    existing = MockConfigEntry(
        domain=DOMAIN,
        data={**entry_data, CONF_REGISTRATION_ID: registration_id},
        entry_id="existing-entry",
    )
    duplicate = MockConfigEntry(
        domain=DOMAIN,
        data={**entry_data, CONF_REGISTRATION_ID: registration_id.upper()},
        entry_id="duplicate-entry",
    )
    existing.add_to_hass(hass)
    duplicate.add_to_hass(hass)

    coordinator = MagicMock()
    coordinator.async_refresh = AsyncMock()
    with (
        patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()),
        patch(
            "custom_components.horizoniq.HorizonIQCoordinator",
            return_value=coordinator,
        ),
        pytest.raises(ConfigEntryNotReady, match="registration is already configured"),
    ):
        await async_setup_entry(hass, duplicate)

    coordinator.async_refresh.assert_not_awaited()
    assert duplicate.entry_id not in hass.data.get(DOMAIN, {})


async def test_async_setup_entry_loads_unavailable_entities_after_initial_failure(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    aioclient_mock,
) -> None:
    """An unavailable forecast does not prevent entity setup."""
    hass.states.async_set(entry_data[CONF_BATTERY_CAPACITY_SENSOR], "53")
    aioclient_mock.get(
        "https://example.com/api/Forecast_Get?code=test-code"
        "&currentBatteryCapacity=53&hash=&registrationData=",
        status=500,
    )

    with patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][mock_config_entry.entry_id].coordinator
    assert coordinator.last_update_success is False
    assert hass.states.get("sensor.horizoniq_total_cost").state == "unavailable"


async def test_async_setup_entry_stops_before_forecasting_when_no_subscription(
    hass,
    entry_data: dict[str, str],
) -> None:
    """A no-subscription bootstrap entry does not create a forecast coordinator."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HorizonIQ",
        data={
            **entry_data,
            CONF_SUBSCRIPTION_STATUS: SUBSCRIPTION_STATUS_NO_SUBSCRIPTION,
            CONF_CAN_FORECAST: False,
            CONF_OAUTH_RUNTIME: {
                "client_id": "ha-client",
                "portal_connection_url": (
                    "https://sandbox.example.test/portal/horizoniq/connect"
                ),
                "token_endpoint": "https://login.example.test/token",
                "backend_api_scope": "api://backend/user_impersonation",
                "backend_api_base_url": "https://api.example.test",
            },
        },
        entry_id="no-subscription-entry",
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()),
        patch("custom_components.horizoniq._async_create_issue") as create_issue,
        patch("custom_components.horizoniq.HorizonIQCoordinator") as coordinator_class,
    ):
        with pytest.raises(ConfigEntryAuthFailed):
            await async_setup_entry(hass, entry)

    coordinator_class.assert_not_called()
    create_issue.assert_called_once_with(
        hass,
        "entitlement_lost",
        "https://sandbox.example.test/portal/billing",
    )
    assert entry.entry_id not in hass.data.get(DOMAIN, {})


async def test_async_setup_entry_sets_cadence_sensor_from_forecast_payload(
    hass,
    entry_data: dict[str, str],
) -> None:
    """Forecast responses update cadence without duplicating encrypted registration data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HorizonIQ",
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
        "hasTrial": True,
        "isActive": True,
        "isEligible": False,
        "status": "active",
        "registrationData": "encrypted-registration-data-new",
        "totalCost": 1.340718750000001,
        "chargingCost": 0.40609296,
        "saving": 0.9346257900000011,
    }

    with (
        patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()),
        patch(
            "custom_components.horizoniq.coordinator.HorizonIQCoordinator._fetch_payload",
            new=AsyncMock(return_value=payload),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    cadence_state = hass.states.get("sensor.horizoniq_forecast_cadence")
    assert cadence_state is not None
    assert cadence_state.state == "1"
    assert cadence_state.attributes["effective_poll_interval_minutes"] == 1

    coordinator = hass.data[DOMAIN][entry.entry_id].coordinator
    assert coordinator.forecast_cadence_minutes == 1
    assert coordinator.effective_forecast_cadence_minutes == 1
    assert coordinator.update_interval == timedelta(minutes=1)
    assert entry.data[CONF_REGISTRATION_DATA] == "encrypted-registration-data-new"

    diagnostics_state = hass.states.get("sensor.horizoniq_forecast_diagnostics")
    assert diagnostics_state is not None
    assert diagnostics_state.state == "1"
    assert diagnostics_state.attributes["environment"] == "Live"
    assert diagnostics_state.attributes["period_count"] == 1
    forecast_attributes = diagnostics_state.attributes["forecast"]
    assert forecast_attributes["calculated_on_utc"] == "2026-04-03T09:08:38.2671273Z"
    assert forecast_attributes["low_price"] == 0.05
    assert forecast_attributes["medium_price"] == 0.1
    assert diagnostics_state.attributes["forecast"]["forecast_cadence_minutes"] == 1
    assert diagnostics_state.attributes["trial_status"] == "active"
    assert diagnostics_state.attributes["trial"] == {
        "has_trial": True,
        "is_active": True,
        "is_eligible": False,
        "status": "active",
        "forecast_cadence_minutes": 1,
    }
    assert diagnostics_state.attributes["forecast"]["registration_data"] == "REDACTED"
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

    trial_state = hass.states.get("sensor.horizoniq_trial_status")
    assert trial_state is not None
    assert trial_state.state == "active"
    assert trial_state.attributes["is_active"] is True


async def test_async_setup_entry_loads_entities_when_initial_refresh_is_unauthorized(
    hass,
    entry_data: dict[str, str],
    aioclient_mock,
) -> None:
    """An initial 401 loads diagnostic entities instead of blocking setup."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HorizonIQ",
        data={
            **entry_data,
            CONF_FORECAST_DEVICE_ID: "gx-device-1",
            CONF_FORECAST_DEVICE_TOKEN: "trial-token",
        },
        entry_id="unauthorized-entry",
    )
    entry.add_to_hass(hass)
    hass.states.async_set(entry_data[CONF_BATTERY_CAPACITY_SENSOR], "53")

    aioclient_mock.get(
        (
            "https://example.com/api/Forecast_Get?code=test-code"
            "&currentBatteryCapacity=53&hash=&registrationData="
        ),
        status=401,
        json={},
    )

    with patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    diagnostics_state = hass.states.get("sensor.horizoniq_forecast_diagnostics")
    assert diagnostics_state is not None
    assert diagnostics_state.state == "0"
    assert diagnostics_state.attributes["authorization_status"] == "unauthorized"
    assert diagnostics_state.attributes["authorization_status_code"] == 401

    trial_state = hass.states.get("sensor.horizoniq_trial_status")
    assert trial_state is not None
    assert trial_state.state == "unauthorized"
    assert trial_state.attributes["authorization_status"] == "unauthorized"
    assert trial_state.attributes["authorization_status_code"] == 401


async def test_async_setup_entry_raises_for_missing_required_values(hass) -> None:
    """Missing required configuration blocks entry setup."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HorizonIQ",
        data={
            CONF_URL: "",
            CONF_API_KEY: "api-key",
            CONF_BATTERY_CAPACITY_SENSOR: "sensor.battery_capacity",
            CONF_ENVIRONMENT: DEFAULT_ENVIRONMENT,
            CONF_HASH: "",
            CONF_REGISTRATION_DATA: "",
            CONF_FORECAST_DEVICE_ID: "",
            CONF_FORECAST_DEVICE_TOKEN: "",
        },
        entry_id="missing-url",
    )
    entry.add_to_hass(hass)

    with patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()):
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
        "horizoniq_bms_state",
        config_entry=mock_config_entry,
        suggested_object_id="horizoniq_bms_state",
    )
    duplicate_sensor = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "horizoniq_test-entry_bms_state",
        config_entry=mock_config_entry,
        suggested_object_id="horizoniq_bms_state",
    )
    legacy_button = registry.async_get_or_create(
        "button",
        DOMAIN,
        "horizoniq_clear_registration",
        config_entry=mock_config_entry,
        suggested_object_id="horizoniq_clear_registration",
    )

    assert legacy_sensor.entity_id == "sensor.horizoniq_bms_state"
    assert duplicate_sensor.entity_id == "sensor.horizoniq_bms_state_2"
    assert legacy_button.entity_id == "button.horizoniq_clear_registration"

    coordinator = MagicMock()
    coordinator.async_refresh = AsyncMock()

    with (
        patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()),
        patch(
            "custom_components.horizoniq.HorizonIQCoordinator",
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
    assert "sensor.horizoniq_bms_state_2" not in registry.entities
    assert (
        registry.entities["sensor.horizoniq_bms_state"].unique_id
        == build_unique_id(DEFAULT_ENVIRONMENT, mock_config_entry.entry_id, "bms_state")
    )
    assert (
        registry.entities["button.horizoniq_clear_registration"].unique_id
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
        title="HorizonIQ Stale",
        data=dict(mock_config_entry.data),
        entry_id="stale-entry",
    )
    stale_entry.add_to_hass(hass)

    registry = er.async_get(hass)
    legacy_sensor = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "horizoniq_forecast_diagnostics",
        config_entry=stale_entry,
        suggested_object_id="horizoniq_forecast_diagnostics",
    )
    duplicate_sensor = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "horizoniq_test-entry_forecast_diagnostics",
        config_entry=mock_config_entry,
        suggested_object_id="horizoniq_forecast_diagnostics",
    )

    assert legacy_sensor.entity_id == "sensor.horizoniq_forecast_diagnostics"
    assert duplicate_sensor.entity_id == "sensor.horizoniq_forecast_diagnostics_2"

    coordinator = MagicMock()
    coordinator.async_refresh = AsyncMock()

    with (
        patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()),
        patch(
            "custom_components.horizoniq.HorizonIQCoordinator",
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
    assert "sensor.horizoniq_forecast_diagnostics_2" not in registry.entities
    migrated_entry = registry.entities["sensor.horizoniq_forecast_diagnostics"]
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
        "horizoniq_temporary_conflict",
        config_entry=mock_config_entry,
        suggested_object_id="horizoniq_forecast_diagnostics",
    )
    current_entry = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "horizoniq_test-entry_forecast_diagnostics",
        config_entry=mock_config_entry,
        suggested_object_id="horizoniq_forecast_diagnostics",
    )

    assert conflict_entry.entity_id == "sensor.horizoniq_forecast_diagnostics"
    assert current_entry.entity_id == "sensor.horizoniq_forecast_diagnostics_2"

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
    coordinator.async_refresh = AsyncMock()

    with (
        patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()),
        patch(
            "custom_components.horizoniq.HorizonIQCoordinator",
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
    assert "sensor.horizoniq_forecast_diagnostics_2" not in registry.entities
    renamed_entry = registry.entities["sensor.horizoniq_forecast_diagnostics"]
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
        title="HorizonIQ Old Live",
        data=dict(mock_config_entry.data),
        entry_id="old-live-entry",
    )
    stale_entry.add_to_hass(hass)

    registry = er.async_get(hass)
    stale_entry_registry = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "horizoniq_old-live-entry_forecast_diagnostics",
        config_entry=stale_entry,
        suggested_object_id="horizoniq_forecast_diagnostics",
    )
    current_entry_registry = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "horizoniq_test-entry_forecast_diagnostics",
        config_entry=mock_config_entry,
        suggested_object_id="horizoniq_forecast_diagnostics",
    )

    assert stale_entry_registry.entity_id == "sensor.horizoniq_forecast_diagnostics"
    assert current_entry_registry.entity_id == "sensor.horizoniq_forecast_diagnostics_2"

    coordinator = MagicMock()
    coordinator.async_refresh = AsyncMock()

    with (
        patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()),
        patch(
            "custom_components.horizoniq.HorizonIQCoordinator",
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
    assert "sensor.horizoniq_forecast_diagnostics_2" not in registry.entities
    migrated_entry = registry.entities["sensor.horizoniq_forecast_diagnostics"]
    assert migrated_entry.unique_id == build_unique_id(
        DEFAULT_ENVIRONMENT,
        mock_config_entry.entry_id,
        "forecast_diagnostics",
    )
    assert migrated_entry.config_entry_id == mock_config_entry.entry_id

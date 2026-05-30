"""Tests for the update coordinator."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.mesh_solar.const import (
    CONF_HASH,
    CONF_REGISTRATION_DATA,
    FAILED_REFRESH_RETRY_SECONDS,
    HEADER_API_KEY,
    HEADER_MESH_DEVICE_ID,
    HEADER_MESH_DEVICE_TOKEN,
    SANDBOX_ENVIRONMENT,
)
from custom_components.mesh_solar.coordinator import MeshSolarCoordinator
from custom_components.mesh_solar.models import MeshSolarSnapshot


async def test_coordinator_updates_cached_values_from_api(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    aioclient_mock,
) -> None:
    """Coordinator normalizes payload data and persists cached values."""
    hass.states.async_set(entry_data["battery_capacity_sensor"], "53")

    coordinator = MeshSolarCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
        initial_hash="old-hash",
        initial_registration='{"id":"registration-1","ForecastCadenceMinutes":5}',
    )

    url = coordinator._build_request_url("53")
    aioclient_mock.get(
        url,
        json={
            "Hash": "new-hash",
            "RegistrationData": (
                '{"id":"registration-2","DynamicCharging":true,'
                '"ForecastCadenceMinutes":1}'
            ),
            "Currency": "GBP",
            "TargetCapacity": "57.5",
            "Forecast": {
                "Date": "2026-03-07T10:00:00+00:00",
                "Periods": [
                    {
                        "Period": 1,
                        "Date": "2026-03-07T10:00:00+00:00",
                        "BatteryManagementSystemState": "charging",
                    }
                ],
            },
        },
    )

    snapshot = await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert snapshot == MeshSolarSnapshot(
        forecast={
            "date": "2026-03-07T10:00:00+00:00",
            "hash": "new-hash",
            "periods": [
                {
                    "period": 1,
                    "date": "2026-03-07T10:00:00+00:00",
                    "battery_management_system_state": "charging",
                }
            ],
            "registration_data": (
                '{"id":"registration-2","DynamicCharging":true,'
                '"ForecastCadenceMinutes":1}'
            ),
            "currency": "GBP",
            "target_capacity": 57.5,
        },
        forecast_periods=[
            {
                "period": 1,
                "date": "2026-03-07T10:00:00+00:00",
                "battery_management_system_state": "charging",
            }
        ],
        registration={
            "id": "registration-2",
            "DynamicCharging": True,
            "ForecastCadenceMinutes": 1,
        },
        currency="GBP",
        target_capacity=57.5,
        forecast_hash="new-hash",
        registration_data=(
            '{"id":"registration-2","DynamicCharging":true,'
            '"ForecastCadenceMinutes":1}'
        ),
        forecast_cadence_minutes=1,
    )
    assert coordinator.last_hash == "new-hash"
    assert coordinator.registration_data == (
        '{"id":"registration-2","DynamicCharging":true,"ForecastCadenceMinutes":1}'
    )
    assert coordinator.currency == "GBP"
    assert coordinator.target_capacity == 57.5
    assert coordinator.forecast_cadence_minutes == 1
    assert coordinator.effective_forecast_cadence_minutes == 1
    assert coordinator.update_interval == timedelta(minutes=1)
    assert coordinator.forecast["date"] == "2026-03-07T10:00:00+00:00"
    assert coordinator.forecast_periods == [
        {
            "period": 1,
            "date": "2026-03-07T10:00:00+00:00",
            "battery_management_system_state": "charging",
        }
    ]
    assert mock_config_entry.data[CONF_HASH] == "new-hash"
    assert mock_config_entry.data[CONF_REGISTRATION_DATA] == (
        '{"id":"registration-2","DynamicCharging":true,"ForecastCadenceMinutes":1}'
    )


async def test_clear_registration_data_persists_and_refreshes(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
) -> None:
    """Manual clear removes cached registration data and requests a refresh."""
    coordinator = MeshSolarCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
        initial_hash="existing-hash",
        initial_registration='{"id":"registration-1","ForecastCadenceMinutes":5}',
    )
    coordinator.async_request_refresh = AsyncMock()

    await coordinator.async_clear_registration_data()
    await hass.async_block_till_done()

    assert coordinator.registration_data == ""
    assert coordinator.forecast_cadence_minutes is None
    assert coordinator.effective_forecast_cadence_minutes == 5
    assert coordinator.update_interval == timedelta(minutes=5)
    assert mock_config_entry.data[CONF_REGISTRATION_DATA] == ""
    coordinator.async_request_refresh.assert_awaited_once()


async def test_forecast_request_sends_trial_headers_when_configured(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    aioclient_mock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Forecast requests include app-trial device headers when configured."""
    token = "portal-trial-token"
    hass.states.async_set(entry_data["battery_capacity_sensor"], "53")
    caplog.set_level("DEBUG", logger="custom_components.mesh_solar.coordinator")

    coordinator = MeshSolarCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
        forecast_device_id=" gx-device-1 ",
        forecast_device_token=f" {token} ",
    )

    aioclient_mock.get(coordinator._build_request_url("53"), json={})

    await coordinator._async_update_data()

    _, request_url, _, headers = aioclient_mock.mock_calls[-1]
    assert headers == {
        HEADER_API_KEY: entry_data["api_key"],
        HEADER_MESH_DEVICE_ID: "gx-device-1",
        HEADER_MESH_DEVICE_TOKEN: token,
    }
    assert HEADER_MESH_DEVICE_ID not in request_url.query
    assert HEADER_MESH_DEVICE_TOKEN not in request_url.query
    assert "deviceKind" not in request_url.query
    assert "integrationSource" not in request_url.query
    assert "deviceKind" not in headers
    assert "integrationSource" not in headers
    assert token not in caplog.text
    assert "gx-device-1" not in caplog.text


async def test_forecast_request_omits_trial_headers_when_blank(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    aioclient_mock,
) -> None:
    """Blank app-trial binding values are not sent as headers or query params."""
    hass.states.async_set(entry_data["battery_capacity_sensor"], "53")

    coordinator = MeshSolarCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
        forecast_device_id=" ",
        forecast_device_token="",
    )

    aioclient_mock.get(coordinator._build_request_url("53"), json={})

    await coordinator._async_update_data()

    _, request_url, _, headers = aioclient_mock.mock_calls[-1]
    assert headers == {HEADER_API_KEY: entry_data["api_key"]}
    assert HEADER_MESH_DEVICE_ID not in request_url.query
    assert HEADER_MESH_DEVICE_TOKEN not in request_url.query
    assert "deviceKind" not in request_url.query
    assert "integrationSource" not in request_url.query
    assert "deviceKind" not in headers
    assert "integrationSource" not in headers


async def test_coordinator_failed_refresh_requests_one_minute_retry(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    aioclient_mock,
) -> None:
    """Refresh failures ask Home Assistant to retry after one minute."""
    hass.states.async_set(entry_data["battery_capacity_sensor"], "53")

    coordinator = MeshSolarCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
    )

    aioclient_mock.get(coordinator._build_request_url("53"), status=500)

    with pytest.raises(UpdateFailed) as exc_info:
        await coordinator._async_update_data()

    assert exc_info.value.retry_after == FAILED_REFRESH_RETRY_SECONDS

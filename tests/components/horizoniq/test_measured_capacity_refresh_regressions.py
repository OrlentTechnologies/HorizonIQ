"""Measured-capacity refresh regressions at the real HA coordinator boundary."""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
)

from custom_components.horizoniq.const import (
    CAPACITY_SOURCE_VIRTUAL_BATTERY,
    CONF_API_KEY,
    CONF_BATTERY_CAPACITY_SENSOR,
    CONF_CAPACITY_SOURCE,
    CONF_ENVIRONMENT,
    CONF_HASH,
    CONF_REGISTRATION_CONFIG,
    CONF_REGISTRATION_DATA,
    CONF_REGISTRATION_ID,
    CONF_URL,
    DOMAIN,
    REQUEST_TIMEOUT_SECONDS,
    SANDBOX_ENVIRONMENT,
)
from custom_components.horizoniq.simulation.models import (
    BatteryState,
    CommandStatus,
    OperatingMode,
)
from custom_components.horizoniq.models import ForecastFreshness


NOW = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
FIXTURE = Path(__file__).with_name("fixtures") / "direct_schema5_forecast.json"
SENSOR = "sensor.measured_capacity"
REGISTRATION_ID = "11111111-1111-4111-8111-111111111111"


def _entry(entry_id: str) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HorizonIQ measured capacity",
        entry_id=entry_id,
        version=3,
        data={
            CONF_URL: "https://example.com/api/Forecast_Get?code=test-code",
            CONF_API_KEY: "test-api-key",
            CONF_BATTERY_CAPACITY_SENSOR: SENSOR,
            CONF_CAPACITY_SOURCE: CAPACITY_SOURCE_VIRTUAL_BATTERY,
            CONF_ENVIRONMENT: SANDBOX_ENVIRONMENT,
            CONF_HASH: "",
            CONF_REGISTRATION_DATA: "",
            CONF_REGISTRATION_ID: REGISTRATION_ID,
            CONF_REGISTRATION_CONFIG: {
                "ChargeEfficiency": 0.95,
                "DischargeEfficiency": 0.9,
                "EquipmentProfile": {
                    "BatteryCapacityWh": 28_800,
                    "MinimumCapacityPercentage": 0.2,
                    "MaximumBatteryChargePowerWatts": 4_000,
                    "MaximumBatteryDischargePowerWatts": 4_000,
                },
            },
        },
    )
    return entry


def _schema6_response(
    *,
    current_capacity_wh: int,
    expected_start_soc_kwh: float,
    hash_value: str,
    created_at_utc: str,
    effective_at_utc: str,
    recommended_action: str = "charge_required",
    executable_action: str = "charge_required",
) -> dict[str, object]:
    """Return a complete schema-6 response with distinct Wh and kWh fields."""
    forecast = json.loads(FIXTURE.read_text(encoding="utf-8"))
    forecast["schemaVersion"] = 6
    forecast["currentCapacity"] = current_capacity_wh
    forecast["createdAtUtc"] = created_at_utc
    forecast["effectiveAtUtc"] = effective_at_utc
    forecast["shouldExport"] = recommended_action == "export_for_profit"
    if recommended_action == "export_for_profit":
        forecast["shouldImport"] = False

    period = forecast["periods"][0]
    period["date"] = effective_at_utc
    period["expectedStartSoc"] = expected_start_soc_kwh
    period["expectedEndSoc"] = expected_start_soc_kwh
    period["recommendedAction"] = recommended_action
    period["executableAction"] = executable_action
    period["shouldExport"] = recommended_action == "export_for_profit"
    if recommended_action == "export_for_profit":
        period["shouldImport"] = False
        period["expectedExport"] = 1.0
        period["decisionTrace"]["expectedExportKwh"] = 1.0
    period["decisionTrace"]["selectedAction"] = recommended_action
    period["decisionTrace"]["expectedStartSocKwh"] = expected_start_soc_kwh
    period["decisionTrace"]["expectedEndSocKwh"] = expected_start_soc_kwh
    if executable_action == "none":
        period["commandId"] = None
        period["issuedAtUtc"] = None
        period["expiresAtUtc"] = None
    else:
        period["issuedAtUtc"] = created_at_utc
        period["expiresAtUtc"] = "2026-07-30T12:30:00Z"

    second = forecast["periods"][1]
    second["date"] = "2026-07-30T12:30:00Z"
    second["shouldExport"] = False
    second["expectedStartSoc"] = expected_start_soc_kwh
    second["expectedEndSoc"] = expected_start_soc_kwh
    second["decisionTrace"]["expectedStartSocKwh"] = expected_start_soc_kwh
    second["decisionTrace"]["expectedEndSocKwh"] = expected_start_soc_kwh
    return {"Hash": hash_value, "Forecast": forecast}


def _request_url(capacity: str, hash_value: str = "") -> str:
    return (
        "https://example.com/api/Forecast_Get?code=test-code"
        f"&currentBatteryCapacity={capacity}&hash={hash_value}&registrationData="
    )


async def _setup_runtime(hass, aioclient_mock, *, entry_id: str, response: dict[str, object]):
    """Set up the registered listener and stage the initial real HTTP response."""
    hass.states.async_set(SENSOR, "22000")
    entry = _entry(entry_id)
    entry.add_to_hass(hass)
    aioclient_mock.get(_request_url("14400.0"), json=response)
    aioclient_mock.get(_request_url("22000"), json=response)
    with (
        patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()),
        patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", AsyncMock()),
        patch(
            "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
            AsyncMock(return_value=lambda: None),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        runtime = hass.data[DOMAIN][entry.entry_id]
        runtime._live_forecast_now = lambda: NOW
        runtime._state = BatteryState(22_000)
        await runtime.async_enable(hass)
        await hass.async_block_till_done()
        runtime.coordinator.set_battery_capacity_provider(None)
        return entry, runtime


@pytest.mark.asyncio
async def test_live_sensor_4320_wh_refresh_replaces_cached_22000_wh_forecast_and_stages_fresh_response(
    hass, aioclient_mock
) -> None:
    """A fresh sensor Wh reading replaces the retained forecast through real HTTP."""
    historical = _schema6_response(
        current_capacity_wh=22_000,
        expected_start_soc_kwh=22.0,
        hash_value="historical-hash",
        created_at_utc="2026-07-30T11:59:00Z",
        effective_at_utc="2026-07-30T12:00:00Z",
    )
    entry, runtime = await _setup_runtime(
        hass, aioclient_mock, entry_id="measured-refresh", response=historical
    )
    try:
        coordinator = runtime.coordinator
        before = coordinator.data.schema5_forecast
        assert before is not None and before.current_capacity == 22_000
        assert before.periods[0].expected_start_soc == 22.0
        hass.states.async_set(SENSOR, "4320")
        fresh = _schema6_response(
            current_capacity_wh=4_320, expected_start_soc_kwh=4.32,
            hash_value="fresh-hash", created_at_utc="2026-07-30T11:59:30Z",
            effective_at_utc="2026-07-30T12:00:00Z",
        )
        aioclient_mock.get(_request_url("4320", "historical-hash"), json=fresh)
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()
        snapshot = coordinator.data
        accepted = snapshot.schema5_forecast
        assert accepted is not None and accepted.stale is False
        assert accepted.current_capacity == 4_320
        assert accepted.periods[0].expected_start_soc == 4.32
        assert accepted.created_at_utc == "2026-07-30T11:59:30Z"
        assert accepted.effective_at_utc == "2026-07-30T12:00:00Z"
        assert snapshot.direct_forecast is not None
        assert snapshot.forecast_freshness is ForecastFreshness.FRESH
        assert runtime._staged_direct_forecast is snapshot.direct_forecast
        assert runtime.last_command_status is CommandStatus.APPLIED
        assert runtime._command is not None and runtime._command.mode is OperatingMode.GRID_SETPOINT
        assert coordinator.last_hash == entry.data[CONF_HASH] == "fresh-hash"
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
async def test_timeout_after_live_sensor_4320_wh_keeps_stale_22000_wh_forecast_without_new_command(
    hass, aioclient_mock, monkeypatch
) -> None:
    """A later timeout retains historical diagnostics and cannot stage export control."""
    historical = _schema6_response(
        current_capacity_wh=22_000,
        expected_start_soc_kwh=22.0,
        hash_value="historical-hash",
        created_at_utc="2026-07-30T11:59:00Z",
        effective_at_utc="2026-07-30T12:00:00Z",
        recommended_action="export_for_profit",
        executable_action="none",
    )
    entry, runtime = await _setup_runtime(
        hass, aioclient_mock, entry_id="measured-timeout", response=historical
    )
    try:
        coordinator = runtime.coordinator
        accepted = coordinator.data.schema5_forecast
        assert accepted is not None and accepted.current_capacity == 22_000
        original_ids = runtime._accepted_command_ids
        @asynccontextmanager
        async def deterministic_timeout(seconds: float):
            assert seconds == REQUEST_TIMEOUT_SECONDS == 10
            yield
        monkeypatch.setattr("custom_components.horizoniq.coordinator.asyncio.timeout", deterministic_timeout)
        hass.states.async_set(SENSOR, "4320")
        aioclient_mock.get(_request_url("4320", "historical-hash"), exc=asyncio.TimeoutError())
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()
        snapshot = coordinator.data
        stale = snapshot.schema5_forecast
        assert stale is not None and stale.stale is True
        assert stale.current_capacity == 22_000
        assert stale.periods[0].expected_start_soc == 22.0
        assert stale.created_at_utc == accepted.created_at_utc
        assert stale.effective_at_utc == accepted.effective_at_utc
        assert snapshot.forecast_freshness is ForecastFreshness.STALE
        assert snapshot.direct_forecast is None
        assert runtime._command is not None and runtime._command.mode is OperatingMode.SELF_CONSUMPTION
        assert runtime.last_command_status is CommandStatus.FALLBACK_STALE
        assert runtime._accepted_command_ids == original_ids
        assert coordinator.last_hash == entry.data[CONF_HASH] == "historical-hash"
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
async def test_fresh_schema6_recovery_after_timeout_replaces_stale_history_and_hash_once(
    hass, aioclient_mock, monkeypatch
) -> None:
    """A newer fresh publication safely recovers after a stale timeout."""
    historical = _schema6_response(
        current_capacity_wh=22_000,
        expected_start_soc_kwh=22.0,
        hash_value="historical-hash",
        created_at_utc="2026-07-30T11:59:00Z",
        effective_at_utc="2026-07-30T12:00:00Z",
        recommended_action="export_for_profit",
        executable_action="none",
    )
    entry, runtime = await _setup_runtime(
        hass, aioclient_mock, entry_id="measured-recovery", response=historical
    )
    try:
        coordinator = runtime.coordinator

        @asynccontextmanager
        async def deterministic_timeout(seconds: float):
            assert seconds == REQUEST_TIMEOUT_SECONDS == 10
            yield

        monkeypatch.setattr("custom_components.horizoniq.coordinator.asyncio.timeout", deterministic_timeout)
        hass.states.async_set(SENSOR, "4320")
        fresh = _schema6_response(
            current_capacity_wh=4_320, expected_start_soc_kwh=4.32,
            hash_value="recovery-hash", created_at_utc="2026-07-30T11:59:30Z",
            effective_at_utc="2026-07-30T12:00:00Z",
        )
        responses = (
            {"exc": asyncio.TimeoutError()},
            {"json": fresh},
        )
        response_index = 0

        async def response_sequence(method, url, data):
            nonlocal response_index
            response = responses[response_index]
            response_index += 1
            return AiohttpClientMockResponse(
                method=method,
                url=url,
                **response,
            )

        aioclient_mock.get(
            _request_url("4320", "historical-hash"),
            side_effect=response_sequence,
        )
        request_count_before_recovery = aioclient_mock.call_count
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()
        stale_snapshot = coordinator.data
        assert stale_snapshot.forecast_freshness is ForecastFreshness.STALE
        assert response_index == 1
        assert aioclient_mock.call_count == request_count_before_recovery + 1

        # The sandbox is paused while the runtime is active, so async_refresh()
        # returns the current snapshot without fetching. Use the public sandbox
        # fetch path, which intentionally performs one real fetch, commits it,
        # and publishes the resulting runtime update.
        await coordinator.async_fetch_sandbox_forecast()
        await hass.async_block_till_done()
        snapshot = coordinator.data
        assert response_index == 2
        assert aioclient_mock.call_count == request_count_before_recovery + 2
        assert snapshot.publication_sequence == stale_snapshot.publication_sequence + 1
        assert snapshot.forecast_freshness is ForecastFreshness.FRESH
        assert snapshot.schema5_forecast is not None
        assert snapshot.schema5_forecast.current_capacity == 4_320
        assert snapshot.schema5_forecast.periods[0].expected_start_soc == 4.32
        assert coordinator.last_hash == entry.data[CONF_HASH] == "recovery-hash"
        assert runtime._staged_fresh_snapshot is snapshot
        assert runtime.last_command_status is CommandStatus.APPLIED
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)

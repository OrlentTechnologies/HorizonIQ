"""End-to-end paused direct-forecast lifecycle regressions."""

import asyncio
from copy import deepcopy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
    SANDBOX_ENVIRONMENT,
)
from custom_components.horizoniq.entity_helpers import build_unique_id
from custom_components.horizoniq.coordinator_helpers import build_snapshot
from custom_components.horizoniq.models import ForecastFreshness, HorizonIQSnapshot
from custom_components.horizoniq.sandbox_runtime import HorizonIQEntryRuntime
from custom_components.horizoniq.simulation.clock import ClockRate, VirtualClock
from custom_components.horizoniq.simulation.models import (
    BatteryConfig,
    BatteryState,
    CommandStatus,
    OperatingMode,
)


FIXTURE = Path(__file__).with_name("fixtures") / "deployed_schema5_normalized.json"
SCHEMA5_FIXTURE = Path(__file__).with_name("fixtures") / "direct_schema5_forecast.json"
NOW = datetime(2026, 7, 30, 12, 30, tzinfo=timezone.utc)


def _observed_forecast() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _schema5_forecast() -> dict[str, object]:
    """Load the complete current Solar schema-5 DTO fixture."""
    return json.loads(SCHEMA5_FIXTURE.read_text(encoding="utf-8"))


def _maximum_schema5_forecast() -> dict[str, object]:
    """Expand the complete Solar DTO to a 48-period wire horizon."""
    payload = _schema5_forecast()
    source = payload["periods"]
    assert isinstance(source, list) and source
    periods: list[dict[str, object]] = []
    for index in range(48):
        period = deepcopy(source[index % len(source)])
        assert isinstance(period, dict)
        period["period"] = index
        period["date"] = (
            NOW + timedelta(minutes=30 * index)
        ).isoformat().replace("+00:00", "Z")
        periods.append(period)
    payload["periods"] = periods
    return payload


def _entry(entry_id: str = "paused-direct-entry") -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HorizonIQ (Sandbox)",
        entry_id=entry_id,
        version=3,
        data={
            CONF_URL: "https://example.com/api/Forecast_Get?code=test-code",
            CONF_API_KEY: "test-api-key",
            CONF_BATTERY_CAPACITY_SENSOR: "sensor.unused_capacity",
            CONF_ENVIRONMENT: SANDBOX_ENVIRONMENT,
            CONF_CAPACITY_SOURCE: CAPACITY_SOURCE_VIRTUAL_BATTERY,
            CONF_HASH: "",
            CONF_REGISTRATION_DATA: "",
            CONF_REGISTRATION_ID: "11111111-1111-4111-8111-111111111111",
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
    )
    return entry


def _entity_id(hass, entry_id: str, suffix: str, domain: str = "sensor") -> str:
    registry = __import__("homeassistant.helpers.entity_registry", fromlist=["async_get"])
    entity_id = registry.async_get(hass).async_get_entity_id(
        domain, DOMAIN, build_unique_id(SANDBOX_ENVIRONMENT, entry_id, suffix)
    )
    assert entity_id is not None
    return entity_id


@pytest.mark.asyncio
async def test_paused_entry_processes_real_coordinator_refresh_without_mqtt(
    hass, aioclient_mock
) -> None:
    """A 429 then real coordinator success updates paused HA entity states."""
    entry = _entry()
    entry.add_to_hass(hass)
    request_url = (
        "https://example.com/api/Forecast_Get?code=test-code"
        "&currentBatteryCapacity=5000.0&hash=&registrationData="
    )
    aioclient_mock.get(request_url, status=429)

    with (
        patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()),
        patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", AsyncMock()) as publish,
        patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe", AsyncMock()) as subscribe,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        runtime = hass.data[DOMAIN][entry.entry_id]
        runtime._clock = VirtualClock(NOW - timedelta(days=1), ClockRate.PAUSED)
        runtime._live_forecast_now = lambda: NOW
        energy_before = runtime.energy_wh

        aioclient_mock.clear_requests()
        aioclient_mock.get(request_url, status=429)
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": _entity_id(hass, entry.entry_id, "simulation", "switch")},
            blocking=True,
        )
        aioclient_mock.clear_requests()
        aioclient_mock.get(request_url, json=_observed_forecast())

        await runtime.coordinator.async_request_refresh()
        await hass.async_block_till_done()

        diagnostics = _entity_id(hass, entry.entry_id, "forecast_diagnostics")
        health = _entity_id(hass, entry.entry_id, "forecast")
        command = _entity_id(hass, entry.entry_id, "command")
        decision = _entity_id(hass, entry.entry_id, "decision")

        assert hass.states.get(diagnostics).state == "1"
        assert hass.states.get(health).state == "Healthy"
        assert hass.states.get(command).state == "No action"
        assert "self-consumption" in hass.states.get(decision).state
        assert runtime.energy_wh == energy_before
        assert runtime.virtual_time_utc == NOW
        assert publish.await_count > 0
        assert subscribe.await_count == 6
        assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
async def test_real_schema5_refresh_exposes_complete_entry_local_diagnostics(
    hass, aioclient_mock
) -> None:
    """A config entry keeps the accepted full Solar horizon in live state."""
    entry = _entry("schema5-live-entry")
    entry.add_to_hass(hass)
    request_url = (
        "https://example.com/api/Forecast_Get?code=test-code"
        "&currentBatteryCapacity=5000.0&hash=&registrationData="
    )
    aioclient_mock.get(request_url, status=429)

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
        runtime._clock = VirtualClock(NOW, ClockRate.PAUSED)
        runtime._live_forecast_now = lambda: NOW

        aioclient_mock.clear_requests()
        aioclient_mock.get(request_url, json=_maximum_schema5_forecast())
        await runtime.coordinator.async_request_refresh()
        await hass.async_block_till_done()

        state = hass.states.get(_entity_id(hass, entry.entry_id, "forecast_diagnostics"))
        assert state is not None
        forecast = state.attributes["forecast"]
        assert isinstance(forecast, dict)
        periods = forecast["periods"]
        assert isinstance(periods, list)
        assert len(periods) == 48
        assert periods[0]["decisionTrace"]
        assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
async def test_late_coordinator_update_after_unload_is_inert() -> None:
    """An already-scheduled coordinator listener cannot revive an unloaded entry."""

    forecast = build_snapshot(_observed_forecast()).direct_forecast
    assert forecast is not None

    class TaskHass:
        task: asyncio.Task[None] | None = None

        def async_create_task(self, coroutine: object) -> asyncio.Task[None]:
            assert asyncio.iscoroutine(coroutine)
            self.task = asyncio.create_task(coroutine)
            return self.task

    hass = TaskHass()
    runtime = HorizonIQEntryRuntime(
        SimpleNamespace(
            data=HorizonIQSnapshot(
                direct_forecast=forecast,
                forecast_freshness=ForecastFreshness.FRESH,
                publication_sequence=1,
            )
        ),
        "late-update-registration",
    )
    runtime.simulator_enabled = True
    runtime._config = BatteryConfig(10_000, 2_000, 2_000, 2_000)
    runtime._state = BatteryState(5_000)
    runtime._clock = VirtualClock(NOW, ClockRate.PAUSED)
    runtime._live_forecast_now = lambda: NOW
    runtime._hass = hass

    runtime._on_coordinator_forecast()
    assert hass.task is not None
    await runtime.async_unload()
    await hass.task

    assert runtime.simulator_enabled is False
    assert runtime.forecast_health != "healthy"


@pytest.mark.asyncio
async def test_two_paused_entries_stage_isolated_forecasts() -> None:
    """Each paused virtual battery processes only its own coordinator forecast."""
    forecast = build_snapshot(_observed_forecast()).direct_forecast
    assert forecast is not None
    first = HorizonIQEntryRuntime(SimpleNamespace(), "first-registration")
    second = HorizonIQEntryRuntime(SimpleNamespace(), "second-registration")
    for runtime in (first, second):
        runtime.simulator_enabled = True
        runtime._config = BatteryConfig(10_000, 2_000, 2_000, 2_000)
        runtime._state = BatteryState(5_000)
        runtime._clock = VirtualClock(NOW, ClockRate.PAUSED)
        runtime._live_forecast_now = lambda: NOW

    await first._async_stage_forecast_snapshot(
        HorizonIQSnapshot(
            direct_forecast=forecast,
            forecast_freshness=ForecastFreshness.FRESH,
            publication_sequence=1,
        )
    )

    assert first.forecast_health == "healthy"
    assert second.forecast_health == "unavailable"
    assert first.energy_wh == second.energy_wh == 5_000
    assert first.virtual_time_utc == second.virtual_time_utc == NOW


@pytest.mark.asyncio
async def test_newer_invalid_fresh_blocks_queued_older_valid_fresh() -> None:
    """A lock-gated newer invalid event consumes sequence before an older task."""
    forecast = build_snapshot(_observed_forecast()).direct_forecast
    assert forecast is not None
    runtime = HorizonIQEntryRuntime(SimpleNamespace(), "ordered-registration")
    runtime.simulator_enabled = True
    runtime._config = BatteryConfig(10_000, 2_000, 2_000, 2_000)
    runtime._state = BatteryState(5_000)
    runtime._clock = VirtualClock(NOW, ClockRate.PAUSED)
    runtime._live_forecast_now = lambda: NOW

    invalid = HorizonIQSnapshot(
        direct_forecast=object(),  # type: ignore[arg-type]
        forecast_freshness=ForecastFreshness.FRESH,
        publication_sequence=2,
    )
    older_valid = HorizonIQSnapshot(
        direct_forecast=forecast,
        forecast_freshness=ForecastFreshness.FRESH,
        publication_sequence=1,
    )
    await runtime._direct_forecast_lock.acquire()
    try:
        newer_task = asyncio.create_task(runtime._async_stage_forecast_snapshot(invalid))
        older_task = asyncio.create_task(
            runtime._async_stage_forecast_snapshot(older_valid)
        )
    finally:
        runtime._direct_forecast_lock.release()
    await asyncio.gather(newer_task, older_task)

    assert runtime._last_applied_forecast_sequence == 2
    assert runtime.last_command_status is CommandStatus.FALLBACK_INVALID
    assert runtime._command is not None
    assert runtime._command.mode is OperatingMode.SELF_CONSUMPTION
    assert runtime._accepted_command_ids == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("freshness", "sequence"),
    (
        (ForecastFreshness.STALE, 1),
        (ForecastFreshness.MISSING, 2),
    ),
)
async def test_non_fresh_snapshot_with_direct_data_is_invalid_safe(
    freshness: ForecastFreshness,
    sequence: int,
) -> None:
    """Internally inconsistent non-fresh snapshots cannot drive direct control."""
    forecast = build_snapshot(_observed_forecast()).direct_forecast
    assert forecast is not None
    runtime = HorizonIQEntryRuntime(SimpleNamespace(), "inconsistent-registration")
    runtime.simulator_enabled = True
    runtime._config = BatteryConfig(10_000, 2_000, 2_000, 2_000)
    runtime._state = BatteryState(5_000)
    runtime._clock = VirtualClock(NOW, ClockRate.PAUSED)
    runtime._live_forecast_now = lambda: NOW
    if sequence > 1:
        runtime._last_applied_forecast_sequence = sequence - 1

    await runtime._async_stage_forecast_snapshot(
        HorizonIQSnapshot(
            direct_forecast=forecast,
            forecast_freshness=freshness,
            publication_sequence=sequence,
        )
    )

    assert runtime._last_applied_forecast_sequence == sequence
    assert runtime.last_command_status is CommandStatus.FALLBACK_INVALID
    assert runtime._staged_direct_forecast is None
    assert runtime._staged_fresh_snapshot is None
    assert runtime._command is not None
    assert runtime._command.mode is OperatingMode.SELF_CONSUMPTION
    assert runtime._accepted_command_ids == ()


@pytest.mark.asyncio
async def test_queued_older_stale_listener_cannot_overwrite_newer_fresh_forecast() -> None:
    """Sequence ordering makes a late stale callback a pure no-op."""
    forecast = build_snapshot(_observed_forecast()).direct_forecast
    assert forecast is not None
    runtime = HorizonIQEntryRuntime(SimpleNamespace(), "stale-order-registration")
    runtime.simulator_enabled = True
    runtime._config = BatteryConfig(10_000, 2_000, 2_000, 2_000)
    runtime._state = BatteryState(5_000)
    runtime._clock = VirtualClock(NOW, ClockRate.PAUSED)
    runtime._live_forecast_now = lambda: NOW

    fresh = HorizonIQSnapshot(
        direct_forecast=forecast,
        forecast_freshness=ForecastFreshness.FRESH,
        publication_sequence=2,
    )
    stale = HorizonIQSnapshot(
        forecast_freshness=ForecastFreshness.STALE,
        publication_sequence=1,
    )
    await runtime._direct_forecast_lock.acquire()
    try:
        newer = asyncio.create_task(runtime._async_stage_forecast_snapshot(fresh))
        older = asyncio.create_task(runtime._async_stage_forecast_snapshot(stale))
    finally:
        runtime._direct_forecast_lock.release()
    await asyncio.gather(newer, older)

    assert runtime._last_applied_forecast_sequence == 2
    assert runtime._staged_direct_forecast is forecast
    assert runtime.forecast_health == "healthy"


@pytest.mark.asyncio
async def test_newer_stale_listener_clears_prior_fresh_virtual_export_without_accepting_a_command() -> None:
    """A newer stale publication fails closed and leaves the ID ledger untouched."""
    forecast = build_snapshot(_observed_forecast()).direct_forecast
    assert forecast is not None
    runtime = HorizonIQEntryRuntime(SimpleNamespace(), "stale-clear-registration")
    runtime.simulator_enabled = True
    runtime._config = BatteryConfig(10_000, 2_000, 2_000, 2_000)
    runtime._state = BatteryState(5_000)
    runtime._clock = VirtualClock(NOW, ClockRate.PAUSED)
    runtime._live_forecast_now = lambda: NOW
    await runtime._async_stage_forecast_snapshot(
        HorizonIQSnapshot(
            direct_forecast=forecast,
            forecast_freshness=ForecastFreshness.FRESH,
            publication_sequence=1,
        )
    )
    accepted = runtime._accepted_command_ids

    await runtime._async_stage_forecast_snapshot(
        HorizonIQSnapshot(forecast_freshness=ForecastFreshness.STALE, publication_sequence=2)
    )

    assert runtime._staged_direct_forecast is None
    assert runtime._staged_fresh_snapshot is None
    assert runtime._command is not None and runtime._command.mode is OperatingMode.SELF_CONSUMPTION
    assert runtime.active_setpoint_w is None
    assert runtime.last_command_status is CommandStatus.FALLBACK_STALE
    assert runtime._accepted_command_ids == accepted


@pytest.mark.asyncio
async def test_unknown_or_invalid_publication_sequence_is_a_runtime_noop() -> None:
    """Only positive non-boolean increasing coordinator sequences alter runtime state."""
    forecast = build_snapshot(_observed_forecast()).direct_forecast
    assert forecast is not None
    runtime = HorizonIQEntryRuntime(SimpleNamespace(), "invalid-sequence-registration")
    runtime.simulator_enabled = True
    runtime._config = BatteryConfig(10_000, 2_000, 2_000, 2_000)
    runtime._state = BatteryState(5_000)
    runtime._clock = VirtualClock(NOW, ClockRate.PAUSED)
    runtime._live_forecast_now = lambda: NOW
    valid = HorizonIQSnapshot(
        direct_forecast=forecast,
        forecast_freshness=ForecastFreshness.FRESH,
        publication_sequence=1,
    )
    await runtime._async_stage_forecast_snapshot(valid)
    before = (runtime._command, runtime._accepted_command_ids, runtime._last_applied_forecast_sequence)
    runtime.async_checkpoint = AsyncMock()
    runtime._notify_listeners = MagicMock()

    for sequence in (0, True, -1, "2", 1):
        await runtime._async_stage_forecast_snapshot(
            HorizonIQSnapshot(
                direct_forecast=forecast,
                forecast_freshness=ForecastFreshness.FRESH,
                publication_sequence=sequence,  # type: ignore[arg-type]
            )
        )

    assert (runtime._command, runtime._accepted_command_ids, runtime._last_applied_forecast_sequence) == before
    runtime.async_checkpoint.assert_not_awaited()
    runtime._notify_listeners.assert_not_called()

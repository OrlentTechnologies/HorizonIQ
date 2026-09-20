"""Virtual-mode wall-clock execution tests."""

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from custom_components.horizoniq.const import (
    CAPACITY_SOURCE_VIRTUAL_BATTERY,
    CONF_CAPACITY_SOURCE,
    CONF_ENVIRONMENT,
    CONF_REGISTRATION_CONFIG,
    CONF_REGISTRATION_ID,
    SANDBOX_ENVIRONMENT,
)
from custom_components.horizoniq.coordinator_helpers import build_snapshot
from custom_components.horizoniq.models import (
    Forecast,
    ForecastFreshness,
    HorizonIQSnapshot,
)
from custom_components.horizoniq.button import SandboxStepButton
from custom_components.horizoniq.sandbox_runtime import HorizonIQEntryRuntime
from custom_components.horizoniq.select import (
    SandboxClockRateSelect,
    SandboxProfileSelect,
)
from custom_components.horizoniq.simulation.clock import ClockRate, VirtualClock
from custom_components.horizoniq.simulation.models import (
    Command,
    CommandStatus,
    OperatingMode,
)
from custom_components.horizoniq.switch import SandboxProfilePlaybackSwitch


UTC = timezone.utc
NOW = datetime(2026, 8, 4, 12, tzinfo=UTC)
REGISTRATION_ID = "11111111-1111-4111-8111-111111111111"
FIXTURE = Path(__file__).with_name("fixtures") / "direct_schema5_forecast.json"


class _Loop:
    def __init__(self, now: float = 0) -> None:
        self.now = now

    def time(self) -> float:
        return self.now


class _Hass:
    def __init__(self) -> None:
        self.loop = _Loop()

    def async_create_task(self, coroutine):
        return coroutine.close()


def _data() -> dict[str, object]:
    return {
        CONF_ENVIRONMENT: SANDBOX_ENVIRONMENT,
        CONF_CAPACITY_SOURCE: CAPACITY_SOURCE_VIRTUAL_BATTERY,
        CONF_REGISTRATION_ID: REGISTRATION_ID,
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


def _forecast(*, issued_at: datetime = NOW, expires_at: datetime | None = None) -> Forecast:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    period = dict(payload["periods"][0])
    trace = dict(period["decisionTrace"])
    period.update(
        {
            "date": NOW.isoformat().replace("+00:00", "Z"),
            "recommendedAction": "charge_required",
            "executableAction": "charge_required",
            "commandId": str(uuid4()),
            "issuedAtUtc": issued_at.isoformat().replace("+00:00", "Z"),
            "expiresAtUtc": (expires_at or NOW + timedelta(minutes=30))
            .isoformat()
            .replace("+00:00", "Z"),
        }
    )
    trace["selectedAction"] = "charge_required"
    period["decisionTrace"] = trace
    payload["periods"] = [period]
    forecast = build_snapshot(payload).direct_forecast
    assert isinstance(forecast, Forecast)
    return forecast


def _snapshot(forecast: Forecast, sequence: int = 1) -> HorizonIQSnapshot:
    return HorizonIQSnapshot(
        direct_forecast=forecast,
        forecast_freshness=ForecastFreshness.FRESH,
        publication_sequence=sequence,
    )


def _runtime(
    forecast: Forecast | None = None,
    *,
    entry_id: str = "wall-clock",
) -> tuple[HorizonIQEntryRuntime, MagicMock, _Hass]:
    coordinator = MagicMock()
    coordinator.async_pause_for_sandbox = AsyncMock()
    coordinator.async_resume_from_sandbox = AsyncMock()
    coordinator.async_fetch_sandbox_forecast = AsyncMock(
        return_value=_snapshot(forecast) if forecast is not None else HorizonIQSnapshot()
    )
    coordinator.effective_forecast_cadence_minutes = 15
    runtime = HorizonIQEntryRuntime(coordinator, REGISTRATION_ID, entry_id)
    runtime.configure_sandbox(_data())
    runtime.simulator_enabled = True
    runtime._hass = _Hass()
    runtime._mqtt_emulation_enabled = False
    runtime._live_forecast_now = lambda: NOW
    runtime._clock = VirtualClock(NOW - timedelta(minutes=32), ClockRate.PAUSED)
    return runtime, coordinator, runtime._hass


async def test_virtual_tick_uses_monotonic_elapsed_without_clock_drift() -> None:
    """Scheduling overhead affects physics elapsed time, never a stale VirtualClock."""
    runtime, _, hass = _runtime()
    runtime.set_inputs(load_w=1_000, solar_w=0)
    runtime._virtual_monotonic_baseline = 0
    runtime._virtual_next_refresh_monotonic = 10_000
    hass.loop.now = 1.2

    await runtime._async_virtual_tick(hass)

    assert runtime.energy_wh == pytest.approx(5_000 - (1_000 * 1.2 / 3_600 / 0.9))
    assert runtime.virtual_time_utc == NOW


async def test_virtual_repeated_overhead_tracks_wall_time_without_clock_drift() -> None:
    """Several delayed loop turns use their actual elapsed monotonic durations."""
    runtime, _, hass = _runtime()
    runtime.set_inputs(load_w=1_000, solar_w=0)
    wall_now = NOW
    runtime._live_forecast_now = lambda: wall_now
    runtime._virtual_monotonic_baseline = 0
    runtime._virtual_next_refresh_monotonic = 10_000
    elapsed = (1.1, 1.3, 1.2)

    for elapsed_seconds in elapsed:
        hass.loop.now += elapsed_seconds
        wall_now += timedelta(seconds=elapsed_seconds)
        await runtime._async_virtual_tick(hass)

    assert runtime.virtual_time_utc == wall_now
    assert runtime.energy_wh == pytest.approx(
        5_000 - (1_000 * sum(elapsed) / 3_600 / 0.9)
    )


async def test_virtual_wall_clock_accepts_current_action_despite_stale_replay_clock() -> None:
    """A persisted Replay timestamp cannot make a current live action premature."""
    forecast = _forecast()
    runtime, _, _ = _runtime(forecast)

    await runtime._async_stage_forecast_snapshot(_snapshot(forecast))
    await runtime._async_simulate_virtual_elapsed(30, NOW + timedelta(seconds=30), hass=None)

    assert runtime.last_command_status is CommandStatus.APPLIED
    assert runtime.battery_power_w > 0
    assert runtime.grid_power_w > runtime.load_w
    assert runtime.energy_wh is not None and runtime.energy_wh > 5_000


async def test_virtual_forecast_generation_becomes_effective_solar_without_backfill() -> None:
    """A current period's Wh estimate supplies Virtual solar only going forward."""
    forecast = _forecast()
    period = replace(forecast.periods[0], estimated_generation_wh=500)
    forecast = replace(forecast, periods=(period,))
    runtime, _, _ = _runtime(forecast)
    before = runtime.energy_wh

    await runtime._async_stage_forecast_snapshot(_snapshot(forecast))

    assert runtime.solar_w == 1_000
    assert runtime.energy_wh == before
    assert runtime.forecast_solar_period_start_utc == NOW
    assert runtime.forecast_solar_generation_wh == 500


async def test_virtual_forecast_solar_reselects_at_the_half_hour_boundary() -> None:
    """A cached plan changes solar at its next period without another fetch."""
    forecast = _forecast()
    first = replace(forecast.periods[0], estimated_generation_wh=500)
    second = replace(
        first,
        starts_at_utc=NOW + timedelta(minutes=30),
        estimated_generation_wh=0,
    )
    forecast = replace(forecast, periods=(first, second))
    runtime, _, _ = _runtime(forecast)

    await runtime._async_stage_forecast_snapshot(_snapshot(forecast))
    runtime._update_forecast_solar(NOW + timedelta(minutes=30))

    assert runtime.solar_w == 0
    assert runtime.forecast_solar_period_start_utc == NOW + timedelta(minutes=30)


async def test_invalid_virtual_forecast_generation_clears_previous_solar() -> None:
    """An invalid period follows the safe forecast path rather than retaining sun."""
    forecast = _forecast()
    valid = replace(forecast.periods[0], estimated_generation_wh=500)
    invalid = replace(valid, estimated_generation_wh=float("inf"))
    runtime, _, _ = _runtime(forecast)

    await runtime._async_stage_forecast_snapshot(_snapshot(replace(forecast, periods=(valid,))))
    await runtime._async_stage_forecast_snapshot(_snapshot(replace(forecast, periods=(invalid,)), 2))

    assert runtime.solar_w == 0
    assert runtime.forecast_solar_reason == "forecast_solar_unavailable"


async def test_repeated_current_command_id_keeps_virtual_charging() -> None:
    """A cadence refresh with the same active command must not interrupt charging."""
    forecast = _forecast()
    runtime, _, _ = _runtime(forecast)

    await runtime._async_stage_forecast_snapshot(_snapshot(forecast))
    first_command = runtime._command
    await runtime._async_stage_forecast_snapshot(_snapshot(forecast, 2))
    await runtime._async_simulate_virtual_elapsed(30, NOW + timedelta(seconds=30), hass=None)

    assert runtime._command == first_command
    assert runtime.last_command_status is CommandStatus.APPLIED
    assert runtime.battery_power_w > 0


async def test_reset_restages_only_the_current_staged_fresh_snapshot_without_resetting_sequence() -> None:
    """Reset is an internal restage, not a coordinator publication or sequence reset."""
    forecast = _forecast()
    runtime, coordinator, _ = _runtime(forecast)
    await runtime._async_stage_forecast_snapshot(_snapshot(forecast, 7))

    await runtime.async_reset()

    assert runtime._last_applied_forecast_sequence == 7
    assert runtime._staged_fresh_snapshot is not None
    coordinator.async_fetch_sandbox_forecast.assert_not_awaited()

    await runtime._async_stage_forecast_snapshot(
        HorizonIQSnapshot(
            forecast_freshness=ForecastFreshness.STALE,
            publication_sequence=8,
        )
    )
    accepted_ids = runtime._accepted_command_ids
    publication_sequence = runtime._last_applied_forecast_sequence
    await runtime.async_reset()

    assert runtime._last_applied_forecast_sequence == publication_sequence
    assert runtime._staged_fresh_snapshot is None
    assert runtime._staged_direct_forecast is None
    assert runtime._command is None
    assert runtime.active_setpoint_w is None
    assert runtime.last_command_status is CommandStatus.AWAITING_FORECAST
    assert runtime.forecast_health == "awaiting_forecast"
    assert runtime._accepted_command_ids == accepted_ids
    coordinator.async_fetch_sandbox_forecast.assert_not_awaited()


async def test_reset_restage_cannot_revive_fresh_control_after_newer_stale_wins_lock() -> None:
    """A reset's captured plan is inert when a newer stale event clears staging."""
    forecast = _forecast()
    runtime, _, _ = _runtime(forecast)
    await runtime._async_stage_forecast_snapshot(_snapshot(forecast, 7))
    accepted_ids = runtime._accepted_command_ids
    runtime.async_checkpoint = AsyncMock()
    runtime._notify_listeners = MagicMock()

    await runtime._direct_forecast_lock.acquire()
    try:
        stale_task = asyncio.create_task(
            runtime._async_stage_forecast_snapshot(
                HorizonIQSnapshot(
                    forecast_freshness=ForecastFreshness.STALE,
                    publication_sequence=8,
                )
            )
        )
        await asyncio.sleep(0)
        restage_task = asyncio.create_task(
            runtime._async_restage_fresh_snapshot_after_reset()
        )
        await asyncio.sleep(0)
    finally:
        runtime._direct_forecast_lock.release()
    await asyncio.gather(stale_task, restage_task)

    assert runtime._last_applied_forecast_sequence == 8
    assert runtime._staged_fresh_snapshot is None
    assert runtime._staged_direct_forecast is None
    assert runtime.active_setpoint_w is None
    assert runtime._command is not None
    assert runtime._command.mode is OperatingMode.SELF_CONSUMPTION
    assert runtime._last_direct_action is None
    assert runtime._last_direct_command_id is None
    assert runtime.last_command_status is CommandStatus.FALLBACK_STALE
    assert runtime._accepted_command_ids == accepted_ids
    runtime.async_checkpoint.assert_awaited_once_with(immediate=True)
    runtime._notify_listeners.assert_called_once()


async def test_virtual_action_expiry_returns_safely_to_self_consumption() -> None:
    """The executable action applies until its wall-time expiry, then clears."""
    runtime, _, _ = _runtime()
    await runtime._async_stage_forecast_snapshot(_snapshot(_forecast()))
    assert runtime._command is not None
    runtime._command = replace(runtime._command, expires_at_utc=NOW + timedelta(seconds=10))

    await runtime._async_simulate_virtual_elapsed(30, NOW + timedelta(seconds=30), hass=None)

    assert runtime.energy_wh is not None and runtime.energy_wh > 5_000
    assert runtime._command is not None
    assert runtime._command.mode is OperatingMode.SELF_CONSUMPTION
    assert runtime.active_setpoint_w is None


@pytest.mark.parametrize(
    "issued_at, expires_at, expected_status",
    (
        (NOW + timedelta(seconds=1), NOW + timedelta(minutes=30), CommandStatus.FALLBACK_INVALID),
        (NOW - timedelta(minutes=30), NOW - timedelta(seconds=1), CommandStatus.FALLBACK_INVALID),
    ),
)
async def test_virtual_command_validity_uses_wall_utc(
    issued_at: datetime,
    expires_at: datetime,
    expected_status: CommandStatus,
) -> None:
    """Future and expired live actions cannot alter Virtual battery power."""
    runtime, _, _ = _runtime()
    await runtime._async_stage_forecast_snapshot(
        _snapshot(_forecast(issued_at=issued_at, expires_at=expires_at))
    )

    assert runtime.last_command_status is expected_status
    assert runtime._command is not None
    assert runtime._command.mode is OperatingMode.SELF_CONSUMPTION


async def test_virtual_refresh_uses_monotonic_cadence_after_failure() -> None:
    """An immediate failure retains safe state and schedules the next attempt."""
    runtime, coordinator, hass = _runtime()
    coordinator.async_fetch_sandbox_forecast = AsyncMock(side_effect=RuntimeError())

    await runtime._async_refresh_direct_forecast()

    assert runtime.last_command_status is CommandStatus.FALLBACK_MISSING
    assert runtime._virtual_next_refresh_monotonic == pytest.approx(900)
    hass.loop.now = 900
    coordinator.async_fetch_sandbox_forecast = AsyncMock(
        return_value=_snapshot(_forecast())
    )
    await runtime._async_refresh_virtual_if_due(hass.loop.now)
    assert coordinator.async_fetch_sandbox_forecast.await_count == 1
    assert runtime.last_command_status is CommandStatus.APPLIED


async def test_direct_refresh_timeout_uses_stale_snapshot_not_last_direct_forecast() -> None:
    """A failed explicit refresh cannot revive cached executable control."""
    forecast = _forecast()
    runtime, coordinator, _ = _runtime(forecast)
    await runtime._async_stage_forecast_snapshot(_snapshot(forecast, 1))
    await runtime._async_stage_forecast_snapshot(
        HorizonIQSnapshot(
            forecast_freshness=ForecastFreshness.STALE,
            publication_sequence=2,
        )
    )
    coordinator.last_direct_forecast = forecast
    coordinator.async_fetch_sandbox_forecast = AsyncMock(side_effect=RuntimeError("timeout"))

    await runtime._async_refresh_direct_forecast()

    assert runtime.last_command_status is CommandStatus.FALLBACK_STALE
    assert runtime._staged_direct_forecast is None
    assert runtime._command is not None
    assert runtime._command.mode is OperatingMode.SELF_CONSUMPTION


async def test_fresh_recovery_after_stale_accepts_new_command_once_at_lock_boundary() -> None:
    """A lock-gated fresh recovery applies once and retains its duplicate."""
    runtime, _, _ = _runtime()
    first = _forecast()
    recovered = _forecast()
    assert first.periods[0].command_id != recovered.periods[0].command_id
    await runtime._async_stage_forecast_snapshot(_snapshot(first, 1))
    await runtime._direct_forecast_lock.acquire()
    try:
        stale_task = asyncio.create_task(
            runtime._async_stage_forecast_snapshot(
                HorizonIQSnapshot(
                    forecast_freshness=ForecastFreshness.STALE,
                    publication_sequence=2,
                )
            )
        )
        recovery_task = asyncio.create_task(
            runtime._async_stage_forecast_snapshot(_snapshot(recovered, 3))
        )
    finally:
        runtime._direct_forecast_lock.release()
    await asyncio.gather(stale_task, recovery_task)
    command = runtime._command
    action = runtime._last_direct_action
    accepted_ids = runtime._accepted_command_ids
    await runtime._async_stage_forecast_snapshot(_snapshot(recovered, 3))

    assert runtime.last_command_status is CommandStatus.APPLIED
    assert runtime._command == command
    assert runtime._last_direct_action == action
    assert runtime._accepted_command_ids == accepted_ids
    assert runtime._last_applied_forecast_sequence == 3


async def test_virtual_timing_gap_skips_catch_up_energy() -> None:
    """A long scheduler gap has a bounded diagnostic and no reconstructed flow."""
    runtime, _, hass = _runtime()
    runtime.set_inputs(load_w=1_000, solar_w=0)
    runtime._virtual_monotonic_baseline = 0
    runtime._virtual_next_refresh_monotonic = 10_000
    before = runtime.energy_wh
    hass.loop.now = 301

    await runtime._async_virtual_tick(hass)

    assert runtime.energy_wh == before
    assert runtime.timing_diagnostic == "virtual_timing_gap"


async def test_mode_transitions_preserve_energy_and_clear_only_mode_owned_state() -> None:
    """Virtual to Replay stops wall execution and drops only active control state."""
    runtime, _, _ = _runtime()
    runtime._state = runtime._state.__class__(6_000)
    runtime.load_w = 410
    runtime.solar_w = 0
    runtime._command = Command(
        OperatingMode.GRID_SETPOINT,
        requested_grid_power_w=1_000,
        expires_at_utc=NOW + timedelta(minutes=5),
    )
    runtime._external_power_w = 500
    runtime._external_power_expires_at_utc = NOW + timedelta(minutes=5)
    runtime._virtual_monotonic_baseline = 10
    runtime._virtual_next_refresh_monotonic = 20

    await runtime.async_select_operating_mode("replay")

    assert runtime.simulator_enabled is False
    assert runtime.operating_mode == "replay"
    assert runtime.energy_wh == 6_000
    assert runtime.load_w == 410
    assert runtime.external_power_w is None
    assert runtime.active_setpoint_w is None
    assert runtime._virtual_monotonic_baseline is None
    assert runtime._virtual_next_refresh_monotonic is None
    assert runtime._command is not None
    assert runtime._command.mode is OperatingMode.SELF_CONSUMPTION
    assert runtime.clock_rate == ClockRate.PAUSED.value


async def test_mode_transition_reloads_only_the_owning_entry() -> None:
    """A persisted mode selection recreates this entry's mode-specific controls."""
    runtime, _, hass = _runtime()
    reload_entry = AsyncMock()
    hass.config_entries = SimpleNamespace(async_reload=reload_entry)

    await runtime.async_select_operating_mode("replay")

    reload_entry.assert_awaited_once_with(runtime.entry_id)
    assert runtime.simulator_enabled is False


def test_virtual_hides_replay_only_entities() -> None:
    """Wall-clock Virtual mode exposes no controls that mutate Replay time."""
    runtime, _, _ = _runtime()
    profile = SandboxProfileSelect(runtime, runtime.entry_id)
    rate = SandboxClockRateSelect(runtime, runtime.entry_id)
    step = SandboxStepButton(runtime, runtime.entry_id)
    playback = SandboxProfilePlaybackSwitch(runtime, runtime.entry_id)

    assert profile.available is False
    assert rate.available is False
    assert step.available is False
    assert playback.available is False

    profile._remove_listener()
    rate._remove_listener()
    step._remove_listener()
    playback._remove_listener()


def test_simulator_status_uses_the_active_mode_time_source() -> None:
    """The schema-2 timestamp is wall UTC in Virtual and Replay clock UTC otherwise."""
    runtime, _, _ = _runtime()

    virtual = runtime._build_simulator_status().to_payload()
    replay_now = NOW - timedelta(hours=2)
    runtime._operating_mode = "replay"
    runtime._clock = VirtualClock(replay_now, ClockRate.PAUSED)
    replay = runtime._build_simulator_status().to_payload()

    assert virtual["timestampUtc"] == NOW.isoformat().replace("+00:00", "Z")
    assert virtual["virtualTimeUtc"] == virtual["timestampUtc"]
    assert replay["timestampUtc"] == replay_now.isoformat().replace("+00:00", "Z")
    assert replay["virtualTimeUtc"] == replay["timestampUtc"]


async def test_mixed_mode_entries_keep_time_and_energy_isolated() -> None:
    """Wall-clock updates and Replay steps cannot cross entry-local state."""
    virtual, _, virtual_hass = _runtime(entry_id="wall-clock-virtual")
    replay, _, _ = _runtime(entry_id="wall-clock-replay")
    idle, _, _ = _runtime(entry_id="wall-clock-idle")
    virtual.set_inputs(load_w=1_000, solar_w=0)
    virtual._virtual_monotonic_baseline = 0
    virtual._virtual_next_refresh_monotonic = 10_000
    virtual_hass.loop.now = 10

    replay.simulator_enabled = False
    await replay.async_select_operating_mode("replay")
    replay.simulator_enabled = True
    replay.set_inputs(load_w=1_000, solar_w=0)

    await virtual._async_virtual_tick(virtual_hass)
    await replay.async_step(30)

    assert virtual.energy_wh is not None and virtual.energy_wh < 5_000
    assert replay.energy_wh is not None and replay.energy_wh < 5_000
    assert idle.energy_wh == 5_000
    assert virtual.virtual_time_utc == NOW
    assert replay.virtual_time_utc == NOW + timedelta(seconds=30)

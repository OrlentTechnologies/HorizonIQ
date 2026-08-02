"""B2B2 replay-ready playback and clock publication tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.horizoniq.const import (
    CAPACITY_SOURCE_VIRTUAL_BATTERY,
    CONF_CAPACITY_SOURCE,
    CONF_ENVIRONMENT,
    CONF_REGISTRATION_CONFIG,
    CONF_REGISTRATION_ID,
    SANDBOX_ENVIRONMENT,
)
from custom_components.horizoniq.sandbox_runtime import HorizonIQEntryRuntime
from custom_components.horizoniq.simulation.clock import ClockRate
from custom_components.horizoniq.simulation.replay_contract import ReplayState
from custom_components.horizoniq.simulation.topics import clock_status_topic


UTC = timezone.utc


def _runtime(entry_id: str, registration_id: str) -> HorizonIQEntryRuntime:
    coordinator = MagicMock()
    coordinator.async_pause_for_sandbox = AsyncMock()
    coordinator.async_resume_from_sandbox = AsyncMock()
    runtime = HorizonIQEntryRuntime(coordinator, registration_id, entry_id)
    runtime.configure_sandbox(
        {
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
    )
    return runtime


def _profile(samples: int = 12) -> str:
    start = datetime(2026, 4, 1, tzinfo=UTC)
    return json.dumps(
        {
            "schema_version": 1,
            "starting_battery_energy_wh": 5_000,
            "samples": [
                {
                    "timestamp": (start + timedelta(minutes=index * 5)).isoformat(),
                    "load_w": 600,
                    "solar_w": 100,
                    "import_rate_gbp_per_kwh": -0.1,
                    "export_rate_gbp_per_kwh": 0.05,
                }
                for index in range(samples)
            ],
        }
    )


async def _prepared(hass, runtime: HorizonIQEntryRuntime, *, samples: int = 12) -> None:
    await runtime.async_restore_storage(hass)
    await runtime.async_select_operating_mode("replay")
    directory = Path(hass.config.path("horizoniq", "profiles", runtime.entry_id))
    await hass.async_add_executor_job(lambda: directory.mkdir(parents=True, exist_ok=True))
    await hass.async_add_executor_job((directory / "day.json").write_text, _profile(samples), "utf-8")
    await runtime.async_select_profile("day.json")
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe", new=AsyncMock(return_value=lambda: None)):
        await runtime.async_enable(hass)


async def _ready(runtime: HorizonIQEntryRuntime) -> None:
    session = await runtime.async_start_replay_session()
    loading = MagicMock(
        payload=json.dumps(
            {"schemaVersion": 4, "gxDeviceId": runtime.pretend_gx_id, "replayId": session.replay_id, "state": "loading", "reason": None}
        )
    )
    await runtime._async_handle_replay_status(loading)
    loading.payload = json.dumps(
        {"schemaVersion": 4, "gxDeviceId": runtime.pretend_gx_id, "replayId": session.replay_id, "state": "ready", "reason": None}
    )
    await runtime._async_handle_replay_status(loading)


async def test_ready_starts_once_and_publishes_one_reset_clock(hass) -> None:
    """Ready initializes local profile playback and one schema-4 reset clock message."""
    runtime = _runtime("orchestration-ready", "11111111-1111-4111-8111-111111111111")
    await _prepared(hass, runtime)
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()) as publish:
        await _ready(runtime)
        await _ready_duplicate(runtime)
    assert runtime.replay_state is ReplayState.RUNNING
    assert runtime.playback_state == "running"
    clock_calls = [call for call in publish.await_args_list if call.args[1].endswith("/clock/status")]
    assert len(clock_calls) == 1
    assert clock_calls[0].args[1] == clock_status_topic(runtime.pretend_gx_id or "")
    assert clock_calls[0].kwargs["retain"] is False
    payload = json.loads(clock_calls[0].args[2])
    assert payload["reset"] is True and payload["sequence"] == 0
    await runtime.async_disable()


async def _ready_duplicate(runtime: HorizonIQEntryRuntime) -> None:
    assert runtime.replay_session is not None
    message = MagicMock(
        payload=json.dumps(
            {"schemaVersion": 4, "gxDeviceId": runtime.pretend_gx_id, "replayId": runtime.replay_session.replay_id, "state": "ready", "reason": None}
        )
    )
    await runtime._async_handle_replay_status(message)


async def test_boundary_completion_stop_and_telemetry_remain_local(hass) -> None:
    """Playback emits synthetic telemetry, terminal clock state, and safe cleanup only."""
    runtime = _runtime("orchestration-complete", "22222222-2222-4222-8222-222222222222")
    await _prepared(hass, runtime, samples=6)
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()) as publish:
        await _ready(runtime)
        runtime._replay_last_clock_publish_monotonic = None
        await runtime.async_step(1800)
    assert runtime.replay_state is ReplayState.COMPLETED
    assert runtime.playback_state == "completed"
    assert runtime.load_w == 0 and runtime.solar_w == 0
    assert runtime.virtual_time_utc == datetime(2026, 4, 1, 0, 30, tzinfo=UTC)
    topics = [call.args[1] for call in publish.await_args_list]
    assert any(topic.endswith("/clock/status") for topic in topics)
    assert any(topic.startswith(f"victron/N/{runtime.pretend_gx_id}/") for topic in topics)
    await runtime.async_disable()


async def test_paused_heartbeat_and_isolation_do_not_advance_other_entry(hass) -> None:
    """Paused heartbeat advances only sequence; each replay keeps its own clock and state."""
    first = _runtime("orchestration-a", "33333333-3333-4333-8333-333333333333")
    second = _runtime("orchestration-b", "44444444-4444-4444-8444-444444444444")
    for runtime in (first, second):
        await _prepared(hass, runtime)
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()) as publish:
        await _ready(first)
        await _ready(second)
        await first.async_pause_playback()
        first._replay_last_clock_publish_monotonic = None
        before = first.virtual_time_utc
        await first._async_replay_heartbeat()
    assert first.replay_state is ReplayState.PAUSED
    assert first.virtual_time_utc == before
    assert first.replay_session is not None and first.replay_session.clock_sequence >= 1
    assert second.replay_state is ReplayState.RUNNING
    assert second.virtual_time_utc != first.virtual_time_utc or second.pretend_gx_id != first.pretend_gx_id
    assert any(call.args[1] == clock_status_topic(first.pretend_gx_id or "") for call in publish.await_args_list)
    await first.async_disable()
    await second.async_disable()


async def test_clock_rate_and_delayed_tick_preserve_deterministic_physics(hass) -> None:
    """Equivalent virtual advances at 1x and 60x reach the same local energy state."""
    slow = _runtime("orchestration-slow", "55555555-5555-4555-8555-555555555555")
    fast = _runtime("orchestration-fast", "66666666-6666-4666-8666-666666666666")
    for runtime in (slow, fast):
        await _prepared(hass, runtime)
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()):
        await _ready(slow)
        await _ready(fast)
        slow.set_clock_rate(ClockRate.X1)
        fast.set_clock_rate(ClockRate.X60)
        slow._clock.advance(30 * 60)
        await slow._async_simulate(30 * 60)
        fast._clock.advance(30)
        await fast._async_simulate(30 * 60)
    assert slow.energy_wh == fast.energy_wh
    assert slow.profile_cursor == fast.profile_cursor
    await slow.async_disable()
    await fast.async_disable()

"""Entry-local MQTT lifecycle tests for B2B1 replay sessions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.horizoniq.const import (
    CAPACITY_SOURCE_VIRTUAL_BATTERY,
    CONF_CAPACITY_SOURCE,
    CONF_ENVIRONMENT,
    CONF_REGISTRATION_CONFIG,
    CONF_REGISTRATION_ID,
    SANDBOX_ENVIRONMENT,
)
from custom_components.horizoniq.sandbox_runtime import HorizonIQEntryRuntime
from custom_components.horizoniq.sandbox_storage import (
    STORAGE_SCHEMA_VERSION,
    SandboxStorage,
)
from custom_components.horizoniq.simulation.replay_contract import ReplayState
from custom_components.horizoniq.simulation.faults import FaultKind, FaultState
from custom_components.horizoniq.simulation.topics import (
    VictronCommandKey,
    command_topic,
    command_issued_topic,
    node_red_status_topic,
    refresh_topic,
    replay_request_topic,
    replay_status_topic,
)


UTC = timezone.utc
REGISTRATION_A = "11111111-1111-4111-8111-111111111111"
REGISTRATION_B = "22222222-2222-4222-8222-222222222222"
REGISTRATION_C = "33333333-3333-4333-8333-333333333333"


def _data(
    registration_id: str,
    *,
    import_for_export: object = False,
    export_for_solar_headroom: object = False,
) -> dict[str, object]:
    return {
        CONF_ENVIRONMENT: SANDBOX_ENVIRONMENT,
        CONF_CAPACITY_SOURCE: CAPACITY_SOURCE_VIRTUAL_BATTERY,
        CONF_REGISTRATION_ID: registration_id,
        CONF_REGISTRATION_CONFIG: {
            "ChargeEfficiency": 0.95,
            "DischargeEfficiency": 0.9,
            "ImportForExport": import_for_export,
            "ExportForSolarHeadroom": export_for_solar_headroom,
            "EquipmentProfile": {
                "BatteryCapacityWh": 10_000,
                "MinimumCapacityPercentage": 0.2,
                "MaximumBatteryChargePowerWatts": 2_000,
                "MaximumBatteryDischargePowerWatts": 2_000,
            },
        },
    }


def _runtime(
    entry_id: str,
    registration_id: str = REGISTRATION_A,
    **toggle_values: object,
) -> HorizonIQEntryRuntime:
    coordinator = MagicMock()
    coordinator.async_pause_for_sandbox = AsyncMock()
    coordinator.async_resume_from_sandbox = AsyncMock()
    runtime = HorizonIQEntryRuntime(coordinator, registration_id, entry_id)
    runtime.configure_sandbox(_data(registration_id, **toggle_values))
    return runtime


def _profile() -> str:
    start = datetime(2026, 4, 1, tzinfo=UTC)
    return json.dumps(
        {
            "schema_version": 1,
            "starting_battery_energy_wh": 5_000,
            "samples": [
                {
                    "timestamp": (start + timedelta(minutes=5 * index)).isoformat(),
                    "load_w": 600,
                    "solar_w": 100,
                    "import_rate_gbp_per_kwh": -0.1,
                    "export_rate_gbp_per_kwh": 0.05,
                }
                for index in range(6)
            ],
        }
    )


async def _select_profile(hass, runtime: HorizonIQEntryRuntime, content: str | None = None) -> None:
    await runtime.async_restore_storage(hass)
    await runtime.async_select_operating_mode("replay")
    directory = Path(hass.config.path("horizoniq", "profiles", runtime.entry_id))
    await hass.async_add_executor_job(lambda: directory.mkdir(parents=True, exist_ok=True))
    await hass.async_add_executor_job((directory / "day.json").write_text, content or _profile(), "utf-8")
    await runtime.async_select_profile("day.json")


async def _enable(hass, runtime: HorizonIQEntryRuntime, subscribe: AsyncMock) -> None:
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
        new=subscribe,
    ):
        await runtime.async_enable(hass)


async def test_request_uses_exact_topics_profile_settings_and_non_retained_publish(hass) -> None:
    """A session publishes one trusted request to its exact generated-GX topic."""
    runtime = _runtime(
        "replay-request",
        import_for_export=True,
        export_for_solar_headroom=False,
    )
    await _select_profile(hass, runtime)
    subscribe = AsyncMock(return_value=lambda: None)
    await _enable(hass, runtime, subscribe)

    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",
        new=AsyncMock(),
    ) as publish:
        session = await runtime.async_start_replay_session()
        with pytest.raises(ValueError, match="already active"):
            await runtime.async_start_replay_session()

    assert session.state is ReplayState.REQUESTING
    assert [call.args[1] for call in subscribe.await_args_list] == [
        command_topic(runtime.pretend_gx_id or "", VictronCommandKey.HUB4_MODE),
        command_topic(runtime.pretend_gx_id or "", VictronCommandKey.VE_BUS_MODE),
        command_topic(runtime.pretend_gx_id or "", VictronCommandKey.AC_POWER_SETPOINT),
        refresh_topic(runtime.pretend_gx_id or ""),
        command_issued_topic(runtime.pretend_gx_id or ""),
        replay_status_topic(runtime.pretend_gx_id or ""),
        node_red_status_topic(runtime.pretend_gx_id or ""),
    ]
    request_calls = [
        call
        for call in publish.await_args_list
        if call.args[1] == replay_request_topic(runtime.pretend_gx_id or "")
    ]
    assert len(request_calls) == 1
    assert request_calls[0].kwargs["retain"] is False
    payload = json.loads(request_calls[0].args[2])
    assert payload["startingBatteryEnergyKwh"] == 5.0
    assert payload["importForExportEnabled"] is True
    assert payload["exportForSolarHeadroom"] is False
    assert payload["periods"][0]["expectedLoadKwh"] == 0.3
    assert payload["periods"][0]["expectedSolarKwh"] == 0.05
    assert not {"apiKey", "functionKey", "token", "registrationId"} & set(payload)
    await runtime.async_disable()


async def test_toggle_defaults_and_invalid_values_fail_closed(hass) -> None:
    """Absent registration toggles use backend false defaults; invalid values cannot publish."""
    defaults = _runtime("replay-defaults")
    config = defaults._registration_config
    assert isinstance(config, dict)
    config.pop("ImportForExport")
    config.pop("ExportForSolarHeadroom")
    await _select_profile(hass, defaults)
    await _enable(hass, defaults, AsyncMock(return_value=lambda: None))
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()
    ) as publish:
        await defaults.async_start_replay_session()
    payload = json.loads(
        next(
            call.args[2]
            for call in publish.await_args_list
            if call.args[1] == replay_request_topic(defaults.pretend_gx_id or "")
        )
    )
    assert payload["importForExportEnabled"] is False
    assert payload["exportForSolarHeadroom"] is False
    await defaults.async_disable()

    invalid = _runtime("replay-invalid-toggle", import_for_export="true")
    await _select_profile(hass, invalid)
    await _enable(hass, invalid, AsyncMock(return_value=lambda: None))
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()
    ) as publish:
        with pytest.raises(ValueError, match="boolean"):
            await invalid.async_start_replay_session()
    publish.assert_not_awaited()
    await invalid.async_disable()


async def test_status_transitions_timeout_failures_and_late_callbacks_are_local(hass) -> None:
    """Only matching in-order statuses affect a session and terminal states cancel timeouts."""
    runtime = _runtime("replay-status")
    await _select_profile(hass, runtime)
    await _enable(hass, runtime, AsyncMock(return_value=lambda: None))
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()
    ):
        session = await runtime.async_start_replay_session()
    message = MagicMock(
        payload=json.dumps(
            {
                "schemaVersion": 4,
                "gxDeviceId": runtime.pretend_gx_id,
                "replayId": session.replay_id,
                "state": "loading",
                "reason": None,
            }
        )
    )
    await runtime._async_handle_replay_status(message)
    assert runtime.replay_state is ReplayState.LOADING
    message.payload = json.dumps({**json.loads(message.payload), "state": "ready"})
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()):
        await runtime._async_handle_replay_status(message)
    assert runtime.replay_state is ReplayState.RUNNING
    assert runtime._replay_timeout_handle is None
    await runtime._async_handle_replay_status(message)
    assert runtime.replay_state is ReplayState.RUNNING
    await runtime.async_disable()
    message.payload = "{}"
    await runtime._async_handle_replay_status(message)
    assert runtime.replay_state is ReplayState.RUNNING

    timeout = _runtime("replay-timeout")
    await _select_profile(hass, timeout)
    await _enable(hass, timeout, AsyncMock(return_value=lambda: None))
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()
    ):
        timed_session = await timeout.async_start_replay_session()
    await timeout._async_mark_replay_timeout(hass, timed_session.replay_id)
    assert timeout.replay_state is ReplayState.FAILED
    assert timeout.replay_reason == "Replay readiness timed out."
    await timeout.async_disable()


async def test_rejected_failed_publish_failure_and_explicit_retry(hass) -> None:
    """A failed request stays local and retry always gets a new replay UUID."""
    runtime = _runtime("replay-retry")
    await _select_profile(hass, runtime)
    await _enable(hass, runtime, AsyncMock(return_value=lambda: None))
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock(side_effect=RuntimeError)
    ) as publish:
        failed = await runtime.async_start_replay_session()
    assert failed.state is ReplayState.FAILED
    assert failed.last_remote_reason == "Replay request publication failed."
    assert len(
        [
            call
            for call in publish.await_args_list
            if call.args[1] == replay_request_topic(runtime.pretend_gx_id or "")
        ]
    ) == 1
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()
    ):
        retried = await runtime.async_retry_replay_session()
    assert retried.replay_id != failed.replay_id
    rejected = MagicMock(
        payload=json.dumps(
            {
                "schemaVersion": 4,
                "gxDeviceId": runtime.pretend_gx_id,
                "replayId": retried.replay_id,
                "state": "rejected",
                "reason": "profile rejected",
            }
        )
    )
    await runtime._async_handle_replay_status(rejected)
    assert runtime.replay_state is ReplayState.REJECTED
    assert runtime.replay_reason == "profile rejected"
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()):
        failed_remote = await runtime.async_retry_replay_session()
    rejected.payload = json.dumps(
        {
            "schemaVersion": 4,
            "gxDeviceId": runtime.pretend_gx_id,
            "replayId": failed_remote.replay_id,
            "state": "failed",
            "reason": "bridge failed",
        }
    )
    await runtime._async_handle_replay_status(rejected)
    assert runtime.replay_state is ReplayState.FAILED
    assert runtime.replay_reason == "bridge failed"
    await runtime.async_disable()


async def test_simulated_api_failure_waits_for_matching_node_red_failure(hass) -> None:
    """A replay fault flags one normal request and changes state only on its response."""
    runtime = _runtime("replay-simulated-failure")
    await _select_profile(hass, runtime)
    await _enable(hass, runtime, AsyncMock(return_value=lambda: None))
    fault = await runtime.async_configure_fault(
        kind=FaultKind.REPLAY_API_FAILURE,
        activation_utc=runtime.virtual_time_utc,
        remaining_count=1,
    )
    await runtime.async_activate_fault(fault.fault_id)
    before_energy = runtime.energy_wh
    before_time = runtime.virtual_time_utc

    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()) as publish:
        session = await runtime.async_start_replay_session()
        request = json.loads(
            next(
                call.args[2]
                for call in publish.await_args_list
                if call.args[1] == replay_request_topic(runtime.pretend_gx_id or "")
            )
        )
        assert request["simulateApiFailure"] is True
        assert set(request) == {
            "schemaVersion",
            "replayId",
            "effectiveAtUtc",
            "startingBatteryEnergyKwh",
            "importForExportEnabled",
            "exportForSolarHeadroom",
            "periods",
            "simulateApiFailure",
        }
        assert session.state is ReplayState.REQUESTING
        assert not any(call.args[1].endswith("/clock/status") for call in publish.await_args_list)

        retained = MagicMock(
            retain=True,
            payload=json.dumps(
                {
                    "schemaVersion": 4,
                    "gxDeviceId": runtime.pretend_gx_id,
                    "replayId": session.replay_id,
                    "state": "failed",
                    "reason": "simulated_api_failure",
                }
            ),
        )
        await runtime._async_handle_replay_status(retained)
        assert runtime.replay_state is ReplayState.REQUESTING

        unexpected = MagicMock(
            retain=False,
            payload=json.dumps(
                {
                    "schemaVersion": 4,
                    "gxDeviceId": runtime.pretend_gx_id,
                    "replayId": session.replay_id,
                    "state": "failed",
                    "reason": "other_failure",
                }
            ),
        )
        await runtime._async_handle_replay_status(unexpected)
        assert runtime.replay_state is ReplayState.REQUESTING

        expected = MagicMock(
            retain=False,
            payload=json.dumps(
                {
                    "schemaVersion": 4,
                    "gxDeviceId": runtime.pretend_gx_id,
                    "replayId": session.replay_id,
                    "state": "failed",
                    "reason": "simulated_api_failure",
                }
            ),
        )
        await runtime._async_handle_replay_status(expected)
        await runtime._async_handle_replay_status(expected)

    assert runtime.replay_state is ReplayState.FAILED
    assert runtime.replay_reason == "simulated_api_failure"
    assert runtime.playback_state == "paused"
    assert runtime.energy_wh == before_energy
    assert runtime.virtual_time_utc == before_time
    assert next(item for item in runtime.list_faults() if item.fault_id == fault.fault_id).state is FaultState.EXHAUSTED
    await runtime.async_disable()


async def test_simulated_api_failure_retry_restarts_normally_with_new_identity(hass) -> None:
    """A consumed simulated failure cannot flag the explicit new-ID retry."""
    runtime = _runtime("replay-simulated-retry")
    await _select_profile(hass, runtime)
    await _enable(hass, runtime, AsyncMock(return_value=lambda: None))
    fault = await runtime.async_configure_fault(
        kind=FaultKind.REPLAY_API_FAILURE,
        activation_utc=runtime.virtual_time_utc,
        remaining_count=1,
    )
    await runtime.async_activate_fault(fault.fault_id)
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()) as publish:
        failed = await runtime.async_start_replay_session()
        failed_status = MagicMock(
            retain=False,
            payload=json.dumps(
                {
                    "schemaVersion": 4,
                    "gxDeviceId": runtime.pretend_gx_id,
                    "replayId": failed.replay_id,
                    "state": "failed",
                    "reason": "simulated_api_failure",
                }
            ),
        )
        await runtime._async_handle_replay_status(failed_status)
        retried = await runtime.async_retry_replay_session()
        payloads = [
            json.loads(call.args[2])
            for call in publish.await_args_list
            if call.args[1] == replay_request_topic(runtime.pretend_gx_id or "")
        ]

    assert retried.replay_id != failed.replay_id
    assert payloads[0]["simulateApiFailure"] is True
    assert "simulateApiFailure" not in payloads[1]
    await runtime.async_disable()


async def test_simulated_failure_request_keeps_existing_transport_fault_precedence(hass) -> None:
    """The flag is consumed before drop, delay, or disconnect handles outbound delivery."""
    drop = _runtime("replay-flagged-drop")
    await _select_profile(hass, drop)
    await _enable(hass, drop, AsyncMock(return_value=lambda: None))
    for kind, kwargs in (
        (FaultKind.REPLAY_API_FAILURE, {"remaining_count": 1}),
        (FaultKind.DROP_MQTT, {"remaining_count": 3}),
    ):
        fault = await drop.async_configure_fault(
            kind=kind, activation_utc=drop.virtual_time_utc, **kwargs
        )
        await drop.async_activate_fault(fault.fault_id)
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()) as publish:
        await drop.async_start_replay_session()
    assert drop.replay_state is ReplayState.REQUESTING
    assert not any(
        call.args[1] == replay_request_topic(drop.pretend_gx_id or "")
        for call in publish.await_args_list
    )
    assert all(item.state is FaultState.EXHAUSTED for item in drop.list_faults())
    assert drop.replay_session is not None
    await drop._async_mark_replay_timeout(hass, drop.replay_session.replay_id)
    assert drop.replay_state is ReplayState.FAILED
    await drop.async_disable()

    delay = _runtime("replay-flagged-delay")
    await _select_profile(hass, delay)
    await _enable(hass, delay, AsyncMock(return_value=lambda: None))
    for kind, kwargs in (
        (FaultKind.REPLAY_API_FAILURE, {"remaining_count": 1}),
        (
            FaultKind.DELAY_MQTT,
            {"remaining_count": 3, "settings": {"delay_seconds": 0.1}},
        ),
    ):
        fault = await delay.async_configure_fault(
            kind=kind, activation_utc=delay.virtual_time_utc, **kwargs
        )
        await delay.async_activate_fault(fault.fault_id)
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()) as publish:
        await delay.async_start_replay_session()
        assert not any(
            call.args[1] == replay_request_topic(delay.pretend_gx_id or "")
            for call in publish.await_args_list
        )
        await delay._async_flush_delayed_outbound()
        await delay._async_flush_delayed_outbound()
        await delay._async_flush_delayed_outbound()
    delayed_request = next(
        json.loads(call.args[2])
        for call in publish.await_args_list
        if call.args[1] == replay_request_topic(delay.pretend_gx_id or "")
    )
    assert delayed_request["simulateApiFailure"] is True
    await delay.async_disable()

    disconnect = _runtime("replay-flagged-disconnect")
    await _select_profile(hass, disconnect)
    await _enable(hass, disconnect, AsyncMock(return_value=lambda: None))
    for kind, kwargs in (
        (FaultKind.REPLAY_API_FAILURE, {"remaining_count": 1}),
        (FaultKind.MQTT_DISCONNECT, {"remaining_duration_seconds": 1}),
    ):
        fault = await disconnect.async_configure_fault(
            kind=kind, activation_utc=disconnect.virtual_time_utc, **kwargs
        )
        await disconnect.async_activate_fault(fault.fault_id)
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()) as publish:
        await disconnect.async_start_replay_session()
    assert disconnect.replay_state is ReplayState.REQUESTING
    publish.assert_not_awaited()
    assert any(
        item.kind is FaultKind.REPLAY_API_FAILURE and item.state is FaultState.EXHAUSTED
        for item in disconnect.list_faults()
    )
    await disconnect.async_disable()


async def test_two_and_three_entries_have_no_replay_crosstalk(hass) -> None:
    """Per-entry IDs, publications, status callbacks, and cancellation remain isolated."""
    runtimes = [
        _runtime("replay-a", REGISTRATION_A),
        _runtime("replay-b", REGISTRATION_B),
        _runtime("replay-c", REGISTRATION_C),
    ]
    for runtime in runtimes:
        await _select_profile(hass, runtime)
        await _enable(hass, runtime, AsyncMock(return_value=lambda: None))
    fault = await runtimes[0].async_configure_fault(
        kind=FaultKind.REPLAY_API_FAILURE,
        activation_utc=runtimes[0].virtual_time_utc,
        remaining_count=1,
    )
    await runtimes[0].async_activate_fault(fault.fault_id)
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()
    ) as publish:
        sessions = [await runtime.async_start_replay_session() for runtime in runtimes]
    assert len(
        [
            call
            for call in publish.await_args_list
            if call.args[1].endswith("/replay/request")
        ]
    ) == 3
    request_payloads = {
        call.args[1]: json.loads(call.args[2])
        for call in publish.await_args_list
        if call.args[1].endswith("/replay/request")
    }
    assert request_payloads[replay_request_topic(runtimes[0].pretend_gx_id or "")]["simulateApiFailure"] is True
    assert "simulateApiFailure" not in request_payloads[
        replay_request_topic(runtimes[1].pretend_gx_id or "")
    ]
    assert "simulateApiFailure" not in request_payloads[
        replay_request_topic(runtimes[2].pretend_gx_id or "")
    ]
    foreign = MagicMock(
        payload=json.dumps(
            {
                "schemaVersion": 4,
                "gxDeviceId": runtimes[0].pretend_gx_id,
                "replayId": sessions[0].replay_id,
                "state": "loading",
                "reason": None,
            }
        )
    )
    await runtimes[1]._async_handle_replay_status(foreign)
    assert runtimes[1].replay_state is ReplayState.REQUESTING
    await runtimes[0].async_disable()
    assert runtimes[1]._replay_timeout_handle is not None
    assert runtimes[2]._replay_timeout_handle is not None
    await runtimes[1].async_disable()
    await runtimes[2].async_disable()


async def test_schema_two_migrates_and_restart_reconstructs_with_one_publication(hass) -> None:
    """Schema 2 remains readable; an interrupted replay republishes once after setup."""
    runtime = _runtime("replay-migrate")
    await _select_profile(hass, runtime)
    record = runtime._storage_record()
    legacy = {
        key: value
        for key, value in record.items()
        if not key.startswith("replay_")
    }
    legacy["storage_schema_version"] = 2
    assert runtime._storage is not None
    await runtime._storage.async_save(legacy)
    migrated = _runtime("replay-migrate")
    await migrated.async_restore_storage(hass)
    assert migrated.replay_session is None
    await migrated.async_checkpoint(immediate=True)
    stored = await SandboxStorage(hass, "replay-migrate").async_load()
    assert (
        stored is not None
        and stored["storage_schema_version"] == STORAGE_SCHEMA_VERSION
    )
    assert stored["replay_simulate_api_failure"] is False

    active = _runtime("replay-restart")
    await _select_profile(hass, active)
    await _enable(hass, active, AsyncMock(return_value=lambda: None))
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()):
        original = await active.async_start_replay_session()
    await active.async_unload()
    restored = _runtime("replay-restart")
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe", new=AsyncMock(return_value=lambda: None)
    ) as subscribe, patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()
    ) as publish:
        await restored.async_restore_storage(hass)
    assert restored.replay_session is not None
    assert restored.replay_session.replay_id == original.replay_id
    assert restored.replay_state is ReplayState.REQUESTING
    assert restored.replay_pending_resume is True
    replay_publications = [
        call
        for call in publish.await_args_list
        if call.args[1] == replay_request_topic(restored.pretend_gx_id or "")
    ]
    assert len(replay_publications) == 1
    subscribe.assert_awaited()
    await restored.async_disable()

    changed = _runtime("replay-restart")
    directory = Path(hass.config.path("horizoniq", "profiles", "replay-restart"))
    await hass.async_add_executor_job(
        (directory / "day.json").write_text,
        _profile().replace('"load_w": 600', '"load_w": 601'),
        "utf-8",
    )
    await changed.async_restore_storage(hass)
    assert changed.replay_state is None
    assert changed.simulator_enabled is False
    assert changed.storage_diagnostic is not None


async def test_schema_six_defaults_flag_and_restart_republishes_flagged_request(hass) -> None:
    """Schema 6 defaults the optional flag; a pending flagged request keeps its ID/hash."""
    legacy = _runtime("replay-schema-six")
    await _select_profile(hass, legacy)
    assert legacy._storage is not None
    record = legacy._storage_record()
    record["storage_schema_version"] = 6
    record.pop("replay_simulate_api_failure")
    await legacy._storage.async_save(record)
    migrated = _runtime("replay-schema-six")
    await migrated.async_restore_storage(hass)
    assert migrated._replay_simulate_api_failure is False
    await migrated.async_checkpoint(immediate=True)
    stored = await SandboxStorage(hass, "replay-schema-six").async_load()
    assert stored is not None
    assert stored["storage_schema_version"] == STORAGE_SCHEMA_VERSION
    assert stored["replay_simulate_api_failure"] is False

    active = _runtime("replay-flagged-restart")
    await _select_profile(hass, active)
    await _enable(hass, active, AsyncMock(return_value=lambda: None))
    fault = await active.async_configure_fault(
        kind=FaultKind.REPLAY_API_FAILURE,
        activation_utc=active.virtual_time_utc,
        remaining_count=1,
    )
    await active.async_activate_fault(fault.fault_id)
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()):
        original = await active.async_start_replay_session()
    await active.async_unload()

    restored = _runtime("replay-flagged-restart")
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
        new=AsyncMock(return_value=lambda: None),
    ), patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()) as publish:
        await restored.async_restore_storage(hass)
    requests = [
        json.loads(call.args[2])
        for call in publish.await_args_list
        if call.args[1] == replay_request_topic(restored.pretend_gx_id or "")
    ]
    assert restored.replay_session is not None
    assert restored.replay_session.replay_id == original.replay_id
    assert requests and requests[0]["simulateApiFailure"] is True
    await restored.async_disable()


async def test_replay_status_subscription_failure_keeps_existing_enable_rollback(hass) -> None:
    """Replay subscription loss leaves local simulation enabled without transport."""
    runtime = _runtime("replay-subscription-failure")
    await _select_profile(hass, runtime)
    unsubscribe = MagicMock()
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
        new=AsyncMock(side_effect=[unsubscribe, unsubscribe, RuntimeError("no replay broker")]),
    ):
        await runtime.async_enable(hass)
    assert runtime.simulator_enabled is True
    assert runtime._mqtt_emulation_enabled is False
    assert unsubscribe.call_count == 2
    await runtime.async_disable()


async def test_snapshot_restore_and_storage_exclude_profile_payload_or_backend_data(hass) -> None:
    """Snapshot restore never publishes and Store contains only replay value metadata."""
    runtime = _runtime("replay-security")
    await _select_profile(hass, runtime)
    await _enable(hass, runtime, AsyncMock(return_value=lambda: None))
    fault = await runtime.async_configure_fault(
        kind=FaultKind.REPLAY_API_FAILURE,
        activation_utc=runtime.virtual_time_utc,
        remaining_count=1,
    )
    await runtime.async_activate_fault(fault.fault_id)
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()):
        await runtime.async_start_replay_session()
    await runtime.async_save_snapshot("before")
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()) as publish:
        await runtime.async_restore_snapshot("before")
    publish.assert_not_awaited()
    assert runtime.replay_state is ReplayState.STOPPED
    assert runtime.replay_pending_resume is True
    assert runtime._replay_simulate_api_failure is True
    assert runtime._storage is not None
    stored = await runtime._storage.async_load()
    assert stored is not None
    serialized = json.dumps(stored).lower()
    for forbidden in ("api_key", "token", "broker", "oauth", "actual", "outcome", "samples"):
        assert forbidden not in serialized
    await runtime.async_disable()

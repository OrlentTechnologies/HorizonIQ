"""Frozen schema-2 HA/Node-RED sandbox status MQTT tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
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
from custom_components.horizoniq.simulation.clock import ClockRate
from custom_components.horizoniq.simulation.faults import FaultKind
from custom_components.horizoniq.simulation.models import SimulationHealth
from custom_components.horizoniq.simulation.runtime_status import (
    FaultEnvelopeState,
    FaultLifecycleStatusState,
    SimulatorStatusState,
    parse_faults_status,
    parse_simulator_status,
)
from custom_components.horizoniq.simulation.topics import (
    faults_status_topic,
    node_red_status_topic,
    simulator_status_topic,
)


UTC = timezone.utc
NOW = datetime(2026, 8, 6, 12, tzinfo=UTC)
REGISTRATIONS = (
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
    "33333333-3333-4333-8333-333333333333",
)


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
    runtime._live_forecast_now = lambda: NOW
    return runtime


async def _enable(hass, runtime: HorizonIQEntryRuntime) -> None:
    await runtime.async_restore_storage(hass)
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
        new=AsyncMock(return_value=lambda: None),
    ):
        await runtime.async_enable(hass)


async def test_exact_schema_two_payloads_triggers_and_semantic_coalescing(hass) -> None:
    """HA emits exact typed non-retained statuses and ignores timestamp-only churn."""
    runtime = _runtime("status-payload-v2", REGISTRATIONS[0])
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
        new=AsyncMock(return_value=lambda: None),
    ), patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",
        new=AsyncMock(),
    ) as publish:
        await runtime.async_enable(hass)
        payloads = {
            call.args[1]: json.loads(call.args[2])
            for call in publish.await_args_list
            if call.args[1]
            in {
                simulator_status_topic(runtime.pretend_gx_id or ""),
                faults_status_topic(runtime.pretend_gx_id or ""),
            }
        }
        simulator = payloads[simulator_status_topic(runtime.pretend_gx_id or "")]
        faults = payloads[faults_status_topic(runtime.pretend_gx_id or "")]
        assert set(simulator) == {
            "schemaVersion", "gxDeviceId", "timestampUtc", "state", "reason",
            "virtualTimeUtc", "playbackState", "operatingState", "socPercent",
            "batteryEnergyWh", "batteryPowerW", "gridPowerW", "energyBalanceHealthy",
            "energyBalanceErrorWh", "mqttState", "replayState", "commandState",
        }
        assert simulator == {
            "schemaVersion": 2,
            "gxDeviceId": runtime.pretend_gx_id,
            "timestampUtc": simulator["timestampUtc"],
            "state": "running",
            "reason": None,
            "virtualTimeUtc": simulator["timestampUtc"],
            "playbackState": "none",
            "operatingState": 1,
            "socPercent": 50.0,
            "batteryEnergyWh": 5000.0,
            "batteryPowerW": 0.0,
            "gridPowerW": 0.0,
            "energyBalanceHealthy": True,
            "energyBalanceErrorWh": 0.0,
            "mqttState": "connected",
            "replayState": "none",
            "commandState": "none",
        }
        assert faults == {
            "schemaVersion": 2,
            "gxDeviceId": runtime.pretend_gx_id,
            "timestampUtc": simulator["timestampUtc"],
            "state": "clear",
            "reason": None,
            "faults": [],
        }
        assert all(call.kwargs["retain"] is False for call in publish.await_args_list)
        before = publish.await_count
        await runtime._async_publish_runtime_statuses()
        assert publish.await_count == before
        await runtime.async_step(60)
        assert publish.await_count >= before + 2
    await runtime.async_disable()


async def test_simulator_state_mapping_and_diagnostic_only_reason(hass) -> None:
    """Disabled, unavailable, unhealthy, paused, and running map to frozen enums."""
    runtime = _runtime("status-state-map", REGISTRATIONS[0])
    await runtime.async_restore_storage(hass)
    assert runtime._build_simulator_status().state is SimulatorStatusState.DISABLED
    runtime._config = None
    runtime._state = None
    runtime._clock = None
    unavailable = runtime._build_simulator_status()
    assert unavailable.state is SimulatorStatusState.UNAVAILABLE
    assert unavailable.reason == "Sandbox runtime is unavailable."

    runtime = _runtime("status-state-live", REGISTRATIONS[1])
    await _enable(hass, runtime)
    runtime.last_health = SimulationHealth.UNHEALTHY
    unhealthy = runtime._build_simulator_status()
    assert unhealthy.state is SimulatorStatusState.UNHEALTHY
    assert unhealthy.reason == "Synthetic energy balance is unhealthy."
    runtime.last_health = SimulationHealth.HEALTHY
    assert runtime._build_simulator_status().state is SimulatorStatusState.RUNNING
    await runtime.async_select_operating_mode("replay")
    await _enable(hass, runtime)
    assert runtime._clock is not None
    runtime._clock.set_rate(ClockRate.PAUSED)
    assert runtime._build_simulator_status().state is SimulatorStatusState.PAUSED
    runtime._clock.set_rate(ClockRate.X1)
    assert runtime._build_simulator_status().state is SimulatorStatusState.RUNNING
    await runtime.async_disable()


async def test_fault_configured_mapping_clear_active_bounds_and_unique_kinds(hass) -> None:
    """Pending maps to configured; only reportable kinds form a valid active envelope."""
    runtime = _runtime("status-fault-map", REGISTRATIONS[0])
    await _enable(hass, runtime)
    fault = await runtime.async_configure_fault(
        kind=FaultKind.DELAY_MQTT,
        activation_utc=runtime.virtual_time_utc,
        remaining_count=3,
        settings={"delay_seconds": 0.1},
    )
    configured = runtime._build_faults_status(runtime.virtual_time_utc)
    assert configured.state is FaultEnvelopeState.ACTIVE
    assert configured.reason is None
    assert configured.faults[0].kind.value == "delay_mqtt"
    assert configured.faults[0].state is FaultLifecycleStatusState.CONFIGURED
    assert configured.faults[0].remaining_count == 3
    assert configured.faults[0].remaining_seconds is None
    await runtime.async_activate_fault(fault.fault_id)
    active = runtime._build_faults_status(runtime.virtual_time_utc)
    assert active.faults[0].state is FaultLifecycleStatusState.ACTIVE
    await runtime.async_clear_fault(fault.fault_id)
    assert runtime._build_faults_status(runtime.virtual_time_utc).state is FaultEnvelopeState.CLEAR

    gx = runtime.pretend_gx_id or ""
    invalid = {
        "schemaVersion": 2, "gxDeviceId": gx, "timestampUtc": "2026-04-01T00:00:00Z",
        "state": "active", "reason": None,
        "faults": [
            {"kind": "drop_mqtt", "state": "active", "remainingCount": 1, "remainingSeconds": None},
            {"kind": "drop_mqtt", "state": "active", "remainingCount": 1, "remainingSeconds": None},
        ],
    }
    with pytest.raises(ValueError, match="unique"):
        parse_faults_status(invalid)
    invalid["faults"] = [
        {"kind": "drop_mqtt", "state": "active", "remainingCount": 1_000_001, "remainingSeconds": None}
    ]
    with pytest.raises(ValueError):
        parse_faults_status(invalid)
    await runtime.async_disable()


async def test_status_parser_rejects_schema_one_encoded_data_and_invalid_bounds() -> None:
    """Schema-1 output and encoded/unsafe diagnostics cannot enter schema-2 models."""
    gx = "horizoniq-11111111111141118111111111111111"
    payload = {
        "schemaVersion": 2, "gxDeviceId": gx, "timestampUtc": "2026-04-01T00:00:00Z",
        "state": "running", "reason": "soc=50", "virtualTimeUtc": "2026-04-01T00:00:00Z",
        "playbackState": "none", "operatingState": 1, "socPercent": 50,
        "batteryEnergyWh": 5000, "batteryPowerW": 0, "gridPowerW": 0,
        "energyBalanceHealthy": True, "energyBalanceErrorWh": 0,
        "mqttState": "connected", "replayState": "none", "commandState": "none",
    }
    with pytest.raises(ValueError, match="diagnostic"):
        parse_simulator_status(payload)
    payload["reason"] = None
    payload["schemaVersion"] = 1
    with pytest.raises(ValueError, match="schema"):
        parse_simulator_status(payload)
    payload["schemaVersion"] = 2
    payload["socPercent"] = 101
    with pytest.raises(ValueError):
        parse_simulator_status(payload)


async def test_node_red_status_rejects_retained_stale_invalid_and_cross_entry(hass) -> None:
    """Only a newer exact non-retained schema-1 Node-RED status updates its owner."""
    first = _runtime("status-first", REGISTRATIONS[0])
    second = _runtime("status-second", REGISTRATIONS[1])
    await _enable(hass, first)
    await _enable(hass, second)
    timestamp = datetime(2026, 4, 1, tzinfo=UTC)
    payload = {
        "schemaVersion": 1, "gxDeviceId": first.pretend_gx_id,
        "timestampUtc": timestamp.isoformat().replace("+00:00", "Z"),
        "state": "ready", "reason": "validated",
    }
    await first._async_handle_node_red_status(MagicMock(retain=True, payload=json.dumps(payload)))
    assert first.node_red_status is None
    await first._async_handle_node_red_status(MagicMock(retain=False, payload=json.dumps(payload)))
    assert first.node_red_status is not None and first.node_red_status.state == "ready"
    await first._async_handle_node_red_status(
        MagicMock(retain=False, payload=json.dumps(dict(payload, state="stale")))
    )
    assert first.node_red_status.state == "ready"
    foreign = dict(payload, gxDeviceId=second.pretend_gx_id, timestampUtc=(timestamp + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"))
    await first._async_handle_node_red_status(MagicMock(retain=False, payload=json.dumps(foreign)))
    assert second.node_red_status is None
    await first.async_unload()
    await first._async_handle_node_red_status(MagicMock(retain=False, payload=json.dumps(payload)))
    assert first.node_red_status is not None and first.node_red_status.state == "ready"
    await second.async_disable()


async def test_fault_bridge_reconnect_teardown_and_three_entry_isolation(hass) -> None:
    """Statuses stay generated-GX-local through faults, reconnect, and teardown."""
    runtimes = [_runtime(f"status-{index}", registration) for index, registration in enumerate(REGISTRATIONS)]
    for runtime in runtimes:
        await _enable(hass, runtime)
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=AsyncMock()) as publish:
        await runtimes[0].async_step(30)
        fault = await runtimes[1].async_configure_fault(
            kind=FaultKind.DROP_MQTT,
            activation_utc=runtimes[1].virtual_time_utc,
            remaining_count=1,
        )
        await runtimes[1].async_activate_fault(fault.fault_id)
        runtimes[2]._mqtt_fault_disconnected = False
        with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe", new=AsyncMock(return_value=lambda: None)):
            await runtimes[2]._async_reconnect_fault_mqtt(hass)
    expected = {
        topic
        for runtime in runtimes
        for topic in (simulator_status_topic(runtime.pretend_gx_id or ""), faults_status_topic(runtime.pretend_gx_id or ""))
    }
    actual = {call.args[1] for call in publish.await_args_list if call.args[1].endswith("/status")}
    assert actual <= expected
    assert simulator_status_topic(runtimes[0].pretend_gx_id or "") in actual
    for runtime in runtimes:
        await runtime.async_disable()

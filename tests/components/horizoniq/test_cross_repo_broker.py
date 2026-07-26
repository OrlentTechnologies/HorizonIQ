"""Opt-in real-broker verification against Solar's sandbox peer CLI."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio

from custom_components.horizoniq.const import (
    CAPACITY_SOURCE_VIRTUAL_BATTERY,
    CONF_CAPACITY_SOURCE,
    CONF_ENVIRONMENT,
    CONF_REGISTRATION_CONFIG,
    CONF_REGISTRATION_ID,
    SANDBOX_ENVIRONMENT,
)
from custom_components.horizoniq.sandbox_runtime import HorizonIQEntryRuntime
from custom_components.horizoniq.simulation.faults import FaultKind, FaultState
from custom_components.horizoniq.simulation.models import CommandStatus, OperatingMode
from custom_components.horizoniq.simulation.replay_contract import ReplayState
from custom_components.horizoniq.simulation.topics import (
    VictronCommandKey,
    clock_status_topic,
    command_issued_topic,
    command_status_topic,
    command_topic,
    faults_status_topic,
    refresh_topic,
    replay_request_topic,
    simulator_status_topic,
    telemetry_topic,
    VictronTelemetryKey,
)
from tests.components.horizoniq.cross_repo.mqtt_adapter import (
    BrokerSettings,
    RealMqttAdapter,
)
from tests.components.horizoniq.cross_repo.solar_peer import (
    SolarPeerConfig,
    SolarSandboxPeer,
)


pytestmark = [
    pytest.mark.skipif(
        os.environ.get("HORIZONIQ_CROSS_REPO_MQTT") != "1",
        reason="set HORIZONIQ_CROSS_REPO_MQTT=1 to run real-broker Solar cross-repository tests",
    ),
    pytest.mark.enable_socket,
]

UTC = timezone.utc
REGISTRATION_A = "11111111-1111-4111-8111-111111111111"
REGISTRATION_B = "22222222-2222-4222-8222-222222222222"


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


async def _enable(hass, runtime: HorizonIQEntryRuntime) -> None:
    await runtime.async_restore_storage(hass)
    await runtime.async_enable(hass)


async def _select_profile(hass, runtime: HorizonIQEntryRuntime) -> None:
    start = datetime(2026, 4, 1, tzinfo=UTC)
    samples = [
        {
            "timestamp": (start + timedelta(minutes=5 * index)).isoformat(),
            "load_w": 600,
            "solar_w": 100,
            "import_rate_gbp_per_kwh": -0.1,
            "export_rate_gbp_per_kwh": 0.05,
        }
        for index in range(6)
    ]
    directory = Path(hass.config.path("horizoniq", "profiles", runtime.entry_id))
    await hass.async_add_executor_job(lambda: directory.mkdir(parents=True, exist_ok=True))
    await hass.async_add_executor_job(
        (directory / "cross-repo.json").write_text,
        json.dumps(
            {
                "schema_version": 1,
                "starting_battery_energy_wh": 5_000,
                "samples": samples,
            }
        ),
        "utf-8",
    )
    await runtime.async_select_profile("cross-repo.json")


async def _wait_until(predicate, description: str, *, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"Timed out waiting for {description}.")
        await asyncio.sleep(0.02)


def _z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _peer_command_scenario(runtime: HorizonIQEntryRuntime) -> dict[str, str]:
    now = runtime.virtual_time_utc
    assert now is not None and runtime.pretend_gx_id is not None
    return {
        "mode": "command",
        "gxDeviceId": runtime.pretend_gx_id,
        "planId": str(uuid4()),
        "commandId": str(uuid4()),
        "timestampUtc": _z(now),
        "effectiveAtUtc": _z(now),
        "expiresAtUtc": _z(now + timedelta(minutes=30)),
    }


@pytest_asyncio.fixture(name="cross_repo")
async def cross_repo_fixture(socket_enabled):
    """Connect one real test client and validate all opt-in prerequisites eagerly."""
    broker = BrokerSettings.from_environment()
    peer_config = SolarPeerConfig.from_environment()
    adapter = RealMqttAdapter(broker, name="cross-repo")
    await adapter.async_connect()
    try:
        yield broker, peer_config, adapter
    finally:
        await adapter.async_close()


async def test_real_broker_command_atomicity_and_retained_input_safety(hass, cross_repo) -> None:
    """Solar command peer proves received→applied atomically; retained input is inert."""
    broker, peer_config, adapter = cross_repo
    runtime = _runtime("cross-command", REGISTRATION_A)
    assert runtime.pretend_gx_id is not None
    now = runtime.virtual_time_utc
    assert now is not None
    before_command_status = runtime.last_command_status
    before_command = runtime._command
    issued = {
        "schemaVersion": 4,
        "gxDeviceId": runtime.pretend_gx_id,
        "planId": str(uuid4()),
        "commandId": str(uuid4()),
        "action": "charge_required",
        "issuedAtUtc": _z(now),
        "effectiveAtUtc": _z(now),
        "expiresAtUtc": _z(now + timedelta(minutes=10)),
        "expectedHub4Mode": 1,
        "expectedVeBusMode": 1,
        "expectedAcPowerSetpointW": 2_000,
    }
    retained = [
        (command_issued_topic(runtime.pretend_gx_id), json.dumps(issued)),
        (command_topic(runtime.pretend_gx_id, VictronCommandKey.HUB4_MODE), '{"value":1}'),
        (command_topic(runtime.pretend_gx_id, VictronCommandKey.VE_BUS_MODE), '{"value":1}'),
        (command_topic(runtime.pretend_gx_id, VictronCommandKey.AC_POWER_SETPOINT), '{"value":2000}'),
        (refresh_topic(runtime.pretend_gx_id), "{}"),
    ]
    retained_publisher = RealMqttAdapter(broker, name="retained-publisher")
    await retained_publisher.async_connect()
    for topic, payload in retained:
        await retained_publisher.async_publish(hass, topic, payload, qos=1, retain=True)
    fault = await runtime.async_configure_fault(
        kind=FaultKind.REJECT_COMMAND,
        activation_utc=now,
        remaining_count=1,
    )
    await runtime.async_activate_fault(fault.fault_id)

    with (
        patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=adapter.async_publish),
        patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe", new=adapter.async_subscribe),
    ):
        try:
            await _enable(hass, runtime)
            assert {topic for topic, _payload in retained} <= adapter.subscriptions
            await _wait_until(
                lambda: sum(message.retain for message in adapter.received) >= len(retained),
                "all retained sandbox inputs",
            )
            active = next(item for item in runtime.list_faults() if item.fault_id == fault.fault_id)
            assert active.state is FaultState.ACTIVE and active.remaining_count == 1
            assert runtime.last_command_status is before_command_status
            assert runtime._command is before_command

            await runtime.async_clear_fault(fault.fault_id)
            adapter.published.clear()
            peer = SolarSandboxPeer(peer_config, broker)
            try:
                await peer.async_start(**_peer_command_scenario(runtime))
                result = await peer.async_wait_result()
            finally:
                await peer.async_close()
            assert result["mode"] == "command"
            assert result["states"] == ["received", "applied"]
            assert runtime.last_command_status is CommandStatus.APPLIED
            assert runtime._command is not None and runtime._command.mode is OperatingMode.GRID_SETPOINT
            published_topics = {message.topic for message in adapter.published}
            assert command_status_topic(runtime.pretend_gx_id) in published_topics
            assert simulator_status_topic(runtime.pretend_gx_id) in published_topics
            assert all(
                telemetry_topic(runtime.pretend_gx_id, key) in published_topics
                for key in VictronTelemetryKey
            )
        finally:
            await runtime.async_disable()
            for topic, _payload in retained:
                await retained_publisher.async_publish(hass, topic, "", qos=1, retain=True)
            await retained_publisher.async_close()


async def test_real_broker_replay_failure_is_peer_driven_and_state_neutral(hass, cross_repo) -> None:
    """A flagged HA request is failed only by Solar's matching simulated response."""
    broker, peer_config, adapter = cross_repo
    runtime = _runtime("cross-replay", REGISTRATION_A)
    await runtime.async_restore_storage(hass)
    await _select_profile(hass, runtime)
    now = runtime.virtual_time_utc
    before_energy = runtime._state.energy_wh if runtime._state is not None else None
    assert now is not None and before_energy is not None
    fault = await runtime.async_configure_fault(
        kind=FaultKind.REPLAY_API_FAILURE,
        activation_utc=now,
        remaining_count=1,
    )
    await runtime.async_activate_fault(fault.fault_id)

    with (
        patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=adapter.async_publish),
        patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe", new=adapter.async_subscribe),
    ):
        try:
            await runtime.async_enable(hass)
            session = await runtime.async_prepare_replay_session()
            peer = SolarSandboxPeer(peer_config, broker)
            try:
                await peer.async_start(
                    mode="replay-failure",
                    gxDeviceId=runtime.pretend_gx_id or "",
                    replayId=session.replay_id,
                )
                ready = await peer.async_wait_ready()
                assert ready["mode"] == "replay-failure"
                started = await runtime.async_start_replay_session()
                assert started.state is ReplayState.REQUESTING
                result = await peer.async_wait_result()
            finally:
                await peer.async_close()
            try:
                await _wait_until(
                    lambda: runtime.replay_session is not None
                    and runtime.replay_session.state is ReplayState.FAILED,
                    "matching replay failure status",
                )
            except AssertionError as err:
                raise AssertionError(
                    f"Replay status was not applied: session={runtime.replay_session!r}; "
                    f"received={adapter.received!r}"
                ) from err
            assert result["state"] == "failed" and result["reason"] == "simulated_api_failure"
            request = next(
                json.loads(message.payload)
                for message in adapter.published
                if message.topic == replay_request_topic(runtime.pretend_gx_id or "")
            )
            assert request["simulateApiFailure"] is True
            assert runtime.virtual_time_utc == now
            assert runtime._state is not None and runtime._state.energy_wh == before_energy
            assert runtime._playback_state != "running"
            assert not any(
                message.topic == clock_status_topic(runtime.pretend_gx_id or "")
                for message in adapter.published
            )
        finally:
            await runtime.async_disable()


async def test_real_broker_status_schema_two_and_two_entry_isolation(hass, cross_repo) -> None:
    """Solar validates A's schema-2 statuses while A command/replay traffic leaves B untouched."""
    broker, peer_config, adapter = cross_repo
    first = _runtime("cross-isolation-a", REGISTRATION_A)
    second = _runtime("cross-isolation-b", REGISTRATION_B)
    await first.async_restore_storage(hass)
    await second.async_restore_storage(hass)
    await _select_profile(hass, first)
    before_second_time = second.virtual_time_utc
    before_second_energy = second._state.energy_wh if second._state is not None else None

    with (
        patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", new=adapter.async_publish),
        patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe", new=adapter.async_subscribe),
    ):
        try:
            await first.async_enable(hass)
            await second.async_enable(hass)
            before_second_command_status = second.last_command_status
            adapter.published.clear()
            status_peer = SolarSandboxPeer(peer_config, broker)
            try:
                await status_peer.async_start(mode="status", gxDeviceId=first.pretend_gx_id or "")
                await status_peer.async_wait_ready()
                await first._async_publish_runtime_statuses(force=True)
                status_result = await status_peer.async_wait_result()
            finally:
                await status_peer.async_close()
            assert status_result["mode"] == "status"
            assert status_result["faultCount"] == 0

            peer = SolarSandboxPeer(peer_config, broker)
            try:
                await peer.async_start(**_peer_command_scenario(first))
                command_result = await peer.async_wait_result()
            finally:
                await peer.async_close()
            assert command_result["states"] == ["received", "applied"]

            replay_fault = await first.async_configure_fault(
                kind=FaultKind.REPLAY_API_FAILURE,
                activation_utc=first.virtual_time_utc,
                remaining_count=1,
            )
            await first.async_activate_fault(replay_fault.fault_id)
            prepared = await first.async_prepare_replay_session()
            replay_peer = SolarSandboxPeer(peer_config, broker)
            try:
                await replay_peer.async_start(
                    mode="replay-failure",
                    gxDeviceId=first.pretend_gx_id or "",
                    replayId=prepared.replay_id,
                )
                await replay_peer.async_wait_ready()
                await first.async_start_replay_session()
                await replay_peer.async_wait_result()
            finally:
                await replay_peer.async_close()
            await _wait_until(
                lambda: first.replay_session is not None
                and first.replay_session.state is ReplayState.FAILED,
                "entry A replay failure",
            )
            assert second.last_command_status is before_second_command_status
            assert second.replay_session is None
            assert second.virtual_time_utc == before_second_time
            assert second._state is not None and second._state.energy_wh == before_second_energy
            second_gx = second.pretend_gx_id or ""
            assert all(second_gx not in message.topic for message in adapter.published)
        finally:
            await first.async_disable()
            await second.async_disable()

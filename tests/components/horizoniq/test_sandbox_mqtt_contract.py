"""Frozen Victron sandbox MQTT contract tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
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
from custom_components.horizoniq.simulation.faults import FaultKind, FaultState
from custom_components.horizoniq.simulation.models import OperatingMode
from custom_components.horizoniq.simulation.topics import (
    VictronCommandKey,
    VictronOperatingState,
    VictronTelemetryKey,
    command_topic,
    command_issued_topic,
    node_red_status_topic,
    refresh_topic,
    telemetry_payload,
    telemetry_topic,
    victron_topic,
    VictronTopicDirection,
)


REGISTRATION_A = "11111111-1111-4111-8111-111111111111"
REGISTRATION_B = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2026, 8, 6, 12, tzinfo=timezone.utc)


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
                    "NominalBatteryVoltage": 48,
                },
            },
        }
    )
    runtime._live_forecast_now = lambda: NOW
    return runtime


async def _enable(runtime: HorizonIQEntryRuntime, hass) -> AsyncMock:
    subscribe = AsyncMock(return_value=lambda: None)
    with (
        patch(
            "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
            new=subscribe,
        ),
        patch(
            "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",
            new=AsyncMock(),
        ),
    ):
        await runtime.async_enable(hass)
    return subscribe


def test_frozen_topic_parity_and_payload_validation() -> None:
    """The HA-local builders use only the exact frozen Node-RED paths."""
    gx_id = "horizoniq-11111111111141118111111111111111"

    assert [telemetry_topic(gx_id, key) for key in VictronTelemetryKey] == [
        f"victron/N/{gx_id}/battery/512/Soc",
        f"victron/N/{gx_id}/battery/512/InstalledCapacity",
        f"victron/N/{gx_id}/battery/Power",
        f"victron/N/{gx_id}/grid/Power",
        f"victron/N/{gx_id}/system/Load",
        f"victron/N/{gx_id}/solar/Power",
        f"victron/N/{gx_id}/battery/Voltage",
        f"victron/N/{gx_id}/system/OperatingState",
    ]
    assert [command_topic(gx_id, key) for key in VictronCommandKey] == [
        f"victron/W/{gx_id}/settings/0/Settings/CGwacs/Hub4Mode",
        f"victron/W/{gx_id}/vebus/274/Mode",
        f"victron/W/{gx_id}/settings/0/Settings/CGwacs/AcPowerSetPoint",
    ]
    assert refresh_topic(gx_id) == f"victron/R/{gx_id}/keepalive"
    assert telemetry_payload(VictronTelemetryKey.OPERATING_STATE, 2) == '{"value":2}'
    with pytest.raises(ValueError):
        victron_topic(VictronTopicDirection.WRITE, gx_id, "#")
    with pytest.raises(ValueError):
        telemetry_topic("production-gx", VictronTelemetryKey.STATE_OF_CHARGE)


async def test_snapshot_is_complete_non_retained_and_uses_frozen_units(hass) -> None:
    """A snapshot has all eight values with Ah capacity and numeric enum state."""
    runtime = _runtime("contract-snapshot", REGISTRATION_A)
    await _enable(runtime, hass)
    runtime.set_inputs(load_w=600, solar_w=100)

    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",
        new=AsyncMock(),
    ) as publish:
        await runtime._async_publish_telemetry_snapshot()

    assert publish.await_count == 8
    values = {
        call.args[1]: json.loads(call.args[2])["value"]
        for call in publish.await_args_list
    }
    assert values == {
        telemetry_topic(runtime.pretend_gx_id or "", VictronTelemetryKey.STATE_OF_CHARGE): 50.0,
        telemetry_topic(runtime.pretend_gx_id or "", VictronTelemetryKey.INSTALLED_CAPACITY): 10_000 / 48,
        telemetry_topic(runtime.pretend_gx_id or "", VictronTelemetryKey.BATTERY_POWER): 0.0,
        telemetry_topic(runtime.pretend_gx_id or "", VictronTelemetryKey.GRID_POWER): 0.0,
        telemetry_topic(runtime.pretend_gx_id or "", VictronTelemetryKey.LOAD_POWER): 600,
        telemetry_topic(runtime.pretend_gx_id or "", VictronTelemetryKey.SOLAR_POWER): 100,
        telemetry_topic(runtime.pretend_gx_id or "", VictronTelemetryKey.VOLTAGE): 48,
        telemetry_topic(runtime.pretend_gx_id or "", VictronTelemetryKey.OPERATING_STATE): VictronOperatingState.SELF_CONSUMPTION,
    }
    assert all(call.kwargs["retain"] is False for call in publish.await_args_list)
    await runtime.async_disable()


async def test_exact_subscriptions_reject_retained_writes_and_refreshes(hass) -> None:
    """No wildcard is subscribed and retained W/R messages cannot change local state."""
    runtime = _runtime("contract-retained", REGISTRATION_A)
    subscribe = await _enable(runtime, hass)
    assert [call.args[1] for call in subscribe.await_args_list] == [
        *[command_topic(runtime.pretend_gx_id or "", key) for key in VictronCommandKey],
        refresh_topic(runtime.pretend_gx_id or ""),
            command_issued_topic(runtime.pretend_gx_id or ""),
            f"horizoniq/sandbox/{runtime.pretend_gx_id}/replay/status",
            node_red_status_topic(runtime.pretend_gx_id or ""),
    ]
    assert all("#" not in call.args[1] and "+" not in call.args[1] for call in subscribe.await_args_list)

    reject = await runtime.async_configure_fault(
        kind=FaultKind.REJECT_COMMAND,
        activation_utc=runtime.virtual_time_utc,
        remaining_count=1,
    )
    await runtime.async_activate_fault(reject.fault_id)
    retained_write = MagicMock(
        topic=command_topic(
            runtime.pretend_gx_id or "", VictronCommandKey.AC_POWER_SETPOINT
        ),
        payload='{"value":500}',
        retain=True,
    )
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",
        new=AsyncMock(),
    ) as publish:
        await runtime._async_handle_victron_write(retained_write)
        await runtime._async_handle_victron_refresh(
            MagicMock(
                topic=refresh_topic(runtime.pretend_gx_id or ""),
                payload="{}",
                retain=True,
            )
        )

    assert runtime._command is None
    assert runtime.list_faults()[0].state is FaultState.ACTIVE
    publish.assert_not_awaited()
    await runtime.async_disable()


async def test_refresh_is_state_neutral_and_entry_isolated(hass) -> None:
    """A valid R keepalive republishes exactly the owning N snapshot."""
    first = _runtime("contract-first", REGISTRATION_A)
    second = _runtime("contract-second", REGISTRATION_B)
    await _enable(first, hass)
    await _enable(second, hass)
    first.set_inputs(load_w=700, solar_w=50)
    before = (first.energy_wh, first.virtual_time_utc, first._command, second.energy_wh)

    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",
        new=AsyncMock(),
    ) as publish:
        await first._async_handle_victron_refresh(
            MagicMock(
                topic=refresh_topic(first.pretend_gx_id or ""),
                payload="{}",
                retain=False,
            )
        )

    assert publish.await_count == 8
    assert all(first.pretend_gx_id in call.args[1] for call in publish.await_args_list)
    assert (first.energy_wh, first.virtual_time_utc, first._command, second.energy_wh) == before
    await first.async_disable()
    await second.async_disable()


async def test_snapshot_fault_bridge_and_disable_discard_pending_publication(hass) -> None:
    """Snapshot telemetry uses the shared bridge and teardown cancels delayed output."""
    runtime = _runtime("contract-faults", REGISTRATION_A)
    await _enable(runtime, hass)
    delay = await runtime.async_configure_fault(
        kind=FaultKind.DELAY_MQTT,
        activation_utc=runtime.virtual_time_utc,
        remaining_count=1,
        settings={"delay_seconds": 1},
    )
    await runtime.async_activate_fault(delay.fault_id)

    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",
        new=AsyncMock(),
    ) as publish:
        await runtime._async_publish_telemetry_snapshot()
        assert len(runtime._delayed_outbound) == 1
        await runtime.async_disable()
        await runtime._async_flush_delayed_outbound()

    assert runtime._delayed_outbound == []
    assert publish.await_count == 8
    assert runtime._command is None or runtime._command.mode is OperatingMode.SELF_CONSUMPTION

"""Frozen issued-command/W/status lifecycle tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
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
from custom_components.horizoniq.sandbox_storage import (
    STORAGE_SCHEMA_VERSION,
    SandboxStorage,
)
from custom_components.horizoniq.simulation.command_lifecycle import (
    COMMAND_SCHEMA_VERSION,
    CommandLifecycleState,
)
from custom_components.horizoniq.simulation.faults import FaultKind, FaultState
from custom_components.horizoniq.simulation.models import OperatingMode
from custom_components.horizoniq.simulation.topics import (
    VictronCommandKey,
    command_issued_topic,
    command_status_topic,
    command_topic,
)


REGISTRATION_A = "11111111-1111-4111-8111-111111111111"
REGISTRATION_B = "22222222-2222-4222-8222-222222222222"
REGISTRATION_C = "33333333-3333-4333-8333-333333333333"
NOW = datetime(2026, 8, 6, 12, tzinfo=timezone.utc)


def _runtime(entry_id: str, registration_id: str = REGISTRATION_A) -> HorizonIQEntryRuntime:
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


def _z(value) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _issued(
    runtime: HorizonIQEntryRuntime,
    *,
    command_id: str = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    expires_in_seconds: float = 60,
    hub4_mode: int = 1,
    ve_bus_mode: int = 1,
    setpoint_w: float = 500,
) -> dict[str, object]:
    now = runtime.virtual_time_utc
    assert now is not None
    return {
        "schemaVersion": COMMAND_SCHEMA_VERSION,
        "gxDeviceId": runtime.pretend_gx_id,
        "planId": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "commandId": command_id,
        "action": "charge_required",
        "issuedAtUtc": _z(now),
        "effectiveAtUtc": _z(now),
        "expiresAtUtc": _z(now + timedelta(seconds=expires_in_seconds)),
        "expectedHub4Mode": hub4_mode,
        "expectedVeBusMode": ve_bus_mode,
        "expectedAcPowerSetpointW": setpoint_w,
    }


def _message(topic: str, payload: object, *, retain: bool = False) -> MagicMock:
    return MagicMock(topic=topic, payload=json.dumps(payload), retain=retain)


async def _issue(runtime: HorizonIQEntryRuntime, payload: dict[str, object]) -> None:
    await runtime._async_handle_command_issued(
        _message(command_issued_topic(runtime.pretend_gx_id or ""), payload)
    )


async def _write(runtime: HorizonIQEntryRuntime, key: VictronCommandKey, value: float) -> None:
    await runtime._async_handle_victron_write(
        _message(command_topic(runtime.pretend_gx_id or "", key), {"value": value})
    )


def _statuses(publish: AsyncMock) -> list[dict[str, object]]:
    return [
        json.loads(call.args[2])
        for call in publish.await_args_list
        if "/commands/status" in call.args[1]
    ]


async def test_issued_received_three_writes_and_applied_are_atomic(hass) -> None:
    """Only issued → received → three exact W writes can change command state."""
    runtime = _runtime("command-atomic")
    subscribe = await _enable(runtime, hass)
    assert command_issued_topic(runtime.pretend_gx_id or "") in [
        call.args[1] for call in subscribe.await_args_list
    ]
    assert all(
        "commands/intent" not in call.args[1] and "commands/ack" not in call.args[1]
        for call in subscribe.await_args_list
    )

    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",
        new=AsyncMock(),
    ) as publish:
        await _issue(runtime, _issued(runtime))
        assert runtime._command is None
        await _write(runtime, VictronCommandKey.AC_POWER_SETPOINT, 500)
        await _write(runtime, VictronCommandKey.HUB4_MODE, 1)
        assert runtime._command is None
        await _write(runtime, VictronCommandKey.VE_BUS_MODE, 1)

    statuses = _statuses(publish)
    assert [status["state"] for status in statuses] == ["received", "applied"]
    assert all(status["schemaVersion"] == 4 for status in statuses)
    assert all(status["gxDeviceId"] == runtime.pretend_gx_id for status in statuses)
    assert all(status["timestampUtc"].endswith("Z") for status in statuses)
    assert statuses[-1]["simulatedState"] == {
        "socPercent": 50.0,
        "batteryPowerW": 0.0,
        "gridPowerW": 0.0,
        "operatingState": 2,
    }
    assert runtime._command is not None
    assert runtime._command.mode is OperatingMode.GRID_SETPOINT
    assert runtime._command.requested_grid_power_w == 500
    assert all(call.kwargs["retain"] is False for call in publish.await_args_list)
    await runtime.async_disable()


async def test_retained_invalid_expired_duplicate_and_fault_ordering(hass) -> None:
    """Only a fully valid new issued message can consume reject_command."""
    runtime = _runtime("command-validation")
    await _enable(runtime, hass)
    fault = await runtime.async_configure_fault(
        kind=FaultKind.REJECT_COMMAND,
        activation_utc=runtime.virtual_time_utc,
        remaining_count=1,
    )
    await runtime.async_activate_fault(fault.fault_id)
    payload = _issued(runtime)
    expired = _issued(
        runtime,
        command_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    )
    now = runtime.virtual_time_utc
    assert now is not None
    expired["issuedAtUtc"] = _z(now - timedelta(seconds=2))
    expired["effectiveAtUtc"] = _z(now - timedelta(seconds=1))
    expired["expiresAtUtc"] = _z(now - timedelta(milliseconds=1))
    invalid = dict(payload)
    invalid["unexpected"] = True
    stale = dict(payload)
    stale["commandId"] = "99999999-9999-4999-8999-999999999999"
    stale["effectiveAtUtc"] = _z(now - timedelta(seconds=1))
    future = _issued(
        runtime,
        command_id="ffffffff-ffff-4fff-8fff-ffffffffffff",
    )
    future["issuedAtUtc"] = _z(now + timedelta(seconds=1))
    future["effectiveAtUtc"] = _z(now + timedelta(seconds=1))
    future["expiresAtUtc"] = _z(now + timedelta(seconds=61))

    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",
        new=AsyncMock(),
    ) as publish:
        await runtime._async_handle_command_issued(
            _message(command_issued_topic(runtime.pretend_gx_id or ""), payload, retain=True)
        )
        await _issue(runtime, invalid)
        await _issue(runtime, stale)
        await _issue(runtime, future)
        await _issue(runtime, expired)
        assert runtime.list_faults()[0].remaining_count == 1
        await _issue(runtime, payload)

    statuses = _statuses(publish)
    assert [status["state"] for status in statuses] == [
        "rejected",
        "expired",
        "rejected",
    ]
    assert runtime.list_faults()[0].state is FaultState.EXHAUSTED
    assert runtime._command is None
    assert runtime._pending_command is None

    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",
        new=AsyncMock(),
    ) as publish:
        await _issue(runtime, payload)
        await _write(runtime, VictronCommandKey.HUB4_MODE, 1)
        await _write(runtime, VictronCommandKey.VE_BUS_MODE, 1)
        await _write(runtime, VictronCommandKey.AC_POWER_SETPOINT, 500)
        await _issue(runtime, payload)
    assert [status["state"] for status in _statuses(publish)] == [
        "received",
        "applied",
        "rejected",
    ]
    await runtime.async_disable()


async def test_mismatch_timeout_expiry_and_teardown_fail_safe(hass) -> None:
    """Terminal correlation states clear partial writes and return safe self-consumption."""
    runtime = _runtime("command-terminal")
    await _enable(runtime, hass)
    first = _issued(runtime)
    second = _issued(
        runtime, command_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    )
    third = _issued(
        runtime,
        command_id="dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        expires_in_seconds=1,
    )
    fourth = _issued(
        runtime, command_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    )

    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",
        new=AsyncMock(),
    ) as publish:
        await _issue(runtime, first)
        await _write(runtime, VictronCommandKey.HUB4_MODE, 2)
        await _issue(runtime, second)
        await runtime._async_command_correlation_timeout(second["commandId"])
        await _issue(runtime, third)
        await runtime.async_step(2)
        await _issue(runtime, fourth)
        await runtime.async_disable()

    states = [status["state"] for status in _statuses(publish)]
    assert states == [
        "received",
        "rejected",
        "received",
        "failed",
        "received",
        "expired",
        "received",
        "failed",
    ]
    assert runtime._pending_command is None
    assert runtime._command is not None
    assert runtime._command.mode is OperatingMode.SELF_CONSUMPTION


async def test_ledger_migration_restart_and_three_runtime_isolation(hass) -> None:
    """Only accepted IDs persist; schema-5 migration and other runtimes stay isolated."""
    first = _runtime("command-first", REGISTRATION_A)
    second = _runtime("command-second", REGISTRATION_B)
    third = _runtime("command-third", REGISTRATION_C)
    for runtime in (first, second, third):
        await runtime.async_restore_storage(hass)
        await _enable(runtime, hass)

    payload = _issued(first)
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",
        new=AsyncMock(),
    ):
        await _issue(first, payload)
    assert first._pending_command is not None
    assert second._pending_command is None and third._pending_command is None
    await first.async_checkpoint(immediate=True)
    assert first._storage is not None
    record = await first._storage.async_load()
    assert record is not None and record["storage_schema_version"] == STORAGE_SCHEMA_VERSION
    assert record["accepted_command_ids"] == [
        {"command_id": payload["commandId"], "accepted_at_utc": _z(first.virtual_time_utc)}
    ]
    assert "plan" not in json.dumps(record["accepted_command_ids"]).lower()

    await first.async_unload()
    restored = _runtime("command-first", REGISTRATION_A)
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
        new=AsyncMock(return_value=lambda: None),
    ):
        await restored.async_restore_storage(hass)
    assert restored._pending_command is None
    assert restored._accepted_command_ids
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",
        new=AsyncMock(),
    ) as publish:
        await _issue(restored, payload)
    assert _statuses(publish)[0]["state"] == "rejected"

    legacy = dict(record)
    legacy.pop("accepted_command_ids")
    legacy["storage_schema_version"] = 5
    await SandboxStorage(hass, "command-first").async_save(legacy)
    migrated = _runtime("command-first", REGISTRATION_A)
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
        new=AsyncMock(return_value=lambda: None),
    ):
        await migrated.async_restore_storage(hass)
    await migrated.async_checkpoint(immediate=True)
    stored = await SandboxStorage(hass, "command-first").async_load()
    assert stored is not None and stored["storage_schema_version"] == STORAGE_SCHEMA_VERSION
    assert stored["accepted_command_ids"] == []

    await second.async_disable()
    await third.async_disable()
    await restored.async_disable()
    await migrated.async_disable()

"""Tests for private, entry-scoped virtual-battery persistence."""

from datetime import datetime, timezone
import json
from unittest.mock import AsyncMock, MagicMock, Mock, patch

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
    async_remove_entry_storage,
)
from custom_components.horizoniq.simulation.models import (
    BatteryState,
    ClockState,
    IntervalLedger,
    SimulationSnapshot,
)
from custom_components.horizoniq.simulation.snapshots import to_json
from custom_components.horizoniq.simulation.runtime_status import RuntimeStatus


REGISTRATION_A = "11111111-1111-4111-8111-111111111111"
REGISTRATION_B = "22222222-2222-4222-8222-222222222222"
REGISTRATION_C = "33333333-3333-4333-8333-333333333333"


def _data(registration_id: str) -> dict[str, object]:
    return {
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


def _runtime(entry_id: str, registration_id: str) -> tuple[HorizonIQEntryRuntime, MagicMock]:
    coordinator = MagicMock()
    coordinator.async_pause_for_sandbox = AsyncMock()
    coordinator.async_resume_from_sandbox = AsyncMock()
    runtime = HorizonIQEntryRuntime(
        coordinator=coordinator,
        registration_id=registration_id,
        entry_id=entry_id,
    )
    runtime.configure_sandbox(_data(registration_id))
    return runtime, coordinator


async def _enable(runtime: HorizonIQEntryRuntime, hass) -> None:
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
        new=AsyncMock(return_value=lambda: None),
    ):
        await runtime.async_enable(hass)


async def test_clean_setup_has_disabled_default_without_store(hass) -> None:
    """A new sandbox has no persisted state and starts disabled."""
    runtime, coordinator = _runtime("storage-clean", REGISTRATION_A)

    await runtime.async_restore_storage(hass)

    assert runtime.simulator_enabled is False
    assert runtime.energy_wh == 5_000
    assert runtime.list_snapshots() == ()
    assert runtime.storage_diagnostic is None
    coordinator.async_pause_for_sandbox.assert_not_awaited()


@pytest.mark.parametrize(
    "stage",
    (
        "load",
        "record_validation",
        "fault_validation",
        "profile_restore",
        "replay_restore",
        "enable",
    ),
)
async def test_storage_restore_failures_are_staged_sanitized_and_non_destructive(
    hass, caplog, monkeypatch, stage: str
) -> None:
    """Every restore boundary reports only a bounded reason and safe defaults."""
    source, _ = _runtime(f"storage-stage-{stage}", REGISTRATION_A)
    await source.async_restore_storage(hass)
    assert source._storage is not None
    record = source._storage_record()
    if stage == "enable":
        record["simulator_enabled"] = True
    await source._storage.async_save(record)

    restored, _ = _runtime(f"storage-stage-{stage}", REGISTRATION_A)
    secret = (
        '{"registrationId":"11111111-1111-4111-8111-111111111111",'
        '"gxId":"secret-gx","credentials":"secret-token",'
        '"profile":"sensitive-profile"}'
    )
    save = AsyncMock()
    monkeypatch.setattr(SandboxStorage, "async_save", save)
    failure = ValueError(secret)
    if stage == "load":
        monkeypatch.setattr(
            SandboxStorage, "async_load", AsyncMock(side_effect=failure)
        )
    elif stage == "record_validation":
        monkeypatch.setattr(
            restored, "_validated_storage_record", Mock(side_effect=failure)
        )
    elif stage == "fault_validation":
        monkeypatch.setattr(
            restored, "_validated_fault_storage", Mock(side_effect=failure)
        )
    elif stage == "profile_restore":
        monkeypatch.setattr(
            restored, "_async_restore_profile_state", AsyncMock(side_effect=failure)
        )
    elif stage == "replay_restore":
        monkeypatch.setattr(
            restored, "_async_restore_replay_state", AsyncMock(side_effect=failure)
        )
    else:
        monkeypatch.setattr(restored, "async_enable", AsyncMock(side_effect=failure))

    await restored.async_restore_storage(hass)

    diagnostic = restored.storage_diagnostic
    assert diagnostic is not None
    assert f"at {stage} (ValueError)" in diagnostic
    assert diagnostic.endswith("Details redacted.")
    assert len(diagnostic) <= 240
    assert diagnostic in caplog.messages
    for forbidden in (
        "registrationId",
        "11111111-1111-4111-8111-111111111111",
        "secret-gx",
        "credentials",
        "secret-token",
        "sensitive-profile",
        "{",
    ):
        assert forbidden not in diagnostic
        assert forbidden not in caplog.text
    assert restored.simulator_enabled is False
    assert restored.energy_wh == 5_000
    assert restored.list_snapshots() == ()
    save.assert_not_awaited()


async def test_storage_restore_keeps_known_sanitized_validation_reason(
    hass, monkeypatch
) -> None:
    """An integration-authored validation error remains useful to the user."""
    runtime, _ = _runtime("storage-sanitized-reason", REGISTRATION_A)
    await runtime.async_restore_storage(hass)
    assert runtime._storage is not None
    await runtime._storage.async_save(runtime._storage_record())

    restored, _ = _runtime("storage-sanitized-reason", REGISTRATION_A)
    monkeypatch.setattr(
        restored,
        "_validated_storage_record",
        Mock(side_effect=ValueError("Stored state is not an object")),
    )

    await restored.async_restore_storage(hass)

    assert restored.storage_diagnostic == (
        "Storage restore failed at record_validation (ValueError): "
        "Stored state is not an object"
    )


async def test_save_reload_restore_preserves_state_without_time_jump(hass) -> None:
    """Disabled state restores exactly and does not advance during downtime."""
    runtime, _ = _runtime("storage-reload", REGISTRATION_A)
    await runtime.async_restore_storage(hass)
    await _enable(runtime, hass)
    runtime.set_inputs(load_w=1_000, solar_w=0)
    await runtime.async_step()
    restored_time = runtime.virtual_time_utc
    restored_energy = runtime.energy_wh
    await runtime.async_disable()

    reloaded, coordinator = _runtime("storage-reload", REGISTRATION_A)
    await reloaded.async_restore_storage(hass)

    assert reloaded.simulator_enabled is False
    assert reloaded.virtual_time_utc == restored_time
    assert reloaded.energy_wh == restored_energy
    assert reloaded.storage_diagnostic is None
    coordinator.async_pause_for_sandbox.assert_not_awaited()


async def test_enabled_runtime_restart_restores_only_its_clock_and_task(hass) -> None:
    """An enabled entry restarts from its saved virtual time without wall-clock catchup."""
    runtime, _ = _runtime("storage-enabled", REGISTRATION_A)
    await runtime.async_restore_storage(hass)
    await _enable(runtime, hass)
    await runtime.async_step()
    saved_time = runtime.virtual_time_utc
    await runtime.async_unload()

    reloaded, coordinator = _runtime("storage-enabled", REGISTRATION_A)
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
        new=AsyncMock(return_value=lambda: None),
    ):
        await reloaded.async_restore_storage(hass)

    assert reloaded.simulator_enabled is True
    assert reloaded.virtual_time_utc == saved_time
    coordinator.async_pause_for_sandbox.assert_awaited_once()
    await reloaded.async_disable()


async def test_three_entries_keep_records_and_snapshots_isolated(hass) -> None:
    """Records, identities, and named snapshots never cross entry boundaries."""
    first, _ = _runtime("storage-a", REGISTRATION_A)
    second, _ = _runtime("storage-b", REGISTRATION_B)
    third, _ = _runtime("storage-c", REGISTRATION_C)
    for runtime in (first, second, third):
        await runtime.async_restore_storage(hass)
    await first.async_save_snapshot("first")
    await second.async_save_snapshot("second")

    assert first.list_snapshots() == ("first",)
    assert second.list_snapshots() == ("second",)
    assert third.list_snapshots() == ()
    assert len({first.pretend_gx_id, second.pretend_gx_id, third.pretend_gx_id}) == 3


async def test_identity_mismatch_and_invalid_records_fall_back_without_deletion(hass) -> None:
    """Foreign, future, malformed, and out-of-range data is retained but not restored."""
    original, _ = _runtime("storage-invalid", REGISTRATION_A)
    await original.async_restore_storage(hass)
    await original.async_checkpoint(immediate=True)

    mismatched, _ = _runtime("storage-invalid", REGISTRATION_B)
    await mismatched.async_restore_storage(hass)
    assert mismatched.simulator_enabled is False
    assert mismatched.energy_wh == 5_000
    assert mismatched.storage_diagnostic is not None

    store = SandboxStorage(hass, "storage-invalid")
    record = await store.async_load()
    assert record is not None and record["registration_id"] == REGISTRATION_A
    await store.async_save(
        {
            **record,
            "storage_schema_version": STORAGE_SCHEMA_VERSION + 1,
        }
    )
    future, _ = _runtime("storage-invalid", REGISTRATION_A)
    await future.async_restore_storage(hass)
    assert future.storage_diagnostic is not None


async def test_schema_one_record_migrates_without_losing_state_or_snapshots(hass) -> None:
    """Step 17A records remain readable after profile state is introduced."""
    original, _ = _runtime("storage-schema-one", REGISTRATION_A)
    await original.async_restore_storage(hass)
    await original.async_save_snapshot("keep")
    record = original._storage_record()
    legacy_record = {
        key: value
        for key, value in record.items()
        if key
        not in {"selected_profile_filename", "profile_hash", "playback_state"}
    }
    legacy_record["storage_schema_version"] = 1
    assert original._storage is not None
    await original._storage.async_save(legacy_record)

    restored, _ = _runtime("storage-schema-one", REGISTRATION_A)
    await restored.async_restore_storage(hass)

    assert restored.energy_wh == original.energy_wh
    assert restored.list_snapshots() == ("keep",)
    await restored.async_checkpoint(immediate=True)
    migrated = await SandboxStorage(hass, "storage-schema-one").async_load()
    assert migrated is not None and migrated["storage_schema_version"] == STORAGE_SCHEMA_VERSION


async def test_schema_ten_ledger_migration_resets_only_corrupted_ledgers(hass) -> None:
    """The positional-ledger release keeps state but clears current and named totals."""
    runtime, _ = _runtime("storage-ledger-migration", REGISTRATION_A)
    await runtime.async_restore_storage(hass)
    await _enable(runtime, hass)
    runtime.set_inputs(load_w=750, solar_w=100)
    await runtime.async_step(30)
    await runtime.async_save_snapshot("before")
    assert runtime._storage is not None
    record = runtime._storage_record()
    record["storage_schema_version"] = 10
    record["snapshot_schema_version"] = 3
    for key in ("current_snapshot",):
        snapshot = json.loads(record[key])
        snapshot["schema_version"] = 3
        snapshot["cumulative_ledger"]["manual_adjustment_wh"] = 999.0
        snapshot["cumulative_ledger"]["balance_error_wh"] = 888.0
        record[key] = json.dumps(snapshot, separators=(",", ":"))
    snapshots = record["snapshots"]
    assert isinstance(snapshots, dict)
    for name, serialized in snapshots.items():
        snapshot = json.loads(serialized)
        snapshot["schema_version"] = 3
        snapshot["cumulative_ledger"]["manual_adjustment_wh"] = 777.0
        snapshots[name] = json.dumps(snapshot, separators=(",", ":"))
    await runtime._storage.async_save(record)

    restored, _ = _runtime("storage-ledger-migration", REGISTRATION_A)
    await restored.async_restore_storage(hass)

    assert restored.energy_wh == runtime.energy_wh
    assert restored.virtual_time_utc == runtime.virtual_time_utc
    assert restored.energy_ledger == IntervalLedger()
    assert restored.storage_diagnostic is not None
    await restored.async_restore_snapshot("before")
    assert restored.energy_ledger == IntervalLedger()
    migrated = await SandboxStorage(hass, "storage-ledger-migration").async_load()
    assert migrated is not None
    assert migrated["storage_schema_version"] == STORAGE_SCHEMA_VERSION
    assert migrated["snapshot_schema_version"] == 4

    reloaded, _ = _runtime("storage-ledger-migration", REGISTRATION_A)
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
        new=AsyncMock(return_value=lambda: None),
    ):
        await reloaded.async_restore_storage(hass)
    assert reloaded.energy_wh == runtime.energy_wh
    assert reloaded.energy_ledger == IntervalLedger()
    assert reloaded.storage_diagnostic is None


async def test_reserve_validation_rejects_snapshot_atomically(hass) -> None:
    """An invalid restored battery energy leaves default state untouched."""
    runtime, _ = _runtime("storage-reserve", REGISTRATION_A)
    await runtime.async_restore_storage(hass)
    invalid = SimulationSnapshot(
        1,
        BatteryState(1),
        IntervalLedger(),
        ClockState(datetime.now(timezone.utc), "paused"),
    )
    assert runtime._storage is not None
    await runtime._storage.async_save(
        {
            **runtime._storage_record(),
            "current_snapshot": to_json(invalid),
        }
    )

    restored, _ = _runtime("storage-reserve", REGISTRATION_A)
    await restored.async_restore_storage(hass)
    assert restored.energy_wh == 5_000
    assert restored.storage_diagnostic is not None


async def test_named_snapshot_lifecycle_limit_and_atomic_restore(hass) -> None:
    """Snapshots are bounded, replace explicitly, and never partially restore."""
    runtime, coordinator = _runtime("storage-snapshots", REGISTRATION_A)
    await runtime.async_restore_storage(hass)
    await runtime.async_save_snapshot("before")
    with pytest.raises(ValueError, match="already exists"):
        await runtime.async_save_snapshot(" before ")
    await runtime.async_save_snapshot("before", replace=True)
    for number in range(19):
        await runtime.async_save_snapshot(f"snapshot-{number}")
    assert len(runtime.list_snapshots()) == 20
    with pytest.raises(ValueError, match="limit"):
        await runtime.async_save_snapshot("overflow")

    before_energy = runtime.energy_wh
    runtime._named_snapshots["broken"] = "{}"
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",
        new=AsyncMock(),
    ) as mqtt_publish:
        with pytest.raises(ValueError):
            await runtime.async_restore_snapshot("broken")
    assert runtime.energy_wh == before_energy
    mqtt_publish.assert_not_awaited()
    coordinator.async_pause_for_sandbox.assert_not_awaited()
    coordinator.async_resume_from_sandbox.assert_not_awaited()

    await runtime.async_delete_snapshot("before")
    assert "before" not in runtime.list_snapshots()


async def test_snapshot_restore_discards_observed_node_red_status(hass) -> None:
    """A snapshot never restores an observed external bridge outcome."""
    runtime, _ = _runtime("storage-external-status", REGISTRATION_A)
    await runtime.async_restore_storage(hass)
    await runtime.async_save_snapshot("clean")
    assert runtime.pretend_gx_id is not None
    runtime._node_red_status = RuntimeStatus(
        runtime.pretend_gx_id,
        datetime.now(timezone.utc),
        "healthy",
        "observed remote state",
    )

    await runtime.async_restore_snapshot("clean")

    assert runtime.node_red_status is not None
    assert runtime.node_red_status.state == "unavailable"


async def test_unload_flushes_and_removal_deletes_only_own_store(hass) -> None:
    """Unload saves pending state; removal cannot delete another entry's record."""
    first, _ = _runtime("storage-remove-a", REGISTRATION_A)
    second, _ = _runtime("storage-remove-b", REGISTRATION_B)
    await first.async_restore_storage(hass)
    await second.async_restore_storage(hass)
    await _enable(first, hass)
    first.set_inputs(load_w=1_000, solar_w=0)
    await first._async_simulate(5)
    expected_energy = first.energy_wh
    await first.async_unload()
    await second.async_checkpoint(immediate=True)

    reloaded, _ = _runtime("storage-remove-a", REGISTRATION_A)
    await reloaded.async_restore_storage(hass)
    assert reloaded.energy_wh == expected_energy
    await async_remove_entry_storage(hass, "storage-remove-a")
    assert await SandboxStorage(hass, "storage-remove-a").async_load() is None
    assert await SandboxStorage(hass, "storage-remove-b").async_load() is not None


async def test_serialized_storage_excludes_secrets_and_actual_telemetry(hass) -> None:
    """The record contains only identity and reproducible virtual state."""
    runtime, _ = _runtime("storage-security", REGISTRATION_A)
    await runtime.async_restore_storage(hass)
    await runtime.async_checkpoint(immediate=True)
    stored = await SandboxStorage(hass, "storage-security").async_load()
    assert stored is not None
    serialized = str(stored).lower()
    for forbidden in (
        "api_key",
        "token",
        "password",
        "broker",
        "oauth",
        "forecast",
        "actual",
    ):
        assert forbidden not in serialized

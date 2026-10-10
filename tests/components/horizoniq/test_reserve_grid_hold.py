"""Grid-preservation parser, physics and snapshot regressions."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import uuid4

import pytest

from custom_components.horizoniq.coordinator_helpers import build_snapshot
from custom_components.horizoniq.forecast_schema5 import Schema5ForecastError
from custom_components.horizoniq.direct_control import (
    parse_live_command, parse_replay_command, validate_virtual_recommendation,
)
from custom_components.horizoniq.sandbox_runtime import HorizonIQEntryRuntime
from custom_components.horizoniq.simulation.models import (
    BatteryConfig, BatteryState, ClockState, Command, CommandStatus,
    IntervalLedger, OperatingMode, SimulationSnapshot,
)
from custom_components.horizoniq.simulation.physics import simulate_step
from custom_components.horizoniq.simulation.snapshots import from_json, to_json

NOW = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
CONFIG = BatteryConfig(10_000, 2_000, 2_000, 2_000, 1, 1)
FIXTURE = Path(__file__).with_name("fixtures") / "direct_schema5_forecast.json"


def _payload(action="use_grid", *, schema=6, authority="live", capability=True):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["schemaVersion"] = schema
    payload["planId"] = str(uuid4())
    payload["planKind"] = "sandbox_replay" if authority == "replay" else "live"
    payload["createdAtUtc"] = (NOW - timedelta(seconds=2)).isoformat().replace("+00:00", "Z")
    payload["effectiveAtUtc"] = NOW.isoformat().replace("+00:00", "Z")
    payload["shouldImport"] = action in {"charge_required", "import_for_export"}
    payload["shouldUseGrid"] = action == "use_grid"
    payload["equipmentProfile"]["supportedControl"]["useGrid"] = capability
    payload["equipmentProfile"]["batteryCapacityWh"] = 10_000
    payload["equipmentProfile"]["minimumCapacityPercentage"] = 0.2
    if schema == 6:
        payload["shouldExport"] = action == "export_for_profit"
    period = deepcopy(payload["periods"][0])
    payload["periods"] = [period]
    period["date"] = NOW.isoformat().replace("+00:00", "Z")
    period["shouldImport"] = payload["shouldImport"]
    period["shouldUseGrid"] = payload["shouldUseGrid"]
    period["estimatedGeneration"] = 0
    if schema == 6:
        period["shouldExport"] = action == "export_for_profit"
    period["recommendedAction"] = action
    period["simulationAction"] = action if authority == "replay" else "none"
    period["executableAction"] = action if authority == "live" else "none"
    period["decisionTrace"]["selectedAction"] = action
    period["actionPriority"] = {
        "charge_required": 1, "import_for_export": 2 if schema == 6 else 5,
        "use_grid": 3 if schema == 6 else 4,
    }.get(action)
    if authority != "live":
        for key in ("commandId", "issuedAtUtc", "expiresAtUtc", "actionPriority"):
            period[key] = None
    else:
        period["commandId"] = str(uuid4())
        period["issuedAtUtc"] = NOW.isoformat().replace("+00:00", "Z")
        period["expiresAtUtc"] = (NOW + timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
    charging = action in {"charge_required", "import_for_export"}
    exporting = action == "export_for_profit"
    load_kwh = 0.2
    charge_kwh = 0.5 if charging else 0.0
    discharge_kwh = 0.5 if exporting else 0.0
    import_kwh = load_kwh + charge_kwh if not exporting else 0.0
    export_kwh = discharge_kwh - load_kwh if exporting else 0.0
    cost = import_kwh * 0.11
    revenue = export_kwh * 0.05
    end_kwh = 2.5 + charge_kwh - discharge_kwh
    payload["currentCapacity"] = 2.5
    payload["minCapacity"] = 2.0
    payload["targetCapacity"] = 2.0
    payload["totalCost"] = cost - revenue
    payload["chargingCost"] = charge_kwh * 0.11
    payload["saving"] = revenue
    payload["economicsAssumptions"].update({
        "chargeEfficiency": 1, "dischargeEfficiency": 1,
        "degradationCost": 0, "supplierFeeAllowance": 0,
        "uncertaintyHaircut": 0,
    })
    payload["plannedEnergyLedger"].update({
        "gridImportKwh": import_kwh, "solarGenerationKwh": 0,
        "loadKwh": load_kwh, "batteryChargeKwh": charge_kwh,
        "batteryDischargeKwh": discharge_kwh,
        "gridExportKwh": export_kwh, "modeledLossesKwh": 0,
        "balanceErrorKwh": 0, "healthy": True,
    })
    period.update({
        "used": load_kwh, "expectedStartSoc": 2.5,
        "expectedEndSoc": end_kwh, "expectedImport": import_kwh,
        "expectedExport": export_kwh, "expectedCost": cost,
        "expectedRevenue": revenue, "expectedNetValue": revenue - cost,
        "amount": charge_kwh or discharge_kwh, "imported": import_kwh,
        "exported": export_kwh, "battery": charge_kwh - discharge_kwh,
    })
    trace = period["decisionTrace"]
    trace.update({
        "selectedAction": action,
        "reasonCode": "normal_charge_priority" if action == "charge_required" else "selected",
        "explanation": "Required charging has priority." if action == "charge_required" else "Selected current flow.",
        "rejectedCandidateActions": [],
        "importRate": 0.11, "exportRate": 0.05,
        "expectedImportKwh": import_kwh, "expectedExportKwh": export_kwh,
        "expectedStartSocKwh": 2.5, "expectedEndSocKwh": end_kwh,
    })
    trace["constraints"].update({
        "reserveKwh": 2.0, "availableHeadroomKwh": 7.5,
        "chargePowerLimitKwh": 1.5, "dischargePowerLimitKwh": 1.5,
    })
    trace["economicCalculation"].update({
        "importCost": cost, "exportRevenue": revenue,
        "supplierFees": 0, "degradationCost": 0,
        "grossValue": revenue - cost,
        "riskAdjustedNetValue": revenue - cost,
    })
    return payload


def _forecast(payload):
    forecast = build_snapshot(payload).direct_forecast
    assert forecast is not None
    return forecast


def test_all_direct_use_grid_paths_select_grid_preservation():
    live = parse_live_command(_forecast(_payload()), now_utc=NOW, config=CONFIG)
    assert live.command.mode is OperatingMode.GRID_PRESERVATION
    assert live.command.requested_grid_power_w is None
    assert live.command.expires_at_utc == NOW + timedelta(minutes=30)
    legacy = parse_live_command(
        _forecast(_payload(capability=False)), now_utc=NOW, config=CONFIG
    )
    assert legacy.command.mode is OperatingMode.GRID_PRESERVATION
    assert legacy.command.requested_grid_power_w is None
    assert legacy.command.expires_at_utc == live.command.expires_at_utc
    generic = validate_virtual_recommendation(
        _forecast(_payload(authority="virtual", capability=False)), now_utc=NOW, config=CONFIG
    )
    assert generic.command is not None
    assert generic.command.command.mode is OperatingMode.GRID_PRESERVATION
    assert generic.command.command.requested_grid_power_w is None
    replay = parse_replay_command(_payload(authority="replay", capability=False), virtual_now_utc=NOW, config=CONFIG)
    assert replay.command.mode is OperatingMode.GRID_PRESERVATION
    assert replay.command.requested_grid_power_w is None


@pytest.mark.parametrize("schema,action,priority", [
    (6, "charge_required", 1), (6, "import_for_export", 2), (6, "use_grid", 3),
    (5, "charge_required", 1), (5, "import_for_export", 5), (5, "use_grid", 4),
])
def test_live_priorities_match_each_supported_schema(schema, action, priority):
    payload = _payload(action, schema=schema)
    assert payload["periods"][0]["actionPriority"] == priority
    assert parse_live_command(_forecast(payload), now_utc=NOW, config=CONFIG).action == action
    for invalid in (None, True, priority + 1):
        bad = deepcopy(payload)
        bad["periods"][0]["actionPriority"] = invalid
        with pytest.raises(ValueError):
            parse_live_command(_forecast(bad), now_utc=NOW, config=CONFIG)
    bad = deepcopy(payload)
    bad["schemaVersion"] = 7
    with pytest.raises(Schema5ForecastError, match="Unsupported forecast schemaVersion"):
        build_snapshot(bad)


@pytest.mark.parametrize("load,solar,energy,charge_limit,expected_end,grid_w", [
    (600, 0, 2500, 2000, 2500, 600),
    (800, 400, 2500, 2000, 2500, 400),
    (400, 400, 2500, 2000, 2500, 0),
    (200, 400, 2500, 2000, 2600, 0),
    (200, 400, 10000, 2000, 10000, -200),
    (200, 400, 2500, 0, 2500, -200),
])
def test_hold_uses_actual_load_and_solar(load, solar, energy, charge_limit, expected_end, grid_w):
    config = replace(CONFIG, max_charge_power_w=charge_limit)
    result = simulate_step(
        previous=BatteryState(energy), elapsed_seconds=1800,
        virtual_time_utc=NOW, command=Command(OperatingMode.GRID_PRESERVATION),
        load_w=load, solar_w=solar, config=config,
    )
    assert result.state.energy_wh == expected_end
    assert result.actual_grid_power_w == grid_w
    assert result.ledger.balance_error_wh == pytest.approx(0)
    assert result.ledger.battery_energy_decrease_wh == 0
    if solar == 0:
        assert result.ledger.grid_import_wh == 300
    old = simulate_step(
        previous=BatteryState(2500), elapsed_seconds=1800, virtual_time_utc=NOW,
        command=Command(OperatingMode.GRID_SETPOINT, 0), load_w=600,
        solar_w=0, config=CONFIG,
    )
    assert old.state.energy_wh == 2200


def test_hold_window_and_invalid_setpoint_use_existing_fallbacks():
    command = Command(OperatingMode.GRID_PRESERVATION, None, NOW, NOW + timedelta(minutes=30))
    def step(when, seconds, selected=command):
        return simulate_step(previous=BatteryState(2500), elapsed_seconds=seconds,
            virtual_time_utc=when, command=selected, load_w=600, solar_w=0, config=CONFIG)
    assert step(NOW, 0).state.energy_wh == 2500
    assert step(NOW, 60).command_status is CommandStatus.APPLIED
    assert step(NOW + timedelta(minutes=30), 60).command_status is CommandStatus.FALLBACK_EXPIRED
    assert step(NOW - timedelta(seconds=1), 60).command_status is CommandStatus.FALLBACK_STALE
    invalid = replace(command, requested_grid_power_w=0)
    result = step(NOW, 60, invalid)
    assert result.command_status is CommandStatus.FALLBACK_INVALID
    assert result.reason == "Grid preservation command is invalid; self-consumption used."
    assert result.state.energy_wh == 2490


def test_hold_snapshot_round_trip_and_invalid_restore_are_atomic():
    snapshot = SimulationSnapshot(
        4, BatteryState(2500), IntervalLedger(), ClockState(NOW, "paused", 0, 0),
        None, None, Command(OperatingMode.GRID_PRESERVATION, None, NOW, NOW + timedelta(minutes=30)),
        CommandStatus.APPLIED, 600, 0,
    )
    encoded = to_json(snapshot)
    assert from_json(encoded).active_command == snapshot.active_command
    runtime = HorizonIQEntryRuntime(coordinator=None, registration_id="registration")
    runtime._config = CONFIG
    runtime._state = BatteryState(2500)
    runtime._cumulative_ledger = IntervalLedger()
    assert runtime._validated_snapshot(from_json(encoded)) == snapshot
    for schema in (1, 2, 3, 4):
        older = json.loads(encoded)
        older["schema_version"] = schema
        older["active_command"]["mode"] = "grid_setpoint"
        older["active_command"]["requested_grid_power_w"] = 0
        assert from_json(json.dumps(older)).active_command.mode is OperatingMode.GRID_SETPOINT
    invalid = json.loads(encoded)
    invalid["active_command"]["requested_grid_power_w"] = 0
    before = (runtime._state, runtime._cumulative_ledger)
    with pytest.raises(ValueError, match="Stored command is invalid"):
        runtime._validated_snapshot(from_json(json.dumps(invalid)))
    assert (runtime._state, runtime._cumulative_ledger) == before
    invalid["active_command"]["mode"] = "unknown"
    with pytest.raises(ValueError, match="snapshot is invalid"):
        from_json(json.dumps(invalid))

def test_partial_period_command_uses_remaining_time_and_full_slot_solar_power():
    now = NOW + timedelta(minutes=29, seconds=56)
    payload = _payload("charge_required")
    hours = 4 / 3600
    load_kwh = 400 * hours / 1000
    solar_kwh = 200 * hours / 1000
    charge_kwh = 0.003 + solar_kwh - load_kwh
    period = payload["periods"][0]
    period.update({
        "expectedImport": 0.003, "estimatedGeneration": 100,
        "used": load_kwh, "expectedEndSoc": 2.5 + charge_kwh,
        "expectedCost": 0.003 * 0.11,
        "expectedNetValue": -0.003 * 0.11,
        "amount": charge_kwh, "imported": 0.003,
        "battery": charge_kwh,
    })
    payload["plannedEnergyLedger"].update({
        "gridImportKwh": 0.003, "solarGenerationKwh": solar_kwh,
        "loadKwh": load_kwh, "batteryChargeKwh": charge_kwh,
    })
    payload["totalCost"] = 0.003 * 0.11
    payload["chargingCost"] = charge_kwh * 0.11
    trace = period["decisionTrace"]
    trace.update({
        "expectedImportKwh": 0.003,
        "expectedEndSocKwh": 2.5 + charge_kwh,
    })
    trace["constraints"]["chargePowerLimitKwh"] = 3000 * hours / 1000
    trace["constraints"]["dischargePowerLimitKwh"] = 3000 * hours / 1000
    trace["economicCalculation"].update({
        "importCost": 0.003 * 0.11,
        "grossValue": -0.003 * 0.11,
        "riskAdjustedNetValue": -0.003 * 0.11,
    })
    forecast = _forecast(payload)
    command = parse_live_command(
        forecast, now_utc=now, config=replace(CONFIG, max_charge_power_w=3000)
    )
    assert command.command.requested_grid_power_w == pytest.approx(2700)
    runtime = HorizonIQEntryRuntime(coordinator=None, registration_id="registration")
    runtime._staged_direct_forecast = forecast
    runtime._live_forecast_now = lambda: now
    runtime._update_forecast_solar(now)
    assert runtime.solar_w == 200  # full half-hour Wh-to-W conversion
    hold = simulate_step(
        previous=BatteryState(2500), elapsed_seconds=4,
        virtual_time_utc=now, command=Command(OperatingMode.GRID_PRESERVATION),
        load_w=600, solar_w=runtime.solar_w, config=CONFIG,
    )
    assert hold.state.energy_wh == 2500
    assert hold.actual_grid_power_w == 400
    assert hold.ledger.grid_import_wh == pytest.approx(400 * 4 / 3600)


@pytest.mark.asyncio
async def test_replay_snapshot_restore_retains_valid_hold_and_rejects_invalid_atomically():
    from custom_components.horizoniq.simulation.clock import VirtualClock
    runtime = HorizonIQEntryRuntime(coordinator=None, registration_id="registration")
    runtime._config = CONFIG
    runtime._state = BatteryState(2500)
    runtime._clock = VirtualClock(NOW)
    runtime._operating_mode = "replay"
    runtime._command = Command(OperatingMode.GRID_PRESERVATION, None, NOW, NOW + timedelta(minutes=30))
    await runtime.async_save_snapshot("replay-hold")
    runtime._command = Command(OperatingMode.SELF_CONSUMPTION)
    await runtime.async_restore_snapshot("replay-hold")
    assert runtime._command.mode is OperatingMode.GRID_PRESERVATION
    assert runtime.active_setpoint_w is None
    saved = json.loads(runtime._named_snapshots["replay-hold"])
    saved["active_command"]["requested_grid_power_w"] = 0
    runtime._named_snapshots["invalid"] = json.dumps(saved)
    stored_evidence = dict(runtime._named_snapshots)
    before = (runtime._state, runtime._cumulative_ledger, runtime._clock.state, runtime._command)
    with pytest.raises(ValueError, match="Stored command is invalid"):
        await runtime.async_restore_snapshot("invalid")
    assert (runtime._state, runtime._cumulative_ledger, runtime._clock.state, runtime._command) == before
    assert runtime._named_snapshots == stored_evidence

def test_live_unsupported_action_cannot_become_a_grid_hold():
    payload = _payload("export_for_profit")
    with pytest.raises(ValueError, match="not executable"):
        parse_live_command(_forecast(payload), now_utc=NOW, config=CONFIG)

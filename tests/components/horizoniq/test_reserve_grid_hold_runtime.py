"""Real config-entry and coordinator grid-hold lifecycle regressions."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import NAMESPACE_DNS, uuid4, uuid5

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from homeassistant.helpers import entity_registry

from custom_components.horizoniq.const import (
    CAPACITY_SOURCE_VIRTUAL_BATTERY, CONF_API_KEY, CONF_BATTERY_CAPACITY_SENSOR,
    CONF_CAPACITY_SOURCE, CONF_ENVIRONMENT, CONF_HASH, CONF_REGISTRATION_CONFIG,
    CONF_REGISTRATION_DATA, CONF_REGISTRATION_ID, CONF_URL, DOMAIN,
    SANDBOX_ENVIRONMENT,
)
from custom_components.horizoniq.entity_helpers import build_unique_id
from custom_components.horizoniq.models import ForecastFreshness, HorizonIQSnapshot
from custom_components.horizoniq.simulation.models import CommandStatus, OperatingMode
from custom_components.horizoniq.simulation.snapshots import SNAPSHOT_SCHEMA_VERSION
from custom_components.horizoniq.sandbox_runtime import STORAGE_SCHEMA_VERSION

START = datetime(2026, 9, 25, tzinfo=timezone.utc)
FIXTURE = Path(__file__).with_name("fixtures") / "direct_schema5_forecast.json"


def _entry(entry_id="grid-hold-entry"):
    return MockConfigEntry(
        domain=DOMAIN, title="HorizonIQ (Sandbox)", entry_id=entry_id, version=3,
        data={
            CONF_URL: "https://example.com/api/Forecast_Get?code=test-code",
            CONF_API_KEY: "test-api-key",
            CONF_BATTERY_CAPACITY_SENSOR: "sensor.unused_capacity",
            CONF_ENVIRONMENT: SANDBOX_ENVIRONMENT,
            CONF_CAPACITY_SOURCE: CAPACITY_SOURCE_VIRTUAL_BATTERY,
            CONF_HASH: "", CONF_REGISTRATION_DATA: "",
            CONF_REGISTRATION_ID: str(uuid5(NAMESPACE_DNS, entry_id)),
            CONF_REGISTRATION_CONFIG: {
                "ChargeEfficiency": 1, "DischargeEfficiency": 1,
                "EquipmentProfile": {
                    "BatteryCapacityWh": 10_000, "MinimumCapacityPercentage": 0.2,
                    "MaximumBatteryChargePowerWatts": 2_000,
                    "MaximumBatteryDischargePowerWatts": 2_000,
                },
            },
        },
    )


def _entity_id(hass, entry_id, suffix, domain="sensor"):
    entity_id = entity_registry.async_get(hass).async_get_entity_id(
        domain, DOMAIN, build_unique_id(SANDBOX_ENVIRONMENT, entry_id, suffix)
    )
    assert entity_id is not None
    return entity_id


def _wire(now, *, action="use_grid", energy_wh=2500, cadence=5):
    """Build a complete, energy-balanced current-window schema-6 response."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    period_start = now.replace(minute=0 if now.minute < 30 else 30, second=0, microsecond=0)
    end = period_start + timedelta(minutes=30)
    hold = action == "use_grid"
    charging = action == "charge_required"
    exporting = action == "export_for_profit"
    payload["schemaVersion"] = 6
    payload["planId"] = str(uuid4())
    payload["planKind"] = "live"
    payload["createdAtUtc"] = now.isoformat().replace("+00:00", "Z")
    payload["effectiveAtUtc"] = now.isoformat().replace("+00:00", "Z")
    payload["forecastCadenceMinutes"] = cadence
    payload["currentCapacity"] = energy_wh / 1000
    payload["shouldImport"] = charging
    payload["shouldUseGrid"] = hold
    payload["shouldExport"] = exporting
    period = payload["periods"][0]
    payload["periods"] = [period]
    period["date"] = period_start.isoformat().replace("+00:00", "Z")
    period["period"] = 0
    period["shouldImport"] = charging
    period["shouldUseGrid"] = hold
    period["shouldExport"] = exporting
    period["recommendedAction"] = action
    period["executableAction"] = "none" if exporting else action
    period["simulationAction"] = "none"
    period["commandId"] = str(uuid4())
    period["issuedAtUtc"] = now.isoformat().replace("+00:00", "Z")
    period["expiresAtUtc"] = end.isoformat().replace("+00:00", "Z")
    period["actionPriority"] = None if exporting else (3 if hold else 1)
    if exporting:
        for key in ("commandId", "issuedAtUtc", "expiresAtUtc"):
            period[key] = None
    remaining_hours = (end - now).total_seconds() / 3600
    load_kwh = 0.4 * remaining_hours  # forecast 400 W; actual load is 600 W
    charge_kwh = 0.5 if charging else 0.0
    discharge_kwh = 0.5 if exporting else 0.0
    import_kwh = load_kwh + charge_kwh if not exporting else 0.0
    export_kwh = discharge_kwh - load_kwh if exporting else 0.0
    price = 0.05 if charging else 0.30
    cost = import_kwh * price
    revenue = export_kwh * 0.15
    end_kwh = energy_wh / 1000 + charge_kwh - discharge_kwh
    profile = payload["equipmentProfile"]
    profile["batteryCapacityWh"] = 10_000
    profile["minimumCapacityPercentage"] = 0.2
    profile["maximumBatteryChargePowerWatts"] = 2_000
    profile["maximumBatteryDischargePowerWatts"] = 2_000
    assumptions = payload["economicsAssumptions"]
    assumptions.update({
        "exportRate": 0.15, "chargeEfficiency": 1, "dischargeEfficiency": 1,
        "degradationCost": 0, "supplierFeeAllowance": 0,
        "uncertaintyHaircut": 0,
    })
    payload["minCapacity"] = 2.0
    payload["targetCapacity"] = 2.0
    payload["totalCost"] = cost - revenue
    payload["chargingCost"] = charge_kwh * price
    payload["saving"] = revenue
    payload["plannedEnergyLedger"].update({
        "gridImportKwh": import_kwh, "solarGenerationKwh": 0,
        "loadKwh": load_kwh, "batteryChargeKwh": charge_kwh,
        "batteryDischargeKwh": discharge_kwh, "gridExportKwh": export_kwh,
        "modeledLossesKwh": 0, "balanceErrorKwh": 0,
        "healthy": True,
    })
    period.update({
        "price": price, "estimatedGeneration": 0, "used": load_kwh,
        "expectedStartSoc": energy_wh / 1000, "expectedEndSoc": end_kwh,
        "expectedImport": import_kwh, "expectedExport": export_kwh,
        "expectedCost": cost, "expectedRevenue": revenue,
        "expectedNetValue": revenue - cost,
        "amount": charge_kwh or discharge_kwh,
        "imported": import_kwh, "exported": export_kwh,
        "battery": charge_kwh - discharge_kwh,
    })
    trace = period["decisionTrace"]
    trace.update({
        "selectedAction": action,
        "reasonCode": "normal_charge_priority" if charging else "selected",
        "explanation": "Required charging has priority." if charging else "Selected current flow.",
        "rejectedCandidateActions": [],
        "importRate": price, "exportRate": 0.15,
        "expectedImportKwh": import_kwh, "expectedExportKwh": export_kwh,
        "expectedStartSocKwh": energy_wh / 1000,
        "expectedEndSocKwh": end_kwh,
    })
    trace["constraints"].update({
        "reserveKwh": 2.0,
        "availableHeadroomKwh": 10 - energy_wh / 1000,
        "chargePowerLimitKwh": 2 * remaining_hours,
        "dischargePowerLimitKwh": 2 * remaining_hours,
    })
    trace["economicCalculation"].update({
        "importCost": cost, "exportRevenue": revenue,
        "supplierFees": 0, "degradationCost": 0,
        "grossValue": revenue - cost,
        "riskAdjustedNetValue": revenue - cost,
    })
    return payload


async def _setup(hass, aioclient_mock, entry_id="grid-hold-entry"):
    entry = _entry(entry_id)
    entry.add_to_hass(hass)
    initial_url = (
        "https://example.com/api/Forecast_Get?code=test-code"
        "&currentBatteryCapacity=5000.0&hash=&registrationData="
    )
    aioclient_mock.clear_requests()
    aioclient_mock.get(initial_url, status=429)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    runtime = hass.data[DOMAIN][entry.entry_id]
    aioclient_mock.get(initial_url, status=429)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": _entity_id(hass, entry_id, "simulation", "switch")},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN, "set_virtual_battery_state_of_charge",
        {"entry_id": entry_id, "state_of_charge": 25}, blocking=True,
    )
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": _entity_id(hass, entry_id, "load_w", "number"), "value": 600},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert runtime.energy_wh == 2500
    assert runtime.load_w == 600
    return entry, runtime


async def _deliver(runtime, aioclient_mock, now, *, action="use_grid", cadence=5):
    expected_capacity = runtime.current_capacity()
    assert float(expected_capacity) == pytest.approx(runtime.energy_wh, abs=0.001)
    url = runtime.coordinator._build_request_url(expected_capacity)
    aioclient_mock.clear_requests()
    aioclient_mock.get(url, json=_wire(now, action=action, energy_wh=runtime.energy_wh, cadence=cadence))
    await runtime._async_refresh_direct_forecast()
    assert aioclient_mock.mock_calls[-1][1].query["currentBatteryCapacity"] == expected_capacity
    runtime._virtual_next_refresh_monotonic = float("inf")
    assert runtime._last_applied_forecast_sequence > 0
    assert runtime._command.mode is (OperatingMode.GRID_PRESERVATION if action == "use_grid" else OperatingMode.GRID_SETPOINT), (now, runtime.last_command_status, runtime.last_command_reason)
    return url


@pytest.mark.asyncio
async def test_real_entry_holds_for_four_hours_then_charges(hass, aioclient_mock):
    clock = [START]
    with (
        patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()),
        patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", AsyncMock()),
        patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe", AsyncMock(return_value=lambda: None)),
        patch("custom_components.horizoniq.sandbox_runtime._LOOP_INTERVAL_SECONDS", 100000),
    ):
        entry, runtime = await _setup(hass, aioclient_mock)
        runtime._live_forecast_now = lambda: clock[0]
        runtime._virtual_monotonic_baseline = 0
        runtime._virtual_next_refresh_monotonic = float("inf")
        await _deliver(runtime, aioclient_mock, clock[0], cadence=1)
        fake_hass = SimpleNamespace(loop=SimpleNamespace(time=lambda: (clock[0] - START).total_seconds()))
        for minute in range(1, 241):
            clock[0] = START + timedelta(minutes=minute)
            assert runtime._command.mode is OperatingMode.GRID_PRESERVATION, (minute, runtime._command)
            await runtime._async_virtual_tick(fake_hass)
            runtime._virtual_next_refresh_monotonic = float("inf")
            assert runtime.energy_wh == pytest.approx(2500), (minute, runtime.last_command_status, runtime.last_command_reason)
            if minute % 30:
                assert runtime.last_command_status is CommandStatus.APPLIED
            if minute < 240 and (minute <= 60 or minute % 5 == 0):
                await _deliver(runtime, aioclient_mock, clock[0], cadence=1 if minute <= 60 else 5)
            if minute % 30 == 0:
                assert runtime.energy_wh == pytest.approx(2500)
                assert runtime.grid_power_w == pytest.approx(600)
                assert runtime.battery_power_w == pytest.approx(0)
                assert hass.states.get(_entity_id(hass, entry.entry_id, "energy")).state == "2500.0"
                assert hass.states.get(_entity_id(hass, entry.entry_id, "grid_power")).state == "600.0"
                assert hass.states.get(_entity_id(hass, entry.entry_id, "battery_power")).state == "0.0"
        assert runtime.last_command_status in {CommandStatus.APPLIED, CommandStatus.FALLBACK_EXPIRED}
        await _deliver(runtime, aioclient_mock, clock[0], action="charge_required")
        clock[0] += timedelta(minutes=1)
        await runtime._async_virtual_tick(fake_hass)
        assert runtime.energy_wh > 2500
        assert runtime.battery_power_w > 0
        assert runtime.grid_power_w > 600
        assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
async def test_fresh_hold_replaces_export_without_retaining_export_power(hass, aioclient_mock):
    clock = [START]
    with (
        patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()),
        patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", AsyncMock()),
        patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe", AsyncMock(return_value=lambda: None)),
        patch("custom_components.horizoniq.sandbox_runtime._LOOP_INTERVAL_SECONDS", 100000),
    ):
        entry, runtime = await _setup(hass, aioclient_mock, "replace-entry")
        runtime._live_forecast_now = lambda: clock[0]
        runtime._virtual_monotonic_baseline = 0
        runtime._virtual_next_refresh_monotonic = float("inf")
        await _deliver(runtime, aioclient_mock, clock[0], action="export_for_profit")
        clock[0] += timedelta(minutes=1)
        await runtime._async_virtual_tick(SimpleNamespace(loop=SimpleNamespace(time=lambda: 60)))
        assert runtime.battery_power_w < 0
        assert runtime.grid_power_w < 0
        assert runtime.energy_wh < 2500
        await _deliver(runtime, aioclient_mock, clock[0])
        assert runtime._command.mode is OperatingMode.GRID_PRESERVATION
        clock[0] += timedelta(minutes=1)
        await runtime._async_virtual_tick(SimpleNamespace(loop=SimpleNamespace(time=lambda: 120)))
        held_energy = runtime.energy_wh
        assert runtime.battery_power_w == 0
        assert runtime.grid_power_w == 600
        await _deliver(runtime, aioclient_mock, clock[0])
        clock[0] += timedelta(minutes=1)
        await runtime._async_virtual_tick(SimpleNamespace(loop=SimpleNamespace(time=lambda: 180)))
        assert runtime.energy_wh == held_energy
        await hass.services.async_call(
            DOMAIN, "set_virtual_battery_state_of_charge",
            {"entry_id": entry.entry_id, "state_of_charge": 20}, blocking=True,
        )
        assert runtime.energy_wh == 2000
        await _deliver(runtime, aioclient_mock, clock[0])
        clock[0] += timedelta(minutes=1)
        await runtime._async_virtual_tick(SimpleNamespace(loop=SimpleNamespace(time=lambda: 240)))
        assert runtime.energy_wh == 2000
        assert runtime.grid_power_w == 600
        await _deliver(runtime, aioclient_mock, clock[0], action="charge_required")
        clock[0] += timedelta(minutes=1)
        await runtime._async_virtual_tick(SimpleNamespace(loop=SimpleNamespace(time=lambda: 300)))
        assert runtime.energy_wh > 2000
        assert runtime.battery_power_w > 0
        assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
async def test_hold_expiry_stale_refresh_and_entry_lifecycle_remain_isolated(hass, aioclient_mock):
    clock = [START]
    with (
        patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()),
        patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", AsyncMock()),
        patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe", AsyncMock(return_value=lambda: None)),
        patch("custom_components.horizoniq.sandbox_runtime._LOOP_INTERVAL_SECONDS", 100000),
    ):
        entry, runtime = await _setup(hass, aioclient_mock, "lifecycle-entry")
        runtime._live_forecast_now = lambda: clock[0]
        await _deliver(runtime, aioclient_mock, clock[0])
        first = runtime._command
        snapshot = runtime.coordinator.data
        assert snapshot is not None
        await runtime._async_stage_forecast_snapshot(snapshot)
        assert runtime._command == first
        await runtime.async_select_charging_source("external")
        assert runtime._command.mode is OperatingMode.SELF_CONSUMPTION
        await runtime.async_select_charging_source("virtual_battery")
        await _deliver(runtime, aioclient_mock, clock[0])
        second_entry, second = await _setup(hass, aioclient_mock, "second-lifecycle-entry")
        second._live_forecast_now = lambda: clock[0]
        await _deliver(second, aioclient_mock, clock[0])
        assert second._command.mode is OperatingMode.GRID_PRESERVATION
        import asyncio
        aioclient_mock.clear_requests()
        aioclient_mock.get(
            runtime.coordinator._build_request_url(runtime.current_capacity()),
            exc=asyncio.TimeoutError(),
        )
        await runtime._async_refresh_direct_forecast()
        assert runtime._command.mode is OperatingMode.SELF_CONSUMPTION
        assert second._command.mode is OperatingMode.GRID_PRESERVATION
        await _deliver(runtime, aioclient_mock, clock[0])
        snapshot = runtime.coordinator.data
        assert snapshot is not None
        await runtime._async_stage_forecast_snapshot(snapshot)
        assert runtime._command.mode is OperatingMode.GRID_PRESERVATION
        for freshness in (ForecastFreshness.STALE, ForecastFreshness.MISSING):
            await runtime._async_stage_forecast_snapshot(HorizonIQSnapshot(
                forecast_freshness=freshness,
                publication_sequence=runtime._last_applied_forecast_sequence + 1,
            ))
            assert runtime._command.mode is OperatingMode.SELF_CONSUMPTION
        await runtime._async_stage_forecast_snapshot(HorizonIQSnapshot(
            direct_forecast=object(),
            forecast_freshness=ForecastFreshness.FRESH,
            publication_sequence=runtime._last_applied_forecast_sequence + 1,
        ))
        assert runtime.last_command_status is CommandStatus.FALLBACK_INVALID
        assert second._command.mode is OperatingMode.GRID_PRESERVATION
        await hass.services.async_call(
            "switch", "turn_off",
            {"entity_id": _entity_id(hass, entry.entry_id, "simulation", "switch")},
            blocking=True,
        )
        assert runtime.simulator_enabled is False
        assert second.simulator_enabled is True
        await runtime.async_select_operating_mode("manual")
        reloaded = hass.data[DOMAIN][entry.entry_id]
        assert reloaded.operating_mode == "manual"
        assert reloaded._command.mode is OperatingMode.SELF_CONSUMPTION
        assert second._command.mode is OperatingMode.GRID_PRESERVATION
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert await hass.config_entries.async_unload(second_entry.entry_id)


@pytest.mark.asyncio
async def test_hold_status_and_restore_use_existing_wire_and_storage_contracts(hass, aioclient_mock):
    clock = [START]
    with (
        patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()),
        patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", AsyncMock()),
        patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe", AsyncMock(return_value=lambda: None)),
        patch("custom_components.horizoniq.sandbox_runtime._LOOP_INTERVAL_SECONDS", 100000),
    ):
        entry, runtime = await _setup(hass, aioclient_mock, "restore-entry")
        runtime._live_forecast_now = lambda: clock[0]
        await _deliver(runtime, aioclient_mock, clock[0])
        assert runtime._operating_state().value == 2
        assert runtime.active_setpoint_w is None
        assert runtime._build_simulator_status().to_payload()["schemaVersion"] == 2
        assert STORAGE_SCHEMA_VERSION == 14
        assert SNAPSHOT_SCHEMA_VERSION == 5
        await runtime.async_save_snapshot("hold")
        await runtime.async_restore_snapshot("hold")
        assert runtime.energy_wh == 2500
        assert runtime._command is None
        assert await hass.config_entries.async_unload(entry.entry_id)
        aioclient_mock.clear_requests()
        aioclient_mock.get(
            "https://example.com/api/Forecast_Get?code=test-code"
            "&currentBatteryCapacity=5000.0&hash=&registrationData=",
            status=429,
        )
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        restored = hass.data[DOMAIN][entry.entry_id]
        assert restored.energy_wh == 2500
        assert restored._command.mode is OperatingMode.SELF_CONSUMPTION
        assert await hass.config_entries.async_unload(entry.entry_id)
"""Current live Use Grid recommendation and expiry regressions."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from freezegun import freeze_time
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.horizoniq.const import DOMAIN
from custom_components.horizoniq.forecast_schema5 import parse_schema5_forecast
from custom_components.horizoniq.models import ForecastFreshness, HorizonIQSnapshot
from custom_components.horizoniq.sensors.binary import UseGridSensor

NOW = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
FIXTURE = Path(__file__).with_name("fixtures") / "direct_schema5_forecast.json"


class Coordinator(SimpleNamespace):
    def async_add_listener(self, callback, context=None):
        self.listeners.append(callback)
        def remove():
            self.listeners.remove(callback)
        return remove

    def publish(self, snapshot):
        self.data = snapshot
        for callback in tuple(self.listeners):
            callback()


def _forecast(*, hold=True, capability=True, created=NOW, effective=NOW):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["schemaVersion"] = 6
    payload["planKind"] = "live"
    payload["createdAtUtc"] = created.isoformat().replace("+00:00", "Z")
    payload["effectiveAtUtc"] = effective.isoformat().replace("+00:00", "Z")
    payload["shouldImport"] = False
    payload["shouldUseGrid"] = hold
    payload["shouldExport"] = False
    payload["equipmentProfile"]["supportedControl"]["useGrid"] = capability
    period = payload["periods"][0]
    payload["periods"] = [period]
    period["date"] = NOW.isoformat().replace("+00:00", "Z")
    period["shouldImport"] = False
    period["shouldUseGrid"] = hold
    period["shouldExport"] = False
    period["recommendedAction"] = "use_grid" if hold else "self_consumption"
    period["executableAction"] = "none"
    period["simulationAction"] = "none"
    for key in ("commandId", "issuedAtUtc", "expiresAtUtc", "actionPriority"):
        period[key] = None
    start_kwh = 2.5 if hold else 5.0
    end_kwh = start_kwh if hold else start_kwh - 0.2
    import_kwh = 0.2 if hold else 0.0
    cost = import_kwh * period["price"]
    payload["currentCapacity"] = start_kwh
    payload["minCapacity"] = 2.0
    payload["targetCapacity"] = 2.0
    payload["totalCost"] = cost
    payload["chargingCost"] = 0
    payload["saving"] = 0
    payload["equipmentProfile"]["batteryCapacityWh"] = 10_000
    payload["equipmentProfile"]["minimumCapacityPercentage"] = 0.2
    payload["economicsAssumptions"].update({
        "chargeEfficiency": 1, "dischargeEfficiency": 1,
        "degradationCost": 0, "supplierFeeAllowance": 0,
        "uncertaintyHaircut": 0,
    })
    payload["plannedEnergyLedger"].update({
        "gridImportKwh": import_kwh, "solarGenerationKwh": 0,
        "loadKwh": 0.2, "batteryChargeKwh": 0,
        "batteryDischargeKwh": 0 if hold else 0.2,
        "gridExportKwh": 0, "modeledLossesKwh": 0,
        "balanceErrorKwh": 0, "healthy": True,
    })
    period.update({
        "estimatedGeneration": 0, "used": 0.2,
        "expectedImport": import_kwh, "expectedExport": 0,
        "expectedStartSoc": start_kwh, "expectedEndSoc": end_kwh,
        "expectedCost": cost, "expectedRevenue": 0,
        "expectedNetValue": -cost,
        "amount": 0, "imported": import_kwh, "exported": 0,
        "battery": 0 if hold else -0.2,
    })
    trace = period["decisionTrace"]
    trace.update({
        "selectedAction": "use_grid" if hold else "none",
        "reasonCode": "selected" if hold else "none",
        "explanation": "Grid supplies demand." if hold else "Self-consumption applies.",
        "rejectedCandidateActions": [],
        "expectedImportKwh": import_kwh, "expectedExportKwh": 0,
        "expectedStartSocKwh": start_kwh,
        "expectedEndSocKwh": end_kwh,
    })
    trace["constraints"].update({
        "reserveKwh": 2.0,
        "availableHeadroomKwh": 10 - start_kwh,
        "chargePowerLimitKwh": 1.5,
        "dischargePowerLimitKwh": 1.5,
    })
    trace["economicCalculation"].update({
        "importCost": cost, "exportRevenue": 0,
        "supplierFees": 0, "degradationCost": 0,
        "grossValue": -cost, "riskAdjustedNetValue": -cost,
    })
    forecast = parse_schema5_forecast(payload)
    assert forecast is not None
    return forecast


def _snapshot(forecast):
    return HorizonIQSnapshot(
        schema5_forecast=forecast, forecast_freshness=ForecastFreshness.FRESH,
    )


def _entity(snapshot, *, entry="one", clock=None):
    coordinator = Coordinator(data=snapshot, listeners=[], last_update_success=True, environment="live")
    time = clock or [NOW]
    return UseGridSensor(coordinator, entry, "live", now_utc=lambda: time[0]), coordinator, time


def test_use_grid_entity_uses_current_accepted_recommendation():
    entity, _, _ = _entity(_snapshot(_forecast(capability=False)))
    assert entity.is_on is True
    assert entity.extra_state_attributes == {
        "environment": "Live", "plan_kind": "live", "current_action": "use_grid",
    }
    assert _entity(_snapshot(_forecast(hold=False)))[0].is_on is False


def test_use_grid_entity_rejects_stale_missing_and_conflicting_state():
    forecast = _forecast()
    entity, coordinator, time = _entity(_snapshot(forecast))
    assert entity.is_on is True
    coordinator.data = HorizonIQSnapshot()
    assert entity.is_on is None
    coordinator.data = replace(_snapshot(forecast), forecast_freshness=ForecastFreshness.STALE)
    assert entity.is_on is None
    coordinator.data = _snapshot(replace(forecast, stale=True))
    assert entity.is_on is None
    for changed in (
        replace(forecast, plan_kind="sandbox_replay"),
        replace(forecast, plan_kind="import_for_export_advisory"),
        replace(forecast, created_at_utc=(NOW + timedelta(seconds=1)).isoformat()),
        replace(forecast, effective_at_utc=(NOW + timedelta(seconds=1)).isoformat()),
        replace(forecast, should_use_grid=False),
        replace(forecast, periods=(replace(forecast.periods[0], recommended_action="none"),)),
        replace(forecast, periods=(replace(forecast.periods[0], recommended_action="unbounded-payload"),)),
        replace(forecast, periods=(replace(forecast.periods[0], should_import=True),)),
        replace(forecast, periods=(replace(forecast.periods[0], should_export=True),)),
    ):
        coordinator.data = _snapshot(changed)
        assert entity.is_on is None
    coordinator.data = _snapshot(replace(
        forecast, periods=(replace(forecast.periods[0], recommended_action="unbounded-payload"),)
    ))
    assert entity.extra_state_attributes["current_action"] is None
    coordinator.data = _snapshot(replace(
        forecast, periods=(forecast.periods[0], replace(
            forecast.periods[0], date=(NOW + timedelta(minutes=30)).isoformat()
        ))
    ))
    time[0] = NOW + timedelta(minutes=30)
    assert entity.is_on is None
    time[0] = NOW + timedelta(minutes=31)
    assert entity.is_on is None
    coordinator.data = _snapshot(replace(
        forecast, periods=(replace(forecast.periods[0], date="9999-12-31T23:59:59Z"),)
    ))
    time[0] = NOW
    assert entity.is_on is None


@pytest.mark.asyncio
async def test_use_grid_entity_expires_without_a_refresh(hass):
    entity, _, time = _entity(_snapshot(_forecast()))
    entity.hass = hass
    entity.entity_id = "binary_sensor.horizoniq_use_grid"
    entity.async_write_ha_state = MagicMock()
    await entity.async_added_to_hass()
    assert entity.is_on is True
    assert entity._cancel_expiry is not None
    time[0] = NOW + timedelta(minutes=30)
    async_fire_time_changed(hass, time[0])
    await hass.async_block_till_done()
    assert entity.async_write_ha_state.call_count >= 1
    assert entity.is_on is None
    time[0] += timedelta(microseconds=1)
    assert entity.is_on is None
    await entity.async_will_remove_from_hass()


@pytest.mark.asyncio
async def test_use_grid_entity_replacement_and_unload_cancel_old_deadlines(hass):
    entity, coordinator, time = _entity(_snapshot(_forecast()))
    entity.hass = hass
    entity.entity_id = "binary_sensor.horizoniq_use_grid"
    entity.async_write_ha_state = MagicMock()
    await entity.async_added_to_hass()
    old_cancel = entity._cancel_expiry
    time[0] = NOW + timedelta(minutes=29)
    newer = _forecast(created=time[0], effective=time[0])
    coordinator.publish(_snapshot(newer))
    assert entity.is_on is True
    assert entity._cancel_expiry is not old_cancel
    time[0] = NOW + timedelta(minutes=30)
    async_fire_time_changed(hass, time[0])
    await hass.async_block_till_done()
    assert entity.is_on is None  # tariff half-hour ends even if refreshed at 12:29
    count = entity.async_write_ha_state.call_count
    await entity.async_will_remove_from_hass()
    async_fire_time_changed(hass, NOW + timedelta(minutes=31))
    await hass.async_block_till_done()
    assert entity.async_write_ha_state.call_count == count


def test_use_grid_entity_is_entry_local():
    first, first_coordinator, _ = _entity(_snapshot(_forecast()), entry="first")
    second, _, _ = _entity(_snapshot(_forecast(hold=False)), entry="second")
    assert first.unique_id != second.unique_id
    assert first.is_on is True and second.is_on is False
    first_coordinator.data = HorizonIQSnapshot()
    assert first.is_on is None and second.is_on is False

@pytest.mark.asyncio
async def test_use_grid_real_config_entry_expires(hass, aioclient_mock, mock_config_entry):
    """The actual coordinator and platform publish unknown at the deadline."""
    clock = [NOW]
    instances = []
    original_init = UseGridSensor.__init__

    def capture_init(self, coordinator, entry_id, environment):
        original_init(
            self, coordinator, entry_id, environment, now_utc=lambda: clock[0]
        )
        instances.append(self)

    hass.states.async_set("sensor.battery_capacity", "2500")
    aioclient_mock.get(
        "https://example.com/api/Forecast_Get?code=test-code"
        "&currentBatteryCapacity=2500&hash=&registrationData=",
        json=_forecast(capability=False).to_dict(),
    )
    with (
        freeze_time(NOW) as freezer,
        patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()),
        patch.object(UseGridSensor, "__init__", capture_init),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert len(instances) == 1
        assert instances[0].coordinator is hass.data[DOMAIN][mock_config_entry.entry_id].coordinator
        assert hass.states.get("binary_sensor.horizoniq_use_grid").state == "on"
        clock[0] = NOW + timedelta(minutes=30)
        freezer.move_to(clock[0])
        async_fire_time_changed(hass, clock[0])
        await hass.async_block_till_done()
        assert hass.states.get("binary_sensor.horizoniq_use_grid").state == "unknown"
        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        assert instances[0]._cancel_expiry is None

"""Tests for entity behavior."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.util import dt as dt_util

from custom_components.horizoniq.button import ClearRegistrationButton
from custom_components.horizoniq.const import DEFAULT_ENVIRONMENT, SANDBOX_ENVIRONMENT
from custom_components.horizoniq.forecast_schema5 import (
    Schema5Forecast,
    parse_schema5_forecast,
)
from custom_components.horizoniq.models import HorizonIQSnapshot
from custom_components.horizoniq.sensors.binary import ExportSensor, ImportSensor
from custom_components.horizoniq.sensors.bms_state import (
    BatteryManagementSystemStateSensor,
)
from custom_components.horizoniq.sensors.cadence import ForecastCadenceSensor
from custom_components.horizoniq.sensors.diagnostic import ForecastDetailSensor
from custom_components.horizoniq.sensors.monetary import MonetarySensor
from custom_components.horizoniq.sensors.trial import TrialStatusSensor


SCHEMA5_FIXTURE = Path(__file__).with_name("fixtures") / "direct_schema5_forecast.json"
CURRENT_PERIOD = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)


class DummyCoordinator(SimpleNamespace):
    """Minimal coordinator stand-in for entity tests."""

    def async_add_listener(self, update_callback, context=None):
        return lambda: None


def _build_coordinator(**kwargs) -> DummyCoordinator:
    defaults = {
        "data": HorizonIQSnapshot(),
        "forecast_cadence_minutes": None,
        "effective_forecast_cadence_minutes": 5,
        "last_hash": "",
        "last_update_success": True,
        "async_clear_registration_data": AsyncMock(),
    }
    defaults.update(kwargs)
    return DummyCoordinator(**defaults)


def test_monetary_sensor_exposes_value_currency_and_environment() -> None:
    """Monetary entity parses numeric payload values."""
    coordinator = _build_coordinator(
        data=HorizonIQSnapshot(total_cost=12.34, currency="GBP"),
    )

    entity = MonetarySensor(
        coordinator,
        "entry-1",
        SANDBOX_ENVIRONMENT,
        name_suffix="Total Cost",
        unique_suffix="total_cost",
        value_field="total_cost",
    )

    assert entity.native_value == 12.34
    assert entity.native_unit_of_measurement == "GBP"
    assert entity.extra_state_attributes == {
        "environment": SANDBOX_ENVIRONMENT,
        "currency": "GBP",
    }


def test_binary_sensors_reflect_should_import_state() -> None:
    """Import and Export each mirror their respective snapshot decisions."""
    coordinator = _build_coordinator(data=HorizonIQSnapshot(should_import=True))

    import_entity = ImportSensor(coordinator, "entry-1", SANDBOX_ENVIRONMENT)
    export_entity = ExportSensor(coordinator, "entry-1", SANDBOX_ENVIRONMENT)

    assert import_entity.is_on is True
    assert export_entity.is_on is None


def _schema5_forecast(
    *,
    schema_version: int = 5,
    plan_kind: str = "live",
    enabled: bool = True,
    should_import: bool = True,
    should_export: bool = False,
    recommended_action: str = "export_for_profit",
    simulation_action: str = "none",
    executable_action: str = "none",
) -> Schema5Forecast:
    """Build a complete current schema-5 plan with one controlled action."""
    payload = json.loads(SCHEMA5_FIXTURE.read_text(encoding="utf-8"))
    payload["schemaVersion"] = schema_version
    payload["planKind"] = plan_kind
    payload["importForExportEnabled"] = enabled
    payload["shouldImport"] = should_import
    periods = payload["periods"]
    assert isinstance(periods, list)
    if schema_version == 6:
        payload["shouldExport"] = should_export
        for period in periods:
            assert isinstance(period, dict)
            period["shouldExport"] = should_export
    current = periods[0]
    assert isinstance(current, dict)
    current["date"] = CURRENT_PERIOD.isoformat().replace("+00:00", "Z")
    current["shouldImport"] = should_import
    current["recommendedAction"] = recommended_action
    current["simulationAction"] = simulation_action
    current["executableAction"] = executable_action
    forecast = parse_schema5_forecast(payload)
    assert forecast is not None
    return forecast


def _export_entity(
    forecast: Schema5Forecast,
    *,
    entry_id: str = "entry-1",
    now: datetime = CURRENT_PERIOD,
    runtime: object | None = None,
) -> ExportSensor:
    """Create one Export entity with an explicit coordinator-owned plan."""
    coordinator = _build_coordinator(
        data=HorizonIQSnapshot(should_export=forecast.should_export),
        last_forecast=forecast,
    )
    return ExportSensor(
        coordinator,
        entry_id,
        SANDBOX_ENVIRONMENT,
        runtime=runtime,
        now_utc=lambda: now,
    )


def _live_export_entity(
    *, should_export: bool | None, should_import: bool = False
) -> ExportSensor:
    """Create a Live Export entity with no optional typed diagnostics plan."""
    coordinator = _build_coordinator(
        data=HorizonIQSnapshot(
            should_import=should_import,
            should_export=should_export,
        )
    )
    return ExportSensor(coordinator, "entry-live", DEFAULT_ENVIRONMENT)


def test_live_export_mirrors_snapshot_without_typed_diagnostics() -> None:
    """A known Live backend value is never hidden by missing diagnostics."""
    disabled = _live_export_entity(should_export=False)
    enabled = _live_export_entity(should_export=True)
    unknown = _live_export_entity(should_export=None)

    assert disabled.is_on is False
    assert enabled.is_on is True
    assert unknown.is_on is None
    assert enabled.extra_state_attributes == {
        "environment": "Live",
        "plan_kind": None,
        "current_action": None,
        "expected_export_kwh": None,
        "executable": False,
    }


def test_should_import_false_does_not_imply_export() -> None:
    """Export follows only its backend-owned snapshot value."""
    entity = _live_export_entity(should_export=False, should_import=False)

    assert entity.is_on is False


def test_export_mirrors_backend_should_export_without_action_inference() -> None:
    """Only schema-6 shouldExport controls Export's state."""
    enabled = _export_entity(
        _schema5_forecast(
            schema_version=6,
            should_import=False,
            should_export=True,
            recommended_action="none",
        )
    )
    action_only = _export_entity(
        _schema5_forecast(
            schema_version=6,
            should_import=False,
            should_export=False,
            recommended_action="export_for_profit",
        )
    )
    legacy = _export_entity(
        _schema5_forecast(recommended_action="export_for_profit")
    )

    assert enabled.is_on is True
    assert action_only.is_on is False
    assert legacy.is_on is None


def test_export_reads_backend_boolean_and_has_bounded_attributes() -> None:
    """Live and Replay expose the returned boolean without issuing a command."""
    live = _export_entity(
        _schema5_forecast(
            schema_version=6,
            should_import=False,
            should_export=True,
            executable_action="none",
        )
    )
    assert live.is_on is True
    assert live.extra_state_attributes == {
        "environment": SANDBOX_ENVIRONMENT,
        "plan_kind": "live",
        "current_action": "export_for_profit",
        "expected_export_kwh": 0.0,
        "executable": False,
    }

    replay_runtime = SimpleNamespace(
        operating_mode="replay",
        virtual_time_utc=CURRENT_PERIOD,
        add_listener=lambda listener: lambda: None,
    )
    replay = _export_entity(
        _schema5_forecast(
            schema_version=6,
            plan_kind="sandbox_replay",
            should_import=False,
            should_export=True,
            recommended_action="none",
            simulation_action="none",
        ),
        runtime=replay_runtime,
    )
    assert replay.is_on is True
    assert replay.extra_state_attributes["current_action"] == "none"

    virtual_runtime = SimpleNamespace(
        operating_mode="virtual",
        virtual_time_utc=CURRENT_PERIOD,
        add_listener=lambda listener: lambda: None,
    )
    virtual = _export_entity(
        _schema5_forecast(
            schema_version=6,
            should_import=False,
            should_export=False,
            recommended_action="none",
            simulation_action="export_for_profit",
        ),
        runtime=virtual_runtime,
    )
    assert virtual.is_on is False
    assert virtual.extra_state_attributes["current_action"] == "none"

    advisory = _export_entity(
        _schema5_forecast(
            schema_version=6,
            plan_kind="import_for_export_advisory",
            should_import=False,
            should_export=False,
            recommended_action="export_for_profit",
        )
    )
    assert advisory.is_on is False


def test_export_snapshot_boolean_is_not_overridden_by_optional_diagnostics() -> None:
    """Stale, invalid, and out-of-window diagnostics cannot hide a known value."""
    forecast = _schema5_forecast(schema_version=6, should_import=False)
    assert (
        _export_entity(forecast, now=CURRENT_PERIOD + timedelta(minutes=60)).is_on
        is False
    )
    assert _export_entity(replace(forecast, stale=True)).is_on is False
    assert _export_entity(replace(forecast, plan_kind="unsupported")).is_on is False


def test_export_entities_are_entry_local() -> None:
    """Independent coordinator plans and entry clocks cannot cross-contaminate."""
    earlier = _export_entity(
        _schema5_forecast(
            schema_version=6,
            should_import=False,
            should_export=False,
            recommended_action="none",
        ),
        entry_id="entry-earlier",
        now=CURRENT_PERIOD,
    )
    profitable = _export_entity(
        _schema5_forecast(
            schema_version=6,
            should_import=False,
            should_export=True,
        ),
        entry_id="entry-profitable",
        now=CURRENT_PERIOD,
    )
    later = _export_entity(
        _schema5_forecast(
            schema_version=6,
            should_import=False,
            should_export=True,
        ),
        entry_id="entry-later",
        now=CURRENT_PERIOD + timedelta(minutes=60),
    )

    assert (earlier.is_on, profitable.is_on, later.is_on) == (False, True, True)
    assert {earlier.unique_id, profitable.unique_id, later.unique_id} == {
        "horizoniq_entry-earlier_sandbox_export",
        "horizoniq_entry-profitable_sandbox_export",
        "horizoniq_entry-later_sandbox_export",
    }


def test_forecast_cadence_sensor_exposes_minutes_and_environment() -> None:
    """Cadence entity exposes the backend polling interval."""
    coordinator = _build_coordinator(
        data=HorizonIQSnapshot(forecast_cadence_minutes=5),
        forecast_cadence_minutes=5,
    )

    entity = ForecastCadenceSensor(coordinator, "entry-1", SANDBOX_ENVIRONMENT)

    assert entity.native_value == 5
    assert entity.native_unit_of_measurement == "min"
    assert entity.extra_state_attributes == {
        "environment": SANDBOX_ENVIRONMENT,
        "effective_poll_interval_minutes": 5,
    }


def test_forecast_cadence_sensor_falls_back_to_effective_interval() -> None:
    """Cadence entity falls back to the effective polling interval."""
    coordinator = _build_coordinator(
        data=HorizonIQSnapshot(),
        forecast_cadence_minutes=None,
        effective_forecast_cadence_minutes=5,
    )

    entity = ForecastCadenceSensor(coordinator, "entry-1", SANDBOX_ENVIRONMENT)

    assert entity.native_value == 5
    assert entity.extra_state_attributes == {
        "environment": SANDBOX_ENVIRONMENT,
        "effective_poll_interval_minutes": 5,
    }


def test_forecast_detail_sensor_exposes_only_a_bounded_summary() -> None:
    """Diagnostic entity does not retain complete forecast payloads."""
    coordinator = _build_coordinator(
        data=HorizonIQSnapshot(
            forecast={
                "date": "2026-03-07T10:00:00+00:00",
                "target_capacity": 55.0,
                "periods": [
                    {"period": 1, "date": "2026-03-07T10:00:00+00:00"},
                    {"period": 2, "date": "2026-03-07T10:30:00+00:00"},
                ],
            },
            forecast_periods=[
                {
                    "period": 1,
                    "date": "2026-03-07T10:00:00+00:00",
                    "history": [{"ignored": True}],
                },
                {"period": 2, "date": "2026-03-07T10:30:00+00:00"},
            ],
            registration={
                "id": "registration-7",
                "ForecastCadenceMinutes": 5,
                "DynamicCharging": True,
                "Solar": {"CapacityKw": 4.2},
            },
            currency="GBP",
            target_capacity=55.0,
            forecast_cadence_minutes=5,
        ),
        last_hash="hash-1",
    )

    entity = ForecastDetailSensor(coordinator, "entry-1", SANDBOX_ENVIRONMENT)
    attrs = entity.extra_state_attributes

    assert entity.native_value == 2
    assert attrs["environment"] == SANDBOX_ENVIRONMENT
    assert attrs["period_count"] == 2
    assert attrs == {
        "environment": SANDBOX_ENVIRONMENT,
        "health": "Healthy",
        "period_count": 2,
    }


def test_sandbox_forecast_diagnostics_stays_available_without_coordinator_data() -> None:
    """Sandbox diagnostics remains available from the loaded runtime default."""
    coordinator = _build_coordinator(data=None, environment=SANDBOX_ENVIRONMENT)
    entity = ForecastDetailSensor(coordinator, "entry-1", SANDBOX_ENVIRONMENT)

    assert entity.available is True
    assert entity.native_value == 0


def test_forecast_detail_sensor_never_exposes_forecast_payload_values() -> None:
    """Diagnostic attributes do not expose trial bindings or payloads."""
    token = "portal-trial-token"
    device_id = "gx-device-1"
    function_key = "forecast-function-key"
    registration_data = "encrypted-registration-data"
    coordinator = _build_coordinator(
        data=HorizonIQSnapshot(
            forecast={
                "forecast_device_token": token,
                "forecast_function_key": function_key,
                "registration_data": registration_data,
                "endpoint": (
                    "https://api.horizoniq.uk/api/Forecast_Get"
                    "?code=forecast-function-key&currentBatteryCapacity=50"
                ),
                "nested": {"trialDeviceToken": token},
                "periods": [
                    {
                        "period": 1,
                        "deviceId": device_id,
                        "trialDeviceToken": token,
                        "registrationData": registration_data,
                    }
                ],
            },
            forecast_periods=[
                {
                    "period": 1,
                    "deviceId": device_id,
                    "trialDeviceToken": token,
                    "registrationData": registration_data,
                }
            ],
            registration={
                "id": "registration-7",
                "deviceId": device_id,
                "trialDeviceToken": token,
            },
        )
    )

    entity = ForecastDetailSensor(coordinator, "entry-1", SANDBOX_ENVIRONMENT)
    attrs = entity.extra_state_attributes

    assert token not in repr(attrs)
    assert device_id not in repr(attrs)
    assert function_key not in repr(attrs)
    assert registration_data not in repr(attrs)
    assert attrs == {
        "environment": SANDBOX_ENVIRONMENT,
        "health": "Healthy",
        "period_count": 1,
    }


def test_forecast_detail_sensor_does_not_copy_trial_state() -> None:
    """Forecast diagnostics keeps trial payloads out of state attributes."""
    coordinator = _build_coordinator(
        data=HorizonIQSnapshot(
            trial={
                "has_trial": True,
                "is_active": False,
                "is_eligible": False,
                "status": "expired",
                "forecast_cadence_minutes": 30,
            },
        )
    )

    entity = ForecastDetailSensor(coordinator, "entry-1", SANDBOX_ENVIRONMENT)
    attrs = entity.extra_state_attributes

    assert entity.native_value == 0
    assert attrs == {
        "environment": SANDBOX_ENVIRONMENT,
        "health": "Healthy",
        "period_count": 0,
    }


def test_forecast_detail_sensor_keeps_authorization_payload_out_of_state() -> None:
    """Forecast diagnostics reports only bounded authorization failure context."""
    coordinator = _build_coordinator(
        data=HorizonIQSnapshot(
            trial={
                "authorization_status": "unauthorized",
                "authorization_status_code": 401,
                "authorization_message": (
                    "Forecast request was rejected with HTTP 401 Unauthorized."
                ),
            },
        )
    )

    entity = ForecastDetailSensor(coordinator, "entry-1", SANDBOX_ENVIRONMENT)
    attrs = entity.extra_state_attributes

    assert entity.native_value == 0
    assert attrs["health"] == "Unauthorized"
    assert attrs["period_count"] == 0
    assert attrs["reason"] == "Forecast request was rejected with HTTP 401 Unauthorized."
    assert "trial" not in attrs


def test_forecast_detail_sensor_is_bounded_at_maximum_horizon() -> None:
    """A maximum forecast horizon cannot create oversized state attributes."""
    coordinator = _build_coordinator(
        data=HorizonIQSnapshot(
            forecast={
                "created_at_utc": "2026-03-07T10:00:00+00:00",
                "effective_at_utc": "2026-03-07T10:00:00+00:00",
            },
            forecast_periods=[
                {
                    "executable_action": "self_consumption",
                    "decision_trace": {"response": "x" * 10_000},
                }
                for _ in range(1_488)
            ],
        )
    )

    entity = ForecastDetailSensor(coordinator, "entry-1", SANDBOX_ENVIRONMENT)
    attrs = entity.extra_state_attributes

    assert attrs["period_count"] == 1_488
    assert attrs["selected_action"] == "Self Consumption"
    assert len(json.dumps(attrs)) < 8_192
    assert entity._unrecorded_attributes == frozenset({"forecast"})


def test_trial_status_sensor_exposes_trial_state() -> None:
    """Trial status entity exposes active/eligible flags and dates."""
    coordinator = _build_coordinator(
        data=HorizonIQSnapshot(
            trial={
                "has_trial": True,
                "is_active": False,
                "is_eligible": False,
                "status": "expired",
                "starts_on_utc": "2026-05-01T00:00:00Z",
                "expires_on_utc": "2026-05-15T00:00:00Z",
                "forecast_cadence_minutes": 30,
                "device_display_name": "GX device",
            }
        )
    )

    entity = TrialStatusSensor(coordinator, "entry-1", SANDBOX_ENVIRONMENT)

    assert entity.native_value == "expired"
    assert entity.available is True
    assert entity.extra_state_attributes == {
        "environment": SANDBOX_ENVIRONMENT,
        "has_trial": True,
        "is_active": False,
        "is_eligible": False,
        "status": "expired",
        "starts_on_utc": "2026-05-01T00:00:00Z",
        "expires_on_utc": "2026-05-15T00:00:00Z",
        "forecast_cadence_minutes": 30,
        "device_display_name": "GX device",
    }


def test_trial_status_sensor_falls_back_to_eligibility_state() -> None:
    """Trial status entity remains useful when upstream status is absent."""
    coordinator = _build_coordinator(
        data=HorizonIQSnapshot(
            forecast={
                "trial_has_trial": False,
                "trial_is_active": False,
                "trial_is_eligible": True,
            }
        )
    )

    entity = TrialStatusSensor(coordinator, "entry-1", SANDBOX_ENVIRONMENT)

    assert entity.native_value == "eligible"
    assert entity.extra_state_attributes == {
        "environment": SANDBOX_ENVIRONMENT,
        "has_trial": False,
        "is_active": False,
        "is_eligible": True,
    }


def test_trial_status_sensor_stays_available_with_cached_trial_state() -> None:
    """Trial status remains clickable when later coordinator refreshes fail."""
    coordinator = _build_coordinator(
        data=HorizonIQSnapshot(trial={"status": "expired"}),
        last_update_success=False,
    )

    entity = TrialStatusSensor(coordinator, "entry-1", SANDBOX_ENVIRONMENT)

    assert entity.available is True
    assert entity.native_value == "expired"


def test_trial_status_sensor_exposes_authorization_state() -> None:
    """Trial status falls back to authorization state when no trial status exists."""
    coordinator = _build_coordinator(
        data=HorizonIQSnapshot(
            trial={
                "authorization_status": "unauthorized",
                "authorization_status_code": 401,
                "authorization_message": (
                    "Forecast request was rejected with HTTP 401 Unauthorized."
                ),
            }
        )
    )

    entity = TrialStatusSensor(coordinator, "entry-1", SANDBOX_ENVIRONMENT)

    assert entity.available is True
    assert entity.native_value == "unauthorized"
    assert entity.extra_state_attributes == {
        "environment": SANDBOX_ENVIRONMENT,
        "authorization_status": "unauthorized",
        "authorization_status_code": 401,
        "authorization_message": (
            "Forecast request was rejected with HTTP 401 Unauthorized."
        ),
    }


def test_bms_sensor_uses_current_period_when_forecast_state_missing(monkeypatch) -> None:
    """BMS state falls back to the active period."""
    now = dt_util.parse_datetime("2026-03-07T10:15:00+00:00")
    assert now is not None
    monkeypatch.setattr(
        "custom_components.horizoniq.sensors.bms_state.dt_util.utcnow",
        lambda: now,
    )

    coordinator = _build_coordinator(
        data=HorizonIQSnapshot(
            forecast={
                "periods": [
                    {
                        "period": 1,
                        "date": "2026-03-07T10:00:00+00:00",
                        "battery_management_system_state": "charging",
                        "battery": 61.5,
                    },
                    {
                        "period": 2,
                        "date": "2026-03-07T10:30:00+00:00",
                        "battery_management_system_state": "hold",
                    },
                ]
            },
            forecast_periods=[
                {
                    "period": 1,
                    "date": "2026-03-07T10:00:00+00:00",
                    "battery_management_system_state": "charging",
                    "battery": 61.5,
                },
                {
                    "period": 2,
                    "date": "2026-03-07T10:30:00+00:00",
                    "battery_management_system_state": "hold",
                },
            ],
        )
    )

    entity = BatteryManagementSystemStateSensor(
        coordinator,
        "entry-1",
        SANDBOX_ENVIRONMENT,
    )
    attrs = entity.extra_state_attributes

    assert entity.native_value == "charging"
    assert attrs["environment"] == SANDBOX_ENVIRONMENT
    assert attrs["battery"] == 61.5
    assert attrs["period_start"] == "2026-03-07T10:00:00+00:00"
    assert attrs["period_end"] == (
        now.replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(minutes=30)
    ).isoformat()


async def test_clear_registration_button_calls_coordinator_refresh() -> None:
    """Clear button delegates to the coordinator method."""
    coordinator = _build_coordinator()
    entity = ClearRegistrationButton(coordinator, "entry-1", SANDBOX_ENVIRONMENT)

    await entity.async_press()

    coordinator.async_clear_registration_data.assert_awaited_once()
    assert entity.available is True


def test_default_environment_unique_ids_include_entry_id() -> None:
    """Default-environment entities remain unique per config entry."""
    coordinator = _build_coordinator()

    sensor = MonetarySensor(
        coordinator,
        "entry-1",
        DEFAULT_ENVIRONMENT,
        name_suffix="Total Cost",
        unique_suffix="total_cost",
        value_field="total_cost",
    )
    cadence = ForecastCadenceSensor(coordinator, "entry-1", DEFAULT_ENVIRONMENT)
    button = ClearRegistrationButton(coordinator, "entry-1", DEFAULT_ENVIRONMENT)
    export = ExportSensor(coordinator, "entry-1", DEFAULT_ENVIRONMENT)

    assert sensor.unique_id == "horizoniq_entry-1_total_cost"
    assert cadence.unique_id == "horizoniq_entry-1_forecast_cadence"
    assert button.unique_id == "horizoniq_entry-1_clear_registration"
    assert export.unique_id == "horizoniq_entry-1_export"

    trial = TrialStatusSensor(coordinator, "entry-1", DEFAULT_ENVIRONMENT)
    assert trial.unique_id == "horizoniq_entry-1_trial_status"


def test_default_environment_names_remain_unchanged() -> None:
    """Live/default entity names remain unchanged."""
    coordinator = _build_coordinator()

    sensor = MonetarySensor(
        coordinator,
        "entry-1",
        DEFAULT_ENVIRONMENT,
        name_suffix="Total Cost",
        unique_suffix="total_cost",
        value_field="total_cost",
    )
    cadence = ForecastCadenceSensor(coordinator, "entry-1", DEFAULT_ENVIRONMENT)
    button = ClearRegistrationButton(coordinator, "entry-1", DEFAULT_ENVIRONMENT)
    export = ExportSensor(coordinator, "entry-1", DEFAULT_ENVIRONMENT)

    assert sensor.name == "HorizonIQ Total Cost"
    assert cadence.name == "HorizonIQ Forecast Cadence"
    assert button.name == "HorizonIQ Clear Registration"
    assert export.name == "HorizonIQ Export"


def test_sandbox_environment_names_are_prefixed() -> None:
    """Sandbox entity names are distinct from Live names."""
    coordinator = _build_coordinator()

    sensor = MonetarySensor(
        coordinator,
        "entry-1",
        SANDBOX_ENVIRONMENT,
        name_suffix="Total Cost",
        unique_suffix="total_cost",
        value_field="total_cost",
    )
    import_sensor = ImportSensor(coordinator, "entry-1", SANDBOX_ENVIRONMENT)
    export_sensor = ExportSensor(coordinator, "entry-1", SANDBOX_ENVIRONMENT)
    cadence = ForecastCadenceSensor(coordinator, "entry-1", SANDBOX_ENVIRONMENT)
    button = ClearRegistrationButton(coordinator, "entry-1", SANDBOX_ENVIRONMENT)

    assert sensor.name == "HorizonIQ Sandbox Total Cost"
    assert import_sensor.name == "HorizonIQ Sandbox Import"
    assert export_sensor.name == "HorizonIQ Sandbox Export"
    assert cadence.name == "HorizonIQ Sandbox Forecast Cadence"
    assert button.name == "HorizonIQ Sandbox Clear Registration"

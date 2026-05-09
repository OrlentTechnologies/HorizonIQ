"""Tests for entity behavior."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.util import dt as dt_util

from custom_components.mesh_solar.button import ClearRegistrationButton
from custom_components.mesh_solar.const import DEFAULT_ENVIRONMENT, SANDBOX_ENVIRONMENT
from custom_components.mesh_solar.models import MeshSolarSnapshot
from custom_components.mesh_solar.sensors.binary import ExportSensor, ImportSensor
from custom_components.mesh_solar.sensors.bms_state import (
    BatteryManagementSystemStateSensor,
)
from custom_components.mesh_solar.sensors.cadence import ForecastCadenceSensor
from custom_components.mesh_solar.sensors.diagnostic import ForecastDetailSensor
from custom_components.mesh_solar.sensors.monetary import MonetarySensor


class DummyCoordinator(SimpleNamespace):
    """Minimal coordinator stand-in for entity tests."""

    def async_add_listener(self, update_callback, context=None):
        return lambda: None


def _build_coordinator(**kwargs) -> DummyCoordinator:
    defaults = {
        "data": MeshSolarSnapshot(),
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
        data=MeshSolarSnapshot(total_cost=12.34, currency="GBP"),
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
    """Import/export entities mirror the upstream shouldImport flag."""
    coordinator = _build_coordinator(data=MeshSolarSnapshot(should_import=True))

    import_entity = ImportSensor(coordinator, "entry-1", SANDBOX_ENVIRONMENT)
    export_entity = ExportSensor(coordinator, "entry-1", SANDBOX_ENVIRONMENT)

    assert import_entity.is_on is True
    assert export_entity.is_on is False


def test_forecast_cadence_sensor_exposes_minutes_and_environment() -> None:
    """Cadence entity exposes the backend polling interval."""
    coordinator = _build_coordinator(
        data=MeshSolarSnapshot(forecast_cadence_minutes=5),
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
        data=MeshSolarSnapshot(),
        forecast_cadence_minutes=None,
        effective_forecast_cadence_minutes=5,
    )

    entity = ForecastCadenceSensor(coordinator, "entry-1", SANDBOX_ENVIRONMENT)

    assert entity.native_value == 5
    assert entity.extra_state_attributes == {
        "environment": SANDBOX_ENVIRONMENT,
        "effective_poll_interval_minutes": 5,
    }


def test_forecast_detail_sensor_uses_forecast_payload() -> None:
    """Diagnostic entity exposes forecast summary attributes."""
    coordinator = _build_coordinator(
        data=MeshSolarSnapshot(
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
    assert attrs["forecast"] == {
        "date": "2026-03-07T10:00:00+00:00",
        "target_capacity": 55.0,
        "periods": [
            {"period": 1, "date": "2026-03-07T10:00:00+00:00"},
            {"period": 2, "date": "2026-03-07T10:30:00+00:00"},
        ],
    }
    assert attrs["registration"] == {
        "id": "registration-7",
        "ForecastCadenceMinutes": 5,
        "DynamicCharging": True,
        "Solar": {"CapacityKw": 4.2},
    }
    assert set(attrs) == {"environment", "period_count", "forecast", "registration"}


def test_bms_sensor_uses_current_period_when_forecast_state_missing(monkeypatch) -> None:
    """BMS state falls back to the active period."""
    now = dt_util.parse_datetime("2026-03-07T10:15:00+00:00")
    assert now is not None
    monkeypatch.setattr(
        "custom_components.mesh_solar.sensors.bms_state.dt_util.utcnow",
        lambda: now,
    )

    coordinator = _build_coordinator(
        data=MeshSolarSnapshot(
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

    assert sensor.unique_id == "mesh_solar_entry-1_total_cost"
    assert cadence.unique_id == "mesh_solar_entry-1_forecast_cadence"
    assert button.unique_id == "mesh_solar_entry-1_clear_registration"

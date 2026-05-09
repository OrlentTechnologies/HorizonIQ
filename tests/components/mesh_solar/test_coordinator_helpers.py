"""Tests for payload normalization helpers."""

from custom_components.mesh_solar.coordinator_helpers import (
    build_snapshot,
    extract_forecast_cadence_minutes_from_registration_data,
    extract_first,
    normalize_forecast,
    normalize_registration,
    normalize_periods,
)
from custom_components.mesh_solar.models import MeshSolarSnapshot


def test_extract_first_handles_none_and_missing() -> None:
    """Helper returns an empty string for explicit null values."""
    assert extract_first({"Hash": None}, ("Hash", "hash")) == ""
    assert extract_first({}, ("Hash", "hash")) is None


def test_normalize_periods_handles_nested_forecast_payload() -> None:
    """Periods are normalized from mixed-case upstream payloads."""
    payload = {
        "Forecast": {
            "Periods": [
                {
                    "Id": 42,
                    "Period": "3",
                    "Date": "2026-03-07T10:00:00+00:00",
                    "Price": "12.50",
                    "ShouldImport": "true",
                    "Amount": "0.4",
                    "Imported": "0.2",
                    "Exported": "0.1",
                    "EstimatedGeneration": "1.3",
                    "Used": "0.9",
                    "Battery": "67.5",
                    "BmsHoldPeriod": "false",
                    "BatteryManagementSystemState": "charging",
                    "History": [{"ignored": True}],
                },
                "ignore-me",
            ]
        }
    }

    assert normalize_periods(payload) == [
        {
            "id": "42",
            "period": 3,
            "date": "2026-03-07T10:00:00+00:00",
            "price": 12.5,
            "should_import": True,
            "amount": 0.4,
            "imported": 0.2,
            "exported": 0.1,
            "estimated_generation": 1.3,
            "used": 0.9,
            "battery": 67.5,
            "bms_hold_period": False,
            "battery_management_system_state": "charging",
        }
    ]


def test_normalize_forecast_extracts_primary_fields() -> None:
    """Forecast normalization keeps the stable keys used by entities."""
    payload = {
        "forecastEntity": {
            "Id": "forecast-1",
            "RegistrationId": "registration-7",
            "Date": "2026-03-07T10:00:00+00:00",
            "CalculatedOnUtc": "2026-03-07T09:55:00+00:00",
            "Hash": "hash-123",
            "CurrentCapacity": "18.5",
            "MinCapacity": "10",
            "TargetCapacity": "55.5",
            "LowPrice": "0.05",
            "MediumPrice": "0.10",
            "BatteryManagementSystemState": "hold",
            "ShouldImport": False,
            "CloudUpdateEnabled": "true",
            "ForecastCadenceMinutes": "5",
            "RegistrationData": "reg-data",
            "TotalCost": "1.23",
            "ChargingCost": "0.45",
            "Saving": "0.78",
            "Periods": [{"Period": 1, "Date": "2026-03-07T10:00:00+00:00"}],
        }
    }

    assert normalize_forecast(payload) == {
        "id": "forecast-1",
        "registration_id": "registration-7",
        "date": "2026-03-07T10:00:00+00:00",
        "calculated_on_utc": "2026-03-07T09:55:00+00:00",
        "hash": "hash-123",
        "periods": [{"period": 1, "date": "2026-03-07T10:00:00+00:00"}],
        "current_capacity": 18.5,
        "min_capacity": 10.0,
        "target_capacity": 55.5,
        "low_price": 0.05,
        "medium_price": 0.1,
        "battery_management_system_state": "hold",
        "should_import": False,
        "cloud_update_enabled": True,
        "forecast_cadence_minutes": 5,
        "registration_data": "reg-data",
        "total_cost": 1.23,
        "charging_cost": 0.45,
        "saving": 0.78,
    }


def test_normalize_registration_extracts_json_payload_from_registration_data() -> None:
    """Registration JSON is parsed for diagnostics."""
    payload = {
        "RegistrationData": (
            '{"id":"registration-7","DynamicCharging":true,'
            '"ForecastCadenceMinutes":5,"Solar":{"CapacityKw":4.2}}'
        )
    }

    assert normalize_registration(payload) == {
        "id": "registration-7",
        "DynamicCharging": True,
        "ForecastCadenceMinutes": 5,
        "Solar": {"CapacityKw": 4.2},
    }


def test_normalize_registration_accepts_top_level_registration_payload() -> None:
    """Raw registration payloads are exposed in diagnostics."""
    payload = {
        "id": "registration-7",
        "DynamicCharging": True,
        "ForecastCadenceMinutes": 1,
        "Solar": {"InstallationSizeKw": 3.1},
    }

    assert normalize_registration(payload) == {
        "id": "registration-7",
        "DynamicCharging": True,
        "ForecastCadenceMinutes": 1,
        "Solar": {"InstallationSizeKw": 3.1},
    }


def test_extract_forecast_cadence_minutes_from_registration_data() -> None:
    """Cached registration data controls coordinator cadence."""
    registration_data = (
        '{"id":"registration-7","ForecastCadenceMinutes":5,"DynamicCharging":true}'
    )

    assert extract_forecast_cadence_minutes_from_registration_data(
        registration_data
    ) == 5


def test_build_snapshot_accepts_top_level_registration_payload() -> None:
    """Top-level registration payloads still populate cadence and cacheable data."""
    payload = {
        "id": "registration-7",
        "DynamicCharging": True,
        "ForecastCadenceMinutes": 1,
        "Solar": {"InstallationSizeKw": 3.1},
    }

    assert build_snapshot(payload) == MeshSolarSnapshot(
        forecast={
            "id": "registration-7",
            "forecast_cadence_minutes": 1,
            "registration_data": (
                '{"id":"registration-7","DynamicCharging":true,'
                '"ForecastCadenceMinutes":1,"Solar":{"InstallationSizeKw":3.1}}'
            ),
        },
        registration={
            "id": "registration-7",
            "DynamicCharging": True,
            "ForecastCadenceMinutes": 1,
            "Solar": {"InstallationSizeKw": 3.1},
        },
        registration_data=(
            '{"id":"registration-7","DynamicCharging":true,'
            '"ForecastCadenceMinutes":1,"Solar":{"InstallationSizeKw":3.1}}'
        ),
        forecast_cadence_minutes=1,
    )


def test_build_snapshot_keeps_forecast_payload_out_of_registration() -> None:
    """Forecast payloads with clear-text cadence do not get duplicated as registration data."""
    payload = {
        "id": "forecast-7",
        "registrationId": "registration-7",
        "date": "2026-04-03T09:08:38.2671273Z",
        "hash": "hash-7",
        "periods": [
            {
                "id": "period-1",
                "period": 18,
                "date": "2026-04-03T09:00:00Z",
                "price": 0.1386,
                "shouldImport": False,
                "amount": 0,
                "battery": 8464,
                "batteryManagementSystemState": 0,
            }
        ],
        "currentCapacity": 9216,
        "minCapacity": 5760,
        "targetCapacity": 5760,
        "batteryManagementSystemState": 0,
        "shouldImport": False,
        "cloudUpdateEnabled": False,
        "forecastCadenceMinutes": 1,
        "registrationData": "encrypted-registration-data",
        "totalCost": 1.340718750000001,
        "chargingCost": 0.40609296,
        "saving": 0.9346257900000011,
    }

    assert build_snapshot(payload) == MeshSolarSnapshot(
        forecast={
            "id": "forecast-7",
            "registration_id": "registration-7",
            "date": "2026-04-03T09:08:38.2671273Z",
            "hash": "hash-7",
            "periods": [
                {
                    "id": "period-1",
                    "period": 18,
                    "date": "2026-04-03T09:00:00Z",
                    "price": 0.1386,
                    "should_import": False,
                    "amount": 0.0,
                    "battery": 8464.0,
                    "battery_management_system_state": "0",
                }
            ],
            "current_capacity": 9216.0,
            "min_capacity": 5760.0,
            "target_capacity": 5760.0,
            "battery_management_system_state": "0",
            "should_import": False,
            "cloud_update_enabled": False,
            "forecast_cadence_minutes": 1,
            "registration_data": "encrypted-registration-data",
            "total_cost": 1.340718750000001,
            "charging_cost": 0.40609296,
            "saving": 0.9346257900000011,
        },
        forecast_periods=[
            {
                "id": "period-1",
                "period": 18,
                "date": "2026-04-03T09:00:00Z",
                "price": 0.1386,
                "should_import": False,
                "amount": 0.0,
                "battery": 8464.0,
                "battery_management_system_state": "0",
            }
        ],
        target_capacity=5760.0,
        should_import=False,
        total_cost=1.340718750000001,
        charging_cost=0.40609296,
        saving=0.9346257900000011,
        forecast_hash="hash-7",
        registration_data="encrypted-registration-data",
        forecast_cadence_minutes=1,
    )


def test_build_snapshot_prefers_normalized_shape() -> None:
    """Coordinator snapshots expose a single normalized data model."""
    payload = {
        "Currency": "GBP",
        "TargetCapacity": "55.5",
        "RegistrationData": (
            '{"id":"registration-7","DynamicCharging":true,'
            '"ForecastCadenceMinutes":5,"Solar":{"CapacityKw":4.2}}'
        ),
        "Forecast": {
            "Hash": "hash-123",
            "ShouldImport": False,
            "TotalCost": "1.23",
            "ChargingCost": "0.45",
            "Saving": "0.78",
            "Periods": [{"Period": 1, "Date": "2026-03-07T10:00:00+00:00"}],
        },
    }

    assert build_snapshot(payload) == MeshSolarSnapshot(
        forecast={
            "hash": "hash-123",
            "periods": [{"period": 1, "date": "2026-03-07T10:00:00+00:00"}],
            "target_capacity": 55.5,
            "should_import": False,
            "currency": "GBP",
            "registration_data": (
                '{"id":"registration-7","DynamicCharging":true,'
                '"ForecastCadenceMinutes":5,"Solar":{"CapacityKw":4.2}}'
            ),
            "total_cost": 1.23,
            "charging_cost": 0.45,
            "saving": 0.78,
        },
        forecast_periods=[{"period": 1, "date": "2026-03-07T10:00:00+00:00"}],
        registration={
            "id": "registration-7",
            "DynamicCharging": True,
            "ForecastCadenceMinutes": 5,
            "Solar": {"CapacityKw": 4.2},
        },
        currency="GBP",
        target_capacity=55.5,
        should_import=False,
        total_cost=1.23,
        charging_cost=0.45,
        saving=0.78,
        forecast_hash="hash-123",
        registration_data=(
            '{"id":"registration-7","DynamicCharging":true,'
            '"ForecastCadenceMinutes":5,"Solar":{"CapacityKw":4.2}}'
        ),
        forecast_cadence_minutes=5,
    )

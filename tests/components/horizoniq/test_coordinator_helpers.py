"""Tests for payload normalization helpers."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from custom_components.horizoniq.coordinator_helpers import (
    build_snapshot,
    extract_forecast_cadence_minutes_from_registration_data,
    extract_first,
    normalize_forecast,
    normalize_registration,
    normalize_periods,
    normalize_trial,
)
from custom_components.horizoniq.models import ForecastFreshness, HorizonIQSnapshot


FIXTURE = Path(__file__).with_name("fixtures") / "direct_schema5_forecast.json"


def _schema_payload() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _schema6_payload() -> dict[str, object]:
    """Build a valid schema-6 fixture from the complete schema-5 contract."""
    payload = _schema_payload()
    payload["schemaVersion"] = 6
    payload["shouldExport"] = False
    periods = payload["periods"]
    assert isinstance(periods, list)
    for period in periods:
        assert isinstance(period, dict)
        period["shouldExport"] = False
    return payload


def _legacy_direct_payload() -> dict[str, object]:
    """Return the supported snake-case schema-version legacy wire shape."""
    payload = _schema_payload()
    payload["schema_version"] = payload.pop("schemaVersion")
    return payload


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


def test_normalize_forecast_extracts_trial_fields() -> None:
    """Forecast normalization exposes app-trial state."""
    payload = {
        "hasTrial": True,
        "isActive": False,
        "isEligible": False,
        "status": "expired",
        "startsOnUtc": "2026-05-01T00:00:00Z",
        "expiresOnUtc": "2026-05-15T00:00:00Z",
        "forecastCadenceMinutes": 30,
        "deviceDisplayName": "GX device",
    }

    forecast = normalize_forecast(payload)

    assert forecast["trial_has_trial"] is True
    assert forecast["trial_is_active"] is False
    assert forecast["trial_is_eligible"] is False
    assert forecast["trial_status"] == "expired"
    assert forecast["trial_starts_on_utc"] == "2026-05-01T00:00:00Z"
    assert forecast["trial_expires_on_utc"] == "2026-05-15T00:00:00Z"
    assert forecast["forecast_cadence_minutes"] == 30
    assert forecast["trial_forecast_cadence_minutes"] == 30
    assert forecast["trial_device_display_name"] == "GX device"
    assert normalize_trial(payload) == {
        "has_trial": True,
        "is_active": False,
        "is_eligible": False,
        "status": "expired",
        "starts_on_utc": "2026-05-01T00:00:00Z",
        "expires_on_utc": "2026-05-15T00:00:00Z",
        "forecast_cadence_minutes": 30,
        "device_display_name": "GX device",
    }


def test_normalize_forecast_extracts_top_level_trial_with_nested_forecast() -> None:
    """Top-level trial metadata is preserved when forecast data is nested."""
    payload = {
        "Forecast": {
            "Hash": "hash-123",
            "Periods": [{"Period": 1, "Date": "2026-05-01T00:00:00Z"}],
        },
        "hasTrial": True,
        "isActive": True,
        "isEligible": False,
        "status": "active",
    }

    snapshot = build_snapshot(payload)

    assert snapshot.trial == {
        "has_trial": True,
        "is_active": True,
        "is_eligible": False,
        "status": "active",
    }
    assert snapshot.forecast["trial_status"] == "active"
    assert snapshot.forecast["trial_is_active"] is True


def test_normalize_trial_extracts_nested_trial_container() -> None:
    """Trial metadata may arrive in a dedicated trial object."""
    payload = {
        "Forecast": {"Hash": "hash-123"},
        "trial": {
            "hasTrial": False,
            "isActive": False,
            "isEligible": True,
            "status": "eligible",
            "forecastCadenceMinutes": 30,
        },
    }

    snapshot = build_snapshot(payload)

    assert snapshot.trial == {
        "has_trial": False,
        "is_active": False,
        "is_eligible": True,
        "status": "eligible",
        "forecast_cadence_minutes": 30,
    }
    assert snapshot.forecast["trial_status"] == "eligible"
    assert snapshot.forecast_cadence_minutes == 30


def test_build_snapshot_keeps_trial_payload_out_of_registration() -> None:
    """Trial-only payloads are treated as forecast diagnostics, not registration."""
    payload = {
        "hasTrial": False,
        "isActive": False,
        "isEligible": True,
        "status": "eligible",
    }

    assert build_snapshot(payload) == HorizonIQSnapshot(
        forecast={
            "trial_has_trial": False,
            "trial_is_active": False,
            "trial_is_eligible": True,
            "trial_status": "eligible",
        },
        trial={
            "has_trial": False,
            "is_active": False,
            "is_eligible": True,
            "status": "eligible",
        },
    )


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

    assert build_snapshot(payload) == HorizonIQSnapshot(
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

    assert build_snapshot(payload) == HorizonIQSnapshot(
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

    assert build_snapshot(payload) == HorizonIQSnapshot(
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


@pytest.mark.parametrize("alias", ("Hash", "hash", "forecastHash", "forecast_hash"))
def test_schema6_envelope_hash_is_preserved_with_canonical_aliases(alias: str) -> None:
    """Envelope aliases, rather than nested forecast fields, own cache metadata."""
    payload: dict[str, object] = {alias: " fresh-hash ", "Forecast": _schema6_payload()}

    snapshot = build_snapshot(payload)

    assert snapshot.forecast_freshness is ForecastFreshness.FRESH
    assert snapshot.forecast_hash == "fresh-hash"
    assert snapshot.forecast["hash"] == "fresh-hash"

    duplicate = build_snapshot(
        {
            alias: "fresh-hash",
            "forecast_hash": " fresh-hash ",
            "Forecast": _schema6_payload(),
        }
    )
    assert duplicate.forecast_hash == duplicate.forecast["hash"] == "fresh-hash"


@pytest.mark.parametrize(
    "envelope_hash",
    (None, "", "  ", True, 1, 1.0, [], {}),
)
def test_schema56_envelope_hash_invalid_shapes_or_conflicts_do_not_coerce_or_replace_legacy_diagnostics(
    envelope_hash: object,
) -> None:
    """Present invalid aliases never become cache hashes or raise parsing errors."""
    for forecast in (_schema_payload(), _schema6_payload()):
        snapshot = build_snapshot({"Hash": envelope_hash, "Forecast": forecast})

        assert snapshot.forecast_freshness is ForecastFreshness.FRESH
        assert snapshot.forecast_hash is None


def test_schema56_invalid_or_conflicting_present_envelope_hash_never_uses_nested_cache_fallback() -> None:
    """Invalid envelope aliases leave canonical schema diagnostics unchanged."""
    for forecast in (_schema_payload(), _schema6_payload()):
        forecast["hash"] = "nested-hash"
        canonical = build_snapshot({"Forecast": forecast})
        snapshot = build_snapshot(
            {"Hash": "fresh-hash", "hash": "other-hash", "Forecast": forecast}
        )

        assert snapshot.forecast_hash is None
        assert snapshot.forecast == canonical.forecast


def test_legacy_snapshot_keeps_existing_nested_hash_only_when_envelope_alias_is_truly_absent() -> None:
    """Legacy nested hash coercion is retained only for genuinely absent aliases."""
    legacy = {"Forecast": {"Hash": 123, "Periods": []}}

    absent = build_snapshot(legacy)
    invalid = build_snapshot({"Hash": None, **legacy})
    valid = build_snapshot({"Hash": " envelope ", **legacy})

    assert absent.forecast_hash == "123"
    assert invalid.forecast_hash is None
    assert invalid.forecast["hash"] == "123"
    assert valid.forecast_hash == "envelope"
    assert valid.forecast["hash"] == "envelope"


def test_valid_schema56_without_optional_direct_model_remains_fresh_but_non_executable() -> None:
    """A complete schema response without equipment profile is accepted diagnostics."""
    for forecast in (_schema_payload(), _schema6_payload()):
        forecast.pop("equipmentProfile")

        snapshot = build_snapshot({"Hash": "fresh-hash", "Forecast": forecast})

        assert snapshot.forecast_freshness is ForecastFreshness.FRESH
        assert snapshot.direct_forecast is None
        assert snapshot.schema5_forecast is not None


def test_legacy_direct_capable_and_non_direct_payloads_keep_the_freshness_matrix() -> None:
    """Supported legacy schema aliases remain direct while diagnostics are missing."""
    direct = build_snapshot(_legacy_direct_payload())
    diagnostic = build_snapshot({"Forecast": {"Periods": []}})

    assert direct.forecast_freshness is ForecastFreshness.FRESH
    assert direct.direct_forecast is not None
    assert diagnostic.forecast_freshness is ForecastFreshness.MISSING
    assert diagnostic.direct_forecast is None


@pytest.mark.parametrize("schema_version", (5, 6))
@pytest.mark.parametrize(
    "alias", ("RegistrationData", "registrationData", "registration_data")
)
@pytest.mark.parametrize(
    ("wrapper", "location"),
    (
        (None, "flat"),
        ("Forecast", "envelope"),
        ("Forecast", "nested"),
        ("forecast", "envelope"),
        ("forecast", "nested"),
        ("forecastEntity", "envelope"),
        ("forecastEntity", "nested"),
    ),
)
def test_schema56_registration_metadata_is_kept_private(
    schema_version: int, alias: str, wrapper: str | None, location: str
) -> None:
    """All supported transport shapes keep the opaque credential private."""
    credential = "synthetic-registration+/=&? internal space"
    forecast = _schema_payload() if schema_version == 5 else _schema6_payload()
    baseline = build_snapshot(deepcopy(forecast))
    payload = forecast if wrapper is None else {wrapper: forecast}
    metadata_source = forecast if location in {"flat", "nested"} else payload
    metadata_source[alias] = f" \t{credential}\n "
    original = deepcopy(payload)

    snapshot = build_snapshot(payload)

    assert payload == original
    assert snapshot.forecast_freshness is ForecastFreshness.FRESH
    assert snapshot.registration_data == credential
    assert snapshot.schema5_forecast is not None
    assert snapshot.direct_forecast is not None
    assert baseline.schema5_forecast is not None
    assert snapshot.direct_forecast.registration_data == ""
    assert snapshot.forecast == baseline.forecast
    assert snapshot.schema5_forecast.to_dict() == baseline.schema5_forecast.to_dict()
    assert snapshot.direct_forecast == baseline.direct_forecast
    assert snapshot.forecast_periods == baseline.forecast_periods
    assert snapshot.registration == baseline.registration == {}
    assert credential not in repr(
        (
            snapshot.forecast,
            snapshot.schema5_forecast.to_dict(),
            snapshot.direct_forecast,
            snapshot.forecast_periods,
            snapshot.registration,
        )
    )


@pytest.mark.parametrize("schema_version", (5, 6))
@pytest.mark.parametrize(
    "metadata",
    (
        pytest.param({}, id="absent"),
        pytest.param({"registrationData": None}, id="null"),
        pytest.param({"registrationData": ""}, id="empty"),
        pytest.param({"registrationData": " \t\n "}, id="whitespace"),
        pytest.param({"registrationData": True}, id="bool"),
        pytest.param({"registrationData": 7}, id="integer"),
        pytest.param({"registrationData": 1.5}, id="float"),
        pytest.param({"registrationData": []}, id="empty-list"),
        pytest.param({"registrationData": ["opaque"]}, id="list"),
        pytest.param({"registrationData": [None]}, id="null-list"),
        pytest.param({"registrationData": ["opaque", None]}, id="mixed-list"),
        pytest.param({"registrationData": {}}, id="empty-mapping"),
        pytest.param({"registrationData": {"opaque": "value"}}, id="mapping"),
    ),
)
def test_schema56_missing_or_invalid_registration_metadata_is_ignored(
    schema_version: int, metadata: dict[str, object]
) -> None:
    """Invalid optional metadata leaves the complete accepted plan unchanged."""
    forecast = _schema_payload() if schema_version == 5 else _schema6_payload()
    baseline = build_snapshot(deepcopy(forecast))
    payload = {**forecast, **deepcopy(metadata)}
    original = deepcopy(payload)

    snapshot = build_snapshot(payload)

    assert payload == original
    assert snapshot.registration_data is None
    assert snapshot.forecast_freshness is ForecastFreshness.FRESH
    assert snapshot == baseline


@pytest.mark.parametrize("schema_version", (5, 6))
@pytest.mark.parametrize("wrapper", ("Forecast", "forecast", "forecastEntity"))
@pytest.mark.parametrize(
    ("envelope_metadata", "nested_metadata", "expected"),
    (
        pytest.param(
            {
                "registration_data": "third",
                "registrationData": "second",
                "RegistrationData": " first ",
            },
            {},
            "first",
            id="all-aliases",
        ),
        pytest.param(
            {"registration_data": "third", "registrationData": " second "},
            {},
            "second",
            id="camel-before-snake",
        ),
        pytest.param(
            {"RegistrationData": " same ", "registrationData": "same"},
            {},
            "same",
            id="duplicate",
        ),
        pytest.param(
            {"registration_data": " envelope "},
            {"RegistrationData": "nested"},
            "envelope",
            id="envelope-first",
        ),
        pytest.param(
            {"RegistrationData": None, "registrationData": "lower"},
            {"RegistrationData": "nested"},
            None,
            id="null-blocks-fallback",
        ),
        pytest.param(
            {"registrationData": [None], "registration_data": "lower"},
            {"RegistrationData": "nested"},
            None,
            id="invalid-blocks-fallback",
        ),
        pytest.param(
            {"RegistrationData": " \t ", "registration_data": "lower"},
            {"RegistrationData": "nested"},
            None,
            id="blank-blocks-fallback",
        ),
        pytest.param(
            {},
            {
                "registration_data": "third",
                "registrationData": "second",
                "RegistrationData": " nested ",
            },
            "nested",
            id="absent-envelope",
        ),
        pytest.param(
            {},
            {"RegistrationData": False, "registrationData": "lower"},
            None,
            id="nested-invalid-blocks-fallback",
        ),
    ),
)
def test_schema56_registration_metadata_uses_existing_alias_precedence(
    schema_version: int,
    wrapper: str,
    envelope_metadata: dict[str, object],
    nested_metadata: dict[str, object],
    expected: str | None,
) -> None:
    """First present alias wins, even when it blocks otherwise valid metadata."""
    forecast = _schema_payload() if schema_version == 5 else _schema6_payload()
    forecast.update(deepcopy(nested_metadata))
    payload = {wrapper: forecast, **deepcopy(envelope_metadata)}
    original = deepcopy(payload)

    snapshot = build_snapshot(payload)

    assert snapshot.registration_data == expected
    assert snapshot.forecast_freshness is ForecastFreshness.FRESH
    assert payload == original


@pytest.mark.parametrize("schema_version", (5, 6))
def test_schema56_registration_metadata_is_preserved_without_direct_model(
    schema_version: int,
) -> None:
    """Credential transport does not depend on an optional equipment profile."""
    credential = "synthetic-registration+/=&? internal space"
    forecast = _schema_payload() if schema_version == 5 else _schema6_payload()
    forecast.pop("equipmentProfile")
    forecast["registrationData"] = f" {credential} "
    original = deepcopy(forecast)

    snapshot = build_snapshot(forecast)

    assert snapshot.registration_data == credential
    assert snapshot.forecast_freshness is ForecastFreshness.FRESH
    assert snapshot.schema5_forecast is not None
    assert not snapshot.schema5_forecast.stale
    assert snapshot.direct_forecast is None
    assert forecast == original
    assert credential not in repr(
        (
            snapshot.forecast,
            snapshot.schema5_forecast.to_dict(),
            snapshot.forecast_periods,
            snapshot.registration,
        )
    )

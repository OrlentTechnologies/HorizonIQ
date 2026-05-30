from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal
import json

from .models import (
    ForecastData,
    ForecastPeriod,
    MeshSolarSnapshot,
    RegistrationData,
    TrialData,
)


def extract_first(payload: Mapping[str, object], keys: Iterable[str]) -> object | None:
    """Return the first matching value from a payload."""
    for key in keys:
        if key in payload:
            value = payload[key]
            if value is None:
                return ""
            return value
    return None


def normalize_periods(payload: Mapping[str, object] | None) -> list[ForecastPeriod]:
    """Normalize forecast periods into the integration's stable shape."""
    if not isinstance(payload, Mapping):
        return []

    raw_periods: object | None = None
    for key in ("Periods", "periods", "forecastPeriods", "ForecastPeriods"):
        if key in payload:
            raw_periods = payload.get(key)
            break

    if raw_periods is None:
        forecast_container = _extract_forecast_source(payload)
        if forecast_container is not payload:
            for key in ("Periods", "periods", "forecastPeriods", "ForecastPeriods"):
                if key in forecast_container:
                    raw_periods = forecast_container.get(key)
                    break

    if not isinstance(raw_periods, list):
        return []

    normalized_periods: list[ForecastPeriod] = []
    for item in raw_periods:
        if not isinstance(item, Mapping):
            continue

        period: ForecastPeriod = {}
        _add_if_value(period, "id", _coerce_str(extract_first(item, ("Id", "id"))))
        _add_if_value(
            period,
            "period",
            _coerce_int(extract_first(item, ("Period", "period", "index"))),
        )
        _add_if_value(
            period,
            "date",
            _coerce_datetime(extract_first(item, ("Date", "date", "start"))),
        )
        _add_if_value(
            period,
            "price",
            _coerce_float(extract_first(item, ("Price", "price"))),
        )
        _add_if_value(
            period,
            "should_import",
            _coerce_bool(
                extract_first(item, ("ShouldImport", "shouldImport", "should_import"))
            ),
        )
        _add_if_value(
            period,
            "amount",
            _coerce_float(extract_first(item, ("Amount", "amount"))),
        )
        _add_if_value(
            period,
            "imported",
            _coerce_float(extract_first(item, ("Imported", "imported"))),
        )
        _add_if_value(
            period,
            "exported",
            _coerce_float(extract_first(item, ("Exported", "exported"))),
        )
        _add_if_value(
            period,
            "estimated_generation",
            _coerce_float(
                extract_first(
                    item,
                    (
                        "EstimatedGeneration",
                        "estimatedGeneration",
                        "estimated_generation",
                    ),
                )
            ),
        )
        _add_if_value(
            period,
            "used",
            _coerce_float(extract_first(item, ("Used", "used"))),
        )
        _add_if_value(
            period,
            "battery",
            _coerce_float(extract_first(item, ("Battery", "battery"))),
        )
        _add_if_value(
            period,
            "bms_hold_period",
            _coerce_bool(
                extract_first(
                    item,
                    (
                        "BmsHoldPeriod",
                        "bmsHoldPeriod",
                        "bms_hold_period",
                        "bmsholdperiod",
                    ),
                )
            ),
        )
        _add_if_value(
            period,
            "battery_management_system_state",
            _coerce_str(
                extract_first(
                    item,
                    (
                        "BatteryManagementSystemState",
                        "batteryManagementSystemState",
                        "battery_management_system_state",
                    ),
                )
            ),
        )
        if period:
            normalized_periods.append(period)

    return normalized_periods


def normalize_forecast(payload: Mapping[str, object] | None) -> ForecastData:
    """Normalize a forecast payload into the integration's stable shape."""
    if not isinstance(payload, Mapping):
        return {}

    forecast_source = _extract_forecast_source(payload)
    normalized: ForecastData = {}

    _add_if_value(
        normalized,
        "id",
        _coerce_str(extract_first(forecast_source, ("Id", "id"))),
    )
    _add_if_value(
        normalized,
        "registration_id",
        _coerce_str(
            extract_first(
                forecast_source,
                ("RegistrationId", "registrationId", "registration_id"),
            )
        ),
    )
    _add_if_value(
        normalized,
        "date",
        _coerce_datetime(
            extract_first(
                forecast_source,
                ("Date", "date", "forecastDate", "forecast_date"),
            )
        ),
    )
    _add_if_value(
        normalized,
        "calculated_on_utc",
        _coerce_datetime(
            extract_first(
                forecast_source,
                ("CalculatedOnUtc", "calculatedOnUtc", "calculated_on_utc"),
            )
        ),
    )
    _add_if_value(
        normalized,
        "hash",
        _coerce_str(
            extract_first(
                forecast_source,
                ("Hash", "hash", "forecastHash", "forecast_hash"),
            )
        ),
    )

    periods = normalize_periods(forecast_source)
    if periods:
        normalized["periods"] = periods

    _add_if_value(
        normalized,
        "current_capacity",
        _coerce_float(
            extract_first(
                forecast_source,
                ("CurrentCapacity", "currentCapacity", "current_capacity"),
            )
        ),
    )
    _add_if_value(
        normalized,
        "min_capacity",
        _coerce_float(
            extract_first(
                forecast_source,
                ("MinCapacity", "minCapacity", "min_capacity"),
            )
        ),
    )
    _add_if_value(
        normalized,
        "target_capacity",
        _coerce_float(
            extract_first(
                forecast_source,
                ("TargetCapacity", "targetCapacity", "target_capacity"),
            )
        ),
    )
    _add_if_value(
        normalized,
        "low_price",
        _coerce_float(
            extract_first(
                forecast_source,
                ("LowPrice", "lowPrice", "low_price"),
            )
        ),
    )
    _add_if_value(
        normalized,
        "medium_price",
        _coerce_float(
            extract_first(
                forecast_source,
                ("MediumPrice", "mediumPrice", "medium_price"),
            )
        ),
    )
    _add_if_value(
        normalized,
        "battery_management_system_state",
        _coerce_str(
            extract_first(
                forecast_source,
                (
                    "BatteryManagementSystemState",
                    "batteryManagementSystemState",
                    "battery_management_system_state",
                ),
            )
        ),
    )
    _add_if_value(
        normalized,
        "should_import",
        _coerce_bool(
            extract_first(
                forecast_source,
                ("ShouldImport", "shouldImport", "should_import"),
            )
        ),
    )
    _add_if_value(
        normalized,
        "cloud_update_enabled",
        _coerce_bool(
            extract_first(
                forecast_source,
                ("CloudUpdateEnabled", "cloudUpdateEnabled", "cloud_update_enabled"),
            )
        ),
    )
    _add_if_value(
        normalized,
        "registration_data",
        _coerce_registration_data_string(
            _extract_registration_data_value(forecast_source)
        ),
    )
    _add_if_value(
        normalized,
        "total_cost",
        _coerce_float(
            extract_first(
                forecast_source,
                ("TotalCost", "totalCost", "total_cost"),
            )
        ),
    )
    _add_if_value(
        normalized,
        "charging_cost",
        _coerce_float(
            extract_first(
                forecast_source,
                ("ChargingCost", "chargingCost", "charging_cost"),
            )
        ),
    )
    _add_if_value(
        normalized,
        "saving",
        _coerce_float(
            extract_first(forecast_source, ("Saving", "saving", "savings"))
        ),
    )
    _add_if_value(
        normalized,
        "forecast_cadence_minutes",
        _coerce_positive_int(
            extract_first(
                forecast_source,
                (
                    "ForecastCadenceMinutes",
                    "forecastCadenceMinutes",
                    "forecast_cadence_minutes",
                ),
            )
        ),
    )
    _add_trial_forecast_fields(normalized, normalize_trial(payload))

    return normalized


def normalize_trial(payload: Mapping[str, object] | None) -> TrialData:
    """Normalize app-trial metadata from forecast or trial payload containers."""
    if not isinstance(payload, Mapping):
        return {}

    trial: TrialData = {}
    for source, include_generic_status in _trial_sources(payload):
        has_trial_state = _has_trial_state_key(source)
        source_is_trial = (
            include_generic_status
            or has_trial_state
            or _has_authorization_key(source)
        )
        if not source_is_trial:
            continue
        source_trial = _normalize_trial_source(
            source,
            include_generic_status=include_generic_status or has_trial_state,
        )
        for key, value in source_trial.items():
            if key not in trial:
                trial[key] = value

    return trial


def normalize_registration(payload: Mapping[str, object] | None) -> RegistrationData:
    """Normalize registration data into a JSON-safe mapping for diagnostics."""
    if not isinstance(payload, Mapping):
        return {}

    registration_value = _extract_registration_value(payload)
    if isinstance(registration_value, str):
        registration_value = _parse_json_value(registration_value)

    if not isinstance(registration_value, Mapping):
        return {}

    normalized = _normalize_json_value(registration_value)
    if not isinstance(normalized, dict):
        return {}
    return normalized


def extract_forecast_cadence_minutes_from_registration_data(
    registration_data: str | None,
) -> int | None:
    """Return the cadence in minutes from cached registration data."""
    if registration_data in (None, ""):
        return None

    registration_value = _parse_json_value(registration_data)
    if not isinstance(registration_value, Mapping):
        return None

    return _coerce_positive_int(
        extract_first(
            registration_value,
            (
                "ForecastCadenceMinutes",
                "forecastCadenceMinutes",
                "forecast_cadence_minutes",
            ),
        )
    )


def build_snapshot(payload: Mapping[str, object] | None) -> MeshSolarSnapshot:
    """Build the coordinator snapshot from a raw API payload."""
    if not isinstance(payload, Mapping):
        return MeshSolarSnapshot()

    forecast = dict(normalize_forecast(payload))
    trial = normalize_trial(payload)
    periods = forecast.get("periods") or normalize_periods(payload)
    if periods:
        forecast["periods"] = periods
    registration = normalize_registration(payload)

    forecast_hash = _coerce_str(
        extract_first(payload, ("Hash", "hash", "forecastHash", "forecast_hash"))
    ) or forecast.get("hash")
    registration_data = _coerce_registration_data_string(
        _extract_registration_data_value(payload)
    ) or forecast.get("registration_data")
    if registration_data is None and registration:
        registration_data = _serialize_json_value(registration)
    should_import = _coerce_bool(
        extract_first(payload, ("ShouldImport", "shouldImport", "should_import"))
    )
    if should_import is None:
        should_import = forecast.get("should_import")
    total_cost = _coerce_float(
        extract_first(payload, ("TotalCost", "totalCost", "total_cost"))
    )
    if total_cost is None:
        total_cost = forecast.get("total_cost")
    charging_cost = _coerce_float(
        extract_first(payload, ("ChargingCost", "chargingCost", "charging_cost"))
    )
    if charging_cost is None:
        charging_cost = forecast.get("charging_cost")
    saving = _coerce_float(
        extract_first(payload, ("Saving", "saving", "savings"))
    )
    if saving is None:
        saving = forecast.get("saving")
    target_capacity = _coerce_float(
        extract_first(payload, ("TargetCapacity", "targetCapacity", "target_capacity"))
    )
    if target_capacity is None:
        target_capacity = forecast.get("target_capacity")
    top_level_forecast_cadence_minutes = _coerce_positive_int(
        extract_first(
            payload,
            (
                "ForecastCadenceMinutes",
                "forecastCadenceMinutes",
                "forecast_cadence_minutes",
            ),
        )
    )
    forecast_cadence_minutes = top_level_forecast_cadence_minutes or forecast.get(
        "forecast_cadence_minutes"
    )
    if forecast_cadence_minutes is None and registration:
        forecast_cadence_minutes = _coerce_positive_int(
            extract_first(
                registration,
                (
                    "ForecastCadenceMinutes",
                    "forecastCadenceMinutes",
                    "forecast_cadence_minutes",
                ),
            )
        )
    if forecast_cadence_minutes is None:
        forecast_cadence_minutes = trial.get("forecast_cadence_minutes")
    currency = _coerce_str(
        extract_first(payload, ("currency", "Currency", "currencyCode", "CurrencyCode"))
    )

    _add_if_value(forecast, "hash", forecast_hash)
    _add_if_value(forecast, "registration_data", registration_data)
    _add_if_value(forecast, "should_import", should_import)
    _add_if_value(forecast, "total_cost", total_cost)
    _add_if_value(forecast, "charging_cost", charging_cost)
    _add_if_value(forecast, "saving", saving)
    _add_if_value(forecast, "target_capacity", target_capacity)
    _add_if_value(forecast, "currency", currency)
    _add_if_value(
        forecast,
        "forecast_cadence_minutes",
        top_level_forecast_cadence_minutes,
    )

    return MeshSolarSnapshot(
        forecast=forecast,
        trial=trial,
        forecast_periods=periods,
        registration=registration,
        currency=currency,
        target_capacity=target_capacity,
        should_import=should_import,
        total_cost=total_cost,
        charging_cost=charging_cost,
        saving=saving,
        forecast_hash=forecast_hash,
        registration_data=registration_data,
        forecast_cadence_minutes=forecast_cadence_minutes,
    )


def _extract_forecast_source(payload: Mapping[str, object]) -> Mapping[str, object]:
    for key in ("Forecast", "forecast", "forecastEntity"):
        candidate = payload.get(key)
        if isinstance(candidate, Mapping):
            return candidate
    return payload


def _extract_registration_value(payload: Mapping[str, object]) -> object | None:
    if _looks_like_registration_payload(payload):
        return payload

    for container in _payload_containers(payload):
        for key in ("Registration", "registration", "registrationEntity"):
            if key in container:
                return container.get(key)

    return _extract_registration_data_value(payload)


def _extract_registration_data_value(payload: Mapping[str, object]) -> object | None:
    for container in _payload_containers(payload):
        for key in ("RegistrationData", "registrationData", "registration_data"):
            if key in container:
                return container.get(key)
    return None


def _payload_containers(
    payload: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    forecast_source = _extract_forecast_source(payload)
    if forecast_source is payload:
        return (payload,)
    return (payload, forecast_source)


def _trial_sources(
    payload: Mapping[str, object],
) -> tuple[tuple[Mapping[str, object], bool], ...]:
    sources: list[tuple[Mapping[str, object], bool]] = []
    seen: set[int] = set()

    def add_source(source: Mapping[str, object], include_generic_status: bool) -> None:
        source_id = id(source)
        if source_id in seen:
            return
        seen.add(source_id)
        sources.append((source, include_generic_status))

    for container in _payload_containers(payload):
        for key in (
            "Trial",
            "trial",
            "TrialInfo",
            "trialInfo",
            "trial_info",
            "TrialState",
            "trialState",
            "trial_state",
        ):
            candidate = container.get(key)
            if isinstance(candidate, Mapping):
                add_source(candidate, True)

    for container in _payload_containers(payload):
        add_source(container, False)

    return tuple(sources)


def _normalize_trial_source(
    source: Mapping[str, object],
    *,
    include_generic_status: bool,
) -> TrialData:
    trial: TrialData = {}

    _add_if_value(
        trial,
        "has_trial",
        _coerce_bool(extract_first(source, ("HasTrial", "hasTrial", "has_trial"))),
    )
    _add_if_value(
        trial,
        "is_active",
        _coerce_bool(extract_first(source, ("IsActive", "isActive", "is_active"))),
    )
    _add_if_value(
        trial,
        "is_eligible",
        _coerce_bool(
            extract_first(source, ("IsEligible", "isEligible", "is_eligible"))
        ),
    )

    status_keys = ["TrialStatus", "trialStatus", "trial_status"]
    if include_generic_status:
        status_keys.extend(("Status", "status"))
    _add_if_value(
        trial,
        "status",
        _coerce_str(extract_first(source, status_keys)),
    )
    _add_if_value(
        trial,
        "starts_on_utc",
        _coerce_datetime(
            extract_first(
                source,
                (
                    "TrialStartsOnUtc",
                    "trialStartsOnUtc",
                    "trial_starts_on_utc",
                    "StartsOnUtc",
                    "startsOnUtc",
                    "starts_on_utc",
                ),
            )
        ),
    )
    _add_if_value(
        trial,
        "expires_on_utc",
        _coerce_datetime(
            extract_first(
                source,
                (
                    "TrialExpiresOnUtc",
                    "trialExpiresOnUtc",
                    "trial_expires_on_utc",
                    "ExpiresOnUtc",
                    "expiresOnUtc",
                    "expires_on_utc",
                ),
            )
        ),
    )
    _add_if_value(
        trial,
        "forecast_cadence_minutes",
        _coerce_positive_int(
            extract_first(
                source,
                (
                    "TrialForecastCadenceMinutes",
                    "trialForecastCadenceMinutes",
                    "trial_forecast_cadence_minutes",
                    "ForecastCadenceMinutes",
                    "forecastCadenceMinutes",
                    "forecast_cadence_minutes",
                ),
            )
        ),
    )
    _add_if_value(
        trial,
        "device_display_name",
        _coerce_str(
            extract_first(
                source,
                (
                    "TrialDeviceDisplayName",
                    "trialDeviceDisplayName",
                    "trial_device_display_name",
                    "DeviceDisplayName",
                    "deviceDisplayName",
                    "device_display_name",
                ),
            )
        ),
    )
    _add_if_value(
        trial,
        "authorization_status",
        _coerce_str(
            extract_first(
                source,
                ("AuthorizationStatus", "authorizationStatus", "authorization_status"),
            )
        ),
    )
    _add_if_value(
        trial,
        "authorization_status_code",
        _coerce_int(
            extract_first(
                source,
                (
                    "AuthorizationStatusCode",
                    "authorizationStatusCode",
                    "authorization_status_code",
                ),
            )
        ),
    )
    _add_if_value(
        trial,
        "authorization_message",
        _coerce_str(
            extract_first(
                source,
                (
                    "AuthorizationMessage",
                    "authorizationMessage",
                    "authorization_message",
                ),
            )
        ),
    )

    return trial


def _add_trial_forecast_fields(
    forecast: ForecastData,
    trial: Mapping[str, object],
) -> None:
    _add_if_value(forecast, "trial_has_trial", trial.get("has_trial"))
    _add_if_value(forecast, "trial_is_active", trial.get("is_active"))
    _add_if_value(forecast, "trial_is_eligible", trial.get("is_eligible"))
    _add_if_value(forecast, "trial_status", trial.get("status"))
    _add_if_value(forecast, "trial_starts_on_utc", trial.get("starts_on_utc"))
    _add_if_value(forecast, "trial_expires_on_utc", trial.get("expires_on_utc"))
    _add_if_value(
        forecast,
        "trial_forecast_cadence_minutes",
        trial.get("forecast_cadence_minutes"),
    )
    _add_if_value(
        forecast,
        "trial_device_display_name",
        trial.get("device_display_name"),
    )
    _add_if_value(
        forecast,
        "authorization_status",
        trial.get("authorization_status"),
    )
    _add_if_value(
        forecast,
        "authorization_status_code",
        trial.get("authorization_status_code"),
    )
    _add_if_value(
        forecast,
        "authorization_message",
        trial.get("authorization_message"),
    )


def _has_trial_specific_key(payload: Mapping[str, object]) -> bool:
    return _has_trial_state_key(payload) or _has_authorization_key(payload)


def _has_trial_state_key(payload: Mapping[str, object]) -> bool:
    trial_keys = (
        "HasTrial",
        "hasTrial",
        "has_trial",
        "IsActive",
        "isActive",
        "is_active",
        "IsEligible",
        "isEligible",
        "is_eligible",
        "TrialStatus",
        "trialStatus",
        "trial_status",
        "TrialStartsOnUtc",
        "trialStartsOnUtc",
        "trial_starts_on_utc",
        "TrialExpiresOnUtc",
        "trialExpiresOnUtc",
        "trial_expires_on_utc",
        "TrialForecastCadenceMinutes",
        "trialForecastCadenceMinutes",
        "trial_forecast_cadence_minutes",
        "TrialDeviceDisplayName",
        "trialDeviceDisplayName",
        "trial_device_display_name",
    )
    return any(key in payload for key in trial_keys)


def _has_authorization_key(payload: Mapping[str, object]) -> bool:
    authorization_keys = (
        "AuthorizationStatus",
        "authorizationStatus",
        "authorization_status",
        "AuthorizationStatusCode",
        "authorizationStatusCode",
        "authorization_status_code",
        "AuthorizationMessage",
        "authorizationMessage",
        "authorization_message",
    )
    return any(key in payload for key in authorization_keys)


def _looks_like_registration_payload(payload: Mapping[str, object]) -> bool:
    forecast_keys = (
        "Periods",
        "periods",
        "RegistrationId",
        "registrationId",
        "registration_id",
        "CalculatedOnUtc",
        "calculatedOnUtc",
        "calculated_on_utc",
        "CurrentCapacity",
        "currentCapacity",
        "current_capacity",
        "MinCapacity",
        "minCapacity",
        "min_capacity",
        "TargetCapacity",
        "targetCapacity",
        "target_capacity",
        "ShouldImport",
        "shouldImport",
        "should_import",
        "CloudUpdateEnabled",
        "cloudUpdateEnabled",
        "cloud_update_enabled",
        "TotalCost",
        "totalCost",
        "total_cost",
        "ChargingCost",
        "chargingCost",
        "charging_cost",
        "Saving",
        "saving",
        "LowPrice",
        "lowPrice",
        "low_price",
        "MediumPrice",
        "mediumPrice",
        "medium_price",
        "BatteryManagementSystemState",
        "batteryManagementSystemState",
        "battery_management_system_state",
        "HasTrial",
        "hasTrial",
        "has_trial",
        "IsActive",
        "isActive",
        "is_active",
        "IsEligible",
        "isEligible",
        "is_eligible",
        "TrialStatus",
        "trialStatus",
        "trial_status",
        "Status",
        "status",
        "StartsOnUtc",
        "startsOnUtc",
        "starts_on_utc",
        "ExpiresOnUtc",
        "expiresOnUtc",
        "expires_on_utc",
        "DeviceDisplayName",
        "deviceDisplayName",
        "device_display_name",
        "AuthorizationStatus",
        "authorizationStatus",
        "authorization_status",
        "AuthorizationStatusCode",
        "authorizationStatusCode",
        "authorization_status_code",
        "AuthorizationMessage",
        "authorizationMessage",
        "authorization_message",
    )
    if any(key in payload for key in forecast_keys):
        return False

    registration_keys = (
        "DynamicCharging",
        "dynamicCharging",
        "ImportForExport",
        "importForExport",
        "PaymentValid",
        "paymentValid",
        "RegistrationCheckedOnUtc",
        "registrationCheckedOnUtc",
        "ElectricityMeterMpan",
        "electricityMeterMpan",
        "BatteryManagementSystem",
        "batteryManagementSystem",
        "PreferredPaymentProvider",
        "preferredPaymentProvider",
        "ElectricityTariff",
        "electricityTariff",
        "Postcode",
        "postcode",
        "Solar",
        "solar",
        "Inverter",
        "inverter",
        "Battery",
        "battery",
        "Consumption",
        "consumption",
        "SolisCloud",
        "solisCloud",
    )
    return any(key in payload for key in registration_keys)


def _has_trial_payload(payload: Mapping[str, object]) -> bool:
    return bool(normalize_trial(payload))


def _coerce_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _coerce_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: object) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return value != 0
    if isinstance(value, str):
        candidate = value.strip().lower()
        if not candidate:
            return None
        if candidate in ("true", "t", "yes", "y", "1", "on"):
            return True
        if candidate in ("false", "f", "no", "n", "0", "off"):
            return False
    return None


def _coerce_datetime(value: object) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        candidate = value.strip()
        return candidate or None
    return str(value)


def _coerce_str(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip()


def _coerce_positive_int(value: object) -> int | None:
    candidate = _coerce_int(value)
    if candidate is None or candidate < 1:
        return None
    return candidate


def _coerce_registration_data_string(value: object) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        candidate = value.strip()
        return candidate or None
    if isinstance(value, (Mapping, list)):
        return _serialize_json_value(value)
    return _coerce_str(value)


def _parse_json_value(value: str) -> object | None:
    candidate = value.strip()
    if not candidate:
        return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def _serialize_json_value(value: object) -> str | None:
    normalized = _normalize_json_value(value)
    try:
        return json.dumps(normalized, separators=(",", ":"))
    except (TypeError, ValueError):
        return None


def _normalize_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_json_value(item_value)
            for key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_normalize_json_value(item_value) for item_value in value]
    if isinstance(value, tuple):
        return [_normalize_json_value(item_value) for item_value in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _add_if_value(target: dict[str, object], key: str, value: object) -> None:
    if value is None:
        return
    if isinstance(value, str) and value.strip() == "":
        return
    target[key] = value

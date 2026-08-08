"""Strict, entry-local HorizonIQ schema-5/6 forecast diagnostics models."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import math


LEGACY_SCHEMA_VERSION = 5
SCHEMA_VERSION = 6
SUPPORTED_SCHEMA_VERSIONS = frozenset({LEGACY_SCHEMA_VERSION, SCHEMA_VERSION})
PLAN_KINDS = frozenset({"live", "import_for_export_advisory", "sandbox_replay"})
SCHEMA5_PERIOD_DURATION = timedelta(minutes=30)
REASON_CODES = frozenset(
    {
        "none",
        "selected",
        "disabled",
        "missing_opportunity",
        "price_limit",
        "insufficient_value",
        "normal_charge_priority",
        "use_grid_priority",
        "reserve",
        "capacity",
        "power_limit",
    }
)
_PROHIBITED_DIAGNOSTIC_KEYS = frozenset(
    {
        "apikey",
        "apikeys",
        "api_key",
        "authorization",
        "authorizationheaders",
        "credential",
        "credentials",
        "credentialdata",
        "functionkey",
        "function_key",
        "functionkeys",
        "function_keys",
        "headers",
        "httpheaders",
        "http_headers",
        "requestheaders",
        "responseheaders",
        "keys",
        "key",
        "password",
        "privatekey",
        "privatekeys",
        "publickey",
        "publickeys",
        "registrationdata",
        "registration_data",
        "secret",
        "token",
    }
)
_NORMALIZED_PROHIBITED_DIAGNOSTIC_KEYS = frozenset(
    key.replace("_", "").replace("-", "")
    for key in _PROHIBITED_DIAGNOSTIC_KEYS
)


class Schema5ForecastError(ValueError):
    """Raised when a schema-5/6 forecast is incomplete or malformed."""


def adapt_schema5_wire(payload: Mapping[str, object]) -> dict[str, object] | None:
    """Adapt Solar's documented wire aliases into one canonical schema-5 object.

    This is deliberately an allow-list adapter.  It recognizes only the
    documented PascalCase, camelCase, and historical snake_case spellings, and
    refuses a response that gives two spellings different values.  Credentials
    and registration data are never copied into the canonical object.
    """
    if not isinstance(payload, Mapping):
        raise Schema5ForecastError("forecast payload must be an object")
    source = _forecast_source(payload)
    if _alias_value(source, "schemaVersion") is _MISSING:
        return None
    return _adapt_object(
        source,
        _FORECAST_FIELDS,
        children={
            "economicsAssumptions": (_ECONOMICS_FIELDS, {}),
            "plannedEnergyLedger": (_LEDGER_FIELDS, {}),
            "equipmentProfile": (
                _EQUIPMENT_FIELDS,
                {"supportedControl": (_CONTROL_FIELDS, {})},
            ),
            "periods": (
                _PERIOD_FIELDS,
                {
                    "decisionTrace": (
                        _TRACE_FIELDS,
                        {
                            "constraints": (_CONSTRAINT_FIELDS, {}),
                            "economicCalculation": (
                                _ECONOMIC_CALCULATION_FIELDS,
                                {},
                            ),
                            "rejectedCandidateActions": (
                                _REJECTED_ACTION_FIELDS,
                                {},
                            ),
                        },
                    )
                },
            ),
        },
    )


_MISSING = object()


def _pascal(name: str) -> str:
    return name[:1].upper() + name[1:]


def _snake(name: str) -> str:
    result: list[str] = []
    for character in name:
        if character.isupper():
            result.extend(("_", character.lower()))
        else:
            result.append(character)
    return "".join(result)


def _aliases(name: str) -> tuple[str, ...]:
    """Return the finite aliases explicitly supported for one contract field."""
    if name == "periods":
        return ("periods", "Periods", "forecastPeriods", "ForecastPeriods")
    return (name, _pascal(name), _snake(name))


_FORECAST_FIELDS = (
    "schemaVersion",
    "planId",
    "planKind",
    "importForExportEnabled",
    "importForExportAdvisoryEnabled",
    "createdAtUtc",
    "effectiveAtUtc",
    "economicsAssumptions",
    "plannedEnergyLedger",
    "equipmentProfile",
    "currentCapacity",
    "minCapacity",
    "targetCapacity",
    "lowPrice",
    "mediumPrice",
    "batteryManagementSystemState",
    "shouldImport",
    "shouldUseGrid",
    "shouldExport",
    "forecastCadenceMinutes",
    "totalCost",
    "chargingCost",
    "saving",
    "periods",
)
_ECONOMICS_FIELDS = (
    "exportRate", "chargeEfficiency", "dischargeEfficiency", "degradationCost",
    "supplierFeeAllowance", "uncertaintyHaircut", "minimumNetValue",
    "importForExportLimit", "exportRateUnit", "degradationCostUnit",
    "supplierFeeAllowanceUnit", "minimumNetValueUnit", "importForExportLimitUnit",
    "chargeEfficiencyUnit", "dischargeEfficiencyUnit", "uncertaintyHaircutUnit",
)
_LEDGER_FIELDS = (
    "gridImportKwh", "solarGenerationKwh", "loadKwh", "batteryChargeKwh",
    "batteryDischargeKwh", "gridExportKwh", "modeledLossesKwh", "balanceErrorKwh",
    "toleranceKwh", "healthy",
)
_EQUIPMENT_FIELDS = (
    "id", "version", "source", "displayName", "batteryCapacityWh",
    "minimumCapacityPercentage", "maximumBatteryChargePowerWatts",
    "maximumBatteryDischargePowerWatts", "inverterMaximumChargePowerWatts",
    "inverterMaximumDischargePowerWatts", "maximumGridImportPowerWatts",
    "maximumGridExportPowerWatts", "controlAdapterId", "supportedControl",
    "productionExportEnabled", "safeFallbackId",
)
_CONTROL_FIELDS = (
    "requiredCharging", "useGrid", "importForExport", "profitableExport",
    "solarHeadroomExport",
)
_PERIOD_FIELDS = (
    "period", "date", "price", "shouldImport", "shouldUseGrid", "shouldExport",
    "recommendedAction", "simulationAction", "executableAction", "commandId",
    "issuedAtUtc", "expiresAtUtc", "actionPriority", "expectedImport",
    "expectedExport", "expectedStartSoc", "expectedEndSoc", "expectedCost",
    "expectedRevenue", "expectedNetValue", "amount", "imported", "exported",
    "estimatedGeneration", "used", "battery", "batteryManagementSystemState",
    "decisionTrace",
)
_TRACE_FIELDS = (
    "selectedAction", "reasonCode", "explanation", "rejectedCandidateActions",
    "importRate", "exportRate", "expectedImportKwh", "expectedExportKwh",
    "expectedStartSocKwh", "expectedEndSocKwh", "constraints",
    "economicCalculation",
)
_REJECTED_ACTION_FIELDS = ("action", "reasonCode", "explanation")
_CONSTRAINT_FIELDS = (
    "reserveKwh", "availableHeadroomKwh", "chargePowerLimitKwh",
    "dischargePowerLimitKwh",
)
_ECONOMIC_CALCULATION_FIELDS = (
    "importCost", "exportRevenue", "supplierFees", "degradationCost",
    "grossValue", "riskAdjustedNetValue",
)


def _alias_value(source: Mapping[str, object], field: str) -> object:
    """Read one explicit alias, rejecting conflicting spellings atomically."""
    values = [(alias, source[alias]) for alias in _aliases(field) if alias in source]
    if not values:
        return _MISSING
    first = values[0][1]
    if any(value != first for _, value in values[1:]):
        names = ", ".join(alias for alias, _ in values)
        raise Schema5ForecastError(f"Conflicting aliases for {field}: {names}")
    return first


def _adapt_object(
    source: Mapping[str, object],
    fields: tuple[str, ...],
    *,
    children: Mapping[str, tuple[tuple[str, ...], Mapping[str, object]]],
) -> dict[str, object]:
    """Copy only supported aliases, recursively adapting declared child objects."""
    if fields is not _FORECAST_FIELDS and any(
        isinstance(key, str)
        and key.lower().replace("_", "").replace("-", "")
        in _NORMALIZED_PROHIBITED_DIAGNOSTIC_KEYS
        for key in source
    ):
        raise Schema5ForecastError("schema-5 diagnostics contain a prohibited key")
    result: dict[str, object] = {}
    for field in fields:
        value = _alias_value(source, field)
        if value is _MISSING:
            continue
        child = children.get(field)
        if child is not None:
            child_fields, grandchildren = child
            if isinstance(value, list):
                result[field] = [
                    _adapt_object(item, child_fields, children=grandchildren)
                    if isinstance(item, Mapping)
                    else item
                    for item in value
                ]
            elif isinstance(value, Mapping):
                result[field] = _adapt_object(value, child_fields, children=grandchildren)
            else:
                result[field] = value
        else:
            result[field] = deepcopy(value)
    return result


@dataclass(frozen=True, slots=True)
class Schema5DecisionTrace:
    """One backend decision trace without locally inferred economics."""

    selected_action: str
    reason_code: str
    explanation: str
    rejected_candidate_actions: tuple[object, ...]
    import_rate: float
    export_rate: float
    expected_import_kwh: float
    expected_export_kwh: float
    expected_start_soc_kwh: float
    expected_end_soc_kwh: float
    constraints: dict[str, object]
    economic_calculation: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        """Return the canonical, JSON-safe diagnostics shape."""
        return {
            "selectedAction": self.selected_action,
            "reasonCode": self.reason_code,
            "explanation": self.explanation,
            "rejectedCandidateActions": deepcopy(list(self.rejected_candidate_actions)),
            "importRate": self.import_rate,
            "exportRate": self.export_rate,
            "expectedImportKwh": self.expected_import_kwh,
            "expectedExportKwh": self.expected_export_kwh,
            "expectedStartSocKwh": self.expected_start_soc_kwh,
            "expectedEndSocKwh": self.expected_end_soc_kwh,
            "constraints": deepcopy(self.constraints),
            "economicCalculation": deepcopy(self.economic_calculation),
        }


@dataclass(frozen=True, slots=True)
class Schema5Period:
    """One complete schema-5/6 forecast period."""

    period: int
    date: str
    price: float
    should_import: bool
    should_use_grid: bool
    should_export: bool | None
    recommended_action: str
    simulation_action: str
    executable_action: str
    command_id: str | None
    issued_at_utc: str | None
    expires_at_utc: str | None
    action_priority: int | None
    expected_import: float
    expected_export: float
    expected_start_soc: float
    expected_end_soc: float
    expected_cost: float
    expected_revenue: float
    expected_net_value: float
    amount: float
    imported: float
    exported: float
    estimated_generation: float
    used: float
    battery: float
    battery_management_system_state: str | int
    decision_trace: Schema5DecisionTrace

    def to_dict(self) -> dict[str, object]:
        """Return the canonical diagnostics shape for this period."""
        return {
            "period": self.period,
            "date": self.date,
            "price": self.price,
            "shouldImport": self.should_import,
            "shouldUseGrid": self.should_use_grid,
            "shouldExport": self.should_export,
            "recommendedAction": self.recommended_action,
            "simulationAction": self.simulation_action,
            "executableAction": self.executable_action,
            "commandId": self.command_id,
            "issuedAtUtc": self.issued_at_utc,
            "expiresAtUtc": self.expires_at_utc,
            "actionPriority": self.action_priority,
            "expectedImport": self.expected_import,
            "expectedExport": self.expected_export,
            "expectedStartSoc": self.expected_start_soc,
            "expectedEndSoc": self.expected_end_soc,
            "expectedCost": self.expected_cost,
            "expectedRevenue": self.expected_revenue,
            "expectedNetValue": self.expected_net_value,
            "amount": self.amount,
            "imported": self.imported,
            "exported": self.exported,
            "estimatedGeneration": self.estimated_generation,
            "used": self.used,
            "battery": self.battery,
            "batteryManagementSystemState": self.battery_management_system_state,
            "decisionTrace": self.decision_trace.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class Schema5Forecast:
    """Complete normalized schema-5/6 plan retained only in entry-local memory."""

    schema_version: int
    plan_id: str
    plan_kind: str
    import_for_export_enabled: bool
    import_for_export_advisory_enabled: bool
    created_at_utc: str
    effective_at_utc: str
    economics_assumptions: dict[str, object]
    planned_energy_ledger: dict[str, object]
    equipment_profile: dict[str, object] | None
    current_capacity: float
    min_capacity: float
    target_capacity: float
    low_price: float
    medium_price: float
    battery_management_system_state: str | int
    should_import: bool
    should_use_grid: bool
    should_export: bool | None
    forecast_cadence_minutes: int | None
    total_cost: float
    charging_cost: float
    saving: float
    periods: tuple[Schema5Period, ...]
    stale: bool = False

    def as_stale(self) -> "Schema5Forecast":
        """Return the last complete forecast marked stale after a rejected update."""
        return replace(self, stale=True)

    def to_dict(self) -> dict[str, object]:
        """Return all contract fields without transport credentials or headers."""
        return {
            "schemaVersion": self.schema_version,
            "planId": self.plan_id,
            "planKind": self.plan_kind,
            "importForExportEnabled": self.import_for_export_enabled,
            "importForExportAdvisoryEnabled": self.import_for_export_advisory_enabled,
            "createdAtUtc": self.created_at_utc,
            "effectiveAtUtc": self.effective_at_utc,
            "economicsAssumptions": deepcopy(self.economics_assumptions),
            "plannedEnergyLedger": deepcopy(self.planned_energy_ledger),
            "equipmentProfile": deepcopy(self.equipment_profile),
            "currentCapacity": self.current_capacity,
            "minCapacity": self.min_capacity,
            "targetCapacity": self.target_capacity,
            "lowPrice": self.low_price,
            "mediumPrice": self.medium_price,
            "batteryManagementSystemState": self.battery_management_system_state,
            "shouldImport": self.should_import,
            "shouldUseGrid": self.should_use_grid,
            "shouldExport": self.should_export,
            "forecastCadenceMinutes": self.forecast_cadence_minutes,
            "totalCost": self.total_cost,
            "chargingCost": self.charging_cost,
            "saving": self.saving,
            "periods": [period.to_dict() for period in self.periods],
        }


def select_current_schema5_period(
    forecast: Schema5Forecast | None,
    now_utc: datetime | None,
) -> Schema5Period | None:
    """Return the accepted current half-hour schema-5 period in UTC.

    A stale, unsupported, or malformed in-memory forecast is deliberately
    unavailable to consumers.  Keeping the timestamp parsing here gives every
    entity the same inclusive-start, exclusive-end boundary behavior.
    """
    if (
        not isinstance(forecast, Schema5Forecast)
        or forecast.schema_version not in SUPPORTED_SCHEMA_VERSIONS
        or forecast.stale
        or forecast.plan_kind not in PLAN_KINDS
        or now_utc is None
        or now_utc.tzinfo is None
        or now_utc.utcoffset() is None
    ):
        return None

    current_time = now_utc.astimezone(timezone.utc)
    for period in forecast.periods:
        try:
            period_start = datetime.fromisoformat(period.date.replace("Z", "+00:00"))
        except ValueError:
            continue
        if period_start.tzinfo is None or period_start.utcoffset() is None:
            continue
        period_start = period_start.astimezone(timezone.utc)
        if period_start <= current_time < period_start + SCHEMA5_PERIOD_DURATION:
            return period
    return None


def parse_schema5_forecast(payload: Mapping[str, object]) -> Schema5Forecast | None:
    """Parse a complete schema-5/6 forecast or reject it before state changes."""
    source = adapt_schema5_wire(payload)
    if source is None:
        return None
    schema_version = _integer(source, "schemaVersion")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise Schema5ForecastError("Unsupported forecast schemaVersion")

    periods_value = source.get("periods")
    if not isinstance(periods_value, list):
        raise Schema5ForecastError("periods must be a list")
    periods = tuple(_period(item, schema_version=schema_version) for item in periods_value)
    economics_assumptions = _complete_object(
        source, "economicsAssumptions", _ECONOMICS_FIELDS
    )
    planned_energy_ledger = _complete_object(
        source, "plannedEnergyLedger", _LEDGER_FIELDS
    )
    equipment_profile = _optional_complete_object(
        source, "equipmentProfile", _EQUIPMENT_FIELDS
    )
    if equipment_profile is not None:
        equipment_profile["supportedControl"] = _complete_object(
            equipment_profile, "supportedControl", _CONTROL_FIELDS
        )
    should_import = _boolean(source, "shouldImport")
    should_export = _should_export(source, schema_version=schema_version)
    if should_import and should_export is True:
        raise Schema5ForecastError("shouldImport and shouldExport cannot both be true")
    if any(
        period.should_import and period.should_export is True for period in periods
    ):
        raise Schema5ForecastError("shouldImport and shouldExport cannot both be true")
    return Schema5Forecast(
        schema_version=schema_version,
        plan_id=_text(source, "planId"),
        plan_kind=_choice(source, "planKind", PLAN_KINDS),
        import_for_export_enabled=_boolean(source, "importForExportEnabled"),
        import_for_export_advisory_enabled=_boolean(
            source, "importForExportAdvisoryEnabled"
        ),
        created_at_utc=_timestamp(source, "createdAtUtc"),
        effective_at_utc=_timestamp(source, "effectiveAtUtc"),
        economics_assumptions=economics_assumptions,
        planned_energy_ledger=planned_energy_ledger,
        equipment_profile=equipment_profile,
        current_capacity=_number(source, "currentCapacity"),
        min_capacity=_number(source, "minCapacity"),
        target_capacity=_number(source, "targetCapacity"),
        low_price=_number(source, "lowPrice"),
        medium_price=_number(source, "mediumPrice"),
        battery_management_system_state=_bms_state(source, "batteryManagementSystemState"),
        should_import=should_import,
        should_use_grid=_boolean(source, "shouldUseGrid"),
        should_export=should_export,
        forecast_cadence_minutes=_optional_positive_integer(
            source, "forecastCadenceMinutes"
        ),
        total_cost=_number(source, "totalCost"),
        charging_cost=_number(source, "chargingCost"),
        saving=_number(source, "saving"),
        periods=periods,
    )


def _forecast_source(payload: Mapping[str, object]) -> Mapping[str, object]:
    """Return the schema-5 object without losing a valid top-level contract.

    Some deployed responses include a legacy ``Forecast`` companion beside
    the normalized schema-5 fields.  Prefer whichever candidate actually
    advertises ``schemaVersion`` so a legacy wrapper cannot hide the accepted
    contract.  The wrapper fallback keeps the parser compatible with the
    ``Forecast``/``forecast``/``forecastEntity`` response shapes.
    """
    if _has_schema_alias(payload) and _has_periods_alias(payload):
        return payload
    for key in ("Forecast", "forecast", "forecastEntity", "ForecastEntity"):
        candidate = payload.get(key)
        if (
            isinstance(candidate, Mapping)
            and _has_schema_alias(candidate)
            and _has_periods_alias(candidate)
        ):
            return candidate
    if _has_schema_alias(payload):
        return payload
    for key in ("Forecast", "forecast", "forecastEntity", "ForecastEntity"):
        candidate = payload.get(key)
        if isinstance(candidate, Mapping) and _has_schema_alias(candidate):
            return candidate
    for key in ("Forecast", "forecast", "forecastEntity", "ForecastEntity"):
        candidate = payload.get(key)
        if isinstance(candidate, Mapping):
            return candidate
    return payload


def _has_schema_alias(source: Mapping[str, object]) -> bool:
    return any(alias in source for alias in _aliases("schemaVersion"))


def _has_periods_alias(source: Mapping[str, object]) -> bool:
    return any(
        alias in source
        for alias in (*_aliases("periods"), "forecastPeriods", "ForecastPeriods")
    )


def _period(value: object, *, schema_version: int) -> Schema5Period:
    if not isinstance(value, Mapping):
        raise Schema5ForecastError("period must be an object")
    return Schema5Period(
        period=_integer(value, "period"),
        date=_timestamp(value, "date"),
        price=_number(value, "price"),
        should_import=_boolean(value, "shouldImport"),
        should_use_grid=_boolean(value, "shouldUseGrid"),
        should_export=_should_export(value, schema_version=schema_version),
        recommended_action=_text(value, "recommendedAction"),
        simulation_action=_text(value, "simulationAction"),
        executable_action=_text(value, "executableAction"),
        command_id=_required_optional_text(value, "commandId"),
        issued_at_utc=_required_optional_timestamp(value, "issuedAtUtc"),
        expires_at_utc=_required_optional_timestamp(value, "expiresAtUtc"),
        action_priority=_required_optional_integer(value, "actionPriority"),
        expected_import=_number(value, "expectedImport"),
        expected_export=_number(value, "expectedExport"),
        expected_start_soc=_number(value, "expectedStartSoc"),
        expected_end_soc=_number(value, "expectedEndSoc"),
        expected_cost=_number(value, "expectedCost"),
        expected_revenue=_number(value, "expectedRevenue"),
        expected_net_value=_number(value, "expectedNetValue"),
        amount=_number(value, "amount"),
        imported=_number(value, "imported"),
        exported=_number(value, "exported"),
        estimated_generation=_number(value, "estimatedGeneration"),
        used=_number(value, "used"),
        battery=_number(value, "battery"),
        battery_management_system_state=_bms_state(
            value, "batteryManagementSystemState"
        ),
        decision_trace=_decision_trace(value.get("decisionTrace")),
    )


def _decision_trace(value: object) -> Schema5DecisionTrace:
    if not isinstance(value, Mapping):
        raise Schema5ForecastError("decisionTrace must be an object")
    rejected = value.get("rejectedCandidateActions")
    if not isinstance(rejected, list) or not _safe_json_value(rejected):
        raise Schema5ForecastError(
            "rejectedCandidateActions must be a safe JSON list"
        )
    for candidate in rejected:
        if not isinstance(candidate, Mapping):
            raise Schema5ForecastError("rejectedCandidateActions must contain objects")
        _complete_mapping(candidate, "rejectedCandidateAction", _REJECTED_ACTION_FIELDS)
    return Schema5DecisionTrace(
        selected_action=_text(value, "selectedAction"),
        reason_code=_choice(value, "reasonCode", REASON_CODES),
        explanation=_text(value, "explanation"),
        rejected_candidate_actions=tuple(deepcopy(rejected)),
        import_rate=_number(value, "importRate"),
        export_rate=_number(value, "exportRate"),
        expected_import_kwh=_number(value, "expectedImportKwh"),
        expected_export_kwh=_number(value, "expectedExportKwh"),
        expected_start_soc_kwh=_number(value, "expectedStartSocKwh"),
        expected_end_soc_kwh=_number(value, "expectedEndSocKwh"),
        constraints=_complete_object(value, "constraints", _CONSTRAINT_FIELDS),
        economic_calculation=_complete_object(
            value, "economicCalculation", _ECONOMIC_CALCULATION_FIELDS
        ),
    )


def _text(source: Mapping[str, object], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value.strip():
        raise Schema5ForecastError(f"{key} must be non-empty text")
    return value


def _complete_object(
    source: Mapping[str, object], key: str, fields: tuple[str, ...]
) -> dict[str, object]:
    """Return one canonical nested contract object with every field present."""
    return _complete_mapping(_object(source, key), key, fields)


def _optional_complete_object(
    source: Mapping[str, object], key: str, fields: tuple[str, ...]
) -> dict[str, object] | None:
    """Validate an optional schema-5 nested object without inventing a value."""
    if key not in source or source[key] is None:
        return None
    return _complete_object(source, key, fields)


def _complete_mapping(
    value: Mapping[str, object], key: str, fields: tuple[str, ...]
) -> dict[str, object]:
    """Validate a nested canonical object that is already selected."""
    result = dict(value)
    missing = [field for field in fields if field not in result]
    if missing:
        raise Schema5ForecastError(
            f"{key} is missing required fields: {', '.join(missing)}"
        )
    return result


def _bms_state(source: Mapping[str, object], key: str) -> str | int:
    """Preserve Solar's enum representation instead of inventing a local label."""
    value = source.get(key)
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise Schema5ForecastError(f"{key} must be a string or integer enum")


def _required_optional_text(source: Mapping[str, object], key: str) -> str | None:
    """Read a contract field that must exist but may explicitly be null."""
    if key not in source:
        raise Schema5ForecastError(f"{key} must be present")
    if source.get(key) is None:
        return None
    return _text(source, key)


def _timestamp(source: Mapping[str, object], key: str) -> str:
    value = _text(source, key)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise Schema5ForecastError(f"{key} must be an ISO-8601 timestamp") from err
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Schema5ForecastError(f"{key} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _required_optional_timestamp(
    source: Mapping[str, object], key: str
) -> str | None:
    """Read a nullable timestamp whose property is mandatory in schema 5."""
    if key not in source:
        raise Schema5ForecastError(f"{key} must be present")
    if source.get(key) is None:
        return None
    return _timestamp(source, key)


def _number(source: Mapping[str, object], key: str) -> float:
    value = source.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Schema5ForecastError(f"{key} must be numeric")
    try:
        result = float(value)
    except OverflowError as err:
        raise Schema5ForecastError(f"{key} must be finite") from err
    if not math.isfinite(result):
        raise Schema5ForecastError(f"{key} must be finite")
    return result


def _integer(source: Mapping[str, object], key: str) -> int:
    value = source.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise Schema5ForecastError(f"{key} must be an integer")
    return value


def _required_optional_integer(source: Mapping[str, object], key: str) -> int | None:
    """Read a mandatory nullable integer contract field."""
    if key not in source:
        raise Schema5ForecastError(f"{key} must be present")
    if source.get(key) is None:
        return None
    return _integer(source, key)


def _positive_integer(source: Mapping[str, object], key: str) -> int:
    value = _integer(source, key)
    if value <= 0:
        raise Schema5ForecastError(f"{key} must be positive")
    return value


def _optional_positive_integer(source: Mapping[str, object], key: str) -> int | None:
    """Validate an optional positive integral schema field."""
    if key not in source or source[key] is None:
        return None
    return _positive_integer(source, key)


def _boolean(source: Mapping[str, object], key: str) -> bool:
    value = source.get(key)
    if not isinstance(value, bool):
        raise Schema5ForecastError(f"{key} must be boolean")
    return value


def _should_export(
    source: Mapping[str, object], *, schema_version: int
) -> bool | None:
    """Read the backend-owned export decision without locally inferring one."""
    if schema_version == LEGACY_SCHEMA_VERSION:
        return None
    return _boolean(source, "shouldExport")


def _choice(source: Mapping[str, object], key: str, choices: frozenset[str]) -> str:
    value = _text(source, key)
    if value not in choices:
        raise Schema5ForecastError(f"{key} is unsupported")
    return value


def _object(source: Mapping[str, object], key: str) -> dict[str, object]:
    value = source.get(key)
    if not isinstance(value, Mapping) or not _safe_json_value(value):
        raise Schema5ForecastError(f"{key} must be a safe JSON object")
    return deepcopy(dict(value))


def _safe_json_value(value: object) -> bool:
    """Accept JSON values only when they cannot carry transport secrets."""
    if isinstance(value, Mapping):
        return all(
            isinstance(key, str)
            and key.lower().replace("_", "").replace("-", "")
            not in _NORMALIZED_PROHIBITED_DIAGNOSTIC_KEYS
            and _safe_json_value(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return all(_safe_json_value(item) for item in value)
    return _json_value(value)


def _json_value(value: object) -> bool:
    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, (int, float)):
        if isinstance(value, bool):
            return False
        try:
            return math.isfinite(float(value))
        except OverflowError:
            return False
    if isinstance(value, Mapping):
        return all(isinstance(key, str) and _json_value(item) for key, item in value.items())
    if isinstance(value, list):
        return all(_json_value(item) for item in value)
    return False

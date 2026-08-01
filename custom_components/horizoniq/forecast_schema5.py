"""Strict, entry-local HorizonIQ schema-5 forecast diagnostics models."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import math


SCHEMA_VERSION = 5
# ``sandbox_replay`` remains readable for locally persisted direct-replay
# responses while Solar's schema-5 contract uses ``replay``.
PLAN_KINDS = frozenset({"live", "advisory", "replay", "sandbox_replay"})
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
    """Raised when a schema-5 forecast is incomplete or malformed."""


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
    """One complete schema-5 forecast period."""

    period: int
    date: str
    price: float
    should_import: bool
    should_use_grid: bool
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
    battery_management_system_state: str
    decision_trace: Schema5DecisionTrace

    def to_dict(self) -> dict[str, object]:
        """Return the canonical diagnostics shape for this period."""
        return {
            "period": self.period,
            "date": self.date,
            "price": self.price,
            "shouldImport": self.should_import,
            "shouldUseGrid": self.should_use_grid,
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
    """Complete normalized schema-5 plan retained only in entry-local memory."""

    schema_version: int
    plan_id: str
    plan_kind: str
    import_for_export_enabled: bool
    import_for_export_advisory_enabled: bool
    created_at_utc: str
    effective_at_utc: str
    economics_assumptions: dict[str, object]
    planned_energy_ledger: dict[str, object]
    equipment_profile: dict[str, object]
    current_capacity: float
    min_capacity: float
    target_capacity: float
    low_price: float
    medium_price: float
    battery_management_system_state: str
    should_import: bool
    should_use_grid: bool
    forecast_cadence_minutes: int
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
            "forecastCadenceMinutes": self.forecast_cadence_minutes,
            "totalCost": self.total_cost,
            "chargingCost": self.charging_cost,
            "saving": self.saving,
            "periods": [period.to_dict() for period in self.periods],
        }


def parse_schema5_forecast(payload: Mapping[str, object]) -> Schema5Forecast | None:
    """Parse a complete schema-5 forecast or reject it before any state changes."""
    if not isinstance(payload, Mapping):
        raise Schema5ForecastError("forecast payload must be an object")
    source = _forecast_source(payload)
    if "schemaVersion" not in source:
        return None
    if _integer(source, "schemaVersion") != SCHEMA_VERSION:
        raise Schema5ForecastError("Unsupported forecast schemaVersion")

    periods_value = source.get("periods")
    if not isinstance(periods_value, list):
        raise Schema5ForecastError("periods must be a list")
    periods = tuple(_period(item) for item in periods_value)
    return Schema5Forecast(
        schema_version=SCHEMA_VERSION,
        plan_id=_text(source, "planId"),
        plan_kind=_choice(source, "planKind", PLAN_KINDS),
        import_for_export_enabled=_boolean(source, "importForExportEnabled"),
        import_for_export_advisory_enabled=_boolean(
            source, "importForExportAdvisoryEnabled"
        ),
        created_at_utc=_timestamp(source, "createdAtUtc"),
        effective_at_utc=_timestamp(source, "effectiveAtUtc"),
        economics_assumptions=_object(source, "economicsAssumptions"),
        planned_energy_ledger=_object(source, "plannedEnergyLedger"),
        equipment_profile=_object(source, "equipmentProfile"),
        current_capacity=_number(source, "currentCapacity"),
        min_capacity=_number(source, "minCapacity"),
        target_capacity=_number(source, "targetCapacity"),
        low_price=_number(source, "lowPrice"),
        medium_price=_number(source, "mediumPrice"),
        battery_management_system_state=_text(source, "batteryManagementSystemState"),
        should_import=_boolean(source, "shouldImport"),
        should_use_grid=_boolean(source, "shouldUseGrid"),
        forecast_cadence_minutes=_positive_integer(source, "forecastCadenceMinutes"),
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
    if "schemaVersion" in payload and "periods" in payload:
        return payload
    for key in ("Forecast", "forecast", "forecastEntity"):
        candidate = payload.get(key)
        if (
            isinstance(candidate, Mapping)
            and "schemaVersion" in candidate
            and "periods" in candidate
        ):
            return candidate
    if "schemaVersion" in payload:
        return payload
    for key in ("Forecast", "forecast", "forecastEntity"):
        candidate = payload.get(key)
        if isinstance(candidate, Mapping) and "schemaVersion" in candidate:
            return candidate
    for key in ("Forecast", "forecast", "forecastEntity"):
        candidate = payload.get(key)
        if isinstance(candidate, Mapping):
            return candidate
    return payload


def _period(value: object) -> Schema5Period:
    if not isinstance(value, Mapping):
        raise Schema5ForecastError("period must be an object")
    return Schema5Period(
        period=_integer(value, "period"),
        date=_timestamp(value, "date"),
        price=_number(value, "price"),
        should_import=_boolean(value, "shouldImport"),
        should_use_grid=_boolean(value, "shouldUseGrid"),
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
        battery_management_system_state=_text(value, "batteryManagementSystemState"),
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
        constraints=_object(value, "constraints"),
        economic_calculation=_object(value, "economicCalculation"),
    )


def _text(source: Mapping[str, object], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value.strip():
        raise Schema5ForecastError(f"{key} must be non-empty text")
    return value


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


def _boolean(source: Mapping[str, object], key: str) -> bool:
    value = source.get(key)
    if not isinstance(value, bool):
        raise Schema5ForecastError(f"{key} must be boolean")
    return value


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

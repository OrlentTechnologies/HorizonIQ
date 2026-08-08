"""Strict Home Assistant-owned sandbox forecast control contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import math
from typing import Mapping
from uuid import UUID

from .forecast_schema5 import (
    SUPPORTED_SCHEMA_VERSIONS,
    Schema5ForecastError,
    parse_schema5_forecast,
)
from .models import DirectEquipmentProfile, DirectForecastPeriod, Forecast
from .simulation.models import BatteryConfig, Command, OperatingMode


_LIVE_PLAN_KIND = "live"
_REPLAY_PLAN_KIND = "sandbox_replay"
_HALF_HOUR = timedelta(minutes=30)
_LIVE_ACTIONS = {"charge_required", "use_grid", "import_for_export"}
_REPLAY_ACTIONS = _LIVE_ACTIONS | {
    "export_for_profit",
    "export_for_solar_headroom",
}

_NORMALIZED_TOP_LEVEL_FIELDS = {
    "schema_version": "schemaVersion",
    "plan_id": "planId",
    "plan_kind": "planKind",
    "created_at_utc": "createdAtUtc",
    "effective_at_utc": "effectiveAtUtc",
    "equipment_profile": "equipmentProfile",
    "forecast_cadence_minutes": "forecastCadenceMinutes",
    "registration_data": "registrationData",
}
_NORMALIZED_PERIOD_FIELDS = {
    "executable_action": "executableAction",
    "simulation_action": "simulationAction",
    "recommended_action": "recommendedAction",
    "command_id": "commandId",
    "issued_at_utc": "issuedAtUtc",
    "expires_at_utc": "expiresAtUtc",
    "action_priority": "actionPriority",
    "expected_import": "expectedImport",
    "expected_export": "expectedExport",
    "expected_start_soc": "expectedStartSoc",
    "expected_end_soc": "expectedEndSoc",
    "decision_trace": "decisionTrace",
}


@dataclass(frozen=True, slots=True)
class DirectCommand:
    """A validated direct action ready for local virtual-battery physics."""

    command: Command
    command_id: str | None
    plan_id: str
    action: str
    replay_key: str | None = None


class DirectForecastRejection(StrEnum):
    """Bounded reasons for refusing a typed direct forecast."""

    MODEL_UNAVAILABLE = "model_unavailable"
    SCHEMA_UNSUPPORTED = "schema_unsupported"
    PLAN_KIND_INVALID = "plan_kind_invalid"
    PROFILE_INVALID = "profile_invalid"
    CURRENT_PERIOD_MISSING = "current_period_missing"
    SIMULATION_ACTION_INVALID = "simulation_action_invalid"
    ACTION_INVALID = "action_invalid"
    COMMAND_METADATA_INVALID = "command_metadata_invalid"
    COMMAND_WINDOW_INVALID = "command_window_invalid"
    CAPABILITY_INVALID = "capability_invalid"
    PERIOD_DATA_INVALID = "period_data_invalid"
    OTHER_INVALID = "other_invalid"


@dataclass(frozen=True, slots=True)
class DirectForecastValidation:
    """Typed direct-forecast validation outcome for runtime observability."""

    command: DirectCommand | None
    rejection: DirectForecastRejection | None = None

    @property
    def is_valid(self) -> bool:
        return self.command is not None


def parse_live_command(
    forecast: Forecast | None,
    *,
    now_utc: datetime,
    config: BatteryConfig,
) -> DirectCommand:
    """Apply only the coordinator's typed live Forecast model."""
    if not isinstance(forecast, Forecast):
        raise ValueError("Direct forecast model is unavailable")
    _validate_live_forecast(forecast)
    period = _current_direct_period(forecast, now_utc)
    action = period.executable_action
    if period.simulation_action != "none":
        raise ValueError("Live forecast includes a simulation action")
    if action == "none":
        return DirectCommand(
            Command(OperatingMode.SELF_CONSUMPTION), None, forecast.plan_id, action
        )
    if action not in _LIVE_ACTIONS:
        raise ValueError("Forecast action is not executable for live control")
    _validate_direct_period_diagnostics(period)
    command_id = _uuid(period.command_id, "commandId")
    issued = _required_timestamp(period.issued_at_utc, "issuedAtUtc")
    expires = _required_timestamp(period.expires_at_utc, "expiresAtUtc")
    period_start = period.starts_at_utc
    if not issued <= now_utc < expires or expires != period_start + _HALF_HOUR:
        raise ValueError("Forecast command is stale or expires outside its period")
    priority = _required_int(period.action_priority, "actionPriority")
    expected_priority = {
        "charge_required": 1,
        "use_grid": 4,
        "import_for_export": 5,
    }[action]
    if priority != expected_priority or not _direct_capability(
        forecast.equipment_profile, action
    ):
        raise ValueError("Forecast action is unsupported by the returned profile")
    command = _direct_command_from_action(
        action=action,
        period=period,
        profile=forecast.equipment_profile,
        config=config,
        remaining_hours=(expires - now_utc).total_seconds() / 3600,
        issued_at_utc=issued,
        expires_at_utc=expires,
    )
    return DirectCommand(command, command_id, forecast.plan_id, action)


def validate_live_forecast(
    forecast: Forecast | None,
    *,
    now_utc: datetime,
    config: BatteryConfig,
) -> DirectForecastValidation:
    """Return a command or a bounded reason without exposing payload details."""
    try:
        return DirectForecastValidation(
            command=parse_live_command(forecast, now_utc=now_utc, config=config)
        )
    except ValueError as err:
        return DirectForecastValidation(
            command=None,
            rejection=_rejection_code(str(err)),
        )


def _rejection_code(message: str) -> DirectForecastRejection:
    if "model" in message:
        return DirectForecastRejection.MODEL_UNAVAILABLE
    if "schema" in message:
        return DirectForecastRejection.SCHEMA_UNSUPPORTED
    if "plan kind" in message:
        return DirectForecastRejection.PLAN_KIND_INVALID
    if "profile" in message:
        return DirectForecastRejection.PROFILE_INVALID
    if "current period" in message:
        return DirectForecastRejection.CURRENT_PERIOD_MISSING
    if "simulation action" in message:
        return DirectForecastRejection.SIMULATION_ACTION_INVALID
    if "action is not executable" in message:
        return DirectForecastRejection.ACTION_INVALID
    if any(field in message for field in ("commandId", "issuedAtUtc", "expiresAtUtc", "actionPriority")):
        return DirectForecastRejection.COMMAND_METADATA_INVALID
    if "stale" in message or "expires" in message or "duration" in message:
        return DirectForecastRejection.COMMAND_WINDOW_INVALID
    if "capability" in message or "unsupported" in message:
        return DirectForecastRejection.CAPABILITY_INVALID
    if any(field in message for field in ("expected", "decisionTrace", "recommendedAction")):
        return DirectForecastRejection.PERIOD_DATA_INVALID
    return DirectForecastRejection.OTHER_INVALID


def _validate_live_forecast(forecast: Forecast) -> None:
    if forecast.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError("Forecast schema is unsupported")
    if forecast.plan_kind != _LIVE_PLAN_KIND:
        raise ValueError("Forecast plan kind is invalid")
    _uuid(forecast.plan_id, "planId")
    if forecast.forecast_cadence_minutes <= 0:
        raise ValueError("forecastCadenceMinutes is invalid")
    _validate_direct_profile(forecast.equipment_profile)


def _validate_direct_profile(profile: DirectEquipmentProfile) -> None:
    if profile.version <= 0:
        raise ValueError("Forecast equipment profile version is invalid")
    for value in (
        profile.battery_capacity_wh,
        profile.maximum_battery_charge_power_watts,
        profile.maximum_battery_discharge_power_watts,
        profile.inverter_maximum_charge_power_watts,
        profile.inverter_maximum_discharge_power_watts,
        profile.maximum_grid_import_power_watts,
        profile.maximum_grid_export_power_watts,
    ):
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Forecast equipment profile limits are invalid")
    if not math.isfinite(profile.minimum_capacity_percentage) or not (
        0 <= profile.minimum_capacity_percentage <= 1
    ):
        raise ValueError("Forecast equipment profile reserve is invalid")


def _current_direct_period(
    forecast: Forecast, now_utc: datetime
) -> DirectForecastPeriod:
    for period in forecast.periods:
        if period.starts_at_utc <= now_utc < period.starts_at_utc + _HALF_HOUR:
            return period
    raise ValueError("Forecast has no current period")


def _validate_direct_period_diagnostics(period: DirectForecastPeriod) -> None:
    for value, name in (
        (period.expected_import_kwh, "expectedImport"),
        (period.expected_export_kwh, "expectedExport"),
        (period.expected_start_soc_kwh, "expectedStartSoc"),
        (period.expected_end_soc_kwh, "expectedEndSoc"),
    ):
        if value is None or not math.isfinite(value):
            raise ValueError(f"{name} is invalid")
    if period.decision_trace is None:
        raise ValueError("decisionTrace is invalid")
    _text(period.recommended_action, "recommendedAction")


def _direct_capability(profile: DirectEquipmentProfile, action: str) -> bool:
    return {
        "charge_required": profile.required_charging,
        "use_grid": profile.use_grid,
        "import_for_export": profile.import_for_export,
    }[action]


def _direct_command_from_action(
    *,
    action: str,
    period: DirectForecastPeriod,
    profile: DirectEquipmentProfile,
    config: BatteryConfig,
    remaining_hours: float,
    issued_at_utc: datetime,
    expires_at_utc: datetime,
) -> Command:
    if action == "use_grid":
        return Command(OperatingMode.GRID_SETPOINT, 0.0, issued_at_utc, expires_at_utc)
    energy_kwh = _required_energy(
        period.expected_import_kwh,
        "expectedImport",
    )
    if not math.isfinite(remaining_hours) or remaining_hours <= 0:
        raise ValueError("Forecast command duration is invalid")
    limit = min(
        config.max_charge_power_w,
        profile.maximum_battery_charge_power_watts,
        profile.inverter_maximum_charge_power_watts,
        profile.maximum_grid_import_power_watts,
    )
    return Command(
        OperatingMode.GRID_SETPOINT,
        min(energy_kwh * 1000 / remaining_hours, limit),
        issued_at_utc,
        expires_at_utc,
    )


def _required_timestamp(value: datetime | None, name: str) -> datetime:
    if value is None:
        raise ValueError(f"{name} is invalid")
    return value


def _required_int(value: int | None, name: str) -> int:
    if value is None:
        raise ValueError(f"{name} is invalid")
    return value


def _required_energy(value: float | None, name: str) -> float:
    if value is None or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} is invalid")
    return value


def parse_replay_command(
    payload: Mapping[str, object],
    *,
    virtual_now_utc: datetime,
    config: BatteryConfig,
) -> DirectCommand:
    """Return the one non-commanding replay action valid at virtual time."""
    payload = _canonical_contract(payload)
    plan_id, profile = _validate_plan(payload, expected_kind=_REPLAY_PLAN_KIND)
    period = _current_period(payload, virtual_now_utc)
    if period.get("executableAction") != "none":
        raise ValueError("Replay response must not include an executable action")
    for field in ("commandId", "issuedAtUtc", "expiresAtUtc", "actionPriority"):
        if period.get(field) is not None:
            raise ValueError("Replay response contains live command metadata")
    action = _text(period.get("simulationAction"), "simulationAction")
    if action not in _REPLAY_ACTIONS:
        raise ValueError("Replay simulation action is invalid")
    period_start = _utc_z(period.get("date"), "date")
    command = _command_from_action(
        action=action,
        period=period,
        profile=profile,
        config=config,
        remaining_hours=0.5,
        issued_at_utc=period_start,
        expires_at_utc=period_start + _HALF_HOUR,
        replay=True,
    )
    return DirectCommand(
        command,
        None,
        plan_id,
        action,
        f"{plan_id}:{period_start.isoformat()}:{action}",
    )


def _validate_plan(
    payload: Mapping[str, object], *, expected_kind: str
) -> tuple[str, Mapping[str, object]]:
    if (
        _integer(payload.get("schemaVersion"), "schemaVersion")
        not in SUPPORTED_SCHEMA_VERSIONS
    ):
        raise ValueError("Forecast schema is unsupported")
    if _text(payload.get("planKind"), "planKind") != expected_kind:
        raise ValueError("Forecast plan kind is invalid")
    plan_id = _uuid(payload.get("planId"), "planId")
    _utc_z(payload.get("createdAtUtc"), "createdAtUtc")
    _utc_z(payload.get("effectiveAtUtc"), "effectiveAtUtc")
    if _integer(payload.get("forecastCadenceMinutes"), "forecastCadenceMinutes") <= 0:
        raise ValueError("forecastCadenceMinutes is invalid")
    profile = payload.get("equipmentProfile")
    if not isinstance(profile, Mapping):
        raise ValueError("Forecast equipment profile is invalid")
    _validate_profile(profile)
    return plan_id, profile


def _current_period(
    payload: Mapping[str, object], now_utc: datetime) -> Mapping[str, object]:
    periods = payload.get("periods")
    if not isinstance(periods, list):
        raise ValueError("Forecast periods are invalid")
    for period in periods:
        if not isinstance(period, Mapping):
            raise ValueError("Forecast period is invalid")
        start = _utc_z(period.get("date"), "date")
        if start <= now_utc < start + _HALF_HOUR:
            return period
    raise ValueError("Forecast has no current period")


def _validate_profile(profile: Mapping[str, object]) -> None:
    if not _text(profile.get("id"), "equipmentProfile.id"):
        raise ValueError("Forecast equipment profile identity is invalid")
    if _integer(profile.get("version"), "equipmentProfile.version") <= 0:
        raise ValueError("Forecast equipment profile version is invalid")
    for field in ("source", "displayName", "controlAdapterId"):
        _text(profile.get(field), f"equipmentProfile.{field}")
    for field in (
        "batteryCapacityWh",
        "maximumBatteryChargePowerWatts",
        "maximumBatteryDischargePowerWatts",
        "inverterMaximumChargePowerWatts",
        "inverterMaximumDischargePowerWatts",
        "maximumGridImportPowerWatts",
        "maximumGridExportPowerWatts",
    ):
        if _positive(profile.get(field), field) <= 0:
            raise ValueError("Forecast equipment profile limits are invalid")
    reserve = _finite(profile.get("minimumCapacityPercentage"), "minimumCapacityPercentage")
    if not 0 <= reserve <= 1:
        raise ValueError("Forecast equipment profile reserve is invalid")
    if not isinstance(profile.get("productionExportEnabled"), bool):
        raise ValueError("Forecast export guard is invalid")
    if not _text(profile.get("safeFallbackId"), "safeFallbackId"):
        raise ValueError("Forecast fallback identity is invalid")
    controls = profile.get("supportedControl")
    if not isinstance(controls, Mapping) or set(controls) != {
        "requiredCharging", "useGrid", "importForExport", "profitableExport", "solarHeadroomExport"
    } or not all(isinstance(value, bool) for value in controls.values()):
        raise ValueError("Forecast control capabilities are invalid")


def _validate_period_diagnostics(period: Mapping[str, object]) -> None:
    """Require schema-5 diagnostics without treating them as commands."""
    _finite(period.get("expectedImport"), "expectedImport")
    _finite(period.get("expectedExport"), "expectedExport")
    _finite(period.get("expectedStartSoc"), "expectedStartSoc")
    _finite(period.get("expectedEndSoc"), "expectedEndSoc")
    if not isinstance(period.get("decisionTrace"), Mapping):
        raise ValueError("decisionTrace is invalid")
    _text(period.get("recommendedAction"), "recommendedAction")


def _validate_null_live_command_fields(period: Mapping[str, object]) -> None:
    """A no-op live action must not conceal an executable command."""
    for field in ("commandId", "issuedAtUtc", "expiresAtUtc", "actionPriority"):
        if period.get(field) is not None:
            raise ValueError("No-op forecast contains command metadata")


def _capability(
    profile: Mapping[str, object], action: str, *, replay: bool = False
) -> bool:
    controls = profile["supportedControl"]
    assert isinstance(controls, Mapping)
    key = {
        "charge_required": "requiredCharging",
        "use_grid": "useGrid",
        "import_for_export": "importForExport",
        "export_for_profit": "profitableExport",
        "export_for_solar_headroom": "solarHeadroomExport",
    }[action]
    return controls[key] is True and (
        replay or not action.startswith("export_") or profile["productionExportEnabled"] is True
    )


def _command_from_action(
    *, action: str, period: Mapping[str, object], profile: Mapping[str, object], config: BatteryConfig,
    remaining_hours: float, issued_at_utc: datetime, expires_at_utc: datetime,
    replay: bool = False,
) -> Command:
    if action == "use_grid":
        return Command(OperatingMode.GRID_SETPOINT, 0.0, issued_at_utc, expires_at_utc)
    if not _capability(profile, action, replay=replay):
        raise ValueError("Forecast action is unsupported by the returned profile")
    energy_key = "expectedImport" if action in {"charge_required", "import_for_export"} else "expectedExport"
    energy_kwh = _positive(period.get(energy_key), energy_key)
    if not math.isfinite(remaining_hours) or remaining_hours <= 0:
        raise ValueError("Forecast command duration is invalid")
    requested = energy_kwh * 1000 / remaining_hours
    if action.startswith("export_"):
        limit = min(config.max_discharge_power_w, _positive(profile.get("maximumBatteryDischargePowerWatts"), "maximumBatteryDischargePowerWatts"), _positive(profile.get("inverterMaximumDischargePowerWatts"), "inverterMaximumDischargePowerWatts"), _positive(profile.get("maximumGridExportPowerWatts"), "maximumGridExportPowerWatts"))
        requested = -min(requested, limit)
    else:
        limit = min(config.max_charge_power_w, _positive(profile.get("maximumBatteryChargePowerWatts"), "maximumBatteryChargePowerWatts"), _positive(profile.get("inverterMaximumChargePowerWatts"), "inverterMaximumChargePowerWatts"), _positive(profile.get("maximumGridImportPowerWatts"), "maximumGridImportPowerWatts"))
        requested = min(requested, limit)
    return Command(OperatingMode.GRID_SETPOINT, requested, issued_at_utc, expires_at_utc)


def _canonical_contract(payload: Mapping[str, object]) -> dict[str, object]:
    """Parse the same canonical schema-5/6 contract used by coordinator views."""
    try:
        forecast = parse_schema5_forecast(payload)
    except Schema5ForecastError as err:
        raise ValueError("Forecast schema is invalid") from err
    if forecast is None:
        raise ValueError("Forecast schema is unsupported")
    return forecast.to_dict()


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is invalid")
    return value.strip()


def _uuid(value: object, name: str) -> str:
    try:
        return str(UUID(_text(value, name)))
    except ValueError as err:
        raise ValueError(f"{name} is invalid") from err


def _utc_z(value: object, name: str) -> datetime:
    text = _text(value, name)
    if not text.endswith("Z"):
        raise ValueError(f"{name} must be UTC Z")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as err:
        raise ValueError(f"{name} is invalid") from err
    if parsed.tzinfo is None:
        raise ValueError(f"{name} is invalid")
    return parsed.astimezone(timezone.utc)


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} is invalid")
    return value


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} is invalid")
    return float(value)


def _positive(value: object, name: str) -> float:
    result = _finite(value, name)
    if result <= 0:
        raise ValueError(f"{name} is invalid")
    return result

"""Strict Home Assistant-owned sandbox forecast control contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
import math
from uuid import UUID

from .forecast_schema5 import (
    SUPPORTED_SCHEMA_VERSIONS,
)
from .models import (
    MAX_FORECAST_PERIOD_ENERGY_WH,
    DirectEquipmentProfile,
    DirectForecastPeriod,
    Forecast,
)
from .simulation.models import BatteryConfig, Command, OperatingMode


_LIVE_PLAN_KIND = "live"
_HALF_HOUR = timedelta(minutes=30)
_LIVE_ACTIONS = {"charge_required", "use_grid", "import_for_export"}
_VIRTUAL_EXPORT_ACTION = "export_for_profit"
_VIRTUAL_RECOMMENDATIONS = _LIVE_ACTIONS | {_VIRTUAL_EXPORT_ACTION}
_VIRTUAL_SAFE_RECOMMENDATIONS = {"none", "self_consumption"}


@dataclass(frozen=True, slots=True)
class DirectCommand:
    """A validated direct action ready for local virtual-battery physics."""

    command: Command
    command_id: str | None
    plan_id: str
    action: str


class DirectForecastRejection(StrEnum):
    """Bounded reasons for refusing a typed direct forecast."""

    MODEL_UNAVAILABLE = "model_unavailable"
    SCHEMA_UNSUPPORTED = "schema_unsupported"
    PLAN_KIND_INVALID = "plan_kind_invalid"
    PROFILE_INVALID = "profile_invalid"
    CURRENT_PERIOD_MISSING = "current_period_missing"
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
            command=parse_live_command(
                forecast,
                now_utc=now_utc,
                config=config,
            )
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
    if "action is not executable" in message:
        return DirectForecastRejection.ACTION_INVALID
    if any(field in message for field in ("commandId", "issuedAtUtc", "expiresAtUtc")):
        return DirectForecastRejection.COMMAND_METADATA_INVALID
    if "stale" in message or "expires" in message or "duration" in message:
        return DirectForecastRejection.COMMAND_WINDOW_INVALID
    if "capability" in message or "unsupported" in message:
        return DirectForecastRejection.CAPABILITY_INVALID
    if any(
        field in message
        for field in (
            "expected",
            "estimatedGeneration",
            "decisionTrace",
            "recommendedAction",
        )
    ):
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


def validate_period_generation(period: DirectForecastPeriod) -> float:
    """Return the safe Wh solar estimate associated with a direct period."""
    generation = period.estimated_generation_wh
    if not (
        math.isfinite(generation)
        and 0 <= generation <= MAX_FORECAST_PERIOD_ENERGY_WH
    ):
        raise ValueError("estimatedGeneration is invalid")
    return generation


def parse_virtual_recommendation(
    forecast: Forecast | None,
    *,
    now_utc: datetime,
    config: BatteryConfig,
) -> DirectCommand:
    """Interpret an accepted generic recommendation for local virtual physics.

    This deliberately does not use the production executable-action or
    adapter-capability fields. Callers must establish Sandbox Virtual authority
    before using this local-only interpretation.
    """
    if not isinstance(forecast, Forecast):
        raise ValueError("Direct forecast model is unavailable")
    _validate_live_forecast(forecast)
    if forecast.created_at_utc > now_utc or forecast.effective_at_utc > now_utc:
        raise ValueError("Forecast is stale or not yet effective")
    period = _current_direct_period(forecast, now_utc)
    validate_period_generation(period)
    _validate_direct_period_diagnostics(period)
    action = _text(period.recommended_action, "recommendedAction")
    expires = period.starts_at_utc + _HALF_HOUR
    if now_utc >= expires:
        raise ValueError("Forecast is stale or expires outside its period")
    if period.issued_at_utc is not None or period.expires_at_utc is not None:
        if (
            period.issued_at_utc is None
            or period.expires_at_utc is None
            or not period.issued_at_utc <= now_utc < period.expires_at_utc
            or period.expires_at_utc != expires
        ):
            raise ValueError("Forecast is stale or expires outside its period")
    if action in _VIRTUAL_SAFE_RECOMMENDATIONS:
        return DirectCommand(
            Command(OperatingMode.SELF_CONSUMPTION), None, forecast.plan_id, action
        )
    if action not in _VIRTUAL_RECOMMENDATIONS:
        raise ValueError("recommendedAction is unsupported for local virtual control")
    command = _direct_command_from_action(
        action=action,
        period=period,
        profile=forecast.equipment_profile,
        config=config,
        remaining_hours=(expires - now_utc).total_seconds() / 3600,
        issued_at_utc=period.starts_at_utc,
        expires_at_utc=expires,
    )
    return DirectCommand(command, None, forecast.plan_id, action)


def validate_virtual_recommendation(
    forecast: Forecast | None,
    *,
    now_utc: datetime,
    config: BatteryConfig,
) -> DirectForecastValidation:
    """Return a bounded local-virtual recommendation validation outcome."""
    try:
        return DirectForecastValidation(
            command=parse_virtual_recommendation(
                forecast, now_utc=now_utc, config=config
            )
        )
    except ValueError as err:
        return DirectForecastValidation(
            command=None,
            rejection=_rejection_code(str(err)),
        )


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
        return Command(OperatingMode.GRID_PRESERVATION, None, issued_at_utc, expires_at_utc)
    energy_kwh = _required_energy(
        period.expected_export_kwh
        if action == _VIRTUAL_EXPORT_ACTION
        else period.expected_import_kwh,
        "expectedExport" if action == _VIRTUAL_EXPORT_ACTION else "expectedImport",
    )
    if not math.isfinite(remaining_hours) or remaining_hours <= 0:
        raise ValueError("Forecast command duration is invalid")
    if action == _VIRTUAL_EXPORT_ACTION:
        limit = min(
            config.max_discharge_power_w,
            profile.maximum_battery_discharge_power_watts,
            profile.inverter_maximum_discharge_power_watts,
            profile.maximum_grid_export_power_watts,
        )
        return Command(
            OperatingMode.GRID_SETPOINT,
            -min(energy_kwh * 1000 / remaining_hours, limit),
            issued_at_utc,
            expires_at_utc,
        )
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


def _required_energy(value: float | None, name: str) -> float:
    if value is None or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} is invalid")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is invalid")
    return value.strip()


def _uuid(value: object, name: str) -> str:
    try:
        return str(UUID(_text(value, name)))
    except ValueError as err:
        raise ValueError(f"{name} is invalid") from err

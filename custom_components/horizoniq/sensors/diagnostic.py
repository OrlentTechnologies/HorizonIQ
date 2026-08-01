"""Bounded, safe forecast diagnostics."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import EntityCategory

from ..const import SANDBOX_ENVIRONMENT
from ..entity import HorizonIQEntity
from ..entity_helpers import (
    build_unique_id,
    entity_name,
    environment_label,
    normalized_environment,
)
from ..forecast_schema5 import Schema5Forecast
from ..models import HorizonIQSnapshot

_MAX_DIAGNOSTIC_TEXT_LENGTH = 512
_SENSITIVE_TEXT_MARKERS = (
    "api_key",
    "api-key",
    "api key",
    "apikey",
    "code=",
    "credential",
    "function_key",
    "function-key",
    "functionkey",
    "header",
    "http_headers",
    "http-headers",
    "key=",
    "privatekey",
    "publickey",
    "token",
    "secret",
    "password",
    "registrationdata",
    "registration_data",
    "registration-data",
    "registration data",
)


class ForecastDetailSensor(HorizonIQEntity, SensorEntity):
    """Expose a bounded summary plus the complete live forecast horizon."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _unrecorded_attributes = frozenset({"forecast"})

    def __init__(self, coordinator, entry_id: str, environment: str) -> None:
        super().__init__(coordinator)
        self._environment = normalized_environment(environment)
        self._attr_name = entity_name(self._environment, "Forecast Diagnostics")
        self._attr_unique_id = build_unique_id(
            self._environment, entry_id, "forecast_diagnostics"
        )

    @property
    def available(self) -> bool:
        """Keep the last accepted live horizon visible when refresh is stale."""
        available = super().available
        if available or self._environment == SANDBOX_ENVIRONMENT:
            return available
        return _accepted_forecast(self.coordinator, self.snapshot) is not None

    @property
    def native_value(self) -> int:
        """Return the number of accepted forecast periods."""
        snapshot = self.snapshot
        forecast = _accepted_forecast(self.coordinator, snapshot)
        if forecast is not None:
            return len(forecast.periods)
        return len(snapshot.forecast_periods) if snapshot is not None else 0

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the small, safe forecast summary shown in Home Assistant."""
        snapshot = self.snapshot
        schema5_forecast = _accepted_forecast(self.coordinator, snapshot)
        attrs: dict[str, object] = {
            "period_count": _period_count(self.coordinator, snapshot),
        }
        _add_text_attribute(
            attrs,
            "health",
            _health(
                self.coordinator.last_update_success,
                snapshot,
                schema5_forecast,
            ),
        )
        _add_text_attribute(
            attrs,
            "environment",
            environment_label(self._environment),
        )
        if schema5_forecast is not None:
            _add_text_attribute(attrs, "plan_id", schema5_forecast.plan_id)
            _add_text_attribute(attrs, "plan_kind", schema5_forecast.plan_kind)
            attrs["stale"] = schema5_forecast.stale
            # Recorder excludes this one attribute through the supported HA
            # ``state_info["unrecorded_attributes"]`` API.  Do not truncate it
            # here: Developer Tools and ``hass.states`` must retain the full
            # accepted schema-5 horizon.
            attrs["forecast"] = schema5_forecast.to_dict()
        if snapshot is None:
            _add_text_attribute(
                attrs,
                "last_error",
                getattr(self.coordinator, "last_exception", None),
            )
            return attrs

        forecast = snapshot.forecast
        _add_text_attribute(
            attrs,
            "selected_action",
            _selected_action(snapshot, schema5_forecast),
        )
        _add_text_attribute(
            attrs, "calculated_on_utc", forecast.get("calculated_on_utc")
        )
        _add_text_attribute(
            attrs,
            "created_at_utc",
            forecast.get("created_at_utc")
            or (
                schema5_forecast.created_at_utc
                if schema5_forecast is not None
                else None
            ),
        )
        _add_text_attribute(
            attrs,
            "effective_at_utc",
            forecast.get("effective_at_utc")
            or (
                schema5_forecast.effective_at_utc
                if schema5_forecast is not None
                else None
            ),
        )
        _add_text_attribute(
            attrs,
            "reason",
            forecast.get("authorization_message")
            or snapshot.trial.get("authorization_message"),
        )
        _add_text_attribute(
            attrs,
            "last_error",
            getattr(self.coordinator, "last_exception", None),
        )
        return attrs


def _accepted_forecast(
    coordinator: object, snapshot: HorizonIQSnapshot | None
) -> Schema5Forecast | None:
    """Read the one entry-owned accepted forecast used by every consumer."""
    forecast = getattr(coordinator, "last_forecast", None)
    if isinstance(forecast, Schema5Forecast):
        return forecast
    forecast = getattr(coordinator, "schema5_forecast", None)
    if isinstance(forecast, Schema5Forecast):
        return forecast
    if snapshot is not None and isinstance(snapshot.schema5_forecast, Schema5Forecast):
        return snapshot.schema5_forecast
    return None


def _period_count(coordinator: object, snapshot: HorizonIQSnapshot | None) -> int:
    """Return the accepted horizon length, falling back to legacy periods."""
    forecast = _accepted_forecast(coordinator, snapshot)
    if forecast is not None:
        return len(forecast.periods)
    return len(snapshot.forecast_periods) if snapshot is not None else 0


def _selected_action(
    snapshot: HorizonIQSnapshot,
    accepted: Schema5Forecast | None = None,
) -> str | None:
    """Return one current action from the accepted entry-owned forecast."""
    if accepted is not None:
        action_field = {
            "live": "executable_action",
            "advisory": "recommended_action",
            "replay": "simulation_action",
            "sandbox_replay": "simulation_action",
        }[accepted.plan_kind]
        for period in accepted.periods:
            action = getattr(period, action_field)
            if action:
                return _friendly_enum(action)

    direct_forecast = snapshot.direct_forecast
    if direct_forecast is not None:
        for period in direct_forecast.periods:
            if period.executable_action:
                return _friendly_enum(period.executable_action)

    for period in snapshot.forecast_periods:
        action = period.get("executable_action") or period.get("recommended_action")
        if action:
            return _friendly_enum(str(action))
    return None


def _health(
    last_update_success: bool,
    snapshot: HorizonIQSnapshot | None,
    accepted: Schema5Forecast | None = None,
) -> str:
    """Return the concise health value for the bounded diagnostics summary."""
    # An accepted empty horizon or a retained last-good horizon must never be
    # masked by a generic authorization status from the legacy snapshot.
    if accepted is not None:
        if accepted.stale:
            return "Stale"
        if not accepted.periods:
            return "Unavailable"
        return "Healthy" if last_update_success else "Unavailable"
    if snapshot is not None:
        authorization_status = (
            snapshot.trial.get("authorization_status")
            or snapshot.forecast.get("authorization_status")
        )
        if authorization_status:
            return str(authorization_status).replace("_", " ").title()
    return "Healthy" if last_update_success else "Unavailable"


def _add_text_attribute(attrs: dict[str, object], key: str, value: object) -> None:
    """Add one bounded, credential-safe diagnostic value."""
    if value is None:
        return
    text = str(value).strip()
    if not text:
        return
    lowered = text.lower()
    if any(marker in lowered for marker in _SENSITIVE_TEXT_MARKERS):
        attrs[key] = "REDACTED"
        return
    attrs[key] = text[:_MAX_DIAGNOSTIC_TEXT_LENGTH]


def _friendly_enum(value: str) -> str:
    """Return a readable label for a machine-readable forecast action."""
    return value.replace("_", " ").replace("-", " ").title()

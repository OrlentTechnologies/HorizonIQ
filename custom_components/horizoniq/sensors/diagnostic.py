"""Bounded, safe forecast diagnostics."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import EntityCategory

from ..entity import HorizonIQEntity
from ..entity_helpers import (
    build_unique_id,
    entity_name,
    environment_label,
    normalized_environment,
)
from ..models import HorizonIQSnapshot

_MAX_DIAGNOSTIC_TEXT_LENGTH = 512
_SENSITIVE_TEXT_MARKERS = (
    "api_key",
    "apikey",
    "code=",
    "token",
    "secret",
    "password",
    "registrationdata",
    "registration_data",
)


class ForecastDetailSensor(HorizonIQEntity, SensorEntity):
    """Expose a compact forecast summary without retaining payload data."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _unrecorded_attributes = frozenset({"reason", "last_error"})

    def __init__(self, coordinator, entry_id: str, environment: str) -> None:
        super().__init__(coordinator)
        self._environment = normalized_environment(environment)
        self._attr_name = entity_name(self._environment, "Forecast Diagnostics")
        self._attr_unique_id = build_unique_id(
            self._environment, entry_id, "forecast_diagnostics"
        )

    @property
    def native_value(self) -> int:
        """Return the number of forecast periods, including an empty default."""
        snapshot = self.snapshot
        return len(snapshot.forecast_periods) if snapshot is not None else 0

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the small, safe forecast summary shown in Home Assistant."""
        snapshot = self.snapshot
        attrs: dict[str, object] = {
            "environment": environment_label(self._environment),
            "health": _health(self.coordinator.last_update_success, snapshot),
            "period_count": len(snapshot.forecast_periods) if snapshot is not None else 0,
        }
        if snapshot is None:
            _add_text_attribute(
                attrs,
                "last_error",
                getattr(self.coordinator, "last_exception", None),
            )
            return attrs

        forecast = snapshot.forecast
        _add_text_attribute(attrs, "selected_action", _selected_action(snapshot))
        for key in ("calculated_on_utc", "created_at_utc", "effective_at_utc"):
            _add_text_attribute(attrs, key, forecast.get(key))
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


def _selected_action(snapshot: HorizonIQSnapshot) -> str | None:
    """Return one current action without retaining the forecast period list."""
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


def _health(last_update_success: bool, snapshot: HorizonIQSnapshot | None) -> str:
    """Return the concise health value for the bounded diagnostics summary."""
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

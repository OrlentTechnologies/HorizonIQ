from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import EntityCategory

from ..entity import MeshSolarEntity
from ..entity_helpers import (
    build_unique_id,
    entity_name,
    environment_label,
    normalized_environment,
)

_REDACTED = "REDACTED"
_SENSITIVE_KEY_PARTS = ("password", "secret", "token", "function_key")
_SENSITIVE_EXACT_KEYS = {
    "api_key",
    "apikey",
    "code",
    "forecastfunctionkey",
    "forecast_function_key",
    "registrationdata",
    "registration_data",
}
_URL_KEY_PARTS = ("endpoint", "url")
_SENSITIVE_QUERY_PARAMETERS = {"code"}


class ForecastDetailSensor(MeshSolarEntity, SensorEntity):
    """Expose normalized forecast detail for diagnostics."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry_id: str, environment: str) -> None:
        super().__init__(coordinator)
        self._environment = normalized_environment(environment)
        self._attr_name = entity_name(self._environment, "Forecast Diagnostics")
        self._attr_unique_id = build_unique_id(
            self._environment, entry_id, "forecast_diagnostics"
        )

    @property
    def native_value(self) -> int | None:
        """Return the number of forecast periods in the current snapshot."""
        snapshot = self.snapshot
        if snapshot is None:
            return None
        return len(snapshot.forecast_periods)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return normalized diagnostic attributes."""
        attrs: dict[str, object] = {
            "environment": environment_label(self._environment),
        }

        snapshot = self.snapshot
        if snapshot is None:
            return attrs

        periods_payload = [
            _period_diagnostics_payload(period) for period in snapshot.forecast_periods
        ]
        attrs["period_count"] = len(periods_payload)

        forecast = _diagnostics_safe_payload(snapshot.forecast)
        if forecast:
            if periods_payload:
                forecast["periods"] = periods_payload
            else:
                forecast_periods = forecast.get("periods")
                if isinstance(forecast_periods, list):
                    forecast["periods"] = [
                        _period_diagnostics_payload(period)
                        if isinstance(period, Mapping)
                        else period
                        for period in forecast_periods
                    ]
            attrs["forecast"] = forecast
        if snapshot.trial:
            trial = _diagnostics_safe_payload(snapshot.trial)
            status = trial.get("status")
            if status is not None:
                attrs["trial_status"] = status
            authorization_status = trial.get("authorization_status")
            if authorization_status is not None:
                attrs["authorization_status"] = authorization_status
            authorization_status_code = trial.get("authorization_status_code")
            if authorization_status_code is not None:
                attrs["authorization_status_code"] = authorization_status_code
            attrs["trial"] = trial
        if snapshot.registration:
            attrs["registration"] = _diagnostics_safe_payload(snapshot.registration)

        return attrs


def _period_diagnostics_payload(period: Mapping[str, object]) -> dict[str, object]:
    """Return the diagnostics-safe period payload without history details."""
    return {
        key: _diagnostics_safe_value(key, value)
        for key, value in period.items()
        if str(key).lower() != "history"
    }


def _diagnostics_safe_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Return a diagnostics payload with sensitive trial binding values redacted."""
    return {
        key: _diagnostics_safe_value(key, value)
        for key, value in payload.items()
    }


def _diagnostics_safe_value(key: object, value: object) -> object:
    key_text = str(key)
    if _is_sensitive_diagnostics_key(key_text):
        return _REDACTED
    if isinstance(value, str):
        return _diagnostics_safe_string(key_text, value)
    return _diagnostics_safe_object(value)


def _diagnostics_safe_object(value: object) -> object:
    if isinstance(value, Mapping):
        return _diagnostics_safe_payload(value)
    if isinstance(value, list):
        return [_diagnostics_safe_object(item) for item in value]
    return deepcopy(value)


def _is_sensitive_diagnostics_key(key: str) -> bool:
    normalized = key.replace("-", "_").lower()
    collapsed = normalized.replace("_", "")
    if normalized in _SENSITIVE_EXACT_KEYS or collapsed in _SENSITIVE_EXACT_KEYS:
        return True
    if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
        return True

    return collapsed.endswith("deviceid")


def _diagnostics_safe_string(key: str, value: str) -> str:
    normalized = key.replace("-", "_").lower()
    if not any(part in normalized for part in _URL_KEY_PARTS):
        return value

    parsed = urlparse(value)
    if not parsed.query:
        return value

    query = [
        (name, _REDACTED if name.lower() in _SENSITIVE_QUERY_PARAMETERS else val)
        for name, val in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

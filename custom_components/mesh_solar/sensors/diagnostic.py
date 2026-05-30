from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import EntityCategory

from ..entity import MeshSolarEntity
from ..entity_helpers import (
    build_unique_id,
    display_suffix,
    environment_label,
    normalized_environment,
)

_REDACTED = "REDACTED"
_SENSITIVE_KEY_PARTS = ("password", "secret", "token")


class ForecastDetailSensor(MeshSolarEntity, SensorEntity):
    """Expose normalized forecast detail for diagnostics."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry_id: str, environment: str) -> None:
        super().__init__(coordinator)
        self._environment = normalized_environment(environment)
        self._attr_name = (
            f"Mesh Solar Forecast Diagnostics{display_suffix(self._environment)}"
        )
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
    if _is_sensitive_diagnostics_key(str(key)):
        return _REDACTED
    return _diagnostics_safe_object(value)


def _diagnostics_safe_object(value: object) -> object:
    if isinstance(value, Mapping):
        return _diagnostics_safe_payload(value)
    if isinstance(value, list):
        return [_diagnostics_safe_object(item) for item in value]
    return deepcopy(value)


def _is_sensitive_diagnostics_key(key: str) -> bool:
    normalized = key.replace("-", "_").lower()
    if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
        return True

    collapsed = normalized.replace("_", "")
    return collapsed.endswith("deviceid")

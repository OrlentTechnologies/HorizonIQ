from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import EntityCategory

from ..entity import MeshSolarEntity
from ..entity_helpers import (
    build_unique_id,
    display_suffix,
    environment_label,
    normalized_environment,
)


class TrialStatusSensor(MeshSolarEntity, SensorEntity):
    """Expose app trial state returned by the forecast endpoint."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry_id: str, environment: str) -> None:
        super().__init__(coordinator)
        self._environment = normalized_environment(environment)
        self._attr_name = f"Mesh Solar Trial Status{display_suffix(self._environment)}"
        self._attr_unique_id = build_unique_id(
            self._environment, entry_id, "trial_status"
        )

    @property
    def available(self) -> bool:
        """Return whether trial state can be shown."""
        return super().available or bool(self._trial)

    @property
    def native_value(self) -> str | None:
        """Return the best trial status string for the current forecast."""
        trial = self._trial
        if not trial:
            return None

        status = _text_value(trial.get("status"))
        if status is not None:
            return status

        authorization_status = _text_value(trial.get("authorization_status"))
        if authorization_status is not None:
            return authorization_status

        if trial.get("is_active") is True:
            return "active"
        if trial.get("is_eligible") is True:
            return "eligible"
        if trial.get("has_trial") is False:
            return "none"
        if trial.get("has_trial") is True:
            return "available"
        return None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return trial details as diagnostic attributes."""
        attrs: dict[str, object] = {"environment": environment_label(self._environment)}
        trial = self._trial
        if not trial:
            return attrs

        _add_attr(attrs, "has_trial", trial.get("has_trial"))
        _add_attr(attrs, "is_active", trial.get("is_active"))
        _add_attr(attrs, "is_eligible", trial.get("is_eligible"))
        _add_attr(attrs, "status", trial.get("status"))
        _add_attr(attrs, "starts_on_utc", trial.get("starts_on_utc"))
        _add_attr(attrs, "expires_on_utc", trial.get("expires_on_utc"))
        _add_attr(
            attrs,
            "forecast_cadence_minutes",
            trial.get("forecast_cadence_minutes"),
        )
        _add_attr(attrs, "device_display_name", trial.get("device_display_name"))
        _add_attr(attrs, "authorization_status", trial.get("authorization_status"))
        _add_attr(
            attrs,
            "authorization_status_code",
            trial.get("authorization_status_code"),
        )
        _add_attr(attrs, "authorization_message", trial.get("authorization_message"))
        return attrs

    @property
    def _trial(self) -> dict[str, object]:
        snapshot = self.snapshot
        if snapshot is None:
            return {}
        if snapshot.trial:
            return snapshot.trial

        forecast = snapshot.forecast
        trial: dict[str, object] = {}
        _add_attr(trial, "has_trial", forecast.get("trial_has_trial"))
        _add_attr(trial, "is_active", forecast.get("trial_is_active"))
        _add_attr(trial, "is_eligible", forecast.get("trial_is_eligible"))
        _add_attr(trial, "status", forecast.get("trial_status"))
        _add_attr(trial, "starts_on_utc", forecast.get("trial_starts_on_utc"))
        _add_attr(trial, "expires_on_utc", forecast.get("trial_expires_on_utc"))
        _add_attr(
            trial,
            "forecast_cadence_minutes",
            forecast.get("trial_forecast_cadence_minutes"),
        )
        _add_attr(
            trial,
            "device_display_name",
            forecast.get("trial_device_display_name"),
        )
        _add_attr(trial, "authorization_status", forecast.get("authorization_status"))
        _add_attr(
            trial,
            "authorization_status_code",
            forecast.get("authorization_status_code"),
        )
        _add_attr(trial, "authorization_message", forecast.get("authorization_message"))
        return trial


def _add_attr(attrs: dict[str, object], key: str, value: object) -> None:
    if value is None:
        return
    if isinstance(value, str) and not value.strip():
        return
    attrs[key] = value


def _text_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    return candidate or None

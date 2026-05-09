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
        if snapshot is None or not snapshot.forecast_periods:
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

        forecast = deepcopy(snapshot.forecast)
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
        if snapshot.registration:
            attrs["registration"] = deepcopy(snapshot.registration)

        return attrs


def _period_diagnostics_payload(period: Mapping[str, object]) -> dict[str, object]:
    """Return the diagnostics-safe period payload without history details."""
    return {
        key: value
        for key, value in period.items()
        if str(key).lower() != "history"
    }

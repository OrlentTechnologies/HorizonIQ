from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfTime

from ..entity import HorizonIQEntity
from ..entity_helpers import (
    build_unique_id,
    entity_name,
    environment_label,
    normalized_environment,
)


class ForecastCadenceSensor(HorizonIQEntity, SensorEntity):
    """Expose the current backend polling cadence in minutes."""

    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(self, coordinator, entry_id: str, environment: str) -> None:
        super().__init__(coordinator)
        self._environment = normalized_environment(environment)
        self._attr_name = entity_name(self._environment, "Forecast Cadence")
        self._attr_unique_id = build_unique_id(
            self._environment, entry_id, "forecast_cadence"
        )

    @property
    def native_value(self) -> int | None:
        """Return the current cadence in minutes."""
        snapshot = self.snapshot
        if snapshot is not None and snapshot.forecast_cadence_minutes is not None:
            return snapshot.forecast_cadence_minutes
        if getattr(self.coordinator, "forecast_cadence_minutes", None) is not None:
            return getattr(self.coordinator, "forecast_cadence_minutes")
        return getattr(self.coordinator, "effective_forecast_cadence_minutes", None)

    @property
    def extra_state_attributes(self) -> dict[str, str | int]:
        """Return diagnostic attributes."""
        return {
            "environment": environment_label(self._environment),
            "effective_poll_interval_minutes": getattr(
                self.coordinator,
                "effective_forecast_cadence_minutes",
                None,
            ),
        }

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from ..const import DEFAULT_ENVIRONMENT, DOMAIN
from ..entity import HorizonIQEntity
from ..entity_helpers import (
    build_unique_id,
    entity_name,
    environment_label,
    normalized_environment,
)
from ..forecast_schema5 import (
    Schema5Forecast,
    Schema5Period,
    select_current_schema5_period,
)
from ..sandbox_runtime import HorizonIQEntryRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HorizonIQ binary sensors."""
    runtime: HorizonIQEntryRuntime = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = runtime.coordinator
    environment = normalized_environment(
        getattr(coordinator, "environment", DEFAULT_ENVIRONMENT)
    )

    async_add_entities(
        [
            ImportSensor(coordinator, config_entry.entry_id, environment),
            ExportSensor(
                coordinator,
                config_entry.entry_id,
                environment,
                runtime=runtime if runtime.is_sandbox_configured else None,
            ),
        ]
    )


class ImportSensor(HorizonIQEntity, BinarySensorEntity):
    """Expose the normalized import recommendation."""

    def __init__(self, coordinator, entry_id: str, environment: str) -> None:
        super().__init__(coordinator)
        self._environment = normalized_environment(environment)
        self._attr_name = entity_name(self._environment, "Import")
        self._attr_unique_id = build_unique_id(self._environment, entry_id, "import")

    @property
    def is_on(self) -> bool | None:
        """Return whether import is currently recommended."""
        snapshot = self.snapshot
        if snapshot is None:
            return None
        return snapshot.should_import

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return diagnostic attributes."""
        return {"environment": environment_label(self._environment)}


class ExportSensor(HorizonIQEntity, BinarySensorEntity):
    """Expose the backend-owned current-period export recommendation."""

    def __init__(
        self,
        coordinator,
        entry_id: str,
        environment: str,
        *,
        runtime: HorizonIQEntryRuntime | None = None,
        now_utc: Callable[[], datetime] = dt_util.utcnow,
    ) -> None:
        super().__init__(coordinator)
        self._environment = normalized_environment(environment)
        self._runtime = runtime
        self._now_utc = now_utc
        self._attr_name = entity_name(self._environment, "Export")
        self._attr_unique_id = build_unique_id(self._environment, entry_id, "export")
        self._remove_listener = (
            runtime.add_listener(self.async_write_ha_state)
            if runtime is not None
            else None
        )

    @property
    def is_on(self) -> bool | None:
        """Return whether export is currently recommended."""
        snapshot = self.snapshot
        if snapshot is None:
            return None
        return snapshot.should_export

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the bounded source evidence for the current export decision."""
        forecast = self._forecast
        period = select_current_schema5_period(forecast, self._current_time_utc())
        current_action: str | None = None
        expected_export_kwh: float | None = None
        executable = False
        if forecast is not None and period is not None:
            current_action = self._current_action(period, forecast)
            expected_export_kwh = period.expected_export
            executable = period.executable_action == "export_for_profit"
        return {
            "environment": environment_label(self._environment),
            "plan_kind": forecast.plan_kind if forecast is not None else None,
            "current_action": current_action,
            "expected_export_kwh": expected_export_kwh,
            "executable": executable,
        }

    @property
    def _forecast(self) -> Schema5Forecast | None:
        """Return the coordinator-owned accepted schema-5 forecast only."""
        forecast = getattr(self.coordinator, "last_forecast", None)
        if not isinstance(forecast, Schema5Forecast):
            forecast = getattr(self.coordinator, "schema5_forecast", None)
        if not isinstance(forecast, Schema5Forecast):
            snapshot = getattr(self.coordinator, "data", None)
            forecast = getattr(snapshot, "schema5_forecast", None)
        return forecast if isinstance(forecast, Schema5Forecast) else None

    def _current_time_utc(self) -> datetime | None:
        """Use entry-local virtual/replay time, otherwise the coordinator wall clock."""
        if self._runtime is not None:
            return self._runtime.virtual_time_utc
        return self._now_utc()

    def _current_action(
        self,
        period: Schema5Period,
        forecast: Schema5Forecast,
    ) -> str:
        """Expose the plan's current action only as bounded diagnostics."""
        if forecast.plan_kind == "sandbox_replay":
            return period.simulation_action
        return period.recommended_action

    async def async_will_remove_from_hass(self) -> None:
        """Release the optional entry-local runtime listener."""
        if self._remove_listener is not None:
            self._remove_listener()
        await super().async_will_remove_from_hass()

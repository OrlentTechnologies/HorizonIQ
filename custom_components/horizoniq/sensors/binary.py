from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_utc_time
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
    PLAN_KINDS,
    SCHEMA5_PERIOD_DURATION,
    SUPPORTED_SCHEMA_VERSIONS,
    Schema5Forecast,
    Schema5Period,
    select_current_schema5_period,
)
from ..models import ForecastFreshness, HorizonIQSnapshot
from ..sandbox_runtime import HorizonIQEntryRuntime

_RECOMMENDED_ACTIONS = frozenset(
    {
        "none",
        "self_consumption",
        "charge_required",
        "use_grid",
        "import_for_export",
        "export_for_profit",
        "export_for_solar_headroom",
    }
)


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
            UseGridSensor(coordinator, config_entry.entry_id, environment),
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


class UseGridSensor(HorizonIQEntity, BinarySensorEntity):
    """Expose only a fresh live recommendation for the effective half-hour."""

    def __init__(
        self,
        coordinator,
        entry_id: str,
        environment: str,
        *,
        now_utc: Callable[[], datetime] = dt_util.utcnow,
    ) -> None:
        super().__init__(coordinator)
        self._environment = normalized_environment(environment)
        self._now_utc = now_utc
        self._attr_name = entity_name(self._environment, "Use Grid")
        self._attr_unique_id = build_unique_id(self._environment, entry_id, "use_grid")
        self._cancel_expiry: Callable[[], None] | None = None
        self._removed = False

    def _current(
        self,
    ) -> tuple[bool | None, Schema5Forecast | None, Schema5Period | None, datetime | None]:
        """Evaluate the current coordinator publication with one captured clock read."""
        now = self._now_utc()
        snapshot = self.snapshot
        if (
            not isinstance(snapshot, HorizonIQSnapshot)
            or snapshot.forecast_freshness is not ForecastFreshness.FRESH
            or not isinstance(snapshot.schema5_forecast, Schema5Forecast)
            or not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
        ):
            return None, None, None, None
        forecast = snapshot.schema5_forecast
        if forecast.plan_kind not in PLAN_KINDS:
            return None, None, None, None
        if (
            forecast.stale
            or forecast.schema_version not in SUPPORTED_SCHEMA_VERSIONS
            or forecast.plan_kind != "live"
        ):
            return None, forecast, None, None
        now = now.astimezone(timezone.utc)
        try:
            created = datetime.fromisoformat(forecast.created_at_utc.replace("Z", "+00:00"))
            effective = datetime.fromisoformat(forecast.effective_at_utc.replace("Z", "+00:00"))
            deadline = effective + SCHEMA5_PERIOD_DURATION
        except (ValueError, OverflowError, AttributeError, TypeError):
            return None, forecast, None, None
        if (
            created.tzinfo is None
            or effective.tzinfo is None
            or created > now
            or effective > now
            or now >= deadline
        ):
            return None, forecast, None, None
        try:
            period = select_current_schema5_period(forecast, now)
        except (ValueError, OverflowError, AttributeError, TypeError):
            return None, forecast, None, None
        if period is None:
            return None, forecast, None, None
        try:
            period_start = datetime.fromisoformat(period.date.replace("Z", "+00:00"))
            period_end = period_start + SCHEMA5_PERIOD_DURATION
        except (ValueError, OverflowError, AttributeError, TypeError):
            return None, forecast, None, None
        if period_start.tzinfo is None or not period_start <= effective < period_end:
            return None, forecast, None, None
        deadline = min(deadline, period_end)
        if now >= deadline:
            return None, forecast, None, None
        hold = period.should_use_grid
        if (
            not isinstance(hold, bool)
            or not isinstance(forecast.should_use_grid, bool)
            or not isinstance(period.should_import, bool)
            or (
                period.should_export is not None
                and not isinstance(period.should_export, bool)
            )
            or not isinstance(period.recommended_action, str)
            or period.recommended_action not in _RECOMMENDED_ACTIONS
            or forecast.should_use_grid != hold
            or hold != (period.recommended_action == "use_grid")
            or (hold and (period.should_import or period.should_export is True))
        ):
            return None, forecast, period, deadline
        return hold, forecast, period, deadline

    @property
    def is_on(self) -> bool | None:
        """Return the current typed recommendation, including a valid false."""
        return self._current()[0]

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Expose bounded diagnostics without a forecast payload."""
        _, forecast, period, _ = self._current()
        return {
            "environment": environment_label(self._environment),
            "plan_kind": forecast.plan_kind if forecast is not None else None,
            "current_action": (
                period.recommended_action
                if (
                    period is not None
                    and isinstance(period.recommended_action, str)
                    and period.recommended_action in _RECOMMENDED_ACTIONS
                )
                else None
            ),
        }

    def _schedule_expiry(self, *, after: datetime | None = None) -> None:
        if self._cancel_expiry is not None:
            self._cancel_expiry()
            self._cancel_expiry = None
        _, _, _, deadline = self._current()
        if (
            deadline is not None
            and self.hass is not None
            and not self._removed
            and (after is None or deadline > after)
        ):
            self._cancel_expiry = async_track_point_in_utc_time(
                self.hass, self._on_expiry, deadline
            )

    @callback
    def _on_expiry(self, _now: datetime) -> None:
        if self._removed:
            return
        self._cancel_expiry = None
        self.async_write_ha_state()
        self._schedule_expiry(after=_now)

    def _handle_coordinator_update(self) -> None:
        if self._removed:
            return
        self._schedule_expiry()
        super()._handle_coordinator_update()

    async def async_added_to_hass(self) -> None:
        self._removed = False
        await super().async_added_to_hass()
        self._schedule_expiry()

    async def async_will_remove_from_hass(self) -> None:
        self._removed = True
        if self._cancel_expiry is not None:
            self._cancel_expiry()
            self._cancel_expiry = None
        await super().async_will_remove_from_hass()


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
        """Use entry-local virtual/manual time, otherwise the coordinator wall clock."""
        if self._runtime is not None:
            return self._runtime.virtual_time_utc
        return self._now_utc()

    def _current_action(
        self,
        period: Schema5Period,
        forecast: Schema5Forecast,
    ) -> str:
        """Expose the plan's current action only as bounded diagnostics."""
        return period.recommended_action

    async def async_will_remove_from_hass(self) -> None:
        """Release the optional entry-local runtime listener."""
        if self._remove_listener is not None:
            self._remove_listener()
        await super().async_will_remove_from_hass()

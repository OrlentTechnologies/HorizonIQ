from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from ..entity import HorizonIQEntity
from ..entity_helpers import (
    build_unique_id,
    entity_name,
    environment_label,
    normalized_environment,
)
from ..models import ForecastPeriod


class BatteryManagementSystemStateSensor(HorizonIQEntity, SensorEntity):
    """Expose the active BMS state derived from the current forecast period."""

    _period_duration = timedelta(minutes=30)

    def __init__(self, coordinator, entry_id: str, environment: str) -> None:
        super().__init__(coordinator)
        self._environment = normalized_environment(environment)
        self._attr_name = entity_name(self._environment, "BMS State")
        self._attr_unique_id = build_unique_id(
            self._environment, entry_id, "bms_state"
        )

    @property
    def native_value(self) -> StateType:
        """Return the BMS state from the forecast or active period."""
        forecast_state = self._extract_forecast_state()
        if forecast_state is not None:
            return forecast_state

        period, _ = self._select_relevant_period()
        if period is None:
            return None

        value = period.get("battery_management_system_state")
        if value in (None, ""):
            return None
        return str(value).strip()

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return attributes for the selected forecast period."""
        period, start = self._select_relevant_period()
        attrs: dict[str, object] = {
            "environment": environment_label(self._environment),
        }
        forecast_state = self._extract_forecast_state()
        if forecast_state not in (None, ""):
            attrs["forecast_state"] = forecast_state
        if period is None:
            return attrs

        if start is not None:
            attrs["period_start"] = start.isoformat()
            attrs["period_end"] = (start + self._period_duration).isoformat()

        for key in (
            "id",
            "period",
            "date",
            "price",
            "should_import",
            "amount",
            "battery",
            "bms_hold_period",
        ):
            value = period.get(key)
            if value not in (None, ""):
                attrs[key] = value

        return attrs

    def _select_relevant_period(
        self,
    ) -> tuple[ForecastPeriod | None, datetime | None]:
        periods = self._extract_periods()
        if not periods:
            return None, None

        now = dt_util.utcnow()
        current_period: ForecastPeriod | None = None
        current_start: datetime | None = None
        upcoming_period: ForecastPeriod | None = None
        upcoming_start: datetime | None = None

        for period in periods:
            start = self._parse_datetime(period.get("date"))
            if start is None:
                continue
            if start <= now < start + self._period_duration:
                if current_start is None or start > current_start:
                    current_period = period
                    current_start = start
            elif start > now:
                if upcoming_start is None or start < upcoming_start:
                    upcoming_period = period
                    upcoming_start = start
            elif start <= now and current_start is None:
                current_period = period
                current_start = start

        if current_period is not None:
            return current_period, current_start
        if upcoming_period is not None:
            return upcoming_period, upcoming_start

        return None, None

    def _extract_periods(self) -> list[ForecastPeriod]:
        snapshot = self.snapshot
        if snapshot is None:
            return []
        return snapshot.forecast_periods

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return dt_util.as_utc(value)
        if isinstance(value, (int, float)):
            return dt_util.utc_from_timestamp(float(value))
        parsed = dt_util.parse_datetime(str(value))
        if parsed is None:
            return None
        return dt_util.as_utc(parsed)

    def _extract_forecast_state(self) -> StateType:
        snapshot = self.snapshot
        if snapshot is None:
            return None
        value = snapshot.forecast.get("battery_management_system_state")
        if value in (None, ""):
            return None
        return str(value).strip()

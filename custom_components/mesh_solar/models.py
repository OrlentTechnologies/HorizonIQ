from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict


class MeshSolarConfigData(TypedDict):
    """Stored config entry values for Mesh Solar."""

    url: str
    api_key: str
    battery_capacity_sensor: str
    environment: str
    hash: str
    registration_data: str
    forecast_device_id: str
    forecast_device_token: str


class ForecastPeriod(TypedDict, total=False):
    """Normalized forecast period payload."""

    id: str
    period: int
    date: str
    price: float
    should_import: bool
    amount: float
    imported: float
    exported: float
    estimated_generation: float
    used: float
    battery: float
    bms_hold_period: bool
    battery_management_system_state: str


class ForecastData(TypedDict, total=False):
    """Normalized forecast payload."""

    id: str
    registration_id: str
    date: str
    calculated_on_utc: str
    hash: str
    periods: list[ForecastPeriod]
    current_capacity: float
    min_capacity: float
    target_capacity: float
    low_price: float
    medium_price: float
    battery_management_system_state: str
    should_import: bool
    cloud_update_enabled: bool
    currency: str
    registration_data: str
    total_cost: float
    charging_cost: float
    saving: float
    forecast_cadence_minutes: int
    trial_has_trial: bool
    trial_is_active: bool
    trial_is_eligible: bool
    trial_status: str
    trial_starts_on_utc: str
    trial_expires_on_utc: str
    trial_forecast_cadence_minutes: int
    trial_device_display_name: str
    authorization_status: str
    authorization_status_code: int
    authorization_message: str


class TrialData(TypedDict, total=False):
    """Normalized app trial payload."""

    has_trial: bool
    is_active: bool
    is_eligible: bool
    status: str
    starts_on_utc: str
    expires_on_utc: str
    forecast_cadence_minutes: int
    device_display_name: str
    authorization_status: str
    authorization_status_code: int
    authorization_message: str


RegistrationData = dict[str, object]


@dataclass(frozen=True, slots=True)
class MeshSolarSnapshot:
    """Typed coordinator snapshot consumed by entities."""

    forecast: ForecastData = field(default_factory=dict)
    trial: TrialData = field(default_factory=dict)
    forecast_periods: list[ForecastPeriod] = field(default_factory=list)
    registration: RegistrationData = field(default_factory=dict)
    currency: str | None = None
    target_capacity: float | None = None
    should_import: bool | None = None
    total_cost: float | None = None
    charging_cost: float | None = None
    saving: float | None = None
    forecast_hash: str | None = None
    registration_data: str | None = None
    forecast_cadence_minutes: int | None = None

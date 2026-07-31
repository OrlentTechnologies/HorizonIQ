from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TypedDict


class HorizonIQConfigData(TypedDict):
    """Stored config entry values for HorizonIQ."""

    url: str
    api_key: str
    battery_capacity_sensor: str
    capacity_source: str
    environment: str
    hash: str
    registration_data: str
    forecast_device_id: str
    forecast_device_token: str


class SupportedControl(TypedDict):
    """Exact schema-5 equipment-profile control capabilities."""

    requiredCharging: bool
    useGrid: bool
    importForExport: bool
    profitableExport: bool
    solarHeadroomExport: bool


class EquipmentProfile(TypedDict):
    """Exact camel-case schema-5 registration-owned equipment profile."""

    id: str
    version: int
    source: str
    displayName: str
    batteryCapacityWh: float
    minimumCapacityPercentage: float
    maximumBatteryChargePowerWatts: float
    maximumBatteryDischargePowerWatts: float
    inverterMaximumChargePowerWatts: float
    inverterMaximumDischargePowerWatts: float
    maximumGridImportPowerWatts: float
    maximumGridExportPowerWatts: float
    controlAdapterId: str
    supportedControl: SupportedControl
    productionExportEnabled: bool
    safeFallbackId: str


@dataclass(frozen=True, slots=True)
class DirectEquipmentProfile:
    """Registration-owned schema-5 equipment profile for direct control."""

    identifier: str
    version: int
    source: str
    display_name: str
    battery_capacity_wh: float
    minimum_capacity_percentage: float
    maximum_battery_charge_power_watts: float
    maximum_battery_discharge_power_watts: float
    inverter_maximum_charge_power_watts: float
    inverter_maximum_discharge_power_watts: float
    maximum_grid_import_power_watts: float
    maximum_grid_export_power_watts: float
    control_adapter_id: str
    required_charging: bool
    use_grid: bool
    import_for_export: bool
    profitable_export: bool
    solar_headroom_export: bool
    production_export_enabled: bool
    safe_fallback_id: str


@dataclass(frozen=True, slots=True)
class DirectForecastPeriod:
    """One normalized schema-5 period, with nullable command metadata preserved."""

    starts_at_utc: datetime
    executable_action: str
    simulation_action: str | None
    recommended_action: str | None
    command_id: str | None
    issued_at_utc: datetime | None
    expires_at_utc: datetime | None
    action_priority: int | None
    expected_import_kwh: float | None
    expected_export_kwh: float | None
    expected_start_soc_kwh: float | None
    expected_end_soc_kwh: float | None
    decision_trace: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class Forecast:
    """Typed direct-control forecast produced only by coordinator normalization."""

    schema_version: int
    plan_id: str
    plan_kind: str
    created_at_utc: datetime
    effective_at_utc: datetime
    equipment_profile: DirectEquipmentProfile
    hash_value: str
    registration_data: str
    forecast_cadence_minutes: int
    periods: tuple[DirectForecastPeriod, ...]


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
    executable_action: str
    simulation_action: str
    recommended_action: str
    command_id: str
    issued_at_utc: str
    expires_at_utc: str
    action_priority: int
    expected_import: float
    expected_export: float
    expected_start_soc: float
    expected_end_soc: float
    decision_trace: dict[str, object]


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
    schema_version: int
    plan_id: str
    plan_kind: str
    created_at_utc: str
    effective_at_utc: str
    equipment_profile: EquipmentProfile


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
class HorizonIQSnapshot:
    """Typed coordinator snapshot consumed by entities."""

    forecast: ForecastData = field(default_factory=dict)
    direct_forecast: Forecast | None = None
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

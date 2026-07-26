"""Frozen domain types. Canonical units: Wh, W, seconds, ratios and UTC."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal

class OperatingMode(str, Enum): IDLE = "idle"; SELF_CONSUMPTION = "self_consumption"; GRID_SETPOINT = "grid_setpoint"
class CommandStatus(str, Enum): APPLIED = "applied"; FALLBACK_MISSING = "fallback_missing"; FALLBACK_STALE = "fallback_stale"; FALLBACK_EXPIRED = "fallback_expired"; FALLBACK_INVALID = "fallback_invalid"
class SimulationHealth(str, Enum): HEALTHY = "healthy"; UNHEALTHY = "unhealthy"
ClockRateValue = Literal["paused", "1x", "10x", "60x", "240x"]

@dataclass(frozen=True, slots=True)
class BatteryConfig:
    capacity_wh: float; reserve_wh: float; max_charge_power_w: float; max_discharge_power_w: float
    charge_efficiency: float = .95; discharge_efficiency: float = .95; balance_tolerance_wh: float = .01; nominal_voltage_v: float = 48.
@dataclass(frozen=True, slots=True)
class BatteryState:
    energy_wh: float
    def soc_ratio(self, capacity_wh: float) -> float: return self.energy_wh / capacity_wh
@dataclass(frozen=True, slots=True)
class Command:
    mode: OperatingMode; requested_grid_power_w: float | None = None; issued_at_utc: datetime | None = None; expires_at_utc: datetime | None = None
@dataclass(frozen=True, slots=True)
class IntervalLedger:
    grid_import_wh: float = 0.; grid_export_wh: float = 0.; solar_generation_wh: float = 0.; load_consumption_wh: float = 0.; battery_energy_increase_wh: float = 0.; battery_energy_decrease_wh: float = 0.; charge_conversion_loss_wh: float = 0.; discharge_conversion_loss_wh: float = 0.; start_battery_energy_wh: float = 0.; end_battery_energy_wh: float = 0.; balance_error_wh: float = 0.
    def plus(self, other: "IntervalLedger") -> "IntervalLedger": return IntervalLedger(**{name: getattr(self, name) + getattr(other, name) for name in self.__dataclass_fields__})
@dataclass(frozen=True, slots=True)
class StepResult:
    state: BatteryState; actual_grid_power_w: float; battery_ac_power_w: float; command_status: CommandStatus; ledger: IntervalLedger; health: SimulationHealth; reason: str | None = None
@dataclass(frozen=True, slots=True)
class ClockState:
    virtual_time_utc: datetime; rate: ClockRateValue; sequence: int = 0; reset_generation: int = 0
@dataclass(frozen=True, slots=True)
class SyntheticPeriod:
    valid_from_utc: datetime; valid_to_utc: datetime; load_w: float; solar_w: float; import_rate_gbp_per_kwh: float; export_rate_gbp_per_kwh: float
@dataclass(frozen=True, slots=True)
class SyntheticProfile:
    schema_version: int; identifier: str; periods: tuple[SyntheticPeriod, ...]; starting_battery_energy_wh: float | None = None
@dataclass(frozen=True, slots=True)
class ProfileCursor: profile_id: str; index: int = 0
@dataclass(frozen=True, slots=True)
class ScenarioDefinition: identifier: str; profile: SyntheticProfile
@dataclass(frozen=True, slots=True)
class SimulationSnapshot:
    schema_version: int; battery_state: BatteryState; cumulative_ledger: IntervalLedger; clock_state: ClockState; active_profile_id: str | None = None; profile_cursor: ProfileCursor | None = None; active_command: Command | None = None; command_status: CommandStatus = CommandStatus.FALLBACK_MISSING; load_w: float = 0.; solar_w: float = 0.; control_config: dict[str, float] | None = None; playback_state: str = "stopped"; selected_profile_filename: str | None = None; profile_hash: str | None = None; replay_session: dict[str, object] | None = None; faults: tuple[dict[str, object], ...] = ()

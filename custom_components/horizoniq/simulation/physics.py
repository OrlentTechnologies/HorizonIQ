"""Pure power balance: grid + solar = load + battery (positive battery charges)."""
from __future__ import annotations
import math
from datetime import datetime, timezone
from .models import BatteryConfig, BatteryState, Command, CommandStatus, IntervalLedger, OperatingMode, SimulationHealth, StepResult
DEFAULT_BALANCE_TOLERANCE_WH = .01  # numerical floating-point accounting tolerance, not physical loss
def _ok(value: float, name: str) -> None:
    if not math.isfinite(value) or value < 0: raise ValueError(f"{name} must be finite and non-negative")
def _command(command: Command | None, when: datetime) -> tuple[OperatingMode, float | None, CommandStatus, str | None]:
    if command is None: return OperatingMode.SELF_CONSUMPTION, None, CommandStatus.FALLBACK_MISSING, "No command; self-consumption used."
    if command.expires_at_utc and command.expires_at_utc <= when: return OperatingMode.SELF_CONSUMPTION, None, CommandStatus.FALLBACK_EXPIRED, "Command expired; self-consumption used."
    if command.issued_at_utc and command.issued_at_utc > when: return OperatingMode.SELF_CONSUMPTION, None, CommandStatus.FALLBACK_STALE, "Command is not yet valid; self-consumption used."
    if command.mode is OperatingMode.GRID_SETPOINT and (command.requested_grid_power_w is None or not math.isfinite(command.requested_grid_power_w)): return OperatingMode.SELF_CONSUMPTION, None, CommandStatus.FALLBACK_INVALID, "Grid setpoint is invalid; self-consumption used."
    return command.mode, command.requested_grid_power_w, CommandStatus.APPLIED, None
def simulate_step(*, previous: BatteryState, elapsed_seconds: float, virtual_time_utc: datetime, command: Command | None, load_w: float, solar_w: float, config: BatteryConfig) -> StepResult:
    if virtual_time_utc.tzinfo is None or virtual_time_utc.utcoffset() is None: raise ValueError("virtual_time_utc must be timezone-aware")
    if not math.isfinite(elapsed_seconds) or elapsed_seconds < 0: raise ValueError("elapsed_seconds must be finite and non-negative")
    for v, n in ((config.capacity_wh,"capacity_wh"),(config.reserve_wh,"reserve_wh"),(config.max_charge_power_w,"max_charge_power_w"),(config.max_discharge_power_w,"max_discharge_power_w"),(config.balance_tolerance_wh,"balance_tolerance_wh"), (load_w,"load_w"),(solar_w,"solar_w")): _ok(v,n)
    if config.reserve_wh > config.capacity_wh or not 0 < config.charge_efficiency <= 1 or not 0 < config.discharge_efficiency <= 1 or not math.isfinite(previous.energy_wh): raise ValueError("battery configuration or state is invalid")
    when = virtual_time_utc.astimezone(timezone.utc); start = min(config.capacity_wh, max(config.reserve_wh, previous.energy_wh)); mode, setpoint, status, reason = _command(command, when)
    if elapsed_seconds == 0:
        return StepResult(BatteryState(start), load_w-solar_w, 0., status, IntervalLedger(start_battery_energy_wh=start,end_battery_energy_wh=start), SimulationHealth.HEALTHY, reason)
    wanted = 0. if mode is OperatingMode.IDLE else (setpoint + solar_w - load_w if mode is OperatingMode.GRID_SETPOINT else solar_w - load_w)
    hours = elapsed_seconds / 3600.; battery = min(config.max_charge_power_w, max(-config.max_discharge_power_w, wanted))
    if battery >= 0:
        battery = min(battery, (config.capacity_wh-start)/(config.charge_efficiency*hours)); increase=battery*hours*config.charge_efficiency; decrease=0.; charge_loss=battery*hours-increase; discharge_loss=0.
    else:
        battery = -min(-battery, (start-config.reserve_wh)*config.discharge_efficiency/hours); increase=0.; decrease=-battery*hours/config.discharge_efficiency; charge_loss=0.; discharge_loss=decrease+battery*hours
    end=start+increase-decrease; grid=load_w+battery-solar_w; grid_wh=grid*hours; gi=max(0.,grid_wh); ge=max(0.,-grid_wh); solar=solar_w*hours; load=load_w*hours
    error=gi+solar+decrease-(load+ge+increase+charge_loss+discharge_loss); ledger=IntervalLedger(grid_import_wh=gi,grid_export_wh=ge,solar_generation_wh=solar,load_consumption_wh=load,battery_energy_increase_wh=increase,battery_energy_decrease_wh=decrease,charge_conversion_loss_wh=charge_loss,discharge_conversion_loss_wh=discharge_loss,start_battery_energy_wh=start,end_battery_energy_wh=end,balance_error_wh=error); health=SimulationHealth.HEALTHY if abs(error)<=config.balance_tolerance_wh else SimulationHealth.UNHEALTHY
    return StepResult(BatteryState(end),grid,battery,status,ledger,health,reason)

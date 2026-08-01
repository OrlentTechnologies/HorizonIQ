"""Pure simulation regression tests; no Home Assistant fixture is required."""
from datetime import datetime, timedelta, timezone
import pytest
from custom_components.horizoniq.simulation.clock import ClockRate, VirtualClock
from custom_components.horizoniq.simulation.models import BatteryConfig, BatteryState, Command, CommandStatus, IntervalLedger, OperatingMode, SimulationHealth, SimulationSnapshot
from custom_components.horizoniq.simulation.physics import simulate_step
from custom_components.horizoniq.simulation.profiles import ProfileCursor, SyntheticPeriod, SyntheticProfile, period_at, validate_profile
from custom_components.horizoniq.simulation.snapshots import from_json, to_json

UTC=timezone.utc
NOW=datetime(2026,3,29,0,0,tzinfo=UTC)
CONFIG=BatteryConfig(10000,2000,2000,2000,.9,.8)
def step(**kwargs): return simulate_step(previous=kwargs.pop("previous",BatteryState(5000)),elapsed_seconds=kwargs.pop("elapsed_seconds",1800),virtual_time_utc=kwargs.pop("virtual_time_utc",NOW),command=kwargs.pop("command",None),load_w=kwargs.pop("load_w",0),solar_w=kwargs.pop("solar_w",0),config=kwargs.pop("config",CONFIG))

def test_idle_and_zero_time_are_unchanged():
    result=step(command=Command(OperatingMode.IDLE),elapsed_seconds=0)
    assert result.state.energy_wh==5000 and result.ledger.grid_import_wh==0
def test_self_consumption_and_battery_supported_load():
    result=step(load_w=1000)
    assert result.battery_ac_power_w==-1000 and result.actual_grid_power_w==0 and result.state.energy_wh==4375
def test_grid_charging_and_solar_charging_apply_efficiency():
    charge=step(command=Command(OperatingMode.GRID_SETPOINT,1000),load_w=0)
    solar=step(solar_w=1000)
    assert charge.battery_ac_power_w==1000 and charge.state.energy_wh==5450
    assert solar.state.energy_wh==5450 and solar.ledger.charge_conversion_loss_wh==50
def test_deliberate_export_and_residual_grid_after_reserve_clamp():
    export=step(command=Command(OperatingMode.GRID_SETPOINT,-1000))
    reserve=step(previous=BatteryState(2000),load_w=1000)
    assert export.actual_grid_power_w==-1000 and export.battery_ac_power_w==-1000
    assert reserve.battery_ac_power_w==0 and reserve.actual_grid_power_w==1000
def test_capacity_and_power_limits_apply():
    full=step(previous=BatteryState(9950),solar_w=2000)
    limited=step(load_w=5000)
    assert full.state.energy_wh==10000 and full.actual_grid_power_w==-1888.888888888889
    assert limited.battery_ac_power_w==-2000 and limited.actual_grid_power_w==3000
def test_invalid_or_expired_commands_fallback_explicitly():
    expired=step(command=Command(OperatingMode.GRID_SETPOINT,1000,expires_at_utc=NOW))
    invalid=step(command=Command(OperatingMode.GRID_SETPOINT,None))
    assert expired.command_status is CommandStatus.FALLBACK_EXPIRED
    assert invalid.command_status is CommandStatus.FALLBACK_INVALID
def test_negative_time_and_nonfinite_are_rejected():
    with pytest.raises(ValueError): step(elapsed_seconds=-1)
    with pytest.raises(ValueError): step(load_w=float("nan"))
def test_balance_and_cumulative_ledger_are_explicit():
    result=step(load_w=1000)
    assert result.health is SimulationHealth.HEALTHY and abs(result.ledger.balance_error_wh)<.01
    assert IntervalLedger().plus(result.ledger)==result.ledger
def test_normal_ticks_never_create_manual_adjustments():
    state=BatteryState(5000); cumulative=IntervalLedger()
    for index in range(1000):
        result=step(previous=state,virtual_time_utc=NOW+timedelta(seconds=30*index),load_w=800,solar_w=250,elapsed_seconds=30)
        state=result.state; cumulative=cumulative.plus(result.ledger)
    assert cumulative.manual_adjustment_wh==0
    assert abs(cumulative.balance_error_wh)<CONFIG.balance_tolerance_wh
def test_clock_rates_step_reset_and_isolation():
    first=VirtualClock(NOW); second=VirtualClock(NOW,ClockRate.X10)
    assert first.advance(10).virtual_time_utc==NOW
    assert second.advance(10).virtual_time_utc==NOW+timedelta(seconds=100)
    assert first.step().virtual_time_utc==NOW+timedelta(minutes=30)
    reset=first.reset(datetime(2026,3,29,1,tzinfo=timezone(timedelta(hours=1))))
    assert reset.virtual_time_utc==NOW and reset.reset_generation==1 and second.state.sequence==1
@pytest.mark.parametrize("rate,multiplier",[(ClockRate.X1,1),(ClockRate.X10,10),(ClockRate.X60,60),(ClockRate.X240,240)])
def test_accelerated_clock_rates(rate,multiplier):
    assert VirtualClock(NOW,rate).advance(2).virtual_time_utc==NOW+timedelta(seconds=2*multiplier)
def test_profile_validation_cursor_and_limit():
    periods=tuple(SyntheticPeriod(NOW+timedelta(minutes=30*i),NOW+timedelta(minutes=30*(i+1)),100,0,-.01,.1) for i in range(2))
    profile=SyntheticProfile(1,"test",periods,3000); validate_profile(profile,CONFIG)
    assert period_at(profile,ProfileCursor("test"),NOW+timedelta(minutes=31))[1].index==1
    with pytest.raises(ValueError): validate_profile(SyntheticProfile(1,"bad",periods[:1]+(SyntheticPeriod(NOW+timedelta(hours=2),NOW+timedelta(hours=2,minutes=30),0,0,0,.1),)),CONFIG)
    with pytest.raises(ValueError): validate_profile(SyntheticProfile(1,"long",periods*745),CONFIG)
def test_snapshot_round_trip_reproduces_next_step_exactly():
    result=step(load_w=400); clock=VirtualClock(NOW,ClockRate.X60); clock.advance(1)
    snapshot=SimulationSnapshot(4,result.state,result.ledger,clock.state,"p",ProfileCursor("p"),Command(OperatingMode.IDLE),CommandStatus.APPLIED)
    restored=from_json(to_json(snapshot))
    assert restored==snapshot
    assert step(previous=restored.battery_state,virtual_time_utc=restored.clock_state.virtual_time_utc,load_w=400)==step(previous=snapshot.battery_state,virtual_time_utc=snapshot.clock_state.virtual_time_utc,load_w=400)

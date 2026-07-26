"""Deterministic synthetic planning profiles; never actual telemetry."""
from __future__ import annotations
import math
from datetime import datetime, timedelta, timezone
from .models import BatteryConfig, ProfileCursor, ScenarioDefinition, SyntheticPeriod, SyntheticProfile
MAX_PROFILE_PERIODS=1488
def validate_profile(profile: SyntheticProfile, config: BatteryConfig) -> None:
    if not profile.identifier or profile.schema_version != 1 or not profile.periods or len(profile.periods)>MAX_PROFILE_PERIODS: raise ValueError("profile identifier, schema version, or period count is invalid")
    expected=None
    for item in profile.periods:
        if item.valid_from_utc.tzinfo is None or item.valid_to_utc.tzinfo is None or item.valid_from_utc.utcoffset() is None or item.valid_to_utc.utcoffset() is None: raise ValueError("profile timestamps must be timezone-aware")
        start=item.valid_from_utc.astimezone(timezone.utc); end=item.valid_to_utc.astimezone(timezone.utc)
        if end-start!=timedelta(minutes=30) or (expected and start!=expected): raise ValueError("profile periods must be contiguous half-hour UTC periods")
        if not all(math.isfinite(v) for v in (item.load_w,item.solar_w,item.import_rate_gbp_per_kwh,item.export_rate_gbp_per_kwh)) or item.load_w<0 or item.solar_w<0 or item.export_rate_gbp_per_kwh<0: raise ValueError("profile values are invalid")
        expected=end
    if profile.starting_battery_energy_wh is not None and not config.reserve_wh<=profile.starting_battery_energy_wh<=config.capacity_wh: raise ValueError("starting battery energy is outside reserve/capacity")
def period_at(profile: SyntheticProfile, cursor: ProfileCursor, at_utc: datetime) -> tuple[SyntheticPeriod, ProfileCursor]:
    if at_utc.tzinfo is None or at_utc.utcoffset() is None: raise ValueError("timestamps must be timezone-aware")
    if cursor.profile_id!=profile.identifier: raise ValueError("cursor does not belong to profile")
    at=at_utc.astimezone(timezone.utc)
    for index in range(cursor.index,len(profile.periods)):
        period=profile.periods[index]
        if period.valid_from_utc.astimezone(timezone.utc)<=at<period.valid_to_utc.astimezone(timezone.utc): return period,ProfileCursor(profile.identifier,index)
    raise ValueError("virtual time is outside profile")
def standard_scenarios(start_utc: datetime) -> tuple[ScenarioDefinition,...]:
    start=start_utc.astimezone(timezone.utc)
    def scenario(identifier: str, load: float, solar: float) -> ScenarioDefinition:
        return ScenarioDefinition(identifier,SyntheticProfile(1,identifier,(SyntheticPeriod(start,start+timedelta(minutes=30),load,solar,.2,.1),)))
    return (scenario("idle",0,0),scenario("household_load",800,0),scenario("solar_surplus",200,1200),scenario("grid_charging",0,0),scenario("battery_supported_load",1200,0),scenario("deliberate_export",0,0))

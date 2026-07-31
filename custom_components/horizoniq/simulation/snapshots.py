"""Versioned value-only snapshots; no HA objects, credentials or device details."""
from __future__ import annotations
import json
from datetime import datetime
from .models import BatteryState, ClockState, Command, CommandStatus, IntervalLedger, OperatingMode, ProfileCursor, SimulationSnapshot
SNAPSHOT_SCHEMA_VERSION = 3
def to_json(snapshot: SimulationSnapshot) -> str:
    def encode(value: object) -> object:
        if isinstance(value,datetime): return value.isoformat()
        if isinstance(value,(OperatingMode,CommandStatus)): return value.value
        if hasattr(value,"__dataclass_fields__"): return {key:encode(getattr(value,key)) for key in value.__dataclass_fields__}
        return value
    if snapshot.schema_version not in {1, 2, SNAPSHOT_SCHEMA_VERSION}: raise ValueError("unsupported snapshot schema")
    return json.dumps(encode(snapshot),sort_keys=True,separators=(",",":"))
def from_json(value: str) -> SimulationSnapshot:
    raw=json.loads(value)
    if not isinstance(raw,dict) or raw.get("schema_version") not in {1, 2, SNAPSHOT_SCHEMA_VERSION}: raise ValueError("unsupported snapshot schema")
    try:
        state=BatteryState(**raw["battery_state"]); ledger=IntervalLedger(**raw["cumulative_ledger"]); clock_raw=raw["clock_state"]; clock=ClockState(datetime.fromisoformat(clock_raw["virtual_time_utc"]),clock_raw["rate"],clock_raw["sequence"],clock_raw["reset_generation"])
        cursor=ProfileCursor(**raw["profile_cursor"]) if raw.get("profile_cursor") else None; command_raw=raw.get("active_command"); command=Command(OperatingMode(command_raw["mode"]),command_raw.get("requested_grid_power_w"),datetime.fromisoformat(command_raw["issued_at_utc"]) if command_raw.get("issued_at_utc") else None,datetime.fromisoformat(command_raw["expires_at_utc"]) if command_raw.get("expires_at_utc") else None) if command_raw else None
        if clock.virtual_time_utc.tzinfo is None: raise ValueError("snapshot clock is naive")
        return SimulationSnapshot(SNAPSHOT_SCHEMA_VERSION,state,ledger,clock,raw.get("active_profile_id"),cursor,command,CommandStatus(raw["command_status"]),raw.get("load_w", 0.),raw.get("solar_w", 0.),raw.get("control_config"),raw.get("playback_state", "stopped"),raw.get("selected_profile_filename"),raw.get("profile_hash"),raw.get("replay_session"),tuple(raw.get("faults", ())))
    except (KeyError,TypeError,ValueError) as error: raise ValueError("snapshot is invalid") from error

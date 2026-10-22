"""Versioned local snapshots with atomic decoding and legacy sanitation."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
import json
import math

from .clock import ClockRate
from .faults import validate_faults
from .models import (
    BatteryState, ClockState, Command, CommandStatus, IntervalLedger,
    OperatingMode, ProfileCursor, SimulationSnapshot,
)

SNAPSHOT_SCHEMA_VERSION = 5


def to_json(snapshot: SimulationSnapshot) -> str:
    """Emit only the current value-only snapshot contract."""
    def encode(value: object) -> object:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        if is_dataclass(value) and not isinstance(value, type):
            return {item.name: encode(getattr(value, item.name)) for item in fields(value)}
        return value

    if snapshot.schema_version != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("unsupported snapshot schema")
    return json.dumps(
        encode(snapshot), sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def from_json(value: str) -> SimulationSnapshot:
    """Validate retained state before converting known old snapshots to schema 5."""
    try:
        raw = json.loads(value)
        if (
            not isinstance(raw, dict)
            or type(raw.get("schema_version")) is not int
            or raw["schema_version"] not in {1, 2, 3, 4, 5}
        ):
            raise ValueError("unsupported snapshot schema")
        legacy = raw["schema_version"] < SNAPSHOT_SCHEMA_VERSION
        state = BatteryState(**raw["battery_state"])
        ledger = IntervalLedger(**raw["cumulative_ledger"])
        numbers = (
            state.energy_wh,
            *(getattr(ledger, item.name) for item in fields(ledger)),
        )
        for number in numbers:
            _finite(number)
        clock_raw = raw["clock_state"]
        clock = ClockState(
            virtual_time_utc=_timestamp(clock_raw["virtual_time_utc"]),
            rate=ClockRate(clock_raw["rate"]).value,
            sequence=_counter(clock_raw["sequence"]),
            reset_generation=_counter(clock_raw["reset_generation"]),
        )
        cursor_raw = raw.get("profile_cursor")
        cursor = ProfileCursor(**cursor_raw) if cursor_raw is not None else None
        profile_id = raw.get("active_profile_id")
        if profile_id is not None and (
            not isinstance(profile_id, str) or not profile_id
        ):
            raise ValueError("snapshot is invalid")
        if cursor is not None:
            _counter(cursor.index)
            if cursor.profile_id != profile_id:
                raise ValueError("snapshot is invalid")
        load = _finite(raw.get("load_w", 0.0))
        solar = _finite(raw.get("solar_w", 0.0))
        if not 0 <= load <= 100_000 or not 0 <= solar <= 100_000:
            raise ValueError("snapshot is invalid")
        if not legacy and raw.get("playback_state", "stopped") not in {
            "stopped", "paused", "running", "completed",
        }:
            raise ValueError("snapshot is invalid")
        command = None
        command_raw = raw.get("active_command")
        if not legacy and command_raw is not None:
            command = Command(
                mode=OperatingMode(command_raw["mode"]),
                requested_grid_power_w=command_raw.get("requested_grid_power_w"),
                issued_at_utc=_optional_timestamp(command_raw.get("issued_at_utc")),
                expires_at_utc=_optional_timestamp(command_raw.get("expires_at_utc")),
            )
            if command.requested_grid_power_w is not None:
                _finite(command.requested_grid_power_w)
                if abs(command.requested_grid_power_w) > 100_000:
                    raise ValueError("snapshot is invalid")
            if (
                command.mode is OperatingMode.GRID_PRESERVATION
                and command.requested_grid_power_w is not None
            ):
                raise ValueError("snapshot is invalid")
            if (
                command.mode is OperatingMode.GRID_SETPOINT
                and command.requested_grid_power_w is None
            ):
                raise ValueError("snapshot is invalid")
            if (command.issued_at_utc is None) != (command.expires_at_utc is None):
                raise ValueError("snapshot is invalid")
            if (
                command.issued_at_utc is not None
                and not command.issued_at_utc <= clock.virtual_time_utc < command.expires_at_utc
            ):
                raise ValueError("snapshot is invalid")
        raw_faults = raw.get("faults", [])
        if legacy and isinstance(raw_faults, list):
            raw_faults = [
                item for item in raw_faults
                if not (isinstance(item, dict) and item.get("kind") == "replay_api_failure")
            ]
        faults = validate_faults(raw_faults)
        return SimulationSnapshot(
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            battery_state=state,
            cumulative_ledger=ledger,
            clock_state=clock,
            active_profile_id=profile_id,
            profile_cursor=cursor,
            active_command=command,
            command_status=(
                CommandStatus.FALLBACK_MISSING
                if legacy else CommandStatus(raw["command_status"])
            ),
            load_w=load,
            solar_w=solar,
            control_config=raw.get("control_config"),
            playback_state="stopped",
            faults=tuple(fault.to_dict() for fault in faults),
        )
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise ValueError("snapshot is invalid") from error


def _finite(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError("snapshot is invalid")
    return float(value)


def _counter(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("snapshot is invalid")
    return value


def _optional_timestamp(value: object) -> datetime | None:
    return _timestamp(value) if value is not None else None


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("snapshot is invalid")
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("snapshot clock is naive")
    return timestamp

"""Pure frozen sandbox command metadata, status, and duplicate-ledger models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import json
import math
import re
from uuid import UUID

from .topics import (
    MAX_ABSOLUTE_POWER_WATTS,
    VictronOperatingState,
    is_sandbox_gx_id,
)


COMMAND_SCHEMA_VERSION = 4
COMMAND_CORRELATION_TIMEOUT_SECONDS = 30
COMMAND_DUPLICATE_RETENTION_SECONDS = 86_400
COMMAND_DUPLICATE_MAX_ENTRIES = 1_024
_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)


class CommandAction(StrEnum):
    """The frozen Node-RED command actions."""

    CHARGE_REQUIRED = "charge_required"
    IMPORT_FOR_EXPORT = "import_for_export"
    EXPORT_FOR_PROFIT = "export_for_profit"
    EXPORT_FOR_SOLAR_HEADROOM = "export_for_solar_headroom"


class CommandLifecycleState(StrEnum):
    """The only canonical HA command-status states."""

    RECEIVED = "received"
    APPLIED = "applied"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class IssuedCommand:
    """Validated command metadata, excluding any W messages."""

    gx_device_id: str
    plan_id: str
    command_id: str
    action: CommandAction
    issued_at_utc: datetime
    effective_at_utc: datetime
    expires_at_utc: datetime
    expected_hub4_mode: int
    expected_ve_bus_mode: int
    expected_ac_power_setpoint_w: float


@dataclass(frozen=True, slots=True)
class AcceptedCommandId:
    """A bounded duplicate-protection ledger entry without command payload data."""

    command_id: str
    accepted_at_utc: datetime


def parse_issued_command(payload: str | bytes | object) -> IssuedCommand:
    """Strictly parse the exact frozen schema-4 issued-metadata payload."""
    raw = _json_object(payload, "issued metadata")
    required = {
        "schemaVersion",
        "gxDeviceId",
        "planId",
        "commandId",
        "action",
        "issuedAtUtc",
        "effectiveAtUtc",
        "expiresAtUtc",
        "expectedHub4Mode",
        "expectedVeBusMode",
        "expectedAcPowerSetpointW",
    }
    if set(raw) != required:
        raise ValueError("Issued metadata fields are invalid")
    if raw["schemaVersion"] != COMMAND_SCHEMA_VERSION:
        raise ValueError("Issued metadata schema is unsupported")
    gx_device_id = raw["gxDeviceId"]
    if not is_sandbox_gx_id(gx_device_id):
        raise ValueError("Issued metadata GX identity is invalid")
    issued = _utc_z(raw["issuedAtUtc"], "issuedAtUtc")
    effective = _utc_z(raw["effectiveAtUtc"], "effectiveAtUtc")
    expires = _utc_z(raw["expiresAtUtc"], "expiresAtUtc")
    if not issued <= effective < expires:
        raise ValueError("Issued metadata command window is invalid")
    try:
        action = CommandAction(raw["action"])
    except (TypeError, ValueError) as err:
        raise ValueError("Issued metadata action is invalid") from err
    return IssuedCommand(
        gx_device_id=gx_device_id,
        plan_id=_uuid(raw["planId"], "planId"),
        command_id=_uuid(raw["commandId"], "commandId"),
        action=action,
        issued_at_utc=issued,
        effective_at_utc=effective,
        expires_at_utc=expires,
        expected_hub4_mode=_integer(raw["expectedHub4Mode"], "expectedHub4Mode"),
        expected_ve_bus_mode=_integer(raw["expectedVeBusMode"], "expectedVeBusMode"),
        expected_ac_power_setpoint_w=_finite(
            raw["expectedAcPowerSetpointW"], "expectedAcPowerSetpointW"
        ),
    )


def command_status_payload(
    command: IssuedCommand,
    state: CommandLifecycleState,
    timestamp_utc: datetime,
    reason: str,
    *,
    soc_percent: float,
    battery_power_w: float,
    grid_power_w: float,
    operating_state: VictronOperatingState,
) -> str:
    """Build the exact frozen schema-4 status payload with local synthetic state."""
    timestamp = _utc_z_value(timestamp_utc, "timestampUtc")
    if not isinstance(reason, str) or not 0 < len(reason) <= 240:
        raise ValueError("Command status reason is invalid")
    summary = {
        "socPercent": _bounded(soc_percent, "socPercent", 0.0, 100.0),
        "batteryPowerW": _bounded(
            battery_power_w,
            "batteryPowerW",
            -MAX_ABSOLUTE_POWER_WATTS,
            MAX_ABSOLUTE_POWER_WATTS,
        ),
        "gridPowerW": _bounded(
            grid_power_w,
            "gridPowerW",
            -MAX_ABSOLUTE_POWER_WATTS,
            MAX_ABSOLUTE_POWER_WATTS,
        ),
        "operatingState": int(operating_state),
    }
    return json.dumps(
        {
            "schemaVersion": COMMAND_SCHEMA_VERSION,
            "gxDeviceId": command.gx_device_id,
            "planId": command.plan_id,
            "commandId": command.command_id,
            "timestampUtc": timestamp,
            "state": state.value,
            "reason": reason,
            "simulatedState": summary,
        },
        separators=(",", ":"),
    )


def prune_command_ledger(
    entries: tuple[AcceptedCommandId, ...], now_utc: datetime
) -> tuple[AcceptedCommandId, ...]:
    """Return valid bounded entries within the frozen duplicate-retention window."""
    now = _aware_utc(now_utc, "now")
    cutoff = now - timedelta(seconds=COMMAND_DUPLICATE_RETENTION_SECONDS)
    kept = tuple(entry for entry in entries if entry.accepted_at_utc > cutoff)
    return kept[-COMMAND_DUPLICATE_MAX_ENTRIES:]


def accept_command_id(
    entries: tuple[AcceptedCommandId, ...], command_id: str, now_utc: datetime
) -> tuple[tuple[AcceptedCommandId, ...], bool]:
    """Add a non-duplicate ID or return the retained immutable ledger unchanged."""
    pruned = prune_command_ledger(entries, now_utc)
    if any(entry.command_id == command_id for entry in pruned):
        return pruned, False
    return (
        (*pruned, AcceptedCommandId(command_id, _aware_utc(now_utc, "now")))[
            -COMMAND_DUPLICATE_MAX_ENTRIES:
        ],
        True,
    )


def ledger_to_storage(entries: tuple[AcceptedCommandId, ...]) -> list[dict[str, str]]:
    """Serialize only command IDs and accepted virtual UTC timestamps."""
    return [
        {"command_id": entry.command_id, "accepted_at_utc": _utc_z_value(entry.accepted_at_utc, "accepted_at_utc")}
        for entry in entries
    ]


def ledger_from_storage(value: object, now_utc: datetime) -> tuple[AcceptedCommandId, ...]:
    """Validate persisted duplicate entries without retaining command metadata."""
    if not isinstance(value, list) or len(value) > COMMAND_DUPLICATE_MAX_ENTRIES:
        raise ValueError("Stored command ledger is invalid")
    entries: list[AcceptedCommandId] = []
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != {"command_id", "accepted_at_utc"}:
            raise ValueError("Stored command ledger is invalid")
        entries.append(
            AcceptedCommandId(
                _uuid(raw["command_id"], "command_id"),
                _utc_z(raw["accepted_at_utc"], "accepted_at_utc"),
            )
        )
    if len({entry.command_id for entry in entries}) != len(entries):
        raise ValueError("Stored command ledger has duplicate IDs")
    if list(entries) != sorted(entries, key=lambda entry: entry.accepted_at_utc):
        raise ValueError("Stored command ledger is unordered")
    return prune_command_ledger(tuple(entries), now_utc)


def _json_object(payload: str | bytes | object, name: str) -> dict[str, object]:
    if isinstance(payload, (str, bytes)):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError, UnicodeDecodeError) as err:
            raise ValueError(f"{name} must be JSON") from err
    if not isinstance(payload, dict):
        raise ValueError(f"{name} must be an object")
    return payload


def _uuid(value: object, name: str) -> str:
    if not isinstance(value, str) or _UUID_PATTERN.fullmatch(value.strip()) is None:
        raise ValueError(f"{name} must be a UUID")
    return str(UUID(value.strip()))


def _utc_z(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{name} must be explicit UTC Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise ValueError(f"{name} must be explicit UTC Z") from err
    return _aware_utc(parsed, name)


def _utc_z_value(value: datetime, name: str) -> str:
    parsed = _aware_utc(value, name)
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _aware_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
        raise ValueError(f"{name} must be an integer")
    return value


def _finite(value: object, name: str) -> float:
    return _bounded(value, name, -MAX_ABSOLUTE_POWER_WATTS, MAX_ABSOLUTE_POWER_WATTS)


def _bounded(value: object, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{name} is outside range")
    return number

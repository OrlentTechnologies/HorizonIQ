"""Pure, bounded deterministic fault value model; it has no effect executor."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
import math
from typing import Mapping
from uuid import UUID, uuid4

FAULT_SCHEMA_VERSION = 1
MAX_FAULTS = 16
MAX_COUNT = 100
MAX_SHORT_COUNT = 10
MIN_DURATION_SECONDS = 1
MAX_DURATION_SECONDS = 900
MIN_DELAY_SECONDS = 0.1
MAX_DELAY_SECONDS = 60
FUTURE_DELAY_QUEUE_LIMIT = 100
MAX_REASON_LENGTH = 256


class FaultKind(StrEnum):
    STALE_TELEMETRY = "stale_telemetry"
    DROP_MQTT = "drop_mqtt"
    DELAY_MQTT = "delay_mqtt"
    MALFORMED_TELEMETRY = "malformed_telemetry"
    REPLAY_API_FAILURE = "replay_api_failure"
    REJECT_COMMAND = "reject_command"
    MQTT_DISCONNECT = "mqtt_disconnect"
    RUNTIME_RESTART = "runtime_restart"


class FaultState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    EXHAUSTED = "exhausted"
    CLEARED = "cleared"


_TIMED = frozenset({FaultKind.STALE_TELEMETRY, FaultKind.MQTT_DISCONNECT})
_COUNTED = frozenset(set(FaultKind) - _TIMED)
_SHORT_COUNT = frozenset({FaultKind.MALFORMED_TELEMETRY, FaultKind.RUNTIME_RESTART})
_FIELDS = {
    "version", "fault_id", "kind", "state", "activation_utc", "remaining_count",
    "remaining_duration_seconds", "settings", "last_transition_reason",
}


@dataclass(frozen=True, slots=True)
class Fault:
    """One validated fault definition and local lifecycle value."""
    fault_id: str
    kind: FaultKind
    state: FaultState
    activation_utc: datetime
    remaining_count: int | None
    remaining_duration_seconds: float | None
    settings: tuple[tuple[str, float], ...]
    last_transition_reason: str | None = None
    version: int = FAULT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version, "fault_id": self.fault_id, "kind": self.kind.value,
            "state": self.state.value, "activation_utc": _utc_z(self.activation_utc),
            "remaining_count": self.remaining_count,
            "remaining_duration_seconds": self.remaining_duration_seconds,
            "settings": dict(self.settings), "last_transition_reason": self.last_transition_reason,
        }


def configure_fault(
    *, kind: FaultKind | str, activation_utc: datetime, remaining_count: int | None = None,
    remaining_duration_seconds: float | None = None, settings: Mapping[str, object] | None = None,
    fault_id: str | None = None, reason: str | None = "configured",
) -> Fault:
    parsed_kind = FaultKind(kind)
    count, duration, normalized = _validate_parts(
        parsed_kind, remaining_count, remaining_duration_seconds, settings or {}
    )
    return Fault(_uuid(fault_id or str(uuid4())), parsed_kind, FaultState.PENDING,
                 _utc(activation_utc), count, duration, normalized, _reason(reason))


def activate_fault(fault: Fault, now_utc: datetime, reason: str | None = "activated") -> Fault:
    _validate_fault(fault)
    if fault.state is not FaultState.PENDING or _utc(now_utc) < fault.activation_utc:
        raise ValueError("Fault cannot activate")
    return replace(fault, state=FaultState.ACTIVE, last_transition_reason=_reason(reason))


def consume_fault_event(fault: Fault, reason: str | None = "event consumed") -> Fault:
    _validate_fault(fault)
    if fault.state is not FaultState.ACTIVE or fault.remaining_count is None:
        raise ValueError("Fault cannot consume an event")
    remaining = fault.remaining_count - 1
    return replace(fault, remaining_count=remaining,
                   state=FaultState.EXHAUSTED if remaining == 0 else FaultState.ACTIVE,
                   last_transition_reason=_reason(reason))


def advance_fault_duration(fault: Fault, seconds: float, reason: str | None = "duration advanced") -> Fault:
    _validate_fault(fault)
    value = _number(seconds, "Duration advance")
    if value < 0 or fault.state is not FaultState.ACTIVE or fault.remaining_duration_seconds is None:
        raise ValueError("Fault duration cannot advance")
    remaining = max(0.0, fault.remaining_duration_seconds - value)
    return replace(fault, remaining_duration_seconds=remaining,
                   state=FaultState.EXHAUSTED if remaining == 0 else FaultState.ACTIVE,
                   last_transition_reason=_reason(reason))


def exhaust_fault(fault: Fault, reason: str | None = "exhausted") -> Fault:
    _validate_fault(fault)
    if fault.state in {FaultState.CLEARED, FaultState.EXHAUSTED}:
        raise ValueError("Fault cannot exhaust")
    return replace(fault, state=FaultState.EXHAUSTED, remaining_count=0 if fault.remaining_count is not None else None,
                   remaining_duration_seconds=0.0 if fault.remaining_duration_seconds is not None else None,
                   last_transition_reason=_reason(reason))


def clear_fault(fault: Fault, reason: str | None = "cleared") -> Fault:
    _validate_fault(fault)
    if fault.state is FaultState.CLEARED:
        raise ValueError("Fault is already cleared")
    return replace(fault, state=FaultState.CLEARED, last_transition_reason=_reason(reason))


def clear_all_faults(faults: tuple[Fault, ...]) -> tuple[Fault, ...]:
    return tuple(fault if fault.state is FaultState.CLEARED else clear_fault(fault) for fault in faults)


def validate_faults(value: object) -> tuple[Fault, ...]:
    if not isinstance(value, list) or len(value) > MAX_FAULTS:
        raise ValueError("Fault list is invalid")
    faults = tuple(_from_dict(item) for item in value)
    if len({fault.fault_id for fault in faults}) != len(faults):
        raise ValueError("Fault IDs must be unique")
    active_kinds = [fault.kind for fault in faults if fault.state is not FaultState.CLEARED]
    if len(set(active_kinds)) != len(active_kinds):
        raise ValueError("Only one non-cleared fault of each kind is allowed")
    return faults


def outbound_mqtt_precedence() -> tuple[FaultKind, ...]:
    """Future executor precedence only; C1 does not apply any fault."""
    return (FaultKind.MQTT_DISCONNECT, FaultKind.DROP_MQTT, FaultKind.DELAY_MQTT,
            FaultKind.MALFORMED_TELEMETRY)


def _from_dict(value: object) -> Fault:
    if not isinstance(value, Mapping) or set(value) != _FIELDS or value.get("version") != FAULT_SCHEMA_VERSION:
        raise ValueError("Fault data is invalid")
    try:
        fault = Fault(
            _uuid(value["fault_id"]), FaultKind(value["kind"]), FaultState(value["state"]),
            _parse_utc(value["activation_utc"]), value["remaining_count"], value["remaining_duration_seconds"],
            _settings(value["settings"]), _reason(value["last_transition_reason"]), value["version"],
        )
    except (TypeError, ValueError) as err:
        raise ValueError("Fault data is invalid") from err
    _validate_fault(fault)
    return fault


def _validate_fault(fault: Fault) -> None:
    if fault.version != FAULT_SCHEMA_VERSION:
        raise ValueError("Fault version is invalid")
    _uuid(fault.fault_id); _utc(fault.activation_utc); _reason(fault.last_transition_reason)
    validation_count = 1 if fault.state is FaultState.EXHAUSTED and fault.remaining_count == 0 else fault.remaining_count
    validation_duration = 1.0 if fault.state is FaultState.EXHAUSTED and fault.remaining_duration_seconds == 0 else fault.remaining_duration_seconds
    _validate_parts(fault.kind, validation_count, validation_duration, dict(fault.settings))
    if fault.state is FaultState.EXHAUSTED and not (
        fault.remaining_count == 0 or fault.remaining_duration_seconds == 0
    ):
        raise ValueError("Exhausted fault has remaining work")
    if fault.state in {FaultState.PENDING, FaultState.ACTIVE} and (
        fault.remaining_count == 0 or fault.remaining_duration_seconds == 0
    ):
        raise ValueError("Active fault has no remaining work")


def _validate_parts(kind: FaultKind, count: object, duration: object, settings: Mapping[str, object]) -> tuple[int | None, float | None, tuple[tuple[str, float], ...]]:
    if kind in _COUNTED:
        if duration is not None or isinstance(count, bool) or not isinstance(count, int):
            raise ValueError("Count fault configuration is invalid")
        maximum = MAX_SHORT_COUNT if kind in _SHORT_COUNT else MAX_COUNT
        if not 1 <= count <= maximum:
            raise ValueError("Fault event count is invalid")
        expected = {"delay_seconds"} if kind is FaultKind.DELAY_MQTT else set()
        normalized = _settings(settings)
        if set(dict(normalized)) != expected:
            raise ValueError("Fault settings are invalid")
        if kind is FaultKind.DELAY_MQTT and not MIN_DELAY_SECONDS <= dict(normalized)["delay_seconds"] <= MAX_DELAY_SECONDS:
            raise ValueError("MQTT delay is invalid")
        return count, None, normalized
    if count is not None or duration is None or set(settings):
        raise ValueError("Timed fault configuration is invalid")
    value = _number(duration, "Fault duration")
    if not MIN_DURATION_SECONDS <= value <= MAX_DURATION_SECONDS:
        raise ValueError("Fault duration is invalid")
    return None, value, ()


def _settings(value: object) -> tuple[tuple[str, float], ...]:
    if not isinstance(value, Mapping): raise ValueError("Fault settings are invalid")
    return tuple(sorted((str(key), _number(item, "Fault setting")) for key, item in value.items()))
def _number(value: object, name: str) -> float:
    if isinstance(value, bool): raise ValueError(f"{name} is invalid")
    try: number = float(value)
    except (TypeError, ValueError) as err: raise ValueError(f"{name} is invalid") from err
    if not math.isfinite(number): raise ValueError(f"{name} is invalid")
    return number
def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None: raise ValueError("Activation time is invalid")
    return value.astimezone(timezone.utc)
def _utc_z(value: datetime) -> str: return _utc(value).isoformat().replace("+00:00", "Z")
def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"): raise ValueError("Activation time is invalid")
    return _utc(datetime.fromisoformat(value[:-1] + "+00:00"))
def _uuid(value: object) -> str:
    try: parsed = UUID(str(value))
    except (TypeError, ValueError) as err: raise ValueError("Fault ID is invalid") from err
    if str(parsed) != value: raise ValueError("Fault ID is invalid")
    return str(parsed)
def _reason(value: object) -> str | None:
    if value is None: return None
    if not isinstance(value, str) or len(value) > MAX_REASON_LENGTH: raise ValueError("Fault reason is invalid")
    return value

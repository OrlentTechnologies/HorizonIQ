"""Pure frozen MQTT status contracts for generated HorizonIQ sandboxes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import math
import re
from typing import Mapping

from .topics import is_sandbox_gx_id


RUNTIME_STATUS_SCHEMA_VERSION = 1
SIMULATOR_STATUS_SCHEMA_VERSION = 2
FAULTS_STATUS_SCHEMA_VERSION = 2
MAX_ABSOLUTE_POWER_WATTS = 100_000.0
MAX_BATTERY_ENERGY_WH = 2_000_000.0
MAX_ENERGY_BALANCE_ERROR_WH = 2_000_000.0
MAX_STATUS_REASON_LENGTH = 240
MAX_STATUS_FAULTS = 16
MAX_FAULT_REMAINING_COUNT = 1_000_000
MAX_FAULT_REMAINING_SECONDS = 86_400

_RUNTIME_FIELDS = {"schemaVersion", "gxDeviceId", "timestampUtc", "state", "reason"}
_SIMULATOR_FIELDS = {
    "schemaVersion",
    "gxDeviceId",
    "timestampUtc",
    "state",
    "reason",
    "virtualTimeUtc",
    "playbackState",
    "operatingState",
    "socPercent",
    "batteryEnergyWh",
    "batteryPowerW",
    "gridPowerW",
    "energyBalanceHealthy",
    "energyBalanceErrorWh",
    "mqttState",
    "replayState",
    "commandState",
}
_FAULTS_FIELDS = {"schemaVersion", "gxDeviceId", "timestampUtc", "state", "reason", "faults"}
_FAULT_FIELDS = {"kind", "state", "remainingCount", "remainingSeconds"}
_STRUCTURED_REASON = re.compile(r"\b[a-z][a-z0-9_-]*\s*[:=]", re.IGNORECASE)
_SECRET_REASON = re.compile(r"\b(?:credential|password|secret|api[_ -]?key|token)\b", re.IGNORECASE)


class SimulatorStatusState(StrEnum):
    """Frozen simulator health/lifecycle state vocabulary."""

    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"
    PAUSED = "paused"
    RUNNING = "running"
    UNHEALTHY = "unhealthy"


class PlaybackStatusState(StrEnum):
    """Frozen local playback state vocabulary."""

    NONE = "none"
    PAUSED = "paused"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class MqttStatusState(StrEnum):
    """Frozen local MQTT bridge state vocabulary."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FAULTED = "faulted"


class ReplayStatusState(StrEnum):
    """Frozen replay-session summary vocabulary."""

    NONE = "none"
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class CommandStatusState(StrEnum):
    """Frozen command-session summary vocabulary."""

    NONE = "none"
    RECEIVED = "received"
    APPLIED = "applied"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"


class FaultEnvelopeState(StrEnum):
    """Frozen fault-summary envelope state vocabulary."""

    CLEAR = "clear"
    ACTIVE = "active"


class FaultLifecycleStatusState(StrEnum):
    """Frozen per-fault lifecycle vocabulary."""

    CONFIGURED = "configured"
    ACTIVE = "active"
    EXHAUSTED = "exhausted"
    CLEARED = "cleared"


class FaultStatusKind(StrEnum):
    """Frozen per-fault kinds; no arbitrary MQTT target is representable."""

    STALE_TELEMETRY = "stale_telemetry"
    DROP_MQTT = "drop_mqtt"
    DELAY_MQTT = "delay_mqtt"
    MALFORMED_TELEMETRY = "malformed_telemetry"
    MQTT_DISCONNECT = "mqtt_disconnect"
    REPLAY_API_FAILURE = "replay_api_failure"
    REJECT_COMMAND = "reject_command"
    RUNTIME_RESTART = "runtime_restart"


@dataclass(frozen=True, slots=True)
class RuntimeStatus:
    """One exact Node-RED-owned schema-1 status retained only in memory."""

    gx_device_id: str
    timestamp_utc: datetime
    state: str
    reason: str


@dataclass(frozen=True, slots=True)
class SimulatorStatus:
    """One exact HA-owned schema-2 simulator status."""

    gx_device_id: str
    timestamp_utc: datetime
    state: SimulatorStatusState
    reason: str | None
    virtual_time_utc: datetime | None
    playback_state: PlaybackStatusState | None
    operating_state: int | None
    soc_percent: float | None
    battery_energy_wh: float | None
    battery_power_w: float | None
    grid_power_w: float | None
    energy_balance_healthy: bool | None
    energy_balance_error_wh: float | None
    mqtt_state: MqttStatusState | None
    replay_state: ReplayStatusState | None
    command_state: CommandStatusState | None

    def to_payload(self) -> dict[str, object]:
        """Serialize the exact frozen simulator status JSON shape."""
        return {
            "schemaVersion": SIMULATOR_STATUS_SCHEMA_VERSION,
            "gxDeviceId": self.gx_device_id,
            "timestampUtc": _utc_z(self.timestamp_utc),
            "state": self.state.value,
            "reason": self.reason,
            "virtualTimeUtc": _nullable_utc_z(self.virtual_time_utc),
            "playbackState": _nullable_value(self.playback_state),
            "operatingState": self.operating_state,
            "socPercent": self.soc_percent,
            "batteryEnergyWh": self.battery_energy_wh,
            "batteryPowerW": self.battery_power_w,
            "gridPowerW": self.grid_power_w,
            "energyBalanceHealthy": self.energy_balance_healthy,
            "energyBalanceErrorWh": self.energy_balance_error_wh,
            "mqttState": _nullable_value(self.mqtt_state),
            "replayState": _nullable_value(self.replay_state),
            "commandState": _nullable_value(self.command_state),
        }

    @property
    def semantic_key(self) -> tuple[object, ...]:
        """Return every semantic field except publication timestamp."""
        return tuple(value for key, value in self.to_payload().items() if key != "timestampUtc")


@dataclass(frozen=True, slots=True)
class FaultStatusItem:
    """One bounded, non-sensitive schema-2 fault status item."""

    kind: FaultStatusKind
    state: FaultLifecycleStatusState
    remaining_count: int | None
    remaining_seconds: int | None

    def to_payload(self) -> dict[str, object]:
        """Serialize the exact frozen fault item JSON shape."""
        return {
            "kind": self.kind.value,
            "state": self.state.value,
            "remainingCount": self.remaining_count,
            "remainingSeconds": self.remaining_seconds,
        }


@dataclass(frozen=True, slots=True)
class FaultsStatus:
    """One exact HA-owned schema-2 fault status."""

    gx_device_id: str
    timestamp_utc: datetime
    state: FaultEnvelopeState
    reason: str | None
    faults: tuple[FaultStatusItem, ...]

    def to_payload(self) -> dict[str, object]:
        """Serialize the exact frozen faults status JSON shape."""
        return {
            "schemaVersion": FAULTS_STATUS_SCHEMA_VERSION,
            "gxDeviceId": self.gx_device_id,
            "timestampUtc": _utc_z(self.timestamp_utc),
            "state": self.state.value,
            "reason": self.reason,
            "faults": [fault.to_payload() for fault in self.faults],
        }

    @property
    def semantic_key(self) -> tuple[object, ...]:
        """Return every semantic field except publication timestamp."""
        return tuple(value for key, value in self.to_payload().items() if key != "timestampUtc")


def build_simulator_status(**kwargs: object) -> SimulatorStatus:
    """Strictly validate trusted local values into a simulator status."""
    return _parse_simulator_status(kwargs)


def parse_simulator_status(value: object) -> SimulatorStatus:
    """Strictly parse a schema-2 simulator status payload."""
    if not isinstance(value, Mapping):
        raise ValueError("Simulator status fields are invalid")
    return _parse_simulator_status(value)


def build_faults_status(**kwargs: object) -> FaultsStatus:
    """Strictly validate trusted local values into a faults status."""
    return _parse_faults_status(kwargs)


def parse_faults_status(value: object) -> FaultsStatus:
    """Strictly parse a schema-2 faults status payload."""
    if not isinstance(value, Mapping):
        raise ValueError("Faults status fields are invalid")
    return _parse_faults_status(value)


def parse_runtime_status(value: object, *, owning_gx_device_id: str) -> RuntimeStatus:
    """Strictly parse an inbound Node-RED-owned schema-1 status."""
    if not isinstance(value, Mapping) or set(value) != _RUNTIME_FIELDS:
        raise ValueError("Runtime status fields are invalid")
    if value["schemaVersion"] != RUNTIME_STATUS_SCHEMA_VERSION:
        raise ValueError("Runtime status schema version is unsupported")
    gx_device_id = _gx_id(value["gxDeviceId"])
    if gx_device_id != owning_gx_device_id:
        raise ValueError("Runtime status GX ID does not match")
    return RuntimeStatus(
        gx_device_id=gx_device_id,
        timestamp_utc=_parse_utc_z(value["timestampUtc"]),
        state=_runtime_state(value["state"]),
        reason=_runtime_reason(value["reason"]),
    )


def _parse_simulator_status(value: Mapping[str, object]) -> SimulatorStatus:
    if set(value) != _SIMULATOR_FIELDS:
        raise ValueError("Simulator status fields are invalid")
    if value["schemaVersion"] != SIMULATOR_STATUS_SCHEMA_VERSION:
        raise ValueError("Simulator status schema version is unsupported")
    healthy = value["energyBalanceHealthy"]
    if healthy is not None and not isinstance(healthy, bool):
        raise ValueError("Simulator energy balance health is invalid")
    return SimulatorStatus(
        gx_device_id=_gx_id(value["gxDeviceId"]),
        timestamp_utc=_parse_utc_z(value["timestampUtc"]),
        state=_enum(value["state"], SimulatorStatusState, "Simulator state"),
        reason=_diagnostic_reason(value["reason"]),
        virtual_time_utc=_nullable_utc(value["virtualTimeUtc"]),
        playback_state=_nullable_enum(value["playbackState"], PlaybackStatusState, "Playback state"),
        operating_state=_nullable_integer(value["operatingState"], 0, 2, "Operating state"),
        soc_percent=_nullable_number(value["socPercent"], 0, 100, "State of charge"),
        battery_energy_wh=_nullable_number(
            value["batteryEnergyWh"], 0, MAX_BATTERY_ENERGY_WH, "Battery energy"
        ),
        battery_power_w=_nullable_number(
            value["batteryPowerW"], -MAX_ABSOLUTE_POWER_WATTS, MAX_ABSOLUTE_POWER_WATTS, "Battery power"
        ),
        grid_power_w=_nullable_number(
            value["gridPowerW"], -MAX_ABSOLUTE_POWER_WATTS, MAX_ABSOLUTE_POWER_WATTS, "Grid power"
        ),
        energy_balance_healthy=healthy,
        energy_balance_error_wh=_nullable_number(
            value["energyBalanceErrorWh"],
            -MAX_ENERGY_BALANCE_ERROR_WH,
            MAX_ENERGY_BALANCE_ERROR_WH,
            "Energy balance error",
        ),
        mqtt_state=_nullable_enum(value["mqttState"], MqttStatusState, "MQTT state"),
        replay_state=_nullable_enum(value["replayState"], ReplayStatusState, "Replay state"),
        command_state=_nullable_enum(value["commandState"], CommandStatusState, "Command state"),
    )


def _parse_faults_status(value: Mapping[str, object]) -> FaultsStatus:
    if set(value) != _FAULTS_FIELDS:
        raise ValueError("Faults status fields are invalid")
    if value["schemaVersion"] != FAULTS_STATUS_SCHEMA_VERSION:
        raise ValueError("Faults status schema version is unsupported")
    raw_faults = value["faults"]
    if not isinstance(raw_faults, (list, tuple)) or len(raw_faults) > MAX_STATUS_FAULTS:
        raise ValueError("Fault status items are invalid")
    faults = tuple(_parse_fault_item(item) for item in raw_faults)
    if len({fault.kind for fault in faults}) != len(faults):
        raise ValueError("Fault status kinds must be unique")
    state = _enum(value["state"], FaultEnvelopeState, "Fault status state")
    if (state is FaultEnvelopeState.CLEAR and faults) or (
        state is FaultEnvelopeState.ACTIVE and not faults
    ):
        raise ValueError("Fault status envelope is invalid")
    return FaultsStatus(
        gx_device_id=_gx_id(value["gxDeviceId"]),
        timestamp_utc=_parse_utc_z(value["timestampUtc"]),
        state=state,
        reason=_diagnostic_reason(value["reason"]),
        faults=faults,
    )


def _parse_fault_item(value: object) -> FaultStatusItem:
    if not isinstance(value, Mapping) or set(value) != _FAULT_FIELDS:
        raise ValueError("Fault status item is invalid")
    return FaultStatusItem(
        kind=_enum(value["kind"], FaultStatusKind, "Fault kind"),
        state=_enum(value["state"], FaultLifecycleStatusState, "Fault state"),
        remaining_count=_nullable_integer(
            value["remainingCount"], 0, MAX_FAULT_REMAINING_COUNT, "Fault remaining count"
        ),
        remaining_seconds=_nullable_integer(
            value["remainingSeconds"], 0, MAX_FAULT_REMAINING_SECONDS, "Fault remaining seconds"
        ),
    )


def _gx_id(value: object) -> str:
    if not isinstance(value, str) or not is_sandbox_gx_id(value):
        raise ValueError("Runtime status GX ID is invalid")
    return value


def _runtime_state(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 80:
        raise ValueError("Runtime status state is invalid")
    return value


def _runtime_reason(value: object) -> str:
    if not isinstance(value, str) or len(value) > MAX_STATUS_REASON_LENGTH:
        raise ValueError("Runtime status reason is invalid")
    return value


def _diagnostic_reason(value: object) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_STATUS_REASON_LENGTH
        or re.search(r"[\r\n{}\[\]]", value)
        or _STRUCTURED_REASON.search(value)
        or _SECRET_REASON.search(value)
    ):
        raise ValueError("Status reason must be concise diagnostic text")
    return value


def _nullable_number(value: object, minimum: float, maximum: float, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} is invalid")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{name} is invalid")
    return number


def _nullable_integer(value: object, minimum: int, maximum: int, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} is invalid")
    return value


def _enum(value: object, enum: type[StrEnum], name: str) -> StrEnum:
    try:
        return enum(value)
    except (TypeError, ValueError) as err:
        raise ValueError(f"{name} is invalid") from err


def _nullable_enum(value: object, enum: type[StrEnum], name: str) -> StrEnum | None:
    return None if value is None else _enum(value, enum, name)


def _nullable_utc(value: object) -> datetime | None:
    return None if value is None else _parse_utc_z(value)


def _utc_z(value: datetime) -> str:
    return _utc_datetime(value).isoformat().replace("+00:00", "Z")


def _nullable_utc_z(value: datetime | None) -> str | None:
    return None if value is None else _utc_z(value)


def _nullable_value(value: StrEnum | None) -> str | None:
    return None if value is None else value.value


def _parse_utc_z(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("Runtime status timestamp must use UTC Z serialization")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as err:
        raise ValueError("Runtime status timestamp is invalid") from err
    if parsed.tzinfo != timezone.utc:
        raise ValueError("Runtime status timestamp is invalid")
    return parsed


def _utc_datetime(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Runtime status timestamp requires an explicit UTC offset")
    return value.astimezone(timezone.utc)

"""Pure contracts for the future sandbox Node-RED replay bridge.

This module intentionally has no Home Assistant, MQTT, filesystem, or network
imports.  B2B is responsible for wiring these validated values to a runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import hashlib
import json
import math
from typing import Mapping
from uuid import UUID, uuid4

from .local_profiles import HalfHourReplayInput
from .models import BatteryConfig


REPLAY_REQUEST_SCHEMA_VERSION = 1
FORECAST_STATUS_SCHEMA_VERSION = 4
REPLAY_SESSION_SCHEMA_VERSION = 1
SIMULATED_REPLAY_API_FAILURE_REASON = "simulated_api_failure"
MAX_REPLAY_PERIODS = 1_488
MAX_REPLAY_REQUEST_BYTES = 1_048_576
MAX_STATUS_REASON_LENGTH = 240
_HALF_HOUR = timedelta(minutes=30)
_REQUEST_REQUIRED_FIELDS = {
    "schemaVersion",
    "replayId",
    "effectiveAtUtc",
    "startingBatteryEnergyKwh",
    "importForExportEnabled",
    "exportForSolarHeadroom",
    "periods",
}
_REQUEST_OPTIONAL_FIELDS = {"simulateApiFailure"}
_PERIOD_FIELDS = {
    "validFromUtc",
    "validToUtc",
    "importRateGbpPerKwh",
    "exportRateGbpPerKwh",
    "expectedLoadKwh",
    "expectedSolarKwh",
}
_STATUS_FIELDS = {"schemaVersion", "gxDeviceId", "replayId", "state", "reason"}
_CLOCK_FIELDS = {"schemaVersion", "gxDeviceId", "replayId", "virtualTimeUtc", "sequence", "reset"}
_SESSION_FIELDS = {
    "schema_version",
    "replay_id",
    "request_hash",
    "state",
    "clock_sequence",
    "last_remote_status",
    "last_remote_reason",
    "profile_identifier",
    "profile_hash",
}


class RemoteReplayState(StrEnum):
    """States that Node-RED may report for a requested replay."""

    LOADING = "loading"
    READY = "ready"
    REJECTED = "rejected"
    FAILED = "failed"


class ReplayState(StrEnum):
    """Local replay lifecycle state; no MQTT operation is implied."""

    IDLE = "idle"
    REQUESTING = "requesting"
    LOADING = "loading"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class ReplayPeriod:
    """One validated backend-compatible half-hour replay period."""

    valid_from_utc: datetime
    valid_to_utc: datetime
    import_rate_gbp_per_kwh: float
    export_rate_gbp_per_kwh: float
    expected_load_kwh: float
    expected_solar_kwh: float

    def to_payload(self) -> dict[str, object]:
        """Return the exact Node-RED/backend period JSON shape."""
        return {
            "validFromUtc": _utc_z(self.valid_from_utc),
            "validToUtc": _utc_z(self.valid_to_utc),
            "importRateGbpPerKwh": self.import_rate_gbp_per_kwh,
            "exportRateGbpPerKwh": self.export_rate_gbp_per_kwh,
            "expectedLoadKwh": self.expected_load_kwh,
            "expectedSolarKwh": self.expected_solar_kwh,
        }


@dataclass(frozen=True, slots=True)
class ReplayRequest:
    """Validated replay request, deliberately free of operational secrets."""

    replay_id: str
    effective_at_utc: datetime
    starting_battery_energy_kwh: float
    import_for_export_enabled: bool
    export_for_solar_headroom: bool
    periods: tuple[ReplayPeriod, ...]
    simulate_api_failure: bool = False

    def to_payload(self) -> dict[str, object]:
        """Return the exact schema-version 1 backend request payload."""
        payload: dict[str, object] = {
            "schemaVersion": REPLAY_REQUEST_SCHEMA_VERSION,
            "replayId": self.replay_id,
            "effectiveAtUtc": _utc_z(self.effective_at_utc),
            "startingBatteryEnergyKwh": self.starting_battery_energy_kwh,
            "importForExportEnabled": self.import_for_export_enabled,
            "exportForSolarHeadroom": self.export_for_solar_headroom,
            "periods": [period.to_payload() for period in self.periods],
        }
        if self.simulate_api_failure:
            payload["simulateApiFailure"] = True
        return payload


@dataclass(frozen=True, slots=True)
class RemoteReplayStatus:
    """One accepted, identity-bound Node-RED replay status payload."""

    state: RemoteReplayState
    reason: str | None


@dataclass(frozen=True, slots=True)
class ClockStatus:
    """A local virtual-clock status message for a future bridge."""

    gx_device_id: str
    replay_id: str
    virtual_time_utc: datetime
    sequence: int
    reset: bool

    def to_payload(self) -> dict[str, object]:
        """Return the exact schema-version 4 clock status JSON shape."""
        return {
            "schemaVersion": FORECAST_STATUS_SCHEMA_VERSION,
            "gxDeviceId": self.gx_device_id,
            "replayId": self.replay_id,
            "virtualTimeUtc": _utc_z(self.virtual_time_utc),
            "sequence": self.sequence,
            "reset": self.reset,
        }


@dataclass(frozen=True, slots=True)
class ReplaySession:
    """Versioned local replay value data for B2B Store integration."""

    replay_id: str
    request_hash: str
    state: ReplayState
    clock_sequence: int
    last_remote_status: RemoteReplayState | None
    last_remote_reason: str | None
    profile_identifier: str | None
    profile_hash: str | None
    schema_version: int = REPLAY_SESSION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        """Serialize only local replay identity and status value data."""
        return {
            "schema_version": self.schema_version,
            "replay_id": self.replay_id,
            "request_hash": self.request_hash,
            "state": self.state.value,
            "clock_sequence": self.clock_sequence,
            "last_remote_status": (
                self.last_remote_status.value if self.last_remote_status is not None else None
            ),
            "last_remote_reason": self.last_remote_reason,
            "profile_identifier": self.profile_identifier,
            "profile_hash": self.profile_hash,
        }

    @classmethod
    def from_dict(cls, value: object) -> ReplaySession:
        """Strictly parse versioned local value data without Store access."""
        if not isinstance(value, Mapping) or set(value) != _SESSION_FIELDS:
            raise ValueError("Replay session fields are invalid")
        if value["schema_version"] != REPLAY_SESSION_SCHEMA_VERSION:
            raise ValueError("Replay session schema version is unsupported")
        replay_id = _uuid_string(value["replay_id"], "Replay ID")
        request_hash = _sha256(value["request_hash"], "Request hash")
        try:
            state = ReplayState(value["state"])
        except (TypeError, ValueError) as err:
            raise ValueError("Replay state is invalid") from err
        sequence = value["clock_sequence"]
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ValueError("Clock sequence is invalid")
        remote_value = value["last_remote_status"]
        try:
            remote_state = None if remote_value is None else RemoteReplayState(remote_value)
        except (TypeError, ValueError) as err:
            raise ValueError("Remote replay state is invalid") from err
        reason = _reason(value["last_remote_reason"])
        profile_identifier = _optional_text(value["profile_identifier"], "Profile identifier")
        profile_hash = (
            None if value["profile_hash"] is None else _sha256(value["profile_hash"], "Profile hash")
        )
        if (profile_identifier is None) != (profile_hash is None):
            raise ValueError("Profile identity is incomplete")
        return cls(
            replay_id=replay_id,
            request_hash=request_hash,
            state=state,
            clock_sequence=sequence,
            last_remote_status=remote_state,
            last_remote_reason=reason,
            profile_identifier=profile_identifier,
            profile_hash=profile_hash,
        )


class ReplayIdentityRegistry:
    """In-memory duplicate guard for one runtime's replay request identities."""

    def __init__(self) -> None:
        self._hashes: dict[str, str] = {}

    def register(self, request: ReplayRequest) -> str:
        """Record a request or reject reuse of its ID with different content."""
        request_hash = request_hash_sha256(request)
        known_hash = self._hashes.get(request.replay_id)
        if known_hash is not None and known_hash != request_hash:
            raise ValueError("Replay ID cannot be reused with different content")
        self._hashes[request.replay_id] = request_hash
        return request_hash


def build_replay_request(
    *,
    periods: tuple[HalfHourReplayInput, ...],
    starting_battery_energy_wh: float,
    config: BatteryConfig,
    import_for_export_enabled: bool,
    export_for_solar_headroom: bool,
    simulate_api_failure: bool = False,
    replay_id: UUID | str | None = None,
) -> ReplayRequest:
    """Build a bounded, backend-compatible request from trusted local values."""
    if not isinstance(import_for_export_enabled, bool) or not isinstance(
        export_for_solar_headroom, bool
    ):
        raise ValueError("Registration replay settings must be boolean")
    if not isinstance(simulate_api_failure, bool):
        raise ValueError("Simulated API failure flag must be boolean")
    energy_wh = _finite_number(starting_battery_energy_wh, "Starting battery energy")
    if not config.reserve_wh <= energy_wh <= config.capacity_wh:
        raise ValueError("Starting battery energy is outside reserve and capacity")
    request = ReplayRequest(
        replay_id=_new_or_valid_replay_id(replay_id),
        effective_at_utc=_first_period_start(periods),
        starting_battery_energy_kwh=energy_wh / 1_000,
        import_for_export_enabled=import_for_export_enabled,
        export_for_solar_headroom=export_for_solar_headroom,
        periods=tuple(_period_from_input(item) for item in periods),
        simulate_api_failure=simulate_api_failure,
    )
    _validate_request(request)
    _validate_request_size(request)
    return request


def parse_replay_request(value: object, *, config: BatteryConfig) -> ReplayRequest:
    """Strictly parse a stored request, rejecting unknown and sensitive fields."""
    if not isinstance(value, Mapping) or not (
        _REQUEST_REQUIRED_FIELDS <= set(value)
        and set(value) <= _REQUEST_REQUIRED_FIELDS | _REQUEST_OPTIONAL_FIELDS
    ):
        raise ValueError("Replay request fields are invalid")
    if value["schemaVersion"] != REPLAY_REQUEST_SCHEMA_VERSION:
        raise ValueError("Replay request schema version is unsupported")
    replay_id = _uuid_string(value["replayId"], "Replay ID")
    effective_at = _parse_utc_z(value["effectiveAtUtc"], "Effective time")
    energy_kwh = _finite_number(value["startingBatteryEnergyKwh"], "Starting battery energy")
    energy_wh = energy_kwh * 1_000
    if not config.reserve_wh <= energy_wh <= config.capacity_wh:
        raise ValueError("Starting battery energy is outside reserve and capacity")
    if not isinstance(value["importForExportEnabled"], bool) or not isinstance(
        value["exportForSolarHeadroom"], bool
    ):
        raise ValueError("Replay settings are invalid")
    simulate_api_failure = value.get("simulateApiFailure", False)
    if not isinstance(simulate_api_failure, bool):
        raise ValueError("Simulated API failure flag is invalid")
    raw_periods = value["periods"]
    if not isinstance(raw_periods, list):
        raise ValueError("Replay periods are invalid")
    periods = tuple(_parse_period(item) for item in raw_periods)
    request = ReplayRequest(
        replay_id=replay_id,
        effective_at_utc=effective_at,
        starting_battery_energy_kwh=energy_kwh,
        import_for_export_enabled=value["importForExportEnabled"],
        export_for_solar_headroom=value["exportForSolarHeadroom"],
        periods=periods,
        simulate_api_failure=simulate_api_failure,
    )
    _validate_request(request)
    _validate_request_size(request)
    return request


def canonical_request_json(request: ReplayRequest) -> str:
    """Return HA-local canonical JSON used exclusively for local identity."""
    _validate_request(request)
    return json.dumps(request.to_payload(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def request_hash_sha256(request: ReplayRequest) -> str:
    """Return the deterministic HA-local SHA-256 identity for a request."""
    return hashlib.sha256(canonical_request_json(request).encode("utf-8")).hexdigest()


def validate_remote_status(
    value: object,
    *,
    owning_gx_device_id: str,
    active_replay_id: str,
) -> RemoteReplayStatus:
    """Validate an exact forecast-schema 4 status for the owning session."""
    if not isinstance(value, Mapping) or set(value) != _STATUS_FIELDS:
        raise ValueError("Replay status fields are invalid")
    if value["schemaVersion"] != FORECAST_STATUS_SCHEMA_VERSION:
        raise ValueError("Replay status schema version is unsupported")
    if value["gxDeviceId"] != owning_gx_device_id:
        raise ValueError("Replay status GX ID does not match")
    if _uuid_string(value["replayId"], "Replay ID") != active_replay_id:
        raise ValueError("Replay status ID does not match")
    try:
        state = RemoteReplayState(value["state"])
    except (TypeError, ValueError) as err:
        raise ValueError("Replay status state is invalid") from err
    return RemoteReplayStatus(state=state, reason=_reason(value["reason"]))


def create_replay_session(
    request: ReplayRequest,
    *,
    profile_identifier: str | None,
    profile_hash: str | None,
) -> ReplaySession:
    """Create an idle local value model for one validated request."""
    identifier = _optional_text(profile_identifier, "Profile identifier")
    content_hash = None if profile_hash is None else _sha256(profile_hash, "Profile hash")
    if (identifier is None) != (content_hash is None):
        raise ValueError("Profile identity is incomplete")
    return ReplaySession(
        replay_id=request.replay_id,
        request_hash=request_hash_sha256(request),
        state=ReplayState.IDLE,
        clock_sequence=0,
        last_remote_status=None,
        last_remote_reason=None,
        profile_identifier=identifier,
        profile_hash=content_hash,
    )


def start_replay_request(session: ReplaySession) -> ReplaySession:
    """Move an idle session to requesting for a future publisher."""
    return _transition(session, ReplayState.REQUESTING)


def apply_remote_status(session: ReplaySession, status: RemoteReplayStatus) -> ReplaySession:
    """Apply only legal in-order remote status changes to a local session."""
    target = ReplayState(status.state.value)
    allowed = {
        (ReplayState.REQUESTING, ReplayState.LOADING),
        (ReplayState.LOADING, ReplayState.READY),
        (ReplayState.REQUESTING, ReplayState.REJECTED),
        (ReplayState.LOADING, ReplayState.REJECTED),
        (ReplayState.REQUESTING, ReplayState.FAILED),
        (ReplayState.LOADING, ReplayState.FAILED),
    }
    if (session.state, target) not in allowed:
        raise ValueError("Replay status transition is invalid or stale")
    return replace(
        session,
        state=target,
        last_remote_status=status.state,
        last_remote_reason=status.reason,
    )


def transition_local_replay(session: ReplaySession, target: ReplayState) -> ReplaySession:
    """Perform one strict local lifecycle transition without external effects."""
    return _transition(session, target)


def stop_replay(session: ReplaySession) -> ReplaySession:
    """Stop any active replay state without emitting an executable command."""
    active = {
        ReplayState.REQUESTING,
        ReplayState.LOADING,
        ReplayState.READY,
        ReplayState.RUNNING,
        ReplayState.PAUSED,
    }
    if session.state not in active:
        raise ValueError("Only an active replay can be stopped")
    return replace(session, state=ReplayState.STOPPED)


def build_clock_status(
    *,
    gx_device_id: str,
    replay_id: str,
    virtual_time_utc: datetime,
    previous: ClockStatus | None = None,
    reset: bool = False,
) -> ClockStatus:
    """Build a reset or strictly monotonic local virtual-clock status message."""
    replay_id = _uuid_string(replay_id, "Replay ID")
    moment = _ensure_utc_datetime(virtual_time_utc, "Virtual time")
    if previous is None:
        if not reset:
            raise ValueError("The first clock status must be a reset")
        return ClockStatus(gx_device_id, replay_id, moment, 0, True)
    if previous.gx_device_id != gx_device_id or previous.replay_id != replay_id:
        raise ValueError("Clock status identity does not match")
    if reset:
        return ClockStatus(gx_device_id, replay_id, moment, 0, True)
    if moment < previous.virtual_time_utc:
        raise ValueError("Virtual time cannot move backwards without reset")
    return ClockStatus(gx_device_id, replay_id, moment, previous.sequence + 1, False)


def parse_clock_status(value: object) -> ClockStatus:
    """Strictly parse a local clock message for tests and persistence boundaries."""
    if not isinstance(value, Mapping) or set(value) != _CLOCK_FIELDS:
        raise ValueError("Clock status fields are invalid")
    if value["schemaVersion"] != FORECAST_STATUS_SCHEMA_VERSION:
        raise ValueError("Clock status schema version is unsupported")
    gx_device_id = value["gxDeviceId"]
    if not isinstance(gx_device_id, str) or not gx_device_id:
        raise ValueError("Clock GX ID is invalid")
    sequence = value["sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise ValueError("Clock sequence is invalid")
    reset = value["reset"]
    if not isinstance(reset, bool) or (reset and sequence != 0):
        raise ValueError("Clock reset is invalid")
    return ClockStatus(
        gx_device_id=gx_device_id,
        replay_id=_uuid_string(value["replayId"], "Replay ID"),
        virtual_time_utc=_parse_utc_z(value["virtualTimeUtc"], "Virtual time"),
        sequence=sequence,
        reset=reset,
    )


def _period_from_input(value: HalfHourReplayInput) -> ReplayPeriod:
    if not isinstance(value, HalfHourReplayInput):
        raise ValueError("Replay period is invalid")
    return ReplayPeriod(
        valid_from_utc=_ensure_utc_datetime(value.valid_from_utc, "Period start"),
        valid_to_utc=_ensure_utc_datetime(value.valid_to_utc, "Period end"),
        import_rate_gbp_per_kwh=_finite_number(value.import_rate_gbp_per_kwh, "Import rate"),
        export_rate_gbp_per_kwh=_finite_number(value.export_rate_gbp_per_kwh, "Export rate"),
        expected_load_kwh=_finite_number(value.expected_load_kwh, "Expected load"),
        expected_solar_kwh=_finite_number(value.expected_solar_kwh, "Expected solar"),
    )


def _parse_period(value: object) -> ReplayPeriod:
    if not isinstance(value, Mapping) or set(value) != _PERIOD_FIELDS:
        raise ValueError("Replay period fields are invalid")
    return ReplayPeriod(
        valid_from_utc=_parse_utc_z(value["validFromUtc"], "Period start"),
        valid_to_utc=_parse_utc_z(value["validToUtc"], "Period end"),
        import_rate_gbp_per_kwh=_finite_number(value["importRateGbpPerKwh"], "Import rate"),
        export_rate_gbp_per_kwh=_finite_number(value["exportRateGbpPerKwh"], "Export rate"),
        expected_load_kwh=_finite_number(value["expectedLoadKwh"], "Expected load"),
        expected_solar_kwh=_finite_number(value["expectedSolarKwh"], "Expected solar"),
    )


def _validate_request(request: ReplayRequest) -> None:
    _uuid_string(request.replay_id, "Replay ID")
    if not isinstance(request.simulate_api_failure, bool):
        raise ValueError("Simulated API failure flag is invalid")
    if not request.periods or len(request.periods) > MAX_REPLAY_PERIODS:
        raise ValueError("Replay horizon size is invalid")
    if request.effective_at_utc != request.periods[0].valid_from_utc:
        raise ValueError("Effective time must equal the first period start")
    for index, period in enumerate(request.periods):
        if period.valid_to_utc - period.valid_from_utc != _HALF_HOUR:
            raise ValueError("Replay periods must be complete half hours")
        if index and request.periods[index - 1].valid_to_utc != period.valid_from_utc:
            raise ValueError("Replay periods must be contiguous")
        if period.export_rate_gbp_per_kwh < 0:
            raise ValueError("Export rate must be non-negative")
        if period.expected_load_kwh < 0 or period.expected_solar_kwh < 0:
            raise ValueError("Expected energy must be non-negative")


def _validate_request_size(request: ReplayRequest) -> None:
    encoded = json.dumps(
        request.to_payload(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    if len(encoded) > MAX_REPLAY_REQUEST_BYTES:
        raise ValueError("Replay request exceeds 1 MiB")


def _first_period_start(periods: tuple[HalfHourReplayInput, ...]) -> datetime:
    if not periods:
        raise ValueError("Replay periods are required")
    return _ensure_utc_datetime(periods[0].valid_from_utc, "Period start")


def _new_or_valid_replay_id(value: UUID | str | None) -> str:
    if value is None:
        return str(uuid4())
    return _uuid_string(str(value), "Replay ID")


def _transition(session: ReplaySession, target: ReplayState) -> ReplaySession:
    allowed = {
        (ReplayState.IDLE, ReplayState.REQUESTING),
        (ReplayState.READY, ReplayState.RUNNING),
        (ReplayState.READY, ReplayState.PAUSED),
        (ReplayState.READY, ReplayState.COMPLETED),
        (ReplayState.RUNNING, ReplayState.PAUSED),
        (ReplayState.PAUSED, ReplayState.RUNNING),
        (ReplayState.RUNNING, ReplayState.COMPLETED),
        (ReplayState.PAUSED, ReplayState.COMPLETED),
    }
    if (session.state, target) not in allowed:
        raise ValueError("Replay lifecycle transition is invalid")
    return replace(session, state=target)


def _utc_z(value: datetime) -> str:
    return _ensure_utc_datetime(value, "UTC time").isoformat().replace("+00:00", "Z")


def _parse_utc_z(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{name} must use explicit UTC Z serialization")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as err:
        raise ValueError(f"{name} is invalid") from err
    if parsed.tzinfo != timezone.utc:
        raise ValueError(f"{name} is invalid")
    return parsed


def _ensure_utc_datetime(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} requires an explicit UTC offset")
    return value.astimezone(timezone.utc)


def _uuid_string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} is invalid")
    try:
        parsed = UUID(value)
    except (TypeError, ValueError, AttributeError) as err:
        raise ValueError(f"{name} is invalid") from err
    canonical = str(parsed)
    if value != canonical:
        raise ValueError(f"{name} must be canonical lowercase UUID text")
    return canonical


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} is invalid")
    try:
        number = float(value)
    except (TypeError, ValueError) as err:
        raise ValueError(f"{name} is invalid") from err
    if not math.isfinite(number):
        raise ValueError(f"{name} is invalid")
    return number


def _reason(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > MAX_STATUS_REASON_LENGTH:
        raise ValueError("Replay status reason is invalid")
    return value


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} is invalid")
    return value


def _sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{name} is invalid")
    try:
        int(value, 16)
    except ValueError as err:
        raise ValueError(f"{name} is invalid") from err
    if value.lower() != value:
        raise ValueError(f"{name} is invalid")
    return value

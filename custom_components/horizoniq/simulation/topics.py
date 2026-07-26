"""Pure, frozen MQTT vocabulary for generated HorizonIQ sandboxes only."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
import json
import math
import re


MAX_ABSOLUTE_POWER_WATTS = 100_000.0
_SANDBOX_GX_ID_PATTERN = re.compile(r"horizoniq-[0-9a-f]{32}")


class VictronTopicDirection(StrEnum):
    """The only supported Victron MQTT topic directions."""

    NOTIFICATION = "N"
    WRITE = "W"
    REQUEST = "R"


class VictronTelemetryKey(StrEnum):
    """Frozen sandbox Victron telemetry identifiers."""

    STATE_OF_CHARGE = "state_of_charge"
    INSTALLED_CAPACITY = "installed_capacity"
    BATTERY_POWER = "battery_power"
    GRID_POWER = "grid_power"
    LOAD_POWER = "load_power"
    SOLAR_POWER = "solar_power"
    VOLTAGE = "voltage"
    OPERATING_STATE = "operating_state"


class VictronCommandKey(StrEnum):
    """Frozen sandbox Victron write identifiers."""

    HUB4_MODE = "hub4_mode"
    VE_BUS_MODE = "ve_bus_mode"
    AC_POWER_SETPOINT = "ac_power_setpoint"


class VictronOperatingState(IntEnum):
    """Frozen numeric operating-state values."""

    IDLE = 0
    SELF_CONSUMPTION = 1
    GRID_SETPOINT = 2


@dataclass(frozen=True, slots=True)
class TelemetryDefinition:
    """One fixed telemetry suffix and its allowed numeric range."""

    suffix: str
    unit: str
    minimum: float
    maximum: float


VICTRON_TELEMETRY: dict[VictronTelemetryKey, TelemetryDefinition] = {
    VictronTelemetryKey.STATE_OF_CHARGE: TelemetryDefinition(
        "battery/512/Soc", "percent", 0.0, 100.0
    ),
    VictronTelemetryKey.INSTALLED_CAPACITY: TelemetryDefinition(
        "battery/512/InstalledCapacity", "Ah", 0.0, math.inf
    ),
    VictronTelemetryKey.BATTERY_POWER: TelemetryDefinition(
        "battery/Power", "W", -MAX_ABSOLUTE_POWER_WATTS, MAX_ABSOLUTE_POWER_WATTS
    ),
    VictronTelemetryKey.GRID_POWER: TelemetryDefinition(
        "grid/Power", "W", -MAX_ABSOLUTE_POWER_WATTS, MAX_ABSOLUTE_POWER_WATTS
    ),
    VictronTelemetryKey.LOAD_POWER: TelemetryDefinition(
        "system/Load", "W", 0.0, MAX_ABSOLUTE_POWER_WATTS
    ),
    VictronTelemetryKey.SOLAR_POWER: TelemetryDefinition(
        "solar/Power", "W", 0.0, MAX_ABSOLUTE_POWER_WATTS
    ),
    VictronTelemetryKey.VOLTAGE: TelemetryDefinition(
        "battery/Voltage", "V", math.ulp(1.0), 1_000.0
    ),
    VictronTelemetryKey.OPERATING_STATE: TelemetryDefinition(
        "system/OperatingState", "enum", 0.0, 2.0
    ),
}

VICTRON_COMMANDS: dict[VictronCommandKey, str] = {
    VictronCommandKey.HUB4_MODE: "settings/0/Settings/CGwacs/Hub4Mode",
    VictronCommandKey.VE_BUS_MODE: "vebus/274/Mode",
    VictronCommandKey.AC_POWER_SETPOINT: "settings/0/Settings/CGwacs/AcPowerSetPoint",
}
_REFRESH_SUFFIX = "keepalive"


def is_sandbox_gx_id(gx_id: str) -> bool:
    """Return whether an ID is the exact generated sandbox GX form."""
    return isinstance(gx_id, str) and _SANDBOX_GX_ID_PATTERN.fullmatch(gx_id) is not None


def telemetry_topic(gx_id: str, key: VictronTelemetryKey) -> str:
    """Build one exact frozen notification topic."""
    return victron_topic(VictronTopicDirection.NOTIFICATION, gx_id, VICTRON_TELEMETRY[key].suffix)


def command_topic(gx_id: str, key: VictronCommandKey) -> str:
    """Build one exact frozen write topic."""
    return victron_topic(VictronTopicDirection.WRITE, gx_id, VICTRON_COMMANDS[key])


def refresh_topic(gx_id: str) -> str:
    """Build the sole fixed Victron refresh topic."""
    return victron_topic(VictronTopicDirection.REQUEST, gx_id, _REFRESH_SUFFIX)


def victron_topic(direction: VictronTopicDirection, gx_id: str, path: str) -> str:
    """Build only a frozen Victron topic; arbitrary paths and wildcards fail closed."""
    if not is_sandbox_gx_id(gx_id):
        raise ValueError("A sandbox runtime requires a generated GX ID")
    allowed_paths = {
        VictronTopicDirection.NOTIFICATION: {
            definition.suffix for definition in VICTRON_TELEMETRY.values()
        },
        VictronTopicDirection.WRITE: set(VICTRON_COMMANDS.values()),
        VictronTopicDirection.REQUEST: {_REFRESH_SUFFIX},
    }
    if path not in allowed_paths[direction]:
        raise ValueError("A Victron topic must use a frozen non-wildcard suffix")
    return f"victron/{direction.value}/{gx_id}/{path}"


def telemetry_payload(key: VictronTelemetryKey, value: float | int) -> str:
    """Validate and serialize the exact frozen telemetry payload shape."""
    definition = VICTRON_TELEMETRY[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Telemetry value must be finite number")
    numeric_value = float(value)
    if not math.isfinite(numeric_value) or not definition.minimum <= numeric_value <= definition.maximum:
        raise ValueError("Telemetry value is outside the frozen range")
    if (
        key is VictronTelemetryKey.OPERATING_STATE
        and numeric_value not in {state.value for state in VictronOperatingState}
    ):
        raise ValueError("Operating state must use the frozen enum")
    return json.dumps({"value": value}, separators=(",", ":"))


def parse_victron_write_payload(payload: str | bytes) -> float:
    """Parse exactly one finite frozen Victron write value."""
    raw = json.loads(payload)
    if not isinstance(raw, dict) or set(raw) != {"value"}:
        raise ValueError("Victron write payload must contain only value")
    value = raw["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Victron write value must be finite number")
    numeric_value = float(value)
    if not math.isfinite(numeric_value) or abs(numeric_value) > MAX_ABSOLUTE_POWER_WATTS:
        raise ValueError("Victron write value is outside the frozen range")
    return numeric_value


def parse_refresh_payload(payload: str | bytes | None) -> None:
    """Accept only the frozen empty or empty-object refresh request."""
    if payload is None or payload == "" or payload == b"":
        return
    raw = json.loads(payload)
    if not isinstance(raw, dict) or raw:
        raise ValueError("Victron refresh payload must be empty")


def inbound_is_retained(message: object) -> bool:
    """Return true only for an explicitly retained inbound MQTT message."""
    return getattr(message, "retain", False) is True


def command_issued_topic(gx_id: str) -> str:
    """Build the sole canonical Node-RED command metadata topic."""
    return _local_sandbox_topic(gx_id, "commands/issued")


def command_status_topic(gx_id: str) -> str:
    """Build the sole canonical HA command-status topic."""
    return _local_sandbox_topic(gx_id, "commands/status")


def node_red_status_topic(gx_id: str) -> str:
    """Build the sole canonical Node-RED runtime-status topic."""
    return _local_sandbox_topic(gx_id, "node-red/status")


def simulator_status_topic(gx_id: str) -> str:
    """Build the sole canonical HA simulator-status topic."""
    return _local_sandbox_topic(gx_id, "simulator/status")


def faults_status_topic(gx_id: str) -> str:
    """Build the sole canonical HA fault-status topic."""
    return _local_sandbox_topic(gx_id, "faults/status")


def replay_request_topic(gx_id: str) -> str:
    """Build the isolated replay request topic."""
    return _local_sandbox_topic(gx_id, "replay/request")


def replay_status_topic(gx_id: str) -> str:
    """Build the isolated replay status topic."""
    return _local_sandbox_topic(gx_id, "replay/status")


def clock_status_topic(gx_id: str) -> str:
    """Build the isolated virtual-clock status topic."""
    return _local_sandbox_topic(gx_id, "clock/status")


def _local_sandbox_topic(gx_id: str, suffix: str) -> str:
    if not is_sandbox_gx_id(gx_id):
        raise ValueError("A sandbox runtime requires a generated GX ID")
    return f"horizoniq/sandbox/{gx_id}/{suffix}"

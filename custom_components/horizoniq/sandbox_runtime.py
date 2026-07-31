"""Entry-local lifecycle ownership for HorizonIQ virtual batteries."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CAPACITY_SOURCE_VIRTUAL_BATTERY,
    CONF_CAPACITY_SOURCE,
    CONF_ENVIRONMENT,
    CONF_REGISTRATION_CONFIG,
    CONF_REGISTRATION_ID,
    SANDBOX_ENVIRONMENT,
    normalize_environment,
)
from .simulation.clock import ClockRate, VirtualClock
from .simulation.models import (
    BatteryConfig,
    BatteryState,
    Command,
    CommandStatus,
    ClockState,
    IntervalLedger,
    OperatingMode,
    ProfileCursor,
    SimulationHealth,
    SimulationSnapshot,
)
from .simulation.physics import simulate_step
from .simulation.snapshots import from_json, to_json
from .simulation.topics import (
    VictronCommandKey,
    VictronOperatingState,
    VictronTelemetryKey,
    command_topic,
    command_issued_topic,
    command_status_topic,
    faults_status_topic,
    inbound_is_retained,
    node_red_status_topic,
    parse_refresh_payload,
    parse_victron_write_payload,
    replay_request_topic,
    replay_status_topic,
    simulator_status_topic,
    clock_status_topic,
    refresh_topic,
    telemetry_payload,
    telemetry_topic,
)
from .simulation.runtime_status import (
    CommandStatusState,
    FaultEnvelopeState,
    FaultLifecycleStatusState,
    FaultStatusItem,
    FaultStatusKind,
    FaultsStatus,
    MqttStatusState,
    PlaybackStatusState,
    ReplayStatusState,
    RuntimeStatus,
    SimulatorStatus,
    SimulatorStatusState,
    build_faults_status,
    build_simulator_status,
    parse_runtime_status,
)
from .simulation.command_lifecycle import (
    AcceptedCommandId,
    COMMAND_CORRELATION_TIMEOUT_SECONDS,
    CommandLifecycleState,
    IssuedCommand,
    accept_command_id,
    command_status_payload,
    ledger_from_storage,
    ledger_to_storage,
    parse_issued_command,
    prune_command_ledger,
)
from .direct_control import (
    DirectForecastRejection,
    parse_replay_command,
    validate_live_forecast,
)
from .models import Forecast
from .sandbox_storage import (
    MAX_NAMED_SNAPSHOTS,
    SNAPSHOT_SCHEMA_VERSION,
    STORAGE_SCHEMA_VERSION,
    SandboxStorage,
    record_mapping,
)
from .sandbox_profiles import SandboxProfileRepository
from .simulation.local_profiles import LocalSyntheticProfile, aggregate_half_hours
from .simulation.replay_contract import (
    ReplayRequest,
    ClockStatus,
    ReplaySession,
    ReplayState,
    SIMULATED_REPLAY_API_FAILURE_REASON,
    apply_remote_status,
    build_clock_status,
    build_replay_request,
    create_replay_session,
    start_replay_request,
    stop_replay,
    transition_local_replay,
    validate_remote_status,
)
from .simulation.faults import (
    Fault,
    FaultKind,
    FaultState,
    activate_fault,
    clear_all_faults,
    clear_fault,
    consume_fault_event,
    advance_fault_duration,
    configure_fault,
    validate_faults,
)

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .coordinator import HorizonIQCoordinator


_LOOP_INTERVAL_SECONDS = 1.0
_SNAPSHOT_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}")
_PLAYBACK_STATES = frozenset({"stopped", "paused", "running", "completed"})
_REPLAY_ACTIVE_STATES = frozenset(
    {ReplayState.REQUESTING, ReplayState.LOADING, ReplayState.READY}
)
_REPLAY_READINESS_TIMEOUT_SECONDS = 30
_REPLAY_TIMEOUT_REASON = "Replay readiness timed out."
_REPLAY_PUBLISH_FAILURE_REASON = "Replay request publication failed."
_REPLAY_CLOCK_PUBLISH_FAILURE_REASON = "Replay clock publication failed."
_REPLAY_HEARTBEAT_SECONDS = 30
_REPLAY_CLOCK_MINIMUM_INTERVAL_SECONDS = 1
MAX_BATTERY_ENERGY_WH = 2_000_000.0
MAX_ABSOLUTE_POWER_W = 100_000.0
_MAX_ENERGY_WH = MAX_BATTERY_ENERGY_WH
_MAX_POWER_W = MAX_ABSOLUTE_POWER_W


@dataclass(slots=True)
class _DelayedOutbound:
    topic: str
    payload: str
    retain: bool


def canonical_registration_id(value: object) -> str | None:
    """Return a stable canonical registration UUID, if one was supplied."""
    try:
        return str(UUID(str(value).strip()))
    except (TypeError, ValueError):
        return None


def pretend_gx_id(registration_id: str) -> str:
    """Derive a sandbox-only GX identity from a stable registration ID."""
    canonical = canonical_registration_id(registration_id)
    if canonical is None:
        raise ValueError("registration ID must be a UUID")
    return f"horizoniq-{UUID(canonical).hex}"


def registration_id_is_unique(
    entries: Iterable[ConfigEntry],
    registration_id: str,
    excluding_entry_id: str | None = None,
) -> bool:
    """Return whether no other HorizonIQ entry owns the registration."""
    canonical = canonical_registration_id(registration_id)
    return canonical is not None and all(
        entry.entry_id == excluding_entry_id
        or canonical_registration_id(entry.data.get(CONF_REGISTRATION_ID)) != canonical
        for entry in entries
    )


def _number(source: Mapping[str, object], *names: str) -> float:
    for name in names:
        value = source.get(name)
        if value is None:
            continue
        number = float(value)
        if math.isfinite(number):
            return number
    raise ValueError(names[0])


def simulator_config(data: Mapping[str, object]) -> tuple[BatteryConfig, str] | None:
    """Build virtual-battery configuration from a sandbox registration snapshot."""
    if (
        normalize_environment(str(data.get(CONF_ENVIRONMENT, "")))
        != SANDBOX_ENVIRONMENT
        or data.get(CONF_CAPACITY_SOURCE) != CAPACITY_SOURCE_VIRTUAL_BATTERY
    ):
        return None

    registration_id = canonical_registration_id(data.get(CONF_REGISTRATION_ID))
    profile = data.get(CONF_REGISTRATION_CONFIG)
    if registration_id is None or not isinstance(profile, Mapping):
        return None

    equipment = profile.get("EquipmentProfile") or profile.get("equipmentProfile")
    if not isinstance(equipment, Mapping):
        return None

    try:
        capacity = _number(equipment, "BatteryCapacityWh", "batteryCapacityWh")
        try:
            reserve = _number(equipment, "MinimumCapacityWh", "minimumCapacityWh")
        except ValueError:
            reserve = _number(
                equipment,
                "MinimumCapacityPercentage",
                "minimumCapacityPercentage",
                "MinimumCapacityRatio",
                "minimumCapacityRatio",
            ) * capacity
        config = BatteryConfig(
            capacity_wh=capacity,
            reserve_wh=reserve,
            max_charge_power_w=_number(
                equipment,
                "MaximumBatteryChargePowerWatts",
                "maximumBatteryChargePowerWatts",
            ),
            max_discharge_power_w=_number(
                equipment,
                "MaximumBatteryDischargePowerWatts",
                "maximumBatteryDischargePowerWatts",
            ),
            charge_efficiency=_number(profile, "ChargeEfficiency", "chargeEfficiency"),
            discharge_efficiency=_number(
                profile,
                "DischargeEfficiency",
                "dischargeEfficiency",
            ),
            nominal_voltage_v=_optional_number(
                equipment,
                48.0,
                "NominalBatteryVoltage",
                "nominalBatteryVoltage",
            ),
        )
    except (TypeError, ValueError):
        return None

    if (
        not 0 < config.capacity_wh <= _MAX_ENERGY_WH
        or not 0 <= config.reserve_wh <= config.capacity_wh
        or config.reserve_wh > _MAX_ENERGY_WH
        or not 0 <= config.max_charge_power_w <= _MAX_POWER_W
        or not 0 <= config.max_discharge_power_w <= _MAX_POWER_W
        or not 0 < config.charge_efficiency <= 1
        or not 0 < config.discharge_efficiency <= 1
        or not 0 < config.nominal_voltage_v <= 1_000
    ):
        return None
    return config, pretend_gx_id(registration_id)


def _optional_number(
    source: Mapping[str, object],
    default: float,
    *names: str,
) -> float:
    """Read an optional finite registration-owned number without coercing booleans."""
    for name in names:
        value = source.get(name)
        if value is None:
            continue
        if isinstance(value, bool):
            raise ValueError(name)
        number = float(value)
        if math.isfinite(number):
            return number
        raise ValueError(name)
    return default


@dataclass
class HorizonIQEntryRuntime:
    """Own all mutable sandbox state for exactly one config entry."""

    coordinator: HorizonIQCoordinator
    registration_id: str
    entry_id: str = ""
    pretend_gx_id: str | None = None
    simulator_enabled: bool = False
    available_reason: str | None = None
    load_w: float = 0.0
    solar_w: float = 0.0
    last_command_status: CommandStatus = CommandStatus.FALLBACK_MISSING
    last_command_reason: str | None = None
    last_health: SimulationHealth = SimulationHealth.HEALTHY
    _config: BatteryConfig | None = None
    _state: BatteryState | None = None
    _clock: VirtualClock | None = None
    _command: Command | None = None
    _cumulative_ledger: IntervalLedger = field(default_factory=IntervalLedger)
    _active_profile_id: str | None = None
    _profile_cursor: ProfileCursor | None = None
    _task: asyncio.Task[None] | None = None
    _hass: HomeAssistant | None = None
    _coordinator_paused: bool = False
    _mqtt_emulation_enabled: bool = False
    _direct_forecast_health: str = "unavailable"
    _last_direct_command_id: str | None = None
    _staged_direct_forecast: Forecast | None = None
    _direct_forecast_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _state_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _live_forecast_now: Callable[[], datetime] = field(
        default=lambda: datetime.now(timezone.utc)
    )
    _direct_replay_payload: Mapping[str, object] | None = None
    _last_direct_replay_key: str | None = None
    _unloaded: bool = False
    _storage: SandboxStorage | None = None
    _named_snapshots: dict[str, str] = field(default_factory=dict)
    storage_diagnostic: str | None = None
    _checkpoint_handle: asyncio.TimerHandle | None = None
    _profile_repository: SandboxProfileRepository | None = None
    _active_profile: LocalSyntheticProfile | None = None
    _selected_profile_filename: str | None = None
    _profile_hash: str | None = None
    _playback_state: str = "stopped"
    _unsubscribers: list[Callable[[], None]] = field(default_factory=list)
    _listeners: list[Callable[[], None]] = field(default_factory=list)
    _registration_config: Mapping[str, object] | None = None
    _replay_session: ReplaySession | None = None
    _replay_starting_energy_wh: float | None = None
    _replay_import_for_export_enabled: bool | None = None
    _replay_export_for_solar_headroom: bool | None = None
    _replay_simulate_api_failure: bool = False
    _replay_pending_resume: bool = False
    _replay_timeout_handle: asyncio.TimerHandle | None = None
    _prepared_replay_request: ReplayRequest | None = None
    _replay_start_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _last_replay_clock_status: ClockStatus | None = None
    _replay_last_clock_publish_monotonic: float | None = None
    _replay_heartbeat_handle: asyncio.TimerHandle | None = None
    _replay_auto_resume_pending: bool = False
    _replay_paused_rate: ClockRate | None = None
    _faults: tuple[Fault, ...] = ()
    _named_fault_snapshots: dict[str, tuple[Fault, ...]] = field(default_factory=dict)
    _fault_duration_handles: dict[str, asyncio.TimerHandle] = field(default_factory=dict)
    _fault_duration_deadlines: dict[str, float] = field(default_factory=dict)
    _fault_timer_generation: int = 0
    _fault_timer_generations: dict[str, int] = field(default_factory=dict)
    _delayed_outbound: list[_DelayedOutbound] = field(default_factory=list)
    _delayed_outbound_handle: asyncio.TimerHandle | None = None
    _mqtt_fault_disconnected: bool = False
    _accepted_command_ids: tuple[AcceptedCommandId, ...] = ()
    _pending_command: IssuedCommand | None = None
    _pending_command_writes: set[VictronCommandKey] = field(default_factory=set)
    _command_correlation_timeout_handle: asyncio.TimerHandle | None = None
    _last_grid_power_w: float = 0.0
    _last_simulator_status_signature: tuple[object, ...] | None = None
    _last_fault_status_signature: tuple[object, ...] | None = None
    _node_red_status: RuntimeStatus | None = None
    _last_battery_power_w: float = 0.0
    _selected_fault_kind: FaultKind = FaultKind.STALE_TELEMETRY

    @property
    def is_sandbox_configured(self) -> bool:
        """Return whether this entry has a valid virtual-battery configuration."""
        return self._config is not None and self.pretend_gx_id is not None

    @property
    def energy_wh(self) -> float | None:
        """Return the entry-local stored battery energy."""
        return self._state.energy_wh if self._state is not None else None

    @property
    def capacity_wh(self) -> float | None:
        """Return the registration-owned virtual battery capacity."""
        return self._config.capacity_wh if self._config is not None else None

    @property
    def max_charge_power_w(self) -> float | None:
        """Return the active sandbox charge limit."""
        return self._config.max_charge_power_w if self._config is not None else None

    @property
    def max_discharge_power_w(self) -> float | None:
        """Return the active sandbox discharge limit."""
        return self._config.max_discharge_power_w if self._config is not None else None

    @property
    def charge_efficiency(self) -> float | None:
        """Return the active sandbox charge efficiency ratio."""
        return self._config.charge_efficiency if self._config is not None else None

    @property
    def discharge_efficiency(self) -> float | None:
        """Return the active sandbox discharge efficiency ratio."""
        return self._config.discharge_efficiency if self._config is not None else None

    @property
    def reserve_wh(self) -> float | None:
        """Return the registration-owned virtual battery reserve."""
        return self._config.reserve_wh if self._config is not None else None

    @property
    def soc_percent(self) -> float | None:
        """Return the simulated battery state of charge as a percentage."""
        if self._state is None or self._config is None:
            return None
        return self._state.soc_ratio(self._config.capacity_wh) * 100

    @property
    def can_set_state_of_charge(self) -> bool:
        """Return whether the live state-of-charge control can act now."""
        return (
            self.simulator_enabled
            and self._playback_state != "running"
            and (
                self._replay_session is None
                or self._replay_session.state
                not in (_REPLAY_ACTIVE_STATES | {ReplayState.RUNNING, ReplayState.PAUSED})
            )
        )

    @property
    def reserve_percent(self) -> float | None:
        """Return the current hard reserve in the number control's unit."""
        if self._config is None:
            return None
        return self._config.reserve_wh / self._config.capacity_wh * 100

    @property
    def battery_power_w(self) -> float:
        """Return the most recently simulated AC battery power."""
        return self._last_battery_power_w

    @property
    def grid_power_w(self) -> float:
        """Return the most recently simulated grid power."""
        return self._last_grid_power_w

    @property
    def energy_ledger(self) -> IntervalLedger:
        """Return the entry-local accumulated modeled energy ledger."""
        return self._cumulative_ledger

    @property
    def mqtt_health(self) -> str:
        """Return a safe local MQTT bridge summary."""
        if not self.simulator_enabled:
            return "inactive"
        return "faulted" if self._mqtt_fault_disconnected else "connected"

    @property
    def forecast_health(self) -> str:
        """Return the direct HA forecast status for this virtual battery."""
        return self._direct_forecast_health

    @property
    def decision_summary(self) -> str:
        """Return the bounded latest direct-forecast decision summary."""
        return self.last_command_reason or self.last_command_status.value

    @property
    def virtual_time_utc(self) -> datetime | None:
        """Return this sandbox's virtual timestamp."""
        return self._clock.state.virtual_time_utc if self._clock is not None else None

    @property
    def clock_rate(self) -> str | None:
        """Return the current virtual-clock rate."""
        return self._clock.state.rate if self._clock is not None else None

    @property
    def selected_profile_filename(self) -> str | None:
        """Return this runtime's selected owned profile filename."""
        return self._selected_profile_filename

    @property
    def equipment_profile_name(self) -> str:
        """Return the registration-owned equipment profile label."""
        return "Registration profile"

    @property
    def playback_state(self) -> str:
        """Return local playback state without exposing profile contents."""
        return self._playback_state

    @property
    def profile_cursor(self) -> ProfileCursor | None:
        """Return the selected profile's current sample cursor."""
        return self._profile_cursor

    @property
    def replay_session(self) -> ReplaySession | None:
        """Return this entry's local replay session value data, if any."""
        return self._replay_session

    @property
    def replay_state(self) -> ReplayState | None:
        """Return the entry-local replay lifecycle state without a request payload."""
        return self._replay_session.state if self._replay_session is not None else None

    @property
    def replay_reason(self) -> str | None:
        """Return the last safe local or remote replay reason, if available."""
        return (
            self._replay_session.last_remote_reason
            if self._replay_session is not None
            else None
        )

    @property
    def replay_pending_resume(self) -> bool:
        """Return whether a restored interrupted session awaits a future resume flow."""
        return self._replay_pending_resume

    @property
    def node_red_status(self) -> RuntimeStatus | None:
        """Return only the latest validated, in-memory Node-RED runtime status."""
        return self._node_red_status

    @property
    def active_fault_diagnostics(self) -> tuple[str, ...]:
        """Read-only local fault diagnostics; C1 intentionally applies no effects."""
        return tuple(
            f"{fault.kind.value}: {fault.state.value}"
            for fault in self._faults
            if fault.state in {FaultState.PENDING, FaultState.ACTIVE}
        )

    @property
    def selected_fault_kind(self) -> str:
        """Return the user-selected safe local fault kind."""
        return self._selected_fault_kind.value

    def set_selected_fault_kind(self, kind: str) -> None:
        """Select a supported fault kind without activating it."""
        self._selected_fault_kind = FaultKind(kind)
        self._notify_listeners()

    async def async_inject_selected_fault(self) -> None:
        """Create and activate one conservative, entry-local test fault."""
        now = self.virtual_time_utc
        if now is None or not self.simulator_enabled:
            raise ValueError("Sandbox is inactive")
        kind = self._selected_fault_kind
        kwargs: dict[str, object] = {"kind": kind, "activation_utc": now}
        if kind in {FaultKind.STALE_TELEMETRY, FaultKind.MQTT_DISCONNECT}:
            kwargs["remaining_duration_seconds"] = 30
        else:
            kwargs["remaining_count"] = 1
        if kind is FaultKind.DELAY_MQTT:
            kwargs["settings"] = {"delay_seconds": 1}
        fault = await self.async_configure_fault(**kwargs)
        await self.async_activate_fault(fault.fault_id)

    def list_faults(self) -> tuple[Fault, ...]:
        """Return immutable entry-local fault values only."""
        return self._faults

    async def async_configure_fault(self, **kwargs: object) -> Fault:
        """Configure state only; no C1 caller can affect runtime behavior."""
        fault = configure_fault(**kwargs)
        if len(self._faults) >= 16 or any(
            item.kind is fault.kind and item.state is not FaultState.CLEARED
            for item in self._faults
        ):
            raise ValueError("Fault limit or kind uniqueness is invalid")
        self._faults = (*self._faults, fault)
        await self.async_checkpoint(immediate=True)
        self._notify_listeners()
        return fault

    async def async_activate_fault(self, fault_id: str) -> Fault:
        """Activate state against this sandbox virtual UTC only."""
        now = self.virtual_time_utc
        if now is None:
            raise ValueError("Sandbox clock is unavailable")
        self._faults = tuple(
            activate_fault(fault, now) if fault.fault_id == fault_id else fault
            for fault in self._faults
        )
        fault = next((item for item in self._faults if item.fault_id == fault_id), None)
        if fault is None:
            raise ValueError("Fault does not exist")
        self._schedule_fault_expiry(fault)
        if fault.kind is FaultKind.MQTT_DISCONNECT:
            await self._async_enter_fault_disconnect(fault)
        elif fault.kind is FaultKind.RUNTIME_RESTART:
            await self._async_restart_for_fault(fault)
        await self.async_checkpoint(immediate=True)
        await self._async_publish_runtime_statuses(force=True)
        self._notify_listeners()
        return fault

    async def async_clear_fault(self, fault_id: str) -> None:
        """Clear only local fault state without touching an executor."""
        found = False
        cleared: list[Fault] = []
        for fault in self._faults:
            if fault.fault_id == fault_id:
                cleared.append(clear_fault(fault)); found = True
            else: cleared.append(fault)
        if not found: raise ValueError("Fault does not exist")
        self._faults = tuple(cleared)
        self._cancel_fault_work(fault_id)
        self._maybe_leave_fault_disconnect()
        await self.async_checkpoint(immediate=True)
        await self._async_publish_runtime_statuses(force=True)
        self._notify_listeners()

    async def async_clear_all_faults(self) -> None:
        self._faults = clear_all_faults(self._faults)
        self._cancel_all_fault_work()
        self._maybe_leave_fault_disconnect()
        await self.async_checkpoint(immediate=True)
        await self._async_publish_runtime_statuses(force=True)
        self._notify_listeners()

    def configure_sandbox(self, data: Mapping[str, object]) -> None:
        """Configure this runtime without starting it or touching other entries."""
        if self._unloaded:
            raise RuntimeError("Sandbox runtime has been unloaded")
        configured = simulator_config(data)
        if configured is None:
            self._config = None
            self._registration_config = None
            self._state = None
            self._clock = None
            self.pretend_gx_id = None
            self.coordinator.set_battery_capacity_provider(None)
            self.available_reason = (
                "Sandbox virtual battery requires valid registration-owned "
                "equipment values."
            )
            return

        self._config, self.pretend_gx_id = configured
        registration_config = data.get(CONF_REGISTRATION_CONFIG)
        self._registration_config = (
            registration_config if isinstance(registration_config, Mapping) else None
        )
        self._state = BatteryState(
            max(self._config.capacity_wh * 0.5, self._config.reserve_wh)
        )
        self._last_grid_power_w = 0.0
        self._last_battery_power_w = 0.0
        self._clock = VirtualClock(datetime.now(timezone.utc))
        self._cumulative_ledger = IntervalLedger()
        self._active_profile_id = None
        self._profile_cursor = None
        self._accepted_command_ids = ()
        self._clear_pending_command()
        self.coordinator.set_battery_capacity_provider(self.current_capacity)
        self.available_reason = None
        self._notify_listeners()

    async def async_restore_storage(self, hass: HomeAssistant) -> None:
        """Restore only this entry's validated state, without inferring identity."""
        if not self.is_sandbox_configured or not self.entry_id:
            return
        self._storage = SandboxStorage(hass, self.entry_id)
        self._profile_repository = SandboxProfileRepository(hass, self.entry_id)
        try:
            record = await self._storage.async_load()
            if record is None:
                return
            (
                snapshot,
                enabled,
                snapshots,
                profile_state,
                replay_state,
                command_ledger,
                control_config,
            ) = self._validated_storage_record(record)
            faults, fault_snapshots = self._validated_fault_storage(
                record, expected_snapshot_names=set(snapshots)
            )
            self._config = control_config
            self._apply_snapshot(snapshot)
            self.load_w = snapshot.load_w
            self.solar_w = snapshot.solar_w
            self._named_snapshots = snapshots
            self._faults = faults
            self._named_fault_snapshots = fault_snapshots
            self._accepted_command_ids = command_ledger
            self._clear_pending_command()
            self._reset_node_red_status()
            if not await self._async_restore_profile_state(profile_state):
                enabled = False
            await self._async_restore_replay_state(replay_state)
            if enabled:
                await self.async_enable(hass)
        except (HomeAssistantError, NotImplementedError, ValueError, TypeError, KeyError):
            self.storage_diagnostic = (
                "Stored simulator state is incompatible or invalid; using a disabled default."
            )
            self.simulator_enabled = False
            self._named_snapshots = {}
            self._notify_listeners()

    async def async_list_profile_filenames(self) -> tuple[str, ...]:
        """List only this entry's direct-child supported profile files."""
        if self._profile_repository is None or self._config is None:
            return ()
        valid: list[str] = []
        for filename in await self._profile_repository.async_list_filenames():
            try:
                await self._profile_repository.async_load(filename, self._config)
            except ValueError:
                continue
            valid.append(filename)
        return tuple(valid)

    async def async_load_profile(
        self,
        filename: str,
    ) -> tuple[LocalSyntheticProfile, str]:
        """Validate one owned profile without mutating simulator state."""
        if self._profile_repository is None or self._config is None:
            raise ValueError("Sandbox profile storage is unavailable")
        return await self._profile_repository.async_load(filename, self._config)

    async def async_select_profile(self, filename: str) -> None:
        """Select a validated owned profile and reset its local cursor."""
        profile, content_hash = await self.async_load_profile(filename)
        self._active_profile = profile
        self._selected_profile_filename = filename
        self._profile_hash = content_hash
        self._active_profile_id = profile.identifier
        self._profile_cursor = ProfileCursor(profile.identifier, 0)
        self._playback_state = "paused"
        self.load_w = 0.0
        self.solar_w = 0.0
        self._command = Command(OperatingMode.SELF_CONSUMPTION)
        if self._clock is not None:
            self._clock.reset(profile.samples[0].timestamp_utc)
        if profile.starting_battery_energy_wh is not None:
            self._state = BatteryState(profile.starting_battery_energy_wh)
            self._last_grid_power_w = 0.0
            self._last_battery_power_w = 0.0
        if self.simulator_enabled:
            await self._async_publish_telemetry_snapshot()
        await self.async_checkpoint(immediate=True)
        await self._async_publish_runtime_statuses(force=True)
        self._notify_listeners()

    async def async_start_playback(self) -> None:
        """Start deterministic local playback from the selected cursor."""
        if not self.simulator_enabled or self._active_profile is None:
            raise ValueError("A selected profile requires an active sandbox")
        if self._profile_cursor is None:
            raise ValueError("Profile cursor is unavailable")
        if self._replay_session is not None and self._replay_session.state is ReplayState.PAUSED:
            self._replay_session = transition_local_replay(
                self._replay_session,
                ReplayState.RUNNING,
            )
            if self._clock is not None:
                self._clock.set_rate(self._replay_paused_rate or ClockRate.X1)
            await self._async_publish_replay_clock(immediate=True)
            self._schedule_replay_heartbeat()
        self._playback_state = "running"
        await self.async_checkpoint(immediate=True)
        await self._async_publish_runtime_statuses(force=True)
        self._notify_listeners()

    async def async_pause_playback(self) -> None:
        """Pause playback without changing the virtual clock or cursor."""
        if self._active_profile is None:
            raise ValueError("No profile is selected")
        self._playback_state = "paused"
        if self._clock is not None:
            self._replay_paused_rate = ClockRate(self._clock.state.rate)
            self._clock.set_rate(ClockRate.PAUSED)
        if self._replay_session is not None and self._replay_session.state is ReplayState.RUNNING:
            self._replay_session = transition_local_replay(
                self._replay_session,
                ReplayState.PAUSED,
            )
            await self._async_publish_replay_clock(immediate=True)
            self._schedule_replay_heartbeat()
        await self.async_checkpoint(immediate=True)
        await self._async_publish_runtime_statuses(force=True)
        self._notify_listeners()

    async def async_stop_playback(self) -> None:
        """Stop playback and return this sandbox to safe self-consumption."""
        self._playback_state = "stopped"
        self.load_w = 0.0
        self.solar_w = 0.0
        self._command = Command(OperatingMode.SELF_CONSUMPTION)
        if self._replay_session is not None and self._replay_session.state in {
            ReplayState.RUNNING,
            ReplayState.PAUSED,
        }:
            await self.async_stop_replay_session()
        await self.async_checkpoint(immediate=True)
        await self._async_publish_runtime_statuses(force=True)
        self._notify_listeners()

    async def async_reset_playback(self) -> None:
        """Reset the selected profile cursor without loading another file."""
        if self._active_profile is None:
            raise ValueError("No profile is selected")
        self._profile_cursor = ProfileCursor(self._active_profile.identifier, 0)
        self._playback_state = "paused"
        if self._clock is not None:
            self._clock.reset(self._active_profile.samples[0].timestamp_utc)
        if self.simulator_enabled:
            await self._async_publish_telemetry_snapshot()
        await self.async_checkpoint(immediate=True)
        await self._async_publish_runtime_statuses(force=True)
        self._notify_listeners()

    async def async_prepare_replay_session(self) -> ReplaySession:
        """Build one new local replay session from trusted entry-owned inputs."""
        self._require_replay_startable()
        profile, content_hash = await self._async_revalidate_selected_profile()
        if self._config is None or self._state is None:
            raise ValueError("Sandbox state is unavailable")
        import_for_export, export_for_solar_headroom = self._trusted_replay_toggles()
        starting_energy_wh = (
            profile.starting_battery_energy_wh
            if profile.starting_battery_energy_wh is not None
            else self._state.energy_wh
        )
        request = build_replay_request(
            periods=aggregate_half_hours(profile),
            starting_battery_energy_wh=starting_energy_wh,
            config=self._config,
            import_for_export_enabled=import_for_export,
            export_for_solar_headroom=export_for_solar_headroom,
            simulate_api_failure=self._consume_replay_api_failure_fault(),
        )
        self._replay_starting_energy_wh = starting_energy_wh
        self._replay_import_for_export_enabled = import_for_export
        self._replay_export_for_solar_headroom = export_for_solar_headroom
        self._replay_pending_resume = False
        self._replay_session = create_replay_session(
            request,
            profile_identifier=profile.identifier,
            profile_hash=content_hash,
        )
        self._prepared_replay_request = request
        return self._replay_session

    async def async_start_replay_session(self) -> ReplaySession:
        """Start one direct HA replay without MQTT or Node-RED acknowledgements."""
        async with self._replay_start_lock:
            if (
                self._replay_session is not None
                and self._replay_session.state is ReplayState.IDLE
                and self._prepared_replay_request is not None
            ):
                session = self._replay_session
            else:
                session = await self.async_prepare_replay_session()
            request = self._prepared_replay_request
            if request is None or self._config is None or self._clock is None:
                raise ValueError("Sandbox runtime is unavailable")
            self._replay_session = start_replay_request(session)
            try:
                payload = await self.coordinator.async_fetch_sandbox_replay(
                    request.to_payload()
                )
                direct = parse_replay_command(
                    payload,
                    virtual_now_utc=self._clock.state.virtual_time_utc,
                    config=self._config,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                self._replay_session = replace(
                    self._replay_session,
                    state=ReplayState.FAILED,
                    last_remote_reason=_REPLAY_PUBLISH_FAILURE_REASON,
                )
                self._prepared_replay_request = None
                await self.async_checkpoint(immediate=True)
                await self._async_publish_runtime_statuses(force=True)
                self._notify_listeners()
                return self._replay_session
            self._prepared_replay_request = None
            self._direct_replay_payload = payload
            self._last_direct_replay_key = direct.replay_key
            self._command = direct.command
            self.last_command_status = CommandStatus.APPLIED
            self.last_command_reason = direct.action
            self._replay_session = replace(self._replay_session, state=ReplayState.RUNNING)
            await self.async_checkpoint(immediate=True)
            await self._async_publish_runtime_statuses(force=True)
            self._notify_listeners()
            return self._replay_session

    def _consume_replay_api_failure_fault(self) -> bool:
        """Consume one configured simulated Node-RED API failure at request formation."""
        fault = self._active_fault(FaultKind.REPLAY_API_FAILURE)
        if fault is None:
            self._replay_simulate_api_failure = False
            return False
        self._consume_outbound_fault(FaultKind.REPLAY_API_FAILURE)
        self._replay_simulate_api_failure = True
        return True

    async def async_retry_replay_session(self) -> ReplaySession:
        """Explicitly create and publish a new UUID after a terminal failure."""
        if self._replay_session is None or self._replay_session.state not in {
            ReplayState.REJECTED,
            ReplayState.FAILED,
        }:
            raise ValueError("Only a rejected or failed replay can be retried")
        self._replay_session = None
        self._replay_starting_energy_wh = None
        self._replay_import_for_export_enabled = None
        self._replay_export_for_solar_headroom = None
        self._replay_simulate_api_failure = False
        return await self.async_start_replay_session()

    async def _async_resume_pending_replay(self) -> None:
        """Republish one identity/hash-checked interrupted request after MQTT setup."""
        if (
            not self._replay_auto_resume_pending
            or self._replay_session is None
            or self._replay_session.state is not ReplayState.STOPPED
            or self._hass is None
            or self.pretend_gx_id is None
            or self._config is None
            or self._replay_starting_energy_wh is None
            or self._replay_import_for_export_enabled is None
            or self._replay_export_for_solar_headroom is None
        ):
            return
        try:
            profile, content_hash = await self._async_revalidate_selected_profile()
            request = build_replay_request(
                periods=aggregate_half_hours(profile),
                starting_battery_energy_wh=self._replay_starting_energy_wh,
                config=self._config,
                import_for_export_enabled=self._replay_import_for_export_enabled,
                export_for_solar_headroom=self._replay_export_for_solar_headroom,
                replay_id=self._replay_session.replay_id,
                simulate_api_failure=self._replay_simulate_api_failure,
            )
            rebuilt = create_replay_session(
                request,
                profile_identifier=profile.identifier,
                profile_hash=content_hash,
            )
            if rebuilt.request_hash != self._replay_session.request_hash:
                raise ValueError("Stored replay request hash does not match")
            self._replay_session = replace(
                self._replay_session,
                state=ReplayState.REQUESTING,
            )
            await self._async_publish_outbound(
                replay_request_topic(self.pretend_gx_id),
                json.dumps(request.to_payload(), separators=(",", ":")),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._async_fail_replay(_REPLAY_PUBLISH_FAILURE_REASON)
            return
        self._schedule_replay_timeout(self._replay_session.replay_id)
        await self._async_publish_runtime_statuses(force=True)

    async def async_stop_replay_session(self) -> None:
        """Stop this entry's replay lifecycle without publishing a bridge command."""
        if self._replay_session is None:
            raise ValueError("No replay session exists")
        self._cancel_replay_timeout()
        self._cancel_replay_heartbeat()
        if self._replay_session.state in _REPLAY_ACTIVE_STATES:
            self._replay_session = stop_replay(self._replay_session)
        else:
            self._replay_session = replace(self._replay_session, state=ReplayState.STOPPED)
        self._replay_pending_resume = False
        self._replay_auto_resume_pending = False
        self._prepared_replay_request = None
        self._playback_state = "stopped"
        self.load_w = 0.0
        self.solar_w = 0.0
        self._command = Command(OperatingMode.SELF_CONSUMPTION)
        self._move_clock_to_replay_end()
        await self._async_publish_replay_clock(
            reset=self._last_replay_clock_status is None,
            immediate=True,
        )
        await self.async_checkpoint(immediate=True)
        await self._async_publish_runtime_statuses(force=True)
        self._notify_listeners()

    async def _async_revalidate_selected_profile(
        self,
    ) -> tuple[LocalSyntheticProfile, str]:
        if (
            self._selected_profile_filename is None
            or self._profile_hash is None
            or self._active_profile is None
        ):
            raise ValueError("A selected profile is required for replay")
        profile, content_hash = await self.async_load_profile(self._selected_profile_filename)
        if content_hash != self._profile_hash or profile.identifier != self._active_profile.identifier:
            raise ValueError("Selected profile changed; replay cannot start")
        return profile, content_hash

    def _require_replay_startable(self) -> None:
        if self._unloaded or not self.simulator_enabled or self._hass is None:
            raise ValueError("An enabled sandbox MQTT runtime is required")
        if not self.is_sandbox_configured:
            raise ValueError("Sandbox is unavailable")
        if self._replay_session is not None and self._replay_session.state in (
            _REPLAY_ACTIVE_STATES | {ReplayState.RUNNING, ReplayState.PAUSED}
        ):
            raise ValueError("A replay request is already active")
        if self._replay_session is not None and self._replay_session.state in {
            ReplayState.REJECTED,
            ReplayState.FAILED,
        }:
            raise ValueError("Retry the failed replay explicitly")

    def _trusted_replay_toggles(self) -> tuple[bool, bool]:
        config = self._registration_config
        if config is None:
            raise ValueError("Registration replay settings are unavailable")
        return (
            _registration_toggle(config, "ImportForExport", "importForExport"),
            _registration_toggle(
                config,
                "ExportForSolarHeadroom",
                "exportForSolarHeadroom",
            ),
        )

    async def _async_start_ready_replay(self) -> None:
        """Start local playback once after the sole accepted ready transition."""
        if self._replay_session is None or self._replay_session.state is not ReplayState.READY:
            return
        try:
            profile, content_hash = await self._async_revalidate_selected_profile()
            if (
                self._state is None
                or self._clock is None
                or self._replay_starting_energy_wh is None
                or content_hash != self._replay_session.profile_hash
            ):
                raise ValueError("Replay profile is unavailable")
            resuming = self._replay_auto_resume_pending
            if not resuming:
                self._state = BatteryState(self._replay_starting_energy_wh)
                self._clock.reset(profile.samples[0].timestamp_utc)
                self._profile_cursor = ProfileCursor(profile.identifier, 0)
            elif self._profile_cursor is None or self._profile_cursor.profile_id != profile.identifier:
                raise ValueError("Stored replay cursor is unavailable")
            if self._clock.state.rate == ClockRate.PAUSED.value:
                self._clock.set_rate(ClockRate.X1)
            self._playback_state = "running"
            self._last_replay_clock_status = None
            self._replay_last_clock_publish_monotonic = None
            self._replay_session = transition_local_replay(
                self._replay_session,
                ReplayState.RUNNING,
            )
            self._replay_pending_resume = False
            self._replay_auto_resume_pending = False
            await self._async_publish_replay_clock(reset=True, immediate=True)
        except (HomeAssistantError, ValueError):
            await self._async_fail_replay(_REPLAY_CLOCK_PUBLISH_FAILURE_REASON)
            return
        self._schedule_replay_heartbeat()
        await self.async_checkpoint(immediate=True)
        await self._async_publish_runtime_statuses(force=True)
        self._notify_listeners()

    async def _async_publish_replay_clock(
        self,
        *,
        reset: bool = False,
        immediate: bool = False,
    ) -> bool:
        """Publish one bounded, non-retained virtual-clock status for this replay."""
        if (
            self._unloaded
            or self._hass is None
            or self.pretend_gx_id is None
            or self._clock is None
            or self._replay_session is None
            or self._replay_session.state
            not in {ReplayState.RUNNING, ReplayState.PAUSED, ReplayState.COMPLETED, ReplayState.STOPPED}
        ):
            return False
        now = self._hass.loop.time()
        if (
            not reset
            and self._replay_last_clock_publish_monotonic is not None
            and now - self._replay_last_clock_publish_monotonic
            < _REPLAY_CLOCK_MINIMUM_INTERVAL_SECONDS
        ):
            return False
        try:
            status = build_clock_status(
                gx_device_id=self.pretend_gx_id,
                replay_id=self._replay_session.replay_id,
                virtual_time_utc=self._clock.state.virtual_time_utc,
                previous=self._last_replay_clock_status,
                reset=reset,
            )
            await self._async_publish_outbound(
                clock_status_topic(self.pretend_gx_id),
                json.dumps(status.to_payload(), separators=(",", ":")),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._async_fail_replay(_REPLAY_CLOCK_PUBLISH_FAILURE_REASON)
            return False
        self._last_replay_clock_status = status
        self._replay_last_clock_publish_monotonic = now
        self._replay_session = replace(self._replay_session, clock_sequence=status.sequence)
        return True

    async def _async_fail_replay(self, reason: str) -> None:
        """Fail only the owning replay and return its local inputs to a safe state."""
        self._cancel_replay_timeout()
        self._cancel_replay_heartbeat()
        if self._replay_session is not None:
            self._replay_session = replace(
                self._replay_session,
                state=ReplayState.FAILED,
                last_remote_reason=reason,
            )
        self._playback_state = "stopped"
        self.load_w = 0.0
        self.solar_w = 0.0
        self._command = Command(OperatingMode.SELF_CONSUMPTION)
        self._replay_pending_resume = False
        self._replay_auto_resume_pending = False
        if self._storage is not None:
            await self.async_checkpoint(immediate=True)
        await self._async_publish_runtime_statuses(force=True)
        self._notify_listeners()

    def _schedule_replay_heartbeat(self) -> None:
        self._cancel_replay_heartbeat()
        if self._hass is None or self._unloaded:
            return
        self._replay_heartbeat_handle = self._hass.loop.call_later(
            _REPLAY_HEARTBEAT_SECONDS,
            self._async_replay_heartbeat_due,
        )

    def _async_replay_heartbeat_due(self) -> None:
        self._replay_heartbeat_handle = None
        if self._hass is not None:
            self._hass.async_create_task(self._async_replay_heartbeat())

    async def _async_replay_heartbeat(self) -> None:
        if (
            self._unloaded
            or not self.simulator_enabled
            or self._mqtt_fault_disconnected
            or self._replay_session is None
            or self._replay_session.state not in {ReplayState.RUNNING, ReplayState.PAUSED}
        ):
            return
        await self._async_publish_replay_clock(immediate=True)
        if self._replay_session is not None and self._replay_session.state in {
            ReplayState.RUNNING,
            ReplayState.PAUSED,
        }:
            self._schedule_replay_heartbeat()

    def _cancel_replay_heartbeat(self) -> None:
        if self._replay_heartbeat_handle is not None:
            self._replay_heartbeat_handle.cancel()
            self._replay_heartbeat_handle = None

    async def _async_complete_replay(self) -> None:
        """Finish the local profile exactly once and send its terminal clock position."""
        if self._replay_session is None:
            self._playback_state = "completed"
            self.load_w = 0.0
            self.solar_w = 0.0
            self._command = Command(OperatingMode.SELF_CONSUMPTION)
            self._notify_listeners()
            return
        if self._replay_session.state not in {ReplayState.RUNNING, ReplayState.PAUSED}:
            return
        self._playback_state = "completed"
        self.load_w = 0.0
        self.solar_w = 0.0
        self._command = Command(OperatingMode.SELF_CONSUMPTION)
        self._move_clock_to_replay_end()
        self._replay_session = transition_local_replay(
            self._replay_session,
            ReplayState.COMPLETED,
        )
        self._cancel_replay_heartbeat()
        await self._async_publish_replay_clock(immediate=True)
        await self.async_checkpoint(immediate=True)
        await self._async_publish_runtime_statuses(force=True)
        self._notify_listeners()

    def _move_clock_to_replay_end(self) -> None:
        if self._active_profile is None or self._clock is None:
            return
        replay_end = self._active_profile.samples[-1].timestamp_utc + timedelta(minutes=5)
        current = self._clock.state.virtual_time_utc
        if current < replay_end:
            self._clock.step((replay_end - current).total_seconds())

    async def _async_restore_profile_state(
        self,
        profile_state: tuple[str | None, str | None, str],
    ) -> bool:
        filename, expected_hash, playback_state = profile_state
        if filename is None:
            self._playback_state = "stopped"
            return True
        try:
            profile, content_hash = await self.async_load_profile(filename)
        except ValueError:
            self.storage_diagnostic = "Stored profile is unavailable; simulator playback is paused."
            self._clear_profile_state()
            return False
        if content_hash != expected_hash:
            self.storage_diagnostic = "Stored profile changed; simulator playback is paused."
            self._clear_profile_state()
            return False
        if self._profile_cursor is None or self._profile_cursor.profile_id != profile.identifier:
            self.storage_diagnostic = "Stored profile cursor is invalid; simulator playback is paused."
            self._clear_profile_state()
            return False
        if self._profile_cursor.index < 0 or self._profile_cursor.index > len(profile.samples):
            self.storage_diagnostic = "Stored profile cursor is invalid; simulator playback is paused."
            self._clear_profile_state()
            return False
        self._active_profile = profile
        self._selected_profile_filename = filename
        self._profile_hash = content_hash
        self._playback_state = playback_state
        return True

    def _clear_profile_state(self) -> None:
        self._active_profile = None
        self._selected_profile_filename = None
        self._profile_hash = None
        self._active_profile_id = None
        self._profile_cursor = None
        self._playback_state = "paused"

    async def _async_restore_replay_state(
        self,
        replay_state: tuple[
            ReplaySession | None,
            float | None,
            bool | None,
            bool | None,
            bool,
            bool,
            bool,
        ],
    ) -> None:
        (
            session,
            starting_energy,
            import_for_export,
            export_for_solar_headroom,
            pending_resume,
            auto_resume,
            simulate_api_failure,
        ) = replay_state
        if session is None:
            return
        try:
            profile, content_hash = await self._async_revalidate_selected_profile()
            if (
                self._config is None
                or starting_energy is None
                or import_for_export is None
                or export_for_solar_headroom is None
            ):
                raise ValueError("Stored replay state is incomplete")
            request = build_replay_request(
                periods=aggregate_half_hours(profile),
                starting_battery_energy_wh=starting_energy,
                config=self._config,
                import_for_export_enabled=import_for_export,
                export_for_solar_headroom=export_for_solar_headroom,
                replay_id=session.replay_id,
                simulate_api_failure=simulate_api_failure,
            )
            rebuilt = create_replay_session(
                request,
                profile_identifier=profile.identifier,
                profile_hash=content_hash,
            )
            if rebuilt.request_hash != session.request_hash:
                raise ValueError("Stored replay request hash does not match")
        except ValueError:
            self._replay_session = replace(
                session,
                state=ReplayState.FAILED,
                last_remote_reason="Stored replay cannot be reconstructed.",
            )
            self._replay_pending_resume = False
            self._replay_auto_resume_pending = False
            self.storage_diagnostic = "Stored replay cannot be reconstructed; it was not resumed."
            return
        self._replay_starting_energy_wh = starting_energy
        self._replay_import_for_export_enabled = import_for_export
        self._replay_export_for_solar_headroom = export_for_solar_headroom
        self._replay_simulate_api_failure = simulate_api_failure
        if session.state in _REPLAY_ACTIVE_STATES or pending_resume:
            self._replay_session = replace(session, state=ReplayState.STOPPED)
            self._replay_pending_resume = True
            self._replay_auto_resume_pending = auto_resume
        else:
            self._replay_session = session
            self._replay_pending_resume = False
            self._replay_auto_resume_pending = False

    async def async_checkpoint(
        self,
        *,
        immediate: bool = False,
        enabled_override: bool | None = None,
    ) -> None:
        """Save a minimal entry-local checkpoint immediately or with debounce."""
        if self._storage is None or not self.is_sandbox_configured:
            return
        if immediate:
            self._cancel_pending_checkpoint()
            await self._storage.async_save(
                self._storage_record(enabled_override=enabled_override)
            )
            return
        self._schedule_checkpoint()

    async def async_save_snapshot(self, name: str, *, replace: bool = False) -> None:
        """Save a named, entry-local snapshot with explicit replacement."""
        normalized = _snapshot_name(name)
        if normalized in self._named_snapshots and not replace:
            raise ValueError("A snapshot with this name already exists")
        if normalized not in self._named_snapshots and len(self._named_snapshots) >= MAX_NAMED_SNAPSHOTS:
            raise ValueError("The snapshot limit has been reached")
        self._named_snapshots[normalized] = to_json(self._simulation_snapshot())
        self._named_fault_snapshots[normalized] = self._faults
        await self.async_checkpoint(immediate=True)

    def list_snapshots(self) -> tuple[str, ...]:
        """List this entry's named snapshots in stable order."""
        return tuple(sorted(self._named_snapshots))

    async def async_restore_snapshot(self, name: str) -> None:
        """Atomically restore one validated local snapshot without I/O side effects."""
        normalized = _snapshot_name(name)
        try:
            serialized = self._named_snapshots[normalized]
        except KeyError as err:
            raise ValueError("Snapshot does not exist") from err
        raw_snapshot = from_json(serialized)
        restored_config = (
            _control_config_from_storage(raw_snapshot.control_config, fallback=self._config)
            if raw_snapshot.control_config is not None and self._config is not None
            else self._config
        )
        snapshot = self._validated_snapshot(raw_snapshot, config=restored_config)
        restored_faults = (
            validate_faults(list(raw_snapshot.faults))
            if raw_snapshot.faults
            else self._named_fault_snapshots.get(normalized, ())
        )
        validate_faults([fault.to_dict() for fault in restored_faults])
        restored_profile: LocalSyntheticProfile | None = None
        if snapshot.selected_profile_filename is not None:
            restored_profile, restored_hash = await self.async_load_profile(
                snapshot.selected_profile_filename
            )
            if restored_hash != snapshot.profile_hash or (
                snapshot.profile_cursor is not None
                and snapshot.profile_cursor.profile_id != restored_profile.identifier
            ):
                raise ValueError("Snapshot profile cannot be reconstructed")
        restored_replay = (
            ReplaySession.from_dict(snapshot.replay_session)
            if snapshot.replay_session is not None
            else None
        )
        # Commit only after the whole snapshot and its fault companion have
        # validated. The duplicate ledger deliberately remains untouched.
        self._cancel_all_fault_work()
        self._clear_pending_command()
        self._cancel_replay_timeout()
        self._cancel_replay_heartbeat()
        if restored_config is not None:
            self._config = restored_config
        self._apply_snapshot(snapshot)
        self.load_w = snapshot.load_w
        self.solar_w = snapshot.solar_w
        self._playback_state = snapshot.playback_state
        self._selected_profile_filename = snapshot.selected_profile_filename
        self._profile_hash = snapshot.profile_hash
        self._active_profile = restored_profile
        # Remote readiness is intentionally never recreated by a local
        # snapshot. Preserve only validated local replay identity/state and
        # require an explicit start before publishing again.
        self._replay_session = (
            replace(restored_replay, state=ReplayState.STOPPED)
            if restored_replay is not None
            else None
        )
        self._replay_pending_resume = False
        self._replay_auto_resume_pending = False
        self._faults = restored_faults
        self._mqtt_fault_disconnected = False
        self._reset_node_red_status()
        if self._replay_session is not None:
            # A local snapshot cannot prove that the external replay bridge is
            # still ready. Keep the restored manual inputs, but require a new
            # explicit replay start before the bridge can influence them.
            self._playback_state = "stopped"
            self._command = Command(OperatingMode.SELF_CONSUMPTION)
        for fault in self._faults:
            if fault.state is FaultState.ACTIVE:
                self._schedule_fault_expiry(fault)
                if fault.kind is FaultKind.MQTT_DISCONNECT:
                    await self._async_enter_fault_disconnect(fault)
        self._notify_listeners()
        await self.async_checkpoint(immediate=True)

    async def async_delete_snapshot(self, name: str) -> None:
        """Delete one named snapshot owned by this entry."""
        normalized = _snapshot_name(name)
        if normalized not in self._named_snapshots:
            raise ValueError("Snapshot does not exist")
        del self._named_snapshots[normalized]
        self._named_fault_snapshots.pop(normalized, None)
        await self.async_checkpoint(immediate=True)

    def _storage_record(
        self,
        *,
        enabled_override: bool | None = None,
    ) -> dict[str, object]:
        if self.pretend_gx_id is None:
            raise ValueError("Sandbox identity is unavailable")
        return {
            "storage_schema_version": STORAGE_SCHEMA_VERSION,
            "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
            "entry_id": self.entry_id,
            "registration_id": self.registration_id,
            "pretend_gx_id": self.pretend_gx_id,
            "simulator_enabled": (
                self.simulator_enabled
                if enabled_override is None
                else enabled_override
            ),
            "current_snapshot": to_json(self._simulation_snapshot()),
            "snapshots": dict(self._named_snapshots),
            "selected_profile_filename": self._selected_profile_filename,
            "profile_hash": self._profile_hash,
            "playback_state": self._playback_state,
            "replay_session": (
                self._replay_session.to_dict() if self._replay_session is not None else None
            ),
            "replay_starting_energy_wh": self._replay_starting_energy_wh,
            "replay_import_for_export_enabled": self._replay_import_for_export_enabled,
            "replay_export_for_solar_headroom": self._replay_export_for_solar_headroom,
            "replay_simulate_api_failure": self._replay_simulate_api_failure,
            "replay_pending_resume": self._replay_pending_resume,
            "replay_auto_resume_pending": self._replay_auto_resume_pending,
            "accepted_command_ids": ledger_to_storage(
                prune_command_ledger(
                    self._accepted_command_ids,
                    self.virtual_time_utc or datetime.now(timezone.utc),
                )
            ),
            "faults": [fault.to_dict() for fault in self._faults_for_storage()],
            "fault_snapshots": {
                name: [fault.to_dict() for fault in faults]
                for name, faults in self._named_fault_snapshots.items()
            },
            "control_config": _control_config_to_storage(self._config),
        }

    def _validated_fault_storage(
        self, record_value: object, *, expected_snapshot_names: set[str] | None = None,
    ) -> tuple[tuple[Fault, ...], dict[str, tuple[Fault, ...]]]:
        record = record_mapping(record_value)
        if record is None:
            raise ValueError("Stored fault state is invalid")
        if record.get("storage_schema_version") not in {5, 6, 7, 8, 9, STORAGE_SCHEMA_VERSION}:
            return (), {}
        faults = validate_faults(record.get("faults"))
        raw_snapshots = record.get("fault_snapshots")
        expected_names = set(self._named_snapshots) if expected_snapshot_names is None else expected_snapshot_names
        if not isinstance(raw_snapshots, Mapping) or set(raw_snapshots) != expected_names:
            raise ValueError("Stored fault snapshots are invalid")
        snapshots: dict[str, tuple[Fault, ...]] = {}
        for name, values in raw_snapshots.items():
            normalized = _snapshot_name(name)
            snapshots[normalized] = validate_faults(values)
        return faults, snapshots

    def _validated_storage_record(
        self, record_value: object,
    ) -> tuple[
        SimulationSnapshot,
        bool,
        dict[str, str],
        tuple[str | None, str | None, str],
        tuple[ReplaySession | None, float | None, bool | None, bool | None, bool, bool, bool],
        tuple[AcceptedCommandId, ...],
        BatteryConfig,
    ]:
        record = record_mapping(record_value)
        if record is None:
            raise ValueError("Stored state is not an object")
        storage_schema = record.get("storage_schema_version")
        if storage_schema not in {1, 2, 3, 4, 5, 6, 7, 8, 9, STORAGE_SCHEMA_VERSION}:
            raise ValueError("Unsupported storage schema")
        if record.get("snapshot_schema_version") not in {1, 2, SNAPSHOT_SCHEMA_VERSION}:
            raise ValueError("Unsupported snapshot schema")
        if record.get("entry_id") != self.entry_id:
            raise ValueError("Stored entry identity does not match")
        if record.get("registration_id") != self.registration_id:
            raise ValueError("Stored registration identity does not match")
        if record.get("pretend_gx_id") != self.pretend_gx_id:
            raise ValueError("Stored GX identity does not match")
        if not isinstance(record.get("simulator_enabled"), bool):
            raise ValueError("Stored enabled state is invalid")
        serialized = record.get("current_snapshot")
        if not isinstance(serialized, str):
            raise ValueError("Stored snapshot is invalid")
        control_config = self._config
        if control_config is None:
            raise ValueError("Sandbox configuration is unavailable")
        if storage_schema in {8, 9, STORAGE_SCHEMA_VERSION}:
            control_config = _control_config_from_storage(
                record.get("control_config"),
                fallback=control_config,
            )
        snapshots_value = record.get("snapshots", {})
        if not isinstance(snapshots_value, Mapping):
            raise ValueError("Stored snapshots are invalid")
        snapshots: dict[str, str] = {}
        if len(snapshots_value) > MAX_NAMED_SNAPSHOTS:
            raise ValueError("Stored snapshot limit is invalid")
        for name, snapshot_json in snapshots_value.items():
            normalized = _snapshot_name(name)
            if normalized in snapshots or not isinstance(snapshot_json, str):
                raise ValueError("Stored snapshot is invalid")
            self._validated_snapshot(from_json(snapshot_json), config=control_config)
            snapshots[normalized] = snapshot_json
        profile_state: tuple[str | None, str | None, str] = (None, None, "stopped")
        if storage_schema in {2, 3, 4, 5, 6, 7, 8, 9, STORAGE_SCHEMA_VERSION}:
            filename = record.get("selected_profile_filename")
            profile_hash = record.get("profile_hash")
            playback_state = record.get("playback_state")
            if filename is not None and (not isinstance(filename, str) or not filename):
                raise ValueError("Stored profile selection is invalid")
            if filename is None and profile_hash is not None:
                raise ValueError("Stored profile hash is invalid")
            if filename is not None and (
                not isinstance(profile_hash, str) or len(profile_hash) != 64
            ):
                raise ValueError("Stored profile hash is invalid")
            if playback_state not in _PLAYBACK_STATES:
                raise ValueError("Stored playback state is invalid")
            profile_state = (filename, profile_hash, playback_state)
        replay_state: tuple[ReplaySession | None, float | None, bool | None, bool | None, bool, bool, bool] = (
            None,
            None,
            None,
            None,
            False,
            False,
            False,
        )
        if storage_schema in {3, 4, 5, 6, 7, 8, 9, STORAGE_SCHEMA_VERSION}:
            session_value = record.get("replay_session")
            starting_energy = record.get("replay_starting_energy_wh")
            import_for_export = record.get("replay_import_for_export_enabled")
            export_for_solar_headroom = record.get("replay_export_for_solar_headroom")
            pending_resume = record.get("replay_pending_resume")
            auto_resume = (
                record.get("replay_auto_resume_pending")
                if storage_schema in {4, 5, 6, 7, 8, 9, STORAGE_SCHEMA_VERSION}
                else None
            )
            simulate_api_failure = (
                record.get("replay_simulate_api_failure")
                if storage_schema in {8, 9, STORAGE_SCHEMA_VERSION}
                else False
            )
            if session_value is None:
                if any(
                    value is not None
                    for value in (
                        starting_energy,
                        import_for_export,
                        export_for_solar_headroom,
                    )
                ) or pending_resume is not False or (
                    storage_schema in {4, 5, 6, 7, 8, 9, STORAGE_SCHEMA_VERSION} and auto_resume is not False
                ) or simulate_api_failure is not False:
                    raise ValueError("Stored replay state is invalid")
            else:
                session = ReplaySession.from_dict(session_value)
                if isinstance(starting_energy, bool):
                    raise ValueError("Stored replay starting energy is invalid")
                try:
                    starting_energy = float(starting_energy)
                except (TypeError, ValueError) as err:
                    raise ValueError("Stored replay starting energy is invalid") from err
                if not math.isfinite(starting_energy) or not (
                    control_config.reserve_wh <= starting_energy <= control_config.capacity_wh
                ):
                    raise ValueError("Stored replay starting energy is invalid")
                if not isinstance(import_for_export, bool) or not isinstance(
                    export_for_solar_headroom, bool
                ) or not isinstance(pending_resume, bool):
                    raise ValueError("Stored replay settings are invalid")
                if storage_schema in {4, 5, 6, 7, 8, 9, STORAGE_SCHEMA_VERSION} and not isinstance(auto_resume, bool):
                    raise ValueError("Stored replay resume state is invalid")
                if not isinstance(simulate_api_failure, bool):
                    raise ValueError("Stored replay simulated API failure state is invalid")
                if session.profile_identifier != filename or session.profile_hash != profile_hash:
                    raise ValueError("Stored replay profile identity is invalid")
                replay_state = (
                    session,
                    starting_energy,
                    import_for_export,
                    export_for_solar_headroom,
                    pending_resume,
                    (
                        auto_resume
                        if storage_schema in {4, 5, 6, 7, 8, 9, STORAGE_SCHEMA_VERSION}
                        else session.state in _REPLAY_ACTIVE_STATES or pending_resume
                    ),
                    simulate_api_failure,
                )
        snapshot = self._validated_snapshot(from_json(serialized), config=control_config)
        command_ledger = (
            ledger_from_storage(
                record.get("accepted_command_ids"),
                snapshot.clock_state.virtual_time_utc,
            )
            if storage_schema in {6, 7, 8, 9, STORAGE_SCHEMA_VERSION}
            else ()
        )
        return (
            snapshot,
            record["simulator_enabled"],
            snapshots,
            profile_state,
            replay_state,
            command_ledger,
            control_config,
        )

    def _simulation_snapshot(self) -> SimulationSnapshot:
        if self._state is None or self._clock is None:
            raise ValueError("Sandbox state is unavailable")
        return SimulationSnapshot(
            SNAPSHOT_SCHEMA_VERSION,
            self._state,
            self._cumulative_ledger,
            self._clock.state,
            self._active_profile_id,
            self._profile_cursor,
            self._command,
            self.last_command_status,
            self.load_w,
            self.solar_w,
            _control_config_to_storage(self._config),
            self._playback_state,
            self._selected_profile_filename,
            self._profile_hash,
            self._replay_session.to_dict() if self._replay_session is not None else None,
            tuple(fault.to_dict() for fault in self._faults_for_storage()),
        )

    def _validated_snapshot(
        self,
        snapshot: SimulationSnapshot,
        *,
        config: BatteryConfig | None = None,
    ) -> SimulationSnapshot:
        active_config = self._config if config is None else config
        if active_config is None:
            raise ValueError("Sandbox configuration is unavailable")
        if not active_config.reserve_wh <= snapshot.battery_state.energy_wh <= active_config.capacity_wh:
            raise ValueError("Stored energy is outside reserve and capacity")
        values = [
            snapshot.battery_state.energy_wh,
            *(
                getattr(snapshot.cumulative_ledger, field_name)
                for field_name in snapshot.cumulative_ledger.__dataclass_fields__
            ),
        ]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Stored numeric state is invalid")
        if (
            isinstance(snapshot.load_w, bool)
            or isinstance(snapshot.solar_w, bool)
            or not all(
                isinstance(value, (int, float))
                and math.isfinite(value)
                and 0 <= value <= _MAX_POWER_W
                for value in (snapshot.load_w, snapshot.solar_w)
            )
        ):
            raise ValueError("Snapshot inputs are invalid")
        if snapshot.playback_state not in _PLAYBACK_STATES:
            raise ValueError("Snapshot playback state is invalid")
        if (snapshot.selected_profile_filename is None) != (snapshot.profile_hash is None):
            raise ValueError("Snapshot profile identity is invalid")
        if snapshot.selected_profile_filename is not None and (
            not isinstance(snapshot.selected_profile_filename, str)
            or not isinstance(snapshot.profile_hash, str)
            or len(snapshot.profile_hash) != 64
        ):
            raise ValueError("Snapshot profile identity is invalid")
        if snapshot.control_config is not None:
            _control_config_from_storage(snapshot.control_config, fallback=active_config)
        if snapshot.faults:
            validate_faults(list(snapshot.faults))
        if snapshot.replay_session is not None:
            ReplaySession.from_dict(snapshot.replay_session)
        ClockRate(snapshot.clock_state.rate)
        if (
            snapshot.clock_state.virtual_time_utc.tzinfo is None
            or snapshot.clock_state.virtual_time_utc.utcoffset() is None
        ):
            raise ValueError("Stored virtual time is invalid")
        if snapshot.clock_state.sequence < 0 or snapshot.clock_state.reset_generation < 0:
            raise ValueError("Stored clock state is invalid")
        if snapshot.profile_cursor is not None and snapshot.profile_cursor.profile_id != snapshot.active_profile_id:
            raise ValueError("Stored profile cursor is invalid")
        if snapshot.active_command is not None:
            if (
                snapshot.active_command.requested_grid_power_w is not None
                and not math.isfinite(snapshot.active_command.requested_grid_power_w)
            ):
                raise ValueError("Stored command is invalid")
            for timestamp in (
                snapshot.active_command.issued_at_utc,
                snapshot.active_command.expires_at_utc,
            ):
                if timestamp is not None and (
                    timestamp.tzinfo is None or timestamp.utcoffset() is None
                ):
                    raise ValueError("Stored command timestamp is invalid")
        return snapshot

    def _apply_snapshot(self, snapshot: SimulationSnapshot) -> None:
        self._state = snapshot.battery_state
        self._cumulative_ledger = snapshot.cumulative_ledger
        self._clock = VirtualClock.from_state(snapshot.clock_state)
        self._active_profile_id = snapshot.active_profile_id
        self._profile_cursor = snapshot.profile_cursor
        self._command = snapshot.active_command
        self.last_command_status = snapshot.command_status
        self.last_command_reason = None


    def current_capacity(self) -> str:
        """Return this runtime's capacity in Wh for the forecast request."""
        if self._state is None:
            return ""
        return str(round(self._state.energy_wh, 3))

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register an entry-local state listener and return its disposer."""
        self._listeners.append(listener)

        def remove_listener() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove_listener

    async def async_enable(self, hass: HomeAssistant) -> None:
        """Start direct HA control and the entry-local virtual clock."""
        if self._unloaded:
            raise RuntimeError("Sandbox runtime has been unloaded")
        if self.simulator_enabled:
            return
        if not self.is_sandbox_configured:
            raise ValueError(self.available_reason or "Sandbox is unavailable")

        self.simulator_enabled = True
        self._hass = hass
        try:
            self._subscribe_to_coordinator_forecasts()
            for fault in self._faults:
                if fault.state is FaultState.ACTIVE:
                    self._schedule_fault_expiry(fault)
            await self._async_refresh_direct_forecast()
            self._task = hass.async_create_task(self._async_loop(hass))
        except Exception:
            await self.async_disable()
            raise
        await self.async_checkpoint(immediate=True)
        self._notify_listeners()

    async def async_disable(
        self,
        *,
        resume_coordinator: bool = True,
        checkpoint: bool = True,
    ) -> None:
        """Stop only this sandbox and resume its own cloud coordinator once."""
        if (
            not self.simulator_enabled
            and self._task is None
            and not self._coordinator_paused
        ):
            return
        if self._pending_command is not None:
            await self._async_finish_pending_command(
                CommandLifecycleState.FAILED,
                "Sandbox runtime stopped before command correlation completed.",
            )
        self._cancel_replay_timeout()
        self._cancel_replay_heartbeat()
        self._freeze_fault_durations()
        self._cancel_all_fault_work()
        self._mqtt_fault_disconnected = False
        if self._replay_session is not None and self._replay_session.state in (
            _REPLAY_ACTIVE_STATES | {ReplayState.RUNNING, ReplayState.PAUSED}
        ):
            self._replay_pending_resume = True
            self._replay_auto_resume_pending = True
        self.simulator_enabled = False
        task, self._task = self._task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        self._hass = None
        if self._coordinator_paused and resume_coordinator:
            self._coordinator_paused = False
            await self.coordinator.async_resume_from_sandbox()
        elif self._coordinator_paused:
            self._coordinator_paused = False
        if checkpoint:
            await self.async_checkpoint(immediate=True)
        self._notify_listeners()

    async def async_unload(self) -> None:
        """Release all entry-local async work without affecting other entries."""
        was_enabled = self.simulator_enabled
        await self.async_disable(resume_coordinator=False, checkpoint=False)
        await self.async_checkpoint(immediate=True, enabled_override=was_enabled)
        self._unloaded = True
        self._listeners.clear()

    def set_clock_rate(self, rate: ClockRate) -> None:
        """Set this sandbox's virtual clock rate."""
        if self._unloaded:
            raise RuntimeError("Sandbox runtime has been unloaded")
        if self._clock is None:
            raise ValueError("Sandbox is unavailable")
        self._clock.set_rate(rate)
        self._schedule_immediate_checkpoint()
        self._notify_listeners()

    async def async_step(self, seconds: float = 1800) -> None:
        """Advance and apply one deterministic virtual-battery step."""
        if not self.simulator_enabled:
            raise ValueError("Sandbox is inactive")
        if self._clock is None:
            raise ValueError("Sandbox is unavailable")
        if self._replay_session is not None and self._replay_session.state is ReplayState.PAUSED:
            return
        self._clock.step(seconds)
        await self._async_refresh_direct_forecast()
        await self._async_simulate(seconds, hass=self._hass)
        if self._replay_session is not None and self._replay_session.state in {
            ReplayState.RUNNING,
            ReplayState.PAUSED,
        }:
            await self._async_publish_replay_clock(immediate=True)
        await self._async_publish_runtime_statuses(force=True)
        await self.async_checkpoint(immediate=True)

    def reset(self, *, energy_wh: float | None = None) -> None:
        """Reset this sandbox state without changing another runtime's clock."""
        if self._unloaded:
            raise RuntimeError("Sandbox runtime has been unloaded")
        if self._config is None or self._clock is None:
            raise ValueError("Sandbox is unavailable")
        target = self._config.capacity_wh * 0.5 if energy_wh is None else energy_wh
        if not self._config.reserve_wh <= target <= self._config.capacity_wh:
            raise ValueError("Battery energy is outside reserve and capacity")
        self._state = BatteryState(target)
        self._last_grid_power_w = 0.0
        self._last_battery_power_w = 0.0
        self._cumulative_ledger = IntervalLedger()
        self._command = None
        self.last_command_status = CommandStatus.AWAITING_FORECAST
        self.last_command_reason = "Awaiting direct forecast."
        self._direct_forecast_health = "awaiting_forecast"
        self._clock.reset(datetime.now(timezone.utc))
        self._schedule_immediate_checkpoint()
        self._notify_listeners()

    async def async_reset(self, *, energy_wh: float | None = None) -> None:
        """Reset and durably checkpoint this sandbox before returning."""
        if self._pending_command is not None:
            await self._async_finish_pending_command(
                CommandLifecycleState.FAILED,
                "Sandbox reset before command correlation completed.",
            )
        self.reset(energy_wh=energy_wh)
        if self._staged_forecast_covers_virtual_time():
            await self._async_stage_direct_forecast(self._staged_direct_forecast)
        await self._async_publish_telemetry_snapshot()
        await self._async_publish_runtime_statuses(force=True)
        await self.async_checkpoint(immediate=True)

    def set_inputs(self, *, load_w: float, solar_w: float) -> None:
        """Set entry-local synthetic load and solar inputs."""
        if self._unloaded:
            raise RuntimeError("Sandbox runtime has been unloaded")
        if not all(
            math.isfinite(value) and 0 <= value <= _MAX_POWER_W
            for value in (load_w, solar_w)
        ):
            raise ValueError(
                "Load and solar power must be finite and within the supported range"
            )
        self.load_w = load_w
        self.solar_w = solar_w
        self._schedule_immediate_checkpoint()
        self._notify_listeners()

    async def async_set_inputs(self, *, load_w: float, solar_w: float) -> None:
        """Set manual synthetic inputs and republish the owning sandbox state."""
        self.set_inputs(load_w=load_w, solar_w=solar_w)
        if self.simulator_enabled:
            await self._async_publish_telemetry_snapshot()
            await self._async_publish_runtime_statuses(force=True)
        await self.async_checkpoint(immediate=True)

    async def async_set_control_value(self, field_name: str, value: float) -> None:
        """Update one bounded virtual-battery control for this entry only."""
        if not self.simulator_enabled or self._config is None or self._state is None:
            raise ValueError("Sandbox is inactive")
        if not math.isfinite(value):
            raise ValueError("Control value must be finite")
        values = {
            "capacity_wh": self._config.capacity_wh,
            "reserve_wh": self._config.reserve_wh,
            "max_charge_power_w": self._config.max_charge_power_w,
            "max_discharge_power_w": self._config.max_discharge_power_w,
            "charge_efficiency": self._config.charge_efficiency,
            "discharge_efficiency": self._config.discharge_efficiency,
        }
        if field_name not in values:
            raise ValueError("Sandbox control is invalid")
        values[field_name] = value
        if (
            values["capacity_wh"] <= 0
            or not 0 <= values["reserve_wh"] <= values["capacity_wh"]
            or values["capacity_wh"] > _MAX_ENERGY_WH
            or values["reserve_wh"] > _MAX_ENERGY_WH
            or not 0 <= values["max_charge_power_w"] <= _MAX_POWER_W
            or not 0 <= values["max_discharge_power_w"] <= _MAX_POWER_W
            or not 0 < values["charge_efficiency"] <= 1
            or not 0 < values["discharge_efficiency"] <= 1
        ):
            raise ValueError("Sandbox control value is outside the supported range")
        self._config = replace(self._config, **values)
        energy = min(self._config.capacity_wh, max(self._config.reserve_wh, self._state.energy_wh))
        self._state = BatteryState(energy)
        await self._async_publish_telemetry_snapshot()
        await self._async_publish_runtime_statuses(force=True)
        await self.async_checkpoint(immediate=True)
        self._notify_listeners()

    async def async_set_state_of_charge(self, state_of_charge: float) -> None:
        """Atomically set this active virtual battery's stored energy in percent.

        This is simulator setup, rather than a modeled grid/solar flow.  The
        signed ledger term keeps the energy-balance equation explicit while
        leaving every physical input and the virtual clock unchanged.
        """
        if isinstance(state_of_charge, bool) or not math.isfinite(state_of_charge):
            raise ValueError("State of charge must be a finite percentage")
        async with self._state_lock:
            if (
                self._unloaded
                or not self.simulator_enabled
                or self._config is None
                or self._state is None
            ):
                raise ValueError("Sandbox is inactive")
            if self._playback_state == "running" or (
                self._replay_session is not None
                and self._replay_session.state
                in (_REPLAY_ACTIVE_STATES | {ReplayState.RUNNING, ReplayState.PAUSED})
            ):
                raise ValueError("Stop profile playback or replay before setting state of charge")
            reserve_percent = self._config.reserve_wh / self._config.capacity_wh * 100
            if not reserve_percent <= state_of_charge <= 100:
                raise ValueError(
                    f"State of charge must be between reserve ({reserve_percent:g}%) and 100%"
                )

            target_energy_wh = self._config.capacity_wh * state_of_charge / 100
            adjustment_wh = target_energy_wh - self._state.energy_wh
            self._state = BatteryState(target_energy_wh)
            ledger_values = {
                name: getattr(self._cumulative_ledger, name)
                for name in self._cumulative_ledger.__dataclass_fields__
            }
            ledger_values["manual_adjustment_wh"] += adjustment_wh
            if adjustment_wh >= 0:
                ledger_values["battery_energy_increase_wh"] += adjustment_wh
            else:
                ledger_values["battery_energy_decrease_wh"] -= adjustment_wh
            self._cumulative_ledger = IntervalLedger(**ledger_values)

            # A command calculated for the former energy level must never
            # continue.  Keep the cadence-limited forecast request untouched.
            self._command = Command(OperatingMode.SELF_CONSUMPTION)
            self._last_direct_command_id = None
            self.last_command_status = CommandStatus.AWAITING_FORECAST
            self.last_command_reason = "Awaiting scheduled forecast after manual state-of-charge change."
            self._direct_forecast_health = "awaiting_forecast"
            self._clear_pending_command()

            await self._async_publish_telemetry_snapshot()
            await self._async_publish_runtime_statuses(force=True)
            await self.async_checkpoint(immediate=True)
            self._notify_listeners()

    async def async_select_scenario(self, scenario: str) -> None:
        """Apply one deterministic built-in scenario without loading a profile."""
        from .simulation.profiles import standard_scenarios

        if not self.simulator_enabled or self._clock is None:
            raise ValueError("Sandbox is inactive")
        selected = next(
            (item for item in standard_scenarios(self._clock.state.virtual_time_utc)
             if item.identifier == scenario),
            None,
        )
        if selected is None:
            raise ValueError("Scenario is invalid")
        period = selected.profile.periods[0]
        self._playback_state = "stopped"
        self._active_profile = None
        self._active_profile_id = None
        self._profile_cursor = None
        self._selected_profile_filename = None
        self._profile_hash = None
        self._command = Command(OperatingMode.SELF_CONSUMPTION)
        await self.async_set_inputs(load_w=period.load_w, solar_w=period.solar_w)

    async def _async_loop(self, hass: HomeAssistant) -> None:
        try:
            while self.simulator_enabled:
                await asyncio.sleep(_LOOP_INTERVAL_SECONDS)
                if not self.simulator_enabled or self._clock is None:
                    return
                before = self._clock.state.virtual_time_utc
                after = self._clock.advance(_LOOP_INTERVAL_SECONDS).virtual_time_utc
                elapsed_seconds = (after - before).total_seconds()
                if elapsed_seconds:
                    if after.minute % 30 == 0 and after.second == 0:
                        await self._async_refresh_direct_forecast()
                    await self._async_simulate(elapsed_seconds, hass=hass)
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.async_disable()

    async def _async_simulate(
        self,
        elapsed_seconds: float,
        *,
        hass: HomeAssistant | None = None,
    ) -> None:
        if (
            self._unloaded
            or not self.simulator_enabled
            or self._config is None
            or self._state is None
            or self._clock is None
        ):
            return
        end_time = self._clock.state.virtual_time_utc
        start_time = end_time - timedelta(seconds=elapsed_seconds)
        if (
            self._pending_command is not None
            and end_time >= self._pending_command.expires_at_utc
        ):
            await self._async_finish_pending_command(
                CommandLifecycleState.EXPIRED,
                "Issued command expired before correlation completed.",
            )
        if self._replay_session is not None and self._replay_session.state is ReplayState.PAUSED:
            return
        if self._playback_state == "running" and self._active_profile is not None:
            await self._async_play_profile_interval(start_time, end_time, hass=hass)
            return
        await self._async_simulate_segment(
            elapsed_seconds,
            end_time,
            self.load_w,
            self.solar_w,
            hass=hass,
        )

    async def _async_play_profile_interval(
        self,
        start_time: datetime,
        end_time: datetime,
        *,
        hass: HomeAssistant | None,
    ) -> None:
        if self._active_profile is None or self._profile_cursor is None:
            return
        current = start_time
        while current < end_time and self._playback_state == "running":
            index = self._profile_cursor.index
            if index >= len(self._active_profile.samples):
                await self._async_complete_replay()
                return
            sample = self._active_profile.samples[index]
            sample_end = sample.timestamp_utc + timedelta(minutes=5)
            if current < sample.timestamp_utc or current >= sample_end:
                raise ValueError("Virtual clock is outside the selected profile")
            segment_end = min(end_time, sample_end)
            await self._async_apply_direct_replay_action(segment_end)
            await self._async_simulate_segment(
                (segment_end - current).total_seconds(),
                segment_end,
                sample.load_w,
                sample.solar_w,
                hass=hass,
            )
            current = segment_end
            if current == sample_end:
                self._profile_cursor = ProfileCursor(
                    self._active_profile.identifier,
                    index + 1,
                )
                if self._profile_cursor.index == len(self._active_profile.samples):
                    await self._async_complete_replay()
                elif current.minute % 30 == 0 and current.second == 0:
                    await self._async_publish_replay_clock(immediate=True)

    async def _async_apply_direct_replay_action(self, virtual_now_utc: datetime) -> None:
        """Apply the cached replay horizon only at the owning virtual time."""
        if self._direct_replay_payload is None or self._config is None:
            return
        try:
            direct = parse_replay_command(
                self._direct_replay_payload,
                virtual_now_utc=virtual_now_utc,
                config=self._config,
            )
            if direct.replay_key != self._last_direct_replay_key:
                self._command = direct.command
                self._last_direct_replay_key = direct.replay_key
                self.last_command_status = CommandStatus.APPLIED
                self.last_command_reason = direct.action
        except ValueError:
            self._command = Command(OperatingMode.SELF_CONSUMPTION)
            self.last_command_status = CommandStatus.FALLBACK_INVALID
            self.last_command_reason = "Direct replay rejected; self-consumption used."
            await self._async_fail_replay("Direct replay horizon is invalid.")

    async def _async_simulate_segment(
        self,
        elapsed_seconds: float,
        virtual_time_utc: datetime,
        load_w: float,
        solar_w: float,
        *,
        hass: HomeAssistant | None,
    ) -> None:
        if self._config is None or self._state is None:
            return
        result = simulate_step(
            previous=self._state,
            elapsed_seconds=elapsed_seconds,
            virtual_time_utc=virtual_time_utc,
            command=self._command,
            load_w=load_w,
            solar_w=solar_w,
            config=self._config,
        )
        self._state = result.state
        self._last_grid_power_w = result.actual_grid_power_w
        self._last_battery_power_w = result.battery_ac_power_w
        if (
            self._direct_forecast_health == "healthy"
            and self._last_direct_command_id is None
            and self._command is not None
            and self._command.mode is OperatingMode.SELF_CONSUMPTION
        ):
            self.last_command_status = CommandStatus.NO_ACTION
            self.last_command_reason = "No executable action; self-consumption applied."
        else:
            self.last_command_status = result.command_status
            self.last_command_reason = result.reason
        self.last_health = result.health
        self._cumulative_ledger = self._cumulative_ledger.plus(result.ledger)
        self._schedule_checkpoint()
        self._notify_listeners()
        if hass is not None:
            await self._async_publish_runtime_statuses()

    async def _async_refresh_direct_forecast(self) -> None:
        """Fetch and apply one validated Forecast_Get action without MQTT authority."""
        if not self.simulator_enabled or self._config is None or self._clock is None:
            return
        try:
            forecast = await self.coordinator.async_fetch_sandbox_forecast()
        except Exception as err:
            self._logger_debug_direct_failure(err)
            forecast = None
        await self._async_stage_direct_forecast(forecast)

    def _subscribe_to_coordinator_forecasts(self) -> None:
        """Stage normal coordinator updates even while virtual time is paused."""
        subscribe = getattr(self.coordinator, "async_add_listener", None)
        if not callable(subscribe):
            return
        self._unsubscribers.append(subscribe(self._on_coordinator_forecast))

    def _on_coordinator_forecast(self) -> None:
        """Schedule forecast validation without advancing the simulation clock."""
        if not self.simulator_enabled or self._hass is None:
            return
        snapshot = getattr(self.coordinator, "data", None)
        forecast = getattr(snapshot, "direct_forecast", None)
        self._hass.async_create_task(self._async_stage_direct_forecast(forecast))

    async def _async_stage_direct_forecast(self, forecast: Forecast | None) -> None:
        """Validate and apply a coordinator forecast independently of physics time."""
        if not self.simulator_enabled or self._config is None or self._clock is None:
            return
        async with self._direct_forecast_lock:
            live_now_utc = self._live_forecast_now()
            validation = validate_live_forecast(
                forecast,
                now_utc=live_now_utc,
                config=self._config,
            )
            if not validation.is_valid:
                rejection = validation.rejection or DirectForecastRejection.OTHER_INVALID
                self._command = Command(OperatingMode.SELF_CONSUMPTION)
                self.last_command_status = CommandStatus.FALLBACK_INVALID
                self.last_command_reason = f"direct_forecast:{rejection.value}"
                self._direct_forecast_health = "failed"
                _LOGGER.debug(
                    "Rejected direct forecast for entry %s: %s",
                    self.entry_id,
                    rejection.value,
                )
                await self.async_checkpoint(immediate=True)
                self._notify_listeners()
                return
            try:
                direct = validation.command
                assert direct is not None
                self._staged_direct_forecast = forecast
                if direct.command_id is None:
                    self._command = direct.command
                    self._last_direct_command_id = None
                    self.last_command_status = CommandStatus.NO_ACTION
                    self.last_command_reason = (
                        "No executable action; self-consumption applied."
                    )
                    self._direct_forecast_health = "healthy"
                elif direct.command_id == self._last_direct_command_id:
                    self._direct_forecast_health = "healthy"
                elif any(
                    entry.command_id == direct.command_id
                    for entry in self._accepted_command_ids
                ):
                    if (
                        self._command is not None
                        and self._command.expires_at_utc is not None
                        and live_now_utc < self._command.expires_at_utc
                    ):
                        self._last_direct_command_id = direct.command_id
                        self._direct_forecast_health = "healthy"
                    else:
                        raise ValueError("Forecast command is a terminal duplicate")
                else:
                    self._accepted_command_ids, accepted = accept_command_id(
                        self._accepted_command_ids,
                        direct.command_id,
                        live_now_utc,
                    )
                    if not accepted:
                        raise ValueError("Forecast command is a retained duplicate")
                    self._command = direct.command
                    self._last_direct_command_id = direct.command_id
                    self.last_command_status = CommandStatus.APPLIED
                    self.last_command_reason = direct.action
                    self._direct_forecast_health = "healthy"
            except Exception as err:
                self._command = Command(OperatingMode.SELF_CONSUMPTION)
                self.last_command_status = CommandStatus.FALLBACK_INVALID
                self.last_command_reason = "Direct forecast rejected; self-consumption used."
                self._direct_forecast_health = "failed"
                self._logger_debug_direct_failure(err)
            await self.async_checkpoint(immediate=True)
            self._notify_listeners()

    def _staged_forecast_covers_virtual_time(self) -> bool:
        """Only reapply a cached plan when it is current after a reset."""
        if self._staged_direct_forecast is None or self._clock is None:
            return False
        now_utc = self._live_forecast_now()
        return any(
            period.starts_at_utc <= now_utc < period.starts_at_utc + timedelta(minutes=30)
            for period in self._staged_direct_forecast.periods
        )

    def _logger_debug_direct_failure(self, err: Exception) -> None:
        """Keep malformed or failed direct forecast details out of state."""
        return

    def _active_fault(self, kind: FaultKind) -> Fault | None:
        return next((fault for fault in self._faults if fault.kind is kind and fault.state is FaultState.ACTIVE), None)

    def _replace_fault(self, replacement: Fault) -> None:
        self._faults = tuple(
            replacement if fault.fault_id == replacement.fault_id else fault
            for fault in self._faults
        )

    def _consume_outbound_fault(self, kind: FaultKind) -> None:
        fault = self._active_fault(kind)
        if fault is None:
            return
        self._replace_fault(consume_fault_event(fault))
        self._schedule_immediate_checkpoint()

    def _reject_command_for_fault(self) -> bool:
        fault = self._active_fault(FaultKind.REJECT_COMMAND)
        if fault is None:
            return False
        self._consume_outbound_fault(FaultKind.REJECT_COMMAND)
        self.last_command_status = CommandStatus.FALLBACK_INVALID
        self.last_command_reason = "Sandbox command rejected by local fault injection."
        return True

    async def _async_restart_for_fault(self, fault: Fault) -> None:
        """Restart this runtime through its own Store path; never restart HA/process MQTT."""
        if self._hass is None or not self.simulator_enabled or fault.state is not FaultState.ACTIVE:
            return
        self._replace_fault(consume_fault_event(fault, "runtime restart consumed"))
        await self.async_checkpoint(immediate=True)
        hass = self._hass
        was_enabled = self.simulator_enabled
        await self.async_disable(checkpoint=False)
        if was_enabled and not self._unloaded:
            try:
                await self.async_restore_storage(hass)
            except Exception:
                self.simulator_enabled = False
                self.storage_diagnostic = "Fault-injected runtime restoration failed; simulator is disabled."
                self._notify_listeners()

    def _schedule_fault_expiry(self, fault: Fault) -> None:
        if fault.remaining_duration_seconds is None or self._hass is None:
            return
        self._cancel_fault_work(fault.fault_id)
        self._fault_timer_generation += 1
        generation = self._fault_timer_generation
        self._fault_timer_generations[fault.fault_id] = generation
        self._fault_duration_deadlines[fault.fault_id] = (
            self._hass.loop.time() + fault.remaining_duration_seconds
        )
        self._fault_duration_handles[fault.fault_id] = self._hass.loop.call_later(
            fault.remaining_duration_seconds,
            self._fault_expiry_due,
            fault.fault_id,
            fault.remaining_duration_seconds,
            generation,
        )

    def _fault_expiry_due(self, fault_id: str, duration: float, generation: int) -> None:
        self._fault_duration_handles.pop(fault_id, None)
        self._fault_duration_deadlines.pop(fault_id, None)
        if self._hass is not None:
            self._hass.async_create_task(
                self._async_expire_fault(fault_id, duration, generation)
            )

    async def _async_expire_fault(
        self, fault_id: str, duration: float, generation: int
    ) -> None:
        if (
            self._unloaded
            or not self.simulator_enabled
            or self._fault_timer_generations.get(fault_id) != generation
        ):
            return
        self._fault_timer_generations.pop(fault_id, None)
        fault = next((item for item in self._faults if item.fault_id == fault_id), None)
        if fault is None or fault.state is not FaultState.ACTIVE:
            return
        self._replace_fault(advance_fault_duration(fault, duration))
        self._maybe_leave_fault_disconnect()
        await self.async_checkpoint(immediate=True)
        await self._async_publish_runtime_statuses(force=True)
        self._notify_listeners()

    async def _async_enter_fault_disconnect(self, fault: Fault) -> None:
        if self._unloaded or not self.simulator_enabled or fault.state is not FaultState.ACTIVE:
            return
        if self._pending_command is not None:
            await self._async_finish_pending_command(
                CommandLifecycleState.FAILED,
                "Sandbox MQTT disconnected before command correlation completed.",
            )
        self._mqtt_fault_disconnected = True
        self._command = Command(OperatingMode.SELF_CONSUMPTION)
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        self._discard_delayed_outbound()

    def _maybe_leave_fault_disconnect(self) -> None:
        if self._active_fault(FaultKind.MQTT_DISCONNECT) is not None:
            return
        if not self._mqtt_fault_disconnected:
            return
        self._mqtt_fault_disconnected = False
        if self._hass is not None and self.simulator_enabled and not self._unloaded:
            self._hass.async_create_task(self._async_reconnect_fault_mqtt(self._hass))

    async def _async_reconnect_fault_mqtt(self, hass: HomeAssistant) -> None:
        if self._unloaded or not self.simulator_enabled or self._hass is not hass or self._mqtt_fault_disconnected:
            return
        try:
            await self._async_subscribe_mqtt(hass)
        except Exception:
            await self.async_disable()
            return
        await self._async_publish_runtime_statuses(force=True)

    def _cancel_fault_work(self, fault_id: str) -> None:
        handle = self._fault_duration_handles.pop(fault_id, None)
        if handle is not None:
            handle.cancel()
        self._fault_duration_deadlines.pop(fault_id, None)
        self._fault_timer_generations.pop(fault_id, None)

    def _cancel_all_fault_work(self) -> None:
        for handle in self._fault_duration_handles.values():
            handle.cancel()
        self._fault_duration_handles.clear()
        self._fault_duration_deadlines.clear()
        self._fault_timer_generations.clear()
        self._discard_delayed_outbound()

    def _faults_for_storage(self) -> tuple[Fault, ...]:
        """Serialize active timed faults with their elapsed enabled-runtime time."""
        if self._hass is None:
            return self._faults
        now = self._hass.loop.time()
        return tuple(
            self._fault_with_remaining_duration(fault, now) for fault in self._faults
        )

    def _freeze_fault_durations(self) -> None:
        """Stop timed faults without charging time while this runtime is disabled."""
        if self._hass is None:
            return
        now = self._hass.loop.time()
        self._faults = tuple(
            self._fault_with_remaining_duration(fault, now) for fault in self._faults
        )

    def _fault_with_remaining_duration(self, fault: Fault, now: float) -> Fault:
        deadline = self._fault_duration_deadlines.get(fault.fault_id)
        if fault.state is not FaultState.ACTIVE or deadline is None:
            return fault
        remaining = max(0.0, deadline - now)
        return advance_fault_duration(
            fault, max(0.0, fault.remaining_duration_seconds - remaining)
        )

    def _reset_node_red_status(self) -> None:
        """Discard observed Node-RED state until this entry receives a fresh status."""
        if self.pretend_gx_id is None:
            self._node_red_status = None
            return
        self._node_red_status = RuntimeStatus(
            self.pretend_gx_id,
            datetime.min.replace(tzinfo=timezone.utc),
            "unavailable",
            "Awaiting a fresh Node-RED status.",
        )

    def _discard_delayed_outbound(self) -> None:
        self._delayed_outbound.clear()
        if self._delayed_outbound_handle is not None:
            self._delayed_outbound_handle.cancel()
            self._delayed_outbound_handle = None

    async def _async_publish_outbound(
        self, topic: str, payload: str, *, telemetry: bool = False, retain: bool = False,
    ) -> bool:
        if (not self._mqtt_emulation_enabled or self._hass is None or self.pretend_gx_id is None or self._unloaded or self._mqtt_fault_disconnected):
            return False
        gx = self.pretend_gx_id
        if not (topic.startswith(f"victron/N/{gx}/") or topic.startswith(f"horizoniq/sandbox/{gx}/")):
            raise ValueError("Sandbox outbound topic is invalid")
        if self._active_fault(FaultKind.DROP_MQTT) is not None:
            self._consume_outbound_fault(FaultKind.DROP_MQTT)
            return False
        delay = self._active_fault(FaultKind.DELAY_MQTT)
        if delay is not None:
            self._consume_outbound_fault(FaultKind.DELAY_MQTT)
            if len(self._delayed_outbound) >= 100:
                return False
            self._delayed_outbound.append(_DelayedOutbound(topic, payload, retain))
            if self._delayed_outbound_handle is None:
                seconds = dict(delay.settings)["delay_seconds"]
                self._delayed_outbound_handle = self._hass.loop.call_later(seconds, self._delayed_outbound_due)
            return False
        if telemetry and self._active_fault(FaultKind.MALFORMED_TELEMETRY) is not None:
            self._consume_outbound_fault(FaultKind.MALFORMED_TELEMETRY)
            payload = '{"value":["invalid"]}'
        try:
            await mqtt.async_publish(self._hass, topic, payload, retain=retain)
        except HomeAssistantError:
            return False
        return True

    def _delayed_outbound_due(self) -> None:
        self._delayed_outbound_handle = None
        if self._hass is not None:
            self._hass.async_create_task(self._async_flush_delayed_outbound())

    async def _async_flush_delayed_outbound(self) -> None:
        if self._unloaded or not self.simulator_enabled or self._mqtt_fault_disconnected or not self._delayed_outbound:
            self._discard_delayed_outbound()
            return
        item = self._delayed_outbound.pop(0)
        try:
            await mqtt.async_publish(self._hass, item.topic, item.payload, retain=item.retain)
        except HomeAssistantError:
            pass
        if self._delayed_outbound and self._hass is not None:
            delay = self._active_fault(FaultKind.DELAY_MQTT)
            seconds = dict(delay.settings)["delay_seconds"] if delay is not None else 0.1
            self._delayed_outbound_handle = self._hass.loop.call_later(seconds, self._delayed_outbound_due)

    async def _async_subscribe_mqtt(self, hass: HomeAssistant) -> None:
        if self._unloaded or self.pretend_gx_id is None:
            return
        for key in VictronCommandKey:
            self._unsubscribers.append(
                await mqtt.async_subscribe(
                    hass,
                    command_topic(self.pretend_gx_id, key),
                    self._async_handle_victron_write,
                )
            )
        self._unsubscribers.append(
            await mqtt.async_subscribe(
                hass,
                refresh_topic(self.pretend_gx_id),
                self._async_handle_victron_refresh,
            )
        )
        self._unsubscribers.append(
            await mqtt.async_subscribe(
                hass,
                command_issued_topic(self.pretend_gx_id),
                self._async_handle_command_issued,
            )
        )
        self._unsubscribers.append(
            await mqtt.async_subscribe(
                hass,
                replay_status_topic(self.pretend_gx_id),
                self._async_handle_replay_status,
            )
        )
        self._unsubscribers.append(
            await mqtt.async_subscribe(
                hass,
                node_red_status_topic(self.pretend_gx_id),
                self._async_handle_node_red_status,
            )
        )

    async def _async_handle_node_red_status(self, message: mqtt.ReceiveMessage) -> None:
        """Keep only the newest strict non-retained Node-RED status in memory."""
        if (
            self._unloaded
            or not self.simulator_enabled
            or self._mqtt_fault_disconnected
            or inbound_is_retained(message)
            or self.pretend_gx_id is None
        ):
            return
        try:
            status = parse_runtime_status(
                json.loads(message.payload),
                owning_gx_device_id=self.pretend_gx_id,
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        if (
            self._node_red_status is not None
            and status.timestamp_utc <= self._node_red_status.timestamp_utc
        ):
            return
        self._node_red_status = status
        self._notify_listeners()

    async def _async_handle_replay_status(self, message: mqtt.ReceiveMessage) -> None:
        """Accept only one valid, in-order status for this entry's active replay."""
        if (
            self._unloaded
            or not self.simulator_enabled
            or self._mqtt_fault_disconnected
            or inbound_is_retained(message)
            or self.pretend_gx_id is None
            or self._replay_session is None
            or self._replay_session.state not in _REPLAY_ACTIVE_STATES
        ):
            return
        try:
            payload = json.loads(message.payload)
            status = validate_remote_status(
                payload,
                owning_gx_device_id=self.pretend_gx_id,
                active_replay_id=self._replay_session.replay_id,
            )
            if self._replay_simulate_api_failure and (
                status.state.value != "failed"
                or status.reason != SIMULATED_REPLAY_API_FAILURE_REASON
            ):
                return
            updated = apply_remote_status(self._replay_session, status)
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        self._replay_session = updated
        if updated.state in {
            ReplayState.READY,
            ReplayState.REJECTED,
            ReplayState.FAILED,
        }:
            self._cancel_replay_timeout()
        if updated.state is ReplayState.READY:
            await self._async_start_ready_replay()
            return
        await self.async_checkpoint(immediate=True)
        await self._async_publish_runtime_statuses(force=True)
        self._notify_listeners()

    def _schedule_replay_timeout(self, replay_id: str) -> None:
        self._cancel_replay_timeout()
        if self._hass is None or self._unloaded:
            return
        hass = self._hass
        self._replay_timeout_handle = hass.loop.call_later(
            _REPLAY_READINESS_TIMEOUT_SECONDS,
            self._async_replay_timeout_due,
            hass,
            replay_id,
        )

    def _async_replay_timeout_due(self, hass: HomeAssistant, replay_id: str) -> None:
        self._replay_timeout_handle = None
        hass.async_create_task(self._async_mark_replay_timeout(hass, replay_id))

    async def _async_mark_replay_timeout(
        self,
        hass: HomeAssistant,
        replay_id: str,
    ) -> None:
        if (
            self._unloaded
            or not self.simulator_enabled
            or self._hass is not hass
            or self._replay_session is None
            or self._replay_session.replay_id != replay_id
            or self._replay_session.state not in {ReplayState.REQUESTING, ReplayState.LOADING}
        ):
            return
        self._replay_session = replace(
            self._replay_session,
            state=ReplayState.FAILED,
            last_remote_reason=_REPLAY_TIMEOUT_REASON,
        )
        await self.async_checkpoint(immediate=True)
        await self._async_publish_runtime_statuses(force=True)
        self._notify_listeners()

    def _cancel_replay_timeout(self) -> None:
        if self._replay_timeout_handle is not None:
            self._replay_timeout_handle.cancel()
            self._replay_timeout_handle = None

    async def _async_handle_victron_write(self, message: mqtt.ReceiveMessage) -> None:
        """Collect only exact W writes for this entry's pending issued command."""
        if (
            self._unloaded
            or not self.simulator_enabled
            or self._mqtt_fault_disconnected
            or inbound_is_retained(message)
            or self.pretend_gx_id is None
        ):
            return
        pending = self._pending_command
        if pending is None:
            return
        now = self.virtual_time_utc
        if now is None:
            return
        if now >= pending.expires_at_utc:
            await self._async_finish_pending_command(
                CommandLifecycleState.EXPIRED,
                "Command expired before all expected Victron writes arrived.",
            )
            return
        expected_values = {
            VictronCommandKey.HUB4_MODE: pending.expected_hub4_mode,
            VictronCommandKey.VE_BUS_MODE: pending.expected_ve_bus_mode,
            VictronCommandKey.AC_POWER_SETPOINT: pending.expected_ac_power_setpoint_w,
        }
        key = next(
            (
                candidate
                for candidate in VictronCommandKey
                if message.topic == command_topic(self.pretend_gx_id, candidate)
            ),
            None,
        )
        if key is None:
            return
        try:
            value = parse_victron_write_payload(message.payload)
        except (TypeError, ValueError):
            await self._async_finish_pending_command(
                CommandLifecycleState.REJECTED,
                "Expected Victron write payload was malformed.",
            )
            return
        if key in self._pending_command_writes or value != expected_values[key]:
            await self._async_finish_pending_command(
                CommandLifecycleState.REJECTED,
                "Victron write did not match issued command metadata.",
            )
            return
        self._pending_command_writes.add(key)
        if len(self._pending_command_writes) != len(VictronCommandKey):
            return
        await self._async_apply_pending_command()

    async def _async_handle_victron_refresh(self, message: mqtt.ReceiveMessage) -> None:
        """Republish only this runtime's current snapshot for a valid keepalive."""
        if (
            self._unloaded
            or not self.simulator_enabled
            or self._mqtt_fault_disconnected
            or self.pretend_gx_id is None
            or inbound_is_retained(message)
            or message.topic != refresh_topic(self.pretend_gx_id)
        ):
            return
        try:
            parse_refresh_payload(message.payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        await self._async_publish_telemetry_snapshot()

    async def _async_handle_command_issued(self, message: mqtt.ReceiveMessage) -> None:
        """Accept one valid non-retained issued command and stage its exact W writes."""
        if (
            self._unloaded
            or not self.simulator_enabled
            or self._mqtt_fault_disconnected
            or inbound_is_retained(message)
            or self.pretend_gx_id is None
            or message.topic != command_issued_topic(self.pretend_gx_id)
        ):
            return
        try:
            issued = parse_issued_command(message.payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        if issued.gx_device_id != self.pretend_gx_id:
            return
        now = self.virtual_time_utc
        if now is None:
            return
        if now >= issued.expires_at_utc:
            await self._async_publish_command_status(
                issued,
                CommandLifecycleState.EXPIRED,
                "Issued command is already expired in virtual time.",
            )
            return
        if now < issued.issued_at_utc or now < issued.effective_at_utc:
            await self._async_publish_command_status(
                issued,
                CommandLifecycleState.REJECTED,
                "Issued command is not yet effective in virtual time.",
            )
            return
        self._accepted_command_ids = prune_command_ledger(
            self._accepted_command_ids, now
        )
        if any(entry.command_id == issued.command_id for entry in self._accepted_command_ids):
            await self._async_publish_command_status(
                issued,
                CommandLifecycleState.REJECTED,
                "Issued command ID is already retained by this sandbox.",
            )
            return
        if self._pending_command is not None:
            await self._async_publish_command_status(
                issued,
                CommandLifecycleState.REJECTED,
                "Another issued command is already pending correlation.",
            )
            return
        if self._reject_command_for_fault():
            await self._async_publish_command_status(
                issued,
                CommandLifecycleState.REJECTED,
                "Sandbox command rejected by local fault injection.",
            )
            await self.async_checkpoint(immediate=True)
            await self._async_publish_runtime_statuses(force=True)
            self._notify_listeners()
            return
        self._accepted_command_ids, accepted = accept_command_id(
            self._accepted_command_ids, issued.command_id, now
        )
        if not accepted:
            return
        self._pending_command = issued
        self._pending_command_writes.clear()
        self._schedule_command_correlation_timeout(issued.command_id)
        await self._async_publish_command_status(
            issued,
            CommandLifecycleState.RECEIVED,
            "Issued command accepted; awaiting matching Victron writes.",
        )
        await self.async_checkpoint(immediate=True)
        await self._async_publish_runtime_statuses(force=True)
        self._notify_listeners()

    async def _async_apply_pending_command(self) -> None:
        """Apply a fully correlated command atomically after its three W writes."""
        pending = self._pending_command
        if pending is None:
            return
        fallback = (
            pending.expected_hub4_mode == 2
            and pending.expected_ve_bus_mode == 3
            and pending.expected_ac_power_setpoint_w == 0
        )
        self._command = Command(
            OperatingMode.SELF_CONSUMPTION if fallback else OperatingMode.GRID_SETPOINT,
            None if fallback else pending.expected_ac_power_setpoint_w,
            issued_at_utc=pending.effective_at_utc,
            expires_at_utc=pending.expires_at_utc,
        )
        self.last_command_status = CommandStatus.APPLIED
        self.last_command_reason = None
        await self._async_publish_command_status(
            pending,
            CommandLifecycleState.APPLIED,
            "All expected Victron writes were correlated and applied.",
        )
        self._clear_pending_command()
        await self._async_publish_telemetry_snapshot()
        await self.async_checkpoint(immediate=True)
        await self._async_publish_runtime_statuses(force=True)
        self._notify_listeners()

    async def _async_finish_pending_command(
        self,
        state: CommandLifecycleState,
        reason: str,
    ) -> None:
        """Safely terminate one pending command without retaining partial W state."""
        pending = self._pending_command
        if pending is None:
            return
        self._command = Command(OperatingMode.SELF_CONSUMPTION)
        self.last_command_status = (
            CommandStatus.FALLBACK_EXPIRED
            if state is CommandLifecycleState.EXPIRED
            else CommandStatus.FALLBACK_INVALID
        )
        self.last_command_reason = reason
        await self._async_publish_command_status(pending, state, reason)
        self._clear_pending_command()
        await self._async_publish_telemetry_snapshot()
        await self.async_checkpoint(immediate=True)
        await self._async_publish_runtime_statuses(force=True)
        self._notify_listeners()

    async def _async_publish_command_status(
        self,
        command: IssuedCommand,
        state: CommandLifecycleState,
        reason: str,
    ) -> None:
        """Publish one exact non-retained schema-4 status through the fault bridge."""
        if self.pretend_gx_id is None or self.virtual_time_utc is None or self._state is None or self._config is None:
            return
        payload = command_status_payload(
            command,
            state,
            self.virtual_time_utc,
            reason,
            soc_percent=self._state.soc_ratio(self._config.capacity_wh) * 100,
            battery_power_w=self._last_battery_power_w,
            grid_power_w=self._last_grid_power_w,
            operating_state=self._operating_state(),
        )
        await self._async_publish_outbound(
            command_status_topic(self.pretend_gx_id), payload
        )

    def _schedule_command_correlation_timeout(self, command_id: str) -> None:
        self._cancel_command_correlation_timeout()
        if self._hass is None or self._unloaded:
            return
        self._command_correlation_timeout_handle = self._hass.loop.call_later(
            COMMAND_CORRELATION_TIMEOUT_SECONDS,
            self._command_correlation_timeout_due,
            command_id,
        )

    def _command_correlation_timeout_due(self, command_id: str) -> None:
        self._command_correlation_timeout_handle = None
        if self._hass is not None:
            self._hass.async_create_task(
                self._async_command_correlation_timeout(command_id)
            )

    async def _async_command_correlation_timeout(self, command_id: str) -> None:
        if (
            self._unloaded
            or not self.simulator_enabled
            or self._pending_command is None
            or self._pending_command.command_id != command_id
        ):
            return
        await self._async_finish_pending_command(
            CommandLifecycleState.FAILED,
            "Timed out waiting for all expected Victron writes.",
        )

    def _cancel_command_correlation_timeout(self) -> None:
        if self._command_correlation_timeout_handle is not None:
            self._command_correlation_timeout_handle.cancel()
            self._command_correlation_timeout_handle = None

    def _clear_pending_command(self) -> None:
        self._cancel_command_correlation_timeout()
        self._pending_command = None
        self._pending_command_writes.clear()

    async def _async_publish_telemetry_snapshot(self) -> None:
        """Publish one complete current synthetic N snapshot without advancing physics."""
        if self.pretend_gx_id is None or self._state is None or self._config is None:
            return
        if self._active_fault(FaultKind.STALE_TELEMETRY) is not None:
            return
        values = {
            VictronTelemetryKey.STATE_OF_CHARGE: self._state.soc_ratio(
                self._config.capacity_wh
            ) * 100,
            VictronTelemetryKey.INSTALLED_CAPACITY: (
                self._config.capacity_wh / self._config.nominal_voltage_v
            ),
            VictronTelemetryKey.BATTERY_POWER: self._last_battery_power_w,
            VictronTelemetryKey.GRID_POWER: self._last_grid_power_w,
            VictronTelemetryKey.LOAD_POWER: self.load_w,
            VictronTelemetryKey.SOLAR_POWER: self.solar_w,
            VictronTelemetryKey.VOLTAGE: self._config.nominal_voltage_v,
            VictronTelemetryKey.OPERATING_STATE: self._operating_state().value,
        }
        for key, value in values.items():
            await self._async_publish_outbound(
                telemetry_topic(self.pretend_gx_id, key),
                telemetry_payload(key, value),
                telemetry=True,
            )

    async def _async_publish_runtime_statuses(self, *, force: bool = False) -> None:
        """Publish exact schema-2 HA statuses without recursive fault transitions."""
        if self._unloaded or not self.simulator_enabled or self.pretend_gx_id is None:
            return
        simulator_status = self._build_simulator_status()
        faults_status = self._build_faults_status(simulator_status.timestamp_utc)
        await self._async_publish_one_runtime_status(
            topic=simulator_status_topic(self.pretend_gx_id),
            status=simulator_status,
            previous="simulator",
            force=force,
        )
        await self._async_publish_one_runtime_status(
            topic=faults_status_topic(self.pretend_gx_id),
            status=faults_status,
            previous="faults",
            force=force,
        )

    def _build_simulator_status(self) -> SimulatorStatus:
        """Map only entry-owned synthetic state to the frozen simulator schema."""
        timestamp = (
            self._clock.state.virtual_time_utc
            if self._clock is not None
            else datetime.now(timezone.utc)
        )
        unavailable = self._config is None or self._state is None or self._clock is None
        if unavailable:
            state = SimulatorStatusState.UNAVAILABLE
            reason = "Sandbox runtime is unavailable."
        elif not self.simulator_enabled:
            state = SimulatorStatusState.DISABLED
            reason = None
        elif self.last_health is SimulationHealth.UNHEALTHY:
            state = SimulatorStatusState.UNHEALTHY
            reason = "Synthetic energy balance is unhealthy."
        elif self._mqtt_fault_disconnected:
            state = SimulatorStatusState.UNHEALTHY
            reason = "Sandbox MQTT bridge is faulted."
        elif self._clock.state.rate == ClockRate.PAUSED.value or self._playback_state == "paused":
            state = SimulatorStatusState.PAUSED
            reason = None
        else:
            state = SimulatorStatusState.RUNNING
            reason = None
        ready = not unavailable and state is not SimulatorStatusState.DISABLED
        return build_simulator_status(
            schemaVersion=2,
            gxDeviceId=self.pretend_gx_id,
            timestampUtc=timestamp.isoformat().replace("+00:00", "Z"),
            state=state.value,
            reason=reason,
            virtualTimeUtc=(timestamp.isoformat().replace("+00:00", "Z") if ready else None),
            playbackState=(self._playback_status_state().value if ready else None),
            operatingState=(self._operating_state().value if ready else None),
            socPercent=(self._state.soc_ratio(self._config.capacity_wh) * 100 if ready else None),
            batteryEnergyWh=(self._state.energy_wh if ready else None),
            batteryPowerW=(self._last_battery_power_w if ready else None),
            gridPowerW=(self._last_grid_power_w if ready else None),
            energyBalanceHealthy=(self.last_health is SimulationHealth.HEALTHY if ready else None),
            energyBalanceErrorWh=(self._cumulative_ledger.balance_error_wh if ready else None),
            mqttState=(self._mqtt_status_state().value if ready else None),
            replayState=(self._replay_status_state().value if ready else None),
            commandState=(self._command_status_state().value if ready else None),
        )

    def _build_faults_status(self, timestamp: datetime) -> FaultsStatus:
        """Map only bounded lifecycle counters into the frozen faults schema."""
        reportable = tuple(
            fault for fault in self._faults if fault.state in {FaultState.PENDING, FaultState.ACTIVE}
        )
        faults = tuple(_fault_status_item(fault) for fault in reportable)
        return build_faults_status(
            schemaVersion=2,
            gxDeviceId=self.pretend_gx_id,
            timestampUtc=timestamp.isoformat().replace("+00:00", "Z"),
            state=(FaultEnvelopeState.ACTIVE.value if faults else FaultEnvelopeState.CLEAR.value),
            reason=None,
            faults=tuple(item.to_payload() for item in faults),
        )

    def _playback_status_state(self) -> PlaybackStatusState:
        if self._replay_session is not None and self._replay_session.state is ReplayState.FAILED:
            return PlaybackStatusState.FAILED
        return {
            "paused": PlaybackStatusState.PAUSED,
            "running": PlaybackStatusState.RUNNING,
            "completed": PlaybackStatusState.COMPLETED,
        }.get(self._playback_state, PlaybackStatusState.NONE)

    def _mqtt_status_state(self) -> MqttStatusState:
        if self._mqtt_fault_disconnected:
            return MqttStatusState.FAULTED
        return MqttStatusState.CONNECTED if self._hass is not None else MqttStatusState.DISCONNECTED

    def _replay_status_state(self) -> ReplayStatusState:
        if self._replay_session is None:
            return ReplayStatusState.NONE
        return {
            ReplayState.REQUESTING: ReplayStatusState.PENDING,
            ReplayState.LOADING: ReplayStatusState.PENDING,
            ReplayState.STOPPED: ReplayStatusState.PENDING,
            ReplayState.READY: ReplayStatusState.READY,
            ReplayState.RUNNING: ReplayStatusState.RUNNING,
            ReplayState.PAUSED: ReplayStatusState.RUNNING,
            ReplayState.COMPLETED: ReplayStatusState.COMPLETED,
            ReplayState.FAILED: ReplayStatusState.FAILED,
            ReplayState.REJECTED: ReplayStatusState.REJECTED,
        }.get(self._replay_session.state, ReplayStatusState.NONE)

    def _command_status_state(self) -> CommandStatusState:
        if self._pending_command is not None:
            return CommandStatusState.RECEIVED
        if self.last_command_status is CommandStatus.APPLIED:
            return CommandStatusState.APPLIED
        if self.last_command_status is CommandStatus.NO_ACTION:
            return CommandStatusState.NONE
        if self.last_command_status is CommandStatus.AWAITING_FORECAST:
            return CommandStatusState.NONE
        if self.last_command_status is CommandStatus.FALLBACK_EXPIRED:
            return CommandStatusState.EXPIRED
        if self.last_command_status is CommandStatus.FALLBACK_INVALID:
            return CommandStatusState.REJECTED
        if self.last_command_status is CommandStatus.FALLBACK_STALE:
            return CommandStatusState.FAILED
        return CommandStatusState.NONE

    async def _async_publish_one_runtime_status(
        self,
        *,
        topic: str,
        status: SimulatorStatus | FaultsStatus,
        previous: str,
        force: bool,
    ) -> None:
        """Coalesce unchanged status summaries before using the common outbound path."""
        signature = status.semantic_key
        previous_signature = (
            self._last_simulator_status_signature
            if previous == "simulator"
            else self._last_fault_status_signature
        )
        if not force and signature == previous_signature:
            return
        if previous == "simulator":
            self._last_simulator_status_signature = signature
        else:
            self._last_fault_status_signature = signature
        try:
            await self._async_publish_outbound(
                topic,
                json.dumps(status.to_payload(), separators=(",", ":")),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    def _operating_state(self) -> VictronOperatingState:
        """Map only local synthetic command state to the frozen numeric enum."""
        if self._command is None or self._command.mode is OperatingMode.SELF_CONSUMPTION:
            return VictronOperatingState.SELF_CONSUMPTION
        if self._command.mode is OperatingMode.GRID_SETPOINT:
            return VictronOperatingState.GRID_SETPOINT
        return VictronOperatingState.IDLE

    def _notify_listeners(self) -> None:
        if self._unloaded:
            return
        for listener in tuple(self._listeners):
            listener()

    def _schedule_checkpoint(self) -> None:
        if (
            self._storage is None
            or self._hass is None
            or self._unloaded
            or self._checkpoint_handle is not None
        ):
            return
        self._checkpoint_handle = self._hass.loop.call_later(
            30,
            self._async_checkpoint_due,
        )

    def _async_checkpoint_due(self) -> None:
        self._checkpoint_handle = None
        if self._hass is not None and not self._unloaded:
            self._hass.async_create_task(self.async_checkpoint(immediate=True))

    def _cancel_pending_checkpoint(self) -> None:
        if self._checkpoint_handle is not None:
            self._checkpoint_handle.cancel()
            self._checkpoint_handle = None

    def _schedule_immediate_checkpoint(self) -> None:
        if self._storage is not None and self._hass is not None and not self._unloaded:
            self._hass.async_create_task(self.async_checkpoint(immediate=True))


def _snapshot_name(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Snapshot name is invalid")
    normalized = value.strip()
    if _SNAPSHOT_NAME_PATTERN.fullmatch(normalized) is None:
        raise ValueError("Snapshot name is invalid")
    return normalized


def _fault_status_item(fault: Fault) -> FaultStatusItem:
    """Map one local fault without leaking settings or queued MQTT data."""
    lifecycle = {
        FaultState.PENDING: FaultLifecycleStatusState.CONFIGURED,
        FaultState.ACTIVE: FaultLifecycleStatusState.ACTIVE,
        FaultState.EXHAUSTED: FaultLifecycleStatusState.EXHAUSTED,
        FaultState.CLEARED: FaultLifecycleStatusState.CLEARED,
    }[fault.state]
    remaining_seconds = (
        None
        if fault.remaining_duration_seconds is None
        else math.ceil(fault.remaining_duration_seconds)
    )
    return FaultStatusItem(
        kind=FaultStatusKind(fault.kind.value),
        state=lifecycle,
        remaining_count=fault.remaining_count,
        remaining_seconds=remaining_seconds,
    )


def _registration_toggle(
    config: Mapping[str, object],
    pascal_name: str,
    camel_name: str,
) -> bool:
    """Read one registration-owned boolean, defaulting only when absent."""
    value = config.get(pascal_name, config.get(camel_name, False))
    if not isinstance(value, bool):
        raise ValueError(f"{pascal_name} must be boolean")
    return value


_CONTROL_CONFIG_FIELDS = (
    "capacity_wh",
    "reserve_wh",
    "max_charge_power_w",
    "max_discharge_power_w",
    "charge_efficiency",
    "discharge_efficiency",
)


def _control_config_to_storage(config: BatteryConfig | None) -> dict[str, float]:
    """Serialize only editable sandbox controls, never registration data."""
    if config is None:
        raise ValueError("Sandbox configuration is unavailable")
    return {field_name: getattr(config, field_name) for field_name in _CONTROL_CONFIG_FIELDS}


def _control_config_from_storage(
    value: object,
    *,
    fallback: BatteryConfig,
) -> BatteryConfig:
    """Validate persisted manual control values against simulation invariants."""
    if not isinstance(value, Mapping) or set(value) != set(_CONTROL_CONFIG_FIELDS):
        raise ValueError("Stored sandbox controls are invalid")
    values: dict[str, float] = {}
    for field_name in _CONTROL_CONFIG_FIELDS:
        candidate = value[field_name]
        if isinstance(candidate, bool):
            raise ValueError("Stored sandbox controls are invalid")
        try:
            parsed = float(candidate)
        except (TypeError, ValueError) as err:
            raise ValueError("Stored sandbox controls are invalid") from err
        if not math.isfinite(parsed):
            raise ValueError("Stored sandbox controls are invalid")
        values[field_name] = parsed
    if (
        not 0 < values["capacity_wh"] <= _MAX_ENERGY_WH
        or not 0 <= values["reserve_wh"] <= values["capacity_wh"]
        or values["reserve_wh"] > _MAX_ENERGY_WH
        or not 0 <= values["max_charge_power_w"] <= _MAX_POWER_W
        or not 0 <= values["max_discharge_power_w"] <= _MAX_POWER_W
        or not 0 < values["charge_efficiency"] <= 1
        or not 0 < values["discharge_efficiency"] <= 1
    ):
        raise ValueError("Stored sandbox controls are invalid")
    return replace(fallback, **values)

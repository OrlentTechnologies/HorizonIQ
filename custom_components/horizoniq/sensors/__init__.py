from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..const import DEFAULT_ENVIRONMENT, DOMAIN
from ..entity_helpers import normalized_environment
from ..sandbox_runtime import HorizonIQEntryRuntime
from ..const import DOMAIN
from ..entity_helpers import build_unique_id
from .cadence import ForecastCadenceSensor
from .monetary import MonetarySensor
from .diagnostic import ForecastDetailSensor
from .bms_state import BatteryManagementSystemStateSensor
from .trial import TrialStatusSensor


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HorizonIQ sensor entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id].coordinator
    environment = normalized_environment(
        getattr(coordinator, "environment", DEFAULT_ENVIRONMENT)
    )

    async_add_entities(
        [
            MonetarySensor(
                coordinator,
                config_entry.entry_id,
                environment,
                name_suffix="Total Cost",
                unique_suffix="total_cost",
                value_field="total_cost",
            ),
            MonetarySensor(
                coordinator,
                config_entry.entry_id,
                environment,
                name_suffix="Charging Cost",
                unique_suffix="charging_cost",
                value_field="charging_cost",
            ),
            MonetarySensor(
                coordinator,
                config_entry.entry_id,
                environment,
                name_suffix="Saving",
                unique_suffix="saving",
                value_field="saving",
            ),
            ForecastDetailSensor(
                coordinator,
                config_entry.entry_id,
                environment,
            ),
            ForecastCadenceSensor(
                coordinator,
                config_entry.entry_id,
                environment,
            ),
            BatteryManagementSystemStateSensor(
                coordinator,
                config_entry.entry_id,
                environment,
            ),
            TrialStatusSensor(
                coordinator,
                config_entry.entry_id,
                environment,
            ),
        ]
        + _sandbox_entities(hass.data[DOMAIN][config_entry.entry_id], config_entry.entry_id)
    )


def _sandbox_entities(
    runtime: HorizonIQEntryRuntime,
    entry_id: str,
) -> list[SensorEntity]:
    """Return operational virtual-device entities for a configured sandbox."""
    if not runtime.is_sandbox_configured:
        return []
    return [
        SandboxRuntimeSensor(runtime, entry_id, "status", "Status"),
        SandboxRuntimeSensor(runtime, entry_id, "soc", "State of charge", PERCENTAGE),
        SandboxRuntimeSensor(runtime, entry_id, "energy", "Energy"),
        SandboxRuntimeSensor(runtime, entry_id, "battery_power", "Battery power", UnitOfPower.WATT),
        SandboxRuntimeSensor(runtime, entry_id, "grid_power", "Grid power", UnitOfPower.WATT),
        SandboxRuntimeSensor(runtime, entry_id, "clock", "Virtual time"),
        SandboxRuntimeSensor(runtime, entry_id, "mqtt", "MQTT health"),
        SandboxRuntimeSensor(runtime, entry_id, "forecast", "Forecast health"),
        SandboxRuntimeSensor(runtime, entry_id, "command", "Command status"),
        SandboxRuntimeSensor(runtime, entry_id, "decision", "Decision summary"),
        SandboxRuntimeSensor(runtime, entry_id, "health", "Energy-balance health"),
        SandboxRuntimeSensor(runtime, entry_id, "balance_error", "Energy-balance error", UnitOfEnergy.WATT_HOUR),
        SandboxRuntimeSensor(runtime, entry_id, "profile_cursor", "Profile cursor"),
        SandboxRuntimeSensor(runtime, entry_id, "faults", "Active faults"),
    ]


class SandboxRuntimeSensor(SensorEntity):
    """Expose one entry-local virtual-device status value."""

    _attr_has_entity_name = True

    def __init__(
        self,
        runtime: HorizonIQEntryRuntime,
        entry_id: str,
        key: str,
        name: str,
        unit: str | None = None,
    ) -> None:
        """Initialize a sandbox state sensor."""
        self._runtime = runtime
        self._key = key
        self._attr_name = name
        self._attr_unique_id = build_unique_id("Sandbox", entry_id, key)
        self._attr_native_unit_of_measurement = unit
        self._remove_listener = runtime.add_listener(self.async_write_ha_state)

    @property
    def device_info(self) -> DeviceInfo:
        """Associate the sensor with its one entry-local virtual battery."""
        assert self._runtime.pretend_gx_id is not None
        return DeviceInfo(
            identifiers={(DOMAIN, self._runtime.pretend_gx_id)},
            name="HorizonIQ Virtual Battery",
            manufacturer="HorizonIQ",
            model="Sandbox virtual battery",
        )

    @property
    def available(self) -> bool:
        """Keep status visible while operational readings follow lifecycle state."""
        return self._key == "status" or self._runtime.simulator_enabled

    @property
    def native_value(self) -> str | float | None:
        """Return the requested entry-local status value."""
        if self._key == "status":
            return "active" if self._runtime.simulator_enabled else "inactive"
        if self._key == "energy":
            return self._runtime.energy_wh
        if self._key == "soc":
            return self._runtime.soc_percent
        if self._key == "battery_power":
            return self._runtime.battery_power_w
        if self._key == "grid_power":
            return self._runtime.grid_power_w
        if self._key == "clock":
            virtual_time = self._runtime.virtual_time_utc
            return virtual_time.isoformat() if virtual_time is not None else None
        if self._key == "command":
            return self._runtime.last_command_status.value
        if self._key == "mqtt":
            return self._runtime.mqtt_health
        if self._key == "forecast":
            return self._runtime.forecast_health
        if self._key == "decision":
            return self._runtime.decision_summary
        if self._key == "health":
            return self._runtime.last_health.value
        if self._key == "balance_error":
            return self._runtime.energy_ledger.balance_error_wh
        if self._key == "profile_cursor":
            cursor = self._runtime.profile_cursor
            return cursor.index if cursor is not None else 0
        if self._key == "faults":
            return len(self._runtime.active_fault_diagnostics)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose safe lifecycle context without credentials or forecast payloads."""
        return {
            "gx_id": self._runtime.pretend_gx_id,
            "clock_rate": self._runtime.clock_rate,
            "capacity_wh": self._runtime.capacity_wh,
            "reserve_wh": self._runtime.reserve_wh,
            "command_reason": self._runtime.last_command_reason,
            "storage_diagnostic": self._runtime.storage_diagnostic,
            "profile": self._runtime.selected_profile_filename,
            "profile_cursor": (
                self._runtime.profile_cursor.index
                if self._runtime.profile_cursor is not None
                else None
            ),
            "active_faults": self._runtime.active_fault_diagnostics,
            "ledger": {
                "grid_import_wh": self._runtime.energy_ledger.grid_import_wh,
                "grid_export_wh": self._runtime.energy_ledger.grid_export_wh,
                "solar_generation_wh": self._runtime.energy_ledger.solar_generation_wh,
                "load_consumption_wh": self._runtime.energy_ledger.load_consumption_wh,
                "modeled_losses_wh": (
                    self._runtime.energy_ledger.charge_conversion_loss_wh
                    + self._runtime.energy_ledger.discharge_conversion_loss_wh
                ),
            },
        }

    async def async_will_remove_from_hass(self) -> None:
        """Remove the entry-local runtime callback."""
        self._remove_listener()
        await super().async_will_remove_from_hass()

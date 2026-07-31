"""Manual virtual-battery controls for configured HorizonIQ sandboxes."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity_helpers import build_unique_id, virtual_battery_device_info
from .sandbox_runtime import (
    MAX_ABSOLUTE_POWER_W,
    MAX_BATTERY_ENERGY_WH,
    HorizonIQEntryRuntime,
)


@dataclass(frozen=True, slots=True)
class _ControlDescription:
    key: str
    name: str
    minimum: float
    maximum: float
    step: float
    unit: str | None = None
    percentage: bool = False
    mode: NumberMode = NumberMode.BOX


_CONTROLS = (
    _ControlDescription("load_w", "Load", 0, MAX_ABSOLUTE_POWER_W, 10, UnitOfPower.WATT),
    _ControlDescription("solar_w", "Solar generation", 0, MAX_ABSOLUTE_POWER_W, 10, UnitOfPower.WATT),
    _ControlDescription("capacity_wh", "Battery capacity", 1, MAX_BATTERY_ENERGY_WH, 10, UnitOfEnergy.WATT_HOUR),
    _ControlDescription("reserve_wh", "Battery reserve", 0, MAX_BATTERY_ENERGY_WH, 10, UnitOfEnergy.WATT_HOUR),
    _ControlDescription("max_charge_power_w", "Charge limit", 0, MAX_ABSOLUTE_POWER_W, 10, UnitOfPower.WATT),
    _ControlDescription("max_discharge_power_w", "Discharge limit", 0, MAX_ABSOLUTE_POWER_W, 10, UnitOfPower.WATT),
    _ControlDescription("charge_efficiency", "Charge efficiency", 1, 100, 1, PERCENTAGE, True),
    _ControlDescription("discharge_efficiency", "Discharge efficiency", 1, 100, 1, PERCENTAGE, True),
    _ControlDescription(
        "set_state_of_charge",
        "State of charge",
        0,
        100,
        0.1,
        PERCENTAGE,
        True,
        NumberMode.BOX,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up writable controls for one virtual battery."""
    runtime: HorizonIQEntryRuntime = hass.data[DOMAIN][config_entry.entry_id]
    if runtime.is_sandbox_configured:
        async_add_entities(
            [SandboxNumber(runtime, config_entry.entry_id, description) for description in _CONTROLS]
        )


class SandboxNumber(NumberEntity):
    """One active-only, entry-scoped simulation control."""

    _attr_has_entity_name = True

    def __init__(
        self,
        runtime: HorizonIQEntryRuntime,
        entry_id: str,
        description: _ControlDescription,
    ) -> None:
        """Initialize this manual control."""
        self._runtime = runtime
        self._description = description
        self._attr_name = description.name
        self._attr_unique_id = build_unique_id("Sandbox", entry_id, description.key)
        self._attr_native_min_value = description.minimum
        self._attr_native_max_value = description.maximum
        self._attr_native_step = description.step
        self._attr_native_unit_of_measurement = description.unit
        self._attr_mode = description.mode
        self._remove_listener = runtime.add_listener(self.async_write_ha_state)

    @property
    def device_info(self) -> DeviceInfo:
        """Associate controls with their generated virtual device."""
        assert self._runtime.pretend_gx_id is not None
        return virtual_battery_device_info(self._runtime.pretend_gx_id)

    @property
    def available(self) -> bool:
        """Manual operating controls cannot alter an inactive sandbox."""
        if self._description.key == "set_state_of_charge":
            return self._runtime.can_set_state_of_charge
        return self._runtime.simulator_enabled

    @property
    def native_value(self) -> float | None:
        """Return the current value in HA's display unit."""
        key = self._description.key
        if key == "set_state_of_charge":
            soc_percent = self._runtime.soc_percent
            return round(soc_percent, 1) if soc_percent is not None else None
        if key == "load_w":
            return round(self._runtime.load_w, 1)
        if key == "solar_w":
            return round(self._runtime.solar_w, 1)
        value = getattr(self._runtime, key)
        if value is None:
            return None
        displayed_value = value * 100 if self._description.percentage else value
        return round(displayed_value, 1)

    @property
    def native_min_value(self) -> float:
        """Follow the current reserve for the state-of-charge setter."""
        if self._description.key == "set_state_of_charge":
            return self._runtime.reserve_percent or 0
        return self._description.minimum

    @property
    def native_max_value(self) -> float:
        """Expose the fixed upper state-of-charge limit."""
        return self._description.maximum

    async def async_set_native_value(self, value: float) -> None:
        """Apply one bounded value to this entry only."""
        key = self._description.key
        if key == "set_state_of_charge":
            await self._runtime.async_set_state_of_charge(value)
            return
        if key in {"load_w", "solar_w"}:
            await self._runtime.async_set_inputs(
                load_w=value if key == "load_w" else self._runtime.load_w,
                solar_w=value if key == "solar_w" else self._runtime.solar_w,
            )
            return
        await self._runtime.async_set_control_value(
            key,
            value / 100 if self._description.percentage else value,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Detach the runtime listener."""
        self._remove_listener()
        await super().async_will_remove_from_hass()

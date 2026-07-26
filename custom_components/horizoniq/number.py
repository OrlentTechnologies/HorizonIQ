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
from .entity_helpers import build_unique_id
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


_CONTROLS = (
    _ControlDescription("load_w", "Load", 0, MAX_ABSOLUTE_POWER_W, 10, UnitOfPower.WATT),
    _ControlDescription("solar_w", "Solar generation", 0, MAX_ABSOLUTE_POWER_W, 10, UnitOfPower.WATT),
    _ControlDescription("capacity_wh", "Battery capacity", 1, MAX_BATTERY_ENERGY_WH, 10, UnitOfEnergy.WATT_HOUR),
    _ControlDescription("reserve_wh", "Battery reserve", 0, MAX_BATTERY_ENERGY_WH, 10, UnitOfEnergy.WATT_HOUR),
    _ControlDescription("max_charge_power_w", "Charge power limit", 0, MAX_ABSOLUTE_POWER_W, 10, UnitOfPower.WATT),
    _ControlDescription("max_discharge_power_w", "Discharge power limit", 0, MAX_ABSOLUTE_POWER_W, 10, UnitOfPower.WATT),
    _ControlDescription("charge_efficiency", "Charge efficiency", 1, 100, 1, PERCENTAGE, True),
    _ControlDescription("discharge_efficiency", "Discharge efficiency", 1, 100, 1, PERCENTAGE, True),
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
    _attr_mode = NumberMode.BOX

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
        self._remove_listener = runtime.add_listener(self.async_write_ha_state)

    @property
    def device_info(self) -> DeviceInfo:
        """Associate controls with their generated virtual device."""
        assert self._runtime.pretend_gx_id is not None
        return DeviceInfo(
            identifiers={(DOMAIN, self._runtime.pretend_gx_id)},
            name="HorizonIQ Virtual Battery",
            manufacturer="HorizonIQ",
            model="Sandbox virtual battery",
        )

    @property
    def available(self) -> bool:
        """Manual operating controls cannot alter an inactive sandbox."""
        return self._runtime.simulator_enabled

    @property
    def native_value(self) -> float | None:
        """Return the current value in HA's display unit."""
        key = self._description.key
        if key == "load_w":
            return self._runtime.load_w
        if key == "solar_w":
            return self._runtime.solar_w
        value = getattr(self._runtime, key)
        if value is None:
            return None
        return value * 100 if self._description.percentage else value

    async def async_set_native_value(self, value: float) -> None:
        """Apply one bounded value to this entry only."""
        key = self._description.key
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

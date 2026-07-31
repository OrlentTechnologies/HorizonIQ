"""Virtual-clock controls for configured sandbox entries."""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity_helpers import build_unique_id
from .entity_helpers import virtual_battery_device_info
from .sandbox_runtime import HorizonIQEntryRuntime
from .simulation.clock import ClockRate
from .simulation.faults import FaultKind
from .simulation.profiles import standard_scenarios


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the entry-local virtual-clock rate control."""
    runtime: HorizonIQEntryRuntime = hass.data[DOMAIN][config_entry.entry_id]
    if runtime.is_sandbox_configured:
        async_add_entities(
            [
                SandboxClockRateSelect(runtime, config_entry.entry_id),
                SandboxProfileSelect(runtime, config_entry.entry_id),
                SandboxScenarioSelect(runtime, config_entry.entry_id),
                SandboxEquipmentProfileSelect(runtime, config_entry.entry_id),
                SandboxFaultKindSelect(runtime, config_entry.entry_id),
            ]
        )


class _SandboxSelect(SelectEntity):
    """Shared lifecycle support for entry-local sandbox selections."""

    _attr_has_entity_name = True

    def __init__(self, runtime: HorizonIQEntryRuntime, entry_id: str, suffix: str) -> None:
        self._runtime = runtime
        self._attr_unique_id = build_unique_id("Sandbox", entry_id, suffix)
        self._remove_listener = runtime.add_listener(self.async_write_ha_state)

    @property
    def available(self) -> bool:
        """Selections only control an active virtual device."""
        return self._runtime.simulator_enabled

    @property
    def device_info(self) -> DeviceInfo:
        """Associate each sandbox selection with its entry-owned virtual battery."""
        assert self._runtime.pretend_gx_id is not None
        return virtual_battery_device_info(self._runtime.pretend_gx_id)

    async def async_will_remove_from_hass(self) -> None:
        self._remove_listener()
        await super().async_will_remove_from_hass()


class SandboxClockRateSelect(_SandboxSelect):
    """Select the rate of one sandbox's isolated virtual clock."""

    _attr_has_entity_name = True
    _attr_name = "Simulation clock rate"
    _attr_options = [rate.value for rate in ClockRate]

    def __init__(self, runtime: HorizonIQEntryRuntime, entry_id: str) -> None:
        """Initialize the entry-local virtual-clock control."""
        super().__init__(runtime, entry_id, "clock_rate")

    @property
    def current_option(self) -> str | None:
        """Return this sandbox's selected virtual-clock rate."""
        return self._runtime.clock_rate

    async def async_select_option(self, option: str) -> None:
        """Change only this sandbox's virtual-clock rate."""
        self._runtime.set_clock_rate(ClockRate(option))



class SandboxProfileSelect(_SandboxSelect):
    """Choose one validated profile stored in this entry's owned directory."""

    _attr_name = "Replay profile"
    _not_selected = "Not selected"
    _attr_options: list[str] = [_not_selected]

    def __init__(self, runtime: HorizonIQEntryRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id, "profile")
        self._attr_options = [self._not_selected]

    @property
    def current_option(self) -> str | None:
        return self._runtime.selected_profile_filename or self._not_selected

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._attr_options = [
            self._not_selected,
            *await self._runtime.async_list_profile_filenames(),
        ]
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        if option == self._not_selected:
            return
        await self._runtime.async_select_profile(option)


class SandboxScenarioSelect(_SandboxSelect):
    """Apply one built-in deterministic scenario to this sandbox."""

    _attr_name = "Scenario"
    _attr_options = [
        item.identifier for item in standard_scenarios(datetime.now(timezone.utc))
    ]

    def __init__(self, runtime: HorizonIQEntryRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id, "scenario")
        self._selected = "idle"

    @property
    def current_option(self) -> str:
        return self._selected

    async def async_select_option(self, option: str) -> None:
        await self._runtime.async_select_scenario(option)
        self._selected = option


class SandboxEquipmentProfileSelect(_SandboxSelect):
    """Expose the immutable registration-owned equipment profile selection."""

    _attr_name = "Equipment profile"
    _attr_options = ["Registration profile"]

    def __init__(self, runtime: HorizonIQEntryRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id, "equipment_profile")

    @property
    def current_option(self) -> str:
        return self._runtime.equipment_profile_name

    @property
    def available(self) -> bool:
        """The registration-owned equipment profile is informational only."""
        return False

    async def async_select_option(self, option: str) -> None:
        if option != self._runtime.equipment_profile_name:
            raise ValueError("Only the registration-owned equipment profile is available")


def _friendly_option(value: str) -> str:
    """Return a readable label for a machine-readable select option."""
    return value.replace("_", " ").replace("-", " ").title()


class SandboxFaultKindSelect(_SandboxSelect):
    """Select the supported local fault to inject with the fault button."""

    _attr_name = "Fault injection kind"
    _attr_options = [_friendly_option(kind.value) for kind in FaultKind]

    def __init__(self, runtime: HorizonIQEntryRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id, "fault_kind")

    @property
    def current_option(self) -> str:
        return _friendly_option(self._runtime.selected_fault_kind)

    async def async_select_option(self, option: str) -> None:
        selected_kind = next(
            (kind.value for kind in FaultKind if _friendly_option(kind.value) == option),
            None,
        )
        if selected_kind is None:
            raise ValueError("Fault injection kind is invalid")
        self._runtime.set_selected_fault_kind(selected_kind)

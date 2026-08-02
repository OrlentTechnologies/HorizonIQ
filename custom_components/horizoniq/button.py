from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_ENVIRONMENT, DOMAIN
from .entity import HorizonIQEntity
from .entity_helpers import (
    build_unique_id,
    entity_name,
    environment_label,
    normalized_environment,
    virtual_battery_device_info,
)
from .sandbox_runtime import HorizonIQEntryRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the clear-registration button."""
    runtime: HorizonIQEntryRuntime = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = runtime.coordinator
    environment = normalized_environment(
        getattr(coordinator, "environment", DEFAULT_ENVIRONMENT)
    )

    entities: list[ButtonEntity] = [
        ClearRegistrationButton(coordinator, config_entry.entry_id, environment)
    ]
    if runtime.is_sandbox_configured:
        entities.extend(
            [
                SandboxStepButton(runtime, config_entry.entry_id),
                SandboxResetButton(runtime, config_entry.entry_id),
                SandboxResetProfileButton(runtime, config_entry.entry_id),
                SandboxSaveSnapshotButton(runtime, config_entry.entry_id),
                SandboxInjectFaultButton(runtime, config_entry.entry_id),
                SandboxClearFaultsButton(runtime, config_entry.entry_id),
            ]
        )
    async_add_entities(entities)


class ClearRegistrationButton(HorizonIQEntity, ButtonEntity):
    """Button entity to clear cached registration data."""

    def __init__(self, coordinator, entry_id: str, environment: str) -> None:
        super().__init__(coordinator)
        self._environment = normalized_environment(environment)
        self._attr_name = entity_name(self._environment, "Clear Registration")
        self._attr_unique_id = build_unique_id(
            self._environment, entry_id, "clear_registration"
        )

    async def async_press(self) -> None:
        """Handle button presses."""
        await self.coordinator.async_clear_registration_data()

    @property
    def available(self) -> bool:
        """Keep this button callable even when coordinator updates are failing."""
        return True

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return diagnostic attributes for the button."""
        return {"environment": environment_label(self._environment)}


class _SandboxButton(ButtonEntity):
    """Common state and lifecycle support for a virtual-device button."""

    _attr_has_entity_name = True

    def __init__(self, runtime: HorizonIQEntryRuntime, entry_id: str, suffix: str) -> None:
        """Initialize an entry-local sandbox control."""
        self._runtime = runtime
        self._attr_unique_id = build_unique_id("Sandbox", entry_id, suffix)
        self._remove_listener = runtime.add_listener(self.async_write_ha_state)

    @property
    def available(self) -> bool:
        """Keep actions visible while their loaded runtime owns the device."""
        return self._runtime.virtual_entity_available

    @property
    def device_info(self) -> DeviceInfo:
        """Associate each sandbox action with its entry-owned virtual battery."""
        assert self._runtime.pretend_gx_id is not None
        return virtual_battery_device_info(self._runtime.pretend_gx_id)

    async def async_will_remove_from_hass(self) -> None:
        """Remove the entry-local runtime callback."""
        self._remove_listener()
        await super().async_will_remove_from_hass()


class SandboxStepButton(_SandboxButton):
    """Advance this sandbox by one deterministic half-hour step."""

    _attr_name = "Step simulation"

    def __init__(self, runtime: HorizonIQEntryRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id, "simulation_step")

    @property
    def available(self) -> bool:
        return super().available and self._runtime.operating_mode == "replay"

    async def async_press(self) -> None:
        """Apply the next virtual half hour."""
        await self._runtime.async_step()


class SandboxResetButton(_SandboxButton):
    """Reset this sandbox to its initial battery state."""

    _attr_name = "Reset simulation"

    def __init__(self, runtime: HorizonIQEntryRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id, "simulation_reset")

    async def async_press(self) -> None:
        """Reset only this virtual battery state and clock."""
        await self._runtime.async_reset()


class SandboxResetProfileButton(_SandboxButton):
    """Reset the selected replay profile cursor."""

    _attr_name = "Reset profile"

    def __init__(self, runtime: HorizonIQEntryRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id, "profile_reset")

    @property
    def available(self) -> bool:
        return super().available and self._runtime.operating_mode == "replay"

    async def async_press(self) -> None:
        await self._runtime.async_reset_playback()


class SandboxSaveSnapshotButton(_SandboxButton):
    """Save a clearly named, local point-in-time snapshot."""

    _attr_name = "Save snapshot"

    def __init__(self, runtime: HorizonIQEntryRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id, "snapshot_save")

    async def async_press(self) -> None:
        timestamp = datetime.now(timezone.utc).strftime("manual-%Y%m%d-%H%M%S")
        await self._runtime.async_save_snapshot(timestamp)


class SandboxInjectFaultButton(_SandboxButton):
    """Inject the currently selected bounded sandbox fault."""

    _attr_name = "Inject selected fault"

    def __init__(self, runtime: HorizonIQEntryRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id, "fault_inject")

    async def async_press(self) -> None:
        await self._runtime.async_inject_selected_fault()


class SandboxClearFaultsButton(_SandboxButton):
    """Clear all local fault definitions for this sandbox."""

    _attr_name = "Clear faults"

    def __init__(self, runtime: HorizonIQEntryRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id, "fault_clear")

    async def async_press(self) -> None:
        await self._runtime.async_clear_all_faults()

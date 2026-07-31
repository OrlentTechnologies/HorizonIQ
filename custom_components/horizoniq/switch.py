"""Sandbox lifecycle controls."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity_helpers import build_unique_id, virtual_battery_device_info
from .sandbox_runtime import HorizonIQEntryRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the entry-local sandbox enable control when configured."""
    runtime: HorizonIQEntryRuntime = hass.data[DOMAIN][config_entry.entry_id]
    if runtime.is_sandbox_configured:
        async_add_entities(
            [
                SandboxEnableSwitch(runtime, config_entry.entry_id),
                SandboxProfilePlaybackSwitch(runtime, config_entry.entry_id),
            ]
        )


class SandboxEnableSwitch(SwitchEntity):
    """Start and stop one virtual battery without touching other entries."""

    _attr_has_entity_name = True
    _attr_name = "Simulation"

    def __init__(self, runtime: HorizonIQEntryRuntime, entry_id: str) -> None:
        """Initialize the entry-local control."""
        self._runtime = runtime
        self._attr_unique_id = build_unique_id("Sandbox", entry_id, "simulation")
        self._remove_listener = runtime.add_listener(self.async_write_ha_state)

    @property
    def device_info(self) -> DeviceInfo:
        """Associate the control with exactly one generated virtual device."""
        assert self._runtime.pretend_gx_id is not None
        return virtual_battery_device_info(self._runtime.pretend_gx_id)

    @property
    def is_on(self) -> bool:
        """Return whether this entry's simulation loop is active."""
        return self._runtime.simulator_enabled

    async def async_turn_on(self, **kwargs: object) -> None:
        """Enable this entry's virtual battery."""
        await self._runtime.async_enable(self.hass)

    async def async_turn_off(self, **kwargs: object) -> None:
        """Disable this entry's virtual battery."""
        await self._runtime.async_disable()

    async def async_will_remove_from_hass(self) -> None:
        """Remove the entry-local runtime callback."""
        self._remove_listener()
        await super().async_will_remove_from_hass()


class SandboxProfilePlaybackSwitch(SwitchEntity):
    """Start or pause the selected deterministic replay profile."""

    _attr_has_entity_name = True
    _attr_name = "Profile playback"

    def __init__(self, runtime: HorizonIQEntryRuntime, entry_id: str) -> None:
        self._runtime = runtime
        self._attr_unique_id = build_unique_id("Sandbox", entry_id, "profile_playback")
        self._remove_listener = runtime.add_listener(self.async_write_ha_state)

    @property
    def device_info(self) -> DeviceInfo:
        assert self._runtime.pretend_gx_id is not None
        return virtual_battery_device_info(self._runtime.pretend_gx_id)

    @property
    def available(self) -> bool:
        return self._runtime.simulator_enabled and self._runtime.selected_profile_filename is not None

    @property
    def is_on(self) -> bool:
        return self._runtime.playback_state == "running"

    async def async_turn_on(self, **kwargs: object) -> None:
        await self._runtime.async_start_playback()

    async def async_turn_off(self, **kwargs: object) -> None:
        await self._runtime.async_pause_playback()

    async def async_will_remove_from_hass(self) -> None:
        self._remove_listener()
        await super().async_will_remove_from_hass()

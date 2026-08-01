"""Entry-scoped Home Assistant services for HorizonIQ virtual sandboxes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Final
import math

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .forecast_schema5 import Schema5Forecast
from .sandbox_runtime import MAX_BATTERY_ENERGY_WH, HorizonIQEntryRuntime


_SETUP_KEY: Final = f"{DOMAIN}_sandbox_services_registered"
_ENTRY_ID = vol.Required("entry_id")
_NAME = vol.Required("name")
_FAULT_ID = vol.Required("fault_id")


def _finite_percentage(value: object) -> float:
    """Reject boolean and non-finite values before entry-local validation."""
    if isinstance(value, bool):
        raise vol.Invalid("state_of_charge must be a finite percentage")
    try:
        percentage = float(value)
    except (TypeError, ValueError) as err:
        raise vol.Invalid("state_of_charge must be a finite percentage") from err
    if not math.isfinite(percentage):
        raise vol.Invalid("state_of_charge must be a finite percentage")
    return percentage


def _runtime(hass: HomeAssistant, entry_id: str) -> HorizonIQEntryRuntime:
    runtime = hass.data.get(DOMAIN, {}).get(entry_id)
    if not isinstance(runtime, HorizonIQEntryRuntime) or not runtime.is_sandbox_configured:
        raise HomeAssistantError("The selected HorizonIQ entry is not a virtual sandbox")
    if runtime._unloaded or not runtime.simulator_enabled:
        raise HomeAssistantError("The selected HorizonIQ sandbox is inactive")
    return runtime


def _diagnostics_runtime(hass: HomeAssistant, entry_id: str) -> HorizonIQEntryRuntime:
    """Return one configured sandbox without requiring its simulator to run."""
    runtime = hass.data.get(DOMAIN, {}).get(entry_id)
    if not isinstance(runtime, HorizonIQEntryRuntime) or not runtime.is_sandbox_configured:
        raise HomeAssistantError("The selected HorizonIQ entry is not a virtual sandbox")
    if runtime._unloaded:
        raise HomeAssistantError("The selected HorizonIQ sandbox is unloaded")
    return runtime


async def _async_load_profile(hass: HomeAssistant, call: ServiceCall) -> None:
    await _runtime(hass, call.data["entry_id"]).async_select_profile(call.data["filename"])


async def _async_start_profile(hass: HomeAssistant, call: ServiceCall) -> None:
    await _runtime(hass, call.data["entry_id"]).async_start_playback()


async def _async_pause_profile(hass: HomeAssistant, call: ServiceCall) -> None:
    await _runtime(hass, call.data["entry_id"]).async_pause_playback()


async def _async_stop_profile(hass: HomeAssistant, call: ServiceCall) -> None:
    await _runtime(hass, call.data["entry_id"]).async_stop_playback()


async def _async_reset_profile(hass: HomeAssistant, call: ServiceCall) -> None:
    await _runtime(hass, call.data["entry_id"]).async_reset_playback()


async def _async_step(hass: HomeAssistant, call: ServiceCall) -> None:
    await _runtime(hass, call.data["entry_id"]).async_step(call.data.get("seconds", 1800))


async def _async_reset(hass: HomeAssistant, call: ServiceCall) -> None:
    await _runtime(hass, call.data["entry_id"]).async_reset(
        energy_wh=call.data.get("energy_wh")
    )


async def _async_set_state_of_charge(hass: HomeAssistant, call: ServiceCall) -> None:
    """Set the stored energy of exactly one active virtual sandbox."""
    await _runtime(hass, call.data["entry_id"]).async_set_state_of_charge(
        call.data["state_of_charge"]
    )


async def _async_snapshot_create(hass: HomeAssistant, call: ServiceCall) -> None:
    await _runtime(hass, call.data["entry_id"]).async_save_snapshot(
        call.data["name"],
        replace=call.data.get("replace", False),
    )


async def _async_snapshot_list(hass: HomeAssistant, call: ServiceCall) -> dict[str, list[str]]:
    snapshots = _runtime(hass, call.data["entry_id"]).list_snapshots()
    return {"snapshots": list(snapshots)}


async def _async_snapshot_restore(hass: HomeAssistant, call: ServiceCall) -> None:
    await _runtime(hass, call.data["entry_id"]).async_restore_snapshot(call.data["name"])


async def _async_snapshot_delete(hass: HomeAssistant, call: ServiceCall) -> None:
    await _runtime(hass, call.data["entry_id"]).async_delete_snapshot(call.data["name"])


async def _async_get_sandbox_forecast_diagnostics(
    hass: HomeAssistant, call: ServiceCall
) -> dict[str, object]:
    """Return the complete normalized horizon for exactly one sandbox entry."""
    runtime = _diagnostics_runtime(hass, call.data["entry_id"])
    forecast = getattr(runtime, "last_forecast", None)
    if not isinstance(forecast, Schema5Forecast):
        forecast = getattr(runtime, "forecast_diagnostics", None)
    if not isinstance(forecast, Schema5Forecast):
        raise HomeAssistantError("No complete schema-5 forecast is available")
    return forecast.to_dict()


async def _async_fault_configure(hass: HomeAssistant, call: ServiceCall) -> None:
    runtime = _runtime(hass, call.data["entry_id"])
    virtual_time = runtime.virtual_time_utc
    if virtual_time is None:
        raise HomeAssistantError("The sandbox clock is unavailable")
    fault = await runtime.async_configure_fault(
        kind=call.data["kind"],
        activation_utc=virtual_time,
        remaining_count=call.data.get("remaining_count"),
        remaining_duration_seconds=call.data.get("remaining_duration_seconds"),
        settings=call.data.get("settings"),
    )
    if call.data.get("activate", True):
        await runtime.async_activate_fault(fault.fault_id)


async def _async_fault_activate(hass: HomeAssistant, call: ServiceCall) -> None:
    await _runtime(hass, call.data["entry_id"]).async_activate_fault(call.data["fault_id"])


async def _async_fault_clear(hass: HomeAssistant, call: ServiceCall) -> None:
    await _runtime(hass, call.data["entry_id"]).async_clear_fault(call.data["fault_id"])


async def _async_fault_clear_all(hass: HomeAssistant, call: ServiceCall) -> None:
    await _runtime(hass, call.data["entry_id"]).async_clear_all_faults()


def _service_handler(
    hass: HomeAssistant,
    callback: Callable[[HomeAssistant, ServiceCall], Awaitable[object]],
) -> Callable[[ServiceCall], Awaitable[object]]:
    """Bind Home Assistant while retaining an async service callback."""

    async def handler(call: ServiceCall) -> object:
        try:
            return await callback(hass, call)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    return handler


def async_setup_services(hass: HomeAssistant) -> None:
    """Register idempotent global services; every call remains entry scoped."""
    if hass.data.get(_SETUP_KEY):
        return
    hass.data[_SETUP_KEY] = True
    entry_schema = vol.Schema({_ENTRY_ID: str})
    named_schema = vol.Schema({_ENTRY_ID: str, _NAME: str})
    hass.services.async_register(DOMAIN, "load_profile", _service_handler(hass, _async_load_profile), schema=vol.Schema({_ENTRY_ID: str, vol.Required("filename"): str}))
    hass.services.async_register(DOMAIN, "start_profile", _service_handler(hass, _async_start_profile), schema=entry_schema)
    hass.services.async_register(DOMAIN, "pause_profile", _service_handler(hass, _async_pause_profile), schema=entry_schema)
    hass.services.async_register(DOMAIN, "stop_profile", _service_handler(hass, _async_stop_profile), schema=entry_schema)
    hass.services.async_register(DOMAIN, "reset_profile", _service_handler(hass, _async_reset_profile), schema=entry_schema)
    hass.services.async_register(DOMAIN, "step", _service_handler(hass, _async_step), schema=vol.Schema({_ENTRY_ID: str, vol.Optional("seconds"): vol.All(vol.Coerce(float), vol.Range(min=0.001, max=86_400))}))
    hass.services.async_register(DOMAIN, "reset", _service_handler(hass, _async_reset), schema=vol.Schema({_ENTRY_ID: str, vol.Optional("energy_wh"): vol.All(vol.Coerce(float), vol.Range(min=0, max=MAX_BATTERY_ENERGY_WH))}))
    hass.services.async_register(DOMAIN, "set_virtual_battery_state_of_charge", _service_handler(hass, _async_set_state_of_charge), schema=vol.Schema({_ENTRY_ID: str, vol.Required("state_of_charge"): _finite_percentage}))
    hass.services.async_register(DOMAIN, "snapshot_create", _service_handler(hass, _async_snapshot_create), schema=vol.Schema({_ENTRY_ID: str, _NAME: str, vol.Optional("replace", default=False): bool}))
    hass.services.async_register(DOMAIN, "snapshot_list", _service_handler(hass, _async_snapshot_list), schema=entry_schema, supports_response=SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, "snapshot_restore", _service_handler(hass, _async_snapshot_restore), schema=named_schema)
    hass.services.async_register(DOMAIN, "snapshot_delete", _service_handler(hass, _async_snapshot_delete), schema=named_schema)
    hass.services.async_register(
        DOMAIN,
        "get_sandbox_forecast_diagnostics",
        _service_handler(hass, _async_get_sandbox_forecast_diagnostics),
        schema=entry_schema,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(DOMAIN, "fault_configure", _service_handler(hass, _async_fault_configure), schema=vol.Schema({_ENTRY_ID: str, vol.Required("kind"): str, vol.Optional("remaining_count"): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)), vol.Optional("remaining_duration_seconds"): vol.All(vol.Coerce(float), vol.Range(min=1, max=900)), vol.Optional("settings"): dict, vol.Optional("activate", default=True): bool}))
    hass.services.async_register(DOMAIN, "fault_activate", _service_handler(hass, _async_fault_activate), schema=vol.Schema({_ENTRY_ID: str, _FAULT_ID: str}))
    hass.services.async_register(DOMAIN, "fault_clear", _service_handler(hass, _async_fault_clear), schema=vol.Schema({_ENTRY_ID: str, _FAULT_ID: str}))
    hass.services.async_register(DOMAIN, "fault_clear_all", _service_handler(hass, _async_fault_clear_all), schema=entry_schema)

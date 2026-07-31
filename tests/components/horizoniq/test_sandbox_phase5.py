"""Phase 5 entity-control, service, and status coverage."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.helpers.entity import EntityCategory

from homeassistant.exceptions import HomeAssistantError
from custom_components.horizoniq.const import (
    CAPACITY_SOURCE_VIRTUAL_BATTERY,
    CONF_CAPACITY_SOURCE,
    CONF_ENVIRONMENT,
    CONF_REGISTRATION_CONFIG,
    CONF_REGISTRATION_ID,
    DOMAIN,
    SANDBOX_ENVIRONMENT,
)
from custom_components.horizoniq.sandbox_runtime import HorizonIQEntryRuntime
from custom_components.horizoniq.number import SandboxNumber, _CONTROLS
from custom_components.horizoniq.services import async_setup_services
from custom_components.horizoniq.select import (
    SandboxEquipmentProfileSelect,
    SandboxFaultKindSelect,
    SandboxProfileSelect,
)
from custom_components.horizoniq.sensors import (
    SandboxRuntimeSensor,
    _sandbox_entities,
)
from custom_components.horizoniq.simulation.models import (
    CommandStatus,
    IntervalLedger,
)


REGISTRATION_ID = "11111111-1111-4111-8111-111111111111"


def _runtime(entry_id: str = "phase5-entry") -> HorizonIQEntryRuntime:
    coordinator = MagicMock()
    coordinator.async_pause_for_sandbox = AsyncMock()
    coordinator.async_resume_from_sandbox = AsyncMock()
    coordinator.last_update_success = True
    runtime = HorizonIQEntryRuntime(coordinator, REGISTRATION_ID, entry_id)
    runtime.configure_sandbox(
        {
            CONF_ENVIRONMENT: SANDBOX_ENVIRONMENT,
            CONF_CAPACITY_SOURCE: CAPACITY_SOURCE_VIRTUAL_BATTERY,
            CONF_REGISTRATION_ID: REGISTRATION_ID,
            CONF_REGISTRATION_CONFIG: {
                "ChargeEfficiency": 0.95,
                "DischargeEfficiency": 0.9,
                "EquipmentProfile": {
                    "BatteryCapacityWh": 10_000,
                    "MinimumCapacityPercentage": 0.2,
                    "MaximumBatteryChargePowerWatts": 2_000,
                    "MaximumBatteryDischargePowerWatts": 2_000,
                },
            },
        }
    )
    return runtime


async def _enable(hass, runtime: HorizonIQEntryRuntime) -> None:
    with (
        patch(
            "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
            new=AsyncMock(return_value=lambda: None),
        ),
        patch(
            "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",
            new=AsyncMock(),
        ),
    ):
        await runtime.async_enable(hass)


async def test_manual_controls_persist_and_status_entities_are_entry_local(hass) -> None:
    """Manual operational controls update only their active virtual battery."""
    runtime = _runtime()
    await runtime.async_restore_storage(hass)
    await _enable(hass, runtime)

    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",
        new=AsyncMock(),
    ):
        await runtime.async_set_inputs(load_w=1_250, solar_w=350)
        await runtime.async_set_control_value("capacity_wh", 12_000)
        await runtime.async_set_control_value("reserve_wh", 2_500)
        await runtime.async_set_control_value("charge_efficiency", 0.92)

    assert runtime.load_w == 1_250
    assert runtime.solar_w == 350
    assert runtime.capacity_wh == 12_000
    assert runtime.reserve_wh == 2_500
    assert runtime.charge_efficiency == 0.92

    balance = SandboxRuntimeSensor(runtime, runtime.entry_id, "balance_error", "Balance")
    decision = SandboxRuntimeSensor(runtime, runtime.entry_id, "decision", "Decision")
    assert balance.native_value == 0
    assert decision.native_value == "Fallback missing"
    assert balance.extra_state_attributes["ledger"]["grid_import_wh"] == 0
    balance._remove_listener()
    decision._remove_listener()

    await runtime.async_disable()
    reloaded = _runtime()
    await reloaded.async_restore_storage(hass)
    assert reloaded.capacity_wh == 12_000
    assert reloaded.reserve_wh == 2_500
    assert reloaded.charge_efficiency == 0.92


async def test_virtual_battery_ui_formats_states_and_categories(hass) -> None:
    """Virtual-battery states remain readable without changing their IDs."""
    runtime = _runtime()
    await runtime.async_restore_storage(hass)
    await _enable(hass, runtime)
    await runtime.async_set_state_of_charge(66.666)
    runtime._last_battery_power_w = 123.456
    runtime._last_grid_power_w = -456.789
    runtime._cumulative_ledger = IntervalLedger(
        grid_import_wh=12.345,
        manual_adjustment_wh=1_666.6,
        balance_error_wh=0.123,
    )
    runtime.last_command_status = CommandStatus.NO_ACTION
    runtime.last_command_reason = "stale_telemetry"

    sensors = {sensor._key: sensor for sensor in _sandbox_entities(runtime, runtime.entry_id)}
    assert sensors["soc"].native_value == 66.7
    assert sensors["energy"].native_value == 6666.6
    assert sensors["battery_power"].native_value == 123.5
    assert sensors["grid_power"].native_value == -456.8
    assert sensors["balance_error"].native_value == 0.1
    assert sensors["command"].native_value == "No action"
    assert sensors["decision"].native_value == "Stale telemetry"
    assert sensors["soc"].extra_state_attributes["profile"] == "Not selected"
    assert sensors["soc"].extra_state_attributes["ledger"]["grid_import_wh"] == 12.3

    diagnostic_keys = {
        "mqtt",
        "forecast",
        "command",
        "decision",
        "health",
        "balance_error",
        "profile_cursor",
        "faults",
    }
    for key, sensor in sensors.items():
        expected = EntityCategory.DIAGNOSTIC if key in diagnostic_keys else None
        assert sensor.entity_category is expected
        sensor._remove_listener()

    await runtime.async_disable()


def test_state_of_charge_control_availability_follows_loaded_runtime() -> None:
    """The SoC control remains visible while the entry owns its runtime."""
    runtime = _runtime()
    description = next(item for item in _CONTROLS if item.key == "set_state_of_charge")
    number = SandboxNumber(runtime, runtime.entry_id, description)

    assert number.available is True
    runtime.simulator_enabled = True
    assert number.available is True
    runtime._playback_state = "running"
    assert number.available is True
    number._remove_listener()


def test_fault_selector_uses_friendly_enum_labels() -> None:
    """Fault selection keeps runtime enum values out of the visible UI."""
    runtime = _runtime()
    selector = SandboxFaultKindSelect(runtime, runtime.entry_id)

    assert selector.current_option == "Stale Telemetry"
    assert "Stale Telemetry" in selector.options
    selector._remove_listener()


def test_profile_controls_expose_selection_state_and_availability() -> None:
    """Profile controls do not expose unknown or become unavailable when idle."""
    runtime = _runtime()
    profile = SandboxProfileSelect(runtime, runtime.entry_id)
    equipment = SandboxEquipmentProfileSelect(runtime, runtime.entry_id)

    assert profile.current_option == "Not selected"
    assert "Not selected" in profile.options
    assert profile.available is True
    assert equipment.available is True
    profile._remove_listener()
    equipment._remove_listener()


async def test_manual_control_and_input_bounds_match_the_mqtt_contract(hass) -> None:
    """The service-facing controls accept exactly the documented limits."""
    runtime = _runtime()
    await runtime.async_restore_storage(hass)
    await _enable(hass, runtime)

    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",
        new=AsyncMock(),
    ):
        await runtime.async_set_inputs(load_w=100_000, solar_w=100_000)
        await runtime.async_set_control_value("capacity_wh", 2_000_000)
        await runtime.async_set_control_value("reserve_wh", 2_000_000)
        await runtime.async_set_control_value("max_charge_power_w", 100_000)
        await runtime.async_set_control_value("max_discharge_power_w", 100_000)

        with pytest.raises(ValueError, match="supported range"):
            await runtime.async_set_inputs(load_w=100_001, solar_w=0)
        with pytest.raises(ValueError, match="supported range"):
            await runtime.async_set_inputs(load_w=0, solar_w=100_001)
        with pytest.raises(ValueError, match="supported range"):
            await runtime.async_set_control_value("capacity_wh", 2_000_001)
        with pytest.raises(ValueError, match="supported range"):
            await runtime.async_set_control_value("max_charge_power_w", 100_001)

    await runtime.async_disable()


async def test_snapshot_services_are_registered_and_scoped_to_owning_entry(hass) -> None:
    """Snapshot service calls cannot cross the configured sandbox entry boundary."""
    runtime = _runtime()
    await runtime.async_restore_storage(hass)
    await _enable(hass, runtime)
    hass.data.setdefault(DOMAIN, {})[runtime.entry_id] = runtime
    async_setup_services(hass)

    await hass.services.async_call(
        DOMAIN,
        "snapshot_create",
        {"entry_id": runtime.entry_id, "name": "phase-five"},
        blocking=True,
    )
    response = await hass.services.async_call(
        DOMAIN,
        "snapshot_list",
        {"entry_id": runtime.entry_id},
        blocking=True,
        return_response=True,
    )

    assert response == {"snapshots": ["phase-five"]}
    await runtime.async_disable()


async def test_mutating_services_reject_inactive_and_unknown_entries(hass) -> None:
    """Service calls never bypass the active entry-local simulator boundary."""
    runtime = _runtime()
    await runtime.async_restore_storage(hass)
    hass.data.setdefault(DOMAIN, {})[runtime.entry_id] = runtime
    async_setup_services(hass)

    with pytest.raises(HomeAssistantError, match="inactive"):
        await hass.services.async_call(
            DOMAIN,
            "reset",
            {"entry_id": runtime.entry_id},
            blocking=True,
        )
    with pytest.raises(HomeAssistantError, match="not a virtual sandbox"):
        await hass.services.async_call(
            DOMAIN,
            "snapshot_create",
            {"entry_id": "unknown", "name": "never"},
            blocking=True,
        )

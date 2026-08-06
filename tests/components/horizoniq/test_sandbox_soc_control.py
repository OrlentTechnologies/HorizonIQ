"""End-to-end Home Assistant controls for virtual-battery state of charge."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.horizoniq.const import (
    CAPACITY_SOURCE_VIRTUAL_BATTERY,
    CONF_API_KEY,
    CONF_BATTERY_CAPACITY_SENSOR,
    CONF_CAPACITY_SOURCE,
    CONF_ENVIRONMENT,
    CONF_HASH,
    CONF_REGISTRATION_CONFIG,
    CONF_REGISTRATION_DATA,
    CONF_REGISTRATION_ID,
    CONF_URL,
    DOMAIN,
    SANDBOX_ENVIRONMENT,
)
from custom_components.horizoniq.entity_helpers import build_unique_id
from custom_components.horizoniq.number import _CONTROLS
from custom_components.horizoniq.simulation.clock import ClockRate


REGISTRATION_ID = "33333333-3333-4333-8333-333333333333"


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="HorizonIQ (Sandbox)",
        entry_id="soc-control-entry",
        version=3,
        data={
            CONF_URL: "https://example.com/api/Forecast_Get?code=test-code",
            CONF_API_KEY: "test-api-key",
            CONF_BATTERY_CAPACITY_SENSOR: "sensor.unused_capacity",
            CONF_CAPACITY_SOURCE: CAPACITY_SOURCE_VIRTUAL_BATTERY,
            CONF_ENVIRONMENT: SANDBOX_ENVIRONMENT,
            CONF_HASH: "",
            CONF_REGISTRATION_DATA: "",
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
        },
    )


def _entity_id(hass, domain: str, entry_id: str, suffix: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, build_unique_id(SANDBOX_ENVIRONMENT, entry_id, suffix)
    )
    assert entity_id is not None
    return entity_id


def _assert_virtual_entities_are_available(hass, entry_id: str) -> None:
    """Assert all entry-local virtual entities publish a state immediately."""
    entity_suffixes = {
        "sensor": (
            "forecast_diagnostics",
            "forecast_cadence",
            "bms_state",
            "trial_status",
            "status",
            "soc",
            "energy",
            "battery_power",
            "grid_power",
            "clock",
            "mqtt",
            "forecast",
            "command",
            "decision",
            "health",
            "balance_error",
            "profile_cursor",
            "faults",
        ),
        "number": tuple(description.key for description in _CONTROLS),
        "switch": ("simulation", "profile_playback"),
        "select": (
            "clock_rate",
            "profile",
            "scenario",
            "equipment_profile",
            "operating_mode",
            "charging_source",
            "fault_kind",
        ),
        "button": (
            "simulation_step",
            "simulation_reset",
            "profile_reset",
            "snapshot_save",
            "fault_inject",
            "fault_clear",
        ),
    }
    replay_only = {
        ("sensor", "clock"),
        ("switch", "profile_playback"),
        ("select", "clock_rate"),
        ("select", "profile"),
        ("button", "simulation_step"),
        ("button", "profile_reset"),
    }
    for domain, suffixes in entity_suffixes.items():
        for suffix in suffixes:
            entity_id = _entity_id(hass, domain, entry_id, suffix)
            if (domain, suffix) in replay_only:
                assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
            else:
                assert hass.states.get(entity_id).state != STATE_UNAVAILABLE


@pytest.mark.asyncio
async def test_virtual_entities_remain_available_when_runtime_is_disabled_or_offline(hass) -> None:
    """UI availability is independent from simulation, MQTT, and forecast health."""
    entry = _entry()
    entry.add_to_hass(hass)
    with (
        patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()),
        patch(
            "custom_components.horizoniq.coordinator.HorizonIQCoordinator.async_refresh",
            AsyncMock(),
        ),
        patch(
            "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
            AsyncMock(side_effect=RuntimeError("MQTT unavailable")),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        _assert_virtual_entities_are_available(hass, entry.entry_id)

        simulation = _entity_id(hass, "switch", entry.entry_id, "simulation")
        state_of_charge = _entity_id(
            hass, "number", entry.entry_id, "set_state_of_charge"
        )
        assert hass.states.get(state_of_charge).state == "50.0"
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": simulation}, blocking=True
        )
        await hass.async_block_till_done()
        assert hass.states.get(simulation).state == "on"
        _assert_virtual_entities_are_available(hass, entry.entry_id)

        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": state_of_charge, "value": 75},
            blocking=True,
        )

        assert await hass.config_entries.async_unload(entry.entry_id)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        _assert_virtual_entities_are_available(hass, entry.entry_id)
        assert hass.states.get(state_of_charge).state == "75.0"
        assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
async def test_service_and_number_update_paused_virtual_battery_entities(hass) -> None:
    """A real entry setup changes SoC/energy without a broker or clock advance."""
    entry = _entry()
    entry.add_to_hass(hass)
    with (
        patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()),
        patch(
            "custom_components.horizoniq.coordinator.HorizonIQCoordinator.async_refresh",
            AsyncMock(),
        ),
        patch(
            "custom_components.horizoniq.coordinator.HorizonIQCoordinator.async_fetch_sandbox_forecast",
            AsyncMock(return_value=None),
        ),
        patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", AsyncMock()) as publish,
        patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe", AsyncMock()) as subscribe,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        runtime = hass.data[DOMAIN][entry.entry_id]
        switch = _entity_id(hass, "switch", entry.entry_id, "simulation")
        number = _entity_id(hass, "number", entry.entry_id, "set_state_of_charge")
        soc = _entity_id(hass, "sensor", entry.entry_id, "soc")
        energy = _entity_id(hass, "sensor", entry.entry_id, "energy")

        await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
        assert runtime.clock_rate == ClockRate.PAUSED.value
        frozen_now = runtime.virtual_time_utc
        assert frozen_now is not None
        runtime._live_forecast_now = lambda: frozen_now
        time_before = runtime.virtual_time_utc
        number_state = hass.states.get(number)
        assert number_state.attributes["mode"] == "box"
        assert number_state.attributes["unit_of_measurement"] == "%"
        assert number_state.attributes["step"] == 0.1

        await hass.services.async_call(
            DOMAIN,
            "set_virtual_battery_state_of_charge",
            {"entry_id": entry.entry_id, "state_of_charge": 75},
            blocking=True,
        )
        await hass.async_block_till_done()
        assert hass.states.get(soc).state == "75.0"
        assert hass.states.get(energy).state == "7500.0"
        assert hass.states.get(energy).attributes["unit_of_measurement"] == "Wh"
        assert hass.states.get(number).state == "75.0"
        assert runtime.virtual_time_utc == time_before
        assert runtime.energy_ledger.manual_adjustment_wh == 2_500
        assert runtime.energy_ledger.balance_error_wh == 0
        assert runtime.current_capacity() == "7500.0"
        assert runtime.last_command_status.value == "awaiting_forecast"

        await runtime.async_reset(energy_wh=7_777.77)
        await hass.async_block_till_done()
        assert hass.states.get(number).state == "77.8"

        await runtime.async_set_control_value("capacity_wh", 20_000)
        await hass.async_block_till_done()
        assert hass.states.get(number).state == "38.9"

        await runtime.async_save_snapshot("soc-box")

        await hass.services.async_call(
            "number", "set_value", {"entity_id": number, "value": 72.3}, blocking=True
        )
        await hass.async_block_till_done()
        assert hass.states.get(soc).state == "72.3"
        assert hass.states.get(energy).state == "14460.0"
        assert runtime.energy_wh == 14_460

        await runtime.async_restore_snapshot("soc-box")
        await hass.async_block_till_done()
        assert hass.states.get(number).state == "38.9"

        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": switch}, blocking=True
        )
        assert hass.states.get(number).state == "38.9"
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": switch}, blocking=True
        )
        assert hass.states.get(number).state == "38.9"
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": switch}, blocking=True
        )
        assert publish.await_count > 0
        assert subscribe.await_count == 14
        assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
async def test_soc_validation_persistence_snapshots_and_isolation(hass) -> None:
    """Reserve, replay, records, and entries remain safely isolated."""
    entry = _entry()
    entry.add_to_hass(hass)
    with patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()), patch(
        "custom_components.horizoniq.coordinator.HorizonIQCoordinator.async_refresh", AsyncMock()
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    runtime = hass.data[DOMAIN][entry.entry_id]
    runtime.simulator_enabled = True
    runtime._hass = hass
    await runtime.async_restore_storage(hass)
    await runtime.async_set_state_of_charge(75)
    await runtime.async_save_snapshot("manual")
    assert runtime._named_snapshots["manual"]

    before = runtime.energy_wh
    for invalid in (19, 101, float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            await runtime.async_set_state_of_charge(invalid)
    assert runtime.energy_wh == before

    await runtime.async_set_control_value("reserve_wh", 3_000)
    assert runtime.reserve_percent == 30
    with pytest.raises(ValueError, match="reserve"):
        await runtime.async_set_state_of_charge(29)
    await runtime.async_restore_snapshot("manual")
    assert runtime.energy_wh == 7_500
    assert runtime.energy_ledger.manual_adjustment_wh == 2_500

    before_manual_adjustment = runtime.energy_ledger.manual_adjustment_wh
    await runtime.async_set_state_of_charge(80)
    assert runtime.energy_wh == 8_000
    assert runtime.energy_ledger.manual_adjustment_wh == (
        before_manual_adjustment + 500
    )

    await runtime.async_unload()
    with pytest.raises(ValueError, match="inactive"):
        await runtime.async_set_state_of_charge(80)
    assert await hass.config_entries.async_unload(entry.entry_id)

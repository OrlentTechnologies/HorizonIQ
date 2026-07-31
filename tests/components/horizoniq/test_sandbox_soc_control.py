"""End-to-end Home Assistant controls for virtual-battery state of charge."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
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
        time_before = runtime.virtual_time_utc
        number_state = hass.states[number]
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
        assert hass.states[soc].state == "75.0"
        assert hass.states[energy].state == "7500.0"
        assert hass.states[energy].attributes["unit_of_measurement"] == "Wh"
        assert hass.states[number].state == "75.0"
        assert runtime.virtual_time_utc == time_before
        assert runtime.energy_ledger.manual_adjustment_wh == 2_500
        assert runtime.energy_ledger.balance_error_wh == 0
        assert runtime.current_capacity() == "7500.0"
        assert runtime.last_command_status.value == "awaiting_forecast"

        await runtime.async_reset(energy_wh=7_777.77)
        await hass.async_block_till_done()
        assert hass.states[number].state == "77.8"

        await runtime.async_set_control_value("capacity_wh", 20_000)
        await hass.async_block_till_done()
        assert hass.states[number].state == "38.9"

        await runtime.async_save_snapshot("soc-box")

        await hass.services.async_call(
            "number", "set_value", {"entity_id": number, "value": 72.3}, blocking=True
        )
        await hass.async_block_till_done()
        assert hass.states[soc].state == "72.3"
        assert hass.states[energy].state == "14460.0"
        assert runtime.energy_wh == 14_460

        await runtime.async_restore_snapshot("soc-box")
        await hass.async_block_till_done()
        assert hass.states[number].state == "38.9"
        assert publish.await_count == 0
        assert subscribe.await_count == 0
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

    await runtime.async_unload()
    with pytest.raises(ValueError, match="inactive"):
        await runtime.async_set_state_of_charge(80)
    assert await hass.config_entries.async_unload(entry.entry_id)

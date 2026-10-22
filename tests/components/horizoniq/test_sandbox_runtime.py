"""Tests for entry-local virtual-battery runtime ownership."""

from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

import pytest

from custom_components.horizoniq.const import (
    CAPACITY_SOURCE_VIRTUAL_BATTERY,
    CONF_CAPACITY_SOURCE,
    CONF_ENVIRONMENT,
    CONF_INSTALLATION_ID,
    CONF_REGISTRATION_CONFIG,
    CONF_REGISTRATION_ID,
    SANDBOX_ENVIRONMENT,
)
from custom_components.horizoniq.sandbox_runtime import (
    HorizonIQEntryRuntime,
    canonical_registration_id,
    pretend_gx_id,
    registration_id_is_unique,
    simulator_config,
)
from custom_components.horizoniq.simulation.models import CommandStatus
from custom_components.horizoniq.simulation.topics import (
    VictronCommandKey,
    VictronTelemetryKey,
    command_issued_topic,
    command_topic,
    telemetry_topic,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry


REGISTRATION_ID = "11111111-1111-4111-8111-111111111111"


def _entry_data(registration_id: str = REGISTRATION_ID) -> dict[str, object]:
    return {
        CONF_ENVIRONMENT: SANDBOX_ENVIRONMENT,
        CONF_INSTALLATION_ID: "same-home-assistant-installation",
        CONF_CAPACITY_SOURCE: CAPACITY_SOURCE_VIRTUAL_BATTERY,
        CONF_REGISTRATION_ID: registration_id,
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


def _runtime(
    registration_id: str = REGISTRATION_ID,
) -> tuple[HorizonIQEntryRuntime, MagicMock]:
    coordinator = MagicMock()
    coordinator.async_pause_for_sandbox = AsyncMock()
    coordinator.async_resume_from_sandbox = AsyncMock()
    runtime = HorizonIQEntryRuntime(coordinator, registration_id)
    runtime.configure_sandbox(_entry_data(registration_id))
    return runtime, coordinator


def test_simulator_configuration_is_sandbox_and_registration_scoped() -> None:
    """Only a valid virtual Sandbox registration creates a virtual battery."""
    config, gx_id = simulator_config(_entry_data()) or (None, None)

    assert config is not None
    assert config.capacity_wh == 10_000
    assert config.reserve_wh == 2_000
    assert gx_id == pretend_gx_id(REGISTRATION_ID)

    live_data = _entry_data()
    live_data[CONF_ENVIRONMENT] = ""
    assert simulator_config(live_data) is None


async def test_runtime_lifecycle_and_step_are_isolated(hass) -> None:
    """Starting, stepping, and stopping one runtime only changes its own state."""
    runtime, coordinator = _runtime()
    second, second_coordinator = _runtime("22222222-2222-4222-8222-222222222222")

    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
        new=AsyncMock(return_value=lambda: None),
    ):
        await runtime.async_enable(hass)
        runtime.set_inputs(load_w=1_000, solar_w=0)
        await runtime.async_step()
        await runtime.async_disable()

    assert runtime.energy_wh is not None and runtime.energy_wh < 5_000
    assert runtime.simulator_enabled is False
    assert second.energy_wh == 5_000
    assert second.simulator_enabled is False
    assert runtime.pretend_gx_id != second.pretend_gx_id
    coordinator.async_pause_for_sandbox.assert_awaited_once()
    coordinator.async_resume_from_sandbox.assert_awaited_once()
    second_coordinator.async_pause_for_sandbox.assert_not_awaited()


async def test_unload_prevents_late_mqtt_callbacks_from_mutating_state(hass) -> None:
    """An in-flight subscription callback cannot change an unloaded runtime."""
    runtime, coordinator = _runtime()
    unsubscribe = MagicMock()

    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
        new=AsyncMock(return_value=unsubscribe),
    ):
        await runtime.async_enable(hass)
        before = runtime.energy_wh
        await runtime.async_unload()

    write = MagicMock(
        payload='{"value": -750}',
        topic=command_topic(
            runtime.pretend_gx_id or "", VictronCommandKey.AC_POWER_SETPOINT
        ),
    )
    await runtime._async_handle_victron_write(write)

    assert runtime.energy_wh == before
    assert runtime.simulator_enabled is False
    assert runtime.last_command_status is CommandStatus.FALLBACK_MISSING
    assert unsubscribe.call_count == 6
    coordinator.async_resume_from_sandbox.assert_not_awaited()


async def test_failed_mqtt_setup_cleans_up_only_its_runtime(hass) -> None:
    """A subscription failure leaves the local virtual runtime usable."""
    runtime, coordinator = _runtime()
    unsubscribe = MagicMock()

    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
        new=AsyncMock(
            side_effect=[
                unsubscribe,
                unsubscribe,
                unsubscribe,
                unsubscribe,
                unsubscribe,
                RuntimeError("no broker"),
            ]
        ),
    ):
        await runtime.async_enable(hass)

    assert runtime.simulator_enabled is True
    assert runtime._mqtt_emulation_enabled is False
    assert unsubscribe.call_count == 5
    coordinator.async_pause_for_sandbox.assert_awaited_once()
    coordinator.async_resume_from_sandbox.assert_not_awaited()
    await runtime.async_disable()
    coordinator.async_resume_from_sandbox.assert_awaited_once()


async def test_virtual_mode_external_power_uses_physics_and_expires(hass) -> None:
    """External control is entry-local, bounded, and never changes SoC directly."""
    runtime, _ = _runtime()
    runtime._live_forecast_now = lambda: datetime(2026, 8, 4, tzinfo=timezone.utc)
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
        new=AsyncMock(return_value=lambda: None),
    ):
        await runtime.async_enable(hass)
    assert runtime.operating_mode == "virtual"
    assert runtime.charging_source == "virtual_battery"
    assert runtime.clock_rate == "paused"

    await runtime.async_select_charging_source("external")
    before = runtime.energy_wh
    await runtime.async_set_external_power(1_000, 60)
    await runtime._async_simulate_segment(
        60,
        runtime.virtual_time_utc,
        0,
        0,
        hass=hass,
    )
    assert runtime.energy_wh is not None and before is not None
    assert runtime.energy_wh > before
    assert runtime.external_power_w == 1_000

    await runtime.async_select_charging_source("virtual_battery")
    assert runtime.external_power_w is None
    assert runtime.last_command_status is CommandStatus.NO_ACTION
    await runtime.async_disable()


async def test_external_power_rejects_wrong_mode_source_and_duration(hass) -> None:
    """Only an active Virtual-mode external entry can accept a bounded command."""
    runtime, _ = _runtime()
    with pytest.raises(ValueError):
        await runtime.async_set_external_power(1_000)
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
        new=AsyncMock(return_value=lambda: None),
    ):
        await runtime.async_enable(hass)
    with pytest.raises(ValueError):
        await runtime.async_set_external_power(1_000)
    await runtime.async_select_charging_source("external")
    with pytest.raises(ValueError):
        await runtime.async_set_external_power(1_000, 301)
    await runtime.async_select_operating_mode("manual")
    with pytest.raises(ValueError):
        await runtime.async_set_external_power(1_000)
    await runtime.async_disable()


async def test_mqtt_setup_is_coordinator_ordered_and_entry_local(hass) -> None:
    """One unavailable MQTT setup leaves only its local transport disabled."""
    failed, failed_coordinator = _runtime()
    healthy, healthy_coordinator = _runtime(
        "22222222-2222-4222-8222-222222222222"
    )
    healthy_unsubscribers = [MagicMock() for _ in range(6)]
    healthy_subscription_index = 0

    async def subscribe(_hass, topic, _callback):
        nonlocal healthy_subscription_index
        if failed.pretend_gx_id in topic:
            assert failed_coordinator.async_pause_for_sandbox.await_count == 1
            raise RuntimeError("Home Assistant MQTT integration is unavailable")
        assert healthy_coordinator.async_pause_for_sandbox.await_count == 1
        unsubscribe = healthy_unsubscribers[healthy_subscription_index]
        healthy_subscription_index += 1
        return unsubscribe

    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
        new=AsyncMock(side_effect=subscribe),
    ):
        await failed.async_enable(hass)
        await healthy.async_enable(hass)

    assert failed.simulator_enabled is True
    assert failed._mqtt_emulation_enabled is False
    failed_coordinator.async_resume_from_sandbox.assert_not_awaited()
    assert healthy.simulator_enabled is True
    healthy_coordinator.async_resume_from_sandbox.assert_not_awaited()
    assert healthy_subscription_index == 6

    await failed.async_disable()
    await healthy.async_disable()
    failed_coordinator.async_resume_from_sandbox.assert_awaited_once()
    for unsubscribe in healthy_unsubscribers:
        unsubscribe.assert_called_once()
    healthy_coordinator.async_resume_from_sandbox.assert_awaited_once()


async def test_runtime_ignores_invalid_issued_metadata_and_unstaged_victron_write(
    hass,
) -> None:
    """Invalid metadata and uncorrelated writes cannot change sandbox state."""
    runtime, _ = _runtime()
    invalid = MagicMock(payload="{", topic="horizoniq/sandbox/example/commands/issued")
    await runtime._async_handle_command_issued(invalid)
    assert runtime.last_command_status is CommandStatus.FALLBACK_MISSING

    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
        new=AsyncMock(return_value=lambda: None),
    ):
        await runtime.async_enable(hass)
        await runtime._async_handle_command_issued(invalid)
    assert runtime.last_command_status is CommandStatus.FALLBACK_MISSING

    write = MagicMock(
        payload='{"value": -750}',
        topic=command_topic(
            runtime.pretend_gx_id or "", VictronCommandKey.AC_POWER_SETPOINT
        ),
    )
    await runtime._async_handle_victron_write(write)
    assert runtime.last_command_status is CommandStatus.FALLBACK_MISSING
    await runtime.async_disable()


def test_registration_and_topic_identity_fail_closed() -> None:
    """A production-looking GX ID cannot be used for sandbox topics."""
    first = MockConfigEntry(
        domain="horizoniq",
        entry_id="first",
        data={CONF_REGISTRATION_ID: REGISTRATION_ID.upper()},
    )
    second = MockConfigEntry(
        domain="horizoniq",
        entry_id="second",
        data={CONF_REGISTRATION_ID: REGISTRATION_ID},
    )

    assert canonical_registration_id(REGISTRATION_ID.upper()) == REGISTRATION_ID
    assert not registration_id_is_unique([first, second], REGISTRATION_ID, "first")
    assert telemetry_topic(
        pretend_gx_id(REGISTRATION_ID), VictronTelemetryKey.STATE_OF_CHARGE
    ).startswith("victron/N/horizoniq-")
    assert command_issued_topic(pretend_gx_id(REGISTRATION_ID)).endswith("/commands/issued")
    with pytest.raises(ValueError):
        command_topic("production-gx", VictronCommandKey.HUB4_MODE)
    with pytest.raises(ValueError):
        command_topic("horizoniq-production", VictronCommandKey.HUB4_MODE)


async def test_manual_mode_advances_local_physics_without_network_or_live_command(hass) -> None:
    """Manual stepping keeps synthetic time entirely local to physics/scenarios."""
    from custom_components.horizoniq.simulation.models import Command, OperatingMode
    runtime, coordinator = _runtime()
    coordinator.async_fetch_sandbox_forecast = AsyncMock(side_effect=AssertionError("manual network"))
    await runtime.async_select_operating_mode("manual")
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe", AsyncMock(return_value=lambda: None)), patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", AsyncMock()):
        await runtime.async_enable(hass)
        await runtime.async_select_scenario("idle")
        runtime.set_inputs(load_w=1_000, solar_w=0)
        runtime._command = Command(OperatingMode.SELF_CONSUMPTION)
        before = runtime.energy_wh
        before_time = runtime.virtual_time_utc
        await runtime.async_step(60)
        assert runtime.energy_wh < before
        assert (runtime.virtual_time_utc - before_time).total_seconds() == 60
        assert runtime._command.mode is OperatingMode.SELF_CONSUMPTION
        coordinator.async_fetch_sandbox_forecast.assert_not_awaited()
        coordinator.async_resume_from_sandbox.assert_not_awaited()
        await runtime.async_unload()


async def test_manual_to_virtual_stays_paused_and_uses_wall_clock_on_enable(hass) -> None:
    """Both mode transitions checkpoint paused; Virtual starts only explicitly."""
    from datetime import timedelta
    runtime, coordinator = _runtime()
    coordinator.async_fetch_sandbox_forecast = AsyncMock(return_value=None)
    wall = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
    runtime._live_forecast_now = lambda: wall
    await runtime.async_select_operating_mode("manual")
    runtime._clock.step(86_400)
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe", AsyncMock(return_value=lambda: None)), patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", AsyncMock()):
        await runtime.async_enable(hass)
        await runtime.async_select_operating_mode("virtual")
        assert runtime.simulator_enabled is False
        assert runtime.virtual_time_utc == wall
        assert runtime.clock_rate == "paused"
        assert runtime.active_setpoint_w is None
        coordinator.async_fetch_sandbox_forecast.assert_not_awaited()
        coordinator.async_resume_from_sandbox.assert_not_awaited()
        await runtime.async_select_operating_mode("virtual")
        with pytest.raises(ValueError, match="^Sandbox operating mode is invalid$"):
            await runtime.async_select_operating_mode("replay")
        wall += timedelta(minutes=1)
        await runtime.async_enable(hass)
        coordinator.async_fetch_sandbox_forecast.assert_awaited_once()
        assert runtime.virtual_time_utc == wall
        await runtime.async_unload()


async def test_manual_registry_cleanup_removes_only_owned_retired_controls(hass) -> None:
    """Removed profile controls disappear in Manual without crossing entry owners."""
    from homeassistant.helpers import entity_registry as er
    from custom_components.horizoniq import _async_remove_stale_sandbox_entities
    from custom_components.horizoniq.const import DOMAIN
    from custom_components.horizoniq.entity_helpers import build_unique_id

    first = MockConfigEntry(domain=DOMAIN, title="First", data=_entry_data(), entry_id="registry-owner")
    second = MockConfigEntry(domain=DOMAIN, title="Second", data=_entry_data("22222222-2222-4222-8222-222222222222"), entry_id="registry-other")
    first.add_to_hass(hass)
    second.add_to_hass(hass)
    registry = er.async_get(hass)
    owned, foreign = [], []
    for entry, saved in ((first, owned), (second, foreign)):
        for domain, suffix in (("select", "profile"), ("switch", "profile_playback"), ("button", "profile_reset")):
            entity = registry.async_get_or_create(domain, DOMAIN, build_unique_id("Sandbox", entry.entry_id, suffix), config_entry=entry)
            saved.append(entity.entity_id)
    manual = registry.async_get_or_create("select", DOMAIN, build_unique_id("Sandbox", first.entry_id, "clock_rate"), config_entry=first)
    runtime, _ = _runtime()
    runtime.entry_id = first.entry_id
    runtime._operating_mode = "manual"
    _async_remove_stale_sandbox_entities(hass=hass, entry=first, runtime=runtime)
    assert all(registry.async_get(entity_id) is None for entity_id in owned)
    assert all(registry.async_get(entity_id) is not None for entity_id in foreign)
    assert registry.async_get(manual.entity_id) is not None

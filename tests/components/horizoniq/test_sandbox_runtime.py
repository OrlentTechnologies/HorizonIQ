"""Tests for entry-local virtual-battery runtime ownership."""

from unittest.mock import AsyncMock, MagicMock, patch

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
    assert unsubscribe.call_count == 7
    coordinator.async_resume_from_sandbox.assert_not_awaited()


async def test_failed_mqtt_setup_cleans_up_only_its_runtime(hass) -> None:
    """A subscription failure removes partial setup and resumes its coordinator."""
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
        with pytest.raises(RuntimeError, match="no broker"):
            await runtime.async_enable(hass)

    assert runtime.simulator_enabled is False
    assert unsubscribe.call_count == 5
    coordinator.async_pause_for_sandbox.assert_awaited_once()
    coordinator.async_resume_from_sandbox.assert_awaited_once()


async def test_mqtt_setup_is_coordinator_ordered_and_entry_local(hass) -> None:
    """One unavailable MQTT setup resumes only the affected coordinator."""
    failed, failed_coordinator = _runtime()
    healthy, healthy_coordinator = _runtime(
        "22222222-2222-4222-8222-222222222222"
    )
    healthy_unsubscribers = [MagicMock() for _ in range(7)]
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
        with pytest.raises(
            RuntimeError,
            match="Home Assistant MQTT integration is unavailable",
        ):
            await failed.async_enable(hass)
        await healthy.async_enable(hass)

    assert failed.simulator_enabled is False
    failed_coordinator.async_resume_from_sandbox.assert_awaited_once()
    assert healthy.simulator_enabled is True
    healthy_coordinator.async_resume_from_sandbox.assert_not_awaited()
    assert healthy_subscription_index == 7

    await healthy.async_disable()
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

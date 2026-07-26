"""C1 fault values: validation, persistence, and intentionally absent effects."""
from __future__ import annotations
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import json
import pytest

from custom_components.horizoniq.const import CAPACITY_SOURCE_VIRTUAL_BATTERY, CONF_CAPACITY_SOURCE, CONF_ENVIRONMENT, CONF_REGISTRATION_CONFIG, CONF_REGISTRATION_ID, SANDBOX_ENVIRONMENT
from custom_components.horizoniq.sandbox_runtime import HorizonIQEntryRuntime
from custom_components.horizoniq.simulation.faults import FaultKind, FaultState, activate_fault, advance_fault_duration, clear_all_faults, configure_fault, consume_fault_event, outbound_mqtt_precedence, validate_faults
from custom_components.horizoniq.simulation.models import BatteryState
from custom_components.horizoniq.simulation.topics import (
    VictronCommandKey,
    command_topic,
)

UTC=timezone.utc; NOW=datetime(2026,4,1,tzinfo=UTC)
def _runtime(entry: str, registration: str="11111111-1111-4111-8111-111111111111") -> HorizonIQEntryRuntime:
    coordinator=MagicMock(); coordinator.async_pause_for_sandbox=AsyncMock(); coordinator.async_resume_from_sandbox=AsyncMock()
    runtime=HorizonIQEntryRuntime(coordinator,registration,entry)
    runtime.configure_sandbox({CONF_ENVIRONMENT:SANDBOX_ENVIRONMENT,CONF_CAPACITY_SOURCE:CAPACITY_SOURCE_VIRTUAL_BATTERY,CONF_REGISTRATION_ID:registration,CONF_REGISTRATION_CONFIG:{"ChargeEfficiency":.95,"DischargeEfficiency":.9,"EquipmentProfile":{"BatteryCapacityWh":10000,"MinimumCapacityPercentage":.2,"MaximumBatteryChargePowerWatts":2000,"MaximumBatteryDischargePowerWatts":2000}}})
    return runtime

@pytest.mark.parametrize("kind",list(FaultKind))
def test_every_fault_kind_is_bounded_and_immutable(kind: FaultKind) -> None:
    kwargs={"kind":kind,"activation_utc":NOW}
    if kind in {FaultKind.STALE_TELEMETRY,FaultKind.MQTT_DISCONNECT}: kwargs["remaining_duration_seconds"]=1
    else:
        kwargs["remaining_count"]=1
        if kind is FaultKind.DELAY_MQTT: kwargs["settings"]={"delay_seconds":.1}
    fault=configure_fault(**kwargs)
    active=activate_fault(fault,NOW)
    assert fault.state is FaultState.PENDING and active.state is FaultState.ACTIVE
    next_fault=advance_fault_duration(active,1) if active.remaining_duration_seconds is not None else consume_fault_event(active)
    assert next_fault.state is FaultState.EXHAUSTED

def test_fault_validation_limits_precedence_and_unknown_data() -> None:
    with pytest.raises(ValueError): configure_fault(kind=FaultKind.DROP_MQTT,activation_utc=NOW,remaining_count=True)
    with pytest.raises(ValueError): configure_fault(kind=FaultKind.MALFORMED_TELEMETRY,activation_utc=NOW,remaining_count=11)
    with pytest.raises(ValueError): configure_fault(kind=FaultKind.DELAY_MQTT,activation_utc=NOW,remaining_count=1,settings={"delay_seconds":61})
    with pytest.raises(ValueError): configure_fault(kind=FaultKind.STALE_TELEMETRY,activation_utc=NOW,remaining_duration_seconds=901)
    faults=[configure_fault(kind=FaultKind.DROP_MQTT,activation_utc=NOW,remaining_count=1) for _ in range(2)]
    with pytest.raises(ValueError): validate_faults([item.to_dict() for item in faults])
    raw=faults[0].to_dict(); raw["unknown"]=1
    with pytest.raises(ValueError): validate_faults([raw])
    assert outbound_mqtt_precedence()==(FaultKind.MQTT_DISCONNECT,FaultKind.DROP_MQTT,FaultKind.DELAY_MQTT,FaultKind.MALFORMED_TELEMETRY)
    assert clear_all_faults((activate_fault(faults[0],NOW),))[0].state is FaultState.CLEARED

async def test_fault_runtime_store_snapshot_and_no_effects(hass) -> None:
    runtime=_runtime("fault-a"); other=_runtime("fault-b","22222222-2222-4222-8222-222222222222")
    await runtime.async_restore_storage(hass); await other.async_restore_storage(hass)
    fault=await runtime.async_configure_fault(kind=FaultKind.DROP_MQTT,activation_utc=runtime.virtual_time_utc,remaining_count=2)
    await runtime.async_activate_fault(fault.fault_id)
    assert runtime.active_fault_diagnostics==("drop_mqtt: active",) and other.list_faults()==()
    await runtime.async_save_snapshot("faults")
    await runtime.async_clear_fault(fault.fault_id)
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",new=AsyncMock()) as publish:
        await runtime.async_restore_snapshot("faults")
    publish.assert_not_awaited(); assert runtime.list_faults()[0].state is FaultState.ACTIVE
    await runtime.async_checkpoint(immediate=True)
    stored=runtime._storage_record(); serialized=json.dumps(stored).lower()
    for forbidden in ("token","broker","actual","outcome","payload","exception"): assert forbidden not in serialized
    restored=_runtime("fault-a")
    await restored.async_restore_storage(hass)
    assert restored.list_faults() and restored.list_faults()[0].remaining_count==2, restored.storage_diagnostic

async def test_outbound_faults_are_scoped_fifo_and_effect_free_outside_publication(hass) -> None:
    """C2A touches only this runtime's generated sandbox outbound messages."""
    runtime=_runtime("fault-outbound"); other=_runtime("fault-other","33333333-3333-4333-8333-333333333333")
    for item in (runtime,other):
        await item.async_restore_storage(hass); item._hass=hass; item.simulator_enabled=True
    drop=await runtime.async_configure_fault(kind=FaultKind.DROP_MQTT,activation_utc=runtime.virtual_time_utc,remaining_count=3)
    await runtime.async_activate_fault(drop.fault_id)
    topic=f"horizoniq/sandbox/{runtime.pretend_gx_id}/commands/status"
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",new=AsyncMock()) as publish:
        assert not await runtime._async_publish_outbound(topic,"{}")
        assert (await runtime._async_publish_outbound(topic,"{}"))
    publish.assert_awaited_once()
    assert runtime.list_faults()[0].state is FaultState.EXHAUSTED and other.list_faults()==()

    delay=await runtime.async_configure_fault(kind=FaultKind.DELAY_MQTT,activation_utc=runtime.virtual_time_utc,remaining_count=4,settings={"delay_seconds":.1})
    await runtime.async_activate_fault(delay.fault_id)
    runtime._discard_delayed_outbound()
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",new=AsyncMock()) as publish:
        await runtime._async_publish_outbound(topic,'{"one":1}')
        await runtime._async_publish_outbound(topic,'{"two":2}')
        await runtime._async_flush_delayed_outbound(); await runtime._async_flush_delayed_outbound()
    assert [call.args[2] for call in publish.await_args_list]==['{"one":1}','{"two":2}']
    with pytest.raises(ValueError): await runtime._async_publish_outbound("victron/N/production-gx/x","{}")

async def test_telemetry_disconnect_and_cleanup_faults(hass) -> None:
    """Stale/malformed apply only N telemetry; disconnect blocks late command callbacks."""
    runtime=_runtime("fault-telemetry"); await runtime.async_restore_storage(hass); runtime._hass=hass; runtime.simulator_enabled=True
    runtime._state=runtime._state; runtime._config=runtime._config
    stale=await runtime.async_configure_fault(kind=FaultKind.STALE_TELEMETRY,activation_utc=runtime.virtual_time_utc,remaining_duration_seconds=1)
    await runtime.async_activate_fault(stale.fault_id)
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",new=AsyncMock()) as publish:
        await runtime._async_publish_telemetry_snapshot()
    publish.assert_not_awaited()
    await runtime.async_clear_fault(stale.fault_id)
    malformed=await runtime.async_configure_fault(kind=FaultKind.MALFORMED_TELEMETRY,activation_utc=runtime.virtual_time_utc,remaining_count=1)
    await runtime.async_activate_fault(malformed.fault_id)
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",new=AsyncMock()) as publish:
        await runtime._async_publish_telemetry_snapshot()
    assert any('["invalid"]' in call.args[2] for call in publish.await_args_list)
    disconnect=await runtime.async_configure_fault(kind=FaultKind.MQTT_DISCONNECT,activation_utc=runtime.virtual_time_utc,remaining_duration_seconds=1)
    await runtime.async_activate_fault(disconnect.fault_id)
    await runtime._async_handle_victron_write(MagicMock(payload='{"value":1}',topic=command_topic(runtime.pretend_gx_id or "",VictronCommandKey.HUB4_MODE)))
    assert runtime._command is not None and runtime._command.mode.value=="self_consumption"
    generation=runtime._fault_timer_generations[disconnect.fault_id]
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",new=AsyncMock(return_value=lambda: None)):
        await runtime._async_expire_fault(disconnect.fault_id,1,generation)
        await hass.async_block_till_done()
    assert runtime._mqtt_fault_disconnected is False
    assert next(item for item in runtime.list_faults() if item.fault_id==disconnect.fault_id).state is FaultState.EXHAUSTED
    await runtime.async_disable()

async def test_replay_command_and_runtime_restart_faults_are_local(hass) -> None:
    """C2B consumes only valid owning operations and preserves unrelated state."""
    runtime=_runtime("fault-c2b"); await runtime.async_restore_storage(hass)
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",new=AsyncMock(return_value=lambda: None)):
        await runtime.async_enable(hass)
    replay=await runtime.async_configure_fault(kind=FaultKind.REPLAY_API_FAILURE,activation_utc=runtime.virtual_time_utc,remaining_count=1)
    await runtime.async_activate_fault(replay.fault_id)
    # No selected profile: the fault remains local and cannot fabricate a backend request.
    with pytest.raises(ValueError): await runtime.async_start_replay_session()
    command=await runtime.async_configure_fault(kind=FaultKind.REJECT_COMMAND,activation_utc=runtime.virtual_time_utc,remaining_count=1)
    await runtime.async_activate_fault(command.fault_id)
    before=runtime._command
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish",new=AsyncMock()) as publish:
        await runtime._async_handle_victron_write(MagicMock(payload='{"value":500}',topic=command_topic(runtime.pretend_gx_id or "",VictronCommandKey.AC_POWER_SETPOINT)))
    assert runtime._command==before
    assert next(item for item in runtime.list_faults() if item.fault_id==command.fault_id).state is FaultState.ACTIVE
    publish.assert_not_awaited()
    restart=await runtime.async_configure_fault(kind=FaultKind.RUNTIME_RESTART,activation_utc=runtime.virtual_time_utc,remaining_count=1)
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",new=AsyncMock(return_value=lambda: None)):
        await runtime.async_activate_fault(restart.fault_id)
    assert next(item for item in runtime.list_faults() if item.fault_id==restart.fault_id).state is FaultState.EXHAUSTED
    await runtime.async_disable()

async def test_fault_corruption_fails_closed(hass) -> None:
    """Invalid Store faults cannot apply a snapshot."""
    runtime=_runtime("fault-review"); await runtime.async_restore_storage(hass)
    runtime._state=BatteryState(3000); await runtime.async_checkpoint(immediate=True)
    assert runtime._storage is not None
    record=runtime._storage_record(); record["faults"]=[{"bad":True}]
    await runtime._storage.async_save(record)
    recovered=_runtime("fault-review"); await recovered.async_restore_storage(hass)
    assert recovered.energy_wh==5000 and recovered.simulator_enabled is False and recovered.storage_diagnostic

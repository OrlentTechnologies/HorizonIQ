"""Retired priority inputs cross the real forecast and entry boundaries safely."""

import asyncio
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
import json
import logging
from unittest.mock import AsyncMock, patch

import pytest
from freezegun import freeze_time
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, State
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.horizoniq.const import CONF_HASH, SANDBOX_ENVIRONMENT
from custom_components.horizoniq.coordinator import HorizonIQCoordinator
from custom_components.horizoniq.coordinator_helpers import (
    build_snapshot,
    normalize_direct_forecast,
    normalize_forecast,
    normalize_periods,
)
from custom_components.horizoniq.direct_control import (
    DirectForecastRejection,
    parse_live_command,
    validate_live_forecast,
)
from custom_components.horizoniq.forecast_schema5 import (
    Schema5ForecastError,
    parse_schema5_forecast,
)
from custom_components.horizoniq.models import ForecastFreshness, ForecastPeriod
from custom_components.horizoniq.sensors.diagnostic import ForecastDetailSensor
from custom_components.horizoniq.simulation.models import CommandStatus, OperatingMode

from .test_forecast_schema5 import _schema8_payload, _wire_alias
from .test_reserve_grid_hold import CONFIG, NOW, _payload
from .test_reserve_grid_hold_runtime import START, _entity_id, _setup, _wire


ALIASES = ("actionPriority", "ActionPriority", "action_priority")
LEGACY_VALUES = (
    pytest.param("absent", id="absent"),
    pytest.param(None, id="null"),
    pytest.param(1, id="one"),
    pytest.param(99, id="other-number"),
    pytest.param(True, id="true"),
    pytest.param(False, id="false"),
    pytest.param("discarded-priority-sentinel", id="string"),
    pytest.param(["discarded-priority-sentinel"], id="list"),
    pytest.param({"Authorization": "discarded-priority-sentinel"}, id="object"),
)


def _supported_payload(schema: int, action: str = "charge_required") -> dict[str, object]:
    payload = _payload(action, schema=schema)
    return _schema8_payload(payload) if schema == 8 else payload


def _assert_priority_free(value: object) -> None:
    rendered = repr(value)
    for alias in ALIASES:
        assert alias not in rendered
    assert "discarded-priority-sentinel" not in rendered


@pytest.mark.parametrize("schema", (5, 6, 7, 8))
@pytest.mark.parametrize("action", ("charge_required", "import_for_export", "use_grid"))
@pytest.mark.parametrize("style", ("camel", "pascal", "snake"))
def test_priority_free_forecast_round_trips_and_executes(schema, action, style) -> None:
    payload = _supported_payload(schema, action)
    wire = payload if style == "camel" else _wire_alias(payload, style)
    original = deepcopy(wire)
    parsed = parse_schema5_forecast(wire)
    assert parsed is not None
    assert parse_schema5_forecast(parsed.to_dict()) == parsed
    snapshot = build_snapshot(wire)
    assert snapshot.schema5_forecast == parsed
    assert snapshot.direct_forecast is not None
    command = parse_live_command(snapshot.direct_forecast, now_utc=NOW, config=CONFIG)
    assert command == parse_live_command(
        build_snapshot(payload).direct_forecast, now_utc=NOW, config=CONFIG
    )
    assert command.action == action
    assert command.command_id == payload["periods"][0]["commandId"]
    assert command.command.expires_at_utc == NOW + timedelta(minutes=30)
    assert command.command.mode is (
        OperatingMode.GRID_PRESERVATION if action == "use_grid"
        else OperatingMode.GRID_SETPOINT
    )
    _assert_priority_free(parsed.to_dict())
    _assert_priority_free(asdict(snapshot))
    assert "action_priority" not in ForecastPeriod.__annotations__
    assert wire == original


@pytest.mark.parametrize("schema", (5, 6, 7, 8))
@pytest.mark.parametrize("alias", ALIASES)
@pytest.mark.parametrize("value", LEGACY_VALUES)
def test_legacy_priority_aliases_and_values_are_discarded(schema, alias, value, caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="custom_components.horizoniq")
    payload = _supported_payload(schema)
    baseline = build_snapshot(payload)
    ordinary = deepcopy(payload)
    ordinary.pop("schemaVersion")
    ordinary_baseline = normalize_forecast(ordinary)
    periods_baseline = normalize_periods(payload)
    if value != "absent":
        payload["periods"][0][alias] = deepcopy(value)
        ordinary["periods"][0][alias] = deepcopy(value)
    original = deepcopy(payload)
    snapshot = build_snapshot(payload)
    assert snapshot == baseline
    assert normalize_forecast(ordinary) == ordinary_baseline
    assert normalize_periods(payload) == periods_baseline
    assert parse_live_command(snapshot.direct_forecast, now_utc=NOW, config=CONFIG) == (
        parse_live_command(baseline.direct_forecast, now_utc=NOW, config=CONFIG)
    )
    _assert_priority_free(snapshot.schema5_forecast.to_dict())
    _assert_priority_free(asdict(snapshot))
    _assert_priority_free(caplog.text)
    assert payload == original


@pytest.mark.parametrize("schema", (5, 6, 7, 8))
def test_retired_priority_alias_conflicts_are_ignored(schema) -> None:
    payload = _supported_payload(schema, "use_grid")
    baseline = build_snapshot(payload)
    payload["periods"][0].update({
        "actionPriority": None,
        "ActionPriority": {"Authorization": "discarded-priority-sentinel"},
        "action_priority": [True, 99],
    })
    assert build_snapshot(payload) == baseline
    assert normalize_periods(payload) == normalize_periods(baseline.schema5_forecast.to_dict())
    _assert_priority_free(asdict(build_snapshot(payload)))


@pytest.mark.parametrize("fault", (
    "action-alias", "date-alias", "number-alias", "missing-metadata",
    "retained-secret", "invalid-diagnostics", "missing-export", "null-period",
    "missing-periods", "null-periods", "partial-period", "invalid-number",
))
async def test_retained_alias_conflicts_still_reject_atomically(
    hass, mock_config_entry, entry_data, aioclient_mock, caplog, fault,
) -> None:
    caplog.set_level(logging.DEBUG, logger="custom_components.horizoniq")
    hass.states.async_set(entry_data["battery_capacity_sensor"], "4320")
    coordinator = HorizonIQCoordinator(
        hass, mock_config_entry, entry_data["url"], entry_data["api_key"],
        entry_data["battery_capacity_sensor"], SANDBOX_ENVIRONMENT,
    )
    payload = _supported_payload(8)
    payload["hash"] = "accepted-priority-free"
    aioclient_mock.get(coordinator._build_request_url("4320"), json=payload)
    accepted = await coordinator.async_fetch_sandbox_forecast()
    accepted_config = dict(mock_config_entry.data)
    previous = accepted.schema5_forecast.to_dict()
    invalid = deepcopy(payload)
    period = invalid["periods"][0]
    period.update({alias: {"ignored": "discarded-priority-sentinel"} for alias in ALIASES})
    if fault == "action-alias":
        period["executable_action"] = "use_grid"
    elif fault == "date-alias":
        period["Date"] = "2026-07-30T13:00:00Z"
    elif fault == "number-alias":
        period["expected_import"] = 999
    elif fault == "missing-metadata":
        period.pop("commandId")
    elif fault == "retained-secret":
        period["decisionTrace"]["constraints"]["Authorization"] = "retained-secret-sentinel"
    elif fault == "invalid-diagnostics":
        invalid["diagnostics"]["plannedEnergyLedger"]["healthy"] = "invalid-retained-sentinel"
    elif fault == "missing-export":
        period.pop("shouldExport")
    elif fault == "null-period":
        invalid["periods"].append(None)
    elif fault == "missing-periods":
        invalid.pop("periods")
    elif fault == "null-periods":
        invalid["periods"] = None
    elif fault == "partial-period":
        period.pop("expectedNetValue")
    elif fault == "invalid-number":
        period["expectedImport"] = True
    with pytest.raises(Schema5ForecastError):
        build_snapshot(invalid)
    aioclient_mock.clear_requests()
    aioclient_mock.get(coordinator._build_request_url("4320"), json=invalid)
    with pytest.raises(UpdateFailed):
        await coordinator.async_fetch_sandbox_forecast()
    assert coordinator.data.forecast_freshness is ForecastFreshness.STALE
    assert coordinator.data.direct_forecast is None
    assert coordinator.data.schema5_forecast.to_dict()["periods"] == previous["periods"]
    assert mock_config_entry.data == accepted_config
    _assert_priority_free(coordinator.data.schema5_forecast.to_dict())
    for sentinel in ("retained-secret-sentinel", "invalid-retained-sentinel", "discarded-priority-sentinel"):
        assert sentinel not in caplog.text


@pytest.mark.parametrize("schema", (5, 6, 7, 8))
@pytest.mark.parametrize("field", ("commandId", "issuedAtUtc", "expiresAtUtc"))
@pytest.mark.parametrize("value", ("missing", None, "", True, "malformed"))
def test_priority_removal_preserves_command_metadata_and_expiry_guards(schema, field, value) -> None:
    payload = _supported_payload(schema)
    period = payload["periods"][0]
    if value == "missing":
        period.pop(field)
    else:
        period[field] = value
    if value is None or (field == "commandId" and value == "malformed"):
        rejected = validate_live_forecast(build_snapshot(payload).direct_forecast, now_utc=NOW, config=CONFIG)
        assert rejected.rejection is DirectForecastRejection.COMMAND_METADATA_INVALID
    else:
        with pytest.raises(Schema5ForecastError):
            build_snapshot(payload)
    valid = _supported_payload(schema)
    for field_name, timestamp in (
        ("issuedAtUtc", "2026-07-30T12:00:01Z"),
        ("expiresAtUtc", "2026-07-30T12:00:00Z"),
        ("expiresAtUtc", "2026-07-30T12:29:00Z"),
        ("expiresAtUtc", "2026-07-30T12:31:00Z"),
    ):
        invalid = deepcopy(valid)
        invalid["periods"][0][field_name] = timestamp
        assert validate_live_forecast(
            build_snapshot(invalid).direct_forecast, now_utc=NOW, config=CONFIG
        ).rejection is DirectForecastRejection.COMMAND_WINDOW_INVALID
    forecast = build_snapshot(valid).direct_forecast
    assert validate_live_forecast(
        forecast, now_utc=NOW + timedelta(minutes=30), config=CONFIG
    ).rejection is DirectForecastRejection.CURRENT_PERIOD_MISSING


@pytest.mark.parametrize("schema", (5, 6, 7, 8))
def test_priority_removal_preserves_none_and_unsupported_action_paths(schema) -> None:
    payload = _supported_payload(schema, "none")
    period = payload["periods"][0]
    for field in ("commandId", "issuedAtUtc", "expiresAtUtc"):
        period[field] = None
    # A recommendation alone cannot grant live control authority.
    period["recommendedAction"] = "charge_required"
    command = parse_live_command(build_snapshot(payload).direct_forecast, now_utc=NOW, config=CONFIG)
    assert command.action == "none"
    assert command.command_id is None
    assert command.command.mode is OperatingMode.SELF_CONSUMPTION
    for action in ("export_for_profit", "export_for_solar_headroom", "unknown"):
        period["executableAction"] = action
        assert validate_live_forecast(
            build_snapshot(payload).direct_forecast, now_utc=NOW, config=CONFIG
        ).rejection is DirectForecastRejection.ACTION_INVALID
    payload["schemaVersion"] = 9
    with pytest.raises(Schema5ForecastError, match="Unsupported forecast schemaVersion"):
        build_snapshot(payload)
    for missing in (None, {}, {"Forecast": None}, {"Forecast": {}}, {"periods": None}):
        assert build_snapshot(missing).direct_forecast is None
    empty = _supported_payload(schema)
    empty["periods"] = []
    snapshot = build_snapshot(empty)
    assert snapshot.schema5_forecast.periods == ()
    assert snapshot.direct_forecast is None
    assert validate_live_forecast(
        snapshot.direct_forecast, now_utc=NOW, config=CONFIG
    ).rejection is DirectForecastRejection.MODEL_UNAVAILABLE


@pytest.mark.parametrize("action", ("charge_required", "use_grid", "none"))
@pytest.mark.parametrize("value", LEGACY_VALUES)
def test_old_normalised_priority_is_not_restored_into_direct_model(action, value) -> None:
    payload = _supported_payload(8, action)
    if action == "none":
        for key in ("commandId", "issuedAtUtc", "expiresAtUtc"):
            payload["periods"][0][key] = None
    normalized = normalize_forecast(payload)
    baseline = normalize_direct_forecast(normalized)
    assert baseline is not None
    legacy = deepcopy(normalized)
    if value != "absent":
        for alias in ALIASES:
            legacy["periods"][0][alias] = deepcopy(value)
    original = deepcopy(legacy)
    restored = normalize_direct_forecast(legacy)
    assert restored == baseline
    assert legacy == original
    assert normalize_periods(legacy) == normalize_periods(normalized)
    _assert_priority_free(asdict(restored))
    if action == "none":
        assert restored.periods[0].command_id is None
        assert restored.periods[0].issued_at_utc is None
        assert restored.periods[0].expires_at_utc is None
    assert parse_live_command(restored, now_utc=NOW, config=CONFIG) == (
        parse_live_command(baseline, now_utc=NOW, config=CONFIG)
    )


async def test_priority_free_refresh_keeps_runtime_state_entry_local(hass, aioclient_mock, caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="custom_components.horizoniq")
    with (
        freeze_time(START),
        patch("custom_components.horizoniq._ensure_local_docs", AsyncMock()),
        patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_publish", AsyncMock()),
        patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe", AsyncMock(return_value=lambda: None)),
        patch("custom_components.horizoniq.sandbox_runtime._LOOP_INTERVAL_SECONDS", 100000),
    ):
        entries = []
        runtimes = []
        payloads = []
        for index in range(2):
            entry, runtime = await _setup(hass, aioclient_mock, f"priority-free-{index}")
            entries.append(entry)
            runtimes.append(runtime)
            runtime._live_forecast_now = lambda: START
            payload = _wire(START, energy_wh=runtime.energy_wh)
            payload["hash"] = f"stable-priority-free-{index}"
            payloads.append(payload)
            aioclient_mock.clear_requests()
            aioclient_mock.get(runtime.coordinator._build_request_url(runtime.current_capacity()), json=payload)
            await runtime._async_refresh_direct_forecast()
            await hass.async_block_till_done()
            assert runtime._command.mode is OperatingMode.GRID_PRESERVATION
            assert hass.states.get(_entity_id(hass, entry.entry_id, "use_grid", "binary_sensor")).state == "on"
            _assert_priority_free(asdict(runtime.coordinator.data))
        first, second = runtimes
        first_snapshot = first.coordinator.data
        other_snapshot = second.coordinator.data
        first_command = first._command
        other_command = second._command
        first_config = dict(entries[0].data)
        ids = first._accepted_command_ids
        # An equal-hash response still refreshes retained diagnostics.
        updated = deepcopy(payloads[0])
        updated["hash"] = first_config[CONF_HASH]
        updated["periods"][0]["decisionTrace"]["explanation"] = "Refreshed retained diagnostics."
        updated["periods"][0]["actionPriority"] = {"Authorization": "discarded-priority-sentinel"}
        aioclient_mock.clear_requests()
        aioclient_mock.get(first.coordinator._build_request_url(first.current_capacity()), json=updated)
        await first._async_refresh_direct_forecast()
        await hass.async_block_till_done()
        refreshed = first.coordinator.data
        assert refreshed.publication_sequence > first_snapshot.publication_sequence
        assert refreshed.schema5_forecast.periods[0].decision_trace.explanation == "Refreshed retained diagnostics."
        assert entries[0].data == first_config
        assert first._accepted_command_ids == ids
        # Replaying an already-consumed publication cannot apply another command.
        current_command = first._command
        await first._async_stage_forecast_snapshot(refreshed)
        assert first._command is current_command
        assert first._command == first_command
        assert second.coordinator.data is other_snapshot
        assert second._command is other_command
        # A retained alias conflict cannot partially replace a running plan.
        conflicting = deepcopy(updated)
        conflicting["periods"][0]["expected_import"] = 999
        aioclient_mock.clear_requests()
        aioclient_mock.get(
            first.coordinator._build_request_url(first.current_capacity()),
            json=conflicting,
        )
        await first._async_refresh_direct_forecast()
        await hass.async_block_till_done()
        assert first.coordinator.data.forecast_freshness is ForecastFreshness.STALE
        assert first.coordinator.data.direct_forecast is None
        assert first.last_command_status is CommandStatus.FALLBACK_STALE
        assert first._command.mode is OperatingMode.SELF_CONSUMPTION
        assert first._accepted_command_ids == ids
        assert entries[0].data == first_config
        assert second.coordinator.data is other_snapshot
        assert second._command is other_command
        # The same accepted response can recover after a rejected replacement.
        aioclient_mock.clear_requests()
        aioclient_mock.get(
            first.coordinator._build_request_url(first.current_capacity()),
            json=updated,
        )
        await first._async_refresh_direct_forecast()
        await hass.async_block_till_done()
        assert first.coordinator.data.forecast_freshness is ForecastFreshness.FRESH
        assert first._command == first_command
        aioclient_mock.clear_requests()
        aioclient_mock.get(first.coordinator._build_request_url(first.current_capacity()), exc=asyncio.TimeoutError())
        await first._async_refresh_direct_forecast()
        await hass.async_block_till_done()
        assert first.coordinator.data.forecast_freshness is ForecastFreshness.STALE
        assert first.coordinator.data.direct_forecast is None
        assert first.coordinator.data.schema5_forecast.to_dict()["periods"] == refreshed.schema5_forecast.to_dict()["periods"]
        assert first.last_command_status is CommandStatus.FALLBACK_STALE
        assert first._command.mode is OperatingMode.SELF_CONSUMPTION
        assert second.coordinator.data is other_snapshot
        assert second._command is other_command
        assert second.coordinator.data.forecast_freshness is ForecastFreshness.FRESH
        assert hass.states.get(_entity_id(hass, entries[0].entry_id, "use_grid", "binary_sensor")).state == "unknown"
        assert hass.states.get(_entity_id(hass, entries[1].entry_id, "use_grid", "binary_sensor")).state == "on"
        attributes = ForecastDetailSensor(first.coordinator, entries[0].entry_id, "Sandbox").extra_state_attributes
        _assert_priority_free(attributes)
        from homeassistant.components.recorder.db_schema import StateAttributes

        entity = ForecastDetailSensor(first.coordinator, entries[0].entry_id, "Sandbox")
        state = State(
            "sensor.priority_free_diagnostics", "1", attributes,
            state_info={"unrecorded_attributes": entity._unrecorded_attributes},
        )
        event = Event(EVENT_STATE_CHANGED, {
            "entity_id": state.entity_id, "old_state": None, "new_state": state,
        })
        recorded = StateAttributes.shared_attrs_bytes_from_event(event, dialect=None)
        assert b'"forecast"' not in recorded
        _assert_priority_free(recorded)
        _assert_priority_free(caplog.text)
        assert "diagnostics" not in json.dumps(dict(entries[0].data))
        for entry in entries:
            assert await hass.config_entries.async_unload(entry.entry_id)

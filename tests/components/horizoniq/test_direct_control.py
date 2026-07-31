"""Direct Home Assistant sandbox-control contract tests."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from custom_components.horizoniq.direct_control import (
    parse_live_command,
    parse_replay_command,
)
from custom_components.horizoniq.coordinator_helpers import build_snapshot
from custom_components.horizoniq.models import Forecast
from custom_components.horizoniq.sandbox_runtime import HorizonIQEntryRuntime
from custom_components.horizoniq.simulation.clock import ClockRate, VirtualClock
from custom_components.horizoniq.simulation.models import (
    BatteryConfig,
    BatteryState,
    CommandStatus,
    OperatingMode,
)


NOW = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
CONFIG = BatteryConfig(10_000, 2_000, 2_000, 2_000)
FIXTURE = Path(__file__).with_name("fixtures") / "direct_schema5_forecast.json"


def _fixture_payload() -> dict[str, object]:
    """Load a complete server-shaped schema-5 Forecast_Get response."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _coordinator_forecast(payload: dict[str, object]) -> Forecast | None:
    """Use the production raw API → coordinator model boundary."""
    return build_snapshot(payload).direct_forecast


def _profile(*, exports: bool = False) -> dict[str, object]:
    return {
        "id": "sandbox-profile", "version": 1, "source": "registration",
        "displayName": "Sandbox profile", "batteryCapacityWh": 10_000,
        "minimumCapacityPercentage": 0.2,
        "maximumBatteryChargePowerWatts": 3_000,
        "maximumBatteryDischargePowerWatts": 3_000,
        "inverterMaximumChargePowerWatts": 3_000,
        "inverterMaximumDischargePowerWatts": 3_000,
        "maximumGridImportPowerWatts": 3_000,
        "maximumGridExportPowerWatts": 3_000,
        "controlAdapterId": "home-assistant-virtual-battery",
        "supportedControl": {
            "requiredCharging": True, "useGrid": True, "importForExport": True,
            "profitableExport": exports, "solarHeadroomExport": exports,
        },
        "productionExportEnabled": exports,
        "safeFallbackId": "self-consumption-only",
    }


def _payload(*, action: str, plan_kind: str = "live", expires: datetime | None = None) -> dict[str, object]:
    """Derive one valid contract variation from the complete schema-5 fixture."""
    end = expires or NOW + timedelta(minutes=30)
    payload = _fixture_payload()
    period = dict(payload["periods"][0])
    trace = dict(period["decisionTrace"])
    period.update(
        {
            "date": NOW.isoformat().replace("+00:00", "Z"),
            "recommendedAction": action,
            "executableAction": action,
            "commandId": str(uuid4()),
            "issuedAtUtc": NOW.isoformat().replace("+00:00", "Z"),
            "expiresAtUtc": end.isoformat().replace("+00:00", "Z"),
            "actionPriority": {"charge_required": 1, "use_grid": 4, "import_for_export": 5}.get(action, 0),
        }
    )
    trace["selectedAction"] = action
    period["decisionTrace"] = trace
    payload.update(
        {
            "planId": str(uuid4()),
            "planKind": plan_kind,
            "createdAtUtc": NOW.isoformat().replace("+00:00", "Z"),
            "effectiveAtUtc": NOW.isoformat().replace("+00:00", "Z"),
            "equipmentProfile": _profile(),
            "periods": [period],
        }
    )
    return payload


def test_live_charge_and_import_are_clamped_to_virtual_limits() -> None:
    command = parse_live_command(
        _coordinator_forecast(_payload(action="charge_required")),
        now_utc=NOW,
        config=CONFIG,
    )
    assert command.command.mode is OperatingMode.GRID_SETPOINT
    assert command.command.requested_grid_power_w == 2_000


def test_complete_schema5_fixture_normalizes_and_drives_direct_charge() -> None:
    """All camel-case schema-5 fields survive coordinator normalization."""
    from custom_components.horizoniq.coordinator_helpers import normalize_forecast

    normalized = normalize_forecast(_fixture_payload())
    assert normalized["schema_version"] == 5
    assert normalized["plan_id"] == "a2b2eb79-6a79-469f-ac10-df23a9532685"
    assert normalized["created_at_utc"] == "2026-07-30T11:59:58Z"
    assert normalized["equipment_profile"]["controlAdapterId"] == (
        "home-assistant-virtual-battery"
    )
    assert normalized["periods"][0]["executable_action"] == "charge_required"
    assert normalized["periods"][0]["decision_trace"]["reasonCode"] == (
        "normal_charge_priority"
    )

    command = parse_live_command(
        _coordinator_forecast(_fixture_payload()), now_utc=NOW, config=CONFIG
    )
    assert command.command.mode is OperatingMode.GRID_SETPOINT
    assert command.command.requested_grid_power_w == 2_000


def test_live_none_with_null_command_metadata_is_safe_self_consumption() -> None:
    """Keep the complete contract's null command metadata non-commanding."""
    payload = _fixture_payload()
    period = payload["periods"][1]
    assert isinstance(period, dict)
    assert period["commandId"] is None
    assert period["issuedAtUtc"] is None
    assert period["expiresAtUtc"] is None
    command = parse_live_command(
        _coordinator_forecast(payload),
        now_utc=NOW + timedelta(minutes=30),
        config=CONFIG,
    )
    assert command.action == "none"
    assert command.command.mode is OperatingMode.SELF_CONSUMPTION
    assert command.command_id is None


@pytest.mark.asyncio
async def test_runtime_marks_a_valid_none_forecast_healthy() -> None:
    """A no-op response is a successful direct forecast, not fallback_missing."""

    class FixtureCoordinator:
        async def async_fetch_sandbox_forecast(self) -> Forecast | None:
            return _coordinator_forecast(_fixture_payload())

    runtime = HorizonIQEntryRuntime(FixtureCoordinator(), "registration-id")
    runtime.simulator_enabled = True
    runtime._config = CONFIG
    runtime._clock = VirtualClock(NOW + timedelta(minutes=30))
    runtime._live_forecast_now = lambda: NOW + timedelta(minutes=30)

    await runtime._async_refresh_direct_forecast()

    assert runtime.forecast_health == "healthy"
    assert runtime.last_command_status.value == "no_action"
    assert runtime.last_command_reason == (
        "No executable action; self-consumption applied."
    )
    assert runtime._command is not None
    assert runtime._command.mode is OperatingMode.SELF_CONSUMPTION


@pytest.mark.asyncio
async def test_raw_api_to_coordinator_model_to_runtime_boundary_for_no_action() -> None:
    """Direct control rejects raw JSON and accepts only its typed coordinator model."""
    raw = _fixture_payload()
    with pytest.raises(ValueError):
        parse_live_command(raw, now_utc=NOW + timedelta(minutes=30), config=CONFIG)

    forecast = _coordinator_forecast(raw)
    assert isinstance(forecast, Forecast)
    assert forecast.equipment_profile.control_adapter_id == (
        "home-assistant-virtual-battery"
    )
    assert forecast.equipment_profile.safe_fallback_id == "self-consumption-only"
    assert forecast.periods[1].executable_action == "none"
    assert forecast.periods[1].command_id is None

    command = parse_live_command(
        forecast, now_utc=NOW + timedelta(minutes=30), config=CONFIG
    )
    assert command.action == "none"
    assert command.command.mode is OperatingMode.SELF_CONSUMPTION

    class BoundaryCoordinator:
        async def async_fetch_sandbox_forecast(self) -> Forecast:
            return forecast

    runtime = HorizonIQEntryRuntime(BoundaryCoordinator(), "registration-id")
    runtime.simulator_enabled = True
    runtime._config = CONFIG
    runtime._clock = VirtualClock(NOW + timedelta(minutes=30))
    runtime._live_forecast_now = lambda: NOW + timedelta(minutes=30)

    await runtime._async_refresh_direct_forecast()

    assert runtime.forecast_health == "healthy"
    assert runtime.last_command_status.value == "no_action"
    assert runtime._command is not None
    assert runtime._command.mode is OperatingMode.SELF_CONSUMPTION


@pytest.mark.asyncio
async def test_paused_runtime_stages_forecasts_and_reset_reports_awaiting() -> None:
    """Coordinator updates remain direct-control inputs while physics is paused."""

    forecast = _coordinator_forecast(_fixture_payload())
    assert isinstance(forecast, Forecast)

    class TaskHass:
        task: asyncio.Task[None] | None = None

        def async_create_task(self, coroutine: object) -> asyncio.Task[None]:
            assert asyncio.iscoroutine(coroutine)
            self.task = asyncio.create_task(coroutine)
            return self.task

    hass = TaskHass()
    coordinator = SimpleNamespace(data=SimpleNamespace(direct_forecast=forecast))
    runtime = HorizonIQEntryRuntime(coordinator, "registration-id")
    runtime.simulator_enabled = True
    runtime._config = CONFIG
    runtime._state = BatteryState(5_000)
    runtime._clock = VirtualClock(NOW + timedelta(minutes=30), ClockRate.PAUSED)
    runtime._live_forecast_now = lambda: NOW + timedelta(minutes=30)
    runtime._hass = hass

    runtime._on_coordinator_forecast()
    assert hass.task is not None
    await hass.task

    assert runtime.virtual_time_utc == NOW + timedelta(minutes=30)
    assert runtime.energy_wh == 5_000
    assert runtime.forecast_health == "healthy"
    assert runtime.last_command_status is CommandStatus.NO_ACTION
    assert runtime.decision_summary == "No executable action; self-consumption applied."

    runtime.set_clock_rate(ClockRate.X1)
    await runtime._async_stage_direct_forecast(forecast)
    assert runtime.forecast_health == "healthy"
    assert runtime.last_command_status is CommandStatus.NO_ACTION

    runtime.set_clock_rate(ClockRate.PAUSED)
    runtime.reset()
    assert runtime.forecast_health == "awaiting_forecast"
    assert runtime.last_command_status is CommandStatus.AWAITING_FORECAST
    assert runtime.last_command_status not in {
        CommandStatus.FALLBACK_INVALID,
        CommandStatus.FALLBACK_MISSING,
    }


def test_live_advisory_and_expired_actions_are_rejected() -> None:
    with pytest.raises(ValueError):
        parse_live_command(
            _coordinator_forecast(_payload(action="export_for_profit")),
            now_utc=NOW,
            config=CONFIG,
        )
    with pytest.raises(ValueError):
        parse_live_command(
            _coordinator_forecast(_payload(action="charge_required", expires=NOW)),
            now_utc=NOW,
            config=CONFIG,
        )


def test_missing_or_wrong_schema5_fields_are_rejected() -> None:
    payload = _fixture_payload()
    payload["schemaVersion"] = 4
    with pytest.raises(ValueError):
        parse_live_command(_coordinator_forecast(payload), now_utc=NOW, config=CONFIG)

    payload = _fixture_payload()
    del payload["equipmentProfile"]
    with pytest.raises(ValueError):
        parse_live_command(_coordinator_forecast(payload), now_utc=NOW, config=CONFIG)


def test_replay_export_uses_half_hour_power_and_no_command_identity() -> None:
    payload = _payload(action="none", plan_kind="sandbox_replay")
    period = payload["periods"][0]
    assert isinstance(period, dict)
    period.update(
        {
            "simulationAction": "export_for_profit",
            "executableAction": "none",
            "commandId": None,
            "issuedAtUtc": None,
            "expiresAtUtc": None,
            "actionPriority": None,
            "expectedExport": 1.0,
        }
    )
    payload["equipmentProfile"] = _profile(exports=True)
    command = parse_replay_command(payload, virtual_now_utc=NOW, config=CONFIG)
    assert command.command.requested_grid_power_w == -2_000
    assert command.command_id is None

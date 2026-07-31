"""Schema-5 virtual-battery forecast diagnostics regression coverage."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, State

from custom_components.horizoniq.forecast_schema5 import (
    REASON_CODES,
    Schema5ForecastError,
    parse_schema5_forecast,
)
from custom_components.horizoniq.coordinator import HorizonIQCoordinator
from custom_components.horizoniq.coordinator_helpers import build_snapshot
from custom_components.horizoniq.sensors.import_for_export import (
    ImportForExportDecisionSensor,
)
from custom_components.horizoniq.sensors.diagnostic import ForecastDetailSensor


FIXTURE = Path(__file__).with_name("fixtures") / "direct_schema5_forecast.json"


def _payload() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_complete_schema5_contract_survives_strict_normalization() -> None:
    """Every documented plan, period, trace, economics, and ledger field survives."""
    payload = _payload()
    forecast = parse_schema5_forecast(payload)

    assert forecast is not None
    normalized = forecast.to_dict()
    assert normalized["schemaVersion"] == 5
    for field in (
        "planId",
        "planKind",
        "importForExportEnabled",
        "importForExportAdvisoryEnabled",
        "createdAtUtc",
        "effectiveAtUtc",
        "economicsAssumptions",
        "plannedEnergyLedger",
        "equipmentProfile",
        "currentCapacity",
        "minCapacity",
        "targetCapacity",
        "lowPrice",
        "mediumPrice",
        "batteryManagementSystemState",
        "shouldImport",
        "shouldUseGrid",
        "forecastCadenceMinutes",
        "totalCost",
        "chargingCost",
        "saving",
    ):
        assert normalized[field] == payload[field]
    period = normalized["periods"][0]
    source_period = payload["periods"][0]
    for field in (
        "period",
        "date",
        "price",
        "shouldImport",
        "shouldUseGrid",
        "recommendedAction",
        "simulationAction",
        "executableAction",
        "commandId",
        "issuedAtUtc",
        "expiresAtUtc",
        "actionPriority",
        "expectedImport",
        "expectedExport",
        "expectedStartSoc",
        "expectedEndSoc",
        "expectedCost",
        "expectedRevenue",
        "expectedNetValue",
        "amount",
        "imported",
        "exported",
        "estimatedGeneration",
        "used",
        "battery",
        "batteryManagementSystemState",
    ):
        assert period[field] == source_period[field]
    assert period["decisionTrace"] == source_period["decisionTrace"]


def test_schema5_contract_rejects_incomplete_period_atomically() -> None:
    """A missing required field never produces a partial normalized horizon."""
    payload = _payload()
    del payload["periods"][0]["expectedNetValue"]

    with pytest.raises(Schema5ForecastError, match="expectedNetValue"):
        parse_schema5_forecast(payload)


def test_schema5_contract_rejects_transport_secrets_in_diagnostics_objects() -> None:
    """The memory-only horizon cannot accept registration or transport secrets."""
    payload = _payload()
    payload["economicsAssumptions"]["registrationData"] = "not-for-ha"

    with pytest.raises(Schema5ForecastError, match="safe JSON object"):
        parse_schema5_forecast(payload)


def test_malformed_schema5_refresh_keeps_the_last_complete_plan_as_stale() -> None:
    """A failed replacement leaves the previous entry-local horizon intact."""
    valid = _payload()
    snapshot = build_snapshot(valid)
    assert snapshot.schema5_forecast is not None
    coordinator = object.__new__(HorizonIQCoordinator)
    coordinator._latest_snapshot = snapshot
    coordinator._last_valid_schema5_forecast = snapshot.schema5_forecast

    invalid = deepcopy(valid)
    del invalid["periods"][0]["expectedNetValue"]
    stale = coordinator._build_snapshot_or_stale(invalid)

    assert stale.schema5_forecast is not None
    assert stale.schema5_forecast.stale is True
    assert stale.schema5_forecast.plan_id == snapshot.schema5_forecast.plan_id
    assert stale.schema5_forecast.to_dict()["periods"] == snapshot.schema5_forecast.to_dict()[
        "periods"
    ]


def test_three_coordinators_keep_schema5_diagnostics_entry_local() -> None:
    """A rejected update for one entry cannot stale or replace another entry's plan."""
    coordinators = []
    for plan_id in ("plan-a", "plan-b", "plan-c"):
        payload = _payload()
        payload["planId"] = plan_id
        snapshot = build_snapshot(payload)
        assert snapshot.schema5_forecast is not None
        coordinator = object.__new__(HorizonIQCoordinator)
        coordinator._latest_snapshot = snapshot
        coordinator._last_valid_schema5_forecast = snapshot.schema5_forecast
        coordinators.append(coordinator)

    invalid = _payload()
    del invalid["periods"][0]["decisionTrace"]["constraints"]
    stale = coordinators[0]._build_snapshot_or_stale(invalid)

    assert stale.schema5_forecast is not None
    assert stale.schema5_forecast.plan_id == "plan-a"
    assert stale.schema5_forecast.stale is True
    assert [
        coordinator._last_valid_schema5_forecast.plan_id
        for coordinator in coordinators[1:]
    ] == ["plan-b", "plan-c"]


@pytest.mark.parametrize("plan_kind", ("live", "advisory", "replay"))
def test_schema5_preserves_all_action_semantics(plan_kind: str) -> None:
    """Live, advisory, and replay expose exact backend action fields unchanged."""
    payload = _payload()
    payload["planKind"] = plan_kind
    payload["periods"][0].update(
        {
            "recommendedAction": "import_for_export",
            "simulationAction": "use_grid",
            "executableAction": "charge_required",
        }
    )
    forecast = parse_schema5_forecast(payload)

    assert forecast is not None
    period = forecast.to_dict()["periods"][0]
    assert period["recommendedAction"] == "import_for_export"
    assert period["simulationAction"] == "use_grid"
    assert period["executableAction"] == "charge_required"


@pytest.mark.parametrize("reason_code", sorted(REASON_CODES))
def test_import_for_export_decision_keeps_exact_backend_reason_codes(
    reason_code: str,
) -> None:
    """Rejected periods are grouped solely by exact backend reasonCode values."""
    payload = _payload()
    payload["periods"][0]["recommendedAction"] = "none"
    payload["periods"][0]["simulationAction"] = "none"
    payload["periods"][0]["executableAction"] = "none"
    payload["periods"][0]["decisionTrace"]["selectedAction"] = "none"
    payload["periods"][0]["decisionTrace"]["reasonCode"] = reason_code
    forecast = parse_schema5_forecast(payload)
    assert forecast is not None
    sensor = ImportForExportDecisionSensor(_Runtime(forecast), "entry-1")

    assert sensor.native_value == "not_planned"
    assert reason_code in sensor.extra_state_attributes["rejected_periods"]


def test_import_for_export_decision_selected_and_disabled() -> None:
    """Selected and disabled states come only from the relevant plan switch and trace."""
    payload = _payload()
    period = payload["periods"][0]
    period["recommendedAction"] = "import_for_export"
    period["executableAction"] = "import_for_export"
    period["decisionTrace"]["selectedAction"] = "import_for_export"
    forecast = parse_schema5_forecast(payload)
    assert forecast is not None
    sensor = ImportForExportDecisionSensor(_Runtime(forecast), "entry-1")
    assert sensor.native_value == "planned"
    assert sensor.extra_state_attributes["selected_periods"][0]["period"] == 0

    disabled_payload = deepcopy(payload)
    disabled_payload["importForExportEnabled"] = False
    disabled = parse_schema5_forecast(disabled_payload)
    assert disabled is not None
    assert ImportForExportDecisionSensor(_Runtime(disabled), "entry-1").native_value == "disabled"

    advisory_payload = deepcopy(payload)
    advisory_payload["planKind"] = "advisory"
    advisory_payload["importForExportEnabled"] = True
    advisory_payload["importForExportAdvisoryEnabled"] = False
    advisory_payload["periods"][0]["recommendedAction"] = "import_for_export"
    advisory = parse_schema5_forecast(advisory_payload)
    assert advisory is not None
    assert ImportForExportDecisionSensor(_Runtime(advisory), "entry-1").native_value == "disabled"


@pytest.mark.parametrize(
    ("plan_kind", "authoritative_action"),
    (("live", "executableAction"), ("advisory", "recommendedAction"), ("replay", "simulationAction")),
)
def test_import_for_export_uses_the_action_authoritative_for_each_plan_kind(
    plan_kind: str, authoritative_action: str
) -> None:
    """Live commands, advisory suggestions, and replay actions stay distinct."""
    payload = _payload()
    payload["planKind"] = plan_kind
    period = payload["periods"][0]
    period.update(
        {
            "recommendedAction": "charge_required",
            "simulationAction": "charge_required",
            "executableAction": "charge_required",
        }
    )
    period[authoritative_action] = "import_for_export"
    forecast = parse_schema5_forecast(payload)
    assert forecast is not None

    assert (
        ImportForExportDecisionSensor(_Runtime(forecast), "entry-1").native_value
        == "planned"
    )


def test_full_horizon_is_explicitly_unrecorded() -> None:
    """Recorder serialization keeps only the bounded diagnostics summary."""
    forecast = parse_schema5_forecast(_payload())
    assert forecast is not None
    entity = ForecastDetailSensor(
        _Coordinator(forecast), "entry-1", "Sandbox"
    )
    attributes = entity.extra_state_attributes
    recorder_attributes = {
        key: value
        for key, value in attributes.items()
        if key not in entity._unrecorded_attributes
    }

    assert "forecast_horizon" in ForecastDetailSensor._unrecorded_attributes
    assert attributes["forecast_horizon"] == forecast.to_dict()
    assert "plannedEnergyLedger" not in json.dumps(recorder_attributes)
    assert len(json.dumps(recorder_attributes)) < 8_192


def test_recorder_serializes_only_bounded_forecast_diagnostics() -> None:
    """The production Recorder serializer excludes the complete live horizon."""
    from homeassistant.components.recorder.db_schema import StateAttributes

    forecast = parse_schema5_forecast(_payload())
    assert forecast is not None
    entity = ForecastDetailSensor(_Coordinator(forecast), "entry-1", "Sandbox")
    attributes = entity.extra_state_attributes
    state = State(
        "sensor.horizoniq_sandbox_forecast_diagnostics_recorder",
        "2",
        attributes,
        state_info={"unrecorded_attributes": entity._unrecorded_attributes},
    )
    event = Event(
        EVENT_STATE_CHANGED,
        {
            "entity_id": state.entity_id,
            "old_state": None,
            "new_state": state,
        },
    )
    serialized = StateAttributes.shared_attrs_bytes_from_event(event, dialect=None)

    assert b"forecast_horizon" not in serialized
    assert b"plannedEnergyLedger" not in serialized
    assert b"decisionTrace" not in serialized
    assert len(serialized) < 8_192


class _Runtime:
    """Minimal entry-local runtime double for pure entity diagnostics tests."""

    def __init__(self, forecast) -> None:
        self.forecast_diagnostics = forecast
        self.virtual_entity_available = True

    def add_listener(self, _listener):
        return lambda: None


class _Coordinator:
    """Minimal coordinator that exposes a complete in-memory schema-5 snapshot."""

    def __init__(self, forecast) -> None:
        from custom_components.horizoniq.models import HorizonIQSnapshot

        self.data = HorizonIQSnapshot(
            schema5_forecast=forecast,
            forecast_periods=[{"executable_action": "charge_required"}],
        )
        self.last_update_success = True
        self.last_exception = None

    def async_add_listener(self, _listener, context=None):
        return lambda: None

"""Schema-5 virtual-battery forecast diagnostics regression coverage."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from unittest.mock import MagicMock

import pytest
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, State
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.horizoniq.forecast_schema5 import (
    REASON_CODES,
    Schema5ForecastError,
    parse_schema5_forecast,
    select_current_schema5_period,
)
from custom_components.horizoniq.coordinator import HorizonIQCoordinator
from custom_components.horizoniq.coordinator_helpers import build_snapshot
from custom_components.horizoniq.direct_control import (
    DirectForecastRejection,
    parse_live_command,
    validate_live_forecast,
)
from custom_components.horizoniq.models import ForecastFreshness
from custom_components.horizoniq.sensors.import_for_export import (
    ImportForExportDecisionSensor,
)
from custom_components.horizoniq.sensors.diagnostic import ForecastDetailSensor
from custom_components.horizoniq.simulation.models import BatteryConfig, OperatingMode


FIXTURE = Path(__file__).with_name("fixtures") / "direct_schema5_forecast.json"


def _payload() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _schema6_payload(*, should_export: bool) -> dict[str, object]:
    """Return a complete schema-6 plan with one explicit export decision."""
    payload = _payload()
    payload["schemaVersion"] = 6
    payload["shouldExport"] = should_export
    periods = payload["periods"]
    assert isinstance(periods, list)
    for period in periods:
        assert isinstance(period, dict)
        period["shouldExport"] = should_export
    return payload


def _maximum_horizon_payload() -> dict[str, object]:
    """Expand the complete fixture to the production 48-period horizon."""
    payload = _payload()
    source_periods = payload["periods"]
    assert isinstance(source_periods, list) and source_periods
    start = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
    periods: list[dict[str, object]] = []
    for index in range(48):
        period = deepcopy(source_periods[index % len(source_periods)])
        assert isinstance(period, dict)
        period["period"] = index
        period["date"] = (start + timedelta(minutes=30 * index)).isoformat().replace(
            "+00:00", "Z"
        )
        periods.append(period)
    payload["periods"] = periods
    return payload


def _wire_alias(value: object, style: str) -> object:
    """Build a complete Solar DTO fixture in one documented wire spelling."""
    if isinstance(value, list):
        return [_wire_alias(item, style) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, object] = {}
    for key, item in value.items():
        alias = (
            key[:1].upper() + key[1:]
            if style == "pascal"
            else "".join(
                f"_{character.lower()}" if character.isupper() else character
                for character in key
            )
        )
        result[alias] = _wire_alias(item, style)
    return result


def test_complete_schema5_contract_survives_strict_normalization() -> None:
    """Every documented plan, period, trace, economics, and ledger field survives."""
    payload = _payload()
    forecast = parse_schema5_forecast(payload)

    assert forecast is not None
    normalized = forecast.to_dict()
    assert normalized["schemaVersion"] == 5
    assert normalized["shouldExport"] is None
    for field in (
        "planId",
        "planKind",
        "importForExportEnabled",
        "importForExportAdvisoryEnabled",
        "createdAtUtc",
        "effectiveAtUtc",
        "economicsAssumptions",
        "plannedEnergyLedger",
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
    physical_profile = dict(payload["equipmentProfile"])
    physical_profile.pop("supportedControl")
    physical_profile.pop("productionExportEnabled")
    assert normalized["equipmentProfile"] == physical_profile
    period = normalized["periods"][0]
    source_period = payload["periods"][0]
    assert period["shouldExport"] is None
    for field in (
        "period",
        "date",
        "price",
        "shouldImport",
        "shouldUseGrid",
        "recommendedAction",
        "executableAction",
        "commandId",
        "issuedAtUtc",
        "expiresAtUtc",
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
    assert "actionPriority" not in period
    assert period["decisionTrace"] == source_period["decisionTrace"]


@pytest.mark.parametrize("style", ("camel", "pascal", "snake"))
@pytest.mark.parametrize("legacy_value", ("absent", None, False, True, "malformed"))
def test_old_and_new_profiles_normalize_to_identical_physical_profile(
    style: str, legacy_value: object
) -> None:
    """Retired aliases have no place in the canonical physical contract."""
    new_payload = _payload()
    profile = new_payload["equipmentProfile"]
    assert isinstance(profile, dict)
    profile.pop("supportedControl")
    profile.pop("productionExportEnabled")
    new_forecast = parse_schema5_forecast(new_payload)
    assert new_forecast is not None

    old_payload = (
        deepcopy(new_payload)
        if style == "camel"
        else _wire_alias(new_payload, style)
    )
    profile_key = {
        "camel": "equipmentProfile",
        "pascal": "EquipmentProfile",
        "snake": "equipment_profile",
    }[style]
    old_profile = old_payload[profile_key]
    assert isinstance(old_profile, dict)
    if legacy_value != "absent":
        old_profile["supportedControl"] = legacy_value
        old_profile["SupportedControl"] = {"requiredCharging": False}
        old_profile["supported_control"] = {"useGrid": None}
        old_profile["productionExportEnabled"] = legacy_value
        old_profile["ProductionExportEnabled"] = not bool(legacy_value)
    old_forecast = parse_schema5_forecast(old_payload)
    assert old_forecast is not None
    assert old_forecast.to_dict() == new_forecast.to_dict()
    assert set(old_forecast.to_dict()["equipmentProfile"]) == set(profile)

    conflicting = deepcopy(old_payload)
    conflicting_profile = conflicting[profile_key]
    assert isinstance(conflicting_profile, dict)
    conflicting_profile[
        "BatteryCapacityWh" if style == "camel" else "batteryCapacityWh"
    ] = 9_999
    with pytest.raises(Schema5ForecastError, match="Conflicting aliases"):
        parse_schema5_forecast(conflicting)


def test_retained_physical_profile_validation_is_unchanged() -> None:
    """Missing, null, unsafe, and out-of-bounds physical limits still refuse control."""
    payload = _payload()
    profile = payload["equipmentProfile"]
    assert isinstance(profile, dict)
    profile.pop("supportedControl")
    profile.pop("productionExportEnabled")
    missing = deepcopy(payload)
    del missing["equipmentProfile"]["batteryCapacityWh"]
    with pytest.raises(Schema5ForecastError, match="batteryCapacityWh"):
        parse_schema5_forecast(missing)

    unsafe = deepcopy(payload)
    unsafe["equipmentProfile"]["batteryCapacityWh"] = float("nan")
    with pytest.raises(Schema5ForecastError, match="safe JSON object"):
        parse_schema5_forecast(unsafe)

    for invalid in (None, 0, -1):
        malformed = deepcopy(payload)
        malformed["equipmentProfile"]["batteryCapacityWh"] = invalid
        result = validate_live_forecast(
            build_snapshot(malformed).direct_forecast,
            now_utc=datetime(2026, 7, 30, 12, tzinfo=timezone.utc),
            config=BatteryConfig(10_000, 2_000, 2_000, 2_000),
        )
        assert result.rejection in {
            DirectForecastRejection.MODEL_UNAVAILABLE,
            DirectForecastRejection.PROFILE_INVALID,
        }


@pytest.mark.parametrize(
    "alias",
    (
        "supportedControl", "SupportedControl", "supported_control",
        "productionExportEnabled", "ProductionExportEnabled",
        "production_export_enabled",
    ),
)
@pytest.mark.parametrize("secret_key", ("apiKey", "registration_data", "function-key"))
def test_retired_profile_aliases_reject_nested_diagnostic_secrets(
    alias: str, secret_key: str
) -> None:
    """Discarded legacy profile maps still enforce diagnostic redaction."""
    payload = _payload()
    profile = payload["equipmentProfile"]
    assert isinstance(profile, dict)
    profile[alias] = {"extra": [[{"nested": {secret_key: "secret"}}]]}
    with pytest.raises(Schema5ForecastError, match="prohibited key"):
        parse_schema5_forecast(payload)


def test_new_profile_survives_real_coordinator_refresh() -> None:
    """A new schema-6 profile reaches typed direct control through refresh parsing."""
    payload = _schema6_payload(should_export=False)
    profile = payload["equipmentProfile"]
    assert isinstance(profile, dict)
    profile.pop("supportedControl")
    profile.pop("productionExportEnabled")
    coordinator = object.__new__(HorizonIQCoordinator)
    coordinator._last_valid_schema5_forecast = None
    snapshot = coordinator._build_snapshot_or_stale(payload)
    assert snapshot.forecast_freshness is ForecastFreshness.FRESH
    assert snapshot.direct_forecast is not None
    command = parse_live_command(
        snapshot.direct_forecast,
        now_utc=datetime(2026, 7, 30, 12, tzinfo=timezone.utc),
        config=BatteryConfig(10_000, 2_000, 2_000, 2_000),
    )
    assert command.command.mode is OperatingMode.GRID_SETPOINT
    assert command.command.requested_grid_power_w == 2_000

    malformed = deepcopy(payload)
    del malformed["equipmentProfile"]["maximumGridImportPowerWatts"]
    coordinator._latest_snapshot = snapshot
    coordinator._publication_sequence = 0
    coordinator.async_set_updated_data = MagicMock()
    with pytest.raises(UpdateFailed, match="maximumGridImportPowerWatts"):
        coordinator._build_snapshot_or_stale(malformed)
    stale = coordinator._latest_snapshot
    assert stale.forecast_freshness is ForecastFreshness.STALE
    assert stale.direct_forecast is None
    assert stale.schema5_forecast is not None
    assert stale.schema5_forecast.plan_id == snapshot.schema5_forecast.plan_id


def test_schema6_requires_and_preserves_backend_should_export() -> None:
    """Schema 6 carries the backend export decision without HA inference."""
    payload = _schema6_payload(should_export=True)
    payload["shouldImport"] = False
    periods = payload["periods"]
    assert isinstance(periods, list)
    for period in periods:
        assert isinstance(period, dict)
        period["shouldImport"] = False

    forecast = parse_schema5_forecast(payload)
    snapshot = build_snapshot(payload)

    assert forecast is not None
    assert forecast.schema_version == 6
    assert forecast.should_export is True
    assert all(period.should_export is True for period in forecast.periods)
    assert snapshot.should_export is True
    assert snapshot.forecast["should_export"] is True
    assert all(period["should_export"] is True for period in snapshot.forecast_periods)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda payload: payload.pop("shouldExport"),
        lambda payload: payload["periods"][0].pop("shouldExport"),
        lambda payload: payload.__setitem__("shouldExport", "true"),
        lambda payload: payload["periods"][0].__setitem__("shouldExport", 1),
    ),
)
def test_schema6_rejects_missing_or_non_boolean_should_export(mutate) -> None:
    """Schema 6 never silently substitutes an export decision."""
    payload = _schema6_payload(should_export=False)

    mutate(payload)

    with pytest.raises(Schema5ForecastError, match="shouldExport must be boolean"):
        parse_schema5_forecast(payload)


def test_schema6_rejects_simultaneous_import_and_export() -> None:
    """The simple planning decisions cannot contradict each other."""
    payload = _schema6_payload(should_export=True)

    with pytest.raises(Schema5ForecastError, match="cannot both be true"):
        parse_schema5_forecast(payload)


@pytest.mark.parametrize("style", ("pascal", "snake"))
def test_complete_solar_dto_alias_fixtures_normalize_once(style: str) -> None:
    """PascalCase and legacy snake_case wire forms reach the same contract."""
    camel = parse_schema5_forecast(_payload())
    alias = parse_schema5_forecast(_wire_alias(_payload(), style))

    assert camel is not None and alias is not None
    assert alias.to_dict() == camel.to_dict()


def test_conflicting_schema5_wire_aliases_are_rejected_atomically() -> None:
    """A response cannot select an arbitrary casing when aliases disagree."""
    payload = _payload()
    payload["SchemaVersion"] = 4

    with pytest.raises(Schema5ForecastError, match="Conflicting aliases"):
        parse_schema5_forecast(payload)


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

    with pytest.raises(Schema5ForecastError, match="prohibited key"):
        parse_schema5_forecast(payload)


def test_schema5_contract_omits_top_level_transport_metadata() -> None:
    """Transport metadata beside the Solar plan never enters live diagnostics."""
    payload = _payload()
    payload.update(
        {
            "registrationData": "encrypted-registration-data",
            "credentials": {"apiKey": "secret"},
            "functionKeys": ["secret-function-key"],
            "headers": {"X-API-KEY": "secret"},
        }
    )

    forecast = parse_schema5_forecast(payload)
    assert forecast is not None
    serialized = json.dumps(forecast.to_dict())
    assert "registrationData" not in serialized
    assert "credentials" not in serialized
    assert "functionKeys" not in serialized
    assert "headers" not in serialized
    assert "secret" not in serialized


def test_malformed_schema5_refresh_keeps_the_last_complete_plan_as_stale() -> None:
    """A failed replacement leaves the previous entry-local horizon intact."""
    valid = _payload()
    snapshot = build_snapshot(valid)
    assert snapshot.schema5_forecast is not None
    coordinator = object.__new__(HorizonIQCoordinator)
    coordinator._latest_snapshot = snapshot
    coordinator._last_valid_schema5_forecast = snapshot.schema5_forecast
    coordinator._publish_stale_forecast = MagicMock()

    invalid = deepcopy(valid)
    del invalid["periods"][0]["expectedNetValue"]
    with pytest.raises(UpdateFailed, match="Malformed schema-5 forecast"):
        coordinator._build_snapshot_or_stale(invalid)

    coordinator._publish_stale_forecast.assert_called_once_with()
    assert coordinator._last_valid_schema5_forecast is not None
    assert coordinator._last_valid_schema5_forecast.plan_id == snapshot.schema5_forecast.plan_id
    assert coordinator._last_valid_schema5_forecast.to_dict()["periods"] == snapshot.schema5_forecast.to_dict()[
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
        coordinator._publish_stale_forecast = MagicMock()
        coordinators.append(coordinator)

    invalid = _payload()
    del invalid["periods"][0]["decisionTrace"]["constraints"]
    with pytest.raises(UpdateFailed, match="Malformed schema-5 forecast"):
        coordinators[0]._build_snapshot_or_stale(invalid)

    coordinators[0]._publish_stale_forecast.assert_called_once_with()
    assert coordinators[0]._last_valid_schema5_forecast is not None
    assert coordinators[0]._last_valid_schema5_forecast.plan_id == "plan-a"
    assert [
        coordinator._last_valid_schema5_forecast.plan_id
        for coordinator in coordinators[1:]
    ] == ["plan-b", "plan-c"]


@pytest.mark.parametrize(
    "plan_kind", ("live", "import_for_export_advisory")
)
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
    assert "simulationAction" not in period
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
    advisory_payload["planKind"] = "import_for_export_advisory"
    advisory_payload["importForExportEnabled"] = True
    advisory_payload["importForExportAdvisoryEnabled"] = False
    advisory_payload["periods"][0]["recommendedAction"] = "import_for_export"
    advisory = parse_schema5_forecast(advisory_payload)
    assert advisory is not None
    assert ImportForExportDecisionSensor(_Runtime(advisory), "entry-1").native_value == "disabled"


@pytest.mark.parametrize(
    ("plan_kind", "authoritative_action"),
    (
        ("live", "executableAction"),
        ("import_for_export_advisory", "recommendedAction"),
    ),
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


def test_zero_period_schema5_forecast_is_unavailable_and_kept_complete() -> None:
    """An accepted zero-period response is never reported as healthy."""
    payload = _payload()
    payload["periods"] = []
    forecast = parse_schema5_forecast(payload)
    assert forecast is not None

    entity = ForecastDetailSensor(_Coordinator(forecast), "entry-1", "Sandbox")
    assert entity.native_value == 0
    assert entity.extra_state_attributes["health"] == "Unavailable"
    assert entity.extra_state_attributes["forecast"]["periods"] == []


def test_current_schema5_period_uses_utc_half_hour_boundaries() -> None:
    """The shared selector includes a period start and excludes its end."""
    forecast = parse_schema5_forecast(_payload())

    assert forecast is not None
    first = forecast.periods[0]
    second = forecast.periods[1]
    start = datetime.fromisoformat(first.date.replace("Z", "+00:00"))

    assert select_current_schema5_period(forecast, start) == first
    assert (
        select_current_schema5_period(forecast, start + timedelta(minutes=29, seconds=59))
        == first
    )
    assert select_current_schema5_period(forecast, start + timedelta(minutes=30)) == second


def test_stale_last_good_forecast_remains_visible_after_refresh_failure() -> None:
    """Refresh failure marks the horizon stale without hiding its live data."""
    forecast = parse_schema5_forecast(_payload())
    assert forecast is not None
    coordinator = _Coordinator(forecast.as_stale())
    coordinator.last_update_success = False
    entity = ForecastDetailSensor(coordinator, "entry-1", "Live")

    assert entity.available is True
    assert entity.extra_state_attributes["stale"] is True
    assert len(entity.extra_state_attributes["forecast"]["periods"]) == 2


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

    assert ForecastDetailSensor._unrecorded_attributes == frozenset({"forecast"})
    assert attributes["forecast"] == forecast.to_dict()
    assert "plannedEnergyLedger" not in json.dumps(recorder_attributes)
    assert len(json.dumps(recorder_attributes)) < 8_192


def test_recorder_serializes_only_bounded_forecast_diagnostics(caplog) -> None:
    """The production Recorder serializer excludes the complete live horizon."""
    from homeassistant.components.recorder.db_schema import StateAttributes

    forecast = parse_schema5_forecast(_maximum_horizon_payload())
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

    assert len(attributes["forecast"]["periods"]) == 48
    assert attributes["forecast"]["periods"][0]["decisionTrace"]
    assert b'"forecast"' not in serialized
    assert b"plannedEnergyLedger" not in serialized
    assert b"decisionTrace" not in serialized
    assert len(serialized) < 8_192
    assert "exceed maximum size" not in caplog.text


@pytest.mark.skipif(
    sqlite3.sqlite_version_info < (3, 40, 1),
    reason="Home Assistant Recorder requires SQLite 3.40.1 or newer",
)
class TestRecorderForecastAttributes:
    """Recorder coverage requiring its database before Home Assistant starts."""

    @pytest.fixture
    def auto_enable_custom_integrations(self) -> None:
        """Avoid starting Home Assistant before the Recorder database is ready."""

    async def test_recorder_database_omits_only_the_full_forecast(
        self, recorder_mock, hass, caplog
    ) -> None:
        """A real Recorder write keeps the complete horizon out of persistence."""
        from homeassistant.components.recorder.db_schema import (
            StateAttributes,
            States,
            StatesMeta,
        )

        forecast = parse_schema5_forecast(_maximum_horizon_payload())
        assert forecast is not None
        entity = ForecastDetailSensor(_Coordinator(forecast), "entry-1", "Sandbox")
        attributes = entity.extra_state_attributes
        entity_id = "sensor.horizoniq_sandbox_forecast_diagnostics_recorder"

        hass.states.async_set(
            entity_id,
            "48",
            attributes,
            state_info={"unrecorded_attributes": entity._unrecorded_attributes},
        )
        live_state = hass.states.get(entity_id)
        assert live_state is not None
        assert len(live_state.attributes["forecast"]["periods"]) == 48

        # Recorder owns a separate worker queue.  On slower CI runners it can
        # begin processing the state-changed event just after the first drain,
        # so wait for the observable database result rather than a scheduler
        # timing boundary.
        recorded_state = None
        for _ in range(100):
            await hass.async_block_till_done()
            await recorder_mock.async_block_till_done()
            with recorder_mock.get_session() as session:
                recorded_state = (
                    session.query(States)
                    .join(StatesMeta, States.metadata_id == StatesMeta.metadata_id)
                    .filter(StatesMeta.entity_id == entity_id)
                    .order_by(States.state_id.desc())
                    .first()
                )
            if recorded_state is not None:
                break
            await asyncio.sleep(0.01)

        assert recorded_state is not None
        with recorder_mock.get_session() as session:
            assert recorded_state.attributes_id is not None
            recorded_attributes = session.get(
                StateAttributes, recorded_state.attributes_id
            )
            assert recorded_attributes is not None
            assert "forecast" not in (recorded_attributes.shared_attrs or "")
            assert "decisionTrace" not in (recorded_attributes.shared_attrs or "")
            assert len(recorded_attributes.shared_attrs or "") < 8_192
        assert not any(
            "exceed maximum size" in record.message for record in caplog.records
        )


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


def _schema8_payload(source: dict[str, object] | None = None) -> dict[str, object]:
    """Transform the historical fixture once into the current wire contract."""
    payload = deepcopy(source) if source is not None else _schema6_payload(should_export=False)
    payload["schemaVersion"] = 8
    payload.setdefault("shouldExport", False)
    for period in payload["periods"]:
        period.setdefault("shouldExport", False)
        period.pop("simulationAction", None)
    payload["diagnostics"] = {"plannedEnergyLedger": payload.pop("plannedEnergyLedger")}
    return payload


def test_schema7_accepts_no_simulation_field() -> None:
    payload = _schema6_payload(should_export=False)
    payload["schemaVersion"] = 7
    for period in payload["periods"]:
        period.pop("simulationAction", None)
    forecast = parse_schema5_forecast(payload)
    assert forecast is not None and forecast.schema_version == 7
    assert all("simulationAction" not in period for period in forecast.to_dict()["periods"])
    assert not hasattr(forecast.periods[0], "simulation_action")


@pytest.mark.parametrize("version", (5, 6))
@pytest.mark.parametrize("value", ("absent", None, "export_for_profit", {"ignored": True}))
@pytest.mark.parametrize("alias", ("simulationAction", "SimulationAction", "simulation_action"))
def test_legacy5_and6_ignore_retired_simulation_field(version, value, alias) -> None:
    payload = _schema6_payload(should_export=False)
    payload["schemaVersion"] = version
    for period in payload["periods"]:
        period.pop("simulationAction", None)
        if value != "absent":
            period[alias] = value
    snapshot = build_snapshot(payload)
    command = parse_live_command(snapshot.direct_forecast, now_utc=datetime(2026, 7, 30, 12, tzinfo=timezone.utc), config=BatteryConfig(10_000, 2_000, 2_000, 2_000))
    assert command.action == "charge_required"
    assert "simulationAction" not in snapshot.schema5_forecast.to_dict()["periods"][0]


@pytest.mark.parametrize("version", (5, 6, 7, 8))
def test_replay_plan_is_rejected_without_control_mutation(version) -> None:
    coordinator = object.__new__(HorizonIQCoordinator)
    coordinator._last_valid_schema5_forecast = None
    good = _schema8_payload()
    accepted = coordinator._build_snapshot_or_stale(good)
    coordinator._latest_snapshot = accepted
    coordinator._publish_stale_forecast = MagicMock()
    payload = _schema8_payload() if version == 8 else _schema6_payload(should_export=False)
    payload["schemaVersion"] = version
    payload["planKind"] = "sandbox_replay"
    with pytest.raises(UpdateFailed, match="planKind is unsupported"):
        coordinator._build_snapshot_or_stale(payload)
    assert coordinator._last_valid_schema5_forecast is accepted.schema5_forecast
    assert coordinator._latest_snapshot is accepted


@pytest.mark.parametrize("style", ("camel", "pascal", "snake"))
def test_schema8_normalizes_nested_diagnostics_for_each_wire_style(style) -> None:
    payload = _schema8_payload()
    expected = payload["diagnostics"]["plannedEnergyLedger"]
    payload["diagnostics"]["ignored"] = {"harmless": [1, 2]}
    if style != "camel":
        payload = _wire_alias(payload, style)
    forecast = parse_schema5_forecast(payload)
    assert forecast is not None and forecast.schema_version == 8
    assert forecast.planned_energy_ledger == expected
    assert len(forecast.planned_energy_ledger) == 10
    assert forecast.to_dict()["diagnostics"] == {"plannedEnergyLedger": expected}


@pytest.mark.parametrize("diagnostics", ("missing", None))
def test_schema8_missing_or_null_diagnostics_does_not_disable_live_command(diagnostics) -> None:
    payload = _schema8_payload()
    if diagnostics == "missing":
        payload.pop("diagnostics")
    else:
        payload["diagnostics"] = None
    snapshot = build_snapshot(payload)
    assert snapshot.schema5_forecast.planned_energy_ledger is None
    result = validate_live_forecast(snapshot.direct_forecast, now_utc=datetime(2026, 7, 30, 12, tzinfo=timezone.utc), config=BatteryConfig(10_000, 2_000, 2_000, 2_000))
    assert result.command is not None and result.command.action == "charge_required"


def _invalid_schema8_diagnostics():
    import math
    for value in (False, 1, "invalid", [], {}, {"plannedEnergyLedger": None}, {"plannedEnergyLedger": []}, {"plannedEnergyLedger": 1}, {"plannedEnergyLedger": {}}):
        yield value
    ledger = _schema8_payload()["diagnostics"]["plannedEnergyLedger"]
    for field in ledger:
        incomplete = deepcopy(ledger)
        incomplete.pop(field)
        yield {"plannedEnergyLedger": incomplete}
        values = (None, 0, 1, "true", [], {}) if field == "healthy" else (None, True, False, float("nan"), float("inf"), -float("inf"), "0", 10**400)
        for value in values:
            invalid = deepcopy(ledger)
            invalid[field] = value
            yield {"plannedEnergyLedger": invalid}
    for tolerance in (0, -0.001, 0.01, math.nextafter(0.001, 0), math.nextafter(0.001, math.inf)):
        yield {"plannedEnergyLedger": {**ledger, "toleranceKwh": tolerance}}
    for error in (0.001, -0.001, math.nextafter(0.001, math.inf), math.nextafter(-0.001, -math.inf)):
        yield {"plannedEnergyLedger": {**ledger, "balanceErrorKwh": error, "healthy": abs(error) > 0.001}}


@pytest.mark.parametrize("diagnostics", list(_invalid_schema8_diagnostics()))
def test_schema8_rejects_invalid_diagnostics_atomically(diagnostics) -> None:
    payload = _schema8_payload()
    before = deepcopy(payload)
    payload["diagnostics"] = diagnostics
    coordinator = object.__new__(HorizonIQCoordinator)
    accepted = build_snapshot(before).schema5_forecast
    coordinator._last_valid_schema5_forecast = accepted
    coordinator._publish_stale_forecast = MagicMock()
    with pytest.raises(Schema5ForecastError, match=r"^Schema-8 diagnostics are invalid\.$"):
        parse_schema5_forecast(payload)
    with pytest.raises(UpdateFailed, match=r"Schema-8 diagnostics are invalid\.$"):
        coordinator._build_snapshot_or_stale(payload)
    assert coordinator._last_valid_schema5_forecast is accepted
    coordinator._publish_stale_forecast.assert_called_once_with()


@pytest.mark.parametrize("error", (0, 0.001, -0.001, 0.0010000000000000002, -0.0010000000000000002, -4.0))
def test_schema8_accepts_inclusive_tolerance_and_finite_negative_error(error) -> None:
    import math
    payload = _schema8_payload()
    ledger = payload["diagnostics"]["plannedEnergyLedger"]
    ledger.update(balanceErrorKwh=error, healthy=abs(error) <= 0.001)
    forecast = parse_schema5_forecast(payload)
    assert forecast.planned_energy_ledger == ledger
    if abs(error) > 0.001 and abs(error) < 0.002:
        assert abs(error) == math.nextafter(0.001, math.inf)
    # Finite signed fields retain their backend meaning without extra sign rules.
    ledger["gridImportKwh"] = -1.0
    assert parse_schema5_forecast(payload).planned_energy_ledger["gridImportKwh"] == -1.0


@pytest.mark.parametrize("alias", ("plannedEnergyLedger", "PlannedEnergyLedger", "planned_energy_ledger"))
@pytest.mark.parametrize("value", (None, {}, "invalid"))
def test_schema8_rejects_root_ledger_and_conflicting_nested_aliases(alias, value) -> None:
    payload = _schema8_payload()
    payload[alias] = value
    with pytest.raises(Schema5ForecastError):
        parse_schema5_forecast(payload)
    for mutate in (
        lambda p: p.update(Diagnostics=None),
        lambda p: p["diagnostics"].update(PlannedEnergyLedger=None),
        lambda p: p["diagnostics"]["plannedEnergyLedger"].update(BalanceErrorKwh=42),
    ):
        payload = _schema8_payload()
        mutate(payload)
        with pytest.raises(Schema5ForecastError, match="Conflicting aliases"):
            parse_schema5_forecast(payload)
    payload = _schema8_payload()
    payload["schemaVersion"] = 9
    with pytest.raises(Schema5ForecastError, match="Unsupported forecast schemaVersion"):
        parse_schema5_forecast(payload)


@pytest.mark.parametrize("key", ("apiKey", "Authorization", "registration_data", "function-key", "headers", "credentials", "token"))
@pytest.mark.parametrize("location", ("wrapper", "ledger", "unknown-list"))
def test_schema8_diagnostics_reject_nested_transport_secrets(key, location) -> None:
    payload = _schema8_payload()
    target = payload["diagnostics"] if location == "wrapper" else payload["diagnostics"]["plannedEnergyLedger"]
    target["unknown"] = [{"nested": [{key: "never-log-this-value"}]}] if location == "unknown-list" else {key: "never-log-this-value"}
    with pytest.raises(Schema5ForecastError, match="diagnostics contain a prohibited key") as error:
        parse_schema5_forecast(payload)
    assert "never-log-this-value" not in str(error.value)


@pytest.mark.parametrize("version", (5, 6, 7, 8))
@pytest.mark.parametrize("available", (True, False))
def test_schema8_to_dict_emits_only_nested_diagnostics(version, available) -> None:
    payload = _schema8_payload() if version == 8 else _schema6_payload(should_export=False)
    payload["schemaVersion"] = version
    if version == 8 and not available:
        payload["diagnostics"] = None
    forecast = parse_schema5_forecast(payload)
    serialized = forecast.to_dict()
    if version == 8:
        assert "plannedEnergyLedger" not in serialized
        assert serialized["diagnostics"] == payload["diagnostics"]
    else:
        assert "diagnostics" not in serialized
        assert serialized["plannedEnergyLedger"] == payload["plannedEnergyLedger"]
        missing = deepcopy(payload)
        missing.pop("plannedEnergyLedger")
        with pytest.raises(Schema5ForecastError):
            parse_schema5_forecast(missing)
    assert parse_schema5_forecast(serialized) == forecast


async def test_schema8_same_hash_refreshes_entry_local_diagnostics(hass, mock_config_entry, entry_data, aioclient_mock) -> None:
    """Real Forecast_Get refresh replaces diagnostics even when its hash is stable."""
    import re
    from unittest.mock import patch
    from yarl import URL
    from custom_components.horizoniq.const import CONF_HASH, SANDBOX_ENVIRONMENT

    hass.states.async_set(entry_data["battery_capacity_sensor"], "4320")
    coordinator = HorizonIQCoordinator(hass, mock_config_entry, entry_data["url"], entry_data["api_key"], entry_data["battery_capacity_sensor"], SANDBOX_ENVIRONMENT)
    first_payload = {**_schema8_payload(), "hash": "same-hash"}
    aioclient_mock.get(re.compile(rf"\A{re.escape(str(URL(coordinator._build_request_url('4320'))))}\Z"), json=first_payload)
    first = await coordinator.async_fetch_sandbox_forecast()
    assert first.forecast_freshness is ForecastFreshness.FRESH
    assert mock_config_entry.data[CONF_HASH] == "same-hash"
    accepted_config = dict(mock_config_entry.data)
    second_payload = deepcopy(first_payload)
    second_payload["diagnostics"]["plannedEnergyLedger"]["gridImportKwh"] = 123.5
    aioclient_mock.clear_requests()
    aioclient_mock.get(re.compile(rf"\A{re.escape(str(URL(coordinator._build_request_url('4320'))))}\Z"), json=second_payload)
    with patch.object(hass.config_entries, "async_update_entry", wraps=hass.config_entries.async_update_entry) as update_entry:
        second = await coordinator.async_fetch_sandbox_forecast()
    update_entry.assert_not_called()
    assert aioclient_mock.call_count == 1
    assert second.publication_sequence > first.publication_sequence
    assert coordinator.last_forecast is second.schema5_forecast
    assert second.schema5_forecast.planned_energy_ledger["gridImportKwh"] == 123.5
    assert first.schema5_forecast.planned_energy_ledger["gridImportKwh"] != 123.5
    assert mock_config_entry.data == accepted_config
    assert "diagnostics" not in json.dumps(accepted_config)


async def test_schema8_refresh_keeps_diagnostics_entry_local_and_unrecorded(hass, mock_config_entry, entry_data, aioclient_mock, caplog) -> None:
    """HTTP refresh, stale-last-good and Recorder serialization stay entry scoped."""
    import re
    from yarl import URL
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from homeassistant.components.recorder.db_schema import StateAttributes
    from custom_components.horizoniq.const import DOMAIN, SANDBOX_ENVIRONMENT

    hass.states.async_set(entry_data["battery_capacity_sensor"], "4320")
    other_entry = MockConfigEntry(domain=DOMAIN, title="Other", data=entry_data, entry_id="schema8-other")
    other_entry.add_to_hass(hass)
    coordinators = [HorizonIQCoordinator(hass, entry, entry_data["url"], entry_data["api_key"], entry_data["battery_capacity_sensor"], SANDBOX_ENVIRONMENT) for entry in (mock_config_entry, other_entry)]
    snapshots = []
    for index, coordinator in enumerate(coordinators):
        payload = _schema8_payload()
        payload["planId"] = f"entry-{index}"
        payload["diagnostics"]["plannedEnergyLedger"]["gridImportKwh"] = index + 10.0
        payload["registrationData"] = "private-registration-sentinel"
        payload["headers"] = {"Authorization": "transport-sentinel"}
        aioclient_mock.clear_requests()
        aioclient_mock.get(re.compile(rf"\A{re.escape(str(URL(coordinator._build_request_url('4320'))))}\Z"), json=payload)
        snapshots.append(await coordinator.async_fetch_sandbox_forecast())
    assert coordinators[0].last_forecast is not coordinators[1].last_forecast
    other_before = coordinators[1].last_forecast.to_dict()
    invalid = _schema8_payload()
    invalid["diagnostics"]["plannedEnergyLedger"]["healthy"] = "unsafe-value"
    aioclient_mock.clear_requests()
    first = coordinators[0]
    aioclient_mock.get(re.compile(rf"\A{re.escape(str(URL(first._build_request_url('4320'))))}\Z"), json=invalid)
    with pytest.raises(UpdateFailed, match="Schema-8 diagnostics are invalid"):
        await first.async_fetch_sandbox_forecast()
    assert first.data.forecast_freshness is ForecastFreshness.STALE
    assert first.data.direct_forecast is None
    assert first.data.schema5_forecast.planned_energy_ledger == snapshots[0].schema5_forecast.planned_energy_ledger
    assert coordinators[1].last_forecast.to_dict() == other_before
    assert not coordinators[1].last_forecast.stale
    entity = ForecastDetailSensor(first, "schema8-entry", "Sandbox")
    attributes = entity.extra_state_attributes
    assert attributes["forecast"]["diagnostics"] is not None
    state = State("sensor.schema8_diagnostics", "2", attributes, state_info={"unrecorded_attributes": entity._unrecorded_attributes})
    event = Event(EVENT_STATE_CHANGED, {"entity_id": state.entity_id, "old_state": None, "new_state": state})
    serialized = StateAttributes.shared_attrs_bytes_from_event(event, dialect=None)
    assert b'"forecast"' not in serialized
    assert b"diagnostics" not in serialized
    assert b"plannedEnergyLedger" not in serialized
    assert len(serialized) < 8_192
    for sentinel in ("private-registration-sentinel", "transport-sentinel", "unsafe-value"):
        assert sentinel not in repr(attributes)
        assert sentinel not in caplog.text
    assert "diagnostics" not in json.dumps(dict(mock_config_entry.data))
    assert "diagnostics" not in json.dumps(dict(other_entry.data))

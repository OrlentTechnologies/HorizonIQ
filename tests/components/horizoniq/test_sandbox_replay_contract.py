"""Pure contract tests for the future sandbox Node-RED replay bridge."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import UUID

import pytest

from custom_components.horizoniq.simulation.local_profiles import HalfHourReplayInput
from custom_components.horizoniq.simulation.models import BatteryConfig
from custom_components.horizoniq.simulation.replay_contract import (
    FORECAST_STATUS_SCHEMA_VERSION,
    MAX_REPLAY_PERIODS,
    ClockStatus,
    RemoteReplayState,
    ReplayIdentityRegistry,
    ReplayState,
    apply_remote_status,
    build_clock_status,
    build_replay_request,
    canonical_request_json,
    create_replay_session,
    parse_clock_status,
    parse_replay_request,
    request_hash_sha256,
    start_replay_request,
    stop_replay,
    transition_local_replay,
    validate_remote_status,
)
from custom_components.horizoniq.simulation.topics import (
    clock_status_topic,
    replay_request_topic,
    replay_status_topic,
)


UTC = timezone.utc
START = datetime(2026, 4, 1, 12, tzinfo=UTC)
REPLAY_ID = "11111111-1111-4111-8111-111111111111"
GX_ID = "horizoniq-11111111111141118111111111111111"
CONFIG = BatteryConfig(10_000, 2_000, 2_000, 2_000)


def _periods(count: int = 2) -> tuple[HalfHourReplayInput, ...]:
    return tuple(
        HalfHourReplayInput(
            valid_from_utc=START + timedelta(minutes=30 * index),
            valid_to_utc=START + timedelta(minutes=30 * (index + 1)),
            expected_load_kwh=0.30,
            expected_solar_kwh=0.05,
            import_rate_gbp_per_kwh=-0.10,
            export_rate_gbp_per_kwh=0.05,
        )
        for index in range(count)
    )


def _request(replay_id: str = REPLAY_ID):
    return build_replay_request(
        periods=_periods(),
        starting_battery_energy_wh=5_000,
        config=CONFIG,
        import_for_export_enabled=True,
        export_for_solar_headroom=False,
        replay_id=replay_id,
    )


def test_request_json_shape_units_negative_import_and_absent_sensitive_fields() -> None:
    """The request matches the backend schema and contains no bridge secrets."""
    payload = _request().to_payload()

    assert payload == {
        "schemaVersion": 1,
        "replayId": REPLAY_ID,
        "effectiveAtUtc": "2026-04-01T12:00:00Z",
        "startingBatteryEnergyKwh": 5.0,
        "importForExportEnabled": True,
        "exportForSolarHeadroom": False,
        "periods": [
            {
                "validFromUtc": "2026-04-01T12:00:00Z",
                "validToUtc": "2026-04-01T12:30:00Z",
                "importRateGbpPerKwh": -0.10,
                "exportRateGbpPerKwh": 0.05,
                "expectedLoadKwh": 0.30,
                "expectedSolarKwh": 0.05,
            },
            {
                "validFromUtc": "2026-04-01T12:30:00Z",
                "validToUtc": "2026-04-01T13:00:00Z",
                "importRateGbpPerKwh": -0.10,
                "exportRateGbpPerKwh": 0.05,
                "expectedLoadKwh": 0.30,
                "expectedSolarKwh": 0.05,
            },
        ],
    }
    rendered = json.dumps(payload)
    for forbidden in ("registration", "key", "credential", "actual", "outcome", "command", "Override"):
        assert forbidden not in rendered


def test_request_horizon_order_capacity_and_size_boundaries(monkeypatch) -> None:
    """Only contiguous complete half hours within request bounds are accepted."""
    assert len(_request().periods) == 2
    build_replay_request(
        periods=_periods(MAX_REPLAY_PERIODS),
        starting_battery_energy_wh=2_000,
        config=CONFIG,
        import_for_export_enabled=False,
        export_for_solar_headroom=True,
        replay_id=REPLAY_ID,
    )
    with pytest.raises(ValueError):
        build_replay_request(
            periods=_periods(MAX_REPLAY_PERIODS + 1),
            starting_battery_energy_wh=5_000,
            config=CONFIG,
            import_for_export_enabled=True,
            export_for_solar_headroom=False,
            replay_id=REPLAY_ID,
        )
    with pytest.raises(ValueError):
        build_replay_request(
            periods=(_periods()[0], _periods()[0]),
            starting_battery_energy_wh=5_000,
            config=CONFIG,
            import_for_export_enabled=True,
            export_for_solar_headroom=False,
            replay_id=REPLAY_ID,
        )
    with pytest.raises(ValueError):
        build_replay_request(
            periods=_periods(),
            starting_battery_energy_wh=1_999,
            config=CONFIG,
            import_for_export_enabled=True,
            export_for_solar_headroom=False,
            replay_id=REPLAY_ID,
        )
    monkeypatch.setattr(
        "custom_components.horizoniq.simulation.replay_contract.MAX_REPLAY_REQUEST_BYTES",
        1,
    )
    with pytest.raises(ValueError, match="1 MiB"):
        _request()


def test_stored_request_parser_rejects_unknown_forbidden_and_invalid_fields() -> None:
    """Stored payloads cannot add credentials, overrides, or malformed values."""
    payload = _request().to_payload()
    assert parse_replay_request(payload, config=CONFIG) == _request()
    payload["equipmentProfileOverride"] = {}
    with pytest.raises(ValueError):
        parse_replay_request(payload, config=CONFIG)


def test_simulated_failure_flag_is_optional_strict_and_hash_bound() -> None:
    """The frozen optional failure flag is exact and changes HA-local request identity."""
    flagged = build_replay_request(
        periods=_periods(),
        starting_battery_energy_wh=5_000,
        config=CONFIG,
        import_for_export_enabled=True,
        export_for_solar_headroom=False,
        replay_id=REPLAY_ID,
        simulate_api_failure=True,
    )
    payload = flagged.to_payload()
    assert payload["simulateApiFailure"] is True
    assert parse_replay_request(payload, config=CONFIG) == flagged
    assert request_hash_sha256(flagged) != request_hash_sha256(_request())
    payload["simulateApiFailure"] = 1
    with pytest.raises(ValueError, match="failure flag"):
        parse_replay_request(payload, config=CONFIG)
    payload = _request().to_payload()
    payload["periods"][0]["exportRateGbpPerKwh"] = -0.01
    with pytest.raises(ValueError):
        parse_replay_request(payload, config=CONFIG)
    payload = _request().to_payload()
    payload["effectiveAtUtc"] = "2026-04-01T12:00:00+00:00"
    with pytest.raises(ValueError):
        parse_replay_request(payload, config=CONFIG)


def test_local_hash_and_replay_id_collision_guard_are_deterministic() -> None:
    """The local hash is stable and a replay ID cannot name different content."""
    request = _request()
    assert request_hash_sha256(request) == request_hash_sha256(request)
    assert canonical_request_json(request) == canonical_request_json(_request())
    registry = ReplayIdentityRegistry()
    assert registry.register(request) == request_hash_sha256(request)
    assert registry.register(_request()) == request_hash_sha256(request)
    changed = build_replay_request(
        periods=_periods(),
        starting_battery_energy_wh=6_000,
        config=CONFIG,
        import_for_export_enabled=True,
        export_for_solar_headroom=False,
        replay_id=REPLAY_ID,
    )
    with pytest.raises(ValueError, match="cannot be reused"):
        registry.register(changed)
    assert UUID(_request().replay_id)


def test_sandbox_replay_topics_reject_non_generated_gx_ids() -> None:
    """Replay and clock topics remain confined to generated sandbox GX IDs."""
    assert replay_request_topic(GX_ID) == f"horizoniq/sandbox/{GX_ID}/replay/request"
    assert replay_status_topic(GX_ID) == f"horizoniq/sandbox/{GX_ID}/replay/status"
    assert clock_status_topic(GX_ID) == f"horizoniq/sandbox/{GX_ID}/clock/status"
    for invalid in ("gx-123", "horizoniq-ABC", "horizoniq-" + "a" * 31):
        with pytest.raises(ValueError):
            replay_request_topic(invalid)


def test_status_identity_schema_and_transition_validation_are_strict() -> None:
    """Only fresh, matching remote statuses advance the local lifecycle."""
    session = start_replay_request(
        create_replay_session(_request(), profile_identifier="day.json", profile_hash="a" * 64)
    )
    loading = validate_remote_status(
        {
            "schemaVersion": FORECAST_STATUS_SCHEMA_VERSION,
            "gxDeviceId": GX_ID,
            "replayId": REPLAY_ID,
            "state": "loading",
            "reason": None,
        },
        owning_gx_device_id=GX_ID,
        active_replay_id=REPLAY_ID,
    )
    loading_session = apply_remote_status(session, loading)
    assert loading_session.state is ReplayState.LOADING
    ready = validate_remote_status(
        {
            "schemaVersion": 4,
            "gxDeviceId": GX_ID,
            "replayId": REPLAY_ID,
            "state": "ready",
            "reason": "validated",
        },
        owning_gx_device_id=GX_ID,
        active_replay_id=REPLAY_ID,
    )
    ready_session = apply_remote_status(loading_session, ready)
    assert ready_session.state is ReplayState.READY
    assert ready_session.last_remote_status is RemoteReplayState.READY
    assert transition_local_replay(ready_session, ReplayState.RUNNING).state is ReplayState.RUNNING
    assert transition_local_replay(ready_session, ReplayState.COMPLETED).state is ReplayState.COMPLETED
    assert stop_replay(ready_session).state is ReplayState.STOPPED
    with pytest.raises(ValueError, match="invalid or stale"):
        apply_remote_status(ready_session, ready)
    assert ready_session.state is ReplayState.READY
    invalid = {
        "schemaVersion": 4,
        "gxDeviceId": GX_ID,
        "replayId": REPLAY_ID,
        "state": "ready",
        "reason": None,
        "unexpected": True,
    }
    with pytest.raises(ValueError):
        validate_remote_status(invalid, owning_gx_device_id=GX_ID, active_replay_id=REPLAY_ID)
    invalid["replayId"] = "not-a-uuid"
    with pytest.raises(ValueError):
        validate_remote_status(invalid, owning_gx_device_id=GX_ID, active_replay_id=REPLAY_ID)
    invalid["replayId"] = REPLAY_ID
    invalid["schemaVersion"] = 3
    with pytest.raises(ValueError):
        validate_remote_status(invalid, owning_gx_device_id=GX_ID, active_replay_id=REPLAY_ID)
    invalid["schemaVersion"] = 4
    invalid.pop("unexpected")
    invalid["reason"] = "x" * 240
    assert validate_remote_status(
        invalid, owning_gx_device_id=GX_ID, active_replay_id=REPLAY_ID
    ).reason == invalid["reason"]
    invalid["reason"] = "x" * 241
    with pytest.raises(ValueError):
        validate_remote_status(invalid, owning_gx_device_id=GX_ID, active_replay_id=REPLAY_ID)
    invalid["replayId"] = "11111111-1111-4111-8111-111111111112"
    with pytest.raises(ValueError):
        validate_remote_status(invalid, owning_gx_device_id=GX_ID, active_replay_id=REPLAY_ID)


def test_clock_reset_sequence_paused_heartbeat_and_backwards_time() -> None:
    """Clock messages reset once and remain monotonic without wall-clock input."""
    reset = build_clock_status(
        gx_device_id=GX_ID,
        replay_id=REPLAY_ID,
        virtual_time_utc=START,
        reset=True,
    )
    assert reset.to_payload() == {
        "schemaVersion": 4,
        "gxDeviceId": GX_ID,
        "replayId": REPLAY_ID,
        "virtualTimeUtc": "2026-04-01T12:00:00Z",
        "sequence": 0,
        "reset": True,
    }
    paused = build_clock_status(
        gx_device_id=GX_ID,
        replay_id=REPLAY_ID,
        virtual_time_utc=START,
        previous=reset,
    )
    assert paused.sequence == 1 and paused.virtual_time_utc == reset.virtual_time_utc
    advanced = build_clock_status(
        gx_device_id=GX_ID,
        replay_id=REPLAY_ID,
        virtual_time_utc=START + timedelta(minutes=5),
        previous=paused,
    )
    assert advanced.sequence == 2 and not advanced.reset
    assert parse_clock_status(advanced.to_payload()) == advanced
    with pytest.raises(ValueError, match="backwards"):
        build_clock_status(
            gx_device_id=GX_ID,
            replay_id=REPLAY_ID,
            virtual_time_utc=START,
            previous=advanced,
        )
    reset_again = build_clock_status(
        gx_device_id=GX_ID,
        replay_id=REPLAY_ID,
        virtual_time_utc=START,
        previous=advanced,
        reset=True,
    )
    assert reset_again.sequence == 0 and reset_again.reset
    with pytest.raises(ValueError):
        build_clock_status(
            gx_device_id=GX_ID,
            replay_id=REPLAY_ID,
            virtual_time_utc=START,
        )


def test_replay_session_value_data_is_versioned_and_side_effect_free() -> None:
    """Session serialization holds only local replay identity and status values."""
    session = create_replay_session(
        _request(), profile_identifier="day.json", profile_hash="b" * 64
    )
    restored = type(session).from_dict(session.to_dict())
    assert restored == session
    serialized = json.dumps(session.to_dict())
    for forbidden in ("key", "credential", "mqtt", "actual", "command", "outcome"):
        assert forbidden not in serialized.lower()
    source = Path(
        "custom_components/horizoniq/simulation/replay_contract.py"
    ).read_text(encoding="utf-8").lower()
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imports & {"homeassistant", "mqtt", "requests", "aiohttp", "pathlib"}

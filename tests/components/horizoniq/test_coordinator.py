"""Tests for the update coordinator."""

import asyncio
from datetime import timedelta
import json
import logging
from pathlib import Path
import re
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, quote_plus, urlparse

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed
from yarl import URL

from custom_components.horizoniq.const import (
    CONF_FORECAST_FUNCTION_KEY,
    CONF_HASH,
    CONF_REGISTRATION_DATA,
    CONF_SUBSCRIPTION_STATUS,
    CONF_URL,
    EXACT_SUBSCRIPTION_FAILURE_BODY,
    HEADER_API_KEY,
    SANDBOX_ENVIRONMENT,
    HEADER_FORECAST_DEVICE_ID,
    HEADER_FORECAST_DEVICE_TOKEN,
    INITIAL_FORECAST_RETRY_SECONDS,
    SUBSCRIPTION_STATUS_NO_SUBSCRIPTION,
)
from custom_components.horizoniq.coordinator import HorizonIQCoordinator
from custom_components.horizoniq.models import ForecastFreshness, HorizonIQSnapshot
from custom_components.horizoniq.sensors.diagnostic import ForecastDetailSensor


FIXTURE = Path(__file__).with_name("fixtures") / "direct_schema5_forecast.json"

REGISTRATION_SENTINEL = "synthetic-registration+/=&? internal space"


def _flat_registration_forecast(schema_version: int) -> dict[str, object]:
    """Return a complete backend-style flat plan with transport hash metadata."""
    if schema_version == 6:
        payload = _schema6_payload()["Forecast"]
        assert isinstance(payload, dict)
    else:
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return {**payload, "hash": "fresh-hash"}


@pytest.mark.parametrize("schema_version", (5, 6))
@pytest.mark.parametrize("fetch_path", ("normal", "virtual"))
async def test_schema56_registration_data_persists_and_is_sent_on_next_request(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    aioclient_mock,
    schema_version: int,
    fetch_path: str,
) -> None:
    """Accepted private metadata reaches real storage and the next HTTP query."""
    hass.states.async_set(entry_data["battery_capacity_sensor"], "4320")
    original_entry = dict(mock_config_entry.data)
    coordinator = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
    )
    fetch = (
        coordinator._async_update_data
        if fetch_path == "normal"
        else coordinator.async_fetch_sandbox_forecast
    )
    assert coordinator.registration_data == ""
    assert mock_config_entry.data[CONF_REGISTRATION_DATA] == ""
    payload = _flat_registration_forecast(schema_version)
    payload["registrationData"] = f" \t{REGISTRATION_SENTINEL}\n "
    # Exact URL matching includes blank query values and avoids response reuse.
    aioclient_mock.get(
        re.compile(
            rf"\A{re.escape(str(URL(coordinator._build_request_url('4320'))))}\Z"
        ),
        json=payload,
    )

    with patch.object(
        hass.config_entries,
        "async_update_entry",
        wraps=hass.config_entries.async_update_entry,
    ) as update_entry:
        snapshot = await fetch()
        first_query = parse_qs(
            urlparse(str(aioclient_mock.mock_calls[0][1])).query,
            keep_blank_values=True,
        )
        assert first_query["registrationData"] == [""]
        assert first_query["hash"] == [""]
        assert first_query["currentBatteryCapacity"] == ["4320"]
        assert snapshot.forecast_freshness is ForecastFreshness.FRESH
        assert snapshot.registration_data == REGISTRATION_SENTINEL
        assert coordinator.registration_data == REGISTRATION_SENTINEL
        assert mock_config_entry.data[CONF_REGISTRATION_DATA] == REGISTRATION_SENTINEL
        update_entry.assert_called_once()

        aioclient_mock.get(
            re.compile(
                rf"\A{re.escape(str(URL(coordinator._build_request_url('4320'))))}\Z"
            ),
            json=_flat_registration_forecast(schema_version),
        )
        repeated = await fetch()
        update_entry.assert_called_once()

    assert aioclient_mock.call_count == 2
    second_query = parse_qs(
        urlparse(str(aioclient_mock.mock_calls[1][1])).query,
        keep_blank_values=True,
    )
    assert second_query["registrationData"] == [REGISTRATION_SENTINEL]
    assert second_query["hash"] == ["fresh-hash"]
    assert second_query["currentBatteryCapacity"] == ["4320"]
    assert repeated.forecast_freshness is ForecastFreshness.FRESH
    assert repeated.registration_data is None
    assert coordinator.registration_data == REGISTRATION_SENTINEL
    assert mock_config_entry.data == {
        **original_entry,
        CONF_HASH: "fresh-hash",
        CONF_REGISTRATION_DATA: REGISTRATION_SENTINEL,
    }


@pytest.mark.parametrize("schema_version", (5, 6))
@pytest.mark.parametrize("fetch_path", ("normal", "virtual"))
async def test_schema56_registration_data_rotates_without_hash_change(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    aioclient_mock,
    schema_version: int,
    fetch_path: str,
) -> None:
    """A renewed credential replaces storage even when the plan hash is stable."""
    hass.states.async_set(entry_data["battery_capacity_sensor"], "4320")
    original_entry = dict(mock_config_entry.data)
    coordinator = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
    )
    fetch = (
        coordinator._async_update_data
        if fetch_path == "normal"
        else coordinator.async_fetch_sandbox_forecast
    )
    renewed = f"{REGISTRATION_SENTINEL} renewed"
    with patch.object(
        hass.config_entries,
        "async_update_entry",
        wraps=hass.config_entries.async_update_entry,
    ) as update_entry:
        for credential in (REGISTRATION_SENTINEL, renewed):
            payload = _flat_registration_forecast(schema_version)
            payload["registrationData"] = f" {credential} "
            aioclient_mock.get(
                re.compile(
                    r"\A"
                    rf"{re.escape(str(URL(coordinator._build_request_url('4320'))))}\Z"
                ),
                json=payload,
            )
            snapshot = await fetch()
            assert snapshot.forecast_freshness is ForecastFreshness.FRESH
            assert snapshot.registration_data == credential
            assert coordinator.registration_data == credential
            assert mock_config_entry.data[CONF_REGISTRATION_DATA] == credential
            assert coordinator.last_hash == "fresh-hash"
            assert mock_config_entry.data[CONF_HASH] == "fresh-hash"
        assert update_entry.call_count == 2
        aioclient_mock.get(
            re.compile(
                rf"\A{re.escape(str(URL(coordinator._build_request_url('4320'))))}\Z"
            ),
            json=_flat_registration_forecast(schema_version),
        )
        await fetch()
        assert update_entry.call_count == 2

    assert aioclient_mock.call_count == 3
    queries = [
        parse_qs(urlparse(str(call[1])).query, keep_blank_values=True)
        for call in aioclient_mock.mock_calls
    ]
    assert [query["registrationData"] for query in queries] == [
        [""], [REGISTRATION_SENTINEL], [renewed],
    ]
    assert [query["hash"] for query in queries] == [
        [""], ["fresh-hash"], ["fresh-hash"],
    ]
    assert all(query["currentBatteryCapacity"] == ["4320"] for query in queries)
    assert mock_config_entry.data == {
        **original_entry,
        CONF_HASH: "fresh-hash",
        CONF_REGISTRATION_DATA: renewed,
    }


@pytest.mark.parametrize("schema_version", (5, 6))
@pytest.mark.parametrize("fetch_path", ("normal", "virtual"))
async def test_schema56_registration_data_survives_coordinator_reload(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    aioclient_mock,
    schema_version: int,
    fetch_path: str,
) -> None:
    """A fresh coordinator reads its credential from the actual persisted entry."""
    hass.states.async_set(entry_data["battery_capacity_sensor"], "4320")
    coordinator = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
    )
    payload = _flat_registration_forecast(schema_version)
    payload["registrationData"] = REGISTRATION_SENTINEL
    aioclient_mock.get(
        re.compile(
            rf"\A{re.escape(str(URL(coordinator._build_request_url('4320'))))}\Z"
        ),
        json=payload,
    )
    fetch = (
        coordinator._async_update_data
        if fetch_path == "normal"
        else coordinator.async_fetch_sandbox_forecast
    )
    await fetch()
    renewed = f"{REGISTRATION_SENTINEL} renewed"
    renewal = _flat_registration_forecast(schema_version)
    renewal["registrationData"] = renewed
    aioclient_mock.get(
        re.compile(
            rf"\A{re.escape(str(URL(coordinator._build_request_url('4320'))))}\Z"
        ),
        json=renewal,
    )
    await fetch()
    persisted_entry = dict(mock_config_entry.data)
    assert persisted_entry[CONF_REGISTRATION_DATA] == renewed
    assert persisted_entry[CONF_HASH] == "fresh-hash"

    reloaded = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        persisted_entry["url"],
        persisted_entry["api_key"],
        persisted_entry["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
        initial_hash=persisted_entry[CONF_HASH],
        initial_registration=persisted_entry[CONF_REGISTRATION_DATA],
    )
    aioclient_mock.get(
        re.compile(
            rf"\A{re.escape(str(URL(reloaded._build_request_url('4320'))))}\Z"
        ),
        json=_flat_registration_forecast(schema_version),
    )
    reload_fetch = (
        reloaded._async_update_data
        if fetch_path == "normal"
        else reloaded.async_fetch_sandbox_forecast
    )
    with patch.object(
        hass.config_entries,
        "async_update_entry",
        wraps=hass.config_entries.async_update_entry,
    ) as update_entry:
        snapshot = await reload_fetch()
        update_entry.assert_not_called()

    assert aioclient_mock.call_count == 3
    query = parse_qs(
        urlparse(str(aioclient_mock.mock_calls[-1][1])).query,
        keep_blank_values=True,
    )
    assert query["registrationData"] == [renewed]
    assert query["hash"] == ["fresh-hash"]
    assert query["currentBatteryCapacity"] == ["4320"]
    assert snapshot.forecast_freshness is ForecastFreshness.FRESH
    assert reloaded.registration_data == renewed
    assert mock_config_entry.data == persisted_entry


@pytest.mark.parametrize("schema_version", (5, 6))
@pytest.mark.parametrize("fetch_path", ("normal", "virtual"))
@pytest.mark.parametrize(
    "metadata",
    (
        pytest.param({}, id="absent"),
        pytest.param({"registrationData": None}, id="null"),
        pytest.param({"registrationData": ""}, id="empty"),
        pytest.param({"registrationData": " \t\n "}, id="whitespace"),
        pytest.param({"registrationData": False}, id="bool"),
        pytest.param({"registrationData": 7}, id="integer"),
        pytest.param({"registrationData": 1.5}, id="float"),
        pytest.param({"registrationData": []}, id="empty-list"),
        pytest.param({"registrationData": ["opaque"]}, id="list"),
        pytest.param({"registrationData": [None]}, id="null-list"),
        pytest.param({"registrationData": ["opaque", None]}, id="mixed-list"),
        pytest.param({"registrationData": {}}, id="empty-mapping"),
        pytest.param({"registrationData": {"opaque": "value"}}, id="mapping"),
    ),
)
async def test_schema56_absent_or_invalid_registration_metadata_keeps_cached_value(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    aioclient_mock,
    schema_version: int,
    fetch_path: str,
    metadata: dict[str, object],
) -> None:
    """Invalid optional metadata accepts the plan without clearing or rewriting."""
    hass.states.async_set(entry_data["battery_capacity_sensor"], "4320")
    coordinator = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
    )
    fetch = (
        coordinator._async_update_data
        if fetch_path == "normal"
        else coordinator.async_fetch_sandbox_forecast
    )
    accepted = _flat_registration_forecast(schema_version)
    accepted["registrationData"] = REGISTRATION_SENTINEL
    aioclient_mock.get(
        re.compile(
            rf"\A{re.escape(str(URL(coordinator._build_request_url('4320'))))}\Z"
        ),
        json=accepted,
    )
    baseline = await fetch()
    persisted_entry = dict(mock_config_entry.data)
    payload = {**_flat_registration_forecast(schema_version), **metadata}
    aioclient_mock.get(
        re.compile(
            rf"\A{re.escape(str(URL(coordinator._build_request_url('4320'))))}\Z"
        ),
        json=payload,
    )

    with patch.object(
        hass.config_entries,
        "async_update_entry",
        wraps=hass.config_entries.async_update_entry,
    ) as update_entry:
        snapshot = await fetch()
        update_entry.assert_not_called()
        assert snapshot.registration_data is None
        assert snapshot.forecast_freshness is ForecastFreshness.FRESH
        assert snapshot.schema5_forecast == baseline.schema5_forecast
        assert snapshot.forecast == baseline.forecast
        assert coordinator.registration_data == REGISTRATION_SENTINEL
        assert mock_config_entry.data == persisted_entry

        # The same registered HTTP response also checks the next actual request.
        await fetch()
        update_entry.assert_not_called()

    assert aioclient_mock.call_count == 3
    for call in aioclient_mock.mock_calls[1:]:
        query = parse_qs(urlparse(str(call[1])).query, keep_blank_values=True)
        assert query["registrationData"] == [REGISTRATION_SENTINEL]
        assert query["hash"] == ["fresh-hash"]
        assert query["currentBatteryCapacity"] == ["4320"]
    assert coordinator.registration_data == REGISTRATION_SENTINEL
    assert mock_config_entry.data == persisted_entry


@pytest.mark.parametrize("schema_version", (5, 6))
@pytest.mark.parametrize("fetch_path", ("normal", "virtual"))
@pytest.mark.parametrize("rejection", ("malformed", "unauthorized", "http-failure"))
async def test_schema56_rejected_responses_do_not_replace_registration_data(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    aioclient_mock,
    schema_version: int,
    fetch_path: str,
    rejection: str,
) -> None:
    """Rejected HTTP/plan metadata never replaces an already accepted credential."""
    hass.states.async_set(entry_data["battery_capacity_sensor"], "4320")
    coordinator = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
    )
    fetch = (
        coordinator._async_update_data
        if fetch_path == "normal"
        else coordinator.async_fetch_sandbox_forecast
    )
    accepted = _flat_registration_forecast(schema_version)
    accepted["registrationData"] = REGISTRATION_SENTINEL
    aioclient_mock.get(
        re.compile(
            rf"\A{re.escape(str(URL(coordinator._build_request_url('4320'))))}\Z"
        ),
        json=accepted,
    )
    await fetch()
    persisted_entry = dict(mock_config_entry.data)
    replacement = f"{REGISTRATION_SENTINEL} rejected"
    offered = _flat_registration_forecast(schema_version)
    offered["registrationData"] = replacement
    status = 200
    if rejection == "malformed":
        offered.pop("planId")
    elif rejection == "unauthorized":
        status = 401
        offered = {
            "AuthorizationStatus": "unauthorized",
            "registrationData": replacement,
        }
    else:
        status = 500
    aioclient_mock.get(
        re.compile(
            rf"\A{re.escape(str(URL(coordinator._build_request_url('4320'))))}\Z"
        ),
        json=offered,
        status=status,
    )

    with patch.object(
        hass.config_entries,
        "async_update_entry",
        wraps=hass.config_entries.async_update_entry,
    ) as update_entry:
        if rejection == "unauthorized":
            stale = await fetch()
            assert stale.forecast_freshness is ForecastFreshness.STALE
            assert stale.direct_forecast is None
            assert stale.schema5_forecast is not None and stale.schema5_forecast.stale
            assert stale.trial["authorization_status"] == "unauthorized"
        else:
            reason = (
                "Malformed schema-5 forecast"
                if rejection == "malformed"
                else "API returned status 500"
            )
            with pytest.raises(UpdateFailed, match=reason):
                await fetch()
            assert coordinator.data.forecast_freshness is ForecastFreshness.STALE
            assert coordinator.data.direct_forecast is None
        update_entry.assert_not_called()
        assert coordinator.registration_data == REGISTRATION_SENTINEL
        assert mock_config_entry.data == persisted_entry
        rejected_query = parse_qs(
            urlparse(str(aioclient_mock.mock_calls[-1][1])).query,
            keep_blank_values=True,
        )
        assert rejected_query["registrationData"] == [REGISTRATION_SENTINEL]
        assert aioclient_mock.call_count == 2

        rejected_calls = tuple(aioclient_mock.mock_calls)
        aioclient_mock.clear_requests()
        aioclient_mock.get(
            re.compile(
                rf"\A{re.escape(str(URL(coordinator._build_request_url('4320'))))}\Z"
            ),
            json=_flat_registration_forecast(schema_version),
        )
        recovered = await fetch()
        update_entry.assert_not_called()

    assert aioclient_mock.call_count == 1
    all_calls = [*rejected_calls, *aioclient_mock.mock_calls]
    assert len(all_calls) == 3
    queries = [
        parse_qs(urlparse(str(call[1])).query, keep_blank_values=True)
        for call in all_calls
    ]
    assert [query["registrationData"] for query in queries] == [
        [""], [REGISTRATION_SENTINEL], [REGISTRATION_SENTINEL],
    ]
    assert [query["hash"] for query in queries] == [
        [""], ["fresh-hash"], ["fresh-hash"],
    ]
    assert all(query["currentBatteryCapacity"] == ["4320"] for query in queries)
    query = parse_qs(
        urlparse(str(aioclient_mock.mock_calls[-1][1])).query,
        keep_blank_values=True,
    )
    assert query["registrationData"] == [REGISTRATION_SENTINEL]
    assert query["hash"] == ["fresh-hash"]
    assert query["currentBatteryCapacity"] == ["4320"]
    assert recovered.forecast_freshness is ForecastFreshness.FRESH
    assert recovered.registration_data is None
    assert coordinator.registration_data == REGISTRATION_SENTINEL
    assert mock_config_entry.data == persisted_entry


@pytest.mark.parametrize("schema_version", (5, 6))
@pytest.mark.parametrize("fetch_path", ("normal", "virtual"))
async def test_schema56_cached_registration_is_not_exposed_by_sensors_or_logs(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    aioclient_mock,
    caplog,
    schema_version: int,
    fetch_path: str,
) -> None:
    """Real credential reuse stays out of public forecast, sensor and DEBUG logs."""
    hass.states.async_set(entry_data["battery_capacity_sensor"], "4320")
    coordinator = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
    )
    fetch = (
        coordinator._async_update_data
        if fetch_path == "normal"
        else coordinator.async_fetch_sandbox_forecast
    )
    payload = _flat_registration_forecast(schema_version)
    payload["registrationData"] = REGISTRATION_SENTINEL
    aioclient_mock.get(
        re.compile(
            rf"\A{re.escape(str(URL(coordinator._build_request_url('4320'))))}\Z"
        ),
        json=payload,
    )
    with caplog.at_level(logging.DEBUG):
        snapshot = await fetch()
        coordinator.async_set_updated_data(snapshot)
        sensor = ForecastDetailSensor(
            coordinator, mock_config_entry.entry_id, SANDBOX_ENVIRONMENT
        )
        accepted_sensor_output = (sensor.native_value, sensor.extra_state_attributes)
        aioclient_mock.get(
            re.compile(
                rf"\A{re.escape(str(URL(coordinator._build_request_url('4320'))))}\Z"
            ),
            json=_flat_registration_forecast(schema_version),
        )
        repeated = await fetch()
        coordinator.async_set_updated_data(repeated)
        public_output = (sensor.native_value, sensor.extra_state_attributes)

    assert aioclient_mock.call_count == 2
    query = parse_qs(
        urlparse(str(aioclient_mock.mock_calls[-1][1])).query,
        keep_blank_values=True,
    )
    assert query["registrationData"] == [REGISTRATION_SENTINEL]
    assert snapshot.registration_data == REGISTRATION_SENTINEL
    assert coordinator.registration_data == REGISTRATION_SENTINEL
    assert snapshot.forecast_freshness is ForecastFreshness.FRESH
    assert repeated.forecast_freshness is ForecastFreshness.FRESH
    assert snapshot.schema5_forecast is not None
    assert snapshot.direct_forecast is not None
    assert snapshot.direct_forecast.registration_data == ""
    assert sensor.native_value == len(snapshot.forecast_periods) > 0
    assert accepted_sensor_output == public_output
    assert public_output[1]["forecast"] == snapshot.schema5_forecast.to_dict()
    assert REGISTRATION_SENTINEL not in repr(public_output)
    assert REGISTRATION_SENTINEL not in repr(
        (
            snapshot.forecast,
            snapshot.schema5_forecast.to_dict(),
            snapshot.direct_forecast,
            snapshot.forecast_periods,
            snapshot.registration,
        )
    )
    messages = [record.getMessage() for record in caplog.records]
    assert REGISTRATION_SENTINEL not in "\n".join(messages)
    assert quote_plus(REGISTRATION_SENTINEL) not in "\n".join(messages)
    request_messages = [
        message
        for message in messages
        if message.startswith("Requesting HorizonIQ forecast")
    ]
    if fetch_path == "normal":
        assert len(request_messages) == 2
    for message in request_messages:
        assert "registrationData=" not in message
        assert "code=" not in message
        assert "?" not in message
        assert "#" not in message
        assert "https://example.com/api/Forecast_Get" in message


def _schema6_payload(*, hash_value: str = "fresh-hash") -> dict[str, object]:
    """Return the complete schema-6 response shape used at the HTTP boundary."""
    forecast = json.loads(FIXTURE.read_text(encoding="utf-8"))
    forecast["schemaVersion"] = 6
    forecast["shouldExport"] = False
    periods = forecast["periods"]
    assert isinstance(periods, list)
    for period in periods:
        assert isinstance(period, dict)
        period["shouldExport"] = False
    return {"Hash": hash_value, "Forecast": forecast}


def _legacy_direct_payload() -> dict[str, object]:
    """Return the supported snake-case schema-version legacy wire shape."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["schema_version"] = payload.pop("schemaVersion")
    return payload


async def test_sandbox_forecast_request_has_no_client_control_capability(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
) -> None:
    """The generic forecast request never declares a downstream control target."""
    coordinator = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
    )

    assert "executionTarget=" not in coordinator._build_request_url("53")
    coordinator._url = (
        f"{entry_data['url']}&executionTarget=forged&execution_target=forged"
    )
    assert "executionTarget=" not in coordinator._build_request_url("53")
    assert "execution_target=" not in coordinator._build_request_url("53")


async def test_coordinator_updates_cached_values_from_api(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    aioclient_mock,
) -> None:
    """A legacy diagnostic refreshes registration data but not its hash."""
    hass.states.async_set(entry_data["battery_capacity_sensor"], "53")
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={
            **mock_config_entry.data,
            CONF_HASH: "old-hash",
            CONF_REGISTRATION_DATA: (
                '{"id":"registration-1","ForecastCadenceMinutes":5}'
            ),
        },
    )

    coordinator = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
        initial_hash="old-hash",
        initial_registration='{"id":"registration-1","ForecastCadenceMinutes":5}',
    )

    url = coordinator._build_request_url("53")
    aioclient_mock.get(
        url,
        json={
            "Hash": "new-hash",
            "RegistrationData": (
                '{"id":"registration-2","DynamicCharging":true,'
                '"ForecastCadenceMinutes":1}'
            ),
            "Currency": "GBP",
            "TargetCapacity": "57.5",
            "Forecast": {
                "RegistrationId": "registration-2",
                "Date": "2026-03-07T10:00:00+00:00",
                "Periods": [
                    {
                        "Period": 1,
                        "Date": "2026-03-07T10:00:00+00:00",
                        "BatteryManagementSystemState": "charging",
                    }
                ],
            },
        },
    )

    with patch.object(
        hass.config_entries,
        "async_update_entry",
        wraps=hass.config_entries.async_update_entry,
    ) as update_entry:
        snapshot = await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert snapshot == HorizonIQSnapshot(
        forecast={
            "registration_id": "registration-2",
            "date": "2026-03-07T10:00:00+00:00",
            "hash": "new-hash",
            "periods": [
                {
                    "period": 1,
                    "date": "2026-03-07T10:00:00+00:00",
                    "battery_management_system_state": "charging",
                }
            ],
            "registration_data": (
                '{"id":"registration-2","DynamicCharging":true,'
                '"ForecastCadenceMinutes":1}'
            ),
            "currency": "GBP",
            "target_capacity": 57.5,
        },
        forecast_periods=[
            {
                "period": 1,
                "date": "2026-03-07T10:00:00+00:00",
                "battery_management_system_state": "charging",
            }
        ],
        registration={
            "id": "registration-2",
            "DynamicCharging": True,
            "ForecastCadenceMinutes": 1,
        },
        currency="GBP",
        target_capacity=57.5,
        forecast_hash="new-hash",
        registration_data=(
            '{"id":"registration-2","DynamicCharging":true,'
            '"ForecastCadenceMinutes":1}'
        ),
        forecast_cadence_minutes=1,
        forecast_freshness=ForecastFreshness.MISSING,
        publication_sequence=1,
    )
    assert coordinator.last_hash == "old-hash"
    assert coordinator.registration_data == (
        '{"id":"registration-2","DynamicCharging":true,"ForecastCadenceMinutes":1}'
    )
    assert coordinator.currency == "GBP"
    assert coordinator.target_capacity == 57.5
    assert coordinator.forecast_cadence_minutes == 1
    assert coordinator.effective_forecast_cadence_minutes == 1
    assert coordinator.update_interval == timedelta(minutes=1)
    assert coordinator.forecast["date"] == "2026-03-07T10:00:00+00:00"
    assert coordinator.forecast_periods == [
        {
            "period": 1,
            "date": "2026-03-07T10:00:00+00:00",
            "battery_management_system_state": "charging",
        }
    ]
    assert mock_config_entry.data[CONF_HASH] == "old-hash"
    assert mock_config_entry.data[CONF_REGISTRATION_DATA] == (
        '{"id":"registration-2","DynamicCharging":true,"ForecastCadenceMinutes":1}'
    )
    update_entry.assert_called_once_with(
        mock_config_entry,
        data={
            **entry_data,
            CONF_HASH: "old-hash",
            CONF_REGISTRATION_DATA: (
                '{"id":"registration-2","DynamicCharging":true,'
                '"ForecastCadenceMinutes":1}'
            ),
        },
    )


async def test_schema6_envelope_hash_persists_and_is_sent_on_the_next_request(
    hass, mock_config_entry, entry_data: dict[str, str], aioclient_mock
) -> None:
    """A valid response-envelope hash reaches cache, entry storage and next URL."""
    coordinator = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
    )
    hass.states.async_set(entry_data["battery_capacity_sensor"], "4320")
    first_url = coordinator._build_request_url("4320")
    assert first_url.endswith("currentBatteryCapacity=4320&hash=&registrationData=")
    aioclient_mock.get(first_url, json=_schema6_payload(hash_value=" fresh-hash "))

    with patch.object(
        hass.config_entries,
        "async_update_entry",
        wraps=hass.config_entries.async_update_entry,
    ) as update_entry:
        snapshot = await coordinator._async_update_data()
        assert aioclient_mock.call_count == 1

        next_url = coordinator._build_request_url("4320")
        assert next_url == first_url.replace("hash=&", "hash=fresh-hash&")
        aioclient_mock.get(next_url, json=_schema6_payload())
        repeated = await coordinator._async_update_data()

    assert snapshot.forecast_freshness is ForecastFreshness.FRESH
    assert snapshot.forecast_hash == "fresh-hash"
    assert snapshot.publication_sequence == 1
    assert repeated.publication_sequence == 2
    assert aioclient_mock.call_count == 2
    assert coordinator.last_hash == mock_config_entry.data[CONF_HASH] == "fresh-hash"
    assert "hash=fresh-hash" in coordinator._build_request_url("4320")
    update_entry.assert_called_once()


async def test_stale_response_keeps_cached_hash_and_publishes_non_executable_stale_snapshot(
    hass, mock_config_entry, entry_data: dict[str, str]
) -> None:
    """Transport failure after a fresh response retains diagnostics and cache only."""
    hass.states.async_set(entry_data["battery_capacity_sensor"], "4320")
    coordinator = HorizonIQCoordinator(
        hass, mock_config_entry, entry_data["url"], entry_data["api_key"],
        entry_data["battery_capacity_sensor"], SANDBOX_ENVIRONMENT,
        initial_registration="accepted-registration-data",
    )
    fresh = coordinator._commit_snapshot_publication(
        coordinator._build_snapshot_or_stale(_schema6_payload())
    )
    coordinator.async_set_updated_data(fresh)
    coordinator._update_cached_state(fresh)
    coordinator._persist_state()
    accepted = fresh.schema5_forecast
    assert accepted is not None

    coordinator._fetch_payload = AsyncMock(side_effect=UpdateFailed("timeout"))  # type: ignore[method-assign]
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    stale = coordinator.data
    assert stale.forecast_freshness is ForecastFreshness.STALE
    assert stale.direct_forecast is None
    assert stale.schema5_forecast is not None and stale.schema5_forecast.stale is True
    assert stale.schema5_forecast.current_capacity == accepted.current_capacity
    assert coordinator.last_hash == mock_config_entry.data[CONF_HASH] == "fresh-hash"
    assert coordinator.registration_data == "accepted-registration-data"
    assert mock_config_entry.data[CONF_REGISTRATION_DATA] == "accepted-registration-data"
    assert "hash=fresh-hash" in coordinator._build_request_url("4320")


async def test_malformed_schema6_after_history_publishes_stale_once_then_fails_each_fetch_path(
    hass, mock_config_entry, entry_data: dict[str, str], aioclient_mock
) -> None:
    """Malformed history publishes stale once per caller, then propagates failure."""
    hass.states.async_set(entry_data["battery_capacity_sensor"], "4320")
    coordinator = HorizonIQCoordinator(
        hass, mock_config_entry, entry_data["url"], entry_data["api_key"],
        entry_data["battery_capacity_sensor"], SANDBOX_ENVIRONMENT,
        initial_registration="accepted-registration-data",
    )
    fresh_url = coordinator._build_request_url("4320")
    aioclient_mock.get(fresh_url, json=_schema6_payload())
    fresh = await coordinator._async_update_data()
    coordinator.async_set_updated_data(fresh)
    aioclient_mock.clear_requests()
    malformed = _schema6_payload()
    forecast = malformed["Forecast"]
    assert isinstance(forecast, dict)
    periods = forecast["periods"]
    assert isinstance(periods, list) and periods
    assert isinstance(periods[0], dict)
    periods[0]["period"] = "not-an-integer"
    malformed["RegistrationData"] = "unsafe-registration-data"
    malformed_url = coordinator._build_request_url("4320")
    aioclient_mock.get(malformed_url, json=malformed)
    listener = MagicMock()
    coordinator.async_add_listener(listener)

    with pytest.raises(UpdateFailed, match="Malformed schema-5 forecast"):
        await coordinator._async_update_data()
    normal_stale = coordinator.data

    with pytest.raises(UpdateFailed, match="Malformed schema-5 forecast"):
        await coordinator.async_fetch_sandbox_forecast()
    explicit_stale = coordinator.data

    assert normal_stale.forecast_freshness is ForecastFreshness.STALE
    assert normal_stale.direct_forecast is None
    assert normal_stale.schema5_forecast is not None and normal_stale.schema5_forecast.stale
    assert explicit_stale.forecast_freshness is ForecastFreshness.STALE
    assert explicit_stale.direct_forecast is None
    assert explicit_stale.publication_sequence == normal_stale.publication_sequence + 1
    assert listener.call_count == 2
    assert coordinator.last_hash == mock_config_entry.data[CONF_HASH] == "fresh-hash"
    assert coordinator.registration_data == "accepted-registration-data"
    assert mock_config_entry.data[CONF_REGISTRATION_DATA] == "accepted-registration-data"


async def test_absent_schema_or_authorization_diagnostic_after_history_is_stale_but_initial_is_missing(
    hass, mock_config_entry, entry_data: dict[str, str]
) -> None:
    """Diagnostic-only successful payloads preserve the initial/history matrix."""
    coordinator = HorizonIQCoordinator(
        hass, mock_config_entry, entry_data["url"], entry_data["api_key"],
        entry_data["battery_capacity_sensor"], SANDBOX_ENVIRONMENT,
    )
    initial = coordinator._build_snapshot_or_stale({"AuthorizationStatus": "unauthorized"})
    assert initial.forecast_freshness is ForecastFreshness.MISSING

    coordinator._build_snapshot_or_stale(_schema6_payload())
    after_history = coordinator._build_snapshot_or_stale({"AuthorizationStatus": "unauthorized"})
    assert after_history.forecast_freshness is ForecastFreshness.STALE
    assert after_history.direct_forecast is None


async def test_legacy_direct_capable_response_remains_fresh_with_or_without_schema_history(
    hass, mock_config_entry, entry_data: dict[str, str]
) -> None:
    """The supported snake-case schema alias retains its schema-parser path."""
    coordinator = HorizonIQCoordinator(
        hass, mock_config_entry, entry_data["url"], entry_data["api_key"],
        entry_data["battery_capacity_sensor"], SANDBOX_ENVIRONMENT,
    )
    legacy = _legacy_direct_payload()
    first = coordinator._build_snapshot_or_stale(legacy)
    coordinator._build_snapshot_or_stale(_schema6_payload())
    second = coordinator._build_snapshot_or_stale(legacy)

    assert first.forecast_freshness is second.forecast_freshness is ForecastFreshness.FRESH
    assert first.direct_forecast is not None and second.direct_forecast is not None
    assert first.schema5_forecast is not None and second.schema5_forecast is not None


@pytest.mark.parametrize("uncommitted_sequence", (False, 0.0))
async def test_commit_rejects_non_integer_uncommitted_sequence_without_state_change(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    uncommitted_sequence: object,
) -> None:
    """Only the actual integer zero denotes an uncommitted publication."""
    coordinator = HorizonIQCoordinator(
        hass, mock_config_entry, entry_data["url"], entry_data["api_key"],
        entry_data["battery_capacity_sensor"], SANDBOX_ENVIRONMENT,
    )
    before = (coordinator._publication_sequence, coordinator._latest_snapshot)

    with pytest.raises(RuntimeError, match="publication sequence"):
        coordinator._commit_snapshot_publication(
            HorizonIQSnapshot(publication_sequence=uncommitted_sequence)  # type: ignore[arg-type]
        )

    assert (coordinator._publication_sequence, coordinator._latest_snapshot) == before


async def test_exact_subscription_failure_clears_persisted_hash_but_never_publishes_executable_control(
    hass, mock_config_entry, entry_data: dict[str, str]
) -> None:
    """Entitlement loss is the sole terminal cache-clear path and is non-executable."""
    coordinator = HorizonIQCoordinator(
        hass, mock_config_entry, entry_data["url"], entry_data["api_key"],
        entry_data["battery_capacity_sensor"], SANDBOX_ENVIRONMENT,
    )
    fresh = coordinator._commit_snapshot_publication(
        coordinator._build_snapshot_or_stale(_schema6_payload())
    )
    coordinator.async_set_updated_data(fresh)
    coordinator._update_cached_state(fresh)
    coordinator._persist_state()

    coordinator._handle_subscription_loss()

    assert coordinator.last_hash == mock_config_entry.data[CONF_HASH] == ""
    assert coordinator.data.forecast_freshness is ForecastFreshness.STALE
    assert coordinator.data.direct_forecast is None
    assert coordinator.data.publication_sequence == 2


async def test_coordinator_cancellation_does_not_publish_or_increment_sequence(
    hass, mock_config_entry, entry_data: dict[str, str]
) -> None:
    """Caller cancellation stays outside stale publication and cache mutation paths."""
    coordinator = HorizonIQCoordinator(
        hass, mock_config_entry, entry_data["url"], entry_data["api_key"],
        entry_data["battery_capacity_sensor"], SANDBOX_ENVIRONMENT,
    )
    coordinator._fetch_payload = AsyncMock(side_effect=asyncio.CancelledError())  # type: ignore[method-assign]

    with pytest.raises(asyncio.CancelledError):
        await coordinator._async_update_data()

    assert coordinator._publication_sequence == 0
    assert coordinator._latest_snapshot == HorizonIQSnapshot()


async def test_clear_registration_data_persists_and_refreshes(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
) -> None:
    """Manual clear removes cached registration data and requests a refresh."""
    coordinator = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
        initial_hash="existing-hash",
        initial_registration='{"id":"registration-1","ForecastCadenceMinutes":5}',
    )
    coordinator.async_request_refresh = AsyncMock()

    await coordinator.async_clear_registration_data()
    await hass.async_block_till_done()

    assert coordinator.registration_data == ""
    assert coordinator.forecast_cadence_minutes is None
    assert coordinator.effective_forecast_cadence_minutes == 5
    assert coordinator.update_interval == timedelta(minutes=5)
    assert mock_config_entry.data[CONF_REGISTRATION_DATA] == ""
    coordinator.async_request_refresh.assert_awaited_once()


async def test_sandbox_pause_prevents_forecast_http_after_initial_failure(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
) -> None:
    """A paused sandbox never retries the cloud endpoint without prior data."""
    coordinator = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
    )
    coordinator._fetch_payload = AsyncMock(  # type: ignore[method-assign]
        side_effect=AssertionError("Sandbox pause must prevent HTTP")
    )

    await coordinator.async_pause_for_sandbox()
    snapshot = await coordinator._async_update_data()

    assert snapshot == HorizonIQSnapshot()
    coordinator._fetch_payload.assert_not_awaited()


async def test_clear_registration_data_preserves_hash_and_makes_one_request(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    aioclient_mock,
) -> None:
    """The explicit refresh clears registration data without repeating a forecast."""
    hass.states.async_set(entry_data["battery_capacity_sensor"], "53")
    coordinator = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
        initial_hash="existing-hash",
        initial_registration="existing-registration",
    )
    cleared_url = coordinator._build_request_url("53").replace(
        "registrationData=existing-registration", "registrationData="
    )
    aioclient_mock.get(cleared_url, json={})

    await coordinator.async_clear_registration_data()

    assert coordinator.last_hash == "existing-hash"
    assert coordinator.registration_data == ""
    assert mock_config_entry.data[CONF_HASH] == "existing-hash"
    assert mock_config_entry.data[CONF_REGISTRATION_DATA] == ""
    assert len(aioclient_mock.mock_calls) == 1


async def test_forecast_request_sends_trial_headers_when_configured(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    aioclient_mock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Forecast requests include app-trial device headers when configured."""
    token = "portal-trial-token"
    hass.states.async_set(entry_data["battery_capacity_sensor"], "53")
    caplog.set_level("DEBUG", logger="custom_components.horizoniq.coordinator")

    coordinator = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
        forecast_device_id=" gx-device-1 ",
        forecast_device_token=f" {token} ",
    )

    aioclient_mock.get(coordinator._build_request_url("53"), json={})

    await coordinator._async_update_data()

    _, request_url, _, headers = aioclient_mock.mock_calls[-1]
    assert headers == {
        HEADER_API_KEY: entry_data["api_key"],
        HEADER_FORECAST_DEVICE_ID: "gx-device-1",
        HEADER_FORECAST_DEVICE_TOKEN: token,
    }
    assert HEADER_FORECAST_DEVICE_ID not in request_url.query
    assert HEADER_FORECAST_DEVICE_TOKEN not in request_url.query
    assert "deviceKind" not in request_url.query
    assert "integrationSource" not in request_url.query
    assert "deviceKind" not in headers
    assert "integrationSource" not in headers
    assert token not in caplog.text
    assert "gx-device-1" not in caplog.text


async def test_forecast_request_omits_trial_headers_when_blank(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    aioclient_mock,
) -> None:
    """Blank app-trial binding values are not sent as headers or query params."""
    hass.states.async_set(entry_data["battery_capacity_sensor"], "53")

    coordinator = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
        forecast_device_id=" ",
        forecast_device_token="",
    )

    aioclient_mock.get(coordinator._build_request_url("53"), json={})

    await coordinator._async_update_data()

    _, request_url, _, headers = aioclient_mock.mock_calls[-1]
    assert headers == {HEADER_API_KEY: entry_data["api_key"]}
    assert HEADER_FORECAST_DEVICE_ID not in request_url.query
    assert HEADER_FORECAST_DEVICE_TOKEN not in request_url.query
    assert "deviceKind" not in request_url.query
    assert "integrationSource" not in request_url.query
    assert "deviceKind" not in headers
    assert "integrationSource" not in headers


async def test_forecast_request_uses_separate_function_key(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    aioclient_mock,
) -> None:
    """Bootstrap entries store endpoint and function key separately."""
    hass.states.async_set(entry_data["battery_capacity_sensor"], "53")

    coordinator = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        "https://example.com/api/Forecast_Get",
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
        forecast_function_key="returned-function-key",
    )

    aioclient_mock.get(coordinator._build_request_url("53"), json={})

    await coordinator._async_update_data()

    _, request_url, _, _headers = aioclient_mock.mock_calls[-1]
    assert request_url.query["code"] == "returned-function-key"


async def test_forecast_auth_failure_refreshes_key_and_retries_once(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    aioclient_mock,
) -> None:
    """Bootstrap entries refresh credentials once after function-key rejection."""
    hass.states.async_set(entry_data["battery_capacity_sensor"], "53")
    endpoint = "https://example.com/api/Forecast_Get"
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={
            **mock_config_entry.data,
            CONF_URL: endpoint,
            CONF_FORECAST_FUNCTION_KEY: "old-function-key",
        },
    )

    async def refresh_credentials() -> bool:
        hass.config_entries.async_update_entry(
            mock_config_entry,
            data={
                **mock_config_entry.data,
                CONF_URL: endpoint,
                CONF_FORECAST_FUNCTION_KEY: "new-function-key",
            },
        )
        return True

    credential_refresh = AsyncMock(side_effect=refresh_credentials)
    coordinator = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        endpoint,
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
        forecast_function_key="old-function-key",
        credential_refresh=credential_refresh,
    )

    first_url = coordinator._build_request_url("53")
    aioclient_mock.get(first_url, status=403, json={"message": "Forbidden"})

    retry_url = str(first_url).replace("old-function-key", "new-function-key")
    aioclient_mock.get(retry_url, json={"Forecast": {"Periods": []}})

    snapshot = await coordinator._async_update_data()

    credential_refresh.assert_awaited_once()
    assert snapshot.forecast_periods == []
    _, request_url, _, _headers = aioclient_mock.mock_calls[-1]
    assert request_url.query["code"] == "new-function-key"


async def test_coordinator_uses_trial_payload_from_unauthorized_response(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    aioclient_mock,
) -> None:
    """A 401 carrying trial state still produces a usable coordinator snapshot."""
    hass.states.async_set(entry_data["battery_capacity_sensor"], "53")

    coordinator = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
        forecast_device_id="gx-device-1",
        forecast_device_token="trial-token",
    )

    aioclient_mock.get(
        coordinator._build_request_url("53"),
        status=401,
        json={
            "hasTrial": True,
            "isActive": False,
            "isEligible": False,
            "status": "expired",
            "forecastCadenceMinutes": 30,
        },
    )

    snapshot = await coordinator._async_update_data()

    assert snapshot.trial == {
        "has_trial": True,
        "is_active": False,
        "is_eligible": False,
        "status": "expired",
        "forecast_cadence_minutes": 30,
        "authorization_status": "unauthorized",
        "authorization_status_code": 401,
        "authorization_message": (
            "Forecast request was rejected with HTTP 401 Unauthorized."
        ),
    }
    assert snapshot.forecast["trial_status"] == "expired"
    assert coordinator.forecast_cadence_minutes == 30
    assert coordinator.update_interval == timedelta(minutes=30)


async def test_coordinator_uses_diagnostic_payload_from_plain_unauthorized_response(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    aioclient_mock,
) -> None:
    """A plain 401 still creates diagnostic state instead of blocking setup."""
    hass.states.async_set(entry_data["battery_capacity_sensor"], "53")

    coordinator = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
        forecast_device_id="gx-device-1",
        forecast_device_token="trial-token",
    )

    aioclient_mock.get(
        coordinator._build_request_url("53"),
        status=401,
        json={"status": 401, "message": "Unauthorized"},
    )

    snapshot = await coordinator._async_update_data()

    assert snapshot.trial == {
        "authorization_status": "unauthorized",
        "authorization_status_code": 401,
        "authorization_message": (
            "Forecast request was rejected with HTTP 401 Unauthorized."
        ),
    }
    assert snapshot.forecast["authorization_status"] == "unauthorized"
    assert snapshot.forecast_periods == []


async def test_coordinator_initial_failures_follow_retry_schedule(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
) -> None:
    """Initial forecast failures use the coordinator-owned retry schedule."""
    hass.states.async_set(entry_data["battery_capacity_sensor"], "53")

    coordinator = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
    )

    coordinator._fetch_payload = AsyncMock(  # type: ignore[method-assign]
        side_effect=UpdateFailed("API returned status 500")
    )

    retry_delays = []
    for _ in range(len(INITIAL_FORECAST_RETRY_SECONDS) + 2):
        with pytest.raises(UpdateFailed) as exc_info:
            await coordinator._async_update_data()
        retry_delays.append(exc_info.value.retry_after)

    assert retry_delays == [*INITIAL_FORECAST_RETRY_SECONDS, 480, 480]


@pytest.mark.parametrize("status", [500, 429])
async def test_coordinator_initial_http_failures_make_one_request_and_ignore_retry_after(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    aioclient_mock,
    status: int,
) -> None:
    """HTTP failures are scheduled once by the coordinator, not by the server."""
    hass.states.async_set(entry_data["battery_capacity_sensor"], "53")
    coordinator = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
    )
    request_url = coordinator._build_request_url("53")
    aioclient_mock.get(
        request_url,
        status=status,
        headers={"Retry-After": "3600"},
    )

    with pytest.raises(UpdateFailed) as exc_info:
        await coordinator._async_update_data()

    assert exc_info.value.retry_after == INITIAL_FORECAST_RETRY_SECONDS[0]
    assert len(aioclient_mock.mock_calls) == 1


async def test_coordinator_success_resets_initial_retry_state_and_later_uses_cadence(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    aioclient_mock,
) -> None:
    """A successful forecast switches failures to the backend cadence."""
    hass.states.async_set(entry_data["battery_capacity_sensor"], "53")
    coordinator = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
    )
    request_url = coordinator._build_request_url("53")
    aioclient_mock.get(request_url, status=500)

    with pytest.raises(UpdateFailed) as exc_info:
        await coordinator._async_update_data()
    assert exc_info.value.retry_after == INITIAL_FORECAST_RETRY_SECONDS[0]

    aioclient_mock.clear_requests()
    aioclient_mock.get(request_url, json={"forecastCadenceMinutes": 17})
    await coordinator._async_update_data()

    assert coordinator._has_successful_forecast is True
    assert coordinator._initial_forecast_failures == 0
    assert coordinator.update_interval == timedelta(minutes=17)

    aioclient_mock.clear_requests()
    aioclient_mock.get(request_url, status=500)
    with pytest.raises(UpdateFailed) as exc_info:
        await coordinator._async_update_data()

    assert exc_info.value.retry_after is None


async def test_exact_subscription_failure_stops_polling_and_clears_cache(
    hass,
    mock_config_entry,
    entry_data: dict[str, str],
    aioclient_mock,
) -> None:
    """Exact backend no-subscription body marks the entry terminal."""
    hass.states.async_set(entry_data["battery_capacity_sensor"], "53")

    coordinator = HorizonIQCoordinator(
        hass,
        mock_config_entry,
        entry_data["url"],
        entry_data["api_key"],
        entry_data["battery_capacity_sensor"],
        SANDBOX_ENVIRONMENT,
        initial_hash="old-hash",
        initial_registration="encrypted-registration",
    )

    aioclient_mock.get(
        coordinator._build_request_url("53"),
        status=400,
        text=EXACT_SUBSCRIPTION_FAILURE_BODY,
    )

    with pytest.raises(UpdateFailed) as exc_info:
        await coordinator._async_update_data()

    assert str(exc_info.value) == EXACT_SUBSCRIPTION_FAILURE_BODY
    assert coordinator.update_interval is None
    assert mock_config_entry.data[CONF_SUBSCRIPTION_STATUS] == (
        SUBSCRIPTION_STATUS_NO_SUBSCRIPTION
    )
    assert mock_config_entry.data[CONF_HASH] == ""
    assert mock_config_entry.data[CONF_REGISTRATION_DATA] == ""


async def test_live_virtual_battery_uses_normal_forecast_get_only(hass, mock_config_entry, entry_data, aioclient_mock) -> None:
    """A real virtual runtime uses only its normal authenticated coordinator path."""
    from datetime import datetime, timezone
    from .test_sandbox_runtime import _entry_data, REGISTRATION_ID
    from custom_components.horizoniq.sandbox_runtime import HorizonIQEntryRuntime

    coordinator = HorizonIQCoordinator(hass, mock_config_entry, entry_data["url"], entry_data["api_key"], entry_data["battery_capacity_sensor"], SANDBOX_ENVIRONMENT)
    runtime = HorizonIQEntryRuntime(coordinator, REGISTRATION_ID, mock_config_entry.entry_id)
    runtime.configure_sandbox(_entry_data())
    runtime._live_forecast_now = lambda: datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
    aioclient_mock.get(re.compile(r"https://example.com/api/Forecast_Get\?.*"), json=_flat_registration_forecast(6))
    with patch("custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe", AsyncMock(side_effect=RuntimeError("optional broker unavailable"))):
        await runtime.async_enable(hass)
        assert aioclient_mock.call_count == 1
        assert runtime.selected_direct_action == "charge_required"
        assert runtime.time_source == "wall_clock"
        assert coordinator.last_forecast.plan_kind == "live"
        assert coordinator.last_direct_forecast is not None
        assert urlparse(str(aioclient_mock.mock_calls[0][1])).path == "/api/Forecast_Get"
        await runtime.async_unload()


async def test_removed_replay_endpoint_is_never_called(hass, mock_config_entry, entry_data, aioclient_mock) -> None:
    """The sole HTTP request remains Forecast_Get and no replay API is exposed."""
    coordinator = HorizonIQCoordinator(hass, mock_config_entry, entry_data["url"], entry_data["api_key"], entry_data["battery_capacity_sensor"], SANDBOX_ENVIRONMENT)
    hass.states.async_set(entry_data["battery_capacity_sensor"], "4320")
    aioclient_mock.get(re.compile(r"https://example.com/api/Forecast_Get\?.*"), json=_flat_registration_forecast(6))
    result = await coordinator.async_fetch_sandbox_forecast()
    assert result.forecast_freshness is ForecastFreshness.FRESH
    assert not hasattr(coordinator, "async_fetch_sandbox_replay")
    assert aioclient_mock.call_count == 1
    assert all(urlparse(str(call[1])).path == "/api/Forecast_Get" for call in aioclient_mock.mock_calls)


@pytest.mark.parametrize("version,mode", ((13, "replay"), (14, "manual"), (14, "virtual"), (14, None)))
async def test_restored_paused_modes_suppress_setup_forecast_get(hass, mock_config_entry, entry_data, aioclient_mock, version, mode) -> None:
    """The actual coordinator setup refresh cannot escape a paused restore."""
    from .test_sandbox_runtime import _entry_data, REGISTRATION_ID
    from custom_components.horizoniq.sandbox_runtime import HorizonIQEntryRuntime
    from custom_components.horizoniq.sandbox_storage import SandboxStorage

    coordinator = HorizonIQCoordinator(hass, mock_config_entry, entry_data["url"], entry_data["api_key"], entry_data["battery_capacity_sensor"], SANDBOX_ENVIRONMENT)
    source = HorizonIQEntryRuntime(coordinator, REGISTRATION_ID, mock_config_entry.entry_id)
    source.configure_sandbox(_entry_data())
    record = source._storage_record()
    record.update(storage_schema_version=version, operating_mode=mode, simulator_enabled=False)
    await SandboxStorage(hass, mock_config_entry.entry_id).async_save(record)
    restored = HorizonIQEntryRuntime(coordinator, REGISTRATION_ID, mock_config_entry.entry_id)
    restored.configure_sandbox(_entry_data())
    await restored.async_restore_storage(hass)
    assert not restored.simulator_enabled
    assert coordinator._sandbox_paused
    await coordinator.async_refresh()
    assert aioclient_mock.call_count == 0
    assert coordinator.last_direct_forecast is None
    await restored.async_unload()

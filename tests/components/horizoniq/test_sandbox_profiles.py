"""Tests for entry-owned five-minute local synthetic profiles."""

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.horizoniq.const import (
    CAPACITY_SOURCE_VIRTUAL_BATTERY,
    CONF_CAPACITY_SOURCE,
    CONF_ENVIRONMENT,
    CONF_REGISTRATION_CONFIG,
    CONF_REGISTRATION_ID,
    SANDBOX_ENVIRONMENT,
)
from custom_components.horizoniq.sandbox_runtime import HorizonIQEntryRuntime
from custom_components.horizoniq.simulation.local_profiles import (
    aggregate_half_hours,
    parse_csv_profile,
    parse_json_profile,
)
from custom_components.horizoniq.simulation.models import BatteryConfig


UTC = timezone.utc
REGISTRATION = "11111111-1111-4111-8111-111111111111"
CONFIG = BatteryConfig(10_000, 2_000, 2_000, 2_000)


def _samples(start: datetime = datetime(2026, 3, 29, tzinfo=UTC)) -> list[dict[str, object]]:
    return [
        {
            "timestamp": (start + timedelta(minutes=5 * index)).isoformat(),
            "load_w": 600 + index * 10,
            "solar_w": 100,
            "import_rate_gbp_per_kwh": -0.1 + index * 0.01,
            "export_rate_gbp_per_kwh": 0.05 + index * 0.01,
        }
        for index in range(6)
    ]


def _json_content(samples: list[dict[str, object]]) -> str:
    return json.dumps({"schema_version": 1, "name": "Example", "samples": samples})


def _csv_content(samples: list[dict[str, object]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(samples[0]))
    writer.writeheader()
    writer.writerows(samples)
    return output.getvalue()


def _runtime(entry_id: str) -> HorizonIQEntryRuntime:
    coordinator = MagicMock()
    coordinator.async_pause_for_sandbox = AsyncMock()
    coordinator.async_resume_from_sandbox = AsyncMock()
    runtime = HorizonIQEntryRuntime(coordinator, REGISTRATION, entry_id)
    runtime.configure_sandbox(
        {
            CONF_ENVIRONMENT: SANDBOX_ENVIRONMENT,
            CONF_CAPACITY_SOURCE: CAPACITY_SOURCE_VIRTUAL_BATTERY,
            CONF_REGISTRATION_ID: REGISTRATION,
            CONF_REGISTRATION_CONFIG: {
                "ChargeEfficiency": 0.95,
                "DischargeEfficiency": 0.95,
                "EquipmentProfile": {
                    "BatteryCapacityWh": 10_000,
                    "MinimumCapacityPercentage": 0.2,
                    "MaximumBatteryChargePowerWatts": 2_000,
                    "MaximumBatteryDischargePowerWatts": 2_000,
                },
            },
        }
    )
    return runtime


async def _write_profile(hass, entry_id: str, filename: str, content: str) -> None:
    path = Path(hass.config.path("horizoniq", "profiles", entry_id))
    await hass.async_add_executor_job(
        lambda: path.mkdir(parents=True, exist_ok=True)
    )
    await hass.async_add_executor_job((path / filename).write_text, content, "utf-8")


async def _enable(runtime: HorizonIQEntryRuntime, hass) -> None:
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
        new=AsyncMock(return_value=lambda: None),
    ):
        await runtime.async_enable(hass)


def test_json_csv_and_aggregation_are_canonical_and_pure() -> None:
    """Both documented formats normalize to identical five-minute samples."""
    samples = _samples()
    json_profile = parse_json_profile(_json_content(samples), identifier="a.json", config=CONFIG)
    csv_profile = parse_csv_profile(_csv_content(samples), identifier="a.csv", config=CONFIG)

    assert json_profile.samples == csv_profile.samples
    aggregate = aggregate_half_hours(json_profile)[0]
    assert aggregate.valid_from_utc == datetime.fromisoformat(
        str(samples[0]["timestamp"])
    )
    assert aggregate.expected_load_kwh == sum(item["load_w"] for item in samples) / 12_000
    assert aggregate.import_rate_gbp_per_kwh == sum(item["import_rate_gbp_per_kwh"] for item in samples) / 6


@pytest.mark.parametrize(
    "mutate",
    [
        lambda samples: samples.__setitem__(1, {**samples[1], "timestamp": samples[0]["timestamp"]}),
        lambda samples: samples.__setitem__(0, {**samples[0], "export_rate_gbp_per_kwh": -1}),
        lambda samples: samples.__setitem__(0, {**samples[0], "timestamp": "2026-03-29T00:00:00"}),
    ],
)
def test_profile_validation_rejects_gaps_invalid_rates_and_naive_timestamps(mutate) -> None:
    """Unsafe timing and energy values fail before state can change."""
    samples = _samples()
    mutate(samples)
    with pytest.raises(ValueError):
        parse_json_profile(_json_content(samples), identifier="bad.json", config=CONFIG)


async def test_profile_files_are_entry_scoped_and_playback_splits_boundaries(hass) -> None:
    """One runtime cannot read another's profile and cursor advances per sample."""
    first = _runtime("profile-a")
    second = _runtime("profile-b")
    await first.async_restore_storage(hass)
    await second.async_restore_storage(hass)
    content = _json_content(_samples())
    await _write_profile(hass, "profile-a", "day.json", content)

    assert await first.async_list_profile_filenames() == ("day.json",)
    assert await second.async_list_profile_filenames() == ()
    with pytest.raises(ValueError):
        await first.async_load_profile("../profile-b/day.json")

    await first.async_select_profile("day.json")
    await _enable(first, hass)
    await first.async_start_playback()
    await first.async_step(900)

    assert first.profile_cursor is not None and first.profile_cursor.index == 3
    assert second.profile_cursor is None
    assert first.playback_state == "running"
    await first.async_step(900)
    assert first.playback_state == "completed"
    await first.async_disable()


async def test_changed_profile_pauses_restore_without_mqtt_or_backend(hass) -> None:
    """A changed owned file cannot silently resume persisted playback."""
    runtime = _runtime("profile-restore")
    await runtime.async_restore_storage(hass)
    await _write_profile(hass, "profile-restore", "day.json", _json_content(_samples()))
    await runtime.async_select_profile("day.json")
    await runtime.async_checkpoint(immediate=True)
    await _write_profile(hass, "profile-restore", "day.json", _json_content(_samples(datetime(2026, 3, 30, tzinfo=UTC))))

    reloaded = _runtime("profile-restore")
    with patch(
        "custom_components.horizoniq.sandbox_runtime.mqtt.async_subscribe",
        new=AsyncMock(),
    ) as subscribe:
        await reloaded.async_restore_storage(hass)
    assert reloaded.storage_diagnostic is not None
    assert reloaded.selected_profile_filename is None
    subscribe.assert_not_awaited()

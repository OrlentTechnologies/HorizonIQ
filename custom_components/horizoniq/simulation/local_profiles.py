"""Pure five-minute synthetic profile validation and half-hour aggregation."""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping

from .models import BatteryConfig

PROFILE_SCHEMA_VERSION = 1
SAMPLE_INTERVAL = timedelta(minutes=5)
SAMPLES_PER_HALF_HOUR = 6
MAX_PROFILE_SAMPLES = 8_928
MAX_PROFILE_DURATION = timedelta(days=31)
_ROOT_FIELDS = {"schema_version", "name", "starting_battery_energy_wh", "samples"}
_SAMPLE_FIELDS = {
    "timestamp",
    "load_w",
    "solar_w",
    "import_rate_gbp_per_kwh",
    "export_rate_gbp_per_kwh",
}


@dataclass(frozen=True, slots=True)
class LocalSyntheticSample:
    """One canonical five-minute synthetic input sample."""

    timestamp_utc: datetime
    load_w: float
    solar_w: float
    import_rate_gbp_per_kwh: float
    export_rate_gbp_per_kwh: float


@dataclass(frozen=True, slots=True)
class LocalSyntheticProfile:
    """A validated local replay profile, distinct from backend replay contracts."""

    schema_version: int
    identifier: str
    samples: tuple[LocalSyntheticSample, ...]
    name: str | None = None
    starting_battery_energy_wh: float | None = None


@dataclass(frozen=True, slots=True)
class HalfHourReplayInput:
    """Pure backend-compatible aggregate for a future replay request."""

    valid_from_utc: datetime
    valid_to_utc: datetime
    expected_load_kwh: float
    expected_solar_kwh: float
    import_rate_gbp_per_kwh: float
    export_rate_gbp_per_kwh: float


def parse_json_profile(
    content: str,
    *,
    identifier: str,
    config: BatteryConfig,
) -> LocalSyntheticProfile:
    """Parse and validate the documented JSON profile format."""
    try:
        raw = json.loads(content)
    except json.JSONDecodeError as err:
        raise ValueError("Profile JSON is invalid") from err
    if not isinstance(raw, Mapping) or set(raw) - _ROOT_FIELDS:
        raise ValueError("Profile contains unsupported fields")
    if raw.get("schema_version") != PROFILE_SCHEMA_VERSION:
        raise ValueError("Profile schema version is unsupported")
    samples = raw.get("samples")
    if not isinstance(samples, list):
        raise ValueError("Profile samples are required")
    name = raw.get("name")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        raise ValueError("Profile name is invalid")
    starting = raw.get("starting_battery_energy_wh")
    starting_energy = _number(starting, "starting_battery_energy_wh") if starting is not None else None
    return _build_profile(
        identifier=identifier,
        samples=tuple(_sample_from_mapping(item) for item in samples),
        config=config,
        name=name.strip() if isinstance(name, str) else None,
        starting_battery_energy_wh=starting_energy,
    )


def parse_csv_profile(
    content: str,
    *,
    identifier: str,
    config: BatteryConfig,
) -> LocalSyntheticProfile:
    """Parse and validate the documented CSV profile format."""
    try:
        reader = csv.DictReader(io.StringIO(content))
        if reader.fieldnames is None or set(reader.fieldnames) != _SAMPLE_FIELDS:
            raise ValueError("CSV headers are invalid")
        samples = tuple(_sample_from_mapping(row) for row in reader)
    except csv.Error as err:
        raise ValueError("Profile CSV is invalid") from err
    return _build_profile(identifier=identifier, samples=samples, config=config)


def aggregate_half_hours(
    profile: LocalSyntheticProfile,
) -> tuple[HalfHourReplayInput, ...]:
    """Aggregate six five-minute samples into deterministic half-hour inputs."""
    aggregates: list[HalfHourReplayInput] = []
    for offset in range(0, len(profile.samples), SAMPLES_PER_HALF_HOUR):
        group = profile.samples[offset : offset + SAMPLES_PER_HALF_HOUR]
        start = group[0].timestamp_utc
        end = group[-1].timestamp_utc + SAMPLE_INTERVAL
        aggregates.append(
            HalfHourReplayInput(
                valid_from_utc=start,
                valid_to_utc=end,
                expected_load_kwh=sum(item.load_w for item in group) / 12_000,
                expected_solar_kwh=sum(item.solar_w for item in group) / 12_000,
                import_rate_gbp_per_kwh=sum(item.import_rate_gbp_per_kwh for item in group) / 6,
                export_rate_gbp_per_kwh=sum(item.export_rate_gbp_per_kwh for item in group) / 6,
            )
        )
    return tuple(aggregates)


def _build_profile(
    *,
    identifier: str,
    samples: tuple[LocalSyntheticSample, ...],
    config: BatteryConfig,
    name: str | None = None,
    starting_battery_energy_wh: float | None = None,
) -> LocalSyntheticProfile:
    if not identifier or not samples or len(samples) > MAX_PROFILE_SAMPLES:
        raise ValueError("Profile identifier or sample count is invalid")
    if len(samples) % SAMPLES_PER_HALF_HOUR:
        raise ValueError("Profile sample count must be divisible by six")
    if samples[0].timestamp_utc.minute % 30 or samples[-1].timestamp_utc.minute % 30 != 25:
        raise ValueError("Profile must start and finish on half-hour boundaries")
    expected = samples[0].timestamp_utc
    for sample in samples:
        if sample.timestamp_utc != expected:
            raise ValueError("Profile samples must be ordered and contiguous")
        expected += SAMPLE_INTERVAL
    if expected - samples[0].timestamp_utc > MAX_PROFILE_DURATION:
        raise ValueError("Profile exceeds 31 days")
    if starting_battery_energy_wh is not None and not (
        config.reserve_wh <= starting_battery_energy_wh <= config.capacity_wh
    ):
        raise ValueError("Profile starting energy is outside reserve and capacity")
    return LocalSyntheticProfile(
        PROFILE_SCHEMA_VERSION,
        identifier,
        samples,
        name,
        starting_battery_energy_wh,
    )


def _sample_from_mapping(value: object) -> LocalSyntheticSample:
    if not isinstance(value, Mapping) or set(value) != _SAMPLE_FIELDS:
        raise ValueError("Profile sample fields are invalid")
    timestamp = value["timestamp"]
    if not isinstance(timestamp, str):
        raise ValueError("Profile timestamp is invalid")
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Profile timestamp requires an explicit UTC offset")
    load = _number(value["load_w"], "load_w")
    solar = _number(value["solar_w"], "solar_w")
    export = _number(value["export_rate_gbp_per_kwh"], "export_rate_gbp_per_kwh")
    if load < 0 or solar < 0 or export < 0:
        raise ValueError("Profile power or export rate is invalid")
    return LocalSyntheticSample(
        parsed.astimezone(timezone.utc),
        load,
        solar,
        _number(value["import_rate_gbp_per_kwh"], "import_rate_gbp_per_kwh"),
        export,
    )


def _number(value: object, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as err:
        raise ValueError(f"{name} is invalid") from err
    if not math.isfinite(number):
        raise ValueError(f"{name} is invalid")
    return number

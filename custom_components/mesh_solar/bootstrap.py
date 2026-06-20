from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping
from urllib.parse import urlparse
from uuid import UUID

from .const import (
    ENTITLED_SUBSCRIPTION_STATUSES,
    SUBSCRIPTION_STATUS_NO_SUBSCRIPTION,
    SUBSCRIPTION_STATUS_SUBSCRIBED,
    SUBSCRIPTION_STATUS_TRIAL,
    SUPPORTED_BOOTSTRAP_SCHEMA_VERSION,
)


class BootstrapValidationError(ValueError):
    """Raised when bootstrap data is incomplete or inconsistent."""


class UnsupportedBootstrapSchemaError(BootstrapValidationError):
    """Raised when the backend returns an unknown bootstrap schema."""

    def __init__(self, schema_version: object) -> None:
        super().__init__("Unsupported bootstrap schema version")
        self.schema_version = schema_version


@dataclass(frozen=True, slots=True)
class TrialAvailability:
    """Trial availability returned by an observational bootstrap call."""

    eligible: bool
    duration_days: int | None
    starts_only_on_explicit_request: bool


@dataclass(frozen=True, slots=True)
class ForecastBootstrapConfig:
    """Validated forecast credentials returned by bootstrap."""

    endpoint: str
    function_key: str
    device_token: str | None
    cadence_minutes: int


@dataclass(frozen=True, slots=True)
class BootstrapData:
    """Validated Mesh Solar bootstrap response."""

    schema_version: int
    subscription_status: str
    can_forecast: bool
    registration_id: str | None
    installation_id: str
    refresh_after_utc: str | None
    entitlement_expires_on_utc: str | None
    registration: dict[str, object]
    forecast: ForecastBootstrapConfig | None
    reason: str | None
    subscribe_url: str | None
    trial: TrialAvailability | None

    @property
    def entitled(self) -> bool:
        """Return whether the response permits forecasting."""
        return self.subscription_status in ENTITLED_SUBSCRIPTION_STATUSES


def parse_bootstrap_response(
    payload: object,
    *,
    requested_installation_id: str,
) -> BootstrapData:
    """Validate and normalize a bootstrap response."""
    source = _mapping(payload, "bootstrap response")
    schema_version = source.get("schemaVersion")
    if schema_version != SUPPORTED_BOOTSTRAP_SCHEMA_VERSION:
        raise UnsupportedBootstrapSchemaError(schema_version)

    subscription_status = _required_string(source, "subscriptionStatus")
    if subscription_status not in {
        SUBSCRIPTION_STATUS_NO_SUBSCRIPTION,
        SUBSCRIPTION_STATUS_TRIAL,
        SUBSCRIPTION_STATUS_SUBSCRIBED,
    }:
        raise BootstrapValidationError("Invalid subscription status")

    installation_id = _required_uuid(source, "installationId")
    if installation_id != requested_installation_id:
        raise BootstrapValidationError("Bootstrap installation ID mismatch")

    can_forecast = source.get("canForecast") is True
    refresh_after_utc = _optional_datetime(source.get("refreshAfterUtc"))
    entitlement_expires_on_utc = _optional_datetime(
        source.get("entitlementExpiresOnUtc")
    )
    reason = _optional_string(source.get("reason"))
    subscribe_url = _optional_https_url(
        source.get("subscribeUrl") or source.get("portalBillingUrl")
    )
    trial = _parse_trial(source.get("trial"))

    if subscription_status == SUBSCRIPTION_STATUS_NO_SUBSCRIPTION:
        if can_forecast:
            raise BootstrapValidationError(
                "No-subscription bootstrap cannot allow forecasting"
            )
        return BootstrapData(
            schema_version=schema_version,
            subscription_status=subscription_status,
            can_forecast=False,
            registration_id=_optional_string(source.get("registrationId")),
            installation_id=installation_id,
            refresh_after_utc=refresh_after_utc,
            entitlement_expires_on_utc=entitlement_expires_on_utc,
            registration={},
            forecast=None,
            reason=reason,
            subscribe_url=subscribe_url,
            trial=trial,
        )

    if not can_forecast:
        raise BootstrapValidationError("Entitled bootstrap must allow forecasting")

    registration_id = _required_string(source, "registrationId")
    registration = dict(_mapping(source.get("registration"), "registration"))
    if not registration:
        raise BootstrapValidationError("Bootstrap registration is empty")

    forecast_source = _mapping(source.get("forecast"), "forecast")
    endpoint = _required_https_url(forecast_source, "endpoint")
    function_key = _required_string(forecast_source, "functionKey")
    cadence_minutes = _required_positive_int(forecast_source, "cadenceMinutes")
    device_token = _optional_string(forecast_source.get("deviceToken"))

    if subscription_status == SUBSCRIPTION_STATUS_TRIAL and not device_token:
        raise BootstrapValidationError("Trial bootstrap is missing a device token")

    return BootstrapData(
        schema_version=schema_version,
        subscription_status=subscription_status,
        can_forecast=True,
        registration_id=registration_id,
        installation_id=installation_id,
        refresh_after_utc=refresh_after_utc,
        entitlement_expires_on_utc=entitlement_expires_on_utc,
        registration=registration,
        forecast=ForecastBootstrapConfig(
            endpoint=endpoint,
            function_key=function_key,
            device_token=device_token,
            cadence_minutes=cadence_minutes,
        ),
        reason=reason,
        subscribe_url=subscribe_url,
        trial=trial,
    )


def _parse_trial(value: object) -> TrialAvailability | None:
    if value is None:
        return None
    source = _mapping(value, "trial")
    eligible = source.get("eligible") is True
    duration_value = source.get("durationDays")
    duration_days = None
    if duration_value is not None:
        if not isinstance(duration_value, int) or duration_value < 1:
            raise BootstrapValidationError("Invalid trial duration")
        duration_days = duration_value
    explicit = source.get("startsOnlyOnExplicitRequest") is True
    if eligible and not explicit:
        raise BootstrapValidationError("Trial availability is not explicitly gated")
    return TrialAvailability(
        eligible=eligible,
        duration_days=duration_days,
        starts_only_on_explicit_request=explicit,
    )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise BootstrapValidationError(f"Invalid {name}")
    return value


def _required_string(source: Mapping[str, object], key: str) -> str:
    value = _optional_string(source.get(key))
    if value is None:
        raise BootstrapValidationError(f"Missing {key}")
    return value


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _required_uuid(source: Mapping[str, object], key: str) -> str:
    value = _required_string(source, key)
    try:
        return str(UUID(value))
    except ValueError as err:
        raise BootstrapValidationError(f"Invalid {key}") from err


def _required_positive_int(source: Mapping[str, object], key: str) -> int:
    value = source.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise BootstrapValidationError(f"Invalid {key}")
    return value


def _required_https_url(source: Mapping[str, object], key: str) -> str:
    value = _required_string(source, key)
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username:
        raise BootstrapValidationError(f"Invalid {key}")
    return value


def _optional_https_url(value: object) -> str | None:
    normalized = _optional_string(value)
    if normalized is None:
        return None
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username:
        raise BootstrapValidationError("Invalid subscribe URL")
    return normalized


def _optional_datetime(value: object) -> str | None:
    normalized = _optional_string(value)
    if normalized is None:
        return None
    candidate = normalized.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as err:
        raise BootstrapValidationError("Invalid UTC timestamp") from err
    if parsed.tzinfo is None:
        raise BootstrapValidationError("UTC timestamp is missing timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

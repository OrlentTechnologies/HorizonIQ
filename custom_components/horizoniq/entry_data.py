from __future__ import annotations

from typing import Any, Mapping

from .bootstrap import BootstrapData
from .const import (
    CONF_API_KEY,
    CONF_BATTERY_CAPACITY_SENSOR,
    CONF_BOOTSTRAP_REASON,
    CONF_BOOTSTRAP_REFRESH_AFTER_UTC,
    CONF_BOOTSTRAP_SCHEMA_VERSION,
    CONF_CAN_FORECAST,
    CONF_ENTITLEMENT_EXPIRES_ON_UTC,
    CONF_ENVIRONMENT,
    CONF_FORECAST_CADENCE_MINUTES,
    CONF_FORECAST_DEVICE_ID,
    CONF_FORECAST_DEVICE_TOKEN,
    CONF_FORECAST_ENDPOINT,
    CONF_FORECAST_FUNCTION_KEY,
    CONF_HASH,
    CONF_INSTALLATION_ID,
    CONF_REGISTRATION_CONFIG,
    CONF_REGISTRATION_DATA,
    CONF_REGISTRATION_ID,
    CONF_SUBSCRIBE_URL,
    CONF_SUBSCRIPTION_STATUS,
    CONF_URL,
    DOMAIN,
    INTEGRATION_VERSION,
    PORTAL_BILLING_URL,
    SUBSCRIPTION_STATUS_TRIAL,
)
from .oauth import OAuthRuntimeConfig

CONF_OAUTH_RUNTIME = "oauth_runtime"


def entry_data_from_bootstrap(
    *,
    bootstrap: BootstrapData,
    oauth_data: Mapping[str, Any],
    runtime: OAuthRuntimeConfig | None,
    battery_capacity_sensor: str,
    environment: str,
    device_token: str | None,
) -> dict[str, object]:
    """Build an atomic config-entry update from a validated bootstrap response."""
    if bootstrap.forecast is None or bootstrap.registration_id is None:
        raise ValueError("Entitled bootstrap response is incomplete")

    trial_token = (
        bootstrap.forecast.device_token
        if bootstrap.subscription_status == SUBSCRIPTION_STATUS_TRIAL
        else None
    )

    return {
        "auth_implementation": DOMAIN,
        "token": oauth_data["token"],
        CONF_OAUTH_RUNTIME: _runtime_data(runtime),
        CONF_INSTALLATION_ID: bootstrap.installation_id,
        CONF_SUBSCRIPTION_STATUS: bootstrap.subscription_status,
        CONF_CAN_FORECAST: bootstrap.can_forecast,
        CONF_BOOTSTRAP_REASON: bootstrap.reason or "",
        CONF_REGISTRATION_ID: bootstrap.registration_id,
        CONF_FORECAST_ENDPOINT: bootstrap.forecast.endpoint,
        CONF_FORECAST_FUNCTION_KEY: bootstrap.forecast.function_key,
        CONF_FORECAST_CADENCE_MINUTES: bootstrap.forecast.cadence_minutes,
        CONF_BOOTSTRAP_REFRESH_AFTER_UTC: bootstrap.refresh_after_utc or "",
        CONF_ENTITLEMENT_EXPIRES_ON_UTC: bootstrap.entitlement_expires_on_utc or "",
        CONF_REGISTRATION_CONFIG: bootstrap.registration,
        CONF_BOOTSTRAP_SCHEMA_VERSION: bootstrap.schema_version,
        CONF_SUBSCRIBE_URL: PORTAL_BILLING_URL,
        CONF_URL: bootstrap.forecast.endpoint,
        CONF_API_KEY: bootstrap.registration_id,
        CONF_BATTERY_CAPACITY_SENSOR: battery_capacity_sensor,
        CONF_ENVIRONMENT: environment,
        CONF_HASH: "",
        CONF_REGISTRATION_DATA: "",
        CONF_FORECAST_DEVICE_ID: (
            bootstrap.installation_id
            if bootstrap.subscription_status == SUBSCRIPTION_STATUS_TRIAL
            else ""
        ),
        CONF_FORECAST_DEVICE_TOKEN: trial_token or device_token or "",
        "integration_version": INTEGRATION_VERSION,
    }


def no_subscription_entry_data(bootstrap: BootstrapData) -> dict[str, object]:
    """Build a config-entry update for a valid no-subscription response."""
    return {
        CONF_SUBSCRIPTION_STATUS: bootstrap.subscription_status,
        CONF_CAN_FORECAST: False,
        CONF_BOOTSTRAP_REASON: bootstrap.reason or "",
        CONF_BOOTSTRAP_REFRESH_AFTER_UTC: bootstrap.refresh_after_utc or "",
        CONF_ENTITLEMENT_EXPIRES_ON_UTC: bootstrap.entitlement_expires_on_utc or "",
        CONF_SUBSCRIBE_URL: PORTAL_BILLING_URL,
        CONF_FORECAST_FUNCTION_KEY: "",
        CONF_FORECAST_DEVICE_TOKEN: "",
        CONF_HASH: "",
        CONF_REGISTRATION_DATA: "",
    }


def runtime_from_entry_data(entry_data: Mapping[str, Any]) -> OAuthRuntimeConfig | None:
    """Rehydrate runtime config needed by Home Assistant's OAuth session."""
    data = entry_data.get(CONF_OAUTH_RUNTIME)
    if not isinstance(data, Mapping):
        return None

    try:
        return OAuthRuntimeConfig(
            client_id=_required_text(data, "client_id"),
            portal_connection_url=_required_text(data, "portal_connection_url"),
            token_endpoint=_required_text(data, "token_endpoint"),
            backend_api_scope=_required_text(data, "backend_api_scope"),
            backend_api_base_url=_required_text(data, "backend_api_base_url"),
        )
    except ValueError:
        return None


def _runtime_data(runtime: OAuthRuntimeConfig | None) -> dict[str, str]:
    if runtime is None:
        return {
            "client_id": "",
            "portal_connection_url": "",
            "token_endpoint": "",
            "backend_api_scope": "",
            "backend_api_base_url": "",
        }

    return {
        "client_id": runtime.client_id,
        "portal_connection_url": runtime.portal_connection_url,
        "token_endpoint": runtime.token_endpoint,
        "backend_api_scope": runtime.backend_api_scope,
        "backend_api_base_url": runtime.backend_api_base_url,
    }


def _required_text(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(key)
    return value.strip()

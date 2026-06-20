from homeassistant.const import Platform

DOMAIN = "mesh_solar"
INTEGRATION_VERSION = "2.0.3"

CONF_URL = "url"
CONF_API_KEY = "api_key"
CONF_BATTERY_CAPACITY_SENSOR = "battery_capacity_sensor"
CONF_ENVIRONMENT = "environment"
CONF_HASH = "hash"
CONF_REGISTRATION_DATA = "registration_data"
CONF_FORECAST_DEVICE_ID = "forecast_device_id"
CONF_FORECAST_DEVICE_TOKEN = "forecast_device_token"
CONF_HOME_ASSISTANT_INSTALLATION_ID = "home_assistant_installation_id"
CONF_GX_DEVICE_ID = "gx_device_id"
CONF_INSTALLATION_ID = "installation_id"
CONF_SUBSCRIPTION_STATUS = "subscription_status"
CONF_REGISTRATION_ID = "registration_id"
CONF_FORECAST_ENDPOINT = "forecast_endpoint"
CONF_FORECAST_FUNCTION_KEY = "forecast_function_key"
CONF_FORECAST_CADENCE_MINUTES = "forecast_cadence_minutes"
CONF_BOOTSTRAP_REFRESH_AFTER_UTC = "bootstrap_refresh_after_utc"
CONF_ENTITLEMENT_EXPIRES_ON_UTC = "entitlement_expires_on_utc"
CONF_REGISTRATION_CONFIG = "registration_config"
CONF_BOOTSTRAP_SCHEMA_VERSION = "bootstrap_schema_version"
CONF_CAN_FORECAST = "can_forecast"
CONF_SUBSCRIBE_URL = "subscribe_url"
CONF_BOOTSTRAP_REASON = "bootstrap_reason"
CONF_MIGRATION_REQUIRED = "oauth_migration_required"
CONF_TEST_MODE = "test_mode"
CONF_PORTAL_CONNECTION_URL = "portal_connection_url"

SUBSCRIPTION_STATUS_NO_SUBSCRIPTION = "no_subscription"
SUBSCRIPTION_STATUS_TRIAL = "trial"
SUBSCRIPTION_STATUS_SUBSCRIBED = "subscribed"
ENTITLED_SUBSCRIPTION_STATUSES = frozenset(
    {SUBSCRIPTION_STATUS_TRIAL, SUBSCRIPTION_STATUS_SUBSCRIBED}
)

ACTION_SIGN_IN = "signin"
ACTION_CREATE_ACCOUNT = "create"
ACTION_START_TRIAL = "start_trial"
ACTION_SUBSCRIBE = "subscribe"
ACTION_CHECK_AGAIN = "check_again"
ACTION_REAUTHENTICATE = "reauthenticate"
ACTION_RELOAD = "reload"

PORTAL_BASE_URL = "https://mesh-forecaster.com"
PORTAL_CONNECT_URL = f"{PORTAL_BASE_URL}/portal/ha-integration/connect"
PORTAL_RUNTIME_CONFIG_URL = f"{PORTAL_BASE_URL}/config.json"
PORTAL_BILLING_URL = f"{PORTAL_BASE_URL}/portal/billing"
BOOTSTRAP_PATH = "/api/ha/bootstrap"
TRIAL_START_PATH = "/api/trials/start"
SUPPORTED_BOOTSTRAP_SCHEMA_VERSION = 1
DEFAULT_BOOTSTRAP_REFRESH_HOURS = 24
BOOTSTRAP_JITTER_MAX_MINUTES = 30
EXACT_SUBSCRIPTION_FAILURE_BODY = "No valid subscription found."

ISSUE_ENTITLEMENT_LOST = "entitlement_lost"
ISSUE_FORECAST_CREDENTIAL_REFRESH = "forecast_credential_refresh"
ISSUE_OAUTH_MIGRATION = "oauth_migration_required"
ISSUE_REAUTH_REQUIRED = "reauth_required"
ISSUE_TRIAL_TOKEN_RECOVERY = "trial_token_recovery"
ISSUE_UNSUPPORTED_BOOTSTRAP_SCHEMA = "unsupported_bootstrap_schema"

HEADER_API_KEY = "X-API-KEY"
HEADER_MESH_DEVICE_ID = "X-Mesh-Device-Id"
HEADER_MESH_DEVICE_TOKEN = "X-Mesh-Device-Token"
UNAVAILABLE_HOME_ASSISTANT_INSTALLATION_ID = "Unavailable"
DEFAULT_ENVIRONMENT = ""
DEFAULT_ENVIRONMENT_LABEL = "Live"
SANDBOX_ENVIRONMENT = "Sandbox"
LEGACY_LIVE_ENVIRONMENT = "Live"
DEFAULT_TITLE = "Mesh Solar"
DEFAULT_FORECAST_URL = (
    "https://meshsolar-production-faf.azurewebsites.net/api/Forecast_Get?code="
)
DEFAULT_API_KEY = ""
DEFAULT_BATTERY_CAPACITY_SENSOR = "sensor.battery_capacity"
DEFAULT_FORECAST_CADENCE_MINUTES = 5
FAILED_REFRESH_RETRY_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 10
PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.BUTTON,
]


def normalize_environment(value: str | None) -> str:
    """Normalize environment strings to canonical values."""
    if value is None:
        return DEFAULT_ENVIRONMENT

    candidate = value.strip()
    if not candidate:
        return DEFAULT_ENVIRONMENT

    lowered = candidate.lower()

    if lowered == LEGACY_LIVE_ENVIRONMENT.lower():
        return DEFAULT_ENVIRONMENT

    if lowered == SANDBOX_ENVIRONMENT.lower():
        return SANDBOX_ENVIRONMENT

    return candidate


def display_environment(value: str | None) -> str:
    """Return a user-friendly environment label."""
    normalized = normalize_environment(value)
    if normalized == DEFAULT_ENVIRONMENT:
        return DEFAULT_ENVIRONMENT_LABEL
    return normalized

from homeassistant.const import Platform

DOMAIN = "mesh_solar"

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

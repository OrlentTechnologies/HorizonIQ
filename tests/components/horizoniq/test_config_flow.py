"""Tests for config and options flows."""

from unittest.mock import AsyncMock, call, patch
from urllib.parse import parse_qs, urlparse

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import selector
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.horizoniq.config_data import merged_config_data
from custom_components.horizoniq.const import (
    ACTION_CHECK_AGAIN,
    ACTION_CREATE_ACCOUNT,
    ACTION_SIGN_IN,
    ACTION_START_TRIAL,
    ACTION_SUBSCRIBE,
    CONF_API_KEY,
    CONF_BATTERY_CAPACITY_SENSOR,
    CONF_ENVIRONMENT,
    CONF_FORECAST_CADENCE_MINUTES,
    CONF_FORECAST_DEVICE_ID,
    CONF_FORECAST_DEVICE_TOKEN,
    CONF_FORECAST_ENDPOINT,
    CONF_FORECAST_FUNCTION_KEY,
    CONF_GX_DEVICE_ID,
    CONF_HOME_ASSISTANT_INSTALLATION_ID,
    CONF_HASH,
    CONF_INSTALLATION_ID,
    CONF_PORTAL_CONNECTION_URL,
    CONF_REGISTRATION_DATA,
    CONF_TEST_MODE,
    CONF_SUBSCRIPTION_STATUS,
    CONF_URL,
    DEFAULT_ENVIRONMENT,
    DEFAULT_ENVIRONMENT_LABEL,
    DOMAIN,
    PORTAL_BILLING_URL,
    PORTAL_CONNECT_URL,
    SANDBOX_ENVIRONMENT,
    SUBSCRIPTION_STATUS_NO_SUBSCRIPTION,
    SUBSCRIPTION_STATUS_SUBSCRIBED,
    SUBSCRIPTION_STATUS_TRIAL,
    UNAVAILABLE_HOME_ASSISTANT_INSTALLATION_ID,
)
from custom_components.horizoniq.bootstrap import (
    BootstrapData,
    ForecastBootstrapConfig,
    TrialAvailability,
)
from custom_components.horizoniq.config_flow import (
    HorizonIQConfigFlow,
    _entry_title,
    _no_subscription_schema,
    _no_subscription_placeholders,
)
from custom_components.horizoniq.oauth import OAuthRuntimeConfig


def _runtime() -> OAuthRuntimeConfig:
    return OAuthRuntimeConfig(
        client_id="ha-client",
        portal_connection_url=PORTAL_CONNECT_URL,
        token_endpoint="https://login.example.test/tenant/oauth2/v2.0/token",
        backend_api_scope="api://backend/user_impersonation",
        backend_api_base_url="https://api.example.test",
    )


async def test_user_flow_shows_sign_in_create_and_battery_sensor(hass) -> None:
    """Initial setup offers account actions instead of manual forecast keys."""
    with patch(
        "custom_components.horizoniq.config_flow.instance_id.async_get",
        AsyncMock(return_value="76d85cbc-5a44-4e41-88f7-f02f41562f15"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )

    assert result["type"] == FlowResultType.FORM
    defaults = result["data_schema"]({})
    assert defaults[CONF_HOME_ASSISTANT_INSTALLATION_ID] == (
        "76d85cbc-5a44-4e41-88f7-f02f41562f15"
    )
    assert defaults["action"] == ACTION_SIGN_IN
    assert defaults[CONF_BATTERY_CAPACITY_SENSOR] == "sensor.battery_capacity"
    assert defaults[CONF_TEST_MODE] is False
    assert defaults[CONF_PORTAL_CONNECTION_URL] == ""


async def test_user_flow_create_account_generates_portal_oauth_url(hass) -> None:
    """Create Account preserves HA installation ID while using PKCE OAuth."""
    hass.config.components.add("my")
    with (
        patch(
            "custom_components.horizoniq.config_flow.instance_id.async_get",
            AsyncMock(return_value="76d85cbc-5a44-4e41-88f7-f02f41562f15"),
        ),
        patch(
            "custom_components.horizoniq.config_flow.async_get_oauth_runtime_config",
            AsyncMock(return_value=_runtime()),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "action": ACTION_CREATE_ACCOUNT,
                CONF_BATTERY_CAPACITY_SENSOR: "sensor.battery_capacity",
                CONF_HOME_ASSISTANT_INSTALLATION_ID: "tampered",
            },
        )

    assert result["type"] == FlowResultType.EXTERNAL_STEP
    url = urlparse(result["url"])
    params = parse_qs(url.query)
    assert f"{url.scheme}://{url.netloc}{url.path}" == PORTAL_CONNECT_URL
    assert params["mode"] == [ACTION_CREATE_ACCOUNT]
    assert params["installationId"] == [
        "76d85cbc-5a44-4e41-88f7-f02f41562f15"
    ]
    assert params["code_challenge_method"] == ["S256"]
    assert "code_challenge" in params
    assert "state" in params
    assert "client_secret" not in params


async def test_user_flow_normalizes_hex_instance_id_to_uuid(hass) -> None:
    """Home Assistant's 32-character instance id is sent as a UUID."""
    hass.config.components.add("my")
    with (
        patch(
            "custom_components.horizoniq.config_flow.instance_id.async_get",
            AsyncMock(return_value="2da3bfbe301d4f759ba662d96a76a2c1"),
        ),
        patch(
            "custom_components.horizoniq.config_flow.async_get_oauth_runtime_config",
            AsyncMock(return_value=_runtime()),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "action": ACTION_SIGN_IN,
                CONF_BATTERY_CAPACITY_SENSOR: "sensor.battery_capacity",
            },
        )

    assert result["type"] == FlowResultType.EXTERNAL_STEP
    url = urlparse(result["url"])
    params = parse_qs(url.query)
    assert params["installationId"] == [
        "2da3bfbe-301d-4f75-9ba6-62d96a76a2c1"
    ]


async def test_user_flow_test_mode_uses_manual_portal_connection_url(hass) -> None:
    """Test Mode requires and uses the manually entered sandbox portal URL."""
    hass.config.components.add("my")
    portal_connection_url = (
        "https://sandbox.example.test/portal/horizoniq/connect"
    )
    oauth_config = AsyncMock(return_value=_runtime())
    with (
        patch(
            "custom_components.horizoniq.config_flow.instance_id.async_get",
            AsyncMock(return_value="76d85cbc-5a44-4e41-88f7-f02f41562f15"),
        ),
        patch(
            "custom_components.horizoniq.config_flow.async_get_oauth_runtime_config",
            oauth_config,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "action": ACTION_SIGN_IN,
                CONF_BATTERY_CAPACITY_SENSOR: "sensor.battery_capacity",
                CONF_TEST_MODE: True,
                CONF_PORTAL_CONNECTION_URL: portal_connection_url,
            },
        )

    assert result["type"] == FlowResultType.EXTERNAL_STEP
    oauth_config.assert_awaited_once_with(
        hass,
        portal_connection_url=portal_connection_url,
    )


async def test_user_flow_test_mode_sets_sandbox_environment(hass) -> None:
    """Test Mode stores Sandbox instead of overwriting the Live entry data."""
    captured: dict[str, str] = {}

    async def fake_begin_oauth(flow):
        captured["environment"] = flow._environment
        return flow.async_abort(reason="bootstrap_failed")

    with (
        patch(
            "custom_components.horizoniq.config_flow.instance_id.async_get",
            AsyncMock(return_value="76d85cbc-5a44-4e41-88f7-f02f41562f15"),
        ),
        patch(
            "custom_components.horizoniq.config_flow.HorizonIQConfigFlow._async_begin_oauth",
            side_effect=fake_begin_oauth,
            autospec=True,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "action": ACTION_SIGN_IN,
                CONF_BATTERY_CAPACITY_SENSOR: "sensor.battery_capacity",
                CONF_TEST_MODE: True,
                CONF_PORTAL_CONNECTION_URL: (
                    "https://sandbox.example.test/portal/horizoniq/connect"
                ),
            },
        )

    assert result["type"] == FlowResultType.ABORT
    assert captured["environment"] == SANDBOX_ENVIRONMENT


async def test_user_flow_test_mode_requires_manual_portal_connection_url(hass) -> None:
    """Test Mode does not auto-populate a sandbox portal URL."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "action": ACTION_SIGN_IN,
            CONF_BATTERY_CAPACITY_SENSOR: "sensor.battery_capacity",
            CONF_TEST_MODE: True,
            CONF_PORTAL_CONNECTION_URL: "",
        },
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_PORTAL_CONNECTION_URL: "required"}


def test_entry_title_only_labels_sandbox() -> None:
    """Live keeps the original title and Sandbox is explicitly labelled."""
    assert _entry_title(DEFAULT_ENVIRONMENT) == "HorizonIQ"
    assert _entry_title(SANDBOX_ENVIRONMENT) == "HorizonIQ (Sandbox)"


def test_no_subscription_schema_shows_device_id_and_start_trial() -> None:
    """No-subscription flow displays the device ID and trial action."""
    bootstrap = _bootstrap_no_subscription(reason="trial_available", trial_eligible=True)

    schema = _no_subscription_schema(bootstrap)
    defaults = schema({})

    assert defaults[CONF_HOME_ASSISTANT_INSTALLATION_ID] == (
        "76d85cbc-5a44-4e41-88f7-f02f41562f15"
    )
    assert defaults["action"] == ACTION_START_TRIAL
    installation_id_selector = _schema_validator(
        schema, CONF_HOME_ASSISTANT_INSTALLATION_ID
    )
    assert isinstance(installation_id_selector, selector.TextSelector)
    assert installation_id_selector.config["read_only"] is True


def test_no_subscription_schema_hides_start_trial_when_trial_used() -> None:
    """Used-trial/no-subscription state only allows checking again or subscribing."""
    bootstrap = _bootstrap_no_subscription(
        reason="no_subscription",
        trial_eligible=False,
    )

    schema = _no_subscription_schema(bootstrap)
    defaults = schema({})

    assert defaults["action"] == ACTION_CHECK_AGAIN
    with pytest.raises(vol.Invalid):
        schema({"action": ACTION_START_TRIAL})
    assert _no_subscription_placeholders(bootstrap)["reason"] == "no_subscription"
    assert (
        _no_subscription_placeholders(bootstrap)["subscribe_url"]
        == PORTAL_BILLING_URL
    )


async def test_no_subscription_subscribe_redirects_to_billing_portal(hass) -> None:
    """Subscribe action opens billing through Home Assistant's flow manager."""

    async def fake_begin_oauth(flow: HorizonIQConfigFlow):
        flow._bootstrap = _bootstrap_no_subscription(
            reason="no_subscription",
            trial_eligible=False,
        )
        return await flow.async_step_no_subscription()

    with (
        patch(
            "custom_components.horizoniq.config_flow.instance_id.async_get",
            AsyncMock(return_value="76d85cbc-5a44-4e41-88f7-f02f41562f15"),
        ),
        patch(
            "custom_components.horizoniq.config_flow.HorizonIQConfigFlow._async_begin_oauth",
            side_effect=fake_begin_oauth,
            autospec=True,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "action": ACTION_SIGN_IN,
                CONF_BATTERY_CAPACITY_SENSOR: "sensor.battery_capacity",
            },
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "no_subscription"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"action": ACTION_SUBSCRIBE},
    )

    assert result["type"] == FlowResultType.EXTERNAL_STEP
    assert result["step_id"] == ACTION_SUBSCRIBE
    assert result["url"] == PORTAL_BILLING_URL

    result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert result["type"] == FlowResultType.EXTERNAL_STEP_DONE
    assert result["step_id"] == "no_subscription"


def test_trial_bootstrap_creates_forecast_entry_with_trial_cadence() -> None:
    """A valid trial creates forecast configuration using the trial interval."""
    flow = _entitled_flow()
    bootstrap = _bootstrap_trial(device_token="trial-token", cadence_minutes=30)

    result = flow._async_create_or_update_entitled_entry(bootstrap)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert data[CONF_SUBSCRIPTION_STATUS] == SUBSCRIPTION_STATUS_TRIAL
    assert data[CONF_FORECAST_CADENCE_MINUTES] == 30
    assert data[CONF_FORECAST_ENDPOINT] == "https://api.example.test/api/Forecast_Get"
    assert data[CONF_FORECAST_FUNCTION_KEY] == "function-key"
    assert data[CONF_FORECAST_DEVICE_ID] == bootstrap.installation_id
    assert data[CONF_FORECAST_DEVICE_TOKEN] == "trial-token"
    assert data[CONF_URL] == "https://api.example.test/api/Forecast_Get"


@pytest.mark.parametrize("trial_eligible", [True, False])
def test_subscription_bootstrap_creates_forecast_entry_regardless_of_trial_state(
    trial_eligible: bool,
) -> None:
    """A valid subscription wins whether a trial is available or already used."""
    flow = _entitled_flow()
    bootstrap = _bootstrap_subscription(
        trial_eligible=trial_eligible,
        cadence_minutes=5,
    )

    result = flow._async_create_or_update_entitled_entry(bootstrap)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert data[CONF_SUBSCRIPTION_STATUS] == SUBSCRIPTION_STATUS_SUBSCRIBED
    assert data[CONF_FORECAST_CADENCE_MINUTES] == 5
    assert data[CONF_FORECAST_ENDPOINT] == "https://api.example.test/api/Forecast_Get"
    assert data[CONF_FORECAST_FUNCTION_KEY] == "function-key"
    assert data[CONF_FORECAST_DEVICE_ID] == ""
    assert data[CONF_FORECAST_DEVICE_TOKEN] == ""
    assert data[CONF_URL] == "https://api.example.test/api/Forecast_Get"


async def test_bootstrap_retries_trial_device_token_recovery() -> None:
    """Existing active trials can recover a missing local device token after sign-in."""
    flow = HorizonIQConfigFlow()
    initial = _bootstrap_no_subscription(reason="trial_device_token_required")
    recovered = _bootstrap_trial(device_token="recovered-token")
    flow._async_bootstrap = AsyncMock(side_effect=[initial, recovered])

    result = await flow._async_bootstrap_with_trial_token_recovery()

    assert result is recovered
    assert flow._device_token == "recovered-token"
    flow._async_bootstrap.assert_has_awaits(
        [call(), call(rotate_device_token=True)]
    )


async def test_bootstrap_does_not_retry_other_no_subscription_reasons() -> None:
    """Only the backend's token-recovery reason rotates the trial device token."""
    flow = HorizonIQConfigFlow()
    initial = _bootstrap_no_subscription(reason="no_subscription")
    flow._async_bootstrap = AsyncMock(return_value=initial)

    result = await flow._async_bootstrap_with_trial_token_recovery()

    assert result is initial
    flow._async_bootstrap.assert_awaited_once_with()


async def test_user_flow_rejects_invalid_entity_id(hass) -> None:
    """The user flow validates the battery capacity entity ID."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "action": ACTION_SIGN_IN,
            CONF_BATTERY_CAPACITY_SENSOR: "not an entity",
        },
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_BATTERY_CAPACITY_SENSOR: "invalid_entity_id"}


async def test_options_flow_updates_entry_data_and_clears_duplicate_options(hass) -> None:
    """Options flow writes authoritative legacy values back into entry.data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HorizonIQ",
        data={
            CONF_URL: "https://example.com/original",
            CONF_API_KEY: "original-key",
            CONF_BATTERY_CAPACITY_SENSOR: "sensor.original_capacity",
            CONF_ENVIRONMENT: DEFAULT_ENVIRONMENT,
            CONF_HASH: "",
            CONF_REGISTRATION_DATA: "",
            CONF_FORECAST_DEVICE_ID: "",
            CONF_FORECAST_DEVICE_TOKEN: "",
        },
        options={
            CONF_URL: "https://example.com/legacy-option",
            CONF_API_KEY: "legacy-option-key",
        },
        entry_id="options-entry",
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.horizoniq.config_flow.instance_id.async_get",
        AsyncMock(return_value="ha-installation-options"),
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    defaults = result["data_schema"]({})
    assert defaults[CONF_HOME_ASSISTANT_INSTALLATION_ID] == "ha-installation-options"
    installation_id_selector = _schema_validator(
        result["data_schema"], CONF_HOME_ASSISTANT_INSTALLATION_ID
    )
    assert isinstance(installation_id_selector, selector.TextSelector)
    assert installation_id_selector.config["read_only"] is True

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_URL: "https://example.com/updated",
            CONF_API_KEY: "updated-key",
            CONF_BATTERY_CAPACITY_SENSOR: "sensor.updated_capacity",
            CONF_ENVIRONMENT: SANDBOX_ENVIRONMENT,
            CONF_HASH: "new-hash",
            CONF_REGISTRATION_DATA: "new-registration",
            CONF_FORECAST_DEVICE_ID: "gx-device-2",
            CONF_FORECAST_DEVICE_TOKEN: "new-trial-token",
            CONF_HOME_ASSISTANT_INSTALLATION_ID: "tampered-installation-id",
        },
    )
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.data == {
        CONF_URL: "https://example.com/updated",
        CONF_API_KEY: "updated-key",
        CONF_BATTERY_CAPACITY_SENSOR: "sensor.updated_capacity",
        CONF_ENVIRONMENT: SANDBOX_ENVIRONMENT,
        CONF_HASH: "new-hash",
        CONF_REGISTRATION_DATA: "new-registration",
        CONF_FORECAST_DEVICE_ID: "gx-device-2",
        CONF_FORECAST_DEVICE_TOKEN: "new-trial-token",
    }
    assert CONF_HOME_ASSISTANT_INSTALLATION_ID not in entry.data
    assert entry.options == {}


async def test_user_flow_shows_unavailable_when_installation_id_fails(hass) -> None:
    """The config form remains usable when the HA installation ID is unavailable."""
    with patch(
        "custom_components.horizoniq.config_flow.instance_id.async_get",
        AsyncMock(side_effect=RuntimeError("storage unavailable")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )

    assert result["type"] == FlowResultType.FORM
    defaults = result["data_schema"]({})
    assert (
        defaults[CONF_HOME_ASSISTANT_INSTALLATION_ID]
        != UNAVAILABLE_HOME_ASSISTANT_INSTALLATION_ID
    )


def test_merged_config_data_defaults_forecast_device_id_from_gx_device_id() -> None:
    """Legacy GX device ID data seeds the forecast device ID when unset."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HorizonIQ",
        data={
            CONF_URL: "https://example.com/forecast",
            CONF_API_KEY: "api-key",
            CONF_BATTERY_CAPACITY_SENSOR: "sensor.battery_capacity",
            CONF_ENVIRONMENT: DEFAULT_ENVIRONMENT_LABEL,
            CONF_HASH: "",
            CONF_REGISTRATION_DATA: "",
            CONF_GX_DEVICE_ID: "gx-device-legacy",
        },
        entry_id="gx-entry",
    )

    assert merged_config_data(entry)[CONF_FORECAST_DEVICE_ID] == "gx-device-legacy"


def _schema_validator(schema, field: str):
    for key, validator in schema.schema.items():
        if getattr(key, "schema", None) == field:
            return validator
    raise AssertionError(f"Schema field {field} not found")


def _entitled_flow() -> HorizonIQConfigFlow:
    flow = HorizonIQConfigFlow()
    flow._oauth_data = {"token": {"access_token": "access-token"}}
    flow._runtime = _runtime()
    flow._battery_capacity_sensor = "sensor.battery_capacity"
    flow._environment = SANDBOX_ENVIRONMENT
    return flow


def _bootstrap_no_subscription(
    *,
    reason: str,
    trial_eligible: bool = False,
) -> BootstrapData:
    return BootstrapData(
        schema_version=1,
        subscription_status=SUBSCRIPTION_STATUS_NO_SUBSCRIPTION,
        can_forecast=False,
        registration_id="11111111-1111-4111-8111-111111111111",
        installation_id="76d85cbc-5a44-4e41-88f7-f02f41562f15",
        refresh_after_utc="2026-06-16T12:00:00Z",
        entitlement_expires_on_utc=None,
        registration={},
        forecast=None,
        reason=reason,
        subscribe_url=PORTAL_BILLING_URL,
        trial=TrialAvailability(
            eligible=trial_eligible,
            duration_days=14 if trial_eligible else None,
            starts_only_on_explicit_request=trial_eligible,
        ),
    )


def _bootstrap_trial(
    *,
    device_token: str,
    cadence_minutes: int = 30,
) -> BootstrapData:
    return BootstrapData(
        schema_version=1,
        subscription_status=SUBSCRIPTION_STATUS_TRIAL,
        can_forecast=True,
        registration_id="11111111-1111-4111-8111-111111111111",
        installation_id="76d85cbc-5a44-4e41-88f7-f02f41562f15",
        refresh_after_utc="2026-06-16T12:00:00Z",
        entitlement_expires_on_utc="2026-06-23T12:00:00Z",
        registration={"BatteryCapacitySensor": "sensor.battery_capacity"},
        forecast=ForecastBootstrapConfig(
            endpoint="https://api.example.test/api/Forecast_Get",
            function_key="function-key",
            device_token=device_token,
            cadence_minutes=cadence_minutes,
        ),
        reason=None,
        subscribe_url=PORTAL_BILLING_URL,
        trial=None,
    )


def _bootstrap_subscription(
    *,
    trial_eligible: bool,
    cadence_minutes: int,
) -> BootstrapData:
    return BootstrapData(
        schema_version=1,
        subscription_status=SUBSCRIPTION_STATUS_SUBSCRIBED,
        can_forecast=True,
        registration_id="11111111-1111-4111-8111-111111111111",
        installation_id="76d85cbc-5a44-4e41-88f7-f02f41562f15",
        refresh_after_utc="2026-06-16T12:00:00Z",
        entitlement_expires_on_utc=None,
        registration={"BatteryCapacitySensor": "sensor.battery_capacity"},
        forecast=ForecastBootstrapConfig(
            endpoint="https://api.example.test/api/Forecast_Get",
            function_key="function-key",
            device_token=None,
            cadence_minutes=cadence_minutes,
        ),
        reason=None,
        subscribe_url=PORTAL_BILLING_URL,
        trial=TrialAvailability(
            eligible=trial_eligible,
            duration_days=14 if trial_eligible else None,
            starts_only_on_explicit_request=trial_eligible,
        ),
    )

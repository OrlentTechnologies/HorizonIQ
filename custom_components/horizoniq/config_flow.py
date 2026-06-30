from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

from aiohttp import ClientError
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers import instance_id
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .api import (
    HorizonIQApiAuthError,
    HorizonIQApiError,
    HorizonIQApiTransientError,
    HorizonIQBootstrapClient,
    StaticAccessTokenSession,
)
from .bootstrap import BootstrapData
from .config_data import (
    build_config_schema,
    default_config_data,
    merged_config_data,
    normalize_config_input,
    validate_config_data,
)
from .const import (
    ACTION_CHECK_AGAIN,
    ACTION_CREATE_ACCOUNT,
    ACTION_SIGN_IN,
    ACTION_START_TRIAL,
    ACTION_SUBSCRIBE,
    CONF_API_KEY,
    CONF_BATTERY_CAPACITY_SENSOR,
    CONF_ENVIRONMENT,
    CONF_FORECAST_DEVICE_ID,
    CONF_FORECAST_DEVICE_TOKEN,
    CONF_HOME_ASSISTANT_INSTALLATION_ID,
    CONF_INSTALLATION_ID,
    CONF_PORTAL_CONNECTION_URL,
    CONF_TEST_MODE,
    CONF_URL,
    DEFAULT_ENVIRONMENT,
    DEFAULT_TITLE,
    DOMAIN,
    PORTAL_BILLING_URL,
    SANDBOX_ENVIRONMENT,
    SUBSCRIPTION_STATUS_NO_SUBSCRIPTION,
    display_environment,
    normalize_environment,
)
from .entry_data import entry_data_from_bootstrap, runtime_from_entry_data
from .oauth import (
    HorizonIQOAuth2Implementation,
    OAuthRuntimeConfig,
    OAuthRuntimeConfigError,
    async_get_oauth_runtime_config,
)

_LOGGER = logging.getLogger(__name__)

_CONF_ACTION = "action"
_CONF_CONFIRM_START_TRIAL = "confirm_start_trial"
_BOOTSTRAP_REASON_TRIAL_DEVICE_TOKEN_REQUIRED = "trial_device_token_required"
_READ_ONLY_TEXT_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(read_only=True)
)


class HorizonIQConfigFlow(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Handle HorizonIQ config and reauth flows."""

    DOMAIN = DOMAIN
    VERSION = 2

    def __init__(self) -> None:
        super().__init__()
        self._runtime: OAuthRuntimeConfig | None = None
        self._oauth_data: dict[str, Any] | None = None
        self._bootstrap: BootstrapData | None = None
        self._installation_id = ""
        self._mode = ACTION_SIGN_IN
        self._battery_capacity_sensor = default_config_data()[
            CONF_BATTERY_CAPACITY_SENSOR
        ]
        self._environment = DEFAULT_ENVIRONMENT
        self._device_token: str | None = None
        self._reauth_entry: ConfigEntry | None = None
        self._portal_connection_url: str | None = None

    @property
    def logger(self) -> logging.Logger:
        """Return the flow logger."""
        return _LOGGER

    @property
    def extra_authorize_data(self) -> dict[str, str]:
        """Attach portal routing data after the OAuth helper adds state and PKCE."""
        return {
            "installationId": self._installation_id,
            "mode": self._mode,
        }

    async def async_step_user(
        self, user_input: dict[str, object] | None = None
    ) -> ConfigFlowResult:
        """Start setup with Sign In or Create Account."""
        errors: dict[str, str] = {}
        config_data = default_config_data()

        if user_input is not None:
            action = str(user_input.get(_CONF_ACTION, "")).strip()
            test_mode = user_input.get(CONF_TEST_MODE) is True
            selected_environment = (
                SANDBOX_ENVIRONMENT if test_mode else DEFAULT_ENVIRONMENT
            )
            self._battery_capacity_sensor = str(
                user_input.get(CONF_BATTERY_CAPACITY_SENSOR, "")
            ).strip()
            config_data = normalize_config_input(
                {
                    CONF_URL: "https://placeholder.invalid/api/Forecast_Get",
                    CONF_API_KEY: "bootstrap",
                    CONF_BATTERY_CAPACITY_SENSOR: self._battery_capacity_sensor,
                    CONF_ENVIRONMENT: selected_environment,
                }
            )
            errors = {
                key: value
                for key, value in validate_config_data(config_data).items()
                if key == CONF_BATTERY_CAPACITY_SENSOR
            }

            if action not in {ACTION_SIGN_IN, ACTION_CREATE_ACCOUNT}:
                errors[_CONF_ACTION] = "required"

            portal_connection_url = _optional_string(
                user_input.get(CONF_PORTAL_CONNECTION_URL)
            )
            if test_mode:
                if portal_connection_url is None:
                    errors[CONF_PORTAL_CONNECTION_URL] = "required"
                elif not _is_valid_portal_connection_url(portal_connection_url):
                    errors[CONF_PORTAL_CONNECTION_URL] = "invalid_url"
            else:
                portal_connection_url = None

            if not errors:
                self._environment = config_data[CONF_ENVIRONMENT]
                self._installation_id = await _async_installation_id(self.hass)
                self._mode = action
                self._portal_connection_url = portal_connection_url
                return await self._async_begin_oauth()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_HOME_ASSISTANT_INSTALLATION_ID,
                        default=await _async_installation_id(self.hass),
                    ): str,
                    vol.Required(_CONF_ACTION, default=ACTION_SIGN_IN): vol.In(
                        {
                            ACTION_SIGN_IN: "Sign In",
                            ACTION_CREATE_ACCOUNT: "Create Account",
                        }
                    ),
                    vol.Required(
                        CONF_BATTERY_CAPACITY_SENSOR,
                        default=config_data[CONF_BATTERY_CAPACITY_SENSOR],
                    ): str,
                    vol.Optional(CONF_TEST_MODE, default=False): bool,
                    vol.Optional(CONF_PORTAL_CONNECTION_URL, default=""): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Require the user to sign in again before checking bootstrap."""
        entry_id = self.context.get("entry_id")
        self._reauth_entry = (
            self.hass.config_entries.async_get_entry(entry_id)
            if isinstance(entry_id, str)
            else None
        )
        self._battery_capacity_sensor = str(
            entry_data.get(CONF_BATTERY_CAPACITY_SENSOR)
            or default_config_data()[CONF_BATTERY_CAPACITY_SENSOR]
        )
        self._environment = str(entry_data.get(CONF_ENVIRONMENT) or DEFAULT_ENVIRONMENT)
        self._device_token = _optional_string(entry_data.get(CONF_FORECAST_DEVICE_TOKEN))
        stored_runtime = runtime_from_entry_data(entry_data)
        self._portal_connection_url = (
            stored_runtime.portal_connection_url if stored_runtime is not None else None
        )
        self._installation_id = (
            _optional_string(entry_data.get(CONF_INSTALLATION_ID))
            or _optional_string(entry_data.get(CONF_FORECAST_DEVICE_ID))
            or await _async_installation_id(self.hass)
        )
        self._mode = ACTION_SIGN_IN
        return await self._async_begin_oauth()

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Call bootstrap after OAuth succeeds and branch by subscription state."""
        self._oauth_data = data
        try:
            self._bootstrap = await self._async_bootstrap_with_trial_token_recovery()
        except HorizonIQApiAuthError:
            return self.async_abort(reason="oauth_unauthorized")
        except HorizonIQApiTransientError:
            return self.async_abort(reason="service_unavailable")
        except (HorizonIQApiError, ClientError, OAuthRuntimeConfigError):
            _LOGGER.exception("Home Assistant bootstrap failed after OAuth")
            return self.async_abort(reason="bootstrap_failed")

        if self._bootstrap.entitled:
            return self._async_create_or_update_entitled_entry(self._bootstrap)

        return await self.async_step_no_subscription()

    async def async_step_no_subscription(
        self, user_input: dict[str, object] | None = None
    ) -> ConfigFlowResult:
        """Handle the no-subscription state without starting a trial implicitly."""
        bootstrap = self._bootstrap
        if bootstrap is None:
            return self.async_abort(reason="bootstrap_failed")

        if user_input is not None:
            action = str(user_input.get(_CONF_ACTION, "")).strip()
            if action == ACTION_CHECK_AGAIN:
                try:
                    self._bootstrap = (
                        await self._async_bootstrap_with_trial_token_recovery()
                    )
                except HorizonIQApiTransientError:
                    return self.async_show_form(
                        step_id="no_subscription",
                        data_schema=_no_subscription_schema(bootstrap),
                        errors={"base": "service_unavailable"},
                        description_placeholders=_no_subscription_placeholders(
                            bootstrap
                        ),
                    )
                if self._bootstrap.entitled:
                    return self._async_create_or_update_entitled_entry(self._bootstrap)
                return await self.async_step_no_subscription()

            if action == ACTION_START_TRIAL and bootstrap.trial and bootstrap.trial.eligible:
                return await self.async_step_confirm_start_trial()

            if action == ACTION_SUBSCRIBE:
                return self.async_external_step(
                    step_id=ACTION_SUBSCRIBE,
                    url=PORTAL_BILLING_URL,
                )

            return self.async_abort(reason="subscription_required")

        return self.async_show_form(
            step_id="no_subscription",
            data_schema=_no_subscription_schema(bootstrap),
            errors={},
            description_placeholders=_no_subscription_placeholders(bootstrap),
        )

    async def async_step_subscribe(
        self, user_input: dict[str, object] | None = None
    ) -> ConfigFlowResult:
        """Return to subscription checking after opening the billing portal."""
        if user_input is None:
            return self.async_external_step_done(next_step_id="no_subscription")

        return await self.async_step_no_subscription(user_input)

    async def async_step_confirm_start_trial(
        self, user_input: dict[str, object] | None = None
    ) -> ConfigFlowResult:
        """Require explicit user confirmation before starting the 14-day trial."""
        if user_input is None:
            return self.async_show_form(
                step_id="confirm_start_trial",
                data_schema=vol.Schema(
                    {vol.Required(_CONF_CONFIRM_START_TRIAL, default=False): bool}
                ),
                errors={},
            )

        if user_input.get(_CONF_CONFIRM_START_TRIAL) is not True:
            return await self.async_step_no_subscription()

        try:
            client = self._bootstrap_client()
            self._device_token = await client.async_start_trial(
                installation_id=self._installation_id
            )
            self._bootstrap = await client.async_bootstrap(
                installation_id=self._installation_id,
                device_token=self._device_token,
            )
        except HorizonIQApiTransientError:
            return self.async_show_form(
                step_id="confirm_start_trial",
                data_schema=vol.Schema(
                    {vol.Required(_CONF_CONFIRM_START_TRIAL, default=False): bool}
                ),
                errors={"base": "service_unavailable"},
            )
        except HorizonIQApiError:
            _LOGGER.exception("Explicit Home Assistant trial start failed")
            return self.async_abort(reason="trial_start_failed")

        if self._bootstrap.entitled:
            return self._async_create_or_update_entitled_entry(self._bootstrap)

        return await self.async_step_no_subscription()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "HorizonIQOptionsFlow":
        """Return the options flow handler."""
        return HorizonIQOptionsFlow()

    async def _async_begin_oauth(self) -> ConfigFlowResult:
        try:
            self._runtime = await async_get_oauth_runtime_config(
                self.hass,
                portal_connection_url=self._portal_connection_url,
            )
        except OAuthRuntimeConfigError:
            _LOGGER.exception("Home Assistant OAuth runtime configuration is invalid")
            return self.async_abort(reason="oauth_implementation_unavailable")

        self.flow_impl = HorizonIQOAuth2Implementation(
            self.hass,
            auth_domain=DOMAIN,
            runtime=self._runtime,
        )
        return await self.async_step_auth()

    async def _async_bootstrap(
        self, *, rotate_device_token: bool = False
    ) -> BootstrapData:
        return await self._bootstrap_client().async_bootstrap(
            installation_id=self._installation_id,
            device_token=self._device_token,
            rotate_device_token=rotate_device_token,
        )

    async def _async_bootstrap_with_trial_token_recovery(self) -> BootstrapData:
        bootstrap = await self._async_bootstrap()
        if not _requires_trial_token_recovery(bootstrap):
            return bootstrap

        recovered = await self._async_bootstrap(rotate_device_token=True)
        if recovered.forecast is not None and recovered.forecast.device_token:
            self._device_token = recovered.forecast.device_token
        return recovered

    def _bootstrap_client(self) -> HorizonIQBootstrapClient:
        if self._runtime is None or self._oauth_data is None:
            raise HorizonIQApiError("OAuth data is not available for bootstrap")

        return HorizonIQBootstrapClient(
            oauth_session=StaticAccessTokenSession(
                async_get_clientsession(self.hass),
                self._oauth_data["token"]["access_token"],
            ),
            backend_api_base_url=self._runtime.backend_api_base_url,
        )

    def _async_create_or_update_entitled_entry(
        self, bootstrap: BootstrapData
    ) -> ConfigFlowResult:
        entry_data = _entry_data_from_bootstrap(
            bootstrap=bootstrap,
            oauth_data=self._oauth_data or {},
            runtime=self._runtime,
            battery_capacity_sensor=self._battery_capacity_sensor,
            environment=self._environment,
            device_token=self._device_token,
        )

        if self._reauth_entry is not None:
            self.hass.config_entries.async_update_entry(
                self._reauth_entry,
                data={**self._reauth_entry.data, **entry_data},
            )
            return self.async_abort(reason="reauth_successful")

        return self.async_create_entry(
            title=_entry_title(self._environment),
            data=entry_data,
        )


class HorizonIQOptionsFlow(config_entries.OptionsFlow):
    """Handle HorizonIQ options."""

    async def async_step_init(
        self, user_input: dict[str, object] | None = None
    ) -> ConfigFlowResult:
        """Manage HorizonIQ options."""
        errors: dict[str, str] = {}
        config_data = merged_config_data(self.config_entry)

        if user_input is not None:
            config_data = normalize_config_input(user_input)
            errors = validate_config_data(config_data)
            if not errors:
                updated_options = dict(self.config_entry.options)
                for key in config_data:
                    updated_options.pop(key, None)

                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={**self.config_entry.data, **dict(config_data)},
                    options=updated_options,
                )
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=build_config_schema(
                config_data=config_data,
                installation_id=await _async_installation_id(self.hass),
            ),
            errors=errors,
        )


async def _async_installation_id(hass: HomeAssistant) -> str:
    """Return a stable UUID for this Home Assistant installation."""
    try:
        value = await instance_id.async_get(hass)
    except Exception:
        _LOGGER.warning("Unable to read Home Assistant installation ID", exc_info=True)
        value = ""

    normalized = _optional_string(value)
    if normalized:
        return _normalize_installation_id(normalized)
    return str(uuid4())


def _entry_data_from_bootstrap(
    *,
    bootstrap: BootstrapData,
    oauth_data: dict[str, Any],
    runtime: OAuthRuntimeConfig | None,
    battery_capacity_sensor: str,
    environment: str,
    device_token: str | None,
) -> dict[str, object]:
    try:
        return entry_data_from_bootstrap(
            bootstrap=bootstrap,
            oauth_data=oauth_data,
            runtime=runtime,
            battery_capacity_sensor=battery_capacity_sensor,
            environment=environment,
            device_token=device_token,
        )
    except ValueError as err:
        raise HorizonIQApiError("Entitled bootstrap response is incomplete") from err


def _no_subscription_schema(bootstrap: BootstrapData) -> vol.Schema:
    actions = {ACTION_CHECK_AGAIN: "Check Again", ACTION_SUBSCRIBE: "Subscribe"}
    if bootstrap.trial and bootstrap.trial.eligible:
        actions = {ACTION_START_TRIAL: "Start Trial", **actions}
    return vol.Schema(
        {
            vol.Optional(
                CONF_HOME_ASSISTANT_INSTALLATION_ID,
                default=bootstrap.installation_id,
            ): _READ_ONLY_TEXT_SELECTOR,
            vol.Required(_CONF_ACTION, default=next(iter(actions))): vol.In(actions),
        }
    )


def _no_subscription_placeholders(bootstrap: BootstrapData) -> dict[str, str]:
    return {
        "reason": bootstrap.reason or SUBSCRIPTION_STATUS_NO_SUBSCRIPTION,
        "subscribe_url": PORTAL_BILLING_URL,
        "installation_id": bootstrap.installation_id,
    }


def _requires_trial_token_recovery(bootstrap: BootstrapData) -> bool:
    return (
        not bootstrap.entitled
        and bootstrap.reason == _BOOTSTRAP_REASON_TRIAL_DEVICE_TOKEN_REQUIRED
    )


def _entry_title(environment: str) -> str:
    normalized = normalize_environment(environment)
    if normalized == DEFAULT_ENVIRONMENT:
        return DEFAULT_TITLE
    return f"{DEFAULT_TITLE} ({display_environment(normalized)})"


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_installation_id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError:
        return value


def _is_valid_portal_connection_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False

    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/portal/horizoniq/connect"
    ):
        return False

    return True

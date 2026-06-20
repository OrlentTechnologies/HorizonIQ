from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import timedelta
from http import HTTPStatus
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from aiohttp import ClientError, ClientResponse, ContentTypeError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_API_KEY,
    CONF_FORECAST_DEVICE_ID,
    CONF_FORECAST_DEVICE_TOKEN,
    CONF_FORECAST_FUNCTION_KEY,
    CONF_HASH,
    CONF_REGISTRATION_DATA,
    CONF_SUBSCRIPTION_STATUS,
    CONF_URL,
    DEFAULT_FORECAST_CADENCE_MINUTES,
    DOMAIN,
    EXACT_SUBSCRIPTION_FAILURE_BODY,
    FAILED_REFRESH_RETRY_SECONDS,
    HEADER_API_KEY,
    HEADER_MESH_DEVICE_ID,
    HEADER_MESH_DEVICE_TOKEN,
    ISSUE_ENTITLEMENT_LOST,
    ISSUE_FORECAST_CREDENTIAL_REFRESH,
    REQUEST_TIMEOUT_SECONDS,
    SUBSCRIPTION_STATUS_NO_SUBSCRIPTION,
    normalize_environment,
)
from .coordinator_helpers import (
    build_snapshot,
    extract_forecast_cadence_minutes_from_registration_data,
    normalize_trial,
)
from .models import ForecastData, ForecastPeriod, MeshSolarSnapshot

_LOGGER = logging.getLogger(__name__)


class MeshSolarCoordinator(DataUpdateCoordinator[MeshSolarSnapshot]):
    """Fetch and normalize Mesh Solar data for the integration."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        url: str,
        api_key: str,
        battery_capacity_sensor: str,
        environment: str,
        forecast_device_id: str = "",
        forecast_device_token: str = "",
        forecast_function_key: str = "",
        initial_hash: str | None = None,
        initial_registration: str | None = None,
        credential_refresh: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._url = url
        self._api_key = api_key
        self._forecast_device_id = forecast_device_id.strip()
        self._forecast_device_token = forecast_device_token.strip()
        self._forecast_function_key = forecast_function_key.strip()
        self._battery_capacity_sensor = battery_capacity_sensor
        self._session = async_get_clientsession(hass)
        self._last_hash = (initial_hash or "").strip()
        self._registration_data = (initial_registration or "").strip()
        self._credential_refresh = credential_refresh
        self._forecast_cadence_minutes = extract_forecast_cadence_minutes_from_registration_data(
            self._registration_data
        )
        self._effective_forecast_cadence_minutes = (
            self._forecast_cadence_minutes or DEFAULT_FORECAST_CADENCE_MINUTES
        )
        self._latest_snapshot = MeshSolarSnapshot()
        self.environment = normalize_environment(environment)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=self._effective_forecast_cadence_minutes),
        )

    @property
    def last_hash(self) -> str:
        """Return the latest cached forecast hash."""
        return self._last_hash

    @property
    def registration_data(self) -> str:
        """Return the latest cached registration data."""
        return self._registration_data

    @property
    def forecast_cadence_minutes(self) -> int | None:
        """Return the last backend-reported polling cadence in minutes."""
        return self._forecast_cadence_minutes

    @property
    def effective_forecast_cadence_minutes(self) -> int:
        """Return the effective polling cadence in minutes."""
        return self._effective_forecast_cadence_minutes

    @property
    def currency(self) -> str | None:
        """Return the current forecast currency."""
        return self._current_snapshot.currency

    @property
    def forecast_periods(self) -> list[ForecastPeriod]:
        """Return normalized forecast periods."""
        return self._current_snapshot.forecast_periods

    @property
    def forecast(self) -> ForecastData:
        """Return the normalized forecast payload."""
        return self._current_snapshot.forecast

    @property
    def target_capacity(self) -> float | None:
        """Return the target capacity from the current snapshot."""
        return self._current_snapshot.target_capacity

    async def _async_update_data(self) -> MeshSolarSnapshot:
        """Fetch the latest Mesh Solar data."""
        battery_capacity = self._current_battery_capacity()
        request_url = self._build_request_url(battery_capacity)
        _LOGGER.debug(
            "Requesting Mesh Solar forecast for entry %s from %s",
            self._entry.entry_id,
            self._redacted_request_target(request_url),
        )

        try:
            payload = await self._fetch_payload(
                request_url=request_url,
                battery_capacity=battery_capacity,
            )
        except UpdateFailed as err:
            if str(err) == EXACT_SUBSCRIPTION_FAILURE_BODY:
                raise
            raise UpdateFailed(
                str(err),
                retry_after=FAILED_REFRESH_RETRY_SECONDS,
            ) from err
        snapshot = build_snapshot(payload)
        if snapshot.forecast_cadence_minutes is not None:
            self._set_forecast_cadence_minutes(snapshot.forecast_cadence_minutes)
        self._latest_snapshot = snapshot

        if self._update_cached_state(snapshot):
            self._persist_state()

        _LOGGER.debug(
            "Fetched Mesh Solar forecast for entry %s with %s periods",
            self._entry.entry_id,
            len(snapshot.forecast_periods),
        )
        return snapshot

    @property
    def _current_snapshot(self) -> MeshSolarSnapshot:
        """Return the freshest available snapshot."""
        if self.data is not None:
            return self.data
        return self._latest_snapshot

    async def async_clear_registration_data(self) -> None:
        """Clear cached registration data and refresh the coordinator."""
        if self._registration_data:
            _LOGGER.info(
                "Clearing registration data for entry %s", self._entry.entry_id
            )
        else:
            _LOGGER.info(
                "Registration data already empty for entry %s", self._entry.entry_id
            )

        self._registration_data = ""
        self._reset_forecast_cadence_minutes()
        self._persist_state()
        try:
            await self.async_request_refresh()
        except UpdateFailed as err:
            _LOGGER.warning(
                "Registration data was cleared for entry %s, but refresh failed: %s",
                self._entry.entry_id,
                err,
            )

    async def _fetch_payload(
        self,
        *,
        request_url: str,
        battery_capacity: str,
        allow_credential_refresh: bool = True,
    ) -> dict[str, object]:
        headers = self._build_request_headers()
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                async with self._session.get(request_url, headers=headers) as response:
                    if response.status != HTTPStatus.OK:
                        if response.status == HTTPStatus.BAD_REQUEST:
                            body = (await response.text()).strip()
                            if body == EXACT_SUBSCRIPTION_FAILURE_BODY:
                                self._handle_subscription_loss()
                                raise UpdateFailed(EXACT_SUBSCRIPTION_FAILURE_BODY)
                        if response.status in {
                            HTTPStatus.UNAUTHORIZED,
                            HTTPStatus.FORBIDDEN,
                        }:
                            if (
                                allow_credential_refresh
                                and self._credential_refresh is not None
                                and await self._async_refresh_forecast_credentials()
                            ):
                                retry_url = self._build_request_url(battery_capacity)
                                _LOGGER.info(
                                    "Retrying Mesh Solar forecast for entry %s after credential refresh",
                                    self._entry.entry_id,
                                )
                                return await self._fetch_payload(
                                    request_url=retry_url,
                                    battery_capacity=battery_capacity,
                                    allow_credential_refresh=False,
                                )

                            if self._credential_refresh is not None:
                                self._handle_forecast_credential_refresh_failed()
                                raise UpdateFailed(
                                    "Forecast credentials could not be refreshed"
                                )

                            payload = await self._read_optional_json_payload(response)
                            _LOGGER.info(
                                "Mesh Solar API returned unauthorized forecast "
                                "response for entry %s",
                                self._entry.entry_id,
                            )
                            return self._authorization_diagnostic_payload(
                                response=response,
                                payload=payload,
                            )
                        raise UpdateFailed(f"API returned status {response.status}")
                    payload = await self._read_json_payload(response)
        except TimeoutError as err:
            raise UpdateFailed("Timed out fetching Mesh Solar data") from err
        except ClientError as err:
            raise UpdateFailed(f"Error communicating with Mesh Solar API: {err}") from err

        if not isinstance(payload, dict):
            raise UpdateFailed("Mesh Solar API returned an unexpected payload shape")
        return payload

    async def _async_refresh_forecast_credentials(self) -> bool:
        if self._credential_refresh is None:
            return False

        try:
            refreshed = await self._credential_refresh()
        except Exception:
            _LOGGER.warning(
                "Mesh Solar forecast credential refresh failed for entry %s",
                self._entry.entry_id,
                exc_info=True,
            )
            return False

        if not refreshed:
            return False

        self._reload_forecast_credentials_from_entry()
        return True

    def _reload_forecast_credentials_from_entry(self) -> None:
        entry_data = self._entry.data
        self._url = str(entry_data.get(CONF_URL, self._url) or self._url)
        self._api_key = str(entry_data.get(CONF_API_KEY, self._api_key) or self._api_key)
        self._forecast_device_id = str(
            entry_data.get(CONF_FORECAST_DEVICE_ID, self._forecast_device_id)
            or ""
        ).strip()
        self._forecast_device_token = str(
            entry_data.get(CONF_FORECAST_DEVICE_TOKEN, self._forecast_device_token)
            or ""
        ).strip()
        self._forecast_function_key = str(
            entry_data.get(CONF_FORECAST_FUNCTION_KEY, self._forecast_function_key)
            or ""
        ).strip()

    @staticmethod
    def _authorization_diagnostic_payload(
        *,
        response: ClientResponse,
        payload: Mapping[str, object] | None,
    ) -> dict[str, object]:
        diagnostic_payload = dict(payload or {})
        diagnostic_payload.setdefault("AuthorizationStatus", "unauthorized")
        diagnostic_payload.setdefault("AuthorizationStatusCode", response.status)
        diagnostic_payload.setdefault(
            "AuthorizationMessage",
            "Forecast request was rejected with HTTP 401 Unauthorized.",
        )

        if normalize_trial(diagnostic_payload):
            return diagnostic_payload

        return {
            "AuthorizationStatus": "unauthorized",
            "AuthorizationStatusCode": response.status,
            "AuthorizationMessage": (
                "Forecast request was rejected with HTTP 401 Unauthorized."
            ),
        }

    async def _read_json_payload(self, response: ClientResponse) -> object:
        try:
            return await response.json(content_type=None)
        except (ContentTypeError, ValueError) as err:
            raise UpdateFailed("Mesh Solar API returned invalid JSON") from err

    @staticmethod
    async def _read_optional_json_payload(
        response: ClientResponse,
    ) -> dict[str, object] | None:
        try:
            payload = await response.json(content_type=None)
        except (ContentTypeError, ValueError):
            return None

        if not isinstance(payload, dict):
            return None
        return payload

    def _build_request_headers(self) -> dict[str, str]:
        """Build forecast request headers without exposing trial data in the URL."""
        headers = {HEADER_API_KEY: self._api_key}
        if self._forecast_device_id and self._forecast_device_token:
            headers[HEADER_MESH_DEVICE_ID] = self._forecast_device_id
            headers[HEADER_MESH_DEVICE_TOKEN] = self._forecast_device_token
        return headers

    def _current_battery_capacity(self) -> str:
        battery_state = self._hass.states.get(self._battery_capacity_sensor)
        if battery_state is None:
            _LOGGER.debug(
                "Battery capacity entity %s is unavailable for entry %s",
                self._battery_capacity_sensor,
                self._entry.entry_id,
            )
            return ""
        return str(battery_state.state or "")

    def _build_request_url(self, battery_capacity: str) -> str:
        parsed = urlparse(self._url)
        query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if self._forecast_function_key:
            query_params["code"] = self._forecast_function_key
        query_params["currentBatteryCapacity"] = battery_capacity
        query_params["hash"] = self._last_hash
        query_params["registrationData"] = self._registration_data
        new_query = urlencode(query_params, doseq=True)
        return urlunparse(parsed._replace(query=new_query))

    @staticmethod
    def _redacted_request_target(request_url: str) -> str:
        parsed = urlparse(request_url)
        return urlunparse(parsed._replace(params="", query="", fragment=""))

    def _update_cached_state(self, snapshot: MeshSolarSnapshot) -> bool:
        updated = False

        if (
            snapshot.forecast_hash is not None
            and snapshot.forecast_hash != self._last_hash
        ):
            self._last_hash = snapshot.forecast_hash
            updated = True
            _LOGGER.debug("Stored new forecast hash for entry %s", self._entry.entry_id)

        if (
            snapshot.registration_data is not None
            and snapshot.registration_data != self._registration_data
        ):
            self._registration_data = snapshot.registration_data
            updated = True
            _LOGGER.debug(
                "Stored new registration data for entry %s", self._entry.entry_id
            )

        return updated

    def _persist_state(self) -> None:
        entry_data = dict(self._entry.data)
        updated = False

        if entry_data.get(CONF_HASH, "") != self._last_hash:
            entry_data[CONF_HASH] = self._last_hash
            updated = True
        if entry_data.get(CONF_REGISTRATION_DATA, "") != self._registration_data:
            entry_data[CONF_REGISTRATION_DATA] = self._registration_data
            updated = True

        if updated:
            self._hass.config_entries.async_update_entry(self._entry, data=entry_data)

    def _handle_subscription_loss(self) -> None:
        """Persist terminal entitlement loss and pause normal polling."""
        self._last_hash = ""
        self._registration_data = ""
        self.update_interval = None

        entry_data = dict(self._entry.data)
        entry_data[CONF_HASH] = ""
        entry_data[CONF_REGISTRATION_DATA] = ""
        entry_data[CONF_SUBSCRIPTION_STATUS] = SUBSCRIPTION_STATUS_NO_SUBSCRIPTION
        self._hass.config_entries.async_update_entry(self._entry, data=entry_data)

        ir.async_create_issue(
            self._hass,
            DOMAIN,
            ISSUE_ENTITLEMENT_LOST,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_ENTITLEMENT_LOST,
            translation_placeholders={"subscribe_url": ""},
        )

    def _handle_forecast_credential_refresh_failed(self) -> None:
        """Pause polling after a failed function-key refresh attempt."""
        self.update_interval = None
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            ISSUE_FORECAST_CREDENTIAL_REFRESH,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_FORECAST_CREDENTIAL_REFRESH,
        )

    def _set_forecast_cadence_minutes(self, cadence_minutes: int | None) -> None:
        previous_effective = self._effective_forecast_cadence_minutes
        self._forecast_cadence_minutes = cadence_minutes
        resolved_minutes = cadence_minutes or DEFAULT_FORECAST_CADENCE_MINUTES
        self._effective_forecast_cadence_minutes = resolved_minutes
        if resolved_minutes == previous_effective:
            return

        self.update_interval = timedelta(minutes=resolved_minutes)
        _LOGGER.debug(
            "Set Mesh Solar backend polling cadence for entry %s to %s minute(s)",
            self._entry.entry_id,
            resolved_minutes,
        )

    def _reset_forecast_cadence_minutes(self) -> None:
        """Reset to the default polling cadence until a backend value is known."""
        self._forecast_cadence_minutes = None
        previous_effective = self._effective_forecast_cadence_minutes
        self._effective_forecast_cadence_minutes = DEFAULT_FORECAST_CADENCE_MINUTES
        if previous_effective == self._effective_forecast_cadence_minutes:
            return

        self.update_interval = timedelta(
            minutes=self._effective_forecast_cadence_minutes
        )
        _LOGGER.debug(
            "Reset Mesh Solar backend polling cadence for entry %s to default %s minute(s)",
            self._entry.entry_id,
            self._effective_forecast_cadence_minutes,
        )

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from http import HTTPStatus
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    HEADER_API_KEY,
    HEADER_MESH_DEVICE_ID,
    HEADER_MESH_DEVICE_TOKEN,
    CONF_HASH,
    CONF_REGISTRATION_DATA,
    DEFAULT_FORECAST_CADENCE_MINUTES,
    DOMAIN,
    FAILED_REFRESH_RETRY_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    normalize_environment,
)
from .coordinator_helpers import (
    build_snapshot,
    extract_forecast_cadence_minutes_from_registration_data,
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
        initial_hash: str | None = None,
        initial_registration: str | None = None,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._url = url
        self._api_key = api_key
        self._forecast_device_id = forecast_device_id.strip()
        self._forecast_device_token = forecast_device_token.strip()
        self._battery_capacity_sensor = battery_capacity_sensor
        self._session = async_get_clientsession(hass)
        self._last_hash = (initial_hash or "").strip()
        self._registration_data = (initial_registration or "").strip()
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
            payload = await self._fetch_payload(request_url=request_url)
        except UpdateFailed as err:
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

    async def _fetch_payload(self, *, request_url: str) -> dict[str, object]:
        headers = self._build_request_headers()
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                async with self._session.get(request_url, headers=headers) as response:
                    if response.status != HTTPStatus.OK:
                        raise UpdateFailed(f"API returned status {response.status}")
                    payload = await response.json()
        except TimeoutError as err:
            raise UpdateFailed("Timed out fetching Mesh Solar data") from err
        except ClientError as err:
            raise UpdateFailed(f"Error communicating with Mesh Solar API: {err}") from err
        except ValueError as err:
            raise UpdateFailed("Mesh Solar API returned invalid JSON") from err

        if not isinstance(payload, dict):
            raise UpdateFailed("Mesh Solar API returned an unexpected payload shape")
        return payload

    def _build_request_headers(self) -> dict[str, str]:
        """Build forecast request headers without exposing trial data in the URL."""
        headers = {HEADER_API_KEY: self._api_key}
        if self._forecast_device_id:
            headers[HEADER_MESH_DEVICE_ID] = self._forecast_device_id
        if self._forecast_device_token:
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

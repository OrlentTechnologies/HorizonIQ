from __future__ import annotations

import asyncio
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any, Protocol

from aiohttp import ClientError, ClientResponse, ClientSession, ContentTypeError
from yarl import URL

from .bootstrap import BootstrapData, parse_bootstrap_response
from .const import (
    BOOTSTRAP_PATH,
    INTEGRATION_VERSION,
    REQUEST_TIMEOUT_SECONDS,
    TRIAL_START_PATH,
)


class AuthenticatedSession(Protocol):
    """Minimal OAuth session contract used by the bootstrap client."""

    async def async_request(
        self, method: str, url: str, **kwargs: Any
    ) -> ClientResponse:
        """Make an OAuth-authenticated request."""


class StaticAccessTokenSession:
    """OAuth request adapter for a newly acquired config-flow token."""

    def __init__(self, session: ClientSession, access_token: str) -> None:
        self._session = session
        self._access_token = access_token

    async def async_request(
        self, method: str, url: str, **kwargs: Any
    ) -> ClientResponse:
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {self._access_token}"
        return await self._session.request(method, url, headers=headers, **kwargs)


class HorizonIQApiError(Exception):
    """Base API error with secret-free messages."""


class HorizonIQApiAuthError(HorizonIQApiError):
    """Raised when the backend rejects OAuth authentication."""


class HorizonIQApiTransientError(HorizonIQApiError):
    """Raised for temporary backend or network failures."""


class HorizonIQBootstrapClient:
    """Client for Entra-protected bootstrap and trial operations."""

    def __init__(
        self,
        *,
        oauth_session: AuthenticatedSession,
        backend_api_base_url: str,
    ) -> None:
        self._oauth_session = oauth_session
        self._backend_api_base_url = backend_api_base_url.rstrip("/")

    async def async_bootstrap(
        self,
        *,
        installation_id: str,
        device_token: str | None,
        rotate_device_token: bool = False,
    ) -> BootstrapData:
        payload = await self._async_post_json(
            BOOTSTRAP_PATH,
            {
                "installationId": installation_id,
                "deviceToken": device_token or None,
                "rotateDeviceToken": rotate_device_token,
                "integrationVersion": INTEGRATION_VERSION,
            },
        )
        return parse_bootstrap_response(
            payload,
            requested_installation_id=installation_id,
        )

    async def async_start_trial(self, *, installation_id: str) -> str:
        payload = await self._async_post_json(
            TRIAL_START_PATH,
            {
                "deviceId": installation_id,
                "deviceDisplayName": "Home Assistant",
            },
        )
        if not isinstance(payload, Mapping):
            raise HorizonIQApiError("Trial start returned an invalid response")
        token = payload.get("deviceToken")
        if not isinstance(token, str) or not token.strip():
            raise HorizonIQApiError("Trial start did not return a device token")
        return token.strip()

    async def _async_post_json(
        self, path: str, body: dict[str, object]
    ) -> object:
        url = str(URL(self._backend_api_base_url).with_path(path))
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                response = await self._oauth_session.async_request(
                    "POST",
                    url,
                    json=body,
                    headers={"Content-Type": "application/json"},
                )
                async with response:
                    if response.status == HTTPStatus.UNAUTHORIZED:
                        raise HorizonIQApiAuthError(
                            "HorizonIQ sign-in is no longer valid"
                        )
                    if response.status == HTTPStatus.TOO_MANY_REQUESTS or (
                        HTTPStatus.INTERNAL_SERVER_ERROR
                        <= response.status
                        <= HTTPStatus.NETWORK_AUTHENTICATION_REQUIRED
                    ):
                        raise HorizonIQApiTransientError(
                            "HorizonIQ service is temporarily unavailable"
                        )
                    if response.status >= HTTPStatus.BAD_REQUEST:
                        raise HorizonIQApiError(
                            f"HorizonIQ request failed with status {response.status}"
                        )
                    try:
                        return await response.json(content_type=None)
                    except (ContentTypeError, ValueError) as err:
                        raise HorizonIQApiError(
                            "HorizonIQ returned invalid JSON"
                        ) from err
        except TimeoutError as err:
            raise HorizonIQApiTransientError("HorizonIQ request timed out") from err
        except ClientError as err:
            raise HorizonIQApiTransientError(
                "Unable to communicate with HorizonIQ"
            ) from err

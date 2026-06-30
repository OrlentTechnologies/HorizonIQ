from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

from aiohttp import ClientError, ClientSession, ContentTypeError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import (
    LocalOAuth2ImplementationWithPkce,
)

from .const import PORTAL_CONNECT_URL, PORTAL_RUNTIME_CONFIG_URL, REQUEST_TIMEOUT_SECONDS


class OAuthRuntimeConfigError(ValueError):
    """Raised when public OAuth runtime configuration is unavailable or invalid."""


@dataclass(frozen=True, slots=True)
class OAuthRuntimeConfig:
    """Public deployment values needed by the Home Assistant OAuth client."""

    client_id: str
    portal_connection_url: str
    token_endpoint: str
    backend_api_scope: str
    backend_api_base_url: str


class HorizonIQOAuth2Implementation(LocalOAuth2ImplementationWithPkce):
    """Home Assistant PKCE implementation routed through the HorizonIQ portal."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        auth_domain: str,
        runtime: OAuthRuntimeConfig,
    ) -> None:
        super().__init__(
            hass,
            auth_domain,
            runtime.client_id,
            authorize_url=runtime.portal_connection_url,
            token_url=runtime.token_endpoint,
            client_secret="",
        )
        self._runtime = runtime

    @property
    def name(self) -> str:
        """Return the public OAuth implementation name."""
        return "HorizonIQ"

    @property
    def extra_token_resolve_data(self) -> dict[str, str]:
        """Redeem the code for the same backend scope requested by the portal."""
        data = dict(super().extra_token_resolve_data)
        data["scope"] = (
            "openid profile offline_access " + self._runtime.backend_api_scope
        )
        return data


async def async_get_oauth_runtime_config(
    hass: HomeAssistant,
    portal_connection_url: str | None = None,
) -> OAuthRuntimeConfig:
    """Fetch and validate public OAuth deployment configuration."""
    return await async_fetch_oauth_runtime_config(
        async_get_clientsession(hass),
        portal_connection_url=portal_connection_url,
    )


async def async_fetch_oauth_runtime_config(
    session: ClientSession,
    portal_connection_url: str | None = None,
) -> OAuthRuntimeConfig:
    """Fetch public OAuth deployment configuration."""
    runtime_config_url = _runtime_config_url(portal_connection_url)
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
            async with session.get(runtime_config_url) as response:
                if response.status != 200:
                    raise OAuthRuntimeConfigError(
                        "HorizonIQ OAuth configuration is unavailable"
                    )
                try:
                    payload: Any = await response.json(content_type=None)
                except (ContentTypeError, ValueError) as err:
                    raise OAuthRuntimeConfigError(
                        "HorizonIQ OAuth configuration is invalid"
                    ) from err
    except TimeoutError as err:
        raise OAuthRuntimeConfigError(
            "Timed out loading HorizonIQ OAuth configuration"
        ) from err
    except ClientError as err:
        raise OAuthRuntimeConfigError(
            "Unable to load HorizonIQ OAuth configuration"
        ) from err

    if not isinstance(payload, dict):
        raise OAuthRuntimeConfigError("HorizonIQ OAuth configuration is invalid")

    token_endpoint = await _resolve_token_endpoint(session, payload)
    backend_api_scope = _optional_text(payload, "haBackendApiScope")
    if backend_api_scope is None:
        backend_api_scope = _required_text(payload, "backendApiScope")

    backend_api_base_url = _required_https_url(payload, "backendApiBaseUrl")

    return OAuthRuntimeConfig(
        client_id=_required_text(payload, "haEntraClientId"),
        portal_connection_url=_validated_portal_connection_url(
            portal_connection_url
        )
        or _optional_https_url(payload, "haPortalConnectionUrl")
        or PORTAL_CONNECT_URL,
        token_endpoint=token_endpoint,
        backend_api_scope=backend_api_scope,
        backend_api_base_url=backend_api_base_url.rstrip("/"),
    )


def _runtime_config_url(portal_connection_url: str | None) -> str:
    portal_url = _validated_portal_connection_url(portal_connection_url)
    if portal_url is None:
        return PORTAL_RUNTIME_CONFIG_URL

    parsed = urlparse(portal_url)
    return urlunparse(parsed._replace(path="/config.json", query="", fragment=""))


def _validated_portal_connection_url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None

    normalized = value.strip()
    parsed = urlparse(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/portal/horizoniq/connect"
    ):
        raise OAuthRuntimeConfigError("Invalid Home Assistant portal connection URL")

    return urlunparse(parsed._replace(path=parsed.path.rstrip("/")))


async def _resolve_token_endpoint(
    session: ClientSession,
    payload: dict[str, object],
) -> str:
    token_endpoint = _optional_https_url(payload, "haEntraTokenEndpoint")
    if token_endpoint is not None:
        return token_endpoint

    authorize_endpoint = _optional_https_url(payload, "haEntraAuthorizeEndpoint")
    if authorize_endpoint is not None:
        return _derive_token_endpoint(authorize_endpoint)

    authority = _optional_https_url(payload, "haEntraAuthority")
    if authority is None:
        authority = _optional_https_url(payload, "entraAuthority")
    if authority is None:
        raise OAuthRuntimeConfigError("Missing OAuth runtime field: entraAuthority")

    discovered = await _try_discover_token_endpoint(session, authority)
    if discovered is not None:
        return discovered

    return _derive_token_endpoint_from_authority(authority)


async def _try_discover_token_endpoint(
    session: ClientSession,
    authority: str,
) -> str | None:
    for metadata_url in _openid_configuration_candidates(authority):
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                async with session.get(metadata_url) as response:
                    if response.status != 200:
                        continue
                    payload: Any = await response.json(content_type=None)
        except (TimeoutError, ClientError, ContentTypeError, ValueError):
            continue

        if not isinstance(payload, dict):
            continue
        token_endpoint = _optional_https_url(payload, "token_endpoint")
        if token_endpoint is not None:
            return token_endpoint

    return None


def _openid_configuration_candidates(authority: str) -> list[str]:
    normalized = authority.rstrip("/")
    parsed = urlparse(normalized)
    path = parsed.path.rstrip("/")
    candidates = [f"{normalized}/.well-known/openid-configuration"]
    if path.lower().endswith("/v2.0"):
        base_path = path[: -len("/v2.0")]
        candidate = urlunparse(
            parsed._replace(
                path=f"{base_path}/v2.0/.well-known/openid-configuration",
                query="",
                fragment="",
            )
        )
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _derive_token_endpoint_from_authority(authority: str) -> str:
    parsed = urlparse(authority)
    path = parsed.path.rstrip("/")
    if path.lower().endswith("/oauth2/v2.0"):
        token_path = f"{path}/token"
    elif path.lower().endswith("/v2.0"):
        token_path = f"{path[:-len('/v2.0')]}/oauth2/v2.0/token"
    else:
        token_path = f"{path}/oauth2/v2.0/token"

    return urlunparse(parsed._replace(path=token_path, query="", fragment=""))


def _derive_token_endpoint(authorize_endpoint: str) -> str:
    parsed = urlparse(authorize_endpoint)
    path = parsed.path.rstrip("/")
    if not path.endswith("/authorize"):
        raise OAuthRuntimeConfigError("Invalid Entra authorize endpoint")
    token_path = f"{path.removesuffix('/authorize')}/token"
    return urlunparse(parsed._replace(path=token_path, query="", fragment=""))


def _required_text(payload: dict[str, object], key: str) -> str:
    value = _optional_text(payload, key)
    if value is None:
        raise OAuthRuntimeConfigError(f"Missing OAuth runtime field: {key}")
    return value


def _optional_text(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _required_https_url(payload: dict[str, object], key: str) -> str:
    value = _required_text(payload, key)
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username:
        raise OAuthRuntimeConfigError(f"Invalid OAuth runtime field: {key}")
    return value


def _optional_https_url(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username:
        raise OAuthRuntimeConfigError(f"Invalid OAuth runtime field: {key}")
    return value

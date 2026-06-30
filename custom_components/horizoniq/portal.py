from __future__ import annotations

from urllib.parse import urlparse, urlunparse

from .const import PORTAL_BILLING_URL

_PORTAL_CONNECT_PATH = "/portal/horizoniq/connect"
_PORTAL_BILLING_PATH = "/portal/billing"


def normalize_portal_connection_url(value: str) -> str:
    """Return a canonical portal connect URL or raise ValueError."""
    normalized = value.strip()
    parsed = urlparse(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != _PORTAL_CONNECT_PATH
    ):
        raise ValueError("Invalid Home Assistant portal connection URL")

    return urlunparse(
        parsed._replace(
            path=parsed.path.rstrip("/"),
            params="",
            query="",
            fragment="",
        )
    )


def is_portal_connection_url(value: str) -> bool:
    """Return whether the supplied value is a valid portal connect URL."""
    try:
        normalize_portal_connection_url(value)
    except ValueError:
        return False
    return True


def portal_base_url_from_connection_url(value: str) -> str:
    """Return the scheme and host for a valid portal connect URL."""
    parsed = urlparse(normalize_portal_connection_url(value))
    return urlunparse(parsed._replace(path="", params="", query="", fragment=""))


def billing_url_from_portal_connection_url(portal_connection_url: str | None) -> str:
    """Return the billing URL for a portal connect URL or production fallback."""
    if portal_connection_url is None or not portal_connection_url.strip():
        return PORTAL_BILLING_URL

    try:
        portal_base_url = portal_base_url_from_connection_url(portal_connection_url)
    except ValueError:
        return PORTAL_BILLING_URL

    return f"{portal_base_url}{_PORTAL_BILLING_PATH}"

"""Tests for portal URL helpers."""

import pytest

from custom_components.horizoniq.const import PORTAL_BILLING_URL
from custom_components.horizoniq.portal import (
    billing_url_from_portal_connection_url,
    is_portal_connection_url,
    normalize_portal_connection_url,
    portal_base_url_from_connection_url,
)


def test_portal_base_url_is_derived_from_connect_url() -> None:
    """Portal base drops the connect path while preserving scheme and host."""
    portal_connection_url = "https://sandbox.example.test/portal/horizoniq/connect"

    assert portal_base_url_from_connection_url(portal_connection_url) == (
        "https://sandbox.example.test"
    )
    assert billing_url_from_portal_connection_url(portal_connection_url) == (
        "https://sandbox.example.test/portal/billing"
    )


def test_normalize_portal_connection_url_removes_trailing_slash() -> None:
    """Valid connect URLs are normalized to a stable form."""
    assert normalize_portal_connection_url(
        " https://sandbox.example.test/portal/horizoniq/connect/ "
    ) == "https://sandbox.example.test/portal/horizoniq/connect"


def test_horizoniq_connect_url_is_accepted() -> None:
    """The HorizonIQ portal connect URL remains accepted in validation."""
    assert is_portal_connection_url(
        "https://sandbox.example.test/portal/horizoniq/connect"
    )


@pytest.mark.parametrize(
    "portal_connection_url",
    [
        "http://sandbox.example.test/portal/horizoniq/connect",
        "https://sandbox.example.test/portal/horizoniq",
        "https://sandbox.example.test/portal/horizoniq/connect?x=1",
    ],
)
def test_portal_helpers_reject_invalid_connect_urls(
    portal_connection_url: str,
) -> None:
    """Invalid connect URLs raise in strict helpers and fall back in billing lookup."""
    with pytest.raises(ValueError):
        portal_base_url_from_connection_url(portal_connection_url)

    assert (
        billing_url_from_portal_connection_url(portal_connection_url)
        == PORTAL_BILLING_URL
    )

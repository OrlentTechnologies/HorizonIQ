"""Tests for persisted config-entry data helpers."""

from custom_components.horizoniq.bootstrap import BootstrapData
from custom_components.horizoniq.const import (
    CONF_BOOTSTRAP_REASON,
    CONF_SUBSCRIPTION_STATUS,
    CONF_SUBSCRIBE_URL,
    PORTAL_BILLING_URL,
    SUBSCRIPTION_STATUS_NO_SUBSCRIPTION,
)
from custom_components.horizoniq.entry_data import (
    CONF_OAUTH_RUNTIME,
    billing_url_from_entry_data,
    no_subscription_entry_data,
)
from custom_components.horizoniq.oauth import OAuthRuntimeConfig


def test_no_subscription_entry_data_persists_runtime_portal() -> None:
    """No-subscription updates keep the OAuth runtime needed for later redirects."""
    runtime = OAuthRuntimeConfig(
        client_id="ha-client",
        portal_connection_url="https://sandbox.example.test/portal/horizoniq/connect",
        token_endpoint="https://login.example.test/token",
        backend_api_scope="api://backend/user_impersonation",
        backend_api_base_url="https://api.example.test",
    )

    entry_data = no_subscription_entry_data(
        BootstrapData(
            schema_version=1,
            subscription_status=SUBSCRIPTION_STATUS_NO_SUBSCRIPTION,
            can_forecast=False,
            registration_id=None,
            installation_id="76d85cbc-5a44-4e41-88f7-f02f41562f15",
            refresh_after_utc="2026-06-16T12:00:00Z",
            entitlement_expires_on_utc=None,
            registration={},
            forecast=None,
            reason="no_subscription",
            subscribe_url=PORTAL_BILLING_URL,
            trial=None,
        ),
        runtime=runtime,
    )

    assert entry_data[CONF_SUBSCRIPTION_STATUS] == SUBSCRIPTION_STATUS_NO_SUBSCRIPTION
    assert entry_data[CONF_BOOTSTRAP_REASON] == "no_subscription"
    assert entry_data[CONF_OAUTH_RUNTIME] == {
        "client_id": "ha-client",
        "portal_connection_url": (
            "https://sandbox.example.test/portal/horizoniq/connect"
        ),
        "token_endpoint": "https://login.example.test/token",
        "backend_api_scope": "api://backend/user_impersonation",
        "backend_api_base_url": "https://api.example.test",
    }
    assert (
        entry_data[CONF_SUBSCRIBE_URL]
        == "https://sandbox.example.test/portal/billing"
    )


def test_billing_url_from_entry_data_prefers_persisted_runtime() -> None:
    """Repair links derive from the stored runtime portal before legacy fallbacks."""
    assert billing_url_from_entry_data(
        {
            CONF_OAUTH_RUNTIME: {
                "client_id": "ha-client",
                "portal_connection_url": (
                    "https://sandbox.example.test/portal/horizoniq/connect"
                ),
                "token_endpoint": "https://login.example.test/token",
                "backend_api_scope": "api://backend/user_impersonation",
                "backend_api_base_url": "https://api.example.test",
            },
            CONF_SUBSCRIBE_URL: PORTAL_BILLING_URL,
        }
    ) == "https://sandbox.example.test/portal/billing"


def test_billing_url_from_entry_data_falls_back_to_production() -> None:
    """Missing runtime data uses the production billing URL."""
    assert billing_url_from_entry_data({}) == PORTAL_BILLING_URL

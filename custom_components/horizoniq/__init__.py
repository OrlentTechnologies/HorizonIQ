from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from .api import (
    HorizonIQApiAuthError,
    HorizonIQApiError,
    HorizonIQApiTransientError,
    HorizonIQBootstrapClient,
)
from .bootstrap import BootstrapValidationError
from .config_data import merged_config_data, validate_config_data
from .const import (
    CONF_API_KEY,
    CONF_BATTERY_CAPACITY_SENSOR,
    CONF_BOOTSTRAP_REFRESH_AFTER_UTC,
    CONF_ENVIRONMENT,
    CONF_FORECAST_DEVICE_ID,
    CONF_FORECAST_DEVICE_TOKEN,
    CONF_FORECAST_FUNCTION_KEY,
    CONF_HASH,
    CONF_INSTALLATION_ID,
    CONF_REGISTRATION_DATA,
    CONF_SUBSCRIBE_URL,
    CONF_SUBSCRIPTION_STATUS,
    CONF_URL,
    DEFAULT_ENVIRONMENT,
    DOMAIN,
    ENTITLED_SUBSCRIPTION_STATUSES,
    ISSUE_ENTITLEMENT_LOST,
    ISSUE_FORECAST_CREDENTIAL_REFRESH,
    PORTAL_BILLING_URL,
    PLATFORMS,
)
from .coordinator import HorizonIQCoordinator
from .entry_data import (
    entry_data_from_bootstrap,
    no_subscription_entry_data,
    runtime_from_entry_data,
)
from .entity_helpers import build_unique_id
from .models import HorizonIQConfigData
from .oauth import HorizonIQOAuth2Implementation

_LOGGER = logging.getLogger(__name__)
_CONFIG_ENTRY_VERSION = 2
_LOCAL_DOCS_READY_KEY = f"{DOMAIN}_local_docs_ready"
_LOCAL_DOCS_SOURCE = "local_docs/index.html"
_LOCAL_DOCS_TARGET = ("www", "horizoniq", "index.html")
_LEGACY_DEFAULT_ENVIRONMENT_ENTITY_SUFFIXES = (
    ("sensor", "total_cost"),
    ("sensor", "charging_cost"),
    ("sensor", "saving"),
    ("sensor", "forecast_diagnostics"),
    ("sensor", "bms_state"),
    ("binary_sensor", "import"),
    ("binary_sensor", "export"),
    ("button", "clear_registration"),
)
_ENTRY_KEYS = (
    CONF_URL,
    CONF_API_KEY,
    CONF_BATTERY_CAPACITY_SENSOR,
    CONF_ENVIRONMENT,
    CONF_HASH,
    CONF_REGISTRATION_DATA,
    CONF_FORECAST_DEVICE_ID,
    CONF_FORECAST_DEVICE_TOKEN,
)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old HorizonIQ config entries."""
    if entry.version > _CONFIG_ENTRY_VERSION:
        _LOGGER.error(
            "HorizonIQ config entry %s has unsupported version %s",
            entry.entry_id,
            entry.version,
        )
        return False

    if entry.version == _CONFIG_ENTRY_VERSION:
        return True

    if entry.version != 1:
        _LOGGER.error(
            "HorizonIQ config entry %s cannot migrate from version %s",
            entry.entry_id,
            entry.version,
        )
        return False

    config_data = merged_config_data(entry)
    updated_data = dict(entry.data)
    for key in _ENTRY_KEYS:
        updated_data[key] = config_data[key]

    updated_options = dict(entry.options)
    for key in _ENTRY_KEYS:
        updated_options.pop(key, None)

    hass.config_entries.async_update_entry(
        entry,
        data=updated_data,
        options=updated_options,
        version=_CONFIG_ENTRY_VERSION,
    )
    _LOGGER.info(
        "Migrated HorizonIQ config entry %s from version 1 to version %s",
        entry.entry_id,
        _CONFIG_ENTRY_VERSION,
    )
    return True


def _copy_local_docs_file(source_path: Path, target_path: Path) -> None:
    """Copy the bundled documentation page into Home Assistant's www folder."""
    if not source_path.exists():
        _LOGGER.warning(
            "Local docs source file missing at %s. Skipping docs publish.",
            source_path,
        )
        return

    desired_text = source_path.read_text(encoding="utf-8")
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if target_path.exists():
        target_text = target_path.read_text(encoding="utf-8")
        if target_text == desired_text:
            return

    target_path.write_text(desired_text, encoding="utf-8")


async def _ensure_local_docs(hass: HomeAssistant) -> None:
    """Publish the bundled local documentation page."""
    source_path = Path(__file__).resolve().parent / _LOCAL_DOCS_SOURCE
    target_path = Path(hass.config.path(*_LOCAL_DOCS_TARGET))
    try:
        await hass.async_add_executor_job(
            _copy_local_docs_file, source_path, target_path
        )
    except OSError as err:
        _LOGGER.warning("Unable to publish local documentation file: %s", err)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HorizonIQ from a config entry."""
    if not hass.data.get(_LOCAL_DOCS_READY_KEY):
        await _ensure_local_docs(hass)
        hass.data[_LOCAL_DOCS_READY_KEY] = True

    config_data = merged_config_data(entry)
    _sync_entry_data(hass=hass, entry=entry, config_data=config_data)

    if _is_bootstrap_entry(entry):
        await _async_refresh_bootstrap_if_due(hass, entry)
        if entry.data.get(CONF_SUBSCRIPTION_STATUS) not in ENTITLED_SUBSCRIPTION_STATUSES:
            _async_create_issue(
                hass,
                ISSUE_ENTITLEMENT_LOST,
                PORTAL_BILLING_URL,
            )
            raise ConfigEntryAuthFailed(
                "HorizonIQ trial or subscription is not valid. Subscribe, then reload or reconnect the integration."
            )
        config_data = merged_config_data(entry)

    validation_errors = validate_config_data(config_data)
    if validation_errors:
        invalid_fields = ", ".join(sorted(validation_errors))
        message = (
            f"Invalid configuration for entry {entry.entry_id}: {invalid_fields}. "
            "Reconfigure the integration."
        )
        _LOGGER.error(message)
        raise ConfigEntryNotReady(message)

    _migrate_legacy_default_environment_unique_ids(
        hass=hass,
        entry=entry,
        environment=config_data[CONF_ENVIRONMENT],
    )

    credential_refresh = (
        (lambda: _async_refresh_bootstrap_now(hass, entry))
        if _is_bootstrap_entry(entry)
        else None
    )

    coordinator = HorizonIQCoordinator(
        hass=hass,
        entry=entry,
        url=config_data[CONF_URL],
        api_key=config_data[CONF_API_KEY],
        battery_capacity_sensor=config_data[CONF_BATTERY_CAPACITY_SENSOR],
        environment=config_data[CONF_ENVIRONMENT],
        forecast_device_id=config_data[CONF_FORECAST_DEVICE_ID],
        forecast_device_token=config_data[CONF_FORECAST_DEVICE_TOKEN],
        forecast_function_key=str(entry.data.get(CONF_FORECAST_FUNCTION_KEY, "")),
        initial_hash=config_data[CONF_HASH],
        initial_registration=config_data[CONF_REGISTRATION_DATA],
        credential_refresh=credential_refresh,
    )
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady as err:
        _LOGGER.warning(
            "Initial refresh failed for entry %s; Home Assistant will retry setup. "
            "Error: %s",
            entry.entry_id,
            err,
        )
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        raise

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a HorizonIQ config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    _LOGGER.debug("HorizonIQ unloaded for entry %s", entry.entry_id)
    return unload_ok


def _sync_entry_data(
    *,
    hass: HomeAssistant,
    entry: ConfigEntry,
    config_data: HorizonIQConfigData,
) -> None:
    """Keep normalized values in entry.data and remove duplicate options."""
    updated_data = dict(entry.data)
    needs_entry_update = False

    for key in _ENTRY_KEYS:
        value = config_data[key]
        if updated_data.get(key) != value:
            updated_data[key] = value
            needs_entry_update = True

    if not needs_entry_update and not any(key in entry.options for key in _ENTRY_KEYS):
        return

    updated_options = dict(entry.options)
    for key in _ENTRY_KEYS:
        updated_options.pop(key, None)

    hass.config_entries.async_update_entry(
        entry, data=updated_data, options=updated_options
    )


def _is_bootstrap_entry(entry: ConfigEntry) -> bool:
    """Return whether the entry was configured through the HA bootstrap flow."""
    return CONF_SUBSCRIPTION_STATUS in entry.data


async def _async_refresh_bootstrap_if_due(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Refresh bootstrap data when the backend requested refresh time has passed."""
    if not _is_refresh_due(entry):
        return

    await _async_refresh_bootstrap_now(hass, entry)


async def _async_refresh_bootstrap_now(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Refresh bootstrap data immediately and return whether credentials changed."""

    runtime = runtime_from_entry_data(entry.data)
    installation_id = str(entry.data.get(CONF_INSTALLATION_ID, "")).strip()
    if runtime is None or not installation_id:
        _async_create_issue(hass, ISSUE_FORECAST_CREDENTIAL_REFRESH)
        raise ConfigEntryAuthFailed("Home Assistant bootstrap credentials are incomplete.")

    implementation = HorizonIQOAuth2Implementation(
        hass,
        auth_domain=DOMAIN,
        runtime=runtime,
    )
    oauth_session = config_entry_oauth2_flow.OAuth2Session(
        hass,
        entry,
        implementation,
    )
    client = HorizonIQBootstrapClient(
        oauth_session=oauth_session,
        backend_api_base_url=runtime.backend_api_base_url,
    )

    try:
        bootstrap = await client.async_bootstrap(
            installation_id=installation_id,
            device_token=str(entry.data.get(CONF_FORECAST_DEVICE_TOKEN, "")).strip()
            or None,
        )
    except HorizonIQApiAuthError as err:
        raise ConfigEntryAuthFailed("Home Assistant sign-in is required.") from err
    except HorizonIQApiTransientError:
        _async_create_issue(hass, ISSUE_FORECAST_CREDENTIAL_REFRESH)
        _LOGGER.warning(
            "Home Assistant bootstrap refresh failed temporarily for entry %s; keeping previous forecast credentials.",
            entry.entry_id,
        )
        return False
    except BootstrapValidationError as err:
        raise ConfigEntryAuthFailed("Home Assistant bootstrap response is invalid.") from err
    except HorizonIQApiError as err:
        raise ConfigEntryAuthFailed("Home Assistant bootstrap failed.") from err

    if not bootstrap.entitled:
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, **no_subscription_entry_data(bootstrap)},
        )
        _async_create_issue(
            hass,
            ISSUE_ENTITLEMENT_LOST,
            PORTAL_BILLING_URL,
        )
        raise ConfigEntryAuthFailed(
            "HorizonIQ trial or subscription is not valid. Subscribe, then reload or reconnect the integration."
        )

    updated = entry_data_from_bootstrap(
        bootstrap=bootstrap,
        oauth_data=entry.data,
        runtime=runtime,
        battery_capacity_sensor=str(entry.data.get(CONF_BATTERY_CAPACITY_SENSOR, "")),
        environment=str(entry.data.get(CONF_ENVIRONMENT, "")),
        device_token=str(entry.data.get(CONF_FORECAST_DEVICE_TOKEN, "")).strip()
        or None,
    )
    hass.config_entries.async_update_entry(entry, data={**entry.data, **updated})
    return True


def _is_refresh_due(entry: ConfigEntry) -> bool:
    value = entry.data.get(CONF_BOOTSTRAP_REFRESH_AFTER_UTC)
    if not isinstance(value, str) or not value.strip():
        return False

    try:
        refresh_after = datetime.fromisoformat(
            value.strip().replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    except ValueError:
        return True

    return refresh_after <= datetime.now(timezone.utc)


def _async_create_issue(
    hass: HomeAssistant,
    issue_id: str,
    subscribe_url: object = PORTAL_BILLING_URL,
) -> None:
    """Create a repair issue without exposing credentials."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key=issue_id,
        translation_placeholders={
            "subscribe_url": str(subscribe_url or PORTAL_BILLING_URL)
        },
    )


@callback
def _migrate_legacy_default_environment_unique_ids(
    *,
    hass: HomeAssistant,
    entry: ConfigEntry,
    environment: str,
) -> None:
    """Normalize live/default entities onto one canonical registry entry."""
    if environment != DEFAULT_ENVIRONMENT:
        return

    entity_registry = er.async_get(hass)

    for entity_domain, suffix in _LEGACY_DEFAULT_ENVIRONMENT_ENTITY_SUFFIXES:
        desired_unique_id = build_unique_id(DEFAULT_ENVIRONMENT, entry.entry_id, suffix)
        canonical_entity_id = _default_environment_entity_id(entity_domain, suffix)
        candidates = _default_environment_entity_candidates(
            entity_registry=entity_registry,
            entity_domain=entity_domain,
            suffix=suffix,
            canonical_entity_id=canonical_entity_id,
        )
        if not candidates:
            continue

        target_entry = _select_default_environment_entity_candidate(
            candidates=candidates,
            entry_id=entry.entry_id,
            desired_unique_id=desired_unique_id,
            canonical_entity_id=canonical_entity_id,
            suffix=suffix,
        )

        for candidate in candidates:
            if candidate.entity_id == target_entry.entity_id:
                continue
            entity_registry.async_remove(candidate.entity_id)
            entity_registry.deleted_entities.pop(
                (
                    candidate.domain,
                    candidate.platform,
                    candidate.unique_id,
                ),
                None,
            )
            _LOGGER.info(
                "Removed duplicate HorizonIQ entity %s while normalizing entry %s",
                candidate.entity_id,
                entry.entry_id,
            )

        update_kwargs: dict[str, object] = {}
        if target_entry.unique_id != desired_unique_id:
            update_kwargs["new_unique_id"] = desired_unique_id
        if target_entry.config_entry_id != entry.entry_id:
            update_kwargs["config_entry_id"] = entry.entry_id
        if target_entry.entity_id != canonical_entity_id:
            update_kwargs["new_entity_id"] = canonical_entity_id

        if not update_kwargs:
            continue

        entity_registry.async_update_entity(target_entry.entity_id, **update_kwargs)
        _LOGGER.info(
            "Normalized HorizonIQ entity %s for entry %s",
            target_entry.entity_id,
            entry.entry_id,
        )


def _legacy_default_environment_unique_id(suffix: str) -> str:
    """Return the pre-entry-ID unique ID used by legacy live entities."""
    return f"{DOMAIN}_{suffix}"


def _default_environment_entity_id(entity_domain: str, suffix: str) -> str:
    """Return the canonical entity_id for live/default-environment entities."""
    return f"{entity_domain}.{DOMAIN}_{suffix}"


def _is_default_environment_entity_id_variant(
    entity_id: str,
    canonical_entity_id: str,
) -> bool:
    """Return whether the entity_id is the canonical one or an auto-suffixed duplicate."""
    if entity_id == canonical_entity_id:
        return True

    prefix = f"{canonical_entity_id}_"
    if not entity_id.startswith(prefix):
        return False

    duplicate_suffix = entity_id.removeprefix(prefix)
    return duplicate_suffix.isdigit()


def _default_environment_entity_candidates(
    *,
    entity_registry: er.EntityRegistry,
    entity_domain: str,
    suffix: str,
    canonical_entity_id: str,
) -> list[er.RegistryEntry]:
    """Return all live/default candidate entries for a single logical entity."""
    legacy_unique_id = _legacy_default_environment_unique_id(suffix)
    candidates: list[er.RegistryEntry] = []

    for registry_entry in entity_registry.entities.values():
        if registry_entry.domain != entity_domain or registry_entry.platform != DOMAIN:
            continue
        if _is_default_environment_entity_id_variant(
            registry_entry.entity_id,
            canonical_entity_id,
        ):
            candidates.append(registry_entry)
            continue
        if registry_entry.unique_id == legacy_unique_id:
            candidates.append(registry_entry)

    return candidates


def _select_default_environment_entity_candidate(
    *,
    candidates: list[er.RegistryEntry],
    entry_id: str,
    desired_unique_id: str,
    canonical_entity_id: str,
    suffix: str,
) -> er.RegistryEntry:
    """Choose the registry entry to preserve when collapsing duplicate live entities."""
    legacy_unique_id = _legacy_default_environment_unique_id(suffix)

    for candidate in candidates:
        if candidate.entity_id == canonical_entity_id:
            return candidate
    for candidate in candidates:
        if candidate.unique_id == legacy_unique_id:
            return candidate
    for candidate in candidates:
        if (
            candidate.unique_id == desired_unique_id
            and candidate.config_entry_id == entry_id
        ):
            return candidate
    for candidate in candidates:
        if candidate.unique_id == desired_unique_id:
            return candidate
    for candidate in candidates:
        if candidate.config_entry_id == entry_id:
            return candidate
    return candidates[0]

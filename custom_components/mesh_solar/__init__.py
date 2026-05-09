from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

from .config_data import merged_config_data, validate_config_data
from .const import (
    CONF_API_KEY,
    CONF_BATTERY_CAPACITY_SENSOR,
    CONF_ENVIRONMENT,
    CONF_HASH,
    CONF_REGISTRATION_DATA,
    CONF_URL,
    DEFAULT_ENVIRONMENT,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import MeshSolarCoordinator
from .entity_helpers import build_unique_id
from .models import MeshSolarConfigData

_LOGGER = logging.getLogger(__name__)
_LOCAL_DOCS_READY_KEY = f"{DOMAIN}_local_docs_ready"
_LOCAL_DOCS_SOURCE = "local_docs/index.html"
_LOCAL_DOCS_TARGET = ("www", "mesh_solar", "index.html")
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
)


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
    """Set up Mesh Solar from a config entry."""
    if not hass.data.get(_LOCAL_DOCS_READY_KEY):
        await _ensure_local_docs(hass)
        hass.data[_LOCAL_DOCS_READY_KEY] = True

    config_data = merged_config_data(entry)
    _sync_entry_data(hass=hass, entry=entry, config_data=config_data)

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

    coordinator = MeshSolarCoordinator(
        hass=hass,
        entry=entry,
        url=config_data[CONF_URL],
        api_key=config_data[CONF_API_KEY],
        battery_capacity_sensor=config_data[CONF_BATTERY_CAPACITY_SENSOR],
        environment=config_data[CONF_ENVIRONMENT],
        initial_hash=config_data[CONF_HASH],
        initial_registration=config_data[CONF_REGISTRATION_DATA],
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
    """Unload a Mesh Solar config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    _LOGGER.debug("Mesh Solar unloaded for entry %s", entry.entry_id)
    return unload_ok


def _sync_entry_data(
    *,
    hass: HomeAssistant,
    entry: ConfigEntry,
    config_data: MeshSolarConfigData,
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
                "Removed duplicate Mesh Solar entity %s while normalizing entry %s",
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
            "Normalized Mesh Solar entity %s for entry %s",
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

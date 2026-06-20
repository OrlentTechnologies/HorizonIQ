from __future__ import annotations

from homeassistant.util import slugify

from .const import (
    DEFAULT_ENVIRONMENT,
    DOMAIN,
    display_environment,
    normalize_environment,
)


def normalized_environment(environment: str) -> str:
    """Return the canonical stored environment value."""
    return normalize_environment(environment)


def environment_label(environment: str) -> str:
    """Return the user-facing environment label."""
    return display_environment(normalized_environment(environment))


def display_suffix(environment: str) -> str:
    """Return a display suffix for non-default environments."""
    normalized = normalized_environment(environment)
    if normalized == DEFAULT_ENVIRONMENT:
        return ""
    return f" ({display_environment(normalized)})"


def entity_name(environment: str, suffix: str) -> str:
    """Return an entity name without changing default-environment names."""
    normalized = normalized_environment(environment)
    if normalized == DEFAULT_ENVIRONMENT:
        return f"Mesh Solar {suffix}"
    return f"Mesh Solar {display_environment(normalized)} {suffix}"


def build_unique_id(environment: str, entry_id: str, suffix: str) -> str:
    """Build a per-entry unique ID."""
    normalized = normalized_environment(environment)
    unique_id_parts = [DOMAIN, entry_id]
    if normalized != DEFAULT_ENVIRONMENT:
        environment_slug = slugify(normalized)
        if environment_slug:
            unique_id_parts.append(environment_slug)
    unique_id_parts.append(suffix)
    return "_".join(unique_id_parts)

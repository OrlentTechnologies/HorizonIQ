from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..const import DEFAULT_ENVIRONMENT, DOMAIN
from ..entity import MeshSolarEntity
from ..entity_helpers import (
    build_unique_id,
    entity_name,
    environment_label,
    normalized_environment,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Mesh Solar binary sensors."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    environment = normalized_environment(
        getattr(coordinator, "environment", DEFAULT_ENVIRONMENT)
    )

    async_add_entities(
        [
            ImportSensor(coordinator, config_entry.entry_id, environment),
            ExportSensor(coordinator, config_entry.entry_id, environment),
        ]
    )


class ImportSensor(MeshSolarEntity, BinarySensorEntity):
    """Expose the normalized import recommendation."""

    def __init__(self, coordinator, entry_id: str, environment: str) -> None:
        super().__init__(coordinator)
        self._environment = normalized_environment(environment)
        self._attr_name = entity_name(self._environment, "Import")
        self._attr_unique_id = build_unique_id(self._environment, entry_id, "import")

    @property
    def is_on(self) -> bool | None:
        """Return whether import is currently recommended."""
        snapshot = self.snapshot
        if snapshot is None:
            return None
        return snapshot.should_import

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return diagnostic attributes."""
        return {"environment": environment_label(self._environment)}


class ExportSensor(MeshSolarEntity, BinarySensorEntity):
    """Expose the normalized export recommendation."""

    def __init__(self, coordinator, entry_id: str, environment: str) -> None:
        super().__init__(coordinator)
        self._environment = normalized_environment(environment)
        self._attr_name = entity_name(self._environment, "Export")
        self._attr_unique_id = build_unique_id(self._environment, entry_id, "export")

    @property
    def is_on(self) -> bool | None:
        """Return whether export is currently recommended."""
        snapshot = self.snapshot
        if snapshot is None or snapshot.should_import is None:
            return None
        return not snapshot.should_import

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return diagnostic attributes."""
        return {"environment": environment_label(self._environment)}

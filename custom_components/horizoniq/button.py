from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_ENVIRONMENT, DOMAIN
from .entity import HorizonIQEntity
from .entity_helpers import (
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
    """Set up the clear-registration button."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    environment = normalized_environment(
        getattr(coordinator, "environment", DEFAULT_ENVIRONMENT)
    )

    async_add_entities(
        [ClearRegistrationButton(coordinator, config_entry.entry_id, environment)]
    )


class ClearRegistrationButton(HorizonIQEntity, ButtonEntity):
    """Button entity to clear cached registration data."""

    def __init__(self, coordinator, entry_id: str, environment: str) -> None:
        super().__init__(coordinator)
        self._environment = normalized_environment(environment)
        self._attr_name = entity_name(self._environment, "Clear Registration")
        self._attr_unique_id = build_unique_id(
            self._environment, entry_id, "clear_registration"
        )

    async def async_press(self) -> None:
        """Handle button presses."""
        await self.coordinator.async_clear_registration_data()

    @property
    def available(self) -> bool:
        """Keep this button callable even when coordinator updates are failing."""
        return True

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return diagnostic attributes for the button."""
        return {"environment": environment_label(self._environment)}

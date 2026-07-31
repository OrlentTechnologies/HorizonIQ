from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SANDBOX_ENVIRONMENT
from .models import HorizonIQSnapshot

if TYPE_CHECKING:
    from .coordinator import HorizonIQCoordinator


class HorizonIQEntity(CoordinatorEntity["HorizonIQCoordinator"]):
    """Base class for all HorizonIQ entities."""

    @property
    def available(self) -> bool:
        """Keep Sandbox entry entities available from their local runtime state."""
        if getattr(self.coordinator, "environment", None) == SANDBOX_ENVIRONMENT:
            hass = getattr(self, "hass", None)
            entry = getattr(self.coordinator, "config_entry", None)
            if hass is not None and entry is not None:
                runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
                return bool(getattr(runtime, "virtual_entity_available", False))
            return True
        return self.coordinator.last_update_success

    @property
    def snapshot(self) -> HorizonIQSnapshot | None:
        """Return the current normalized coordinator snapshot."""
        return self.coordinator.data

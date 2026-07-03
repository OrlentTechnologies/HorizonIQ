from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .models import HorizonIQSnapshot

if TYPE_CHECKING:
    from .coordinator import HorizonIQCoordinator


class HorizonIQEntity(CoordinatorEntity["HorizonIQCoordinator"]):
    """Base class for all HorizonIQ entities."""

    @property
    def available(self) -> bool:
        """Return if the coordinator is available."""
        return self.coordinator.last_update_success

    @property
    def snapshot(self) -> HorizonIQSnapshot | None:
        """Return the current normalized coordinator snapshot."""
        return self.coordinator.data

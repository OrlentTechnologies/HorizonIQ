from __future__ import annotations

from typing import Literal

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)

from ..entity import HorizonIQEntity
from ..entity_helpers import (
    build_unique_id,
    entity_name,
    environment_label,
    normalized_environment,
)

MonetaryValueField = Literal["total_cost", "charging_cost", "saving"]


class MonetarySensor(HorizonIQEntity, SensorEntity):
    """Expose normalized monetary values from the coordinator snapshot."""

    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(
        self,
        coordinator,
        entry_id: str,
        environment: str,
        name_suffix: str,
        unique_suffix: str,
        value_field: MonetaryValueField,
    ) -> None:
        super().__init__(coordinator)
        self._environment = normalized_environment(environment)
        self._value_field = value_field
        self._attr_name = entity_name(self._environment, name_suffix)
        self._attr_unique_id = build_unique_id(
            self._environment, entry_id, unique_suffix
        )

    @property
    def native_value(self) -> float | None:
        """Return the normalized monetary value."""
        snapshot = self.snapshot
        if snapshot is None:
            return None
        return getattr(snapshot, self._value_field)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the current currency."""
        snapshot = self.snapshot
        if snapshot is None:
            return None
        return snapshot.currency

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return diagnostic attributes."""
        attrs = {"environment": environment_label(self._environment)}
        snapshot = self.snapshot
        if snapshot is not None and snapshot.currency:
            attrs["currency"] = snapshot.currency
        return attrs

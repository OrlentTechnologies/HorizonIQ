from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..const import DEFAULT_ENVIRONMENT, DOMAIN
from ..entity_helpers import normalized_environment
from .cadence import ForecastCadenceSensor
from .monetary import MonetarySensor
from .diagnostic import ForecastDetailSensor
from .bms_state import BatteryManagementSystemStateSensor
from .trial import TrialStatusSensor


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Mesh Solar sensor entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    environment = normalized_environment(
        getattr(coordinator, "environment", DEFAULT_ENVIRONMENT)
    )

    async_add_entities(
        [
            MonetarySensor(
                coordinator,
                config_entry.entry_id,
                environment,
                name_suffix="Total Cost",
                unique_suffix="total_cost",
                value_field="total_cost",
            ),
            MonetarySensor(
                coordinator,
                config_entry.entry_id,
                environment,
                name_suffix="Charging Cost",
                unique_suffix="charging_cost",
                value_field="charging_cost",
            ),
            MonetarySensor(
                coordinator,
                config_entry.entry_id,
                environment,
                name_suffix="Saving",
                unique_suffix="saving",
                value_field="saving",
            ),
            ForecastDetailSensor(
                coordinator,
                config_entry.entry_id,
                environment,
            ),
            ForecastCadenceSensor(
                coordinator,
                config_entry.entry_id,
                environment,
            ),
            BatteryManagementSystemStateSensor(
                coordinator,
                config_entry.entry_id,
                environment,
            ),
            TrialStatusSensor(
                coordinator,
                config_entry.entry_id,
                environment,
            ),
        ]
    )

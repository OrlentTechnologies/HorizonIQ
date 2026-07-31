"""Recorder-safe import-for-export decision diagnostics."""

from __future__ import annotations

from copy import deepcopy

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory

from ..entity_helpers import build_unique_id, virtual_battery_device_info
from ..forecast_schema5 import Schema5Forecast, Schema5Period
from ..sandbox_runtime import HorizonIQEntryRuntime


class ImportForExportDecisionSensor(SensorEntity):
    """Expose backend import-for-export decisions without local inference."""

    _attr_has_entity_name = True
    _attr_name = "Import for export decision"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _unrecorded_attributes = frozenset(
        {
            "plan_kind",
            "import_for_export_enabled",
            "import_for_export_advisory_enabled",
            "price_limit",
            "selected_periods",
            "rejected_periods",
            "period_prices",
            "period_values",
            "constraints",
            "economic_calculations",
        }
    )

    def __init__(self, runtime: HorizonIQEntryRuntime, entry_id: str) -> None:
        """Bind the entity to exactly one virtual sandbox runtime."""
        self._runtime = runtime
        self._key = "import_for_export_decision"
        self._attr_unique_id = build_unique_id(
            "Sandbox", entry_id, "import_for_export_decision"
        )
        self._remove_listener = runtime.add_listener(self.async_write_ha_state)

    @property
    def device_info(self) -> DeviceInfo:
        """Associate the decision with its one virtual battery."""
        assert self._runtime.pretend_gx_id is not None
        return virtual_battery_device_info(self._runtime.pretend_gx_id)

    @property
    def available(self) -> bool:
        """Keep stored virtual state visible while transport is unavailable."""
        return self._runtime.virtual_entity_available

    @property
    def native_value(self) -> str:
        """Return the backend-derived import-for-export decision state."""
        forecast = self._runtime.forecast_diagnostics
        if forecast is None:
            return "not_planned"
        enabled = (
            forecast.import_for_export_advisory_enabled
            if forecast.plan_kind == "advisory"
            else forecast.import_for_export_enabled
        )
        if not enabled:
            return "disabled"
        return "planned" if _selected_periods(forecast) else "not_planned"

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose only exact backend economics and rejection evidence."""
        forecast = self._runtime.forecast_diagnostics
        if forecast is None:
            return {}
        selected = _selected_periods(forecast)
        rejected: dict[str, list[dict[str, object]]] = {}
        constraints: list[dict[str, object]] = []
        economic_calculations: list[dict[str, object]] = []
        period_values: list[dict[str, object]] = []
        period_prices: dict[str, float] = {}
        for period in forecast.periods:
            value = period.to_dict()
            period_key = str(period.period)
            period_prices[period_key] = period.price
            period_values.append(
                {
                    "period": period.period,
                    "expectedImport": period.expected_import,
                    "expectedExport": period.expected_export,
                    "expectedStartSoc": period.expected_start_soc,
                    "expectedEndSoc": period.expected_end_soc,
                    "expectedCost": period.expected_cost,
                    "expectedRevenue": period.expected_revenue,
                    "expectedNetValue": period.expected_net_value,
                }
            )
            constraints.append(
                {
                    "period": period.period,
                    "constraints": deepcopy(period.decision_trace.constraints),
                }
            )
            economic_calculations.append(
                {
                    "period": period.period,
                    "economicCalculation": deepcopy(
                        period.decision_trace.economic_calculation
                    ),
                }
            )
            if not _selects_import_for_export(period, forecast.plan_kind):
                rejected.setdefault(period.decision_trace.reason_code, []).append(value)
        return {
            "plan_kind": forecast.plan_kind,
            "import_for_export_enabled": forecast.import_for_export_enabled,
            "import_for_export_advisory_enabled": (
                forecast.import_for_export_advisory_enabled
            ),
            "price_limit": forecast.economics_assumptions.get("priceLimit"),
            "selected_periods": [period.to_dict() for period in selected],
            "rejected_periods": rejected,
            "period_prices": period_prices,
            "period_values": period_values,
            "constraints": constraints,
            "economic_calculations": economic_calculations,
        }

    async def async_will_remove_from_hass(self) -> None:
        """Release the entry-local runtime listener."""
        self._remove_listener()
        await super().async_will_remove_from_hass()


def _selected_periods(forecast: Schema5Forecast) -> tuple[Schema5Period, ...]:
    """Return periods whose backend plan selected import-for-export."""
    return tuple(
        period
        for period in forecast.periods
        if _selects_import_for_export(period, forecast.plan_kind)
    )


def _selects_import_for_export(period: Schema5Period, plan_kind: str) -> bool:
    """Apply the schema's plan-kind action authority without inventing a command."""
    action = {
        "live": period.executable_action,
        "advisory": period.recommended_action,
        "replay": period.simulation_action,
        "sandbox_replay": period.simulation_action,
    }[plan_kind]
    return action == "import_for_export"

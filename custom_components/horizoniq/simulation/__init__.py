"""Framework-free HorizonIQ virtual-battery simulation domain."""

from .clock import ClockRate, VirtualClock
from .models import BatteryConfig, BatteryState, Command, OperatingMode
from .physics import DEFAULT_BALANCE_TOLERANCE_WH, simulate_step

__all__ = ["BatteryConfig", "BatteryState", "ClockRate", "Command", "DEFAULT_BALANCE_TOLERANCE_WH", "OperatingMode", "VirtualClock", "simulate_step"]

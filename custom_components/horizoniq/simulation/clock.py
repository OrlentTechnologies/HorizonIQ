"""Pure virtual clock. It never reads or mutates the system clock."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from enum import Enum
from .models import ClockState
class ClockRate(str, Enum):
    PAUSED="paused"; X1="1x"; X10="10x"; X60="60x"; X240="240x"
    @property
    def multiplier(self) -> int: return {ClockRate.PAUSED:0,ClockRate.X1:1,ClockRate.X10:10,ClockRate.X60:60,ClockRate.X240:240}[self]
def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None: raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)
class VirtualClock:
    def __init__(self, start_utc: datetime, rate: ClockRate=ClockRate.PAUSED) -> None: self._state=ClockState(_utc(start_utc),rate.value)
    @property
    def state(self) -> ClockState: return self._state
    @classmethod
    def from_state(cls, state: ClockState) -> "VirtualClock":
        """Restore an already validated clock state without advancing time."""
        clock = cls(state.virtual_time_utc, ClockRate(state.rate))
        clock._state = ClockState(
            _utc(state.virtual_time_utc),
            state.rate,
            state.sequence,
            state.reset_generation,
        )
        return clock
    def set_rate(self, rate: ClockRate) -> ClockState: self._state=ClockState(self._state.virtual_time_utc,rate.value,self._state.sequence+1,self._state.reset_generation); return self._state
    def advance(self, real_elapsed_seconds: float) -> ClockState:
        if real_elapsed_seconds < 0: raise ValueError("real_elapsed_seconds must be non-negative")
        rate=ClockRate(self._state.rate); self._state=ClockState(self._state.virtual_time_utc+timedelta(seconds=real_elapsed_seconds*rate.multiplier),rate.value,self._state.sequence+1,self._state.reset_generation); return self._state
    def step(self, seconds: float=1800) -> ClockState:
        if seconds<=0: raise ValueError("step seconds must be positive")
        self._state=ClockState(self._state.virtual_time_utc+timedelta(seconds=seconds),self._state.rate,self._state.sequence+1,self._state.reset_generation); return self._state
    def reset(self, timestamp_utc: datetime) -> ClockState: self._state=ClockState(_utc(timestamp_utc),self._state.rate,self._state.sequence+1,self._state.reset_generation+1); return self._state

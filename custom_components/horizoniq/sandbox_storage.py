"""Private, entry-scoped persistence for virtual-battery state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store


STORAGE_SCHEMA_VERSION: Final = 11
STORE_VERSION: Final = 1
SNAPSHOT_SCHEMA_VERSION: Final = 4
CHECKPOINT_DELAY_SECONDS: Final = 30
MAX_NAMED_SNAPSHOTS: Final = 20


class SandboxStorage:
    """Store one entry's non-sensitive simulator state and named snapshots."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Create a private Store with an entry-specific key."""
        self._store: Store[dict[str, object]] = Store(
            hass,
            STORE_VERSION,
            f"horizoniq.sandbox.{entry_id}",
            private=True,
            atomic_writes=True,
        )

    async def async_load(self) -> dict[str, object] | None:
        """Load this entry's record without attempting migration or repair."""
        return await self._store.async_load()

    async def async_save(self, record: dict[str, object]) -> None:
        """Write a complete record immediately."""
        await self._store.async_save(record)

    def async_delay_save(self, record_factory) -> None:
        """Debounce a checkpoint, retaining the final state on HA shutdown."""
        self._store.async_delay_save(record_factory, CHECKPOINT_DELAY_SECONDS)

    async def async_remove(self) -> None:
        """Delete only this entry's private simulator record."""
        await self._store.async_remove()


async def async_remove_entry_storage(hass: HomeAssistant, entry_id: str) -> None:
    """Delete the simulator state belonging only to a removed config entry."""
    await SandboxStorage(hass, entry_id).async_remove()


def record_mapping(value: object) -> Mapping[str, object] | None:
    """Return a mapping only for JSON-object storage records."""
    return value if isinstance(value, Mapping) else None

"""Entry-scoped local synthetic-profile file access."""

from __future__ import annotations

import hashlib
from pathlib import Path

from homeassistant.core import HomeAssistant

from .simulation.local_profiles import (
    LocalSyntheticProfile,
    parse_csv_profile,
    parse_json_profile,
)
from .simulation.models import BatteryConfig

MAX_PROFILE_FILE_BYTES = 4 * 1024 * 1024
_EXTENSIONS = {".json", ".csv"}


class SandboxProfileRepository:
    """Read profiles directly beneath one config entry's owned directory."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._directory = Path(hass.config.path("horizoniq", "profiles", entry_id))

    async def async_list_filenames(self) -> tuple[str, ...]:
        """List valid direct-child profile filenames for this entry only."""
        return await self._hass.async_add_executor_job(self._list_filenames)

    async def async_load(
        self,
        filename: str,
        config: BatteryConfig,
    ) -> tuple[LocalSyntheticProfile, str]:
        """Read, hash, parse, and validate one owned UTF-8 profile file."""
        return await self._hass.async_add_executor_job(
            self._load,
            filename,
            config,
        )

    def _list_filenames(self) -> tuple[str, ...]:
        if not self._directory.is_dir():
            return ()
        return tuple(
            sorted(
                item.name
                for item in self._directory.iterdir()
                if item.is_file() and item.suffix.lower() in _EXTENSIONS
            )
        )

    def _load(
        self,
        filename: str,
        config: BatteryConfig,
    ) -> tuple[LocalSyntheticProfile, str]:
        path = self._owned_path(filename)
        try:
            size = path.stat().st_size
        except OSError as err:
            raise ValueError("Profile file does not exist") from err
        if size > MAX_PROFILE_FILE_BYTES:
            raise ValueError("Profile file exceeds 4 MiB")
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as err:
            raise ValueError("Profile file must be UTF-8") from err
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if path.suffix.lower() == ".json":
            profile = parse_json_profile(content, identifier=filename, config=config)
        else:
            profile = parse_csv_profile(content, identifier=filename, config=config)
        return profile, content_hash

    def _owned_path(self, filename: str) -> Path:
        candidate = Path(filename)
        if (
            not filename
            or candidate.is_absolute()
            or candidate.name != filename
            or candidate.suffix.lower() not in _EXTENSIONS
        ):
            raise ValueError("Profile filename is invalid")
        directory = self._directory.resolve()
        path = (directory / candidate.name).resolve()
        if path.parent != directory:
            raise ValueError("Profile path is outside this config entry")
        return path

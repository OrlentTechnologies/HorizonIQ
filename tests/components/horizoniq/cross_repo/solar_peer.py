"""Bounded JSON-lines runner for Solar's test-only sandbox MQTT peer."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
from typing import Final

from .mqtt_adapter import BrokerSettings


PEER_TIMEOUT_SECONDS: Final = 16.0
PROCESS_MARGIN_SECONDS: Final = 2.0
MAX_DIAGNOSTIC_LINES: Final = 12
MAX_DIAGNOSTIC_LENGTH: Final = 512
_WINDOWS_PATH = re.compile(r"^([a-zA-Z]):[\\/](.*)$")


@dataclass(frozen=True, slots=True)
class SolarPeerConfig:
    """Validated read-only locations required by the opt-in cross-repo test."""

    repository: Path
    peer_script: Path
    contract_script: Path
    node: str

    @classmethod
    def from_environment(cls) -> "SolarPeerConfig":
        """Require the Solar checkout and Node when this opt-in suite runs."""
        raw_repository = os.environ.get("HORIZONIQ_SOLAR_REPO", "").strip()
        if not raw_repository:
            raise RuntimeError("HORIZONIQ_SOLAR_REPO is required for the cross-repository test.")
        repository = _host_path(raw_repository)
        peer_script = repository / "node-red" / "tests" / "cross-repo" / "sandbox-peer.js"
        contract_script = repository / "node-red" / "data" / "lib" / "sandbox-mqtt-contract.js"
        if not peer_script.is_file() or not contract_script.is_file():
            raise RuntimeError("Solar sandbox peer or MQTT contract file is unavailable.")
        node = _node_executable()
        if node is None:
            raise RuntimeError("Node is required for the cross-repository test.")
        return cls(repository, peer_script, contract_script, node)


class SolarSandboxPeer:
    """Launch Solar's peer and accept only its documented JSON-lines protocol."""

    def __init__(self, config: SolarPeerConfig, broker: BrokerSettings) -> None:
        self._config = config
        self._broker = broker
        self._process: asyncio.subprocess.Process | None = None
        self._events: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self._reader: asyncio.Task[None] | None = None
        self._stderr_reader: asyncio.Task[None] | None = None
        self._diagnostics: list[str] = []

    async def async_start(self, **scenario: str | int) -> None:
        """Start a peer process with credentials passed through its environment only."""
        if self._process is not None:
            raise RuntimeError("Solar sandbox peer is already running.")
        arguments = [self._config.node, str(self._config.peer_script)]
        for key, value in scenario.items():
            arguments.extend((_option_name(key), str(value)))
        environment = dict(os.environ)
        environment["TEST_MQTT_BROKER"] = self._broker.broker
        if self._broker.username is not None:
            environment["TEST_MQTT_USERNAME"] = self._broker.username
        if self._broker.password is not None:
            environment["TEST_MQTT_PASSWORD"] = self._broker.password
        self._process = await asyncio.create_subprocess_exec(
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            env=environment,
        )
        self._reader = asyncio.create_task(self._async_read_protocol())
        self._stderr_reader = asyncio.create_task(self._async_read_stderr())

    async def async_wait_ready(self) -> dict[str, object]:
        """Wait for the peer's ready event before causing the HA-side trigger."""
        event = await self._async_next_event()
        if event.get("event") == "ready":
            return event
        self._raise_protocol_failure(event)
        raise AssertionError("unreachable")

    async def async_wait_result(self) -> dict[str, object]:
        """Wait for the peer's one terminal result and then reap its process."""
        event = await self._async_next_event()
        if event.get("event") != "result":
            self._raise_protocol_failure(event)
        process = self._require_process()
        try:
            await asyncio.wait_for(process.wait(), PROCESS_MARGIN_SECONDS)
        except TimeoutError as err:
            raise AssertionError(self._diagnostic_message("Solar sandbox peer did not exit.")) from err
        if process.returncode != 0:
            raise AssertionError(self._diagnostic_message("Solar sandbox peer failed."))
        return event

    async def async_close(self) -> None:
        """Terminate an unfinished peer and drain all bounded reader tasks."""
        process, self._process = self._process, None
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), PROCESS_MARGIN_SECONDS)
            except TimeoutError:
                process.kill()
                await process.wait()
        for task in (self._reader, self._stderr_reader):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(task for task in (self._reader, self._stderr_reader) if task is not None),
            return_exceptions=True,
        )
        self._reader = None
        self._stderr_reader = None

    async def _async_next_event(self) -> dict[str, object]:
        try:
            return await asyncio.wait_for(self._events.get(), PEER_TIMEOUT_SECONDS)
        except TimeoutError as err:
            raise AssertionError(self._diagnostic_message("Timed out waiting for Solar sandbox peer.")) from err

    async def _async_read_protocol(self) -> None:
        process = self._require_process()
        assert process.stdout is not None
        try:
            async for raw_line in process.stdout:
                if len(raw_line) > MAX_DIAGNOSTIC_LENGTH:
                    await self._events.put({"event": "error", "message": "Peer protocol line is too long."})
                    return
                try:
                    decoded = json.loads(raw_line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    await self._events.put({"event": "error", "message": "Peer protocol is malformed."})
                    return
                if not isinstance(decoded, dict) or decoded.get("event") not in {"ready", "result", "error"}:
                    await self._events.put({"event": "error", "message": "Peer protocol event is invalid."})
                    return
                await self._events.put(decoded)
        except asyncio.CancelledError:
            raise

    async def _async_read_stderr(self) -> None:
        process = self._require_process()
        assert process.stderr is not None
        try:
            async for raw_line in process.stderr:
                if len(self._diagnostics) >= MAX_DIAGNOSTIC_LINES:
                    return
                self._diagnostics.append(_sanitize(raw_line.decode("utf-8", "replace"), self._broker))
        except asyncio.CancelledError:
            raise

    def _raise_protocol_failure(self, event: dict[str, object]) -> None:
        raise AssertionError(self._diagnostic_message("Solar sandbox peer protocol failed."))

    def _diagnostic_message(self, message: str) -> str:
        if not self._diagnostics:
            return message
        return f"{message} diagnostics: {' | '.join(self._diagnostics)}"

    def _require_process(self) -> asyncio.subprocess.Process:
        if self._process is None:
            raise RuntimeError("Solar sandbox peer is not running.")
        return self._process


def _host_path(value: str) -> Path:
    match = _WINDOWS_PATH.fullmatch(value)
    if match is not None:
        return Path("/mnt") / match.group(1).lower() / match.group(2).replace("\\", "/")
    return Path(value)


def _node_executable() -> str | None:
    """Find an executable Node runtime in the same OS environment as pytest."""
    return shutil.which("node") or shutil.which("node.exe")


def _option_name(value: str) -> str:
    if value == "gxDeviceId":
        return "--gx-id"
    return "--" + re.sub(r"(?<!^)([A-Z])", r"-\1", value).lower()


def _sanitize(value: str, broker: BrokerSettings) -> str:
    result = value.strip()[:MAX_DIAGNOSTIC_LENGTH]
    for secret in (broker.username, broker.password):
        if secret:
            result = result.replace(secret, "<redacted>")
    return re.sub(r"mqtt://[^\s/@]+@", "mqtt://<redacted>@", result)

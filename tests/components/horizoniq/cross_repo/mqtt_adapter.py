"""Bounded paho adapter for exercising HA's sandbox MQTT seam in tests only."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import os
from typing import Final
from urllib.parse import urlparse
from uuid import uuid4

import paho.mqtt.client as paho


CONNECT_TIMEOUT_SECONDS: Final = 8.0
OPERATION_TIMEOUT_SECONDS: Final = 5.0


@dataclass(frozen=True, slots=True)
class BrokerSettings:
    """The test-only broker configuration supplied exclusively by environment."""

    broker: str
    username: str | None
    password: str | None

    @classmethod
    def from_environment(cls) -> "BrokerSettings":
        """Read required broker settings without ever formatting credentials."""
        broker = os.environ.get("TEST_MQTT_BROKER", "").strip()
        if not broker:
            raise RuntimeError("TEST_MQTT_BROKER is required for the cross-repository test.")
        return cls(
            broker=broker,
            username=os.environ.get("TEST_MQTT_USERNAME"),
            password=os.environ.get("TEST_MQTT_PASSWORD"),
        )


@dataclass(frozen=True, slots=True)
class BrokerMessage:
    """Minimal HA-compatible inbound message metadata from a real broker."""

    topic: str
    payload: str
    retain: bool
    qos: int


@dataclass(frozen=True, slots=True)
class PublishedMessage:
    """One test-observed outbound message without storing it outside the test process."""

    topic: str
    payload: str
    qos: int
    retain: bool


MessageCallback = Callable[[BrokerMessage], Awaitable[None]]


class RealMqttAdapter:
    """Bridge the integration's patched async MQTT calls to one real MQTT client."""

    def __init__(self, settings: BrokerSettings, *, name: str) -> None:
        self._settings = settings
        self._name = name
        self._client: paho.Client | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connected = asyncio.Event()
        self._connect_error: str | None = None
        self._callbacks: dict[str, list[MessageCallback]] = {}
        self.subscriptions: set[str] = set()
        self._tasks: set[asyncio.Task[object]] = set()
        self.published: list[PublishedMessage] = []
        self.received: list[BrokerMessage] = []
        self._closed = False
        self._subscribe_lock = asyncio.Lock()
        self._subscribe_ack: asyncio.Event | None = None

    async def async_connect(self) -> None:
        """Connect once and bound the broker handshake."""
        if self._client is not None:
            return
        self._loop = asyncio.get_running_loop()
        host, port = _broker_host_port(self._settings.broker)
        try:
            callback_version = paho.CallbackAPIVersion.VERSION2
        except AttributeError:  # pragma: no cover - retained for older paho releases.
            client = paho.Client(client_id=_client_id(self._name), protocol=paho.MQTTv311)
        else:
            client = paho.Client(
                callback_api_version=callback_version,
                client_id=_client_id(self._name),
                protocol=paho.MQTTv311,
            )
        if self._settings.username is not None:
            client.username_pw_set(self._settings.username, self._settings.password)
        client.on_connect = self._on_connect
        client.on_connect_fail = self._on_connect_fail
        client.on_message = self._on_message
        client.on_subscribe = self._on_subscribe
        self._client = client
        try:
            client.connect_async(host, port, keepalive=20)
            client.loop_start()
            await asyncio.wait_for(self._connected.wait(), CONNECT_TIMEOUT_SECONDS)
        except TimeoutError as err:
            await self.async_close()
            raise RuntimeError("MQTT broker connection timed out.") from err
        if self._connect_error is not None:
            await self.async_close()
            raise RuntimeError("MQTT broker connection failed.")

    async def async_publish(
        self,
        _hass: object,
        topic: str,
        payload: str,
        *,
        qos: int = 0,
        retain: bool = False,
        **_kwargs: object,
    ) -> None:
        """Match HA's async_publish seam while retaining exact message properties."""
        client = self._require_client()
        if self._closed:
            raise RuntimeError("MQTT adapter is closed.")
        await asyncio.wait_for(
            asyncio.to_thread(_publish_blocking, client, topic, payload, qos, retain),
            OPERATION_TIMEOUT_SECONDS,
        )
        self.published.append(PublishedMessage(topic, payload, qos, retain))

    async def async_subscribe(
        self,
        _hass: object,
        topic: str,
        callback: MessageCallback,
        *,
        qos: int = 0,
        **_kwargs: object,
    ) -> Callable[[], None]:
        """Subscribe exactly once per broker topic and return an HA-style unsubscriber."""
        if self._closed:
            raise RuntimeError("MQTT adapter is closed.")
        async with self._subscribe_lock:
            callbacks = self._callbacks.setdefault(topic, [])
            callbacks.append(callback)
            if len(callbacks) == 1:
                self._subscribe_ack = asyncio.Event()
                try:
                    client = self._require_client()
                    result, _mid = client.subscribe(topic, qos=qos)
                    if result != paho.MQTT_ERR_SUCCESS:
                        raise RuntimeError("MQTT subscribe failed.")
                    await asyncio.wait_for(self._subscribe_ack.wait(), OPERATION_TIMEOUT_SECONDS)
                    self.subscriptions.add(topic)
                except Exception:
                    self._callbacks.pop(topic, None)
                    raise
                finally:
                    self._subscribe_ack = None

        def unsubscribe() -> None:
            """Remove only this callback immediately and broker subscription when unused."""
            callbacks = self._callbacks.get(topic)
            if callbacks is None:
                return
            try:
                callbacks.remove(callback)
            except ValueError:
                return
            if callbacks:
                return
            self._callbacks.pop(topic, None)
            self.subscriptions.discard(topic)
            client = self._client
            if client is not None and not self._closed:
                client.unsubscribe(topic)

        return unsubscribe

    async def async_close(self) -> None:
        """Cancel callback work, unsubscribe locally, and always disconnect the client."""
        if self._closed:
            return
        self._closed = True
        self._callbacks.clear()
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        client, self._client = self._client, None
        if client is not None:
            await asyncio.to_thread(_disconnect_blocking, client)

    def _require_client(self) -> paho.Client:
        if self._client is None:
            raise RuntimeError("MQTT adapter is not connected.")
        return self._client

    def _on_connect(self, _client: paho.Client, _userdata: object, _flags: object, reason_code: object, *_extra: object) -> None:
        self._connect_error = None if _reason_code_is_success(reason_code) else "failed"
        self._set_event(self._connected)

    def _on_connect_fail(self, _client: paho.Client, _userdata: object) -> None:
        self._connect_error = "failed"
        self._set_event(self._connected)

    def _on_subscribe(self, _client: paho.Client, _userdata: object, _mid: int, *_extra: object) -> None:
        if self._subscribe_ack is not None:
            self._set_event(self._subscribe_ack)

    def _on_message(self, _client: paho.Client, _userdata: object, message: paho.MQTTMessage) -> None:
        if self._closed or self._loop is None:
            return
        try:
            payload = message.payload.decode("utf-8")
        except UnicodeDecodeError:
            return
        incoming = BrokerMessage(
            topic=message.topic,
            payload=payload,
            retain=message.retain is True,
            qos=message.qos,
        )
        self.received.append(incoming)
        for callback in tuple(self._callbacks.get(message.topic, ())):
            self._loop.call_soon_threadsafe(self._create_callback_task, callback, incoming)

    def _create_callback_task(self, callback: MessageCallback, message: BrokerMessage) -> None:
        if self._closed:
            return
        task = asyncio.create_task(callback(message))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _set_event(self, event: asyncio.Event) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(event.set)


def _broker_host_port(value: str) -> tuple[str, int]:
    candidate = value if "://" in value else f"mqtt://{value}"
    parsed = urlparse(candidate)
    if parsed.scheme not in {"mqtt", "tcp"} or not parsed.hostname:
        raise RuntimeError("TEST_MQTT_BROKER must be an mqtt:// host and optional port.")
    return parsed.hostname, parsed.port or 1883


def _client_id(name: str) -> str:
    return f"horizoniq-ha-test-{name}-{uuid4().hex[:12]}"


def _reason_code_is_success(value: object) -> bool:
    return value == 0 or getattr(value, "value", None) == 0


def _publish_blocking(
    client: paho.Client, topic: str, payload: str, qos: int, retain: bool
) -> None:
    info = client.publish(topic, payload, qos=qos, retain=retain)
    if info.rc != paho.MQTT_ERR_SUCCESS:
        raise RuntimeError("MQTT publish failed.")
    info.wait_for_publish(timeout=OPERATION_TIMEOUT_SECONDS)
    if not info.is_published():
        raise RuntimeError("MQTT publish timed out.")


def _disconnect_blocking(client: paho.Client) -> None:
    client.disconnect()
    client.loop_stop()

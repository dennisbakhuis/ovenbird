"""MQTT ingest: subscribe to HeishaMon and the configured plain topics, never publish.

Phase 1 is strictly read-only towards the heat pump. :class:`ReadOnlyMqttClient` is
the only object in the service that holds a broker connection; it exposes
connect, subscribe and an inbound message stream and nothing else, and it connects
without a last will (a will would make the broker publish on our behalf).
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import ssl
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Any, Final, Protocol, Self

import aiomqtt

from ovenbird.backoff import Backoff
from ovenbird.runtime import Runtime
from ovenbird_core import HeishaMonParser, InputRouter, MqttMessage, SourceKind

if TYPE_CHECKING:
    from ovenbird.config import Settings

LOGGER = logging.getLogger("ovenbird.mqtt")
KEEPALIVE_S: Final = 30
CONNECT_TIMEOUT_S: Final = 10.0
MAX_QUEUED_INCOMING: Final = 10_000


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """One delivery as the ingest sees it.

    Parameters
    ----------
    topic
        Full topic.
    payload
        Raw payload bytes.
    retained
        Delivered from the broker's retained store.
    """

    topic: str
    payload: bytes
    retained: bool


class SubscribeOnlyClient(Protocol):
    """The broker capabilities the ingest uses: connect, subscribe, receive."""

    async def __aenter__(self) -> Self:
        """Connect."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Disconnect."""
        ...

    async def subscribe(self, topic: str) -> None:
        """Subscribe to ``topic`` (wildcards allowed)."""
        ...

    def messages(self) -> AsyncIterator[InboundMessage]:
        """Iterate over inbound deliveries until the connection drops."""
        ...


def _payload_bytes(payload: Any) -> bytes:
    if isinstance(payload, bytes | bytearray):
        return bytes(payload)
    if payload is None:
        return b""
    return str(payload).encode("utf-8")


def tls_context(settings: Settings) -> ssl.SSLContext | None:
    """Return the TLS context for the broker connection, or ``None`` without TLS."""
    if not settings.mqtt_tls:
        return None
    cafile = str(settings.mqtt_ca_file) if settings.mqtt_ca_file is not None else None
    return ssl.create_default_context(cafile=cafile)


class ReadOnlyMqttClient:
    """Subscribe-only facade over :class:`aiomqtt.Client`; it has no publish capability.

    Parameters
    ----------
    settings
        Broker address, credentials and TLS.
    client_factory
        Builds the underlying client from keyword arguments (injectable for tests).
    """

    __slots__ = ("_client",)

    def __init__(
        self,
        settings: Settings,
        *,
        client_factory: Callable[..., Any] = aiomqtt.Client,
    ) -> None:
        password = settings.mqtt_password.get_secret_value() if settings.mqtt_password else None
        self._client = client_factory(
            hostname=settings.mqtt_host,
            port=settings.mqtt_port,
            username=settings.mqtt_username,
            password=password,
            identifier=settings.mqtt_client_id or f"ovenbird-{secrets.token_hex(4)}",
            will=None,
            clean_session=True,
            keepalive=KEEPALIVE_S,
            timeout=CONNECT_TIMEOUT_S,
            tls_context=tls_context(settings),
            max_queued_incoming_messages=MAX_QUEUED_INCOMING,
            logger=logging.getLogger("ovenbird.mqtt.client"),
        )

    def __repr__(self) -> str:
        """Representation without credentials."""
        return "ReadOnlyMqttClient()"

    async def __aenter__(self) -> Self:
        """Connect to the broker."""
        await self._client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Disconnect from the broker."""
        await self._client.__aexit__(exc_type, exc, tb)

    async def subscribe(self, topic: str) -> None:
        """Subscribe to ``topic`` with QoS 0."""
        await self._client.subscribe(topic, qos=0)

    async def messages(self) -> AsyncIterator[InboundMessage]:
        """Yield inbound deliveries with their retained flag."""
        async for message in self._client.messages:
            yield InboundMessage(
                str(message.topic), _payload_bytes(message.payload), bool(message.retain)
            )


def subscriptions(settings: Settings) -> tuple[str, ...]:
    """Return the topic filters to subscribe: ``<base>/#`` plus plain inputs outside it."""
    base = settings.heishamon_base
    topics = [f"{base}/#"]
    topics += [item.topic for item in settings.mqtt_inputs if not item.topic.startswith(base + "/")]
    return tuple(topics)


def broker_of(settings: Settings) -> tuple[Any, ...]:
    """Return what a broker session depends on: address, credentials, TLS, client id."""
    password = settings.mqtt_password.get_secret_value() if settings.mqtt_password else None
    return (
        settings.mqtt_host,
        settings.mqtt_port,
        settings.mqtt_username,
        password,
        settings.mqtt_tls,
        settings.mqtt_ca_file,
        settings.mqtt_client_id,
    )


def build_router(settings: Settings) -> InputRouter:
    """Return the core's input router for the configured base and plain inputs."""
    return InputRouter(HeishaMonParser(settings.heishamon_base), settings.mqtt_signals())


class MqttIngest:
    """Keep a subscription alive and route every delivery into the runtime.

    :meth:`reconfigure` takes new settings: a changed broker or subscription ends the
    running session and the next one starts at once with the new settings; changed
    plain inputs only swap the router.

    Parameters
    ----------
    settings
        Service settings.
    runtime
        Receives parse results and the connection state.
    connect
        Returns a fresh, unconnected client per attempt (tests); by default a
        :class:`ReadOnlyMqttClient` of the current settings.
    backoff
        Reconnect delays.
    """

    def __init__(
        self,
        settings: Settings,
        runtime: Runtime,
        *,
        connect: Callable[[], SubscribeOnlyClient] | None = None,
        backoff: Backoff | None = None,
    ) -> None:
        self.settings = settings
        self.runtime = runtime
        self.router = build_router(settings)
        self.topics = subscriptions(settings)
        self._connect = connect
        self.backoff = backoff or Backoff()
        self.received = 0
        self.heishamon_received = 0
        self.heishamon_live = 0
        self._session: asyncio.Task[str] | None = None
        self._restart = False
        self._wake = asyncio.Event()

    def reconfigure(self, settings: Settings) -> None:
        """Take new settings; reconnect when the broker or the subscriptions changed.

        A reconnect starts at once, also while the ingest waits out a reconnect delay
        after a failed session.
        """
        old = self.settings
        self.settings = settings
        self.router = build_router(settings)
        topics = subscriptions(settings)
        if broker_of(old) == broker_of(settings) and topics == self.topics:
            return
        self.topics = topics
        self.heishamon_received = 0
        self.heishamon_live = 0
        self._restart = True
        self._wake.set()
        if self._session is not None and not self._session.done():
            self._session.cancel()

    async def run(self) -> None:
        """Connect, subscribe and ingest forever, reconnecting with backoff."""
        while True:
            started = time.monotonic()
            self._restart = False
            self._wake.clear()
            self._session = asyncio.create_task(self.session())
            try:
                reason = await self._session
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if not self._restart or (current is not None and current.cancelling()):
                    raise
                reason = "settings changed"
            if self._restart:
                LOGGER.warning("MQTT %s; reconnecting with the new settings", reason)
                self.backoff.reset()
                continue
            delay = self.backoff.next_delay(time.monotonic() - started)
            LOGGER.warning("MQTT %s; reconnecting in %.0f s", reason, delay)
            await self._pause(delay)
            if self._restart:
                LOGGER.warning("MQTT settings changed; reconnecting with the new settings")
                self.backoff.reset()

    async def _pause(self, delay: float) -> None:
        """Wait ``delay`` seconds, or less when :meth:`reconfigure` asks for a reconnect."""
        try:
            await asyncio.wait_for(self._wake.wait(), delay)
        except TimeoutError:
            return

    def client(self) -> SubscribeOnlyClient:
        """Return a fresh client for the current settings."""
        if self._connect is not None:
            return self._connect()
        return ReadOnlyMqttClient(self.settings)

    async def session(self) -> str:
        """Run one connection until it ends.

        Returns
        -------
        str
            Why the session ended.
        """
        try:
            async with self.client() as client:
                for topic in self.topics:
                    await client.subscribe(topic)
                self.mark_connected()
                LOGGER.info(
                    "MQTT connected to %s:%d; subscribed %s",
                    self.settings.mqtt_host,
                    self.settings.mqtt_port,
                    ", ".join(self.topics),
                )
                async for message in client.messages():
                    self.ingest(message)
            return "message stream ended"
        except aiomqtt.MqttError as exc:
            return f"connection lost ({exc})"
        except OSError as exc:
            return f"connection failed ({type(exc).__name__}: {exc})"
        finally:
            self.mark_disconnected()

    def mark_connected(self) -> None:
        """Report a subscribed broker session (the link is up and works)."""
        self.runtime.mqtt_connected = True
        self.runtime.set_link(SourceKind.MQTT, up=True, confirmed=True)

    def mark_disconnected(self) -> None:
        """Report the end of the broker session."""
        self.runtime.mqtt_connected = False
        self.runtime.set_link(SourceKind.MQTT, up=False)

    def ingest(self, message: InboundMessage) -> None:
        """Route one delivery through the core and apply it."""
        self.received += 1
        if message.topic.startswith(f"{self.settings.heishamon_base}/main/"):
            self.heishamon_received += 1
            if not message.retained:
                self.heishamon_live += 1
        delivery = MqttMessage(
            message.topic, message.payload, message.retained, self.runtime.clock()
        )
        self.runtime.apply(self.router.route(delivery))

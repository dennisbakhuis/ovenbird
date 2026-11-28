"""An in-memory MQTT broker and the clients the real (asyncio) service and simulator use.

Retained store, wildcard subscriptions, no QoS, no network. The same stand-ins as the
service's end-to-end tests: :class:`IngestClient` for the service's MQTT ingest,
:class:`LinkClient` for its command worker and :class:`SimClient` for the simulated
HeishaMon's runner (which publishes its last will when it disconnects).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Any, Self

import aiomqtt

from ovenbird.control.adapter import Command
from ovenbird.mqtt import InboundMessage

type Delivery = tuple[str, str, bool]


class MemoryBroker:
    """Retained store and subscriptions; :attr:`log` keeps every publish."""

    def __init__(self) -> None:
        """Create an empty store with no subscribers."""
        self.retained: dict[str, str] = {}
        self.subscribers: list[tuple[str, asyncio.Queue[Delivery]]] = []
        self.log: list[Delivery] = []

    def publish(self, topic: str, payload: str, retain: bool) -> None:
        """Deliver to every matching subscription (and keep it when retained)."""
        self.log.append((topic, payload, retain))
        if retain:
            self.retained[topic] = payload
        for pattern, queue in self.subscribers:
            if aiomqtt.Topic(topic).matches(pattern):
                queue.put_nowait((topic, payload, False))

    def subscribe(self, pattern: str, queue: asyncio.Queue[Delivery]) -> None:
        """Subscribe ``queue`` and deliver the matching retained messages."""
        self.subscribers.append((pattern, queue))
        for topic, payload in self.retained.items():
            if aiomqtt.Topic(topic).matches(pattern):
                queue.put_nowait((topic, payload, True))


class _Session:
    """Async context manager that does nothing on enter or exit."""

    async def __aenter__(self) -> Self:
        """Enter the session."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Leave the session without cleanup."""
        return


class IngestClient(_Session):
    """Subscribe-only client of the service's MQTT ingest.

    Parameters
    ----------
    broker
        The broker.
    """

    def __init__(self, broker: MemoryBroker) -> None:
        self.broker = broker
        self.queue: asyncio.Queue[Delivery] = asyncio.Queue()

    async def subscribe(self, topic: str) -> None:
        """Subscribe."""
        self.broker.subscribe(topic, self.queue)

    async def messages(self) -> AsyncIterator[InboundMessage]:
        """Yield deliveries forever."""
        while True:
            topic, payload, retained = await self.queue.get()
            yield InboundMessage(topic, payload.encode("utf-8"), retained)


class LinkClient(_Session):
    """Command link of the service's worker (publishes commands, never retained).

    Parameters
    ----------
    broker
        The broker.
    """

    def __init__(self, broker: MemoryBroker) -> None:
        self.broker = broker

    async def send(self, command: Command) -> None:
        """Publish ``command``."""
        self.broker.publish(command.topic, command.payload, False)


class _Message:
    """A delivered message with the topic, bytes payload and retain flag aiomqtt gives."""

    def __init__(self, topic: str, payload: str, retain: bool) -> None:
        """Wrap ``payload`` as UTF-8 bytes and ``topic`` as an aiomqtt topic."""
        self.topic = aiomqtt.Topic(topic)
        self.payload = payload.encode("utf-8")
        self.retain = retain


class SimClient:
    """Client of the simulator's runner; publishes the last will on disconnect.

    Parameters
    ----------
    broker
        The broker.
    **kwargs
        The runner's connection keywords (``will`` is used).
    """

    def __init__(self, broker: MemoryBroker, **kwargs: Any) -> None:
        self.broker = broker
        self.kwargs = kwargs
        self.queue: asyncio.Queue[Delivery] = asyncio.Queue()

    async def __aenter__(self) -> Self:
        """Connect."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Disconnect; the broker publishes the will."""
        will = self.kwargs.get("will")
        if will is not None:
            self.broker.publish(will.topic, str(will.payload), will.retain)

    async def subscribe(self, topic: str, qos: int = 0) -> None:
        """Subscribe."""
        self.broker.subscribe(topic, self.queue)

    async def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False) -> None:
        """Publish ``payload`` to ``topic`` on the broker.

        Parameters
        ----------
        topic
            Topic to publish to.
        payload
            Message body.
        qos
            Ignored; the broker has no QoS.
        retain
            Keep the message as the topic's retained value.
        """
        self.broker.publish(topic, payload, retain)

    @property
    def messages(self) -> AsyncIterator[_Message]:
        """Deliveries as aiomqtt-like messages."""

        async def stream() -> AsyncIterator[_Message]:
            """Yield deliveries forever as aiomqtt-like messages."""
            while True:
                yield _Message(*(await self.queue.get()))

        return stream()

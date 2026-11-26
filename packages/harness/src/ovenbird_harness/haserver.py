"""An in-memory Home Assistant WebSocket API for the real (asyncio) service.

:class:`MemoryHomeAssistant` stands in for Home Assistant behind the service's
:class:`~ovenbird.ha.HaInput`: :meth:`MemoryHomeAssistant.connect` is the
``ha_connector`` of :func:`ovenbird.service.build_service` and returns a WebSocket
stand-in that speaks the subset of the API the input uses (``auth``,
``subscribe_entities`` with its compressed snapshot and change events, ``get_states``
and ``get_config`` with a metric unit system; other requests, such as the registry
reads, fail as on an instance without them). The entity states come from a device
bridge: :meth:`report` sets a state as a Zigbee integration would (``last_reported``
on every report, ``last_changed`` on a new value) and forwards a change to the open
subscriptions, which is what :func:`bridge` does for the simulated board's room and
humidity publications on the in-memory broker. Nothing touches the network.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self

from ovenbird_harness.broker import Delivery, MemoryBroker

type Wall = Callable[[], float]


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat()


@dataclass
class _State:
    state: str
    unit: str | None
    last_changed: float
    last_reported: float

    def compressed(self) -> dict[str, Any]:
        attributes = {} if self.unit is None else {"unit_of_measurement": self.unit}
        return {"s": self.state, "a": attributes, "lc": self.last_changed}

    def full(self, entity_id: str) -> dict[str, Any]:
        attributes = {} if self.unit is None else {"unit_of_measurement": self.unit}
        return {
            "entity_id": entity_id,
            "state": self.state,
            "attributes": attributes,
            "last_changed": _iso(self.last_changed),
            "last_updated": _iso(self.last_changed),
            "last_reported": _iso(self.last_reported),
        }


class MemorySocket:
    """One client connection (the WebSocket side :class:`~ovenbird.ha.HaInput` sees).

    Parameters
    ----------
    server
        The Home Assistant it talks to.
    """

    def __init__(self, server: MemoryHomeAssistant) -> None:
        self.server = server
        self.outbox: asyncio.Queue[str | None] = asyncio.Queue()
        self.subscription: int | None = None
        self.last_id = 0
        self.closed = False

    async def __aenter__(self) -> Self:
        """Open: Home Assistant asks for authentication."""
        self.push({"type": "auth_required", "ha_version": "2026.11.0"})
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close."""
        await self.close()

    def push(self, message: Any) -> None:
        """Queue a message to the client."""
        if not self.closed:
            self.outbox.put_nowait(json.dumps(message))

    async def send(self, raw: str) -> None:
        """Handle one client message."""
        request = json.loads(raw)
        kind = request.get("type")
        if "id" in request:
            if int(request["id"]) <= self.last_id:
                error = {"code": "id_reuse", "message": "Identifier values have to increase."}
                self.push({"id": request["id"], "type": "result", "success": False, "error": error})
                return
            self.last_id = int(request["id"])
        if kind == "auth":
            self.push({"type": "auth_ok", "ha_version": "2026.11.0"})
        elif kind == "subscribe_entities":
            self.subscription = int(request["id"])
            self.push({"id": self.subscription, "type": "result", "success": True, "result": None})
            wanted = set(request.get("entity_ids") or ())
            added = {
                entity: state.compressed()
                for entity, state in self.server.states.items()
                if entity in wanted
            }
            self.push({"id": self.subscription, "type": "event", "event": {"a": added}})
        elif kind == "get_states":
            self.server.reads += 1
            result = [state.full(entity) for entity, state in self.server.states.items()]
            self.push({"id": request["id"], "type": "result", "success": True, "result": result})
        elif kind == "get_config":
            config = {"unit_system": {"temperature": "°C"}, "version": "2026.11.0"}
            self.push({"id": request["id"], "type": "result", "success": True, "result": config})
        elif "id" in request:
            error = {"code": "unknown_command", "message": "Unknown command."}
            self.push({"id": request["id"], "type": "result", "success": False, "error": error})

    async def recv(self) -> str:
        """Return the next message to the client."""
        item = await self.outbox.get()
        if item is None:
            raise ConnectionError("closed")
        return item

    def __aiter__(self) -> AsyncIterator[str]:
        """Messages until the connection closes."""
        return self._messages()

    async def _messages(self) -> AsyncIterator[str]:
        while True:
            item = await self.outbox.get()
            if item is None:
                return
            yield item

    async def close(self) -> None:
        """Close the connection."""
        if not self.closed:
            self.closed = True
            self.outbox.put_nowait(None)
            self.server.sockets.discard(self)


class MemoryHomeAssistant:
    """Home Assistant's entity states and WebSocket API, in memory.

    Parameters
    ----------
    wall
        Simulated wall-clock unix time of the reports (the service's clock).
    units
        ``unit_of_measurement`` per entity.
    """

    def __init__(self, wall: Wall, units: Mapping[str, str]) -> None:
        self.wall = wall
        self.units = dict(units)
        self.states: dict[str, _State] = {}
        self.sockets: set[MemorySocket] = set()
        self.sessions = 0
        self.reads = 0
        self.events = 0

    def connect(self, url: str) -> MemorySocket:
        """Open a connection (the ``ha_connector`` of ``build_service``)."""
        del url
        socket = MemorySocket(self)
        self.sockets.add(socket)
        self.sessions += 1
        return socket

    def report(self, entity_id: str, state: str) -> None:
        """Apply a device report; forward a new value to the subscriptions."""
        now = self.wall()
        current = self.states.get(entity_id)
        if current is None:
            created = _State(state, self.units.get(entity_id), now, now)
            self.states[entity_id] = created
            self._event({"a": {entity_id: created.compressed()}})
            return
        current.last_reported = now
        if current.state == state:
            return
        current.state = state
        current.last_changed = now
        self._event({"c": {entity_id: {"+": {"s": state, "lc": now}}}})

    def _event(self, event: dict[str, Any]) -> None:
        for socket in list(self.sockets):
            if socket.subscription is not None:
                socket.push({"id": socket.subscription, "type": "event", "event": event})
                self.events += 1


async def bridge(
    broker: MemoryBroker, home: MemoryHomeAssistant, topics: Mapping[str, str]
) -> None:
    """Forward the board's device publications to Home Assistant entities forever.

    Parameters
    ----------
    broker
        The in-memory broker the simulated board publishes to.
    home
        The Home Assistant that receives the reports.
    topics
        Entity id per MQTT topic.
    """
    queue: asyncio.Queue[Delivery] = asyncio.Queue()
    for topic in topics:
        broker.subscribe(topic, queue)
    while True:
        topic, payload, _ = await queue.get()
        home.report(topics[topic], payload)

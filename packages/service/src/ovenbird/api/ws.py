"""WebSocket fan-out: per-client coalescing outboxes and slow-client disconnects.

Each client owns a :class:`Channel` holding at most one pending message per type
(``snapshot``, ``health``, ``decision``, ``config``); a newer message replaces an unsent
one. A client whose
pending messages are replaced too often, or whose send does not complete in time,
is disconnected.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Final

from starlette.websockets import WebSocket, WebSocketDisconnect

from ovenbird.clock import iso_z
from ovenbird.payloads import Json
from ovenbird.runtime import Runtime
from ovenbird_core import Instant

LOGGER = logging.getLogger("ovenbird.api.ws")
SNAPSHOT_INTERVAL_S: Final = 5.0
HEALTH_INTERVAL_S: Final = 1.0
SEND_TIMEOUT_S: Final = 10.0
MAX_OVERWRITES: Final = 3
MAX_CLIENTS: Final = 32
TRY_AGAIN_LATER: Final = 1013


def encode(kind: str, data: Json) -> str:
    """Serialise one server message."""
    return json.dumps({"type": kind, "data": data}, separators=(",", ":"), ensure_ascii=False)


@dataclass(eq=False)
class Channel:
    """Bounded, coalescing outbox of one client.

    Parameters
    ----------
    max_overwrites
        A message type replaced this many times in a row without being sent marks
        the client as slow.
    """

    max_overwrites: int = MAX_OVERWRITES
    pending: dict[str, str] = field(default_factory=dict)
    overwrites: int = 0
    slow: bool = False
    wakeup: asyncio.Event = field(default_factory=asyncio.Event)

    def offer(self, kind: str, text: str) -> bool:
        """Queue ``text`` as the latest message of ``kind``.

        Returns
        -------
        bool
            ``False`` once the client is considered slow.
        """
        if kind in self.pending:
            self.overwrites += 1
            if self.overwrites >= self.max_overwrites:
                self.slow = True
        self.pending[kind] = text
        self.wakeup.set()
        return not self.slow

    async def take(self) -> list[str]:
        """Wait for pending messages and return them in their queueing order."""
        while not self.pending:
            self.wakeup.clear()
            await self.wakeup.wait()
        messages = list(self.pending.values())
        self.pending.clear()
        self.overwrites = 0
        return messages


class Broadcaster:
    """Push snapshots and health changes to every connected client.

    Parameters
    ----------
    runtime
        Source of snapshots and health.
    snapshot_interval
        Minimum seconds between snapshot broadcasts.
    health_interval
        Seconds between health evaluations.
    send_timeout
        A send taking longer disconnects the client.
    max_clients
        Further connections are refused.
    """

    def __init__(
        self,
        runtime: Runtime,
        *,
        snapshot_interval: float = SNAPSHOT_INTERVAL_S,
        health_interval: float = HEALTH_INTERVAL_S,
        send_timeout: float = SEND_TIMEOUT_S,
        max_clients: int = MAX_CLIENTS,
    ) -> None:
        self.runtime = runtime
        self.snapshot_interval = snapshot_interval
        self.health_interval = health_interval
        self.send_timeout = send_timeout
        self.max_clients = max_clients
        self.channels: set[Channel] = set()
        self.disconnected_slow = 0
        self._sent_version = -1
        self._sent_health: Json | None = None

    def publish_changes(self, now: float, last_snapshot: float) -> float:
        """Queue a health message on change and a snapshot when due.

        Parameters
        ----------
        now
            Current monotonic time.
        last_snapshot
            Monotonic time of the previous snapshot broadcast.

        Returns
        -------
        float
            Monotonic time of the latest snapshot broadcast.
        """
        health = self.runtime.health()
        if health != self._sent_health:
            self._sent_health = health
            self._fan_out("health", encode("health", health))
        due = now - last_snapshot >= self.snapshot_interval
        if due and self.runtime.version != self._sent_version:
            self._sent_version = self.runtime.version
            self._fan_out("snapshot", encode("snapshot", self.runtime.snapshot()))
            return now
        return last_snapshot

    def publish_decision(self, decision: Json) -> None:
        """Queue a controller decision for every client."""
        self._fan_out("decision", encode("decision", decision))

    def publish_config(self, version: int | None, applied_at: Instant) -> None:
        """Queue the notice that a configuration version is in effect."""
        data = {"version": version, "applied_at": iso_z(applied_at.wall)}
        self._fan_out("config", encode("config", data))

    def _fan_out(self, kind: str, text: str) -> None:
        """Offer one encoded message to every client's channel."""
        for channel in list(self.channels):
            channel.offer(kind, text)

    async def run(self) -> None:
        """Evaluate changes forever."""
        last_snapshot = -float("inf")
        tick = min(self.health_interval, self.snapshot_interval)
        while True:
            last_snapshot = self.publish_changes(time.monotonic(), last_snapshot)
            await asyncio.sleep(tick)

    async def serve(self, websocket: WebSocket) -> None:
        """Handle one client from accept to disconnect.

        Parameters
        ----------
        websocket
            Accepted-on-entry client connection to serve.
        """
        await websocket.accept()
        if len(self.channels) >= self.max_clients:
            await websocket.close(TRY_AGAIN_LATER, "too many clients")
            return
        channel = Channel()
        channel.offer("snapshot", encode("snapshot", self.runtime.snapshot()))
        channel.offer("health", encode("health", self.runtime.health()))
        self.channels.add(channel)
        sender = asyncio.create_task(self._send_loop(websocket, channel))
        receiver = asyncio.create_task(_drain_incoming(websocket))
        try:
            await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            self.channels.discard(channel)
            for task in (sender, receiver):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        timed_out = (
            sender.done()
            and not sender.cancelled()
            and sender.exception() is None
            and sender.result()
        )
        if channel.slow or timed_out:
            self.disconnected_slow += 1
            LOGGER.warning("disconnected a slow WebSocket client")
            with contextlib.suppress(Exception):
                await websocket.close(TRY_AGAIN_LATER, "client too slow")

    async def _send_loop(self, websocket: WebSocket, channel: Channel) -> bool:
        """Send pending messages until the client is slow; returns ``True`` when it was."""
        while True:
            if channel.slow:
                return True
            messages = await channel.take()
            for text in messages:
                try:
                    await asyncio.wait_for(websocket.send_text(text), self.send_timeout)
                except TimeoutError:
                    return True
            if channel.slow:
                return True


async def _drain_incoming(websocket: WebSocket) -> None:
    """Read and discard client messages until the client disconnects."""
    with contextlib.suppress(WebSocketDisconnect):
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return

"""Drive the command adapter on the service clock and publish what it releases."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

from ovenbird.clock import Sleep
from ovenbird.control.adapter.commands import CommandAdapter
from ovenbird.control.adapter.model import (
    Command,
    Reader,
)
from ovenbird.control.adapter.publish import CommandSender
from ovenbird.runtime import Runtime
from ovenbird_core import Instant

WORKER_POLL_S: Final = 1.0


@dataclass
class CommandWorker:
    """Drive the adapter on the service clock and publish what it releases.

    Parameters
    ----------
    adapter
        The adapter.
    runtime
        Clock and state store.
    connect
        Returns a fresh, unconnected link per attempt.
    sleep
        Sleeps on the service clock.
    poll_s
        Seconds between adapter ticks.
    """

    adapter: CommandAdapter
    runtime: Runtime
    connect: Callable[[], CommandSender]
    sleep: Sleep
    poll_s: float = WORKER_POLL_S
    connected: bool = field(default=False, init=False)

    def reader(self, now: Instant) -> Reader:
        """Return a reader of the store's views at ``now``."""
        store = self.runtime.store
        return lambda signal: store.view(signal, now)

    async def step(self, link: CommandSender) -> Command | None:
        """Tick the adapter once and publish the released command, if any."""
        now = self.runtime.clock()
        board = self.runtime.store.heishamon_status(now)
        command = self.adapter.tick(now, self.reader(now), board)
        if command is None:
            return None
        try:
            await link.send(command)
        except Exception as exc:
            self.adapter.publish_failed(command, self.runtime.clock(), f"{type(exc).__name__}")
            raise
        self.adapter.published(command, self.runtime.clock())
        return command

    async def run(self) -> None:
        """Connect and tick forever (the supervisor restarts it after a failure)."""
        async with self.connect() as link:
            self.connected = True
            try:
                while True:
                    await self.step(link)
                    await self.sleep(self.poll_s)
            finally:
                self.connected = False

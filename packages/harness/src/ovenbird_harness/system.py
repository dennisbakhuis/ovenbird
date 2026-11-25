"""The service's components assembled on a manual clock and driven one call at a time.

:class:`System` builds what :func:`ovenbird.service.build_service` builds, minus the
asyncio supervision and HTTP: the configuration store (:class:`~ovenbird.configstore.ConfigManager`,
whose effective settings everything else is built from), the history writer (a real
writer thread on the real schema), the runtime and state store, the MQTT ingest, and
the control loop, command adapter, worker, safety monitor and alarm board from
:func:`ovenbird.service.build_control` (which also restores persisted controller and
adapter state), and the pump settings service the ``pump/settings`` API uses. The
command worker publishes through the real :class:`~ovenbird.control.adapter.CommandLink`
(guard and allowlist checks) whose MQTT client is replaced by a callback; its coroutine
never suspends, so it is stepped synchronously.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Coroutine
from types import TracebackType
from typing import Any, Final, Self

from ovenbird.config import Settings
from ovenbird.configstore import ConfigManager
from ovenbird.control import CommandLink, CommandWorker, ControlLoop
from ovenbird.control.adapter import Command, CommandAdapter, CommandSender
from ovenbird.control.monitors import SafetyMonitor
from ovenbird.history import HistoryWriter
from ovenbird.history.journal import AlarmRow, CommandRow, DecisionRow, StateRow
from ovenbird.mqtt import InboundMessage, MqttIngest
from ovenbird.pump.settings import PumpSettings
from ovenbird.service import build_control, build_runtime, build_writer
from ovenbird_core import Instant
from ovenbird_harness.clock import ManualClock

MAX_BACKLOG: Final = 50_000
PACE_SLEEP_S: Final = 0.002

type PublishSink = Callable[[str, str, int, bool], None]


class SuspendedError(RuntimeError):
    """A coroutine of the service waited for something; the stepped harness cannot wait."""


def run_sync[T](coroutine: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine that completes without suspending and return its result.

    Raises
    ------
    SuspendedError
        When the coroutine awaits something that is not ready.
    """
    try:
        coroutine.send(None)
    except StopIteration as done:
        result: T = done.value
        return result
    coroutine.close()
    raise SuspendedError("a service coroutine suspended in the stepped harness")


async def _never_sleep(_: float) -> None:
    raise SuspendedError("the stepped harness drives time itself")


class HarnessWriter(HistoryWriter):
    """History writer that shows every journal and state row to the checks and paces producers.

    Takes the arguments of :class:`~ovenbird.history.HistoryWriter`; build it with
    :func:`harness_writer`.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.on_decision: list[Callable[[DecisionRow], None]] = []
        self.on_command: list[Callable[[CommandRow], None]] = []
        self.on_alarm: list[Callable[[AlarmRow], None]] = []
        self.on_state: list[Callable[[StateRow], None]] = []
        self.offered = 0

    def offer_decision(self, row: DecisionRow) -> None:
        """Queue a decision row and show it to the checks."""
        for listener in self.on_decision:
            listener(row)
        super().offer_decision(row)

    def offer_command(self, row: CommandRow) -> None:
        """Queue a command row and show it to the checks."""
        for listener in self.on_command:
            listener(row)
        super().offer_command(row)

    def offer_alarm(self, row: AlarmRow) -> None:
        """Queue an alarm row and show it to the checks."""
        for listener in self.on_alarm:
            listener(row)
        super().offer_alarm(row)

    def offer_state(self, row: StateRow) -> None:
        """Queue a persisted-state row and show it to the checks."""
        for listener in self.on_state:
            listener(row)
        super().offer_state(row)

    def pace(self, limit: int = MAX_BACKLOG) -> None:
        """Wait until the backlog is below ``limit`` so the queue never drops rows."""
        while self.backlog() > limit and self.is_alive():
            time.sleep(PACE_SLEEP_S)


def harness_writer(settings: Settings, clock: ManualClock) -> HarnessWriter:
    """Build the service's history writer on the run's clock, without snapshots.

    Parameters
    ----------
    settings
        Service settings (path, retention, queue size).
    clock
        The run's clock (wall time for retention).

    Returns
    -------
    HarnessWriter
        The writer (not started), with a queue large enough for :meth:`HarnessWriter.pace`.
    """
    return build_writer(
        settings,
        HarnessWriter,
        wall=lambda: clock.wall,
        queue_size=max(settings.history_queue_size, 2 * MAX_BACKLOG),
        snapshots=False,
    )


class CallbackClient:
    """The publishing MQTT client behind :class:`~ovenbird.control.adapter.CommandLink`.

    Parameters
    ----------
    sink
        Receives ``(topic, payload, qos, retain)`` of every publish.
    **_
        The connection keywords the link passes (ignored: nothing connects).
    """

    def __init__(self, sink: PublishSink, **_: Any) -> None:
        self.sink = sink

    async def __aenter__(self) -> Self:
        """Connect (nothing to do)."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Disconnect (nothing to do)."""
        return

    async def publish(self, topic: str, payload: str, qos: int, retain: bool) -> None:
        """Hand the publish to the sink."""
        self.sink(topic, payload, qos, retain)


class System:
    """One ovenbird instance on a manual clock.

    Parameters
    ----------
    settings
        Installation settings (simulation mode); a stored configuration applies on top.
    clock
        The run's clock.
    publish
        Receives every command the worker publishes.
    listen
        Called with the history writer before anything is built on it, so rows the
        restore of persisted state journals reach the run's listeners too.
    """

    def __init__(
        self,
        settings: Settings,
        clock: ManualClock,
        publish: PublishSink,
        listen: Callable[[HarnessWriter], None] | None = None,
    ) -> None:
        self.config = ConfigManager.open(settings, clock, locked={})
        settings = self.config.settings
        self.settings = settings
        self.clock = clock
        self.writer = harness_writer(settings, clock)
        if listen is not None:
            listen(self.writer)
        self.writer.start()
        self.runtime = build_runtime(settings, clock, self.writer)
        self.ingest = MqttIngest(settings, self.runtime)
        self._publish = publish
        self.loop, worker = build_control(
            settings,
            self.runtime,
            self.writer,
            sleep=_never_sleep,
            command_connect=self._link,
            hold=self.config.hold,
            config_version=self.config.version,
        )
        self.config.attach(self.loop, self.loop.alarms)
        if worker is None or self.loop.adapter is None or self.loop.safety is None:
            raise RuntimeError("the harness needs a permitted publish guard (simulation mode)")
        self.worker: CommandWorker = worker
        self.adapter: CommandAdapter = self.loop.adapter
        self.monitor: SafetyMonitor = self.loop.safety
        self.pumps = PumpSettings(
            self.runtime, self.loop.guard, self.adapter, self.config, settings.history_path
        )
        self._sender: CommandSender | None = None

    def _link(self) -> CommandSender:
        return CommandLink(
            self.settings,
            self.loop.guard,
            self.adapter.config.topics(),
            client_factory=lambda **kwargs: CallbackClient(self._publish, **kwargs),
        )

    @property
    def control(self) -> ControlLoop:
        """The control loop."""
        return self.loop

    def connect_mqtt(self) -> None:
        """Open the ingest's broker session (``MqttIngest.mark_connected``).

        Retained deliveries after the subscription are the caller's job.
        """
        self.ingest.mark_connected()

    def disconnect_mqtt(self) -> None:
        """Close the ingest's broker session (``MqttIngest.mark_disconnected``)."""
        self.ingest.mark_disconnected()

    def connect_worker(self) -> None:
        """Open the worker's publishing link."""
        if self._sender is not None:
            return
        sender = self.worker.connect()
        run_sync(sender.__aenter__())
        self._sender = sender
        self.worker.connected = True

    def disconnect_worker(self) -> None:
        """Close the worker's publishing link."""
        sender = self._sender
        if sender is None:
            return
        run_sync(sender.__aexit__(None, None, None))
        self._sender = None
        self.worker.connected = False

    def deliver(self, topic: str, payload: str, *, retained: bool = False) -> None:
        """Ingest one MQTT delivery at the clock's current instant."""
        self.ingest.ingest(InboundMessage(topic, payload.encode("utf-8"), retained))

    def worker_step(self) -> Command | None:
        """Run one command worker step (adapter tick, publish); nothing without a link."""
        if self._sender is None:
            return None
        return run_sync(self.worker.step(self._sender))

    def adapter_tick(self, now: Instant) -> Command | None:
        """Tick the adapter alone at ``now`` (replay of a recorded worker step)."""
        store = self.runtime.store
        return self.adapter.tick(now, self.worker.reader(now), store.heishamon_status(now))

    def check(self, now: Instant | None = None) -> None:
        """Run the safety monitors once."""
        self.monitor.check(now)

    def tick(self, now: Instant | None = None) -> DecisionRow:
        """Run one control loop tick."""
        return self.loop.tick(now)

    def close(self) -> None:
        """Flush and close the history database and the configuration store."""
        self.disconnect_worker()
        self.writer.stop(timeout=600.0)
        self.config.close()

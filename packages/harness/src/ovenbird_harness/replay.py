"""B2a: record the real asyncio service's inbound stream and replay it through the stepper.

:func:`record_service` builds the service with :func:`ovenbird.service.build_service`
(ingest, history, control loop, safety monitor, command worker and HTTP) and runs it
with the simulated HeishaMon's runner through an in-memory broker on a scaled clock,
like ``test_service_against_the_simulator``. It taps the service at the points where
time enters: every delivery the ingest handles, every link-state report, every
control-loop tick, safety check, adapter tick and publish outcome, each with the
service-clock instant it used. :func:`replay` feeds that log, in order and at the same
instants, into a :class:`~ovenbird_harness.system.System` (the B1 stepper's
components) and returns its decision rows; :func:`compare_rows` requires them to be
identical to the real service's.

With Home Assistant configured (the HA path: room and humidity entities, the
``on_change`` profile) the service talks to an in-memory Home Assistant
(:mod:`ovenbird_harness.haserver`) fed by the board's device publications, and the tap
also logs the HA input's session start and end, every ``get_states`` request id and
every message it handles; the clock is frozen while one message is handled, so the
replay sees the same instants. Link reports made inside those calls are not logged
separately (the replayed call makes them again).
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import functools
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ovenbird.config import Settings
from ovenbird.control.adapter import Command
from ovenbird.ha import HaInput
from ovenbird.history.journal import DecisionRow
from ovenbird.mqtt import InboundMessage, MqttIngest
from ovenbird.service import Service, build_service
from ovenbird_core import Instant, SourceKind
from ovenbird_harness.broker import IngestClient, LinkClient, MemoryBroker, SimClient
from ovenbird_harness.clock import ManualClock
from ovenbird_harness.haserver import MemoryHomeAssistant, bridge
from ovenbird_harness.system import System
from ovenbird_sim.heishamon import runner
from ovenbird_sim.heishamon.board import SimulatedHeishaMon

ROW_FIELDS = (
    "ts",
    "controller",
    "mode",
    "ladder",
    "reason",
    "setpoint",
    "record",
    "arbiter",
    "commands",
)


@dataclass(frozen=True, slots=True)
class Event:
    """One recorded event of the real service.

    Parameters
    ----------
    kind
        ``message``, ``link``, ``tick``, ``check``, ``adapter``, ``published``, ``failed``,
        ``ha_open``, ``ha_close``, ``ha_expect`` or ``ha``.
    at
        Service-clock instant the service used.
    data
        Event payload (message, link state, command).
    """

    kind: str
    at: Instant
    data: Any = None


class RecordingClock:
    """Wrap the service clock and remember the last instant it returned."""

    def __init__(self, clock: Callable[[], Instant]) -> None:
        """Wrap ``clock``.

        Parameters
        ----------
        clock
            The service clock to record.
        """
        self.clock = clock
        self.last: Instant | None = None
        self.held: Instant | None = None

    def __call__(self) -> Instant:
        """Return (and remember) the current instant, or the frozen one."""
        self.last = self.held if self.held is not None else self.clock()
        return self.last

    @contextlib.contextmanager
    def frozen(self, moment: Instant) -> Iterator[None]:
        """Return ``moment`` from every call inside the block."""
        self.held = moment
        try:
            yield
        finally:
            self.held = None


@dataclass
class Recording:
    """What a recorded run produced.

    Parameters
    ----------
    events
        The ordered event log.
    rows
        The real service's decision rows, in tick order.
    """

    events: list[Event] = field(default_factory=list)
    rows: list[DecisionRow] = field(default_factory=list)

    def check(self, *, ha: bool = False) -> None:
        """Require the event kinds every recording has (and the HA ones with ``ha``).

        Raises
        ------
        ValueError
            When a kind is missing (a tap that no longer catches its calls).
        """
        kinds = {event.kind for event in self.events}
        required = {"tick", "adapter", "message"} | ({"ha_open", "ha"} if ha else set())
        missing = sorted(required - kinds)
        if missing:
            raise ValueError(f"the recording has no {', '.join(missing)} events")


def override(target: object, name: str, function: Callable[..., Any]) -> None:
    """Replace method ``name`` of one instance (the class and other instances keep theirs).

    Raises
    ------
    AttributeError
        When ``target`` has no method ``name`` (a renamed hook would silently go
        untapped).
    """
    if not callable(getattr(target, name, None)):
        raise AttributeError(f"{type(target).__name__} has no method {name!r} to tap")
    vars(target)[name] = function


def _component[T](service: Service, kind: type[T]) -> T | None:
    """Return the service component whose bound method is an instance of ``kind``, or ``None``."""
    for component in service.components:
        owner = getattr(component.run, "__self__", None)
        if isinstance(owner, kind):
            return owner
    return None


def _mqtt_ingest(service: Service) -> MqttIngest:
    """Return the service's MQTT ingest; raise ``RuntimeError`` if it has none."""
    ingest = _component(service, MqttIngest)
    if ingest is None:
        raise RuntimeError("the service has no MQTT ingest")
    return ingest


def tap(service: Service) -> Recording:
    """Instrument a built service so that every input and tick is logged with its instant.

    Parameters
    ----------
    service
        The assembled service; its clock, ingest, links, control loop, safety monitor,
        adapter and HA input are wrapped in place.

    Returns
    -------
    Recording
        The event log and decision rows filled while the service runs.
    """
    recording = Recording()
    log = recording.events
    runtime = service.runtime
    clock = RecordingClock(runtime.clock)
    runtime.clock = clock
    ingest = _mqtt_ingest(service)
    ingest_message = ingest.ingest

    def message(item: InboundMessage) -> None:
        """Log an ingested MQTT message with the instant it was handled."""
        ingest_message(item)
        assert clock.last is not None
        log.append(Event("message", clock.last, item))

    override(ingest, "ingest", message)
    set_link = runtime.set_link
    inside_ha = [False]

    def link(source: SourceKind, *, up: bool, confirmed: bool = False) -> None:
        """Log a link state change unless it comes from inside an HA call."""
        moment = clock()
        if not inside_ha[0]:
            log.append(Event("link", moment, (source, up, confirmed)))
        set_link(source, up=up, confirmed=confirmed)

    override(runtime, "set_link", link)
    ha = _component(service, HaInput)
    if ha is not None:
        _tap_ha(ha, clock, log, inside_ha)
    loop = service.control
    loop_tick = loop.tick

    def tick(now: Instant | None = None) -> DecisionRow:
        """Log a control tick and collect its decision row."""
        moment = now or clock()
        log.append(Event("tick", moment))
        row = loop_tick(moment)
        recording.rows.append(row)
        return row

    override(loop, "tick", tick)
    monitor = loop.safety
    if monitor is not None:
        monitor_check = monitor.check

        def check(now: Instant | None = None) -> Any:
            """Log a safety monitor check."""
            moment = now or clock()
            log.append(Event("check", moment))
            return monitor_check(moment)

        override(monitor, "check", check)
    adapter = loop.adapter
    if adapter is not None:
        adapter_tick = adapter.tick
        published = adapter.published
        failed = adapter.publish_failed

        def adapter_step(now: Instant, read: Any, board: Any = None) -> Command | None:
            """Log an adapter step."""
            log.append(Event("adapter", now))
            return adapter_tick(now, read, board)

        def on_published(command: Command, now: Instant) -> None:
            """Log a command the adapter published."""
            log.append(Event("published", now, command))
            published(command, now)

        def on_failed(command: Command, now: Instant, error: str) -> None:
            """Log a command whose publish failed, with the error."""
            log.append(Event("failed", now, (command, error)))
            failed(command, now, error)

        override(adapter, "tick", adapter_step)
        override(adapter, "published", on_published)
        override(adapter, "publish_failed", on_failed)
    return recording


def _tap_ha(ha: HaInput, clock: RecordingClock, log: list[Event], inside: list[bool]) -> None:
    """Log the HA input's session and message handling, frozen at the instant of each call.

    Parameters
    ----------
    ha
        The HA input to instrument in place.
    clock
        Recording clock, frozen while a call runs.
    log
        Event log to append to.
    inside
        One-element flag set while inside an HA call (suppresses link events).
    """
    handle, open_session, close_session = ha.handle, ha.open_session, ha.close_session
    expect_states = ha.expect_states

    def hooked(kind: str, call: Callable[[], Any], data: Any = None) -> Any:
        """Run ``call`` with the clock frozen at its start and log the event of ``kind``."""
        moment = clock()
        inside[0] = True
        try:
            with clock.frozen(moment):
                result = call()
        finally:
            inside[0] = False
        log.append(Event(kind, moment, data if data is not None else result))
        return result

    def on_handle(message: dict[str, Any]) -> bool:
        """Log an HA message handled by the input."""
        result: bool = hooked("ha", lambda: handle(message), message)
        return result

    def on_open() -> None:
        """Log the opening of an HA session."""
        hooked("ha_open", open_session, True)

    def on_close() -> None:
        """Log the closing of an HA session."""
        hooked("ha_close", close_session, True)

    def on_expect() -> int:
        """Log the request id the HA input expects the next state read to use."""
        result: int = hooked("ha_expect", expect_states)
        return result

    override(ha, "handle", on_handle)
    override(ha, "open_session", on_open)
    override(ha, "close_session", on_close)
    override(ha, "expect_states", on_expect)


async def run_service(
    settings: Settings,
    board: SimulatedHeishaMon,
    seconds: float,
    *,
    record: bool = False,
    on_cycle: Callable[[SimulatedHeishaMon], None] | None = None,
    ha_topics: Mapping[str, str] | None = None,
    ha_units: Mapping[str, str] | None = None,
) -> tuple[Service, Recording | None]:
    """Run the assembled service and the simulator's runner through an in-memory broker.

    Parameters
    ----------
    settings
        Service settings with a scaled clock (``clock_speed``, ``clock_start``).
    board
        The simulated HeishaMon.
    seconds
        Real seconds to run.
    record
        Tap the service (:func:`tap`).
    on_cycle
        Called after every board cycle (plant sampling).
    ha_topics
        Entity id per board topic: the service reads these devices through an
        in-memory Home Assistant (settings with HA configured) instead of MQTT.
    ha_units
        ``unit_of_measurement`` per entity.

    Returns
    -------
    tuple
        The stopped service and the recording (``None`` unless ``record``).
    """
    broker = MemoryBroker()
    home: MemoryHomeAssistant | None = None
    connector: Callable[[str], Any] | None = None
    if ha_topics is not None:
        holder: list[Callable[[], Instant]] = []
        home = MemoryHomeAssistant(lambda: holder[0]().wall.timestamp(), ha_units or {})
        connector = home.connect
    service = build_service(
        settings,
        mqtt_connect=lambda: IngestClient(broker),
        ha_connector=connector,
        command_connect=lambda: LinkClient(broker),
    )
    if ha_topics is not None:
        holder.append(service.runtime.clock)
    recording = tap(service) if record else None
    if on_cycle is not None:
        cycle = board.cycle

        def sampled() -> Any:
            """Run one board cycle, then report the board to ``on_cycle``."""
            out = cycle()
            on_cycle(board)
            return out

        override(board, "cycle", sampled)
    bridging = (
        asyncio.create_task(bridge(broker, home, ha_topics))
        if home is not None and ha_topics is not None
        else None
    )
    stop = asyncio.Event()
    service_task = asyncio.create_task(service.run(stop))
    await asyncio.sleep(0.2)
    config = runner.RunnerConfig(host="localhost", port=1883, speed=settings.clock_speed)
    sim_task = asyncio.create_task(
        runner.run(board, config, client_factory=functools.partial(SimClient, broker))
    )
    await asyncio.sleep(seconds)
    sim_task.cancel()
    stop.set()
    await asyncio.wait_for(service_task, 30)
    with contextlib.suppress(asyncio.CancelledError):
        await sim_task
    if bridging is not None:
        bridging.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bridging
    return service, recording


def replay(settings: Settings, recording: Recording, data_dir: Path) -> list[DecisionRow]:
    """Feed a recorded event log into a fresh stepped :class:`System` and return its decisions.

    Parameters
    ----------
    settings
        The recorded service's settings (the data directory is replaced).
    recording
        What :func:`tap` logged.
    data_dir
        Empty data directory of the replay.

    Returns
    -------
    list of DecisionRow
        The replay's decision rows, in tick order.
    """
    stepped = settings.model_copy(update={"data_dir": data_dir})
    first = recording.events[0].at if recording.events else None
    clock = ManualClock(first.wall.timestamp() if first else 0.0)
    published: list[tuple[str, str]] = []
    system = System(
        stepped, clock, lambda topic, payload, qos, retain: published.append((topic, payload))
    )
    ha: HaInput | None = None
    if stepped.ha_url is not None and stepped.ha_token is not None:
        ha = HaInput(stepped.ha_url, stepped.ha_token, stepped.ha_subscriptions, system.runtime)
    rows: list[DecisionRow] = []
    try:
        for event in recording.events:
            clock.set_instant(event.at)
            match event.kind:
                case "message":
                    item: InboundMessage = event.data
                    system.ingest.ingest(item)
                case "link":
                    source, up, confirmed = event.data
                    system.runtime.set_link(source, up=up, confirmed=confirmed)
                case "tick":
                    rows.append(system.tick(event.at))
                case "check":
                    system.check(event.at)
                case "adapter":
                    system.adapter_tick(event.at)
                case "published":
                    system.adapter.published(event.data, event.at)
                case "failed":
                    command, error = event.data
                    system.adapter.publish_failed(command, event.at, error)
                case "ha_open" | "ha_close" | "ha_expect" | "ha":
                    if ha is None:
                        raise ValueError("an HA event in a recording without HA settings")
                    _replay_ha(ha, event)
    finally:
        system.close()
    return rows


def _replay_ha(ha: HaInput, event: Event) -> None:
    """Apply a recorded HA event to the replay's HA input; check the expected request id."""
    match event.kind:
        case "ha_open":
            ha.open_session()
        case "ha_close":
            ha.close_session()
        case "ha_expect":
            expected = ha.expect_states()
            if expected != event.data:
                raise ValueError(f"get_states id {expected} replayed, {event.data} recorded")
        case _:
            ha.handle(event.data)


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """Agreement of a replay with the recorded run.

    Parameters
    ----------
    recorded, replayed
        Decision counts.
    identical
        Rows equal field by field.
    first_difference
        Description of the first differing row, if any.
    events
        Recorded events.
    """

    recorded: int
    replayed: int
    identical: int
    first_difference: str | None
    events: int

    @property
    def passed(self) -> bool:
        """Every decision identical."""
        return self.recorded > 0 and self.recorded == self.replayed == self.identical

    def to_json(self) -> dict[str, Any]:
        """Return the JSON form."""
        return {**dataclasses.asdict(self), "passed": self.passed}


def compare_rows(
    recorded: list[DecisionRow], replayed: list[DecisionRow], events: int
) -> ReplayResult:
    """Compare two decision sequences field by field."""
    identical = 0
    first: str | None = None
    for index, (a, b) in enumerate(zip(recorded, replayed, strict=False)):
        differing = [name for name in ROW_FIELDS if getattr(a, name) != getattr(b, name)]
        if not differing:
            identical += 1
        elif first is None:
            when = datetime.fromtimestamp(a.ts).isoformat()
            first = f"decision {index} at {when}: {', '.join(differing)} differ"
    if first is None and len(recorded) != len(replayed):
        first = f"{len(recorded)} recorded decisions, {len(replayed)} replayed"
    return ReplayResult(len(recorded), len(replayed), identical, first, events)

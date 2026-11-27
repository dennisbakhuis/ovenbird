"""Assemble and supervise the service.

The configuration store is opened first (:class:`~ovenbird.configstore.ConfigManager`):
everything is built from the effective settings (installation plus stored version).
One top-level :class:`asyncio.TaskGroup` runs every component under
:func:`supervise`, which restarts a failed component with backoff, and the HTTP
server. The components are the MQTT ingest, the history writer, the HA input (idle
until a URL and a token are configured; it follows every configuration change), the
control loop, the weather component (idle unless the forecast is opted
in), the learner hand-off (keeps the house-model learner's history export current,
:mod:`ovenbird.insight.house`), the learner runner (starts the learner as a low-priority child
process, :mod:`ovenbird.insight.learnrun`), the notifier and dead-man ping when configured and,
only when the publish guard
permits it, the command worker (the single publishing connection). Stopping (SIGTERM)
shuts HTTP down gracefully, cancels the components, flushes history and releases the data directory
lock.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import socket
import time
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from typing import Final

import uvicorn

from ovenbird.api.app import create_app
from ovenbird.api.ws import SNAPSHOT_INTERVAL_S, Broadcaster
from ovenbird.backoff import Backoff
from ovenbird.clock import Clock, Sleep, build_clock, sleeper, system_clock
from ovenbird.config import Settings
from ovenbird.configstore import ConfigManager
from ovenbird.control import (
    AdapterConfig,
    AlarmBoard,
    AlarmCode,
    CommandAdapter,
    CommandJournal,
    CommandLink,
    CommandWorker,
    ControlLoop,
    PublishGuard,
    controller_config,
)
from ovenbird.control.adapter import CommandSender
from ovenbird.control.envelope import EnvelopeWatch
from ovenbird.control.guard import ModeHold
from ovenbird.control.loop import alarm_row
from ovenbird.control.monitors import SafetyMonitor, monitor_config
from ovenbird.control.persist import load_state, restore_adapter
from ovenbird.ha import REFRESH_INTERVAL_S, Connector, HaInput
from ovenbird.history import HistoryWriter
from ovenbird.history.archive import AlarmHook, ConfigSource, MonthArchiver, clean_build_folders
from ovenbird.history.journal import latest_decision
from ovenbird.hotwater import dhw_installed
from ovenbird.insight.house import run_handoff
from ovenbird.insight.learnrun import LearnRunner
from ovenbird.instance import Endpoint, InstanceLock, probe_host
from ovenbird.mqtt import MqttIngest, SubscribeOnlyClient
from ovenbird.mqttsetup import MqttSetup
from ovenbird.notify.notifier import Notifier
from ovenbird.notify.transport import Transport
from ovenbird.pump.settings import PumpSettings
from ovenbird.runtime import Runtime
from ovenbird.signals import signal_candidates
from ovenbird.stove.request import load_request
from ovenbird.system.about import record_start
from ovenbird.system.facts import Facts
from ovenbird.trial.release import ReleaseManager
from ovenbird.trial.supervision import Supervision
from ovenbird.weather import WeatherProvider, WeatherService, build_provider
from ovenbird_core import StateStore
from ovenbird_core.control import Mode, OvenbirdController

LOGGER = logging.getLogger("ovenbird.service")
HISTORY_WATCH_INTERVAL_S: Final = 5.0
GRACEFUL_SHUTDOWN_S: Final = 5
WS_MAX_MESSAGE_BYTES: Final = 64 * 1024


class HistoryWriterStoppedError(RuntimeError):
    """The history writer thread ended while the service runs."""


@dataclass(frozen=True, slots=True)
class Component:
    """A long-running part of the service.

    Parameters
    ----------
    name
        Name used in logs and crash counters.
    run
        Coroutine function that runs until cancelled.
    """

    name: str
    run: Callable[[], Awaitable[None]]


async def supervise(component: Component, runtime: Runtime, backoff: Backoff | None = None) -> None:
    """Run ``component`` forever, restarting it with backoff whenever it fails or returns.

    Parameters
    ----------
    component
        The component.
    runtime
        Receives crash and recovery counts (they drive ``live``).
    backoff
        Restart delays.
    """
    delays = backoff or Backoff()
    while True:
        started = time.monotonic()
        try:
            await component.run()
            LOGGER.error("%s stopped unexpectedly; restarting", component.name)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("%s crashed; restarting", component.name)
        lasted = time.monotonic() - started
        if lasted >= delays.stable_after:
            runtime.record_recovery(component.name)
        runtime.record_crash(component.name)
        await asyncio.sleep(delays.next_delay(lasted))


async def watch_history(writer: HistoryWriter, interval: float = HISTORY_WATCH_INTERVAL_S) -> None:
    """Start the history writer thread and fail when it dies (the supervisor restarts it)."""
    writer.start()
    while True:
        await asyncio.sleep(interval)
        if not writer.is_alive():
            raise HistoryWriterStoppedError("history writer thread stopped")


class EmbeddedServer(uvicorn.Server):
    """Uvicorn server that leaves signal handling to the service and signals readiness.

    Parameters
    ----------
    config
        Uvicorn configuration.
    """

    def __init__(self, config: uvicorn.Config) -> None:
        super().__init__(config)
        self.ready = asyncio.Event()

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        """Start listening and set :attr:`ready`."""
        await super().startup(sockets)
        if self.started:
            self.ready.set()

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        """Install no signal handlers."""
        yield

    def bound_port(self) -> int | None:
        """Return the port actually bound (useful with port 0)."""
        for server in self.servers:
            for sock in server.sockets:
                return int(sock.getsockname()[1])
        return None


def follow_retention(writer: HistoryWriter) -> Callable[[Settings], None]:
    """Return a reconfigure hook that hands changed retention and archive settings to the writer."""

    def follow(settings: Settings) -> None:
        writer.set_retention(settings.history_retention(), settings.history_journal_days())
        if writer.archiver is not None:
            writer.archiver.configure(
                enabled=settings.history_archive_enabled, timezone=settings.control_timezone
            )

    return follow


def archive_alarms(board: AlarmBoard, clock: Clock) -> AlarmHook:
    """Return the hook that raises and clears the archive's alarms on ``board``."""

    def hook(code: str, active: bool, text: str) -> None:
        alarm = AlarmCode(code)
        if active:
            board.raise_alarm(alarm, text, clock())
        else:
            board.clear(alarm, clock(), text)

    return hook


def build_writer[W: HistoryWriter](
    settings: Settings,
    writer_type: type[W],
    *,
    wall: Callable[[], float] | None = None,
    queue_size: int | None = None,
    snapshots: bool = True,
    archive_config: ConfigSource | None = None,
    archive: bool = False,
) -> W:
    """Build the history writer the settings describe (not started).

    Parameters
    ----------
    settings
        Validated settings (path, retention, queue size, free-space floor, snapshots).
    writer_type
        :class:`~ovenbird.history.HistoryWriter` or a subclass taking its arguments.
    wall
        Wall-clock source for retention; the system clock when omitted.
    queue_size
        Queue capacity instead of ``history_queue_size``.
    snapshots
        Write backup snapshots when the settings ask for them.
    archive_config
        Writes ``config.json`` of an archived month.
    archive
        Keep the monthly archive (switched on and off by ``history_archive_enabled``).

    Returns
    -------
    HistoryWriter
        The writer.
    """
    snapshot_hours = settings.history_snapshot_hours if snapshots else None
    min_free = settings.history_min_free_mb * 1024 * 1024
    archiver = (
        MonthArchiver(
            settings.history_path,
            settings.archive_dir,
            timezone=settings.control_timezone,
            enabled=settings.history_archive_enabled,
            config_source=archive_config,
            min_free_bytes=min_free,
        )
        if archive
        else None
    )
    return writer_type(
        settings.history_path,
        settings.history_retention(),
        queue_size=settings.history_queue_size if queue_size is None else queue_size,
        min_free_bytes=min_free,
        snapshot_path=settings.snapshot_path if snapshot_hours is not None else None,
        snapshot_interval=(snapshot_hours or 0.0) * 3600.0,
        journal_days=settings.history_journal_days(),
        wall=time.time if wall is None else wall,
        archiver=archiver,
    )


def build_runtime(settings: Settings, clock: Clock, writer: HistoryWriter | None) -> Runtime:
    """Build the shared runtime: state store with the settings' staleness policy, clock, history."""
    return Runtime(
        StateStore(settings.staleness_policy()),
        clock=clock,
        history=writer,
        ha_enabled=settings.ha_enabled,
    )


@dataclass
class Service:
    """The assembled service; build with :func:`build_service`.

    Parameters
    ----------
    settings
        Settings.
    runtime
        Shared state.
    writer
        History writer.
    components
        Supervised components.
    server
        HTTP server.
    lock
        Data directory lock.
    control
        Control loop.
    worker
        Command worker; ``None`` unless publishing is permitted.
    config
        Configuration manager (store, effective settings, modes).
    """

    settings: Settings
    runtime: Runtime
    writer: HistoryWriter
    components: list[Component]
    server: EmbeddedServer
    lock: InstanceLock
    control: ControlLoop
    worker: CommandWorker | None = None
    config: ConfigManager | None = None

    async def run(self, stop: asyncio.Event) -> None:
        """Run until ``stop`` is set, then shut down cleanly.

        Once the data directory lock is held, the archive build folders a crash left
        behind are removed (:func:`~ovenbird.history.archive.clean_build_folders`).

        Raises
        ------
        RuntimeError
            When the HTTP server cannot start or stops on its own.
        """
        self.lock.acquire()
        try:
            clean_build_folders(self.settings.data_dir)
            async with asyncio.TaskGroup() as group:
                tasks = [
                    group.create_task(supervise(component, self.runtime), name=component.name)
                    for component in self.components
                ]
                http = group.create_task(self._serve_http(stop), name="http")
                await stop.wait()
                LOGGER.info("ovenbird stopping")
                self.server.should_exit = True
                await http
                for task in tasks:
                    task.cancel()
        finally:
            self.writer.stop()
            if self.config is not None:
                self.config.close()
            self.lock.release()
            LOGGER.info("ovenbird stopped")

    async def _serve_http(self, stop: asyncio.Event) -> None:
        recorder = asyncio.create_task(self._record_endpoint())
        try:
            await self.server.serve()
        except SystemExit as exc:
            raise RuntimeError("HTTP server failed to start") from exc
        finally:
            recorder.cancel()
        if not stop.is_set():
            raise RuntimeError("HTTP server stopped unexpectedly")

    async def _record_endpoint(self) -> None:
        await self.server.ready.wait()
        port = self.server.bound_port()
        if port is None:
            return
        host = probe_host(self.settings.http_host)
        self.lock.record_endpoint(Endpoint(host, port))
        LOGGER.info("HTTP listening on %s:%d", self.settings.http_host, port)


def build_control(
    settings: Settings,
    runtime: Runtime,
    writer: HistoryWriter | None,
    *,
    sleep: Sleep,
    broadcaster: Broadcaster | None = None,
    command_connect: Callable[[], CommandSender] | None = None,
    hold: ModeHold | None = None,
    config_version: int | None = None,
    facts: Facts | None = None,
) -> tuple[ControlLoop, CommandWorker | None]:
    """Build the control loop and, only when the publish guard permits it, the command worker.

    Parameters
    ----------
    settings
        Validated settings.
    runtime
        Shared state.
    writer
        Receives decision and command rows.
    sleep
        Sleeps on the service clock.
    broadcaster
        Pushes decisions to WebSocket clients.
    command_connect
        Link factory for the worker (tests pass a fake); a :class:`CommandLink`
        otherwise.
    hold
        Runtime shadow reasons (pause, configuration reset) for the guard.
    config_version
        Configuration version the settings come from.
    facts
        Persistent facts (go-live snapshot, envelope evidence); in memory when
        omitted.

    Returns
    -------
    tuple
        The control loop (its safety monitor in ``loop.safety``, the release
        manager in ``loop.release``, the envelope watch in ``loop.envelope``) and
        the command worker (``None`` when publishing is refused).
    """
    config = controller_config(settings)
    guard = PublishGuard.from_settings(settings, hold)
    alarms = AlarmBoard(
        journal=(lambda event: writer.offer_alarm(alarm_row(event))) if writer is not None else None
    )
    adapter: CommandAdapter | None = None
    worker: CommandWorker | None = None
    now = runtime.clock()
    if guard.installed:
        adapter = CommandAdapter(
            AdapterConfig.from_settings(settings, config.safety),
            guard,
            alarms,
            journal=CommandJournal(writer),
        )
        adapter.restore(restore_adapter(settings.history_path, now), now)
        topics = adapter.config.topics()
        connect = command_connect or (lambda: CommandLink(settings, guard, topics))
        worker = CommandWorker(adapter, runtime, connect, sleep)
        LOGGER.warning(
            "COMMANDS ENABLED: ovenbird publishes %s to %s:%d",
            ", ".join(sorted(topics)),
            settings.mqtt_host,
            settings.mqtt_port,
        )
    else:
        LOGGER.info("publishing disabled: %s", "; ".join(guard.refusals()))
    loop = ControlLoop(
        runtime,
        OvenbirdController(config),
        mode=Mode(settings.control_mode),
        guard=guard,
        alarms=alarms,
        adapter=adapter,
        sink=writer,
        room_signal=settings.control_room_signal,
        room_profile=config.room,
        interval_s=settings.control_interval_s,
        sleep=sleep,
        on_decision=broadcaster.publish_decision if broadcaster is not None else None,
        state_sink=writer.offer_state if writer is not None else None,
        initial_state=load_state(settings.history_path, now, settings.control_state_max_age_s),
        config_version=config_version,
        stove_request=load_request(settings.history_path, now),
    )
    loop.safety = SafetyMonitor(
        monitor_config(settings, config.safety.max_supply_c),
        alarms,
        runtime,
        adapter=adapter,
        desired=lambda: loop.desired_setpoint,
        interval_s=settings.safety_interval_s,
        sleep=sleep,
    )
    runtime.defrost = loop.safety.defrost_state
    store = facts if facts is not None else Facts()
    latest = latest_decision(settings.history_path)
    loop.release = ReleaseManager(
        loop,
        store,
        None if latest is None else latest.mode,
        limits=AdapterConfig.from_settings(settings, config.safety),
        register=settings.command_setpoint_register,
    )
    loop.envelope = EnvelopeWatch(loop, store, installed=settings.envelope_rule_installed)
    runtime.alarm_level = "starting"
    return loop, worker


def ha_follower(ha: HaInput, runtime: Runtime) -> Callable[[Settings], None]:
    """Return the hook that makes the HA input follow new settings (connection, signals)."""

    def hook(settings: Settings) -> None:
        runtime.ha_enabled = settings.ha_enabled
        ha.configure(
            settings.ha_url,
            settings.ha_token,
            settings.ha_subscriptions,
            attributes=settings.ha_attributes,
            temperature=settings.ha_temperature_signals,
        )

    return hook


def build_service(
    settings: Settings,
    *,
    mqtt_connect: Callable[[], SubscribeOnlyClient] | None = None,
    ha_connector: Connector | None = None,
    snapshot_interval: float = SNAPSHOT_INTERVAL_S,
    command_connect: Callable[[], CommandSender] | None = None,
    weather_provider: WeatherProvider | None = None,
    notify_transport: Transport | None = None,
) -> Service:
    """Wire settings, state, inputs, history and HTTP together.

    Parameters
    ----------
    settings
        Validated settings.
    mqtt_connect
        Client factory for the MQTT ingest (tests pass a fake).
    ha_connector
        WebSocket connector for the HA input (tests pass a fake server's).
    snapshot_interval
        Minimum seconds between WebSocket snapshot pushes.
    command_connect
        Link factory of the command worker (tests pass a fake).
    weather_provider
        Forecast provider (tests pass a fake); simulated in simulation mode,
        Open-Meteo otherwise.
    notify_transport
        HTTP transport of the notifier (tests pass a fake); the stdlib one otherwise.

    Returns
    -------
    Service
        Ready to :meth:`Service.run`.
    """
    clock = build_clock(settings.clock_speed, settings.clock_start)
    manager = ConfigManager.open(settings, clock)
    settings = manager.settings
    facts = Facts(manager.store)
    started = clock()
    starts = record_start(facts, started)
    writer = build_writer(
        settings,
        HistoryWriter,
        wall=None if clock is system_clock else lambda: clock().wall.timestamp(),
        archive=True,
        archive_config=manager.archive_config,
    )
    runtime = build_runtime(settings, clock, writer)
    manager.dhw_installed = lambda: dhw_installed(runtime.store, runtime.clock())
    mqtt = MqttIngest(settings, runtime, connect=mqtt_connect)
    components = [
        Component("mqtt", mqtt.run),
        Component("history", functools.partial(watch_history, writer)),
    ]
    ha = HaInput(
        settings.ha_url,
        settings.ha_token,
        settings.ha_subscriptions,
        runtime,
        attributes=settings.ha_attributes,
        temperature=settings.ha_temperature_signals,
        connector=ha_connector,
        refresh_interval=REFRESH_INTERVAL_S / settings.clock_speed,
    )
    components.append(Component("ha", ha.run))
    broadcaster = Broadcaster(runtime, snapshot_interval=snapshot_interval)
    control, worker = build_control(
        settings,
        runtime,
        writer,
        sleep=sleeper(clock),
        broadcaster=broadcaster,
        command_connect=command_connect,
        hold=manager.hold,
        config_version=manager.version,
        facts=facts,
    )
    if writer.archiver is not None:
        writer.archiver.alarm = archive_alarms(control.alarms, clock)
    supervision = Supervision(
        runtime, lambda: manager.settings, control, manager, None, facts, started, starts
    )
    notifier = Notifier(
        settings,
        clock,
        facts,
        transport=notify_transport,
        healthy=supervision.healthy_reason,
        sleep=sleeper(clock),
    )
    supervision.notifier = notifier
    notifier.attach(control.alarms)
    manager.audit_listeners.append(notifier.on_audit)
    manager.attach(control, control.alarms)
    if control.release is not None:
        control.release.config = manager
    manager.on_applied.append(broadcaster.publish_config)
    follow = ha_follower(ha, runtime)
    control.reconfigure_hooks.append(follow)
    control.reconfigure_hooks.append(follow_retention(writer))
    manager.connection_listeners.append(follow)
    manager.mqtt_listeners.append(mqtt.reconfigure)
    control.reconfigure_hooks.append(mqtt.reconfigure)
    components.append(Component("control", control.run))
    if control.safety is not None:
        components.append(Component("safety", control.safety.run))
    weather = WeatherService(
        settings,
        clock,
        weather_provider or build_provider(settings),
        sink=writer,
        home=lambda: ha.home,
        sleep=sleeper(clock),
        history_path=settings.history_path,
    )
    runtime.weather_check = weather.status
    control.reconfigure_hooks.append(weather.reconfigure)
    components.append(Component("weather", weather.run))
    components.append(
        Component("learner", functools.partial(run_handoff, lambda: manager.settings))
    )
    learn_runner = LearnRunner(lambda: manager.settings, facts)
    components.append(Component("learner-run", learn_runner.run))
    mqtt_setup = MqttSetup(manager, mqtt, runtime, lambda: control.guard.installed, control.alarms)
    components.append(Component("mqtt-trial", mqtt_setup.run))
    if worker is not None:
        components.append(Component("commands", worker.run))
    if notifier.configured:
        components.append(Component("notify", notifier.run))
    if notifier.deadman_configured:
        components.append(Component("deadman", notifier.run_deadman))
    pumps = PumpSettings(runtime, control.guard, control.adapter, manager, settings.history_path)
    app = create_app(
        runtime,
        settings,
        broadcaster=broadcaster,
        control=control,
        config=manager,
        pumps=pumps,
        weather=weather,
        signals=lambda: signal_candidates(manager.settings, runtime, ha),
        supervision=supervision,
        writer=writer,
        mqtt=mqtt_setup,
        learn=learn_runner,
    )
    config = uvicorn.Config(
        app,
        host=settings.http_host,
        port=settings.http_port,
        log_config=None,
        access_log=False,
        lifespan="on",
        proxy_headers=False,
        server_header=False,
        ws_max_size=WS_MAX_MESSAGE_BYTES,
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_S,
    )
    return Service(
        settings,
        runtime,
        writer,
        components,
        EmbeddedServer(config),
        InstanceLock(settings.data_dir),
        control,
        worker,
        manager,
    )

"""End to end: the controller drives the simulated HeishaMon (plant model) in closed loop.

``test_closed_loop_hours`` steps everything deterministically on one simulated clock:
the board's publications go through the real MQTT ingest, the control loop ticks
every 60 s, the adapter every 5 s, and released commands are delivered to the board.

``test_service_against_the_simulator`` runs the assembled service (ingest, history,
control loop, command worker) and the simulator's MQTT runner concurrently through an
in-memory broker on a 120x clock. ``test_service_against_a_real_broker`` does the same
through Mosquitto when one is available (``OVENBIRD_TEST_MQTT=host:port`` or a
``mosquitto`` binary on ``PATH``).
"""

from __future__ import annotations

import asyncio
import functools
import os
import secrets
import shutil
import socket
import subprocess
import time
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self

import aiomqtt
import pytest

from ovenbird.config import Settings
from ovenbird.control import CommandAdapter, ControlLoop
from ovenbird.control.adapter import Command
from ovenbird.control.alarms import AlarmCode
from ovenbird.history import query_commands, query_decisions
from ovenbird.mqtt import InboundMessage, MqttIngest
from ovenbird.runtime import Runtime
from ovenbird.service import build_control, build_service
from ovenbird.testing import FakeClock, inbound
from ovenbird_core import PUMP_SETTINGS, Instant, PumpSetting, SignalView, StateStore

pytestmark = pytest.mark.slow

board_module = pytest.importorskip("ovenbird_sim.heishamon.board")
weather_module = pytest.importorskip("ovenbird_sim.heishamon.weather")
reference = pytest.importorskip("ovenbird_sim.heishamon.reference")
registers_module = pytest.importorskip("ovenbird_sim.heishamon.registers")
runner_module = pytest.importorskip("ovenbird_sim.heishamon.runner")

START = datetime(2025, 11, 10, 6, tzinfo=UTC)
ROOM_TOPIC = "sim/room_temperature"
COMFORT_C = 21.0
IDLE_DUTY = 102


def sim_settings(make_settings: Callable[..., Settings], **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "mqtt_host": "mosquitto",
        "control_mode": "auto",
        "allow_commands": True,
        "command_brokers": ("mosquitto",),
        "simulation": True,
        "control_room_signal": "room_temperature",
        "control_comfort_c": COMFORT_C,
        "control_pump_duty": True,
        "mqtt_inputs": [{"topic": ROOM_TOPIC, "signal": "room_temperature", "unit": "°C"}],
    }
    values.update(overrides)
    return make_settings(**values)


def make_board(base: str = "panasonic_heat_pump", room_c: float = 21.0) -> Any:
    """Return the board on the example house, starting on the idle pump duty.

    The example 5 kW pump modulates without a stop through the cold week, so the
    heating duty is only commanded when the board starts from the idle one.
    """
    weather = weather_module.ColdWeek(START)
    state = board_module.preroll(reference.REFERENCE_PARAMS, weather, START, 33, room_c=room_c)
    return board_module.SimulatedHeishaMon(
        reference.REFERENCE_PARAMS,
        weather,
        START,
        registers=registers_module.Registers(
            direct_setpoint=33, curve_target_high=33, max_pump_duty=IDLE_DUTY
        ),
        config=board_module.BoardConfig(base=base, room_topic=ROOM_TOPIC),
        state=state,
    )


def view_at(store: StateStore, at: Instant, signal: str) -> SignalView | None:
    return store.view(signal, at)


@dataclass
class Run:
    rooms: list[float]
    targets: list[int]
    sent: list[Command]


def run_closed_loop(
    loop: ControlLoop, adapter: CommandAdapter, ingest: MqttIngest, clock: FakeClock, board: Any
) -> Run:
    run = Run([], [], [])
    hours = 8
    for cycle in range(hours * 720):
        clock.t = START.timestamp() + (cycle + 1) * 5.0
        for pub in board.cycle():
            ingest.ingest(inbound(pub.topic, pub.payload))
        now = clock()
        store = ingest.runtime.store
        command = adapter.tick(
            now, functools.partial(view_at, store, now), store.heishamon_status(now)
        )
        if command is not None:
            assert command.topic in adapter.config.topics()
            board.receive(command.topic, command.payload)
            adapter.published(command, now)
            run.sent.append(command)
        if cycle % 12 == 11:
            loop.tick()
            run.rooms.append(board.state.t_air)
            run.targets.append(board.water_target)
    return run


def test_closed_loop_hours(make_settings: Callable[..., Settings]) -> None:
    settings = sim_settings(make_settings)
    clock = FakeClock(START.timestamp())
    runtime = Runtime(clock=clock)
    ingest = MqttIngest(settings, runtime)

    async def no_sleep(_: float) -> None:
        return None

    loop, worker = build_control(settings, runtime, None, sleep=no_sleep)
    assert worker is not None
    adapter = loop.adapter
    assert adapter is not None
    board = make_board()
    run = run_closed_loop(loop, adapter, ingest, clock, board)

    assert loop.ticks == 8 * 60
    assert loop.latest is not None
    assert loop.latest["mode"] == "auto"
    counters = adapter.counters
    assert counters.sent >= 2
    assert counters.failed == 0
    assert counters.foreign == 0
    assert counters.retried == 0
    assert counters.verified >= counters.sent - 1
    assert loop.alarms.active() == ()
    assert board.stats.commands_applied == counters.sent
    assert board.stats.commands_ignored == 0
    kinds = {command.kind.value for command in run.sent}
    assert "water_setpoint" in kinds
    assert "max_pump_duty" in kinds
    assert all(20 <= t <= 40 for t in run.targets)
    assert board.registers.heating_mode == 1
    assert min(run.rooms) > COMFORT_C - 1.0
    assert max(run.rooms) < COMFORT_C + 1.0
    assert counters.sent < 8 * 30


def test_shadow_closed_loop_sends_nothing(make_settings: Callable[..., Settings]) -> None:
    settings = sim_settings(make_settings, control_mode="shadow")
    clock = FakeClock(START.timestamp())
    runtime = Runtime(clock=clock)
    ingest = MqttIngest(settings, runtime)

    async def no_sleep(_: float) -> None:
        return None

    loop, worker = build_control(settings, runtime, None, sleep=no_sleep)
    assert worker is None
    assert loop.adapter is None
    board = make_board()
    for cycle in range(720):
        clock.t = START.timestamp() + (cycle + 1) * 5.0
        for pub in board.cycle():
            ingest.ingest(inbound(pub.topic, pub.payload))
        if cycle % 12 == 11:
            loop.tick()
    assert board.stats.commands_received == 0
    assert loop.latest is not None
    assert loop.latest["commands"] == []


class Broker:
    """In-memory MQTT broker: retained store, wildcard subscriptions, no QoS."""

    def __init__(self) -> None:
        self.retained: dict[str, str] = {}
        self.subscribers: list[tuple[str, asyncio.Queue[tuple[str, str, bool]]]] = []
        self.log: list[tuple[str, str, bool]] = []

    def publish(self, topic: str, payload: str, retain: bool) -> None:
        self.log.append((topic, payload, retain))
        if retain:
            self.retained[topic] = payload
        for pattern, queue in self.subscribers:
            if aiomqtt.Topic(topic).matches(pattern):
                queue.put_nowait((topic, payload, False))

    def subscribe(self, pattern: str, queue: asyncio.Queue[tuple[str, str, bool]]) -> None:
        self.subscribers.append((pattern, queue))
        for topic, payload in self.retained.items():
            if aiomqtt.Topic(topic).matches(pattern):
                queue.put_nowait((topic, payload, True))


class IngestClient:
    def __init__(self, broker: Broker) -> None:
        self.broker = broker
        self.queue: asyncio.Queue[tuple[str, str, bool]] = asyncio.Queue()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def subscribe(self, topic: str) -> None:
        self.broker.subscribe(topic, self.queue)

    async def messages(self) -> AsyncIterator[InboundMessage]:
        while True:
            topic, payload, retained = await self.queue.get()
            yield InboundMessage(topic, payload.encode(), retained)


class Link:
    def __init__(self, broker: Broker) -> None:
        self.broker = broker

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def send(self, command: Command) -> None:
        self.broker.publish(command.topic, command.payload, False)


class Delivery:
    def __init__(self, topic: str, payload: str, retain: bool) -> None:
        self.topic = aiomqtt.Topic(topic)
        self.payload = payload.encode()
        self.retain = retain


class SimClient:
    def __init__(self, broker: Broker, **kwargs: Any) -> None:
        self.broker = broker
        self.kwargs = kwargs
        self.queue: asyncio.Queue[tuple[str, str, bool]] = asyncio.Queue()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        will = self.kwargs["will"]
        self.broker.publish(will.topic, will.payload, will.retain)

    async def subscribe(self, topic: str, qos: int = 0) -> None:
        self.broker.subscribe(topic, self.queue)

    async def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False) -> None:
        self.broker.publish(topic, payload, retain)

    @property
    def messages(self) -> Any:
        async def stream() -> Any:
            while True:
                yield Delivery(*(await self.queue.get()))

        return stream()


async def run_service_with_simulator(
    settings: Settings,
    board: Any,
    speed: float,
    seconds: float,
    *,
    mqtt_connect: Callable[[], Any] | None = None,
    command_connect: Callable[[], Any] | None = None,
    sim_factory: Callable[..., Any] | None = None,
    sim_host: str = "localhost",
    sim_port: int = 1883,
) -> Any:
    service = build_service(settings, mqtt_connect=mqtt_connect, command_connect=command_connect)
    stop = asyncio.Event()
    service_task = asyncio.create_task(service.run(stop))
    await asyncio.sleep(0.2)
    config = runner_module.RunnerConfig(host=sim_host, port=sim_port, speed=speed)
    kwargs = {} if sim_factory is None else {"client_factory": sim_factory}
    sim_task = asyncio.create_task(runner_module.run(board, config, **kwargs))
    await asyncio.sleep(seconds)
    sim_task.cancel()
    stop.set()
    await asyncio.wait_for(service_task, 15)
    with pytest.raises(asyncio.CancelledError):
        await sim_task
    return service


def check_service_run(service: Any, board: Any) -> None:
    decisions = query_decisions(service.settings.history_path, 0.0, 4e9, 5000)
    commands = query_commands(service.settings.history_path, 0.0, 4e9, 5000)
    assert len(decisions) >= 5
    assert {d.mode for d in decisions} == {"auto"}
    controlled = [d for d in decisions if d.ladder == "schedule_curve_feedback"]
    assert controlled
    statuses = [c.status for c in commands]
    assert "sent" in statuses
    assert "verified" in statuses
    assert "failed" not in statuses
    assert board.stats.commands_applied >= statuses.count("verified")
    assert service.control.alarms.active() == ()


def test_a_simulated_clock_also_drives_history_retention_and_the_archive(
    make_settings: Callable[..., Settings],
) -> None:
    settings = sim_settings(
        make_settings, clock_speed=120.0, clock_start=START, history_snapshot_hours=None
    )
    service = build_service(settings)
    assert abs(service.writer._wall() - START.timestamp()) < 3600


def test_the_real_clock_drives_history_retention_in_production(
    make_settings: Callable[..., Settings],
) -> None:
    service = build_service(make_settings())
    assert abs(service.writer._wall() - time.time()) < 60


async def test_service_against_the_simulator(make_settings: Callable[..., Settings]) -> None:
    broker = Broker()
    settings = sim_settings(
        make_settings, clock_speed=120.0, clock_start=START, history_snapshot_hours=None
    )
    board = make_board()
    service = await run_service_with_simulator(
        settings,
        board,
        speed=120.0,
        seconds=6.0,
        mqtt_connect=lambda: IngestClient(broker),
        command_connect=lambda: Link(broker),
        sim_factory=lambda **kwargs: SimClient(broker, **kwargs),
    )
    check_service_run(service, board)
    commands_on_broker = [t for t, _, _ in broker.log if "/commands/" in t]
    assert commands_on_broker
    assert not any(retain for t, _, retain in broker.log if "/commands/" in t)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def real_broker(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, int]]:
    configured = os.environ.get("OVENBIRD_TEST_MQTT")
    if configured:
        host, _, raw_port = configured.rpartition(":")
        yield host or "localhost", int(raw_port)
        return
    binary = shutil.which("mosquitto")
    if binary is None:
        pytest.skip("no mosquitto binary on PATH and OVENBIRD_TEST_MQTT unset")
    port = _free_port()
    conf = tmp_path_factory.mktemp("mosquitto") / "mosquitto.conf"
    conf.write_text(f"listener {port} 127.0.0.1\nallow_anonymous true\n", encoding="utf-8")
    process = subprocess.Popen([binary, "-c", str(conf)])  # noqa: S603
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.05)
    yield "127.0.0.1", port
    process.terminate()
    process.wait(5)


async def test_service_against_a_real_broker(
    make_settings: Callable[..., Settings], real_broker: tuple[str, int]
) -> None:
    host, port = real_broker
    if host.strip().lower() not in runner_module.LOCAL_HOSTS:
        pytest.skip("the simulator only connects to local brokers")
    base = f"ovenbird_e2e_{secrets.token_hex(3)}"
    settings = sim_settings(
        make_settings,
        mqtt_host=host,
        mqtt_port=port,
        command_brokers=(f"{host}:{port}",),
        heishamon_base=base,
        clock_speed=60.0,
        clock_start=START,
        history_snapshot_hours=None,
        mqtt_inputs=[{"topic": f"{base}/room", "signal": "room_temperature", "unit": "°C"}],
    )
    board = make_board(base)
    board.config = board_module.BoardConfig(base=base, room_topic=f"{base}/room")
    service = await run_service_with_simulator(
        settings, board, speed=60.0, seconds=8.0, sim_host=host, sim_port=port
    )
    check_service_run(service, board)


INJECT = "heishamon_sim/inject"


class SafetyRig:
    def __init__(self, make_settings: Callable[..., Settings]) -> None:
        self.settings = sim_settings(
            make_settings, control_comfort_c=21.0, control_min_setpoint_c=24.0
        )
        self.clock = FakeClock(START.timestamp())
        self.runtime = Runtime(clock=self.clock)
        self.ingest = MqttIngest(self.settings, self.runtime)

        async def no_sleep(_: float) -> None:
            return None

        self.loop, _ = build_control(self.settings, self.runtime, None, sleep=no_sleep)
        adapter = self.loop.adapter
        monitor = self.loop.safety
        assert adapter is not None
        assert monitor is not None
        self.adapter = adapter
        self.monitor = monitor
        self.board = make_board(room_c=21.0)
        self.board.config = board_module.BoardConfig(room_topic=ROOM_TOPIC, inject_prefix=INJECT)
        self.sent: list[Command] = []
        self.cycle = 0

    def run(self, cycles: int) -> None:
        for _ in range(cycles):
            self.cycle += 1
            self.clock.t = START.timestamp() + self.cycle * 5.0
            for pub in self.board.cycle():
                self.ingest.ingest(inbound(pub.topic, pub.payload))
            now = self.clock()
            store = self.runtime.store
            command = self.adapter.tick(
                now, functools.partial(view_at, store, now), store.heishamon_status(now)
            )
            if command is not None:
                self.board.receive(command.topic, command.payload)
                self.adapter.published(command, now)
                self.sent.append(command)
            self.monitor.check(now)
            if self.cycle % 12 == 0:
                self.loop.tick(now)

    def active(self) -> set[str]:
        return {alarm.code.value for alarm in self.loop.alarms.active()}


def test_safety_injections_against_the_simulator(make_settings: Callable[..., Settings]) -> None:
    rig = SafetyRig(make_settings)
    rig.run(720)
    assert rig.active() == set()
    assert rig.runtime.health()["checks"]["alarms"] == "ok"
    assert rig.adapter.counters.verified >= 1

    base = rig.board.config.base
    rig.board.receive(f"{base}/commands/SetCurves", '{"zone1":{"heat":{"target":{"high":300}}}}')
    rig.run(1)
    assert rig.board.registers.direct_setpoint == 44
    assert "setpoint_above_max" in rig.active()
    assert rig.runtime.health()["ready"] is False
    corrective = [c for c in rig.sent if c.reason == "safety_correction"]
    assert len(corrective) == 1
    assert 25 <= corrective[0].value <= 40
    rig.run(6)
    assert rig.board.registers.direct_setpoint == corrective[0].value
    assert rig.board.water_target <= 40
    assert "setpoint_above_max" not in rig.active()
    assert "foreign_writer" in rig.active()
    assert rig.adapter.hold_reason == "foreign writer"

    held = rig.adapter.release_hold(rig.clock(), "test")
    assert held is not None
    rig.run(120)
    assert "foreign_writer" not in rig.active()

    rig.board.receive(f"{INJECT}/main/Pump_Flow", "3.00")
    assert rig.board.state.running
    rig.run(30)
    assert "low_flow" in rig.active()
    assert AlarmCode.LOW_FLOW in rig.adapter.safety_hold
    assert rig.runtime.health()["checks"]["alarms"] == "critical"
    rig.board.receive(f"{INJECT}/main/Pump_Flow", "")
    rig.run(2)
    assert "low_flow" not in rig.active()
    assert rig.adapter.safety_hold == frozenset()

    rig.board.receive(f"{INJECT}/main/Error", "H62")
    rig.run(1)
    assert "pump_error" in rig.active()
    assert "H62" in next(
        a.message for a in rig.loop.alarms.active() if a.code.value == "pump_error"
    )
    rig.board.receive(f"{INJECT}/main/Error", "")
    rig.run(1)
    assert rig.active() == set()
    assert rig.runtime.health()["checks"]["alarms"] == "ok"
    events = [(e.code, e.event.value) for e in rig.loop.alarms.history]
    for code in ("setpoint_above_max", "low_flow", "pump_error", "foreign_writer"):
        assert (code, "raised") in events
        assert (code, "cleared") in events


def test_pump_settings_against_the_simulator(make_settings: Callable[..., Settings]) -> None:
    rig = SafetyRig(make_settings)
    rig.run(240)
    store = rig.runtime.store
    base = rig.board.config.base
    writes = [
        (PumpSetting.HEAT_DELTA, 6),
        (PumpSetting.PUMP_FLOWRATE_MODE, 0),
        (PumpSetting.HEATING_OFF_OUTDOOR, 25),
    ]
    for setting, value in writes:
        spec = PUMP_SETTINGS[setting]
        now = rig.clock()
        reported = store.view(spec.signal, now)
        assert reported is not None
        rig.adapter.request_setting(
            setting,
            value,
            reported.value,
            "admin from test",
            now,
            functools.partial(view_at, store, now),
        )
        rig.run(12)
        sent = [c for c in rig.sent if c.kind is setting]
        assert [(c.topic, c.payload) for c in sent] == [
            (f"{base}/commands/{spec.command}", str(value))
        ]
        view = store.view(spec.signal, rig.clock())
        assert view is not None
        assert view.value == value
        write = rig.adapter.operator_writes[setting]
        assert write.status.value == "verified"
    registers = rig.board.registers
    assert (registers.heat_delta, registers.pump_flowrate_mode, registers.heating_off_outdoor) == (
        6,
        0,
        25,
    )
    assert "pump_setting_changed" not in rig.active()
    rig.board.receive(f"{INJECT}/register/heat_delta", "8")
    rig.run(2)
    assert "pump_setting_changed" in rig.active()
    assert rig.adapter.hold_reason is None

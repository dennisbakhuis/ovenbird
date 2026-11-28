r"""B1: the whole service in closed loop with the simulated plant, stepped on one clock.

Every 5 s cycle the simulated HeishaMon advances the fitted plant and publishes what
the firmware would; the publications reach the service's real MQTT ingest through a
broker stand-in (retained store, connection state), the room sensor reaches it
through a fake Home Assistant and the service's real HA input, the command worker
steps once (adapter tick, publish through the real command link), the safety
monitors run, and every 12th cycle the control loop ticks. History, alarms and
persistence are the service's own. Every decision, command event and publish is
checked against the invariants of :mod:`ovenbird_harness.invariants`; any violation
fails the run.

Examples
--------
The recorded span with the install profile of the local settings (plant parameters,
weather and HA history from ``capture/captures``, which is local and git-ignored)::

    uv run python -m ovenbird_harness.fullrun

The same with the fault scenarios::

    uv run python -m ovenbird_harness.fullrun --faults
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import aiomqtt

from ovenbird.control import controller_config
from ovenbird.history.journal import AlarmRow, CommandRow, DecisionRow, StateRow
from ovenbird.mqtt import subscriptions
from ovenbird_core import Instant
from ovenbird_harness.clock import ManualClock
from ovenbird_harness.faults import SCENARIOS, Scheduler
from ovenbird_harness.homeassistant import FakeHomeAssistant, RoomFeed, room_feed
from ovenbird_harness.invariants import InvariantChecker, PlantReading
from ovenbird_harness.kpi import Kpis, PlantSample
from ovenbird_harness.report import write_report
from ovenbird_harness.settings import (
    EXAMPLE_COMFORT_C,
    EXAMPLE_CROSSCHECK,
    EXAMPLE_MIN_SETPOINT_C,
    HUMIDITY_ENTITY,
    MQTT_ROOM_TOPIC,
    ROOM_ENTITY,
    Profile,
    harness_settings,
)
from ovenbird_harness.system import HarnessWriter, System
from ovenbird_sim import local
from ovenbird_sim.heishamon.__main__ import build_board, parse_start
from ovenbird_sim.heishamon.board import DEFAULT_BASE, Publication, SimulatedHeishaMon
from ovenbird_sim.heishamon.reference import PLANT_ENV, plant_from_environment

LOGGER = logging.getLogger("ovenbird_harness.fullrun")
CAPTURES: Final = Path("capture/captures")
FITTED_PARAMS: Final = CAPTURES / "models" / "plant_params.json"
DEFAULT_WEATHER: Final = CAPTURES / "weather"
DEFAULT_DATALAKE: Final = CAPTURES / "datalake"
DEFAULT_OUT: Final = CAPTURES / "fullrun"
EXAMPLE_FROM: Final = "2025-11-10T06:00"
EXAMPLE_TO: Final = "2025-11-17T06:00"
DEFAULT_FROM: Final = local.value("RECORDING_FROM", EXAMPLE_FROM)
DEFAULT_TO: Final = local.value("RECORDING_TO", EXAMPLE_TO)
CYCLE_S: Final = 5.0
TICK_EVERY: Final = 12
PACE_EVERY: Final = 120
HEISHAMON_KEEPALIVE_S: Final = 20.0
RESTART_MONOTONIC_SHIFT_S: Final = 7919.0
DB_FILES: Final = ("history.db", "history.db-wal", "history.db-shm")

type Listener[T] = Callable[[T], None]


@dataclass(frozen=True, slots=True)
class RunConfig:
    """What to run.

    Parameters
    ----------
    start, end
        Simulated span (timezone-aware).
    out
        Output directory (``history.db``, ``summary.json``, ``summary.html``).
    params
        Fitted plant parameters; the built-in example house when ``None`` or missing.
    weather_dir
        Recorded weather cache; a synthetic cold week when ``None`` or missing.
    datalake
        Recorded HA states (room ``unavailable`` periods, humidity report times).
    profile
        Owner-facing settings.
    faults
        Fault scenarios to inject (names from :data:`ovenbird_harness.faults.SCENARIOS`).
    fault_at
        Start times of scenarios that do not take a slot, as ``(name, time)`` pairs.
    room_c
        Room temperature the plant is settled at; the comfort temperature when ``None``.
    preroll_hours
        Plant pre-roll before ``start``.
    seed
        Seed of the sensor noise.
    progress
        Log one line per simulated day.
    """

    start: datetime
    end: datetime
    out: Path
    params: Path | None = None
    weather_dir: Path | None = DEFAULT_WEATHER
    datalake: Path | None = DEFAULT_DATALAKE
    profile: Profile = field(default_factory=Profile)
    faults: tuple[str, ...] = ()
    fault_at: tuple[tuple[str, datetime], ...] = ()
    room_c: float | None = None
    preroll_hours: float = 48.0
    seed: int = 0
    progress: bool = False

    def __post_init__(self) -> None:
        """Validate the span."""
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        if not self.start < self.end:
            raise ValueError("the span must be non-empty")
        if any(moment.tzinfo is None for _, moment in self.fault_at):
            raise ValueError("fault start times must be timezone-aware")


@dataclass
class RunResult:
    """Outcome of a run.

    Parameters
    ----------
    summary
        The JSON summary (also written to ``summary.json``).
    passed
        No invariant violation and no failed fault scenario.
    """

    summary: dict[str, Any]
    passed: bool


def board_args(config: RunConfig) -> argparse.Namespace:
    """Return the simulator's command line arguments for ``config`` (``build_board`` input)."""
    params = config.params if config.params is not None and config.params.is_file() else None
    recorded = config.weather_dir is not None and config.weather_dir.is_dir()
    mqtt_room = config.profile.room_via == "mqtt"
    return argparse.Namespace(
        params=params,
        scenario="recorded" if recorded else "cold-week",
        weather_dir=config.weather_dir,
        start=config.start,
        base=DEFAULT_BASE,
        room_topic=MQTT_ROOM_TOPIC if mqtt_room else "",
        room_interval=60.0,
        room_profile="periodic",
        humidity_topic="",
        room_seed=config.seed,
        room_c=config.profile.comfort_c if config.room_c is None else config.room_c,
        heating_mode=1,
        target_lag_cycles=1,
        preroll_hours=config.preroll_hours,
        utc_offset=1.0,
        inject_prefix="",
        state_file=None,
    )


def fresh_output(out: Path) -> None:
    """Create ``out`` and remove a previous run's history database from it."""
    out.mkdir(parents=True, exist_ok=True)
    for name in DB_FILES:
        (out / name).unlink(missing_ok=True)


class FullRun:
    """One stepped closed-loop run (see the module docstring).

    Parameters
    ----------
    config
        What to run.
    """

    def __init__(self, config: RunConfig) -> None:
        self.config = config
        fresh_output(config.out)
        self.settings = harness_settings(config.out, config.profile)
        check_intervals(self.settings.control_interval_s, self.settings.safety_interval_s)
        args = board_args(config)
        self.board: SimulatedHeishaMon = build_board(args)
        self.sources = {
            "params": str(args.params) if args.params is not None else "example house",
            "weather": str(config.weather_dir) if args.scenario == "recorded" else "cold week",
        }
        self.start_ts = config.start.timestamp()
        self.end_ts = config.end.timestamp()
        self.clock = ManualClock(self.start_ts)
        self.cycle = 0
        self.filters = subscriptions(self.settings)
        self.retained: dict[str, str] = {}
        self.broker_up = True
        self.board_online = True
        self.service_up = True
        self.commands_lost = False
        self.commands_dropped = 0
        self.on_decision: list[Listener[DecisionRow]] = []
        self.on_command: list[Listener[CommandRow]] = []
        self.on_alarm: list[Listener[AlarmRow]] = []
        self.on_state: list[Listener[StateRow]] = []
        self.on_cycle: list[Listener[float]] = []
        self.system = self._new_system()
        cfg = controller_config(self.system.settings)
        self.checker = InvariantChecker(
            cfg,
            self.system.adapter.config,
            defrosting=lambda: self.board.state.defrosting,
            dhw=lambda: self.board.dhw,
        )
        self.kpis = Kpis(
            config.profile.comfort_c, daily_budget=self.system.adapter.config.daily_budget
        )
        self.feed: RoomFeed | None = None
        self.ha: FakeHomeAssistant | None = None
        if config.profile.room_via == "ha":
            self.feed, note = room_feed(
                self.start_ts,
                self.end_ts,
                ROOM_ENTITY,
                HUMIDITY_ENTITY,
                config.datalake,
                seed=config.seed,
            )
            self.sources["room"] = note
            self.ha = FakeHomeAssistant(self.settings, self.system.runtime, self.feed.units)
        else:
            self.sources["room"] = f"board MQTT topic {MQTT_ROOM_TOPIC} every 60 s"
        self.restarts = 0
        self._start_service()

    def _new_system(self) -> System:
        """Build the service system on the simulated clock, publishing through the run."""
        system = System(self.settings, self.clock, self._publish, self._listen)
        system.config.on_applied.append(self._config_applied)
        return system

    def _listen(self, writer: HarnessWriter) -> None:
        """Subscribe the run to the writer's decision, command, alarm and state rows."""
        writer.on_decision.append(self._decision)
        writer.on_command.append(self._command)
        writer.on_alarm.append(self._alarm)
        writer.on_state.append(self._state)

    def _config_applied(self, version: int | None, at: Instant) -> None:
        """Rebuild the invariant checker's limits for the configuration version just applied."""
        system = self.system
        self.checker.reconfigure(
            version, controller_config(system.config.settings), system.adapter.config
        )

    def _decision(self, row: DecisionRow) -> None:
        """Feed a decision row to the checker, the KPIs and the listeners."""
        self.checker.decision(row)
        self.kpis.decision(row)
        for listener in self.on_decision:
            listener(row)

    def _command(self, row: CommandRow) -> None:
        """Feed a command row to the checker, the KPIs and the listeners."""
        self.checker.command(row)
        self.kpis.command(row)
        for listener in self.on_command:
            listener(row)

    def _alarm(self, row: AlarmRow) -> None:
        """Feed an alarm row to the checker, the KPIs and the listeners."""
        self.checker.alarm(row)
        self.kpis.alarm(row)
        for listener in self.on_alarm:
            listener(row)

    def _state(self, row: StateRow) -> None:
        """Pass a persisted state row to the listeners."""
        for listener in self.on_state:
            listener(row)

    @property
    def now(self) -> float:
        """Current simulated unix time."""
        return self.clock.wall

    def _subscribed(self, topic: str) -> bool:
        """Return whether the service's MQTT ingest is subscribed to a filter matching ``topic``."""
        return any(aiomqtt.Topic(topic).matches(item) for item in self.filters)

    def _publish(self, topic: str, payload: str, qos: int, retain: bool) -> None:
        """Check a service publication, then deliver it to the board unless the link is cut.

        Parameters
        ----------
        topic
            Topic published to.
        payload
            Message body.
        qos
            Quality of service requested.
        retain
            Whether the message is retained.
        """
        status = self.system.runtime.store.heishamon_status(self.clock())
        self.checker.publish(
            self.now, topic, payload, qos, retain, self.system.loop.guard, status.version
        )
        if not self.broker_up:
            raise ConnectionError("broker down")
        if self.commands_lost:
            self.commands_dropped += 1
        elif self.board_online:
            self.board.receive(topic, payload)

    def _broker_publish(self, topic: str, payload: str, retain: bool) -> None:
        """Retain the message when asked and deliver it to the service if it is connected."""
        if not self.broker_up:
            return
        if retain:
            self.retained[topic] = payload
        if self.service_up and self.system.runtime.mqtt_connected and self._subscribed(topic):
            self.system.deliver(topic, payload)

    def _from_board(self, publications: Sequence[Publication]) -> None:
        """Pass the board's publications to the broker while the board is online."""
        if not self.board_online:
            return
        for item in publications:
            self._broker_publish(item.topic, item.payload, item.retain)

    def connect_mqtt(self) -> None:
        """(Re)connect the ingest and the worker; the broker delivers its retained store."""
        self.system.connect_mqtt()
        for topic, payload in list(self.retained.items()):
            if self._subscribed(topic):
                self.system.deliver(topic, payload, retained=True)
        self.system.connect_worker()

    def _start_service(self) -> None:
        """Connect MQTT and bring the Home Assistant feed up with the current room reading."""
        self.connect_mqtt()
        if self.ha is not None and self.feed is not None:
            self.ha.attach(self.system.runtime)
            room = self.board.observation.room_temp if self.board.observation else None
            if room is None:
                room = self.board.state.t_air
            self.ha.tick(self.now, self.feed.reports(self.now, room))
            self.ha.connect(self.now)

    def drop_broker(self) -> None:
        """Take the broker away: no deliveries, no publishing link."""
        self.broker_up = False
        self.system.disconnect_mqtt()
        self.system.disconnect_worker()

    def restore_broker(self) -> None:
        """Bring the broker back (with its retained store)."""
        self.broker_up = True
        if self.service_up:
            self.connect_mqtt()

    def heishamon_offline(self) -> None:
        """HeishaMon drops off the broker (reboot); the broker publishes its last will."""
        self.board_online = False

    def heishamon_will(self) -> None:
        """Publish HeishaMon's last will (``LWT`` ``Offline``) as the broker does on a dead link."""
        will = self.board.will()
        self._broker_publish(will.topic, will.payload, will.retain)

    def heishamon_boot(self) -> None:
        """HeishaMon is back after a firmware restart: uptime from 0, full dump."""
        self.board.reboot()
        self.board_online = True

    def stop_service(self) -> None:
        """Stop ovenbird (history flushed and closed); the plant runs on."""
        self.system.close()
        self.service_up = False
        if self.ha is not None:
            self.ha.disconnect()

    def start_service(self) -> None:
        """Start a new ovenbird process on the same data directory (state restored)."""
        self.clock.monotonic_offset += RESTART_MONOTONIC_SHIFT_S
        self.clock.set(self.now)
        self.system = self._new_system()
        self.service_up = True
        self.restarts += 1
        loop = self.system.loop
        self.checker.restart(loop.state.as_flat() if loop.restored else None)
        if self.broker_up:
            self._start_service()
        elif self.ha is not None and self.feed is not None:
            self.ha.attach(self.system.runtime)
            self.ha.connect(self.now)

    def step(self) -> None:
        """Advance one 5 s cycle."""
        self.cycle += 1
        t = self.start_ts + self.cycle * CYCLE_S
        now = self.clock.set(t)
        self._from_board(self.board.cycle())
        observation = self.board.observation
        assert observation is not None
        if self.ha is not None and self.feed is not None:
            self.ha.tick(t, self.feed.reports(t, observation.room_temp))
        for listener in self.on_cycle:
            listener(t)
        if self.service_up:
            system = self.system
            system.worker_step()
            system.check(now)
            if self.cycle % TICK_EVERY == 0:
                system.tick(now)
            if self.cycle % PACE_EVERY == 0:
                system.writer.pace()
        self.checker.plant(self._plant_check(t))
        self.kpis.plant(PlantSample(t, CYCLE_S, self.board.state.running, observation.room_temp))

    def _plant_check(self, t: float) -> PlantReading:
        """Return the plant reading at ``t`` that the checker compares with the commands."""
        board = self.board
        registers = board.registers
        adapter = self.system.adapter
        register = (
            registers.curve_target_high
            if adapter.config.setpoint_register == "setcurves_target_high"
            else registers.direct_setpoint
        )
        latest = self.system.loop.latest
        ladder = latest.get("ladder") if latest is not None else None
        blocked = (
            not (self.service_up and self.broker_up and self.board_online)
            or self.commands_lost
            or adapter.hold_reason is not None
            or not self.system.loop.guard.permits
            or ladder in ("refuse", "hold")
        )
        observation = board.observation
        return PlantReading(
            ts=t,
            setpoint_register=register,
            max_pump_duty=registers.max_pump_duty,
            outlet_c=None if observation is None else observation.outlet_temp,
            running=board.state.running,
            defrosting=board.state.defrosting,
            commands_blocked=blocked,
        )

    def run(self) -> RunResult:
        """Run the whole span and write the outputs."""
        at = {name: moment.timestamp() for name, moment in self.config.fault_at}
        scheduler = Scheduler.build(self, self.config.faults, at)
        began = time.perf_counter()
        cycles = int((self.end_ts - self.start_ts) // CYCLE_S)
        day = 0
        while self.cycle < cycles:
            scheduler.before(self.start_ts + (self.cycle + 1) * CYCLE_S)
            self.step()
            if self.config.progress and int((self.now - self.start_ts) // 86400) > day:
                day += 1
                LOGGER.info(
                    "day %d (%s): %.0f s wall, %d decisions, %d violations",
                    day,
                    datetime.fromtimestamp(self.now, UTC).date(),
                    time.perf_counter() - began,
                    self.checker.decisions,
                    self.checker.total,
                )
        stepped = time.perf_counter() - began
        if self.service_up:
            self.system.close()
        self.checker.finish(self.now, self.system.adapter.config.verify_timeout_s)
        wall = time.perf_counter() - began
        outcomes = scheduler.outcomes()
        summary = self._summary(stepped, wall, outcomes)
        failed_faults = [o for o in outcomes if o["status"] != "pass"]
        passed = self.checker.total == 0 and not failed_faults and summary["history"]["consistent"]
        summary["passed"] = passed
        write_report(self.config.out, summary)
        return RunResult(summary, passed)

    def _history(self) -> dict[str, Any]:
        """Return the history database's row counts and size, and whether they match the checker."""
        path = self.settings.history_path
        with sqlite3.connect(path) as db:
            decisions = db.execute("SELECT count(*) FROM decision").fetchone()[0]
            commands = db.execute("SELECT count(*) FROM command").fetchone()[0]
            alarms = db.execute("SELECT count(*) FROM alarm").fetchone()[0]
            samples = db.execute("SELECT count(*) FROM sample").fetchone()[0]
        size = sum(
            (path.parent / name).stat().st_size
            for name in DB_FILES
            if (path.parent / name).exists()
        )
        writer = self.system.writer
        return {
            "path": str(path),
            "size_mb": size / 2**20,
            "decision_rows": decisions,
            "command_rows": commands,
            "alarm_rows": alarms,
            "sample_rows": samples,
            "dropped_overflow": writer.dropped_overflow,
            "consistent": decisions == self.checker.decisions
            and commands == self.checker.command_events
            and writer.dropped_overflow == 0,
        }

    def _summary(
        self, stepped: float, wall: float, outcomes: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Return the run summary.

        Parameters
        ----------
        stepped
            Wall time spent stepping the plant and service, in seconds.
        wall
            Total wall time of the run, in seconds.
        outcomes
            The fault scenario outcomes.

        Returns
        -------
        dict[str, Any]
            Span, profile, timing, KPIs, energy, board and adapter counters, invariants, faults
            and history, as written to ``summary.json``.
        """
        plant = self.board.state
        return {
            "span": {
                "from": self.config.start.isoformat(),
                "to": self.config.end.isoformat(),
                "days": (self.end_ts - self.start_ts) / 86400.0,
                "cycles": self.cycle,
            },
            "sources": self.sources,
            "profile": {
                "comfort_c": self.config.profile.comfort_c,
                "min_setpoint_c": self.config.profile.min_setpoint_c,
                "emitter": self.config.profile.emitter,
                "pump_duty": [
                    self.config.profile.pump_duty_heat,
                    self.config.profile.pump_duty_idle,
                ],
                "room_via": self.config.profile.room_via,
                "room_signal": self.config.profile.room_signal,
                "room_profile": self.config.profile.room_profile,
                "room_crosscheck": self.config.profile.room_crosscheck,
            },
            "wall_time_s": wall,
            "stepping_time_s": stepped,
            "simulated_days_per_wall_minute": (self.end_ts - self.start_ts)
            / 86400.0
            / (wall / 60.0),
            "kpis": self.kpis.summary(),
            "energy": {
                "heat_kwh": plant.heat_j / 3.6e6,
                "electricity_kwh": plant.elec_j / 3.6e6,
                "cop": plant.heat_j / plant.elec_j if plant.elec_j else None,
                "plant_starts": plant.starts,
                "plant_defrosts": plant.defrosts,
            },
            "board": {
                "commands_received": self.board.stats.commands_received,
                "commands_applied": self.board.stats.commands_applied,
                "commands_ignored": self.board.stats.commands_ignored,
            },
            "adapter": self.system.adapter.status(self.clock())["counters"],
            "invariants": self.checker.summary(),
            "faults": outcomes,
            "restarts": self.restarts,
            "commands_lost": self.commands_dropped,
            "history": self._history(),
            "alarm_log": self.kpis.alarm_log[:200],
        }


def check_intervals(control_interval_s: float, safety_interval_s: float) -> None:
    """Refuse settings the stepper does not honour (control every 60 s, monitors every 5 s).

    Raises
    ------
    ValueError
        When the settings ask for other intervals.
    """
    if control_interval_s != CYCLE_S * TICK_EVERY or safety_interval_s != CYCLE_S:
        raise ValueError(
            f"the stepped run ticks the control loop every {CYCLE_S * TICK_EVERY:g} s and the "
            f"safety monitors every {CYCLE_S:g} s; the settings ask for "
            f"{control_interval_s:g} s and {safety_interval_s:g} s"
        )


def _optional_path(raw: str) -> Path | None:
    """Return ``raw`` as a path, or None when it is empty."""
    return Path(raw) if raw else None


def build_parser() -> argparse.ArgumentParser:
    """Build the command line parser."""
    parser = argparse.ArgumentParser(
        prog="python -m ovenbird_harness.fullrun",
        description="Stepped closed-loop run of the whole service against the simulated plant.",
    )
    parser.add_argument(
        "--from", dest="start", type=parse_start, default=None, help=f"default {DEFAULT_FROM}"
    )
    parser.add_argument(
        "--to", dest="end", type=parse_start, default=None, help=f"default {DEFAULT_TO}"
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--params",
        type=_optional_path,
        default=plant_from_environment(),
        help=f"fitted plant (default ${PLANT_ENV}, e.g. {FITTED_PARAMS}); else the example house",
    )
    parser.add_argument("--weather-dir", type=_optional_path, default=DEFAULT_WEATHER)
    parser.add_argument("--datalake", type=_optional_path, default=DEFAULT_DATALAKE)
    parser.add_argument("--faults", action="store_true", help="inject every fault scenario")
    parser.add_argument(
        "--fault", action="append", default=[], choices=sorted(SCENARIOS), help="one scenario"
    )
    parser.add_argument(
        "--at",
        type=parse_start,
        default=None,
        help="start the --fault scenarios at this time (span: a warm-up day before, the "
        "window and a tail after, unless --from/--to are given)",
    )
    parser.add_argument(
        "--sweep",
        type=int,
        default=0,
        metavar="N",
        help="run each scenario (--fault, or all) alone at N start times over the span",
    )
    parser.add_argument("--jobs", type=int, default=None, help="sweep worker processes")
    parser.add_argument(
        "--keep-history", action="store_true", help="keep history.db of passed sweep runs"
    )
    parser.add_argument("--room-via", choices=("ha", "mqtt"), default="ha")
    parser.add_argument("--room-profile", choices=("on_change", "periodic"), default="on_change")
    parser.add_argument(
        "--room-crosscheck",
        default=EXAMPLE_CROSSCHECK,
        help="plausibility cross-check signal ('' disables)",
    )
    parser.add_argument(
        "--comfort", type=float, default=local.number("COMFORT_C", EXAMPLE_COMFORT_C)
    )
    parser.add_argument(
        "--min-setpoint",
        type=float,
        default=local.number("MIN_SETPOINT_C", EXAMPLE_MIN_SETPOINT_C),
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--log-level", default="CRITICAL", help="of the service's loggers")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run B1 from the command line; exit code 1 when the run fails.

    Parameters
    ----------
    argv
        Command line arguments; ``sys.argv`` when None.

    Returns
    -------
    int
        Process exit code: 0 when the run passed, 1 otherwise.
    """
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(levelname)s %(name)s %(message)s")
    LOGGER.setLevel(logging.INFO)
    from ovenbird_harness import sweep

    faults = tuple(SCENARIOS) if args.faults else tuple(args.fault)
    start = args.start or parse_start(DEFAULT_FROM)
    end = args.end or parse_start(DEFAULT_TO)
    fault_at: tuple[tuple[str, datetime], ...] = ()
    if args.at is not None:
        if not faults or args.sweep:
            raise SystemExit("--at needs --fault (and no --sweep)")
        fault_at = tuple((name, args.at) for name in faults)
        auto_start, auto_end = sweep.single_span(args.at, faults)
        start = args.start or auto_start
        end = args.end or auto_end
    config = RunConfig(
        start=start,
        end=end,
        out=args.out / ("faults" if faults else "plain"),
        params=args.params,
        weather_dir=args.weather_dir,
        datalake=args.datalake,
        profile=Profile(
            comfort_c=args.comfort,
            min_setpoint_c=args.min_setpoint,
            room_via=args.room_via,
            room_profile=args.room_profile,
            room_crosscheck=args.room_crosscheck or None,
        ),
        faults=faults,
        fault_at=fault_at,
        seed=args.seed,
        progress=True,
    )
    if args.sweep:
        return _sweep(args, config, faults or tuple(SCENARIOS))
    out = config.out
    if out.exists():
        shutil.rmtree(out)
    result = FullRun(config).run()
    print(json.dumps(headline(result.summary), indent=2, ensure_ascii=False))
    print(f"wrote {out / 'summary.json'}, {out / 'summary.html'}, {out / 'history.db'}")
    return 0 if result.passed else 1


def _sweep(args: argparse.Namespace, base: RunConfig, names: tuple[str, ...]) -> int:
    """Run the scenario sweep and write ``sweep.json``; return 1 when any run failed."""
    from ovenbird_harness import sweep

    out = args.out / "sweep"
    runs = sweep.plan(base, names, args.sweep, out)
    jobs = args.jobs or sweep.default_jobs()
    LOGGER.info("sweep: %d runs on %d processes", len(runs), jobs)
    began = time.perf_counter()
    rows = sweep.run_sweep(runs, jobs, args.log_level, args.keep_history)
    out.mkdir(parents=True, exist_ok=True)
    failed = [row for row in rows if row["status"] != "pass"]
    report = {
        "span": {"from": base.start.isoformat(), "to": base.end.isoformat()},
        "count": args.sweep,
        "wall_time_s": time.perf_counter() - began,
        "passed": not failed,
        "runs": rows,
    }
    (out / "sweep.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(sweep.matrix(rows))
    print(f"{len(rows) - len(failed)} of {len(rows)} runs passed; wrote {out / 'sweep.json'}")
    return 0 if not failed else 1


def headline(summary: dict[str, Any]) -> dict[str, Any]:
    """Return the figures worth printing at the end of a run."""
    kpis = summary["kpis"]
    return {
        "passed": summary["passed"],
        "days": round(summary["span"]["days"], 2),
        "wall_time_s": round(summary["wall_time_s"], 1),
        "ladder_shares": {k: round(v, 4) for k, v in kpis["ladder_shares"].items()},
        "held_value_share": kpis["held_value_share"],
        "commands_per_day": round(kpis["commands"]["sent_per_day_mean"], 1),
        "max_writes_per_day": kpis["commands"]["sent_per_day_max"],
        "starts_per_day": round(kpis["plant"]["starts_per_day"], 2),
        "share_runs_below_20_min": kpis["plant"]["share_runs_below_20_min"],
        "room": {k: round(v, 3) for k, v in kpis["room"].items()},
        "alarms_raised": kpis["alarms_raised"],
        "holds": kpis["holds"],
        "invariant_violations": summary["invariants"]["by_rule"],
        "faults": {item["name"]: item["status"] for item in summary["faults"]},
    }


if __name__ == "__main__":
    sys.exit(main())

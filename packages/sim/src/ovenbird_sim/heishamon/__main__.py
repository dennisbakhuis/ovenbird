r"""Command line: run a simulated HeishaMon against a local MQTT broker.

Examples
--------
Recorded weather of a local day with a fitted plant, 60x faster than real time::

    python -m ovenbird_sim.heishamon --host localhost --port 1884 --speed 60 \\
        --start 2026-01-06 --params capture/captures/models/plant_params.json

A synthetic cold week with the built-in example house (no local data needed)::

    python -m ovenbird_sim.heishamon --scenario cold-week --speed 60

Recorded weather ends: by default the simulator stops there (one log line, ``LWT``
``Offline``, then idle); ``--at-end loop`` repeats the recording instead::

    python -m ovenbird_sim.heishamon --speed 600 --at-end loop

A send-on-delta room sensor (0.1 K grid, no heartbeat) with its
companion humidity as the liveness signal::

    python -m ovenbird_sim.heishamon --room-profile on_change \\
        --humidity-topic climate_manager_capture/room_humidity
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from ovenbird_core.control import EmitterType, default_curve
from ovenbird_sim import local
from ovenbird_sim.evaluate.sensors import example_room_sensor
from ovenbird_sim.heishamon.board import (
    DEFAULT_BASE,
    DEFAULT_ROOM_TOPIC,
    BoardConfig,
    SimulatedHeishaMon,
    preroll,
)
from ovenbird_sim.heishamon.reference import PLANT_ENV, REFERENCE_PARAMS, plant_from_environment
from ovenbird_sim.heishamon.registers import Registers, registers_from_json
from ovenbird_sim.heishamon.runner import END_OF_WEATHER, RemoteBrokerError, RunnerConfig, run
from ovenbird_sim.heishamon.weather import (
    ColdWeek,
    LoopedWeather,
    RecordedWeather,
    Weather,
    local_hour,
)
from ovenbird_sim.identify.io import load
from ovenbird_sim.model import PlantParams

LOGGER = logging.getLogger("ovenbird_sim.heishamon")
DEFAULT_WEATHER_DIR: Final = Path("capture/captures/weather")
EXAMPLE_START: Final = "2026-01-06"
SCENARIOS: Final = ("recorded", "cold-week")
DEFAULT_INJECT_PREFIX: Final = "heishamon_sim/inject"
IDLE_SLEEP_S: Final = 3600.0


def parse_start(text: str) -> datetime:
    """Parse ``YYYY-MM-DD`` or an ISO 8601 time; naive values are UTC."""
    raw = text.strip()
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    moment = datetime.fromisoformat(raw)
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    """Build the command line parser."""
    parser = argparse.ArgumentParser(
        prog="python -m ovenbird_sim.heishamon",
        description="Simulated HeishaMon driven by the fitted plant model (local brokers only).",
    )
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--speed", type=float, default=1.0, help="simulated seconds per second")
    parser.add_argument(
        "--start", type=parse_start, default=parse_start(local.value("SIM_START", EXAMPLE_START))
    )
    parser.add_argument(
        "--params",
        type=lambda raw: Path(raw) if raw else None,
        default=plant_from_environment(),
        help=f"plant_params.json (default ${PLANT_ENV}); the example house when unset or empty",
    )
    parser.add_argument("--scenario", choices=SCENARIOS, default="recorded")
    parser.add_argument("--weather-dir", type=Path, default=DEFAULT_WEATHER_DIR)
    parser.add_argument("--base", default=DEFAULT_BASE, help="HeishaMon mqtt_topic_base")
    parser.add_argument("--room-topic", default=DEFAULT_ROOM_TOPIC, help="'' disables it")
    parser.add_argument(
        "--room-interval", type=float, default=60.0, help="periodic room sensor interval in s"
    )
    parser.add_argument(
        "--room-profile",
        choices=("periodic", "on_change"),
        default="periodic",
        help="room sensor device: periodic 0.1 K, or a send-on-delta 0.2 K device",
    )
    parser.add_argument(
        "--humidity-topic", default="", help="companion humidity topic (on_change); '' disables"
    )
    parser.add_argument("--room-seed", type=int, default=0, help="room sensor noise seed")
    parser.add_argument("--room-c", type=float, default=20.5, help="initial room temperature")
    parser.add_argument("--heating-mode", type=int, choices=(0, 1), default=1)
    parser.add_argument("--target-lag-cycles", type=int, default=1)
    parser.add_argument("--preroll-hours", type=float, default=48.0)
    parser.add_argument("--utc-offset", type=float, default=1.0, help="local clock offset in h")
    parser.add_argument("--duration-hours", type=float, help="stop after this many simulated h")
    parser.add_argument("--status-every", type=float, default=3600.0, help="simulated s")
    parser.add_argument("--allow-remote-broker", action="store_true")
    parser.add_argument(
        "--inject-prefix",
        default=DEFAULT_INJECT_PREFIX,
        help="fault injection topic prefix (simulator only); '' disables it",
    )
    parser.add_argument(
        "--state-file",
        type=lambda raw: Path(raw) if raw else None,
        help="save the pump registers here and restore them on start",
    )
    parser.add_argument(
        "--at-end",
        choices=("stop", "loop"),
        default="stop",
        help="when the recorded weather runs out: stop (LWT Offline, then idle) or loop it",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser


def load_params(path: Path | None) -> PlantParams:
    """Return the fitted parameters from ``path``, or the example house."""
    if path is None:
        return REFERENCE_PARAMS
    return load(path)


def build_weather(args: argparse.Namespace) -> Weather:
    """Return the scenario's exogenous inputs."""
    if args.scenario == "cold-week":
        return ColdWeek(args.start)
    weather = RecordedWeather.load(args.weather_dir)
    if not weather.covers(args.start.timestamp()):
        LOGGER.warning("start %s lies outside the recorded weather", args.start.isoformat())
    if getattr(args, "at_end", "stop") == "loop":
        return LoopedWeather(weather)
    return weather


def load_registers(path: Path | None) -> Registers | None:
    """Return the registers saved in ``path``, or ``None`` when absent or unreadable."""
    if path is None or not path.exists():
        return None
    try:
        registers = registers_from_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        LOGGER.warning("ignoring state file %s: %s", path, exc)
        return None
    LOGGER.info("registers restored from %s", path)
    return registers


def build_board(args: argparse.Namespace) -> SimulatedHeishaMon:
    """Assemble the board from parsed arguments.

    Parameters
    ----------
    args
        Parsed command line.

    Returns
    -------
    SimulatedHeishaMon
        Board with a settled plant; the setpoint register holds the pre-roll's last value.
    """
    params = load_params(args.params)
    weather = build_weather(args)
    start = args.start
    outside = weather.at(start.timestamp(), local_hour(start.timestamp(), args.utc_offset))
    setpoint = math.floor(default_curve(EmitterType.MIXED).water(outside.outside_c) + 0.5)
    state = preroll(
        params,
        weather,
        start,
        setpoint,
        room_c=args.room_c,
        hours=args.preroll_hours,
        utc_offset_h=args.utc_offset,
    )
    if state.last_setpoint is not None:
        setpoint = math.floor(state.last_setpoint + 0.5)
    registers = load_registers(getattr(args, "state_file", None)) or replace(
        Registers(heating_mode=args.heating_mode),
        direct_setpoint=setpoint,
        curve_target_high=setpoint if args.heating_mode == 1 else Registers().curve_target_high,
    )
    inject_prefix = getattr(args, "inject_prefix", DEFAULT_INJECT_PREFIX)
    config = BoardConfig(
        base=args.base,
        target_lag_cycles=args.target_lag_cycles,
        room_topic=args.room_topic or None,
        room_interval_s=args.room_interval,
        room_sensor=example_room_sensor() if args.room_profile == "on_change" else None,
        humidity_topic=(args.humidity_topic or None) if args.room_profile == "on_change" else None,
        room_seed=args.room_seed,
        utc_offset_h=args.utc_offset,
        inject_prefix=inject_prefix.strip("/") or None,
    )
    return SimulatedHeishaMon(
        params, weather, start, registers=registers, config=config, state=state
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the simulator; returns the process exit code."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    try:
        board = build_board(args)
        config = RunnerConfig(
            host=args.host,
            port=args.port,
            speed=args.speed,
            duration_s=None if args.duration_hours is None else args.duration_hours * 3600.0,
            allow_remote=args.allow_remote_broker,
            status_every_s=args.status_every,
            state_file=args.state_file,
        )
        outcome = asyncio.run(run(board, config))
        if outcome == END_OF_WEATHER:
            idle()
    except (RemoteBrokerError, FileNotFoundError, ValueError) as exc:
        LOGGER.error("%s", exc)
        return 2
    except KeyboardInterrupt:
        return 0
    return 0


def idle(sleep: Callable[[float], None] = time.sleep) -> None:
    """Stay alive without publishing until the process is stopped."""
    while True:
        sleep(IDLE_SLEEP_S)


if __name__ == "__main__":
    sys.exit(main())

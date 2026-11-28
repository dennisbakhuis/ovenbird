r"""B2 command line: exact replays and KPI comparison against the real asyncio service.

Two exact replays (30 s at 120x each): the MQTT path with a periodic room sensor,
and the Home Assistant path, the room and humidity through Home Assistant with the
``on_change`` profile. The KPI comparison (48 h at 600x, two real repeats) runs on
the MQTT path. Output goes to a fresh temporary directory unless ``--out`` names one.

Examples
--------
Everything with the defaults::

    uv run python -m ovenbird_harness.validate

A longer KPI window into a chosen directory::

    uv run python -m ovenbird_harness.validate --skip-replay --hours 96 --out /tmp/b2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import tempfile
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

from ovenbird_harness.compare import MIN_WINDOW_H, compare
from ovenbird_harness.fullrun import (
    DEFAULT_WEATHER,
    RunConfig,
    board_args,
)
from ovenbird_harness.replay import compare_rows, replay, run_service
from ovenbird_harness.settings import HUMIDITY_ENTITY, ROOM_ENTITY, Profile, harness_settings
from ovenbird_sim.heishamon.__main__ import build_board, parse_start
from ovenbird_sim.heishamon.reference import plant_from_environment

DEFAULT_START: Final = "2025-11-10T06:00"
HA_ROOM_TOPIC: Final = "sim/ha/room_temperature"
HA_HUMIDITY_TOPIC: Final = "sim/ha/room_humidity"
HA_UNITS: Final = {ROOM_ENTITY: "°C", HUMIDITY_ENTITY: "%"}


def replay_check(
    config: RunConfig, speed: float, seconds: float, work: Path, *, ha: bool = False
) -> dict[str, Any]:
    """Record the real service for ``seconds`` at ``speed`` and replay it through the stepper.

    Parameters
    ----------
    config
        Plant, weather, start and profile (room via the board's MQTT topic, or via
        Home Assistant with ``ha``).
    speed
        Clock speed of the real service.
    seconds
        Real seconds to record.
    work
        Scratch directory (two data directories are created in it).
    ha
        Home Assistant path: the board's on-change room sensor and humidity reach the service
        through an in-memory Home Assistant.

    Returns
    -------
    dict
        The :class:`~ovenbird_harness.replay.ReplayResult` as JSON.
    """
    settings = harness_settings(
        work / "recorded", config.profile, clock_speed=speed, clock_start=config.start
    )
    args = board_args(config)
    topics: dict[str, str] | None = None
    if ha:
        args.room_topic = HA_ROOM_TOPIC
        args.room_profile = "on_change"
        args.humidity_topic = HA_HUMIDITY_TOPIC
        topics = {HA_ROOM_TOPIC: ROOM_ENTITY, HA_HUMIDITY_TOPIC: HUMIDITY_ENTITY}
    board = build_board(args)
    _, recording = asyncio.run(
        run_service(settings, board, seconds, record=True, ha_topics=topics, ha_units=HA_UNITS)
    )
    assert recording is not None
    recording.check(ha=ha)
    rows = replay(settings, recording, work / "replayed")
    result = compare_rows(recording.rows, rows, len(recording.events)).to_json()
    result["speed"] = speed
    result["simulated_minutes"] = seconds * speed / 60.0
    result["path"] = "ha/on_change" if ha else "mqtt/periodic"
    result["event_kinds"] = sorted({event.kind for event in recording.events})
    return result


def mqtt_config(start: datetime, params: Path | None, weather: Path | None, out: Path) -> RunConfig:
    """Return the configuration of the B2 checks: example profile, room via the MQTT topic.

    Parameters
    ----------
    start
        Simulated start time (UTC).
    params
        Plant parameter file, or ``None`` for the defaults.
    weather
        Weather directory, or ``None``.
    out
        Output directory of the run.

    Returns
    -------
    RunConfig
        One simulated hour from ``start``.
    """
    return RunConfig(
        start=start,
        end=start + timedelta(hours=1),
        out=out,
        params=params,
        weather_dir=weather,
        datalake=None,
        profile=Profile(room_via="mqtt", room_profile="periodic"),
    )


def ha_config(start: datetime, params: Path | None, weather: Path | None, out: Path) -> RunConfig:
    """Return the configuration of the HA replay: example profile, room via Home Assistant.

    Parameters
    ----------
    start
        Simulated start time (UTC).
    params
        Plant parameter file, or ``None`` for the defaults.
    weather
        Weather directory, or ``None``.
    out
        Output directory of the run.

    Returns
    -------
    RunConfig
        One simulated hour from ``start``.
    """
    return RunConfig(
        start=start,
        end=start + timedelta(hours=1),
        out=out,
        params=params,
        weather_dir=weather,
        datalake=None,
        profile=Profile(room_via="ha", room_profile="on_change"),
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the command line parser."""
    parser = argparse.ArgumentParser(
        prog="python -m ovenbird_harness.validate",
        description="B2: validate the stepped run against the real asyncio service.",
    )
    parser.add_argument(
        "--from", dest="start", type=parse_start, default=parse_start(DEFAULT_START)
    )
    parser.add_argument("--params", type=Path, default=plant_from_environment())
    parser.add_argument("--weather-dir", type=Path, default=DEFAULT_WEATHER)
    parser.add_argument(
        "--out", type=Path, default=None, help="output directory (default: a new temporary one)"
    )
    parser.add_argument("--replay-speed", type=float, default=120.0)
    parser.add_argument("--replay-seconds", type=float, default=30.0)
    parser.add_argument(
        "--hours", type=float, default=MIN_WINDOW_H, help="KPI window (simulated h, at least 48)"
    )
    parser.add_argument("--speed", type=float, default=600.0, help="real-service clock speed")
    parser.add_argument("--skip-replay", action="store_true")
    parser.add_argument("--skip-kpis", action="store_true")
    parser.add_argument("--log-level", default="CRITICAL")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run B2; exit code 1 when a check fails.

    Parameters
    ----------
    argv
        Command-line arguments; ``None`` reads ``sys.argv``.

    Returns
    -------
    int
        Exit code, 0 when every check passed.
    """
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(levelname)s %(name)s %(message)s")
    out: Path = args.out or Path(tempfile.mkdtemp(prefix="ovenbird-validate-"))
    out.mkdir(parents=True, exist_ok=True)
    config = mqtt_config(args.start, args.params, args.weather_dir, out)
    report: dict[str, Any] = {}
    if not args.skip_replay:
        with tempfile.TemporaryDirectory(prefix="ovenbird-replay-") as work:
            report["replay"] = replay_check(
                config, args.replay_speed, args.replay_seconds, Path(work) / "mqtt"
            )
            report["replay_ha"] = replay_check(
                ha_config(args.start, args.params, args.weather_dir, out),
                args.replay_speed,
                args.replay_seconds,
                Path(work) / "ha",
                ha=True,
            )
    if not args.skip_kpis:
        report["kpis"] = compare(config, args.hours, args.speed)
    passed = all(item.get("passed", False) for item in report.values())
    report["passed"] = passed
    (out / "validate.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"wrote {out / 'validate.json'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())

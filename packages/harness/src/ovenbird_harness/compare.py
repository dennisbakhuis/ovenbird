"""B2b: closed-loop KPIs of the stepped run against the real asyncio service.

Same-time decision agreement is unsound in a closed loop with thresholds, so the
comparison is statistical: the real service (built by ``build_service``, simulator
runner, in-memory broker, scaled clock) runs the same window twice, and B1 must land
within a tolerance set by the spread of those two repeats. Two repeats can agree
exactly on a short window, so every KPI also has a floor:

=====================  =====================================  ====================
KPI                    distance                               tolerance
=====================  =====================================  ====================
starts per day         ``|B1 - mean(real)|``                  ``max(2 spread, 1 start per window)``
ladder shares          largest share difference               ``max(2 spread, 0.01)``
setpoint histogram     total variation distance               ``max(2 TV(r1, r2), 0.02)``
room mean              ``|B1 - mean(real)|``                  ``max(2 spread, 0.02 K)``
=====================  =====================================  ====================

The window must exercise the plant: at least :data:`MIN_WINDOW_H` hours, one
defrost and :data:`MIN_STARTS` compressor starts in every run (B1 and both
repeats), otherwise the comparison fails (``coverage``). The comparison runs on the
MQTT path with a periodic room sensor; the HA path (``on_change``) is covered by the
exact replay.
"""

from __future__ import annotations

import asyncio
import math
import multiprocessing
import tempfile
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Any, Final

from ovenbird.history.journal import query_decisions
from ovenbird_harness.fullrun import CYCLE_S, FullRun, RunConfig, board_args
from ovenbird_harness.kpi import Kpis, PlantSample
from ovenbird_harness.replay import run_service
from ovenbird_harness.settings import harness_settings
from ovenbird_sim.heishamon.__main__ import build_board
from ovenbird_sim.heishamon.board import SimulatedHeishaMon

LADDER_FLOOR: Final = 0.01
HISTOGRAM_FLOOR: Final = 0.02
ROOM_FLOOR_K: Final = 0.02
MIN_WINDOW_H: Final = 48.0
MIN_STARTS: Final = 8
MIN_DEFROSTS: Final = 1
SPREAD_FACTOR: Final = 2.0
MAX_ROWS: Final = 1_000_000


@dataclass(frozen=True, slots=True)
class WindowKpis:
    """The compared KPIs of one run.

    Parameters
    ----------
    days
        Simulated days the plant ran.
    starts_per_day
        Compressor starts per day.
    ladder
        Share of decisions per ladder level.
    setpoints
        Share of controlled decisions per setpoint.
    room_mean_c
        Time-mean true room temperature.
    decisions
        Decisions taken.
    starts, defrosts
        Compressor starts and defrosts of the plant in the window.
    """

    days: float
    starts_per_day: float
    ladder: dict[str, float]
    setpoints: dict[str, float]
    room_mean_c: float
    decisions: int
    starts: int = 0
    defrosts: int = 0

    def to_json(self) -> dict[str, Any]:
        """Return the JSON form."""
        return {
            "days": self.days,
            "starts_per_day": self.starts_per_day,
            "ladder": self.ladder,
            "setpoints": self.setpoints,
            "room_mean_c": self.room_mean_c,
            "decisions": self.decisions,
            "starts": self.starts,
            "defrosts": self.defrosts,
        }


def _normalised(counter: dict[str, int]) -> dict[str, float]:
    """Return the counter as shares summing to one (empty if the counter is empty)."""
    total = sum(counter.values())
    return {k: v / total for k, v in sorted(counter.items())} if total else {}


def window_kpis(kpis: Kpis, defrosts: int = 0) -> WindowKpis:
    """Extract the compared KPIs from an accumulator (``defrosts`` from the plant)."""
    summary = kpis.summary()
    return WindowKpis(
        days=kpis.days,
        starts_per_day=kpis.starts / kpis.days if kpis.days else math.nan,
        ladder=summary["ladder_shares"],
        setpoints=_normalised({str(k): v for k, v in kpis.setpoints.items()}),
        room_mean_c=summary["room"]["mean_c"],
        decisions=kpis.decisions,
        starts=kpis.starts,
        defrosts=defrosts,
    )


def window_config(config: RunConfig, hours: float) -> RunConfig:
    """Return the comparison window: ``hours`` from the start, room via the board's MQTT topic."""
    profile = replace(config.profile, room_via="mqtt", room_profile="periodic")
    return replace(config, end=config.start + timedelta(hours=hours), profile=profile, faults=())


async def _real(config: RunConfig, speed: float, data_dir: Path) -> WindowKpis:
    """Run the real service over the window at ``speed`` and return its KPIs.

    Parameters
    ----------
    config
        Window configuration (start, end, profile, plant, weather).
    speed
        Clock speed multiplier of the real service.
    data_dir
        Scratch directory for the service's database.

    Returns
    -------
    WindowKpis
        KPIs accumulated from plant samples and the recorded decisions.
    """
    hours = (config.end - config.start).total_seconds() / 3600.0
    settings = harness_settings(
        data_dir,
        config.profile,
        clock_speed=speed,
        clock_start=config.start,
    )
    board = build_board(board_args(config))
    kpis = Kpis(config.profile.comfort_c)
    end = config.end.timestamp()

    def sample(item: SimulatedHeishaMon) -> None:
        """Account one plant cycle of the real run, ignoring cycles past the window end."""
        t = item.now.timestamp()
        if item.observation is not None and t <= end:
            kpis.plant(PlantSample(t, CYCLE_S, item.state.running, item.observation.room_temp))

    await run_service(settings, board, hours * 3600.0 / speed, on_cycle=sample)
    for row in query_decisions(settings.history_path, 0.0, end, MAX_ROWS):
        kpis.decision(row)
    return window_kpis(kpis, board.state.defrosts)


def real_window(config: RunConfig, speed: float) -> dict[str, Any]:
    """Run the real service over the window once (process entry point)."""
    with tempfile.TemporaryDirectory(prefix="ovenbird-b2-") as directory:
        return asyncio.run(_real(config, speed, Path(directory))).to_json()


def b1_window(config: RunConfig) -> WindowKpis:
    """Run the stepped B1 over the window."""
    run = FullRun(config)
    run.run()
    return window_kpis(run.kpis, run.board.state.defrosts)


def _from_json(data: dict[str, Any]) -> WindowKpis:
    """Rebuild window KPIs from their JSON form (as sent between processes)."""
    return WindowKpis(
        data["days"],
        data["starts_per_day"],
        data["ladder"],
        data["setpoints"],
        data["room_mean_c"],
        data["decisions"],
        data.get("starts", 0),
        data.get("defrosts", 0),
    )


def _tv(a: dict[str, float], b: dict[str, float]) -> float:
    """Return the total-variation distance between two distributions."""
    keys = set(a) | set(b)
    return 0.5 * sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in keys)


def _mean_dist(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    """Return the pointwise mean of two distributions."""
    keys = set(a) | set(b)
    return {k: 0.5 * (a.get(k, 0.0) + b.get(k, 0.0)) for k in keys}


def _max_diff(a: dict[str, float], b: dict[str, float]) -> float:
    """Return the largest absolute per-key difference between two distributions."""
    keys = set(a) | set(b)
    return max((abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in keys), default=0.0)


def judge(b1: WindowKpis, first: WindowKpis, second: WindowKpis) -> dict[str, Any]:
    """Compare B1 with two real repeats (see the module docstring for the tolerances)."""
    days = max(b1.days, 1e-9)
    results: dict[str, Any] = {}

    def scalar(name: str, b: float, r1: float, r2: float, floor: float) -> None:
        """Judge a scalar KPI: B1 passes within the tolerance of the repeats' mean.

        Parameters
        ----------
        name
            Result key of the KPI.
        b
            B1 value.
        r1
            Value of the first real repeat.
        r2
            Value of the second real repeat.
        floor
            Minimum tolerance, in the units of the KPI.
        """
        spread = abs(r1 - r2)
        tolerance = max(SPREAD_FACTOR * spread, floor)
        distance = abs(b - 0.5 * (r1 + r2))
        results[name] = {
            "b1": b,
            "real": [r1, r2],
            "spread": spread,
            "distance": distance,
            "tolerance": tolerance,
            "passed": distance <= tolerance,
        }

    def distribution(
        name: str,
        b: dict[str, float],
        r1: dict[str, float],
        r2: dict[str, float],
        floor: float,
        tv: bool,
    ) -> None:
        """Judge a distribution KPI against the mean of the two repeats.

        Parameters
        ----------
        name
            Result key of the KPI.
        b
            B1 distribution.
        r1
            Distribution of the first real repeat.
        r2
            Distribution of the second real repeat.
        floor
            Minimum tolerance, in the units of the chosen distance.
        tv
            Use the total-variation distance if true, the largest per-key difference if false.
        """
        measure = _tv if tv else _max_diff
        spread = measure(r1, r2)
        tolerance = max(SPREAD_FACTOR * spread, floor)
        distance = measure(b, _mean_dist(r1, r2))
        results[name] = {
            "b1": b,
            "real": [r1, r2],
            "spread": spread,
            "distance": distance,
            "tolerance": tolerance,
            "passed": distance <= tolerance,
        }

    scalar(
        "starts_per_day", b1.starts_per_day, first.starts_per_day, second.starts_per_day, 1.0 / days
    )
    distribution("ladder_shares", b1.ladder, first.ladder, second.ladder, LADDER_FLOOR, False)
    distribution(
        "setpoint_histogram", b1.setpoints, first.setpoints, second.setpoints, HISTOGRAM_FLOOR, True
    )
    scalar("room_mean_c", b1.room_mean_c, first.room_mean_c, second.room_mean_c, ROOM_FLOOR_K)
    runs = {"b1": b1, "real_1": first, "real_2": second}
    short = {
        name: {"hours": item.days * 24.0, "starts": item.starts, "defrosts": item.defrosts}
        for name, item in runs.items()
        if item.days * 24.0 < MIN_WINDOW_H - 1e-6
        or item.starts < MIN_STARTS
        or item.defrosts < MIN_DEFROSTS
    }
    results["coverage"] = {
        "required": {"hours": MIN_WINDOW_H, "starts": MIN_STARTS, "defrosts": MIN_DEFROSTS},
        "runs": {
            name: {"hours": item.days * 24.0, "starts": item.starts, "defrosts": item.defrosts}
            for name, item in runs.items()
        },
        "short": short,
        "passed": not short,
    }
    return {
        "kpis": results,
        "passed": all(item["passed"] for item in results.values()),
        "b1": b1.to_json(),
        "real": [first.to_json(), second.to_json()],
    }


def compare(
    config: RunConfig, hours: float, speed: float, *, parallel: bool = True
) -> dict[str, Any]:
    """Run B1 and two real-service repeats over ``hours`` and judge the KPIs.

    Parameters
    ----------
    config
        Base configuration (start, plant, weather, profile).
    hours
        Window length in simulated hours.
    speed
        Clock speed of the real service.
    parallel
        Run the two real repeats in two processes at once.

    Returns
    -------
    dict
        Per-KPI verdicts and the overall ``passed``.
    """
    window = window_config(config, hours)
    if parallel:
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=2, mp_context=context) as pool:
            jobs = [pool.submit(real_window, window, speed) for _ in range(2)]
            b1 = b1_window(replace(window, out=window.out / "b1"))
            first, second = (_from_json(job.result()) for job in jobs)
    else:
        first = _from_json(real_window(window, speed))
        second = _from_json(real_window(window, speed))
        b1 = b1_window(replace(window, out=window.out / "b1"))
    verdict = judge(b1, first, second)
    verdict["window"] = {"from": window.start.isoformat(), "hours": hours, "speed": speed}
    return verdict

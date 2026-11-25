"""Each fault scenario alone at several start times: robust to when they run.

A full run with ``--faults`` places every scenario at one fixed slot, so a scenario
that passes there may still fail on a colder night or a milder afternoon. The sweep
runs every scenario on its own, at ``count`` start times spread over the span (and over
the hours of the day), each in a fresh run with a warm-up day before the scenario and
the scenario's window plus a tail after it. Runs are independent and go to a process
pool.

Examples
--------
Every scenario at eight start times over the recorded span::

    uv run python -m ovenbird_harness.fullrun --sweep 8

One scenario at one start time::

    uv run python -m ovenbird_harness.fullrun --fault mode_change --at 2025-11-12T03:00
"""

from __future__ import annotations

import logging
import math
import multiprocessing
import os
import shutil
import time
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from ovenbird_harness.faults import SCENARIOS, TAIL_S, WARMUP_S
from ovenbird_harness.fullrun import DB_FILES, FullRun, RunConfig

DAY_S: Final = 86_400.0
HOURS_PER_DAY: Final = 24


def window_s(name: str) -> float:
    """Return the assessment window of scenario ``name`` in seconds."""
    return SCENARIOS[name]().window_s


def single_span(
    at: datetime, names: Iterable[str], warmup_s: float = WARMUP_S
) -> tuple[datetime, datetime]:
    """Return the span of a run that starts ``names`` at ``at``.

    A warm-up (a day by default) before ``at``, the longest window and the tail after it.
    """
    longest = max(window_s(name) for name in names)
    return at - timedelta(seconds=warmup_s), at + timedelta(seconds=longest + TAIL_S)


def sweep_dates(start: datetime, end: datetime, window: float, count: int) -> list[datetime]:
    """Return ``count`` start times for a scenario with ``window`` inside ``start`` to ``end``.

    The days are spread evenly over the span (after a warm-up day, leaving the window
    and the tail before ``end``); the hour of the day steps by ``24 / count`` hours from
    one start to the next, so the starts cover night and day as well as the cold and
    mild parts of the span.

    Raises
    ------
    ValueError
        When ``count`` is not positive or the span cannot hold the window.
    """
    if count < 1:
        raise ValueError("the sweep needs at least one start time")
    earliest = start.timestamp() + WARMUP_S
    latest = end.timestamp() - window - TAIL_S
    if latest < earliest:
        raise ValueError(f"the span is too short for a {window / 3600:g} h window")
    dates: list[datetime] = []
    for index in range(count):
        centre = earliest + (index + 0.5) / count * (latest - earliest)
        midnight = math.floor(centre / DAY_S) * DAY_S
        hour = (index * HOURS_PER_DAY // count) % HOURS_PER_DAY
        moment = min(max(midnight + hour * 3600.0, earliest), latest)
        dates.append(datetime.fromtimestamp(math.floor(moment / 60.0) * 60.0, UTC))
    return dates


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y%m%dT%H%M")


def plan(
    base: RunConfig,
    names: Sequence[str],
    count: int,
    out: Path,
    *,
    dates: Sequence[datetime] | None = None,
    warmup_s: float = WARMUP_S,
) -> list[tuple[str, datetime, RunConfig]]:
    """Return one run per scenario and start time, each alone in its own directory.

    Parameters
    ----------
    base
        Template for every run (plant, weather, profile, seed); its span bounds the
        start times.
    names
        Scenarios to sweep.
    count
        Start times per scenario (:func:`sweep_dates`).
    out
        Sweep directory (``<out>/<scenario>/<start>`` for each run).
    dates
        Start times for every scenario instead of ``count`` spread ones.
    warmup_s
        Simulated time before each start.
    """
    runs: list[tuple[str, datetime, RunConfig]] = []
    for name in names:
        moments = (
            list(dates)
            if dates is not None
            else sweep_dates(base.start, base.end, window_s(name), count)
        )
        for at in moments:
            start, end = single_span(at, (name,), warmup_s)
            config = replace(
                base,
                start=start,
                end=end,
                out=out / name / _stamp(at),
                faults=(name,),
                fault_at=((name, at),),
                progress=False,
            )
            runs.append((name, at, config))
    return runs


def run_one(config: RunConfig, keep_history: bool = False) -> dict[str, Any]:
    """Run one sweep run and return its outcome (``pass``, ``fail`` or ``error``).

    The history database of a passed run is removed unless ``keep_history``.
    """
    began = time.perf_counter()
    name, at = config.fault_at[0]
    row: dict[str, Any] = {"name": name, "at": at.isoformat(), "out": str(config.out)}
    try:
        result = FullRun(config).run()
    except Exception as exc:
        row |= {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        row["wall_s"] = round(time.perf_counter() - began, 1)
        return row
    summary = result.summary
    (outcome,) = summary["faults"]
    invariants = summary["invariants"]
    row |= {
        "status": "pass" if result.passed else "fail",
        "scenario": outcome["status"],
        "outside_c": outcome.get("outside_c"),
        "failed_checks": [
            {"check": c["check"], "detail": c["detail"]}
            for c in outcome["checks"]
            if c["status"] != "pass"
        ],
        "violations": {rule: n for rule, n in invariants["by_rule"].items() if n},
        "first_violations": invariants["first"][:5],
        "notes": outcome["notes"],
        "wall_s": round(time.perf_counter() - began, 1),
    }
    if result.passed and not keep_history:
        for item in DB_FILES:
            (config.out / item).unlink(missing_ok=True)
    return row


def _quiet(level: str) -> None:
    logging.basicConfig(level=level.upper(), format="%(levelname)s %(name)s %(message)s")


def run_sweep(
    runs: Sequence[tuple[str, datetime, RunConfig]],
    jobs: int,
    log_level: str = "CRITICAL",
    keep_history: bool = False,
) -> list[dict[str, Any]]:
    """Run ``runs`` on ``jobs`` processes and return their outcomes in order."""
    configs = [config for _, _, config in runs]
    for config in configs:
        if config.out.exists():
            shutil.rmtree(config.out)
    if jobs <= 1:
        return [run_one(config, keep_history) for config in configs]
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=jobs, mp_context=context, initializer=_quiet, initargs=(log_level,)
    ) as pool:
        return list(pool.map(run_one, configs, [keep_history] * len(configs)))


def default_jobs() -> int:
    """Return the default number of worker processes (all cores but two)."""
    return max(1, (os.cpu_count() or 1) - 2)


def matrix(rows: Sequence[dict[str, Any]]) -> str:
    """Return the matrix of scenarios and start times as text."""
    names = list(dict.fromkeys(row["name"] for row in rows))
    by_name = {name: [row for row in rows if row["name"] == name] for name in names}
    width = max(len(name) for name in names)
    count = max(len(items) for items in by_name.values())
    header = " ".join(f"{index + 1:>5}" for index in range(count))
    lines = [f"{'scenario':<{width}}  {header}"]
    for name, items in by_name.items():
        marks = " ".join(
            f"{'pass' if r['status'] == 'pass' else r['status'].upper():>5}" for r in items
        )
        lines.append(f"{name:<{width}}  {marks}")
    lines.append("")
    for name, items in by_name.items():
        for index, row in enumerate(items):
            outside = row.get("outside_c") or {}
            mean = outside.get("mean")
            temp = f"{mean:5.1f} °C" if isinstance(mean, (int, float)) else "     -  "
            lines.append(
                f"{name:<{width}}  {index + 1:>2} {row['at'][:16]}  {temp}  {row['status']}"
            )
            for check in row.get("failed_checks", []):
                lines.append(f"{'':<{width}}       ✗ {check['check']}: {check['detail']}")
            for rule, n in row.get("violations", {}).items():
                lines.append(f"{'':<{width}}       ✗ invariant {rule}: {n}")
            if row["status"] == "error":
                lines.append(f"{'':<{width}}       ✗ {row['error']}")
    return "\n".join(lines)

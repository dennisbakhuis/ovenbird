"""Compressor run lengths and period figures for the trial summary.

**Runs** come from the 1 min rollups of ``main/Compressor_Freq``. The running
seconds of a minute follow the same rule as ``insight/daily``'s ``run_s`` (all of
its data when the lowest frequency is at least 1 Hz, none when the highest is below,
otherwise the share the mean implies); a run is a stretch of consecutive minutes with
running seconds, its length the sum of them (1 min resolution). A minute without a
rollup is a gap: a run that touches a gap or the end of the data is not complete and
is left out of the statistics (``censored``), and an off time is counted only
between two complete runs without a gap in between. Runs are assigned to the local
day they started on; a run that started before the window is not counted.

Statistics: count, median, mean, longest, the share of runs shorter than
:data:`SHORT_RUN_MIN` minutes (the cut-over criterion "share of runs < 20 min not
worse"), a histogram and the shortest off time between two runs.
"""

from __future__ import annotations

import math
import sqlite3
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from ovenbird.clock import iso_from_unix
from ovenbird.history.schema import connect
from ovenbird.insight.daily import RUNNING_HZ, LocalDay, local_days
from ovenbird_core import HeishaSignal

MINUTE: Final = 60
SHORT_RUN_MIN: Final = 20.0
LOOKBACK_S: Final = 86_400.0
MAX_DAYS: Final = 90
BINS_MIN: Final = (0, 10, 20, 30, 60, 120, 240)
COMPRESSOR: Final = HeishaSignal.COMPRESSOR_FREQ.value


@dataclass(frozen=True, slots=True)
class Run:
    """One compressor run.

    Parameters
    ----------
    start, end
        First minute and the minute after the last (unix seconds).
    run_s
        Running seconds.
    complete
        Neither end touches a gap or the end of the data.
    off_before_s
        Off time since the previous complete run (``None`` when not measurable).
    """

    start: int
    end: int
    run_s: float
    complete: bool
    off_before_s: float | None

    @property
    def minutes(self) -> float:
        """Length in minutes."""
        return self.run_s / 60.0


def _signal_id(conn: sqlite3.Connection, name: str) -> int | None:
    """Return the id of a signal that has rollups, or ``None``."""
    if (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'rollup'"
        ).fetchone()
        is None
    ):
        return None
    row = conn.execute("SELECT id FROM signal WHERE name = ?", (name,)).fetchone()
    return None if row is None else int(row[0])


def _running(minimum: float, maximum: float, weighted: float, duration: float) -> float:
    """Return the seconds of a bucket the compressor ran, from its minimum, maximum and mean.

    Parameters
    ----------
    minimum
        Lowest compressor frequency in the bucket, in Hz.
    maximum
        Highest compressor frequency in the bucket, in Hz.
    weighted
        Time-weighted sum of the frequency, in Hz times seconds.
    duration
        Covered length of the bucket, in seconds.
    """
    if minimum >= RUNNING_HZ:
        return duration
    if maximum < RUNNING_HZ or duration <= 0 or maximum <= 0:
        return 0.0
    return duration * min(1.0, weighted / duration / maximum)


def compressor_minutes(path: Path, start: float, end: float) -> dict[int, float]:
    """Return the running seconds per minute bucket in ``[start, end)`` (missing: no data)."""
    if not path.exists():
        return {}
    conn = connect(path, read_only=True)
    try:
        signal_id = _signal_id(conn, COMPRESSOR)
        if signal_id is None:
            return {}
        rows = conn.execute(
            "SELECT bucket, minimum, maximum, weighted_sum, duration FROM rollup "
            "WHERE step = ? AND signal_id = ? AND bucket >= ? AND bucket < ? ORDER BY bucket",
            (MINUTE, signal_id, math.floor(start / MINUTE) * MINUTE, end),
        ).fetchall()
    finally:
        conn.close()
    return {
        int(bucket): _running(float(lo), float(hi), float(ws), float(dur))
        for bucket, lo, hi, ws, dur in rows
    }


def find_runs(data: dict[int, float], start: float, end: float) -> list[Run]:
    """Return the runs in the minute data covering ``[start, end)``, oldest first.

    Parameters
    ----------
    data
        Running seconds per minute bucket (see :func:`compressor_minutes`).
    start, end
        Range of the data (a run reaching either edge is not complete).

    Returns
    -------
    list of Run
        Every run; ``off_before_s`` only between two complete runs without a gap.
    """
    first = int(math.floor(start / MINUTE) * MINUTE)
    grid = range(first, int(math.ceil(end / MINUTE) * MINUTE), MINUTE)
    runs: list[Run] = []
    current: list[int] = []
    seconds = 0.0
    starts_clean = False
    off_s: float | None = None
    previous_complete = False

    def close(clean_end: bool) -> None:
        """End the current run and start the next."""
        nonlocal current, seconds, off_s, previous_complete
        complete = starts_clean and clean_end
        off = off_s if complete and previous_complete else None
        runs.append(Run(current[0], current[-1] + MINUTE, seconds, complete, off))
        previous_complete = complete
        current, seconds, off_s = [], 0.0, 0.0 if clean_end else None

    for ts in grid:
        value = data.get(ts)
        if value is None:
            if current:
                close(False)
            off_s = None
            previous_complete = False
            continue
        if value > 0:
            if not current:
                starts_clean = ts != first and data.get(ts - MINUTE) is not None
            current.append(ts)
            seconds += value
            continue
        if current:
            close(True)
        if off_s is not None:
            off_s += MINUTE
    if current:
        close(False)
    return runs


def run_stats(runs: Sequence[Run]) -> dict[str, Any]:
    """Return the statistics of the complete runs in ``runs``."""
    complete = [run for run in runs if run.complete]
    lengths = [run.minutes for run in complete]
    short = sum(1 for length in lengths if length < SHORT_RUN_MIN)
    offs = [run.off_before_s / 60.0 for run in complete if run.off_before_s is not None]
    bins = []
    for index, low in enumerate(BINS_MIN):
        high = BINS_MIN[index + 1] if index + 1 < len(BINS_MIN) else None
        count = sum(1 for length in lengths if length >= low and (high is None or length < high))
        bins.append({"from_min": low, "to_min": high, "runs": count})
    return {
        "runs": len(complete),
        "censored": len(runs) - len(complete),
        "short_runs": short,
        "short_share": round(short / len(lengths), 3) if lengths else None,
        "median_min": round(statistics.median(lengths), 1) if lengths else None,
        "mean_min": round(statistics.fmean(lengths), 1) if lengths else None,
        "longest_min": round(max(lengths), 1) if lengths else None,
        "min_off_min": round(min(offs), 1) if offs else None,
        "histogram": bins,
    }


def runs_between(path: Path, start: float, end: float) -> list[Run]:
    """Return the runs that started in ``[start, end)`` (data read from a day earlier)."""
    data = compressor_minutes(path, start - LOOKBACK_S, end)
    return [run for run in find_runs(data, start - LOOKBACK_S, end) if start <= run.start < end]


def runs_payload(path: Path, *, now: datetime, days: int, timezone: str) -> dict[str, Any]:
    """Return the body of ``GET api/v1/insight/runs``.

    Parameters
    ----------
    path
        History database.
    now
        Service-clock time (today is the last day).
    days
        Local days, today included (1 to :data:`MAX_DAYS`).
    timezone
        IANA time zone of the day boundaries.

    Returns
    -------
    dict
        ``short_run_min``, ``timezone``, ``total`` and one entry per day.

    Raises
    ------
    ValueError
        When ``days`` is outside 1 to :data:`MAX_DAYS`.
    """
    if not 1 <= days <= MAX_DAYS:
        raise ValueError(f"days must be between 1 and {MAX_DAYS}")
    windows: list[LocalDay] = local_days(now, days, timezone)
    stamp = now.timestamp()
    data = compressor_minutes(path, windows[0].start - LOOKBACK_S, stamp)
    every = find_runs(data, windows[0].start - LOOKBACK_S, stamp)
    selected = [run for run in every if windows[0].start <= run.start < stamp]
    rows = []
    for day in windows:
        inside = [run for run in selected if day.start <= run.start < day.end]
        rows.append(
            {
                "date": day.date.isoformat(),
                "from": iso_from_unix(day.start),
                "to": iso_from_unix(day.end),
                "partial": stamp < day.end,
                **run_stats(inside),
            }
        )
    return {
        "timezone": timezone,
        "short_run_min": SHORT_RUN_MIN,
        "signal": COMPRESSOR,
        "total": run_stats(selected),
        "days": rows,
    }


def signal_period(path: Path, signal: str | None, start: float, end: float) -> dict[str, Any]:
    """Return the time-weighted mean, the minimum and the covered hours of ``signal``.

    From the 1 min rollups over ``[start, end)``; ``None`` figures without data.

    Parameters
    ----------
    path
        History database file.
    signal
        Signal to summarise; ``None`` gives no data.
    start
        Start of the period, Unix time.
    end
        End of the period, Unix time.
    """
    empty: dict[str, Any] = {"mean": None, "min": None, "hours": 0.0}
    if signal is None or not path.exists():
        return empty
    conn = connect(path, read_only=True)
    try:
        signal_id = _signal_id(conn, signal)
        if signal_id is None:
            return empty
        row = conn.execute(
            "SELECT SUM(weighted_sum), SUM(duration), MIN(minimum) FROM rollup "
            "WHERE step = ? AND signal_id = ? AND bucket >= ? AND bucket < ?",
            (MINUTE, signal_id, start, end),
        ).fetchone()
    finally:
        conn.close()
    weighted, covered, lowest = row
    if not covered:
        return empty
    return {
        "mean": round(float(weighted) / float(covered), 2),
        "min": None if lowest is None else round(float(lowest), 2),
        "hours": round(float(covered) / 3600.0, 2),
    }


def journal_counts(path: Path, start: float, end: float) -> dict[str, int | None]:
    """Return the ``sent`` commands and the raised ``pump_error`` alarms in ``[start, end)``."""
    counts: dict[str, int | None] = {"writes": None, "pump_errors": None}
    if not path.exists():
        return counts
    conn = connect(path, read_only=True)
    try:
        tables = {
            str(name)
            for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        if "command" in tables:
            row = conn.execute(
                "SELECT COUNT(*) FROM command WHERE status = 'sent' AND ts >= ? AND ts < ?",
                (start, end),
            ).fetchone()
            counts["writes"] = int(row[0])
        if "alarm" in tables:
            row = conn.execute(
                "SELECT COUNT(*) FROM alarm WHERE code = 'pump_error' AND event = 'raised' "
                "AND ts >= ? AND ts < ?",
                (start, end),
            ).fetchone()
            counts["pump_errors"] = int(row[0])
    finally:
        conn.close()
    return counts

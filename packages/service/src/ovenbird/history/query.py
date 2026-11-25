"""Read history series for the API from a read-only connection."""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ovenbird.history.database import ROLLUP_STEPS, SampleKind
from ovenbird.history.schema import connect
from ovenbird_core import CATALOGUE, SourceKind, StalenessPolicy

STEPS: Final = (0, *ROLLUP_STEPS)
TARGET_POINTS: Final = 1500
MAX_GRID_POINTS: Final = 100_000
MAX_RAW_POINTS: Final = 100_000
DECIMALS: Final = 4

type Point = tuple[float, float | None]


class HistoryQueryError(ValueError):
    """The request cannot be answered (window too long for the step)."""


@dataclass(frozen=True, slots=True)
class Series:
    """One signal's points.

    Parameters
    ----------
    unit
        Unit of the values; ``None`` when unknown.
    points
        ``(unix_seconds, value)`` pairs; ``value`` is ``None`` for empty buckets.
    """

    unit: str | None
    points: tuple[Point, ...]


def default_step(start: float, end: float) -> int:
    """Return the finest rollup step that keeps a series at about 1,500 points or fewer."""
    span = max(0.0, end - start)
    for step in ROLLUP_STEPS:
        if span / step <= TARGET_POINTS:
            return step
    return ROLLUP_STEPS[-1]


def staleness_limit(signal: str, policy: StalenessPolicy) -> float:
    """Return the maximum age in seconds of ``signal``'s value, inferred from its id."""
    if signal.startswith("ha/"):
        source = SourceKind.HA
    elif signal in CATALOGUE:
        source = SourceKind.HEISHAMON
    else:
        source = SourceKind.MQTT
    return policy.max_age(signal, source)


def _round(value: float) -> float:
    return round(value, DECIMALS)


def query_series(
    path: Path,
    signals: Sequence[str],
    start: float,
    end: float,
    step: int,
    staleness: StalenessPolicy | None = None,
) -> dict[str, Series]:
    """Read aligned series for ``signals`` over ``[start, end)``.

    Parameters
    ----------
    path
        Database file; a missing file yields empty series.
    signals
        Signal ids.
    start, end
        Window in unix seconds.
    step
        0 for raw samples (value changes, at their own timestamps), otherwise a rollup
        step; every rollup series (also of unknown signals) covers the same grid of
        bucket starts, with ``None`` for buckets without data. Numbers are
        time-weighted means, enums and flags the last value. A raw series starts
        with the value held at ``start`` (the last change before it, reported at
        ``start``), so a signal unchanged inside the window still has a point; the
        seed is omitted when that last change is older than the signal's staleness
        limit before ``start``.
    staleness
        Staleness policy bounding the seed; the defaults when omitted.

    Returns
    -------
    dict
        Series per requested signal id.

    Raises
    ------
    HistoryQueryError
        When the step is unknown or the grid would be too large.
    """
    if step not in STEPS:
        raise HistoryQueryError(f"step must be one of {', '.join(map(str, STEPS))}")
    first_bucket = math.floor(start / step) * step if step else 0
    if step and (end - first_bucket) / step > MAX_GRID_POINTS:
        raise HistoryQueryError("window too long for this step")
    blank = _grid({}, first_bucket, end, step) if step else ()
    empty = {signal: Series(None, blank) for signal in signals}
    if not path.exists():
        return empty
    conn = connect(path, read_only=True)
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'signal'"
        ).fetchone():
            return empty
        policy = staleness or StalenessPolicy()
        result: dict[str, Series] = {}
        for signal in signals:
            row = conn.execute(
                "SELECT id, unit, kind FROM signal WHERE name = ?", (signal,)
            ).fetchone()
            if row is None:
                result[signal] = Series(None, blank)
                continue
            signal_id, unit, kind = int(row[0]), row[1], SampleKind(row[2])
            if step == 0:
                points = _raw(conn, signal_id, start, end, staleness_limit(signal, policy))
            else:
                points = _rollup(conn, signal_id, kind, first_bucket, end, step)
            result[signal] = Series(unit, points)
        return result
    finally:
        conn.close()


def _raw(
    conn: sqlite3.Connection, signal_id: int, start: float, end: float, max_age: float
) -> tuple[Point, ...]:
    rows = conn.execute(
        "SELECT ts, value FROM sample WHERE signal_id = ? AND ts >= ? AND ts < ? "
        "ORDER BY ts LIMIT ?",
        (signal_id, start, end, MAX_RAW_POINTS),
    ).fetchall()
    points = [(float(ts), _round(float(value))) for ts, value in rows]
    if not points or points[0][0] > start:
        seed = conn.execute(
            "SELECT value FROM sample WHERE signal_id = ? AND ts < ? AND ts >= ? "
            "ORDER BY ts DESC LIMIT 1",
            (signal_id, start, start - max_age),
        ).fetchone()
        if seed is not None:
            points.insert(0, (start, _round(float(seed[0]))))
    return tuple(points[:MAX_RAW_POINTS])


def _rollup(
    conn: sqlite3.Connection,
    signal_id: int,
    kind: SampleKind,
    first_bucket: int,
    end: float,
    step: int,
) -> tuple[Point, ...]:
    rows = conn.execute(
        "SELECT bucket, weighted_sum, duration, last FROM rollup "
        "WHERE step = ? AND signal_id = ? AND bucket >= ? AND bucket < ? ORDER BY bucket",
        (step, signal_id, first_bucket, end),
    ).fetchall()
    values: dict[int, float] = {}
    for bucket, weighted_sum, duration, last in rows:
        if kind is SampleKind.NUMBER and duration > 0:
            values[int(bucket)] = _round(weighted_sum / duration)
        else:
            values[int(bucket)] = _round(float(last))
    return _grid(values, first_bucket, end, step)


def _grid(values: dict[int, float], first_bucket: int, end: float, step: int) -> tuple[Point, ...]:
    return tuple(
        (float(bucket), values.get(bucket)) for bucket in range(first_bucket, math.ceil(end), step)
    )

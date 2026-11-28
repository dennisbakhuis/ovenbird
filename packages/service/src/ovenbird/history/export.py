"""Read history for bulk export: the signal inventory, series by day and journal rows.

Every reader works in bounded pieces (one UTC day of series, a few hundred journal
rows), each read in its own short transaction, so an export of any length never
holds much memory nor the database. The range is first clamped to the data present,
so a request for years of nothing costs nothing.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ovenbird.clock import iso_from_unix
from ovenbird.history.database import ROLLUP_STEPS, SECONDS_PER_DAY, SampleKind
from ovenbird.history.query import DECIMALS, HistoryQueryError, staleness_limit
from ovenbird.history.schema import connect
from ovenbird.sql import sql
from ovenbird_core import StalenessPolicy

STEPS: Final = (0, *ROLLUP_STEPS)
CHUNK_S: Final = int(SECONDS_PER_DAY)
BATCH: Final = 500
COMMAND_COLUMNS: Final = ("ts", "kind", "value", "status", "attempt", "topic", "payload", "detail")
ALARM_COLUMNS: Final = ("ts", "code", "severity", "event", "message", "detail")
FORECAST_COLUMNS: Final = (
    "issued_ts",
    "target_ts",
    "temp_c",
    "radiation_wm2",
    "cloud_pct",
    "wind_ms",
)


@dataclass(frozen=True, slots=True)
class SignalInfo:
    """One stored signal.

    Parameters
    ----------
    name
        Signal id.
    unit
        Unit, when known.
    kind
        ``number``, ``enum`` or ``bool``.
    db_id
        Row id in ``signal``.
    """

    name: str
    unit: str | None
    kind: str
    db_id: int


@dataclass(frozen=True, slots=True)
class Point:
    """One exported value.

    Parameters
    ----------
    ts
        Unix seconds (a rollup's bucket start).
    signal
        Index into the exported signals.
    value
        Raw value, or the rollup's mean (numbers) or last value (enums, flags).
    minimum, maximum
        Rollup extremes; ``None`` for raw samples.
    """

    ts: float
    signal: int
    value: float
    minimum: float | None = None
    maximum: float | None = None


def _round(value: float) -> float:
    """Round ``value`` to the precision of the export."""
    return round(value, DECIMALS)


def _open(path: Path, table: str) -> sqlite3.Connection | None:
    """Open the history read-only if it exists and has ``table``, else return ``None``."""
    if not path.exists():
        return None
    conn = connect(path, read_only=True)
    found = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    if found is None:
        conn.close()
        return None
    return conn


def stored_signals(path: Path) -> list[SignalInfo]:
    """Return every stored signal, by id."""
    conn = _open(path, "signal")
    if conn is None:
        return []
    try:
        rows = conn.execute("SELECT name, unit, kind, id FROM signal ORDER BY name").fetchall()
    finally:
        conn.close()
    return [SignalInfo(str(name), unit, str(kind), int(db_id)) for name, unit, kind, db_id in rows]


def signal_inventory(path: Path) -> list[dict[str, Any]]:
    """Return the body items of ``GET api/v1/history/signals``: ranges per resolution.

    Parameters
    ----------
    path
        History database.
    """
    signals = stored_signals(path)
    if not signals:
        return []
    conn = connect(path, read_only=True)
    try:
        items = []
        for info in signals:
            resolutions = []
            count, first, last = conn.execute(
                "SELECT count(*), min(ts), max(ts) FROM sample WHERE signal_id = ?",
                (info.db_id,),
            ).fetchone()
            if count:
                resolutions.append(_range(0, first, last, count))
            for step in ROLLUP_STEPS:
                count, first, last = conn.execute(
                    "SELECT count(*), min(bucket), max(bucket) FROM rollup "
                    "WHERE step = ? AND signal_id = ?",
                    (step, info.db_id),
                ).fetchone()
                if count:
                    resolutions.append(_range(step, first, last, count))
            items.append(
                {"id": info.name, "unit": info.unit, "kind": info.kind, "resolutions": resolutions}
            )
        return items
    finally:
        conn.close()


def _range(step: int, first: float, last: float, count: int) -> dict[str, Any]:
    """Return the API item of one resolution: step, first and last time, and number of points.

    Parameters
    ----------
    step
        Resolution in seconds (0 for raw samples).
    first, last
        Time of the first and last point, Unix seconds.
    count
        Number of points.
    """
    return {
        "step": step,
        "first": iso_from_unix(float(first)),
        "last": iso_from_unix(float(last)),
        "points": int(count),
    }


def resolve_signals(path: Path, requested: Sequence[str] | None) -> list[SignalInfo]:
    """Return the stored signals to export, in request order (all, by id, for ``None``).

    Raises
    ------
    HistoryQueryError
        When a requested id is not stored.
    """
    stored = stored_signals(path)
    if requested is None:
        return stored
    by_name = {info.name: info for info in stored}
    unknown = [name for name in requested if name not in by_name]
    if unknown:
        shown = ", ".join(unknown[:5])
        raise HistoryQueryError(f"no stored history for signal(s): {shown}")
    return [by_name[name] for name in requested]


def data_range(path: Path, signals: Sequence[SignalInfo], step: int) -> tuple[float, float] | None:
    """Return the first and the end of the data of ``signals`` at ``step``; ``None`` when empty.

    Parameters
    ----------
    path
        History database.
    signals
        Signals of the export.
    step
        Resolution in seconds (0 for raw samples).
    """
    if step not in STEPS:
        raise HistoryQueryError(f"step must be one of {', '.join(map(str, STEPS))}")
    if not signals or not path.exists():
        return None
    ids = [info.db_id for info in signals]
    conn = connect(path, read_only=True)
    try:
        if step == 0:
            row = conn.execute(
                sql(
                    "SELECT min(ts), max(ts) FROM sample WHERE signal_id IN ({marks})",
                    marks=len(ids),
                ),
                ids,
            ).fetchone()
            extra = 1e-6
        else:
            row = conn.execute(
                sql(
                    "SELECT min(bucket), max(bucket) FROM rollup WHERE step = ? "
                    "AND signal_id IN ({marks})",
                    marks=len(ids),
                ),
                (step, *ids),
            ).fetchone()
            extra = float(step)
    finally:
        conn.close()
    if row is None or row[0] is None:
        return None
    return float(row[0]), float(row[1]) + extra


def series_chunks(
    path: Path,
    signals: Sequence[SignalInfo],
    start: float,
    end: float,
    step: int,
    staleness: StalenessPolicy | None = None,
) -> Iterator[list[Point]]:
    """Yield the points of ``signals`` in ``[start, end)``, one UTC day per list, oldest first.

    Raw points are the stored value changes; the first day starts with the value each
    signal held at ``start`` (as ``GET api/v1/history`` reports it). Rollup points are
    the stored buckets (``start`` rounded down to the step); empty buckets are left
    out. Points of one timestamp follow the order of ``signals``.

    Parameters
    ----------
    path
        History database.
    signals
        From :func:`resolve_signals`.
    start, end
        Requested window in unix seconds; clamped to the data present.
    step
        0 (raw) or a rollup step.
    staleness
        Bounds the raw seed, as for the history endpoint.
    """
    present = data_range(path, signals, step)
    if present is None:
        return
    if step == 0:
        low, high = start, min(end, max(present[1], start + 1e-6))
        first_data = max(start, present[0])
    else:
        low, high = max(math.floor(start / step) * step, present[0]), min(end, present[1])
        first_data = low
    if low >= high:
        return
    order = {info.db_id: index for index, info in enumerate(signals)}
    kinds = {info.db_id: SampleKind(info.kind) for info in signals}
    ids = list(order)
    policy = staleness or StalenessPolicy()
    seeded = False
    chunk_start = math.floor(min(first_data, high) / CHUNK_S) * CHUNK_S
    while chunk_start < high:
        lo = max(low, chunk_start)
        hi = min(high, chunk_start + CHUNK_S)
        conn = connect(path, read_only=True)
        try:
            if step == 0:
                points = []
                if not seeded:
                    points = _seed(conn, signals, start, policy)
                    seeded = True
                rows = conn.execute(
                    sql(
                        "SELECT signal_id, ts, value FROM sample WHERE ts >= ? AND ts < ? "
                        "AND signal_id IN ({marks}) ORDER BY ts",
                        marks=len(ids),
                    ),
                    (lo, hi, *ids),
                ).fetchall()
                found = [
                    Point(float(ts), order[sid], _round(float(value))) for sid, ts, value in rows
                ]
                points.extend(sorted(found, key=lambda p: (p.ts, p.signal)))
            else:
                rows = conn.execute(
                    sql(
                        "SELECT signal_id, bucket, weighted_sum, duration, minimum, maximum, last "
                        "FROM rollup WHERE step = ? AND bucket >= ? AND bucket < ? "
                        "AND signal_id IN ({marks}) ORDER BY bucket",
                        marks=len(ids),
                    ),
                    (step, lo, hi, *ids),
                ).fetchall()
                points = sorted(
                    (_rollup_point(order[sid], kinds[sid], *rest) for sid, *rest in rows),
                    key=lambda p: (p.ts, p.signal),
                )
        finally:
            conn.close()
        if points:
            yield points
        chunk_start += CHUNK_S


def _seed(
    conn: sqlite3.Connection,
    signals: Sequence[SignalInfo],
    start: float,
    policy: StalenessPolicy,
) -> list[Point]:
    """Return each signal's last value at or before ``start`` that is still fresh.

    These values start a series.

    Parameters
    ----------
    conn
        Open history connection.
    signals
        Signals of the export.
    start
        Start of the export, Unix seconds.
    policy
        How long a value of each signal stays fresh.
    """
    points = []
    for index, info in enumerate(signals):
        max_age = staleness_limit(info.name, policy)
        row = conn.execute(
            "SELECT ts, value FROM sample WHERE signal_id = ? AND ts <= ? AND ts >= ? "
            "ORDER BY ts DESC LIMIT 1",
            (info.db_id, start, start - max_age),
        ).fetchone()
        if row is not None and float(row[0]) < start:
            points.append(Point(start, index, _round(float(row[1]))))
    return points


def _rollup_point(
    index: int,
    kind: SampleKind,
    bucket: float,
    weighted_sum: float,
    duration: float,
    minimum: float,
    maximum: float,
    last: float,
) -> Point:
    """Return the export point of a roll-up bucket: time-weighted mean, or last value.

    The mean applies to numbers; other kinds keep the last value.

    Parameters
    ----------
    index
        Position of the signal in the export.
    kind
        Sample kind of the signal.
    bucket
        Bucket start, Unix seconds.
    weighted_sum
        Sum of value times duration over the bucket.
    duration
        Seconds of data in the bucket.
    minimum, maximum
        Extremes in the bucket.
    last
        Last value in the bucket.
    """
    numeric = kind is SampleKind.NUMBER and duration > 0
    value = weighted_sum / duration if numeric else last
    return Point(float(bucket), index, _round(value), _round(minimum), _round(maximum))


def iter_rows(
    path: Path,
    table: str,
    columns: Sequence[str],
    keys: Sequence[str],
    start: float,
    end: float,
    batch: int = BATCH,
) -> Iterator[tuple[Any, ...]]:
    """Yield the rows of ``table`` whose first key is in ``[start, end)``, in key order.

    Parameters
    ----------
    path
        History database.
    table
        ``command``, ``alarm`` or ``forecast``.
    columns
        Columns to return.
    keys
        Two columns that order the rows uniquely (time first).
    start, end
        Window on the first key, unix seconds.
    batch
        Rows per read.
    """
    conn = _open(path, table)
    if conn is None:
        return
    first, second = keys
    select = ", ".join((*columns, first, second))
    try:
        after: tuple[Any, Any] | None = None
        while True:
            if after is None:
                rows = conn.execute(
                    sql(
                        "SELECT {columns} FROM {table} WHERE {first} >= ? AND {first} < ? "
                        "ORDER BY {first}, {second} LIMIT ?",
                        columns=select,
                        table=table,
                        first=first,
                        second=second,
                    ),
                    (start, end, batch),
                ).fetchall()
            else:
                rows = conn.execute(
                    sql(
                        "SELECT {columns} FROM {table} WHERE {first} >= ? AND {first} < ? "
                        "AND ({first} > ? OR ({first} = ? AND {second} > ?)) "
                        "ORDER BY {first}, {second} LIMIT ?",
                        columns=select,
                        table=table,
                        first=first,
                        second=second,
                    ),
                    (start, end, after[0], after[0], after[1], batch),
                ).fetchall()
            if not rows:
                return
            after = (rows[-1][-2], rows[-1][-1])
            for row in rows:
                yield tuple(row[: len(columns)])
            if len(rows) < batch:
                return
    finally:
        conn.close()

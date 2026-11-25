"""What ``history.db`` holds and how large it is: per table, per resolution, projected.

Table sizes come from SQLite's ``dbstat`` table (pages used per table and index);
where SQLite was built without it the byte figures are ``None`` and only the row
counts and time ranges are reported. The daily growth of a resolution is its present
size divided by the time it covers; the projection multiplies that rate by the
retention (data kept forever counts with its present size, plus its yearly growth).
The same projection is made for each retention preset of Settings → Data.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ovenbird.clock import iso_from_unix
from ovenbird.history.database import ROLLUP_STEPS, SECONDS_PER_DAY, Retention
from ovenbird.history.schema import connect
from ovenbird.history.settings import RETENTION_PRESETS, preset_retention

MIN_SPAN_S: Final = 3600.0
DAYS_PER_YEAR: Final = 365.0
AUTO_VACUUM: Final = {0: "none", 1: "full", 2: "incremental"}
JOURNAL_TABLES: Final = (
    "decision",
    "decision_ts",
    "decision_dictionary",
    "command",
    "command_ts",
    "alarm",
    "alarm_ts",
)
RAW_TABLES: Final = ("sample", "sample_ts")
ROLLUP_TABLES: Final = ("rollup", "rollup_step_bucket")
FORECAST_TABLES: Final = ("forecast", "forecast_target")
COUNTED: Final = ("sample", "rollup", "decision", "command", "alarm", "forecast", "signal")


@dataclass(frozen=True, slots=True)
class Span:
    """Rows and time range of one resolution.

    Parameters
    ----------
    rows
        Row count.
    oldest, newest
        Unix seconds of the first and last row; ``None`` when empty.
    """

    rows: int
    oldest: float | None
    newest: float | None


def file_bytes(path: Path) -> int | None:
    """Size of ``path`` in bytes; ``None`` when it does not exist."""
    try:
        return path.stat().st_size
    except OSError:
        return None


def table_bytes(conn: sqlite3.Connection) -> dict[str, int] | None:
    """Bytes of pages per table and index, from ``dbstat``; ``None`` when unavailable."""
    try:
        rows = conn.execute("SELECT name, sum(pgsize) FROM dbstat GROUP BY name").fetchall()
    except sqlite3.Error:
        return None
    return {str(name): int(size) for name, size in rows}


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master")}


def _span(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Span:
    rows, oldest, newest = conn.execute(sql, params).fetchone()
    return Span(
        int(rows or 0),
        None if oldest is None else float(oldest),
        None if newest is None else float(newest),
    )


def spans(conn: sqlite3.Connection) -> dict[str, Span]:
    """Rows and time range per resolution (raw, the rollup steps, journal, forecast)."""
    tables = _tables(conn)
    empty = Span(0, None, None)
    found: dict[str, Span] = {}
    found["raw"] = (
        _span(conn, "SELECT count(*), min(ts), max(ts) FROM sample")
        if "sample" in tables
        else empty
    )
    for step in ROLLUP_STEPS:
        found[str(step)] = (
            _span(
                conn,
                "SELECT count(*), min(bucket), max(bucket) + ? FROM rollup WHERE step = ?",
                (step, step),
            )
            if "rollup" in tables
            else empty
        )
    journal = [
        _span(conn, f"SELECT count(*), min(ts), max(ts) FROM {name}")  # noqa: S608
        for name in ("decision", "command", "alarm")
        if name in tables
    ]
    oldest = [item.oldest for item in journal if item.oldest is not None]
    newest = [item.newest for item in journal if item.newest is not None]
    found["journal"] = Span(
        sum(item.rows for item in journal),
        min(oldest) if oldest else None,
        max(newest) if newest else None,
    )
    found["forecast"] = (
        _span(conn, "SELECT count(*), min(issued_ts), max(issued_ts) FROM forecast")
        if "forecast" in tables
        else empty
    )
    return found


def resolution_bytes(sizes: Mapping[str, int], found: Mapping[str, Span]) -> dict[str, int]:
    """Split the table sizes over the resolutions (rollups by their share of rows)."""
    rollup = sum(sizes.get(name, 0) for name in ROLLUP_TABLES)
    rollup_rows = sum(found[str(step)].rows for step in ROLLUP_STEPS)
    result = {
        "raw": sum(sizes.get(name, 0) for name in RAW_TABLES),
        "journal": sum(sizes.get(name, 0) for name in JOURNAL_TABLES),
        "forecast": sum(sizes.get(name, 0) for name in FORECAST_TABLES),
    }
    for step in ROLLUP_STEPS:
        share = found[str(step)].rows / rollup_rows if rollup_rows else 0.0
        result[str(step)] = round(rollup * share)
    return result


def retention_days(retention: Retention, journal_days: float | None) -> dict[str, float | None]:
    """Retention per resolution in days (``None`` keeps it forever)."""
    return {
        "raw": retention.raw_days,
        "60": retention.minute_days,
        "900": retention.quarter_days,
        "3600": retention.hour_days,
        "journal": journal_days,
        "forecast": retention.hour_days,
    }


def _per_day(size: int | None, span: Span) -> float | None:
    if size is None or span.oldest is None or span.newest is None:
        return None
    covered = span.newest - span.oldest
    if covered < MIN_SPAN_S:
        return None
    return size / (covered / SECONDS_PER_DAY)


def storage_report(
    path: Path,
    snapshot: Path | None,
    retention: Retention,
    journal_days: float | None,
    free_bytes: int | None,
) -> dict[str, Any]:
    """Return the body of ``GET api/v1/history/storage`` (without the compaction state).

    Parameters
    ----------
    path
        ``history.db``.
    snapshot
        The backup snapshot, when snapshots are enabled.
    retention, journal_days
        The retention in effect.
    free_bytes
        Free space in the data directory.

    Returns
    -------
    dict
        Files, tables, resolutions and the projection (see ``docs/api-v1.md``).
    """
    files = {
        "database": file_bytes(path) or 0,
        "wal": file_bytes(path.with_name(path.name + "-wal")) or 0,
        "snapshot": file_bytes(snapshot) if snapshot is not None else None,
        "free": free_bytes,
    }
    body: dict[str, Any] = {
        "files": files,
        "tables": [],
        "resolutions": [],
        "projected_bytes": None,
        "growth_bytes_per_year": None,
        "reclaimable_bytes": 0,
        "auto_vacuum": "none",
        "presets": [],
        "preset": current_preset(retention, journal_days),
    }
    days = retention_days(retention, journal_days)
    if not path.exists():
        body["resolutions"] = [
            _resolution(key, Span(0, None, None), None, days[key]) for key in days
        ]
        body["presets"] = [_preset(name, 0, []) for name in RETENTION_PRESETS]
        return body
    conn = connect(path, read_only=True)
    try:
        page = int(conn.execute("PRAGMA page_size").fetchone()[0])
        body["reclaimable_bytes"] = int(conn.execute("PRAGMA freelist_count").fetchone()[0]) * page
        body["auto_vacuum"] = AUTO_VACUUM.get(
            int(conn.execute("PRAGMA auto_vacuum").fetchone()[0]), "none"
        )
        sizes = table_bytes(conn)
        found = spans(conn)
        tables = _tables(conn)
        counts = {
            name: int(conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0])  # noqa: S608
            for name in COUNTED
            if name in tables
        }
    finally:
        conn.close()
    if sizes is not None:
        body["tables"] = [
            {"name": name, "bytes": size, "rows": counts.get(name)}
            for name, size in sorted(sizes.items(), key=lambda item: (-item[1], item[0]))
        ]
    split = resolution_bytes(sizes, found) if sizes is not None else None
    resolutions = [
        _resolution(key, found[key], None if split is None else split[key], days[key])
        for key in days
    ]
    body["resolutions"] = resolutions
    other = None
    if sizes is not None:
        other = sum(sizes.values()) - sum(split.values()) if split is not None else 0
        body["projected_bytes"], body["growth_bytes_per_year"] = projection(
            resolutions, days, other
        )
    body["presets"] = [_preset(name, other, resolutions) for name in RETENTION_PRESETS]
    return body


def projection(
    resolutions: list[dict[str, Any]], days: Mapping[str, float | None], other: int
) -> tuple[int, int]:
    """Return the projected size and the yearly growth at the retention ``days``.

    Parameters
    ----------
    resolutions
        Items of the report (``bytes``, ``bytes_per_day``).
    days
        Retention per resolution id (``None`` keeps it forever).
    other
        Bytes of the indexes and small tables, counted as they are.
    """
    projected = float(other)
    growth = 0.0
    for item in resolutions:
        rate = item["bytes_per_day"]
        kept = days[item["id"]]
        if kept is None:
            projected += item["bytes"] or 0
            growth += (rate or 0.0) * DAYS_PER_YEAR
        elif rate is not None:
            projected += rate * kept
        else:
            projected += item["bytes"] or 0
    return round(projected), round(growth)


def current_preset(retention: Retention, journal_days: float | None) -> str | None:
    """Return the preset the retention in effect matches, or ``None`` (custom)."""
    for name in RETENTION_PRESETS:
        if preset_retention(name) == (retention, journal_days):
            return name
    return None


def _preset(name: str, other: int | None, resolutions: list[dict[str, Any]]) -> dict[str, Any]:
    retention, journal_days = preset_retention(name)
    projected: int | None = None
    growth: int | None = None
    if other is not None:
        projected, growth = projection(resolutions, retention_days(retention, journal_days), other)
    return {
        "id": name,
        "values": dict(RETENTION_PRESETS[name]),
        "projected_bytes": projected,
        "growth_bytes_per_year": growth,
    }


def _resolution(key: str, span: Span, size: int | None, days: float | None) -> dict[str, Any]:
    rate = _per_day(size, span)
    return {
        "id": key,
        "retention_days": days,
        "rows": span.rows,
        "oldest": None if span.oldest is None else iso_from_unix(span.oldest),
        "newest": None if span.newest is None else iso_from_unix(span.newest),
        "bytes": size,
        "bytes_per_day": None if rate is None else round(rate, 1),
    }

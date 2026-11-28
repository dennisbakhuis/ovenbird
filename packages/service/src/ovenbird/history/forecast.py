"""Weather forecasts in ``history.db``, stored as issued (table ``forecast``).

Every fetch is kept with its issue time, so later open-loop runs and the error statistics
see what was known at the time (lead-time correct): one row per issue and target
hour. Rows are written by the history writer thread and read through read-only
connections; retention follows the 1 h rollup (by issue time).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ovenbird.history.schema import connect
from ovenbird.sql import qualified, sql

COLUMNS: Final = "issued_ts, target_ts, temp_c, radiation_wm2, cloud_pct, wind_ms"
HOUR_S: Final = 3600.0


@dataclass(frozen=True, slots=True)
class ForecastRow:
    """One forecast hour of one issue.

    Parameters
    ----------
    issued_ts
        When the forecast was fetched (service clock, unix seconds).
    target_ts
        The hour it describes (unix seconds).
    temp_c
        Air temperature at 2 m.
    radiation_wm2
        Global horizontal irradiance (mean over the preceding hour).
    cloud_pct
        Cloud cover.
    wind_ms
        Wind speed at 10 m.
    """

    issued_ts: float
    target_ts: float
    temp_c: float | None
    radiation_wm2: float | None
    cloud_pct: float | None
    wind_ms: float | None


def write_forecast(conn: sqlite3.Connection, rows: Sequence[ForecastRow]) -> int:
    """Insert (or replace) forecast rows in one transaction; returns the rows written."""
    if not rows:
        return 0
    conn.execute("BEGIN")
    try:
        conn.executemany(
            sql(
                "INSERT OR REPLACE INTO forecast ({columns}) VALUES ({marks})",
                columns=COLUMNS,
                marks=6,
            ),
            [
                (r.issued_ts, r.target_ts, r.temp_c, r.radiation_wm2, r.cloud_pct, r.wind_ms)
                for r in rows
            ],
        )
        conn.execute("COMMIT")
    except sqlite3.Error:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return len(rows)


def delete_forecast_before(conn: sqlite3.Connection, cutoff: float) -> int:
    """Delete the forecasts issued before ``cutoff``; returns the rows deleted."""
    return conn.execute("DELETE FROM forecast WHERE issued_ts < ?", (cutoff,)).rowcount


def _open(path: Path) -> sqlite3.Connection | None:
    """Open the history read-only if it has a forecast table, else return ``None``."""
    if not path.exists():
        return None
    conn = connect(path, read_only=True)
    found = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'forecast'"
    ).fetchone()
    if found is None:
        conn.close()
        return None
    return conn


def latest_issue(path: Path, before: float | None = None) -> float | None:
    """Return the newest issue time (at or before ``before``), if any forecast is stored."""
    conn = _open(path)
    if conn is None:
        return None
    try:
        if before is None:
            row = conn.execute("SELECT MAX(issued_ts) FROM forecast").fetchone()
        else:
            row = conn.execute(
                "SELECT MAX(issued_ts) FROM forecast WHERE issued_ts <= ?", (before,)
            ).fetchone()
    finally:
        conn.close()
    return None if row is None or row[0] is None else float(row[0])


def issue_rows(path: Path, issued_ts: float) -> list[ForecastRow]:
    """Return the rows of one issue, by target time."""
    conn = _open(path)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            sql(
                "SELECT {columns} FROM forecast WHERE issued_ts = ? ORDER BY target_ts",
                columns=COLUMNS,
            ),
            (issued_ts,),
        ).fetchall()
    finally:
        conn.close()
    return [ForecastRow(*row) for row in rows]


def at_lead(path: Path, lead_h: float, start: float, end: float) -> dict[float, float]:
    """Return the temperature forecast ``lead_h`` hours ahead for each target in ``[start, end)``.

    For each target hour the issue whose lead is in ``[lead_h, lead_h + 1)`` hours is
    used (the newest one when several qualify).

    Parameters
    ----------
    path
        History database.
    lead_h
        How many hours before the target the forecast was issued.
    start, end
        Target period, Unix seconds.

    Returns
    -------
    dict
        Target unix time to forecast temperature (targets without one are absent).
    """
    conn = _open(path)
    if conn is None:
        return {}
    low = lead_h * HOUR_S
    try:
        rows = conn.execute(
            "SELECT target_ts, temp_c FROM forecast WHERE target_ts >= ? AND target_ts < ? "
            "AND target_ts - issued_ts >= ? AND target_ts - issued_ts < ? "
            "AND temp_c IS NOT NULL ORDER BY target_ts, issued_ts",
            (start, end, low, low + HOUR_S),
        ).fetchall()
    finally:
        conn.close()
    return {float(target): float(temp) for target, temp in rows}


def newest_rows(path: Path, start: float, end: float, issued_by: float) -> list[ForecastRow]:
    """Return, for each target hour in ``[start, end]``, the newest stored issue's row.

    The newest issue at or before ``issued_by`` is the one with the shortest lead
    (``target_ts - issued_ts``), which is what a forecast plan rule needs: the best
    knowledge of each hour, past and future.

    Parameters
    ----------
    path
        Database file; a missing file or table yields no rows.
    start, end
        Target window in unix seconds (both ends included).
    issued_by
        Only issues made at or before this time count.

    Returns
    -------
    list of ForecastRow
        One row per target hour, by target time.
    """
    conn = _open(path)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            sql(
                "SELECT {columns} FROM forecast AS f "
                "JOIN (SELECT target_ts, MAX(issued_ts) AS issued_ts FROM forecast "
                "WHERE issued_ts <= ? AND target_ts >= ? AND target_ts <= ? "
                "GROUP BY target_ts) AS m "
                "ON f.target_ts = m.target_ts AND f.issued_ts = m.issued_ts ORDER BY f.target_ts",
                columns=qualified(COLUMNS, "f"),
            ),
            (issued_by, start, end),
        ).fetchall()
    finally:
        conn.close()
    return [ForecastRow(*row) for row in rows]

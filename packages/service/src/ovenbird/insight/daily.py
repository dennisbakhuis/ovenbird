"""Daily insight: energy, COP, compressor cycles, comfort and writes per local day.

Every figure comes from the 1 min rollups of the HeishaMon and room signals,
bucketed by local day in the service's time zone: a day runs from local midnight
to the next one, so it lasts 23 or 25 h on a daylight saving switch. Energy is the
time integral of the pump's power estimates over the time with data (gaps are not
filled); ``coverage`` is the share of the day, up to now for the current day, for
which both heating power estimates have data. A figure is ``None`` when its
source has no data that day. Days older than the 1 min rollup retention have no
data.

The house basics (:mod:`ovenbird.insight.basics`) read two more aggregates from the
15 min rollups, which are kept longer: :func:`day_figures` (per day the loop heat,
electricity, outside and room temperature) and :func:`heating_hours` (the hours in
which the compressor heated the house throughout, with their mean water temperature).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

from ovenbird.clock import iso_from_unix
from ovenbird.history.database import HEAT_SIGNAL
from ovenbird.history.schema import connect
from ovenbird.sql import sql
from ovenbird_core import HeishaSignal

STEP: Final = 60
MAX_DAYS: Final = 90
BAND_BELOW_K: Final = 0.5
RUNNING_HZ: Final = 1.0
FLAG_ON: Final = 1.0
JOULES_PER_KWH: Final = 3_600_000.0
SECONDS_PER_HOUR: Final = 3600.0
SECONDS_PER_DAY: Final = 86_400.0

ELECTRIC: Final = HeishaSignal.HEAT_POWER_CONSUMPTION.value
HEAT: Final = HeishaSignal.HEAT_POWER_PRODUCTION.value
DHW_ELECTRIC: Final = HeishaSignal.DHW_POWER_CONSUMPTION.value
DHW_HEAT: Final = HeishaSignal.DHW_POWER_PRODUCTION.value
COMPRESSOR: Final = HeishaSignal.COMPRESSOR_FREQ.value
DEFROST: Final = HeishaSignal.DEFROSTING_STATE.value
VALVE: Final = HeishaSignal.THREEWAY_VALVE_STATE.value
OUTSIDE: Final = HeishaSignal.OUTSIDE_TEMP.value
SETPOINT: Final = HeishaSignal.Z1_WATER_TARGET_TEMP.value
INLET: Final = HeishaSignal.INLET_TEMP.value
OUTLET: Final = HeishaSignal.OUTLET_TEMP.value
FLOW: Final = HeishaSignal.PUMP_FLOW.value
QUARTER: Final = 900
QUARTERS_PER_HOUR: Final = 4
FULL_QUARTER: Final = 0.9

TOTALS_SQL: Final = """
WITH {days}
SELECT days.idx, SUM(r.weighted_sum), SUM(r.duration), MIN(r.minimum),
    SUM(CASE
        WHEN r.minimum >= ? THEN r.duration
        WHEN r.maximum < ? OR r.duration <= 0 OR r.maximum <= 0 THEN 0.0
        ELSE r.duration * MIN(1.0, r.weighted_sum / r.duration / r.maximum)
    END),
    SUM(MAX(0.0, ? * r.duration - r.weighted_sum))
FROM days JOIN rollup AS r
    ON r.step = ? AND r.signal_id = ? AND r.bucket >= days.start AND r.bucket < days.stop
GROUP BY days.idx
"""

TRANSITIONS_SQL: Final = """
WITH {days}, r AS (
    SELECT bucket, minimum, maximum, last, LAG(last) OVER (ORDER BY bucket) AS prev
    FROM rollup WHERE step = ? AND signal_id = ? AND bucket >= ? AND bucket < ?
)
SELECT days.idx,
    SUM(CASE
        WHEN r.prev < ? AND r.maximum >= ? THEN 1
        WHEN r.prev >= ? AND r.minimum < ? AND r.last >= ? THEN 1
        ELSE 0
    END),
    SUM(CASE WHEN r.prev IS NOT NULL AND r.last != r.prev THEN 1 ELSE 0 END)
FROM days JOIN r ON r.bucket >= days.start AND r.bucket < days.stop
GROUP BY days.idx
"""

HEATING_QUARTERS_SQL: Final = """
SELECT c.bucket,
    h.weighted_sum / h.duration, i.weighted_sum / i.duration, o.weighted_sum / o.duration,
    r.weighted_sum / r.duration,
    CASE WHEN f.duration > 0 THEN f.weighted_sum / f.duration END,
    CASE WHEN x.duration > 0 THEN x.weighted_sum / x.duration END
FROM rollup AS c
JOIN rollup AS h ON h.step = c.step AND h.signal_id = ? AND h.bucket = c.bucket
JOIN rollup AS i ON i.step = c.step AND i.signal_id = ? AND i.bucket = c.bucket
JOIN rollup AS o ON o.step = c.step AND o.signal_id = ? AND o.bucket = c.bucket
JOIN rollup AS r ON r.step = c.step AND r.signal_id = ? AND r.bucket = c.bucket
LEFT JOIN rollup AS v ON v.step = c.step AND v.signal_id = ? AND v.bucket = c.bucket
LEFT JOIN rollup AS d ON d.step = c.step AND d.signal_id = ? AND d.bucket = c.bucket
LEFT JOIN rollup AS f ON f.step = c.step AND f.signal_id = ? AND f.bucket = c.bucket
LEFT JOIN rollup AS x ON x.step = c.step AND x.signal_id = ? AND x.bucket = c.bucket
WHERE c.step = ? AND c.signal_id = ? AND c.bucket >= ? AND c.bucket < ?
    AND c.minimum >= ? AND c.duration >= ? AND h.duration >= ?
    AND i.duration > 0 AND o.duration > 0 AND r.duration > 0
    AND (v.maximum IS NULL OR v.maximum < ?) AND (d.maximum IS NULL OR d.maximum < ?)
ORDER BY c.bucket
"""

WRITES_SQL: Final = """
WITH {days}
SELECT days.idx, COUNT(c.ts)
FROM days LEFT JOIN command AS c
    ON c.status = 'sent' AND c.ts >= days.start AND c.ts < days.stop
GROUP BY days.idx
"""


@dataclass(frozen=True, slots=True)
class LocalDay:
    """One local calendar day.

    Parameters
    ----------
    date
        Local date.
    start, end
        Unix seconds of its local midnight and the next one.
    """

    date: date
    start: float
    end: float

    @property
    def hours(self) -> float:
        """Length in hours (23 or 25 on a daylight saving switch)."""
        return (self.end - self.start) / SECONDS_PER_HOUR


@dataclass(frozen=True, slots=True)
class Totals:
    """One signal's 1 min rollups summed over a day.

    Parameters
    ----------
    integral
        Time integral of the value (value x seconds).
    covered
        Seconds with data.
    minimum
        Lowest value seen.
    on_s
        Seconds at or above the ``on`` threshold of the query.
    below
        Integral of the shortfall under the ``band`` of the query (K x seconds).
    """

    integral: float = 0.0
    covered: float = 0.0
    minimum: float | None = None
    on_s: float = 0.0
    below: float = 0.0

    @property
    def mean(self) -> float | None:
        """Time-weighted mean; ``None`` without data."""
        return self.integral / self.covered if self.covered > 0 else None


@dataclass(frozen=True, slots=True)
class Transitions:
    """Changes of one signal within a day.

    Parameters
    ----------
    rises
        Changes from below to at or above the ``on`` threshold of the query.
    changes
        Minutes whose last value differs from the previous minute's.
    """

    rises: int = 0
    changes: int = 0


def local_days(now: datetime, days: int, timezone: str) -> list[LocalDay]:
    """Return the ``days`` local days ending with today, oldest first.

    Parameters
    ----------
    now
        Current time (timezone-aware).
    days
        Number of days, today included.
    timezone
        IANA time zone of the day boundaries.

    Returns
    -------
    list of LocalDay
        Consecutive days; each starts at its local midnight.
    """
    zone = ZoneInfo(timezone)
    today = now.astimezone(zone).date()

    def midnight(day: date) -> float:
        """Return the unix time of the local midnight starting ``day``."""
        return datetime(day.year, day.month, day.day, tzinfo=zone).timestamp()

    found = []
    for back in range(days - 1, -1, -1):
        day = today - timedelta(days=back)
        found.append(LocalDay(day, midnight(day), midnight(day + timedelta(days=1))))
    return found


def _days_cte(windows: Sequence[LocalDay]) -> tuple[str, list[float]]:
    """Return the ``days`` CTE of the windows and its parameters."""
    rows = ", ".join("(?, ?, ?)" for _ in windows)
    params = [value for idx, day in enumerate(windows) for value in (idx, day.start, day.end)]
    return f"days(idx, start, stop) AS (VALUES {rows})", params


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    """Return whether the database has ``table``."""
    found = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return found is not None


def _totals(
    conn: sqlite3.Connection,
    windows: Sequence[LocalDay],
    signal_id: int | None,
    *,
    on: float = FLAG_ON,
    band: float = 0.0,
    step: int = STEP,
) -> list[Totals]:
    """Sum one signal's rollups of ``step`` per window (empty totals without a signal).

    Parameters
    ----------
    conn
        Open history database connection.
    windows
        Local days to sum over.
    signal_id
        Signal to sum; ``None`` gives empty totals.
    on
        Value from which a flag counts as on.
    band
        Tolerance below the target that counts as being below it.
    step
        Rollup resolution, in seconds.
    """
    found = [Totals() for _ in windows]
    if signal_id is None:
        return found
    cte, params = _days_cte(windows)
    rows = conn.execute(
        TOTALS_SQL.format(days=cte), [*params, on, on, band, step, signal_id]
    ).fetchall()
    for idx, integral, covered, minimum, on_s, below in rows:
        found[int(idx)] = Totals(
            float(integral or 0.0),
            float(covered or 0.0),
            None if minimum is None else float(minimum),
            float(on_s or 0.0),
            float(below or 0.0),
        )
    return found


def _transitions(
    conn: sqlite3.Connection,
    windows: Sequence[LocalDay],
    signal_id: int | None,
    *,
    on: float = FLAG_ON,
) -> list[Transitions]:
    """Count one signal's rises and changes per window in the 1 min rollups.

    Parameters
    ----------
    conn
        Open history database connection.
    windows
        Local days to count in.
    signal_id
        Signal to count; ``None`` gives no transitions.
    on
        Value from which a flag counts as on.
    """
    found = [Transitions() for _ in windows]
    if signal_id is None or not windows:
        return found
    cte, params = _days_cte(windows)
    lookback = windows[0].start - SECONDS_PER_DAY
    rows = conn.execute(
        TRANSITIONS_SQL.format(days=cte),
        [*params, STEP, signal_id, lookback, windows[-1].end, on, on, on, on, on],
    ).fetchall()
    for idx, rises, changes in rows:
        found[int(idx)] = Transitions(int(rises or 0), int(changes or 0))
    return found


def _writes(conn: sqlite3.Connection, windows: Sequence[LocalDay]) -> list[int | None]:
    """Count the sent commands per window (``None`` without a command journal)."""
    if not windows or not _has_table(conn, "command"):
        return [None for _ in windows]
    cte, params = _days_cte(windows)
    counts = dict(conn.execute(WRITES_SQL.format(days=cte), params).fetchall())
    return [int(counts.get(idx, 0)) for idx in range(len(windows))]


def _signal_ids(conn: sqlite3.Connection, names: Sequence[str]) -> dict[str, int]:
    """Return the ids of the named signals the history knows."""
    if not _has_table(conn, "signal"):
        return {}
    rows = conn.execute(
        sql("SELECT name, id FROM signal WHERE name IN ({marks})", marks=len(names)),
        list(names),
    ).fetchall()
    return {str(name): int(signal_id) for name, signal_id in rows}


def _round(value: float | None, digits: int) -> float | None:
    """Round a value, keeping ``None``."""
    return None if value is None else round(value, digits)


def _kwh(totals: Totals) -> float | None:
    """Return the integral in kWh (``None`` without data)."""
    return round(totals.integral / JOULES_PER_KWH, 3) if totals.covered > 0 else None


def _count(transitions: Transitions, source: Totals) -> int | None:
    """Return the rises when the source has data that day, else ``None``."""
    return transitions.rises if source.covered > 0 else None


@dataclass(frozen=True, slots=True)
class _DayData:
    """Every signal's totals and transitions of one day."""

    electric: Totals = Totals()
    heat: Totals = Totals()
    dhw_electric: Totals = Totals()
    dhw_heat: Totals = Totals()
    compressor: Totals = Totals()
    starts: Transitions = Transitions()
    defrost: Totals = Totals()
    defrosts: Transitions = Transitions()
    valve: Totals = Totals()
    dhw_runs: Transitions = Transitions()
    outside: Totals = Totals()
    room: Totals = Totals()
    setpoint: Totals = Totals()
    setpoint_moves: Transitions = Transitions()
    writes: int | None = None


def _day_json(day: LocalDay, data: _DayData, now: float, comfort_c: float | None) -> dict[str, Any]:
    """Return the API form of one day.

    Parameters
    ----------
    day
        Local day described.
    data
        Totals and transitions of that day.
    now
        Current Unix time, to bound the elapsed part of the day.
    comfort_c
        Comfort room temperature, in degrees Celsius.
    """
    elapsed = max(0.0, min(day.end, now) - day.start)
    covered = min(data.electric.covered, data.heat.covered)
    coverage = min(1.0, covered / elapsed) if elapsed > 0 else 0.0
    electric = _kwh(data.electric)
    heat = _kwh(data.heat)
    cop = round(heat / electric, 2) if electric and heat is not None else None
    room = data.room
    below = room.below / SECONDS_PER_HOUR if room.covered > 0 and comfort_c is not None else None
    compressor_known = data.compressor.covered > 0
    valve_known = data.valve.covered > 0
    return {
        "date": day.date.isoformat(),
        "from": iso_from_unix(day.start),
        "to": iso_from_unix(day.end),
        "hours": day.hours,
        "partial": now < day.end,
        "coverage": round(coverage, 3),
        "electric_kwh": electric,
        "heat_kwh": heat,
        "cop": cop,
        "dhw_electric_kwh": _kwh(data.dhw_electric),
        "dhw_heat_kwh": _kwh(data.dhw_heat),
        "compressor_starts": _count(data.starts, data.compressor),
        "run_s": round(data.compressor.on_s) if compressor_known else None,
        "defrosts": _count(data.defrosts, data.defrost),
        "defrost_s": round(data.defrost.on_s) if data.defrost.covered > 0 else None,
        "dhw_runs": _count(data.dhw_runs, data.valve),
        "dhw_s": round(data.valve.on_s) if valve_known else None,
        "outside_mean_c": _round(data.outside.mean, 2),
        "outside_min_c": _round(data.outside.minimum if data.outside.covered > 0 else None, 2),
        "room_mean_c": _round(room.mean, 2),
        "room_min_c": _round(room.minimum if room.covered > 0 else None, 2),
        "comfort_c": comfort_c,
        "below_comfort_kh": _round(below, 2),
        "setpoint_mean_c": _round(data.setpoint.mean, 2),
        "setpoint_changes": data.setpoint_moves.changes if data.setpoint.covered > 0 else None,
        "writes": data.writes,
    }


def _collect(
    conn: sqlite3.Connection,
    windows: Sequence[LocalDay],
    room_signal: str | None,
    band_c: float,
) -> list[_DayData]:
    """Read every signal of the daily figures for the windows.

    Parameters
    ----------
    conn
        Open history database connection.
    windows
        Local days to read.
    room_signal
        Room temperature signal; ``None`` without one.
    band_c
        Tolerance below the comfort target, in kelvin.
    """
    names = [ELECTRIC, HEAT, DHW_ELECTRIC, DHW_HEAT, COMPRESSOR, DEFROST, VALVE, OUTSIDE, SETPOINT]
    if room_signal is not None:
        names.append(room_signal)
    ids = _signal_ids(conn, names)
    room_id = ids.get(room_signal) if room_signal is not None else None
    columns = (
        _totals(conn, windows, ids.get(ELECTRIC)),
        _totals(conn, windows, ids.get(HEAT)),
        _totals(conn, windows, ids.get(DHW_ELECTRIC)),
        _totals(conn, windows, ids.get(DHW_HEAT)),
        _totals(conn, windows, ids.get(COMPRESSOR), on=RUNNING_HZ),
        _transitions(conn, windows, ids.get(COMPRESSOR), on=RUNNING_HZ),
        _totals(conn, windows, ids.get(DEFROST)),
        _transitions(conn, windows, ids.get(DEFROST)),
        _totals(conn, windows, ids.get(VALVE)),
        _transitions(conn, windows, ids.get(VALVE)),
        _totals(conn, windows, ids.get(OUTSIDE)),
        _totals(conn, windows, room_id, band=band_c),
        _totals(conn, windows, ids.get(SETPOINT)),
        _transitions(conn, windows, ids.get(SETPOINT)),
        _writes(conn, windows),
    )
    return [_DayData(*values) for values in zip(*columns, strict=True)]


def daily_payload(
    path: Path,
    *,
    now: datetime,
    days: int,
    timezone: str,
    room_signal: str | None = None,
    comfort_c: float | None = None,
    journal_days: float | None = None,
) -> dict[str, Any]:
    """Return the ``GET api/v1/insight/daily`` body.

    Parameters
    ----------
    path
        History database; a missing file yields days without data.
    now
        Current service-clock time (timezone-aware); today is the last day.
    days
        Number of days, today included (1 to :data:`MAX_DAYS`).
    timezone
        IANA time zone of the day boundaries.
    room_signal
        Room temperature signal id; ``None`` leaves the room figures empty.
    comfort_c
        Comfort target; degree-hours count below ``comfort_c - BAND_BELOW_K``.
    journal_days
        Command journal retention; ``writes`` is ``None`` for days that start
        before it.

    Returns
    -------
    dict
        ``timezone``, ``band_below_k``, ``room_signal`` and one entry per day in
        ``days``, oldest first.

    Raises
    ------
    ValueError
        When ``days`` is outside 1 to :data:`MAX_DAYS`.
    """
    if not 1 <= days <= MAX_DAYS:
        raise ValueError(f"days must be between 1 and {MAX_DAYS}")
    windows = local_days(now, days, timezone)
    band_c = (comfort_c - BAND_BELOW_K) if comfort_c is not None else 0.0
    data = [_DayData() for _ in windows]
    if path.exists():
        conn = connect(path, read_only=True)
        try:
            if _has_table(conn, "rollup"):
                data = _collect(conn, windows, room_signal, band_c)
        finally:
            conn.close()
    stamp = now.timestamp()
    cutoff = stamp - journal_days * SECONDS_PER_DAY if journal_days is not None else None
    rows = []
    for day, item in zip(windows, data, strict=True):
        body = _day_json(day, item, stamp, comfort_c)
        if cutoff is not None and day.start < cutoff:
            body["writes"] = None
        rows.append(body)
    return {
        "timezone": timezone,
        "band_below_k": BAND_BELOW_K,
        "room_signal": room_signal,
        "days": rows,
    }


@dataclass(frozen=True, slots=True)
class DayFigures:
    """One local day as the house basics read it (15 min rollups).

    Parameters
    ----------
    day
        The local day.
    coverage
        Share of the day (of its elapsed part for today) with the loop heat known or the
        pump on hot water, the outside temperature and the room temperature, whichever
        is lowest.
    heat_coverage
        The same share for the loop heat (or hot water) alone.
    loop_heat_w
        Mean heat into the space-heating loop (``derived/heat_delivered_w``) over the
        time it is known, hot-water time counted as zero heat; a defrost's draw is
        netted. ``None`` without data.
    electric_w
        Mean of ``Heat_Power_Consumption`` (``None`` without data).
    outside_c, room_c
        Time-weighted means (``None`` without data).
    """

    day: LocalDay
    coverage: float
    heat_coverage: float
    loop_heat_w: float | None
    electric_w: float | None
    outside_c: float | None
    room_c: float | None


@dataclass(frozen=True, slots=True)
class HeatingHour:
    """One clock hour in which the compressor heated the house throughout.

    Parameters
    ----------
    start
        Unix seconds of the hour's start.
    heat_w
        Mean heat into the space-heating loop.
    water_c
        Mean water temperature, the mean of inlet and outlet.
    room_c
        Mean room temperature.
    flow_l_min
        Mean pump flow (``None`` without data).
    outside_c
        Mean outside temperature (``None`` without data).
    """

    start: float
    heat_w: float
    water_c: float
    room_c: float
    flow_l_min: float | None
    outside_c: float | None


def _day_figures(
    day: LocalDay,
    now: float,
    heat: Totals,
    hot_water: Totals,
    electric: Totals,
    outside: Totals,
    room: Totals,
) -> DayFigures:
    """Combine one day's totals into :class:`DayFigures`.

    Parameters
    ----------
    day
        Local day the figures are for.
    now
        Current Unix time.
    heat
        Heat output totals.
    hot_water
        Hot water totals.
    electric
        Electric input totals.
    outside
        Outside temperature totals.
    room
        Room temperature totals.
    """
    elapsed = max(0.0, min(day.end, now) - day.start)
    known = min(elapsed, heat.covered + hot_water.on_s) if heat.covered > 0 else 0.0
    covered = min(known, outside.covered, room.covered)

    def share(seconds: float) -> float:
        """Return ``seconds`` as a share of the elapsed part of the day."""
        return min(1.0, seconds / elapsed) if elapsed > 0 else 0.0

    return DayFigures(
        day=day,
        coverage=share(covered),
        heat_coverage=share(known),
        loop_heat_w=heat.integral / known if known > 0 else None,
        electric_w=electric.mean,
        outside_c=outside.mean,
        room_c=room.mean,
    )


def day_figures(
    path: Path,
    windows: Sequence[LocalDay],
    room_signal: str | None,
    *,
    now: float,
    step: int = QUARTER,
) -> list[DayFigures]:
    """Return the house-basics figures of each window from the rollups of ``step``.

    Parameters
    ----------
    path
        History database; a missing file yields days without data.
    windows
        Local days, oldest first.
    room_signal
        Room temperature signal id; ``None`` leaves the room empty (coverage 0).
    now
        Unix seconds; the elapsed part of today is the base of its coverage.
    step
        Rollup step in seconds (15 min by default: kept longer than 1 min).

    Returns
    -------
    list of DayFigures
        One entry per window.
    """
    empty = Totals()
    names = [HEAT_SIGNAL, VALVE, ELECTRIC, OUTSIDE]
    if room_signal is not None:
        names.append(room_signal)
    columns: tuple[list[Totals], ...] = tuple([empty] * len(windows) for _ in range(5))
    if windows and path.exists():
        conn = connect(path, read_only=True)
        try:
            if _has_table(conn, "rollup"):
                ids = _signal_ids(conn, names)
                room_id = ids.get(room_signal) if room_signal is not None else None
                columns = (
                    _totals(conn, windows, ids.get(HEAT_SIGNAL), step=step),
                    _totals(conn, windows, ids.get(VALVE), step=step),
                    _totals(conn, windows, ids.get(ELECTRIC), step=step),
                    _totals(conn, windows, ids.get(OUTSIDE), step=step),
                    _totals(conn, windows, room_id, step=step),
                )
        finally:
            conn.close()
    return [_day_figures(day, now, *values) for day, *values in zip(windows, *columns, strict=True)]


def _full_hours(quarters: Sequence[tuple[float, ...]]) -> list[HeatingHour]:
    """Average complete hours of qualifying quarters, keeping those whose previous hour is full."""
    by_hour: dict[int, list[tuple[float, ...]]] = {}
    for row in quarters:
        hour = int(row[0]) - int(row[0]) % int(SECONDS_PER_HOUR)
        by_hour.setdefault(hour, []).append(row)
    full = {hour for hour, rows in by_hour.items() if len(rows) == QUARTERS_PER_HOUR}
    found = []
    for hour in sorted(full):
        if hour - int(SECONDS_PER_HOUR) not in full:
            continue
        rows = by_hour[hour]
        flows = [row[5] for row in rows if row[5] is not None]
        outsides = [row[6] for row in rows if row[6] is not None]
        found.append(
            HeatingHour(
                start=float(hour),
                heat_w=sum(row[1] for row in rows) / len(rows),
                water_c=sum((row[2] + row[3]) / 2.0 for row in rows) / len(rows),
                room_c=sum(row[4] for row in rows) / len(rows),
                flow_l_min=sum(flows) / len(flows) if flows else None,
                outside_c=sum(outsides) / len(outsides) if outsides else None,
            )
        )
    return found


def heating_hours(
    path: Path, start: float, end: float, room_signal: str | None
) -> list[HeatingHour]:
    """Return the hours in which the compressor heated the house, in its second hour or later.

    A 15 min quarter qualifies when the compressor ran at or above 1 Hz all through it,
    the loop heat is known for at least 90 % of it, inlet, outlet and room have data,
    and neither hot water nor a defrost touched it. An hour counts when its four
    quarters and the four of the hour before qualify, so the start of a run, when the
    water is still warming up, is left out.

    Parameters
    ----------
    path
        History database; a missing file yields no hours.
    start, end
        Unix seconds of the span.
    room_signal
        Room temperature signal id; ``None`` yields no hours.

    Returns
    -------
    list of HeatingHour
        Oldest first.
    """
    if room_signal is None or not path.exists():
        return []
    conn = connect(path, read_only=True)
    try:
        if not _has_table(conn, "rollup"):
            return []
        names = [COMPRESSOR, HEAT_SIGNAL, INLET, OUTLET, room_signal, VALVE, DEFROST, FLOW, OUTSIDE]
        ids = _signal_ids(conn, names)
        needed = (COMPRESSOR, HEAT_SIGNAL, INLET, OUTLET, room_signal)
        if any(name not in ids for name in needed):
            return []
        optional = [ids.get(name, -1) for name in (VALVE, DEFROST, FLOW, OUTSIDE)]
        rows = conn.execute(
            HEATING_QUARTERS_SQL,
            [
                ids[HEAT_SIGNAL],
                ids[INLET],
                ids[OUTLET],
                ids[room_signal],
                *optional,
                QUARTER,
                ids[COMPRESSOR],
                start - SECONDS_PER_HOUR,
                end,
                RUNNING_HZ,
                FULL_QUARTER * QUARTER,
                FULL_QUARTER * QUARTER,
                FLAG_ON,
                FLAG_ON,
            ],
        ).fetchall()
    finally:
        conn.close()
    quarters = [tuple(row) for row in rows]
    return [hour for hour in _full_hours(quarters) if hour.start >= start]

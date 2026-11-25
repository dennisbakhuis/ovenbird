"""Shadow divergence: ovenbird's would-be water setpoint against the pump's target.

Built per minute from two stored sources:

- **ovenbird**: the ``setpoint`` of the last decision in each minute (the integer
  the controller would send, in every mode); a minute without a decision carries
  the previous one when it is at most two control intervals old, otherwise it is a
  gap. Refusals and holds have no setpoint (a gap).
- **pump**: the last value of ``main/Z1_Water_Target_Temp`` in each 1 min rollup
  (what the pump was actually given, by whoever wrote it); a minute without a
  rollup is a gap.

``writer`` is ``ovenbird`` when the pump reports the value of ovenbird's latest
verified water-setpoint command, ``other`` when it reports something else
(Node-RED, the Panasonic remote, the envelope rule) and ``None`` without data.

Gaps are never filled: a minute counts only when both values are known; coverage
says how much of the window could be compared, and an episode that runs into a gap
ends there (``ended_by`` ``gap``).

An **episode** is a run of compared minutes with ``|ovenbird - pump|`` above the
threshold (1 K by default); it carries ovenbird's reason at its start and at its
largest difference. The per-day summary (local days in the service's time zone)
gives the mean and largest absolute difference, hours above the threshold, the
signed mean (bias), the episodes that started that day and the gap minutes.
"""

from __future__ import annotations

import bisect
import math
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from ovenbird.clock import iso_from_unix
from ovenbird.history.schema import connect
from ovenbird.insight.daily import local_days
from ovenbird_core import HeishaSignal

MINUTE: Final = 60
STEPS: Final = (60, 300, 900, 3600)
MAX_POINTS: Final = 1500
MAX_DAYS: Final = 31
MAX_EPISODES: Final = 500
DEFAULT_THRESHOLD_K: Final = 1.0
PUMP_SIGNAL: Final = HeishaSignal.Z1_WATER_TARGET_TEMP.value
OVENBIRD: Final = "ovenbird"
OTHER: Final = "other"


@dataclass(frozen=True, slots=True)
class Minute:
    """One compared minute.

    Parameters
    ----------
    ts
        Minute start (unix seconds).
    ovenbird
        ovenbird's would-be setpoint (``None`` for a gap).
    pump
        The pump's ``Z1_Water_Target_Temp`` (``None`` for a gap).
    mode, reason
        Mode and reason of the decision that set ``ovenbird``.
    writer
        ``ovenbird``, ``other`` or ``None``.
    """

    ts: int
    ovenbird: float | None
    pump: float | None
    mode: str | None
    reason: str | None
    writer: str | None

    @property
    def diff(self) -> float | None:
        """``ovenbird - pump`` when both are known."""
        if self.ovenbird is None or self.pump is None:
            return None
        return self.ovenbird - self.pump


def divergence_step(start: float, end: float) -> int:
    """Return the finest step with at most 1,500 points over ``[start, end)``."""
    for step in STEPS:
        if (end - start) / step <= MAX_POINTS:
            return step
    return STEPS[-1]


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    found = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return found is not None


def _decisions(
    conn: sqlite3.Connection, start: float, end: float, carry_s: float
) -> list[tuple[float, str, str, float | None]]:
    if not _has_table(conn, "decision"):
        return []
    rows = conn.execute(
        "SELECT ts, mode, reason, setpoint FROM decision WHERE ts >= ? AND ts < ? ORDER BY ts, id",
        (start - carry_s, end),
    ).fetchall()
    return [
        (float(ts), str(mode), str(reason), None if sp is None else float(sp))
        for ts, mode, reason, sp in rows
    ]


def _pump(conn: sqlite3.Connection, start: int, end: float) -> dict[int, float]:
    if not _has_table(conn, "rollup") or not _has_table(conn, "signal"):
        return {}
    row = conn.execute("SELECT id FROM signal WHERE name = ?", (PUMP_SIGNAL,)).fetchone()
    if row is None:
        return {}
    rows = conn.execute(
        "SELECT bucket, last FROM rollup WHERE step = ? AND signal_id = ? AND bucket >= ? "
        "AND bucket < ?",
        (MINUTE, int(row[0]), start, end),
    ).fetchall()
    return {int(bucket): float(last) for bucket, last in rows}


def _verified(conn: sqlite3.Connection, end: float) -> list[tuple[float, int]]:
    if not _has_table(conn, "command"):
        return []
    rows = conn.execute(
        "SELECT ts, value FROM command WHERE kind = 'water_setpoint' AND status = 'verified' "
        "AND ts < ? ORDER BY ts",
        (end,),
    ).fetchall()
    return [(float(ts), int(value)) for ts, value in rows]


type Decided = tuple[float, str, str, float | None]


def carry_s(interval_s: float) -> float:
    """Return how long a decision's setpoint is carried into minutes without one."""
    return max(2.0 * interval_s, 2.0 * MINUTE)


def per_minute(
    grid: Sequence[int], decisions: Sequence[Decided], carry: float
) -> list[Decided | None]:
    """Return the last decision of each minute of ``grid``, carried for at most ``carry`` s.

    Parameters
    ----------
    grid
        Minute starts (unix seconds), oldest first.
    decisions
        ``(ts, mode, reason, setpoint)``, oldest first.
    carry
        How long a decision is carried (see :func:`carry_s`).

    Returns
    -------
    list
        One entry per minute; ``None`` for a gap.
    """
    found: list[Decided | None] = []
    index = 0
    current: Decided | None = None
    for ts in grid:
        while index < len(decisions) and decisions[index][0] < ts + MINUTE:
            current = decisions[index]
            index += 1
        fresh = current is not None and ts + MINUTE - current[0] <= carry + MINUTE
        found.append(current if fresh else None)
    return found


def pump_minutes(path: Path, start: float, end: float) -> tuple[dict[int, float], list[Any]]:
    """Return the pump's target per minute and ovenbird's verified water-setpoint commands.

    Parameters
    ----------
    path
        History database; a missing file yields nothing.
    start, end
        Window in unix seconds (``start`` on a minute).

    Returns
    -------
    tuple
        ``{minute: Z1_Water_Target_Temp}`` and the verified ``(ts, value)`` commands
        before ``end``.
    """
    if not path.exists():
        return {}, []
    conn = connect(path, read_only=True)
    try:
        return _pump(conn, int(start), end), _verified(conn, end)
    finally:
        conn.close()


def writers(
    grid: Sequence[int], pump: dict[int, float], verified: Sequence[tuple[float, int]]
) -> list[str | None]:
    """Return who wrote the pump's value in each minute of ``grid`` (``None`` without one)."""
    stamps = [ts for ts, _ in verified]
    found: list[str | None] = []
    for ts in grid:
        value = pump.get(ts)
        if value is None:
            found.append(None)
            continue
        at = bisect.bisect_right(stamps, ts + MINUTE) - 1
        own = verified[at][1] if at >= 0 else None
        found.append(OVENBIRD if own is not None and own == round(value) else OTHER)
    return found


def minutes(path: Path, start: float, end: float, *, interval_s: float = 60.0) -> list[Minute]:
    """Return the compared minutes of ``[start, end)``, oldest first.

    Parameters
    ----------
    path
        History database; a missing file yields minutes without data.
    start, end
        Window in unix seconds.
    interval_s
        Control interval (a decision is carried for at most two intervals).

    Returns
    -------
    list of Minute
        One entry per minute from ``floor(start)`` up to ``end``.
    """
    first = int(math.floor(start / MINUTE) * MINUTE)
    grid = list(range(first, math.ceil(end), MINUTE))
    if not grid:
        return []
    carry = carry_s(interval_s)
    decisions: list[Decided] = []
    pump: dict[int, float] = {}
    verified: list[tuple[float, int]] = []
    if path.exists():
        conn = connect(path, read_only=True)
        try:
            decisions = _decisions(conn, first, end, carry)
            pump = _pump(conn, first, end)
            verified = _verified(conn, end)
        finally:
            conn.close()
    result: list[Minute] = []
    for ts, current, writer in zip(
        grid, per_minute(grid, decisions, carry), writers(grid, pump, verified), strict=True
    ):
        ovenbird = mode = reason = None
        if current is not None:
            _, mode, reason, ovenbird = current
        result.append(Minute(ts, ovenbird, pump.get(ts), mode, reason, writer))
    return result


@dataclass(slots=True)
class _Episode:
    start: int
    end: int
    max_abs: float
    max_diff: float
    at_max: Minute
    first: Minute
    ended_by: str = "open"

    def to_json(self) -> dict[str, Any]:
        return {
            "start": iso_from_unix(self.start),
            "end": iso_from_unix(self.end),
            "minutes": (self.end - self.start) // MINUTE,
            "max_abs_k": round(self.max_abs, 2),
            "max_diff_k": round(self.max_diff, 2),
            "ovenbird_c": self.at_max.ovenbird,
            "pump_c": self.at_max.pump,
            "reason": self.first.reason,
            "reason_at_max": self.at_max.reason,
            "mode": self.first.mode,
            "writer": self.first.writer,
            "ended_by": self.ended_by,
        }


def episodes(rows: Sequence[Minute], threshold_k: float) -> list[_Episode]:
    """Return the runs of minutes with ``|diff|`` above ``threshold_k``, oldest first."""
    found: list[_Episode] = []
    open_: _Episode | None = None
    for row in rows:
        diff = row.diff
        if diff is not None and abs(diff) > threshold_k:
            if open_ is None:
                open_ = _Episode(row.ts, row.ts + MINUTE, abs(diff), diff, row, row)
            else:
                open_.end = row.ts + MINUTE
                if abs(diff) > open_.max_abs:
                    open_.max_abs, open_.max_diff, open_.at_max = abs(diff), diff, row
            continue
        if open_ is not None:
            open_.ended_by = "gap" if diff is None else "converged"
            found.append(open_)
            open_ = None
    if open_ is not None:
        found.append(open_)
    return found


def summarise(rows: Sequence[Minute], threshold_k: float) -> dict[str, Any]:
    """Return compared minutes, coverage, mean/max absolute and signed difference, hours over."""
    diffs = [row.diff for row in rows if row.diff is not None]
    compared = len(diffs)
    over = sum(1 for d in diffs if abs(d) > threshold_k)
    return {
        "minutes": len(rows),
        "compared_minutes": compared,
        "gap_minutes": len(rows) - compared,
        "coverage": round(compared / len(rows), 3) if rows else 0.0,
        "mean_abs_k": round(sum(abs(d) for d in diffs) / compared, 2) if compared else None,
        "max_abs_k": round(max(abs(d) for d in diffs), 2) if compared else None,
        "bias_k": round(sum(diffs) / compared, 2) if compared else None,
        "hours_over": round(over / 60.0, 2),
    }


def _series(rows: Sequence[Minute], step: int) -> dict[str, list[Any]]:
    columns: dict[str, list[Any]] = {
        name: [] for name in ("at", "ovenbird", "pump", "diff", "max_abs", "writer", "mode")
    }
    buckets: dict[int, list[Minute]] = {}
    for row in rows:
        buckets.setdefault(row.ts // step * step, []).append(row)
    for bucket in sorted(buckets):
        items = buckets[bucket]
        ovenbird = next((r for r in reversed(items) if r.ovenbird is not None), None)
        pump = next((r for r in reversed(items) if r.pump is not None), None)
        both = next((r for r in reversed(items) if r.diff is not None), None)
        diffs = [abs(r.diff) for r in items if r.diff is not None]
        columns["at"].append(iso_from_unix(bucket))
        columns["ovenbird"].append(None if ovenbird is None else ovenbird.ovenbird)
        columns["pump"].append(None if pump is None else pump.pump)
        columns["diff"].append(None if both is None or both.diff is None else round(both.diff, 2))
        columns["max_abs"].append(round(max(diffs), 2) if diffs else None)
        columns["writer"].append(None if pump is None else pump.writer)
        columns["mode"].append(None if ovenbird is None else ovenbird.mode)
    return columns


def divergence_payload(
    path: Path,
    *,
    start: float,
    end: float,
    step: int | None = None,
    timezone: str = "UTC",
    threshold_k: float = DEFAULT_THRESHOLD_K,
    interval_s: float = 60.0,
) -> dict[str, Any]:
    """Return the body of ``GET api/v1/shadow/divergence``.

    Parameters
    ----------
    path
        History database.
    start, end
        Window in unix seconds (at most :data:`MAX_DAYS` days).
    step
        Series step (60, 300, 900, 3600); the finest with at most 1,500 points
        when omitted.
    timezone
        IANA time zone of the per-day summary.
    threshold_k
        Difference that counts as divergent.
    interval_s
        Control interval.

    Returns
    -------
    dict
        ``step``, ``threshold_k``, ``summary``, ``days``, ``episodes``
        (newest :data:`MAX_EPISODES`), ``episodes_total`` and ``series``.

    Raises
    ------
    ValueError
        For an unknown step or a window longer than :data:`MAX_DAYS` days.
    """
    if end - start > MAX_DAYS * 86_400.0:
        raise ValueError(f"the window must be at most {MAX_DAYS} days")
    resolved = divergence_step(start, end) if step is None else step
    if resolved not in STEPS:
        raise ValueError(f"step must be one of {', '.join(map(str, STEPS))}")
    rows = minutes(path, start, end, interval_s=interval_s)
    found = episodes(rows, threshold_k)
    days = []
    end_moment = datetime.fromtimestamp(end, UTC)
    span = max(1, math.ceil((end - start) / 86_400.0) + 1)
    stamps = [row.ts for row in rows]
    for day in local_days(end_moment, span, timezone):
        inside = rows[bisect.bisect_left(stamps, day.start) : bisect.bisect_left(stamps, day.end)]
        if not inside:
            continue
        starting = [ep for ep in found if day.start <= ep.start < day.end]
        days.append(
            {
                "date": day.date.isoformat(),
                "from": iso_from_unix(max(day.start, rows[0].ts)),
                "to": iso_from_unix(min(day.end, inside[-1].ts + MINUTE)),
                **summarise(inside, threshold_k),
                "episodes": len(starting),
                "longest_episode_min": max(
                    ((ep.end - ep.start) // MINUTE for ep in starting), default=0
                ),
            }
        )
    return {
        "step": resolved,
        "threshold_k": threshold_k,
        "timezone": timezone,
        "signal": PUMP_SIGNAL,
        "summary": {
            **summarise(rows, threshold_k),
            "episodes": len(found),
            "longest_episode_min": max(((ep.end - ep.start) // MINUTE for ep in found), default=0),
        },
        "days": days,
        "episodes_total": len(found),
        "episodes": [ep.to_json() for ep in found[-MAX_EPISODES:]],
        "series": _series(rows, resolved),
    }

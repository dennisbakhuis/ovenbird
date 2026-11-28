"""The trial summary: the trial period against a baseline on the cut-over criteria.

**Trial summary**: the trial period (from the go-live snapshot to now, at most 30
days, unless given) against a baseline period of the same length before it (the
previous controller), on the cut-over criteria: room mean within ±0.5 K, the room's
lowest value, the share of compressor runs under 20 min not worse, no pump errors,
writes per day within the budget, and the pump's setpoint changes per day for both.
``state`` says whether it is a trial at all: ``no_trial`` (no go-live snapshot: the
default period compares the previous controller with itself), ``running`` (shorter
than :data:`MIN_TRIAL_DAYS`), ``ended_early`` (released before that), ``complete``,
or ``not_a_trial`` for a queried period outside a go-live. ``met`` is true only when
the state is ``complete`` and every criterion is ``ok`` or ``info``
(``criteria_met`` is the latter alone).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from ovenbird.clock import iso_from_unix
from ovenbird.history.schema import connect
from ovenbird.trial.checklist import DAY_S, FAIL, OK
from ovenbird.trial.runs import (
    SHORT_RUN_MIN,
    journal_counts,
    run_stats,
    runs_between,
    signal_period,
)
from ovenbird_core import HeishaSignal, Instant

if TYPE_CHECKING:
    from ovenbird.config import Settings
    from ovenbird.control.loop import ControlLoop

ROOM_LIMIT_K: Final = 0.5
MAX_TRIAL_DAYS: Final = 30.0
DEFAULT_TRIAL_DAYS: Final = 7.0
MIN_TRIAL_DAYS: Final = 7.0
SETPOINT: Final = HeishaSignal.Z1_WATER_TARGET_TEMP.value
OUTSIDE: Final = HeishaSignal.OUTSIDE_TEMP.value
SUMMARY_STATES: Final = ("no_trial", "running", "ended_early", "complete", "not_a_trial")
CRITERION_IDS: Final = (
    "room_mean",
    "room_min",
    "short_runs",
    "pump_errors",
    "writes_per_day",
    "setpoint_changes_per_day",
)


def setpoint_changes(path: Path, start: float, end: float) -> int | None:
    """Return how often the pump's water target changed in ``[start, end)`` (1 min rollups)."""
    if not path.exists():
        return None
    conn = connect(path, read_only=True)
    try:
        if (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'rollup'"
            ).fetchone()
            is None
        ):
            return None
        found = conn.execute("SELECT id FROM signal WHERE name = ?", (SETPOINT,)).fetchone()
        if found is None:
            return None
        row = conn.execute(
            "SELECT COUNT(*) FROM (SELECT last, LAG(last) OVER (ORDER BY bucket) AS prev "
            "FROM rollup WHERE step = 60 AND signal_id = ? AND bucket >= ? AND bucket < ?) "
            "WHERE prev IS NOT NULL AND last != prev",
            (int(found[0]), start, end),
        ).fetchone()
    finally:
        conn.close()
    return int(row[0])


def go_live_snapshot(loop: ControlLoop | None) -> Any:
    """Return the release manager's go-live snapshot, ``None`` without one."""
    release = loop.release if loop is not None else None
    snapshot = release.snapshot if release is not None else None
    if snapshot is None or snapshot.origin != "go_live":
        return None
    return snapshot


def windows(
    loop: ControlLoop | None,
    now: Instant,
    trial: tuple[float, float] | None,
    baseline: tuple[float, float] | None,
) -> tuple[tuple[float, float], tuple[float, float], str]:
    """Resolve the trial and baseline periods (unix seconds) and where they came from.

    Parameters
    ----------
    loop
        Control loop holding the go-live snapshot, ``None`` without one.
    now
        Current time.
    trial
        Trial period asked for, Unix seconds, ``None`` to derive it.
    baseline
        Baseline period asked for, Unix seconds, ``None`` to take the period before the trial.

    Returns
    -------
    tuple
        Trial period, baseline period and the source (``query``, ``go_live`` or ``default``).
    """
    end = now.wall.timestamp()
    source = "query"
    if trial is None:
        snapshot = go_live_snapshot(loop)
        if snapshot is not None:
            start = max(snapshot.taken_at.timestamp(), end - MAX_TRIAL_DAYS * DAY_S)
            stop = end if snapshot.released_at is None else snapshot.released_at.timestamp()
            trial = (start, max(start + 60.0, stop))
            source = "go_live"
        else:
            trial = (end - DEFAULT_TRIAL_DAYS * DAY_S, end)
            source = "default"
    if baseline is None:
        length = min(max(trial[1] - trial[0], DAY_S), MAX_TRIAL_DAYS * DAY_S)
        baseline = (trial[0] - length, trial[0])
    return trial, baseline, source


def trial_state(
    loop: ControlLoop | None, source: str, span: tuple[float, float], end: float
) -> tuple[str, float]:
    """Return the summary's ``state`` and the trial's length in days.

    Parameters
    ----------
    loop
        Control loop holding the go-live snapshot, ``None`` without one.
    source
        Where the trial period came from (``query``, ``go_live`` or ``default``).
    span
        Trial period, Unix seconds.
    end
        Current time, Unix seconds.
    """
    days = max(0.0, (span[1] - span[0]) / DAY_S)
    snapshot = go_live_snapshot(loop)
    if source == "default" or snapshot is None:
        return ("no_trial" if source == "default" else "not_a_trial"), days
    taken = snapshot.taken_at.timestamp()
    stop = end if snapshot.released_at is None else snapshot.released_at.timestamp()
    if source == "query" and (span[0] < taken - 60.0 or span[1] > stop + 60.0):
        return "not_a_trial", days
    if days >= MIN_TRIAL_DAYS:
        return "complete", days
    if source == "go_live" and snapshot.released_at is not None:
        return "ended_early", days
    return "running", days


def period(settings: Settings, span: tuple[float, float]) -> dict[str, Any]:
    """Return one period's figures from ``history.db``: room, outside, runs and writes."""
    path = settings.history_path
    start, end = span
    days = max((end - start) / DAY_S, 1e-9)
    room = signal_period(path, settings.control_room_signal, start, end)
    outside = signal_period(path, OUTSIDE, start, end)
    counts = journal_counts(path, start, end)
    changes = setpoint_changes(path, start, end)
    writes = counts["writes"]
    return {
        "from": iso_from_unix(start),
        "to": iso_from_unix(end),
        "days": round(days, 2),
        "room_mean_c": room["mean"],
        "room_min_c": room["min"],
        "room_hours": room["hours"],
        "outside_mean_c": outside["mean"],
        "runs": run_stats(runs_between(path, start, end)),
        "pump_errors": counts["pump_errors"],
        "writes": writes,
        "writes_per_day": None if writes is None else round(writes / days, 1),
        "setpoint_changes_per_day": None if changes is None else round(changes / days, 1),
    }


def criteria(ours: dict[str, Any], theirs: dict[str, Any], budget: int) -> list[dict[str, Any]]:
    """Return the cut-over criteria of the trial period against the baseline.

    Parameters
    ----------
    ours, theirs
        The trial and baseline periods (:func:`period`).
    budget
        The daily write budget.

    Returns
    -------
    list of dict
        One entry per :data:`CRITERION_IDS`, with its ``status``.
    """
    found = []
    delta = None
    if ours["room_mean_c"] is not None and theirs["room_mean_c"] is not None:
        delta = round(ours["room_mean_c"] - theirs["room_mean_c"], 2)
    found.append(
        {
            "id": "room_mean",
            "trial": ours["room_mean_c"],
            "baseline": theirs["room_mean_c"],
            "delta": delta,
            "limit": ROOM_LIMIT_K,
            "status": "unknown" if delta is None else (OK if abs(delta) <= ROOM_LIMIT_K else FAIL),
        }
    )
    low_delta = None
    if ours["room_min_c"] is not None and theirs["room_min_c"] is not None:
        low_delta = round(ours["room_min_c"] - theirs["room_min_c"], 2)
    found.append(
        {
            "id": "room_min",
            "trial": ours["room_min_c"],
            "baseline": theirs["room_min_c"],
            "delta": low_delta,
            "limit": None,
            "status": "info",
        }
    )
    share, base_share = ours["runs"]["short_share"], theirs["runs"]["short_share"]
    found.append(
        {
            "id": "short_runs",
            "trial": share,
            "baseline": base_share,
            "delta": None if share is None or base_share is None else round(share - base_share, 3),
            "limit": SHORT_RUN_MIN,
            "status": "unknown"
            if share is None or base_share is None
            else (OK if share <= base_share else FAIL),
        }
    )
    errors = ours["pump_errors"]
    found.append(
        {
            "id": "pump_errors",
            "trial": errors,
            "baseline": theirs["pump_errors"],
            "delta": None,
            "limit": 0,
            "status": "unknown" if errors is None else (OK if errors == 0 else FAIL),
        }
    )
    per_day = ours["writes_per_day"]
    found.append(
        {
            "id": "writes_per_day",
            "trial": per_day,
            "baseline": theirs["writes_per_day"],
            "delta": None,
            "limit": budget,
            "status": "unknown" if per_day is None else (OK if per_day <= budget else FAIL),
        }
    )
    found.append(
        {
            "id": "setpoint_changes_per_day",
            "trial": ours["setpoint_changes_per_day"],
            "baseline": theirs["setpoint_changes_per_day"],
            "delta": None,
            "limit": None,
            "status": "info",
        }
    )
    return found


def summary_body(
    source: str,
    state: str,
    days: float,
    ours: dict[str, Any],
    theirs: dict[str, Any],
    budget: int,
) -> dict[str, Any]:
    """Return the trial summary from both periods, the trial's state and length.

    Parameters
    ----------
    source
        Where the trial period came from.
    state
        State of the trial.
    days
        Length of the trial in days.
    ours
        Figures of the trial period.
    theirs
        Figures of the baseline period.
    budget
        Daily command budget the criteria compare against.
    """
    found = criteria(ours, theirs, budget)
    criteria_met = all(c["status"] in {OK, "info"} for c in found)
    return {
        "source": source,
        "state": state,
        "days": round(days, 2),
        "min_days": MIN_TRIAL_DAYS,
        "trial": ours,
        "baseline": theirs,
        "criteria": found,
        "criteria_met": criteria_met,
        "met": criteria_met and state == "complete",
    }


def parse_span(start: datetime | None, end: datetime | None) -> tuple[float, float] | None:
    """Return a ``(from, to)`` span in unix seconds when both bounds are given."""
    if start is None or end is None:
        return None
    return start.astimezone(UTC).timestamp(), end.astimezone(UTC).timestamp()

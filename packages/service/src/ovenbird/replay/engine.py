"""Replay level 1: what ovenbird would have sent over a recorded period.

Every stored decision of the window is stepped again, in one streaming pass:

- with the **chosen configuration** (the active one, a stored version, or a draft on top
  of the active one), from the recorded state just before the window. **Open loop**:
  the house followed the recorded control, so nothing here is a comfort or energy claim;
- with **each tick's own version** (the identity check), which must reproduce every
  recorded setpoint for the replay to be exact.

The replayed setpoints are laid on the minute grid of the shadow divergence
(:mod:`ovenbird.trial.divergence`): per minute the recorded ovenbird setpoint, the
replayed one and the pump's ``Z1_Water_Target_Temp``. Episodes are runs of minutes with
the replayed setpoint more than ``threshold_k`` from the pump's target, with the replayed
reason. Writes are the replayed setpoint's changes (what ovenbird would write once the
pump follows it), counted per local day against the daily write budget.
"""

from __future__ import annotations

import math
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from ovenbird.clock import iso_from_unix
from ovenbird.config import Settings
from ovenbird.history.journal import decision_before, iter_decisions
from ovenbird.history.schema import connect
from ovenbird.insight.daily import local_days
from ovenbird.replay.stepping import (
    CandidateStepper,
    ConfigOf,
    Identity,
    IdentityStepper,
    SettingsOf,
    Tally,
    limitations,
    parse_row,
    setpoint_changes,
    shares,
)
from ovenbird.trial.divergence import (
    DEFAULT_THRESHOLD_K,
    MAX_EPISODES,
    MINUTE,
    PUMP_SIGNAL,
    STEPS,
    Decided,
    Minute,
    carry_s,
    divergence_step,
    episodes,
    minutes,
    per_minute,
    summarise,
)

MAX_DAYS: Final = 92
BATCH: Final = 500
DAY_S: Final = 86_400.0

type Progress = Callable[[str, float], None]


class ReplayCancelledError(Exception):
    """The replay was cancelled before it finished."""


@dataclass(frozen=True, slots=True)
class ReplayRequest:
    """What to replay.

    Parameters
    ----------
    start, end
        Window in unix seconds.
    candidate
        Settings to replay with.
    reference
        Active settings (the replay's limitations are relative to them).
    settings_of
        Settings a stored version ran with (identity check).
    config_of
        Controller configuration a stored version ran with.
    config
        Description of the chosen configuration, echoed in the result.
    timezone
        IANA time zone of the per-day counts.
    interval_s
        Control interval (a decision is carried for at most two intervals).
    threshold_k
        Difference from the pump's target that counts as an episode.
    step
        Series step (60, 300, 900, 3600); the finest with at most 1,500 points when
        ``None``.
    """

    start: float
    end: float
    candidate: Settings
    reference: Settings
    settings_of: SettingsOf
    config_of: ConfigOf
    config: dict[str, Any] = field(default_factory=dict)
    timezone: str = "UTC"
    interval_s: float = 60.0
    threshold_k: float = DEFAULT_THRESHOLD_K
    step: int | None = None


def max_days(decision_days: float) -> float:
    """Return the longest window: the decision retention (plus a day), at most 92 days.

    ``decision_days`` ``0`` keeps decisions forever.
    """
    if decision_days <= 0:
        return float(MAX_DAYS)
    return float(min(MAX_DAYS, math.ceil(decision_days) + 1))


def count_decisions(path: Path, start: float, end: float) -> int:
    """Return the number of stored decisions in ``[start, end)``."""
    if not path.exists():
        return 0
    conn = connect(path, read_only=True)
    try:
        if not _has_decisions(conn):
            return 0
        row = conn.execute(
            "SELECT COUNT(*) FROM decision WHERE ts >= ? AND ts < ?", (start, end)
        ).fetchone()
    finally:
        conn.close()
    return int(row[0])


def _has_decisions(conn: Any) -> bool:
    found = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'decision'"
    ).fetchone()
    return found is not None


def identity_json(identity: Identity) -> dict[str, Any]:
    """Return the ``identity`` object of a replay result."""
    return {
        "ok": identity.ok if identity.ticks else None,
        "ticks": identity.ticks,
        "mismatches": identity.mismatches,
        "first_mismatch": None if identity.first is None else iso_from_unix(identity.first),
        "unknown": identity.unknown,
        "versions": [
            {
                "version": item.version,
                "ticks": item.ticks,
                "mismatches": item.mismatches,
                "first_mismatch": None if item.first is None else iso_from_unix(item.first),
            }
            for item in identity.versions
        ],
    }


def _value(decided: Decided | None) -> float | None:
    return None if decided is None else decided[3]


def _sent(path: Path, start: float, end: float) -> list[float]:
    if not path.exists():
        return []
    conn = connect(path, read_only=True)
    try:
        found = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'command'"
        ).fetchone()
        if found is None:
            return []
        rows = conn.execute(
            "SELECT ts FROM command WHERE status = 'sent' AND kind = 'water_setpoint' "
            "AND ts >= ? AND ts < ? ORDER BY ts",
            (start, end),
        ).fetchall()
    finally:
        conn.close()
    return [float(row[0]) for row in rows]


def _change_times(values: Sequence[tuple[float, float | None]]) -> list[float]:
    found: list[float] = []
    last: float | None = None
    for ts, value in values:
        if value is None:
            continue
        if last is not None and value != last:
            found.append(ts)
        last = value
    return found


def _days(
    request: ReplayRequest,
    replayed: Sequence[Decided],
    recorded: Sequence[tuple[float, float | None]],
    sent: Sequence[float],
) -> list[dict[str, Any]]:
    start, end = request.start, request.end
    span = max(1, math.ceil((end - start) / DAY_S) + 1)
    writes = _change_times([(item[0], item[3]) for item in replayed])
    changes = _change_times(recorded)
    found = []
    for day in local_days(datetime.fromtimestamp(end, UTC), span, request.timezone):
        lo, hi = max(day.start, start), min(day.end, end)
        if lo >= hi:
            continue
        found.append(
            {
                "date": day.date.isoformat(),
                "from": iso_from_unix(lo),
                "to": iso_from_unix(hi),
                "writes": sum(1 for ts in writes if lo <= ts < hi),
                "changes_recorded": sum(1 for ts in changes if lo <= ts < hi),
                "sent_recorded": sum(1 for ts in sent if lo <= ts < hi),
            }
        )
    return found


def _series(
    grid: Sequence[int],
    columns: dict[str, Sequence[float | None]],
    step: int,
) -> dict[str, list[Any]]:
    series: dict[str, list[Any]] = {"at": [], **{name: [] for name in columns}}
    if not grid:
        return series
    first = grid[0]
    bucket_of = [ts // step * step for ts in grid]
    index = 0
    while index < len(grid):
        bucket = bucket_of[index]
        stop = index
        while stop < len(grid) and bucket_of[stop] == bucket:
            stop += 1
        series["at"].append(iso_from_unix(max(bucket, first)))
        for name, values in columns.items():
            last = next(
                (values[i] for i in range(stop - 1, index - 1, -1) if values[i] is not None),
                None,
            )
            series[name].append(last)
        index = stop
    return series


def _summary(
    request: ReplayRequest,
    rows: Sequence[Minute],
    recorded: Sequence[float | None],
    tally: Tally,
    days: Sequence[dict[str, Any]],
    found_episodes: Sequence[Any],
    sent: int,
) -> dict[str, Any]:
    threshold = request.threshold_k
    budget = request.candidate.command_daily_budget
    diffs = [row.diff for row in rows if row.diff is not None]
    pairs = [
        row.ovenbird - old
        for row, old in zip(rows, recorded, strict=True)
        if row.ovenbird is not None and old is not None
    ]
    pump = [None if row.pump is None else round(row.pump) for row in rows]
    writes = setpoint_changes(tally.replayed)
    span_days = max(request.end - request.start, 1.0) / DAY_S
    max_day = max((day["writes"] for day in days), default=0)
    base = tally.summary((request.start, request.end), budget)
    return {
        **summarise(rows, threshold),
        "above_pump_min": sum(1 for d in diffs if d > threshold),
        "below_pump_min": sum(1 for d in diffs if d < -threshold),
        "differs_recorded_min": sum(1 for d in pairs if d != 0),
        "above_recorded_min": sum(1 for d in pairs if d > 0),
        "below_recorded_min": sum(1 for d in pairs if d < 0),
        "mean_diff_recorded_k": base["mean_diff_k"],
        "changes_recorded": base["changes_recorded"],
        "changes_replayed": base["changes_candidate"],
        "changes_pump": setpoint_changes(pump),
        "writes": writes,
        "writes_per_day": round(writes / span_days, 1),
        "max_writes_day": max_day,
        "days_over_budget": sum(1 for day in days if day["writes"] > budget),
        "budget": budget,
        "budget_use": round(max_day / budget, 3) if budget > 0 else None,
        "sent_recorded": sent,
        "share_safety_clamped": base["share_safety_clamped"],
        "share_feedback_limited": base["share_feedback_limited"],
        "ladder": base["ladder"],
        "reason": shares(tally.reasons, len(tally.replayed)),
        "binding": base["binding"],
        "episodes": len(found_episodes),
        "longest_episode_min": max(
            ((ep.end - ep.start) // MINUTE for ep in found_episodes), default=0
        ),
    }


def _episode_json(episode: Any, recorded_at: dict[int, float | None]) -> dict[str, Any]:
    body: dict[str, Any] = episode.to_json()
    body["recorded_c"] = recorded_at.get(episode.at_max.ts)
    return body


def run_replay(
    path: Path,
    request: ReplayRequest,
    *,
    progress: Progress | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Replay the stored decisions of the window and compare them with what happened.

    Parameters
    ----------
    path
        History database.
    request
        What to replay.
    progress
        Called with a phase (``replay``, ``compare``) and the fraction done.
    cancelled
        Polled between batches; the replay stops with
        :class:`ReplayCancelledError` once it returns ``True``.

    Returns
    -------
    dict
        The result body (see ``docs/api-v1.md``, ``POST replay``).

    Raises
    ------
    ValueError
        For an unknown step.
    ReplayCancelledError
        When cancelled.
    """
    started = time.perf_counter()
    start, end = request.start, request.end
    step = divergence_step(start, end) if request.step is None else request.step
    if step not in STEPS:
        raise ValueError(f"step must be one of {', '.join(map(str, STEPS))}")
    report = progress or (lambda _phase, _done: None)
    stop = cancelled or (lambda: False)
    total = max(count_decisions(path, start, end), 1)
    seed_row = decision_before(path, start)
    seed = None if seed_row is None else parse_row(seed_row)
    identity = IdentityStepper(seed, request.settings_of, request.config_of)
    candidate = CandidateStepper(seed, request.candidate, request.config_of)
    tally = Tally()
    replayed: list[Decided] = []
    recorded_ticks: list[tuple[float, float | None]] = []
    rows = unreadable = 0
    report("replay", 0.0)
    for row in iter_decisions(path, start, end, batch=BATCH):
        rows += 1
        if rows % BATCH == 0:
            if stop():
                raise ReplayCancelledError
            report("replay", min(rows / total, 1.0))
            time.sleep(0)
        recorded_ticks.append((row.ts, None if row.setpoint is None else float(row.setpoint)))
        tick = parse_row(row)
        if tick is None:
            unreadable += 1
            continue
        identity.feed(tick)
        decision = candidate.feed(tick)
        if decision is None:
            continue
        tally.add(tick.record, decision)
        replayed.append(
            (
                tick.ts,
                decision.mode.value,
                decision.reason.value,
                None if decision.setpoint is None else float(decision.setpoint),
            )
        )
    if stop():
        raise ReplayCancelledError
    report("compare", 1.0)
    measured = minutes(path, start, end, interval_s=request.interval_s)
    grid = [row.ts for row in measured]
    mine = per_minute(grid, replayed, carry_s(request.interval_s))
    rows_min = [
        Minute(
            row.ts,
            _value(decided),
            row.pump,
            None if decided is None else decided[1],
            None if decided is None else decided[2],
            row.writer,
        )
        for row, decided in zip(measured, mine, strict=True)
    ]
    recorded = [row.ovenbird for row in measured]
    found = episodes(rows_min, request.threshold_k)
    sent = _sent(path, start, end)
    days = _days(request, replayed, recorded_ticks, sent)
    recorded_at = dict(zip(grid, recorded, strict=True))
    return {
        "from": iso_from_unix(start),
        "to": iso_from_unix(end),
        "config": request.config,
        "ticks": rows,
        "skipped": unreadable + candidate.skipped,
        "open_loop": True,
        "threshold_k": request.threshold_k,
        "step": step,
        "timezone": request.timezone,
        "signal": PUMP_SIGNAL,
        "identity": identity_json(identity.result()),
        "summary": _summary(request, rows_min, recorded, tally, days, found, len(sent)),
        "days": days,
        "episodes_total": len(found),
        "episodes": [_episode_json(ep, recorded_at) for ep in found[-MAX_EPISODES:]],
        "series": _series(
            grid,
            {
                "recorded": recorded,
                "replayed": [row.ovenbird for row in rows_min],
                "pump": [row.pump for row in rows_min],
            },
            step,
        ),
        "limitations": limitations(request.candidate, request.reference),
        "run_s": round(time.perf_counter() - started, 2),
    }


def coverage_payload(
    path: Path,
    *,
    start: float,
    end: float,
    timezone: str,
    interval_s: float,
    decision_days: float,
) -> dict[str, Any]:
    """Return the body of ``GET replay/coverage``: where stored decisions exist.

    Parameters
    ----------
    path
        History database.
    start, end
        Window in unix seconds.
    timezone
        IANA time zone of the days.
    interval_s
        Control interval (the expected number of decisions per day).
    decision_days
        Decision retention in days (``0``: forever).

    Returns
    -------
    dict
        ``oldest``, ``newest``, ``max_days``, ``retention_days``, ``days`` (per local
        day: decisions, expected, first and last) and ``versions`` (per configuration
        version: first, last and decisions).
    """
    hours: list[tuple[int, int, float, float]] = []
    versions: list[tuple[int | None, float, float, int]] = []
    oldest = newest = None
    if path.exists():
        conn = connect(path, read_only=True)
        try:
            if _has_decisions(conn):
                oldest, newest = conn.execute("SELECT MIN(ts), MAX(ts) FROM decision").fetchone()
                hours = conn.execute(
                    "SELECT CAST(ts / 3600 AS INTEGER), COUNT(*), MIN(ts), MAX(ts) FROM decision "
                    "WHERE ts >= ? AND ts < ? GROUP BY 1 ORDER BY 1",
                    (start, end),
                ).fetchall()
                versions = conn.execute(
                    "SELECT config_version, MIN(ts), MAX(ts), COUNT(*) FROM decision "
                    "WHERE ts >= ? AND ts < ? GROUP BY config_version ORDER BY MIN(ts)",
                    (start, end),
                ).fetchall()
        finally:
            conn.close()
    span = max(1, math.ceil((end - start) / DAY_S) + 1)
    per_day: Counter[str] = Counter()
    firsts: dict[str, float] = {}
    lasts: dict[str, float] = {}
    windows = local_days(datetime.fromtimestamp(end, UTC), span, timezone)
    days = []
    for day in windows:
        lo, hi = max(day.start, start), min(day.end, end)
        if lo >= hi:
            continue
        key = day.date.isoformat()
        for _, count, first, last in hours:
            if lo <= first < hi or lo <= last < hi:
                inside = count if lo <= first and last < hi else None
                if inside is None:
                    continue
                per_day[key] += int(count)
                firsts[key] = min(firsts.get(key, first), first)
                lasts[key] = max(lasts.get(key, last), last)
        days.append(
            {
                "date": key,
                "from": iso_from_unix(lo),
                "to": iso_from_unix(hi),
                "decisions": per_day[key],
                "expected": int((hi - lo) // interval_s),
                "first": iso_from_unix(firsts[key]) if key in firsts else None,
                "last": iso_from_unix(lasts[key]) if key in lasts else None,
            }
        )
    return {
        "from": iso_from_unix(start),
        "to": iso_from_unix(end),
        "timezone": timezone,
        "interval_s": interval_s,
        "retention_days": decision_days,
        "max_days": max_days(decision_days),
        "oldest": None if oldest is None else iso_from_unix(oldest),
        "newest": None if newest is None else iso_from_unix(newest),
        "days": days,
        "versions": [
            {
                "version": version,
                "from": iso_from_unix(first),
                "to": iso_from_unix(last),
                "decisions": count,
            }
            for version, first, last, count in versions
        ],
    }

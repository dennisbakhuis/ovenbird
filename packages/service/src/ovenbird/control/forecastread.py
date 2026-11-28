"""Read the stored forecast for a plan rule, and the guards every forecast plan shares.

A plan rule that looks ahead (the sun day shift) reads the forecast the weather
component stored in ``history.db`` (:func:`load_forecast`) and should not plan while:

``forecast_stale``
    the newest stored issue is older than :data:`FORECAST_STALE_S` (3 h, the weather
    component's own staleness limit) or there is none;
``room_untrusted``
    the controller has no trusted room value (fresh and not rejected by its
    cross-check);
``stove_active``
    a wood-stove episode is active;
``stove_tail``
    a wood-stove episode ended less than :data:`STOVE_TAIL_S` (12 h) ago, so the
    house is still recovering from it.

:class:`StoveTail` keeps the end of the last episode across ticks and restores it
after a restart from the journalled ``stove_mode`` events; an episode whose end was
lost with the restart is closed at the first tick
(:func:`ovenbird.stove.session.close_orphan_episode`) and the tail starts then.
Everything here reads; nothing writes history except that closing row.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final

from ovenbird.control.alarms import AlarmBoard, AlarmEventKind
from ovenbird.history.forecast import latest_issue, newest_rows
from ovenbird.history.journal import alarms_since
from ovenbird.stove.request import STOVE_JOURNAL_CODE
from ovenbird.stove.session import close_orphan_episode
from ovenbird.weather.service import STALE_AFTER_S
from ovenbird_core import Instant
from ovenbird_core.control import OvenbirdConfig
from ovenbird_core.control.forecast import HISTORY_S, HOUR_S, ForecastHour

LOGGER = logging.getLogger("ovenbird.control.forecastread")
FORECAST_STALE_S: Final = STALE_AFTER_S
FORECAST_MARGIN_S: Final = 2 * HOUR_S
STOVE_TAIL_S: Final = 12 * HOUR_S
STOVE_END_EVENTS: Final = frozenset({AlarmEventKind.EXPIRED.value, AlarmEventKind.RELEASED.value})


class Guard(StrEnum):
    """Why a forecast plan rule should not plan, in the order they are reported."""

    FORECAST_STALE = "forecast_stale"
    ROOM_UNTRUSTED = "room_untrusted"
    STOVE_ACTIVE = "stove_active"
    STOVE_TAIL = "stove_tail"
    AWAY = "away"


GUARD_ORDER: Final = tuple(Guard)


@dataclass(frozen=True, slots=True)
class PlanContext:
    """What a plan rule needs of the control loop at one tick.

    Parameters
    ----------
    now
        The tick's instant.
    room_trusted
        The controller has a trusted room value (fresh and plausible).
    stove_active
        A wood-stove episode is active.
    outside_filtered_c
        The controller's filtered outside temperature (``None`` before the first tick).
    config
        The controller configuration in effect.
    room_c
        The room value when it is trusted (``None`` otherwise).
    away
        An away period is set (its return phase included); a plan rule pauses.
    """

    now: Instant
    room_trusted: bool
    stove_active: bool
    outside_filtered_c: float | None
    config: OvenbirdConfig
    room_c: float | None = None
    away: bool = False


@dataclass(frozen=True, slots=True)
class ForecastWindow:
    """The stored forecast a plan rule reads.

    Parameters
    ----------
    hours
        One row per target hour, the shortest-lead stored row for that hour.
    newest_issue
        Issue time of the newest stored forecast (``None`` when there is none).
    """

    hours: tuple[ForecastHour, ...]
    newest_issue: float | None


def load_forecast(path: Path, now_ts: float, horizon_h: float) -> ForecastWindow:
    """Read the forecast window from ``history.db``.

    Parameters
    ----------
    path
        History database.
    now_ts
        Wall time in unix seconds; only issues made by then count.
    horizon_h
        Hours ahead the rule looks.

    Returns
    -------
    ForecastWindow
        For each target hour from 24 h back to the horizon the shortest-lead stored
        row; a value that cannot be used (negative sun, not finite) is left out as
        missing, and rows off the whole hour are skipped.
    """
    newest = latest_issue(path, now_ts)
    rows = newest_rows(
        path,
        now_ts - HISTORY_S - FORECAST_MARGIN_S,
        now_ts + horizon_h * HOUR_S + FORECAST_MARGIN_S,
        now_ts,
    )
    hours: list[ForecastHour] = []
    for row in rows:
        if row.target_ts % HOUR_S != 0.0:
            continue
        try:
            hours.append(ForecastHour(row.target_ts, row.temp_c, row.radiation_wm2))
        except ValueError:
            hours.append(ForecastHour(row.target_ts, None, None))
    return ForecastWindow(tuple(hours), newest)


def forecast_stale(window: ForecastWindow, now_ts: float) -> bool:
    """Return whether the newest stored issue is missing or older than ``FORECAST_STALE_S``."""
    issued = window.newest_issue
    return issued is None or now_ts - issued > FORECAST_STALE_S


def load_stove_end(path: Path, now_ts: float) -> float | None:
    """Return when the last wood-stove episode ended within the tail, from the journal."""
    rows = alarms_since(path, STOVE_JOURNAL_CODE, now_ts - STOVE_TAIL_S)
    ends = [row.ts for row in rows if row.event in STOVE_END_EVENTS]
    return max(ends, default=None)


def in_stove_tail(stove_end: float | None, now_ts: float) -> bool:
    """Return whether ``now_ts`` lies within ``STOVE_TAIL_S`` after the episode end."""
    return stove_end is not None and 0.0 <= now_ts - stove_end < STOVE_TAIL_S


def live_guards(ctx: PlanContext, stove_end: float | None) -> tuple[Guard, ...]:
    """Return the failing guards that can change inside a slice (room, stove and away).

    Parameters
    ----------
    ctx
        What the control loop knows at this tick.
    stove_end
        Unix time the last wood-stove episode ended (``None``: none known).

    Returns
    -------
    tuple of Guard
        The failing guards in :data:`GUARD_ORDER`.
    """
    found: set[Guard] = set()
    if not ctx.room_trusted:
        found.add(Guard.ROOM_UNTRUSTED)
    if ctx.stove_active:
        found.add(Guard.STOVE_ACTIVE)
    if in_stove_tail(stove_end, ctx.now.wall.timestamp()):
        found.add(Guard.STOVE_TAIL)
    if ctx.away:
        found.add(Guard.AWAY)
    return tuple(guard for guard in GUARD_ORDER if guard in found)


def guards(ctx: PlanContext, window: ForecastWindow, stove_end: float | None) -> tuple[Guard, ...]:
    """Return every failing guard, the forecast's included, in :data:`GUARD_ORDER`.

    Parameters
    ----------
    ctx
        What the control loop knows at this tick.
    window
        The stored forecast.
    stove_end
        Unix time the last wood-stove episode ended (``None``: none known).

    Returns
    -------
    tuple of Guard
        The failing guards.
    """
    found = set(live_guards(ctx, stove_end))
    if forecast_stale(window, ctx.now.wall.timestamp()):
        found.add(Guard.FORECAST_STALE)
    return tuple(guard for guard in GUARD_ORDER if guard in found)


@dataclass
class StoveTail:
    """The end of the last wood-stove episode, followed tick by tick.

    Parameters
    ----------
    end
        Unix time the last episode ended (``None``: none known).
    """

    end: float | None = None
    _was_active: bool = field(default=False, init=False, repr=False)
    _restored: bool = field(default=False, init=False, repr=False)

    def restore(self, path: Path, alarms: AlarmBoard | None, ctx: PlanContext) -> None:
        """Read the end back from the journal once, closing an orphaned episode.

        Never raises: a failure is logged and leaves the end unknown.

        Parameters
        ----------
        path
            History database holding the journal.
        alarms
            Alarm board that writes the closing row (``None``: nothing is closed).
        ctx
            The first tick's context.
        """
        if self._restored:
            return
        self._restored = True
        try:
            now_ts = ctx.now.wall.timestamp()
            self.end = load_stove_end(path, now_ts)
            if alarms is not None:
                closed = close_orphan_episode(path, alarms, ctx.now, ctx.stove_active)
                if closed is not None:
                    self.end = closed
        except Exception:
            LOGGER.exception("could not read the wood-stove journal at start")

    def track(self, ctx: PlanContext) -> float | None:
        """Note the end of an episode at the tick it ends; return the known end."""
        if self._was_active and not ctx.stove_active:
            self.end = ctx.now.wall.timestamp()
        self._was_active = ctx.stove_active
        return self.end

"""Compressor starts: counted from the compressor state signal, kept across restarts.

:class:`StartCounter` watches ``Compressor_Freq`` (running at or above the controller's
lowest running frequency, :func:`ovenbird_core.derived.compressor_running`) on every
safety evaluation and counts a start when the compressor goes from stopped to running.
A defrost is not a new run: when ``Defrosting_State`` was on while the compressor was
stopped (at the stop or later), or is on when it starts again, the restart is not
counted (the pump picks up the run it interrupted), so a run is counted once however
many defrosts it has. The first
observation after a service start counts nothing (a compressor already running is no
start). The start times of the last 24 h are stored as the fact ``compressor_starts``
(``config.db``, :class:`~ovenbird.system.facts.Facts`) at every new start, so a restart
keeps the counts.

:func:`starts_exceeded` decides the ``compressor_starts`` monitor of
:mod:`ovenbird.control.monitors` (a warning): more than ``safety_starts_per_hour_max``
starts in the last 60 minutes and in the 60 minutes before them (two consecutive
hours), or more than ``safety_starts_per_day_max`` in the last 24 h.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ovenbird_core import Snapshot
from ovenbird_core.derived import compressor_running, defrost_active

if TYPE_CHECKING:
    from ovenbird.system.facts import Facts

LOGGER = logging.getLogger("ovenbird.control.starts")
STARTS_FACT: Final = "compressor_starts"
HOUR_S: Final = 3600.0
DAY_S: Final = 86_400.0


@dataclass(frozen=True, slots=True)
class StartCounts:
    """Compressor starts in the windows the alarm looks at.

    Parameters
    ----------
    last_hour
        Starts in the last 60 minutes.
    previous_hour
        Starts in the 60 minutes before those.
    last_day
        Starts in the last 24 h.
    """

    last_hour: int
    previous_hour: int
    last_day: int

    def to_json(self) -> dict[str, int]:
        """Return the API form."""
        return {
            "last_hour": self.last_hour,
            "previous_hour": self.previous_hour,
            "last_day": self.last_day,
        }


class StartCounter:
    """Count compressor starts without counting a defrost's restart.

    Parameters
    ----------
    starts
        Unix times of earlier starts (restored after a restart).
    min_frequency_hz
        Lowest compressor frequency counted as running.
    save
        Stores the start times of the last 24 h at every new start; ``None`` keeps them
        in memory.
    """

    def __init__(
        self,
        starts: Iterable[float] = (),
        *,
        min_frequency_hz: float = 1.0,
        save: Callable[[list[float]], None] | None = None,
    ) -> None:
        self.starts: deque[float] = deque(sorted(starts))
        self.min_frequency_hz = min_frequency_hz
        self.save = save
        self._running: bool | None = None
        self._stopped_in_defrost = False

    def observe(self, snapshot: Snapshot) -> bool:
        """Take one observation; return whether it saw a new start.

        A missing or stale compressor frequency leaves the state as it was.

        Parameters
        ----------
        snapshot
            Current signal snapshot with the compressor and defrost signals.
        """
        running = compressor_running(snapshot, min_frequency_hz=self.min_frequency_hz).value
        defrost = defrost_active(snapshot).value is True
        if running is None:
            return False
        previous, self._running = self._running, running
        now = snapshot.now.wall.timestamp()
        if previous is True and running is False:
            self._stopped_in_defrost = defrost
            return False
        if running is False:
            self._stopped_in_defrost = self._stopped_in_defrost or defrost
            return False
        if previous is not False:
            return False
        resumed = self._stopped_in_defrost or defrost
        self._stopped_in_defrost = False
        if resumed:
            return False
        self.starts.append(now)
        self._prune(now)
        if self.save is not None:
            try:
                self.save(list(self.starts))
            except Exception:
                LOGGER.exception("could not store the compressor starts")
        return True

    def counts(self, now: float) -> StartCounts:
        """Return the starts in the last hour, the hour before and the last 24 h at ``now``."""
        self._prune(now)
        last_hour = sum(1 for ts in self.starts if now - ts < HOUR_S)
        previous = sum(1 for ts in self.starts if HOUR_S <= now - ts < 2 * HOUR_S)
        return StartCounts(last_hour, previous, sum(1 for ts in self.starts if now - ts < DAY_S))

    def _prune(self, now: float) -> None:
        """Forget starts older than 24 h."""
        while self.starts and now - self.starts[0] >= DAY_S:
            self.starts.popleft()


def start_counter(facts: Facts, now: float, min_frequency_hz: float) -> StartCounter:
    """Return a counter restored from the fact ``compressor_starts`` and saving to it.

    Parameters
    ----------
    facts
        Persistent facts.
    now
        Unix seconds; only starts of the 24 h before it are kept.
    min_frequency_hz
        Lowest compressor frequency counted as running.
    """
    try:
        stored = facts.get(STARTS_FACT)
    except Exception:
        LOGGER.exception("cannot read the saved compressor starts")
        stored = None
    items = stored if isinstance(stored, list) else []
    starts = [
        float(ts)
        for ts in items
        if isinstance(ts, int | float) and not isinstance(ts, bool) and 0.0 <= now - ts < DAY_S
    ]
    return StartCounter(
        starts,
        min_frequency_hz=min_frequency_hz,
        save=lambda values: facts.set(STARTS_FACT, values),
    )


def starts_exceeded(counts: StartCounts, per_hour_max: int, per_day_max: int) -> str | None:
    """Return why the counts are too high (``None`` when they are not).

    Parameters
    ----------
    counts
        The current counts.
    per_hour_max
        Starts per hour allowed (exceeded in two consecutive hours alarms).
    per_day_max
        Starts per 24 h allowed.
    """
    if counts.last_hour > per_hour_max and counts.previous_hour > per_hour_max:
        return (
            f"{counts.last_hour} compressor starts in the last hour and {counts.previous_hour} in "
            f"the hour before (limit {per_hour_max} per hour); short runs wear the compressor"
        )
    if counts.last_day > per_day_max:
        return (
            f"{counts.last_day} compressor starts in the last 24 h (limit {per_day_max}); short "
            "runs wear the compressor"
        )
    return None

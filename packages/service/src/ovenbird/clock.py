"""Clock of the shell: the only place the service reads the time for the core.

Production uses :func:`system_clock`. A simulation (the dev stack with the simulated
HeishaMon) may run a :class:`ScaledClock`: simulated time passes ``speed`` times
faster than real time from a chosen start, so the controller's 60 s tick, dwell
times and command spacing all follow the simulated plant.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from ovenbird_core import Instant

type Clock = Callable[[], Instant]
type Sleep = Callable[[float], Awaitable[None]]


def system_clock() -> Instant:
    """Return the current instant from ``time.monotonic()`` and the UTC wall clock."""
    return Instant(time.monotonic(), datetime.now(UTC))


def iso_z(moment: datetime) -> str:
    """Format an aware datetime as an ISO 8601 UTC string with a ``Z`` suffix.

    Parameters
    ----------
    moment
        Timezone-aware datetime.

    Returns
    -------
    str
        Whole seconds when there is no sub-second part, otherwise milliseconds.
    """
    utc = moment.astimezone(UTC)
    spec = "seconds" if utc.microsecond == 0 else "milliseconds"
    return utc.replace(tzinfo=None).isoformat(timespec=spec) + "Z"


def iso_from_unix(seconds: float) -> str:
    """Format unix seconds as an ISO 8601 UTC string; see :func:`iso_z`."""
    return iso_z(datetime.fromtimestamp(seconds, UTC))


class ScaledClock:
    """A clock running ``speed`` times faster than real time from ``start``.

    Parameters
    ----------
    speed
        Simulated seconds per real second.
    start
        Wall time at construction; the current UTC time when ``None``.
    monotonic
        Real monotonic time source (injectable for tests).
    """

    def __init__(
        self,
        speed: float,
        start: datetime | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not speed > 0:
            raise ValueError("speed must be positive")
        self.speed = speed
        self._monotonic = monotonic
        self._origin = monotonic()
        self._start = start or datetime.now(UTC)

    def __call__(self) -> Instant:
        """Return the current simulated instant."""
        elapsed = (self._monotonic() - self._origin) * self.speed
        return Instant(self._origin + elapsed, self._start + timedelta(seconds=elapsed))

    async def sleep(self, seconds: float) -> None:
        """Sleep ``seconds`` of simulated time."""
        await asyncio.sleep(seconds / self.speed)


def build_clock(speed: float, start: datetime | None) -> Clock:
    """Return :func:`system_clock` for real time, otherwise a :class:`ScaledClock`."""
    if speed == 1.0 and start is None:
        return system_clock
    return ScaledClock(speed, start)


def sleeper(clock: Clock) -> Sleep:
    """Return a sleep function measuring time on ``clock``."""
    if isinstance(clock, ScaledClock):
        return clock.sleep
    return asyncio.sleep

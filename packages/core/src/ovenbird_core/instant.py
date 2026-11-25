"""Time model: every point in time carries a monotonic and a wall-clock reading.

Staleness and ages are measured on the monotonic axis, which never jumps when the
system clock is corrected; schedules, tariffs and forecasts are evaluated on the
wall-clock axis in UTC. The core never reads a clock itself: the shell builds an
:class:`Instant` from ``time.monotonic()`` and ``datetime.now(UTC)``, a replay
builds one from the recorded timestamp.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import total_ordering


@total_ordering
@dataclass(frozen=True, slots=True, eq=False)
class Instant:
    """A point in time on both the monotonic and the wall-clock axis.

    Equality and ordering follow the monotonic axis only.

    Parameters
    ----------
    monotonic
        Seconds on a monotonic clock with an arbitrary origin.
    wall
        Timezone-aware wall-clock time; normalised to UTC.

    Raises
    ------
    ValueError
        When ``monotonic`` is not finite or ``wall`` is naive.
    """

    monotonic: float
    wall: datetime

    def __post_init__(self) -> None:
        """Validate and normalise the fields."""
        if not math.isfinite(self.monotonic):
            raise ValueError(f"monotonic time must be finite, got {self.monotonic!r}")
        if self.wall.tzinfo is None or self.wall.utcoffset() is None:
            raise ValueError("wall-clock time must be timezone-aware")
        if self.wall.tzinfo is not UTC:
            object.__setattr__(self, "wall", self.wall.astimezone(UTC))

    @classmethod
    def from_unix(cls, t: float) -> Instant:
        """Build an instant from unix seconds, using them as the monotonic reading too.

        Parameters
        ----------
        t
            Unix timestamp in seconds.

        Returns
        -------
        Instant
            Instant whose monotonic reading equals ``t``.
        """
        return cls(float(t), datetime.fromtimestamp(t, UTC))

    @classmethod
    def from_capture(cls, t: float) -> Instant:
        """Build the instant of a capture record (``t`` is the recorder's receipt time).

        A replay has no separate monotonic clock, so the recorded unix time serves as
        both axes; recorder restarts show up as gaps, exactly as recorded.

        Parameters
        ----------
        t
            The record's ``t`` field in unix seconds.

        Returns
        -------
        Instant
            The record's instant.
        """
        return cls.from_unix(t)

    def since(self, earlier: Instant) -> float:
        """Return monotonic seconds elapsed from ``earlier`` to this instant."""
        return self.monotonic - earlier.monotonic

    def shifted(self, seconds: float) -> Instant:
        """Return the instant ``seconds`` later on both axes."""
        return Instant(self.monotonic + seconds, self.wall + timedelta(seconds=seconds))

    def __eq__(self, other: object) -> bool:
        """Compare on the monotonic axis."""
        if not isinstance(other, Instant):
            return NotImplemented
        return self.monotonic == other.monotonic

    def __lt__(self, other: Instant) -> bool:
        """Order on the monotonic axis."""
        return self.monotonic < other.monotonic

    def __hash__(self) -> int:
        """Hash on the monotonic axis."""
        return hash(self.monotonic)

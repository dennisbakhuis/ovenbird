"""A manually stepped service clock with independent monotonic and wall axes."""

from __future__ import annotations

from datetime import UTC, datetime

from ovenbird_core import Instant


class ManualClock:
    """Clock of the stepped service; the driver sets every instant explicitly.

    Parameters
    ----------
    wall
        Initial wall time in unix seconds.
    monotonic_offset
        ``monotonic = wall - monotonic_offset``; a restarted service gets a new offset,
        as a new process gets a new monotonic origin.
    """

    def __init__(self, wall: float, monotonic_offset: float = 0.0) -> None:
        self.monotonic_offset = monotonic_offset
        self._instant = self._at(wall)

    def _at(self, wall: float) -> Instant:
        return Instant(wall - self.monotonic_offset, datetime.fromtimestamp(wall, UTC))

    def __call__(self) -> Instant:
        """Return the current instant."""
        return self._instant

    def set(self, wall: float) -> Instant:
        """Move the clock to wall time ``wall`` (unix seconds) and return the instant."""
        self._instant = self._at(wall)
        return self._instant

    def set_instant(self, instant: Instant) -> None:
        """Set an exact instant (replay of a recorded run)."""
        self._instant = instant

    @property
    def wall(self) -> float:
        """Current wall time in unix seconds."""
        return self._instant.wall.timestamp()

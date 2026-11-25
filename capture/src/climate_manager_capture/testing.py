"""Helpers for tests that drive the clock-injected components."""

from __future__ import annotations


class FakeClock:
    """A manually advanced clock usable wherever a ``clock`` callable is expected."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        """Return the current fake time."""
        return self.now

    def advance(self, seconds: float) -> None:
        """Move the clock forward; also usable as a ``sleep`` replacement."""
        self.now += seconds

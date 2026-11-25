"""Exponential reconnect backoff shared by the input clients and the supervisor."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Backoff:
    """Delay that doubles per consecutive failure and resets after a stable session.

    Parameters
    ----------
    initial
        First delay in seconds.
    cap
        Largest delay in seconds.
    stable_after
        A session that lasted at least this long resets the failure count.
    """

    initial: float = 1.0
    cap: float = 60.0
    stable_after: float = 60.0
    failures: int = 0

    def next_delay(self, session_s: float = 0.0) -> float:
        """Register a failure and return the delay before the next attempt.

        Parameters
        ----------
        session_s
            How long the failed session lasted.

        Returns
        -------
        float
            Seconds to wait.
        """
        if session_s >= self.stable_after:
            self.failures = 0
        self.failures += 1
        return float(min(self.cap, self.initial * 2 ** (self.failures - 1)))

    def reset(self) -> None:
        """Forget earlier failures."""
        self.failures = 0

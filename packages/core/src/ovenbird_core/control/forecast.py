"""Forecast hours as the service stores them, for plan rules that look ahead.

Pure and immutable: one row per whole hour with the air temperature at that hour and
the global horizontal irradiance over the hour before it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

__all__ = ["HISTORY_S", "HOUR_S", "ForecastHour"]

HOUR_S: Final = 3600.0
HISTORY_S: Final = 24 * HOUR_S


def _require_finite(name: str, value: float) -> None:
    """Raise ``ValueError`` when ``value`` is not finite."""
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")


@dataclass(frozen=True, slots=True)
class ForecastHour:
    """One forecast hour, as stored (the shortest lead available for that hour).

    Parameters
    ----------
    target_ts
        The hour it describes, unix seconds on a whole hour.
    outside_c
        Air temperature at ``target_ts`` (``None``: missing).
    ghi_w_m2
        Global horizontal irradiance, mean over the hour *before* ``target_ts``
        (``None``: missing).
    """

    target_ts: float
    outside_c: float | None
    ghi_w_m2: float | None

    def __post_init__(self) -> None:
        """Reject a time off the hour, non-finite values and negative irradiance."""
        _require_finite("target_ts", self.target_ts)
        if self.target_ts % HOUR_S != 0.0:
            raise ValueError("forecast hours must lie on whole hours")
        if self.outside_c is not None:
            _require_finite("outside_c", self.outside_c)
        if self.ghi_w_m2 is not None:
            _require_finite("ghi_w_m2", self.ghi_w_m2)
            if self.ghi_w_m2 < 0.0:
                raise ValueError("ghi_w_m2 must be non-negative")

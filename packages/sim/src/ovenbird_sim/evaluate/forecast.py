"""Forecast views for closed-loop runs: what the planner sees instead of the truth.

A :class:`TableForecast` holds the *intended* forecast on an hourly grid (the truth for a
perfect forecast, anything else for a deliberate mismatch such as sun forecast but not
delivered) and turns it into the rows the service stores: for every hour the shortest
lead forecast available, with the format of
:class:`~ovenbird_core.control.forecast.ForecastHour` (temperature at the hour mark,
irradiance as the mean over the hour before it).

**Error model (:class:`ForecastError`)**
Everything is seeded: a draw depends only on the seed and on the day or hour it belongs
to, never on the order of the calls, so two runs with the same seed see the same
forecast.

``ghi_factor``
    The irradiance of a day is multiplied by ``exp(sigma z - sigma^2 / 2)`` with ``z``
    standard normal, drawn once per UTC day (``sigma`` = :attr:`ForecastError.ghi_sigma`,
    mean factor 1). This is the dominant real error: a forecast mixes up clear and
    cloudy days, not single hours.
``bias``
    A temperature offset in K drawn once per UTC day (standard deviation
    :attr:`ForecastError.bias_sigma_k`).
``noise``
    Independent temperature noise in K per hour (standard deviation
    :attr:`ForecastError.noise_sigma_k`).

The error grows with the lead time: the weight is ``min(1, lead / ramp_h)`` with the
lead the hour's distance in the future, so past hours (stored with the shortest lead)
are the truth and an hour ``ramp_h`` or more ahead carries the full error. This keeps
the forecast continuous at ``now`` the way a real one is after the pump's sensor has
caught up with it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np

from ovenbird_core.control.forecast import HISTORY_S, HOUR_S, ForecastHour
from ovenbird_core.instant import Instant
from ovenbird_sim.data.series import FloatArray
from ovenbird_sim.evaluate.closedloop import Weather

DAY_S: Final = 86400.0
HOURS_PER_DAY: Final = 24
LOOKAHEAD_S: Final = 14 * HOUR_S
SALT_GHI: Final = 1
SALT_BIAS: Final = 2
SALT_NOISE: Final = 3


@dataclass(frozen=True, slots=True)
class ForecastError:
    """Error model of a forecast (see the module docstring).

    Parameters
    ----------
    ghi_sigma
        Spread of the day-level irradiance factor (log scale).
    bias_sigma_k
        Standard deviation of the day-level temperature offset.
    noise_sigma_k
        Standard deviation of the hourly temperature noise.
    ramp_h
        Lead time in hours at which the error reaches its full size.
    seed
        Seed of all draws.
    """

    ghi_sigma: float = 0.4
    bias_sigma_k: float = 1.0
    noise_sigma_k: float = 0.5
    ramp_h: float = 6.0
    seed: int = 0

    def weight(self, lead_s: float) -> float:
        """Return the share of the error that applies at a lead time (0 for the past)."""
        if self.ramp_h <= 0.0:
            return 1.0 if lead_s > 0.0 else 0.0
        return min(1.0, max(0.0, lead_s / (self.ramp_h * HOUR_S)))

    def _draw(self, salt: int, index: int) -> float:
        """Return a standard-normal draw for ``salt`` and ``index``, fixed by the seed."""
        rng = np.random.default_rng([self.seed, salt, index + 1_000_000])
        return float(rng.standard_normal())

    def ghi_factor(self, day: int) -> float:
        """Return the irradiance factor of UTC day ``day`` (mean 1)."""
        sigma = self.ghi_sigma
        return math.exp(sigma * self._draw(SALT_GHI, day) - 0.5 * sigma * sigma)

    def bias_k(self, day: int) -> float:
        """Return the temperature offset of UTC day ``day``."""
        return self.bias_sigma_k * self._draw(SALT_BIAS, day)

    def noise_k(self, hour_index: int) -> float:
        """Return the temperature noise of the hour with index ``hour_index``."""
        return self.noise_sigma_k * self._draw(SALT_NOISE, hour_index)


@dataclass(frozen=True, slots=True)
class TableForecast:
    """Hourly forecast table with an optional error model, as a closed-loop forecast view.

    The table covers the hours ``first_ts + k 3600``; an hour before it repeats the same
    hour of the table's first day and an hour after it repeats the last day, so the
    planner has its 24 h of history from the first tick on.

    Parameters
    ----------
    first_ts
        Time of the first hour mark (unix s, a whole hour).
    outside_c
        Forecast outside temperature at each hour mark.
    ghi_w_m2
        Forecast irradiance, mean over the hour before each hour mark.
    error
        Error model (``None``: the table is delivered as it is).
    """

    first_ts: float
    outside_c: FloatArray
    ghi_w_m2: FloatArray
    error: ForecastError | None = None

    def _index(self, hour_ts: float) -> int:
        """Return the series index of the hour at ``hour_ts``, wrapping by whole days."""
        count = int(self.outside_c.size)
        k = round((hour_ts - self.first_ts) / HOUR_S)
        if 0 <= k < count:
            return k
        if k < 0:
            return k % HOURS_PER_DAY
        return count - HOURS_PER_DAY + (k - count) % HOURS_PER_DAY

    def row(self, hour_ts: float, now_ts: float) -> ForecastHour:
        """Return the stored forecast for the hour ending at ``hour_ts`` as seen at ``now_ts``."""
        k = self._index(hour_ts)
        outside = float(self.outside_c[k])
        ghi = float(self.ghi_w_m2[k])
        if self.error is not None:
            w = self.error.weight(hour_ts - now_ts)
            if w > 0.0:
                day = math.floor(hour_ts / DAY_S)
                hour_index = round(hour_ts / HOUR_S)
                factor = self.error.ghi_factor(day)
                ghi *= 1.0 + w * (factor - 1.0)
                outside += w * (self.error.bias_k(day) + self.error.noise_k(hour_index))
        return ForecastHour(hour_ts, round(outside, 3), round(max(ghi, 0.0), 3))

    def rows(self, now: Instant) -> tuple[ForecastHour, ...]:
        """Return the rows from 24 h (and one hour) before ``now`` to 14 h after it."""
        now_ts = now.wall.timestamp()
        first = math.floor((now_ts - HISTORY_S) / HOUR_S) * HOUR_S - HOUR_S
        last = math.ceil((now_ts + LOOKAHEAD_S) / HOUR_S) * HOUR_S
        count = round((last - first) / HOUR_S) + 1
        return tuple(self.row(first + k * HOUR_S, now_ts) for k in range(count))


def hourly_table(weather: Weather, ghi_w_m2: FloatArray | None = None) -> TableForecast:
    """Return the perfect forecast table of ``weather`` (or of a replacement irradiance).

    Parameters
    ----------
    weather
        Per-tick truth (``t0`` on a whole hour, ``dt`` dividing an hour).
    ghi_w_m2
        Per-tick irradiance to forecast instead of the truth (the same length).

    Returns
    -------
    TableForecast
        Temperature at each hour mark and the mean irradiance of the hour before it.

    Raises
    ------
    ValueError
        When the weather is shorter than one day.
    """
    per_hour = round(HOUR_S / weather.dt)
    sun = weather.ghi_w_m2 if ghi_w_m2 is None else ghi_w_m2
    hours = weather.n // per_hour
    if hours < HOURS_PER_DAY:
        raise ValueError("a forecast table needs at least one day of weather")
    outside = np.asarray(weather.outside_c[::per_hour][:hours], dtype=np.float64)
    blocks = np.asarray(sun[: hours * per_hour], dtype=np.float64).reshape(hours, per_hour)
    ghi = np.concatenate([[blocks[0].mean()], blocks.mean(axis=1)])[:hours]
    return TableForecast(weather.t0, outside, ghi)


def sample_error(error: ForecastError, days: Sequence[int]) -> list[tuple[float, float]]:
    """Return ``(ghi_factor, bias_k)`` per day, for documentation and tests."""
    return [(error.ghi_factor(d), error.bias_k(d)) for d in days]

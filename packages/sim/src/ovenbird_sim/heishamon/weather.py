"""Exogenous inputs of the simulated house: recorded weather or a synthetic cold week."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, Protocol

import numpy as np

from ovenbird_sim.data.series import Series
from ovenbird_sim.data.weather import CACHE_NAME, load_weather
from ovenbird_sim.model import Exogenous

SECONDS_PER_DAY: Final = 86_400.0
SECONDS_PER_HOUR: Final = 3600.0
TEMPERATURE_KEY: Final = "wx/temperature_2m"
RADIATION_KEY: Final = "wx/shortwave_radiation"
COLD_WEEK_MEANS_C: Final = (-1.0, -3.0, -5.5, -7.0, -6.0, -3.5, -1.5)
COLD_WEEK_CLEARNESS: Final = (0.3, 0.8, 1.0, 0.9, 0.5, 0.2, 0.6)
COLD_WEEK_SWING_K: Final = 3.0
COLD_WEEK_WARMEST_HOUR: Final = 15.0
SUN_RISE_HOUR: Final = 8.5
SUN_SET_HOUR: Final = 16.5
SUN_PEAK_W_M2: Final = 260.0


class Weather(Protocol):
    """Source of exogenous inputs at a unix time."""

    @property
    def name(self) -> str:
        """Scenario name."""
        ...

    def at(self, unix_s: float, local_hour: float) -> Exogenous:
        """Return the inputs at ``unix_s`` (``local_hour`` is the local clock hour)."""
        ...


def local_hour(unix_s: float, utc_offset_h: float) -> float:
    """Local clock hour in ``[0, 24)`` for a fixed UTC offset."""
    return ((unix_s / SECONDS_PER_HOUR) + utc_offset_h) % 24.0


def _interp(series: Series, unix_s: float) -> float:
    valid = np.isfinite(series.v)
    return float(np.interp(unix_s, series.t[valid], series.v[valid]))


@dataclass(frozen=True, slots=True)
class RecordedWeather:
    """Hourly Open-Meteo weather from the local cache, linearly interpolated.

    Times outside the cache hold the first or last value.

    Parameters
    ----------
    temperature
        Air temperature series.
    radiation
        Global horizontal irradiance series.
    name
        Scenario name.
    """

    temperature: Series
    radiation: Series
    name: str = "recorded"

    @classmethod
    def load(cls, directory: Path) -> RecordedWeather:
        """Load the cache in ``directory``.

        Raises
        ------
        FileNotFoundError
            When the directory holds no weather cache.
        """
        series = load_weather(directory)
        if TEMPERATURE_KEY not in series:
            raise FileNotFoundError(f"no weather cache at {directory / CACHE_NAME}")
        radiation = series.get(RADIATION_KEY) or Series.from_pairs([0.0], [0.0])
        return cls(series[TEMPERATURE_KEY], radiation)

    def covers(self, unix_s: float) -> bool:
        """Whether ``unix_s`` lies inside the recorded temperature range."""
        t = self.temperature.t
        return t.size > 0 and float(t[0]) <= unix_s <= float(t[-1])

    @property
    def start_s(self) -> float | None:
        """First recorded instant (unix s); ``None`` for an empty cache."""
        t = self.temperature.t
        return float(t[0]) if t.size else None

    @property
    def end_s(self) -> float | None:
        """Last recorded instant (unix s); ``None`` for an empty cache."""
        t = self.temperature.t
        return float(t[-1]) if t.size else None

    def at(self, unix_s: float, local_hour: float) -> Exogenous:
        """Return the interpolated weather at ``unix_s``."""
        solar = max(_interp(self.radiation, unix_s), 0.0)
        return Exogenous(_interp(self.temperature, unix_s), solar, local_hour)


@dataclass(frozen=True, slots=True)
class ColdWeek:
    """Deterministic synthetic cold week, repeating every seven days from ``start``.

    Daily mean temperatures fall from -1 °C to -7 °C and recover; a 3 K diurnal swing
    peaks at 15:00 local; a winter sun shines between 08:30 and 16:30 local, scaled
    per day by a clearness factor.

    Parameters
    ----------
    start
        Start of the week.
    name
        Scenario name.
    """

    start: datetime
    name: str = "cold-week"

    def _day_position(self, unix_s: float) -> float:
        return ((unix_s - self.start.timestamp()) / SECONDS_PER_DAY) % len(COLD_WEEK_MEANS_C)

    def mean_c(self, unix_s: float) -> float:
        """Daily mean temperature, interpolated between day centres."""
        position = self._day_position(unix_s) - 0.5
        days = len(COLD_WEEK_MEANS_C)
        lower = math.floor(position)
        fraction = position - lower
        a = COLD_WEEK_MEANS_C[lower % days]
        b = COLD_WEEK_MEANS_C[(lower + 1) % days]
        return a + fraction * (b - a)

    def at(self, unix_s: float, local_hour: float) -> Exogenous:
        """Return the synthetic weather at ``unix_s``."""
        angle = 2.0 * math.pi * (local_hour - COLD_WEEK_WARMEST_HOUR) / 24.0
        outside = self.mean_c(unix_s) + COLD_WEEK_SWING_K * math.cos(angle)
        solar = 0.0
        if SUN_RISE_HOUR < local_hour < SUN_SET_HOUR:
            phase = (local_hour - SUN_RISE_HOUR) / (SUN_SET_HOUR - SUN_RISE_HOUR)
            day = int(self._day_position(unix_s))
            solar = SUN_PEAK_W_M2 * COLD_WEEK_CLEARNESS[day] * math.sin(math.pi * phase)
        return Exogenous(outside, solar, local_hour)


@dataclass(frozen=True, slots=True)
class LoopedWeather:
    """Recorded weather repeated end to start, so the simulation never runs out.

    The local hour still follows the simulated clock; only the weather wraps (a jump in
    outside temperature at each wrap).

    Parameters
    ----------
    recorded
        The recording to repeat.
    """

    recorded: RecordedWeather

    @property
    def name(self) -> str:
        """Scenario name."""
        return f"{self.recorded.name} (looped)"

    def at(self, unix_s: float, local_hour: float) -> Exogenous:
        """Return the recorded weather at ``unix_s`` folded into the recorded range."""
        first, last = self.recorded.start_s, self.recorded.end_s
        if first is None or last is None or last <= first or unix_s <= last:
            return self.recorded.at(unix_s, local_hour)
        return self.recorded.at(first + (unix_s - first) % (last - first), local_hour)


def weather_end(weather: Weather) -> float | None:
    """Return when ``weather`` runs out (unix s), ``None`` for an endless source."""
    end = getattr(weather, "end_s", None)
    return float(end) if isinstance(end, int | float) else None

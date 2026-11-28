"""Weather forecast providers: Open-Meteo (live) and a simulated one (simulation mode).

:class:`OpenMeteoProvider` fetches ``https://api.open-meteo.com/v1/forecast`` (hourly
``temperature_2m``, ``shortwave_radiation``, ``cloud_cover``, ``wind_speed_10m``,
``past_days=1``, ``forecast_days=3``, UTC, unix times, wind in m/s) with the standard
library's ``urllib``: no API key, no extra dependency. Its :meth:`~OpenMeteoProvider.fetch`
blocks and is run in a thread by :class:`~ovenbird.weather.service.WeatherService`.

:class:`SimulatedProvider` never touches the network: it derives a "forecast" from an
hourly weather series (the simulator's Open-Meteo cache file, or a synthetic cold
week) plus lead-time dependent noise, seeded by issue and target hour so a forecast
is reproducible. It follows whatever clock calls it, so on the dev stack's scaled clock
the issues match the simulated weather the plant model sees.
"""

from __future__ import annotations

import json
import math
import random
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol

from ovenbird import __version__

OPEN_METEO_URL: Final = "https://api.open-meteo.com/v1/forecast"
HOURLY_FIELDS: Final = ("temperature_2m", "shortwave_radiation", "cloud_cover", "wind_speed_10m")
PAST_DAYS: Final = 1
FORECAST_DAYS: Final = 3
TIMEOUT_S: Final = 20.0
MAX_BODY_BYTES: Final = 2 * 1024 * 1024
HOUR_S: Final = 3600.0
KMH_PER_MS: Final = 3.6
LOCATION_DECIMALS: Final = 2
NOISE_BASE_K: Final = 0.3
NOISE_PER_HOUR_K: Final = 0.04
NOISE_MAX_K: Final = 3.0
SYNTHETIC_MEAN_C: Final = 2.0
SYNTHETIC_SWING_K: Final = 3.0
SYNTHETIC_DAY_SWING_K: Final = 4.0
SYNTHETIC_PEAK_WM2: Final = 260.0


class WeatherError(RuntimeError):
    """A forecast could not be fetched or parsed."""


@dataclass(frozen=True, slots=True)
class ForecastHour:
    """One hour of a forecast.

    Parameters
    ----------
    target_ts
        The hour (unix seconds).
    temp_c
        Air temperature at 2 m.
    radiation_wm2
        Global horizontal irradiance.
    cloud_pct
        Cloud cover.
    wind_ms
        Wind speed at 10 m.
    """

    target_ts: float
    temp_c: float | None
    radiation_wm2: float | None
    cloud_pct: float | None
    wind_ms: float | None


@dataclass(frozen=True, slots=True)
class Forecast:
    """One forecast issue.

    Parameters
    ----------
    issued_ts
        When it was fetched (service clock).
    hours
        Hourly values, by target time.
    """

    issued_ts: float
    hours: tuple[ForecastHour, ...]


class WeatherProvider(Protocol):
    """Fetches one forecast for a location (blocking)."""

    @property
    def name(self) -> str:
        """Provider name (``open-meteo`` or ``simulated``)."""
        ...

    def fetch(self, latitude: float, longitude: float, now_ts: float) -> Forecast:
        """Return the forecast issued at ``now_ts``.

        Raises
        ------
        WeatherError
            When no forecast could be obtained.
        """
        ...


def rounded(value: float) -> float:
    """Round a coordinate to 0.01° (about 1 km), as it leaves the house."""
    return round(value, LOCATION_DECIMALS)


def forecast_url(latitude: float, longitude: float) -> str:
    """Return the Open-Meteo request for a location (coordinates rounded to 0.01°)."""
    query = urllib.parse.urlencode(
        {
            "latitude": f"{rounded(latitude):.2f}",
            "longitude": f"{rounded(longitude):.2f}",
            "hourly": ",".join(HOURLY_FIELDS),
            "past_days": PAST_DAYS,
            "forecast_days": FORECAST_DAYS,
            "timezone": "UTC",
            "timeformat": "unixtime",
            "wind_speed_unit": "ms",
        }
    )
    return f"{OPEN_METEO_URL}?{query}"


def _number(value: Any) -> float | None:
    """Return ``value`` as a finite float, or ``None``."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _column(hourly: Mapping[str, Any], name: str, length: int) -> list[Any]:
    """Return the hourly column ``name``, ``None`` per hour when absent.

    Raises ``WeatherError`` when its length differs from the time axis.
    """
    values = hourly.get(name)
    if values is None:
        return [None] * length
    if not isinstance(values, list) or len(values) != length:
        raise WeatherError(f"hourly {name} does not match the time axis")
    return values


def parse_open_meteo(body: Mapping[str, Any], issued_ts: float) -> Forecast:
    """Parse an Open-Meteo forecast response (``timeformat=unixtime``).

    Parameters
    ----------
    body
        The decoded JSON response.
    issued_ts
        Issue time to record.

    Returns
    -------
    Forecast
        Every hour with a valid time; missing values are ``None``.

    Raises
    ------
    WeatherError
        When the response is an error or has no usable hourly block.
    """
    if body.get("error"):
        raise WeatherError(f"Open-Meteo error: {str(body.get('reason', 'unknown'))[:200]}")
    hourly = body.get("hourly")
    if not isinstance(hourly, dict) or not isinstance(hourly.get("time"), list):
        raise WeatherError("the response has no hourly block")
    times = hourly["time"]
    units = body.get("hourly_units")
    wind_unit = units.get("wind_speed_10m") if isinstance(units, dict) else None
    wind_factor = 1.0 / KMH_PER_MS if wind_unit == "km/h" else 1.0
    columns = [_column(hourly, name, len(times)) for name in HOURLY_FIELDS]
    hours: list[ForecastHour] = []
    for index, raw in enumerate(times):
        target = _number(raw)
        if target is None:
            continue
        temp, radiation, cloud, wind = (_number(column[index]) for column in columns)
        hours.append(
            ForecastHour(
                target,
                temp,
                radiation,
                cloud,
                None if wind is None else round(wind * wind_factor, 2),
            )
        )
    if not hours:
        raise WeatherError("the response has no hours")
    return Forecast(issued_ts, tuple(sorted(hours, key=lambda hour: hour.target_ts)))


type Opener = Callable[[str], bytes]


def _urlopen(url: str) -> bytes:
    """Return the body of an https URL (size capped), refusing other schemes."""
    if not url.startswith("https://"):
        raise WeatherError("only https URLs are fetched")
    request = urllib.request.Request(  # noqa: S310
        url, headers={"User-Agent": f"ovenbird/{__version__}", "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
        body: bytes = response.read(MAX_BODY_BYTES + 1)
    if len(body) > MAX_BODY_BYTES:
        raise WeatherError("the response is too large")
    return body


@dataclass(frozen=True, slots=True)
class OpenMeteoProvider:
    """The Open-Meteo forecast API.

    Parameters
    ----------
    opener
        Returns the body of a GET request (injectable; tests never use the network).
    """

    opener: Opener = _urlopen
    name: str = "open-meteo"

    def fetch(self, latitude: float, longitude: float, now_ts: float) -> Forecast:
        """Fetch and parse the forecast for a location.

        Raises
        ------
        WeatherError
            On a network, HTTP or format problem.
        """
        try:
            raw = self.opener(forecast_url(latitude, longitude))
            body = json.loads(raw)
        except WeatherError:
            raise
        except (OSError, ValueError) as exc:
            raise WeatherError(f"Open-Meteo request failed: {type(exc).__name__}") from None
        if not isinstance(body, dict):
            raise WeatherError("the response is not a JSON object")
        return parse_open_meteo(body, now_ts)


@dataclass(frozen=True, slots=True)
class HourlySeries:
    """An hourly weather series (the source of the simulated forecast).

    Parameters
    ----------
    times
        Unix times, increasing.
    temp_c, radiation_wm2, cloud_pct, wind_ms
        Values per time (``None`` when missing).
    """

    times: tuple[float, ...]
    temp_c: tuple[float | None, ...]
    radiation_wm2: tuple[float | None, ...]
    cloud_pct: tuple[float | None, ...]
    wind_ms: tuple[float | None, ...]

    def __post_init__(self) -> None:
        """Check that the series is aligned and not empty."""
        length = len(self.times)
        if length == 0:
            raise ValueError("an hourly series needs at least one hour")
        for values in (self.temp_c, self.radiation_wm2, self.cloud_pct, self.wind_ms):
            if len(values) != length:
                raise ValueError("hourly columns must align with the times")

    @classmethod
    def load(cls, path: Path) -> HourlySeries:
        """Load the simulator's Open-Meteo cache (``open_meteo_hourly.json``).

        Parameters
        ----------
        path
            Cache file to read.

        Raises
        ------
        ValueError
            When the file is not such a cache.
        """
        body = json.loads(path.read_text(encoding="utf-8"))
        hourly = body.get("hourly") if isinstance(body, dict) else None
        if not isinstance(hourly, dict) or not isinstance(hourly.get("time"), list):
            raise ValueError(f"{path.name} is not an Open-Meteo hourly cache")
        times = hourly["time"]
        columns = [_column(hourly, name, len(times)) for name in HOURLY_FIELDS]
        hours: list[ForecastHour] = []
        for index, raw in enumerate(times):
            ts = _number(raw)
            if ts is None:
                continue
            temp, radiation, cloud, wind = (_number(column[index]) for column in columns)
            hours.append(
                ForecastHour(
                    ts, temp, radiation, cloud, None if wind is None else wind / KMH_PER_MS
                )
            )
        if not hours:
            raise ValueError(f"{path.name} holds no hours")
        hours.sort(key=lambda hour: hour.target_ts)
        return cls(
            times=tuple(hour.target_ts for hour in hours),
            temp_c=tuple(hour.temp_c for hour in hours),
            radiation_wm2=tuple(hour.radiation_wm2 for hour in hours),
            cloud_pct=tuple(hour.cloud_pct for hour in hours),
            wind_ms=tuple(hour.wind_ms for hour in hours),
        )

    def _at(self, values: Sequence[float | None], ts: float) -> float | None:
        """Return the value at ``ts`` by linear interpolation, holding the end values.

        Gaps are skipped.

        Parameters
        ----------
        values
            One value per hour of the series, ``None`` where unknown.
        ts
            Time to read, Unix seconds.
        """
        times = self.times
        if ts <= times[0]:
            return values[0]
        if ts >= times[-1]:
            return values[-1]
        low, high = 0, len(times) - 1
        while high - low > 1:
            middle = (low + high) // 2
            if times[middle] <= ts:
                low = middle
            else:
                high = middle
        a, b = values[low], values[high]
        if a is None or b is None:
            return a if b is None else b
        fraction = (ts - times[low]) / (times[high] - times[low])
        return a + fraction * (b - a)

    def at(self, ts: float) -> ForecastHour:
        """Return the (interpolated) values at ``ts``; the ends are held."""
        return ForecastHour(
            ts,
            self._at(self.temp_c, ts),
            self._at(self.radiation_wm2, ts),
            self._at(self.cloud_pct, ts),
            self._at(self.wind_ms, ts),
        )


def synthetic_series(start_ts: float, days: int = 400) -> HourlySeries:
    """Return a synthetic winter series: a slow weekly swing plus a daily cycle and sun.

    Parameters
    ----------
    start_ts
        Time the series is built around, Unix seconds.
    days
        Number of days to generate.
    """
    times: list[float] = []
    temps: list[float | None] = []
    radiation: list[float | None] = []
    cloud: list[float | None] = []
    wind: list[float | None] = []
    origin = math.floor(start_ts / HOUR_S) * HOUR_S - 30 * 86_400.0
    for index in range(days * 24):
        ts = origin + index * HOUR_S
        hour = (ts / HOUR_S) % 24.0
        week = math.sin(2.0 * math.pi * ts / (7 * 86_400.0))
        day = math.sin(2.0 * math.pi * (hour - 9.0) / 24.0)
        sun = max(0.0, math.sin(math.pi * (hour - 8.0) / 8.5))
        cover = 55.0 + 40.0 * math.sin(ts / (7 * HOUR_S))
        times.append(ts)
        temps.append(SYNTHETIC_MEAN_C + SYNTHETIC_SWING_K * week + SYNTHETIC_DAY_SWING_K * day / 2)
        radiation.append(round(SYNTHETIC_PEAK_WM2 * sun * (1.0 - cover / 130.0), 1))
        cloud.append(round(cover))
        wind.append(round(3.0 + 2.0 * math.sin(ts / (9 * HOUR_S)), 1))
    return HourlySeries(tuple(times), tuple(temps), tuple(radiation), tuple(cloud), tuple(wind))


@dataclass(frozen=True, slots=True)
class SimulatedProvider:
    """A forecast derived from an hourly series plus lead-time noise (no network).

    Parameters
    ----------
    series
        The "true" weather.
    seed
        Noise seed.
    """

    series: HourlySeries
    seed: int = 1
    name: str = "simulated"

    def _noise(self, issued_hour: int, target_hour: int, lead_h: float) -> float:
        """Return the reproducible forecast error (K) for a forecast issued ``lead_h`` ahead."""
        if lead_h <= 0:
            return 0.0
        rng = random.Random(f"{self.seed}:{issued_hour}:{target_hour}")
        sigma = min(NOISE_MAX_K, NOISE_BASE_K + NOISE_PER_HOUR_K * lead_h)
        return rng.gauss(0.0, sigma)

    def fetch(self, latitude: float, longitude: float, now_ts: float) -> Forecast:
        """Return the simulated forecast issued at ``now_ts`` (past day plus three days)."""
        del latitude, longitude
        first = math.floor(now_ts / HOUR_S) * HOUR_S - PAST_DAYS * 86_400.0
        count = (PAST_DAYS + FORECAST_DAYS) * 24
        issued_hour = int(now_ts // HOUR_S)
        hours: list[ForecastHour] = []
        for index in range(count):
            target = first + index * HOUR_S
            true = self.series.at(target)
            lead_h = (target - now_ts) / HOUR_S
            noise = self._noise(issued_hour, int(target // HOUR_S), lead_h)
            temp = None if true.temp_c is None else round(true.temp_c + noise, 1)
            hours.append(
                ForecastHour(
                    target,
                    temp,
                    None if true.radiation_wm2 is None else round(true.radiation_wm2, 1),
                    None if true.cloud_pct is None else round(true.cloud_pct),
                    None if true.wind_ms is None else round(true.wind_ms, 1),
                )
            )
        return Forecast(now_ts, tuple(hours))

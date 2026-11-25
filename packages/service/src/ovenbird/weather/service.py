"""The weather component: fetch a forecast every hour and store it as issued.

Off unless ``weather_enabled`` is set **and** a location is known: the manual
coordinates (``weather_latitude``/``weather_longitude``, source ``manual`` or
``browser``), else Home Assistant's ``zone.home`` (source ``ha_zone_home``). The
coordinates leave the house rounded to 0.01°. Each issue is written to ``history.db``
(table ``forecast``) through the history writer. The forecast is display-only in v1:
it is not a controller input. Its health check ``weather`` is ``disabled``,
``starting`` (enabled, no issue yet), ``ok`` or ``stale`` (newest issue older than
3 h); it never affects readiness.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

from ovenbird.backoff import Backoff
from ovenbird.clock import Clock, Sleep
from ovenbird.history.forecast import ForecastRow, latest_issue
from ovenbird.weather.providers import (
    Forecast,
    HourlySeries,
    OpenMeteoProvider,
    SimulatedProvider,
    WeatherError,
    WeatherProvider,
    rounded,
    synthetic_series,
)
from ovenbird_core import Instant

if TYPE_CHECKING:
    from ovenbird.config import Settings

LOGGER = logging.getLogger("ovenbird.weather")
FETCH_INTERVAL_S: Final = 3600.0
POLL_S: Final = 60.0
STALE_AFTER_S: Final = 3 * 3600.0
RETRY_INITIAL_S: Final = 60.0
RETRY_CAP_S: Final = 3600.0
HA_ZONE_HOME: Final = "ha_zone_home"
STATUSES: Final = ("disabled", "starting", "ok", "stale")


class ForecastSink(Protocol):
    """Where forecast rows go (the history writer)."""

    def offer_forecast(self, rows: list[ForecastRow]) -> None:
        """Queue the rows of one issue."""
        ...


@dataclass(frozen=True, slots=True)
class Location:
    """Where the forecast is for.

    Parameters
    ----------
    latitude, longitude
        Decimal degrees, rounded to 0.01°.
    source
        ``ha_zone_home``, ``manual`` or ``browser``.
    """

    latitude: float
    longitude: float
    source: str

    def to_json(self) -> dict[str, float | str]:
        """Return the API form."""
        return {"latitude": self.latitude, "longitude": self.longitude, "source": self.source}


def build_provider(settings: Settings) -> WeatherProvider:
    """Return the provider for the installation: simulated in simulation mode, else Open-Meteo.

    In simulation mode the series is the simulator's weather cache
    (``OVENBIRD_WEATHER_SIM_FILE``) when it can be read, else a synthetic winter.
    """
    if not settings.simulation:
        return OpenMeteoProvider()
    path = settings.weather_sim_file
    if path is not None:
        try:
            return SimulatedProvider(HourlySeries.load(path))
        except (OSError, ValueError) as exc:
            LOGGER.warning("cannot read the simulated weather %s (%s); synthetic", path, exc)
    start = settings.clock_start.timestamp() if settings.clock_start is not None else 0.0
    return SimulatedProvider(synthetic_series(start))


def forecast_rows(forecast: Forecast) -> list[ForecastRow]:
    """Return the stored rows of one issue."""
    return [
        ForecastRow(
            forecast.issued_ts,
            hour.target_ts,
            hour.temp_c,
            hour.radiation_wm2,
            hour.cloud_pct,
            hour.wind_ms,
        )
        for hour in forecast.hours
    ]


class WeatherService:
    """Fetch, store and report the forecast (see the module docstring).

    Parameters
    ----------
    settings
        Effective settings (updated by :meth:`reconfigure`).
    clock
        Service clock.
    provider
        Forecast provider.
    sink
        Receives the rows of every issue; ``None`` keeps them in memory only.
    home
        Returns Home Assistant's ``zone.home`` coordinates, when known.
    sleep
        Sleeps on the service clock.
    history_path
        ``history.db`` (the newest stored issue after a restart).
    """

    def __init__(
        self,
        settings: Settings,
        clock: Clock,
        provider: WeatherProvider,
        *,
        sink: ForecastSink | None = None,
        home: Callable[[], tuple[float, float] | None] | None = None,
        sleep: Sleep | None = None,
        history_path: Path | None = None,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.provider = provider
        self.sink = sink
        self.home = home
        self._sleep = sleep
        self.history_path = history_path
        self.latest: Forecast | None = None
        self.issued_ts: float | None = None
        self.last_error: str | None = None
        self.fetches = 0
        self._due = 0.0
        self._location: Location | None = None
        self._backoff = Backoff(initial=RETRY_INITIAL_S, cap=RETRY_CAP_S)
        if history_path is not None:
            try:
                self.issued_ts = latest_issue(history_path, clock().wall.timestamp())
            except Exception:
                LOGGER.exception("cannot read the stored forecasts")
            if self.issued_ts is not None:
                self._due = self.issued_ts + FETCH_INTERVAL_S

    def location(self) -> Location | None:
        """Return the forecast location, or ``None`` when none is known."""
        settings = self.settings
        lat, lon = settings.weather_latitude, settings.weather_longitude
        if lat is not None and lon is not None:
            return Location(rounded(lat), rounded(lon), settings.weather_location_source)
        home = self.home() if self.home is not None else None
        if home is None:
            return None
        return Location(rounded(home[0]), rounded(home[1]), HA_ZONE_HOME)

    @property
    def enabled(self) -> bool:
        """Whether forecasts are fetched (opted in and a location known)."""
        return self.settings.weather_enabled and self.location() is not None

    def disabled_reason(self) -> str | None:
        """Why no forecast is fetched, if it is not."""
        if not self.settings.weather_enabled:
            return "weather_enabled is off"
        if self.location() is None:
            return "no location: set one, or connect Home Assistant (zone.home)"
        return None

    def reconfigure(self, settings: Settings) -> None:
        """Follow a new configuration; a changed location is fetched at once."""
        before = self.location() if self.settings.weather_enabled else None
        self.settings = settings
        after = self.location() if settings.weather_enabled else None
        if after != before:
            self._due = 0.0
            self._backoff.reset()

    def age(self, now: Instant | None = None) -> float | None:
        """Seconds since the newest issue, if any."""
        if self.issued_ts is None:
            return None
        moment = now or self.clock()
        return max(0.0, moment.wall.timestamp() - self.issued_ts)

    def status(self, now: Instant | None = None) -> str:
        """Return the ``weather`` health check (``disabled``/``starting``/``ok``/``stale``)."""
        if not self.enabled:
            return "disabled"
        age = self.age(now)
        if age is None:
            return "starting"
        return "ok" if age <= STALE_AFTER_S else "stale"

    async def poll_once(self) -> bool:
        """Fetch when due; returns whether a new issue was stored."""
        if not self.enabled:
            return False
        location = self.location()
        now = self.clock().wall.timestamp()
        if location is None or now < self._due:
            return False
        try:
            forecast = await asyncio.to_thread(
                self.provider.fetch, location.latitude, location.longitude, now
            )
        except WeatherError as exc:
            delay = self._backoff.next_delay()
            self._due = now + delay
            self.last_error = str(exc)
            LOGGER.warning("weather fetch failed (%s); retrying in %.0f s", exc, delay)
            return False
        self._backoff.reset()
        self.latest = forecast
        self.issued_ts = forecast.issued_ts
        self._location = location
        self.last_error = None
        self.fetches += 1
        self._due = now + FETCH_INTERVAL_S
        if self.sink is not None:
            self.sink.offer_forecast(forecast_rows(forecast))
        LOGGER.info(
            "%s forecast stored: %d hours for %.2f, %.2f",
            self.provider.name,
            len(forecast.hours),
            location.latitude,
            location.longitude,
        )
        return True

    async def run(self) -> None:
        """Poll forever on the service clock (the supervisor restarts it after a failure)."""
        if self._sleep is None:
            raise RuntimeError("WeatherService.run needs a sleep function")
        while True:
            await self.poll_once()
            await self._sleep(POLL_S)

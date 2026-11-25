"""Weather forecasts: providers, the hourly fetch component and the API payload."""

from ovenbird.weather.providers import (
    Forecast,
    ForecastHour,
    HourlySeries,
    OpenMeteoProvider,
    SimulatedProvider,
    WeatherError,
    WeatherProvider,
    forecast_url,
    parse_open_meteo,
)
from ovenbird.weather.service import Location, WeatherService, build_provider

__all__ = [
    "Forecast",
    "ForecastHour",
    "HourlySeries",
    "Location",
    "OpenMeteoProvider",
    "SimulatedProvider",
    "WeatherError",
    "WeatherProvider",
    "WeatherService",
    "build_provider",
    "forecast_url",
    "parse_open_meteo",
]

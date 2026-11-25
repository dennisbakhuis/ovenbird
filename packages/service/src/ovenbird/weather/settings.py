"""Weather forecast settings (``weather_*``)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator

from ovenbird.config.fromcore import FeatureSettings
from ovenbird.config.values import LOCATION_DECIMALS, LocationSource


class WeatherSettings(FeatureSettings):
    """Weather forecast (``weather_*``)."""

    weather_enabled: bool = False
    weather_latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    weather_longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    weather_location_source: LocationSource = "ha_zone_home"
    weather_sim_file: Path | None = None

    @field_validator("weather_latitude", "weather_longitude")
    @classmethod
    def _round_location(cls, value: float | None) -> float | None:
        return None if value is None else round(value, LOCATION_DECIMALS)

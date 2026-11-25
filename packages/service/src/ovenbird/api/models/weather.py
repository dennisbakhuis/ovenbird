"""Bodies of the weather router (:mod:`ovenbird.api.weather_api`)."""

from __future__ import annotations

from typing import Literal

from ovenbird.api.models.base import ApiModel, Number

type WeatherPoint = tuple[str, Number | None]
type ForecastPoint = tuple[str, Number | None, Number | None, Number | None, Number | None]


class WeatherLocation(ApiModel):
    """The forecast location (rounded to 0.01°) and where it came from."""

    latitude: Number
    longitude: Number
    source: str


class WeatherOff(ApiModel):
    """``GET weather`` while no forecast is fetched."""

    enabled: Literal[False]
    provider: str
    reason: str | None
    location: WeatherLocation | None


class WeatherNow(ApiModel):
    """The outside temperature now: measured, filtered, forecast, and the curve's water."""

    measured_c: Number | None
    filtered_c: Number | None
    forecast_c: Number | None
    curve_c: Number | None


class SteppedSeries(ApiModel):
    """A series at a fixed step (seconds)."""

    step: int
    points: list[WeatherPoint]


class ForecastSeries(ApiModel):
    """The forecast hours: time, temperature, radiation, cloud cover, wind."""

    step: int
    points: list[ForecastPoint]


class PastForecast(ApiModel):
    """What the forecast said at a fixed lead for the hours that passed."""

    lead_h: int
    points: list[WeatherPoint]


class ForecastError(ApiModel):
    """Bias and mean absolute error of the stored forecasts per lead."""

    lead_h: list[int]
    bias_k: list[Number | None]
    mae_k: list[Number | None]
    n: list[int]


class CurveOutlook(ApiModel):
    """The curve's water temperature on the forecast."""

    points: list[WeatherPoint]


class WeatherOn(ApiModel):
    """``GET weather`` while forecasts are fetched."""

    enabled: Literal[True]
    provider: str
    issued: str | None
    age: Number | None
    stale: bool
    location: WeatherLocation | None
    now: WeatherNow
    measured: SteppedSeries
    filtered: SteppedSeries
    forecast: ForecastSeries
    forecast_past: PastForecast
    error: ForecastError
    curve_outlook: CurveOutlook


type WeatherReport = WeatherOff | WeatherOn

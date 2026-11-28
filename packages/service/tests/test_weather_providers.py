"""Weather provider parsing, series interpolation and the simulated provider (no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ovenbird import history as history
from ovenbird.weather import providers
from ovenbird.weather.providers import (
    ForecastHour,
    HourlySeries,
    OpenMeteoProvider,
    SimulatedProvider,
    WeatherError,
    parse_open_meteo,
    rounded,
    synthetic_series,
)

ISSUED = 1_800_000_000.0


def _body(times: list[object], **columns: list[object]) -> dict[str, object]:
    """Build an Open-Meteo style response with the given hourly times and columns."""
    hourly: dict[str, object] = {"time": times}
    hourly.update(columns)
    return {"hourly": hourly}


def test_rounded_keeps_two_decimals() -> None:
    """Values are rounded to two decimals."""
    assert rounded(52.09123) == 52.09
    assert rounded(5.11789) == 5.12


def test_parse_sorts_hours_and_keeps_missing_values_as_none() -> None:
    """Parsing sorts the hours by time and keeps missing values as None."""
    body = _body([7200, 3600], temperature_2m=[2.0, None])
    forecast = parse_open_meteo(body, ISSUED)
    assert [hour.target_ts for hour in forecast.hours] == [3600.0, 7200.0]
    assert forecast.hours[0].temp_c is None
    assert forecast.hours[1].temp_c == 2.0
    assert forecast.hours[0].wind_ms is None
    assert forecast.issued_ts == ISSUED


def test_parse_skips_hours_without_a_valid_time() -> None:
    """Parsing skips entries whose time is missing, not a number or a boolean."""
    forecast = parse_open_meteo(_body([3600, None, "x", True]), ISSUED)
    assert [hour.target_ts for hour in forecast.hours] == [3600.0]


def test_parse_converts_wind_from_kmh() -> None:
    """Wind speed in km/h is converted to m/s."""
    body = _body([3600], wind_speed_10m=[36.0])
    body["hourly_units"] = {"wind_speed_10m": "km/h"}
    assert parse_open_meteo(body, ISSUED).hours[0].wind_ms == pytest.approx(10.0)


def test_parse_keeps_wind_in_ms() -> None:
    """Wind speed already in m/s is kept as is."""
    body = _body([3600], wind_speed_10m=[4.25])
    body["hourly_units"] = {"wind_speed_10m": "m/s"}
    assert parse_open_meteo(body, ISSUED).hours[0].wind_ms == 4.25


@pytest.mark.parametrize(
    "body",
    [
        {"error": True, "reason": "bad request"},
        {},
        {"hourly": []},
        {"hourly": {"time": "x"}},
        _body([]),
        _body(["x"]),
        _body([3600, 7200], temperature_2m=[1.0]),
    ],
)
def test_parse_rejects_unusable_bodies(body: dict[str, object]) -> None:
    """Error, empty, malformed or misaligned responses raise a weather error."""
    with pytest.raises(WeatherError):
        parse_open_meteo(body, ISSUED)


def test_error_reason_is_cut_to_200_characters() -> None:
    """A long error reason is truncated in the exception message."""
    with pytest.raises(WeatherError) as info:
        parse_open_meteo({"error": True, "reason": "x" * 500}, ISSUED)
    assert len(str(info.value)) < 260


def test_provider_wraps_bad_json_and_non_objects() -> None:
    """The provider turns invalid JSON and non-object bodies into weather errors."""
    with pytest.raises(WeatherError, match="request failed"):
        OpenMeteoProvider(lambda _: b"{not json").fetch(52.0, 5.0, ISSUED)
    with pytest.raises(WeatherError, match="not a JSON object"):
        OpenMeteoProvider(lambda _: b"[1, 2]").fetch(52.0, 5.0, ISSUED)


def test_default_opener_refuses_plain_http() -> None:
    """The default opener refuses URLs that are not HTTPS."""
    with pytest.raises(WeatherError, match="https"):
        providers._urlopen("http://example.invalid/forecast")


def _series() -> HourlySeries:
    """Return a three-hour series with a missing last temperature and no radiation."""
    return HourlySeries(
        times=(0.0, 3600.0, 7200.0),
        temp_c=(0.0, 10.0, None),
        radiation_wm2=(None, None, None),
        cloud_pct=(10.0, 20.0, 30.0),
        wind_ms=(1.0, 1.0, 1.0),
    )


def test_series_interpolates_linearly_and_holds_the_ends() -> None:
    """The series interpolates linearly, holds its end values and yields None where unknown."""
    series = _series()
    assert series.at(1800.0).temp_c == pytest.approx(5.0)
    assert series.at(-100.0).temp_c == 0.0
    assert series.at(99_999.0).temp_c is None
    assert series.at(1800.0).cloud_pct == pytest.approx(15.0)


def test_series_uses_the_known_neighbour_when_one_side_is_missing() -> None:
    """A missing neighbour makes the series use the known value, and None when neither is known."""
    assert _series().at(5400.0).temp_c == 10.0
    assert _series().at(1800.0).radiation_wm2 is None


def test_series_rejects_empty_and_misaligned_columns() -> None:
    """A series needs at least one hour and aligned columns."""
    with pytest.raises(ValueError, match="at least one"):
        HourlySeries((), (), (), (), ())
    with pytest.raises(ValueError, match="align"):
        HourlySeries((0.0, 1.0), (1.0,), (1.0, 1.0), (1.0, 1.0), (1.0, 1.0))


def test_series_loads_a_cache_file_and_converts_kmh(tmp_path: Path) -> None:
    """A cached response loads sorted and with wind converted from km/h to m/s."""
    path = tmp_path / "open_meteo_hourly.json"
    body = _body(
        [7200, 3600],
        temperature_2m=[2.0, 1.0],
        shortwave_radiation=[0, 50],
        cloud_cover=[80, 90],
        wind_speed_10m=[36.0, 18.0],
    )
    path.write_text(json.dumps(body), encoding="utf-8")
    series = HourlySeries.load(path)
    assert series.times == (3600.0, 7200.0)
    assert series.temp_c == (1.0, 2.0)
    assert series.wind_ms == pytest.approx((5.0, 10.0))


@pytest.mark.parametrize("text", ["[]", '{"hourly": {}}', '{"hourly": {"time": []}}'])
def test_series_load_rejects_other_files(tmp_path: Path, text: str) -> None:
    """Cache files that are not a usable hourly response are rejected."""
    path = tmp_path / "bad.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=r"bad\.json"):
        HourlySeries.load(path)


def test_synthetic_series_is_hourly_and_plausible() -> None:
    """The synthetic series is hourly, starts before issue time and has plausible values."""
    series = synthetic_series(ISSUED, days=3)
    assert len(series.times) == 72
    assert {b - a for a, b in zip(series.times, series.times[1:], strict=False)} == {3600.0}
    assert series.times[0] < ISSUED
    temps = [t for t in series.temp_c if t is not None]
    assert -10.0 < min(temps) < max(temps) < 15.0
    assert all(r is not None and r >= 0.0 for r in series.radiation_wm2)


def test_simulated_provider_is_deterministic_per_seed_and_exact_in_the_past() -> None:
    """The simulated provider is deterministic per seed and exact for past hours."""
    series = synthetic_series(ISSUED, days=40)
    first = SimulatedProvider(series, seed=3).fetch(52.0, 5.0, ISSUED)
    again = SimulatedProvider(series, seed=3).fetch(52.0, 5.0, ISSUED)
    other = SimulatedProvider(series, seed=4).fetch(52.0, 5.0, ISSUED)
    assert first == again
    assert first != other
    assert isinstance(first.hours[0], ForecastHour)
    past = [hour for hour in first.hours if hour.target_ts <= ISSUED]
    assert past
    for hour in past:
        true = series.at(hour.target_ts).temp_c
        assert true is not None
        assert hour.temp_c == round(true, 1)

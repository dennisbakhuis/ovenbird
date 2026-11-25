"""Weather: Open-Meteo parsing from a recorded response, as-issued storage, statistics, status.

No test touches the network: the Open-Meteo provider gets a fake opener that serves
the recorded response in ``tests/fixtures/weather``.
"""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Callable
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from ovenbird.clock import ScaledClock
from ovenbird.config import Settings
from ovenbird.history.database import HistoryDatabase, Sample, SampleKind
from ovenbird.history.forecast import at_lead, issue_rows, latest_issue, write_forecast
from ovenbird.history.schema import open_history
from ovenbird.testing import FakeClock, synthetic_open_meteo_text
from ovenbird.weather import (
    Forecast,
    ForecastHour,
    HourlySeries,
    OpenMeteoProvider,
    SimulatedProvider,
    WeatherError,
    WeatherService,
    build_provider,
    forecast_url,
    parse_open_meteo,
)
from ovenbird.weather.report import error_statistics, weather_payload
from ovenbird.weather.service import forecast_rows
from ovenbird_core.control import OvenbirdConfig

FIXTURE = Path(__file__).parent / "fixtures" / "weather" / "open_meteo_forecast.json"
ISSUED = datetime(2026, 11, 10, 0, 30, tzinfo=UTC).timestamp()
HOUR = 3600.0


def fixture_body() -> bytes:
    return FIXTURE.read_bytes()


class Sink:
    def __init__(self, path: Path | None = None) -> None:
        self.rows: list[Any] = []
        self.path = path

    def offer_forecast(self, rows: list[Any]) -> None:
        self.rows.extend(rows)
        if self.path is not None:
            conn = open_history(self.path)
            try:
                write_forecast(conn, rows)
            finally:
                conn.close()


def run(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


def test_the_request_is_rounded_keyless_and_complete() -> None:
    url = forecast_url(52.09123, 5.11789)
    parts = urlsplit(url)
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert parts.scheme == "https"
    assert parts.netloc == "api.open-meteo.com"
    assert parts.path == "/v1/forecast"
    assert query == {
        "latitude": "52.09",
        "longitude": "5.12",
        "hourly": "temperature_2m,shortwave_radiation,cloud_cover,wind_speed_10m",
        "past_days": "1",
        "forecast_days": "3",
        "timezone": "UTC",
        "timeformat": "unixtime",
        "wind_speed_unit": "ms",
    }
    assert "key" not in url


def test_the_fixture_is_the_synthetic_forecast() -> None:
    assert FIXTURE.read_text(encoding="utf-8") == synthetic_open_meteo_text()


def test_the_fixture_response_parses() -> None:
    forecast = parse_open_meteo(json.loads(fixture_body()), ISSUED)
    assert forecast.issued_ts == ISSUED
    assert len(forecast.hours) == 96
    first = forecast.hours[0]
    assert first.target_ts == datetime(2026, 11, 9, tzinfo=UTC).timestamp()
    assert first.temp_c == 3.7
    assert first.wind_ms == 4.68
    assert all(h.cloud_pct is None or 0 <= h.cloud_pct <= 100 for h in forecast.hours)
    times = [h.target_ts for h in forecast.hours]
    assert times == sorted(times)
    assert all(b - a == HOUR for a, b in pairwise(times))


def test_the_provider_uses_only_its_opener() -> None:
    urls: list[str] = []

    def opener(url: str) -> bytes:
        urls.append(url)
        return fixture_body()

    forecast = OpenMeteoProvider(opener).fetch(52.0912, 5.1178, ISSUED)
    assert len(forecast.hours) == 96
    assert urls == [forecast_url(52.09, 5.12)]


@pytest.mark.parametrize(
    "body",
    [b"not json", b"[]", b'{"error": true, "reason": "bad coordinates"}', b'{"hourly": {}}'],
)
def test_bad_responses_raise(body: bytes) -> None:
    with pytest.raises(WeatherError):
        OpenMeteoProvider(lambda _: body).fetch(52.0, 5.0, ISSUED)


def test_network_errors_raise_weather_errors() -> None:
    def broken(_: str) -> bytes:
        raise OSError("unreachable")

    with pytest.raises(WeatherError, match="OSError"):
        OpenMeteoProvider(broken).fetch(52.0, 5.0, ISSUED)


def test_mismatched_columns_raise() -> None:
    body = json.loads(fixture_body())
    body["hourly"]["temperature_2m"] = body["hourly"]["temperature_2m"][:-1]
    with pytest.raises(WeatherError, match="temperature_2m"):
        parse_open_meteo(body, ISSUED)


def test_km_per_hour_wind_is_converted() -> None:
    body = json.loads(fixture_body())
    body["hourly_units"]["wind_speed_10m"] = "km/h"
    body["hourly"]["wind_speed_10m"] = [3.6] * 96
    forecast = parse_open_meteo(body, ISSUED)
    assert {h.wind_ms for h in forecast.hours} == {1.0}


@pytest.fixture
def weather_settings(make_settings: Callable[..., Settings]) -> Callable[..., Settings]:
    def factory(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "weather_enabled": True,
            "weather_latitude": 52.0912,
            "weather_longitude": 5.1178,
            "weather_location_source": "manual",
        }
        values.update(overrides)
        return make_settings(**values)

    return factory


def service(
    settings: Settings,
    clock: Callable[..., Any],
    *,
    opener: Callable[[str], bytes] = lambda _: fixture_body(),
    home: tuple[float, float] | None = None,
    sink: Sink | None = None,
) -> WeatherService:
    return WeatherService(
        settings,
        clock,
        OpenMeteoProvider(opener),
        sink=sink,
        home=lambda: home,
        history_path=settings.history_path,
    )


def test_off_by_default_and_without_a_location(make_settings: Callable[..., Settings]) -> None:
    clock = FakeClock(ISSUED)
    off = service(make_settings(), clock)
    assert off.status() == "disabled"
    assert off.disabled_reason() == "weather_enabled is off"
    assert run(off.poll_once()) is False
    nowhere = service(make_settings(weather_enabled=True), clock)
    assert nowhere.status() == "disabled"
    assert "no location" in str(nowhere.disabled_reason())


def test_the_location_comes_from_zone_home_rounded(
    make_settings: Callable[..., Settings],
) -> None:
    clock = FakeClock(ISSUED)
    weather = service(make_settings(weather_enabled=True), clock, home=(52.091234, 5.117891))
    location = weather.location()
    assert location is not None
    assert location.to_json() == {"latitude": 52.09, "longitude": 5.12, "source": "ha_zone_home"}


def test_a_manual_location_overrides_zone_home(
    weather_settings: Callable[..., Settings],
) -> None:
    settings = weather_settings(weather_location_source="browser")
    assert (settings.weather_latitude, settings.weather_longitude) == (52.09, 5.12)
    weather = service(settings, FakeClock(ISSUED), home=(40.0, 3.0))
    location = weather.location()
    assert location is not None
    assert location.to_json() == {"latitude": 52.09, "longitude": 5.12, "source": "browser"}


def test_issues_are_stored_as_issued_and_fetched_hourly(
    weather_settings: Callable[..., Settings],
) -> None:
    settings = weather_settings()
    clock = FakeClock(ISSUED)
    sink = Sink(settings.history_path)
    urls: list[str] = []

    def opener(url: str) -> bytes:
        urls.append(url)
        return fixture_body()

    weather = service(settings, clock, opener=opener, sink=sink)
    assert weather.status() == "starting"
    assert run(weather.poll_once()) is True
    assert run(weather.poll_once()) is False
    clock.advance(HOUR)
    assert run(weather.poll_once()) is True
    assert len(urls) == 2
    assert len(sink.rows) == 192
    path = settings.history_path
    assert latest_issue(path) == ISSUED + HOUR
    assert len(issue_rows(path, ISSUED)) == 96
    assert len(issue_rows(path, ISSUED + HOUR)) == 96
    assert weather.status() == "ok"
    restarted = service(settings, clock)
    assert restarted.issued_ts == ISSUED + HOUR
    assert restarted.status() == "ok"


def test_stale_after_three_hours_and_backoff_on_failure(
    weather_settings: Callable[..., Settings],
) -> None:
    clock = FakeClock(ISSUED)
    healthy = [True]

    def opener(_: str) -> bytes:
        if healthy[0]:
            return fixture_body()
        raise OSError("down")

    weather = service(weather_settings(), clock, opener=opener)
    assert run(weather.poll_once())
    healthy[0] = False
    clock.advance(HOUR)
    assert run(weather.poll_once()) is False
    assert weather.last_error is not None
    clock.advance(30.0)
    assert run(weather.poll_once()) is False
    assert weather.status() == "ok"
    clock.advance(2 * HOUR)
    assert weather.status() == "stale"
    healthy[0] = True
    assert run(weather.poll_once()) is True
    assert weather.status() == "ok"


def test_a_changed_location_is_fetched_at_once(
    weather_settings: Callable[..., Settings],
) -> None:
    clock = FakeClock(ISSUED)
    urls: list[str] = []

    def opener(url: str) -> bytes:
        urls.append(url)
        return fixture_body()

    weather = service(weather_settings(), clock, opener=opener)
    run(weather.poll_once())
    weather.reconfigure(weather_settings(weather_latitude=51.5, weather_longitude=4.4))
    assert run(weather.poll_once()) is True
    assert "latitude=51.50" in urls[-1]
    weather.reconfigure(weather_settings(weather_enabled=False))
    assert weather.status() == "disabled"


def _store_outside(path: Path, start: float, hours: int, value: Callable[[float], float]) -> None:
    db = HistoryDatabase(open_history(path))
    try:
        samples = [
            Sample(
                "main/Outside_Temp",
                "°C",
                SampleKind.NUMBER,
                start + i * 60.0,
                value(start + i * 60.0),
                600.0,
            )
            for i in range(hours * 60)
        ]
        db.write_batch(samples)
    finally:
        db.close()


def _store_issue(
    path: Path, issued: float, hours: int, temp: Callable[[float, float], float]
) -> None:
    rows = forecast_rows(
        Forecast(
            issued,
            tuple(
                ForecastHour(t, temp(issued, t), 0.0, 50.0, 2.0)
                for t in (math.floor(issued / HOUR) * HOUR + k * HOUR for k in range(hours))
            ),
        )
    )
    conn = open_history(path)
    try:
        write_forecast(conn, rows)
    finally:
        conn.close()


def test_lead_time_error_statistics(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    start = datetime(2026, 11, 1, tzinfo=UTC).timestamp()
    _store_outside(path, start - HOUR, 4 * 24 + 2, lambda _: 5.0)
    for k in range(4 * 24):
        _store_issue(path, start + k * HOUR, 30, lambda issued, t: 5.0 + (t - issued) / HOUR / 12)
    now = start + 4 * 24 * HOUR
    stats = error_statistics(path, now)
    assert stats["lead_h"] == [6, 24]
    assert stats["n"][0] > 50
    assert stats["n"][1] > 30
    assert stats["bias_k"][0] == pytest.approx(0.5, abs=0.01)
    assert stats["mae_k"][1] == pytest.approx(2.0, abs=0.01)
    leads = at_lead(path, 24, start + 30 * HOUR, now)
    assert set(leads.values()) == {7.0}


def test_the_payload_has_every_part(weather_settings: Callable[..., Settings]) -> None:
    settings = weather_settings()
    path = settings.history_path
    path.parent.mkdir(parents=True, exist_ok=True)
    now_ts = ISSUED + 30 * 60
    _store_outside(path, now_ts - 26 * HOUR, 26, lambda t: float(round(3 + math.sin(t / 7200))))
    for k in range(26):
        _store_issue(path, now_ts - (26 - k) * HOUR, 72, lambda issued, t: 3.5)
    clock = FakeClock(now_ts)
    weather = service(settings, clock)
    config = OvenbirdConfig.preset("mixed")
    body = weather_payload(
        weather,
        path,
        config,
        now=clock(),
        back_h=24,
        ahead_h=48,
        filtered_now=2.4,
        measured_now=3.0,
    )
    assert body["enabled"] is True
    assert body["provider"] == "open-meteo"
    assert body["stale"] is False
    assert body["location"] == {"latitude": 52.09, "longitude": 5.12, "source": "manual"}
    assert body["now"]["curve_c"] == round(config.curve.water(2.4), 1)
    assert body["now"]["forecast_c"] == 3.5
    assert body["measured"]["step"] == 900
    assert len(body["measured"]["points"]) >= 90
    assert body["forecast"]["step"] == 3600
    assert 44 <= len(body["forecast"]["points"]) <= 50
    assert len(body["forecast"]["points"][0]) == 5
    assert body["forecast_past"]["lead_h"] == 24
    assert body["error"]["lead_h"] == [6, 24]
    outlook = body["curve_outlook"]["points"]
    assert outlook
    assert outlook[-1][1] == pytest.approx(config.curve.water(3.5), abs=0.15)


def test_the_disabled_payload(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    weather = service(settings, FakeClock(ISSUED))
    body = weather_payload(
        weather,
        settings.history_path,
        OvenbirdConfig.preset("mixed"),
        now=FakeClock(ISSUED)(),
        back_h=24,
        ahead_h=48,
        filtered_now=None,
    )
    assert body == {
        "enabled": False,
        "provider": "open-meteo",
        "reason": "weather_enabled is off",
        "location": None,
    }


def test_the_simulated_provider_follows_the_scaled_clock(
    make_settings: Callable[..., Settings],
) -> None:
    start = datetime(2026, 11, 7, tzinfo=UTC)
    real = [1000.0]
    clock = ScaledClock(60.0, start, monotonic=lambda: real[0])
    series = HourlySeries.load(FIXTURE)
    provider = SimulatedProvider(series)
    settings = make_settings(
        weather_enabled=True,
        weather_latitude=52.1,
        weather_longitude=5.1,
        weather_location_source="manual",
    )
    weather = WeatherService(settings, clock, provider)
    assert run(weather.poll_once()) is True
    first = weather.latest
    assert first is not None
    assert first.issued_ts == start.timestamp()
    assert len(first.hours) == 96
    assert first.hours[0].target_ts == start.timestamp() - 86_400.0
    real[0] += 60.0
    assert run(weather.poll_once()) is True
    second = weather.latest
    assert second is not None
    assert second.issued_ts == start.timestamp() + HOUR
    again = provider.fetch(0.0, 0.0, first.issued_ts)
    assert again == first
    past = [h for h in first.hours if h.target_ts <= first.issued_ts]
    assert all(h.temp_c == round(series.at(h.target_ts).temp_c or 0.0, 1) for h in past)


def test_simulation_mode_uses_the_simulated_provider(
    make_settings: Callable[..., Settings], tmp_path: Path
) -> None:
    sim = make_settings(simulation=True, mqtt_host="mosquitto", weather_sim_file=FIXTURE)
    assert build_provider(sim).name == "simulated"
    missing = make_settings(simulation=True, mqtt_host="mosquitto", weather_sim_file=tmp_path / "x")
    assert build_provider(missing).name == "simulated"
    assert build_provider(make_settings()).name == "open-meteo"

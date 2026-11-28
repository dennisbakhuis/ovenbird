r"""Service responses for the UI tests, from a simulated run (no recorded data).

The UI's vitest suites check their mocks and views against real service responses.
This module produces those responses from the service's own code on a simulated
house: harness full runs on the example house and the synthetic cold week (the
golden ``fullrun`` set-up), and a forecast of that cold week. It writes

``ui/mock/fixtures/decisions-sim.json``
    ``GET api/v1/decisions`` (limit 50) ending at a room-feedback decision, with the
    room temperature on the MQTT input ``room_temperature``.
``ui/mock/fixtures/real/decisions.json``
    ``GET api/v1/decisions`` (limit 200) over the run's last quarter of an hour, with
    the room sensor through Home Assistant (send-on-delta, humidity as liveness).
``ui/mock/fixtures/real/weather-on.json``
    ``GET api/v1/weather`` with the forecast on, after a day of hourly issues.

Examples
--------
Regenerate (then format with prettier, as ``make ui-sim-fixtures`` does)::

    uv run python -m ovenbird_harness.uifixtures
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from ovenbird.clock import iso_z
from ovenbird.config import load_settings
from ovenbird.history.forecast import write_forecast
from ovenbird.history.journal import DecisionRow, query_decisions
from ovenbird.history.schema import open_history
from ovenbird.weather.providers import Forecast, ForecastHour, OpenMeteoProvider
from ovenbird.weather.report import weather_payload
from ovenbird.weather.service import WeatherService, forecast_rows
from ovenbird_core import Instant
from ovenbird_core.control import OvenbirdConfig
from ovenbird_harness.fullrun import FullRun
from ovenbird_harness.settings import Profile
from ovenbird_harness.testing import REFERENCE_START, reference_config
from ovenbird_sim.heishamon.weather import ColdWeek, local_hour

FIXTURES: Final = Path("ui/mock/fixtures")
SIM_DECISIONS: Final = "decisions-sim.json"
REAL_DECISIONS: Final = "real/decisions.json"
REAL_WEATHER: Final = "real/weather-on.json"
RUN_HOURS: Final = 30.0
WINDOW: Final = timedelta(hours=24)
REAL_WINDOW: Final = timedelta(minutes=15)
SIM_LIMIT: Final = 50
REAL_LIMIT: Final = 200
QUIET_TERMS: Final = ("plan", "start_ramp", "cycling_floor")
HOUR: Final = 3600.0
FORECAST_ERROR_K: Final = 0.4
ISSUES: Final = 26
LATITUDE: Final = 52.09
LONGITUDE: Final = 5.12
UTC_OFFSET_H: Final = 1.0
OUTSIDE_SIGNAL: Final = "main/Outside_Temp"


def run_history(work: Path, profile: Profile) -> Path:
    """Run the reference full run for :data:`RUN_HOURS` and return its ``history.db``."""
    run = FullRun(reference_config(work, RUN_HOURS, profile=profile))
    run.run()
    path: Path = run.settings.history_path
    return path


def term(record: dict[str, Any], name: str) -> float:
    """Return the value of the term ``name`` (0 when absent)."""
    for item in record.get("terms", []):
        if item["name"] == name:
            return float(item["value"])
    return 0.0


def plain_feedback(payload: dict[str, Any]) -> bool:
    """Whether a decision is a room-feedback one with only curve and feedback active."""
    record = payload["record"]
    return (
        payload["reason"] == "room_feedback"
        and record["binding"] is None
        and all(term(record, name) == 0.0 for name in QUIET_TERMS)
        and term(record, "room_feedback") != 0.0
    )


def with_terms(payload: dict[str, Any]) -> bool:
    """Whether a decision carries a computed pipeline (no hold or refusal)."""
    record = payload["record"]
    return bool(record["terms"]) and record["pre_round"] is not None


def page(history: Path, end: datetime, limit: int, window: timedelta = WINDOW) -> dict[str, Any]:
    """Return the ``GET api/v1/decisions`` body for ``window`` before ``end``.

    Parameters
    ----------
    history
        Path of the run's ``history.db``.
    end
        End of the page.
    limit
        Maximum number of decisions.
    window
        Length of the period before ``end``.

    Returns
    -------
    dict[str, Any]
        The body: ``from``, ``to``, ``limit`` and the decisions, at most ``limit``.
    """
    since = end - window
    rows: list[DecisionRow] = query_decisions(history, since.timestamp(), end.timestamp(), limit)
    return {
        "from": iso_z(since),
        "to": iso_z(end),
        "limit": limit,
        "decisions": [row.payload() for row in rows],
    }


def sim_decisions(history: Path) -> dict[str, Any]:
    """Return the newest page whose first decision is a plain room-feedback one.

    Every decision on the page has a computed pipeline.

    Raises
    ------
    RuntimeError
        When the run has no such page.
    """
    rows = query_decisions(history, 0.0, math.inf, 1_000_000)
    for row in sorted(rows, key=lambda r: r.ts, reverse=True):
        end = datetime.fromtimestamp(row.ts, UTC) + timedelta(seconds=1)
        body = page(history, end, SIM_LIMIT)
        decisions = body["decisions"]
        if (
            len(decisions) == SIM_LIMIT
            and plain_feedback(decisions[0])
            and all(with_terms(d) for d in decisions)
        ):
            return body
    raise RuntimeError("no page starting with a plain room-feedback decision")


def real_decisions(history: Path) -> dict[str, Any]:
    """Return the run's last :data:`REAL_WINDOW` (at most :data:`REAL_LIMIT` decisions)."""
    end = REFERENCE_START + timedelta(hours=RUN_HOURS)
    return page(history, end, REAL_LIMIT, REAL_WINDOW)


def cold_week_hours(issued: float, first: float, hours: int, error_k: float) -> Forecast:
    """Return a forecast issue of the cold week, off by ``error_k`` (0 for the past).

    Parameters
    ----------
    issued
        Issue time (unix s).
    first
        Target time of the first hour (unix s).
    hours
        Number of hourly targets.
    error_k
        Forecast error in K after 24 h of lead, growing linearly to twice that.

    Returns
    -------
    Forecast
        The issue with outside temperature and solar radiation per target hour.
    """
    weather = ColdWeek(REFERENCE_START)
    values: list[ForecastHour] = []
    for k in range(hours):
        target = first + k * HOUR
        exogenous = weather.at(target, local_hour(target, UTC_OFFSET_H))
        lead = max(0.0, (target - issued) / HOUR)
        offset = error_k * min(lead / 24.0, 2.0)
        values.append(
            ForecastHour(
                target,
                round(exogenous.outside_c + offset, 1),
                round(exogenous.solar_w_m2),
                50.0,
                2.0,
            )
        )
    return Forecast(issued, tuple(values))


def open_meteo_body(forecast: Forecast) -> bytes:
    """Return ``forecast`` as an Open-Meteo hourly response."""
    hours = forecast.hours
    body = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "utc_offset_seconds": 0,
        "timezone": "GMT",
        "hourly_units": {
            "time": "unixtime",
            "temperature_2m": "°C",
            "shortwave_radiation": "W/m²",
            "cloud_cover": "%",
            "wind_speed_10m": "m/s",
        },
        "hourly": {
            "time": [int(h.target_ts) for h in hours],
            "temperature_2m": [h.temp_c for h in hours],
            "shortwave_radiation": [h.radiation_wm2 for h in hours],
            "cloud_cover": [h.cloud_pct for h in hours],
            "wind_speed_10m": [h.wind_ms for h in hours],
        },
    }
    return json.dumps(body).encode()


def weather_on(history: Path, work: Path) -> dict[str, Any]:
    """Return ``GET api/v1/weather`` at the end of the run after a day of hourly issues.

    Parameters
    ----------
    history
        Path of the run's ``history.db``; the forecast issues are written into it.
    work
        Scratch directory for the weather service's data and UI directories.

    Returns
    -------
    dict[str, Any]
        The weather payload, with a day back and two days ahead.
    """
    now_ts = (REFERENCE_START + timedelta(hours=RUN_HOURS)).timestamp()
    issued_now = math.floor(now_ts / HOUR) * HOUR
    conn = open_history(history)
    try:
        for k in range(ISSUES, 0, -1):
            issued = issued_now - k * HOUR
            past = math.floor(issued / 86_400.0) * 86_400.0 - 86_400.0
            write_forecast(conn, forecast_rows(cold_week_hours(issued, past, 96, FORECAST_ERROR_K)))
    finally:
        conn.close()
    current = cold_week_hours(
        issued_now, math.floor(issued_now / 86_400.0) * 86_400.0 - 86_400.0, 96, FORECAST_ERROR_K
    )
    settings = load_settings(
        data_dir=work / "weather",
        ui_dir=work / "ui",
        http_port=0,
        weather_enabled=True,
        weather_latitude=LATITUDE,
        weather_longitude=LONGITUDE,
        weather_location_source="manual",
    )
    clock_now = Instant(now_ts, datetime.fromtimestamp(now_ts, UTC))
    service = WeatherService(
        settings,
        lambda: clock_now,
        OpenMeteoProvider(lambda _: open_meteo_body(current)),
        history_path=history,
    )
    service.latest = current
    service.issued_ts = issued_now
    config = OvenbirdConfig.preset("mixed")
    (latest,) = query_decisions(history, now_ts - HOUR, now_ts, 1)
    record = json.loads(latest.record)
    outside = next(i for i in record["inputs_used"] if i["signal"] == OUTSIDE_SIGNAL)
    return weather_payload(
        service,
        history,
        config,
        now=clock_now,
        back_h=24,
        ahead_h=48,
        filtered_now=record["controller_state"].get("outside_filtered_c"),
        measured_now=outside["value"],
    )


def dump(value: Any) -> str:
    """Return ``value`` as indented JSON text (prettier reflows it)."""
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def write(fixtures: Path) -> list[Path]:
    """Write the three fixtures under ``fixtures``; return their paths."""
    with tempfile.TemporaryDirectory(prefix="uifixtures-") as scratch:
        work = Path(scratch)
        mqtt = run_history(work / "mqtt", Profile(room_via="mqtt"))
        ha = run_history(work / "ha", Profile())
        bodies = {
            SIM_DECISIONS: sim_decisions(mqtt),
            REAL_DECISIONS: real_decisions(ha),
            REAL_WEATHER: weather_on(ha, work),
        }
    written: list[Path] = []
    for name, body in bodies.items():
        path = fixtures / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump(body), encoding="utf-8")
        written.append(path)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    """Write the UI fixtures."""
    parser = argparse.ArgumentParser(prog="python -m ovenbird_harness.uifixtures")
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    args = parser.parse_args(argv)
    logging.basicConfig(level="CRITICAL")
    for path in write(args.fixtures):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

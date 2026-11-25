from __future__ import annotations

import itertools
import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from ovenbird.api.app import create_app
from ovenbird.clock import ScaledClock
from ovenbird.config import Settings
from ovenbird.history import HistoryDatabase, Sample, SampleKind, open_history
from ovenbird.insight.daily import BAND_BELOW_K, daily_payload, local_days
from ovenbird.runtime import Runtime
from ovenbird.testing import FakeClock

AMSTERDAM = "Europe/Amsterdam"
ROOM = "room_temperature"
COMFORT_C = 21.0
ELECTRIC = "main/Heat_Power_Consumption"
HEAT = "main/Heat_Power_Production"
COMPRESSOR = "main/Compressor_Freq"
DEFROST = "main/Defrosting_State"
VALVE = "main/ThreeWay_Valve_State"
OUTSIDE = "main/Outside_Temp"
SETPOINT = "main/Z1_Water_Target_Temp"
TICK = 60.0
HOLD = 330.0
DAY_KEYS = {
    "date",
    "from",
    "to",
    "hours",
    "partial",
    "coverage",
    "electric_kwh",
    "heat_kwh",
    "cop",
    "dhw_electric_kwh",
    "dhw_heat_kwh",
    "compressor_starts",
    "run_s",
    "defrosts",
    "defrost_s",
    "dhw_runs",
    "dhw_s",
    "outside_mean_c",
    "outside_min_c",
    "room_mean_c",
    "room_min_c",
    "comfort_c",
    "below_comfort_kh",
    "setpoint_mean_c",
    "setpoint_changes",
    "writes",
}


def utc(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def local(zone: str, year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(zone))


def plant(ts: float) -> dict[str, tuple[float, SampleKind]]:
    moment = datetime.fromtimestamp(ts, UTC)
    minute = moment.minute
    running = minute < 50
    defrost = running and moment.hour % 6 == 1 and 10 <= minute < 15
    dhw = moment.hour == 4 and minute >= 30
    return {
        ELECTRIC: (1000.0 if running else 0.0, SampleKind.NUMBER),
        HEAT: (4000.0 if running else 0.0, SampleKind.NUMBER),
        COMPRESSOR: (30.0 if running else 0.0, SampleKind.NUMBER),
        DEFROST: (1.0 if defrost else 0.0, SampleKind.ENUM),
        VALVE: (1.0 if dhw else 0.0, SampleKind.ENUM),
        OUTSIDE: (3.0 if moment.hour < 12 else -1.0, SampleKind.NUMBER),
        ROOM: (20.2, SampleKind.NUMBER),
        SETPOINT: (30.0 + (moment.hour >= 12), SampleKind.NUMBER),
    }


def write_history(
    path: Path,
    start: datetime,
    end: datetime,
    values: Callable[[float], dict[str, tuple[float, SampleKind]]],
) -> None:
    database = HistoryDatabase(open_history(path))
    try:
        batch: list[Sample] = []
        ts = start.timestamp()
        while ts <= end.timestamp():
            for signal, (value, kind) in values(ts).items():
                batch.append(Sample(signal, None, kind, ts, value, HOLD))
            if len(batch) > 20_000:
                database.write_batch(batch)
                batch = []
            ts += TICK
        database.write_batch(batch)
    finally:
        database.close()


def constant_power(watts: float) -> Callable[[float], dict[str, tuple[float, SampleKind]]]:
    def values(_ts: float) -> dict[str, tuple[float, SampleKind]]:
        return {
            ELECTRIC: (watts, SampleKind.NUMBER),
            HEAT: (4 * watts, SampleKind.NUMBER),
        }

    return values


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "history.db"


def test_local_days_follow_the_autumn_dst_switch() -> None:
    days = local_days(local(AMSTERDAM, 2026, 10, 26, 12), 3, AMSTERDAM)
    assert [day.date.isoformat() for day in days] == ["2026-10-24", "2026-10-25", "2026-10-26"]
    assert [day.hours for day in days] == [24.0, 25.0, 24.0]
    assert days[1].start == utc(2026, 10, 24, 22).timestamp()
    assert days[1].end == utc(2026, 10, 25, 23).timestamp()
    assert all(a.end == b.start for a, b in itertools.pairwise(days))


def test_local_days_follow_the_spring_dst_switch() -> None:
    days = local_days(local(AMSTERDAM, 2026, 3, 29, 23, 59), 2, AMSTERDAM)
    assert [day.hours for day in days] == [24.0, 23.0]
    assert days[1].start == utc(2026, 3, 28, 23).timestamp()
    assert days[1].end == utc(2026, 3, 29, 22).timestamp()


def test_local_days_use_the_local_date_not_the_utc_date() -> None:
    days = local_days(utc(2026, 1, 14, 23, 30), 1, AMSTERDAM)
    assert days[0].date.isoformat() == "2026-01-15"
    assert local_days(utc(2026, 1, 14, 23, 30), 1, "UTC")[0].date.isoformat() == "2026-01-14"


def test_energy_is_split_at_local_midnight_across_the_dst_switch(db_path: Path) -> None:
    now = local(AMSTERDAM, 2026, 10, 27, 0, 30)
    write_history(db_path, utc(2026, 10, 23, 20), now, constant_power(1000.0))
    body = daily_payload(db_path, now=now, days=4, timezone=AMSTERDAM)
    days = body["days"]
    assert [day["date"] for day in days] == ["2026-10-24", "2026-10-25", "2026-10-26", "2026-10-27"]
    assert [day["hours"] for day in days] == [24.0, 25.0, 24.0, 24.0]
    assert [day["electric_kwh"] for day in days[:3]] == [24.0, 25.0, 24.0]
    assert [day["heat_kwh"] for day in days[:3]] == [96.0, 100.0, 96.0]
    assert [day["cop"] for day in days[:3]] == [4.0, 4.0, 4.0]
    assert [day["coverage"] for day in days] == [1.0, 1.0, 1.0, 1.0]
    assert [day["partial"] for day in days] == [False, False, False, True]
    assert days[3]["electric_kwh"] == 0.5
    assert days[1]["from"] == "2026-10-24T22:00:00Z"
    assert days[1]["to"] == "2026-10-25T23:00:00Z"


def test_spring_day_has_23_hours_of_energy(db_path: Path) -> None:
    now = local(AMSTERDAM, 2026, 3, 30, 12)
    write_history(db_path, utc(2026, 3, 27, 22), now, constant_power(1000.0))
    days = daily_payload(db_path, now=now, days=3, timezone=AMSTERDAM)["days"]
    assert [day["hours"] for day in days] == [24.0, 23.0, 24.0]
    assert [day["electric_kwh"] for day in days[:2]] == [24.0, 23.0]
    assert days[1]["coverage"] == 1.0


def test_gaps_are_not_filled_and_lower_the_coverage(db_path: Path) -> None:
    write_history(db_path, utc(2026, 1, 13, 6), utc(2026, 1, 13, 12), constant_power(1000.0))
    write_history(db_path, utc(2026, 1, 13, 18), utc(2026, 1, 14), constant_power(1000.0))
    now = utc(2026, 1, 14, 6)
    days = daily_payload(db_path, now=now, days=3, timezone="UTC")["days"]
    missing, gappy, today = days
    assert missing["coverage"] == 0.0
    filled = {"date", "from", "to", "hours", "partial", "coverage", "writes"}
    assert all(missing[key] is None for key in DAY_KEYS - filled)
    assert missing["writes"] == 0
    assert gappy["coverage"] == 0.5
    assert gappy["electric_kwh"] == 12.0
    assert gappy["cop"] == 4.0
    assert gappy["compressor_starts"] is None
    assert gappy["run_s"] is None
    assert gappy["defrosts"] is None
    assert gappy["room_mean_c"] is None
    assert gappy["below_comfort_kh"] is None
    assert gappy["outside_mean_c"] is None
    assert today["partial"] is True
    assert today["coverage"] == 0.0
    assert today["electric_kwh"] is None


def test_coverage_of_today_is_measured_against_the_elapsed_part(db_path: Path) -> None:
    now = utc(2026, 1, 14, 12)
    write_history(db_path, utc(2026, 1, 14, 6), now, constant_power(2000.0))
    today = daily_payload(db_path, now=now, days=1, timezone="UTC")["days"][0]
    assert today["coverage"] == 0.5
    assert today["electric_kwh"] == 12.0


def test_missing_database_yields_empty_days(tmp_path: Path) -> None:
    body = daily_payload(
        tmp_path / "none.db",
        now=utc(2026, 1, 14, 12),
        days=7,
        timezone=AMSTERDAM,
        room_signal=ROOM,
        comfort_c=COMFORT_C,
    )
    assert body["timezone"] == AMSTERDAM
    assert body["room_signal"] == ROOM
    assert body["band_below_k"] == BAND_BELOW_K
    assert len(body["days"]) == 7
    for day in body["days"]:
        assert set(day) == DAY_KEYS
        assert day["coverage"] == 0.0
        assert day["electric_kwh"] is None
        assert day["writes"] is None
        assert day["comfort_c"] == COMFORT_C


def test_days_must_be_within_range(db_path: Path) -> None:
    for days in (0, 91):
        with pytest.raises(ValueError, match="days"):
            daily_payload(db_path, now=utc(2026, 1, 14), days=days, timezone="UTC")


def test_a_simulated_week_returns_seven_full_days(db_path: Path) -> None:
    now = utc(2026, 1, 15, 0, 0, 30)
    write_history(db_path, utc(2026, 1, 7, 23), now, plant)
    conn = sqlite3.connect(db_path)
    try:
        for day in range(8, 15):
            for hour, count in ((3, 4), (9, 2)):
                for attempt in range(count):
                    ts = utc(2026, 1, day, hour, attempt).timestamp()
                    conn.execute(
                        "INSERT INTO command (ts, kind, value, status, attempt, topic, payload, "
                        "detail) VALUES (?, 'water_setpoint', 31, 'sent', 1, NULL, NULL, '')",
                        (ts,),
                    )
            conn.execute(
                "INSERT INTO command (ts, kind, value, status, attempt, topic, payload, detail) "
                "VALUES (?, 'water_setpoint', 31, 'verified', 1, NULL, NULL, '')",
                (utc(2026, 1, day, 3, 30).timestamp(),),
            )
        conn.commit()
    finally:
        conn.close()
    body = daily_payload(
        db_path,
        now=now,
        days=8,
        timezone="UTC",
        room_signal=ROOM,
        comfort_c=COMFORT_C,
        journal_days=30.0,
    )
    days = body["days"][:7]
    assert [day["date"] for day in days] == [f"2026-01-{n:02d}" for n in range(8, 15)]
    for day in days:
        assert day["partial"] is False
        assert day["coverage"] == 1.0
        assert day["electric_kwh"] == 20.0
        assert day["heat_kwh"] == 80.0
        assert day["cop"] == 4.0
        assert day["compressor_starts"] == 24
        assert day["run_s"] == 24 * 50 * 60
        assert day["defrosts"] == 4
        assert day["defrost_s"] == 4 * 5 * 60
        assert day["dhw_runs"] == 1
        assert day["dhw_s"] == 30 * 60
        assert day["outside_mean_c"] == 1.0
        assert day["outside_min_c"] == -1.0
        assert day["room_mean_c"] == 20.2
        assert day["room_min_c"] == 20.2
        assert day["comfort_c"] == COMFORT_C
        assert day["below_comfort_kh"] == round((COMFORT_C - BAND_BELOW_K - 20.2) * 24, 2)
        assert day["setpoint_mean_c"] == 30.5
        assert day["setpoint_changes"] == 2
        assert day["writes"] == 6
    assert body["days"][7]["partial"] is True


def test_starts_count_across_a_gap_and_at_midnight(db_path: Path) -> None:
    def on_off(ts: float) -> dict[str, tuple[float, SampleKind]]:
        hour = datetime.fromtimestamp(ts, UTC).hour
        return {COMPRESSOR: (40.0 if hour in (0, 5, 6, 20) else 0.0, SampleKind.NUMBER)}

    write_history(db_path, utc(2026, 1, 13, 22), utc(2026, 1, 14, 2), on_off)
    write_history(db_path, utc(2026, 1, 14, 5), utc(2026, 1, 15), on_off)
    day = daily_payload(db_path, now=utc(2026, 1, 15), days=2, timezone="UTC")["days"][0]
    assert day["compressor_starts"] == 3
    assert day["run_s"] == 4 * 3600


def test_writes_are_null_before_the_journal_retention(db_path: Path) -> None:
    write_history(db_path, utc(2026, 1, 14), utc(2026, 1, 14, 0, 5), constant_power(1.0))
    body = daily_payload(
        db_path, now=utc(2026, 1, 14, 12), days=3, timezone="UTC", journal_days=1.0
    )
    assert [day["writes"] for day in body["days"]] == [None, None, 0]


@pytest.fixture
def insight_settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(
        control_timezone=AMSTERDAM,
        control_room_signal=ROOM,
        control_comfort_c=COMFORT_C,
        mqtt_inputs=[{"topic": "sim/room", "signal": ROOM, "unit": "°C"}],
    )


@pytest.fixture
def week_client(insight_settings: Settings) -> Iterator[tuple[TestClient, FakeClock]]:
    clock = FakeClock(local(AMSTERDAM, 2026, 1, 15, 9).timestamp())
    write_history(
        insight_settings.history_path,
        local(AMSTERDAM, 2026, 1, 8),
        clock().wall,
        plant,
    )
    with TestClient(create_app(Runtime(clock=clock), insight_settings)) as client:
        yield client, clock


def test_endpoint_uses_the_service_clock_and_time_zone(
    week_client: tuple[TestClient, FakeClock],
) -> None:
    client, _clock = week_client
    response = client.get("/api/v1/insight/daily")
    assert response.status_code == 200
    body = response.json()
    assert body["timezone"] == AMSTERDAM
    assert body["room_signal"] == ROOM
    days = body["days"]
    assert [day["date"] for day in days] == [f"2026-01-{n:02d}" for n in range(9, 16)]
    assert days[0]["from"] == "2026-01-08T23:00:00Z"
    assert all(day["coverage"] == 1.0 for day in days)
    assert all(day["electric_kwh"] is not None for day in days)
    assert all(day["comfort_c"] == COMFORT_C for day in days)
    assert days[-1]["partial"] is True
    month = client.get("/api/v1/insight/daily", params={"days": 30}).json()["days"]
    assert len(month) == 30
    assert month[0]["electric_kwh"] is None
    assert month[-7:] == days


@pytest.mark.parametrize("days", ["0", "91", "seven"])
def test_endpoint_refuses_bad_days(week_client: tuple[TestClient, FakeClock], days: str) -> None:
    client, _clock = week_client
    assert client.get("/api/v1/insight/daily", params={"days": days}).status_code == 422


def test_scaled_clock_returns_seven_days_after_a_simulated_week(
    insight_settings: Settings,
) -> None:
    real = [0.0]
    start = utc(2026, 1, 7)
    clock = ScaledClock(60.0, start, monotonic=lambda: real[0])
    real[0] = timedelta(days=7, hours=2).total_seconds() / 60.0
    write_history(insight_settings.history_path, start, clock().wall, plant)
    with TestClient(create_app(Runtime(clock=clock), insight_settings)) as client:
        days: list[dict[str, Any]] = client.get("/api/v1/insight/daily").json()["days"]
    assert len(days) == 7
    assert [day["date"] for day in days] == [f"2026-01-{n:02d}" for n in range(8, 15)]
    assert all(day["coverage"] > 0.9 for day in days)
    assert all(day["compressor_starts"] is not None for day in days)

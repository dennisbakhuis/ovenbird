"""Replay level 1: stored decisions stepped again over a period, against the pump's target."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ovenbird.api.app import create_app
from ovenbird.config import Settings
from ovenbird.configstore import ConfigManager
from ovenbird.history.database import HistoryDatabase, Sample, SampleKind
from ovenbird.history.journal import CommandRow, write_journal
from ovenbird.history.schema import open_history
from ovenbird.replay.engine import (
    MAX_DAYS,
    ReplayCancelledError,
    ReplayRequest,
    coverage_payload,
    max_days,
    run_replay,
)
from ovenbird.runtime import Runtime
from ovenbird.testing import RECORD_ROOM, RECORD_START, FakeClock, record_decisions

TOKEN = "operate-token-" + "x" * 24
MARK = {"X-Ovenbird-Request": "1"}
BEARER = {"Authorization": f"Bearer {TOKEN}"}
PUMP = "main/Z1_Water_Target_Temp"
INPUTS = [{"topic": "climate/room", "signal": RECORD_ROOM, "unit": "°C"}]
T0 = RECORD_START.timestamp()
DAY = 1440


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    """Settings with the recorded room input, a 21.5 degC comfort target and an operate token."""
    return make_settings(
        mqtt_inputs=INPUTS,
        control_room_signal=RECORD_ROOM,
        control_comfort_c=21.5,
        operate_token=TOKEN,
        control_timezone="Europe/Amsterdam",
    )


def write_pump(path: Path, minutes: int, value: Callable[[int], float]) -> None:
    """Write one pump target sample per minute, valued by a function of the minute."""
    database = HistoryDatabase(open_history(path))
    try:
        database.write_batch(
            [
                Sample(PUMP, None, SampleKind.NUMBER, T0 + 60.0 * m + 5.0, value(m), 330.0)
                for m in range(minutes)
            ]
        )
    finally:
        database.close()


def request(
    settings: Settings, minutes: int, candidate: Settings | None = None, **extra: Any
) -> ReplayRequest:
    """Build a replay request over the first minutes of the recording.

    Parameters
    ----------
    settings
        Settings the recording was made with, used as reference.
    minutes
        Length of the replay window in minutes.
    candidate
        Settings to replay with; defaults to ``settings``.
    **extra
        Further ``ReplayRequest`` fields such as ``step`` or ``threshold_k``.

    Returns
    -------
    ReplayRequest
        The request starting at the recording start.
    """
    config = settings.controller_config()
    return ReplayRequest(
        start=T0,
        end=T0 + minutes * 60.0,
        candidate=candidate or settings,
        reference=settings,
        settings_of=lambda version: settings if version in (1, 2) else None,
        config_of=lambda version: config if version in (1, 2) else None,
        config={"kind": "active", "version": 1},
        timezone=settings.control_timezone,
        **extra,
    )


def test_the_active_configuration_replays_exactly(tmp_path: Path, settings: Settings) -> None:
    """Replaying with the active settings reproduces every recorded setpoint and reports summary."""
    path = tmp_path / "history.db"
    records = record_decisions(path, settings, DAY)
    write_pump(path, DAY, lambda m: 32.0 if m < 600 else 45.0)
    phases: list[str] = []
    result = run_replay(
        path, request(settings, DAY, step=60), progress=lambda p, _d: phases.append(p)
    )
    assert result["ticks"] == DAY
    assert result["skipped"] == 0
    assert result["open_loop"] is True
    assert result["identity"]["ok"] is True
    assert result["identity"]["ticks"] == DAY
    assert result["identity"]["versions"] == [
        {"version": 1, "ticks": DAY, "mismatches": 0, "first_mismatch": None}
    ]
    series = result["series"]
    assert len(series["at"]) == DAY
    assert series["replayed"] == series["recorded"]
    assert series["replayed"][-1] == float(records[-1].setpoint or 0)
    summary = result["summary"]
    assert summary["differs_recorded_min"] == 0
    assert summary["changes_replayed"] == summary["changes_recorded"]
    assert summary["writes"] == summary["changes_replayed"]
    assert summary["compared_minutes"] == DAY
    assert summary["above_pump_min"] + summary["below_pump_min"] > 0
    assert result["episodes_total"] >= 1
    late = result["episodes"][-1]
    assert late["pump_c"] == 45.0
    assert late["reason"]
    assert late["recorded_c"] == late["ovenbird_c"]
    assert sum(day["writes"] for day in result["days"]) == summary["writes"]
    assert sum(summary["ladder"].values()) == pytest.approx(1.0, abs=0.01)
    assert sum(summary["reason"].values()) == pytest.approx(1.0, abs=0.01)
    assert "compare" in phases


def test_each_version_is_checked_with_its_own_settings(tmp_path: Path, settings: Settings) -> None:
    """Each config version in the recording is identity-checked against its own settings."""
    path = tmp_path / "history.db"
    record_decisions(path, settings, 600, version_at=300, restart_at=450)
    result = run_replay(path, request(settings, 600))
    identity = result["identity"]
    assert identity["ok"] is True
    assert [item["version"] for item in identity["versions"]] == [1, 2]
    assert identity["unknown"] == 0


def test_a_version_without_settings_is_not_compared(tmp_path: Path, settings: Settings) -> None:
    """Versions whose settings are unknown are counted as unknown instead of compared."""
    path = tmp_path / "history.db"
    record_decisions(path, settings, 120)
    base = request(settings, 120)
    result = run_replay(path, replace(base, settings_of=lambda _version: None))
    assert result["identity"]["ok"] is None
    assert result["identity"]["unknown"] == 120


def test_a_warmer_draft_differs_from_the_recording(
    tmp_path: Path, settings: Settings, make_settings: Callable[..., Settings]
) -> None:
    """A warmer draft config replays above the recording and reports the difference."""
    path = tmp_path / "history.db"
    record_decisions(path, settings, DAY)
    write_pump(path, DAY, lambda _m: 32.0)
    warmer = make_settings(
        mqtt_inputs=INPUTS,
        control_room_signal=RECORD_ROOM,
        control_comfort_c=23.0,
        control_timezone="Europe/Amsterdam",
    )
    result = run_replay(path, request(settings, DAY, candidate=warmer))
    summary = result["summary"]
    assert result["identity"]["ok"] is True
    assert summary["above_recorded_min"] > 0
    assert summary["mean_diff_recorded_k"] > 0
    assert summary["budget"] == warmer.command_daily_budget
    assert result["limitations"] == []


def test_the_replay_compares_the_issued_whole_degree_setpoints(
    tmp_path: Path, settings: Settings, make_settings: Callable[..., Settings]
) -> None:
    """Recorded, replayed and pump series and episodes use whole-degree setpoints."""
    path = tmp_path / "history.db"
    record_decisions(path, settings, DAY)
    write_pump(path, DAY, lambda _m: 31.0)
    draft = make_settings(
        mqtt_inputs=INPUTS,
        control_room_signal=RECORD_ROOM,
        control_comfort_c=22.3,
        control_timezone="Europe/Amsterdam",
    )
    result = run_replay(path, request(settings, DAY, candidate=draft, threshold_k=0.5))
    series = result["series"]
    for name in ("recorded", "replayed", "pump"):
        values = [value for value in series[name] if value is not None]
        assert values, name
        assert all(float(value).is_integer() for value in values), name
    assert result["episodes"]
    for episode in result["episodes"]:
        assert float(episode["ovenbird_c"]).is_integer()
        assert episode["recorded_c"] is None or float(episode["recorded_c"]).is_integer()


def test_ovenbird_commands_sent_are_counted(tmp_path: Path, settings: Settings) -> None:
    """Only commands with status sent are counted as ovenbird writes."""
    path = tmp_path / "history.db"
    record_decisions(path, settings, 120)
    conn = open_history(path)
    try:
        write_journal(
            conn,
            [],
            [
                CommandRow(T0 + 600, "water_setpoint", 33, "sent", 1, None, None, "{}"),
                CommandRow(T0 + 700, "water_setpoint", 33, "verified", 1, None, None, "{}"),
            ],
        )
    finally:
        conn.close()
    result = run_replay(path, request(settings, 120))
    assert result["summary"]["sent_recorded"] == 1


def test_a_cancelled_replay_stops(tmp_path: Path, settings: Settings) -> None:
    """A replay raises as cancelled once the cancel check returns true."""
    path = tmp_path / "history.db"
    record_decisions(path, settings, 1200)
    with pytest.raises(ReplayCancelledError):
        run_replay(path, request(settings, 1200), cancelled=lambda: True)


def test_an_empty_history_replays_nothing(tmp_path: Path, settings: Settings) -> None:
    """Replaying a missing database yields zero ticks and no identity verdict."""
    result = run_replay(tmp_path / "missing.db", request(settings, 60))
    assert result["ticks"] == 0
    assert result["identity"]["ok"] is None
    assert result["episodes"] == []
    assert result["summary"]["writes"] == 0


def test_coverage_counts_decisions_per_day_and_version(tmp_path: Path, settings: Settings) -> None:
    """Coverage reports decisions per day and the config versions present."""
    path = tmp_path / "history.db"
    record_decisions(path, settings, 2 * DAY, version_at=DAY)
    body = coverage_payload(
        path,
        start=T0 - 86_400.0,
        end=T0 + 3 * 86_400.0,
        timezone="UTC",
        interval_s=60.0,
        decision_days=30.0,
    )
    counts = {day["date"]: day["decisions"] for day in body["days"]}
    assert counts["2026-11-09"] == 0
    assert counts["2026-11-10"] == DAY
    assert counts["2026-11-11"] == DAY
    assert [v["version"] for v in body["versions"]] == [1, 2]
    assert body["max_days"] == 31
    assert body["oldest"] == "2026-11-10T00:00:00Z"


@pytest.mark.parametrize(("days", "limit"), [(30.0, 31), (0.0, MAX_DAYS), (400.0, MAX_DAYS)])
def test_the_longest_period_follows_the_retention(days: float, limit: int) -> None:
    """The longest replay period follows the decision retention, capped at the maximum."""
    assert max_days(days) == limit


@pytest.mark.slow
def test_thirty_days_replay_in_reasonable_time(tmp_path: Path, settings: Settings) -> None:
    """A 30-day replay finishes within two minutes with a passing identity check."""
    path = tmp_path / "history.db"
    record_decisions(path, settings, 30 * DAY)
    started = time.perf_counter()
    result = run_replay(path, request(settings, 30 * DAY))
    assert result["ticks"] == 30 * DAY
    assert result["identity"]["ok"] is True
    assert time.perf_counter() - started < 120.0


def wait(client: TestClient, job: dict[str, Any]) -> dict[str, Any]:
    """Poll a replay job until it stops running or 30 seconds pass, and return its last state."""
    deadline = time.monotonic() + 30.0
    while job["state"] == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
        job = client.get(f"/api/v1/replay/{job['id']}").json()
    return job


def app(settings: Settings) -> tuple[TestClient, ConfigManager]:
    """Build a test client and config manager with a clock two days past the recording."""
    clock = FakeClock(T0 + 2 * 86_400.0)
    manager = ConfigManager.open(settings, clock, locked={})
    return TestClient(create_app(Runtime(clock=clock), manager.settings, config=manager)), manager


def test_the_api_runs_a_draft_and_reports_progress(settings: Settings) -> None:
    """The API runs a draft replay as a job that ends done with the draft in the result."""
    client, manager = app(settings)
    record_decisions(manager.settings.history_path, manager.settings, DAY)
    with client:
        coverage = client.get("/api/v1/replay/coverage").json()
        assert sum(day["decisions"] for day in coverage["days"]) == DAY
        started = client.post(
            "/api/v1/replay",
            content=json.dumps(
                {
                    "from": "2026-11-10T00:00:00Z",
                    "to": "2026-11-11T00:00:00Z",
                    "config": "draft",
                    "changes": {"control_comfort_c": 22.5},
                }
            ),
            headers={**BEARER, **MARK, "Content-Type": "application/json"},
        )
        assert started.status_code == 202, started.text
        job = wait(client, started.json())
    assert job["state"] == "done", job
    assert job["config"] == {
        "kind": "draft",
        "version": None,
        "changes": {"control_comfort_c": 22.5},
    }
    assert job["result"]["ticks"] == DAY
    assert job["result"]["summary"]["above_recorded_min"] > 0


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({}, 400),
        ({"from": "2026-11-10T00:00:00Z", "to": "2026-11-09T00:00:00Z"}, 400),
        ({"from": "2026-09-01T00:00:00Z", "to": "2026-11-10T00:00:00Z"}, 400),
        (
            {"from": "2026-11-10T00:00:00Z", "to": "2026-11-11T00:00:00Z", "config": "x"},
            400,
        ),
        (
            {
                "from": "2026-11-10T00:00:00Z",
                "to": "2026-11-11T00:00:00Z",
                "config": "version",
                "version": 7,
            },
            404,
        ),
        (
            {
                "from": "2026-11-10T00:00:00Z",
                "to": "2026-11-11T00:00:00Z",
                "config": "draft",
                "changes": {"control_comfort_c": 99},
            },
            400,
        ),
        (
            {"from": "2026-11-10T00:00:00Z", "to": "2026-11-11T00:00:00Z", "step": 7},
            400,
        ),
        (
            {"from": "2026-11-10T00:00:00Z", "to": "2026-11-11T00:00:00Z", "threshold_k": 0},
            400,
        ),
    ],
)
def test_the_api_refuses_bad_requests(
    settings: Settings, body: dict[str, Any], status: int
) -> None:
    """Invalid replay requests are refused with 400, or 404 for an unknown version."""
    client, _ = app(settings)
    with client:
        response = client.post(
            "/api/v1/replay",
            content=json.dumps(body),
            headers={**BEARER, **MARK, "Content-Type": "application/json"},
        )
    assert response.status_code == status, response.text


def test_a_new_replay_cancels_the_running_one(settings: Settings) -> None:
    """Starting a replay cancels the running one; cancelling and unknown ids answer correctly."""
    client, manager = app(settings)
    record_decisions(manager.settings.history_path, manager.settings, 3 * DAY)
    headers = {**BEARER, **MARK, "Content-Type": "application/json"}
    body = json.dumps({"from": "2026-11-10T00:00:00Z", "to": "2026-11-13T00:00:00Z"})
    with client:
        first = client.post("/api/v1/replay", content=body, headers=headers).json()
        second = client.post("/api/v1/replay", content=body, headers=headers).json()
        first = wait(client, first)
        second = wait(client, second)
        cancelled = client.post(
            f"/api/v1/replay/{second['id']}/cancel", content="{}", headers=headers
        )
        missing = client.get("/api/v1/replay/0000")
    assert first["state"] in {"cancelled", "done"}
    assert second["state"] == "done"
    assert cancelled.status_code == 200
    assert missing.status_code == 404

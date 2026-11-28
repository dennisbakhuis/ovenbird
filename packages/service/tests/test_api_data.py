"""Data endpoints: signal inventory, storage, compaction and the streamed exports."""

from __future__ import annotations

import base64
import csv
import io
import json
import sqlite3
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ovenbird.api.app import create_app
from ovenbird.api.export import accepts_gzip
from ovenbird.config import Settings
from ovenbird.configstore import ConfigManager
from ovenbird.history import HistoryDatabase, Retention, Sample, SampleKind, open_history
from ovenbird.history.forecast import ForecastRow, write_forecast
from ovenbird.history.journal import AlarmRow, CommandRow, DecisionRow, write_journal
from ovenbird.history.writer import HistoryWriter
from ovenbird.runtime import Runtime
from ovenbird.testing import FakeClock

T0 = 1_800_000_000.0
DAY = 86_400.0
PASSWORD = "archive-admin-secret"
TOKEN = "operate-token-" + "z" * 24
HA_TOKEN = "ha-long-lived-" + "q" * 30
MARK = {"X-Ovenbird-Request": "1"}
NO_GZIP = {"Accept-Encoding": "identity"}


def basic(user: str = "admin", password: str = PASSWORD) -> dict[str, str]:
    """Return HTTP Basic authorization headers for the given credentials."""
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def sample(signal: str, ts: float, value: float, unit: str | None = "°C") -> Sample:
    """Build a numeric history sample for a signal."""
    return Sample(signal, unit, SampleKind.NUMBER, ts, value, 600.0)


def decision(ts: float, setpoint: int = 30) -> DecisionRow:
    """Build a shadow-mode decision journal row with the given setpoint."""
    record = json.dumps({"note": f"tick {setpoint}", "setpoint": setpoint}, sort_keys=True)
    return DecisionRow(
        ts, "ovenbird", "shadow", "curve_only", "curve", setpoint, record, "[]", "[]", 2
    )


def fill(path: Path, decisions: int = 3) -> None:
    """Populate a history database with samples, journal rows and a forecast."""
    conn = open_history(path)
    db = HistoryDatabase(conn)
    db.write_batch(
        [sample("main/Outlet_Temp", T0 + 60 * i, 30.0 + (i % 3)) for i in range(0, 2 * 24 * 60, 5)]
        + [sample("=cmd|calc", T0 + 30, 1.0, None), sample("=cmd|calc", T0 + 90, 2.0, None)]
    )
    write_journal(
        conn,
        [decision(T0 + 60 * i, 30 + i % 2) for i in range(decisions)],
        [CommandRow(T0 + 60, "water_setpoint", 31, "sent", 1, "t", "31", "=SUM(A1)")],
        [AlarmRow(T0 + 120, "room_stale", "warning", "raised", "room stale", '{"age": 1}')],
    )
    write_forecast(
        conn, [ForecastRow(T0, T0 + 3600 * h, 5.0 + h, 0.0, 50.0, 3.0) for h in range(3)]
    )
    conn.close()


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    """Secured settings with admin password, operate token and HA token."""
    return make_settings(
        admin_password=PASSWORD,
        operate_token=TOKEN,
        http_host="0.0.0.0",
        ha_token=HA_TOKEN,
        ha_url="http://homeassistant.local:8123",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """Yield a test client over an app backed by a filled history database."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    fill(settings.history_path)
    clock = FakeClock(T0 + 3 * DAY)
    manager = ConfigManager.open(settings, clock, locked={})
    app = create_app(Runtime(clock=clock), manager.settings, config=manager)
    with TestClient(app) as test_client:
        yield test_client


def rows(text: str) -> list[list[str]]:
    """Parse CSV text into rows of cells."""
    return list(csv.reader(io.StringIO(text)))


def test_signal_inventory(client: TestClient) -> None:
    """The signal inventory lists unit, kind and per-resolution coverage."""
    body = client.get("/api/v1/history/signals", headers=basic()).json()
    outlet = next(s for s in body["signals"] if s["id"] == "main/Outlet_Temp")
    assert outlet["unit"] == "°C"
    assert outlet["kind"] == "number"
    steps = {r["step"]: r for r in outlet["resolutions"]}
    assert set(steps) == {0, 60, 900, 3600}
    assert steps[3600]["first"] == "2027-01-15T08:00:00Z"
    assert steps[3600]["points"] == 48


def test_series_long_csv_with_rollup_extremes(client: TestClient) -> None:
    """Hourly CSV export includes rollup minima and maxima and honours the time window."""
    response = client.get(
        "/api/v1/export/series",
        params={
            "signals": "main/Outlet_Temp",
            "step": "3600",
            "from": "2027-01-15T08:00:00Z",
            "to": "2027-01-15T10:00:00Z",
        },
        headers={**basic(), **NO_GZIP},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    table = rows(response.text)
    assert table[0] == ["at", "signal", "unit", "value", "min", "max"]
    assert [r[0] for r in table[1:]] == ["2027-01-15T08:00:00Z", "2027-01-15T09:00:00Z"]
    assert float(table[1][4]) == 30.0
    assert float(table[1][5]) == 32.0


def test_series_spans_days_without_a_point_cap(client: TestClient) -> None:
    """A raw NDJSON export spans all days of data without truncating."""
    response = client.get(
        "/api/v1/export/series",
        params={"signals": "main/Outlet_Temp", "step": "raw", "format": "ndjson"},
        headers={**basic(), **NO_GZIP},
    )
    lines = [json.loads(line) for line in response.text.splitlines()]
    days = {line["at"][:10] for line in lines}
    assert len(days) == 3
    assert all(set(line) == {"at", "signal", "unit", "value"} for line in lines)
    assert response.headers["content-type"].startswith("application/x-ndjson")


def test_series_wide_layout_and_formula_protection(client: TestClient) -> None:
    """Wide layout pivots signals into columns and prefixes formula-like names with a quote."""
    response = client.get(
        "/api/v1/export/series",
        params={"signals": "all", "step": "raw", "layout": "wide", "to": "2027-01-15T08:03:00Z"},
        headers={**basic(), **NO_GZIP},
    )
    table = rows(response.text)
    assert table[0] == ["at", "'=cmd|calc", "main/Outlet_Temp"]
    assert table[1] == ["2027-01-15T08:00:00Z", "", "30.0"]
    assert table[2] == ["2027-01-15T08:00:30Z", "1.0", ""]


def test_series_is_gzipped_when_accepted(client: TestClient) -> None:
    """The series export is gzip-encoded when the client accepts gzip."""
    response = client.get(
        "/api/v1/export/series",
        params={"signals": "main/Outlet_Temp", "step": "60"},
        headers={**basic(), "Accept-Encoding": "gzip"},
    )
    assert response.headers["content-encoding"] == "gzip"
    assert response.text.startswith("at,signal,unit,value,min,max\n")


def test_series_refuses_unknown_signals_and_steps(client: TestClient) -> None:
    """Unknown signals, invalid steps and reversed windows are refused."""
    unknown = client.get("/api/v1/export/series", params={"signals": "main/Nope"}, headers=basic())
    assert unknown.status_code == 400
    assert "main/Nope" in unknown.json()["detail"]
    assert (
        client.get("/api/v1/export/series", params={"step": "5"}, headers=basic()).status_code
        == 422
    )
    reversed_ = client.get(
        "/api/v1/export/series", params={"from": "2027-02-01", "to": "2027-01-01"}, headers=basic()
    )
    assert reversed_.status_code == 400


def test_series_far_beyond_the_data_is_cheap(client: TestClient) -> None:
    """A window far wider than the data still answers 200 with rows."""
    response = client.get(
        "/api/v1/export/series",
        params={"from": "1970-01-02T00:00:00Z", "to": "2100-01-01T00:00:00Z", "step": "900"},
        headers={**basic(), **NO_GZIP},
    )
    assert response.status_code == 200
    assert len(rows(response.text)) > 1


def test_journal_exports(client: TestClient) -> None:
    """Journal exports cover decisions, commands, alarms and forecast; unknown kinds are refused."""
    decisions = client.get("/api/v1/export/journal/decisions", headers={**basic(), **NO_GZIP})
    table = rows(decisions.text)
    assert table[0][:3] == ["at", "controller", "mode"]
    assert len(table) == 4
    commands = rows(
        client.get("/api/v1/export/journal/commands", headers={**basic(), **NO_GZIP}).text
    )
    assert commands[1][-1] == "'=SUM(A1)"
    alarms = client.get(
        "/api/v1/export/journal/alarms", params={"format": "ndjson"}, headers={**basic(), **NO_GZIP}
    )
    assert json.loads(alarms.text.splitlines()[0])["detail"] == {"age": 1}
    forecast = rows(
        client.get("/api/v1/export/journal/forecast", headers={**basic(), **NO_GZIP}).text
    )
    assert forecast[0] == [
        "issued_at",
        "target_at",
        "temp_c",
        "radiation_wm2",
        "cloud_pct",
        "wind_ms",
    ]
    assert len(forecast) == 4
    ndjson = client.get(
        "/api/v1/export/journal/decisions",
        params={"format": "ndjson"},
        headers={**basic(), **NO_GZIP},
    )
    first = json.loads(ndjson.text.splitlines()[0])
    assert first["record"] == {"note": "tick 30", "setpoint": 30}
    assert client.get("/api/v1/export/journal/audit", headers=basic()).status_code == 422


def test_decision_export_has_no_row_cap(settings: Settings) -> None:
    """Exporting thousands of decisions returns every row."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    fill(settings.history_path, decisions=6000)
    app = create_app(Runtime(clock=FakeClock(T0 + 10 * DAY)), settings)
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/export/journal/decisions", params={"format": "ndjson"}, headers=basic()
        )
    lines = response.text.splitlines()
    assert len(lines) == 6000
    assert json.loads(lines[-1])["at"] == "2027-01-19T11:59:00Z"


def test_archive_is_admin_only_and_holds_no_secrets(client: TestClient) -> None:
    """The archive is admin-only and holds config, database and manifest without credentials."""
    assert (
        client.get(
            "/api/v1/export/archive", headers={"Authorization": f"Bearer {TOKEN}"}
        ).status_code
        == 403
    )
    response = client.get("/api/v1/export/archive", headers=basic())
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    raw = response.content
    for secret in (PASSWORD, TOKEN, HA_TOKEN):
        assert secret.encode() not in raw
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert sorted(archive.namelist()) == ["config.json", "history.db", "manifest.json"]
        manifest = json.loads(archive.read("manifest.json"))
        database = archive.read("history.db")
        config = archive.read("config.json")
    for secret in (PASSWORD, TOKEN, HA_TOKEN):
        assert secret.encode() not in database
        assert secret.encode() not in config
    assert manifest["ovenbird_archive"] == 1
    assert manifest["history_schema"] >= 6
    assert {s["id"] for s in manifest["signals"]} == {"main/Outlet_Temp", "=cmd|calc"}
    assert "occupied" in manifest["notice"]


def test_archive_database_is_a_readable_copy(client: TestClient, tmp_path: Path) -> None:
    """The archived history database opens as SQLite and no temporary files remain."""
    raw = client.get("/api/v1/export/archive", headers=basic()).content
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        target = tmp_path / "copy.db"
        target.write_bytes(archive.read("history.db"))
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT count(*) FROM decision").fetchone() == (3,)
    leftovers = [p for p in (tmp_path / "data").iterdir() if p.name.startswith(".archive-")]
    assert leftovers == []


def test_storage_report(client: TestClient) -> None:
    """The storage report lists resolutions with retention, oldest sample and projected size."""
    body = client.get("/api/v1/history/storage", headers=basic()).json()
    assert body["files"]["database"] > 0
    ids = [r["id"] for r in body["resolutions"]]
    assert ids == ["raw", "60", "900", "3600", "journal", "forecast"]
    raw = body["resolutions"][0]
    assert raw["retention_days"] == 14.0
    assert raw["oldest"] == "2027-01-15T08:00:00Z"
    assert body["resolutions"][2]["retention_days"] is None
    assert body["compaction"] is None
    if body["tables"]:
        assert body["projected_bytes"] > 0
        assert {t["name"] for t in body["tables"]} >= {"sample", "rollup", "decision"}


def test_compaction_through_the_api(settings: Settings) -> None:
    """Compaction is admin-only, accepted once while pending, run by the writer and audited."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    fill(settings.history_path)
    clock = FakeClock(T0 + 3 * DAY)
    manager = ConfigManager.open(settings, clock, locked={})
    writer = HistoryWriter(settings.history_path, Retention(), min_free_bytes=0, wall=lambda: T0)
    writer.run_once([])
    app = create_app(Runtime(clock=clock), manager.settings, config=manager, writer=writer)
    with TestClient(app) as client:
        refused = client.post(
            "/api/v1/history/compact", json={}, headers={"Authorization": f"Bearer {TOKEN}", **MARK}
        )
        assert refused.status_code == 403
        response = client.post("/api/v1/history/compact", json={}, headers={**basic(), **MARK})
        assert response.status_code == 202
        assert response.json()["accepted"] is True
        assert response.json()["compaction"]["pending"] is True
        again = client.post("/api/v1/history/compact", json={}, headers={**basic(), **MARK})
        assert again.json()["accepted"] is False
        writer.run_once([])
        state = client.get("/api/v1/history/storage", headers=basic()).json()["compaction"]
        assert state["pending"] is False
        assert state["last_at"] == "2027-01-15T08:00:00Z"
        audit = client.get(
            "/api/v1/audit", params={"from": "2000-01-01", "to": "2100-01-01"}, headers=basic()
        )
        assert "history_compact" in [event["action"] for event in audit.json()["events"]]
    writer._close()


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, False),
        ("gzip", True),
        ("deflate, gzip;q=0.5", True),
        ("gzip;q=0", False),
        ("identity", False),
        ("*", True),
        ("br", False),
    ],
)
def test_accepts_gzip(header: str | None, expected: bool) -> None:
    """Accept-Encoding parsing honours gzip, wildcards and zero quality values."""
    assert accepts_gzip(header) is expected

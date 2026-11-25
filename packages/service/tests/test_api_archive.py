"""Archive endpoints, retention presets and the one-day retention minimum."""

from __future__ import annotations

import base64
import io
import json
import re
import zipfile
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ovenbird.api.app import create_app
from ovenbird.config import ConfigError, Settings
from ovenbird.configstore import ConfigManager
from ovenbird.history import HistoryDatabase, Retention, Sample, SampleKind, open_history
from ovenbird.history.archive import REWIND_S, MonthArchiver
from ovenbird.history.journal import DecisionRow, write_journal
from ovenbird.history.settings import RETENTION_PRESETS
from ovenbird.history.writer import HistoryWriter
from ovenbird.runtime import Runtime
from ovenbird.testing import FakeClock

DAY = 86_400.0
JAN = datetime(2027, 1, 1, tzinfo=UTC).timestamp()
FEB = datetime(2027, 2, 1, tzinfo=UTC).timestamp()
MAR = datetime(2027, 3, 1, tzinfo=UTC).timestamp()
NOW = MAR + 2 * DAY
PASSWORD = "archive-admin-secret"
TOKEN = "operate-token-" + "z" * 24
HA_TOKEN = "ha-long-lived-" + "q" * 30
MARK = {"X-Ovenbird-Request": "1"}
ROOT = Path(__file__).resolve().parents[3]
FIELD_DAYS = re.compile(r"(history_\w+): (\d+)")


def basic() -> dict[str, str]:
    token = base64.b64encode(f"admin:{PASSWORD}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def bearer() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def fill(settings: Settings, start: float, end: float) -> None:
    conn = open_history(settings.history_path)
    db = HistoryDatabase(conn)
    db.write_batch(
        [
            Sample("main/Outlet_Temp", "°C", SampleKind.NUMBER, start + 300 * i, 30.0, 600.0)
            for i in range(int((end - start) // 300))
        ]
    )
    write_journal(
        conn,
        [
            DecisionRow(t, "ovenbird", "shadow", "curve_only", "curve", 31, "{}", "[]", "[]", 1)
            for t in range(int(start), int(end), 3600)
        ],
        [],
    )
    conn.close()


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(
        admin_password=PASSWORD,
        operate_token=TOKEN,
        http_host="0.0.0.0",
        ha_token=HA_TOKEN,
        ha_url="http://homeassistant.local:8123",
        control_timezone="UTC",
    )


@pytest.fixture
def manager(settings: Settings) -> ConfigManager:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return ConfigManager.open(settings, FakeClock(NOW), locked={})


@pytest.fixture
def writer(settings: Settings, manager: ConfigManager) -> Iterator[HistoryWriter]:
    fill(settings, JAN + 5 * DAY, NOW)
    archiver = MonthArchiver(
        settings.history_path,
        settings.archive_dir,
        timezone="UTC",
        config_source=manager.archive_config,
        budget_s=600.0,
    )
    built = HistoryWriter(
        settings.history_path,
        Retention(),
        journal_days=30.0,
        wall=lambda: NOW,
        archiver=archiver,
        min_free_bytes=0,
    )
    built.run_once([])
    yield built
    built._close()


@pytest.fixture
def client(manager: ConfigManager, writer: HistoryWriter) -> Iterator[TestClient]:
    app = create_app(Runtime(clock=FakeClock(NOW)), manager.settings, config=manager, writer=writer)
    with TestClient(app) as test_client:
        yield test_client


def test_status_lists_months_years_and_seasons(client: TestClient) -> None:
    body = client.get("/api/v1/archive", headers=bearer()).json()
    assert body["enabled"] is True
    assert body["timezone"] == "UTC"
    assert body["state"]["error"] is None
    assert body["state"]["behind"] is False
    months = {item["period"]: item for item in body["months"]}
    assert set(months) == {"2027-01", "2027-02", "2027-03"}
    assert months["2027-01"]["state"] == "frozen"
    assert months["2027-01"]["complete"] is False
    assert months["2027-01"]["missing_days"] == 5
    assert months["2027-02"]["complete"] is True
    assert months["2027-03"]["state"] == "open"
    assert months["2027-03"]["archived_to"] is not None
    assert [group["id"] for group in body["years"]] == ["2027"]
    assert [group["period"] for group in body["seasons"]] == ["2026/27"]
    assert body["seasons"][0]["id"] == "2026-27"
    assert "occupied" in body["notice"]


def test_downloads_need_admin(client: TestClient) -> None:
    for path in ("months/2027-01", "years/2027", "seasons/2026-27"):
        assert client.get(f"/api/v1/archive/{path}", headers=bearer()).status_code == 403


def test_a_frozen_month_downloads_as_its_file(client: TestClient) -> None:
    response = client.get("/api/v1/archive/months/2027-02", headers=basic())
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "ovenbird-archive-2027-02.zip" in response.headers["content-disposition"]
    raw = response.content
    for secret in (PASSWORD, TOKEN, HA_TOKEN):
        assert secret.encode() not in raw
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert sorted(archive.namelist()) == ["config.json", "history.db", "manifest.json"]
        manifest = json.loads(archive.read("manifest.json"))
        config = json.loads(archive.read("config.json"))
    assert manifest["period"] == "2027-02"
    assert manifest["complete"] is True
    assert config["ovenbird_config"] == 1
    assert "versions" in config


def test_the_open_month_downloads_as_it_stands(client: TestClient, settings: Settings) -> None:
    response = client.get("/api/v1/archive/months/2027-03", headers=basic())
    assert response.status_code == 200
    assert "2027-03-partial" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["frozen"] is False
    leftovers = [p for p in settings.data_dir.iterdir() if p.name.startswith(".archive-")]
    assert leftovers == []


def test_year_and_season_bundles(client: TestClient) -> None:
    response = client.get("/api/v1/archive/years/2027", headers=basic())
    assert response.status_code == 200
    assert "ovenbird-archive-2027.zip" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        assert sorted(bundle.namelist()) == ["2027-01.zip", "2027-02.zip", "manifest.json"]
        manifest = json.loads(bundle.read("manifest.json"))
    assert manifest["kind"] == "year"
    assert manifest["partial"] is True
    assert manifest["coverage"]["months"] == 2
    season = client.get("/api/v1/archive/seasons/2026-27", headers=basic())
    assert season.status_code == 200
    assert "ovenbird-archive-season-2026-27.zip" in season.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(season.content)) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
    assert manifest["period"] == "2026/27"
    assert manifest["from"] == "2026-08-01T00:00:00Z"


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("months/2027-13", 400),
        ("months/2026-05", 404),
        ("years/27", 400),
        ("years/2025", 404),
        ("seasons/2026-28", 400),
        ("seasons/2020-21", 404),
    ],
)
def test_bad_or_unknown_periods(client: TestClient, path: str, status: int) -> None:
    assert client.get(f"/api/v1/archive/{path}", headers=basic()).status_code == status


def test_delete_a_month_and_a_year(client: TestClient) -> None:
    headers = {**basic(), **MARK}
    refused = client.post(
        "/api/v1/archive/delete", json={"period": "2027-01"}, headers={**bearer(), **MARK}
    )
    assert refused.status_code == 403
    assert (
        client.post(
            "/api/v1/archive/delete", json={"period": "2027-03"}, headers=headers
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/archive/delete", json={"period": "2026-01"}, headers=headers
        ).status_code
        == 404
    )
    assert (
        client.post("/api/v1/archive/delete", json={"period": 5}, headers=headers).status_code
        == 400
    )
    response = client.post("/api/v1/archive/delete", json={"period": "2027-01"}, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["deleted"] == ["2027-01"]
    assert [m["period"] for m in body["archive"]["months"]] == ["2027-03", "2027-02"]
    year = client.post("/api/v1/archive/delete", json={"period": "2027"}, headers=headers)
    assert year.json()["deleted"] == ["2027-02"]
    audit = client.get(
        "/api/v1/audit", params={"from": "2000-01-01", "to": "2100-01-01"}, headers=basic()
    )
    actions = [event["action"] for event in audit.json()["events"]]
    assert actions.count("archive_delete") == 2


def test_deleted_months_stay_deleted(client: TestClient, writer: HistoryWriter) -> None:
    headers = {**basic(), **MARK}
    client.post("/api/v1/archive/delete", json={"period": "2027-02"}, headers=headers)
    assert writer.archiver is not None
    writer.archiver.step(NOW + REWIND_S)
    body = client.get("/api/v1/archive", headers=bearer()).json()
    assert "2027-02" not in [m["period"] for m in body["months"]]


def test_switching_the_archive_off(client: TestClient, writer: HistoryWriter) -> None:
    version = client.get("/api/v1/config", headers=basic()).json()["version"]
    response = client.put(
        "/api/v1/config",
        json={"base_version": version, "changes": {"history_archive_enabled": False}},
        headers={**basic(), **MARK},
    )
    assert response.status_code == 200
    assert client.get("/api/v1/archive", headers=bearer()).json()["enabled"] is False


def test_storage_report_projects_every_preset(client: TestClient) -> None:
    body = client.get("/api/v1/history/storage", headers=bearer()).json()
    assert body["preset"] == "standard"
    presets = {item["id"]: item for item in body["presets"]}
    assert list(presets) == ["short", "standard", "long", "unlimited"]
    assert presets["standard"]["values"]["history_1m_days"] == 90.0
    if body["projected_bytes"] is not None:
        assert presets["standard"]["projected_bytes"] == body["projected_bytes"]
        assert presets["short"]["projected_bytes"] <= presets["long"]["projected_bytes"]


@pytest.mark.parametrize("preset", ["short", "standard", "long", "unlimited"])
def test_every_preset_validates_without_warnings(client: TestClient, preset: str) -> None:
    body = client.post(
        "/api/v1/config/validate",
        json={"changes": dict(RETENTION_PRESETS[preset])},
        headers={**bearer(), **MARK},
    ).json()
    assert (body["errors"], body["warnings"]) == ([], [])


@pytest.mark.parametrize("field", ["history_raw_days", "history_1m_days", "history_decision_days"])
def test_a_retention_below_one_day_is_refused(
    make_settings: Callable[..., Settings], field: str
) -> None:
    with pytest.raises(ConfigError, match="at least"):
        make_settings(**{field: 0.5})
    assert getattr(make_settings(**{field: 0}), field) == 0
    assert getattr(make_settings(**{field: 1}), field) == 1


def test_validation_names_the_retention_minimum(client: TestClient) -> None:
    response = client.post(
        "/api/v1/config/validate",
        json={"changes": {"history_1m_days": 0.25}},
        headers={**bearer(), **MARK},
    )
    body = response.json()
    assert body["valid"] is False
    assert [(e["field"], e["code"]) for e in body["errors"]] == [
        ("history_1m_days", "retention_min")
    ]
    assert body["errors"][0]["params"]["min"] == 1.0


def test_the_ui_knows_the_presets() -> None:
    text = (ROOT / "ui" / "src" / "lib" / "system" / "retention.ts").read_text(encoding="utf-8")
    for name, values in RETENTION_PRESETS.items():
        block = re.search(rf"\n  {name}: \{{(.*?)\}}", text, re.S)
        assert block is not None, name
        found = {field: float(days) for field, days in FIELD_DAYS.findall(block.group(1))}
        assert found == dict(values), name

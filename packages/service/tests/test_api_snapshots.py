"""Every API v1 route answers byte for byte what the recorded snapshots say.

The snapshots in ``tests/fixtures/api/`` were recorded from the routers before the
response models existed; they prove that attaching ``response_model`` changed no
byte of any body (key order, number formatting, absent and ``null`` keys). Set
``UPDATE_API_SNAPSHOTS=1`` to record them again after an intended change. Every
recorded success body also validates against its route's model without a key the
model does not declare.
"""

from __future__ import annotations

import base64
import json
import os
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, TypeAdapter

from ovenbird.api.app import create_app
from ovenbird.api.openapi import routes
from ovenbird.config import Settings
from ovenbird.configstore import ConfigManager
from ovenbird.history import HistoryDatabase, Sample, SampleKind, open_history
from ovenbird.history.journal import AlarmRow, CommandRow, DecisionRow, write_journal
from ovenbird.mqtt import MqttIngest
from ovenbird.notify.notifier import Notifier
from ovenbird.pump.settings import PumpSettings
from ovenbird.runtime import Runtime
from ovenbird.service import build_control
from ovenbird.system.about import record_start
from ovenbird.system.facts import Facts
from ovenbird.testing import FakeClock, pump_messages
from ovenbird.trial.supervision import Supervision
from ovenbird.weather import OpenMeteoProvider, WeatherService

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOTS = FIXTURES / "api"
WEATHER = FIXTURES / "weather" / "open_meteo_forecast.json"
UPDATE_ENV = "UPDATE_API_SNAPSHOTS"
PASSWORD = "pw-123"
T0 = datetime(2026, 11, 2, 0, 0, tzinfo=UTC).timestamp()
NOW = T0 + 200 * 60
ROOM = "room_temperature"
SETPOINT = "main/Z1_Water_Target_Temp"
OUTSIDE = "main/Outside_Temp"
WINDOW = {"from": "2026-11-02T00:00:00Z", "to": "2026-11-02T03:20:00Z"}
TICKET = re.compile(rb'"ticket":"[A-Za-z0-9_-]+"')
PARAM = re.compile(r"\{[^}]+\}")
UNORDERED = frozenset({"insight_house_ready"})
BUILDING = {
    "c_water": 2.5e6,
    "c_mass": 4.0e7,
    "c_air": 1.0e7,
    "h_water_mass": 400.0,
    "h_water_air": 150.0,
    "h_mass_air": 800.0,
    "h_air_out": 145.0,
    "solar_aperture_m2": 3.0,
    "solar_mass_fraction": 0.5,
    "q_int_w": 300.0,
    "q_int_modulation": 0.0,
    "q_int_peak_hour": 19.0,
}
INSIGHT = {
    "schema": "ovenbird.house-insight/1",
    "model": "house-20261101",
    "ua": {"w_per_k": 145.0, "interval_90": [136.0, 156.0], "source": "rc_model"},
    "time_constant_h": {"value": 50.0, "interval_90": [45.0, 60.0]},
    "credibility": {"credible": True, "message": None},
    "score": {"state": "stale value from the learner"},
    "proposal": {
        "based_on_curve": [[-10.0, 39.0], [0.0, 34.0], [15.0, 25.0]],
        "curve": [[-10.0, 38.0], [0.0, 33.5], [15.0, 25.0]],
        "credible": True,
        "points": [
            {"outside_c": -10.0, "water_c": 38.0},
            {"outside_c": 0.0, "water_c": 33.5},
            {"outside_c": 15.0, "water_c": 25.0},
        ],
    },
}


async def no_sleep(_: float) -> None:
    return None


def admin() -> dict[str, str]:
    token = base64.b64encode(f"admin:{PASSWORD}".encode()).decode()
    return {"Authorization": f"Basic {token}", "X-Ovenbird-Request": "1"}


@dataclass(frozen=True, slots=True)
class Case:
    """One recorded request."""

    name: str
    method: str
    path: str
    params: dict[str, Any] | None = None
    body: dict[str, Any] | None = None


CASES = (
    Case("health", "GET", "/health"),
    Case("snapshot", "GET", "/snapshot"),
    Case("history", "GET", "/history", {"signals": f"{OUTSIDE},{ROOM},nope", **WINDOW}),
    Case("history_step", "GET", "/history", {"signals": SETPOINT, "step": 900, **WINDOW}),
    Case("history_bad", "GET", "/history", {"signals": ""}),
    Case("decisions", "GET", "/decisions", {"limit": 3, **WINDOW}),
    Case("decisions_latest", "GET", "/decisions/latest"),
    Case("alarms", "GET", "/alarms", WINDOW),
    Case("commands", "GET", "/commands", WINDOW),
    Case("decision_series", "GET", "/decisions/series", {"step": 900, **WINDOW}),
    Case("config_schema", "GET", "/config/schema"),
    Case("config", "GET", "/config"),
    Case("config_signals", "GET", "/config/signals"),
    Case(
        "config_validate", "POST", "/config/validate", body={"changes": {"control_comfort_c": 21.4}}
    ),
    Case(
        "config_validate_bad",
        "POST",
        "/config/validate",
        body={"changes": {"control_comfort_c": 99}},
    ),
    Case(
        "config_preview",
        "POST",
        "/config/preview",
        body={"changes": {"control_comfort_c": 21.4}, "hours": 3},
    ),
    Case(
        "config_preview_bad", "POST", "/config/preview", body={"changes": {"control_comfort_c": 99}}
    ),
    Case(
        "config_apply",
        "PUT",
        "/config",
        body={"base_version": 0, "changes": {"control_comfort_c": 21.4}, "comment": "warmer"},
    ),
    Case(
        "config_apply_again",
        "PUT",
        "/config",
        body={"base_version": 1, "changes": {"control_comfort_c": 21.6}},
    ),
    Case("config_apply_stale", "PUT", "/config", body={"base_version": 0, "changes": {}}),
    Case("config_versions", "GET", "/config/versions", {"limit": 5}),
    Case("config_version", "GET", "/config/versions/1"),
    Case("config_version_missing", "GET", "/config/versions/99"),
    Case("config_rollback", "POST", "/config/rollback", body={"version": 1, "base_version": 2}),
    Case("config_export", "GET", "/config/export"),
    Case("config_reset_ack", "POST", "/config/reset-ack", body={}),
    Case("pause", "POST", "/control/pause", body={"reason": "snapshot test"}),
    Case("resume", "POST", "/control/resume", body={}),
    Case("stove_on", "POST", "/control/stove", body={"on": True}),
    Case("stove_off", "POST", "/control/stove", body={"on": False}),
    Case("release_hold", "POST", "/control/release-hold", body={}),
    Case("audit", "GET", "/audit", {"limit": 50, "from": WINDOW["from"]}),
    Case("pump_settings", "GET", "/pump/settings"),
    Case("pump_write", "POST", "/pump/settings/heat_delta", body={"value": 4, "expect": 5}),
    Case(
        "pump_write_refused", "POST", "/pump/settings/heat_delta", body={"value": 11, "expect": 5}
    ),
    Case("weather", "GET", "/weather", {"back_h": 4, "ahead_h": 6}),
    Case("insight_daily", "GET", "/insight/daily", {"days": 2}),
    Case("insight_house_not_run", "GET", "/insight/house"),
    Case("insight_house_series_missing", "GET", "/insight/house/series"),
    Case("insight_house_whatif_missing", "GET", "/insight/house/whatif"),
    Case("insight_house_balance_missing", "GET", "/insight/house/balance"),
    Case("insight_house_ready", "GET", "/insight/house"),
    Case("insight_house_history", "GET", "/insight/house/history"),
    Case("insight_house_series", "GET", "/insight/house/series"),
    Case("insight_house_whatif", "GET", "/insight/house/whatif"),
    Case(
        "insight_house_whatif_scenario",
        "GET",
        "/insight/house/whatif",
        {"outside_c": -8, "comfort_c": 21, "sun_wm2": 120, "stove_w": 2000},
    ),
    Case("insight_house_whatif_range", "GET", "/insight/house/whatif", {"outside_c": 99}),
    Case("insight_house_balance", "GET", "/insight/house/balance"),
    Case("proposal_draft", "POST", "/insight/house/proposal/draft", body={}),
    Case("insight_house_run", "GET", "/insight/house/run"),
    Case("insight_house_run_unavailable", "POST", "/insight/house/run", body={}),
    Case("divergence", "GET", "/shadow/divergence", WINDOW),
    Case(
        "explain",
        "POST",
        "/shadow/episodes/explain",
        body={"start": "2026-11-02T01:00:00Z", "note": "service visit"},
    ),
    Case("trial_status", "GET", "/trial/status"),
    Case("insight_runs", "GET", "/insight/runs", {"days": 2}),
    Case("control_snapshot", "GET", "/control/snapshot"),
    Case("control_snapshot_capture", "POST", "/control/snapshot", body={}),
    Case("control_release_status", "GET", "/control/release"),
    Case("control_release", "POST", "/control/release", body={"rehearsal": True, "dry": True}),
    Case("notifications", "GET", "/notifications/status"),
    Case("notifications_test", "POST", "/notifications/test", body={}),
    Case("about", "GET", "/system/about"),
    Case("diagnostics", "GET", "/diagnostics", {"items": 5}),
    Case("live_ticket", "POST", "/live/ticket", body={}),
    Case("archive", "GET", "/archive"),
    Case("archive_delete_missing", "POST", "/archive/delete", body={"period": "2026-10"}),
)


def write_history(path: Path, rows: list[DecisionRow]) -> None:
    database = HistoryDatabase(open_history(path))
    try:
        batch: list[Sample] = []
        ts = T0
        while ts <= NOW:
            minute = (ts - T0) / 60.0
            values = {
                SETPOINT: 34.0 if 60 <= minute < 120 else 30.0,
                OUTSIDE: 3.0 + minute / 100.0,
                ROOM: 20.5 + minute / 400.0,
                "main/Compressor_Freq": 30.0 if minute % 40 < 25 else 0.0,
            }
            batch.extend(
                Sample(signal, None, SampleKind.NUMBER, ts, value, 330.0)
                for signal, value in values.items()
            )
            ts += 60.0
        database.write_batch(batch)
    finally:
        database.close()
    shadow = [
        DecisionRow(
            T0 + 30 + 60 * m, "ovenbird", "shadow", "normal", "curve", 30, "{}", "{}", "[]", 1
        )
        for m in range(195)
    ]
    commands = [
        CommandRow(T0 + 600, "water_setpoint", 31, "verified", 1, None, None, "verified"),
        CommandRow(T0 + 1200, "heat_delta", 5, "refused", 1, None, None, "out of range"),
    ]
    alarms = [AlarmRow(T0 + 900, "pump_error", "critical", "raised", "H23", "{}")]
    conn = open_history(path)
    try:
        write_journal(conn, shadow + rows, commands, alarms)
    finally:
        conn.close()


def write_models(root: Path) -> None:
    models = root / "models"
    models.mkdir(parents=True, exist_ok=True)
    house_file = {"schema": "ovenbird.plant-params/1", "params": {"building": BUILDING}}
    (models / "house-20261101.json").write_text(json.dumps(house_file), encoding="utf-8")
    rows = [
        [
            datetime.fromtimestamp(T0 + 900 * k, UTC).isoformat(timespec="seconds"),
            20.5 + k / 100.0,
            None if k < 4 else 20.4 + k / 100.0,
        ]
        for k in range(12)
    ]
    series = {
        "schema": "ovenbird.house-series/1",
        "model": "house-20261101",
        "step_s": 900,
        "columns": ["ts", "room_measured", "room_predicted_24h"],
        "rows": rows,
    }
    (models / "series-20261101.json").write_text(json.dumps(series), encoding="utf-8")
    (models / "insight-20261101.json").write_text(json.dumps(INSIGHT), encoding="utf-8")
    current = {
        "model": "house-20261101",
        "house": "house-20261101.json",
        "insight": "insight-20261101.json",
        "promoted_at": "2026-11-01T18:00:00+00:00",
    }
    (models / "current.json").write_text(json.dumps(current), encoding="utf-8")
    runs = [
        {
            "model": "house-20261101",
            "data_to": "2026-11-01T18:00:00+00:00",
            "promoted": True,
            "ua_w_per_k": 145.0,
            "ua_interval_90": [136.0, 156.0],
            "credible": True,
            "challenger_room_rmse_k": 0.4,
        }
    ]
    (models / "index.json").write_text(json.dumps({"runs": runs}), encoding="utf-8")
    status = {"outcome": "promoted"}
    (models / "status.json").write_text(json.dumps(status), encoding="utf-8")


@dataclass
class Rig:
    """The service assembled on a fake clock, with history written."""

    app: FastAPI
    clock: FakeClock
    settings: Settings
    root: Path


@pytest.fixture
def rig(make_settings: Callable[..., Settings], tmp_path: Path) -> Rig:
    settings = make_settings(
        control_mode="auto",
        allow_commands=True,
        mqtt_host="mosquitto",
        command_brokers=("mosquitto",),
        http_host="0.0.0.0",
        admin_password=PASSWORD,
        notify_ntfy_url="https://ntfy.example.test",
        notify_ntfy_topic="topic-secret-x",
        mqtt_inputs=[{"topic": "sim/room", "signal": ROOM, "unit": "°C"}],
        control_room_signal=ROOM,
        control_stove_enabled=True,
        envelope_rule_installed=True,
        weather_enabled=True,
        weather_latitude=52.0912,
        weather_longitude=5.1178,
        weather_location_source="manual",
        house_floor_area_m2=130.0,
    )
    clock = FakeClock(NOW - 600)
    runtime = Runtime(clock=clock)
    runtime.mqtt_connected = True
    manager = ConfigManager.open(settings, clock, locked={})
    facts = Facts(manager.store)
    loop, _ = build_control(
        manager.settings,
        runtime,
        None,
        sleep=no_sleep,
        hold=manager.hold,
        config_version=manager.version,
        facts=facts,
    )
    manager.attach(loop, loop.alarms)
    ingest = MqttIngest(manager.settings, runtime)
    rows: list[DecisionRow] = []
    for _ in range(10):
        for message in pump_messages(Heat_Delta="5", Pump_Flowrate_Mode="1"):
            ingest.ingest(message)
        rows.append(loop.tick())
        clock.advance(60)
    write_history(manager.settings.history_path, rows)
    pumps = PumpSettings(runtime, loop.guard, loop.adapter, manager, manager.settings.history_path)
    weather = WeatherService(
        manager.settings,
        clock,
        OpenMeteoProvider(lambda _: WEATHER.read_bytes()),
        history_path=manager.settings.history_path,
    )
    notifier = Notifier(
        manager.settings,
        clock,
        facts,
        transport=lambda _request: 200,
        healthy=lambda: None,
        monotonic=lambda: 1000.0,
    )
    starts = record_start(facts, clock())
    supervision = Supervision(
        runtime, lambda: manager.settings, loop, manager, notifier, facts, clock(), starts
    )
    app = create_app(
        runtime,
        manager.settings,
        control=loop,
        config=manager,
        pumps=pumps,
        weather=weather,
        signals=lambda: {
            "ha": {"enabled": False, "link_up": False},
            "room": [],
            "liveness": [],
            "crosscheck": [],
        },
        supervision=supervision,
    )
    return Rig(app, clock, manager.settings, tmp_path)


def portable(raw: bytes, root: Path) -> bytes:
    """Return a body with the temporary directory and the random ticket replaced."""
    text = raw.replace(str(root).encode(), b"<tmp>")
    return TICKET.sub(b'"ticket":"<ticket>"', text)


def recorded(rig: Rig) -> Iterator[tuple[Case, int, bytes]]:
    """Run every case in order on one client; yield its status and portable body."""
    with TestClient(rig.app, client=("10.0.0.2", 50000)) as client:
        for case in CASES:
            if case.name == "insight_house_ready":
                write_models(rig.settings.data_dir)
            response = client.request(
                case.method,
                f"/api/v1{case.path}",
                params=case.params,
                json=case.body if case.method != "GET" else None,
                headers=admin(),
            )
            rig.clock.advance(1)
            yield case, response.status_code, portable(response.content, rig.root)


def test_every_route_answers_its_recorded_bytes(rig: Rig) -> None:
    update = os.environ.get(UPDATE_ENV) == "1"
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    statuses: dict[str, int] = {}
    for case, status, body in recorded(rig):
        statuses[case.name] = status
        path = SNAPSHOTS / f"{case.name}.json"
        if update or not path.exists():
            path.write_bytes(body + b"\n")
        expected = path.read_bytes()
        if case.name in UNORDERED:
            assert json.loads(body) == json.loads(expected), case.name
        else:
            assert body + b"\n" == expected, f"{case.name} changed; set {UPDATE_ENV}=1 if intended"
    index = SNAPSHOTS / "statuses.json"
    text = json.dumps(statuses, indent=2) + "\n"
    if update or not index.exists():
        index.write_text(text, encoding="utf-8")
    assert index.read_text(encoding="utf-8") == text


def unknown_keys(value: Any, path: str = "$") -> list[str]:
    """Return the paths of the keys no model declares."""
    found: list[str] = []
    if isinstance(value, BaseModel):
        found += [f"{path}.{key}" for key in value.__pydantic_extra__ or {}]
        for name in type(value).model_fields:
            found += unknown_keys(getattr(value, name), f"{path}.{name}")
    elif isinstance(value, list | tuple):
        for item in value:
            found += unknown_keys(item, f"{path}[]")
    elif isinstance(value, dict):
        for key, item in value.items():
            found += unknown_keys(item, f"{path}.{key}")
    return found


def model_of(app: FastAPI, method: str, path: str) -> Any:
    """Return the response model of the route serving ``method path``."""
    for verb, template, model in routes(app):
        pattern = "^" + PARAM.sub("[^/]+", template) + "$"
        if verb == method and re.match(pattern, path):
            return model
    raise LookupError(f"no route for {method} {path}")


def test_every_recorded_body_fits_its_response_model(rig: Rig) -> None:
    statuses = json.loads((SNAPSHOTS / "statuses.json").read_text(encoding="utf-8"))
    for case in CASES:
        model = model_of(rig.app, case.method, f"/api/v1{case.path}")
        if statuses[case.name] >= 300 or model is None:
            continue
        body = json.loads((SNAPSHOTS / f"{case.name}.json").read_bytes())
        value = TypeAdapter[Any](model).validate_python(body)
        assert unknown_keys(value) == [], case.name

from __future__ import annotations

import asyncio
import base64
import csv
import io
import json
import zipfile
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ovenbird.api.app import create_app
from ovenbird.api.export import cell, csv_text
from ovenbird.config import Settings
from ovenbird.configstore import Actor, ConfigManager
from ovenbird.control.alarms import AlarmBoard, AlarmCode
from ovenbird.history import HistoryDatabase, Sample, SampleKind, open_history
from ovenbird.history.journal import AlarmRow, CommandRow, DecisionRow, write_journal
from ovenbird.mqtt import MqttIngest
from ovenbird.notify.notifier import Notifier
from ovenbird.runtime import Runtime
from ovenbird.service import build_control
from ovenbird.system.about import record_start
from ovenbird.system.diagnostics import REDACTED, bundle, redact
from ovenbird.system.facts import Facts
from ovenbird.testing import FakeClock, pump_messages
from ovenbird.trial.checklist import shadow_seconds
from ovenbird.trial.divergence import divergence_payload, episodes, minutes
from ovenbird.trial.explained import annotate
from ovenbird.trial.release import PumpSnapshot
from ovenbird.trial.runs import find_runs, run_stats, runs_payload
from ovenbird.trial.summary import setpoint_changes
from ovenbird.trial.supervision import Supervision

ADMIN = "pw-123"
SETPOINT = "main/Z1_Water_Target_Temp"
COMPRESSOR = "main/Compressor_Freq"
ROOM = "room_temperature"
T0 = datetime(2026, 11, 2, 0, 0, tzinfo=UTC).timestamp()
MQTT_ROOM = [{"topic": "sim/room", "signal": ROOM, "unit": "°C"}]


def basic(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def write_samples(
    path: Path, start: float, end: float, values: Callable[[float], dict[str, float]]
) -> None:
    database = HistoryDatabase(open_history(path))
    try:
        batch: list[Sample] = []
        ts = start
        while ts <= end:
            for signal, value in values(ts).items():
                batch.append(Sample(signal, None, SampleKind.NUMBER, ts, value, 330.0))
            ts += 60.0
        database.write_batch(batch)
    finally:
        database.close()


def decision(
    ts: float, setpoint: int | None, mode: str = "shadow", reason: str = "curve"
) -> DecisionRow:
    return DecisionRow(ts, "ovenbird", mode, "normal", reason, setpoint, "{}", "{}", "[]", 1)


def write_decisions(
    path: Path,
    rows: list[DecisionRow],
    commands: Sequence[CommandRow] = (),
    alarms: Sequence[AlarmRow] = (),
) -> None:
    conn = open_history(path)
    try:
        write_journal(conn, rows, commands, alarms)
    finally:
        conn.close()


@pytest.fixture
def history(tmp_path: Path) -> Path:
    path = tmp_path / "history.db"

    def pump(ts: float) -> dict[str, float]:
        minute = (ts - T0) / 60.0
        return {SETPOINT: 34.0 if 60 <= minute < 120 else 30.0}

    write_samples(path, T0, T0 + 180 * 60, pump)
    rows = [decision(T0 + 30 + 60 * m, 30) for m in range(150)]
    rows += [decision(T0 + 30 + 60 * m, 30) for m in range(165, 181)]
    write_decisions(path, rows)
    return path


def test_divergence_finds_the_episode_and_reports_the_gap(history: Path) -> None:
    rows = minutes(history, T0, T0 + 180 * 60)
    assert len(rows) == 180
    assert rows[70].ovenbird == 30
    assert rows[70].pump == 34.0
    assert rows[70].writer == "other"
    assert rows[155].ovenbird is None
    found = episodes(rows, 1.0)
    assert len(found) == 1
    assert found[0].to_json()["minutes"] == 60
    assert found[0].ended_by == "converged"
    body = divergence_payload(history, start=T0, end=T0 + 180 * 60, timezone="Europe/Amsterdam")
    summary = body["summary"]
    assert summary["episodes"] == 1
    assert summary["hours_over"] == 1.0
    assert summary["max_abs_k"] == 4.0
    assert summary["gap_minutes"] == 13
    assert body["step"] == 60
    assert body["episodes"][0]["reason"] == "curve"
    assert body["episodes"][0]["ovenbird_c"] == 30
    assert len(body["days"]) == 1
    assert body["days"][0]["date"] == "2026-11-02"
    with pytest.raises(ValueError, match="step"):
        divergence_payload(history, start=T0, end=T0 + 3600, step=7)


def test_divergence_names_ovenbird_as_writer_after_a_verified_command(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    write_samples(path, T0, T0 + 600, lambda _ts: {SETPOINT: 31.0})
    write_decisions(
        path,
        [decision(T0 + 60 * m, 31, mode="auto") for m in range(11)],
        [CommandRow(T0 - 30, "water_setpoint", 31, "verified", 1, None, None, "")],
    )
    rows = minutes(path, T0, T0 + 600)
    assert {row.writer for row in rows} == {"ovenbird"}
    assert all(row.diff == 0 for row in rows)


def test_runs_are_measured_and_censored_at_gaps() -> None:
    data: dict[int, float] = {}
    base = 1_000_020
    base -= base % 60
    pattern = [0] * 3 + [60] * 10 + [0] * 5 + [60] * 30 + [0] * 2 + [60] * 4
    for index, value in enumerate(pattern):
        data[base + 60 * index] = float(value)
    runs = find_runs(data, base, base + 60 * len(pattern))
    assert [(round(r.minutes), r.complete) for r in runs] == [(10, True), (30, True), (4, False)]
    assert runs[1].off_before_s == 300
    stats = run_stats(runs)
    assert stats["runs"] == 2
    assert stats["censored"] == 1
    assert stats["short_runs"] == 1
    assert stats["short_share"] == 0.5
    assert stats["median_min"] == 20.0
    assert stats["min_off_min"] == 5.0
    assert [b["runs"] for b in stats["histogram"]][:4] == [0, 1, 0, 1]


def test_runs_payload_reads_the_rollups(tmp_path: Path) -> None:
    path = tmp_path / "history.db"

    def compressor(ts: float) -> dict[str, float]:
        minute = int((ts - T0) / 60.0) % 60
        return {COMPRESSOR: 30.0 if 10 <= minute < 25 else 0.0}

    write_samples(path, T0, T0 + 5 * 3600, compressor)
    now = datetime.fromtimestamp(T0 + 5 * 3600 + 60, UTC)
    body = runs_payload(path, now=now, days=1, timezone="UTC")
    assert body["total"]["runs"] == 5
    assert body["total"]["median_min"] == 15.0
    assert body["total"]["short_share"] == 1.0
    assert body["total"]["min_off_min"] == 45.0


def test_shadow_time_counts_ticks_and_skips_gaps(history: Path) -> None:
    seconds, first, last = shadow_seconds(history, 60.0)
    assert seconds == pytest.approx((149 + 15) * 60.0 + 120.0)
    assert first == T0 + 90
    assert last == T0 + 30 + 180 * 60
    assert setpoint_changes(history, T0, T0 + 180 * 60) == 2
    assert shadow_seconds(history.parent / "missing.db", 60.0) == (0.0, None, None)


def test_csv_cells_cannot_become_formulas() -> None:
    assert cell("=1+1") == "'=1+1"
    assert cell("-x") == "'-x"
    assert cell(-2.5) == -2.5
    assert cell(None) == ""
    assert cell({"b": 1, "a": [1]}) == '{"a":[1],"b":1}'
    text = csv_text(("a", "b"), [{"a": "@SUM", "b": True}])
    assert list(csv.reader(io.StringIO(text))) == [["a", "b"], ["'@SUM", "true"]]


def test_redaction_reaches_every_string() -> None:
    body = {"a": ["x tk_secret y", {"b": "fine"}], "c": 1}
    assert redact(body, ["tk_secret"]) == {"a": [REDACTED, {"b": "fine"}], "c": 1}


@pytest.fixture
def service(make_settings: Callable[..., Settings]) -> dict[str, Any]:
    settings = make_settings(
        http_host="0.0.0.0",
        admin_password=ADMIN,
        mqtt_password="broker-secret-pw",
        notify_ntfy_url="https://ntfy.example.test",
        notify_ntfy_topic="topic-secret-x",
        mqtt_inputs=MQTT_ROOM,
        control_room_signal=ROOM,
        envelope_rule_installed=True,
    )
    clock = FakeClock(T0 + 200 * 60)
    runtime = Runtime(clock=clock)
    manager = ConfigManager.open(settings, clock)
    facts = Facts(manager.store)
    loop, _ = build_control(manager.settings, runtime, None, sleep=_no_sleep, facts=facts)
    starts = record_start(facts, clock())
    supervision = Supervision(
        runtime, lambda: manager.settings, loop, manager, None, facts, clock(), starts
    )
    app = create_app(
        runtime, manager.settings, control=loop, config=manager, supervision=supervision
    )
    return {"settings": manager.settings, "clock": clock, "app": app, "supervision": supervision}


async def _no_sleep(_: float) -> None:
    return None


def test_trial_status_lists_every_item_with_evidence(service: dict[str, Any]) -> None:
    settings: Settings = service["settings"]
    path = settings.history_path
    write_samples(path, T0, T0 + 180 * 60, lambda _ts: {SETPOINT: 30.0, ROOM: 21.0})
    write_decisions(path, [decision(T0 + 60 * m, 30) for m in range(181)])
    with TestClient(service["app"]) as client:
        body = client.get("/api/v1/trial/status", headers=basic("admin", ADMIN)).json()
    items = {entry["id"]: entry for entry in body["checklist"]}
    assert list(items) == [
        "shadow_days",
        "divergence",
        "envelope_rule",
        "notifications",
        "release_plan",
        "alarms",
        "room",
        "pump_snapshot",
        "envelope_proof",
        "rollback_rehearsal",
    ]
    assert [items[i]["phase"] for i in ("pump_snapshot", "envelope_proof")] == ["go_live", "trial"]
    assert items["shadow_days"]["status"] == "warn"
    assert items["shadow_days"]["evidence"]["days"] == pytest.approx(0.12, abs=0.01)
    assert items["divergence"]["status"] == "warn"
    assert items["envelope_rule"]["status"] == "ok"
    assert items["envelope_proof"]["status"] == "warn"
    assert items["notifications"]["status"] == "fail"
    assert items["release_plan"]["status"] == "fail"
    assert items["rollback_rehearsal"]["status"] == "fail"
    assert items["room"]["status"] == "fail"
    assert body["ready"] is False
    assert body["ready_for_cutover"] is False
    assert "shadow_days" in [entry["id"] for entry in body["not_ready"]]
    assert body["groups"]["trial"]["ids"] == ["envelope_proof", "rollback_rehearsal"]
    assert body["mode"] == "shadow"
    summary = body["summary"]
    assert summary["source"] == "default"
    assert summary["state"] == "no_trial"
    assert summary["met"] is False
    assert summary["trial"]["room_mean_c"] == 21.0
    assert [c["id"] for c in summary["criteria"]] == [
        "room_mean",
        "room_min",
        "short_runs",
        "pump_errors",
        "writes_per_day",
        "setpoint_changes_per_day",
    ]


def test_trial_status_accepts_explicit_periods(service: dict[str, Any]) -> None:
    settings: Settings = service["settings"]
    path = settings.history_path

    def room(ts: float) -> dict[str, float]:
        return {ROOM: 20.0 if ts < T0 + 90 * 60 else 21.0}

    write_samples(path, T0, T0 + 180 * 60, room)
    query = {
        "baseline_from": "2026-11-02T00:00:00Z",
        "baseline_to": "2026-11-02T01:30:00Z",
        "from": "2026-11-02T01:30:00Z",
        "to": "2026-11-02T03:00:00Z",
    }
    with TestClient(service["app"]) as client:
        body = client.get("/api/v1/trial/status", params=query, headers=basic("admin", ADMIN))
    summary = body.json()["summary"]
    assert summary["source"] == "query"
    room_mean = summary["criteria"][0]
    assert room_mean["trial"] == 21.0
    assert room_mean["baseline"] == 20.0
    assert room_mean["status"] == "fail"
    assert summary["met"] is False


def test_about_reports_the_installation(service: dict[str, Any]) -> None:
    clock: FakeClock = service["clock"]
    clock.advance(90)
    with TestClient(service["app"]) as client:
        body = client.get("/api/v1/system/about", headers=basic("admin", ADMIN)).json()
    assert body["uptime_s"] == 90.0
    assert body["service_starts"] == 1
    assert body["setpoint_register"] == "setcurves_target_high"
    assert body["control_interval_s"] == 60.0
    assert body["connections"]["mqtt"]["connected"] is False
    assert body["safety_net"]["envelope_rule"]["state"] == "declared"
    assert body["control"]["mode"] == "shadow"


def test_diagnostics_never_contain_secrets(service: dict[str, Any]) -> None:
    settings: Settings = service["settings"]
    write_decisions(
        settings.history_path,
        [decision(T0, 30, reason="broker-secret-pw leaked")],
        alarms=[AlarmRow(T0, "low_flow", "critical", "raised", "topic-secret-x", "{}")],
    )
    with TestClient(service["app"]) as client:
        reader = client.get("/api/v1/diagnostics", headers=basic("viewer", "x"))
        assert reader.status_code == 401
        response = client.get("/api/v1/diagnostics", headers=basic("admin", ADMIN))
        assert response.status_code == 200
        text = response.text
        body = response.json()
        archive = client.get(
            "/api/v1/diagnostics", params={"format": "zip"}, headers=basic("admin", ADMIN)
        )
    for secret in ("broker-secret-pw", "topic-secret-x", ADMIN):
        assert secret not in text
    assert body["config"]["effective"]["mqtt_password"] == "set"
    assert body["config"]["effective"]["notify_ntfy_topic"] == "set"
    assert body["decisions"][0]["reason"] == REDACTED
    assert body["alarms"]["events"][0]["message"] == REDACTED
    assert "audit" not in body
    with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle_zip:
        names = bundle_zip.namelist()
        about = json.loads(bundle_zip.read("about.json"))
    assert "config.json" in names
    assert about["version"] == body["version"]
    supervision: Supervision = service["supervision"]
    assert bundle(supervision, 5)["generated_at"] == body["generated_at"]


def test_exports_are_csv(service: dict[str, Any]) -> None:
    settings: Settings = service["settings"]
    write_decisions(settings.history_path, [decision(T0 + 190 * 60, 30, reason="=cmd")])
    write_samples(settings.history_path, T0 + 190 * 60, T0 + 192 * 60, lambda _ts: {SETPOINT: 30.0})
    auth = basic("admin", ADMIN)
    with TestClient(service["app"]) as client:
        decisions = client.get("/api/v1/decisions", params={"format": "csv"}, headers=auth)
        assert decisions.headers["content-type"].startswith("text/csv")
        assert "attachment" in decisions.headers["content-disposition"]
        rows = list(csv.DictReader(io.StringIO(decisions.text)))
        assert rows[0]["reason"] == "'=cmd"
        history = client.get(
            "/api/v1/history",
            params={"signals": SETPOINT, "format": "csv", "step": 60},
            headers=auth,
        )
        assert history.status_code == 200
        assert history.text.splitlines()[0] == "signal,unit,at,value"
        assert len(history.text.splitlines()) > 1
        for name in ("commands", "alarms", "audit"):
            response = client.get(f"/api/v1/{name}", params={"format": "csv"}, headers=auth)
            assert response.status_code == 200, name
            assert response.headers["content-type"].startswith("text/csv")
        bad = client.get("/api/v1/decisions", params={"format": "xml"}, headers=auth)
        assert bad.status_code == 422


GOOD_PERIOD: dict[str, Any] = {
    "from": "x",
    "to": "y",
    "days": 7.0,
    "room_mean_c": 21.0,
    "room_min_c": 20.5,
    "room_hours": 168.0,
    "outside_mean_c": 4.0,
    "runs": {"short_share": 0.1},
    "pump_errors": 0,
    "writes": 70,
    "writes_per_day": 10.0,
    "setpoint_changes_per_day": 5.0,
}


def _snapshot(taken: float, origin: str = "go_live", released: float | None = None) -> PumpSnapshot:
    return PumpSnapshot(
        datetime.fromtimestamp(taken, UTC),
        "shadow",
        "setcurves_target_high",
        {"water_setpoint": 30, "max_pump_duty": 159, "quiet_mode": 0},
        {},
        released_at=None if released is None else datetime.fromtimestamp(released, UTC),
        origin=origin,
    )


def test_the_summary_is_met_only_for_a_complete_trial(
    service: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    supervision: Supervision = service["supervision"]
    monkeypatch.setattr(supervision, "_period", lambda _settings, _span: dict(GOOD_PERIOD))
    loop = supervision.control
    assert loop is not None
    assert loop.release is not None
    now = service["clock"]().wall.timestamp()
    day = 86_400.0
    none = supervision.summary()
    assert (none["state"], none["criteria_met"], none["met"]) == ("no_trial", True, False)
    loop.release.snapshot = _snapshot(now - day, origin="manual")
    assert supervision.summary()["state"] == "no_trial"
    loop.release.snapshot = _snapshot(now - 2 * day)
    running = supervision.summary()
    assert running["source"] == "go_live"
    assert running["state"] == "running"
    assert running["days"] == pytest.approx(2.0)
    assert running["min_days"] == 7.0
    assert running["met"] is False
    loop.release.snapshot = _snapshot(now - 3 * day, released=now - 2 * day)
    assert supervision.summary()["state"] == "ended_early"
    loop.release.snapshot = _snapshot(now - 8 * day)
    complete = supervision.summary()
    assert complete["state"] == "complete"
    assert complete["met"] is True
    outside = supervision.summary(trial=(now - 20 * day, now - 10 * day))
    assert outside["state"] == "not_a_trial"
    assert outside["met"] is False


def test_long_episodes_marked_as_explained_pass_the_checklist(service: dict[str, Any]) -> None:
    supervision: Supervision = service["supervision"]
    episode = {"start": "2026-11-02T01:00:00Z", "end": "2026-11-02T03:30:00Z", "minutes": 150}
    body: dict[str, Any] = {
        "summary": {
            "coverage": 0.95,
            "compared_minutes": 19_000,
            "mean_abs_k": 0.4,
            "max_abs_k": 3.0,
            "hours_over": 2.5,
            "episodes": 1,
        },
        "episodes": [dict(episode)],
    }
    assert supervision._divergence(annotate(body, supervision.explanations()))["status"] == "warn"
    actor = Actor("admin from 10.0.0.2", "10.0.0.2")
    stored = supervision.explain(
        actor, datetime(2026, 11, 2, 1, 0, tzinfo=UTC), "Node-RED boost for a party"
    )
    assert stored["explained"]["by"] == "admin"
    body["episodes"] = [dict(episode)]
    item = supervision._divergence(annotate(body, supervision.explanations()))
    assert item["status"] == "ok"
    assert item["evidence"]["explained_episodes"] == 1
    assert body["episodes"][0]["explained"]["note"] == "Node-RED boost for a party"
    supervision.explain(actor, datetime(2026, 11, 2, 1, 0, tzinfo=UTC), None)
    body["episodes"] = [dict(episode)]
    assert supervision._divergence(annotate(body, supervision.explanations()))["status"] == "warn"


def test_explaining_an_episode_through_the_api(service: dict[str, Any]) -> None:
    settings: Settings = service["settings"]
    path = settings.history_path

    def pump(ts: float) -> dict[str, float]:
        return {SETPOINT: 34.0 if T0 + 3600 <= ts < T0 + 7200 else 30.0}

    write_samples(path, T0, T0 + 180 * 60, pump)
    write_decisions(path, [decision(T0 + 30 + 60 * m, 30) for m in range(181)])
    admin = {**basic("admin", ADMIN), "X-Ovenbird-Request": "1"}
    query = {"from": "2026-11-02T00:00:00Z", "to": "2026-11-02T03:00:00Z"}
    with TestClient(service["app"]) as client:
        before = client.get("/api/v1/shadow/divergence", params=query, headers=admin).json()
        start = before["episodes"][0]["start"]
        assert before["episodes"][0]["explained"] is None
        missing = client.post(
            "/api/v1/shadow/episodes/explain", json={"start": start}, headers=admin
        )
        assert missing.status_code == 400
        marked = client.post(
            "/api/v1/shadow/episodes/explain",
            json={"start": start, "note": "pump service visit"},
            headers=admin,
        )
        assert marked.status_code == 200
        after = client.get("/api/v1/shadow/divergence", params=query, headers=admin).json()
        assert after["episodes"][0]["explained"]["note"] == "pump service visit"
        reader = client.post(
            "/api/v1/shadow/episodes/explain",
            json={"start": start, "note": "x"},
            headers={"X-Ovenbird-Request": "1"},
        )
        assert reader.status_code in {401, 403}
        removed = client.post(
            "/api/v1/shadow/episodes/explain",
            json={"start": start, "explained": False},
            headers=admin,
        )
        assert removed.json() == {"explained": None}
        service["clock"].advance(1)
        audit = client.get("/api/v1/audit", headers=basic("admin", ADMIN)).json()["events"]
        assert [e["action"] for e in audit].count("divergence_explain") == 2


class UnhealthyWriter:
    def healthy(self) -> bool:
        return False

    def starting(self) -> bool:
        return False


def test_the_deadman_is_held_back_while_history_is_not_written(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings()
    clock = FakeClock()
    runtime = Runtime(clock=clock)
    runtime.mqtt_connected = True
    ingest = MqttIngest(settings, runtime)
    for message in pump_messages():
        ingest.ingest(message)
    loop, _ = build_control(settings, runtime, None, sleep=_no_sleep)
    loop.tick()
    supervision = Supervision(runtime, lambda: settings, loop, None, None, Facts(), clock())
    assert supervision.healthy_reason() is None
    runtime.history = UnhealthyWriter()  # type: ignore[assignment]
    assert supervision.healthy_reason() == "history is not being written"


def test_the_notifications_item_follows_the_delivery_health(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(
        notify_ntfy_url="https://ntfy.example.test",
        notify_ntfy_topic="topic-secret-x",
        notify_deadman_url="https://hc.example.test/ping/abcd",
    )
    clock = FakeClock()
    runtime = Runtime(clock=clock)
    facts = Facts()
    errors: list[Exception] = []

    def transport(_request: Any) -> int:
        if errors:
            raise errors[0]
        return 200

    notifier = Notifier(settings, clock, facts, transport=transport, healthy=lambda: None)
    supervision = Supervision(runtime, lambda: settings, None, None, notifier, facts, clock())
    actor = Actor("admin from 10.0.0.2", "10.0.0.2")
    assert supervision._notifications()["status"] == "warn"
    asyncio.run(notifier.send_test(actor))
    asyncio.run(notifier.ping_once())
    item = supervision._notifications()
    assert item["status"] == "ok"
    assert item["evidence"]["health"] == notifier.status()["health"]
    errors.append(OSError("down"))
    board = AlarmBoard()
    notifier.attach(board)
    board.raise_alarm(AlarmCode.PUMP_ERROR, "H23", clock())
    asyncio.run(notifier.flush())
    failing = supervision._notifications()
    assert failing["status"] == "fail"
    assert "alerts do not arrive" in failing["message"]
    assert notifier.status()["health"]["state"] == "failing"


def test_diagnostics_leave_out_addresses_names_and_the_location(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(
        http_host="0.0.0.0",
        admin_password=ADMIN,
        mqtt_host="192.168.1.5",
        mqtt_username="alex",
        weather_latitude=52.37,
        weather_longitude=4.89,
        ha_url="http://homeassistant.local:8123",
        ha_token="ha-token-secret",
        ha_entities=("sensor.room",),
    )
    clock = FakeClock(T0 + 200 * 60)
    runtime = Runtime(clock=clock)
    manager = ConfigManager.open(settings, clock)
    facts = Facts(manager.store)
    loop, _ = build_control(manager.settings, runtime, None, sleep=_no_sleep, facts=facts)
    write_decisions(
        settings.history_path,
        [decision(T0, 30)],
        commands=[
            CommandRow(
                T0,
                "water_setpoint",
                30,
                "verified",
                1,
                None,
                None,
                "release: admin from 192.168.1.20: restore water_setpoint 34 → 30",
            )
        ],
    )
    facts.set(
        "notify_test", {"at": "x", "ok": True, "error": None, "by": "admin from 192.168.1.20"}
    )
    supervision = Supervision(
        runtime, lambda: manager.settings, loop, manager, None, facts, clock()
    )
    try:
        body = bundle(supervision, 10)
    finally:
        manager.close()
    text = json.dumps(body)
    for private in (
        "192.168.1.20",
        "192.168.1.5",
        "52.37",
        "4.89",
        "alex",
        "homeassistant.local",
    ):
        assert private not in text, private
    effective = body["config"]["effective"]
    assert effective["weather_latitude"] == "[removed]"
    assert effective["mqtt_host"] == "[removed]"
    assert effective["ha_url"] == "[removed]"
    assert effective["heishamon_base"] == "panasonic_heat_pump"
    assert body["commands"][0]["detail"] == "release: [removed]: restore water_setpoint 34 → 30"

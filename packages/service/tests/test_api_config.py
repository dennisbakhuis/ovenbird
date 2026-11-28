from __future__ import annotations

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ovenbird.api.app import create_app
from ovenbird.config import Settings
from ovenbird.configstore import ConfigManager, provided_sources
from ovenbird.control import ControlLoop
from ovenbird.history.journal import AlarmRow, DecisionRow, write_journal
from ovenbird.history.schema import open_history
from ovenbird.mqtt import MqttIngest
from ovenbird.mqttsetup import MqttSetup
from ovenbird.replay.stepping import parse_rows
from ovenbird.runtime import Runtime
from ovenbird.service import build_control
from ovenbird.testing import FakeClock, FakeMqttClient
from ovenbird_core import Instant
from ovenbird_core.control import DecisionRecord, LadderLevel, Mode, ReasonCode

TOKEN = "operate-token-" + "x" * 24
PASSWORD = "pw-123"
PUBLISH: dict[str, Any] = {
    "control_mode": "auto",
    "allow_commands": True,
    "mqtt_host": "mosquitto",
    "command_brokers": ("mosquitto",),
}
MARK = {"X-Ovenbird-Request": "1"}
INGRESS = ("172.30.32.2", 50000)
ALL_TIME = {"from": "2000-01-01T00:00:00Z", "to": "2100-01-01T00:00:00Z"}


def basic(user: str = "admin", password: str = PASSWORD) -> dict[str, str]:
    """Return HTTP Basic authorization headers for the given credentials."""
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


BEARER = {"Authorization": f"Bearer {TOKEN}"}


async def no_sleep(_: float) -> None:
    """Replace asyncio sleep so the control loop never waits in tests."""
    return


@dataclass
class Stack:
    """A wired config manager, runtime, control loop and clock for API tests."""

    manager: ConfigManager
    runtime: Runtime
    loop: ControlLoop
    clock: FakeClock
    settings: Settings

    def client(self, **kwargs: Any) -> TestClient:
        """Build a test client for an app created over this stack with a fake broker."""
        ingest = MqttIngest(self.manager.settings, self.runtime, connect=FakeMqttClient)
        mqtt = MqttSetup(self.manager, ingest, self.runtime, lambda: False, check=no_check)
        app = create_app(
            self.runtime, self.manager.settings, control=self.loop, config=self.manager, mqtt=mqtt
        )
        return TestClient(app, **kwargs)


async def no_check(settings: Settings) -> dict[str, Any]:
    """Stand in for the broker connection test and report an unreachable broker."""
    return {
        "ok": False,
        "host": settings.mqtt_host,
        "port": settings.mqtt_port,
        "base": settings.heishamon_base,
        "connected": False,
        "heishamon": False,
        "topic": None,
        "latency_ms": None,
        "error": "the broker is not reachable",
        "error_code": "unreachable",
    }


def stack(settings: Settings, clock: FakeClock | None = None, *, from_env: bool = False) -> Stack:
    """Build a ``Stack`` from settings, optionally honouring env-provided locks."""
    moment = clock or FakeClock()
    manager = ConfigManager.open(settings, moment, locked=provided_sources() if from_env else {})
    runtime = Runtime(clock=moment)
    loop, _ = build_control(
        manager.settings,
        runtime,
        None,
        sleep=no_sleep,
        hold=manager.hold,
        config_version=manager.version,
    )
    manager.attach(loop, loop.alarms)
    return Stack(manager, runtime, loop, moment, settings)


@pytest.fixture
def open_settings(make_settings: Callable[..., Settings]) -> Settings:
    """Settings with an operate token and no admin password (open mode)."""
    return make_settings(**PUBLISH, operate_token=TOKEN)


@pytest.fixture
def secured(make_settings: Callable[..., Settings]) -> Settings:
    """Settings on a non-loopback host with an operate token and admin password."""
    return make_settings(
        **PUBLISH, operate_token=TOKEN, http_host="0.0.0.0", admin_password=PASSWORD
    )


@pytest.fixture
def ingress(make_settings: Callable[..., Settings]) -> Settings:
    """Settings for Home Assistant ingress mode."""
    return make_settings(**PUBLISH, ingress=True)


def body_for(path: str) -> dict[str, Any]:
    """Return a minimal valid or invalid request body for the given endpoint path."""
    match path:
        case "/api/v1/config/validate":
            return {"changes": {"control_comfort_c": 21.4}}
        case "/api/v1/config":
            return {"base_version": 0, "changes": {"control_comfort_c": 21.5}}
        case "/api/v1/config/rollback":
            return {"version": 1, "base_version": 0}
        case "/api/v1/control/pause":
            return {"reason": "matrix"}
        case "/api/v1/control/stove":
            return {"on": False}
        case "/api/v1/config/ha/test":
            return {"signals": "x"}
        case "/api/v1/config/mqtt/test" | "/api/v1/config/mqtt":
            return {"port": "x"}
    return {}


ENDPOINTS: list[tuple[str, str, str]] = [
    ("GET", "/api/v1/config/schema", "read"),
    ("GET", "/api/v1/config", "read"),
    ("GET", "/api/v1/config/versions", "read"),
    ("GET", "/api/v1/decisions/series", "read"),
    ("POST", "/api/v1/config/validate", "operate"),
    ("POST", "/api/v1/control/pause", "operate"),
    ("POST", "/api/v1/control/stove", "operate"),
    ("PUT", "/api/v1/config", "admin"),
    ("POST", "/api/v1/config/rollback", "admin"),
    ("GET", "/api/v1/config/export", "admin"),
    ("POST", "/api/v1/config/reset-ack", "admin"),
    ("POST", "/api/v1/control/resume", "admin"),
    ("POST", "/api/v1/control/release-hold", "admin"),
    ("POST", "/api/v1/config/ha/test", "admin"),
    ("GET", "/api/v1/config/mqtt", "read"),
    ("POST", "/api/v1/config/mqtt/test", "admin"),
    ("PUT", "/api/v1/config/mqtt", "admin"),
    ("GET", "/api/v1/audit", "admin"),
    ("GET", "/api/v1/history/signals", "read"),
    ("GET", "/api/v1/history/storage", "read"),
    ("GET", "/api/v1/export/series", "read"),
    ("GET", "/api/v1/export/journal/decisions", "read"),
    ("GET", "/api/v1/export/archive", "admin"),
    ("POST", "/api/v1/history/compact", "admin"),
]
RANK = {"read": 0, "operate": 1, "admin": 2}


def call(client: TestClient, method: str, path: str, headers: dict[str, str]) -> int:
    """Send a request and return only its HTTP status code."""
    if method == "GET":
        return client.get(path, headers=headers).status_code
    return client.request(
        method, path, json=body_for(path), headers={**headers, **MARK}
    ).status_code


@pytest.mark.parametrize(("method", "path", "needed"), ENDPOINTS)
@pytest.mark.parametrize(
    ("mode", "credentials", "role"),
    [
        ("open", {}, "read"),
        ("open", BEARER, "operate"),
        ("secured", BEARER, "operate"),
        ("secured", basic(), "admin"),
        ("ingress", {}, "admin"),
    ],
)
def test_role_matrix(
    request: pytest.FixtureRequest,
    mode: str,
    credentials: dict[str, str],
    role: str,
    method: str,
    path: str,
    needed: str,
) -> None:
    """Each endpoint accepts roles at or above its rank and refuses lower ones with 403."""
    settings = request.getfixturevalue({"open": "open_settings"}.get(mode, mode))
    rig = stack(settings)
    kwargs = {"client": INGRESS} if mode == "ingress" else {}
    with rig.client(**kwargs) as client:
        status = call(client, method, path, credentials)
    if RANK[role] >= RANK[needed]:
        assert status not in {401, 403}, (status, role, path)
    else:
        assert status == 403, (status, role, path)


@pytest.mark.parametrize(("method", "path", "needed"), ENDPOINTS)
def test_without_credentials_everything_but_health_is_refused(
    secured: Settings, method: str, path: str, needed: str
) -> None:
    """Missing or wrong credentials give 401 everywhere except on the health endpoint."""
    with stack(secured).client() as client:
        assert call(client, method, path, {}) == 401
        assert call(client, method, path, basic(password="nope")) == 401
        assert call(client, method, path, {"Authorization": "Bearer wrong-token"}) == 401
        assert client.get("/api/v1/health").status_code == 200
    del needed


def test_wrong_bearer_is_refused_in_open_mode(open_settings: Settings) -> None:
    """A wrong bearer token is rejected with 401 even when no password is set."""
    with stack(open_settings).client() as client:
        response = client.get("/api/v1/config", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


@pytest.mark.parametrize("source", ["secured", "ingress"])
@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"Content-Type": "application/json"}, 403),
        ({**MARK, "Content-Type": "application/x-www-form-urlencoded"}, 415),
        ({**MARK, "Content-Type": "text/plain"}, 415),
        ({**MARK, "Content-Type": "application/json", "Origin": "https://evil.example"}, 403),
        ({**MARK, "Content-Type": "application/json", "Sec-Fetch-Site": "cross-site"}, 403),
        ({**MARK, "Content-Type": "application/json", "Sec-Fetch-Site": "same-site"}, 403),
        ({**MARK, "Content-Type": "application/json", "Content-Length": "70000"}, 413),
    ],
)
def test_request_rules(
    request: pytest.FixtureRequest, source: str, headers: dict[str, str], status: int
) -> None:
    """Mutations with a bad marker, content type, origin, fetch site or size are refused."""
    settings = request.getfixturevalue(source)
    rig = stack(settings)
    auth = basic() if source == "secured" else {}
    kwargs = {"client": INGRESS} if source == "ingress" else {}
    content = json.dumps({"base_version": 0, "changes": {"control_comfort_c": 21.5}})
    with rig.client(**kwargs) as client:
        response = client.put("/api/v1/config", content=content, headers={**auth, **headers})
        assert response.status_code == status, response.text
        events = client.get("/api/v1/audit", params=ALL_TIME, headers=auth).json()["events"]
    assert rig.manager.version is None
    assert [e["action"] for e in events] == ["auth_refused"]
    assert events[0]["detail"]["status"] == status


def test_oversized_body_is_refused(secured: Settings) -> None:
    """A request body above the size limit is refused with 413."""
    rig = stack(secured)
    content = json.dumps({"base_version": 0, "changes": {"x": "y" * 70_000}})
    with rig.client() as client:
        response = client.put(
            "/api/v1/config",
            content=content,
            headers={**basic(), **MARK, "Content-Type": "application/json"},
        )
    assert response.status_code == 413


def test_ingress_own_origin_and_actor(ingress: Settings) -> None:
    """Under ingress the forwarded origin is accepted and the actor is the HA user."""
    rig = stack(ingress)
    headers = {
        **MARK,
        "Origin": "https://ha.example:8123",
        "X-Forwarded-Host": "ha.example:8123",
        "X-Forwarded-Proto": "https",
        "Sec-Fetch-Site": "same-origin",
        "X-Remote-User-Name": "alex",
    }
    with rig.client(client=INGRESS) as client:
        response = client.put(
            "/api/v1/config",
            json={"base_version": 0, "changes": {"control_comfort_c": 21.5}},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        events = client.get("/api/v1/audit", params=ALL_TIME).json()["events"]
    assert events[-1]["actor"] == "alex (Home Assistant via ingress)"
    assert events[-1]["action"] == "config_apply"


def test_forwarded_host_is_ignored_outside_ingress(secured: Settings) -> None:
    """Forwarded host headers do not make a foreign origin acceptable outside ingress."""
    rig = stack(secured)
    headers = {
        **basic(),
        **MARK,
        "Origin": "https://ha.example:8123",
        "X-Forwarded-Host": "ha.example:8123",
        "X-Forwarded-Proto": "https",
    }
    with rig.client() as client:
        response = client.post("/api/v1/config/validate", json={"changes": {}}, headers=headers)
    assert response.status_code == 403


def test_apply_conflicts_locks_rate_and_audit(
    monkeypatch: pytest.MonkeyPatch, secured: Settings
) -> None:
    """Applying config handles conflicts, locks, rate limits, history, audit and export."""
    monkeypatch.setenv("OVENBIRD_CONTROL_DWELL_S", "1200")
    full = stack(secured, from_env=True)
    admin = {**basic(), **MARK}
    with full.client() as client:
        ok = client.put(
            "/api/v1/config",
            json={"base_version": 0, "changes": {"control_comfort_c": 21.5}, "comment": "warmer"},
            headers=admin,
        )
        assert ok.status_code == 200, ok.text
        body = ok.json()
        assert body["version"] == 1
        assert body["applies"] == "next_tick"
        assert body["config"]["fields"]["control_comfort_c"]["value"] == 21.5
        stale = client.put(
            "/api/v1/config",
            json={"base_version": 0, "changes": {"control_comfort_c": 21.4}},
            headers=admin,
        )
        assert stale.status_code == 409
        assert stale.json()["version"] == 1
        locked = client.put(
            "/api/v1/config",
            json={"base_version": 1, "changes": {"control_dwell_s": 900}},
            headers=admin,
        )
        assert locked.status_code == 422
        assert [e["code"] for e in locked.json()["errors"]] == ["locked"]
        rate = client.put(
            "/api/v1/config",
            json={"base_version": 1, "changes": {"control_comfort_c": 21.4}},
            headers=admin,
        )
        assert rate.status_code == 429
        bad = client.put("/api/v1/config", json={"changes": {}}, headers=admin)
        assert bad.status_code == 400
        versions = client.get("/api/v1/config/versions", headers=basic()).json()["versions"]
        assert versions[0]["comment"] == "warmer"
        assert versions[0]["changed"] == [{"field": "control_comfort_c", "from": None, "to": 21.5}]
        one = client.get("/api/v1/config/versions/1", headers=basic()).json()
        assert one["values"] == {"control_comfort_c": 21.5}
        assert client.get("/api/v1/config/versions/9", headers=basic()).status_code == 404
        audit = client.get("/api/v1/audit", params=ALL_TIME, headers=basic()).json()["events"]
        assert [e["action"] for e in audit] == ["config_apply"]
        assert audit[0]["detail"]["changed"][0]["field"] == "control_comfort_c"
        assert audit[0]["source_ip"] == "testclient"
        assert audit[0]["actor"] == "admin from testclient"
        export = client.get("/api/v1/config/export", headers=basic())
        assert export.status_code == 200
        assert "attachment" in export.headers["content-disposition"]
        text = export.text
        assert PASSWORD not in text
        assert TOKEN not in text
        assert export.json()["values"] == {"control_comfort_c": 21.5}


def test_validate_reports_errors_warnings_and_effective(open_settings: Settings) -> None:
    """Validation reports errors, warnings and effective values without applying."""
    with stack(open_settings).client() as client:
        response = client.post(
            "/api/v1/config/validate",
            json={
                "changes": {
                    "control_comfort_c": 24.5,
                    "control_curve": [[-10, 39], [5, 37], [15, 25]],
                    "control_dwell_s": None,
                }
            },
            headers={**BEARER, **MARK},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert [(e["field"], e["code"]) for e in body["errors"]] == [
        ("control_curve", "outside_envelope")
    ]
    ok = stack(open_settings)
    result = ok.manager.validate({"control_comfort_c": 24.5, "control_dwell_s": None})
    assert result.to_json()["effective"] == {"control_comfort_c": 24.5, "control_dwell_s": 900.0}
    assert [w.code for w in result.warnings] == ["above_soft_max"]


def test_get_config_shape(open_settings: Settings) -> None:
    """The config and schema responses expose the documented keys, locks and field metadata."""
    with stack(open_settings).client() as client:
        body = client.get("/api/v1/config").json()
        schema = client.get("/api/v1/config/schema")
    assert set(body) == {
        "version",
        "applied_version",
        "updated_at",
        "updated_by",
        "mode",
        "reset_pending",
        "fields",
        "hot_water",
    }
    assert body["hot_water"] == {"setting": "auto", "installed": None, "shown": True}
    assert body["mode"] == {
        "configured": "auto",
        "effective": "auto",
        "paused": False,
        "reset_pending": False,
    }
    assert body["fields"]["operate_token"]["value"] == "set"
    assert body["fields"]["allow_commands"]["locked"] is True
    assert schema.headers["cache-control"] == "no-cache"
    dwell = schema.json()["fields"]["control_dwell_s"]
    assert {
        k: dwell[k] for k in ("min", "max", "soft_min", "unit", "display", "tier", "group")
    } == {
        "min": 300.0,
        "max": 7200.0,
        "soft_min": 600.0,
        "unit": "s",
        "display": "min",
        "tier": "advanced",
        "group": "behaviour",
    }
    assert dwell["env"] == "OVENBIRD_CONTROL_DWELL_S"
    assert dwell["preset_default"] is True


def test_pause_resume_through_the_api(open_settings: Settings, secured: Settings) -> None:
    """Operate role can pause control, only admin can resume, and each step is audited."""
    rig = stack(secured)
    with rig.client() as client:
        paused = client.post(
            "/api/v1/control/pause", json={"reason": "checking"}, headers={**BEARER, **MARK}
        )
        assert paused.status_code == 200
        body = paused.json()
        assert body["mode"]["effective"] == "shadow"
        assert body["control"]["mode"] == "shadow"
        assert body["control"]["paused"] is True
        assert body["control"]["publishing"] is False
        assert "control is paused" in body["control"]["refusals"]
        refused = client.post("/api/v1/control/resume", json={}, headers={**BEARER, **MARK})
        assert refused.status_code == 403
        resumed = client.post("/api/v1/control/resume", json={}, headers={**basic(), **MARK})
        assert resumed.status_code == 200
        assert resumed.json()["mode"]["effective"] == "auto"
        actions = [
            e["action"]
            for e in client.get("/api/v1/audit", params=ALL_TIME, headers=basic()).json()["events"]
        ]
    assert actions == ["mode_pause", "auth_refused", "mode_resume"]


def test_pause_conflicts_without_an_auto_installation(
    make_settings: Callable[..., Settings],
) -> None:
    """Pausing an installation not configured for auto control is refused with 409."""
    rig = stack(make_settings(operate_token=TOKEN))
    with rig.client() as client:
        response = client.post("/api/v1/control/pause", json={}, headers={**BEARER, **MARK})
    assert response.status_code == 409
    assert response.json()["mode"]["configured"] == "shadow"


def test_security_headers(secured: Settings, ingress: Settings) -> None:
    """Responses carry hardening headers, with framing allowed only under ingress."""
    with stack(secured).client() as client:
        headers = client.get("/api/v1/health").headers
        refused = client.get("/api/v1/config").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["content-security-policy"].startswith("default-src 'self'; connect-src 'self'")
    assert "frame-ancestors 'self'" in headers["content-security-policy"]
    assert "content-security-policy" in refused
    assert "access-control-allow-origin" not in headers
    with stack(ingress).client(client=INGRESS) as client:
        framed = client.get("/api/v1/health").headers["content-security-policy"]
    assert "frame-ancestors" not in framed


def test_decision_series(open_settings: Settings) -> None:
    """The decision series endpoint returns raw and downsampled series and rejects bad steps."""
    rig = stack(open_settings)
    conn = open_history(open_settings.history_path)
    rows = []
    for index in range(10):
        record = {
            "pre_round": 33.6,
            "binding": "deadband" if index % 2 else None,
            "terms": [
                {"name": "curve", "raw": 34.1, "value": 34.1},
                {"name": "room_feedback", "raw": -0.6, "value": -0.5},
                {"name": "plan", "raw": 0.0, "value": 0.0},
                {"name": "start_ramp", "raw": 0.0, "value": 0.0},
                {"name": "override", "raw": 0.25, "value": 0.25},
                {"name": "cycling_floor", "raw": 0.0, "value": 0.0},
                *([{"name": "stove", "raw": -3.0, "value": -1.5}] if index == 1 else []),
                {"name": "safety", "raw": 33.85, "value": 33.6},
            ],
            "controller_state": {"safety_low_c": 26.8, "safety_high_c": 37.8},
        }
        rows.append(
            DecisionRow(
                ts=1_800_000_000.0 + 60 * index,
                controller="ovenbird",
                mode="auto",
                ladder="schedule_curve_feedback",
                reason="room_feedback",
                setpoint=34,
                record=json.dumps(record),
                arbiter="[]",
                commands="[]",
                config_version=index // 5 + 1,
            )
        )
    write_journal(conn, rows, [])
    conn.close()
    window = {"from": "2027-01-15T08:00:00Z", "to": "2027-01-15T08:10:00Z"}
    with rig.client() as client:
        raw = client.get("/api/v1/decisions/series", params={**window, "step": 0}).json()
        coarse = client.get("/api/v1/decisions/series", params={**window, "step": 300}).json()
        default = client.get("/api/v1/decisions/series", params=window).json()
        bad = client.get("/api/v1/decisions/series", params={**window, "step": 60})
    assert raw["step"] == 0
    assert len(raw["at"]) == 10
    assert raw["at"][0] == "2027-01-15T08:00:00Z"
    assert raw["curve"][0] == 34.1
    assert raw["room_feedback"][0] == -0.5
    assert raw["other"][0] == 0.25
    assert raw["other"][1] == 0.25
    assert raw["stove"][:3] == [0.0, -1.5, 0.0]
    assert raw["safety_delta"][0] == pytest.approx(-0.25)
    assert raw["safety_low"][0] == 26.8
    assert raw["binding"][:2] == [None, "deadband"]
    assert raw["config_version"] == [1] * 5 + [2] * 5
    assert len(coarse["at"]) == 2
    assert coarse["at"] == ["2027-01-15T08:04:00Z", "2027-01-15T08:09:00Z"]
    assert default["step"] == 0
    assert bad.status_code == 400


@pytest.mark.parametrize(("body", "detail"), [({}, {}), ({"reason": "away"}, {"reason": "away"})])
def test_pause_audit_omits_a_missing_reason(
    secured: Settings, body: dict[str, Any], detail: dict[str, Any]
) -> None:
    """The pause audit detail contains the reason only when one was given."""
    rig = stack(secured)
    with rig.client() as client:
        client.post("/api/v1/control/pause", json=body, headers={**BEARER, **MARK})
        events = client.get("/api/v1/audit", params=ALL_TIME, headers=basic()).json()["events"]
    assert [(e["action"], e["detail"]) for e in events] == [("mode_pause", detail)]


def test_the_broker_endpoints_answer_status_and_refusals(secured: Settings) -> None:
    """Broker endpoints report status, reject bad input and require a passing test."""
    admin = {**basic(), **MARK}
    with stack(secured).client() as client:
        status = client.get("/api/v1/config/mqtt", headers=admin).json()
        invalid = client.post("/api/v1/config/mqtt/test", json={"port": "x"}, headers=admin)
        failed = client.post("/api/v1/config/mqtt/test", json={"host": "b.example"}, headers=admin)
        untested = client.put("/api/v1/config/mqtt", json={"host": "b.example"}, headers=admin)
    assert status["apply"] == {"state": "idle", "message": None, "at": None}
    assert status["host"] == secured.mqtt_host
    assert invalid.status_code == 422
    assert invalid.json()["errors"][0]["code"] == "type"
    assert failed.status_code == 200
    assert failed.json()["error_code"] == "unreachable"
    assert untested.status_code == 409
    assert untested.json()["errors"][0]["code"] == "test_required"


def test_stored_rows_of_the_removed_house_model_read_back(secured: Settings) -> None:
    """Rows from the removed house model still read back and are skipped in replay."""
    rig = stack(secured)
    conn = open_history(secured.history_path)
    ts = 1_800_000_000.0
    record = DecisionRecord(
        at=Instant(ts, datetime.fromtimestamp(ts, UTC)),
        controller="ovenbird",
        mode=Mode.SHADOW,
        ladder=LadderLevel.CURVE_ONLY,
        terms=(),
        pre_round=34.0,
        setpoint=34,
        binding=None,
        flip_distance=None,
        inputs_used=(),
        controller_state={},
        reason=ReasonCode.CURVE,
        note="",
    ).to_json_dict()
    stale = DecisionRow(
        ts,
        "ovenbird",
        "auto",
        "model_plan",
        "curve",
        34,
        json.dumps({**record, "ladder": "model_plan"}),
        "[]",
        "[]",
        1,
    )
    alarm = AlarmRow(ts, "model_plan", "info", "started", "guard verdict", "{}")
    write_journal(conn, [stale], [], [alarm])
    conn.close()
    rig.manager.store.audit(ts, "admin", "house_learn_run", {"fit": "old"})
    window = {"from": "2027-01-15T08:00:00Z", "to": "2027-01-15T09:00:00Z"}
    with rig.client() as client:
        alarms = client.get("/api/v1/alarms", params=window, headers=basic()).json()
        audit = client.get("/api/v1/audit", params=ALL_TIME, headers=basic()).json()
        decisions = client.get("/api/v1/decisions", params=window, headers=basic())
        latest = client.get("/api/v1/decisions/latest", headers=basic())
        series = client.get("/api/v1/decisions/series", params=window, headers=basic())
    assert [e["code"] for e in alarms["events"]] == ["model_plan"]
    assert [e["action"] for e in audit["events"]] == ["house_learn_run"]
    assert decisions.status_code == 200
    assert decisions.json()["decisions"][0]["ladder"] == "model_plan"
    assert latest.status_code == 200
    assert series.status_code == 200
    good = DecisionRow(
        ts, "ovenbird", "auto", "curve_only", "curve", 34, json.dumps(record), "[]", "[]", 1
    )
    ticks, skipped = parse_rows([good, stale])
    assert (len(ticks), skipped) == (1, 1)

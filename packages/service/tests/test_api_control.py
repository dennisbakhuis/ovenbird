from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ovenbird.api.app import create_app
from ovenbird.config import Settings
from ovenbird.control import ControlLoop
from ovenbird.control.alarms import AlarmCode
from ovenbird.history import HistoryWriter, Retention
from ovenbird.runtime import Runtime
from ovenbird.service import build_control
from ovenbird.testing import FakeClock
from ovenbird_core.control import IntentKind

PUBLISH: dict[str, Any] = {
    "control_mode": "auto",
    "allow_commands": True,
    "mqtt_host": "mosquitto",
    "command_brokers": ("mosquitto",),
}
RELEASE = "/api/v1/control/release-hold"
JSON = {"Content-Type": "application/json"}
MARK = {"X-Ovenbird-Request": "1"}


def basic(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


async def no_sleep(_: float) -> None:
    return None


def control(settings: Settings, clock: FakeClock) -> tuple[Runtime, ControlLoop]:
    runtime = Runtime(clock=clock)
    loop, _ = build_control(settings, runtime, None, sleep=no_sleep)
    return runtime, loop


def latch(loop: ControlLoop, clock: FakeClock) -> None:
    adapter = loop.adapter
    assert adapter is not None
    for _ in range(3):
        adapter._start_hold(clock(), "foreign writer")
    assert adapter.hold is not None
    assert adapter.hold.latched


@pytest.fixture
def secured(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(**PUBLISH, http_host="0.0.0.0", admin_password="pw-123")


def test_release_hold_needs_admin_json_and_a_hold(secured: Settings) -> None:
    clock = FakeClock()
    runtime, loop = control(secured, clock)
    with TestClient(create_app(runtime, secured, control=loop)) as client:
        assert client.post(RELEASE, json={}, headers=MARK).status_code == 401
        wrong = client.post(RELEASE, json={}, headers={**basic("admin", "nope"), **MARK})
        assert wrong.status_code == 401
        unmarked = client.post(RELEASE, json={}, headers=basic("admin", "pw-123"))
        assert unmarked.status_code == 403
        admin = {**basic("admin", "pw-123"), **MARK}
        form = client.post(
            RELEASE, content="reason=x", headers={**admin, "Content-Type": "text/plain"}
        )
        assert form.status_code == 415
        foreign = client.post(RELEASE, json={}, headers={**admin, "Origin": "https://evil.example"})
        assert foreign.status_code == 403
        none = client.post(RELEASE, json={}, headers=admin)
        assert none.status_code == 409
        latch(loop, clock)
        bad = client.post(RELEASE, json={"reason": 5}, headers=admin)
        assert bad.status_code == 400
        assert loop.alarms.is_active(AlarmCode.HOLD_LATCHED)
        ok = client.post(RELEASE, json={"reason": "checked the remote"}, headers=admin)
        assert ok.status_code == 200
        body = ok.json()
        assert body["released"]["latched"] is True
        assert body["released"]["incident"] == 3
        assert body["by"].startswith("admin from ")
        assert body["by"].endswith(": checked the remote")
        assert body["hold"] is None
        assert body["safety_hold"] == []
        assert body["control"]["adapter"]["hold_latched"] is False
        assert not loop.alarms.is_active(AlarmCode.HOLD_LATCHED)
        same_origin = client.post(
            RELEASE, json={}, headers={**admin, "Origin": "http://testserver"}
        )
        assert same_origin.status_code == 409


def test_release_hold_refuses_without_a_password(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(**PUBLISH)
    clock = FakeClock()
    runtime, loop = control(settings, clock)
    latch(loop, clock)
    with TestClient(create_app(runtime, settings, control=loop)) as client:
        response = client.post(RELEASE, json={}, headers=MARK)
    assert response.status_code == 403
    assert "OVENBIRD_ADMIN_PASSWORD" in response.json()["detail"]
    assert loop.adapter is not None
    assert loop.adapter.hold is not None


def test_release_hold_through_ingress(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(**PUBLISH, ingress=True)
    clock = FakeClock()
    runtime, loop = control(settings, clock)
    latch(loop, clock)
    app = create_app(runtime, settings, control=loop)
    with TestClient(app, client=("172.30.32.2", 50000)) as client:
        assert client.post(RELEASE, json={}).status_code == 403
        response = client.post(RELEASE, json={}, headers=MARK)
    assert response.status_code == 200
    assert response.json()["by"] == "ingress (Home Assistant admin)"


def test_release_hold_without_publishing_is_a_conflict(
    secured: Settings, make_settings: Callable[..., Settings]
) -> None:
    shadow = make_settings(http_host="0.0.0.0", admin_password="pw-123")
    runtime, loop = control(shadow, FakeClock())
    with TestClient(create_app(runtime, shadow, control=loop)) as client:
        response = client.post(RELEASE, json={}, headers={**basic("admin", "pw-123"), **MARK})
    assert response.status_code == 409
    del secured


def test_alarms_endpoint_lists_active_alarms_and_history(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(**PUBLISH)
    clock = FakeClock()
    writer = HistoryWriter(settings.history_path, Retention(), flush_interval=0.01)
    runtime = Runtime(clock=clock, history=writer)
    loop, _ = build_control(settings, runtime, writer, sleep=no_sleep)
    writer.start()
    try:
        latch(loop, clock)
        assert loop.adapter is not None
        loop.adapter.release_hold(clock(), "admin")
    finally:
        writer.stop()
    loop.alarms.raise_alarm(AlarmCode.LOW_FLOW, "Pump_Flow 3.0 l/min", clock())
    with TestClient(create_app(runtime, settings, control=loop)) as client:
        body = client.get(
            "/api/v1/alarms", params={"from": "2000-01-01T00:00:00Z", "to": "2100-01-01T00:00:00Z"}
        ).json()
        health = client.get("/api/v1/health").json()
        latest = client.get("/api/v1/decisions/latest").json()
    assert [a["code"] for a in body["active"]] == ["low_flow"]
    assert body["active"][0]["severity"] == "critical"
    events = [(e["code"], e["event"]) for e in body["events"]]
    assert ("command_hold", "started") in events
    assert ("hold_latched", "raised") in events
    assert ("command_hold", "released") in events
    assert ("hold_latched", "cleared") in events
    started = next(e for e in body["events"] if e["event"] == "started")
    assert set(started["detail"]) == {"reason", "until", "latched", "incident"}
    assert health["checks"]["alarms"] == "starting"
    assert latest["control"]["safety"]["level"] == "starting"
    assert IntentKind.WATER_SETPOINT.value in {"water_setpoint"}

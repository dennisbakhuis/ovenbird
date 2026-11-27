from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

from ovenbird.api.app import create_app
from ovenbird.api.auth import (
    FailedAuthLimiter,
    LiveTickets,
    Role,
    credentials_match,
    origin_allowed,
)
from ovenbird.api.ws import Broadcaster, Channel
from ovenbird.config import Settings
from ovenbird.history import HistoryDatabase, Sample, SampleKind, open_history
from ovenbird.runtime import Runtime
from ovenbird.testing import FakeClock
from ovenbird_core import Heartbeat, LwtNotice, Reading, SourceKind

HEALTH_KEYS = {"live", "ready", "version", "api_version", "checks"}
SIGNAL_KEYS = {
    "value",
    "unit",
    "label",
    "age",
    "held",
    "max_age",
    "alive_by",
    "fresh",
    "source",
    "retained",
    "reason",
}


class OkHistory:
    def offer(self, sample: Sample) -> None:
        return None

    def healthy(self) -> bool:
        return True

    def starting(self) -> bool:
        return False


class StartingHistory(OkHistory):
    def healthy(self) -> bool:
        return False

    def starting(self) -> bool:
        return True


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def runtime(clock: FakeClock) -> Runtime:
    return Runtime(clock=clock, history=OkHistory())


@pytest.fixture
def settings(make_settings: Callable[..., Settings], tmp_path: Path) -> Settings:
    ui = tmp_path / "ui"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text("<!doctype html><title>ovenbird</title>", encoding="utf-8")
    (ui / "assets" / "app.js").write_text("console.log('ovenbird')", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("do not serve", encoding="utf-8")
    return make_settings()


@pytest.fixture
def client(runtime: Runtime, settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(runtime, settings)) as test_client:
        yield test_client


def reading(clock: FakeClock, signal: str, value: Any, unit: str | None = None) -> Reading:
    return Reading(signal, value, unit, clock(), SourceKind.HEISHAMON)


def feed_pump(runtime: Runtime, clock: FakeClock) -> None:
    runtime.apply(reading(clock, "main/Outside_Temp", 3, "°C"))
    runtime.apply(reading(clock, "main/Operating_Mode_State", 0))
    runtime.apply(reading(clock, "main/Compressor_Freq", 42, "Hz"))
    runtime.apply(Heartbeat(clock(), retained=False))
    runtime.apply(LwtNotice(True, clock(), retained=False))


def test_health_shape(client: TestClient, runtime: Runtime, clock: FakeClock) -> None:
    body = client.get("/api/v1/health").json()
    assert set(body) == HEALTH_KEYS
    assert body["api_version"] == 1
    assert body["version"] == "0.4.1"
    assert body["live"] is True
    assert body["ready"] is False
    assert body["checks"] == {
        "mqtt": "disconnected",
        "heishamon": "dead",
        "ha": "disabled",
        "history": "ok",
        "alarms": "disabled",
        "weather": "disabled",
    }
    runtime.history = StartingHistory()
    assert client.get("/api/v1/health").json()["checks"]["history"] == "starting"
    runtime.history = None
    assert client.get("/api/v1/health").json()["checks"]["history"] == "error"
    runtime.history = OkHistory()
    runtime.mqtt_connected = True
    runtime.apply(Heartbeat(clock(), retained=False))
    body = client.get("/api/v1/health").json()
    assert body["ready"] is True
    assert body["checks"]["heishamon"] == "alive"


def test_snapshot_shape(client: TestClient, runtime: Runtime, clock: FakeClock) -> None:
    feed_pump(runtime, clock)
    clock.advance(12.04)
    body = client.get("/api/v1/snapshot").json()
    assert set(body) == {"at", "heishamon", "links", "signals", "derived", "defrost"}
    assert body["at"].endswith("Z")
    assert body["heishamon"] == {"alive": True, "last_heartbeat_age": 12.0, "lwt": "Online"}
    outside = body["signals"]["main/Outside_Temp"]
    assert set(outside) == SIGNAL_KEYS
    assert outside == {
        "value": 3,
        "unit": "°C",
        "label": None,
        "age": 12.0,
        "held": 12.0,
        "max_age": 330.0,
        "alive_by": None,
        "fresh": True,
        "source": "heishamon",
        "retained": False,
        "reason": None,
    }
    assert body["signals"]["main/Operating_Mode_State"]["label"] == "heat"
    derived = body["derived"]
    assert derived["compressor_running"] == {"value": True, "reason": None}
    assert derived["defrost_active"]["value"] is None
    assert "main/Defrosting_State" in derived["defrost_active"]["reason"]
    assert body["defrost"] == {
        "active": False,
        "mode": None,
        "since": None,
        "inlet_at_start_c": None,
        "outside_at_start_c": None,
        "max_s": None,
    }
    assert derived["heat_delivered_w"]["value"] is None
    assert derived["heat_delivered_w"]["reason"].startswith("missing")


def write_history(path: Path, base: float) -> None:
    db = HistoryDatabase(open_history(path))
    samples = [
        Sample("main/Outside_Temp", "°C", SampleKind.NUMBER, base + i * 30, float(i % 4), 330.0)
        for i in range(10)
    ]
    db.write_batch(samples)
    db.close()


def test_history_endpoint(client: TestClient, settings: Settings) -> None:
    base = 1_800_000_000.0
    write_history(settings.history_path, base)
    body = client.get(
        "/api/v1/history",
        params={
            "signals": "main/Outside_Temp,unknown/x",
            "from": "2027-01-15T08:00:00Z",
            "to": "2027-01-15T08:05:00Z",
        },
    ).json()
    assert body["from"] == "2027-01-15T08:00:00Z"
    assert body["to"] == "2027-01-15T08:05:00Z"
    assert body["step"] == 60
    series = body["series"]["main/Outside_Temp"]
    assert series["unit"] == "°C"
    assert [point[0] for point in series["points"]] == [
        f"2027-01-15T08:0{minute}:00Z" for minute in range(5)
    ]
    assert series["points"][0][1] == pytest.approx(0.5)
    assert body["series"]["unknown/x"] == {
        "unit": None,
        "points": [[point[0], None] for point in series["points"]],
    }
    raw = client.get(
        "/api/v1/history",
        params={
            "signals": "main/Outside_Temp",
            "from": "2027-01-15T08:00:00Z",
            "step": 0,
            "to": "2027-01-15T08:01:00Z",
        },
    ).json()
    assert raw["series"]["main/Outside_Temp"]["points"] == [
        ["2027-01-15T08:00:00Z", 0.0],
        ["2027-01-15T08:00:30Z", 1.0],
    ]


def test_history_default_window(client: TestClient) -> None:
    body = client.get("/api/v1/history", params={"signals": "main/Outside_Temp"}).json()
    assert body["step"] == 60
    assert len(body["series"]["main/Outside_Temp"]["points"]) in (1440, 1441)


@pytest.mark.parametrize(
    "params",
    [
        {"signals": ""},
        {"signals": "a", "step": 30},
        {"signals": "a", "from": "yesterday"},
        {"signals": "a", "from": "2027-01-02T00:00:00Z", "to": "2027-01-01T00:00:00Z"},
        {"signals": ",".join(f"s{i}" for i in range(51))},
    ],
)
def test_history_rejects_bad_requests(client: TestClient, params: dict[str, Any]) -> None:
    assert client.get("/api/v1/history", params=params).status_code == 400


def test_static_ui_and_spa_fallback(client: TestClient) -> None:
    index = client.get("/")
    assert index.status_code == 200
    assert "ovenbird" in index.text
    assert index.headers["cache-control"] == "no-cache"
    assert client.get("/history/today").text == index.text
    script = client.get("/assets/app.js")
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert client.get("/assets/missing.js").status_code == 404
    assert client.get("/%2e%2e/secret.txt").status_code == 404
    assert "do not serve" not in client.get("/..%2fsecret.txt").text
    api_404 = client.get("/api/v1/nope")
    assert api_404.status_code == 404
    assert api_404.json() == {"detail": "Not Found"}
    assert client.get("/docs").text == index.text


def test_without_ui_dir_is_404(
    runtime: Runtime, make_settings: Callable[..., Settings], tmp_path: Path
) -> None:
    settings = make_settings(ui_dir=tmp_path / "absent")
    with TestClient(create_app(runtime, settings)) as test_client:
        assert test_client.get("/").status_code == 404
        assert test_client.get("/api/v1/health").status_code == 200


def basic(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_basic_auth_on_everything_but_health(
    runtime: Runtime, make_settings: Callable[..., Settings], settings: Settings
) -> None:
    secured = make_settings(http_host="0.0.0.0", admin_password="pw-123", ui_dir=settings.ui_dir)
    with TestClient(create_app(runtime, secured)) as test_client:
        assert test_client.get("/api/v1/health").status_code == 200
        for path in ("/api/v1/snapshot", "/api/v1/history?signals=a", "/", "/assets/app.js"):
            response = test_client.get(path)
            assert response.status_code == 401, path
            assert response.headers["www-authenticate"].startswith("Basic")
        assert (
            test_client.get("/api/v1/snapshot", headers=basic("admin", "wrong")).status_code == 401
        )
        assert (
            test_client.get("/api/v1/snapshot", headers=basic("root", "pw-123")).status_code == 401
        )
        assert (
            test_client.get("/api/v1/snapshot", headers=basic("admin", "pw-123")).status_code == 200
        )
        assert test_client.get("/", headers=basic("admin", "pw-123")).status_code == 200
        with pytest.raises(WebSocketDisconnect), test_client.websocket_connect("/api/v1/ws") as ws:
            ws.receive_json()
        with test_client.websocket_connect("/api/v1/ws", headers=basic("admin", "pw-123")) as ws:
            assert ws.receive_json()["type"] == "snapshot"


REQUEST_HEADERS = {"Content-Type": "application/json", "X-Ovenbird-Request": "1"}


def get_ticket(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post("/api/v1/live/ticket", headers={**REQUEST_HEADERS, **headers})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    return cast(str, response.json()["ticket"])


def test_live_connection_opens_with_a_single_use_pass(
    runtime: Runtime, make_settings: Callable[..., Settings], settings: Settings
) -> None:
    secured = make_settings(http_host="0.0.0.0", admin_password="pw-123", ui_dir=settings.ui_dir)
    with TestClient(create_app(runtime, secured)) as test_client:
        assert test_client.post("/api/v1/live/ticket", headers=REQUEST_HEADERS).status_code == 401
        assert (
            test_client.post("/api/v1/live/ticket", headers=basic("admin", "pw-123")).status_code
            == 415
        )
        ticket = get_ticket(test_client, basic("admin", "pw-123"))
        with test_client.websocket_connect(f"/api/v1/ws?ticket={ticket}") as ws:
            assert ws.receive_json()["type"] == "snapshot"
        with (
            pytest.raises(WebSocketDisconnect),
            test_client.websocket_connect(f"/api/v1/ws?ticket={ticket}") as ws,
        ):
            ws.receive_json()
        with (
            pytest.raises(WebSocketDisconnect),
            test_client.websocket_connect("/api/v1/ws?ticket=made-up") as ws,
        ):
            ws.receive_json()
        stale = get_ticket(test_client, basic("admin", "pw-123"))
        with test_client.websocket_connect(
            f"/api/v1/ws?ticket={stale}x", headers=basic("admin", "pw-123")
        ) as ws:
            assert ws.receive_json()["type"] == "snapshot"


def test_live_pass_does_not_skip_the_origin_check(
    runtime: Runtime, make_settings: Callable[..., Settings], settings: Settings
) -> None:
    secured = make_settings(http_host="0.0.0.0", admin_password="pw-123", ui_dir=settings.ui_dir)
    with TestClient(create_app(runtime, secured)) as test_client:
        ticket = get_ticket(test_client, basic("admin", "pw-123"))
        with (
            pytest.raises(WebSocketDisconnect),
            test_client.websocket_connect(
                f"/api/v1/ws?ticket={ticket}", headers={"Origin": "http://evil.example"}
            ) as ws,
        ):
            ws.receive_json()


def test_live_passes_expire_are_single_use_and_bounded() -> None:
    clock = FakeClock(1000.0)
    passes = LiveTickets(ttl=30.0, capacity=2, clock=lambda: clock.t)
    first = passes.issue(Role.ADMIN)
    assert passes.redeem(first) is Role.ADMIN
    assert passes.redeem(first) is None
    late = passes.issue(Role.READ)
    clock.advance(30.0)
    assert passes.redeem(late) is None
    a, b, c = passes.issue(Role.READ), passes.issue(Role.OPERATE), passes.issue(Role.ADMIN)
    assert passes.redeem(a) is None
    assert passes.redeem(b) is Role.OPERATE
    assert passes.redeem(c) is Role.ADMIN
    assert passes.redeem(None) is None
    assert passes.redeem("") is None


def test_tab_icons_need_no_login(
    runtime: Runtime, make_settings: Callable[..., Settings], settings: Settings
) -> None:
    (settings.ui_dir / "favicon.svg").write_text("<svg/>")
    secured = make_settings(http_host="0.0.0.0", admin_password="pw-123", ui_dir=settings.ui_dir)
    with TestClient(create_app(runtime, secured)) as test_client:
        assert test_client.get("/favicon.svg").status_code == 200
        assert test_client.get("/favicon.ico").status_code != 401
        assert test_client.get("/favicon.svg.map").status_code == 401


@pytest.mark.parametrize(
    ("destination", "prompts"),
    [
        (None, True),
        ("document", True),
        ("empty", True),
        ("script", True),
        ("image", False),
        ("font", False),
        ("websocket", False),
    ],
)
def test_background_loads_do_not_prompt_for_the_login(
    runtime: Runtime,
    make_settings: Callable[..., Settings],
    settings: Settings,
    destination: str | None,
    prompts: bool,
) -> None:
    secured = make_settings(http_host="0.0.0.0", admin_password="pw-123", ui_dir=settings.ui_dir)
    headers = {"Sec-Fetch-Dest": destination} if destination else {}
    with TestClient(create_app(runtime, secured)) as test_client:
        response = test_client.get("/assets/app.js", headers=headers)
    assert response.status_code == 401
    assert ("www-authenticate" in response.headers) is prompts


def test_ingress_trusts_only_the_supervisor_address(
    runtime: Runtime, make_settings: Callable[..., Settings], settings: Settings
) -> None:
    ingress = make_settings(ingress=True, admin_password="pw-123", ui_dir=settings.ui_dir)
    for address, expected in (("172.30.32.2", 200), ("192.168.1.20", 401)):
        with TestClient(create_app(runtime, ingress), client=(address, 50000)) as test_client:
            assert test_client.get("/api/v1/snapshot").status_code == expected, address
            assert test_client.get("/").status_code == expected, address
            assert test_client.get("/api/v1/health").status_code == 200
    with TestClient(create_app(runtime, ingress), client=("192.168.1.20", 50000)) as test_client:
        assert (
            test_client.get("/api/v1/snapshot", headers=basic("admin", "pw-123")).status_code == 200
        )


def test_ingress_without_password_rejects_other_sources(
    runtime: Runtime, make_settings: Callable[..., Settings], settings: Settings
) -> None:
    ingress = make_settings(ingress=True, ui_dir=settings.ui_dir)
    with TestClient(create_app(runtime, ingress), client=("192.168.1.20", 50000)) as test_client:
        assert test_client.get("/api/v1/snapshot").status_code == 401
        headers = basic("admin", "")
        assert test_client.get("/api/v1/snapshot", headers=headers).status_code == 401
    trusted = TestClient(create_app(runtime, ingress), client=("172.30.32.2", 50000))
    with trusted as test_client, test_client.websocket_connect("/api/v1/ws") as ws:
        assert ws.receive_json()["type"] == "snapshot"


@pytest.mark.parametrize(
    "header",
    [None, b"Bearer x", b"Basic !!!", b"Basic " + base64.b64encode(b"no-colon")],
)
def test_credentials_match_rejects_malformed(header: bytes | None) -> None:
    assert credentials_match(header, "admin", "pw") is False


def test_websocket_initial_messages_and_coalescing(
    runtime: Runtime, settings: Settings, clock: FakeClock
) -> None:
    broadcaster = Broadcaster(runtime, snapshot_interval=0.3, health_interval=0.05)
    app = create_app(runtime, settings, broadcaster=broadcaster)
    with TestClient(app) as test_client, test_client.websocket_connect("/api/v1/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "snapshot"
        assert set(first["data"]) == {
            "at",
            "heishamon",
            "links",
            "signals",
            "derived",
            "defrost",
        }
        assert ws.receive_json()["type"] == "health"
        for value in range(1, 6):
            runtime.apply(reading(clock, "main/Outside_Temp", value, "°C"))
        snapshot = next_of_type(ws, "snapshot")
        assert snapshot["data"]["signals"]["main/Outside_Temp"]["value"] == 5
        runtime.apply(reading(clock, "main/Outside_Temp", 6, "°C"))
        snapshot = next_of_type(ws, "snapshot")
        assert snapshot["data"]["signals"]["main/Outside_Temp"]["value"] == 6
        runtime.mqtt_connected = True
        health = next_of_type(ws, "health")
        assert health["data"]["checks"]["mqtt"] == "connected"


def next_of_type(ws: Any, kind: str) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        message: dict[str, Any] = ws.receive_json()
        if message["type"] == kind:
            return message
    raise AssertionError(f"no {kind} message")


async def test_channel_coalesces_per_type_and_flags_slow_clients() -> None:
    channel = Channel(max_overwrites=3)
    assert channel.offer("snapshot", "s1")
    assert channel.offer("health", "h1")
    assert channel.offer("snapshot", "s2")
    assert await channel.take() == ["s2", "h1"]
    assert channel.overwrites == 0
    channel.offer("snapshot", "a")
    channel.offer("snapshot", "b")
    channel.offer("snapshot", "c")
    assert not channel.offer("snapshot", "d")
    assert channel.slow


class StuckWebSocket:
    def __init__(self) -> None:
        self.closed_with: int | None = None
        self.sent: list[str] = []

    async def accept(self) -> None:
        return None

    async def send_text(self, text: str) -> None:
        self.sent.append(text)
        await asyncio.Event().wait()

    async def receive(self) -> dict[str, Any]:
        await asyncio.Event().wait()
        return {}

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed_with = code


async def test_slow_client_is_disconnected(runtime: Runtime) -> None:
    broadcaster = Broadcaster(runtime, send_timeout=0.05)
    socket = StuckWebSocket()
    await asyncio.wait_for(broadcaster.serve(cast(WebSocket, socket)), 2)
    assert socket.closed_with == 1013
    assert broadcaster.disconnected_slow == 1
    assert broadcaster.channels == set()
    assert json.loads(socket.sent[0])["type"] == "snapshot"


async def test_too_many_clients_are_refused(runtime: Runtime) -> None:
    broadcaster = Broadcaster(runtime, max_clients=0)
    socket = StuckWebSocket()
    await asyncio.wait_for(broadcaster.serve(cast(WebSocket, socket)), 2)
    assert socket.closed_with == 1013
    assert socket.sent == []


class VanishingWebSocket(StuckWebSocket):
    async def send_text(self, text: str) -> None:
        raise RuntimeError("client went away")


async def test_client_failing_mid_send_is_dropped_quietly(runtime: Runtime) -> None:
    broadcaster = Broadcaster(runtime)
    socket = VanishingWebSocket()
    await asyncio.wait_for(broadcaster.serve(cast(WebSocket, socket)), 2)
    assert broadcaster.channels == set()
    assert broadcaster.disconnected_slow == 0


def test_websocket_origin_check(
    runtime: Runtime, make_settings: Callable[..., Settings], settings: Settings
) -> None:
    configured = make_settings(
        ui_dir=settings.ui_dir, http_allowed_origins="https://ha.example:8123"
    )
    with TestClient(create_app(runtime, configured)) as test_client:
        for origin in ("http://testserver", "http://TESTSERVER:80", "https://ha.example:8123"):
            with test_client.websocket_connect("/api/v1/ws", headers={"Origin": origin}) as ws:
                assert ws.receive_json()["type"] == "snapshot", origin
        with test_client.websocket_connect("/api/v1/ws") as ws:
            assert ws.receive_json()["type"] == "snapshot"
        for origin in (
            "https://evil.example",
            "http://testserver:8099",
            "null",
            "https://ha.example",
        ):
            with (
                pytest.raises(WebSocketDisconnect) as excinfo,
                test_client.websocket_connect("/api/v1/ws", headers={"Origin": origin}) as ws,
            ):
                ws.receive_json()
            assert excinfo.value.code == 1008, origin
        assert (
            test_client.get(
                "/api/v1/snapshot", headers={"Origin": "https://evil.example"}
            ).status_code
            == 200
        )


def test_websocket_origin_check_trusts_ingress(
    runtime: Runtime, make_settings: Callable[..., Settings], settings: Settings
) -> None:
    ingress = make_settings(ingress=True, ui_dir=settings.ui_dir)
    trusted = TestClient(create_app(runtime, ingress), client=("172.30.32.2", 50000))
    headers = {"Origin": "https://homeassistant.local:8123"}
    with trusted as test_client, test_client.websocket_connect("/api/v1/ws", headers=headers) as ws:
        assert ws.receive_json()["type"] == "snapshot"


@pytest.mark.parametrize(
    ("origin", "host", "allowed"),
    [
        ("http://ha.local:8099", "ha.local:8099", True),
        ("https://ha.local", "ha.local:443", False),
        ("https://ha.local", "ha.local", False),
        ("http://[::1]:8099", "[::1]:8099", True),
        ("http://ha.local:8099", "ha.local:8100", False),
        ("http://ha.local:8099", None, False),
        ("file://", "ha.local", False),
        ("http://ha.local:notaport", "ha.local", False),
    ],
)
def test_origin_allowed(origin: str, host: str | None, allowed: bool) -> None:
    assert origin_allowed(origin, host, frozenset()) is allowed


@pytest.mark.parametrize(
    ("origin", "host", "scheme", "allowed"),
    [
        ("https://ha.local", "ha.local", "wss", True),
        ("https://ha.local:443", "ha.local:443", "https", True),
        ("http://ha.local", "ha.local", "wss", False),
        ("https://ha.local", "ha.local", "ws", False),
        ("https://ha.local:8099", "ha.local:8099", "ws", False),
        ("http://ha.local:8099", "ha.local:8099", "ws", True),
    ],
)
def test_origin_allowed_compares_scheme(origin: str, host: str, scheme: str, allowed: bool) -> None:
    assert origin_allowed(origin, host, frozenset(), scheme) is allowed


def test_websocket_origin_check_refuses_https_origin_on_plain_request(
    runtime: Runtime, settings: Settings
) -> None:
    with TestClient(create_app(runtime, settings)) as test_client:
        with (
            pytest.raises(WebSocketDisconnect) as excinfo,
            test_client.websocket_connect(
                "/api/v1/ws", headers={"Origin": "https://testserver"}
            ) as ws,
        ):
            ws.receive_json()
        assert excinfo.value.code == 1008


def test_lockout_is_per_source_and_username(
    runtime: Runtime, make_settings: Callable[..., Settings], settings: Settings
) -> None:
    secured = make_settings(http_host="0.0.0.0", admin_password="pw-123", ui_dir=settings.ui_dir)
    with TestClient(create_app(runtime, secured)) as test_client:
        for _ in range(12):
            test_client.get("/api/v1/snapshot", headers=basic("root", "guess"))
        assert (
            test_client.get("/api/v1/snapshot", headers=basic("root", "guess")).status_code == 429
        )
        assert (
            test_client.get("/api/v1/snapshot", headers=basic("admin", "pw-123")).status_code == 200
        )
        for _ in range(12):
            test_client.get("/api/v1/snapshot", headers=basic("admin", "guess"))
        assert (
            test_client.get("/api/v1/snapshot", headers=basic("admin", "guess")).status_code == 429
        )


def test_limiter_keys_are_independent() -> None:
    limiter = FailedAuthLimiter(free_attempts=0, max_sources=3)
    limiter.failure(("1.2.3.4", "root"))
    assert limiter.retry_after(("1.2.3.4", "root")) > 0
    assert limiter.retry_after(("1.2.3.4", "admin")) == 0
    assert limiter.retry_after(("5.6.7.8", "root")) == 0


def test_limiter_backs_off_exponentially_and_forgets() -> None:
    now = {"t": 0.0}
    limiter = FailedAuthLimiter(
        free_attempts=2,
        base_lockout=1.0,
        max_lockout=8.0,
        forget_after=100.0,
        clock=lambda: now["t"],
    )
    limiter.failure("a")
    assert limiter.retry_after("a") == 0
    limiter.failure("a")
    assert limiter.retry_after("a") == 1.0
    limiter.failure("a")
    assert limiter.retry_after("a") == 2.0
    for _ in range(10):
        limiter.failure("a")
    assert limiter.retry_after("a") == 8.0
    assert limiter.retry_after("b") == 0
    now["t"] = 8.0
    assert limiter.retry_after("a") == 0
    now["t"] = 200.0
    limiter.failure("a")
    assert limiter.retry_after("a") == 0
    limiter.success("a")
    limiter.failure("a")
    assert limiter.retry_after("a") == 0


def test_limiter_bounds_tracked_sources() -> None:
    limiter = FailedAuthLimiter(free_attempts=0, max_sources=3)
    for index in range(10):
        limiter.failure(f"10.0.0.{index}")
    assert limiter.retry_after("10.0.0.0") == 0
    assert limiter.retry_after("10.0.0.9") > 0


def test_failed_logins_are_rate_limited(
    runtime: Runtime, make_settings: Callable[..., Settings], settings: Settings
) -> None:
    secured = make_settings(http_host="0.0.0.0", admin_password="pw-123", ui_dir=settings.ui_dir)
    app = create_app(runtime, secured)
    with TestClient(app, client=("10.1.1.1", 4000)) as test_client:
        for _ in range(5):
            response = test_client.get("/api/v1/snapshot", headers=basic("admin", "guess"))
            assert response.status_code == 401
        locked = test_client.get("/api/v1/snapshot", headers=basic("admin", "pw-123"))
        assert locked.status_code == 429
        assert int(locked.headers["retry-after"]) >= 1
        assert test_client.get("/api/v1/snapshot").status_code == 401
        assert test_client.get("/api/v1/health").status_code == 200
        with (
            pytest.raises(WebSocketDisconnect) as excinfo,
            test_client.websocket_connect("/api/v1/ws", headers=basic("admin", "pw-123")) as ws,
        ):
            ws.receive_json()
        assert excinfo.value.code == 1008
    with TestClient(app, client=("10.1.1.2", 4000)) as other:
        assert other.get("/api/v1/snapshot", headers=basic("admin", "pw-123")).status_code == 200

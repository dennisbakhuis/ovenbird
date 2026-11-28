"""The Home Assistant connection set in the app: store, locks, secrecy, test endpoint."""

from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
from collections.abc import AsyncIterator, Callable
from http import HTTPStatus
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.http11 import Request, Response

from ovenbird.api.app import create_app
from ovenbird.config import Settings
from ovenbird.configstore import (
    Actor,
    ConfigManager,
    ConfigRefusedError,
    Source,
    provided_sources,
)
from ovenbird.ha import HaInput
from ovenbird.hacheck import CheckResult, check_connection, check_deadline, rest_url
from ovenbird.runtime import Runtime
from ovenbird.service import build_control, ha_follower
from ovenbird.system.diagnostics import effective_config, redact, secret_values
from ovenbird.testing import FakeClock

ADMIN = Actor("admin from 127.0.0.1", "127.0.0.1")
TOKEN = "long-lived-" + "t" * 40
OTHER = "other-token-" + "o" * 40
URL = "http://192.0.2.10:8123"
PASSWORD = "pw-123"
MARK = {"X-Ovenbird-Request": "1"}
ROOM = "ha/sensor.living_room_temperature"


def open_manager(
    settings: Settings, clock: FakeClock | None = None, locked: dict[str, Source] | None = None
) -> ConfigManager:
    """Open a ConfigManager on the settings with an optional clock and locked fields."""
    return ConfigManager.open(settings, clock or FakeClock(), locked=locked or {})


def everything(manager: ConfigManager) -> str:
    """Return every manager payload, version, export and audit event as one JSON string."""
    latest = manager.store.latest()
    audit = manager.store.audit_events(0.0, 1e12, 100)
    return json.dumps(
        {
            "payload": manager.payload(),
            "versions": manager.versions_payload(10),
            "version": None if latest is None else manager.version_payload(latest, values=True),
            "export": manager.export(),
            "audit": [event.detail for event in audit],
        }
    )


def test_connection_is_stored_outside_the_versions(
    make_settings: Callable[..., Settings],
) -> None:
    """A stored connection leaves config versions alone, notifies listeners, hides the token."""
    manager = open_manager(make_settings())
    calls: list[Settings] = []
    manager.connection_listeners.append(calls.append)
    body = manager.set_connection({"ha_url": URL, "ha_token": TOKEN}, ADMIN)
    fields = body["config"]["fields"]
    assert fields["ha_url"] == {
        "value": URL,
        "source": "store",
        "locked": False,
        "stored": URL,
        "default": None,
    }
    assert fields["ha_token"]["value"] == "set"
    assert fields["ha_token"]["stored"] == "set"
    assert fields["ha_token"]["locked"] is False
    assert manager.version is None
    assert manager.settings.ha_enabled
    assert [settings.ha_url for settings in calls] == [URL]
    assert TOKEN not in everything(manager)
    audit = manager.store.latest_audit("ha_connection")
    assert audit[0].detail == {"changed": ["ha_token", "ha_url"], "token": "set", "url": URL}
    manager.close()
    reopened = open_manager(make_settings())
    assert reopened.settings.ha_url == URL
    assert reopened.settings.ha_token is not None
    assert reopened.settings.ha_token.get_secret_value() == TOKEN


def test_token_is_redacted_from_diagnostics(make_settings: Callable[..., Settings]) -> None:
    """The token is redacted from the effective config and from leaked log text."""
    manager = open_manager(make_settings())
    manager.set_connection({"ha_url": URL, "ha_token": TOKEN}, ADMIN)
    config = effective_config(manager.settings)
    assert (config["ha_token"], config["ha_url"]) == ("set", "[removed]")
    assert TOKEN in secret_values(manager.settings)
    leaked = {"log": f"Bearer {TOKEN}"}
    assert redact(leaked, secret_values(manager.settings)) == {"log": "[redacted]"}


def test_signals_need_the_connection_and_keep_it(make_settings: Callable[..., Settings]) -> None:
    """Signals need the stored connection, and removing it is refused while one depends on it."""
    clock = FakeClock()
    manager = open_manager(make_settings(), clock)
    refused = manager.validate({"control_room_signal": ROOM})
    assert ("control_room_signal", "signal_unknown") in [(e.field, e.code) for e in refused.errors]
    manager.set_connection({"ha_url": URL, "ha_token": TOKEN}, ADMIN)
    clock.advance(61.0)
    manager.apply(0, {"control_room_signal": ROOM}, ADMIN)
    assert manager.settings.ha_subscriptions == ("sensor.living_room_temperature",)
    with pytest.raises(ConfigRefusedError) as removed:
        manager.set_connection({"ha_url": None, "ha_token": None}, ADMIN)
    assert removed.value.status == 422
    codes = [(e["field"], e["code"]) for e in removed.value.body["errors"]]
    assert ("control_room_signal", "signal_unknown") in codes
    manager.close()
    assert open_manager(make_settings()).settings.control_room_signal == ROOM


@pytest.mark.parametrize(
    ("changes", "field", "code"),
    [
        ({"ha_url": URL}, "ha_token", "missing"),
        ({"ha_token": TOKEN}, "ha_url", "missing"),
        ({"ha_url": "ftp://ha", "ha_token": TOKEN}, "ha_url", "invalid"),
        ({"ha_url": "http://me:pw@ha:8123", "ha_token": TOKEN}, "ha_url", "invalid"),
        ({"ha_url": URL, "ha_token": "two words"}, "ha_token", "invalid"),
        ({"ha_url": 5, "ha_token": TOKEN}, "ha_url", "type"),
        ({"mqtt_host": "x"}, "mqtt_host", "unknown_field"),
    ],
)
def test_invalid_connections_are_refused(
    make_settings: Callable[..., Settings], changes: dict[str, Any], field: str, code: str
) -> None:
    """Malformed or unknown connection input is refused with a field and code, storing nothing."""
    manager = open_manager(make_settings())
    with pytest.raises(ConfigRefusedError) as refused:
        manager.set_connection(changes, ADMIN)
    assert (field, code) in [(e["field"], e["code"]) for e in refused.value.body["errors"]]
    assert TOKEN not in json.dumps(refused.value.body)
    assert manager.store.connection() == {}


def test_unchanged_connection_is_no_change(make_settings: Callable[..., Settings]) -> None:
    """An identical connection is refused as no change, while a new token alone is accepted."""
    manager = open_manager(make_settings())
    manager.set_connection({"ha_url": URL, "ha_token": TOKEN}, ADMIN)
    with pytest.raises(ConfigRefusedError) as refused:
        manager.set_connection({"ha_url": URL}, ADMIN)
    assert refused.value.body["errors"][0]["code"] == "no_change"
    manager.set_connection({"ha_token": OTHER}, ADMIN)
    assert manager.settings.ha_token is not None
    assert manager.settings.ha_token.get_secret_value() == OTHER


def test_a_new_url_needs_its_token(make_settings: Callable[..., Settings]) -> None:
    """Changing the URL requires a new token, and nothing changes or notifies until it is given."""
    manager = open_manager(make_settings())
    seen: list[Settings] = []
    manager.set_connection({"ha_url": URL, "ha_token": TOKEN}, ADMIN)
    manager.connection_listeners.append(seen.append)
    elsewhere = "http://elsewhere.example:8123"
    with pytest.raises(ConfigRefusedError) as refused:
        manager.set_connection({"ha_url": elsewhere}, ADMIN)
    codes = [(e["field"], e["code"]) for e in refused.value.body["errors"]]
    assert codes == [("ha_token", "token_required")]
    assert manager.settings.ha_url == URL
    assert manager.store.connection()["ha_url"] == URL
    assert seen == []
    manager.set_connection({"ha_url": elsewhere, "ha_token": OTHER}, ADMIN)
    assert manager.settings.ha_url == elsewhere
    assert manager.settings.ha_token is not None
    assert manager.settings.ha_token.get_secret_value() == OTHER
    assert len(seen) == 1


def test_a_new_url_cannot_take_an_environment_token(
    make_settings: Callable[..., Settings],
) -> None:
    """A URL change cannot reuse a token that comes from the environment."""
    locked = {"ha_token": Source.ENV}
    settings = make_settings(ha_url="http://ha.base:8123", ha_token="env-token")
    manager = open_manager(settings, locked=locked)
    with pytest.raises(ConfigRefusedError) as refused:
        manager.set_connection({"ha_url": URL}, ADMIN)
    codes = [(e["field"], e["code"]) for e in refused.value.body["errors"]]
    assert codes == [("ha_token", "token_required")]


def test_environment_locks_the_connection(make_settings: Callable[..., Settings]) -> None:
    """Connection fields set from the environment are locked and cannot be changed."""
    locked = {"ha_url": Source.ENV, "ha_token": Source.ENV}
    manager = open_manager(
        make_settings(ha_url="http://ha.env:8123", ha_token="env-token"), locked=locked
    )
    fields = manager.payload()["fields"]
    assert (fields["ha_url"]["source"], fields["ha_url"]["locked"]) == ("env", True)
    assert (fields["ha_token"]["value"], fields["ha_token"]["locked"]) == ("set", True)
    with pytest.raises(ConfigRefusedError) as refused:
        manager.set_connection({"ha_url": URL, "ha_token": TOKEN}, ADMIN)
    codes = {(e["field"], e["code"]) for e in refused.value.body["errors"]}
    assert codes == {("ha_url", "locked"), ("ha_token", "locked")}


def test_environment_wins_over_a_stored_connection(make_settings: Callable[..., Settings]) -> None:
    """An environment connection wins over a stored one, which is kept as the stored value."""
    manager = open_manager(make_settings())
    manager.set_connection({"ha_url": URL, "ha_token": TOKEN}, ADMIN)
    manager.close()
    locked = {"ha_url": Source.ENV, "ha_token": Source.ENV}
    env = open_manager(make_settings(ha_url="http://ha.env:8123", ha_token="env"), locked=locked)
    assert env.settings.ha_url == "http://ha.env:8123"
    assert env.payload()["fields"]["ha_url"]["stored"] == URL


def test_put_config_refuses_connection_fields(make_settings: Callable[..., Settings]) -> None:
    """Validating a config change that contains connection fields is refused."""
    result = open_manager(make_settings()).validate({"ha_url": URL})
    assert [(e.field, e.code) for e in result.errors] == [("ha_url", "connection_field")]


def test_a_store_of_the_previous_schema_opens_and_migrates(
    make_settings: Callable[..., Settings], tmp_path: Path
) -> None:
    """A store of the previous schema version opens, migrates and keeps its values."""
    settings = make_settings()
    settings.data_dir.mkdir(parents=True)
    first = resources.files("ovenbird.configstore.migrations") / "0001_initial.sql"
    conn = sqlite3.connect(settings.data_dir / "config.db")
    conn.executescript(first.read_text("utf-8"))
    conn.execute(
        "INSERT INTO config_version VALUES "
        "(1, 1.0, 'seed', NULL, 'seed', NULL, NULL, ?, 'x', NULL)",
        ('{"control_comfort_c":21.5}',),
    )
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()
    manager = open_manager(settings)
    assert manager.settings.control_comfort_c == 21.5
    assert manager.store.connection() == {}
    assert manager.store._conn.execute("PRAGMA user_version").fetchone()[0] == 2


def test_follower_reconnects_the_input(make_settings: Callable[..., Settings]) -> None:
    """The HA follower reconfigures the input and the runtime when the connection is set."""
    manager = open_manager(make_settings())
    runtime = Runtime()
    ha = HaInput(None, None, (), runtime)
    manager.connection_listeners.append(ha_follower(ha, runtime))
    manager.set_connection({"ha_url": URL, "ha_token": TOKEN}, ADMIN)
    assert ha.configured
    assert ha.url == "ws://192.0.2.10:8123/api/websocket"
    assert runtime.ha_enabled is True
    assert TOKEN not in repr(ha)


def test_connection_change_reaches_the_control_loop(
    make_settings: Callable[..., Settings],
) -> None:
    """A connection change is passed to the control loop's reconfigure hooks at the next tick."""
    clock = FakeClock()
    manager = open_manager(make_settings(), clock)
    runtime = Runtime(clock=clock)

    async def no_sleep(_: float) -> None:
        """Replace the asyncio sleep so the control loop does not wait."""
        return

    loop, _ = build_control(
        manager.settings, runtime, None, sleep=no_sleep, hold=manager.hold, config_version=None
    )
    manager.attach(loop, loop.alarms)
    seen: list[bool] = []
    loop.reconfigure_hooks.append(lambda settings: seen.append(settings.ha_enabled))
    manager.set_connection({"ha_url": URL, "ha_token": TOKEN}, ADMIN)
    assert loop.reconfigure_pending
    loop.tick()
    assert seen == [True]


class FakeChecker:
    """Fake connection checker that records its calls and reports a healthy Home Assistant."""

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self.calls: list[tuple[Any, ...]] = []

    async def __call__(
        self, url: str | None, token: SecretStr | None, signals: Any, **kwargs: Any
    ) -> dict[str, Any]:
        """Record the URL, token and signals of a check and return a successful result."""
        self.calls.append((url, None if token is None else token.get_secret_value(), signals))
        return CheckResult(url, reachable=True, auth_ok=True).to_json()


def client_for(manager: ConfigManager, checker: FakeChecker) -> TestClient:
    """Create a test client for an app that uses the fake connection checker."""
    app = create_app(Runtime(), manager.settings, config=manager, ha_check=checker)
    return TestClient(app)


def basic(password: str = PASSWORD) -> dict[str, str]:
    """Return Basic-auth headers for the admin user with the given password."""
    return {"Authorization": "Basic " + base64.b64encode(f"admin:{password}".encode()).decode()}


def test_put_and_test_endpoints(make_settings: Callable[..., Settings]) -> None:
    """The PUT and test endpoints validate input, need admin, hide the token and pass values on."""
    settings = make_settings(http_host="0.0.0.0", admin_password=PASSWORD)
    manager = open_manager(settings)
    checker = FakeChecker()
    with client_for(manager, checker) as client:
        put = client.put(
            "/api/v1/config/ha", json={"url": URL, "token": TOKEN}, headers={**basic(), **MARK}
        )
        assert put.status_code == 200, put.text
        assert TOKEN not in put.text
        assert put.json()["config"]["fields"]["ha_token"]["value"] == "set"
        bad = client.put("/api/v1/config/ha", json={"url": "ftp://x"}, headers={**basic(), **MARK})
        assert bad.status_code == 422
        unknown = client.put("/api/v1/config/ha", json={"x": 1}, headers={**basic(), **MARK})
        assert unknown.status_code == 400
        anonymous = client.put("/api/v1/config/ha", json={"url": URL}, headers=MARK)
        assert anonymous.status_code == 401
        tested = client.post("/api/v1/config/ha/test", json={}, headers={**basic(), **MARK})
        assert tested.status_code == 200
        assert TOKEN not in tested.text
        other = client.post(
            "/api/v1/config/ha/test", json={"url": "http://other:8123"}, headers={**basic(), **MARK}
        )
        with_token = client.post(
            "/api/v1/config/ha/test",
            json={"url": "http://other:8123", "token": OTHER, "signals": [ROOM, "main/x"]},
            headers={**basic(), **MARK},
        )
        assert other.status_code == with_token.status_code == 200
        wrong = client.post(
            "/api/v1/config/ha/test", json={"signals": "x"}, headers={**basic(), **MARK}
        )
        assert wrong.status_code == 400
    assert checker.calls == [
        (URL, TOKEN, ()),
        ("http://other:8123", None, ()),
        ("http://other:8123", OTHER, (ROOM,)),
    ]


class FakeServer:
    """Fake Home Assistant websocket server with a fixed set of entity states."""

    def __init__(self, unit: str = "°C") -> None:
        """Create the fake with the given temperature unit and canned entity states."""
        self.unit = unit
        self.received: list[dict[str, Any]] = []
        self.states = [
            {
                "entity_id": "sensor.living_room_temperature",
                "state": "70.2",
                "attributes": {"unit_of_measurement": "°F"},
            },
            {"entity_id": "sensor.bare", "state": "21.0", "attributes": {}},
            {"entity_id": "sensor.gone", "state": "unavailable", "attributes": {}},
            {
                "entity_id": "climate.living",
                "state": "heat",
                "attributes": {"current_temperature": 21.5},
            },
        ]

    async def handler(self, ws: ServerConnection) -> None:
        """Serve one websocket session: authenticate with TOKEN, then answer config and states."""
        await ws.send(json.dumps({"type": "auth_required", "ha_version": "2026.11.1"}))
        auth = json.loads(await ws.recv())
        self.received.append(auth)
        if auth["access_token"] != TOKEN:
            await ws.send(json.dumps({"type": "auth_invalid", "message": "bad"}))
            return
        await ws.send(json.dumps({"type": "auth_ok", "ha_version": "2026.11.1"}))
        async for raw in ws:
            request = json.loads(raw)
            self.received.append(request)
            if request["type"] == "get_config":
                result: Any = {"unit_system": {"temperature": self.unit}}
            else:
                result = self.states
            reply = {"id": request["id"], "type": "result", "success": True, "result": result}
            await ws.send(json.dumps(reply))


@pytest.fixture
async def server() -> AsyncIterator[tuple[FakeServer, str]]:
    """Run a fake Home Assistant websocket server on a free port and yield it with its URL."""
    fake = FakeServer()
    running: Server
    async with serve(fake.handler, "127.0.0.1", 0) as running:
        port = next(iter(running.sockets)).getsockname()[1]
        yield fake, f"http://127.0.0.1:{port}"


def http(status: int) -> Callable[..., Any]:
    """Return a REST getter that always answers with the given HTTP status."""

    async def get(url: str, token: str, limit_s: float) -> tuple[int, bytes]:
        """Check that the URL is the REST API root and return the status with a fixed body."""
        assert url.endswith("/api/")
        return status, b'{"message": "API running."}'

    return get


async def test_check_reports_entities_and_units(server: tuple[FakeServer, str]) -> None:
    """The check reports entity units, values and problems, without leaking the token."""
    fake, url = server
    signals = (
        "ha/sensor.living_room_temperature",
        "ha/sensor.bare",
        "ha/sensor.gone",
        "ha/sensor.missing",
        "ha/climate.living#current_temperature",
    )
    body = await check_connection(
        url,
        SecretStr(TOKEN),
        signals,
        temperature=frozenset({"ha/sensor.bare", "ha/climate.living#current_temperature"}),
        get=http(200),
    )
    assert (body["reachable"], body["auth_ok"], body["ha_version"]) == (True, True, "2026.11.1")
    assert (body["temperature_unit"], body["metric"]) == ("°C", True)
    assert body["latency_ms"] is not None
    checks = {item["signal"]: item for item in body["entities"]}
    assert checks["ha/sensor.living_room_temperature"]["found"] is True
    assert checks["ha/sensor.living_room_temperature"]["unit"] == "°F"
    assert checks["ha/sensor.bare"]["problem"] is None
    assert checks["ha/sensor.gone"]["problem"] == "unavailable"
    assert checks["ha/sensor.missing"]["problem"] == "not found in Home Assistant"
    assert checks["ha/climate.living#current_temperature"]["value"] == 21.5
    assert body["ok"] is False
    assert [m["type"] for m in fake.received] == ["auth", "get_config", "get_states"]
    assert TOKEN not in json.dumps(body)


async def test_check_follows_no_websocket_redirect(server: tuple[FakeServer, str]) -> None:
    """The check reports a websocket error when the server redirects and does not follow it."""
    fake, target = server

    def redirect(connection: ServerConnection, request: Request) -> Response:
        """Answer every websocket handshake with a redirect to the real server."""
        response = connection.respond(HTTPStatus.FOUND, "moved\n")
        response.headers["Location"] = target.replace("http", "ws") + "/api/websocket"
        return response

    async with serve(fake.handler, "127.0.0.1", 0, process_request=redirect) as running:
        port = next(iter(running.sockets)).getsockname()[1]
        body = await check_connection(
            f"http://127.0.0.1:{port}", SecretStr(TOKEN), (), get=http(200), limit_s=2.0
        )
    assert body["error_code"] == "websocket"
    assert fake.received == []
    assert TOKEN not in json.dumps(body)


async def test_check_ends_within_its_deadline() -> None:
    """The check gives up within its deadline when the server never answers."""

    async def hang(url: str, token: str, limit_s: float) -> tuple[int, bytes]:
        """Wait forever instead of answering."""
        await asyncio.sleep(3600.0)
        return 200, b""

    started = asyncio.get_running_loop().time()
    body = await check_connection(
        "http://192.0.2.1:8123", SecretStr(TOKEN), (), get=hang, limit_s=0.05
    )
    assert body["error_code"] == "unreachable"
    assert asyncio.get_running_loop().time() - started < check_deadline(0.05)


async def test_check_refuses_a_bare_unit_outside_metric(server: tuple[FakeServer, str]) -> None:
    """A bare temperature entity is a problem when Home Assistant does not use metric units."""
    fake, url = server
    fake.unit = "°F"
    body = await check_connection(
        url,
        SecretStr(TOKEN),
        ("ha/sensor.bare",),
        temperature=frozenset({"ha/sensor.bare"}),
        get=http(200),
    )
    assert body["metric"] is False
    assert "not metric" in body["entities"][0]["problem"]
    assert body["ok"] is False


async def test_check_passes_for_a_good_setup(server: tuple[FakeServer, str]) -> None:
    """A check with a reachable server, valid token and found entities is ok."""
    _, url = server
    body = await check_connection(
        url, SecretStr(TOKEN), ("ha/sensor.living_room_temperature",), get=http(200)
    )
    assert body["ok"] is True
    assert body["error"] is None


async def test_check_reports_a_rejected_token(server: tuple[FakeServer, str]) -> None:
    """A rejected token is reported as auth_failed, over REST and over the websocket."""
    _, url = server
    body = await check_connection(url, SecretStr("wrong-token"), (), get=http(401))
    assert (body["reachable"], body["auth_ok"], body["error_code"]) == (True, False, "auth_failed")
    assert body["ok"] is False
    socket = await check_connection(url, SecretStr("wrong-token"), (), get=http(200))
    assert (socket["auth_ok"], socket["error_code"]) == (False, "auth_failed")
    assert "wrong-token" not in json.dumps(socket)


async def test_check_reports_an_unreachable_host() -> None:
    """An unreachable host is reported without leaking the token."""

    async def refused(url: str, token: str, limit_s: float) -> tuple[int, bytes]:
        """Raise a connection error that includes the token."""
        raise ConnectionRefusedError(f"refused {token}")

    body = await check_connection(URL, SecretStr(TOKEN), (), get=refused)
    assert (body["reachable"], body["error_code"]) == (False, "unreachable")
    assert TOKEN not in body["error"]


async def test_check_times_out_quickly() -> None:
    """A server that never answers makes the check fail quickly as unreachable."""

    async def hangs(url: str, token: str, limit_s: float) -> tuple[int, bytes]:
        """Wait far longer than the check limit."""
        await asyncio.sleep(10)
        return 200, b""

    body = await asyncio.wait_for(
        check_connection(URL, SecretStr(TOKEN), (), get=hangs, limit_s=0.05), 3
    )
    assert body["error_code"] == "unreachable"


@pytest.mark.parametrize(
    ("url", "token", "code"),
    [
        ("ftp://x", TOKEN, "invalid_url"),
        (None, TOKEN, "not_configured"),
        (URL, None, "token_required"),
    ],
)
async def test_check_needs_a_url_and_a_token(url: str | None, token: str | None, code: str) -> None:
    """A missing or invalid URL or token is reported with a specific error code."""
    body = await check_connection(url, None if token is None else SecretStr(token), ())
    assert body["error_code"] == code
    assert body["ok"] is False


async def test_check_reports_a_redirect_or_foreign_server() -> None:
    """A redirect on the REST probe is reported as an HTTP error."""
    body = await check_connection(URL, SecretStr(TOKEN), (), get=http(302))
    assert body["error_code"] == "http_error"


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("http://ha.local:8123", "http://ha.local:8123/api/"),
        ("https://proxy.example/ha/", "https://proxy.example/ha/api/"),
        ("http://supervisor/core", "http://supervisor/core/api/"),
        ("wss://ha.example/api/websocket", "https://ha.example/api/"),
    ],
)
def test_rest_url(base: str, expected: str) -> None:
    """The REST API URL is derived from the base URL, keeping path prefixes and mapping wss."""
    assert rest_url(base) == expected


def test_empty_environment_values_do_not_lock(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> None:
    """Empty environment values do not lock the connection fields, while set ones do."""
    monkeypatch.setenv("OVENBIRD_HA_URL", "")
    monkeypatch.setenv("OVENBIRD_HA_TOKEN", "")
    assert "ha_url" not in provided_sources()
    manager = ConfigManager.open(make_settings(), FakeClock(), locked=provided_sources())
    manager.set_connection({"ha_url": URL, "ha_token": TOKEN}, ADMIN)
    assert manager.settings.ha_url == URL
    monkeypatch.setenv("OVENBIRD_HA_URL", "http://ha.env:8123")
    assert provided_sources()["ha_url"] is Source.ENV

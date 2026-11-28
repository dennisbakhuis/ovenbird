from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ovenbird.api.app import create_app
from ovenbird.config import ConfigError, Settings
from ovenbird.configstore import Actor, ConfigManager
from ovenbird.configstore.store import MARKER_NAME
from ovenbird.control.alarms import AlarmBoard, AlarmCode
from ovenbird.notify.notifier import (
    CLEAR_HOLD_S,
    FAILING_AFTER,
    MAX_ERROR,
    RATE_LIMITS,
    RETRY_BASE_S,
    TEST_SPACING_S,
    Notifier,
)
from ovenbird.notify.transport import OPENER, HttpRequest, _NoRedirect
from ovenbird.runtime import Runtime
from ovenbird.service import build_service
from ovenbird.system.facts import Facts
from ovenbird.testing import FakeClock
from ovenbird.trial.supervision import Supervision

NTFY = {
    "notify_ntfy_url": "https://ntfy.example.test/",
    "notify_ntfy_topic": "ovenbird-secret-topic",
    "notify_ntfy_token": "tk_secret_token",
}
DEADMAN = "https://hc.example.test/ping/secret-uuid"
ADMIN = "pw-123"
ACTOR = Actor("admin from 10.0.0.2", "10.0.0.2")


class FakeTransport:
    """Notification transport stub that records requests and returns a status or raises."""

    def __init__(self, status: int = 200, error: Exception | None = None) -> None:
        """Set the status to return and an optional error to raise."""
        self.status = status
        self.error = error
        self.requests: list[HttpRequest] = []

    def __call__(self, request: HttpRequest) -> int:
        """Record the request, then raise the error or return the status."""
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.status

    def bodies(self) -> list[dict[str, Any]]:
        """Return the decoded JSON bodies of the recorded POST requests."""
        return [json.loads(r.body or b"{}") for r in self.requests if r.method == "POST"]

    def titles(self) -> list[str]:
        """Return the titles of the recorded POST notifications."""
        return [body["title"] for body in self.bodies()]


class Ticker:
    """Manually advanced monotonic clock."""

    def __init__(self) -> None:
        """Start at zero."""
        self.t = 0.0

    def __call__(self) -> float:
        """Return the current monotonic time in seconds."""
        return self.t


def basic(user: str, password: str) -> dict[str, str]:
    """Build a Basic authorization header for the credentials."""
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def flush(notifier: Notifier) -> float | None:
    """Run a notifier flush to completion and return the delay before it should run again."""
    return asyncio.run(notifier.flush())


Rig = tuple[Notifier, FakeTransport, Ticker, AlarmBoard, FakeClock]


@pytest.fixture
def rig(make_settings: Callable[..., Settings]) -> Rig:
    """Provide a notifier on fake transport, ticker and clock attached to a fresh alarm board."""
    transport = FakeTransport()
    ticker = Ticker()
    clock = FakeClock()
    notifier = Notifier(
        make_settings(**NTFY), clock, Facts(), transport=transport, monotonic=ticker
    )
    board = AlarmBoard()
    notifier.attach(board)
    return notifier, transport, ticker, board, clock


def test_settings_keep_ntfy_consistent(make_settings: Callable[..., Settings]) -> None:
    """Settings normalise the ntfy URL and reject incomplete or invalid ntfy settings."""
    settings = make_settings(**NTFY)
    assert settings.notify_ntfy_url == "https://ntfy.example.test"
    assert settings.notify_language == "en"
    with pytest.raises(ConfigError):
        make_settings(notify_ntfy_url="https://ntfy.example.test")
    with pytest.raises(ConfigError):
        make_settings(**{**NTFY, "notify_ntfy_url": "ftp://x"})
    with pytest.raises(ConfigError):
        make_settings(**{**NTFY, "notify_ntfy_topic": "has space"})
    assert make_settings(notify_ntfy_url="", notify_ntfy_topic="").notify_ntfy_url is None


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pw@ntfy.example.test",
        "https://ntfy.example.test/?auth=abc",
        "https://ntfy.example.test/#x",
    ],
)
def test_the_ntfy_url_cannot_carry_credentials(
    make_settings: Callable[..., Settings], url: str
) -> None:
    """An ntfy URL carrying credentials, a query or a fragment is rejected."""
    with pytest.raises(ConfigError):
        make_settings(**{**NTFY, "notify_ntfy_url": url})


def test_the_deadman_url_must_be_https_unless_allowed(
    make_settings: Callable[..., Settings],
) -> None:
    """A plain-http dead-man URL is rejected unless explicitly allowed."""
    with pytest.raises(ConfigError):
        make_settings(notify_deadman_url="http://hc.example.test/ping/x")
    allowed = make_settings(
        notify_deadman_url="http://hc.example.test/ping/x", notify_deadman_allow_http=True
    )
    assert allowed.notify_deadman_url is not None


def test_an_alarm_is_sent_at_once_and_its_clearing_once_it_stays_clear(rig: Rig) -> None:
    """An alarm is sent at once and its clearing only after it has stayed clear."""
    notifier, transport, ticker, board, clock = rig
    board.raise_alarm(AlarmCode.LOW_FLOW, "flow 4.1 l/min below 7.0", clock())
    board.raise_alarm(AlarmCode.HEATING_OFF_OUTDOOR, "info only", clock())
    flush(notifier)
    assert transport.titles() == ["ovenbird · Low flow"]
    body = transport.bodies()[0]
    assert body["topic"] == "ovenbird-secret-topic"
    assert body["priority"] == 5
    assert body["message"].splitlines()[0] == "Critical."
    assert body["message"].splitlines()[1].startswith("You: Open closed radiator")
    assert "Details: flow 4.1 l/min below 7.0" in body["message"]
    assert transport.requests[0].url == "https://ntfy.example.test"
    assert transport.requests[0].headers is not None
    assert transport.requests[0].headers["Authorization"] == "Bearer tk_secret_token"
    board.clear(AlarmCode.LOW_FLOW, clock(), "flow back to 9.0 l/min")
    flush(notifier)
    assert len(transport.requests) == 1
    ticker.t = CLEAR_HOLD_S
    flush(notifier)
    assert transport.titles()[1] == "ovenbird · Low flow: resolved"
    assert notifier.status()["health"]["state"] == "ok"


def test_a_flapping_alarm_never_ends_as_cleared_while_active(rig: Rig) -> None:
    """A flapping alarm that ends active never produces a resolved message."""
    notifier, transport, ticker, board, clock = rig
    for minute in range(10):
        ticker.t = minute * 60.0
        board.raise_alarm(AlarmCode.LOW_FLOW, "flow is low", clock())
        flush(notifier)
        ticker.t += 30.0
        board.clear(AlarmCode.LOW_FLOW, clock())
        flush(notifier)
    ticker.t += 10.0
    board.raise_alarm(AlarmCode.LOW_FLOW, "flow is low", clock())
    ticker.t += CLEAR_HOLD_S * 3
    flush(notifier)
    assert transport.titles() == ["ovenbird · Low flow"]
    assert board.is_active(AlarmCode.LOW_FLOW)


def test_a_raise_after_a_sent_clearing_is_never_dropped(rig: Rig) -> None:
    """A raise after a clearing was sent is sent again."""
    notifier, transport, ticker, board, clock = rig
    board.raise_alarm(AlarmCode.LOW_FLOW, "flow is low", clock())
    flush(notifier)
    board.clear(AlarmCode.LOW_FLOW, clock())
    ticker.t = CLEAR_HOLD_S
    flush(notifier)
    ticker.t = CLEAR_HOLD_S + 60.0
    board.raise_alarm(AlarmCode.LOW_FLOW, "flow is low again", clock())
    flush(notifier)
    assert transport.titles() == [
        "ovenbird · Low flow",
        "ovenbird · Low flow: resolved",
        "ovenbird · Low flow",
    ]


def test_a_failed_send_is_retried_with_backoff_and_health_says_failing(
    make_settings: Callable[..., Settings],
) -> None:
    """A failed send is retried with growing delay, then raises a failing alarm until it works."""
    transport = FakeTransport(error=OSError("network unreachable"))
    ticker = Ticker()
    clock = FakeClock()
    notifier = Notifier(
        make_settings(**NTFY), clock, Facts(), transport=transport, monotonic=ticker
    )
    board = AlarmBoard()
    notifier.attach(board)
    board.raise_alarm(AlarmCode.PUMP_ERROR, "H23", clock())
    assert flush(notifier) == RETRY_BASE_S
    health = notifier.health()
    assert health["state"] == "failing"
    assert health["pending"] == ["pump_error"]
    for attempt in range(1, FAILING_AFTER):
        ticker.t += RETRY_BASE_S * 2 ** (attempt - 1)
        flush(notifier)
    assert len(transport.requests) == FAILING_AFTER
    failing = board.get(AlarmCode.NOTIFY_FAILING)
    assert failing is not None
    assert "network unreachable" in failing.message
    transport.error = None
    ticker.t += 3600.0
    flush(notifier)
    assert transport.titles()[-1] == "ovenbird · Pump error"
    assert not board.is_active(AlarmCode.NOTIFY_FAILING)
    assert notifier.health()["state"] == "ok"
    assert notifier.status()["ntfy"]["retries"] == FAILING_AFTER
    assert all("Notifications" not in title for title in transport.titles())


def test_an_alarm_that_came_and_went_while_sending_failed_is_reported_once(
    make_settings: Callable[..., Settings],
) -> None:
    """An alarm that came and went during a failing send is reported once as came and went."""
    transport = FakeTransport(error=OSError("down"))
    ticker = Ticker()
    clock = FakeClock()
    notifier = Notifier(
        make_settings(**NTFY), clock, Facts(), transport=transport, monotonic=ticker
    )
    board = AlarmBoard()
    notifier.attach(board)
    board.raise_alarm(AlarmCode.LOW_FLOW, "flow is low", clock())
    flush(notifier)
    ticker.t = 300.0
    board.clear(AlarmCode.LOW_FLOW, clock())
    transport.error = None
    flush(notifier)
    assert transport.titles()[-1] == "ovenbird · Low flow: came and went"
    assert "It lasted 5 min" in transport.bodies()[-1]["message"]
    ticker.t = 300.0 + CLEAR_HOLD_S * 2
    flush(notifier)
    assert transport.titles().count("ovenbird · Low flow: came and went") == 1
    assert "ovenbird · Low flow: resolved" not in transport.titles()


def test_critical_alarms_are_never_starved_by_warnings(rig: Rig) -> None:
    """Warnings are rate limited without blocking a critical alarm."""
    notifier, transport, ticker, board, clock = rig
    warnings = [code for code in AlarmCode if code.value.startswith("room_")]
    for index in range(RATE_LIMITS[next(iter(RATE_LIMITS))] * 3):
        ticker.t = float(index)
        code = warnings[index % len(warnings)]
        board.raise_alarm(code, "warning", clock())
        flush(notifier)
        board.clear(code, clock())
        ticker.t = float(index) + CLEAR_HOLD_S
        flush(notifier)
    sent_before = len(transport.requests)
    board.raise_alarm(AlarmCode.PUMP_ERROR, "H23", clock())
    flush(notifier)
    assert len(transport.requests) == sent_before + 1
    assert transport.titles()[-1] == "ovenbird · Pump error"
    status = notifier.status()["ntfy"]
    assert status["deferred"] > 0
    assert status["rate_limits"] == {"critical": 30, "warning": 20, "info": 20}


def test_messages_are_in_the_configured_language(make_settings: Callable[..., Settings]) -> None:
    """Messages are in the configured language and leave out the client address."""
    transport = FakeTransport()
    clock = FakeClock()
    notifier = Notifier(
        make_settings(**NTFY, notify_language="nl", notify_events=True),
        clock,
        Facts(),
        transport=transport,
        monotonic=Ticker(),
    )
    board = AlarmBoard()
    notifier.attach(board)
    board.raise_alarm(AlarmCode.FOREIGN_WRITER, "water setpoint 35, ovenbird set 31", clock())
    notifier.on_audit(ACTOR, "mode_pause", {"reason": "weg"})
    flush(notifier)
    raised, paused = transport.bodies()
    assert raised["title"] == "ovenbird · Iemand anders wijzigde de pomp"
    assert raised["message"].startswith("Waarschuwing.\nJij: Zoek uit wie de pomp wijzigde")
    assert paused["title"] == "ovenbird · Regeling gepauzeerd"
    assert paused["message"] == "door admin: weg"
    assert "10.0.0.2" not in json.dumps(transport.bodies())


def test_events_are_sent_only_when_enabled(make_settings: Callable[..., Settings]) -> None:
    """Audit events are only queued for notification when events are enabled and relevant."""
    transport = FakeTransport()
    quiet = Notifier(make_settings(**NTFY), FakeClock(), Facts(), transport=transport)
    quiet.on_audit(ACTOR, "mode_pause", {"reason": "away"})
    assert not quiet.event_queue
    loud = Notifier(
        make_settings(**NTFY, notify_events=True), FakeClock(), Facts(), transport=transport
    )
    loud.on_audit(ACTOR, "mode_pause", {"reason": "away"})
    loud.on_audit(ACTOR, "control_release", {"phase": "started"})
    loud.on_audit(ACTOR, "control_release", {"phase": "finished", "outcome": "ok"})
    loud.on_audit(ACTOR, "config_apply", {})
    assert len(loud.event_queue) == 2


def test_the_state_survives_a_restart_and_is_replayed(
    make_settings: Callable[..., Settings],
) -> None:
    """Notified state survives a restart so only new alarms and resolved ones are sent."""
    facts = Facts()
    transport = FakeTransport()
    clock = FakeClock()
    first = Notifier(make_settings(**NTFY), clock, facts, transport=transport, monotonic=Ticker())
    board = AlarmBoard()
    first.attach(board)
    board.raise_alarm(AlarmCode.LOW_FLOW, "flow is low", clock())
    board.raise_alarm(AlarmCode.PUMP_ERROR, "H23", clock())
    flush(first)
    assert len(transport.requests) == 2
    ticker = Ticker()
    second = Notifier(make_settings(**NTFY), clock, facts, transport=transport, monotonic=ticker)
    after = AlarmBoard()
    after.raise_alarm(AlarmCode.PUMP_ERROR, "H23", clock())
    after.raise_alarm(AlarmCode.CONFIG_RESET, "lost", clock())
    second.attach(after)
    flush(second)
    assert transport.titles()[2:] == ["ovenbird · Configuration reset"]
    ticker.t = CLEAR_HOLD_S
    flush(second)
    assert transport.titles()[3:] == ["ovenbird · Low flow: resolved"]


def test_config_reset_at_start_reaches_the_notifier(
    make_settings: Callable[..., Settings], tmp_path: Path
) -> None:
    """A config reset found at start is notified through the service's notifier."""
    data = tmp_path / "data"
    data.mkdir()
    (data / MARKER_NAME).write_text("x\n")
    transport = FakeTransport()
    service = build_service(make_settings(**NTFY), notify_transport=transport)
    try:
        assert service.control.alarms.is_active(AlarmCode.CONFIG_RESET)
        owners = [
            getattr(listener, "__self__", None) for listener in service.control.alarms.listeners
        ]
        app_notifier = next(owner for owner in owners if isinstance(owner, Notifier))
        assert list(app_notifier.pending) == ["config_reset"]
        flush(app_notifier)
        assert transport.titles() == ["ovenbird · Configuration reset"]
    finally:
        assert service.config is not None
        service.config.close()


def test_a_failed_send_never_leaks_the_secret(make_settings: Callable[..., Settings]) -> None:
    """A failed send reports a truncated error without the topic or token."""
    long = "x" * (MAX_ERROR - 20)
    transport = FakeTransport(error=OSError(f"{long} ovenbird-secret-topic tk_secret_token"))
    facts = Facts()
    notifier = Notifier(make_settings(**NTFY), FakeClock(), facts, transport=transport)
    result = asyncio.run(notifier.send_test(ACTOR))
    assert result["ok"] is False
    assert result["by"] == "admin"
    text = json.dumps(notifier.status())
    assert "secret" not in text
    assert "ovenbird-se" not in text
    assert notifier.last_test() == result
    assert notifier.health()["state"] == "failing"
    assert Notifier(make_settings(**NTFY), FakeClock(), facts).last_test() == result


def test_redirects_are_not_followed() -> None:
    """The notification transport does not follow redirects."""
    handler: Any = _NoRedirect()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://elsewhere") is None
    assert any(isinstance(h, _NoRedirect) for h in getattr(OPENER, "handlers", []))


def test_tests_have_their_own_rate_limit(make_settings: Callable[..., Settings]) -> None:
    """Test notifications are limited to one per spacing interval."""
    ticker = Ticker()
    notifier = Notifier(
        make_settings(**NTFY), FakeClock(), Facts(), transport=FakeTransport(), monotonic=ticker
    )
    asyncio.run(notifier.send_test(ACTOR))
    ticker.t = TEST_SPACING_S / 2
    with pytest.raises(Exception, match="retry in"):
        asyncio.run(notifier.send_test(ACTOR))
    ticker.t = TEST_SPACING_S
    assert asyncio.run(notifier.send_test(ACTOR))["ok"] is True


def test_the_deadman_pings_only_while_healthy(make_settings: Callable[..., Settings]) -> None:
    """The dead-man ping is sent only while healthy and the status hides its URL."""
    transport = FakeTransport()
    reason: list[str | None] = [None]
    notifier = Notifier(
        make_settings(notify_deadman_url=DEADMAN),
        FakeClock(),
        Facts(),
        transport=transport,
        healthy=lambda: reason[0],
    )
    assert not notifier.configured
    assert asyncio.run(notifier.ping_once()) is True
    reason[0] = "MQTT is disconnected"
    assert asyncio.run(notifier.ping_once()) is False
    assert [r.method for r in transport.requests] == ["GET"]
    assert transport.requests[0].url == DEADMAN
    status = notifier.status()["deadman"]
    assert status["pings"] == 1
    assert status["last_skip"] == "MQTT is disconnected"
    assert status["server"] == "hc.example.test"
    assert notifier.health()["deadman_state"] == "skipped"
    assert "secret-uuid" not in json.dumps(notifier.status())


def test_notification_endpoints(make_settings: Callable[..., Settings]) -> None:
    """The notification endpoints report status, require the request marker and rate limit tests."""
    settings = make_settings(**NTFY, http_host="0.0.0.0", admin_password=ADMIN)
    clock = FakeClock()
    runtime = Runtime(clock=clock)
    manager = ConfigManager.open(settings, clock)
    transport = FakeTransport()
    facts = Facts(manager.store)
    notifier = Notifier(settings, clock, facts, transport=transport)
    supervision = Supervision(runtime, lambda: settings, None, manager, notifier, facts, clock())
    mark = {**basic("admin", ADMIN), "X-Ovenbird-Request": "1"}
    app = create_app(runtime, settings, config=manager, supervision=supervision)
    with TestClient(app) as client:
        status = client.get("/api/v1/notifications/status", headers=basic("admin", ADMIN))
        assert status.json()["ntfy"]["configured"] is True
        assert status.json()["health"]["state"] == "untested"
        assert "secret" not in status.text
        unmarked = client.post("/api/v1/notifications/test", json={}, headers=basic("admin", ADMIN))
        assert unmarked.status_code == 403
        sent = client.post("/api/v1/notifications/test", json={}, headers=mark)
        assert sent.status_code == 200
        assert sent.json()["test"]["ok"] is True
        assert sent.json()["status"]["health"]["state"] == "ok"
        assert transport.titles()[0] == "ovenbird · test notification"
        again = client.post("/api/v1/notifications/test", json={}, headers=mark)
        assert again.status_code == 429
        assert again.json()["detail"]["code"] == "test_rate"
        assert int(again.headers["Retry-After"]) >= 1
        assert len(transport.requests) == 1
        clock.advance(1)
        audit = client.get("/api/v1/audit", headers=basic("admin", ADMIN)).json()["events"]
        assert any(event["action"] == "notify_test" for event in audit)


def test_test_endpoint_refuses_without_ntfy(make_settings: Callable[..., Settings]) -> None:
    """Testing notifications without ntfy answers 409 and status shows it as not configured."""
    settings = make_settings(http_host="0.0.0.0", admin_password=ADMIN)
    with TestClient(create_app(Runtime(clock=FakeClock()), settings)) as client:
        mark = {**basic("admin", ADMIN), "X-Ovenbird-Request": "1"}
        assert client.post("/api/v1/notifications/test", json={}, headers=mark).status_code == 409
        body = client.get("/api/v1/notifications/status", headers=basic("admin", ADMIN)).json()
        assert body["ntfy"]["configured"] is False

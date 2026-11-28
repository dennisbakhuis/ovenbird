"""Notifications: ntfy messages for alarms and events, and an external dead-man ping.

**ntfy** (``OVENBIRD_NOTIFY_NTFY_URL`` + ``_TOPIC``, optional ``_TOKEN``; environment
or options file only, never the configuration store): every raised alarm at or above
``OVENBIRD_NOTIFY_MIN_SEVERITY`` (``warning``) is sent as one JSON message to the
server (``POST <url>`` with ``topic``, ``title``, ``message``, ``priority``, ``tags``;
the token as ``Authorization: Bearer``), its clearing too when the raise was sent.
Titles and bodies are in ``OVENBIRD_NOTIFY_LANGUAGE`` (``en`` or ``nl``): the alarm's
display name, what ovenbird does and what the person can do. With
``OVENBIRD_NOTIFY_EVENTS`` the hold, wood-stove, pause/resume and release events are
sent as well.

**Per-alarm state.** The notifier keeps, per alarm code, what the phone was last told
(raised or cleared; kept in ``config.db`` so a restart neither repeats nor loses it)
and the one message still to deliver. A raise is sent at once; a clearing only after
the alarm has stayed clear for :data:`CLEAR_HOLD_S`, so a flapping alarm sends one
raise and, once it stays away, one clearing, and never ends as "cleared" while it is
active. A raise is never dropped after a clearing was sent. An alarm that came and
went before its raise could be delivered is sent once as "came and went".
:meth:`Notifier.attach` registers the notifier on the alarm board and replays the
active alarms (and the clearings of alarms that were told raised before a restart).

**Delivery.** Messages wait in a bounded in-memory outbox (one entry per alarm code,
:data:`EVENT_QUEUE_SIZE` events) and are sent off the event loop, critical first. A
failed send is retried with back-off (:data:`RETRY_BASE_S` doubling up to
:data:`RETRY_MAX_S`): warning and critical states until they are delivered or
superseded, info states and events a few times. Rate limits are per severity
(:data:`RATE_LIMITS` per hour; critical has its own budget, so warnings never starve
it); an alarm state over the limit waits, an event over it is dropped and counted.
After :data:`FAILING_AFTER` failed sends in a row ``notify_failing`` (warning) is
raised on the alarm board (never sent itself); the next delivered message clears it.
:meth:`Notifier.health` is the one verdict the status tile and the trial checklist
both read. ``POST api/v1/notifications/test`` sends a test at once, at most one per
:data:`TEST_SPACING_S` and :data:`TEST_PER_HOUR` per hour; its outcome is kept across
restarts.

**Dead-man ping** (:mod:`ovenbird.notify.deadman`): an HTTP ``GET`` every interval
while the service is healthy; the notifier runs it and reports its status.

All HTTP goes through a :data:`~ovenbird.notify.transport.Transport` (stdlib
``urllib`` by default, only ``http``/``https``, redirects are not followed); tests
pass a fake. Secrets (topic,
token, dead-man URL) never appear in the status or the logs; error texts are redacted
before they are shortened.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit

from ovenbird.clock import Clock, Sleep, iso_z
from ovenbird.control.alarms import (
    ENVELOPE_JOURNAL_CODE,
    HOLD_JOURNAL_CODE,
    SEVERITY,
    SEVERITY_RANK,
    AlarmBoard,
    AlarmCode,
    AlarmEvent,
    AlarmEventKind,
    Severity,
)
from ovenbird.notify.deadman import DeadmanPing
from ovenbird.notify.text import Language, alarm_text, word
from ovenbird.notify.transport import (
    HttpRequest,
    NotifyError,
    Transport,
    host_of,
    urllib_transport,
)
from ovenbird.stove.request import STOVE_JOURNAL_CODE
from ovenbird.system.privacy import public_name

if TYPE_CHECKING:
    from ovenbird.config import Settings
    from ovenbird.configstore import Actor
    from ovenbird.system.facts import Facts

LOGGER = logging.getLogger("ovenbird.notify")
CLEAR_HOLD_S: Final = 600.0
RATE_WINDOW_S: Final = 3600.0
RATE_LIMITS: Final = {Severity.CRITICAL: 30, Severity.WARNING: 20, Severity.INFO: 20}
RATE_LIMIT: Final = RATE_LIMITS[Severity.WARNING]
EVENT_QUEUE_SIZE: Final = 50
RETRY_BASE_S: Final = 30.0
RETRY_MAX_S: Final = 900.0
INFO_ATTEMPTS: Final = 5
EVENT_ATTEMPTS: Final = 3
FAILING_AFTER: Final = 3
TEST_SPACING_S: Final = 30.0
TEST_PER_HOUR: Final = 10
TEST_KEY: Final = "notify_test"
STATE_KEY: Final = "notify_state"
DELIVERY_KEY: Final = "notify_delivery"
MAX_ERROR: Final = 200
MIN_SECRET: Final = 4
PRIORITY: Final = {Severity.INFO: 3, Severity.WARNING: 4, Severity.CRITICAL: 5}
TAGS: Final = {Severity.INFO: "information_source", Severity.WARNING: "warning"}
CRITICAL_TAG: Final = "rotating_light"
EVENT_ACTIONS: Final = frozenset({"mode_pause", "mode_resume", "control_release", "hold_release"})
EVENT_JOURNAL_CODES: Final = frozenset(
    {HOLD_JOURNAL_CODE, STOVE_JOURNAL_CODE, ENVELOPE_JOURNAL_CODE}
)
SILENT_CODES: Final = frozenset({AlarmCode.NOTIFY_FAILING.value})
HEALTH_STATES: Final = ("not_configured", "untested", "ok", "failing")
RAISED: Final = "raised"
CLEARED: Final = "cleared"
BRIEF: Final = "brief"


class TestLimitError(Exception):
    """A test notification was asked for too soon after the last one.

    Parameters
    ----------
    retry_after_s
        Seconds until the next test is allowed.
    """

    def __init__(self, retry_after_s: float) -> None:
        super().__init__(f"a test notification was sent recently; retry in {retry_after_s:.0f} s")
        self.retry_after_s = retry_after_s


@dataclass(slots=True)
class Message:
    """One ntfy message in the outbox.

    Parameters
    ----------
    title
        Title.
    text
        Body text.
    priority
        ntfy priority 1-5.
    tags
        ntfy tags (emoji short codes).
    key
        Alarm code of an alarm state; ``None`` for events and tests.
    state
        ``raised``, ``cleared`` or ``brief`` (came and went) for an alarm state.
    severity
        Severity of the alarm (the rate-limit budget of a raise).
    due
        Monotonic time it may be sent.
    attempts
        Failed attempts so far.
    max_attempts
        Attempts before it is given up; ``None`` retries until delivered or superseded.
    since
        Monotonic time the alarm was raised (for "came and went").
    """

    title: str
    text: str
    priority: int = 3
    tags: tuple[str, ...] = ()
    key: str | None = None
    state: str | None = None
    severity: Severity = Severity.INFO
    due: float = 0.0
    attempts: int = 0
    max_attempts: int | None = EVENT_ATTEMPTS
    since: float = 0.0
    deferred: bool = False

    @property
    def budget(self) -> Severity:
        """The rate-limit budget: the alarm's severity for a raise, else info."""
        return self.severity if self.state == RAISED else Severity.INFO


class Notifier:
    """Send ntfy messages and dead-man pings; report their status and health.

    Parameters
    ----------
    settings
        Settings (ntfy server, topic, token, severity, events, language, dead-man).
    clock
        Service clock (status times).
    facts
        Keeps the last test, the per-alarm state and the delivery health across restarts.
    transport
        HTTP transport; the stdlib one when omitted.
    healthy
        Returns ``None`` while the service is healthy, else why not (dead-man).
    sleep
        Sleeps between dead-man pings.
    monotonic
        Time source of the outbox, rate limits and back-off.
    """

    def __init__(
        self,
        settings: Settings,
        clock: Clock,
        facts: Facts,
        *,
        transport: Transport | None = None,
        healthy: Callable[[], str | None] | None = None,
        sleep: Sleep | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.clock = clock
        self.facts = facts
        self.transport = transport or urllib_transport
        self.healthy = healthy
        self._sleep: Callable[[float], Awaitable[None]] = sleep or asyncio.sleep
        self._monotonic = monotonic
        self.url = settings.notify_ntfy_url
        topic = settings.notify_ntfy_topic
        token = settings.notify_ntfy_token
        deadman = settings.notify_deadman_url
        self._topic = None if topic is None else topic.get_secret_value()
        self._token = None if token is None else token.get_secret_value()
        self.language: Language = settings.notify_language
        self.min_severity = Severity(settings.notify_min_severity)
        self.events = settings.notify_events
        self.deadman = DeadmanPing(
            None if deadman is None else deadman.get_secret_value(),
            settings.notify_deadman_interval_s,
        )
        self.board: AlarmBoard | None = None
        self.pending: dict[str, Message] = {}
        self.event_queue: deque[Message] = deque()
        self._wake = asyncio.Event()
        self._sent_times: dict[Severity, deque[float]] = {s: deque() for s in RATE_LIMITS}
        self._test_times: deque[float] = deque()
        self._notified = self._load_notified()
        delivery = facts.get(DELIVERY_KEY)
        stored = delivery if isinstance(delivery, dict) else {}
        self.sent = 0
        self.suppressed = 0
        self.dropped = 0
        self.deferred = 0
        self.retries = 0
        self.failures_in_row = int(stored.get("failures_in_row") or 0)
        self.failing_since: str | None = stored.get("failing_since")
        self.last_sent: dict[str, Any] | None = stored.get("last_sent")
        self.last_error: dict[str, Any] | None = stored.get("last_error")

    @property
    def configured(self) -> bool:
        """Whether ntfy is configured."""
        return self.url is not None and self._topic is not None

    @property
    def deadman_configured(self) -> bool:
        """Whether a dead-man URL is configured."""
        return self.deadman.configured

    def secrets(self) -> tuple[str, ...]:
        """Return the secret values and the dead-man URL's path (for redaction)."""
        url = self.deadman.url
        values = [self._topic, self._token, url]
        if url is not None:
            values.append(urlsplit(url).path.strip("/"))
        found = {value for value in values if value and len(value) >= MIN_SECRET}
        return tuple(sorted(found, key=len, reverse=True))

    def _load_notified(self) -> set[str]:
        """Return the alarm codes stored as already told raised."""
        stored = self.facts.get(STATE_KEY)
        if not isinstance(stored, dict):
            return set()
        raised = stored.get("raised")
        return {str(code) for code in raised} if isinstance(raised, list) else set()

    def _store_notified(self) -> None:
        """Store the alarm codes told raised."""
        self.facts.set(STATE_KEY, {"raised": sorted(self._notified)})

    def attach(self, board: AlarmBoard) -> None:
        """Listen to ``board`` and replay what the phone has not been told yet.

        Every active alarm at or above the minimum severity that was not told raised
        is offered; an alarm told raised before a restart that is no longer active
        gets its clearing (after :data:`CLEAR_HOLD_S`, so a condition that comes back
        while the service starts is not cleared at all).
        """
        self.board = board
        board.listeners.append(self.on_alarm)
        now = self._monotonic()
        active = {alarm.code.value for alarm in board.active()}
        for alarm in board.active():
            if alarm.code.value in SILENT_CODES or not self._qualifies(alarm.severity):
                continue
            if alarm.code.value not in self._notified:
                self._put(self._raised(alarm.code.value, alarm.severity, alarm.message, now))
        for code in sorted(self._notified - active):
            severity = _severity_of(code)
            self._put(self._cleared(code, severity, "", now + CLEAR_HOLD_S))
        if self.failures_in_row >= FAILING_AFTER:
            self._raise_failing()

    def _qualifies(self, severity: Severity) -> bool:
        """Return whether a severity reaches the minimum to notify."""
        return SEVERITY_RANK[severity] >= SEVERITY_RANK[self.min_severity]

    def _raised(self, code: str, severity: Severity, detail: str, now: float) -> Message:
        """Return the message telling that an alarm is raised.

        Parameters
        ----------
        code
            Alarm code.
        severity
            Severity of the alarm.
        detail
            Detail text of the alarm.
        now
            Current Unix time.
        """
        lang = self.language
        text = alarm_text(code, lang)
        lines = [f"{word(severity.value, lang)}."]
        if text.you:
            lines.append(f"{word('you', lang)} {text.you}")
        if text.now:
            lines.append(f"{word('ovenbird', lang)} {text.now}")
        if detail:
            lines.append(f"{word('details', lang)} {detail}")
        tag = CRITICAL_TAG if severity is Severity.CRITICAL else TAGS[severity]
        return Message(
            f"ovenbird · {text.name}",
            "\n".join(lines),
            PRIORITY[severity],
            (tag,),
            key=code,
            state=RAISED,
            severity=severity,
            due=now,
            max_attempts=INFO_ATTEMPTS if severity is Severity.INFO else None,
            since=now,
        )

    def _cleared(self, code: str, severity: Severity, why: str, due: float) -> Message:
        """Return the message telling that an alarm cleared.

        Parameters
        ----------
        code
            Alarm code.
        severity
            Severity of the alarm.
        why
            Reason it cleared; may be empty.
        due
            Unix time the message may be sent from.
        """
        lang = self.language
        text = alarm_text(code, lang)
        body = f"{word('details', lang)} {why}" if why else word("resolved", lang)
        return Message(
            f"ovenbird · {text.name}: {word('resolved', lang)}",
            body,
            2,
            ("white_check_mark",),
            key=code,
            state=CLEARED,
            severity=severity,
            due=due,
            max_attempts=INFO_ATTEMPTS if severity is Severity.INFO else None,
        )

    def _brief(self, raised: Message, now: float) -> Message:
        """Return the message telling that an alarm came and went within the hold."""
        lang = self.language
        text = alarm_text(raised.key or "", lang)
        minutes = max(1, round((now - raised.since) / 60.0))
        body = word("lasted", lang).format(minutes=minutes) + "\n" + raised.text
        return Message(
            f"ovenbird · {text.name}: {word('brief', lang)}",
            body,
            3,
            ("white_check_mark",),
            key=raised.key,
            state=BRIEF,
            severity=raised.severity,
            due=now,
            max_attempts=INFO_ATTEMPTS if raised.severity is Severity.INFO else None,
            since=raised.since,
        )

    def _put(self, message: Message) -> None:
        """Queue a message, replacing an older one for the same alarm."""
        if not self.configured or message.key is None:
            return
        self.pending[message.key] = message
        self._wake.set()

    def _offer_event(self, message: Message) -> None:
        """Queue a one-off event message, dropping the oldest when full."""
        if not self.configured:
            return
        if len(self.event_queue) >= EVENT_QUEUE_SIZE:
            self.event_queue.popleft()
            self.dropped += 1
        message.due = self._monotonic()
        self.event_queue.append(message)
        self._wake.set()

    def on_alarm(self, event: AlarmEvent) -> None:
        """Turn an alarm transition into the alarm's next message (an alarm-board listener).

        Parameters
        ----------
        event
            Alarm transition to turn into a message.
        """
        lang = self.language
        if event.code in EVENT_JOURNAL_CODES:
            if self.events:
                self._offer_event(
                    Message(
                        f"ovenbird · {word(event.code, lang)}: {word(event.event.value, lang)}",
                        event.message,
                        3,
                        ("information_source",),
                    )
                )
            return
        code = event.code
        if code in SILENT_CODES:
            return
        now = self._monotonic()
        if event.event is AlarmEventKind.RAISED:
            if self._qualifies(event.severity):
                self._put(self._raised(code, event.severity, event.message, now))
            return
        if event.event is not AlarmEventKind.CLEARED:
            return
        waiting = self.pending.get(code)
        if code in self._notified:
            self._put(self._cleared(code, event.severity, event.message, now + CLEAR_HOLD_S))
        elif waiting is not None and waiting.state == RAISED:
            self._put(self._brief(waiting, now))

    def on_audit(self, actor: Actor, action: str, detail: Mapping[str, Any]) -> None:
        """Send pause, resume, release and hold-release events when events are on."""
        if not self.events or action not in EVENT_ACTIONS:
            return
        if action == "control_release" and detail.get("phase") != "finished":
            return
        lang = self.language
        reason = detail.get("reason")
        text = word("by", lang).format(who=public_name(actor.name))
        if isinstance(reason, str):
            text += f": {reason}"
        if action == "control_release":
            outcome = word(f"outcome_{detail.get('outcome')}", lang)
            text += f" ({outcome}, {detail.get('duration_s')} s)"
        title = f"ovenbird · {word(action, lang)}"
        self._offer_event(Message(title, text, 3, ("information_source",)))

    def _request(self, message: Message) -> HttpRequest:
        """Return the ntfy request for a message."""
        assert self.url is not None
        body = {
            "topic": self._topic,
            "title": message.title,
            "message": message.text,
            "priority": message.priority,
            "tags": list(message.tags),
        }
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return HttpRequest(
            "POST", self.url, json.dumps(body, ensure_ascii=False).encode("utf-8"), headers
        )

    def _now_iso(self) -> str:
        """Return the current time as ISO text."""
        return iso_z(self.clock().wall)

    def _redact(self, text: str) -> str:
        """Return ``text`` with every secret replaced."""
        for secret in self.secrets():
            text = text.replace(secret, "[redacted]")
        return text

    def _error_text(self, exc: BaseException) -> str:
        """Return an error as short, redacted text."""
        return self._redact(f"{type(exc).__name__}: {exc}")[:MAX_ERROR]

    def _store_delivery(self) -> None:
        """Store the delivery state: failure streak, last error and last sent."""
        self.facts.set(
            DELIVERY_KEY,
            {
                "failures_in_row": self.failures_in_row,
                "failing_since": self.failing_since,
                "last_sent": self.last_sent,
                "last_error": self.last_error,
            },
        )

    def _raise_failing(self) -> None:
        """Raise the alarm for failing notification delivery."""
        board = self.board
        if board is None:
            return
        error = (self.last_error or {}).get("error")
        board.raise_alarm(
            AlarmCode.NOTIFY_FAILING,
            f"{self.failures_in_row} messages in a row could not be sent to ntfy: {error}",
            self.clock(),
            {"failures": self.failures_in_row, "since": self.failing_since, "error": error},
        )

    async def deliver(self, message: Message) -> str | None:
        """Send one message now; returns ``None`` on success, else the (redacted) error.

        Parameters
        ----------
        message
            Message to send.
        """
        if not self.configured:
            return "ntfy is not configured"
        try:
            status = await asyncio.to_thread(self.transport, self._request(message))
            if not 200 <= status < 300:
                raise NotifyError(f"HTTP {status}")
        except Exception as exc:
            error = self._error_text(exc)
            at = self._now_iso()
            self.last_error = {"at": at, "error": error}
            self.failures_in_row += 1
            if self.failing_since is None:
                self.failing_since = at
            LOGGER.warning("ntfy message %r not sent: %s", message.title, error)
            self._store_delivery()
            if self.failures_in_row >= FAILING_AFTER:
                self._raise_failing()
            return error
        self.sent += 1
        self.last_sent = {"at": self._now_iso(), "title": message.title}
        self.failures_in_row = 0
        self.failing_since = None
        self._store_delivery()
        if self.board is not None:
            self.board.clear(AlarmCode.NOTIFY_FAILING, self.clock(), "a message was delivered")
        return None

    def _budget_left(self, budget: Severity, now: float) -> bool:
        """Return whether the rate budget of a severity allows another message."""
        times = self._sent_times[budget]
        while times and now - times[0] >= RATE_WINDOW_S:
            times.popleft()
        return len(times) < RATE_LIMITS[budget]

    def _redundant(self, message: Message) -> bool:
        """Return whether the phone already knows what a message says."""
        if message.state == RAISED:
            return message.key in self._notified
        if message.state == CLEARED:
            return message.key not in self._notified
        return False

    def _due(self, now: float) -> Message | None:
        """Return the most urgent message that is due, or ``None``."""
        ready = [m for m in self.pending.values() if m.due <= now]
        ready.extend(m for m in self.event_queue if m.due <= now)
        if not ready:
            return None
        return min(ready, key=lambda m: (-SEVERITY_RANK[m.budget], m.due))

    def _discard(self, message: Message) -> None:
        """Remove a message from its queue."""
        if message.key is not None:
            if self.pending.get(message.key) is message:
                del self.pending[message.key]
        elif message in self.event_queue:
            self.event_queue.remove(message)

    def _delivered(self, message: Message) -> None:
        """Record that a message reached the phone."""
        if message.state == RAISED and message.key is not None:
            self._notified.add(message.key)
            self._store_notified()
        elif message.state == CLEARED and message.key is not None:
            self._notified.discard(message.key)
            self._store_notified()

    async def _attempt(self, message: Message, now: float) -> None:
        """Try to send a due message, keeping it queued when it fails or the budget is spent.

        Parameters
        ----------
        message
            Message to send.
        now
            Current Unix time.
        """
        if message.key is not None and self._redundant(message):
            self._discard(message)
            return
        budget = message.budget
        if not self._budget_left(budget, now):
            if message.key is None:
                self._discard(message)
                self.suppressed += 1
                return
            if not message.deferred:
                message.deferred = True
                self.deferred += 1
            message.due = max(now + 1.0, self._sent_times[budget][0] + RATE_WINDOW_S)
            return
        self._sent_times[budget].append(now)
        error = await self.deliver(message)
        if error is None:
            self._discard(message)
            self._delivered(message)
            return
        message.attempts += 1
        current = message.key is None or self.pending.get(message.key) is message
        if not current:
            return
        if message.max_attempts is not None and message.attempts >= message.max_attempts:
            self._discard(message)
            self.dropped += 1
            return
        self.retries += 1
        delay = min(RETRY_MAX_S, RETRY_BASE_S * 2.0 ** (message.attempts - 1))
        message.due = self._monotonic() + delay

    async def flush(self) -> float | None:
        """Send every due message (critical first); returns seconds until the next is due."""
        while True:
            now = self._monotonic()
            message = self._due(now)
            if message is None:
                break
            await self._attempt(message, now)
        waiting = [m.due for m in self.pending.values()] + [m.due for m in self.event_queue]
        if not waiting:
            return None
        return max(0.0, min(waiting) - self._monotonic())

    async def run(self) -> None:
        """Deliver the outbox forever (a supervised component)."""
        while True:
            self._wake.clear()
            wait = await self.flush()
            try:
                async with asyncio.timeout(wait):
                    await self._wake.wait()
            except TimeoutError:
                pass

    def _check_test_rate(self, now: float) -> None:
        """Raise when a test message was sent too recently."""
        times = self._test_times
        while times and now - times[0] >= RATE_WINDOW_S:
            times.popleft()
        if times and now - times[-1] < TEST_SPACING_S:
            raise TestLimitError(TEST_SPACING_S - (now - times[-1]))
        if len(times) >= TEST_PER_HOUR:
            raise TestLimitError(times[0] + RATE_WINDOW_S - now)

    async def send_test(self, actor: Actor) -> dict[str, Any]:
        """Send a test message now and keep its outcome (``POST api/v1/notifications/test``).

        Raises
        ------
        TestLimitError
            Within :data:`TEST_SPACING_S` of the last test or after
            :data:`TEST_PER_HOUR` tests in the last hour.
        """
        now = self._monotonic()
        self._check_test_rate(now)
        self._test_times.append(now)
        lang = self.language
        who = public_name(actor.name)
        error = await self.deliver(
            Message(
                f"ovenbird · {word('test_title', lang)}",
                word("test_body", lang).format(who=who),
                3,
                ("white_check_mark",),
            )
        )
        result = {"at": self._now_iso(), "ok": error is None, "error": error, "by": who}
        self.facts.set(TEST_KEY, result)
        return result

    def last_test(self) -> dict[str, Any] | None:
        """Return the last test's outcome (kept across restarts; the name without address)."""
        stored = self.facts.get(TEST_KEY)
        if not isinstance(stored, dict):
            return None
        return {**stored, "by": public_name(stored.get("by"))}

    def health(self) -> dict[str, Any]:
        """Return whether alarms reach the phone: the one verdict of the tile and the checklist.

        Returns
        -------
        dict
            ``state`` (``not_configured``, ``untested``, ``ok`` or ``failing``),
            ``reason``, ``failing_since``, ``failures_in_row``, ``pending`` (alarm
            states not yet delivered) and the dead-man's ``deadman_state``
            (``not_configured``, ``waiting``, ``ok``, ``failing``, ``skipped``).
        """
        test = self.last_test()
        state, reason = "ok", None
        if not self.configured:
            state, reason = "not_configured", "ntfy is not configured"
        elif self.failures_in_row > 0:
            error = (self.last_error or {}).get("error")
            state, reason = "failing", f"the last {self.failures_in_row} sends failed: {error}"
        elif test is not None and not test.get("ok") and not self._sent_after(test.get("at")):
            state, reason = "failing", f"the last test failed: {test.get('error')}"
        elif test is None and self.last_sent is None:
            state, reason = "untested", "no test notification sent yet"
        return {
            "state": state,
            "reason": reason,
            "failing_since": self.failing_since,
            "failures_in_row": self.failures_in_row,
            "pending": sorted(self.pending),
            "deadman_state": self.deadman.state(),
        }

    def _sent_after(self, at: Any) -> bool:
        """Return whether the last message was sent after ISO time ``at``."""
        sent = (self.last_sent or {}).get("at")
        return isinstance(sent, str) and isinstance(at, str) and sent > at

    async def ping_once(self) -> bool:
        """Ping the dead-man URL if the service is healthy; ``True`` when a ping succeeded."""
        return await self.deadman.ping(
            self.transport, self.healthy, self._now_iso, self._error_text
        )

    async def run_deadman(self) -> None:
        """Ping every interval forever (a supervised component)."""
        while True:
            await self.ping_once()
            await self._sleep(self.deadman.interval_s)

    def status(self) -> dict[str, Any]:
        """Return the body of ``GET api/v1/notifications/status`` (no secrets)."""
        reason = self.healthy() if self.healthy is not None else None
        return {
            "ntfy": {
                "configured": self.configured,
                "server": host_of(self.url),
                "token": self._token is not None,
                "min_severity": self.min_severity.value,
                "events": self.events,
                "language": self.language,
                "sent": self.sent,
                "suppressed": self.suppressed,
                "dropped": self.dropped,
                "deferred": self.deferred,
                "retries": self.retries,
                "queued": len(self.pending) + len(self.event_queue),
                "last_sent": self.last_sent,
                "last_error": self.last_error,
                "last_test": self.last_test(),
                "rate_limit_per_hour": RATE_LIMIT,
                "rate_limits": {severity.value: limit for severity, limit in RATE_LIMITS.items()},
                "clear_hold_s": CLEAR_HOLD_S,
                "test_spacing_s": TEST_SPACING_S,
            },
            "deadman": self.deadman.status(reason),
            "health": self.health(),
        }


def _severity_of(code: str) -> Severity:
    """Return the severity of an alarm code, a warning when it is unknown."""
    try:
        return SEVERITY[AlarmCode(code)]
    except ValueError:
        return Severity.WARNING

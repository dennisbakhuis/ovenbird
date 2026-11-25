"""Commands, life-cycle events and records of the HeishaMon command adapter."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Final

from ovenbird.clock import iso_z
from ovenbird_core import (
    PUMP_SETTINGS,
    HeishaSignal,
    Instant,
    PumpSetting,
    SignalId,
    SignalView,
)
from ovenbird_core.control import IntentKind
from ovenbird_core.control.observe import as_number

LOGGER = logging.getLogger("ovenbird.control.adapter")
VERIFY_SIGNALS: Final[dict[IntentKind, SignalId]] = {
    IntentKind.WATER_SETPOINT: HeishaSignal.Z1_WATER_TARGET_TEMP,
    IntentKind.MAX_PUMP_DUTY: HeishaSignal.MAX_PUMP_DUTY,
    IntentKind.QUIET_MODE: HeishaSignal.QUIET_MODE_LEVEL,
}
SAFETY_REASON: Final = "safety_correction"
OPERATOR_REASON: Final = "operator"
OPERATOR_PREFIX: Final = "operator: "
RESTORE_REASON: Final = "release"
RESTORE_PREFIX: Final = "release: "
OPERATOR_WINDOW_S: Final = 86_400.0

type Reader = Callable[[SignalId], SignalView | None]
type CommandKind = IntentKind | PumpSetting


def verify_signal(kind: CommandKind) -> SignalId:
    """Return the read-back signal a command of ``kind`` is verified against."""
    if isinstance(kind, PumpSetting):
        return PUMP_SETTINGS[kind].signal
    return VERIFY_SIGNALS[kind]


class SettingRefusedError(Exception):
    """An operator's pump-setting request is refused.

    Parameters
    ----------
    status
        HTTP status: ``404`` unknown setting, ``409`` state, ``422`` value, ``429`` rate.
    code
        Stable refusal code (see ``docs/api-v1.md``).
    message
        English explanation.
    params
        Values the UI renders the message from.
    """

    def __init__(
        self, status: int, code: str, message: str, params: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.params = params or {}

    def to_json(self) -> dict[str, Any]:
        """Return the ``detail`` object of the API response."""
        return {"code": self.code, "message": self.message, "params": self.params}


class CommandStatus(StrEnum):
    """Life-cycle events of a command."""

    QUEUED = "queued"
    SENT = "sent"
    VERIFIED = "verified"
    RETRY = "retry"
    FAILED = "failed"
    REFUSED = "refused"
    DROPPED = "dropped"


@dataclass(frozen=True, slots=True)
class Command:
    """One command the adapter may publish.

    Parameters
    ----------
    kind
        Setting.
    value
        Clamped integer value.
    topic
        Full command topic.
    payload
        Payload text.
    reason
        Why it was requested (``safety_correction`` for safety corrections,
        ``operator`` for an operator's pump setting, ``release`` for restoring the
        go-live snapshot).
    actor
        Who requested an operator's pump setting or a release.
    """

    kind: CommandKind
    value: int
    topic: str
    payload: str
    reason: str
    actor: str | None = None

    @property
    def corrective(self) -> bool:
        """Whether this is a safety correction."""
        return self.reason == SAFETY_REASON

    @property
    def operator(self) -> bool:
        """Whether this is an operator's pump setting."""
        return self.reason == OPERATOR_REASON

    @property
    def restore(self) -> bool:
        """Whether this restores the go-live snapshot (Release control)."""
        return self.reason == RESTORE_REASON


@dataclass(frozen=True, slots=True)
class CommandEvent:
    """A command life-cycle event (journal entry).

    Parameters
    ----------
    at
        When it happened.
    kind
        Setting.
    value
        Value concerned.
    status
        Event.
    attempt
        Attempt number (0 for events before the first publish).
    detail
        Human explanation.
    topic, payload
        What was (or would have been) published.
    """

    at: Instant
    kind: CommandKind
    value: int
    status: CommandStatus
    attempt: int
    detail: str
    topic: str | None = None
    payload: str | None = None

    def to_json(self) -> dict[str, Any]:
        """Return the API form."""
        return {
            "at": iso_z(self.at.wall),
            "kind": self.kind.value,
            "value": self.value,
            "status": self.status.value,
            "attempt": self.attempt,
            "detail": self.detail,
            "topic": self.topic,
            "payload": self.payload,
        }


@dataclass(slots=True)
class OperatorWrite:
    """The latest operator write of one pump setting.

    Parameters
    ----------
    at
        When it was requested (wall clock).
    by
        Who requested it.
    from_value
        The reported value at the request.
    to
        The requested value.
    status
        Latest life-cycle status of the command.
    """

    at: datetime
    by: str
    from_value: int | None
    to: int
    status: CommandStatus

    def to_json(self) -> dict[str, Any]:
        """Return the API form (``last_write`` of ``GET api/v1/pump/settings``)."""
        return {
            "at": iso_z(self.at),
            "by": self.by,
            "from": self.from_value,
            "to": self.to,
            "status": self.status.value,
        }


@dataclass(slots=True)
class AdapterCounters:
    """Counters of the adapter.

    Parameters
    ----------
    sent, verified, retried, failed, refused, clamped, foreign
        Event counts since start.
    superseded
        Queued values dropped because the controller no longer wanted them.
    corrections
        Safety corrections published.
    restarts
        Read-back differences attributed to a HeishaMon restart.
    envelope_corrections
        Read-back differences recognised as the HeishaMon envelope rule's correction
        and adopted (no foreign-writer hold).
    """

    sent: int = 0
    verified: int = 0
    retried: int = 0
    failed: int = 0
    refused: int = 0
    clamped: int = 0
    foreign: int = 0
    superseded: int = 0
    corrections: int = 0
    restarts: int = 0
    envelope_corrections: int = 0


@dataclass(frozen=True, slots=True)
class HoldRecord:
    """A hold as journalled (and restored after a restart).

    Parameters
    ----------
    reason
        Why it started.
    until
        Wall-clock end; ``None`` when latched.
    latched
        Lasts until an operator releases it.
    incident
        Number of holds within the escalation window, this one included.
    """

    reason: str
    until: datetime | None
    latched: bool
    incident: int

    def detail(self) -> dict[str, Any]:
        """Return the journal ``detail`` form."""
        return {
            "reason": self.reason,
            "until": None if self.until is None else self.until.timestamp(),
            "latched": self.latched,
            "incident": self.incident,
        }

    def to_json(self) -> dict[str, Any]:
        """Return the API form."""
        return {
            "reason": self.reason,
            "until": None if self.until is None else iso_z(self.until),
            "latched": self.latched,
            "incident": self.incident,
        }


@dataclass(frozen=True, slots=True)
class RestoredAdapter:
    """Adapter state recovered from the journal at start.

    Parameters
    ----------
    day
        UTC day of ``sent_today``.
    sent_today
        Commands published on ``day``.
    incidents
        Wall-clock unix times of the holds since the last operator release.
    hold
        The hold active at shutdown, if any.
    operator_requests
        Wall-clock unix time and setting of the operator's pump-setting requests of
        the last 24 h (their rate limits survive a restart).
    """

    day: date | None = None
    sent_today: int = 0
    incidents: tuple[float, ...] = ()
    hold: HoldRecord | None = None
    operator_requests: tuple[tuple[float, PumpSetting], ...] = ()


def reported_int(view: SignalView | None) -> int | None:
    """Return a fresh view's integer value, otherwise ``None``."""
    if view is None or not view.fresh:
        return None
    number = as_number(view.value)
    if number is None or not number.is_integer():
        return None
    return int(number)

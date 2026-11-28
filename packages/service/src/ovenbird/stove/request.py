"""Wood-stove mode in the service: the manual request, its persistence and the journal.

The controller decides wood-stove mode (``ovenbird_core.control``); the service adds
what lives outside the controller:

- **Manual request** (``POST api/v1/control/stove``): ``on`` with an end (default 8 h,
  at most the episode cap, and at most 24 h ahead) or a stop. The control loop turns
  it into an override of kind ``stove`` on every tick until it expires. A stop without
  an end is one-shot: it is dropped after the first tick the controller acted on it
  (the controller then keeps the detection blocked until the room has cooled below
  its exit threshold); a stop with an end suppresses the detection until then. The
  request is stored in ``control_state`` under ``stove_request`` so it survives a
  restart (an expired one is dropped on load).
- **Journal**: every entry and exit is journalled as an informational
  ``stove_mode`` event (``started``; ``released`` for a manual stop, ``expired`` for
  any other end), not as an alarm.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from ovenbird.clock import iso_z
from ovenbird.control.alarms import AlarmEvent, AlarmEventKind, Severity
from ovenbird.history.journal import read_state
from ovenbird.system.privacy import public_name
from ovenbird_core import Instant
from ovenbird_core.control import DecisionRecord, Override, OverrideKind

LOGGER = logging.getLogger("ovenbird.control.stove")
STOVE_KEY: Final = "stove_request"
STOVE_JOURNAL_CODE: Final = "stove_mode"
MAX_REQUEST_S: Final = 24 * 3600.0
MANUAL_DEFAULT_S: Final = 8 * 3600.0
STOVE_DETAIL: Final = (
    "stove_source",
    "stove_trigger",
    "stove_entry_c",
    "stove_enter_c",
    "stove_exit_c",
    "stove_backoff_k",
    "stove_reference_c",
    "stove_reference_gap_k",
    "stove_fault",
    "stove_jump_k",
    "stove_exit",
    "stove_until",
)


class StoveRequestError(ValueError):
    """A manual request the loop does not accept (the message says why)."""


@dataclass(frozen=True, slots=True)
class StoveRequest:
    """A manual wood-stove request.

    Parameters
    ----------
    on
        Start (or keep) an episode; ``False`` stops one.
    until
        End of the request (wall time); ``None`` only for a one-shot stop.
    actor
        Who asked: the role or user label only. A client address (``admin from
        192.168.1.20``) is stripped, because the request is visible to the read role
        and goes into the decision records; the audit row keeps the full name.
    at
        When it was asked.
    """

    on: bool
    until: datetime | None
    actor: str
    at: datetime

    def __post_init__(self) -> None:
        """Strip the client address from ``actor``."""
        object.__setattr__(self, "actor", public_name(self.actor) or "")

    def expired(self, wall: datetime) -> bool:
        """Whether the request has ended at ``wall``."""
        return self.until is not None and wall >= self.until

    def override(self, now: Instant) -> Override:
        """Return the controller override of the request at ``now``."""
        until = None
        if self.until is not None:
            until = now.shifted((self.until - now.wall).total_seconds())
        return Override(OverrideKind.STOVE, 1.0 if self.on else 0.0, until, self.actor)

    def to_json(self) -> dict[str, Any]:
        """Return the API and stored form."""
        return {
            "on": self.on,
            "until": None if self.until is None else iso_z(self.until),
            "actor": self.actor,
            "at": iso_z(self.at),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> StoveRequest:
        """Rebuild a request from :meth:`to_json` output.

        Raises
        ------
        ValueError
            For a malformed entry.
        """
        until = data.get("until")
        on = data["on"]
        if not isinstance(on, bool):
            raise ValueError("on must be a boolean")
        return cls(
            on=on,
            until=None if until is None else parse_wall(str(until)),
            actor=str(data["actor"]),
            at=parse_wall(str(data["at"])),
        )


def parse_wall(text: str) -> datetime:
    """Parse an ISO 8601 time; a naive time is UTC.

    Raises
    ------
    ValueError
        When it is not an ISO 8601 time.
    """
    raw = text.strip()
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def new_request(
    on: bool, until: datetime | None, actor: str, now: datetime, default_s: float
) -> StoveRequest:
    """Return a validated request made at ``now``.

    Parameters
    ----------
    on
        Start or stop.
    until
        Requested end; a start without one lasts ``default_s``.
    actor
        Who asks.
    now
        Service wall time.
    default_s
        Length of a start without an end (the automatic episode's maximum).

    Raises
    ------
    StoveRequestError
        When the end is not in the future or more than 24 h ahead.
    """
    if until is None and on:
        until = now + timedelta(seconds=default_s)
    if until is not None:
        ahead = (until - now).total_seconds()
        if ahead <= 0.0:
            raise StoveRequestError("until must lie in the future")
        if ahead > MAX_REQUEST_S:
            raise StoveRequestError(f"until must lie at most {MAX_REQUEST_S / 3600:.0f} h ahead")
    return StoveRequest(on, until, actor, now)


def encode_request(request: StoveRequest | None) -> str:
    """Return the stored JSON form (``null`` when there is no request)."""
    return json.dumps(None if request is None else request.to_json(), separators=(",", ":"))


def load_request(path: Path, now: Instant) -> StoveRequest | None:
    """Return the stored request, unless missing, unreadable or expired at ``now``."""
    if not path.exists():
        return None
    try:
        row = read_state(path, STOVE_KEY)
        data = None if row is None else json.loads(row.value)
        request = None if data is None else StoveRequest.from_json(data)
    except Exception:
        LOGGER.exception("cannot read the saved wood-stove request")
        return None
    if request is None or request.expired(now.wall) or request.until is None:
        return None
    LOGGER.info("wood-stove request restored: %s", request.to_json())
    return request


def stove_event(decision: DecisionRecord) -> AlarmEvent | None:
    """Return the journal event of a decision that entered or left wood-stove mode.

    Parameters
    ----------
    decision
        Decision whose controller state may carry a stove event.
    """
    state = decision.controller_state
    event = state.get("stove_event")
    if event not in ("entered", "exited"):
        return None
    detail = {key.removeprefix("stove_"): state.get(key) for key in STOVE_DETAIL}
    if event == "entered":
        trigger = state.get("stove_trigger")
        entry = state.get("stove_entry_c")
        at = f" at {entry:.1f} °C" if isinstance(entry, int | float) else ""
        backoff = state.get("stove_backoff_k")
        size = f" by {backoff:.1f} K" if isinstance(backoff, int | float) else ""
        message = (
            f"wood-stove mode on ({state.get('stove_source')}, {trigger}{at}): heating backed "
            f"off{size}, room feedback paused with its integrator held"
        )
        kind = AlarmEventKind.STARTED
    else:
        reason = state.get("stove_exit")
        message = f"wood-stove mode off ({reason}); normal room feedback resumes"
        kind = AlarmEventKind.RELEASED if reason == "manual_stop" else AlarmEventKind.EXPIRED
    return AlarmEvent(decision.at, STOVE_JOURNAL_CODE, Severity.INFO, kind, message, detail)

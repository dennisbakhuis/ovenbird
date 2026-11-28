"""Manual boost and away in the service: the requests, their persistence and the journal.

The controller shifts the room target (``ovenbird_core.control``, overrides of kind
``room_target`` and ``away`` in ``ControlInputs.room_override``); the service adds what
lives outside it:

- **Boost** (``POST api/v1/control/boost``): a temporary room target for 15 min to 12 h,
  as an offset to the comfort target (``offset_k``, -3 to +2 K, so "cooler" is a negative
  offset) or as an absolute target (``target_c``, within the same offsets of comfort).
  It ends by itself, or with ``DELETE``; a manual wood-stove start ends it (the owner
  lights the stove, so the extra heat is not wanted), an automatic stove episode and the
  summer switch only pause it in the controller. A boost is refused while away is set.
- **Away** (``PUT api/v1/control/away``): the away target (10 to 20 °C, below comfort)
  until an end time at most 60 days ahead; ``comfort_lead_s`` before the end (6 h by
  default) the comfort target returns, so the house is warm when the owner is back
  (phase ``returning``); at the end the request is dropped. Setting away ends a running
  boost. While away is set (until its end, the return included) the comfort-floor alarm
  follows the away target, the day shift pauses (guard ``away``) and the house basics
  leave the days out.

Both are switched by ``control_boost_enabled`` and ``control_away_enabled`` (on by
default: they act only on request); switching one off drops its request. A request is
stored in ``control_state`` (``boost_request``, ``away_request``) so it survives a
restart (an expired one is dropped on load) and every start and end is journalled as an
informational ``boost`` or ``away_mode`` event (``started``; ``released`` when it was
ended early, ``expired`` when it ran out).
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Protocol

from ovenbird.clock import iso_z
from ovenbird.control.alarms import AlarmBoard, AlarmEvent, AlarmEventKind, Severity
from ovenbird.history.journal import StateRow, read_state
from ovenbird.stove.request import parse_wall
from ovenbird.system.privacy import public_name
from ovenbird_core import Instant
from ovenbird_core.control import Override, OverrideKind

if TYPE_CHECKING:
    from ovenbird.config import Settings

LOGGER = logging.getLogger("ovenbird.control.roomtarget")
BOOST_KEY: Final = "boost_request"
AWAY_KEY: Final = "away_request"
BOOST_JOURNAL_CODE: Final = "boost"
AWAY_JOURNAL_CODE: Final = "away_mode"
BOOST_MIN_S: Final = 15 * 60.0
BOOST_MAX_S: Final = 12 * 3600.0
BOOST_MIN_K: Final = -3.0
BOOST_MAX_K: Final = 2.0
AWAY_MAX_S: Final = 60 * 86_400.0
AWAY_MIN_C: Final = 10.0
AWAY_MAX_C: Final = 20.0
AWAY_MAX_LEAD_S: Final = 86_400.0
EPSILON: Final = 1e-9


class RoomTargetError(ValueError):
    """A boost or away request the loop does not accept.

    Parameters
    ----------
    message
        Why it is refused.
    status
        HTTP status: 400 for a bad value, 409 when the state does not allow it.
    """

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class AwayPhase(StrEnum):
    """Where an away request stands."""

    AWAY = "away"
    RETURNING = "returning"


@dataclass(frozen=True, slots=True)
class TargetLimits:
    """The settings of boost and away.

    Parameters
    ----------
    boost_enabled, boost_default_s, boost_default_k
        ``control_boost_enabled``, ``control_boost_default_s``, ``control_boost_default_k``.
    away_enabled, away_target_c, away_lead_s
        ``control_away_enabled``, ``control_away_target_c``, ``control_away_comfort_lead_s``.
    comfort_c
        The comfort room target.
    """

    boost_enabled: bool = True
    boost_default_s: float = 2 * 3600.0
    boost_default_k: float = 1.0
    away_enabled: bool = True
    away_target_c: float = 16.0
    away_lead_s: float = 6 * 3600.0
    comfort_c: float = 21.0

    @classmethod
    def from_settings(cls, settings: Settings) -> TargetLimits:
        """Return the limits the settings describe."""
        return cls(
            boost_enabled=settings.control_boost_enabled,
            boost_default_s=settings.control_boost_default_s,
            boost_default_k=settings.control_boost_default_k,
            away_enabled=settings.control_away_enabled,
            away_target_c=settings.control_away_target_c,
            away_lead_s=settings.control_away_comfort_lead_s,
            comfort_c=settings.control_comfort_c,
        )


def _instant_at(now: Instant, wall: datetime) -> Instant:
    """Return the instant of wall time ``wall`` on the monotonic axis of ``now``."""
    return now.shifted((wall - now.wall).total_seconds())


@dataclass(frozen=True, slots=True)
class BoostRequest:
    """A temporary room target.

    Parameters
    ----------
    offset_k
        Shift of the comfort target in K (``None`` when an absolute target was asked).
    target_c
        Absolute room target in °C (``None`` when an offset was asked).
    until
        End (wall time).
    actor
        Who asked (the role or user label only, as for the stove request).
    at
        When it was asked.
    """

    offset_k: float | None
    target_c: float | None
    until: datetime
    actor: str
    at: datetime

    def __post_init__(self) -> None:
        """Strip the client address from ``actor``."""
        object.__setattr__(self, "actor", public_name(self.actor) or "")

    def expired(self, wall: datetime) -> bool:
        """Whether the boost has ended at ``wall``."""
        return wall >= self.until

    def shift_k(self, comfort_c: float) -> float:
        """Return the shift of the comfort target in K."""
        if self.offset_k is not None:
            return self.offset_k
        return (self.target_c or comfort_c) - comfort_c

    def override(self, now: Instant, comfort_c: float) -> Override:
        """Return the controller override at ``now``."""
        until = _instant_at(now, self.until)
        return Override(OverrideKind.ROOM_TARGET, self.shift_k(comfort_c), until, self.actor)

    def to_json(self) -> dict[str, Any]:
        """Return the API and stored form."""
        return {
            "offset_k": self.offset_k,
            "target_c": self.target_c,
            "until": iso_z(self.until),
            "actor": self.actor,
            "at": iso_z(self.at),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> BoostRequest:
        """Rebuild a request from :meth:`to_json` output.

        Raises
        ------
        ValueError
            For a malformed entry.
        """
        offset, target = data.get("offset_k"), data.get("target_c")
        if (offset is None) == (target is None):
            raise ValueError("exactly one of offset_k and target_c must be set")
        return cls(
            offset_k=None if offset is None else _finite(offset),
            target_c=None if target is None else _finite(target),
            until=parse_wall(str(data["until"])),
            actor=str(data["actor"]),
            at=parse_wall(str(data["at"])),
        )


@dataclass(frozen=True, slots=True)
class AwayRequest:
    """An away period.

    Parameters
    ----------
    target_c
        Room target while away.
    until
        End of the away period (wall time): the owner is back.
    lead_s
        How long before ``until`` the comfort target returns.
    actor
        Who asked (the role or user label only).
    at
        When it was asked.
    """

    target_c: float
    until: datetime
    lead_s: float
    actor: str
    at: datetime

    def __post_init__(self) -> None:
        """Strip the client address from ``actor``."""
        object.__setattr__(self, "actor", public_name(self.actor) or "")

    @property
    def comfort_from(self) -> datetime:
        """When the comfort target returns."""
        return self.until - timedelta(seconds=self.lead_s)

    def expired(self, wall: datetime) -> bool:
        """Whether the away period has ended at ``wall``."""
        return wall >= self.until

    def phase(self, wall: datetime) -> AwayPhase:
        """Return ``away`` before the comfort lead and ``returning`` within it."""
        return AwayPhase.AWAY if wall < self.comfort_from else AwayPhase.RETURNING

    def override(self, now: Instant, comfort_c: float) -> Override | None:
        """Return the controller override at ``now`` (``None`` once comfort has returned)."""
        if self.phase(now.wall) is not AwayPhase.AWAY:
            return None
        until = _instant_at(now, self.comfort_from)
        shift = min(0.0, self.target_c - comfort_c)
        return Override(OverrideKind.AWAY, shift, until, self.actor)

    def to_json(self) -> dict[str, Any]:
        """Return the API and stored form."""
        return {
            "target_c": self.target_c,
            "until": iso_z(self.until),
            "comfort_lead_s": self.lead_s,
            "comfort_from": iso_z(self.comfort_from),
            "actor": self.actor,
            "at": iso_z(self.at),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> AwayRequest:
        """Rebuild a request from :meth:`to_json` output.

        Raises
        ------
        ValueError
            For a malformed entry.
        """
        return cls(
            target_c=_finite(data["target_c"]),
            until=parse_wall(str(data["until"])),
            lead_s=_finite(data["comfort_lead_s"]),
            actor=str(data["actor"]),
            at=parse_wall(str(data["at"])),
        )


def _finite(value: Any) -> float:
    """Return ``value`` as a finite float.

    Raises
    ------
    ValueError
        When it is no finite number.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("not a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("not a finite number")
    return number


def new_boost(
    limits: TargetLimits,
    *,
    offset_k: float | None,
    target_c: float | None,
    duration_s: float | None,
    until: datetime | None,
    actor: str,
    now: datetime,
) -> BoostRequest:
    """Return a validated boost made at ``now``.

    Parameters
    ----------
    limits
        The boost settings and the comfort target.
    offset_k, target_c
        At most one: the shift of the comfort target or the absolute target; neither
        takes ``boost_default_k``.
    duration_s, until
        At most one: how long or until when; neither takes ``boost_default_s``.
    actor
        Who asks.
    now
        Service wall time.

    Raises
    ------
    RoomTargetError
        When a value is out of range or both forms of one value are given.
    """
    if offset_k is not None and target_c is not None:
        raise RoomTargetError("give offset_k or target_c, not both")
    if duration_s is not None and until is not None:
        raise RoomTargetError("give duration_s or until, not both")
    if offset_k is None and target_c is None:
        offset_k = limits.boost_default_k
    shift = offset_k if offset_k is not None else (target_c or 0.0) - limits.comfort_c
    if not BOOST_MIN_K - EPSILON <= shift <= BOOST_MAX_K + EPSILON:
        raise RoomTargetError(
            f"the room target must lie {BOOST_MIN_K:g} to +{BOOST_MAX_K:g} K from comfort "
            f"({limits.comfort_c:g} °C)"
        )
    if abs(shift) < EPSILON:
        raise RoomTargetError("the room target equals comfort; nothing to boost")
    if until is None:
        until = now + timedelta(
            seconds=limits.boost_default_s if duration_s is None else duration_s
        )
    ahead = (until - now).total_seconds()
    if not BOOST_MIN_S - EPSILON <= ahead <= BOOST_MAX_S + EPSILON:
        raise RoomTargetError(
            f"a boost lasts {BOOST_MIN_S / 60:.0f} min to {BOOST_MAX_S / 3600:.0f} h"
        )
    return BoostRequest(offset_k, target_c, until, actor, now)


def new_away(
    limits: TargetLimits,
    *,
    target_c: float | None,
    until: datetime,
    lead_s: float | None,
    actor: str,
    now: datetime,
) -> AwayRequest:
    """Return a validated away period made at ``now``.

    Parameters
    ----------
    limits
        Allowed ranges and defaults.
    target_c
        Away target in °C, the default when ``None``.
    until
        When the period ends.
    lead_s
        Seconds before the end at which comfort resumes, the default when ``None``.
    actor
        Who asked.
    now
        Time of the request.

    Raises
    ------
    RoomTargetError
        When the target is out of range or not below comfort, or the end is not after
        the comfort lead or more than 60 days ahead.
    """
    target = limits.away_target_c if target_c is None else target_c
    lead = limits.away_lead_s if lead_s is None else lead_s
    if not AWAY_MIN_C <= target <= AWAY_MAX_C:
        raise RoomTargetError(f"the away target must lie {AWAY_MIN_C:g} to {AWAY_MAX_C:g} °C")
    if target >= limits.comfort_c - EPSILON:
        raise RoomTargetError(
            f"the away target must lie below the comfort target ({limits.comfort_c:g} °C)"
        )
    if not 0.0 <= lead <= AWAY_MAX_LEAD_S:
        raise RoomTargetError(f"comfort_lead_s must lie 0 to {AWAY_MAX_LEAD_S:.0f} s")
    ahead = (until - now).total_seconds()
    if ahead > AWAY_MAX_S:
        raise RoomTargetError(f"until must lie at most {AWAY_MAX_S / 86_400:.0f} days ahead")
    if ahead <= lead:
        raise RoomTargetError(
            f"until must lie more than the comfort lead ({lead / 3600:g} h) ahead"
        )
    return AwayRequest(target, until, lead, actor, now)


def encode_request(request: BoostRequest | AwayRequest | None) -> str:
    """Return the stored JSON form (``null`` when there is no request)."""
    return json.dumps(None if request is None else request.to_json(), separators=(",", ":"))


def _load(path: Path, key: str) -> dict[str, Any] | None:
    """Return the stored request ``key`` as a mapping (``None`` when absent or unreadable)."""
    if not path.exists():
        return None
    try:
        row = read_state(path, key)
        data = None if row is None else json.loads(row.value)
    except Exception:
        LOGGER.exception("cannot read the saved %s", key)
        return None
    return data if isinstance(data, dict) else None


def load_boost(path: Path, now: Instant) -> BoostRequest | None:
    """Return the stored boost, unless missing, unreadable or expired at ``now``."""
    data = _load(path, BOOST_KEY)
    try:
        request = None if data is None else BoostRequest.from_json(data)
    except ValueError, KeyError:
        LOGGER.exception("cannot read the saved boost")
        return None
    if request is None or request.expired(now.wall):
        return None
    LOGGER.info("boost restored: %s", request.to_json())
    return request


def load_away(path: Path, now: Instant) -> AwayRequest | None:
    """Return the stored away period, unless missing, unreadable or over at ``now``."""
    data = _load(path, AWAY_KEY)
    try:
        request = None if data is None else AwayRequest.from_json(data)
    except ValueError, KeyError:
        LOGGER.exception("cannot read the saved away period")
        return None
    if request is None or request.expired(now.wall):
        return None
    LOGGER.info("away restored: %s", request.to_json())
    return request


class TargetHost(Protocol):
    """The owner of :class:`RoomTargets` (the control loop): its current collaborators."""

    @property
    def alarms(self) -> AlarmBoard:
        """The alarm board (``boost`` and ``away_mode`` events)."""
        ...

    @property
    def state_sink(self) -> Callable[[StateRow], None] | None:
        """Saves the requests with the controller state, if set."""
        ...


class RoomTargets:
    """The boost and away requests of a control loop, with their journal and status.

    Parameters
    ----------
    host
        The owner whose ``alarms`` and ``state_sink`` are used at every call.
    limits
        The boost and away settings.
    boost, away
        Requests to start with (restored after a restart).
    """

    def __init__(
        self,
        host: TargetHost,
        limits: TargetLimits | None = None,
        boost: BoostRequest | None = None,
        away: AwayRequest | None = None,
    ) -> None:
        self.host = host
        self.limits = limits or TargetLimits()
        self.boost = boost
        self.away = away

    def accept_boost(
        self,
        *,
        offset_k: float | None,
        target_c: float | None,
        duration_s: float | None,
        until: datetime | None,
        actor: str,
        moment: Instant,
    ) -> BoostRequest:
        """Accept a boost; it takes effect at the next tick.

        Parameters
        ----------
        offset_k
            Shift of the comfort target in K, or ``None`` when an absolute target is asked.
        target_c
            Absolute room target in °C, or ``None`` when a shift is asked.
        duration_s
            How long the boost lasts, in seconds, or ``None``.
        until
            When the boost ends, or ``None``.
        actor
            Who asked.
        moment
            Time of the request.

        Raises
        ------
        RoomTargetError
            When boost is switched off or away is set (409), or a value is refused (400).
        """
        if not self.limits.boost_enabled:
            raise RoomTargetError("boost is not enabled (control_boost_enabled)", 409)
        if self.away is not None and not self.away.expired(moment.wall):
            raise RoomTargetError("away is set; end it before a boost", 409)
        request = new_boost(
            self.limits,
            offset_k=offset_k,
            target_c=target_c,
            duration_s=duration_s,
            until=until,
            actor=actor,
            now=moment.wall,
        )
        replaced = self.boost is not None
        self._set(BOOST_KEY, request, moment)
        self.boost = request
        detail = {**request.to_json(), "replaced": replaced}
        shift = request.shift_k(self.limits.comfort_c)
        message = (
            f"boost {shift:+.1f} K on the room target by {request.actor} until "
            f"{iso_z(request.until)}"
        )
        self._journal(BOOST_JOURNAL_CODE, AlarmEventKind.STARTED, message, moment, detail)
        LOGGER.warning("boost by %s: %s", actor, request.to_json())
        return request

    def end_boost(self, moment: Instant, why: str) -> BoostRequest | None:
        """End the boost early (``None`` when there was none); journalled as ``released``."""
        request = self.boost
        if request is None:
            return None
        self.boost = None
        self._set(BOOST_KEY, None, moment)
        detail = {**request.to_json(), "why": why}
        self._journal(
            BOOST_JOURNAL_CODE, AlarmEventKind.RELEASED, f"boost ended: {why}", moment, detail
        )
        return request

    def accept_away(
        self,
        *,
        target_c: float | None,
        until: datetime,
        lead_s: float | None,
        actor: str,
        moment: Instant,
    ) -> AwayRequest:
        """Accept an away period (ending a running boost); it takes effect at the next tick.

        Parameters
        ----------
        target_c
            Away target in °C, the default when ``None``.
        until
            When the period ends.
        lead_s
            Seconds before the end at which comfort resumes, the default when ``None``.
        actor
            Who asked.
        moment
            Time of the request.

        Raises
        ------
        RoomTargetError
            When away is switched off (409) or a value is refused (400).
        """
        if not self.limits.away_enabled:
            raise RoomTargetError("away is not enabled (control_away_enabled)", 409)
        request = new_away(
            self.limits, target_c=target_c, until=until, lead_s=lead_s, actor=actor, now=moment.wall
        )
        self.end_boost(moment, "away was set")
        replaced = self.away is not None
        self._set(AWAY_KEY, request, moment)
        self.away = request
        detail = {**request.to_json(), "replaced": replaced}
        message = (
            f"away at {request.target_c:g} °C by {request.actor} until {iso_z(request.until)} "
            f"(comfort from {iso_z(request.comfort_from)})"
        )
        self._journal(AWAY_JOURNAL_CODE, AlarmEventKind.STARTED, message, moment, detail)
        LOGGER.warning("away by %s: %s", actor, request.to_json())
        return request

    def end_away(self, moment: Instant, why: str) -> AwayRequest | None:
        """End the away period early (``None`` when there was none); journalled ``released``."""
        request = self.away
        if request is None:
            return None
        self.away = None
        self._set(AWAY_KEY, None, moment)
        detail = {**request.to_json(), "why": why}
        self._journal(
            AWAY_JOURNAL_CODE, AlarmEventKind.RELEASED, f"away ended: {why}", moment, detail
        )
        return request

    def configure(self, limits: TargetLimits, moment: Instant) -> None:
        """Take new settings; a switched-off feature drops its request."""
        self.limits = limits
        if not limits.boost_enabled:
            self.end_boost(moment, "boost switched off (control_boost_enabled)")
        if not limits.away_enabled:
            self.end_away(moment, "away switched off (control_away_enabled)")

    def live(self, moment: Instant) -> Override | None:
        """Return the room override in force at ``moment``, dropping what has run out."""
        self._expire(moment)
        comfort = self.limits.comfort_c
        if self.boost is not None:
            return self.boost.override(moment, comfort)
        if self.away is not None:
            return self.away.override(moment, comfort)
        return None

    def away_active(self, wall: datetime) -> bool:
        """Whether an away period is set at ``wall`` (its return phase included)."""
        return self.away is not None and not self.away.expired(wall)

    def lowered_target_c(self, wall: datetime) -> float | None:
        """Return the room target below comfort that away or a cooler boost asks for.

        Away counts until its end (the house is still warming up during the return);
        ``None`` without one, or for a boost that raises the target.
        """
        comfort = self.limits.comfort_c
        if self.away_active(wall) and self.away is not None:
            return min(comfort, self.away.target_c)
        boost = self.boost
        if boost is not None and not boost.expired(wall) and boost.shift_k(comfort) < 0.0:
            return comfort + boost.shift_k(comfort)
        return None

    def boost_status(self, moment: Instant, latest: dict[str, Any] | None) -> dict[str, Any]:
        """Return the API form of the boost: settings, state and request."""
        request = self.boost
        comfort = self.limits.comfort_c
        live = request is not None and not request.expired(moment.wall)
        shift = request.shift_k(comfort) if request is not None and live else None
        return {
            "enabled": self.limits.boost_enabled,
            "active": live,
            "paused": self._paused(OverrideKind.ROOM_TARGET, latest) if live else None,
            "shift_k": shift,
            "target_c": None if shift is None else comfort + shift,
            "remaining_s": (
                (request.until - moment.wall).total_seconds()
                if request is not None and live
                else None
            ),
            "default_s": self.limits.boost_default_s,
            "default_k": self.limits.boost_default_k,
            "request": None if request is None else request.to_json(),
        }

    def away_status(self, moment: Instant, latest: dict[str, Any] | None) -> dict[str, Any]:
        """Return the API form of away: settings, phase and request."""
        request = self.away
        live = request is not None and not request.expired(moment.wall)
        phase = request.phase(moment.wall) if request is not None and live else None
        return {
            "enabled": self.limits.away_enabled,
            "active": live,
            "phase": None if phase is None else phase.value,
            "paused": (
                self._paused(OverrideKind.AWAY, latest) if phase is AwayPhase.AWAY else None
            ),
            "target_c": request.target_c if request is not None and live else None,
            "until": iso_z(request.until) if request is not None and live else None,
            "comfort_from": iso_z(request.comfort_from) if request is not None and live else None,
            "default_target_c": self.limits.away_target_c,
            "default_lead_s": self.limits.away_lead_s,
            "request": None if request is None else request.to_json(),
        }

    @staticmethod
    def _paused(kind: OverrideKind, latest: dict[str, Any] | None) -> str | None:
        """Return why the controller paused the override at the latest tick, if it did."""
        state = latest or {}
        if state.get("room_override") != kind.value:
            return None
        paused = state.get("room_override_paused")
        return paused if isinstance(paused, str) else None

    def _expire(self, moment: Instant) -> None:
        """Drop the requests that have run out, journalling them as ``expired``."""
        boost, away = self.boost, self.away
        if boost is not None and boost.expired(moment.wall):
            self.boost = None
            self._set(BOOST_KEY, None, moment)
            self._journal(
                BOOST_JOURNAL_CODE,
                AlarmEventKind.EXPIRED,
                "boost ended; the comfort target applies again",
                moment,
                boost.to_json(),
            )
        if away is not None and away.expired(moment.wall):
            self.away = None
            self._set(AWAY_KEY, None, moment)
            self._journal(
                AWAY_JOURNAL_CODE,
                AlarmEventKind.EXPIRED,
                "away ended; welcome back",
                moment,
                away.to_json(),
            )

    def _set(self, key: str, request: BoostRequest | AwayRequest | None, moment: Instant) -> None:
        """Save ``request`` under ``key`` with the controller state."""
        sink = self.host.state_sink
        if sink is not None:
            sink(StateRow(key, moment.wall.timestamp(), encode_request(request)))

    def _journal(
        self,
        code: str,
        kind: AlarmEventKind,
        message: str,
        moment: Instant,
        detail: dict[str, Any],
    ) -> None:
        """Journal one informational event.

        Parameters
        ----------
        code
            Event code.
        kind
            Whether it started or ended.
        message
            Event text.
        moment
            Time of the event.
        detail
            Structured detail of the event.
        """
        LOGGER.warning("%s", message)
        self.host.alarms.record(AlarmEvent(moment, code, Severity.INFO, kind, message, detail))

"""State of the command adapter and the event emission every part of it shares.

:class:`AdapterBase` holds the queue, the command in flight, the verified and
wanted values, the holds, the board and mode problems, the budget and the counters.
The behaviour is layered on top of it: :mod:`.envelope`, :mod:`.holds`, :mod:`.link`,
:mod:`.settings` and finally :class:`~ovenbird.control.adapter.commands.CommandAdapter`.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from ovenbird.control.adapter.model import (
    LOGGER,
    OPERATOR_PREFIX,
    RESTORE_PREFIX,
    AdapterCounters,
    Command,
    CommandEvent,
    CommandKind,
    CommandStatus,
    HoldRecord,
    OperatorWrite,
)
from ovenbird.control.adapter.publish import AdapterConfig
from ovenbird.control.alarms import (
    AlarmBoard,
    AlarmCode,
)
from ovenbird.control.guard import PublishGuard
from ovenbird_core import (
    Instant,
    PumpSetting,
)
from ovenbird_core.control import IntentKind


@dataclass(slots=True)
class _Pending:
    """A queued command and the number of the attempt it is on."""

    command: Command
    attempt: int


@dataclass(slots=True)
class _InFlight:
    """The command awaiting verification, its attempt and when it was sent."""

    command: Command
    attempt: int
    sent_at: Instant


@dataclass(slots=True)
class _Hold:
    """An active hold on publishing: its record and its end (monotonic s, ``None`` if latched)."""

    record: HoldRecord
    until: float | None

    @property
    def reason(self) -> str:
        """Return why the hold was started."""
        return self.record.reason


@dataclass(slots=True)
class _Board:
    """What is known of the HeishaMon board: heartbeat, uptime, last will and last restart."""

    alive: bool | None = None
    uptime_s: float | None = None
    lwt_online: bool | None = None
    restarted_at: float | None = None
    why: str = ""


class AdapterBase:
    """State of the command adapter (see :class:`~.commands.CommandAdapter`).

    Parameters
    ----------
    config
        Limits and timing.
    guard
        Publish guard, checked on every request and every release.
    alarms
        Alarm board.
    journal
        Receives every command event (history log, API).

    Attributes
    ----------
    listeners
        Also receive every command event (the release run, the envelope watch).
    """

    def __init__(
        self,
        config: AdapterConfig,
        guard: PublishGuard,
        alarms: AlarmBoard,
        *,
        journal: Callable[[CommandEvent], None] | None = None,
    ) -> None:
        self.config = config
        self.guard = guard
        self.alarms = alarms
        self._journal = journal
        self.listeners: list[Callable[[CommandEvent], None]] = []
        self._queue: dict[CommandKind, _Pending] = {}
        self._in_flight: _InFlight | None = None
        self._verified: dict[IntentKind, int] = {}
        self._own: dict[IntentKind, int] = {}
        self._wanted: dict[IntentKind, int] = {}
        self._reconciled = False
        self._hold: _Hold | None = None
        self._incidents: list[float] = []
        self._mode_problem: str | None = None
        self._board_problem: str | None = None
        self._safety: frozenset[AlarmCode] = frozenset()
        self._awaiting: dict[AlarmCode, set[CommandKind]] = {}
        self._known: dict[PumpSetting, int] = {}
        self._failed_targets: dict[PumpSetting, int] = {}
        self._changed_at: float | None = None
        self._operator_requests: list[tuple[float, PumpSetting]] = []
        self.operator_writes: dict[PumpSetting, OperatorWrite] = {}
        self._corrections: deque[float] = deque()
        self._outside: float | None = None
        self._own_band: tuple[int, float, float] | None = None
        self._board = _Board()
        self._last_sent_at: float | None = None
        self._day: date | None = None
        self._sent_today = 0
        self._budget_warned = False
        self.counters = AdapterCounters()

    def _emit(
        self,
        at: Instant,
        command: Command,
        status: CommandStatus,
        attempt: int,
        detail: str,
    ) -> CommandEvent:
        """Journal and publish a command event, marking operator and restore commands in its detail.

        Parameters
        ----------
        at
            Time of the event.
        command
            Command the event is about.
        status
            New status of the command.
        attempt
            Attempt number, 0 when the command was never sent.
        detail
            Human-readable explanation.

        Returns
        -------
        CommandEvent
            The event that was recorded.
        """
        if command.operator and not detail.startswith(OPERATOR_PREFIX):
            detail = f"{OPERATOR_PREFIX}{command.actor}: {detail}"
        if command.restore and not detail.startswith(RESTORE_PREFIX):
            detail = f"{RESTORE_PREFIX}{command.actor}: {detail}"
        event = CommandEvent(
            at, command.kind, command.value, status, attempt, detail, command.topic, command.payload
        )
        if command.operator and isinstance(command.kind, PumpSetting):
            write = self.operator_writes.get(command.kind)
            if write is not None and write.to == command.value:
                write.status = status
        if self._journal is not None:
            self._journal(event)
        self._notify(event)
        return event

    def _notify(self, event: CommandEvent) -> None:
        """Pass ``event`` to every listener; a failing listener is logged, not raised."""
        for listener in self.listeners:
            try:
                listener(event)
            except Exception:
                LOGGER.exception("command event listener failed")

    def _drop_queue(self, now: Instant, why: str) -> None:
        """Drop every queued command, recording ``why`` on each."""
        for pending in self._queue.values():
            self._emit(now, pending.command, CommandStatus.DROPPED, pending.attempt - 1, why)
        self._queue.clear()

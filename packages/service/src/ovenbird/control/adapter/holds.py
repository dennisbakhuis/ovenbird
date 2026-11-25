"""Holds of the command adapter: foreign writers, failed verification and escalation.

A verified value later read back different (a foreign writer) or a command that is
not applied after its retries starts a hold; repeated holds within the escalation
window last longer and then latch until an operator releases them. The safety hold
(any critical alarm other than ``setpoint_above_max``) restricts releases to water
setpoint decreases. Alarms raised about a setting clear once ovenbird's value is in
effect again.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Final

from ovenbird.clock import iso_z
from ovenbird.control.adapter.base import _Hold
from ovenbird.control.adapter.envelope import EnvelopeMixin
from ovenbird.control.adapter.model import (
    LOGGER,
    OPERATOR_WINDOW_S,
    CommandKind,
    HoldRecord,
    Reader,
    RestoredAdapter,
    reported_int,
    verify_signal,
)
from ovenbird.control.alarms import (
    HOLD_JOURNAL_CODE,
    AlarmCode,
    AlarmEvent,
    AlarmEventKind,
    Severity,
)
from ovenbird_core import (
    HeishaMonStatus,
    Instant,
    SignalView,
)
from ovenbird_core.control import IntentKind

CONFIRM_CODES: Final = (
    AlarmCode.FOREIGN_WRITER,
    AlarmCode.VERIFICATION_FAILED,
    AlarmCode.HEISHAMON_RESTARTED,
)


class HoldsMixin(EnvelopeMixin):
    """Holds, their escalation and the foreign-writer detection of the adapter."""

    @property
    def hold_reason(self) -> str | None:
        """Why the adapter does not publish the controller's values right now, if it does not."""
        if self._board_problem is not None:
            return self._board_problem
        if self._mode_problem is not None:
            return self._mode_problem
        return self._hold.reason if self._hold is not None else None

    @property
    def hold(self) -> HoldRecord | None:
        """The current foreign-writer or verification hold, if any."""
        return self._hold.record if self._hold is not None else None

    @property
    def safety_hold(self) -> frozenset[AlarmCode]:
        """Critical alarms restricting releases to water setpoint decreases."""
        if self.alarms.is_active(AlarmCode.CORRECTION_FAILED):
            return self._safety | {AlarmCode.CORRECTION_FAILED}
        return self._safety

    def safety_update(self, codes: frozenset[AlarmCode], now: Instant) -> None:
        """Receive the active critical safety alarms from the safety monitor.

        ``setpoint_above_max`` is handled by the safety correction; every other
        critical alarm puts the adapter into the safety hold.
        """
        held = codes - {AlarmCode.SETPOINT_ABOVE_MAX}
        if held != self._safety:
            if held:
                LOGGER.error(
                    "safety hold (%s): only water setpoint decreases are released",
                    ", ".join(sorted(code.value for code in held)),
                )
            else:
                LOGGER.warning("safety hold ended")
        self._safety = held
        del now

    def _await(
        self,
        code: AlarmCode,
        kind: CommandKind,
        message: str,
        now: Instant,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._awaiting.setdefault(code, set()).add(kind)
        self.alarms.raise_alarm(code, message, now, detail)

    def _confirm(self, now: Instant, kind: IntentKind, why: str) -> None:
        """Clear the alarms waiting for ovenbird's ``kind`` to be in effect again.

        An alarm raised about a setting clears only once that setting is verified
        or adopted (and every other setting it named as well); an alarm without a
        recorded setting clears on any confirmation.
        """
        if self._hold is not None:
            return
        for code in CONFIRM_CODES:
            waiting = self._awaiting.get(code)
            if waiting is not None:
                waiting.discard(kind)
                if waiting:
                    continue
                del self._awaiting[code]
            self.alarms.clear(code, now, why)

    def _window_incidents(self, now: Instant) -> list[float]:
        stamp = now.wall.timestamp()
        cutoff = stamp - self.config.escalation_window_s
        return [t for t in self._incidents if cutoff <= t <= stamp]

    def _plan_hold(self, now: Instant, reason: str) -> tuple[HoldRecord, float | None]:
        incident = len(self._window_incidents(now)) + 1
        if incident >= self.config.latch_after:
            return HoldRecord(reason, None, True, incident), None
        duration = self.config.hold_s * (self.config.escalation_factor if incident > 1 else 1.0)
        record = HoldRecord(reason, now.wall + timedelta(seconds=duration), False, incident)
        return record, now.monotonic + duration

    def _foreign_detail(
        self, kind: IntentKind, own: int | None, seen: int, view: SignalView | None, now: Instant
    ) -> dict[str, Any]:
        """Return the structured ``detail`` of a foreign-writer alarm (hold forensics)."""
        record, _ = self._plan_hold(now, "foreign writer")
        held = view.held if view is not None else None
        since = now.wall - timedelta(seconds=held) if held is not None else now.wall
        return {
            "setting": kind.value,
            "signal": verify_signal(kind),
            "command": self.config.command_name(kind),
            "register": self.config.setpoint_register
            if kind is IntentKind.WATER_SETPOINT
            else None,
            "ovenbird_value": own,
            "seen_value": seen,
            "seen_since": iso_z(since),
            "pump_keeps": seen,
            "hold_until": None if record.until is None else iso_z(record.until),
            "latched": record.latched,
            "incident": record.incident,
            "at_hold_end": "await_release" if record.latched else "write_again",
            "controller_wants": self._wanted.get(kind),
        }

    def _start_hold(self, now: Instant, reason: str) -> None:
        record, until = self._plan_hold(now, reason)
        self._incidents = [*self._window_incidents(now), now.wall.timestamp()]
        incident = record.incident
        window_h = self.config.escalation_window_s / 3600.0
        if record.latched:
            what = "latched until an operator releases it"
        else:
            duration = (record.until - now.wall).total_seconds() if record.until else 0.0
            what = f"for {duration / 60:.0f} min"
        self._hold = _Hold(record, until)
        message = f"hold {incident} within {window_h:.0f} h ({reason}), {what}"
        LOGGER.error("command %s", message)
        severity = Severity.WARNING
        self.alarms.record(
            AlarmEvent(
                now, HOLD_JOURNAL_CODE, severity, AlarmEventKind.STARTED, message, record.detail()
            )
        )
        if record.latched:
            self.alarms.raise_alarm(
                AlarmCode.HOLD_LATCHED,
                f"{incident} holds within {window_h:.0f} h (latest: {reason}); publishing "
                "stopped until an operator releases it (POST api/v1/control/release-hold)",
                now,
            )
        self._drop_queue(now, f"hold: {reason}")

    def _expire_hold(self, now: Instant) -> None:
        hold = self._hold
        if hold is None or hold.until is None or now.monotonic < hold.until:
            return
        LOGGER.warning("command hold (%s) expired", hold.reason)
        self._hold = None
        self.alarms.record(
            AlarmEvent(
                now,
                HOLD_JOURNAL_CODE,
                Severity.INFO,
                AlarmEventKind.EXPIRED,
                f"hold ({hold.reason}) expired",
                hold.record.detail(),
            )
        )

    def release_hold(self, now: Instant, by: str) -> HoldRecord | None:
        """End the current hold (timed or latched) on an operator's request.

        Parameters
        ----------
        now
            Current instant.
        by
            Who released it (journalled).

        Returns
        -------
        HoldRecord or None
            The released hold; ``None`` when there was none. The escalation count
            restarts; mode, simulation and safety holds are not affected.
        """
        hold = self._hold
        if hold is None:
            return None
        self._hold = None
        self._incidents.clear()
        LOGGER.warning("command hold (%s) released by %s", hold.reason, by)
        self.alarms.record(
            AlarmEvent(
                now,
                HOLD_JOURNAL_CODE,
                Severity.INFO,
                AlarmEventKind.RELEASED,
                f"hold ({hold.reason}) released by {by}",
                hold.record.detail(),
            )
        )
        self.alarms.clear(AlarmCode.HOLD_LATCHED, now, f"released by {by}")
        return hold.record

    def restore(self, state: RestoredAdapter, now: Instant) -> None:
        """Recover the daily budget, the escalation count and the hold from the journal.

        Parameters
        ----------
        state
            What :func:`ovenbird.control.persist.restore_adapter` read.
        now
            Current instant.
        """
        today = now.wall.date()
        if state.day == today:
            self._day = today
            self._sent_today = state.sent_today
        stamp = now.wall.timestamp()
        cutoff = stamp - self.config.escalation_window_s
        self._incidents = [t for t in state.incidents if cutoff <= t <= stamp]
        self._operator_requests = [
            (t, setting)
            for t, setting in state.operator_requests
            if stamp - OPERATOR_WINDOW_S < t <= stamp
        ]
        record = state.hold
        if record is not None and record.latched:
            self._hold = _Hold(record, None)
            self.alarms.raise_alarm(
                AlarmCode.HOLD_LATCHED,
                f"latched hold ({record.reason}) restored from the journal; publishing stopped "
                "until an operator releases it (POST api/v1/control/release-hold)",
                now,
            )
        elif record is not None and record.until is not None and record.until > now.wall:
            remaining = (record.until - now.wall).total_seconds()
            self._hold = _Hold(record, now.monotonic + remaining)
        LOGGER.info(
            "restored from the journal: %d commands today, %d recent holds, hold %s",
            self._sent_today,
            len(self._incidents),
            self._hold.record.to_json() if self._hold is not None else None,
        )

    def _detect_foreign(self, now: Instant, read: Reader, board: HeishaMonStatus | None) -> None:
        if (board is not None and not board.alive) or self._mode_problem is not None:
            return
        flying = self._in_flight.command.kind if self._in_flight is not None else None
        restarted = self._board.restarted_at
        recent_restart = (
            restarted is not None and now.monotonic - restarted <= self.config.restart_grace_s
        )
        for kind, value in list(self._verified.items()):
            if kind == flying or kind in self._queue:
                continue
            view = read(verify_signal(kind))
            reported = reported_int(view)
            if reported is None or reported == value:
                continue
            if kind is IntentKind.WATER_SETPOINT and self._rule_correction(value, reported, now):
                continue
            if recent_restart:
                del self._verified[kind]
                self.counters.restarts += 1
                self._await(
                    AlarmCode.HEISHAMON_RESTARTED,
                    kind,
                    f"HeishaMon restarted ({self._board.why}); {kind.value} reads {reported} "
                    f"instead of ovenbird's {value}: not a foreign writer, the controller "
                    "sends its value again",
                    now,
                )
                continue
            self.counters.foreign += 1
            detail = self._foreign_detail(kind, value, reported, view, now)
            end = (
                "the hold is latched until an operator releases it"
                if detail["latched"]
                else f"ovenbird writes its own value again at {detail['hold_until']}"
            )
            message = (
                f"{kind.value} changed to {reported} after ovenbird set {value}; the pump keeps "
                f"{reported}, {end}"
            )
            self._await(AlarmCode.FOREIGN_WRITER, kind, message, now, detail)
            self._verified.clear()
            self._start_hold(now, "foreign writer")
            return

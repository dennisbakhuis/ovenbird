"""The command adapter: queue, de-duplication, release, verification and retries.

:class:`CommandAdapter` (pure state machine, no I/O) turns arbiter requests into
commands: a closed allowlist of three settings, integer clamps to the safety limits,
a serial queue (one command in flight, the newest value per setting queued, values
the controller no longer wants dropped) with a minimum spacing, effect verification
with retries and an alarm plus hold when they run out, a per-day write budget, and
the safety correction (see :meth:`CommandAdapter.tick`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC
from typing import Any, Final

from ovenbird.clock import iso_z
from ovenbird.control.adapter.base import (
    _InFlight,
    _Pending,
)
from ovenbird.control.adapter.model import (
    LOGGER,
    SAFETY_REASON,
    VERIFY_SIGNALS,
    Command,
    CommandEvent,
    CommandKind,
    CommandStatus,
    Reader,
    reported_int,
    verify_signal,
)
from ovenbird.control.adapter.settings import SettingsMixin
from ovenbird.control.alarms import AlarmCode
from ovenbird.control.arbiter import AdapterView
from ovenbird.control.monitors import setpoint_excess
from ovenbird_core import (
    HeishaMonStatus,
    HeishaSignal,
    Instant,
    PumpSetting,
)
from ovenbird_core.control import CommandIntent, IntentKind, SafetyLimits

BUDGET_WARNING_SHARE: Final = 0.8


class CommandAdapter(SettingsMixin):
    """Pure command state machine (see the module docstring and :meth:`tick`).

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

    def _refuse(self, at: Instant, intent: CommandIntent, detail: str) -> CommandEvent:
        self.counters.refused += 1
        value = intent.value if type(intent.value) is int else 0
        event = CommandEvent(at, intent.kind, value, CommandStatus.REFUSED, 0, detail)
        if self._journal is not None:
            self._journal(event)
        self._notify(event)
        LOGGER.warning("command %s=%r refused: %s", intent.kind.value, intent.value, detail)
        return event

    def build(self, intent: CommandIntent) -> tuple[Command | None, str]:
        """Turn an intent into a clamped command.

        Returns
        -------
        tuple
            The command (``None`` when refused) and a note (clamp or refusal reason).
        """
        if intent.kind not in VERIFY_SIGNALS:
            return None, f"{intent.kind!r} is not an allowed setting"
        if type(intent.value) is not int:
            return None, f"value {intent.value!r} is not an integer"
        low, high = self.config.clamp_range(intent.kind)
        value = min(max(intent.value, low), high)
        note = "" if value == intent.value else f"clamped from {intent.value} to [{low}, {high}]"
        command = Command(
            intent.kind,
            value,
            self.config.topic(intent.kind),
            self.config.payload(intent.kind, value),
            intent.reason.value,
        )
        return command, note

    @property
    def in_flight(self) -> Command | None:
        """The command published and not yet verified, if any."""
        flying = self._in_flight
        return None if flying is None else flying.command

    def view(self) -> AdapterView:
        """Return what the arbiter needs: in-flight and queued values and the hold."""
        in_flight: dict[IntentKind, int] = {}
        flying = self._in_flight
        if flying is not None and isinstance(flying.command.kind, IntentKind):
            in_flight[flying.command.kind] = flying.command.value
        queued = {
            kind: pending.command.value
            for kind, pending in self._queue.items()
            if isinstance(kind, IntentKind)
        }
        return AdapterView(in_flight, queued, self.hold_reason)

    def submit(self, intents: Sequence[CommandIntent], now: Instant) -> tuple[CommandEvent, ...]:
        """Queue the arbiter's requests.

        Parameters
        ----------
        intents
            Values the arbiter decided to send.
        now
            Current instant.

        Returns
        -------
        tuple of CommandEvent
            ``queued`` or ``refused`` per request (nothing for duplicates).
        """
        events: list[CommandEvent] = []
        refusals = self.guard.refusals()
        for intent in intents:
            if refusals:
                events.append(self._refuse(now, intent, "; ".join(refusals)))
                continue
            command, note = self.build(intent)
            if command is None:
                events.append(self._refuse(now, intent, note))
                continue
            if self.hold_reason is not None:
                events.append(self._refuse(now, intent, f"hold: {self.hold_reason}"))
                continue
            flying = self._in_flight
            if flying is not None and (flying.command.kind, flying.command.value) == (
                command.kind,
                command.value,
            ):
                continue
            queued = self._queue.get(command.kind)
            if queued is not None and queued.command == command:
                continue
            if note:
                self.counters.clamped += 1
                LOGGER.warning("command %s %s", command.kind.value, note)
            self._queue[command.kind] = _Pending(command, 1)
            events.append(self._emit(now, command, CommandStatus.QUEUED, 0, note or "queued"))
        return tuple(events)

    def reconcile(self, intents: Sequence[CommandIntent], now: Instant) -> tuple[CommandEvent, ...]:
        """Record the controller's current intents and drop queued values it no longer wants.

        Parameters
        ----------
        intents
            Every intent of the tick (not only the ones to send).
        now
            Current instant.

        Returns
        -------
        tuple of CommandEvent
            One ``dropped`` event per superseded queued value.
        """
        wanted: dict[IntentKind, int] = {}
        for intent in intents:
            command, _ = self.build(intent)
            if command is not None and isinstance(command.kind, IntentKind):
                wanted[command.kind] = command.value
        self._wanted = wanted
        self._reconciled = True
        events: list[CommandEvent] = []
        for kind, pending in list(self._queue.items()):
            if not isinstance(kind, IntentKind):
                continue
            target = wanted.get(kind)
            if target == pending.command.value:
                continue
            del self._queue[kind]
            self.counters.superseded += 1
            why = (
                "superseded: the controller no longer asks for it"
                if target is None
                else f"superseded: the controller now wants {target}"
            )
            events.append(
                self._emit(now, pending.command, CommandStatus.DROPPED, pending.attempt - 1, why)
            )
        return tuple(events)

    def adopt(self, kind: IntentKind, value: int, now: Instant) -> None:
        """Take ownership of a value the pump already reports and the controller wants.

        Re-arms foreign-writer detection after a hold or a restart without a write,
        and clears the alarms that wait for ovenbird's value to be in effect again.
        Ignored while any hold applies or a command of ``kind`` is pending.
        """
        if self.hold_reason is not None or kind in self._queue:
            return
        if self._in_flight is not None and self._in_flight.command.kind == kind:
            return
        self._verified[kind] = value
        self._own[kind] = value
        self._confirm(now, kind, f"the pump reports ovenbird's {kind.value} {value}")

    def set_envelope_rule(self, safety: SafetyLimits) -> None:
        """Follow a new configuration's envelope (only while the rule is declared installed)."""
        if self.config.envelope_rule is not None:
            self.config = replace(self.config, envelope_rule=safety)
            self._own_band = None

    def set_setpoint_range(self, low: int, high: int) -> None:
        """Replace the water setpoint clamp (a new configuration's safety limits).

        Queued values outside the new range are superseded at the next
        :meth:`reconcile`, which builds the controller's intents with the new clamp.
        """
        self.config = replace(self.config, setpoint_range=(low, high))

    def _roll_day(self, now: Instant) -> None:
        today = now.wall.date()
        if self._day != today:
            self._day = today
            self._sent_today = 0
            self._budget_warned = False
            self.alarms.clear(AlarmCode.WRITE_BUDGET, now, "new day")

    def clear_queue(self, now: Instant, why: str) -> None:
        """Drop every queued command (journalled as ``dropped`` with ``why``)."""
        self._drop_queue(now, why)

    def _verify(self, now: Instant, read: Reader) -> None:
        flying = self._in_flight
        if flying is None:
            return
        command = flying.command
        view = read(verify_signal(command.kind))
        reported = reported_int(view)
        took = now.monotonic - flying.sent_at.monotonic
        timed_out = took >= self.config.verify_timeout_s
        shown = view is not None and reported == command.value and flying.sent_at < view.observed
        unchanged = timed_out and view is not None and view.fresh and reported == command.value
        if shown or unchanged:
            self._in_flight = None
            self.counters.verified += 1
            what = "safety correction applied" if command.corrective else "applied"
            detail = (
                f"{what} in {took:.0f} s"
                if shown
                else f"{what}: the pump reports {command.value} and no change within "
                f"{took:.0f} s (it was already in effect)"
            )
            self._emit(now, command, CommandStatus.VERIFIED, flying.attempt, detail)
            why = f"ovenbird's {command.kind.value} {command.value} verified"
            if isinstance(command.kind, PumpSetting):
                self._known[command.kind] = command.value
                self._confirm_setting(now, command.kind, why)
                return
            self._verified[command.kind] = command.value
            self._own[command.kind] = command.value
            self._confirm(now, command.kind, why)
            return
        if not timed_out:
            return
        self._in_flight = None
        seen = "nothing" if reported is None else str(reported)
        if command.corrective:
            self.counters.failed += 1
            detail = f"safety correction not applied, pump reports {seen}"
            self._emit(now, command, CommandStatus.FAILED, flying.attempt, detail)
            return
        wanted = self._wanted.get(command.kind) if isinstance(command.kind, IntentKind) else None
        if (
            self._reconciled
            and not command.operator
            and not command.restore
            and wanted != command.value
        ):
            self.counters.superseded += 1
            why = (
                "the controller no longer asks for it"
                if wanted is None
                else f"the controller now wants {wanted}"
            )
            detail = f"not applied, pump reports {seen}; superseded in flight: {why}"
            self._emit(now, command, CommandStatus.DROPPED, flying.attempt, detail)
            return
        if self.guard.hold.releasing and not command.restore:
            detail = f"not applied, pump reports {seen}; not retried: control is being released"
            self._emit(now, command, CommandStatus.DROPPED, flying.attempt, detail)
            return
        if flying.attempt <= self.config.max_retries:
            self.counters.retried += 1
            detail = f"not applied, pump reports {seen}"
            self._emit(now, command, CommandStatus.RETRY, flying.attempt, detail)
            if command.kind not in self._queue:
                self._queue = {command.kind: _Pending(command, flying.attempt + 1), **self._queue}
            return
        self.counters.failed += 1
        detail = f"not applied after {flying.attempt} attempts, pump reports {seen}"
        self._emit(now, command, CommandStatus.FAILED, flying.attempt, detail)
        if isinstance(command.kind, PumpSetting):
            self._known.pop(command.kind, None)
            self._failed_targets[command.kind] = command.value
            self._await(
                AlarmCode.VERIFICATION_FAILED,
                command.kind,
                f"{command.kind.value}={command.value} {detail} (not supported by this "
                "model?); setpoint control continues",
                now,
            )
            return
        self._await(
            AlarmCode.VERIFICATION_FAILED,
            command.kind,
            f"{command.kind.value}={command.value} {detail}",
            now,
        )
        self._start_hold(now, "verification failed")

    def _safe_setpoint(self) -> int:
        low, high = self.config.setpoint_range
        for source in (self._wanted, self._own):
            value = source.get(IntentKind.WATER_SETPOINT)
            if value is not None:
                return min(max(value, low), high)
        return low

    def _spaced(self, now: Instant) -> bool:
        return (
            self._last_sent_at is None
            or now.monotonic - self._last_sent_at >= self.config.min_spacing_s
        )

    def _release(self, now: Instant, command: Command, attempt: int) -> Command:
        self._in_flight = _InFlight(command, attempt, now)
        self._last_sent_at = now.monotonic
        self._sent_today += 1
        self.counters.sent += 1
        return command

    def _correct(self, now: Instant, read: Reader) -> Command | None:
        excess = setpoint_excess(read, self.config.setpoint_range[1])
        if excess is None:
            self.alarms.clear(
                AlarmCode.CORRECTION_FAILED, now, "the water setpoint is within the limits"
            )
            return None
        if self._mode_problem is not None or self._board_problem is not None:
            return None
        signal, reported = excess
        if self._hold is None:
            self.counters.foreign += 1
            kind = IntentKind.WATER_SETPOINT
            forensics = self._foreign_detail(kind, self._own.get(kind), reported, read(signal), now)
            forensics.update(signal=signal, pump_keeps=None, correction=self._safe_setpoint())
            self._await(
                AlarmCode.FOREIGN_WRITER,
                kind,
                f"{signal.removeprefix('main/')} reports {reported} °C, a value ovenbird never "
                "sends",
                now,
                forensics,
            )
            self._verified.clear()
            self._start_hold(now, "foreign writer")
        flying = self._in_flight
        if flying is not None and flying.command.corrective:
            return None
        if not self._spaced(now):
            return None
        window_start = now.monotonic - self.config.correction_window_s
        while self._corrections and self._corrections[0] < window_start:
            self._corrections.popleft()
        limit = self.config.max_corrections
        if len(self._corrections) >= limit:
            self.alarms.raise_alarm(
                AlarmCode.CORRECTION_FAILED,
                f"{signal.removeprefix('main/')} still reports {reported} °C after {limit} safety "
                f"corrections within {self.config.correction_window_s / 60:.0f} min; holding",
                now,
            )
            return None
        if self._sent_today >= self.config.daily_budget + self.config.safety_reserve:
            self.alarms.raise_alarm(
                AlarmCode.CORRECTION_FAILED,
                f"{signal.removeprefix('main/')} reports {reported} °C but the write budget and "
                "its safety reserve are used up",
                now,
            )
            return None
        value = self._safe_setpoint()
        command = Command(
            IntentKind.WATER_SETPOINT,
            value,
            self.config.topic(IntentKind.WATER_SETPOINT),
            self.config.payload(IntentKind.WATER_SETPOINT, value),
            SAFETY_REASON,
        )
        if flying is not None:
            self._in_flight = None
            if isinstance(flying.command.kind, PumpSetting):
                self._known.pop(flying.command.kind, None)
            self._emit(
                now,
                flying.command,
                CommandStatus.DROPPED,
                flying.attempt,
                "pre-empted by a safety correction",
            )
        queued = self._queue.pop(IntentKind.WATER_SETPOINT, None)
        if queued is not None:
            self._emit(
                now,
                queued.command,
                CommandStatus.DROPPED,
                queued.attempt - 1,
                "superseded by a safety correction",
            )
        self._corrections.append(now.monotonic)
        self.counters.corrections += 1
        detail = (
            f"safety correction: {signal.removeprefix('main/')} reports {reported} °C, above "
            f"{self.config.setpoint_range[1]} °C; re-asserting {value} °C"
        )
        LOGGER.critical("%s", detail)
        self._emit(now, command, CommandStatus.QUEUED, 0, detail)
        return self._release(now, command, 1)

    def _drop_duty_in_defrost(self, now: Instant, read: Reader) -> None:
        pending = self._queue.get(IntentKind.MAX_PUMP_DUTY)
        if pending is None or reported_int(read(HeishaSignal.DEFROSTING_STATE)) != 1:
            return
        del self._queue[IntentKind.MAX_PUMP_DUTY]
        self.counters.superseded += 1
        self._emit(
            now,
            pending.command,
            CommandStatus.DROPPED,
            pending.attempt - 1,
            "defrost: the pump sets its own duty; not sent",
        )

    def _next(self, read: Reader) -> CommandKind | None:
        held = self.safety_hold
        for kind, pending in self._queue.items():
            if not held:
                return kind
            if kind is not IntentKind.WATER_SETPOINT:
                continue
            reported = reported_int(read(verify_signal(kind)))
            if reported is not None and pending.command.value < reported:
                return kind
        return None

    def tick(
        self, now: Instant, read: Reader, board: HeishaMonStatus | None = None
    ) -> Command | None:
        """Verify, detect foreign writers and restarts, and release at most one command.

        Release rules, in order:

        0. during a shadow hold of the guard (pause, configuration reset) a command
           in flight is still verified, but nothing else happens: the queue is
           dropped, the verified values are forgotten (whoever writes meanwhile is
           not a foreign writer; the values are adopted again after the resume) and
           nothing is released, not even a safety correction;
        1. nothing while the publish guard refuses (the queue is dropped), or, in
           simulation mode, while HeishaMon does not report simulated firmware;
        2. **safety correction**: when ``Z1_Water_Target_Temp`` (or, in Direct mode,
           ``Z1_Heat_Request_Temp``) reads above the maximum supply, the adapter
           re-asserts a safe setpoint — the controller's current water intent, else
           ovenbird's last verified value, else the safety minimum, clamped. It
           bypasses foreign-writer, verification and latched holds and pre-empts
           the queue and a non-corrective command in flight; it needs a fresh
           Direct ``Heating_Mode`` and heat ``Operating_Mode_State`` (never in
           compensation mode, where the register is a shift), keeps the minimum
           spacing, may use ``safety_reserve`` writes beyond the daily budget and
           is limited to ``max_corrections`` per ``correction_window_s``; when
           those run out ``correction_failed`` (critical) is raised and the
           adapter holds;
           A read-back difference the declared envelope rule explains is adopted
           instead (no hold, see :meth:`_rule_correction`);
        3. nothing during a mode problem or a foreign-writer/verification hold; a
           queued maximum pump duty is dropped while ``Defrosting_State`` reads 1
           (the pump drives its own duty during a defrost and ignores the setting);
        4. during the **safety hold** (any other critical alarm) only queued water
           setpoint decreases (below the reported value) are released;
        5. otherwise the oldest queued command, subject to spacing and budget.

        Parameters
        ----------
        now
            Current instant.
        read
            Returns the current view of a signal.
        board
            HeishaMon status (liveness, uptime, LWT, firmware version).

        Returns
        -------
        Command or None
            The command to publish now; the caller reports the outcome through
            :meth:`published` or :meth:`publish_failed`.
        """
        self._roll_day(now)
        self._watch_board(now, board)
        self._expire_hold(now)
        self._watch_settings(now, read)
        if self.guard.hold.active:
            self._verify(now, read)
            self._verified.clear()
            if self._queue:
                self._drop_queue(now, "; ".join(self.guard.hold.refusals()))
            return None
        self._check_mode(now, read)
        self._verify(now, read)
        self._watch_envelope(now, read)
        self._detect_foreign(now, read, board)
        if not self.guard.permits:
            if self._queue:
                self._drop_queue(now, "; ".join(self.guard.refusals()))
            return None
        self._check_board(now, board)
        correction = self._correct(now, read)
        if correction is not None:
            return correction
        self._drop_duty_in_defrost(now, read)
        self._drop_operator(now, read)
        if self.hold_reason is not None or self._in_flight is not None or not self._queue:
            return None
        if not self._spaced(now):
            return None
        if self._sent_today >= self.config.daily_budget:
            self.alarms.raise_alarm(
                AlarmCode.WRITE_BUDGET,
                f"{self._sent_today} commands today; budget of {self.config.daily_budget} used up",
                now,
            )
            return None
        kind = self._next(read)
        if kind is None:
            return None
        pending = self._queue.pop(kind)
        command = self._release(now, pending.command, pending.attempt)
        if (
            not self._budget_warned
            and self._sent_today >= BUDGET_WARNING_SHARE * self.config.daily_budget
        ):
            self._budget_warned = True
            LOGGER.warning(
                "%d of %d daily commands used", self._sent_today, self.config.daily_budget
            )
        return command

    def published(self, command: Command, now: Instant) -> None:
        """Record that ``command`` went out."""
        flying = self._in_flight
        attempt = flying.attempt if flying is not None and flying.command == command else 1
        self._emit(now, command, CommandStatus.SENT, attempt, f"published to {command.topic}")
        LOGGER.info("command %s=%d sent (attempt %d)", command.kind.value, command.value, attempt)

    def publish_failed(self, command: Command, now: Instant, error: str) -> None:
        """Put ``command`` back at the head of the queue after a failed publish."""
        flying = self._in_flight
        if flying is None or flying.command != command:
            return
        self._in_flight = None
        if not command.corrective and command.kind not in self._queue:
            self._queue = {command.kind: _Pending(command, flying.attempt), **self._queue}
        LOGGER.warning("publishing %s failed: %s", command.topic, error)

    def status(self, now: Instant | None = None) -> dict[str, Any]:
        """Return the API form of the adapter state."""
        flying = self._in_flight
        hold = self._hold
        window = len(self._window_incidents(now)) if now is not None else len(self._incidents)
        return {
            "setpoint_register": self.config.setpoint_register,
            "hold": self.hold_reason,
            "hold_until": None
            if hold is None or hold.record.until is None
            else iso_z(hold.record.until.astimezone(UTC)),
            "hold_latched": hold is not None and hold.record.latched,
            "hold_incidents": window,
            "safety_hold": sorted(code.value for code in self.safety_hold),
            "corrections": {
                "recent": len(self._corrections),
                "limit": self.config.max_corrections,
                "window_s": self.config.correction_window_s,
            },
            "in_flight": None
            if flying is None
            else {
                "kind": flying.command.kind.value,
                "value": flying.command.value,
                "attempt": flying.attempt,
                "sent_at": iso_z(flying.sent_at.wall),
                "corrective": flying.command.corrective,
            },
            "queued": {kind.value: p.command.value for kind, p in self._queue.items()},
            "verified": {kind.value: value for kind, value in self._verified.items()},
            "budget": {
                "day": None if self._day is None else self._day.isoformat(),
                "used": self._sent_today,
                "limit": self.config.daily_budget,
                "safety_reserve": self.config.safety_reserve,
            },
            "counters": {
                "sent": self.counters.sent,
                "verified": self.counters.verified,
                "retried": self.counters.retried,
                "failed": self.counters.failed,
                "refused": self.counters.refused,
                "clamped": self.counters.clamped,
                "foreign": self.counters.foreign,
                "superseded": self.counters.superseded,
                "corrections": self.counters.corrections,
                "restarts": self.counters.restarts,
                "envelope_corrections": self.counters.envelope_corrections,
            },
        }

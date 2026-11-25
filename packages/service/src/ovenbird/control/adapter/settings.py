"""Operator writes of the three pump settings and the release-control restore.

A second closed allowlist holds the three pump settings an operator may write
(:class:`~ovenbird_core.PumpSetting`: heating delta-T, flow-rate mode, heating-off
outdoor temperature; see :meth:`SettingsMixin.request_setting`): one-shot requests
through the same queue, guard, spacing, verification, budget and journal, refused
instead of clamped, compare-and-set on the fresh reported value, refused during a
defrost, a DHW run or any hold, and a failed verification raises
``verification_failed`` without holding setpoint control. A later change of such a
value that ovenbird did not make raises the info alarm ``pump_setting_changed``.
A third kind of request restores the pump-state snapshot taken at go-live
(:meth:`SettingsMixin.request_restore`, "Release control").
"""

from __future__ import annotations

from typing import Final

from ovenbird.control.adapter.base import _Pending
from ovenbird.control.adapter.link import LinkMixin
from ovenbird.control.adapter.model import (
    LOGGER,
    OPERATOR_PREFIX,
    OPERATOR_REASON,
    OPERATOR_WINDOW_S,
    RESTORE_PREFIX,
    RESTORE_REASON,
    VERIFY_SIGNALS,
    Command,
    CommandEvent,
    CommandStatus,
    OperatorWrite,
    Reader,
    SettingRefusedError,
    reported_int,
    verify_signal,
)
from ovenbird.control.adapter.publish import AdapterConfig
from ovenbird.control.alarms import AlarmCode
from ovenbird_core import (
    PUMP_SETTINGS,
    HeishaSignal,
    Instant,
    PumpSetting,
)
from ovenbird_core.control import IntentKind

OPERATOR_SPACING_S: Final = 600.0
OPERATOR_DAY_LIMIT: Final = 6
CHANGE_NOTICE_S: Final = 86_400.0


def restore_target(
    config: AdapterConfig,
    kind: IntentKind,
    value: int,
    band: tuple[int, int, str] | None = None,
) -> tuple[int, str]:
    """Return the value a restore of ``value`` sends and a note when it was clamped.

    Parameters
    ----------
    config
        The adapter's limits (static clamps).
    kind
        The setting.
    value
        The snapshot value.
    band
        ``(low, high, description)`` of the envelope band for the water setpoint.

    Returns
    -------
    tuple
        The target and the clamp note (empty when the value is sent as recorded).
    """
    low, high = config.clamp_range(kind)
    target = value
    notes: list[str] = []
    if band is not None and kind is IntentKind.WATER_SETPOINT:
        band_low, band_high, where = band
        banded = min(max(target, band_low), band_high)
        if banded != target:
            notes.append(
                f"clamped from {target} to the envelope band {band_low}-{band_high} {where}"
            )
            target = banded
    static = min(max(target, low), high)
    if static != target:
        notes.append(f"clamped from {target} to [{low}, {high}]")
        target = static
    return target, "; ".join(notes)


class SettingsMixin(LinkMixin):
    """Operator pump-setting writes and the go-live restore of the adapter."""

    def operator_block(self, read: Reader) -> tuple[str, str] | None:
        """Why an operator's pump setting may not be written now, if it may not.

        Returns
        -------
        tuple or None
            ``(code, message)``: ``not_publishing`` (the publish guard refuses:
            not ``auto``, paused, ...), ``hold`` (a board, mode, foreign-writer,
            verification or safety hold), ``defrost``, ``dhw`` or ``state_unknown``
            (``Defrosting_State`` or ``ThreeWay_Valve_State`` not fresh).
        """
        refusals = self.guard.refusals()
        if refusals:
            return "not_publishing", "; ".join(refusals)
        if self.hold_reason is not None:
            return "hold", f"hold: {self.hold_reason}"
        if self.safety_hold:
            codes = ", ".join(sorted(code.value for code in self.safety_hold))
            return "hold", f"safety hold ({codes})"
        defrost = reported_int(read(HeishaSignal.DEFROSTING_STATE))
        valve = reported_int(read(HeishaSignal.THREEWAY_VALVE_STATE))
        if defrost is None or valve is None:
            return "state_unknown", "Defrosting_State or ThreeWay_Valve_State not fresh"
        if defrost == 1:
            return "defrost", "a defrost is running"
        if valve == 1:
            return "dhw", "a DHW run is active"
        return None

    def operator_busy(self) -> PumpSetting | None:
        """Return the pump setting whose write is queued or in flight, if any."""
        flying = self._in_flight
        if flying is not None and isinstance(flying.command.kind, PumpSetting):
            return flying.command.kind
        return next((kind for kind in self._queue if isinstance(kind, PumpSetting)), None)

    def _check_operator_rate(self, setting: PumpSetting, now: Instant) -> None:
        stamp = now.wall.timestamp()
        recent = [
            (t, s) for t, s in self._operator_requests if stamp - OPERATOR_WINDOW_S < t <= stamp
        ]
        self._operator_requests = recent
        last = max((t for t, s in recent if s is setting), default=None)
        if last is not None and stamp - last < OPERATOR_SPACING_S:
            retry = round(OPERATOR_SPACING_S - (stamp - last), 1)
            raise SettingRefusedError(
                429,
                "rate_limited",
                f"at most one write of {setting.value} per {OPERATOR_SPACING_S / 60:.0f} min",
                {"retry_after": retry},
            )
        if len(recent) >= OPERATOR_DAY_LIMIT:
            retry = round(min(t for t, _ in recent) + OPERATOR_WINDOW_S - stamp, 1)
            raise SettingRefusedError(
                429,
                "day_limit",
                f"at most {OPERATOR_DAY_LIMIT} pump-setting writes per 24 h",
                {"limit": OPERATOR_DAY_LIMIT, "retry_after": retry},
            )
        if self._sent_today >= self.config.daily_budget:
            raise SettingRefusedError(
                429,
                "write_budget",
                f"the daily write budget of {self.config.daily_budget} commands is used up",
                {"limit": self.config.daily_budget},
            )

    def request_setting(
        self,
        setting: PumpSetting,
        value: object,
        expect: object,
        actor: str,
        now: Instant,
        read: Reader,
        *,
        comment: str | None = None,
    ) -> CommandEvent:
        """Queue an operator's write of one pump setting (compare-and-set, never clamped).

        Parameters
        ----------
        setting
            The setting (the second closed allowlist).
        value
            Requested value; must be an integer inside the setting's clamp.
        expect
            The value the operator saw; must equal the fresh reported value.
        actor
            Who asks (journalled with every event of the command).
        now
            Current instant.
        read
            Returns the current view of a signal.
        comment
            Optional note for the journal.

        Returns
        -------
        CommandEvent
            The ``queued`` event.

        Raises
        ------
        SettingRefusedError
            ``422`` for a non-integer or out-of-range value; ``409`` when the guard
            refuses, a hold applies, a defrost or DHW run is active (or their state
            is not fresh), the value is not fresh or not reported, ``expect``
            differs from it, it is already the reported value, or another pump
            setting is in flight or queued; ``429`` for the rate limits (one write
            per setting per 10 min, six per 24 h) or a used-up daily budget.
        """
        spec = PUMP_SETTINGS[setting]
        if type(value) is not int:
            raise SettingRefusedError(422, "not_an_integer", "value must be an integer")
        if not spec.low <= value <= spec.high:
            raise SettingRefusedError(
                422,
                "out_of_range",
                f"{setting.value} must lie within [{spec.low}, {spec.high}]",
                {"min": spec.low, "max": spec.high},
            )
        if type(expect) is not int:
            raise SettingRefusedError(
                422, "expect_required", "expect must be the integer value currently reported"
            )
        blocked = self.operator_block(read)
        if blocked is not None:
            raise SettingRefusedError(409, blocked[0], blocked[1])
        reported = reported_int(read(spec.signal))
        if reported is None:
            raise SettingRefusedError(
                409, "not_fresh", f"{spec.signal} is not freshly reported by the pump"
            )
        if expect != reported:
            raise SettingRefusedError(
                409,
                "value_changed",
                f"the pump reports {reported}, not {expect}",
                {"reported": reported},
            )
        if value == reported:
            raise SettingRefusedError(409, "unchanged", f"the pump already reports {value}")
        busy = self.operator_busy()
        if busy is not None:
            raise SettingRefusedError(
                409, "in_flight", f"a write of {busy.value} is still in progress"
            )
        self._check_operator_rate(setting, now)
        command = Command(
            setting,
            value,
            self.config.topic(setting),
            self.config.payload(setting, value),
            OPERATOR_REASON,
            actor,
        )
        self._operator_requests.append((now.wall.timestamp(), setting))
        self.operator_writes[setting] = OperatorWrite(
            now.wall, actor, reported, value, CommandStatus.QUEUED
        )
        self._queue[setting] = _Pending(command, 1)
        detail = f"{OPERATOR_PREFIX}{actor}: {setting.value} {reported} → {value}"
        if comment:
            detail += f" ({comment})"
        LOGGER.warning("%s", detail)
        return self._emit(now, command, CommandStatus.QUEUED, 0, detail)

    def request_restore(
        self,
        kind: IntentKind,
        value: int,
        actor: str,
        now: Instant,
        read: Reader,
        band: tuple[int, int, str] | None = None,
    ) -> CommandEvent:
        """Queue one restore of the go-live snapshot (Release control).

        The value goes through the controller's allowlist and clamps, the queue,
        spacing, daily budget and verification like a controller intent; it is not
        superseded by the controller (which is stopped during a release). A water
        setpoint is also clamped to ``band``, the envelope band at the current
        outside temperature, so the HeishaMon rule does not rewrite it at once. A
        command of the same setting still in flight is verified first: the restore
        waits in the queue until it has settled.

        Parameters
        ----------
        kind
            A controller setting (water setpoint, maximum pump duty, quiet mode).
        value
            The value recorded at go-live.
        actor
            Who releases control (journalled with every event of the command).
        now
            Current instant.
        read
            Returns the current view of a signal.
        band
            ``(low, high, description)`` of the envelope band for the water
            setpoint; ``None`` clamps to the static limits only.

        Returns
        -------
        CommandEvent
            The ``queued`` event.

        Raises
        ------
        SettingRefusedError
            ``422`` for another setting or a non-integer; ``409`` while the guard
            refuses or any hold applies (a safety hold allows only a water setpoint
            decrease); ``429`` when the daily budget is used up.
        """
        if kind not in VERIFY_SIGNALS:
            raise SettingRefusedError(422, "not_allowed", f"{kind!r} is not an allowed setting")
        if type(value) is not int:
            raise SettingRefusedError(422, "not_an_integer", "value must be an integer")
        refusals = self.guard.refusals()
        if refusals:
            raise SettingRefusedError(409, "not_publishing", "; ".join(refusals))
        if self.hold_reason is not None:
            raise SettingRefusedError(409, "hold", f"hold: {self.hold_reason}")
        target, note = self.restore_target(kind, value, band)
        reported = reported_int(read(verify_signal(kind)))
        if self.safety_hold and (
            kind is not IntentKind.WATER_SETPOINT or reported is None or target >= reported
        ):
            codes = ", ".join(sorted(code.value for code in self.safety_hold))
            raise SettingRefusedError(409, "hold", f"safety hold ({codes})")
        if self._sent_today >= self.config.daily_budget:
            raise SettingRefusedError(
                429,
                "write_budget",
                f"the daily write budget of {self.config.daily_budget} commands is used up",
                {"limit": self.config.daily_budget},
            )
        command = Command(
            kind,
            target,
            self.config.topic(kind),
            self.config.payload(kind, target),
            RESTORE_REASON,
            actor,
        )
        queued = self._queue.pop(kind, None)
        if queued is not None:
            self._emit(
                now,
                queued.command,
                CommandStatus.DROPPED,
                queued.attempt - 1,
                "superseded by a release",
            )
        self._queue[kind] = _Pending(command, 1)
        suffix = f" ({note})" if note else ""
        detail = f"{RESTORE_PREFIX}{actor}: restore {kind.value} {reported} → {target}{suffix}"
        LOGGER.warning("%s", detail)
        return self._emit(now, command, CommandStatus.QUEUED, 0, detail)

    def restore_target(
        self, kind: IntentKind, value: int, band: tuple[int, int, str] | None = None
    ) -> tuple[int, str]:
        """Return the value a restore of ``value`` sends and why it differs, if it does.

        The static limits always apply; a water setpoint is also kept inside ``band``
        (the envelope band at the current outside temperature).
        """
        return restore_target(self.config, kind, value, band)

    def _confirm_setting(self, now: Instant, setting: PumpSetting, why: str) -> None:
        self._failed_targets.pop(setting, None)
        waiting = self._awaiting.get(AlarmCode.VERIFICATION_FAILED)
        if waiting is None or setting not in waiting:
            return
        waiting.discard(setting)
        if waiting:
            return
        del self._awaiting[AlarmCode.VERIFICATION_FAILED]
        self.alarms.clear(AlarmCode.VERIFICATION_FAILED, now, why)

    def _watch_settings(self, now: Instant, read: Reader) -> None:
        """Notice pump-setting changes ovenbird did not make (``pump_setting_changed``)."""
        busy = self.operator_busy()
        restarted = self._board.restarted_at
        recent_restart = (
            restarted is not None and now.monotonic - restarted <= self.config.restart_grace_s
        )
        for setting, spec in PUMP_SETTINGS.items():
            reported = reported_int(read(spec.signal))
            if reported is None or setting is busy:
                continue
            if self._failed_targets.get(setting) == reported:
                self._confirm_setting(now, setting, f"the pump reports {setting.value} {reported}")
            known = self._known.get(setting)
            self._known[setting] = reported
            if known is None or known == reported or recent_restart:
                continue
            message = (
                f"{spec.signal.removeprefix('main/')} changed from {known} to {reported} "
                "without ovenbird (the Panasonic remote or another client)"
            )
            if self.alarms.is_active(AlarmCode.PUMP_SETTING_CHANGED):
                self.alarms.clear(AlarmCode.PUMP_SETTING_CHANGED, now, "changed again")
            self.alarms.raise_alarm(AlarmCode.PUMP_SETTING_CHANGED, message, now)
            self._changed_at = now.monotonic
        changed = self._changed_at
        if changed is not None and now.monotonic - changed >= CHANGE_NOTICE_S:
            self._changed_at = None
            self.alarms.clear(
                AlarmCode.PUMP_SETTING_CHANGED, now, f"{CHANGE_NOTICE_S / 3600:.0f} h ago"
            )

    def _drop_operator(self, now: Instant, read: Reader) -> None:
        settings = [kind for kind in self._queue if isinstance(kind, PumpSetting)]
        if not settings:
            return
        blocked = self.operator_block(read)
        if blocked is None:
            return
        for setting in settings:
            pending = self._queue.pop(setting)
            self._emit(
                now,
                pending.command,
                CommandStatus.DROPPED,
                pending.attempt - 1,
                f"not sent: {blocked[1]}",
            )

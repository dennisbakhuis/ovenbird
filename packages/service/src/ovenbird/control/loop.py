"""The control loop: one controller tick per interval, recorded and arbitrated.

Each tick builds :class:`~ovenbird_core.control.ControlInputs` from the state
store, runs the controller, lets the arbiter compare the intents with the pump's
reported settings and, only in ``auto`` mode with a command adapter present, hands
the values to send to the adapter (after dropping queued values the controller no
longer wants and adopting values the pump already reports). Every tick is stored as
a decision row (record, arbiter decisions, command events) and pushed to WebSocket
clients, and the controller state is saved so a restart does not reset the PI. In
``shadow`` there is no adapter: the arbiter's ``send`` actions record what would
have been sent and nothing is published.

The effective mode is the configured one, except that an ``auto`` installation runs
as ``shadow`` while the publish guard's :class:`~ovenbird.control.guard.ModeHold`
holds (operator pause, configuration reset) or a release of control restores the
go-live snapshot (``ModeHold.releasing``: the controller is stopped but the adapter
still sends the restore commands). A new configuration
(:meth:`ControlLoop.reconfigure`) is swapped in between ticks: the controller state
is carried over (:func:`~ovenbird_core.control.carry_state`), and the store's
staleness policy, the adapter's setpoint clamp, the safety monitor's limits and the
registered hooks (the HA subscription set) follow; the first decision made with it
carries the new configuration version.

Overrides: the loop's :class:`~ovenbird.stove.session.StoveSession` keeps the
operator's manual wood-stove request
(:class:`~ovenbird.stove.request.StoveRequest`, ``POST api/v1/control/stove``) and
hands it to the controller as an override of kind ``stove`` on every tick until it
expires (a one-shot stop until the controller has acted on it). The request is saved
with the controller state so a restart keeps it, and every entry into and exit from
wood-stove mode is journalled as an informational ``stove_mode`` event.

The loop's :class:`~ovenbird.control.roomtarget.RoomTargets` keeps the manual boost and
away period (``api/v1/control/boost`` and ``control/away``) the same way and hands the
one in force to the controller as ``ControlInputs.room_override``; a boost wins over
away only in theory, as one ends or refuses the other. Starting wood-stove mode by hand
ends a boost. A switch of the controller's summer state is journalled as an
informational ``summer_mode`` event (``started`` when space heating stops, ``expired``
when it resumes).

The loop raises five alarms from what each tick saw: ``room_implausible`` (the
controller's cross-check, which keeps running with a wider threshold during a
wood-stove episode), ``stove_reference_missing`` (wood-stove mode is active with a
reference room configured but the reference has no fresh temperature: the back-off is
halved until it reports again), ``outside_sensor_stale`` (the chosen outside sensor
of the heating curve has no usable value or none younger than its age limit) and
``outside_sensor_implausible`` (its value is no finite number, lies outside the
plausible range or is too far from the pump's own sensor; both mean the curve uses
the pump's sensor until the chosen one is usable again, and at most one of the two is
active) and ``room_sensor_quiet``, the early warning for an
``on_change`` room sensor without proof of life (the value or a liveness signal) for
``alive_decay_end_s`` (8 h): its cooling authority is gone by then and the room runs
on the curve plus the held offset, long before ``room_sensor_silent`` at the
silence limit. It clears with the next proof of life.

Plan rule: the loop has one plan slot, ``plan_rule`` (a :class:`PlanRule`, the sun day
shift runner :class:`~ovenbird.control.dayshiftrun.DayShiftRunner` in the service). It is
asked for a slice before the controller step with :meth:`ControlLoop.plan_context` and
told the decision afterwards; a slice it returns is passed to the controller with the
tick's inputs, ``None`` leaves the inputs exactly as without a rule. A failing rule is
logged and means no plan for that tick. :meth:`ControlLoop.room_shift` reports the
room-target shift the controller applied (the safety monitor's comfort floor follows a
set-back).

Tick hooks (``tick_hooks``) run after the controller step and the room alarms, before
the arbiter: the release manager (:mod:`ovenbird.trial.release`) records the go-live
snapshot there, so nothing sent in that tick can be in it, and the envelope watch
(:mod:`ovenbird.control.envelope`) looks for the envelope rule's corrections. A failing
hook is logged and never stops the tick.
"""

from __future__ import annotations

import json
import logging
import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Protocol

from ovenbird.clock import Sleep
from ovenbird.control.adapter import CommandAdapter, CommandEvent
from ovenbird.control.alarms import AlarmBoard, AlarmCode, AlarmEvent, AlarmEventKind, Severity
from ovenbird.control.arbiter import Action, arbitrate
from ovenbird.control.forecastread import PlanContext
from ovenbird.control.guard import PublishGuard
from ovenbird.control.monitors import SafetyMonitor, monitor_config
from ovenbird.control.persist import STATE_KEY, encode_state
from ovenbird.control.roomtarget import AwayRequest, BoostRequest, RoomTargets, TargetLimits
from ovenbird.history.journal import AlarmRow, CommandRow, DecisionRow, StateRow
from ovenbird.runtime import Runtime
from ovenbird.stove.request import StoveRequest
from ovenbird.stove.session import StoveSession
from ovenbird_core import Instant, Snapshot
from ovenbird_core.catalogue import HeishaSignal
from ovenbird_core.control import (
    ControlInputs,
    DecisionRecord,
    IntentKind,
    Mode,
    OutsideReason,
    OutsideSource,
    OvenbirdConfig,
    OvenbirdController,
    OvenbirdState,
    PlanSlice,
    RoomSensorProfile,
    carry_state,
    control_inputs,
)
from ovenbird_core.control.observe import as_number
from ovenbird_core.control.record import InputValue

if TYPE_CHECKING:
    from ovenbird.config import Settings
    from ovenbird.control.dayshiftrun import DayShiftRunner
    from ovenbird.control.envelope import EnvelopeWatch
    from ovenbird.trial.release import ReleaseManager

LOGGER = logging.getLogger("ovenbird.control")
RECENT_COMMANDS: Final = 50
COMPACT: Final = (",", ":")
SUMMER_JOURNAL_CODE: Final = "summer_mode"


class PlanRule(Protocol):
    """What the loop's plan slot holds: a rule that may hand the controller a plan slice."""

    def step(self, ctx: PlanContext) -> PlanSlice | None:
        """Return the slice for this tick (``None``: no plan)."""
        ...

    def after(self, decision: DecisionRecord) -> None:
        """Take note of the tick's decision."""
        ...


class JournalSink(Protocol):
    """Where decision and command rows go (the history writer)."""

    def offer_decision(self, row: DecisionRow) -> None:
        """Queue a decision row."""
        ...

    def offer_command(self, row: CommandRow) -> None:
        """Queue a command row."""
        ...


def controller_config(settings: Settings) -> OvenbirdConfig:
    """Return the controller configuration the settings describe.

    The emitter preset with every set field applied; the safety envelope stays
    anchored to the preset curve (see :meth:`ovenbird.config.Settings.controller_config`).
    """
    return settings.controller_config()


def _shown(value: InputValue) -> str:
    """Return an input value as ``<n> °C`` text, or a note that it is no finite number."""
    number = as_number(value)
    return "a value that is no finite number" if number is None else f"{number:g} °C"


def outside_message(source: OutsideSource, decision: DecisionRecord) -> str:
    """Return the alarm text for a decision whose curve did not use the chosen outside sensor.

    Parameters
    ----------
    source
        The chosen outside sensor.
    decision
        The decision; its ``outside_reason`` says why the sensor was not used.

    Returns
    -------
    str
        What was wrong (no usable value, too old, implausible, too far from the pump's
        sensor) and that the curve uses the pump's own sensor meanwhile.
    """
    values = {str(ref.signal): ref.value for ref in decision.inputs_used}
    signal = str(source.signal)
    chosen = _shown(values.get(signal))
    pump = _shown(values.get(str(HeishaSignal.OUTSIDE_TEMP)))
    uses = "the heating curve uses the pump's own outside sensor"
    match decision.controller_state.get("outside_reason"):
        case OutsideReason.MISSING:
            return f"the outside sensor {signal} has no usable value; {uses} until it reports again"
        case OutsideReason.IMPLAUSIBLE:
            return (
                f"the outside sensor {signal} reads {chosen}, outside the plausible range of "
                f"{source.plausible_min_c:g} to {source.plausible_max_c:g} °C; {uses} until it "
                "reads a plausible value again"
            )
        case OutsideReason.DEVIATES:
            return (
                f"the outside sensor {signal} reads {chosen}, more than "
                f"{source.max_deviation_k:g} K from the pump's own outside sensor ({pump}); "
                f"{uses} until the two agree again"
            )
        case _:
            return (
                f"the outside sensor {signal} has no value younger than "
                f"{source.max_age_s / 60:.0f} min; {uses} until it reports again"
            )


def command_row(event: CommandEvent) -> CommandRow:
    """Return the stored form of a command event."""
    return CommandRow(
        ts=event.at.wall.timestamp(),
        kind=event.kind.value,
        value=event.value,
        status=event.status.value,
        attempt=event.attempt,
        topic=event.topic,
        payload=event.payload,
        detail=event.detail,
    )


def alarm_row(event: AlarmEvent) -> AlarmRow:
    """Return the stored form of an alarm transition."""
    return AlarmRow(
        ts=event.at.wall.timestamp(),
        code=event.code,
        severity=event.severity.value,
        event=event.event.value,
        message=event.message,
        detail=event.detail_text(),
    )


@dataclass
class CommandJournal:
    """Fan command events out to the history writer and a short in-memory list.

    Parameters
    ----------
    sink
        History writer; ``None`` keeps events in memory only.
    """

    sink: JournalSink | None = None
    recent: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=RECENT_COMMANDS))

    def __call__(self, event: CommandEvent) -> None:
        """Record one event."""
        self.recent.append(event.to_json())
        if self.sink is not None:
            self.sink.offer_command(command_row(event))


class ControlLoop:
    """Run the controller on a fixed interval of the service clock.

    Parameters
    ----------
    runtime
        Clock and state store.
    controller
        The controller.
    mode
        Operating mode.
    guard
        Publish guard (reported in :meth:`status`).
    alarms
        Alarm board shared with the adapter.
    adapter
        Command adapter; ``None`` unless the guard permits publishing.
    sink
        Receives decision rows.
    room_signal
        Room temperature signal id.
    room_profile
        Room sensor profile (step and reporting kind of the room input).
    interval_s
        Seconds between ticks.
    sleep
        Sleeps on the service clock.
    on_decision
        Called with every decision's API payload (WebSocket broadcast).
    state_sink
        Receives the controller state after every tick (persistence).
    initial_state
        State to start from (restored after a restart); a fresh one when omitted.
    config_version
        Configuration version the loop starts with (``None`` without a store).
    on_config
        Called with the version and the instant once a new configuration is in
        effect (after :meth:`reconfigure`, at the next tick).
    stove_request
        Manual wood-stove request to start with (restored after a restart).
    target_limits
        Boost and away settings; the defaults with the controller's comfort when omitted.
    boost_request, away_request
        Boost and away period to start with (restored after a restart).
    """

    def __init__(
        self,
        runtime: Runtime,
        controller: OvenbirdController,
        *,
        mode: Mode,
        guard: PublishGuard,
        alarms: AlarmBoard,
        adapter: CommandAdapter | None = None,
        sink: JournalSink | None = None,
        room_signal: str | None = None,
        room_profile: RoomSensorProfile | None = None,
        interval_s: float = 60.0,
        sleep: Sleep | None = None,
        on_decision: Callable[[dict[str, Any]], None] | None = None,
        state_sink: Callable[[StateRow], None] | None = None,
        initial_state: OvenbirdState | None = None,
        config_version: int | None = None,
        on_config: Callable[[int | None, Instant], None] | None = None,
        stove_request: StoveRequest | None = None,
        target_limits: TargetLimits | None = None,
        boost_request: BoostRequest | None = None,
        away_request: AwayRequest | None = None,
    ) -> None:
        if adapter is not None and not guard.installed:
            raise ValueError("an adapter requires a publish guard that permits publishing")
        self.runtime = runtime
        self.controller = controller
        self.mode = mode
        self.guard = guard
        self.alarms = alarms
        self.adapter = adapter
        self.sink = sink
        self.room_signal = room_signal
        self.room_profile = room_profile or controller.config.room
        self.interval_s = interval_s
        self._sleep = sleep
        self.on_decision = on_decision
        self.state_sink = state_sink
        self.restored = initial_state is not None
        self.state: OvenbirdState = initial_state or controller.initial_state()
        self.latest: dict[str, Any] | None = None
        self.latest_state: dict[str, Any] | None = None
        self.latest_binding: str | None = None
        self.ticks = 0
        self.desired_setpoint: int | None = None
        self.safety: SafetyMonitor | None = None
        self.config_version = config_version
        self.on_config = on_config
        self.reconfigure_hooks: list[Callable[[Settings], None]] = []
        self._pending: tuple[Settings, int | None] | None = None
        self.stove = StoveSession(lambda: self.runtime.clock(), self, stove_request)
        limits = target_limits or TargetLimits(comfort_c=controller.config.comfort_room_c)
        self.targets = RoomTargets(self, limits, boost_request, away_request)
        self.last_tick: Instant | None = None
        self.tick_hooks: list[Callable[[Instant, Mode], None]] = []
        self.release: ReleaseManager | None = None
        self.envelope: EnvelopeWatch | None = None
        self.plan_rule: PlanRule | None = None
        self.dayshift: DayShiftRunner | None = None

    @property
    def effective_mode(self) -> Mode:
        """The mode the controller runs in: ``shadow`` while an ``auto`` install is held."""
        hold = self.guard.hold
        if self.mode is Mode.AUTO and (hold.active or hold.releasing):
            return Mode.SHADOW
        return self.mode

    def reconfigure(self, settings: Settings, version: int | None) -> None:
        """Swap in a new configuration at the start of the next tick.

        Parameters
        ----------
        settings
            Validated settings of the new configuration.
        version
            Its configuration version.

        Raises
        ------
        ValueError
            When the controller rejects the configuration (it stays unchanged).
        """
        controller_config(settings)
        self._pending = (settings, version)

    @property
    def reconfigure_pending(self) -> bool:
        """Whether a new configuration waits for the next tick."""
        return self._pending is not None

    def _apply_pending(self, moment: Instant) -> None:
        """Switch to the configuration an apply queued, keeping the controller state.

        Parameters
        ----------
        moment
            Time of the tick that applies the change.
        """
        pending = self._pending
        if pending is None:
            return
        self._pending = None
        settings, version = pending
        old = self.controller.config
        new = controller_config(settings)
        self.state = carry_state(self.state, old, new)
        self.controller = OvenbirdController(new, self.controller.name)
        if new.stove is None and self.stove.request is not None:
            self.stove.set(None, moment)
        self.targets.configure(TargetLimits.from_settings(settings), moment)
        self.room_signal = settings.control_room_signal
        self.room_profile = new.room
        self.runtime.store.policy = settings.staleness_policy()
        safety = new.safety
        if self.adapter is not None:
            self.adapter.set_setpoint_range(
                math.ceil(safety.min_setpoint_c - 1e-9), math.floor(safety.max_supply_c + 1e-9)
            )
            self.adapter.set_envelope_rule(safety)
        if self.safety is not None:
            self.safety.config = monitor_config(settings, safety.max_supply_c)
        for hook in self.reconfigure_hooks:
            hook(settings)
        self.config_version = version
        LOGGER.warning("configuration version %s in effect", version)
        if self.on_config is not None:
            self.on_config(version, moment)

    def tick(self, now: Instant | None = None) -> DecisionRow:
        """Run one controller tick.

        Parameters
        ----------
        now
            Tick instant; the runtime clock when omitted.

        Returns
        -------
        DecisionRow
            The stored decision.
        """
        moment = now or self.runtime.clock()
        self._apply_pending(moment)
        mode = self.effective_mode
        snapshot = self.runtime.store.snapshot(moment)
        request = self.stove.live(moment)
        inputs = control_inputs(
            snapshot,
            room_signal=self.room_signal,
            mode=mode,
            override=None if request is None else request.override(moment),
            room_profile=self.room_profile,
            room_override=self.targets.live(moment),
        )
        plan = self._plan(moment, inputs)
        if plan is not None:
            inputs = replace(inputs, plan=plan)
        summer_before = self.state.summer_active
        result = self.controller.step(self.state, inputs)
        self.state = result.state
        self.stove.after(result.decision, moment)
        self._summer_event(summer_before, result.decision, moment)
        if self.plan_rule is not None:
            try:
                self.plan_rule.after(result.decision)
            except Exception:
                LOGGER.exception("the plan rule could not take note of the decision")
        self._room_alarm(result.decision, moment)
        self.stove.reference_alarm(self.controller.config.stove, result.decision, moment)
        self._outside_alarm(result.decision, moment)
        self._quiet_alarm(snapshot, moment)
        for hook in self.tick_hooks:
            try:
                hook(moment, mode)
            except Exception:
                LOGGER.exception("tick hook failed")
        adapter = self.adapter if mode is Mode.AUTO else None
        decisions = arbitrate(
            result.intents, inputs.actual, adapter.view() if adapter is not None else None
        )
        sends = [item.intent for item in decisions if item.action is Action.SEND]
        self.desired_setpoint = next(
            (
                intent.value
                for intent in result.intents
                if intent.kind is IntentKind.WATER_SETPOINT and type(intent.value) is int
            ),
            None,
        )
        events: tuple[CommandEvent, ...] = ()
        if adapter is not None:
            events = adapter.reconcile(result.intents, moment)
            for item in decisions:
                applied = item.action is Action.NONE and item.reason == "already applied"
                if applied and type(item.intent.value) is int:
                    adapter.adopt(item.intent.kind, item.intent.value, moment)
            if sends:
                events += adapter.submit(sends, moment)
        record = result.decision
        self.latest_state = dict(record.controller_state)
        self.latest_binding = record.binding
        row = DecisionRow(
            ts=moment.wall.timestamp(),
            controller=record.controller,
            mode=record.mode.value,
            ladder=record.ladder.value,
            reason=record.reason.value,
            setpoint=record.setpoint,
            record=json.dumps(record.to_json_dict(), separators=COMPACT, ensure_ascii=False),
            arbiter=json.dumps([item.to_json() for item in decisions], separators=COMPACT),
            commands=json.dumps(
                [event.to_json() for event in events], separators=COMPACT, ensure_ascii=False
            ),
            config_version=self.config_version,
        )
        self.ticks += 1
        self.last_tick = moment
        if self.sink is not None:
            self.sink.offer_decision(row)
        if self.state_sink is not None:
            self.state_sink(StateRow(STATE_KEY, row.ts, encode_state(self.state, moment)))
        self.latest = row.payload()
        if self.on_decision is not None:
            self.on_decision(self.latest)
        level = logging.INFO if sends else logging.DEBUG
        LOGGER.log(
            level,
            "%s %s setpoint %s (%s); %s",
            record.mode.value,
            record.ladder.value,
            record.setpoint,
            record.reason.value,
            ", ".join(f"{d.intent.kind.value}={d.intent.value}:{d.action.value}" for d in decisions)
            or "no intents",
        )
        return row

    def plan_context(self, moment: Instant, inputs: ControlInputs) -> PlanContext:
        """Return what a plan rule needs at ``moment``.

        The room counts as trusted when the controller has a fresh room value that its
        cross-check did not reject at the previous tick.
        """
        room = inputs.room
        plausible = (self.latest_state or {}).get("room_plausible") is not False
        trusted = room is not None and room.fresh and plausible
        return PlanContext(
            now=moment,
            room_trusted=trusted,
            stove_active=self.state.stove_active,
            outside_filtered_c=self.state.outside_filtered,
            config=self.controller.config,
            room_c=room.value if trusted and room is not None else None,
            away=self.targets.away_active(moment.wall),
        )

    def room_shift(self) -> float | None:
        """Return the room-target shift of the latest decision (effective target minus comfort).

        ``None`` before the first tick or without a room value (no target then).
        """
        target = as_number((self.latest_state or {}).get("room_target_c"))
        if target is None:
            return None
        return target - self.controller.config.comfort_room_c

    def _plan(self, moment: Instant, inputs: ControlInputs) -> PlanSlice | None:
        """Return the slice of the plan rule for this tick (``None``: none, or it failed)."""
        rule = self.plan_rule
        if rule is None:
            return None
        try:
            return rule.step(self.plan_context(moment, inputs))
        except Exception:
            LOGGER.exception("the plan rule failed; no plan this tick")
            return None

    def request_stove(
        self, on: bool, until: datetime | None, actor: str, now: Instant | None = None
    ) -> StoveRequest:
        """Accept a manual wood-stove request; it takes effect at the next tick.

        Parameters
        ----------
        on
            Start (or keep) wood-stove mode; ``False`` stops it.
        until
            End of the request; a start without one lasts 8 h (at most the episode
            cap), a stop without one is one-shot.
        actor
            Who asks.
        now
            Current instant; the runtime clock when omitted.

        Returns
        -------
        StoveRequest
            The stored request.

        Raises
        ------
        StoveRequestError
            When wood-stove mode is not enabled or ``until`` is not acceptable.
        """
        moment = now or self.runtime.clock()
        accepted = self.stove.accept(self.controller.config.stove, on, until, actor, moment)
        if on:
            self.targets.end_boost(moment, "wood-stove mode started by hand")
        return accepted

    def request_boost(
        self,
        *,
        offset_k: float | None,
        target_c: float | None,
        duration_s: float | None,
        until: datetime | None,
        actor: str,
        now: Instant | None = None,
    ) -> BoostRequest:
        """Accept a boost (see :meth:`RoomTargets.accept_boost`); it acts at the next tick.

        Parameters
        ----------
        offset_k
            Boost as a raise of the room target, in kelvin.
        target_c
            Boost as an absolute room target, in degrees Celsius.
        duration_s
            Length of the boost, in seconds.
        until
            End of the boost as a wall-clock time.
        actor
            Who asks, for the journal.
        now
            Time of the request; the service clock when omitted.

        Raises
        ------
        RoomTargetError
            When boost is off or away is set (409), or a value is refused (400).
        """
        return self.targets.accept_boost(
            offset_k=offset_k,
            target_c=target_c,
            duration_s=duration_s,
            until=until,
            actor=actor,
            moment=now or self.runtime.clock(),
        )

    def request_away(
        self,
        *,
        target_c: float | None,
        until: datetime,
        lead_s: float | None,
        actor: str,
        now: Instant | None = None,
    ) -> AwayRequest:
        """Accept an away period (see :meth:`RoomTargets.accept_away`); it ends a boost.

        Parameters
        ----------
        target_c
            Room target while away, in degrees Celsius.
        until
            End of the away period.
        lead_s
            How long before the end heating restarts, in seconds.
        actor
            Who asks, for the journal.
        now
            Time of the request; the service clock when omitted.

        Raises
        ------
        RoomTargetError
            When away is off (409) or a value is refused (400).
        """
        return self.targets.accept_away(
            target_c=target_c,
            until=until,
            lead_s=lead_s,
            actor=actor,
            moment=now or self.runtime.clock(),
        )

    def end_boost(self, actor: str, now: Instant | None = None) -> BoostRequest | None:
        """End the boost (``None`` when there was none)."""
        return self.targets.end_boost(now or self.runtime.clock(), f"ended by {actor}")

    def end_away(self, actor: str, now: Instant | None = None) -> AwayRequest | None:
        """End the away period (``None`` when there was none)."""
        return self.targets.end_away(now or self.runtime.clock(), f"ended by {actor}")

    def boost_status(self) -> dict[str, Any]:
        """Return the API form of the boost."""
        return self.targets.boost_status(self.runtime.clock(), self.latest_state)

    def away_status(self) -> dict[str, Any]:
        """Return the API form of away."""
        return self.targets.away_status(self.runtime.clock(), self.latest_state)

    def lowered_target(self) -> float | None:
        """Return the manual room target below comfort in force (away, a cooler boost)."""
        return self.targets.lowered_target_c(self.runtime.clock().wall)

    def summer_status(self) -> dict[str, Any]:
        """Return the API form of the summer switch: settings, slow mean and state."""
        summer = self.controller.config.summer
        state = self.state
        return {
            "enabled": summer is not None,
            "active": summer is not None and state.summer_active,
            "mean_c": None if summer is None else state.summer_mean_c,
            "off_c": None if summer is None else summer.off_c,
            "on_c": None if summer is None else summer.on_c,
            "mean_tau_s": None if summer is None else summer.mean_tau_s,
            "warming_up": summer is not None and self._summer_warming(summer.mean_tau_s),
        }

    def _summer_warming(self, tau_s: float) -> bool:
        """Whether the slow outside mean is younger than one time constant."""
        since = self.state.summer_mean_from
        if since is None or self.last_tick is None:
            return True
        return self.last_tick.monotonic - since < tau_s

    def _summer_event(self, before: bool, decision: DecisionRecord, moment: Instant) -> None:
        """Journal a switch of the summer state as an informational ``summer_mode`` event."""
        after = self.state.summer_active
        if after == before:
            return
        mean = self.state.summer_mean_c
        shown = "unknown" if mean is None else f"{mean:.1f} °C"
        if after:
            kind = AlarmEventKind.STARTED
            message = f"summer switch: no space heating (slow outside mean {shown})"
        else:
            kind = AlarmEventKind.EXPIRED
            message = f"summer switch: space heating resumes (slow outside mean {shown})"
        LOGGER.warning("%s", message)
        detail = {"mean_c": mean, "setpoint": decision.setpoint}
        self.alarms.record(
            AlarmEvent(moment, SUMMER_JOURNAL_CODE, Severity.INFO, kind, message, detail)
        )

    @property
    def stove_request(self) -> StoveRequest | None:
        """The manual wood-stove request in force, if any."""
        return self.stove.request

    @stove_request.setter
    def stove_request(self, request: StoveRequest | None) -> None:
        """Replace the manual request without saving it (as an attribute assignment)."""
        self.stove.request = request

    def stove_status(self) -> dict[str, Any]:
        """Return the API form of wood-stove mode: configuration, state and request."""
        return self.stove.status(self.controller.config.stove, self.state, self.latest_state)

    def _room_alarm(self, decision: DecisionRecord, moment: Instant) -> None:
        """Raise or clear the room-implausible alarm from the decision."""
        code = AlarmCode.ROOM_IMPLAUSIBLE
        plausible = decision.controller_state.get("room_plausible")
        if plausible is False:
            term = decision.term("room_feedback")
            message = term.note if term is not None else "room value implausible"
            self.alarms.raise_alarm(code, message, moment)
        elif plausible is True or self.room_profile.crosscheck is None:
            self.alarms.clear(code, moment, "room value and cross-check agree")

    def _outside_alarm(self, decision: DecisionRecord, moment: Instant) -> None:
        """Raise or clear the outside-sensor alarms from the decision.

        Parameters
        ----------
        decision
            Decision of the tick.
        moment
            Time of the tick.
        """
        stale, implausible = AlarmCode.OUTSIDE_SENSOR_STALE, AlarmCode.OUTSIDE_SENSOR_IMPLAUSIBLE
        source = self.controller.config.outside
        if source is None:
            for code in (stale, implausible):
                self.alarms.clear(code, moment, "the curve uses the pump's outside sensor")
            return
        state = decision.controller_state
        fallback = state.get("outside_fallback")
        if fallback is False:
            self.alarms.clear(stale, moment, "the outside sensor reports again")
            self.alarms.clear(implausible, moment, "the outside sensor reads a plausible value")
            return
        if fallback is not True:
            return
        reason = state.get("outside_reason")
        rejected = reason in (OutsideReason.IMPLAUSIBLE, OutsideReason.DEVIATES)
        code, other = (implausible, stale) if rejected else (stale, implausible)
        self.alarms.clear(other, moment, f"the outside sensor is {reason or 'not used'} now")
        detail = {"signal": str(source.signal), "reason": reason}
        self.alarms.raise_alarm(code, outside_message(source, decision), moment, detail)

    def _quiet_alarm(self, snapshot: Snapshot, moment: Instant) -> None:
        """Raise or clear the quiet room sensor alarm from the sensor's age."""
        code = AlarmCode.ROOM_SENSOR_QUIET
        profile = self.room_profile
        signal = self.room_signal
        if signal is None or not profile.held:
            self.alarms.clear(code, moment, "no on_change room sensor")
            return
        view = snapshot.get(signal)
        if view is None or view.age is None:
            return
        limit = profile.alive_decay_end_s
        if view.age <= limit:
            self.alarms.clear(code, moment, "the room sensor reported again")
            return
        self.alarms.raise_alarm(
            code,
            f"no proof of life from the room sensor for {view.age / 3600:.1f} h (limit "
            f"{limit / 3600:.0f} h); its cooling authority is gone, so the room runs on the "
            f"curve plus the held offset until it reports again (room_sensor_silent "
            f"follows at {profile.silence_limit_s / 3600:.0f} h)",
            moment,
        )

    def room_status(self, now: Instant | None = None) -> dict[str, Any] | None:
        """Return the API form of the room input: profile, held and alive ages, link."""
        signal = self.room_signal
        if signal is None:
            return None
        moment = now or self.runtime.clock()
        store = self.runtime.store
        view = store.view(signal, moment)
        profile = self.room_profile
        state = self.latest_state or {}
        return {
            "signal": signal,
            "profile": profile.kind.value,
            "step_k": profile.quantum_k,
            "max_age_s": None if view is None else view.max_age,
            "report_interval_s": profile.report_interval_s,
            "silence_limit_s": profile.silence_limit_s,
            "liveness": list(profile.liveness),
            "crosscheck": profile.crosscheck,
            "value": None if view is None else view.value,
            "fresh": view is not None and view.fresh,
            "held_s": None if view is None or view.held is None else round(view.held, 1),
            "alive_s": None if view is None or view.age is None else round(view.age, 1),
            "alive_by": None if view is None else view.alive_by,
            "link_up": None if view is None else store.link_up(view.source, moment),
            "authority": state.get("room_authority"),
            "plausible": state.get("room_plausible"),
        }

    def status(self) -> dict[str, Any]:
        """Return the API form of the control state."""
        now = self.runtime.clock()
        hold = self.guard.hold
        return {
            "mode": self.effective_mode.value,
            "configured_mode": self.mode.value,
            "paused": hold.paused,
            "reset_pending": hold.reset_pending,
            "releasing": hold.releasing,
            "config_version": self.config_version,
            "controller": self.controller.name,
            "interval_s": self.interval_s,
            "ticks": self.ticks,
            "restored_state": self.restored,
            "publishing": self.guard.permits,
            "refusals": list(self.guard.refusals()),
            "alarms": [alarm.to_json() for alarm in self.alarms.active()],
            "safety": self.safety.status() if self.safety is not None else None,
            "adapter": self.adapter.status(now) if self.adapter is not None else None,
            "room": self.room_status(now),
            "stove": self.stove_status(),
            "boost": self.boost_status(),
            "away": self.away_status(),
            "summer": self.summer_status(),
        }

    async def run(self) -> None:
        """Tick forever on the configured interval."""
        if self._sleep is None:
            raise RuntimeError("ControlLoop.run needs a sleep function")
        while True:
            self.tick()
            await self._sleep(self.interval_s)

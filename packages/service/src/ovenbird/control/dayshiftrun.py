"""The sun day shift runner: the rule every quarter hour, a rule plan slice in ``on``.

The runner sits in the control loop's plan slot. Every quarter hour of the loop's clock
(the simulated one too) it reads the stored forecast and the guards
(:mod:`ovenbird.control.forecastread`) and evaluates
:func:`ovenbird_core.control.dayshift.decide` in the local zone ``control_timezone``;
it evaluates at once as well when a guard that
can change inside a slice (room trust, wood stove, its tail) changes, and again at the
next tick while the controller has no filtered outside temperature yet (the first tick
after a cold start). What it does depends on ``control_dayshift_use``:

``off``
    nothing is read, computed, recorded or persisted.
``shadow``
    the rule runs and records what it would do, but the controller never gets a slice
    (``plan=None``), so every decision is that of ``off``.
``on``
    a non-zero offset becomes a :class:`~ovenbird_core.control.PlanSlice` of source
    ``rule`` (``plan_preheat`` for a boost, ``plan_setback`` for a set-back), valid for
    :data:`SLICE_VALID_S` from its evaluation, so it expires by itself when the next
    evaluation does not come. A failing live guard withdraws it at once. ``on`` is
    experimental: the settings only hold it together with
    ``control_dayshift_experimental_ok`` (:mod:`ovenbird.config.validation.dayshift`).

Recording (while not ``off``): at every tick ``derived/dayshift_offset_k``, the offset
the controller got (0 in ``shadow`` and without a slice), and
``derived/dayshift_shadow_k``, the offset the rule computed whether or not it was handed
over. Both go to the history writer only, never into the state store, so the controller
cannot read them. The start and end of a boost or a set-back and a cancel are journalled
as informational ``dayshift`` events (no alarm, no notification) with the event code
(``boost_start``, ``boost_end``, ``setback_start``, ``setback_end``, ``cancel``) and the
reasons in the detail.

Restart: the rule's memory (whether a day boosted, the offset the step limit starts
from, the phase) is saved in the ``control_state`` table under ``dayshift`` after every
evaluation and read back at the first tick. An offset saved more than
:data:`SLICE_VALID_S` ago counts as zero (its slice has expired); the rest is kept, so
the night after a boosted day still sets back after a restart and an unchanged phase is
not journalled again.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Protocol

from ovenbird.clock import iso_from_unix, iso_z
from ovenbird.config import Settings
from ovenbird.configstore.fields import Feature
from ovenbird.control.alarms import AlarmBoard, AlarmEvent, AlarmEventKind, Severity
from ovenbird.control.dayshift import (
    OFFSET_DIGITS,
    SLICE_VALID_S,
    SLOT_S,
    DayShiftInputs,
    DayShiftMemory,
    DayShiftResult,
    Phase,
    Reason,
    decide,
    params_from_settings,
    rule_slice,
)
from ovenbird.control.features import EXPERIMENTAL, on_available
from ovenbird.control.forecastread import (
    ForecastWindow,
    Guard,
    PlanContext,
    StoveTail,
    guards,
    live_guards,
    load_forecast,
)
from ovenbird.history.database import Sample, SampleKind
from ovenbird.history.journal import StateRow, read_state
from ovenbird_core import Instant
from ovenbird_core.control import DecisionRecord, PlanSlice
from ovenbird_core.control.observe import as_number

LOGGER = logging.getLogger("ovenbird.control.dayshift")
OFFSET_SIGNAL: Final = "derived/dayshift_offset_k"
SHADOW_SIGNAL: Final = "derived/dayshift_shadow_k"
UNIT: Final = "K"
HORIZON_H: Final = 30.0
MEMORY_KEY: Final = "dayshift"
JOURNAL_CODE: Final = "dayshift"
MIN_HOLD_S: Final = 120.0
ACTIVE_PHASES: Final = frozenset({Phase.BOOST, Phase.SETBACK})


class SampleSink(Protocol):
    """Where the derived signals go (the history writer)."""

    def offer(self, sample: Sample) -> None:
        """Queue a sample."""
        ...


class JournalEvent(StrEnum):
    """Day shift events written to the journal."""

    BOOST_START = "boost_start"
    BOOST_END = "boost_end"
    SETBACK_START = "setback_start"
    SETBACK_END = "setback_end"
    CANCEL = "cancel"


EVENT_TEXT: Final = {
    JournalEvent.BOOST_START: "boost started",
    JournalEvent.BOOST_END: "boost ended",
    JournalEvent.SETBACK_START: "night set-back started",
    JournalEvent.SETBACK_END: "night set-back ended",
    JournalEvent.CANCEL: "cancelled",
}


def transitions(before: Phase, after: Phase) -> tuple[JournalEvent, ...]:
    """Return the journal events of a change of phase.

    Parameters
    ----------
    before, after
        The phase of the previous and of this evaluation.

    Returns
    -------
    tuple of JournalEvent
        The end of a boost or set-back that ended normally, a cancel when an active one
        became blocked, and the start of a new one.
    """
    if before is after:
        return ()
    events: list[JournalEvent] = []
    if after is Phase.BLOCKED and before in ACTIVE_PHASES:
        events.append(JournalEvent.CANCEL)
    elif before is Phase.BOOST:
        events.append(JournalEvent.BOOST_END)
    elif before is Phase.SETBACK:
        events.append(JournalEvent.SETBACK_END)
    if after is Phase.BOOST:
        events.append(JournalEvent.BOOST_START)
    elif after is Phase.SETBACK:
        events.append(JournalEvent.SETBACK_START)
    return tuple(events)


def load_memory(path: Path) -> tuple[DayShiftMemory, float] | None:
    """Return the saved memory and when it was saved (``None``: none or unreadable)."""
    row = read_state(path, MEMORY_KEY)
    if row is None:
        return None
    try:
        body = json.loads(row.value)
        if not isinstance(body, dict):
            return None
        return DayShiftMemory.from_json(body), row.ts
    except ValueError, KeyError, TypeError:
        LOGGER.warning("the saved day shift memory is unreadable; starting afresh")
        return None


def plan_slice(result: DayShiftResult, now: Instant) -> PlanSlice | None:
    """Return the rule slice of an evaluation (``None`` for a zero offset)."""
    return rule_slice(result, now)


@dataclass
class DayShiftRunner:
    """Evaluate the sun day shift and hand its slice to the control loop.

    Parameters
    ----------
    settings
        Effective settings (kept current by :meth:`reconfigure`).
    sink
        History writer for the derived signals; ``None`` records nothing.
    alarms
        Alarm board whose journal receives the day shift events (never its listeners).
    state_sink
        Saves the memory (the history writer's ``offer_state``); ``None`` keeps it in
        memory only.
    load_forecast, load_memory
        Readers of the stored forecast and the saved memory (tests replace them).
    """

    settings: Settings
    sink: SampleSink | None = None
    alarms: AlarmBoard | None = None
    state_sink: Callable[[StateRow], None] | None = None
    load_forecast: Callable[[Path, float, float], ForecastWindow] = load_forecast
    load_memory: Callable[[Path], tuple[DayShiftMemory, float] | None] = load_memory
    memory: DayShiftMemory = field(default_factory=DayShiftMemory, init=False)
    result: DayShiftResult | None = field(default=None, init=False)
    window: ForecastWindow | None = field(default=None, init=False)
    evaluations: int = field(default=0, init=False)
    _slice: PlanSlice | None = field(default=None, init=False, repr=False)
    _slot: int | None = field(default=None, init=False, repr=False)
    _live: tuple[Guard, ...] | None = field(default=None, init=False, repr=False)
    _booted: bool = field(default=False, init=False, repr=False)
    _tail: StoveTail = field(default_factory=StoveTail, init=False, repr=False)
    _offered: PlanSlice | None = field(default=None, init=False, repr=False)
    _applied_k: float = field(default=0.0, init=False, repr=False)
    _comfort_c: float = field(default=0.0, init=False, repr=False)

    @property
    def use(self) -> str:
        """The switch: ``off``, ``shadow`` or ``on``."""
        return str(self.settings.control_dayshift_use)

    @property
    def applied_k(self) -> float:
        """The offset the controller applied at the latest tick (0 without one)."""
        return self._applied_k

    def reconfigure(self, settings: Settings) -> None:
        """Follow a new configuration: withdraw the slice and evaluate at the next tick."""
        self.settings = settings
        self._slice = None
        self._slot = None

    def step(self, ctx: PlanContext) -> PlanSlice | None:
        """Evaluate when due and return the slice to apply at this tick.

        Never raises: a failure is logged and means no plan.

        Parameters
        ----------
        ctx
            What the control loop knows at this tick.

        Returns
        -------
        PlanSlice or None
            Only with ``on``, no failing live guard and a non-zero offset in
            force; ``None`` otherwise (always in ``shadow`` and ``off``).
        """
        self._offered = None
        try:
            return self._step(ctx)
        except Exception:
            LOGGER.exception("the day shift failed; no plan this tick")
            self._slice = None
            self.result = None
            return None

    def after(self, decision: DecisionRecord) -> None:
        """Note what the controller applied and record the derived signals of the tick."""
        self._applied_k = self._applied(decision)
        if self.use == "off":
            return
        result = self.result
        self._write(OFFSET_SIGNAL, decision.at, self._applied_k)
        self._write(SHADOW_SIGNAL, decision.at, None if result is None else result.offset_k)

    def _applied(self, decision: DecisionRecord) -> float:
        """Return the room-target shift the offered slice had in ``decision`` (0 if none)."""
        offered = self._offered
        if offered is None:
            return 0.0
        target = as_number(decision.controller_state.get("room_target_c"))
        if target is not None:
            return round(target - self._comfort_c, OFFSET_DIGITS)
        term = decision.term("plan")
        return offered.room_offset_k if term is not None and term.value != 0.0 else 0.0

    def _step(self, ctx: PlanContext) -> PlanSlice | None:
        """Run one tick (see :meth:`step`).

        Parameters
        ----------
        ctx
            Plan context of this tick (clock, configuration, filtered outside temperature).
        """
        use = self.use
        if use == "off":
            self._idle()
            return None
        self._comfort_c = ctx.config.comfort_room_c
        self._tail.restore(self.settings.history_path, self.alarms, ctx)
        stove_end = self._tail.track(ctx)
        if not self._booted:
            self._boot(ctx.now)
        live = live_guards(ctx, stove_end)
        slot = math.floor(ctx.now.wall.timestamp() / SLOT_S)
        if slot != self._slot or live != self._live:
            self._slot = slot if ctx.outside_filtered_c is not None else None
            self._live = live
            self._evaluate(ctx, stove_end, use)
        plan = self._slice
        if use != "on" or live or plan is None or not plan.active(ctx.now):
            return None
        self._offered = plan
        return plan

    def _idle(self) -> None:
        """Forget the evaluation while the day shift is off."""
        self.result = None
        self.window = None
        self._slice = None
        self._slot = None
        self._live = None
        self._applied_k = 0.0
        self._tail = StoveTail()

    def _boot(self, now: Instant) -> None:
        """Read the saved memory back once."""
        self._booted = True
        try:
            saved = self.load_memory(self.settings.history_path)
        except Exception:
            LOGGER.exception("could not read the saved day shift memory")
            return
        if saved is None:
            return
        memory, saved_at = saved
        if now.wall.timestamp() - saved_at >= SLICE_VALID_S:
            memory = replace(memory, offset_k=0.0)
        self.memory = memory

    def _evaluate(self, ctx: PlanContext, stove_end: float | None, use: str) -> None:
        """Evaluate the rule, journal a change of phase and save the memory.

        Parameters
        ----------
        ctx
            Plan context of this tick.
        stove_end
            Unix time the wood stove mode ended, if recently.
        use
            Configured use of the day shift: ``off``, ``shadow`` or active.
        """
        moment = ctx.now
        now_ts = moment.wall.timestamp()
        window = self.load_forecast(self.settings.history_path, now_ts, HORIZON_H)
        failing = guards(ctx, window, stove_end)
        inputs = DayShiftInputs(
            now=moment.wall,
            outside_c=ctx.outside_filtered_c,
            hours=window.hours,
            room_c=ctx.room_c,
            comfort_c=ctx.config.comfort_room_c,
            guards=tuple(guard.value for guard in failing),
        )
        params = replace(params_from_settings(self.settings), max_k=ctx.config.plan_rule_max_k)
        before = self.memory.phase
        result = decide(params, inputs, self.memory)
        self.evaluations += 1
        self.window = window
        self.result = result
        self.memory = result.memory
        self._slice = plan_slice(result, moment)
        for event in transitions(before, result.phase):
            self._journal(moment, event, result, use)
        if self.state_sink is not None:
            text = json.dumps(result.memory.to_json(), separators=(",", ":"))
            self.state_sink(StateRow(MEMORY_KEY, now_ts, text))

    def _write(self, signal: str, moment: Instant, value: float | None) -> None:
        """Offer one derived sample to the history writer."""
        if self.sink is None:
            return
        hold = max(MIN_HOLD_S, 2.0 * self.settings.control_interval_s)
        self.sink.offer(
            Sample(signal, UNIT, SampleKind.NUMBER, moment.wall.timestamp(), value, hold)
        )

    def _journal(
        self, moment: Instant, event: JournalEvent, result: DayShiftResult, use: str
    ) -> None:
        """Journal one day shift event as an informational ``dayshift`` row.

        Parameters
        ----------
        moment
            Time of the event.
        event
            Phase change being journalled.
        result
            Rule result that explains the event.
        use
            Configured use of the day shift.
        """
        if self.alarms is None:
            return
        starts = event in (JournalEvent.BOOST_START, JournalEvent.SETBACK_START)
        reasons = ", ".join(result.reasons) or "no reason"
        self.alarms.journal_only(
            AlarmEvent(
                moment,
                JOURNAL_CODE,
                Severity.INFO,
                AlarmEventKind.STARTED if starts else AlarmEventKind.RELEASED,
                f"day shift ({use}): {EVENT_TEXT[event]} ({reasons})",
                {
                    "use": use,
                    "event": event.value,
                    "phase": result.phase.value,
                    "offset_k": result.offset_k,
                    "reasons": list(result.reasons),
                },
            )
        )

    def status(self) -> dict[str, Any]:
        """Return the body of ``GET api/v1/control/dayshift`` (see ``docs/api-v1.md``)."""
        settings = self.settings
        use = self.use
        result = self.result if use != "off" else None
        plan = self._slice
        window = self.window
        body: dict[str, Any] = {
            "mode": use,
            "configured": use,
            "on_available": on_available(Feature.DAYSHIFT, settings),
            "experimental": Feature.DAYSHIFT in EXPERIMENTAL,
            "phase": Phase.IDLE.value if result is None else result.phase.value,
            "offset_k": 0.0 if result is None else result.offset_k,
            "desired_k": 0.0 if result is None else result.desired_k,
            "applied_k": self._applied_k,
            "reasons": [Reason.OFF.value] if use == "off" else _reasons(result),
            "guards": [] if result is None else list(result.guards),
            "evaluated_at": None if result is None else iso_z(result.at),
            "valid_until": None if plan is None or use != "on" else iso_z(plan.valid_until.wall),
            "next_change": None,
            "boosted_today": result is not None and result.memory.boost_day == result.at.date(),
            "windows": {
                "day_start": settings.control_dayshift_day_start,
                "day_end": settings.control_dayshift_day_end,
                "night_start": settings.control_dayshift_night_start,
                "night_end": settings.control_dayshift_night_end,
                "comfort_at": settings.control_dayshift_comfort_at,
                "setback_end": None
                if result is None or result.setback_end is None
                else iso_z(result.setback_end),
                "timezone": settings.control_timezone,
            },
            "forecast": None,
        }
        if result is not None:
            change = result.next_change
            if change is not None:
                body["next_change"] = {"at": iso_z(change.at), "phase": change.phase.value}
            summary = result.forecast
            issued = None if window is None else window.newest_issue
            body["forecast"] = {
                "issued_at": None if issued is None else iso_from_unix(issued),
                "hours": summary.hours,
                "sun_wm2": summary.sun_wm2,
                "sun_limit_wm2": summary.sun_limit_wm2,
                "outside_c": summary.outside_c,
                "outside_min_c": summary.outside_min_c,
                "outside_limit_c": summary.outside_limit_c,
                "night_min_c": summary.night_min_c,
                "night_limit_c": summary.night_limit_c,
            }
        return body


def _reasons(result: DayShiftResult | None) -> list[str]:
    """Return the reasons of an evaluation (none before the first)."""
    return [] if result is None else list(result.reasons)

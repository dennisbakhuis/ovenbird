"""The model plan runner: the learned house model as a bounded room-target offset.

Every quarter hour of the loop's clock (also the simulated one) the runner evaluates
the guards and, when all pass, calls :func:`ovenbird_core.control.planner.plan_offset`
with the champion model, the stored forecast and the controller's filtered outside
temperature. What it computed is recorded; whether it is passed to the controller
depends on ``control_model_use``:

``off``
    nothing is called and nothing is written;
``shadow``
    the plan is computed and recorded exactly as for ``on``, but the controller never
    gets it (``plan=None``), so its decisions are those of ``off``;
``on``
    the slice is passed to :func:`~ovenbird_core.control.control_inputs` for the ticks
    inside its validity. Refused for now (:data:`ovenbird.config.validation.modelplan.ON_LOCKED`).

Guards
------
Evaluated in a fixed order and all reported (:class:`Guard`). The model guards need a
champion and are skipped without one. The cheap ones that can change inside a slice
(``room_untrusted``, ``stove_active``, ``stove_tail``) are checked at every tick and
withdraw a slice at once, as does a changed switch or configuration.

``weather_compensation`` needs no guard: :class:`PlannerConfig` carries the
controller's weather-dependent switch and the planner then holds the loop heat
instead of modelling the curve, so its assumptions hold either way.

Recording
---------
While the switch is not ``off`` two derived history signals are written at every tick:
``derived/model_plan_offset_k`` (the computed offset; ``0`` when the planner ran and
issued no slice; a gap while a guard blocks or the planner failed) and
``derived/model_plan_applied`` (``1`` only when the controller really applied a model
offset this tick). They go to the history writer only and never into the state store,
so the controller cannot read them. Changes of the guard verdict are journalled as
informational ``model_plan`` events without raising an alarm or a notification.

After a restart no plan is in force until the next evaluation (the first tick) and the
previous offset the rate limit starts from is 0, so the offset ramps from 0 again.
The end of the last wood-stove episode survives a restart: it is read back from the
journalled ``stove_mode`` events.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from ovenbird.clock import iso_z
from ovenbird.config import Settings
from ovenbird.config.validation import modelplan as lock
from ovenbird.control.alarms import (
    MODEL_PLAN_JOURNAL_CODE,
    AlarmBoard,
    AlarmEvent,
    AlarmEventKind,
    Severity,
)
from ovenbird.history.database import Sample, SampleKind
from ovenbird.history.forecast import latest_issue, newest_rows
from ovenbird.history.journal import alarms_since
from ovenbird.history.query import query_series
from ovenbird.insight import house
from ovenbird.insight.whatif import ModelChoice, champion_model
from ovenbird.runtime import HistorySink
from ovenbird.weather.service import STALE_AFTER_S
from ovenbird_core import Instant
from ovenbird_core.control import DecisionRecord, OvenbirdConfig, PlanSlice
from ovenbird_core.control.planner import (
    HISTORY_S,
    HOUR_S,
    ForecastHour,
    PlannerConfig,
    PlannerResult,
    plan_offset,
)

LOGGER = logging.getLogger("ovenbird.control.modelplan")
OFFSET_SIGNAL: Final = "derived/model_plan_offset_k"
APPLIED_SIGNAL: Final = "derived/model_plan_applied"
OFFSET_UNIT: Final = "K"
APPLIED_UNIT: Final = "1"
PLANNER_ERROR: Final = "planner_error"
SLOT_S: Final = 900.0
STOVE_TAIL_S: Final = 12 * HOUR_S
FORECAST_STALE_S: Final = STALE_AFTER_S
FORECAST_MARGIN_S: Final = 2 * HOUR_S
HISTORY_DAYS: Final = 7
HISTORY_STEP_S: Final = 900
STOVE_JOURNAL_CODE: Final = "stove_mode"
STOVE_END_EVENTS: Final = frozenset({AlarmEventKind.EXPIRED.value, AlarmEventKind.RELEASED.value})
OFFSET_VALID_S: Final = PlannerConfig().slice_s + PlannerConfig().grace_s
MIN_HOLD_S: Final = 120.0


class Guard(StrEnum):
    """Why no model plan is issued, in the fixed order the guards are evaluated."""

    WEATHER_OFF = "weather_off"
    MODEL_MISSING = "model_missing"
    MODEL_NOT_CREDIBLE = "model_not_credible"
    MODEL_STALE = "model_stale"
    MODEL_ERROR_HIGH = "model_error_high"
    FORECAST_STALE = "forecast_stale"
    ROOM_UNTRUSTED = "room_untrusted"
    STOVE_ACTIVE = "stove_active"
    STOVE_TAIL = "stove_tail"


GUARD_ORDER: Final = tuple(Guard)
STATIC_GUARDS: Final = frozenset(GUARD_ORDER[:6])


@dataclass(frozen=True, slots=True)
class PlanContext:
    """What the runner needs of the control loop at one tick.

    Parameters
    ----------
    now
        The tick's instant.
    room_trusted
        The controller has a trusted room value (fresh and plausible).
    stove_active
        A wood-stove episode is active.
    outside_filtered_c
        The controller's filtered outside temperature (``None`` before the first tick).
    config
        The controller configuration in effect.
    """

    now: Instant
    room_trusted: bool
    stove_active: bool
    outside_filtered_c: float | None
    config: OvenbirdConfig


@dataclass(frozen=True, slots=True)
class ForecastWindow:
    """The stored forecast the planner reads.

    Parameters
    ----------
    hours
        One row per target hour, the newest stored issue's.
    newest_issue
        Issue time of the newest stored forecast (``None`` when there is none).
    """

    hours: tuple[ForecastHour, ...]
    newest_issue: float | None


@dataclass(frozen=True, slots=True)
class Facts:
    """What the static guards looked at.

    Parameters
    ----------
    champion
        The champion model (``None``: none, or its files are refused).
    stale
        The learner has not re-validated the model within twice its interval.
    window
        The stored forecast.
    stove_end
        Unix time the last wood-stove episode ended, when within the tail.
    """

    champion: ModelChoice | None
    stale: bool
    window: ForecastWindow
    stove_end: float | None


@dataclass(frozen=True, slots=True)
class Evaluation:
    """One planner evaluation (the latest is what ``insight/house/control`` reports).

    Parameters
    ----------
    at
        When the planner ran.
    status
        A :class:`PlannerStatus` value, or ``planner_error``.
    result
        What the planner returned (``None`` after an error).
    use
        The switch it ran under.
    """

    at: Instant
    status: str
    result: PlannerResult | None
    use: str

    @property
    def slice(self) -> PlanSlice | None:
        """The issued slice, if any."""
        return None if self.result is None else self.result.slice

    @property
    def offset_k(self) -> float:
        """The offset the planner issued (0 without a slice or after an error)."""
        return 0.0 if self.result is None else self.result.offset_k


def load_forecast(path: Path, now_ts: float, horizon_h: float) -> ForecastWindow:
    """Read the forecast window the planner needs from ``history.db``.

    Parameters
    ----------
    path
        History database.
    now_ts
        Wall time in unix seconds; only issues made by then count.
    horizon_h
        Hours ahead the planner looks.

    Returns
    -------
    ForecastWindow
        For each target hour from 24 h back to the horizon the shortest-lead stored
        row; a value the planner cannot use (negative sun) is left out as missing.
    """
    newest = latest_issue(path, now_ts)
    rows = newest_rows(
        path,
        now_ts - HISTORY_S - FORECAST_MARGIN_S,
        now_ts + horizon_h * HOUR_S + FORECAST_MARGIN_S,
        now_ts,
    )
    hours: list[ForecastHour] = []
    for row in rows:
        if row.target_ts % HOUR_S != 0.0:
            continue
        try:
            hours.append(ForecastHour(row.target_ts, row.temp_c, row.radiation_wm2))
        except ValueError:
            hours.append(ForecastHour(row.target_ts, None, None))
    return ForecastWindow(tuple(hours), newest)


def load_stove_end(path: Path, now_ts: float) -> float | None:
    """Return when the last wood-stove episode ended within the tail, from the journal."""
    rows = alarms_since(path, STOVE_JOURNAL_CODE, now_ts - STOVE_TAIL_S)
    ends = [row.ts for row in rows if row.event in STOVE_END_EVENTS]
    return max(ends, default=None)


def _iso(ts: float | None) -> str | None:
    return None if ts is None else iso_z(datetime.fromtimestamp(ts, UTC))


@dataclass
class ModelPlanRunner:
    """Evaluate the model plan guards and planner and hand the slice to the control loop.

    Parameters
    ----------
    settings
        Effective settings (kept current by :meth:`reconfigure`).
    models
        Returns the learner's models directory.
    weather_enabled
        Whether forecasts are fetched.
    embedded
        Whether the service runs the learner itself (its health then uses the
        configured interval).
    sink
        History writer for the derived signals; ``None`` records nothing.
    alarms
        Alarm board whose journal receives the verdict events (never its listeners).
    load_champion, load_forecast, load_stove_end
        Readers of the learner's files, the stored forecast and the journal (tests
        replace them).
    """

    settings: Settings
    models: Callable[[], Path]
    weather_enabled: Callable[[], bool] = lambda: False
    embedded: Callable[[], bool] = lambda: False
    sink: HistorySink | None = None
    alarms: AlarmBoard | None = None
    load_champion: Callable[[Path], ModelChoice | None] = champion_model
    load_forecast: Callable[[Path, float, float], ForecastWindow] = load_forecast
    load_stove_end: Callable[[Path, float], float | None] = load_stove_end
    evaluation: Evaluation | None = field(default=None, init=False)
    facts: Facts | None = field(default=None, init=False)
    calls: int = field(default=0, init=False)
    _slot: int | None = field(default=None, init=False, repr=False)
    _issued: PlanSlice | None = field(default=None, init=False, repr=False)
    _slice: PlanSlice | None = field(default=None, init=False, repr=False)
    _slice_use: str = field(default="off", init=False, repr=False)
    _stamp: int = field(default=0, init=False, repr=False)
    _slice_stamp: int = field(default=0, init=False, repr=False)
    _was_stove: bool = field(default=False, init=False, repr=False)
    _stove_end: float | None = field(default=None, init=False, repr=False)
    _blocks: tuple[Guard, ...] = field(default=(), init=False, repr=False)
    _last_blocks: tuple[Guard, ...] | None = field(default=None, init=False, repr=False)
    _seen_use: str = field(default="off", init=False, repr=False)
    _offered: PlanSlice | None = field(default=None, init=False, repr=False)
    _applied: bool = field(default=False, init=False, repr=False)
    _interval_s: float = field(default=60.0, init=False, repr=False)

    @property
    def use(self) -> str:
        """The effective switch (``on`` counts as ``shadow`` while the lock holds)."""
        use = str(self.settings.control_model_use)
        if use == "on" and lock.ON_LOCKED:
            return "shadow"
        return use

    @property
    def applied(self) -> bool:
        """Whether the controller applied a model offset at the latest tick."""
        return self._applied

    def reconfigure(self, settings: Settings) -> None:
        """Follow a new configuration: withdraw the slice and restart the rate limit."""
        self.settings = settings
        self._stamp += 1
        self._slice = None
        self._issued = None
        self._applied = False
        self._interval_s = settings.control_interval_s

    def step(self, ctx: PlanContext) -> PlanSlice | None:
        """Run the guards and, once per quarter hour, the planner; return the slice to apply.

        Never raises: a failure is logged and means no plan.

        Parameters
        ----------
        ctx
            What the control loop knows at this tick.

        Returns
        -------
        PlanSlice or None
            The slice to pass to the controller: only with ``on``, all guards passing
            and a slice in force; ``None`` otherwise (always in ``shadow`` and ``off``).
        """
        self._offered = None
        self._applied = False
        try:
            return self._step(ctx)
        except Exception:
            LOGGER.exception("the model plan runner failed; no plan this tick")
            self._slice = None
            self._issued = None
            return None

    def after(self, decision: DecisionRecord) -> None:
        """Record whether the controller applied the offered slice at this tick."""
        try:
            applied = self._offered is not None and bool(
                decision.controller_state.get("model_plan_applied_k")
            )
            self._applied = applied
            if self.use != "off":
                self._write(APPLIED_SIGNAL, APPLIED_UNIT, decision.at, 1.0 if applied else 0.0)
        except Exception:
            LOGGER.exception("the model plan runner could not record the tick")

    def static_blocks(self, facts: Facts) -> tuple[Guard, ...]:
        """Return the failing guards that need the weather, the model or the forecast."""
        blocks: list[Guard] = []
        champion = facts.champion
        if not self.weather_enabled():
            blocks.append(Guard.WEATHER_OFF)
        if champion is None:
            blocks.append(Guard.MODEL_MISSING)
        else:
            if not champion.credible:
                blocks.append(Guard.MODEL_NOT_CREDIBLE)
            if facts.stale:
                blocks.append(Guard.MODEL_STALE)
            limit = self.settings.control_model_max_rmse_k
            if champion.rmse_k is None or champion.rmse_k > limit:
                blocks.append(Guard.MODEL_ERROR_HIGH)
        return tuple(blocks)

    def forecast_blocks(self, facts: Facts, now_ts: float) -> tuple[Guard, ...]:
        """Return ``forecast_stale`` when the newest stored issue is older than 3 h."""
        issued = facts.window.newest_issue
        if issued is None or now_ts - issued > FORECAST_STALE_S:
            return (Guard.FORECAST_STALE,)
        return ()

    def live_blocks(self, ctx: PlanContext) -> tuple[Guard, ...]:
        """Return the cheap guards that can change inside a slice."""
        blocks: list[Guard] = []
        if not ctx.room_trusted:
            blocks.append(Guard.ROOM_UNTRUSTED)
        if ctx.stove_active:
            blocks.append(Guard.STOVE_ACTIVE)
        end = self._stove_end
        if end is not None and 0.0 <= ctx.now.wall.timestamp() - end < STOVE_TAIL_S:
            blocks.append(Guard.STOVE_TAIL)
        return tuple(blocks)

    def read_facts(self, now: datetime, horizon_h: float | None = None) -> Facts:
        """Read what the static guards look at: the champion, the learner's health, the forecast."""
        settings = self.settings
        models = self.models()
        champion = self.load_champion(models) if house.models_ok(models) else None
        health = house.learner_health(
            house.last_run(models),
            now,
            settings.house_learn_interval_h if self.embedded() else house.DEFAULT_INTERVAL_H,
        )
        stale = bool(health["stale"]) or health["age_h"] is None
        horizon = settings.control_model_horizon_h if horizon_h is None else horizon_h
        now_ts = now.timestamp()
        window = self.load_forecast(settings.history_path, now_ts, horizon)
        stove_end = self.load_stove_end(settings.history_path, now_ts)
        return Facts(champion, stale, window, stove_end)

    def blocks_for(self, facts: Facts, ctx: PlanContext) -> tuple[Guard, ...]:
        """Return every failing guard in the fixed order."""
        now_ts = ctx.now.wall.timestamp()
        found = {
            *self.static_blocks(facts),
            *self.forecast_blocks(facts, now_ts),
            *self.live_blocks(ctx),
        }
        return tuple(guard for guard in GUARD_ORDER if guard in found)

    def _step(self, ctx: PlanContext) -> PlanSlice | None:
        use = self.use
        self._interval_s = self.settings.control_interval_s
        self._track_stove(ctx)
        if use == "off":
            self._idle()
            return None
        if use != self._seen_use:
            self._seen_use = use
            self._last_blocks = None
        moment = ctx.now
        slot = math.floor(moment.wall.timestamp() / SLOT_S)
        if slot != self._slot and ctx.outside_filtered_c is not None:
            self._slot = slot
            self._evaluate(ctx, use)
        blocks = self._current_blocks(ctx)
        self._journal(moment, blocks, use)
        self._write(OFFSET_SIGNAL, OFFSET_UNIT, moment, self._offset_value(moment, blocks))
        plan = self._slice
        if (
            use == "on"
            and not blocks
            and plan is not None
            and plan.active(moment)
            and self._slice_use == "on"
            and self._slice_stamp == self._stamp
        ):
            self._offered = plan
            return plan
        return None

    def _idle(self) -> None:
        self.evaluation = None
        self.facts = None
        self._slice = None
        self._issued = None
        self._slot = None
        self._blocks = ()
        self._last_blocks = None
        self._seen_use = "off"

    def _track_stove(self, ctx: PlanContext) -> None:
        if self._was_stove and not ctx.stove_active:
            self._stove_end = ctx.now.wall.timestamp()
        self._was_stove = ctx.stove_active

    def _current_blocks(self, ctx: PlanContext) -> tuple[Guard, ...]:
        facts = self.facts
        if facts is None:
            self._blocks = self.live_blocks(ctx)
        else:
            self._blocks = self.blocks_for(facts, ctx)
        return self._blocks

    def _evaluate(self, ctx: PlanContext, use: str) -> None:
        moment = ctx.now
        try:
            facts = self.read_facts(moment.wall)
        except Exception:
            LOGGER.exception("the model plan guards could not be read")
            self.facts = None
            self._slice = None
            self._issued = None
            self.evaluation = Evaluation(moment, PLANNER_ERROR, None, use)
            return
        self.facts = facts
        if facts.stove_end is not None:
            known = self._stove_end
            self._stove_end = facts.stove_end if known is None else max(known, facts.stove_end)
        blocks = self.blocks_for(facts, ctx)
        self._slice = None
        if blocks or facts.champion is None or ctx.outside_filtered_c is None:
            self._issued = None
            return
        previous = 0.0
        issued = self._issued
        if issued is not None and moment < issued.valid_until:
            previous = issued.room_offset_k
        planner = PlannerConfig.for_controller(
            ctx.config, horizon_h=self.settings.control_model_horizon_h
        )
        self.calls += 1
        try:
            result = plan_offset(
                facts.champion.model,
                facts.window.hours,
                moment,
                ctx.outside_filtered_c,
                planner,
                previous,
            )
        except Exception:
            LOGGER.exception("the model planner failed")
            self._issued = None
            self.evaluation = Evaluation(moment, PLANNER_ERROR, None, use)
            return
        self.evaluation = Evaluation(moment, result.status.value, result, use)
        self._issued = result.slice
        self._slice = result.slice
        self._slice_use = use
        self._slice_stamp = self._stamp

    def _offset_value(self, moment: Instant, blocks: tuple[Guard, ...]) -> float | None:
        evaluation = self.evaluation
        if blocks or evaluation is None or evaluation.result is None:
            return None
        if moment.since(evaluation.at) >= OFFSET_VALID_S:
            return None
        return evaluation.offset_k

    def _write(self, signal: str, unit: str, moment: Instant, value: float | None) -> None:
        if self.sink is None:
            return
        hold = max(MIN_HOLD_S, 2.0 * self._interval_s)
        self.sink.offer(
            Sample(signal, unit, SampleKind.NUMBER, moment.wall.timestamp(), value, hold)
        )

    def _journal(self, moment: Instant, blocks: tuple[Guard, ...], use: str) -> None:
        if blocks == self._last_blocks or self.alarms is None:
            self._last_blocks = blocks
            return
        self._last_blocks = blocks
        names = [guard.value for guard in blocks]
        if blocks:
            message = f"model plan ({use}): no plan, blocked by {', '.join(names)}"
            kind = AlarmEventKind.STARTED
        else:
            message = f"model plan ({use}): all guards pass"
            kind = AlarmEventKind.RELEASED
        self.alarms.journal_only(
            AlarmEvent(
                moment,
                MODEL_PLAN_JOURNAL_CODE,
                Severity.INFO,
                kind,
                message,
                {"use": use, "blocks": names},
            )
        )

    def report(self, ctx: PlanContext) -> dict[str, Any]:
        """Return the body of ``GET insight/house/control`` (see ``docs/api-v1.md``).

        Reads the learner's files and the history database, so call it off the event loop.
        """
        settings = self.settings
        now = ctx.now.wall
        facts = self.read_facts(now)
        blocks = self.blocks_for(facts, ctx)
        champion = facts.champion
        return {
            "use": self.use,
            "verdict": {"ok": not blocks, "blocks": [guard.value for guard in blocks]},
            "model": None if champion is None else champion.name,
            "model_rmse_k": None if champion is None else _rounded(champion.rmse_k),
            "bounds": {
                "max_setback_k": settings.control_model_max_setback_k,
                "max_preheat_k": settings.control_model_max_preheat_k,
                "horizon_h": settings.control_model_horizon_h,
                "max_rmse_k": settings.control_model_max_rmse_k,
            },
            "now": self._now_body(),
            "history": self._history_body(now),
        }

    def _now_body(self) -> dict[str, Any] | None:
        evaluation = self.evaluation
        if self.use == "off" or evaluation is None:
            return None
        result = evaluation.result
        plan = evaluation.slice
        return {
            "at": iso_z(evaluation.at.wall),
            "status": evaluation.status,
            "offset_k": evaluation.offset_k,
            "applied": self._applied,
            "reason": None if plan is None else plan.reason.value,
            "valid_until": None if plan is None else iso_z(plan.valid_until.wall),
            "rise_k": None if result is None else result.rise_k,
            "rise_at": None if result is None else _iso(result.rise_at_ts),
            "fall_k": None if result is None else result.fall_k,
            "fall_at": None if result is None else _iso(result.fall_at_ts),
            "solar_k": None if result is None else result.solar_k,
            "outside_k": None if result is None else result.outside_k,
        }

    def _history_body(self, now: datetime) -> dict[str, Any]:
        end = now.timestamp()
        start = math.floor((end - HISTORY_DAYS * 86_400.0) / HISTORY_STEP_S) * HISTORY_STEP_S
        series = query_series(
            self.settings.history_path,
            [OFFSET_SIGNAL, APPLIED_SIGNAL],
            start,
            end,
            HISTORY_STEP_S,
        )
        offsets = series[OFFSET_SIGNAL].points
        applied = series[APPLIED_SIGNAL].points
        points: list[list[Any]] = []
        if any(value is not None for _, value in offsets) or any(
            value is not None for _, value in applied
        ):
            for (ts, offset), (_, share) in zip(offsets, applied, strict=True):
                flag = None if share is None else int(share >= 0.5)
                points.append([_iso(ts), offset, flag])
        return {
            "step_s": HISTORY_STEP_S,
            "from": _iso(start),
            "to": _iso(end),
            "points": points,
        }


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 3)

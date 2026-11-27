"""The ovenbird controller: curve + room feedback + plan + start ramp, then safety.

Pipeline of one tick
--------------------
1. **Tracking** (every tick, also when refusing): compressor start/stop detection,
   start-ramp clock (paused in defrost) and the outside-temperature filter.
2. **Gates**: ``off`` mode, a dead HeishaMon, an unknown or wrong ``Heating_Mode``
   (not Direct) or ``Operating_Mode_State`` (not heat) refuse: no intents at all.
   Missing required inputs hold: the last intents are repeated.
3. **Terms**: ``curve(filtered outside)`` + ``room_feedback`` (PI) + ``plan`` (+
   ``boost``) + ``start_ramp`` (≤ 0) + ``cycling_floor`` (≥ 0), each recorded before
   and after its own clamp.
4. **Safety** clamps the continuous value to the envelope (``pre_round``).
5. **Rounding with hysteresis, deadband, dwell**: the issued integer setpoint keeps
   its value while ``pre_round`` stays within ``0.5 + hysteresis`` (rounding) or
   ``deadband`` (≥ 1 K) of it; a change also waits for the dwell time since the
   previous change (a shorter one while a start ramp runs, none on the ramp's
   first tick); during defrost and DHW the setpoint never decreases.
6. **Hard constraints** bypass stage 5: the cycling floor (inside the minimum-run
   window; a decrease there must also keep extra headroom so outlet jitter cannot
   flip the setpoint) and the safety envelope on the integer value, which always
   has the last word.
7. **Anti-windup**: the integrator integrates only when nothing saturates in the
   direction of the error (feedback clamp, safety clamp, start ramp, cycling
   floor) and nothing freezes it (defrost, DHW, stale room, override, hold,
   refusal). The integrator itself is clamped as well.
8. **Pump duty** (optional): the heat duty while the compressor runs or a DHW run
   is active (never lowered then), the idle duty after the compressor has been
   stopped for ``idle_delay_s``. During a defrost the pump drives its own duty and
   ignores the setting, so no pump-duty intent is issued (the desired duty is kept
   for after the defrost).

Room value guards
-----------------
* **Integrator dead zone**: the integrator integrates
  ``sign(e) * max(0, |e| - quantum_k)``, one full sensor step less than the error
  (the proportional part sees the full error). A room value is only known to
  within one step, so on a sensor grid offset from the target (20.9/21.1 around
  21.0) the dead zone is symmetric, and a value held for many hours just outside
  the target cannot wind the integrator up.
* **Stuck-warm protection** (``on_change`` sensors): the cooling (negative)
  feedback is scaled by an authority, the smaller of a ramp on the proof-of-life
  age (1 up to 3 h, 0 from 8 h) and a ramp on the held time (1 up to 12 h, 0 at
  the silence limit), so a sensor that died at a warm reading cannot keep the
  water below the curve for long; the integrator does not integrate cooling while
  the authority is reduced. What the reduced authority takes away is replaced by
  the held offset ``H`` (below), ``u = u_lim * a + (1 - a) * H`` for a cooling
  ``u_lim``, so at zero authority the water keeps the house's learned offset over
  the curve instead of dropping to the bare curve (the same value the stale
  fallback starts from). Heating feedback is never reduced (the comfort-floor
  monitor and the curve bound that side).
* **Provisional cooling on a silent device** (``on_change``): the integrator at
  the last proof of life is remembered; once the device has been silent longer
  than ``alive_decay_start_s`` (3 h, where its cooling authority starts to decay),
  or as soon as its value goes stale or implausible (a stuck warm reading the
  cross-check flags before then), cooling the integrator did since then is undone
  and the integrator stays at or above that mark until the device reports again,
  so a reading nothing confirms cannot wind down the house's learned offset.
  Defrost, DHW and a wood-stove episode (which holds the integrator itself) defer
  the undo to their end; the mark is kept meanwhile.
* **Plausibility cross-check** (optional): when the room value and the
  cross-check signal minus their slowly learned offset disagree by more than the
  threshold (1.5 K) for the sustain time (2 h), the room input counts as
  implausible: feedback off (curve plus the held offset, as for a stale
  value), integrator frozen. A disagreement ends only below the threshold minus
  ``CROSSCHECK_HYSTERESIS_K`` (0.5 K), so an integer cross-check signal flipping
  by one step does not restart the clock, and the
  verdict is latched until the room value has changed and agrees with the
  cross-check again (below that lower threshold), so a sensor that is stuck, or
  fails high and keeps reporting, stays flagged. The offset is learned
  only while the two agree (below that lower threshold) and the room value changed
  recently (held less than 6 h).
* **Held offset on a stale or implausible room value**: when the room value goes
  stale or implausible (curve only), the held offset
  ``H = min(output_limit, max(0, I) + min(held_step_max_k, kp * quantum_k))``
  keeps being applied,
  frozen, and fades linearly to zero over ``HELD_INTEGRAL_FADE_S`` (24 h) from the
  moment the value was lost, so losing the sensor or the HA link does not drop the
  water to the bare curve at once. A negative integrator (typically the passive
  gains of a sunny day) is not applied. Inside the integrator's dead zone the P
  part carries the room by up to ``kp * quantum_k``, which the integrator alone
  misses; without a room value the loop is open and cannot see the room drifting
  low, so ``H`` takes the warm edge of that band; ``held_step_max_k`` (0.4 K)
  keeps a coarse sensor's step from becoming a large bias. It is a constant,
  never integrated.

Wood-stove mode
---------------
See :mod:`ovenbird_core.control.stove`: while an episode is active the room PI is
frozen with its integrator held, the plan is paused and the ``stove`` term lowers
the curve; every other stage applies as always.

Model plan
----------
A plan slice from the learned house model (``PlanSource.MODEL``,
:mod:`ovenbird_core.control.planner`) is clamped to the bounds of
:class:`~ovenbird_core.control.config.ModelPlanConfig` and only shifts the room
target of an active room feedback. It has no effect at all (no water term, ladder and
reason as without a plan, the reason in ``model_plan_ignored``) from the first tick
on which the room value is not trusted, a wood-stove episode is active, the
wood-stove detection is still waiting after an episode or a sensor fault
(``stove_blocked``, ``stove_level_blocked``, ``stove_reentry_wait``,
``stove_fault``), or the slice is valid for longer than ``MODEL_PLAN_MAX_SLICE_S``.
Start ramp, cycling floor, rounding, dwell and the safety clamps act after it as
always, and the integrator follows the shifted target under the same freezes and
anti-windup as without a plan.

A model *water* slice (``PlanSlice.water_offset_k``, a feed-forward from the forecast
sun) does not shift the room target. Under the same blocks it is clamped to
``[-max_lower_water_k, +max_raise_water_k]`` and scaled by the room authority of the
trusted room value against comfort (full down to ``comfort - authority_full_k`` or one
sensor step, whichever is further, none from ``comfort - authority_zero_k``, mirrored
above comfort for a raise). The result is the ``plan`` term: added after the curve and
the room feedback, before the start ramp, the cycling floor, rounding, dwell and the
safety clamps, which all act after it as always. The integrator's anti-windup sees
the summed value (``pre_clamp``) and the floor, so an offset that runs into the minimum
setpoint or the cycling floor freezes cooling integration as any other term does; with
a correct plan the room error stays zero and the integrator does not move. Ladder
``model_plan`` and the plan's reason apply only while the applied water offset is
non-zero.

Because deadband and dwell keep the issued setpoint below or above ``pre_round``
for a while, the integrator keeps integrating through them; this is intended (it
is what eventually moves the setpoint by one step) and bounded by its clamp.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Final

from ovenbird_core.catalogue import HeishaSignal
from ovenbird_core.control import stove as stove_mode
from ovenbird_core.control.config import MODEL_PLAN_MAX_SLICE_S, OutsideSource, OvenbirdConfig
from ovenbird_core.control.curve import filter_outside
from ovenbird_core.control.integrator import freezes, integral_at_life, integrate, rollback
from ovenbird_core.control.notes import (
    BINDINGS,
    PRE_ROUND_INPUT,
    SECONDS_PER_HOUR,
    SECONDS_PER_MINUTE,
    TERMS,
    decision_note,
    duration_text,
    flip_distance,
    liveness_label,
    reason_code,
    room_status,
    soft_binding,
)
from ovenbird_core.control.observe import as_number
from ovenbird_core.control.protocol import StepResult
from ovenbird_core.control.record import DecisionRecord, InputRef, StateValue, Term
from ovenbird_core.control.safety import SafetyBounds
from ovenbird_core.control.stages import dwell_time, hard_constraints, round_half_up, soften
from ovenbird_core.control.stove import (
    CELSIUS,
    REFERENCE_MAX_C,
    REFERENCE_MIN_C,
    StoveExit,
    StoveSource,
    StoveStep,
    StoveTrigger,
)
from ovenbird_core.control.terms import (
    HELD_INTEGRAL_FADE_S,
    Feedback,
    Floor,
    ModelPlan,
    Ramp,
    RampPhase,
    boost_term,
    curve_term,
    cycling_floor,
    override_term,
    plan_term,
    room_feedback,
    safety_term,
    start_ramp,
)
from ovenbird_core.control.types import (
    ActualValue,
    CommandIntent,
    ControlInputs,
    IntentKind,
    LadderLevel,
    Mode,
    ModelPlanBlock,
    Override,
    OverrideKind,
    PlanSlice,
    PlanSource,
    ReasonCode,
    RoomInput,
    RoomProfile,
)
from ovenbird_core.derived import compressor_running, defrost_active, dhw_active
from ovenbird_core.readings import SignalId
from ovenbird_core.store import SignalView, Snapshot

CONTROLLER_NAME: Final = "ovenbird"
STATS_SIGNAL: Final = "stats"
CROSSCHECK_LEARN_HELD_S: Final = 6 * 3600.0
CROSSCHECK_HYSTERESIS_K: Final = 0.5

__all__ = [
    "BINDINGS",
    "CELSIUS",
    "CONTROLLER_NAME",
    "CROSSCHECK_HYSTERESIS_K",
    "CROSSCHECK_LEARN_HELD_S",
    "HELD_INTEGRAL_FADE_S",
    "PRE_ROUND_INPUT",
    "REFERENCE_MAX_C",
    "REFERENCE_MIN_C",
    "SECONDS_PER_HOUR",
    "SECONDS_PER_MINUTE",
    "STATS_SIGNAL",
    "TERMS",
    "OvenbirdController",
    "OvenbirdState",
    "RampPhase",
    "StoveExit",
    "StoveSource",
    "StoveTrigger",
    "carry_state",
    "duration_text",
    "liveness_label",
    "room_status",
    "round_half_up",
]


@dataclass(frozen=True, slots=True)
class OvenbirdState:
    """Controller state carried from tick to tick (monotonic seconds for times).

    Parameters
    ----------
    setpoint
        Last desired integer water setpoint.
    last_change_at
        When the desired setpoint last changed.
    integral_k
        PI integrator in K water.
    outside_filtered
        Filtered outside temperature.
    outside_at
        When the filter last took a sample.
    last_tick_at
        When the previous tick ran.
    running
        Compressor running at the previous tick (``None`` before it was known).
    run_started_at
        Detected start of the current run (``None`` when unknown or stopped).
    stopped_at
        Detected end of the previous run.
    ramp_phase
        Start-ramp phase.
    ramp_elapsed_s
        Non-defrost run time since the ramp started.
    ramp_cap
        Current ramp cap in °C.
    pump_duty
        Last desired max pump duty.
    quiet_level
        Last desired quiet level.
    crosscheck_offset_k
        Learned offset of the cross-check signal over the room value.
    crosscheck_since
        When the room value and the cross-check started to disagree.
    crosscheck_latched
        Room value at which the cross-check declared it implausible; the verdict
        holds until the room value changes.
    room_lost_at
        When the room value went stale or implausible (the held offset fades
        from then).
    integral_at_life_k
        Integrator at the room sensor's last proof of life (``on_change``), kept
        while the value is lost; a device silent beyond ``alive_decay_start_s``,
        or whose value went stale or implausible, keeps no cooling integrated
        since then.
    stove_source
        Who started the active wood-stove episode (``None``: inactive).
    stove_trigger
        What started it.
    stove_since
        When it started.
    stove_entry_c
        Room value at the start (``None`` when unknown, e.g. a manual start).
    stove_integral_k
        Integrator at the start (held through the episode).
    stove_blocked
        The automatic detection waits until the room has cooled below the exit
        threshold (after a manual stop).
    stove_level_blocked
        The level trigger waits until the room has cooled below the exit threshold
        (after an episode reached ``max_active_s``); a new fast rise may still enter.
    stove_reentry_wait, stove_trusted_since
        After an episode ended because the room value lost its trust: no automatic
        entry until the value has been trusted again for ``reentry_hold_s``, and
        since when it is.
    stove_low_c, stove_low_at
        Lowest trusted room value of the fast-rise window and when it was seen.
    stove_high_c, stove_high_at
        Highest trusted room value of the fast-rise window and when it was seen.
    stove_predip_c
        Highest value of the window when its low was last set (the level before a
        dip); a fast rise must go above it.
    stove_step_low_c, stove_step_low_at
        Lowest plausible room value of the sensor-fault window and when it was seen.
    stove_fault
        A sensor-fault step was seen: the automatic detection waits until the room has
        cooled below the exit threshold.
    """

    setpoint: int | None = None
    last_change_at: float | None = None
    integral_k: float = 0.0
    outside_filtered: float | None = None
    outside_at: float | None = None
    last_tick_at: float | None = None
    running: bool | None = None
    run_started_at: float | None = None
    stopped_at: float | None = None
    ramp_phase: RampPhase = RampPhase.IDLE
    ramp_elapsed_s: float = 0.0
    ramp_cap: float | None = None
    pump_duty: int | None = None
    quiet_level: int | None = None
    crosscheck_offset_k: float | None = None
    crosscheck_since: float | None = None
    crosscheck_latched: float | None = None
    room_lost_at: float | None = None
    integral_at_life_k: float | None = None
    stove_source: StoveSource | None = None
    stove_trigger: StoveTrigger | None = None
    stove_since: float | None = None
    stove_entry_c: float | None = None
    stove_integral_k: float | None = None
    stove_blocked: bool = False
    stove_level_blocked: bool = False
    stove_reentry_wait: bool = False
    stove_trusted_since: float | None = None
    stove_low_c: float | None = None
    stove_low_at: float | None = None
    stove_high_c: float | None = None
    stove_high_at: float | None = None
    stove_predip_c: float | None = None
    stove_step_low_c: float | None = None
    stove_step_low_at: float | None = None
    stove_fault: bool = False

    @property
    def stove_active(self) -> bool:
        """Whether a wood-stove episode is active."""
        return self.stove_source is not None

    @property
    def held_integral_k(self) -> float:
        """Integrator kept when the room value is not trusted (its positive part)."""
        return max(0.0, self.integral_k)

    def as_flat(self) -> dict[str, StateValue]:
        """Return the state as a flat, JSON-friendly mapping."""
        return {
            "setpoint": self.setpoint,
            "last_change_at": self.last_change_at,
            "integral_k": self.integral_k,
            "outside_filtered_c": self.outside_filtered,
            "outside_at": self.outside_at,
            "last_tick_at": self.last_tick_at,
            "running": self.running,
            "run_started_at": self.run_started_at,
            "stopped_at": self.stopped_at,
            "ramp_phase": self.ramp_phase.value,
            "ramp_elapsed_s": self.ramp_elapsed_s,
            "ramp_cap_c": self.ramp_cap,
            "pump_duty": self.pump_duty,
            "quiet_level": self.quiet_level,
            "crosscheck_offset_k": self.crosscheck_offset_k,
            "crosscheck_since": self.crosscheck_since,
            "crosscheck_latched_c": self.crosscheck_latched,
            "room_lost_at": self.room_lost_at,
            "integral_at_life_k": self.integral_at_life_k,
            "stove_source": None if self.stove_source is None else self.stove_source.value,
            "stove_trigger": None if self.stove_trigger is None else self.stove_trigger.value,
            "stove_since": self.stove_since,
            "stove_entry_c": self.stove_entry_c,
            "stove_integral_k": self.stove_integral_k,
            "stove_blocked": self.stove_blocked,
            "stove_level_blocked": self.stove_level_blocked,
            "stove_reentry_wait": self.stove_reentry_wait,
            "stove_trusted_since": self.stove_trusted_since,
            "stove_low_c": self.stove_low_c,
            "stove_low_at": self.stove_low_at,
            "stove_high_c": self.stove_high_c,
            "stove_high_at": self.stove_high_at,
            "stove_predip_c": self.stove_predip_c,
            "stove_step_low_c": self.stove_step_low_c,
            "stove_step_low_at": self.stove_step_low_at,
            "stove_fault": self.stove_fault,
        }


def carry_state(state: OvenbirdState, old: OvenbirdConfig, new: OvenbirdConfig) -> OvenbirdState:
    """Carry the controller state over a configuration change without a setpoint jump.

    The issued setpoint, its change time (dwell timer), the run and filter state
    survive, so a new configuration moves the setpoint only through deadband and
    dwell (or a hard constraint). The integrator and its mark at the room
    sensor's last proof of life are clamped to the new limit, and reset (the mark
    forgotten) when the new configuration has no integral part; a disabled start ramp
    ends a running ramp; a changed cross-check signal forgets the learned offset;
    a configuration without wood-stove mode ends an episode and forgets its state
    (an episode otherwise continues under the new thresholds).

    Parameters
    ----------
    state
        State after the last tick under ``old``.
    old, new
        Previous and new configuration.

    Returns
    -------
    OvenbirdState
        The state to continue with under ``new``.
    """
    feedback = new.feedback
    limit = feedback.integral_limit_k
    proportional_only = feedback.ki_per_s == 0.0
    integral = 0.0 if proportional_only else min(max(state.integral_k, -limit), limit)
    mark = state.integral_at_life_k
    if mark is not None:
        mark = None if proportional_only else min(max(mark, -limit), limit)
    carried = replace(state, integral_k=integral, integral_at_life_k=mark)
    if not new.ramp.enabled and carried.ramp_phase is not RampPhase.IDLE:
        carried = replace(carried, ramp_phase=RampPhase.IDLE, ramp_elapsed_s=0.0, ramp_cap=None)
    if old.room.crosscheck != new.room.crosscheck:
        carried = replace(
            carried, crosscheck_offset_k=None, crosscheck_since=None, crosscheck_latched=None
        )
    if new.stove is None:
        carried = stove_mode.stove_cleared(carried)
    return carried


class OutsideReason(StrEnum):
    """Why the curve does not use the chosen outside sensor this tick."""

    MISSING = "missing"
    STALE = "stale"
    IMPLAUSIBLE = "implausible"
    DEVIATES = "deviates"


@dataclass(frozen=True, slots=True)
class CurveOutside:
    """The outside temperature the heating curve uses this tick.

    Parameters
    ----------
    value
        Raw value in °C (``None`` when neither the chosen sensor nor the pump has one).
    source
        Signal it came from.
    fallback
        The chosen outside sensor was not used, so the pump's sensor is.
    note
        Clause for the curve term's note (``None`` without a chosen sensor).
    reason
        Why the chosen sensor was not used (``None`` when it was, or without one).
    """

    value: float | None
    source: SignalId
    fallback: bool = False
    note: str | None = None
    reason: OutsideReason | None = None


def curve_outside(
    source: OutsideSource | None, snapshot: Snapshot, pump: float | None
) -> CurveOutside:
    """Return the outside temperature for the curve: the chosen sensor's or the pump's.

    Parameters
    ----------
    source
        The chosen outside sensor; ``None`` uses the pump's ``main/Outside_Temp``.
    snapshot
        The tick's snapshot.
    pump
        The pump's fresh outside temperature (``None`` when it has none).

    Returns
    -------
    CurveOutside
        The value, where it came from and, when it fell back to the pump's sensor, why.
    """
    if source is None:
        return CurveOutside(pump, HeishaSignal.OUTSIDE_TEMP)
    checked = _check_outside(source, snapshot.get(source.signal), pump)
    if isinstance(checked, float):
        return CurveOutside(checked, source.signal, note=f"from {source.signal}")
    reason, why = checked
    return CurveOutside(
        pump,
        HeishaSignal.OUTSIDE_TEMP,
        fallback=True,
        note=f"from the pump: {source.signal} {why}",
        reason=reason,
    )


def _check_outside(
    source: OutsideSource, view: SignalView | None, pump: float | None
) -> float | tuple[OutsideReason, str]:
    if view is None or view.age is None:
        return OutsideReason.MISSING, "has no value"
    if view.reason is not None:
        return OutsideReason.MISSING, f"has no usable value, {view.reason}"
    if not view.fresh or view.age > source.max_age_s:
        return OutsideReason.STALE, f"is stale, {view.age / SECONDS_PER_MINUTE:.0f} min old"
    value = as_number(view.value)
    if value is None:
        return OutsideReason.IMPLAUSIBLE, "is implausible, not a finite number"
    low, high = source.plausible_min_c, source.plausible_max_c
    if not low <= value <= high:
        why = f"is implausible, {value:g} °C is outside {low:g}…{high:g} °C"
        return OutsideReason.IMPLAUSIBLE, why
    if pump is not None and abs(value - pump) > source.max_deviation_k:
        why = (
            f"is too far from the pump, {value:g} °C against {pump:g} °C, "
            f"more than {source.max_deviation_k:g} K apart"
        )
        return OutsideReason.DEVIATES, why
    return value


@dataclass(frozen=True, slots=True)
class _Observed:
    outside: float | None
    curve: CurveOutside
    outlet: float | None
    running: bool | None
    defrost: bool | None
    dhw: bool | None
    heating_mode: int | None
    operating_mode: int | None
    alive: bool
    room: RoomInput | None
    refs: tuple[InputRef, ...]
    missing: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Check:
    offset: float | None
    since: float | None
    plausible: bool
    deviation: float | None = None
    latched: float | None = None


def _fresh_number(view: SignalView | None) -> float | None:
    if view is None or not view.fresh:
        return None
    return as_number(view.value)


def _view_ref(snapshot: Snapshot, signal: SignalId) -> InputRef:
    view = snapshot.get(signal)
    if view is None:
        return InputRef(signal, None, None, False)
    return InputRef(signal, view.value, view.age, view.fresh, view.source.value)


def _actual_ref(actual: ActualValue | None, signal: SignalId) -> InputRef:
    if actual is None:
        return InputRef(signal, None, None, False)
    return InputRef(actual.signal, actual.value, actual.age, actual.fresh, "actual")


def _fresh_int(actual: ActualValue | None) -> int | None:
    return actual.value if actual is not None and actual.fresh else None


@dataclass(frozen=True, slots=True)
class _Tick:
    """What one controlled tick sees before any term is computed."""

    now: float
    dt: float
    outside: float
    outlet: float
    outside_f: float
    curve: CurveOutside
    defrost: bool
    dhw: bool
    running: bool
    plan: PlanSlice | None
    model: ModelPlan | None
    override: Override | None
    manual_setpoint: Override | None
    boost: float
    seen: RoomInput | None
    fresh_room: RoomInput | None
    check: _Check
    room: RoomInput | None
    implausible: bool
    reference_c: float | None
    stove: StoveStep
    pi_room: RoomInput | None
    room_lost_at: float | None
    lost_for: float
    fade: float


@dataclass(frozen=True, slots=True)
class _Sum:
    """The terms of one tick and their sum before and after the safety clamp."""

    terms: tuple[Term, ...]
    curve_sp: float
    target: float
    feedback: Feedback
    plan_raw: float
    plan_w: float
    stove_value: float
    bounds: SafetyBounds
    ramp: Ramp
    floor: Floor
    pre_clamp: float
    pre_round: float


@dataclass(frozen=True, slots=True)
class _Setpoint:
    """The issued integer setpoint of one tick and what decided it."""

    final: int
    binding: str | None
    integer_clamp: tuple[int, int] | None
    reference: int | None
    dwell: float
    last_change_at: float | None


_PLAN_LADDER: Final = {
    PlanSource.OPTIMISER: LadderLevel.OPTIMISER_PLAN,
    PlanSource.MODEL: LadderLevel.MODEL_PLAN,
    PlanSource.RULE: LadderLevel.RULE_PLAN,
}


def _ladder(plan: PlanSlice | None, room: RoomInput | None) -> LadderLevel:
    if plan is not None:
        return _PLAN_LADDER[plan.source]
    if room is not None:
        return LadderLevel.SCHEDULE_CURVE_FEEDBACK
    return LadderLevel.CURVE_ONLY


@dataclass(frozen=True, slots=True)
class OvenbirdController:
    """The ovenbird controller (see the module docstring for the pipeline).

    Parameters
    ----------
    config
        Controller configuration.
    name
        Controller name recorded in every decision.
    """

    config: OvenbirdConfig = field(default_factory=lambda: OvenbirdConfig.preset("mixed"))
    name: str = CONTROLLER_NAME

    def initial_state(self) -> OvenbirdState:
        """Return the state before the first tick."""
        return OvenbirdState()

    def step(self, state: OvenbirdState, inputs: ControlInputs) -> StepResult[OvenbirdState]:
        """Advance one tick.

        Parameters
        ----------
        state
            State returned by the previous tick (or :meth:`initial_state`).
        inputs
            The tick's inputs.

        Returns
        -------
        StepResult[OvenbirdState]
            New state, intents and the decision record.
        """
        observed = self._observe(inputs)
        tracked = self._track(state, observed, inputs.now.monotonic)
        refusal = self._refusal(inputs, observed)
        if refusal is not None:
            return self._refuse(tracked, inputs, observed, *refusal)
        if observed.missing:
            detail = "missing or stale: " + ", ".join(observed.missing)
            return self._hold(tracked, inputs, observed, ReasonCode.INPUTS_MISSING, detail)
        override = (
            inputs.override if inputs.override and inputs.override.active(inputs.now) else None
        )
        if inputs.mode is Mode.MANUAL and (
            override is None or override.kind != OverrideKind.SETPOINT
        ):
            detail = "manual mode without an active setpoint override"
            return self._hold(tracked, inputs, observed, ReasonCode.OVERRIDE_MISSING, detail)
        return self._control(state, tracked, inputs, observed)

    def _observe(self, inputs: ControlInputs) -> _Observed:
        snapshot = inputs.snapshot
        actual = inputs.actual
        running = compressor_running(snapshot, min_frequency_hz=self.config.compressor_min_hz)
        defrost = defrost_active(snapshot)
        dhw = dhw_active(snapshot)
        outside = _fresh_number(snapshot.get(HeishaSignal.OUTSIDE_TEMP))
        outlet = _fresh_number(snapshot.get(HeishaSignal.OUTLET_TEMP))
        required: tuple[tuple[str, object], ...] = (
            (HeishaSignal.OUTSIDE_TEMP, outside),
            (HeishaSignal.OUTLET_TEMP, outlet),
            (HeishaSignal.COMPRESSOR_FREQ, running.value),
            (HeishaSignal.DEFROSTING_STATE, defrost.value),
            (HeishaSignal.THREEWAY_VALVE_STATE, dhw.value),
        )
        refs = [
            _view_ref(snapshot, signal)
            for signal in (
                HeishaSignal.OUTSIDE_TEMP,
                HeishaSignal.OUTLET_TEMP,
                HeishaSignal.INLET_TEMP,
                HeishaSignal.COMPRESSOR_FREQ,
                HeishaSignal.DEFROSTING_STATE,
                HeishaSignal.THREEWAY_VALVE_STATE,
            )
        ]
        refs.append(_actual_ref(actual.heating_mode, HeishaSignal.HEATING_MODE))
        refs.append(_actual_ref(actual.operating_mode, HeishaSignal.OPERATING_MODE_STATE))
        refs.append(_actual_ref(actual.water_target, HeishaSignal.Z1_WATER_TARGET_TEMP))
        refs.append(_actual_ref(actual.max_pump_duty, HeishaSignal.MAX_PUMP_DUTY))
        crosscheck = self.config.room.crosscheck
        if crosscheck is not None:
            refs.append(_view_ref(snapshot, crosscheck))
        stove = self.config.stove
        if stove is not None and stove.reference is not None:
            refs.append(_view_ref(snapshot, stove.reference))
        if self.config.outside is not None:
            refs.append(_view_ref(snapshot, self.config.outside.signal))
        heartbeat = snapshot.heishamon
        refs.append(
            InputRef(STATS_SIGNAL, heartbeat.alive, heartbeat.heartbeat_age, heartbeat.alive)
        )
        room = inputs.room
        if room is not None:
            refs.append(InputRef(room.source, room.value, room.age, room.fresh, "room"))
        return _Observed(
            outside=outside,
            curve=curve_outside(self.config.outside, snapshot, outside),
            outlet=outlet,
            running=running.value,
            defrost=defrost.value,
            dhw=dhw.value,
            heating_mode=_fresh_int(actual.heating_mode),
            operating_mode=_fresh_int(actual.operating_mode),
            alive=heartbeat.alive,
            room=room,
            refs=tuple(refs),
            missing=tuple(str(signal) for signal, value in required if value is None),
        )

    def _track(self, state: OvenbirdState, observed: _Observed, now: float) -> OvenbirdState:
        dt = 0.0 if state.last_tick_at is None else max(0.0, now - state.last_tick_at)
        running, started, stopped = state.running, state.run_started_at, state.stopped_at
        phase, elapsed, cap = state.ramp_phase, state.ramp_elapsed_s, state.ramp_cap
        if observed.running is True:
            if state.running is False:
                started = now
                phase, elapsed, cap = RampPhase.IDLE, 0.0, None
                quiet_start = observed.dhw is False and observed.defrost is False
                if self.config.ramp.enabled and quiet_start:
                    phase = RampPhase.HOLD
            elif state.running is True and phase is not RampPhase.IDLE:
                if observed.defrost is not True:
                    elapsed += dt
            running = True
        elif observed.running is False:
            if state.running is True:
                stopped = now
            started, phase, elapsed, cap = None, RampPhase.IDLE, 0.0, None
            running = False
        outside_filtered, outside_at = state.outside_filtered, state.outside_at
        if observed.curve.value is not None:
            outside_filtered = filter_outside(
                state.outside_filtered,
                state.outside_at,
                observed.curve.value,
                now,
                self.config.outside_filter_tau_s,
            )
            outside_at = now
        return replace(
            state,
            last_tick_at=now,
            running=running,
            run_started_at=started,
            stopped_at=stopped,
            ramp_phase=phase,
            ramp_elapsed_s=elapsed,
            ramp_cap=cap,
            outside_filtered=outside_filtered,
            outside_at=outside_at,
        )

    def _refusal(self, inputs: ControlInputs, observed: _Observed) -> tuple[ReasonCode, str] | None:
        if inputs.mode is Mode.OFF:
            return ReasonCode.MODE_OFF, "controller is off"
        if not observed.alive:
            return ReasonCode.HEISHAMON_DEAD, "no live HeishaMon heartbeat"
        if observed.heating_mode is None or observed.operating_mode is None:
            return ReasonCode.MODE_UNKNOWN, "heating or operating mode not freshly known"
        if observed.heating_mode != self.config.direct_heating_mode:
            return ReasonCode.MODE_MISMATCH, f"Heating_Mode is {observed.heating_mode}, not Direct"
        if observed.operating_mode not in self.config.allowed_operating_modes:
            return (
                ReasonCode.MODE_MISMATCH,
                f"Operating_Mode_State is {observed.operating_mode}, not heat",
            )
        return None

    def _record(
        self,
        state: OvenbirdState,
        inputs: ControlInputs,
        observed: _Observed,
        *,
        ladder: LadderLevel,
        reason: ReasonCode,
        note: str,
        intents: tuple[CommandIntent, ...],
        extra: dict[str, StateValue] | None = None,
        terms: tuple[Term, ...] = (),
        pre_round: float | None = None,
        setpoint: int | None = None,
        binding: str | None = None,
        flip: tuple[float, str] | None = None,
        actor: str | None = None,
    ) -> DecisionRecord:
        flat = state.as_flat()
        flat.update(extra or {})
        return DecisionRecord(
            at=inputs.now,
            controller=self.name,
            mode=inputs.mode,
            ladder=ladder,
            terms=terms,
            pre_round=pre_round,
            setpoint=setpoint,
            binding=binding,
            flip_distance=None if flip is None else flip[0],
            flip_input=None if flip is None else flip[1],
            inputs_used=observed.refs,
            controller_state=flat,
            reason=reason,
            note=note,
            intents=intents,
            actor=actor,
        )

    def _refuse(
        self,
        state: OvenbirdState,
        inputs: ControlInputs,
        observed: _Observed,
        reason: ReasonCode,
        detail: str,
    ) -> StepResult[OvenbirdState]:
        note = f"Refusing control: {detail}; no intents, integrator frozen."
        record = self._record(
            state,
            inputs,
            observed,
            ladder=LadderLevel.REFUSE,
            reason=reason,
            note=note,
            intents=(),
            extra={"frozen_by": reason.value},
        )
        return StepResult(state, (), record)

    def _hold(
        self,
        state: OvenbirdState,
        inputs: ControlInputs,
        observed: _Observed,
        reason: ReasonCode,
        detail: str,
    ) -> StepResult[OvenbirdState]:
        """Repeat the last setpoint and quiet level; the pump duty follows the compressor.

        The held setpoint is clamped to the safety bounds at the current raw
        ``Outside_Temp`` when that is fresh (the bounds move with the outside
        temperature; the clamp is the decision's binding). The pump duty depends only
        on the compressor, defrost and DHW states, so it is decided as usual when
        those are known (a held idle duty would otherwise stay while the compressor
        starts); otherwise the last duty is repeated, and during a defrost none is
        asked for.
        """
        extra: dict[str, StateValue] = {"frozen_by": reason.value}
        binding: str | None = None
        clamp_note: str | None = None
        held = state.setpoint
        if held is not None and observed.outside is not None:
            bounds = self.config.safety.bounds(observed.outside)
            extra |= {"safety_low_c": bounds.low, "safety_high_c": bounds.high}
            clamped = bounds.clamp_int(held)
            if clamped != held:
                binding = (bounds.high_source if clamped < held else bounds.low_source).value
                clamp_note = f"safety bound {binding} clamps the held {held} → {clamped} °C"
                state = replace(state, setpoint=clamped, last_change_at=inputs.now.monotonic)
        known = (observed.running, observed.defrost, observed.dhw)
        if self.config.pump_duty is not None and all(flag is not None for flag in known):
            duty, duty_reason = self._pump_duty(state, inputs, observed)
            state = replace(state, pump_duty=duty)
        else:
            duty_reason = None if observed.defrost is True else reason
        intents = self._held_intents(state, reason, duty_reason)
        kept = "keeping the last intents" if intents else "no previous intent to keep"
        parts = [f"Holding: {detail}; {kept}"]
        if clamp_note is not None:
            parts.append(clamp_note)
        if observed.defrost is True and self.config.pump_duty is not None:
            parts.append("defrost: the pump sets its own duty; no duty command")
        note = "; ".join(parts) + "."
        record = self._record(
            state,
            inputs,
            observed,
            ladder=LadderLevel.HOLD,
            reason=reason,
            note=note,
            intents=intents,
            setpoint=state.setpoint,
            binding=binding,
            extra=extra,
        )
        return StepResult(state, intents, record)

    @staticmethod
    def _held_intents(
        state: OvenbirdState, reason: ReasonCode, duty_reason: ReasonCode | None = None
    ) -> tuple[CommandIntent, ...]:
        intents: list[CommandIntent] = []
        if state.setpoint is not None:
            intents.append(CommandIntent(IntentKind.WATER_SETPOINT, state.setpoint, reason))
        if state.pump_duty is not None and duty_reason is not None:
            intents.append(CommandIntent(IntentKind.MAX_PUMP_DUTY, state.pump_duty, duty_reason))
        if state.quiet_level is not None:
            intents.append(CommandIntent(IntentKind.QUIET_MODE, state.quiet_level, reason))
        return tuple(intents)

    def _control(
        self,
        previous: OvenbirdState,
        state: OvenbirdState,
        inputs: ControlInputs,
        observed: _Observed,
    ) -> StepResult[OvenbirdState]:
        outside, outlet, outside_f = observed.outside, observed.outlet, state.outside_filtered
        if outside is None or outlet is None or outside_f is None:
            detail = "outside or outlet temperature unavailable"
            return self._hold(state, inputs, observed, ReasonCode.INPUTS_MISSING, detail)
        cfg = self.config
        tick = self._tick(previous, state, inputs, observed, outside, outlet, outside_f)
        total = self._sum(state, tick)
        setpoint = self._setpoint(previous, state, inputs, tick, total)
        integral, frozen_by, at_life = self._integrator(state, tick, total, setpoint)
        duty, duty_reason = self._pump_duty(state, inputs, observed)
        quiet = cfg.quiet.level_at(inputs.now.wall) if cfg.quiet is not None else None
        new_state = stove_mode.with_stove(
            replace(
                state,
                setpoint=setpoint.final,
                last_change_at=setpoint.last_change_at,
                integral_k=integral,
                ramp_phase=total.ramp.phase,
                ramp_cap=total.ramp.cap,
                pump_duty=duty,
                quiet_level=quiet,
                crosscheck_offset_k=tick.check.offset,
                crosscheck_since=tick.check.since,
                crosscheck_latched=tick.check.latched,
                room_lost_at=tick.room_lost_at,
                integral_at_life_k=at_life,
            ),
            tick.stove,
        )
        reason = reason_code(
            setpoint.binding,
            tick.override is not None,
            tick.plan,
            tick.defrost,
            tick.dhw,
            tick.room,
            inputs,
            tick.implausible,
            stove=tick.stove.active,
        )
        intents: list[CommandIntent] = [
            CommandIntent(IntentKind.WATER_SETPOINT, setpoint.final, reason)
        ]
        if duty is not None and duty_reason is not None:
            intents.append(CommandIntent(IntentKind.MAX_PUMP_DUTY, duty, duty_reason))
        if quiet is not None:
            intents.append(CommandIntent(IntentKind.QUIET_MODE, quiet, ReasonCode.QUIET_SCHEDULE))
        record = self._explain(
            new_state, state, inputs, observed, tick, total, setpoint, frozen_by, reason, intents
        )
        return StepResult(new_state, tuple(intents), record)

    def _tick(
        self,
        previous: OvenbirdState,
        state: OvenbirdState,
        inputs: ControlInputs,
        observed: _Observed,
        outside: float,
        outlet: float,
        outside_f: float,
    ) -> _Tick:
        """Gather what this tick sees: overrides, the trusted room value and the stove."""
        cfg = self.config
        now = inputs.now.monotonic
        dt = 0.0 if previous.last_tick_at is None else max(0.0, now - previous.last_tick_at)
        plan = inputs.plan if inputs.plan is not None and inputs.plan.active(inputs.now) else None
        override = (
            inputs.override if inputs.override and inputs.override.active(inputs.now) else None
        )
        manual_setpoint = override if override and override.kind is OverrideKind.SETPOINT else None
        boost = override.value if override and override.kind is OverrideKind.BOOST else 0.0
        fresh_room = inputs.room if inputs.room is not None and inputs.room.fresh else None
        check = self._crosscheck(
            state, fresh_room, inputs.snapshot, now, dt, stove=state.stove_active
        )
        room = fresh_room if check.plausible else None
        implausible = fresh_room is not None and room is None
        reference_c = stove_mode.reference_temperature(cfg, inputs.snapshot)
        stove = stove_mode.advance(cfg, state, room, override, now, reference_c)
        if stove.active and not state.stove_active:
            check = replace(check, since=None)
        stale = inputs.room is not None and fresh_room is None
        room_lost_at = (
            (state.room_lost_at if state.room_lost_at is not None else now)
            if stale or implausible
            else None
        )
        lost_for = 0.0 if room_lost_at is None else now - room_lost_at
        plan, model = self._model_plan(plan, room, stove)
        return _Tick(
            now=now,
            dt=dt,
            outside=outside,
            outlet=outlet,
            outside_f=outside_f,
            curve=observed.curve,
            defrost=observed.defrost is True,
            dhw=observed.dhw is True,
            running=observed.running is True,
            plan=plan,
            model=model,
            override=override,
            manual_setpoint=manual_setpoint,
            boost=boost,
            seen=inputs.room,
            fresh_room=fresh_room,
            check=check,
            room=room,
            implausible=implausible,
            reference_c=reference_c,
            stove=stove,
            pi_room=None if stove.active else room,
            room_lost_at=room_lost_at,
            lost_for=lost_for,
            fade=max(0.0, 1.0 - lost_for / HELD_INTEGRAL_FADE_S),
        )

    def _model_plan(
        self, plan: PlanSlice | None, room: RoomInput | None, stove: StoveStep
    ) -> tuple[PlanSlice | None, ModelPlan | None]:
        """Return the plan that applies this tick and, for a model slice, what became of it.

        A model slice is clamped to the model bounds and gets the reason of its sign;
        it does not apply (``None``) while blocked or when the bounds cut it to zero.
        A model water slice is clamped to the water bounds and scaled by the room
        authority of the trusted room value against comfort
        (:meth:`~ovenbird_core.control.config.ModelPlanConfig.authority`), under the
        same blocks. Every other slice passes unchanged.
        """
        if plan is None or plan.source is not PlanSource.MODEL:
            return plan, None
        block: ModelPlanBlock | None = None
        if stove.active:
            block = ModelPlanBlock.STOVE_ACTIVE
        elif room is None:
            block = ModelPlanBlock.ROOM_UNTRUSTED
        elif stove.blocked or stove.level_blocked or stove.reentry_wait or stove.fault:
            block = ModelPlanBlock.STOVE_RECOVERY
        elif plan.valid_until.since(plan.valid_from) > MODEL_PLAN_MAX_SLICE_S:
            block = ModelPlanBlock.SLICE_TOO_LONG
        if plan.water:
            return self._model_water(plan, room, block)
        applied = 0.0 if block is not None else self.config.model_plan.clamp(plan.room_offset_k)
        model = ModelPlan(plan.room_offset_k, applied, block)
        if applied == 0.0:
            return None, model
        reason = ReasonCode.PLAN_SETBACK if applied < 0.0 else ReasonCode.PLAN_PREHEAT
        return replace(plan, room_offset_k=applied, reason=reason), model

    def _model_water(
        self, plan: PlanSlice, room: RoomInput | None, block: ModelPlanBlock | None
    ) -> tuple[PlanSlice | None, ModelPlan]:
        """Return a model water slice as it applies this tick (bounded, authority-scaled)."""
        mp = self.config.model_plan
        requested = plan.water_offset_k
        applied = 0.0
        authority: float | None = None
        if block is None and room is not None:
            authority = mp.authority(
                room.value, self.config.comfort_room_c, requested, room.quantum_k
            )
            applied = mp.clamp_water(requested) * authority + 0.0
        model = ModelPlan(plan.room_offset_k, 0.0, block, requested, applied, authority)
        if applied == 0.0:
            return None, model
        reason = ReasonCode.PLAN_SETBACK if applied < 0.0 else ReasonCode.PLAN_PREHEAT
        return replace(plan, water_offset_k=applied, reason=reason), model

    def _sum(self, state: OvenbirdState, tick: _Tick) -> _Sum:
        """Add the terms up to the continuous, safety-clamped ``pre_round`` (stages 3-4)."""
        cfg = self.config
        raw = tick.outside if tick.curve.value is None else tick.curve.value
        curve_sp, curve = curve_term(cfg, tick.outside_f, raw, tick.curve.note)
        terms: list[Term] = [curve]
        plan = tick.plan
        plan_room = plan.room_offset_k if plan is not None and tick.pi_room is not None else 0.0
        target = cfg.comfort_room_c + plan_room
        feedback = room_feedback(
            cfg,
            state,
            target,
            stove=tick.stove.active,
            room=tick.room,
            fresh_room=tick.fresh_room,
            implausible=tick.implausible,
            deviation=tick.check.deviation,
            seen=tick.seen,
            fade=tick.fade,
            lost_for=tick.lost_for,
        )
        terms.append(feedback.term)
        plan_raw, plan_w, plan_t = plan_term(
            cfg,
            plan,
            tick.outside_f,
            stove=tick.stove.active,
            pi_room=tick.pi_room,
            model=tick.model,
        )
        terms.append(plan_t)
        boost_t = boost_term(tick.override, tick.boost)
        if boost_t is not None:
            terms.append(boost_t)
        bounds = cfg.safety.bounds(tick.outside)
        stove_value, stove_t = stove_mode.stove_term(
            cfg, tick.stove, tick.room, tick.reference_c, curve_sp, bounds, tick.now
        )
        if stove_t is not None:
            terms.append(stove_t)
        base = curve_sp + feedback.u + plan_w + tick.boost + stove_value
        ramp = start_ramp(
            cfg,
            state,
            running=tick.running,
            defrost=tick.defrost,
            dhw=tick.dhw,
            outlet=tick.outlet,
            curve_sp=curve_sp,
            base=base,
            dt=tick.dt,
        )
        terms.append(ramp.term)
        raw_sum = base + ramp.value
        if tick.manual_setpoint is not None:
            terms.append(override_term(tick.manual_setpoint, raw_sum))
            raw_sum = tick.manual_setpoint.value
        floor = cycling_floor(
            cfg,
            state,
            tick.now,
            manual=tick.manual_setpoint is not None,
            running=tick.running,
            defrost=tick.defrost,
            dhw=tick.dhw,
            outlet=tick.outlet,
            base=base,
            raw_sum=raw_sum,
        )
        terms.append(floor.term)
        pre_clamp = raw_sum + floor.cycling
        pre_round, safety = safety_term(bounds, pre_clamp, tick.outside)
        terms.append(safety)
        return _Sum(
            terms=tuple(terms),
            curve_sp=curve_sp,
            target=target,
            feedback=feedback,
            plan_raw=plan_raw,
            plan_w=plan_w,
            stove_value=stove_value,
            bounds=bounds,
            ramp=ramp,
            floor=floor,
            pre_clamp=pre_clamp,
            pre_round=pre_round,
        )

    def _setpoint(
        self,
        previous: OvenbirdState,
        state: OvenbirdState,
        inputs: ControlInputs,
        tick: _Tick,
        total: _Sum,
    ) -> _Setpoint:
        """Turn ``pre_round`` into the issued integer setpoint (stages 5-6) and its binding."""
        cfg = self.config
        reference = previous.setpoint
        if reference is None and inputs.actual.water_target is not None:
            reference = _fresh_int(inputs.actual.water_target)
        dwell = dwell_time(cfg, total.ramp.phase, state.ramp_phase, state.ramp_cap)
        manual = tick.manual_setpoint is not None
        stages = soften(
            cfg.stages,
            total.pre_round,
            reference,
            previous.last_change_at,
            tick.now,
            dwell,
            tick.defrost,
            tick.dhw,
            manual,
        )
        final, binding, integer_clamp = hard_constraints(
            cfg, stages, total.floor.floor, reference, total.bounds
        )
        if binding is None:
            feedback = total.feedback
            binding = soft_binding(
                manual,
                total.pre_clamp,
                total.bounds,
                total.floor.cycling,
                total.ramp.value,
                feedback.u,
                feedback.u_lim,
                feedback.u_raw,
                total.plan_w,
                total.plan_raw,
            )
        changed = reference is None or final != reference
        last_change_at = tick.now if changed else previous.last_change_at
        return _Setpoint(final, binding, integer_clamp, reference, dwell, last_change_at)

    def _integrator(
        self, state: OvenbirdState, tick: _Tick, total: _Sum, setpoint: _Setpoint
    ) -> tuple[float, list[str], float | None]:
        """Advance the integrator (stage 7).

        Returns
        -------
        tuple[float, list[str], float | None]
            The new integrator, what froze it and its value at the last proof of life.
        """
        cfg = self.config
        frozen_by = freezes(
            defrost=tick.defrost,
            dhw=tick.dhw,
            implausible=tick.implausible,
            room=tick.room,
            seen=tick.seen,
            stove=tick.stove.active,
            manual=tick.manual_setpoint is not None,
        )
        integral, frozen_by = integrate(
            cfg,
            state.integral_k,
            total.feedback,
            frozen_by,
            pre_clamp=total.pre_clamp,
            pre_round=total.pre_round,
            bounds=total.bounds,
            final=setpoint.final,
            binding=setpoint.binding,
            ramp=total.ramp.value,
            cycling=total.floor.cycling,
            dt=tick.dt,
        )
        lost = tick.room_lost_at is not None
        at_life = integral_at_life(cfg, state, tick.room, tick.dt, lost=lost)
        integral, frozen_by = rollback(
            cfg,
            integral,
            at_life,
            tick.pi_room,
            frozen_by,
            defrost=tick.defrost,
            dhw=tick.dhw,
            stove=tick.stove.active,
            lost=lost,
        )
        return integral, frozen_by, at_life

    def _explain(
        self,
        new_state: OvenbirdState,
        state: OvenbirdState,
        inputs: ControlInputs,
        observed: _Observed,
        tick: _Tick,
        total: _Sum,
        setpoint: _Setpoint,
        frozen_by: list[str],
        reason: ReasonCode,
        intents: list[CommandIntent],
    ) -> DecisionRecord:
        """Build the decision record (flip distance, controller state, note) of the tick."""
        cfg = self.config
        feedback, bounds, ramp, floor = total.feedback, total.bounds, total.ramp, total.floor
        final, binding, last_change_at = setpoint.final, setpoint.binding, setpoint.last_change_at
        pi_room = tick.pi_room
        flip = flip_distance(
            cfg,
            final,
            total.pre_round,
            total.pre_clamp,
            bounds,
            pi_room,
            cfg.feedback.kp,
            feedback.u_raw,
            tick.outside_f,
            feedback.u != feedback.u_raw,
        )
        dwell_left = (
            0.0
            if last_change_at is None
            else max(0.0, setpoint.dwell - (tick.now - last_change_at))
        )
        extra: dict[str, StateValue] = {
            "frozen_by": ",".join(frozen_by) or None,
            "room_target_c": total.target if tick.room is not None else None,
            "room_error_k": feedback.error,
            "dwell_remaining_s": dwell_left,
            "safety_low_c": bounds.low,
            "safety_high_c": bounds.high,
        }
        extra |= self._room_extra(
            inputs.room, feedback.authority, tick.check, tick.implausible, state.stove_active
        )
        extra |= stove_mode.stove_extra(
            cfg, tick.stove, tick.reference_c, total.stove_value, inputs.now
        )
        if not cfg.weather_compensation:
            extra["base"] = "fixed"
        if cfg.outside is not None:
            extra["outside_source"] = str(tick.curve.source)
            extra["outside_fallback"] = tick.curve.fallback
            extra["outside_reason"] = None if tick.curve.reason is None else tick.curve.reason.value
        if tick.model is not None:
            extra["model_plan_requested_k"] = tick.model.requested_k
            extra["model_plan_applied_k"] = tick.model.applied_k
            extra["model_plan_ignored"] = (
                None if tick.model.block is None else tick.model.block.value
            )
            if tick.model.water:
                extra["model_plan_water_requested_k"] = tick.model.water_requested_k
                extra["model_plan_water_applied_k"] = tick.model.water_applied_k
                extra["model_plan_authority"] = tick.model.authority
        on_change = pi_room is not None and pi_room.profile is RoomProfile.ON_CHANGE
        stove = stove_mode.sentence(
            tick.stove,
            state.integral_k,
            total.curve_sp,
            tick.outside_f,
            total.stove_value,
            tick.now,
        )
        note = decision_note(
            total.curve_sp,
            tick.outside_f,
            pi_room,
            feedback.error,
            feedback.u,
            tick.plan,
            total.plan_w,
            tick.boost,
            ramp.cap,
            ramp.value,
            floor.floor,
            floor.cycling,
            total.pre_clamp,
            total.pre_round,
            bounds,
            final,
            setpoint.reference,
            binding,
            dwell_left,
            feedback.status if on_change else None,
            tick.implausible,
            defrost=tick.defrost,
            dhw=tick.dhw,
            duty_skipped=tick.defrost and cfg.pump_duty is not None,
            integer_clamp=setpoint.integer_clamp,
            held_offset=feedback.held_offset,
            stove=stove,
            fixed=not cfg.weather_compensation,
            model_ignored=None if tick.model is None else tick.model.ignored_text(),
            model_water=(
                tick.model.water_text() if tick.model is not None and tick.model.water else None
            ),
        )
        return self._record(
            new_state,
            inputs,
            observed,
            ladder=_ladder(tick.plan, tick.room),
            reason=reason,
            note=note,
            intents=tuple(intents),
            extra=extra,
            terms=total.terms,
            pre_round=total.pre_round,
            setpoint=final,
            binding=binding,
            flip=flip,
            actor=tick.override.actor if tick.override is not None else None,
        )

    def crosscheck_threshold_k(self, stove: bool) -> float:
        """Disagreement at which the cross-check starts its timer (wider in stove mode)."""
        threshold = self.config.room.crosscheck_threshold_k
        sc = self.config.stove
        return threshold + sc.crosscheck_allow_k if stove and sc is not None else threshold

    def _crosscheck(
        self,
        state: OvenbirdState,
        room: RoomInput | None,
        snapshot: Snapshot,
        now: float,
        dt: float,
        *,
        stove: bool = False,
    ) -> _Check:
        """Advance the plausibility cross-check (see the module docstring).

        A latched verdict ends only when the room value has changed and agrees with
        the cross-check again (a sensor that fails high but keeps reporting stays
        flagged). In stove mode (``stove``: an episode was active at the previous
        tick) the threshold is widened by the stove's ``crosscheck_allow_k`` and the
        offset is not learned.
        """
        rc = self.config.room
        if rc.crosscheck is None:
            return _Check(state.crosscheck_offset_k, None, True)
        other = _fresh_number(snapshot.get(rc.crosscheck))
        offset, since = state.crosscheck_offset_k, state.crosscheck_since
        latched = state.crosscheck_latched
        agree = rc.crosscheck_threshold_k - CROSSCHECK_HYSTERESIS_K
        deviation: float | None = None
        if room is not None and other is not None and offset is not None:
            deviation = other - room.value - offset
        agreed = deviation is not None and abs(deviation) < agree
        if latched is not None and room is not None and room.value != latched and agreed:
            latched, since = None, None
        threshold = self.crosscheck_threshold_k(stove)
        if room is not None and other is not None:
            diff = other - room.value
            if offset is None:
                offset = diff
            deviation = diff - offset
            if latched is None and abs(deviation) > threshold:
                since = now if since is None else since
            elif latched is None and abs(deviation) < threshold - CROSSCHECK_HYSTERESIS_K:
                since = None
                held = room.held_s
                if not stove and held is not None and held < CROSSCHECK_LEARN_HELD_S:
                    offset += (diff - offset) * min(1.0, dt / rc.crosscheck_tau_s)
        sustained = since is not None and now - since >= rc.crosscheck_sustain_s
        if sustained and latched is None and room is not None:
            latched = room.value
        plausible = latched is None and not sustained
        return _Check(offset, since, plausible, deviation, latched)

    def _room_extra(
        self,
        room: RoomInput | None,
        authority: float,
        check: _Check,
        implausible: bool,
        stove: bool = False,
    ) -> dict[str, StateValue]:
        if room is None:
            return {}
        checked = self.config.room.crosscheck is not None
        return {
            "room_profile": room.profile.value,
            "room_quantum_k": room.quantum_k,
            "room_held_s": room.held_s,
            "room_alive_s": room.alive_s,
            "room_alive_by": room.alive_by,
            "room_authority": authority,
            "room_plausible": check.plausible if checked else None,
            "room_crosscheck_deviation_k": check.deviation,
            "room_crosscheck_threshold_k": self.crosscheck_threshold_k(stove) if checked else None,
        }

    def _pump_duty(
        self, state: OvenbirdState, inputs: ControlInputs, observed: _Observed
    ) -> tuple[int | None, ReasonCode | None]:
        """Return the desired max pump duty and its reason (no reason: no intent).

        During a defrost the pump drives its own duty and ignores the setting, so
        nothing is asked and the desired duty is kept for after the defrost. While
        the compressor runs or a DHW run is active the heat duty applies (a higher
        reported value is kept); the idle duty once the compressor has been stopped
        for ``idle_delay_s``.
        """
        pd = self.config.pump_duty
        if pd is None:
            return None, None
        if observed.defrost is True:
            return state.pump_duty, None
        if observed.running is True or observed.dhw is True:
            reported = _fresh_int(inputs.actual.max_pump_duty)
            kept = max(pd.heat, state.pump_duty or 0, reported or 0)
            return kept, ReasonCode.PUMP_DUTY_HEAT
        since_stop = None if state.stopped_at is None else inputs.now.monotonic - state.stopped_at
        if since_stop is None or since_stop >= pd.idle_delay_s:
            return pd.idle, ReasonCode.PUMP_DUTY_IDLE
        return (state.pump_duty if state.pump_duty is not None else pd.heat), (
            ReasonCode.PUMP_DUTY_HEAT
        )

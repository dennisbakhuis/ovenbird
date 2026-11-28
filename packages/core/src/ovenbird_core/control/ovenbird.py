"""The ovenbird controller: curve + room feedback + plan + start ramp, then safety.

**Pipeline of one tick**
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

**Room value guards**
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

**Plan slices**
An active :class:`~ovenbird_core.control.types.PlanSlice` shifts the room target the PI
works on (``room_target_c``); without a room sensor its offset maps to water through
the curve slope (``plan_max_water_k``). A rule slice is clamped to
``±plan_rule_max_k`` first (default 1 K, at most 1.5 K), whatever the planner sent; the
``plan`` term and the decision note say so. An expired or future slice has no effect.
A slice is paused (no effect, noted in the ``plan`` term) during a wood-stove episode,
in its tail (the detection waits for the room to cool below the exit threshold after
the cap or a manual stop) and while a room sensor exists but its value is not trusted
(stale or implausible). A raised target lifts the stove's entry thresholds by the
same bounded amount; the start ramp, the cycling floor, the stages, the defrost/DHW
rules and the safety envelope apply to the shifted sum as always. The target steps
with the slice: its P part moves the water by ``kp`` times the step at once and the
integrator only winds while the room is more than one sensor step off the new target.

**Wood-stove mode**
See :mod:`ovenbird_core.control.stove`: while an episode is active the room PI is
frozen with its integrator held, the plan is paused and the ``stove`` term lowers
the curve; every other stage applies as always.

**Manual room target and away**
A ``room_target`` override (a manual boost or a cooler room) or an ``away`` override
in :attr:`~ovenbird_core.control.types.ControlInputs.room_override` shifts the comfort
room target by its value for as long as it is active, exactly as a plan slice does: the
PI works on the shifted target, and without a trusted room value the shift maps to
water through the curve slope (``plan_max_water_k``). It replaces the plan (a slice is
paused meanwhile), raises the stove's entry thresholds by a positive shift, and is
itself paused (no effect, noted in the ``room_target`` term) during a wood-stove episode
and while the summer switch is on. Ramp, cycling floor, stages, defrost/DHW rules and
the safety envelope apply to the shifted sum as always. Without such an override
nothing of this appears in the record.

**Summer switch**
With :class:`~ovenbird_core.control.config.SummerConfig` the controller keeps a slow
mean of the curve's outside temperature (an exponential filter, 24 h by default). Once
it is above ``off_c`` (after the filter has run for its time constant) the switch is on
until the mean falls below ``off_c - hysteresis_k``. While on, no space heating is
requested: the ``summer`` term takes the setpoint down to the safety minimum (ovenbird
never switches the pump off), the room PI is paused with its integrator held and the
plan and a manual room target are paused. The cycling floor and the safety envelope
still apply, so a running compressor is not cut inside its minimum-run window.

**Quiet mode after a start**
With :class:`~ovenbird_core.control.config.QuietStartConfig` the quiet-mode intent is,
for ``duration_s`` after a detected compressor start, the quieter (higher) of the start
level and the scheduled level; outside that window the schedule applies (level 0
outside its windows). During a defrost the quiet level is not changed.

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
from ovenbird_core.control.config import OutsideSource, OvenbirdConfig
from ovenbird_core.control.curve import filter_outside
from ovenbird_core.control.integrator import freezes, integral_at_life, integrate, rollback
from ovenbird_core.control.notes import (
    SECONDS_PER_MINUTE,
    NoteInputs,
    decision_note,
    flip_distance,
    reason_code,
    signed,
    soft_binding,
)
from ovenbird_core.control.observe import as_number
from ovenbird_core.control.protocol import StepResult
from ovenbird_core.control.record import DecisionRecord, InputRef, StateValue, Term
from ovenbird_core.control.safety import EPSILON, SafetyBounds
from ovenbird_core.control.stages import dwell_time, hard_constraints, soften
from ovenbird_core.control.state import OvenbirdState, RampPhase
from ovenbird_core.control.stove import (
    StoveStep,
)
from ovenbird_core.control.terms import (
    HELD_INTEGRAL_FADE_S,
    Feedback,
    Floor,
    PlanShift,
    Ramp,
    RoomShift,
    active_room_override,
    boost_term,
    bounded_offset,
    curve_term,
    cycling_floor,
    override_term,
    plan_clause,
    plan_shift,
    plan_term,
    room_feedback,
    room_shift,
    room_target_clause,
    room_target_term,
    safety_term,
    start_ramp,
    summer_term,
)
from ovenbird_core.control.types import (
    ActualValue,
    CommandIntent,
    ControlInputs,
    IntentKind,
    LadderLevel,
    Mode,
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


def carry_state(state: OvenbirdState, old: OvenbirdConfig, new: OvenbirdConfig) -> OvenbirdState:
    """Carry the controller state over a configuration change without a setpoint jump.

    The issued setpoint, its change time (dwell timer), the run and filter state
    survive, so a new configuration moves the setpoint only through deadband and
    dwell (or a hard constraint). The integrator and its mark at the room
    sensor's last proof of life are clamped to the new limit, and reset (the mark
    forgotten) when the new configuration has no integral part; a disabled start ramp
    ends a running ramp; a changed cross-check signal forgets the learned offset;
    a configuration without wood-stove mode ends an episode and forgets its state
    (an episode otherwise continues under the new thresholds); a configuration without
    the summer switch forgets its slow mean and turns it off.

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
    if new.summer is None:
        carried = replace(
            carried,
            summer_mean_c=None,
            summer_mean_at=None,
            summer_mean_from=None,
            summer_active=False,
        )
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
    """Return the usable outside value of ``source`` or why it was rejected.

    Parameters
    ----------
    source
        Configuration of the chosen outside sensor (age and plausibility limits).
    view
        Latest reading of the sensor's signal.
    pump
        The pump's own outside temperature in °C for the deviation check, if fresh.

    Returns
    -------
    float | tuple[OutsideReason, str]
        The value in °C, or the rejection reason with a note.
    """
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
    """What one tick reads from the snapshot and the caller's inputs."""

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
    """Outcome of the room plausibility cross-check: offset, onset, verdict and latch."""

    offset: float | None
    since: float | None
    plausible: bool
    deviation: float | None = None
    latched: float | None = None


def _fresh_number(view: SignalView | None) -> float | None:
    """Return the numeric value of ``view`` when present and fresh, else ``None``."""
    if view is None or not view.fresh:
        return None
    return as_number(view.value)


def _view_ref(snapshot: Snapshot, signal: SignalId) -> InputRef:
    """Return the input reference recording ``signal``'s reading in ``snapshot``."""
    view = snapshot.get(signal)
    if view is None:
        return InputRef(signal, None, None, False)
    return InputRef(signal, view.value, view.age, view.fresh, view.source.value)


def _actual_ref(actual: ActualValue | None, signal: SignalId) -> InputRef:
    """Return the input reference for the applied (read-back) value of ``signal``."""
    if actual is None:
        return InputRef(signal, None, None, False)
    return InputRef(actual.signal, actual.value, actual.age, actual.fresh, "actual")


def _fresh_int(actual: ActualValue | None) -> int | None:
    """Return the applied integer value when present and fresh, else ``None``."""
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
    plan: PlanShift | None
    override: Override | None
    room_shift: RoomShift | None
    summer: bool
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
    room_raw: float
    room_w: float
    stove_value: float
    summer_value: float
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
    PlanSource.RULE: LadderLevel.RULE_PLAN,
}


def _ladder(plan: PlanSlice | None, room: RoomInput | None) -> LadderLevel:
    """Return the ladder level: the plan's source, else curve with feedback, else curve only."""
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
        """Read the pump states, outside and outlet values and input references of a tick.

        Parameters
        ----------
        inputs
            Controller inputs of this tick.

        Returns
        -------
        _Observed
            The values and references this tick works with, and what was missing.
        """
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
        """Return the state after tracking the compressor run, start-ramp clock and outside filter.

        Parameters
        ----------
        state
            State before this tick.
        observed
            What this tick read from the snapshot.
        now
            Monotonic time of this tick, in s.
        """
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
        summer = self._track_summer(state, observed, now)
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
            summer_mean_c=summer[0],
            summer_mean_at=summer[1],
            summer_mean_from=summer[2],
            summer_active=summer[3],
        )

    def _track_summer(
        self, state: OvenbirdState, observed: _Observed, now: float
    ) -> tuple[float | None, float | None, float | None, bool]:
        """Advance the summer switch's slow outside mean and its on/off state.

        Returns
        -------
        tuple
            The mean, its sample time, the time of its first sample and whether the
            switch is on (unchanged without a curve outside value or without the switch).
        """
        sc = self.config.summer
        mean, at, since, active = (
            state.summer_mean_c,
            state.summer_mean_at,
            state.summer_mean_from,
            state.summer_active,
        )
        sample = observed.curve.value
        if sc is None or sample is None:
            return mean, at, since, active
        mean = filter_outside(mean, at, sample, now, sc.mean_tau_s)
        since = now if since is None else since
        if active and mean < sc.on_c - EPSILON:
            active = False
        elif not active and mean > sc.off_c + EPSILON and now - since >= sc.mean_tau_s:
            active = True
        return mean, now, since, active

    def _refusal(self, inputs: ControlInputs, observed: _Observed) -> tuple[ReasonCode, str] | None:
        """Return the reason code and detail for refusing control, ``None`` when the gates pass.

        Parameters
        ----------
        inputs
            Controller inputs of this tick (snapshot, applied values, mode, plan).
        observed
            What this tick read from the snapshot.
        """
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
        """Build the decision record of a tick from its state, inputs and outcome.

        Parameters
        ----------
        state
            State whose flat form the record carries.
        inputs
            Controller inputs of this tick (snapshot, applied values, mode, plan).
        observed
            What this tick read from the snapshot.
        ladder
            Decision-ladder level reached.
        reason
            Reason code of the decision.
        note
            Human-readable explanation.
        intents
            Intents issued by the decision.
        extra
            Additional flat controller-state entries.
        terms
            Terms of the setpoint sum.
        pre_round
            Continuous setpoint before rounding, in °C.
        setpoint
            Issued integer setpoint, in °C.
        binding
            Constraint that bound the setpoint, if any.
        flip
            Distance to the nearest decision flip and the input that causes it.
        actor
            Who caused a manual override, if any.
        """
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
        """Return the result of refusing control: no intents and a record saying why.

        Parameters
        ----------
        state
            State to keep unchanged.
        inputs
            Controller inputs of this tick (snapshot, applied values, mode, plan).
        observed
            What this tick read from the snapshot.
        reason
            Reason code of the refusal.
        detail
            Explanation placed in the record's note.
        """
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

        Parameters
        ----------
        state
            State after this tick's tracking.
        inputs
            Controller inputs of this tick (snapshot, applied values, mode, plan).
        observed
            What this tick read from the snapshot.
        reason
            Reason code of the held intents.
        detail
            Explanation placed in the record's note.
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
        """Return the last setpoint, pump duty and quiet level of ``state`` as intents.

        Parameters
        ----------
        state
            State holding the last issued values.
        reason
            Reason code of the setpoint and quiet intents.
        duty_reason
            Reason code of the pump-duty intent; ``None`` asks for none.
        """
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
        """Run the control stages for one tick and return the new state, intents and record.

        Parameters
        ----------
        previous
            State before this tick's tracking.
        state
            Controller state after this tick's tracking.
        inputs
            Controller inputs of this tick (snapshot, applied values, mode, plan).
        observed
            What this tick read from the snapshot.
        """
        outside, outlet, outside_f = observed.outside, observed.outlet, state.outside_filtered
        if outside is None or outlet is None or outside_f is None:
            detail = "outside or outlet temperature unavailable"
            return self._hold(state, inputs, observed, ReasonCode.INPUTS_MISSING, detail)
        tick = self._tick(previous, state, inputs, observed, outside, outlet, outside_f)
        total = self._sum(state, tick)
        setpoint = self._setpoint(previous, state, inputs, tick, total)
        integral, frozen_by, at_life = self._integrator(state, tick, total, setpoint)
        duty, duty_reason = self._pump_duty(state, inputs, observed)
        quiet, quiet_reason = self._quiet(state, inputs, observed)
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
            None if tick.plan is None else tick.plan.applied,
            tick.defrost,
            tick.dhw,
            tick.room,
            inputs,
            tick.implausible,
            stove=tick.stove.active,
            summer=tick.summer,
            room_target=(
                tick.room_shift.override.kind
                if tick.room_shift is not None and tick.room_shift.applied
                else None
            ),
        )
        intents: list[CommandIntent] = [
            CommandIntent(IntentKind.WATER_SETPOINT, setpoint.final, reason)
        ]
        if duty is not None and duty_reason is not None:
            intents.append(CommandIntent(IntentKind.MAX_PUMP_DUTY, duty, duty_reason))
        if quiet is not None:
            intents.append(CommandIntent(IntentKind.QUIET_MODE, quiet, quiet_reason))
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
        """Gather what this tick sees: overrides, the trusted room value and the stove.

        Parameters
        ----------
        previous
            State before this tick's tracking.
        state
            Controller state after this tick's tracking.
        inputs
            Controller inputs of this tick (snapshot, applied values, mode, plan).
        observed
            What this tick read from the snapshot.
        outside
            Raw outside temperature, in °C.
        outlet
            Water outlet temperature, in °C.
        outside_f
            Filtered outside temperature, in °C.
        """
        cfg = self.config
        now = inputs.now.monotonic
        dt = 0.0 if previous.last_tick_at is None else max(0.0, now - previous.last_tick_at)
        plan = inputs.plan if inputs.plan is not None and inputs.plan.active(inputs.now) else None
        override = (
            inputs.override if inputs.override and inputs.override.active(inputs.now) else None
        )
        manual_setpoint = override if override and override.kind is OverrideKind.SETPOINT else None
        boost = override.value if override and override.kind is OverrideKind.BOOST else 0.0
        room_override = active_room_override(inputs.room_override, inputs.now)
        summer = cfg.summer is not None and state.summer_active
        fresh_room = inputs.room if inputs.room is not None and inputs.room.fresh else None
        check = self._crosscheck(
            state, fresh_room, inputs.snapshot, now, dt, stove=state.stove_active
        )
        room = fresh_room if check.plausible else None
        implausible = fresh_room is not None and room is None
        reference_c = stove_mode.reference_temperature(cfg, inputs.snapshot)
        entry_shift = 0.0 if plan is None else max(0.0, bounded_offset(cfg, plan)[0])
        if room_override is not None:
            entry_shift = max(0.0, room_override.value)
        stove = stove_mode.advance(cfg, state, room, override, now, reference_c, entry_shift)
        shift = room_shift(room_override, stove=stove.active, summer=summer)
        if stove.active and not state.stove_active:
            check = replace(check, since=None)
        stale = inputs.room is not None and fresh_room is None
        room_lost_at = (
            (state.room_lost_at if state.room_lost_at is not None else now)
            if stale or implausible
            else None
        )
        lost_for = 0.0 if room_lost_at is None else now - room_lost_at
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
            plan=plan_shift(
                cfg,
                plan,
                stove=stove.active,
                stove_tail=stove.blocked or stove.level_blocked,
                seen=inputs.room,
                room=room,
                summer=summer,
                room_target=shift is not None and shift.applied,
            ),
            override=override,
            room_shift=shift,
            summer=summer,
            manual_setpoint=manual_setpoint,
            boost=boost,
            seen=inputs.room,
            fresh_room=fresh_room,
            check=check,
            room=room,
            implausible=implausible,
            reference_c=reference_c,
            stove=stove,
            pi_room=None if stove.active or summer else room,
            room_lost_at=room_lost_at,
            lost_for=lost_for,
            fade=max(0.0, 1.0 - lost_for / HELD_INTEGRAL_FADE_S),
        )

    def _sum(self, state: OvenbirdState, tick: _Tick) -> _Sum:
        """Add the terms up to the continuous, safety-clamped ``pre_round`` (stages 3-4).

        Parameters
        ----------
        state
            Controller state after this tick's tracking.
        tick
            What this tick sees before any term is computed.
        """
        cfg = self.config
        raw = tick.outside if tick.curve.value is None else tick.curve.value
        curve_sp, curve = curve_term(cfg, tick.outside_f, raw, tick.curve.note)
        terms: list[Term] = [curve]
        shift = tick.plan
        applied = shift is not None and shift.paused is None and tick.pi_room is not None
        plan_room = shift.offset_k if applied and shift is not None else 0.0
        manual = tick.room_shift
        manual_room = (
            manual.offset_k
            if manual is not None and manual.applied and tick.pi_room is not None
            else 0.0
        )
        target = cfg.comfort_room_c + plan_room + manual_room
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
            summer=tick.summer,
        )
        terms.append(feedback.term)
        plan_raw, plan_w, plan_t = plan_term(cfg, shift, tick.outside_f, pi_room=tick.pi_room)
        terms.append(plan_t)
        room_raw, room_w, room_t = room_target_term(
            cfg, manual, tick.outside_f, pi_room=tick.pi_room
        )
        if room_t is not None:
            terms.append(room_t)
        boost_t = boost_term(tick.override, tick.boost)
        if boost_t is not None:
            terms.append(boost_t)
        bounds = cfg.safety.bounds(tick.outside)
        stove_value, stove_t = stove_mode.stove_term(
            cfg, tick.stove, tick.room, tick.reference_c, curve_sp, bounds, tick.now
        )
        if stove_t is not None:
            terms.append(stove_t)
        pre_summer = curve_sp + feedback.u + plan_w + room_w + tick.boost + stove_value
        summer_value, summer_t = summer_term(
            cfg.summer, tick.summer, state.summer_mean_c, pre_summer, bounds
        )
        if summer_t is not None:
            terms.append(summer_t)
        base = pre_summer + summer_value
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
            room_raw=room_raw,
            room_w=room_w,
            stove_value=stove_value,
            summer_value=summer_value,
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
        """Turn ``pre_round`` into the issued integer setpoint (stages 5-6) and its binding.

        Parameters
        ----------
        previous
            State before this tick's tracking.
        state
            Controller state after this tick's tracking.
        inputs
            Controller inputs of this tick (snapshot, applied values, mode, plan).
        tick
            What this tick sees before any term is computed.
        total
            Summed terms of this tick.
        """
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
                total.plan_w + total.room_w,
                total.plan_raw + total.room_raw,
            )
        changed = reference is None or final != reference
        last_change_at = tick.now if changed else previous.last_change_at
        return _Setpoint(final, binding, integer_clamp, reference, dwell, last_change_at)

    def _integrator(
        self, state: OvenbirdState, tick: _Tick, total: _Sum, setpoint: _Setpoint
    ) -> tuple[float, list[str], float | None]:
        """Advance the integrator (stage 7).

        Parameters
        ----------
        state
            Controller state after this tick's tracking.
        tick
            What this tick sees before any term is computed.
        total
            Summed terms of this tick.
        setpoint
            Issued setpoint of this tick.

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
            summer=tick.summer,
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
            stove=tick.stove.active or tick.summer,
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
        """Build the decision record (flip distance, controller state, note) of the tick.

        Parameters
        ----------
        new_state
            State after this tick.
        state
            Controller state after this tick's tracking.
        inputs
            Controller inputs of this tick (snapshot, applied values, mode, plan).
        observed
            What this tick read from the snapshot.
        tick
            What this tick sees before any term is computed.
        total
            Summed terms of this tick.
        setpoint
            Issued setpoint of this tick.
        frozen_by
            What froze the integrator.
        reason
            Reason code of the decision.
        intents
            Intents issued by the decision.
        """
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
        extra |= self._manual_extra(tick)
        extra |= self._summer_extra(tick)
        if cfg.quiet_start is not None:
            extra["quiet_start"] = self._quiet_window(state, inputs)
        if not cfg.weather_compensation:
            extra["base"] = "fixed"
        if cfg.outside is not None:
            extra["outside_source"] = str(tick.curve.source)
            extra["outside_fallback"] = tick.curve.fallback
            extra["outside_reason"] = None if tick.curve.reason is None else tick.curve.reason.value
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
            NoteInputs(
                curve_sp=total.curve_sp,
                outside_f=tick.outside_f,
                final=final,
                reference=setpoint.reference,
                binding=binding,
                pre_clamp=total.pre_clamp,
                pre_round=total.pre_round,
                fixed=not cfg.weather_compensation,
                summer=self._summer_sentence(state, tick, total),
                stove=stove,
                room=pi_room,
                error=feedback.error,
                pi_k=feedback.u,
                status=feedback.status if on_change else None,
                implausible=tick.implausible,
                held_offset=feedback.held_offset,
                defrost=tick.defrost,
                dhw=tick.dhw,
                duty_skipped=tick.defrost and cfg.pump_duty is not None,
                plan=plan_clause(tick.plan, total.plan_w),
                room_target=room_target_clause(tick.room_shift, total.room_w),
                boost=tick.boost,
                ramp_k=ramp.value,
                ramp_cap_c=ramp.cap,
                floor_c=floor.floor,
                cycling_lift_k=floor.cycling,
                integer_clamp=setpoint.integer_clamp,
                dwell_left_s=dwell_left,
            )
        )
        return self._record(
            new_state,
            inputs,
            observed,
            ladder=_ladder(None if tick.plan is None else tick.plan.applied, tick.room),
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

    @staticmethod
    def _manual_extra(tick: _Tick) -> dict[str, StateValue]:
        """Return the manual room target's entries of the controller state (none without one)."""
        shift = tick.room_shift
        if shift is None:
            return {}
        return {
            "room_override": shift.override.kind.value,
            "room_override_k": shift.offset_k,
            "room_override_paused": None if shift.paused is None else shift.paused.value,
        }

    def _summer_extra(self, tick: _Tick) -> dict[str, StateValue]:
        """Return the summer switch's entries of the controller state (none without it)."""
        sc = self.config.summer
        if sc is None:
            return {}
        return {
            "summer_state": "active" if tick.summer else "inactive",
            "summer_off_c": sc.off_c,
            "summer_on_c": sc.on_c,
            "summer_mean_tau_s": sc.mean_tau_s,
        }

    def _summer_sentence(self, state: OvenbirdState, tick: _Tick, total: _Sum) -> str | None:
        """Return the first sentence of the decision note while the summer switch is on."""
        sc = self.config.summer
        if sc is None or not tick.summer or state.summer_mean_c is None:
            return None
        return (
            f"Summer switch: slow outside mean {state.summer_mean_c:.1f} °C above "
            f"{sc.off_c:g} °C, so no space heating is requested: the curve's "
            f"{total.curve_sp:.1f} °C goes down to the safety minimum {total.bounds.low:.1f} °C, "
            f"room PI paused with the integrator held at {signed(state.integral_k)} K"
        )

    def _quiet_window(self, state: OvenbirdState, inputs: ControlInputs) -> bool:
        """Whether the tick lies in the quiet window after a compressor start."""
        qs = self.config.quiet_start
        started = state.run_started_at
        if qs is None or state.running is not True or started is None:
            return False
        return inputs.now.monotonic - started < qs.duration_s

    def _quiet(
        self, state: OvenbirdState, inputs: ControlInputs, observed: _Observed
    ) -> tuple[int | None, ReasonCode]:
        """Return the desired quiet level and its reason (``None``: no quiet intent).

        The schedule's level, or within the window after a compressor start the quieter
        of it and the start level; during a defrost the previous level is kept.
        """
        cfg = self.config
        scheduled = cfg.quiet.level_at(inputs.now.wall) if cfg.quiet is not None else None
        qs = cfg.quiet_start
        if qs is None:
            return scheduled, ReasonCode.QUIET_SCHEDULE
        base = scheduled or 0
        level = max(base, qs.level) if self._quiet_window(state, inputs) else base
        if observed.defrost is True and state.quiet_level is not None:
            level = state.quiet_level
        return level, ReasonCode.QUIET_START if level > base else ReasonCode.QUIET_SCHEDULE

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

        Parameters
        ----------
        state
            Controller state after this tick's tracking.
        room
            Trusted room value, ``None`` when unusable.
        snapshot
            Current signal snapshot.
        now
            Monotonic time of this tick, in s.
        dt
            Time since the previous tick, in s.
        stove
            A wood-stove episode was active at the previous tick.
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
        """Return the room-related flat controller-state entries of the record.

        Parameters
        ----------
        room
            Trusted room value, ``None`` when unusable.
        authority
            Feedback authority of the room value, 0 to 1.
        check
            Outcome of the plausibility cross-check.
        implausible
            The room value failed the plausibility cross-check.
        stove
            A wood-stove episode is active.
        """
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

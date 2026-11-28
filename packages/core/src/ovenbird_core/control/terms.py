"""The terms of the ovenbird water setpoint, one function per term (pipeline stage 3-4).

Each function returns its contribution before and after its own clamp together with
the :class:`~ovenbird_core.control.record.Term` that records it. The controller adds
them in the order of :data:`~ovenbird_core.control.notes.TERMS`; the ``stove`` term
lives in :mod:`ovenbird_core.control.stove`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from ovenbird_core.control.config import OvenbirdConfig, SummerConfig
from ovenbird_core.control.curve import room_offset_to_water
from ovenbird_core.control.notes import SECONDS_PER_HOUR, duration_text, kept, room_status, signed
from ovenbird_core.control.record import Term
from ovenbird_core.control.safety import SafetyBounds
from ovenbird_core.control.state import OvenbirdState, RampPhase
from ovenbird_core.control.types import Override, OverrideKind, PlanSlice, PlanSource, RoomInput
from ovenbird_core.instant import Instant

HELD_INTEGRAL_FADE_S: Final = 24 * 3600.0


class PlanPause(StrEnum):
    """Why an active plan slice has no effect this tick."""

    STOVE = "stove"
    STOVE_TAIL = "stove_tail"
    SUMMER = "summer"
    ROOM_TARGET = "room_target"
    ROOM_UNTRUSTED = "room_untrusted"


PLAN_PAUSE_NOTES: Final = {
    PlanPause.STOVE: "paused by wood-stove mode",
    PlanPause.STOVE_TAIL: (
        "paused: the room is still warm after a wood-stove episode (until it has cooled "
        "below the stove's exit threshold)"
    ),
    PlanPause.SUMMER: "paused by the summer switch",
    PlanPause.ROOM_TARGET: "paused: a manual room target or away is active",
    PlanPause.ROOM_UNTRUSTED: "paused: room value not trusted",
}
ROOM_KINDS: Final = frozenset({OverrideKind.ROOM_TARGET, OverrideKind.AWAY})
ROOM_LABELS: Final = {OverrideKind.ROOM_TARGET: "manual room target", OverrideKind.AWAY: "away"}


@dataclass(frozen=True, slots=True)
class PlanShift:
    """The active plan slice of one tick after its bound, and whether it applies.

    Parameters
    ----------
    slice
        The active slice as the planner sent it.
    offset_k
        Its room offset within the bound (a rule slice is clamped to
        ``plan_rule_max_k``; an optimiser slice is not).
    limit_k
        The bound applied (``None`` for an optimiser slice).
    paused
        Why it has no effect this tick (``None``: it applies).
    """

    slice: PlanSlice
    offset_k: float
    limit_k: float | None
    paused: PlanPause | None = None

    @property
    def clamped(self) -> bool:
        """Whether the bound cut the slice's offset."""
        return self.offset_k != self.slice.room_offset_k

    @property
    def applied(self) -> PlanSlice | None:
        """The slice when it applies this tick, else ``None``."""
        return self.slice if self.paused is None else None

    def clamp_text(self) -> str:
        """Return the clause that tells a clamped slice apart (empty when not clamped)."""
        if not self.clamped or self.limit_k is None:
            return ""
        return f" (slice {signed(self.slice.room_offset_k)} K clamped to ±{self.limit_k:g} K)"


def bounded_offset(cfg: OvenbirdConfig, plan: PlanSlice) -> tuple[float, float | None]:
    """Return a slice's room offset within the rule bound, and the bound applied.

    A rule slice is clamped to ``±plan_rule_max_k`` whatever the planner sent; an
    optimiser slice keeps its offset (bound ``None``).
    """
    if plan.source is PlanSource.RULE:
        return clamp(plan.room_offset_k, cfg.plan_rule_max_k), cfg.plan_rule_max_k
    return plan.room_offset_k, None


def plan_shift(
    cfg: OvenbirdConfig,
    plan: PlanSlice | None,
    *,
    stove: bool,
    stove_tail: bool,
    seen: RoomInput | None,
    room: RoomInput | None,
    summer: bool = False,
    room_target: bool = False,
) -> PlanShift | None:
    """Return the tick's active plan slice after its bound, paused where it may not act.

    Parameters
    ----------
    cfg
        Controller configuration.
    plan
        The slice active at this tick (``None`` without one).
    stove
        A wood-stove episode is active.
    stove_tail
        The stove detection waits for the room to cool below its exit threshold after
        an episode (the cap or a manual stop ended it while the room was still warm).
    seen
        The room input as received (``None`` without a room sensor).
    room
        The trusted room value (fresh and plausible).
    summer
        The summer switch is on.
    room_target
        A manual room target or away applies this tick (it replaces the plan).

    Returns
    -------
    PlanShift or None
        ``None`` without an active slice. A slice is paused during an episode, in its
        tail, while the summer switch is on, while a manual room target applies and
        while a room sensor exists but its value is not trusted; without a room sensor
        it applies (mapped to water by :func:`plan_term`).
    """
    if plan is None:
        return None
    offset, limit = bounded_offset(cfg, plan)
    paused: PlanPause | None = None
    if stove:
        paused = PlanPause.STOVE
    elif stove_tail:
        paused = PlanPause.STOVE_TAIL
    elif summer:
        paused = PlanPause.SUMMER
    elif room_target:
        paused = PlanPause.ROOM_TARGET
    elif seen is not None and room is None:
        paused = PlanPause.ROOM_UNTRUSTED
    return PlanShift(plan, offset, limit, paused)


def plan_clause(shift: PlanShift | None, plan_w: float) -> str | None:
    """Return the plan's clause of the decision note (``None`` without an active slice)."""
    if shift is None:
        return None
    if shift.paused is not None:
        return f"plan {signed(shift.slice.room_offset_k)} K room {PLAN_PAUSE_NOTES[shift.paused]}"
    return f"plan {signed(shift.offset_k)} K room{shift.clamp_text()} ({signed(plan_w)} K water)"


@dataclass(frozen=True, slots=True)
class Feedback:
    """The room feedback of one tick.

    Parameters
    ----------
    error
        Room target minus room value (``None`` without a trusted room value).
    e_int
        Error the integrator sees (one sensor step less, see the dead zone).
    authority
        Cooling authority of the room value.
    status
        One-line state of the room value for the notes.
    u_raw, u_lim, u
        PI output before the clamp, after it, and after the cooling authority.
    held_offset
        Offset kept (fading) while the room value is stale or implausible
        (:func:`held_offset`).
    term
        The ``room_feedback`` term.
    """

    error: float | None
    e_int: float
    authority: float
    status: str | None
    u_raw: float
    u_lim: float
    u: float
    held_offset: float
    term: Term


@dataclass(frozen=True, slots=True)
class Ramp:
    """The start ramp of one tick: its phase and cap carried on, and its term."""

    phase: RampPhase
    cap: float | None
    raw: float
    value: float
    term: Term


@dataclass(frozen=True, slots=True)
class Floor:
    """The cycling floor of one tick (``floor`` is ``None`` outside the min-run window)."""

    floor: float | None
    cycling: float
    term: Term


def clamp(value: float, limit: float) -> float:
    """Clamp ``value`` to ``[-limit, limit]``."""
    return min(max(value, -limit), limit)


def curve_term(
    cfg: OvenbirdConfig, outside_f: float, outside: float, source: str | None = None
) -> tuple[float, Term]:
    """Return the base water setpoint (curve or fixed) and its term.

    The term keeps the name ``curve`` in both cases; its note says which applies and,
    with a chosen outside sensor, where the raw value came from (``source``).

    Parameters
    ----------
    cfg
        Controller configuration.
    outside_f
        Filtered outside temperature, in °C.
    outside
        Raw outside temperature, in °C.
    source
        Name of the chosen outside sensor, ``None`` for the pump's own.
    """
    curve_sp = cfg.base_water(outside_f)
    if cfg.weather_compensation:
        raw = f"{outside:g} °C raw" if source is None else f"{outside:g} °C raw {source}"
        note = f"curve at {outside_f:.2f} °C filtered outside ({raw})"
    else:
        note = "fixed water temperature (weather-dependent control off)"
    return curve_sp, Term("curve", curve_sp, curve_sp, "°C", note)


def held_offset(cfg: OvenbirdConfig, state: OvenbirdState, room: RoomInput) -> float:
    """Return the offset over the curve kept while the room value is not trusted.

    The positive integrator plus the proportional part of one sensor step, the
    latter at most ``held_step_max_k`` and the sum at most the feedback clamp.
    Inside the integrator's dead zone the P part carries the room by up to
    ``kp * quantum_k``, which the integrator alone misses; without a room value
    the loop is open and cannot see the room drifting low, so the estimate takes
    the warm edge of that band. The bound keeps a coarse sensor's step (up to
    2 K) from turning into a large bias: 0.4 K water is about 0.15-0.2 K room
    through the curve, and the mean P part measured inside the dead zone stayed
    within ±0.45 K. It is a constant, never integrated.
    """
    fb = cfg.feedback
    step = min(fb.held_step_max_k, fb.kp * room.quantum_k)
    return min(fb.output_limit_k, state.held_integral_k + step)


def room_feedback(
    cfg: OvenbirdConfig,
    state: OvenbirdState,
    target: float,
    *,
    stove: bool,
    room: RoomInput | None,
    fresh_room: RoomInput | None,
    implausible: bool,
    deviation: float | None,
    seen: RoomInput | None,
    fade: float,
    lost_for: float,
    summer: bool = False,
) -> Feedback:
    """Return the room feedback (PI) of one tick (see the room value guards).

    ``room`` is the trusted room value, ``fresh_room`` the fresh one (implausible or
    not) and ``seen`` the room input as received (possibly stale). While the summer
    switch is on the feedback is paused with its integrator held, as in wood-stove mode.

    Parameters
    ----------
    cfg
        Controller configuration.
    state
        Controller state after tracking.
    target
        Room target, in °C.
    stove
        A wood-stove episode is active.
    room
        Trusted room value, ``None`` when unusable.
    fresh_room
        Fresh room value, plausible or not.
    implausible
        The room value failed the plausibility cross-check.
    deviation
        Deviation found by the cross-check, in K, if any.
    seen
        Room input as received, possibly stale.
    fade
        Share of the held integral still kept after the value was lost, 0 to 1.
    lost_for
        Time the room value has been unusable, in s.
    summer
        The summer switch is on.
    """
    fb = cfg.feedback
    error: float | None = None
    e_int = 0.0
    authority = 1.0
    status: str | None = None
    u_raw = u_lim = u = 0.0
    held = 0.0
    if stove:
        fb_note = f"paused by wood-stove mode; integrator held at {signed(state.integral_k)} K"
        if room is not None:
            status = room_status(room, cfg.room.authority(room.held_s, room.age))
            fb_note += f"; {status}"
    elif summer:
        fb_note = f"paused by the summer switch; integrator held at {signed(state.integral_k)} K"
        if room is not None:
            status = room_status(room, cfg.room.authority(room.held_s, room.age))
            fb_note += f"; {status}"
    elif room is not None:
        error = target - room.value
        e_int = math.copysign(max(0.0, abs(error) - room.quantum_k), error)
        authority = cfg.room.authority(room.held_s, room.age)
        u_raw = fb.kp * error + state.integral_k
        u_lim = clamp(u_raw, fb.output_limit_k)
        if u_lim < 0.0:
            u = u_lim * authority + (1.0 - authority) * held_offset(cfg, state, room)
        else:
            u = u_lim
        status = room_status(room, authority, cooling=u_lim < 0.0)
        fb_note = (
            f"room {room.value:.2f} °C vs target {target:.2f} °C: "
            f"P {signed(fb.kp * error)} K + I {signed(state.integral_k)} K; {status}"
        )
    elif implausible and fresh_room is not None:
        held = held_offset(cfg, state, fresh_room) * fade
        u_raw = u_lim = u = held
        fb_note = (
            f"room value {fresh_room.value:.1f} °C implausible: {cfg.room.crosscheck} "
            f"disagrees by {signed(deviation or 0.0)} K after its learned offset; "
            f"feedback off{kept(held, lost_for, 'implausible', HELD_INTEGRAL_FADE_S)}"
        )
    elif seen is not None:
        held = held_offset(cfg, state, seen) * fade
        u_raw = u_lim = u = held
        fb_note = (
            f"room sensor {seen.source} stale (last proof of life "
            f"{duration_text(seen.age)} ago); feedback off"
            f"{kept(held, lost_for, 'stale', HELD_INTEGRAL_FADE_S)}"
        )
    else:
        fb_note = "no room sensor; feedback off (curve only)"
    term = Term("room_feedback", u_raw, u, "K", fb_note)
    return Feedback(error, e_int, authority, status, u_raw, u_lim, u, held, term)


def plan_term(
    cfg: OvenbirdConfig,
    shift: PlanShift | None,
    outside_f: float,
    *,
    pi_room: RoomInput | None,
) -> tuple[float, float, Term]:
    """Return the plan's water offset before and after its clamp, and its term.

    With an active room PI the bounded slice shifts the room target instead (no water
    offset); a paused slice has no effect; without a room sensor the bounded offset
    maps to water through the curve slope, clamped to ``plan_max_water_k``.

    Parameters
    ----------
    cfg
        Controller configuration.
    shift
        Plan's bounded room shift, ``None`` without a plan.
    outside_f
        Filtered outside temperature, in °C.
    pi_room
        Room value driving the feedback, ``None`` without one.
    """
    plan_raw = plan_w = 0.0
    if shift is None:
        plan_note = "no plan"
    elif shift.paused is not None:
        plan_note = PLAN_PAUSE_NOTES[shift.paused]
    elif pi_room is not None:
        plan_note = f"shifts room target by {signed(shift.offset_k)} K{shift.clamp_text()}"
    else:
        plan_raw = room_offset_to_water(cfg.curve, outside_f, shift.offset_k)
        plan_w = clamp(plan_raw, cfg.plan_max_water_k)
        plan_note = (
            f"room offset {signed(shift.offset_k)} K mapped via curve slope "
            f"{cfg.curve.sensitivity(outside_f):.2f}{shift.clamp_text()}"
        )
    return plan_raw, plan_w, Term("plan", plan_raw, plan_w, "K", plan_note)


@dataclass(frozen=True, slots=True)
class RoomShift:
    """The tick's manual room target (a boost, a cooler room or away) and whether it applies.

    Parameters
    ----------
    override
        The active ``room_target`` or ``away`` override; its value is the shift of the
        comfort room target in K.
    paused
        Why it has no effect this tick (``None``: it applies).
    """

    override: Override
    paused: PlanPause | None = None

    @property
    def offset_k(self) -> float:
        """The shift of the comfort room target in K."""
        return self.override.value

    @property
    def applied(self) -> bool:
        """Whether the shift applies this tick."""
        return self.paused is None

    @property
    def label(self) -> str:
        """What the decision note calls it (``manual room target`` or ``away``)."""
        return ROOM_LABELS[self.override.kind]


def active_room_override(override: Override | None, now: Instant) -> Override | None:
    """Return ``override`` when it is a room-target kind active at ``now``, else ``None``."""
    if override is None or override.kind not in ROOM_KINDS or not override.active(now):
        return None
    return override


def room_shift(override: Override | None, *, stove: bool, summer: bool) -> RoomShift | None:
    """Return the tick's manual room target, paused during a wood-stove episode or summer."""
    if override is None:
        return None
    paused: PlanPause | None = None
    if stove:
        paused = PlanPause.STOVE
    elif summer:
        paused = PlanPause.SUMMER
    return RoomShift(override, paused)


def room_target_term(
    cfg: OvenbirdConfig,
    shift: RoomShift | None,
    outside_f: float,
    *,
    pi_room: RoomInput | None,
) -> tuple[float, float, Term | None]:
    """Return the manual room target's water offset before and after its clamp, and its term.

    With an active room PI the shift moves the room target instead (no water offset); a
    paused shift has no effect; without a trusted room value the shift maps to water
    through the curve slope, clamped to ``plan_max_water_k`` (as a plan slice does).

    Parameters
    ----------
    cfg
        Controller configuration.
    shift
        Manual room-target shift, ``None`` without one.
    outside_f
        Filtered outside temperature, in °C.
    pi_room
        Room value driving the feedback, ``None`` without one.
    """
    if shift is None:
        return 0.0, 0.0, None
    raw = water = 0.0
    who = f"{shift.label} {signed(shift.offset_k)} K by {shift.override.actor}"
    if shift.paused is not None:
        note = f"{who} {PLAN_PAUSE_NOTES[shift.paused]}"
    elif pi_room is not None:
        note = f"{who}: shifts the room target"
    else:
        raw = room_offset_to_water(cfg.curve, outside_f, shift.offset_k)
        water = clamp(raw, cfg.plan_max_water_k)
        note = f"{who}: mapped via curve slope {cfg.curve.sensitivity(outside_f):.2f}"
    return raw, water, Term("room_target", raw, water, "K", note)


def room_target_clause(shift: RoomShift | None, water: float) -> str | None:
    """Return the manual room target's clause of the decision note (``None`` without one)."""
    if shift is None:
        return None
    if shift.paused is not None:
        return f"{shift.label} {signed(shift.offset_k)} K room {PLAN_PAUSE_NOTES[shift.paused]}"
    if water:
        return f"{shift.label} {signed(shift.offset_k)} K room ({signed(water)} K water)"
    return f"{shift.label} {signed(shift.offset_k)} K room"


def summer_term(
    summer: SummerConfig | None,
    active: bool,
    mean_c: float | None,
    pre_summer: float,
    bounds: SafetyBounds,
) -> tuple[float, Term | None]:
    """Return the summer switch's water offset and its term (``None`` without the switch).

    While on, the offset takes the sum of the terms before it down to the safety
    minimum ``bounds.low`` (never up): ovenbird never switches the pump off, "no space
    heating" is the lowest allowed setpoint, as wood-stove mode's ``to_minimum``.

    Parameters
    ----------
    summer
        Summer switch configuration, ``None`` without the switch.
    active
        Whether the switch is currently on.
    mean_c
        Slow outside mean, in °C, if known.
    pre_summer
        Sum of the terms before this one, in °C.
    bounds
        Safety envelope at the current outside temperature.
    """
    if summer is None:
        return 0.0, None
    mean = "unknown" if mean_c is None else f"{mean_c:.1f} °C"
    if not active:
        note = f"inactive (slow outside mean {mean}; heating off above {summer.off_c:g} °C)"
        return 0.0, Term("summer", 0.0, 0.0, "K", note)
    value = min(0.0, bounds.low - pre_summer)
    note = (
        f"no space heating: slow outside mean {mean} above {summer.off_c:g} °C (resumes "
        f"below {summer.on_c:g} °C); water to the safety minimum {bounds.low:.1f} °C"
    )
    return value, Term("summer", value, value, "K", note)


def boost_term(override: Override | None, boost: float) -> Term | None:
    """Return the ``boost`` term while a boost override is active."""
    if override is not None and override.kind is OverrideKind.BOOST:
        return Term("boost", boost, boost, "K", f"boost by {override.actor}")
    return None


def start_ramp(
    cfg: OvenbirdConfig,
    state: OvenbirdState,
    *,
    running: bool,
    defrost: bool,
    dhw: bool,
    outlet: float,
    curve_sp: float,
    base: float,
    dt: float,
) -> Ramp:
    """Return the start ramp (≤ 0): a cap tracking the outlet after a compressor start.

    The cap holds for ``hold_s`` and then rises at ``release_k_per_h``; it never
    falls below the outlet minus ``below_outlet_k`` or the curve minus
    ``max_below_curve_k``, and is frozen during defrost and DHW. The ramp ends once
    the cap is no longer below ``base``.

    Parameters
    ----------
    cfg
        Controller configuration.
    state
        Controller state after tracking.
    running
        The compressor runs.
    defrost
        The heat pump is defrosting.
    dhw
        The heat pump is making domestic hot water.
    outlet
        Water outlet temperature, in °C.
    curve_sp
        Curve setpoint, in °C.
    base
        Sum of the terms before the ramp, in °C.
    dt
        Time since the previous tick, in s.
    """
    phase, cap = state.ramp_phase, state.ramp_cap
    ramp_raw = ramp = 0.0
    ramp_note = "no ramp"
    if phase is not RampPhase.IDLE and running:
        rc = cfg.ramp
        floor_curve = curve_sp - rc.max_below_curve_k
        track = outlet - rc.below_outlet_k
        phase = RampPhase.RELEASE if state.ramp_elapsed_s >= rc.hold_s else RampPhase.HOLD
        if defrost or dhw:
            cap = cap if cap is not None else max(track, floor_curve)
        else:
            candidates = [track, floor_curve]
            if cap is not None:
                rise = rc.release_k_per_h * dt / SECONDS_PER_HOUR
                candidates.append(cap + (rise if phase is RampPhase.RELEASE else 0.0))
            cap = max(candidates)
        ramp_raw = cap - base
        if ramp_raw >= 0.0:
            phase, cap = RampPhase.IDLE, None
            ramp_note = "ramp released"
        else:
            ramp = ramp_raw
            ramp_note = (
                f"{phase.value} phase, cap {cap:.2f} °C ({state.ramp_elapsed_s / 60:.0f} min run)"
            )
    term = Term("start_ramp", ramp_raw, ramp, "K", ramp_note)
    return Ramp(phase, cap, ramp_raw, ramp, term)


def override_term(manual_setpoint: Override, raw_sum: float) -> Term:
    """Return the ``override`` term replacing the sum by a manual setpoint."""
    return Term(
        "override",
        manual_setpoint.value - raw_sum,
        manual_setpoint.value - raw_sum,
        "K",
        f"setpoint {manual_setpoint.value:g} °C by {manual_setpoint.actor}",
    )


def cycling_floor(
    cfg: OvenbirdConfig,
    state: OvenbirdState,
    now: float,
    *,
    manual: bool,
    running: bool,
    defrost: bool,
    dhw: bool,
    outlet: float,
    base: float,
    raw_sum: float,
) -> Floor:
    """Return the cycling floor (≥ 0) inside the compressor's minimum-run window.

    Parameters
    ----------
    cfg
        Controller configuration.
    state
        Controller state after tracking.
    now
        Monotonic time of this tick, in s.
    manual
        A manual setpoint is active.
    running
        The compressor runs.
    defrost
        The heat pump is defrosting.
    dhw
        The heat pump is making domestic hot water.
    outlet
        Water outlet temperature, in °C.
    base
        Sum of the terms before the floor, in °C.
    raw_sum
        Sum of all terms before the floor, in °C.
    """
    floor: float | None = None
    cycling = 0.0
    cc = cfg.cycling
    if (
        cc.enabled
        and not manual
        and running
        and not defrost
        and not dhw
        and state.run_started_at is not None
        and now - state.run_started_at < cc.min_run_s
    ):
        floor = min(outlet - cc.stop_delta_k + cc.margin_k, base + cc.max_raise_k)
        cycling = max(0.0, floor - raw_sum)
        cyc_note = f"min-run window: keep ≥ {floor:.2f} °C (outlet {outlet:g} °C)"
    else:
        cyc_note = "outside min-run window"
    term = Term("cycling_floor", 0.0 if floor is None else floor - raw_sum, cycling, "K", cyc_note)
    return Floor(floor, cycling, term)


def safety_term(bounds: SafetyBounds, pre_clamp: float, outside: float) -> tuple[float, Term]:
    """Return the continuous value clamped to the safety envelope (``pre_round``) and its term."""
    pre_round = bounds.clamp(pre_clamp)
    note = f"allowed [{bounds.low:.2f}, {bounds.high:.2f}] °C at {outside:g} °C outside"
    return pre_round, Term("safety", pre_clamp, pre_round, "°C", note)

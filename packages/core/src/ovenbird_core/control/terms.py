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
from typing import TYPE_CHECKING, Final

from ovenbird_core.control.config import OvenbirdConfig
from ovenbird_core.control.curve import room_offset_to_water
from ovenbird_core.control.notes import SECONDS_PER_HOUR, duration_text, kept, room_status, signed
from ovenbird_core.control.record import Term
from ovenbird_core.control.safety import SafetyBounds
from ovenbird_core.control.types import (
    ModelPlanBlock,
    Override,
    OverrideKind,
    PlanSlice,
    PlanSource,
    RoomInput,
)

if TYPE_CHECKING:
    from ovenbird_core.control.ovenbird import OvenbirdState

HELD_INTEGRAL_FADE_S: Final = 24 * 3600.0
MODEL_BLOCK_TEXT: Final[dict[ModelPlanBlock, str]] = {
    ModelPlanBlock.ROOM_UNTRUSTED: "no trusted room value (a model plan never maps to water)",
    ModelPlanBlock.STOVE_ACTIVE: "wood-stove episode active",
    ModelPlanBlock.STOVE_RECOVERY: "wood-stove recovery (the detection has not re-armed yet)",
    ModelPlanBlock.SLICE_TOO_LONG: "slice longer than a model slice may be",
}
MODEL_WATER_BLOCK_TEXT: Final[dict[ModelPlanBlock, str]] = {
    **MODEL_BLOCK_TEXT,
    ModelPlanBlock.ROOM_UNTRUSTED: "no trusted room value to judge its authority by",
}


class RampPhase(StrEnum):
    """Phase of the start ramp."""

    IDLE = "idle"
    HOLD = "hold"
    RELEASE = "release"


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
class ModelPlan:
    """An active model plan slice of one tick (``PlanSource.MODEL``).

    Parameters
    ----------
    requested_k
        Room offset the planner sent.
    applied_k
        Room offset applied to the room target: ``requested_k`` clamped to the model
        bounds, ``0`` while ``block`` is set.
    block
        Why the slice has no effect this tick (``None``: it applies).
    water_requested_k
        Water offset the planner sent (``0`` on a room-target slice).
    water_applied_k
        Water offset applied: ``water_requested_k`` clamped to the model water bounds
        and scaled by ``authority``; ``0`` while ``block`` is set.
    authority
        Room authority of a water slice (``None`` on a room-target slice or while
        ``block`` is set).
    """

    requested_k: float
    applied_k: float
    block: ModelPlanBlock | None
    water_requested_k: float = 0.0
    water_applied_k: float = 0.0
    authority: float | None = None

    @property
    def water(self) -> bool:
        """Whether the slice is a water slice."""
        return self.water_requested_k != 0.0

    @property
    def clamped(self) -> bool:
        """Whether the bounds cut the requested offset."""
        return self.block is None and self.applied_k != self.requested_k

    def ignored_text(self) -> str | None:
        """Return why the slice is ignored, for the notes (``None`` when it applies)."""
        if self.block is None:
            return None
        if self.water:
            return (
                f"model plan {signed(self.water_requested_k)} K water ignored: "
                f"{MODEL_WATER_BLOCK_TEXT[self.block]}"
            )
        return f"model plan {signed(self.requested_k)} K ignored: {MODEL_BLOCK_TEXT[self.block]}"

    def water_text(self) -> str:
        """Return what became of a water slice, for the notes."""
        asked = signed(self.water_requested_k)
        if self.block is not None:
            return self.ignored_text() or ""
        if self.water_applied_k == 0.0 and self.authority == 0.0:
            return f"model plan {asked} K water has no effect: room authority 0 % (room cool)"
        if self.water_applied_k == 0.0:
            return f"model plan {asked} K water cut to 0 by the model water bounds"
        text = f"model plan {signed(self.water_applied_k)} K water for the forecast sun"
        details: list[str] = []
        if self.authority is not None and self.authority < 1.0:
            details.append(f"room authority {math.floor(self.authority * 100):.0f} %")
        if self.water_applied_k != self.water_requested_k:
            details.append(f"asked {self.water_requested_k:+.2f} K")
        return f"{text} ({', '.join(details)})" if details else text


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
) -> Feedback:
    """Return the room feedback (PI) of one tick (see the room value guards).

    ``room`` is the trusted room value, ``fresh_room`` the fresh one (implausible or
    not) and ``seen`` the room input as received (possibly stale).
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
    plan: PlanSlice | None,
    outside_f: float,
    *,
    stove: bool,
    pi_room: RoomInput | None,
    model: ModelPlan | None = None,
) -> tuple[float, float, Term]:
    """Return the plan's water offset before and after its clamp, and its term.

    With an active room PI the plan shifts the room target instead (no water offset).
    A model plan (``PlanSource.MODEL``) room-target slice only ever shifts the room
    target: without an active room PI it has no effect at all, and ``model`` says why
    it was ignored or whether its bounds cut it. A model water slice adds its applied
    water offset (bounded, scaled by the room authority); the term's raw value is the
    offset the planner asked for.
    """
    plan_raw = plan_w = 0.0
    ignored = None if model is None else model.ignored_text()
    if model is not None and model.water:
        plan_note = model.water_text()
        if plan is not None and model.block is None:
            plan_raw, plan_w = model.water_requested_k, plan.water_offset_k
    elif ignored is not None:
        plan_note = ignored
    elif plan is None and model is not None:
        plan_note = f"model plan {signed(model.requested_k)} K cut to 0 by the model bounds"
    elif plan is None:
        plan_note = "no plan"
    elif plan.source is PlanSource.MODEL:
        if stove or pi_room is None:
            plan_note = "model plan ignored: no active room feedback"
        else:
            plan_note = f"model plan shifts room target by {signed(plan.room_offset_k)} K"
            if model is not None and model.clamped:
                plan_note += f" (asked {model.requested_k:+.2f} K, cut to the model bounds)"
    elif stove:
        plan_note = "paused by wood-stove mode"
    elif pi_room is not None:
        plan_note = f"shifts room target by {signed(plan.room_offset_k)} K"
    else:
        plan_raw = room_offset_to_water(cfg.curve, outside_f, plan.room_offset_k)
        plan_w = clamp(plan_raw, cfg.plan_max_water_k)
        plan_note = (
            f"room offset {signed(plan.room_offset_k)} K mapped via curve slope "
            f"{cfg.curve.sensitivity(outside_f):.2f}"
        )
    return plan_raw, plan_w, Term("plan", plan_raw, plan_w, "K", plan_note)


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
    """Return the cycling floor (≥ 0) inside the compressor's minimum-run window."""
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

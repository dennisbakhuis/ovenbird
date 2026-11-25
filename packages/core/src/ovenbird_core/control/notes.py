"""Explanations of an ovenbird decision: binding, reason code, flip distance and note text.

Nothing here changes a setpoint. These functions turn the numbers a tick computed
into the decision record's ``binding``, ``reason``, ``flip_distance`` and the
one-line ``note`` the UI shows.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Final

from ovenbird_core.catalogue import HeishaSignal
from ovenbird_core.control.safety import EPSILON, Bound, SafetyBounds
from ovenbird_core.control.types import (
    ControlInputs,
    PlanSlice,
    ReasonCode,
    RoomInput,
    RoomProfile,
)
from ovenbird_core.readings import SignalId

if TYPE_CHECKING:
    from ovenbird_core.control.config import OvenbirdConfig

PRE_ROUND_INPUT: Final = "pre_round"
SECONDS_PER_HOUR: Final = 3600.0
SECONDS_PER_MINUTE: Final = 60.0

HARD_HIGH: Final = frozenset({Bound.MAX_SUPPLY.value, Bound.ENVELOPE_MAX.value})

BINDINGS: Final = frozenset(
    {
        *(bound.value for bound in Bound),
        "cycling_floor",
        "defrost_hold",
        "dhw_hold",
        "dwell",
        "deadband",
        "rounding",
        "override",
        "start_ramp",
        "room_feedback_limit",
        "room_authority",
        "plan_limit",
    }
)
TERMS: Final = (
    "curve",
    "room_feedback",
    "plan",
    "boost",
    "stove",
    "start_ramp",
    "override",
    "cycling_floor",
    "safety",
)

BINDING_REASONS: Final[dict[str, ReasonCode]] = {
    Bound.MAX_SUPPLY.value: ReasonCode.SAFETY_CLAMP,
    Bound.MIN_SETPOINT.value: ReasonCode.SAFETY_CLAMP,
    Bound.ENVELOPE_MAX.value: ReasonCode.SAFETY_CLAMP,
    Bound.ENVELOPE_MIN.value: ReasonCode.SAFETY_CLAMP,
    "cycling_floor": ReasonCode.CYCLING_PROTECT,
    "defrost_hold": ReasonCode.DEFROST_FREEZE,
    "dhw_hold": ReasonCode.DHW_FREEZE,
    "dwell": ReasonCode.DWELL_HOLD,
    "deadband": ReasonCode.DEADBAND_HOLD,
    "rounding": ReasonCode.DEADBAND_HOLD,
    "override": ReasonCode.OVERRIDE,
    "start_ramp": ReasonCode.START_RAMP,
}

HOLD_EXPLANATIONS: Final[dict[str, str]] = {
    "rounding": "within rounding hysteresis",
    "deadband": "within the deadband",
    "dwell": "dwell time not over",
    "defrost_hold": "no decrease during defrost",
    "dhw_hold": "no decrease during DHW",
    "cycling_floor": "the min-run window keeps headroom to the pump's stop rule",
}


def signed(value: float) -> str:
    """Format ``value`` with an explicit sign and one decimal (``+1.2``, no ``-0.0``)."""
    return f"{round(value, 1) + 0.0:+.1f}"


def duration_text(seconds: float | None) -> str:
    """Format a duration for a decision note (``45 s``, ``4 min``, ``2 h 10 m``)."""
    if seconds is None or not math.isfinite(seconds):
        return "unknown"
    if seconds < SECONDS_PER_MINUTE:
        return f"{seconds:.0f} s"
    if seconds < SECONDS_PER_HOUR:
        return f"{seconds // SECONDS_PER_MINUTE:.0f} min"
    hours, rest = divmod(seconds, SECONDS_PER_HOUR)
    return f"{hours:.0f} h {rest // SECONDS_PER_MINUTE:02.0f} m"


def liveness_label(signal: SignalId, room: SignalId) -> str:
    """Short name of a liveness signal next to its room signal (``humidity``).

    The common prefix of the two names (``ha/sensor.living_room_``) is dropped.
    """
    name = signal.rsplit(".", 1)[-1].rsplit("/", 1)[-1]
    base = room.rsplit(".", 1)[-1].rsplit("/", 1)[-1]
    common = 0
    for a, b in zip(name, base, strict=False):
        if a != b:
            break
        common += 1
    cut = name.rfind("_", 0, common) + 1
    return name[cut:] or name


def room_status(room: RoomInput, authority: float, cooling: bool = False) -> str:
    """One-line state of the room value for decision notes.

    ``on_change`` with a liveness signal: ``held value 22.9 °C (2 h 10 m), device
    alive (humidity 4 min ago), ±0.2 K``; without one (the value was its own last
    proof of life): ``held value 22.9 °C (2 h 10 m), last report 2 h 10 m ago,
    ±0.2 K``. The cooling authority is added only when it is reduced or the
    feedback cools (``cooling``): ``, cooling authority 60 %``. ``periodic``:
    ``value 22.9 °C (4 min old), ±0.1 K``.
    """
    step = f"±{room.quantum_k:.1f} K"
    if room.profile is not RoomProfile.ON_CHANGE:
        return f"value {room.value:.1f} °C ({duration_text(room.age)} old), {step}"
    if room.alive_by is not None:
        alive = (
            f"device alive ({liveness_label(room.alive_by, room.source)} "
            f"{duration_text(room.age)} ago)"
        )
    else:
        alive = f"last report {duration_text(room.age)} ago"
    text = f"held value {room.value:.1f} °C ({duration_text(room.held_s)}), {alive}, {step}"
    if authority < 1.0 or cooling:
        text += f", cooling authority {math.floor(authority * 100):.0f} %"
    return text


def kept(held_offset: float, lost_for: float, why: str, fade_s: float) -> str:
    """Return the note fragment on the held offset (fading to zero over ``fade_s``)."""
    if held_offset <= 0.0:
        return " (curve only)"
    return (
        f" (curve only); keeps the held offset {signed(held_offset)} K (positive integrator "
        f"plus one sensor step), fading to 0 over "
        f"{fade_s / SECONDS_PER_HOUR:.0f} h ({why} for {duration_text(lost_for)})"
    )


def soft_binding(
    manual: bool,
    pre_clamp: float,
    bounds: SafetyBounds,
    cycling: float,
    ramp: float,
    u: float,
    u_lim: float,
    u_raw: float,
    plan_w: float,
    plan_raw: float,
) -> str | None:
    """Return what bound the continuous value when no stage or hard constraint did."""
    if pre_clamp > bounds.high + EPSILON:
        return bounds.high_source.value
    if pre_clamp < bounds.low - EPSILON:
        return bounds.low_source.value
    if manual:
        return "override"
    if cycling > 0.0:
        return "cycling_floor"
    if ramp < 0.0:
        return "start_ramp"
    if u != u_lim:
        return "room_authority"
    if u_lim != u_raw:
        return "room_feedback_limit"
    if plan_w != plan_raw:
        return "plan_limit"
    return None


def reason_code(
    binding: str | None,
    overridden: bool,
    plan: PlanSlice | None,
    defrost: bool,
    dhw: bool,
    room: RoomInput | None,
    inputs: ControlInputs,
    implausible: bool = False,
    *,
    stove: bool = False,
) -> ReasonCode:
    """Return the reason code of the setpoint intent (the binding first, then the mode)."""
    mapped = BINDING_REASONS.get(binding) if binding is not None else None
    if mapped is not None:
        return mapped
    if stove:
        return ReasonCode.STOVE
    if overridden:
        return ReasonCode.OVERRIDE
    if plan is not None:
        return plan.reason
    if defrost:
        return ReasonCode.DEFROST_FREEZE
    if dhw:
        return ReasonCode.DHW_FREEZE
    if room is not None:
        return ReasonCode.ROOM_FEEDBACK
    if implausible:
        return ReasonCode.ROOM_IMPLAUSIBLE
    if inputs.room is not None:
        return ReasonCode.ROOM_STALE
    return ReasonCode.CURVE


def flip_distance(
    cfg: OvenbirdConfig,
    final: int,
    pre_round: float,
    pre_clamp: float,
    bounds: SafetyBounds,
    room: RoomInput | None,
    kp: float,
    u_raw: float,
    outside_f: float,
    feedback_limited: bool = False,
) -> tuple[float, str]:
    """Distance an input must move to change the integer setpoint (dwell ignored).

    The water distance is measured from ``pre_round`` to the nearest change
    threshold around the issued setpoint. While the room feedback is active and
    unclamped it is converted to K of room temperature (``/ kp``); on the curve
    alone to K of outside temperature (``/ curve slope``); otherwise (clamped)
    it stays in K of ``pre_round``.
    """
    threshold = cfg.stages.change_threshold_k
    water = max(0.0, min(final + threshold - pre_round, pre_round - (final - threshold)))
    clamped = pre_clamp != pre_round or bounds.low_int == bounds.high_int
    if not clamped and room is not None and kp > 0.0 and not feedback_limited:
        return water / kp, room.source
    slope = cfg.base_sensitivity(outside_f)
    if not clamped and room is None and slope > 0.0:
        return water / slope, HeishaSignal.OUTSIDE_TEMP.value
    return water, PRE_ROUND_INPUT


def decision_note(
    curve_sp: float,
    outside_f: float,
    room: RoomInput | None,
    error: float | None,
    u: float,
    plan: PlanSlice | None,
    plan_w: float,
    boost: float,
    cap: float | None,
    ramp: float,
    floor: float | None,
    cycling: float,
    pre_clamp: float,
    pre_round: float,
    bounds: SafetyBounds,
    final: int,
    reference: int | None,
    binding: str | None,
    dwell_left: float,
    status: str | None = None,
    implausible: bool = False,
    *,
    defrost: bool = False,
    dhw: bool = False,
    duty_skipped: bool = False,
    integer_clamp: tuple[int, int] | None = None,
    held_offset: float = 0.0,
    stove: str | None = None,
    fixed: bool = False,
) -> str:
    """Return the decision note: what drove the water setpoint and what held or moved it."""
    parts: list[str] = []
    curve = f"the curve's {curve_sp:.1f} °C at {outside_f:.1f} °C outside"
    if fixed:
        curve = f"the fixed {curve_sp:.1f} °C (weather-dependent control off)"
    if stove is not None:
        parts.append(stove)
    elif room is not None and error is not None:
        side = "below" if error > 0 else "above"
        parts.append(f"Room {abs(error):.1f} K {side} target; PI adds {signed(u)} K to {curve}")
        if status is not None:
            parts.append(status)
    elif implausible and held_offset > 0.0:
        parts.append(
            f"Room value implausible (cross-check), so {curve} plus the held "
            f"offset {signed(held_offset)} K (fading)"
        )
    elif implausible:
        parts.append(f"Room value implausible (cross-check), so {curve} alone")
    elif held_offset > 0.0:
        parts.append(
            f"No usable room temperature, so {curve} plus the held offset "
            f"{signed(held_offset)} K (fading)"
        )
    else:
        parts.append(f"No usable room temperature, so {curve} alone")
    if defrost:
        parts.append("defrost in progress: integrator frozen, no decrease")
    if dhw:
        parts.append("DHW run in progress: integrator frozen, no decrease")
    if duty_skipped:
        parts.append("defrost: the pump sets its own duty; no duty command")
    if plan is not None:
        parts.append(f"plan {signed(plan.room_offset_k)} K room ({signed(plan_w)} K water)")
    if boost:
        parts.append(f"boost {signed(boost)} K")
    if ramp < 0.0 and cap is not None:
        parts.append(f"start ramp caps at {cap:.1f} °C")
    if binding == "cycling_floor" and floor is not None:
        if reference is not None and final <= reference:
            parts.append(f"cycling floor {floor:.1f} °C limits the decrease")
        else:
            parts.append(f"cycling floor raises to {final} °C")
    elif cycling > 0.0 and floor is not None:
        parts.append(f"min-run window lifts the target to {floor:.1f} °C")
    if pre_round != pre_clamp:
        parts.append(f"safety clamps {pre_clamp:.1f} to {pre_round:.1f} °C")
    if integer_clamp is not None:
        before, after = integer_clamp
        parts.append(f"safety bound {binding} clamps {before} → {after} °C")
    if reference is not None and final == reference and binding in HOLD_EXPLANATIONS:
        held = HOLD_EXPLANATIONS[binding]
        if binding == "dwell":
            held = f"{held} ({dwell_left / 60:.0f} min left)"
        outcome = f"setpoint stays {final} °C, {held}"
    elif reference is not None and final != reference:
        outcome = f"setpoint {reference} → {final} °C"
    else:
        outcome = f"setpoint {final} °C"
    return "; ".join(parts) + f"; {outcome}."

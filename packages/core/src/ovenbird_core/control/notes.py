"""Explanations of an ovenbird decision: binding, reason code, flip distance and note text.

Nothing here changes a setpoint. These functions turn the numbers a tick computed
into the decision record's ``binding``, ``reason``, ``flip_distance`` and the
one-line ``note`` the UI shows.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ovenbird_core.catalogue import HeishaSignal
from ovenbird_core.control.safety import EPSILON, Bound, SafetyBounds
from ovenbird_core.control.types import (
    ControlInputs,
    OverrideKind,
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
    "room_target",
    "boost",
    "stove",
    "summer",
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
    """Return the note fragment on the held offset (fading to zero over ``fade_s``).

    Parameters
    ----------
    held_offset
        The held offset in K (``0`` or less: none).
    lost_for
        Seconds since the room value was lost.
    why
        Why the room value counts as lost.
    fade_s
        Seconds over which the offset fades to zero.
    """
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
    """Return what bound the continuous value when no stage or hard constraint did.

    Parameters
    ----------
    manual
        A manual setpoint override applies.
    pre_clamp
        The continuous setpoint before the safety clamps in °C.
    bounds
        Safety bounds of this tick.
    cycling
        Lift of the min-run window in K.
    ramp
        The start ramp's term in K (negative while it caps).
    u
        Room PI output after the cooling authority in K.
    u_lim
        Room PI output after its limit in K.
    u_raw
        Room PI output before its limit in K.
    plan_w
        The plan's term after its limit in K water.
    plan_raw
        The plan's term before its limit in K water.
    """
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
    summer: bool = False,
    room_target: OverrideKind | None = None,
) -> ReasonCode:
    """Return the reason code of the setpoint intent (the binding first, then the mode).

    ``summer`` is the summer switch being on; ``room_target`` the kind of a manual room
    target that applies this tick (``room_target`` or ``away``).

    Parameters
    ----------
    binding
        What bound the setpoint, ``None`` when nothing did.
    overridden
        A manual setpoint override applies.
    plan
        The active plan slice, ``None`` without one.
    defrost
        A defrost is in progress.
    dhw
        A DHW run is in progress.
    room
        The room value the feedback used, ``None`` without one.
    inputs
        This tick's control inputs.
    implausible
        The cross-check flagged the room value.
    stove
        A wood-stove episode is active.
    summer
        The summer switch is on.
    room_target
        Kind of the manual room target that applies, ``None`` without one.
    """
    mapped = BINDING_REASONS.get(binding) if binding is not None else None
    if mapped is not None:
        return mapped
    if summer:
        return ReasonCode.SUMMER
    if stove:
        return ReasonCode.STOVE
    if overridden:
        return ReasonCode.OVERRIDE
    if room_target is OverrideKind.AWAY:
        return ReasonCode.AWAY
    if room_target is not None:
        return ReasonCode.ROOM_TARGET
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

    Parameters
    ----------
    cfg
        Controller configuration.
    final
        The integer setpoint issued this tick.
    pre_round
        The continuous setpoint after the safety clamps in °C.
    pre_clamp
        The continuous setpoint before the safety clamps in °C.
    bounds
        Safety bounds of this tick.
    room
        The room value the feedback used, ``None`` without one.
    kp
        Proportional gain of the room PI in K water per K room.
    u_raw
        Room PI output before its limit in K.
    outside_f
        Filtered outside temperature in °C.
    feedback_limited
        The room feedback was limited this tick.
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


@dataclass(frozen=True, slots=True)
class NoteInputs:
    """What one tick computed, as far as the decision note tells it.

    Parameters
    ----------
    curve_sp
        Water setpoint of the curve (or the fixed setpoint) in °C.
    outside_f
        Filtered outside temperature in °C.
    final
        The integer setpoint issued this tick.
    reference
        The setpoint a change is measured from, ``None`` without one.
    binding
        What bound the setpoint (a :data:`BINDINGS` entry), ``None`` when nothing did.
    pre_clamp, pre_round
        The continuous setpoint before and after the safety clamps.
    fixed
        Weather-dependent control is off (the curve is a fixed setpoint).
    summer
        The summer switch's sentence, ``None`` while it is off.
    stove
        The wood-stove sentence, ``None`` without an episode.
    room
        The room value the feedback used, ``None`` without one.
    error
        Room error in K (target minus room), ``None`` without feedback.
    pi_k
        What the room PI adds to the curve in K.
    status
        State of an on-change room value, ``None`` to leave it out.
    implausible
        The cross-check flagged the room value.
    held_offset
        Offset kept on the curve while the room value is lost, in K.
    defrost, dhw
        A defrost or DHW run freezes the integrator.
    duty_skipped
        No pump duty command during defrost.
    plan
        The plan's clause (:func:`~ovenbird_core.control.terms.plan_clause`), ``None``
        without an active slice.
    room_target
        The manual room target's clause, ``None`` without one.
    boost
        Boost in K (``0``: none).
    ramp_k
        The start ramp's term in K (negative while it caps).
    ramp_cap_c
        The start ramp's cap in °C, ``None`` without one.
    floor_c
        The cycling floor in °C, ``None`` without one.
    cycling_lift_k
        How far the min-run window lifts the target in K.
    integer_clamp
        The integer setpoint before and after a safety bound clamped it.
    dwell_left_s
        Seconds until the dwell time is over.
    """

    curve_sp: float
    outside_f: float
    final: int
    reference: int | None
    binding: str | None
    pre_clamp: float
    pre_round: float
    fixed: bool = False
    summer: str | None = None
    stove: str | None = None
    room: RoomInput | None = None
    error: float | None = None
    pi_k: float = 0.0
    status: str | None = None
    implausible: bool = False
    held_offset: float = 0.0
    defrost: bool = False
    dhw: bool = False
    duty_skipped: bool = False
    plan: str | None = None
    room_target: str | None = None
    boost: float = 0.0
    ramp_k: float = 0.0
    ramp_cap_c: float | None = None
    floor_c: float | None = None
    cycling_lift_k: float = 0.0
    integer_clamp: tuple[int, int] | None = None
    dwell_left_s: float = 0.0


def decision_note(note: NoteInputs) -> str:
    """Return the decision note: what drove the water setpoint and what held or moved it.

    The lead sentence, the freezes, the plan and room-target clauses, the boost, the
    start ramp, the cycling floor and the safety clamps follow each other, separated
    by ``; ``, and the outcome on the setpoint ends it.
    """
    parts = [
        *_lead_parts(note),
        *_freeze_parts(note),
        *_clause_parts(note),
        *_ramp_parts(note),
        *_floor_parts(note),
        *_clamp_parts(note),
    ]
    return "; ".join(parts) + f"; {_outcome(note)}."


def _curve_text(note: NoteInputs) -> str:
    """Return the curve as the lead sentence names it (or the fixed setpoint)."""
    if note.fixed:
        return f"the fixed {note.curve_sp:.1f} °C (weather-dependent control off)"
    return f"the curve's {note.curve_sp:.1f} °C at {note.outside_f:.1f} °C outside"


def _lead_parts(note: NoteInputs) -> list[str]:
    """Return the lead: summer, stove, room feedback (with its status) or the curve alone."""
    if note.summer is not None:
        return [note.summer]
    if note.stove is not None:
        return [note.stove]
    if note.room is not None and note.error is not None:
        return _feedback_parts(note, note.error)
    return [_without_feedback(note)]


def _feedback_parts(note: NoteInputs, error: float) -> list[str]:
    """Return the room feedback sentence and the room value's status."""
    side = "below" if error > 0 else "above"
    lead = (
        f"Room {abs(error):.1f} K {side} target; PI adds {signed(note.pi_k)} K to "
        f"{_curve_text(note)}"
    )
    return [lead] if note.status is None else [lead, note.status]


def _without_feedback(note: NoteInputs) -> str:
    """Return the lead without room feedback: implausible or no value, with a held offset."""
    curve = _curve_text(note)
    why = (
        "Room value implausible (cross-check)" if note.implausible else "No usable room temperature"
    )
    if note.held_offset > 0.0:
        return f"{why}, so {curve} plus the held offset {signed(note.held_offset)} K (fading)"
    return f"{why}, so {curve} alone"


def _freeze_parts(note: NoteInputs) -> list[str]:
    """Return the defrost, DHW and skipped-duty clauses."""
    parts = []
    if note.defrost:
        parts.append("defrost in progress: integrator frozen, no decrease")
    if note.dhw:
        parts.append("DHW run in progress: integrator frozen, no decrease")
    if note.duty_skipped:
        parts.append("defrost: the pump sets its own duty; no duty command")
    return parts


def _clause_parts(note: NoteInputs) -> list[str]:
    """Return the plan clause, the manual room target clause and the boost."""
    parts = [clause for clause in (note.plan, note.room_target) if clause is not None]
    if note.boost:
        parts.append(f"boost {signed(note.boost)} K")
    return parts


def _ramp_parts(note: NoteInputs) -> list[str]:
    """Return the start ramp's cap while it lowers the setpoint."""
    if note.ramp_k < 0.0 and note.ramp_cap_c is not None:
        return [f"start ramp caps at {note.ramp_cap_c:.1f} °C"]
    return []


def _floor_parts(note: NoteInputs) -> list[str]:
    """Return what the cycling floor or the min-run window did to the setpoint."""
    if note.floor_c is None:
        return []
    if note.binding == "cycling_floor":
        if note.reference is not None and note.final <= note.reference:
            return [f"cycling floor {note.floor_c:.1f} °C limits the decrease"]
        return [f"cycling floor raises to {note.final} °C"]
    if note.cycling_lift_k > 0.0:
        return [f"min-run window lifts the target to {note.floor_c:.1f} °C"]
    return []


def _clamp_parts(note: NoteInputs) -> list[str]:
    """Return the safety clamps of the continuous and of the integer setpoint."""
    parts = []
    if note.pre_round != note.pre_clamp:
        parts.append(f"safety clamps {note.pre_clamp:.1f} to {note.pre_round:.1f} °C")
    if note.integer_clamp is not None:
        before, after = note.integer_clamp
        parts.append(f"safety bound {note.binding} clamps {before} → {after} °C")
    return parts


def _outcome(note: NoteInputs) -> str:
    """Return the closing clause: the setpoint held (and why), changed or issued."""
    if note.reference is None:
        return f"setpoint {note.final} °C"
    if note.final != note.reference:
        return f"setpoint {note.reference} → {note.final} °C"
    if note.binding is not None and note.binding in HOLD_EXPLANATIONS:
        return f"setpoint stays {note.final} °C, {_held(note, note.binding)}"
    return f"setpoint {note.final} °C"


def _held(note: NoteInputs, binding: str) -> str:
    """Return why the setpoint holds under ``binding`` (with the dwell time left)."""
    held = HOLD_EXPLANATIONS[binding]
    if binding == "dwell":
        return f"{held} ({note.dwell_left_s / 60:.0f} min left)"
    return held

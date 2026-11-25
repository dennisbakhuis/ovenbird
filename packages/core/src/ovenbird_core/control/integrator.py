"""The room PI's integrator: freezes, anti-windup and the silent-device rollback (stage 7).

The integrator integrates only when nothing saturates in the direction of the error
(feedback clamp, safety clamp, start ramp, cycling floor) and nothing freezes it
(defrost, DHW, stale or implausible room, wood stove, override, reduced cooling
authority). Once an ``on_change`` room sensor has been silent beyond
``alive_decay_start_s``, or its value went stale or implausible, the cooling
integrated since its last proof of life is undone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ovenbird_core.control.config import OvenbirdConfig
from ovenbird_core.control.notes import HARD_HIGH
from ovenbird_core.control.safety import EPSILON, SafetyBounds
from ovenbird_core.control.stages import round_half_up
from ovenbird_core.control.terms import Feedback, clamp
from ovenbird_core.control.types import RoomInput

if TYPE_CHECKING:
    from ovenbird_core.control.ovenbird import OvenbirdState


def freezes(
    *,
    defrost: bool,
    dhw: bool,
    implausible: bool,
    room: RoomInput | None,
    seen: RoomInput | None,
    stove: bool,
    manual: bool,
) -> list[str]:
    """Return what freezes the integrator this tick, in the order the record lists it."""
    frozen_by: list[str] = []
    if defrost:
        frozen_by.append("defrost")
    if dhw:
        frozen_by.append("dhw")
    if implausible:
        frozen_by.append("room_implausible")
    elif room is None:
        frozen_by.append("room_stale" if seen is not None else "no_room_sensor")
    if stove:
        frozen_by.append("stove")
    if manual:
        frozen_by.append("override")
    return frozen_by


def integrate(
    cfg: OvenbirdConfig,
    integral: float,
    feedback: Feedback,
    frozen_by: list[str],
    *,
    pre_clamp: float,
    pre_round: float,
    bounds: SafetyBounds,
    final: int,
    binding: str | None,
    ramp: float,
    cycling: float,
    dt: float,
) -> tuple[float, list[str]]:
    """Advance the integrator unless frozen or saturated (anti-windup).

    Returns
    -------
    tuple[float, list[str]]
        The new integrator and ``frozen_by`` with ``anti_windup`` or
        ``room_authority`` appended when one of them stopped the integration.
    """
    fb = cfg.feedback
    error = feedback.error
    u_raw = feedback.u_raw
    frozen = list(frozen_by)
    if error is not None and not frozen:
        saturated = (
            (u_raw > fb.output_limit_k and error > 0.0)
            or (u_raw < -fb.output_limit_k and error < 0.0)
            or (pre_clamp > bounds.high + EPSILON and error > 0.0)
            or (pre_clamp < bounds.low - EPSILON and error < 0.0)
            or (final < round_half_up(pre_round) and binding in HARD_HIGH and error > 0.0)
            or (ramp < 0.0 and error > 0.0)
            or ((cycling > 0.0 or binding == "cycling_floor") and error < 0.0)
        )
        if saturated:
            frozen.append("anti_windup")
        elif feedback.authority < 1.0 and feedback.e_int < 0.0:
            frozen.append("room_authority")
        else:
            step_s = min(dt, fb.max_integration_step_s)
            integral = clamp(integral + fb.ki_per_s * feedback.e_int * step_s, fb.integral_limit_k)
    return integral, frozen


def integral_at_life(
    cfg: OvenbirdConfig,
    state: OvenbirdState,
    room: RoomInput | None,
    dt: float,
    *,
    lost: bool = False,
) -> float | None:
    """Return the integrator at the room sensor's last proof of life.

    A proof of life since the previous tick (an age below the tick interval)
    takes the integrator as it stood before this tick; a ``lost`` (stale or
    implausible) value keeps the mark it had; without a usable ``on_change``
    value nothing is kept.
    """
    if room is None and lost:
        return state.integral_at_life_k
    if room is None or not cfg.room.held or room.age is None:
        return None
    if state.integral_at_life_k is None or room.age < dt:
        return state.integral_k
    return state.integral_at_life_k


def silent(room: RoomInput, cfg: OvenbirdConfig) -> bool:
    """Whether a held room value has had no proof of life for the alive decay start."""
    return room.age is not None and room.age > cfg.room.alive_decay_start_s


def rollback(
    cfg: OvenbirdConfig,
    integral: float,
    at_life: float | None,
    pi_room: RoomInput | None,
    frozen_by: list[str],
    *,
    defrost: bool,
    dhw: bool,
    stove: bool = False,
    lost: bool = False,
) -> tuple[float, list[str]]:
    """Undo the cooling integrated since the last proof of life of a silent or lost device.

    A value that went stale or implausible before the device fell silent long
    enough (a stuck reading the cross-check flags within its sustain time) keeps
    no cooling nothing confirmed either. Defrost, DHW and a wood-stove episode
    defer the undo (the mark is kept); it never goes beyond the integrator clamp.
    """
    if defrost or dhw or stove or at_life is None or integral >= at_life:
        return integral, frozen_by
    at_life = clamp(at_life, cfg.feedback.integral_limit_k)
    if integral >= at_life:
        return integral, frozen_by
    if lost:
        return at_life, [*frozen_by, "room_lost_rollback"]
    if pi_room is not None and silent(pi_room, cfg):
        return at_life, [*frozen_by, "room_silent_rollback"]
    return integral, frozen_by

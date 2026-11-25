"""From the continuous ``pre_round`` to the issued integer setpoint (pipeline stages 5-6).

Stage 5 keeps the issued setpoint through rounding hysteresis, deadband, dwell and the
no-decrease rule of defrost and DHW. Stage 6 applies the hard constraints that bypass
it: the cycling floor inside the minimum-run window and the safety envelope on the
integer value, which always has the last word.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ovenbird_core.control.config import OvenbirdConfig, SetpointStageConfig
from ovenbird_core.control.safety import EPSILON, SafetyBounds
from ovenbird_core.control.terms import RampPhase


@dataclass(frozen=True, slots=True)
class Stages:
    """The integer candidate after stage 5 and what kept it (``None``: nothing)."""

    candidate: int
    binding: str | None


def round_half_up(value: float) -> int:
    """Round to the nearest integer, halves upwards (independent of parity)."""
    return math.floor(value + 0.5)


def dwell_time(
    cfg: OvenbirdConfig, phase: RampPhase, before: RampPhase, before_cap: float | None
) -> float:
    """Return the dwell time before a change: shorter while a start ramp runs.

    ``phase`` is the ramp phase after this tick, ``before`` and ``before_cap`` the
    phase and cap it started from. On the ramp's first tick (no cap yet) there is
    no dwell.
    """
    ramping = phase is not RampPhase.IDLE or (
        before is not RampPhase.IDLE and before_cap is not None
    )
    dwell = cfg.stages.ramp_dwell_s if ramping else cfg.stages.dwell_s
    if phase is not RampPhase.IDLE and before_cap is None:
        dwell = 0.0
    return dwell


def soften(
    stages: SetpointStageConfig,
    pre_round: float,
    reference: int | None,
    last_change_at: float | None,
    now: float,
    dwell: float,
    defrost: bool,
    dhw: bool,
    manual: bool,
) -> Stages:
    """Return the integer candidate after rounding hysteresis, deadband and dwell."""
    rounded = round_half_up(pre_round)
    if reference is None or manual:
        return Stages(rounded, None)
    distance = abs(pre_round - reference)
    if distance <= 0.5 + stages.rounding_hysteresis_k:
        return Stages(reference, "rounding" if rounded != reference else None)
    if distance < stages.deadband_k:
        return Stages(reference, "deadband")
    if rounded < reference and (defrost or dhw):
        return Stages(reference, "defrost_hold" if defrost else "dhw_hold")
    if last_change_at is not None and now - last_change_at < dwell:
        return Stages(reference, "dwell")
    return Stages(rounded, None)


def hard_constraints(
    cfg: OvenbirdConfig,
    stages: Stages,
    floor: float | None,
    reference: int | None,
    bounds: SafetyBounds,
) -> tuple[int, str | None, tuple[int, int] | None]:
    """Apply the cycling floor and the integer safety clamp to the stage-5 candidate.

    A decrease inside the minimum-run window must also keep ``decrease_headroom_k``
    above the floor, so outlet jitter cannot flip the setpoint.

    Returns
    -------
    tuple[int, str | None, tuple[int, int] | None]
        The final setpoint, its binding and, when the safety envelope clamped the
        integer value, the value before and after that clamp.
    """
    final, binding = stages.candidate, stages.binding
    if floor is not None:
        cc = cfg.cycling
        floor_int = math.ceil(floor - EPSILON)
        decrease_floor = math.ceil(floor + cc.decrease_headroom_k - EPSILON)
        if reference is not None and final < reference and final < decrease_floor:
            final, binding = min(reference, decrease_floor), "cycling_floor"
        if final < floor_int:
            final, binding = floor_int, "cycling_floor"
    clamped = bounds.clamp_int(final)
    integer_clamp: tuple[int, int] | None = None
    if clamped != final:
        binding = (bounds.high_source if clamped < final else bounds.low_source).value
        integer_clamp = (final, clamped)
        final = clamped
    return final, binding, integer_clamp

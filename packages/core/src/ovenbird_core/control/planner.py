"""Model plan: a bounded room-target offset from the learned house model and the forecast.

The planner looks ahead over the forecast sun and outside temperature and asks the room
feedback for a small shift of its target: set back before free heat arrives, pre-heat
before a loss arrives. It is pure and deterministic: no I/O, no clock, the same inputs
give the same :class:`PlannerResult`. The controller clamps its slice again
(:class:`~ovenbird_core.control.config.ModelPlanConfig`) and applies it only with a
trusted room value and no wood-stove episode or recovery, so the comfort effect is at
most the bound whatever the model error.

Method
------
By linearity of the :class:`~ovenbird_core.housemodel.HouseModel` only the *deviation*
of the room temperature caused by the weather is simulated, in steps of one slice
(15 min), from a zero deviation state ``HISTORY_S`` (24 h) before ``now`` to
``now + horizon_h``. The past rows (the shortest-lead forecasts already stored) charge
the building mass; no state estimate is needed. Two parts are simulated apart:

``solar``
    the room's response to the forecast irradiance, with the loop heat held (zero
    deviation);
``outside``
    the room's response to what the heating curve does *not* compensate of the
    forecast outside temperature: the outside temperature moves the air node at once,
    while the curve follows a filtered outside temperature (``outside_filter_tau_s``,
    the controller's filter) and its heat reaches the room through the emitter. The
    curve's heat is modelled as that of a curve matched to the house,
    ``-UA (F - T_ref)`` with ``F`` the filtered forecast; both inputs are deviations
    from the forecast outside temperature at the start of the window, so a forecast
    with a constant bias against the pump's sensor gives no outside part. With
    weather-dependent control off the curve does not follow the outside temperature
    and the loop heat is held. A constant outside temperature gives no outside part;
    a forecast that differs from the measured filtered outside temperature only by
    the curve's own lag would otherwise be counted twice (once by the curve, once by
    the planner).

``Δ`` is the largest rise of the summed deviation above its value at ``now`` within
the horizon plus its largest fall below it (signed: positive, the house drifts warmer
on its own). Both extremes move continuously as the horizon rolls on, so ``Δ`` does
too; taking only the larger of the two would jump between a rise and a fall of
nearly equal size (the hour after the sun's peak), and when both a gain and a loss
lie ahead they partly cancel, which is the cautious answer. The offset is
``-gain Δ`` with the first ``dead_zone_k`` left to the room feedback, quantised to
``quantum_k`` (kept at the previous offset when within ``0.75 quantum_k`` of it, so a
value on a step edge does not flip), moved at most ``rate_k_per_slice`` from the
previous offset and clamped to ``[-max_setback_k, +max_preheat_k]``.

Gain and horizon
----------------
``Δ`` is an open-loop prediction (loop heat held), while the room feedback rejects part
of a disturbance by itself; the planner should cover only what the feedback leaves. A
continuous PI with the preset ``kp`` (2 K water per K room) has a steady loop gain of
``kp K / (K + UA)`` from water to room (``K`` the loop-to-room conductance), about 1.35
for both the learner's prior house and the example house, so it would leave
``1 / (1 + 1.35)`` = 0.43 of a slow disturbance. The real loop rejects less: the
issued setpoint moves in whole kelvin with a 1 K deadband and a dwell, which is
0.5 K of room error through ``kp`` before the P part acts at all, the integrator
adds only ``kp / Ti`` per K room (0.17 K water per hour at 0.5 K for the mixed
preset), and the floor delays the heat by hours. Measured in closed loop on the
example plant (the simulator's reference house, all three emitter presets, the
learner's prior house as well), the room's rise from a sunny winter day was
0.6-1.1 of the open-loop rise ``Δ`` (median about 0.9). The default gain 0.6 takes
the low end of that band: with the 0.2 K dead zone a sunny winter day (``Δ`` about
0.7-1 K) asks for 0.2-0.4 K, a spring day reaches the 0.5 K bound. In closed-loop runs
(8 days, example plant, perfect forecast) it cut the degree-hours above the comfort
band on sunny winter days by 40 % without more below comfort, and a forecast sun that never came
cost 0.4 Kh below comfort per day and nothing below the band; a gain of 1 gained
little more and cost more when the sun stayed away or the model was wrong.

The horizon is set by the lag the plan acts through, not by the slowest building time
constant (50-80 h): a target shift moves the water mostly through the integrator
(hours for 0.5 K water) and the floor answers a water change within 1-3 h, and the
sun rises to its peak over about 4 h. Six hours see the peak from the early morning;
in the same runs 3 h acted too late (overshoot nearly unchanged) and 9-12 h set back
through the night before a sunny day, trading overshoot for undershoot (12 h on a
mild sunny week: 7 Kh below the band).

Calling contract
----------------
Call once per slice (every ``slice_s``, best on the quarter hour) with the offset of
the slice issued by the previous call (0 when none was issued or it expired). The slice
is valid for ``slice_s + grace_s``, so a missed call lets it expire by itself; the rate
limit is per call.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Final

from ovenbird_core.control.config import (
    MODEL_PLAN_MAX_PREHEAT_K,
    MODEL_PLAN_MAX_SETBACK_K,
    MODEL_PLAN_MAX_SLICE_S,
    OvenbirdConfig,
)
from ovenbird_core.control.types import PlanSlice, PlanSource, ReasonCode
from ovenbird_core.housemodel import DiscreteHouse, HouseModel
from ovenbird_core.instant import Instant
from ovenbird_core.setting import check_settings, setting

__all__ = [
    "DIGITS",
    "HISTORY_S",
    "HOUR_S",
    "ForecastHour",
    "PlannerConfig",
    "PlannerResult",
    "PlannerStatus",
    "plan_offset",
]

HOUR_S: Final = 3600.0
HISTORY_S: Final = 24 * HOUR_S
DIGITS: Final = 3
OFFSET_DIGITS: Final = 6
QUANTUM_HOLD: Final = 0.75
EPSILON: Final = 1e-9


class PlannerStatus(StrEnum):
    """Outcome of one planner call (a closed set).

    ``issued``: a slice with a non-zero offset. ``inside_dead_zone``: the offset is
    zero (the predicted drift is within the dead zone or too small for one quantum).
    ``crossing_zero``: the offset changes sign and the rate limit holds it at zero for
    this slice.
    ``forecast_gap``: a forecast hour the window needs is missing or has no value.
    ``forecast_mismatch``: the filtered forecast outside temperature at ``now`` is
    further than ``max_outside_mismatch_k`` from the controller's filtered outside
    temperature (a forecast for another place or time). ``model_invalid``: the model
    cannot be discretised or gives a non-finite prediction.
    """

    ISSUED = "issued"
    INSIDE_DEAD_ZONE = "inside_dead_zone"
    CROSSING_ZERO = "crossing_zero"
    FORECAST_GAP = "forecast_gap"
    FORECAST_MISMATCH = "forecast_mismatch"
    MODEL_INVALID = "model_invalid"


def _require_finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")


@dataclass(frozen=True, slots=True)
class ForecastHour:
    """One forecast hour, as stored (the shortest lead available for that hour).

    Parameters
    ----------
    target_ts
        The hour it describes, unix seconds on a whole hour.
    outside_c
        Air temperature at ``target_ts`` (``None``: missing).
    ghi_w_m2
        Global horizontal irradiance, mean over the hour *before* ``target_ts``
        (``None``: missing).
    """

    target_ts: float
    outside_c: float | None
    ghi_w_m2: float | None

    def __post_init__(self) -> None:
        """Reject a time off the hour, non-finite values and negative irradiance."""
        _require_finite("target_ts", self.target_ts)
        if self.target_ts % HOUR_S != 0.0:
            raise ValueError("forecast hours must lie on whole hours")
        if self.outside_c is not None:
            _require_finite("outside_c", self.outside_c)
        if self.ghi_w_m2 is not None:
            _require_finite("ghi_w_m2", self.ghi_w_m2)
            if self.ghi_w_m2 < 0.0:
                raise ValueError("ghi_w_m2 must be non-negative")


@dataclass(frozen=True, slots=True)
class PlannerConfig:
    """Settings of the model planner (described on the fields).

    :meth:`for_controller` takes the bounds, the outside filter and the
    weather-dependent switch from the controller's configuration, so planner and
    controller agree on them.
    """

    max_setback_k: float = setting(
        0.5,
        ge=0.0,
        le=MODEL_PLAN_MAX_SETBACK_K,
        unit="K",
        doc="Largest room-target set-back the planner issues.",
    )
    max_preheat_k: float = setting(
        0.3,
        ge=0.0,
        le=MODEL_PLAN_MAX_PREHEAT_K,
        unit="K",
        doc="Largest room-target pre-heat the planner issues.",
    )
    horizon_h: float = setting(
        6.0, ge=1.0, le=12.0, unit="h", doc="How far ahead the planner looks."
    )
    gain: float = setting(
        0.6,
        gt=0.0,
        le=1.0,
        doc="Share of the predicted open-loop drift turned into a room-target offset.",
    )
    dead_zone_k: float = setting(
        0.2,
        ge=0.0,
        le=1.0,
        unit="K",
        doc="Part of the offset left to the room feedback (smaller offsets are not issued).",
    )
    quantum_k: float = setting(0.1, gt=0.0, le=0.5, unit="K", doc="Step of the issued offset.")
    rate_k_per_slice: float = setting(
        0.1,
        gt=0.0,
        le=1.0,
        unit="K",
        doc="Largest change of the offset from one slice to the next.",
    )
    slice_s: float = setting(900.0, ge=300.0, le=HOUR_S, unit="s", doc="Length of one slice.")
    grace_s: float = setting(
        300.0,
        ge=0.0,
        le=HOUR_S,
        unit="s",
        doc="Extra validity of a slice, so one late call does not drop the plan.",
    )
    outside_weight: float = setting(
        1.0,
        ge=0.0,
        le=1.0,
        doc="Weight of the outside part (what the heating curve leaves) in the prediction.",
    )
    outside_filter_tau_s: float = setting(
        4 * HOUR_S,
        ge=0.0,
        le=24 * HOUR_S,
        unit="s",
        doc="Time constant of the controller's outside-temperature filter.",
    )
    weather_compensation: bool = setting(
        True, doc="The controller's water follows the heating curve (weather-dependent control)."
    )
    max_outside_mismatch_k: float = setting(
        8.0,
        gt=0.0,
        le=30.0,
        unit="K",
        doc=(
            "Largest difference between the filtered forecast and the controller's filtered "
            "outside temperature at the time of planning."
        ),
    )

    def __post_init__(self) -> None:
        """Validate the ranges and that a slice cannot outlive the controller's limit."""
        check_settings(self)
        if self.rate_k_per_slice < self.quantum_k:
            raise ValueError("rate_k_per_slice must be at least one quantum_k")
        if self.slice_s + self.grace_s > MODEL_PLAN_MAX_SLICE_S:
            raise ValueError("slice_s + grace_s must not exceed MODEL_PLAN_MAX_SLICE_S")

    @classmethod
    def for_controller(cls, cfg: OvenbirdConfig, **overrides: Any) -> PlannerConfig:
        """Return the planner settings matching the controller configuration ``cfg``.

        Parameters
        ----------
        cfg
            Controller configuration: its model-plan bounds, outside filter and
            weather-dependent switch are taken over.
        **overrides
            Other planner settings (``horizon_h``, ``gain``, ...).

        Returns
        -------
        PlannerConfig
            The planner settings.
        """
        base = cls(
            max_setback_k=cfg.model_plan.max_setback_k,
            max_preheat_k=cfg.model_plan.max_preheat_k,
            outside_filter_tau_s=cfg.outside_filter_tau_s,
            weather_compensation=cfg.weather_compensation,
        )
        return replace(base, **overrides) if overrides else base

    @property
    def steps(self) -> tuple[int, int]:
        """Number of slices simulated before ``now`` and after it (the horizon)."""
        return round(HISTORY_S / self.slice_s), math.ceil(self.horizon_h * HOUR_S / self.slice_s)


@dataclass(frozen=True, slots=True)
class PlannerResult:
    """What one planner call decided, with the numbers a UI shows.

    Numbers are rounded to :data:`DIGITS` decimals; the offsets are exact multiples of
    the quantum. Prediction fields are ``None`` when the planner could not predict
    (``forecast_gap``, ``model_invalid``).

    Parameters
    ----------
    status
        Outcome (:class:`PlannerStatus`).
    slice
        The plan slice (``None`` unless ``status`` is ``issued``).
    peak_change_k
        ``Δ``: the predicted rise plus the predicted fall (positive: warmer).
    rise_k, rise_at_ts
        Largest rise of the room deviation above its value at ``now`` within the
        horizon (``>= 0``) and when it is reached (unix seconds, end of a slice;
        ``None`` without a rise).
    fall_k, fall_at_ts
        Largest fall below it (``<= 0``) and when.
    solar_k, outside_k
        The solar and the outside part of ``Δ`` (they add up to it within rounding).
    raw_offset_k
        ``-gain Δ`` before dead zone, quantisation, rate limit and bounds.
    target_offset_k
        The offset after dead zone, quantisation and bounds, before the rate limit.
    offset_k
        The offset issued (0 without a slice).
    previous_offset_k
        The previous offset the rate limit started from.
    forecast_outside_c
        The filtered forecast outside temperature at ``now`` (the mismatch check).
    """

    status: PlannerStatus
    slice: PlanSlice | None
    peak_change_k: float | None
    rise_k: float | None
    rise_at_ts: float | None
    fall_k: float | None
    fall_at_ts: float | None
    solar_k: float | None
    outside_k: float | None
    raw_offset_k: float | None
    target_offset_k: float | None
    offset_k: float
    previous_offset_k: float
    forecast_outside_c: float | None


@dataclass(frozen=True, slots=True)
class _Inputs:
    outside: tuple[float, ...]
    sun: tuple[float, ...]


def _index(rows: Iterable[ForecastHour]) -> dict[float, ForecastHour]:
    found: dict[float, ForecastHour] = {}
    for row in rows:
        if row.target_ts in found:
            raise ValueError(f"forecast hour {row.target_ts:.0f} is given twice")
        found[row.target_ts] = row
    return found


def _resample(
    hours: dict[float, ForecastHour], start_ts: float, count: int, step_s: float
) -> _Inputs | None:
    """Return the outside temperature and irradiance at the middle of every step.

    The outside temperature is interpolated linearly between the hours around the
    middle; the irradiance is the mean of the hour the middle falls in (the row at the
    end of that hour). ``None`` when a needed hour is missing or has no value.
    """
    outside: list[float] = []
    sun: list[float] = []
    for k in range(count):
        middle = start_ts + (k + 0.5) * step_s
        before = math.floor(middle / HOUR_S) * HOUR_S
        after = before + HOUR_S
        low, high = hours.get(before), hours.get(after)
        if low is None or high is None or low.outside_c is None or high.outside_c is None:
            return None
        if high.ghi_w_m2 is None:
            return None
        share = (middle - before) / HOUR_S
        outside.append(low.outside_c + share * (high.outside_c - low.outside_c))
        sun.append(high.ghi_w_m2)
    return _Inputs(tuple(outside), tuple(sun))


def _room_response(
    discrete: DiscreteHouse, inputs: Sequence[tuple[float, float, float]]
) -> list[float]:
    """Return the room deviation at the end of every step for ``[Q, T_o, I]`` deviations."""
    state: tuple[float, float, float] = (0.0, 0.0, 0.0)
    room: list[float] = []
    for heat, outside, sun in inputs:
        state = discrete.step(state, (heat, outside, sun, 0.0))
        room.append(state[2])
    return room


def _filtered(values: Sequence[float], step_s: float, tau_s: float) -> list[float]:
    """Return the controller's first-order filter of ``values`` (one value per step)."""
    if tau_s <= 0.0:
        return list(values)
    alpha = 1.0 - math.exp(-step_s / tau_s)
    out: list[float] = []
    level = values[0]
    for value in values:
        level += alpha * (value - level)
        out.append(level)
    return out


def _extremes(changes: Sequence[float]) -> tuple[int | None, int | None]:
    """Return the index of the largest rise above zero and of the largest fall below it.

    ``None`` when there is no rise (or no fall); ties take the earliest step.
    """
    rise_at: int | None = None
    fall_at: int | None = None
    for k, value in enumerate(changes):
        if value > 0.0 and (rise_at is None or value > changes[rise_at]):
            rise_at = k
        if value < 0.0 and (fall_at is None or value < changes[fall_at]):
            fall_at = k
    return rise_at, fall_at


def _quantise(value: float, quantum: float) -> float:
    return round(round(value / quantum) * quantum, OFFSET_DIGITS) + 0.0


def _rounded(value: float) -> float:
    return round(value, DIGITS) + 0.0


def plan_offset(
    model: HouseModel,
    forecast: Sequence[ForecastHour],
    now: Instant,
    outside_filtered_c: float,
    config: PlannerConfig,
    previous_offset_k: float = 0.0,
) -> PlannerResult:
    """Return the model plan for the slice starting at ``now`` (see the module docstring).

    Parameters
    ----------
    model
        The learned house model (champion), already checked by the caller.
    forecast
        Hourly forecast rows covering at least ``HISTORY_S`` before ``now`` to
        ``horizon_h`` after it (past hours: the shortest-lead forecast stored).
    now
        Start of the slice.
    outside_filtered_c
        The controller's filtered outside temperature (the mismatch check).
    config
        Planner settings.
    previous_offset_k
        Offset of the slice the previous call issued (0 when none).

    Returns
    -------
    PlannerResult
        The slice (or none, with the reason) and the prediction behind it.

    Raises
    ------
    ValueError
        When a forecast hour is given twice or an argument is not finite.
    """
    _require_finite("outside_filtered_c", outside_filtered_c)
    _require_finite("previous_offset_k", previous_offset_k)
    previous = _quantise(previous_offset_k, config.quantum_k)
    hours = _index(forecast)
    step_s = config.slice_s
    past, ahead = config.steps
    now_ts = now.wall.timestamp()
    start_ts = now_ts - past * step_s
    nothing = PlannerResult(
        PlannerStatus.FORECAST_GAP,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        0.0,
        previous,
        None,
    )
    sampled = _resample(hours, start_ts, past + ahead, step_s)
    if sampled is None:
        return nothing
    try:
        discrete = model.discretise(step_s)
    except ValueError:
        return replace(nothing, status=PlannerStatus.MODEL_INVALID)
    reference = sampled.outside[0]
    filtered = _filtered(sampled.outside, step_s, config.outside_filter_tau_s)
    ua = model.h_air_out if config.weather_compensation else 0.0
    solar = _room_response(discrete, [(0.0, 0.0, sun) for sun in sampled.sun])
    outside = _room_response(
        discrete,
        [
            (-ua * (level - reference), value - reference, 0.0)
            for value, level in zip(sampled.outside, filtered, strict=True)
        ],
    )
    weight = config.outside_weight
    total = [s + weight * o for s, o in zip(solar, outside, strict=True)]
    if not all(math.isfinite(value) for value in total):
        return replace(nothing, status=PlannerStatus.MODEL_INVALID)
    forecast_outside = filtered[past - 1]
    base, base_solar, base_outside = total[past - 1], solar[past - 1], outside[past - 1]
    rise_at, fall_at = _extremes([value - base for value in total[past : past + ahead]])
    rise = 0.0 if rise_at is None else total[past + rise_at] - base
    fall = 0.0 if fall_at is None else total[past + fall_at] - base
    change = rise + fall
    picked = [past + k for k in (rise_at, fall_at) if k is not None]
    solar_part = sum(solar[k] - base_solar for k in picked)
    outside_part = weight * sum(outside[k] - base_outside for k in picked)
    raw = -config.gain * change
    target = _target(config, raw, previous)
    offset = _bounded(config, _rate_limited(config, target, previous))
    result = PlannerResult(
        status=PlannerStatus.ISSUED,
        slice=None,
        peak_change_k=_rounded(change),
        rise_k=_rounded(rise),
        rise_at_ts=None if rise_at is None else now_ts + (rise_at + 1) * step_s,
        fall_k=_rounded(fall),
        fall_at_ts=None if fall_at is None else now_ts + (fall_at + 1) * step_s,
        solar_k=_rounded(solar_part),
        outside_k=_rounded(outside_part),
        raw_offset_k=_rounded(raw),
        target_offset_k=target,
        offset_k=offset,
        previous_offset_k=previous,
        forecast_outside_c=_rounded(forecast_outside),
    )
    if abs(forecast_outside - outside_filtered_c) > config.max_outside_mismatch_k:
        return replace(result, status=PlannerStatus.FORECAST_MISMATCH, offset_k=0.0)
    if offset == 0.0:
        status = PlannerStatus.CROSSING_ZERO if target != 0.0 else PlannerStatus.INSIDE_DEAD_ZONE
        return replace(result, status=status)
    reason = ReasonCode.PLAN_SETBACK if offset < 0.0 else ReasonCode.PLAN_PREHEAT
    plan = PlanSlice(
        room_offset_k=offset,
        reason=reason,
        valid_from=now,
        valid_until=now.shifted(step_s + config.grace_s),
        source=PlanSource.MODEL,
    )
    return replace(result, slice=plan)


def _bounded(config: PlannerConfig, offset: float) -> float:
    """Return ``offset`` clamped to ``[-max_setback_k, +max_preheat_k]`` on the quantum grid."""
    clamped = min(max(offset, -config.max_setback_k), config.max_preheat_k)
    whole = math.floor(abs(clamped) / config.quantum_k + EPSILON)
    return _quantise(math.copysign(whole * config.quantum_k, clamped), config.quantum_k)


def _target(config: PlannerConfig, raw: float, previous: float) -> float:
    """Return the offset the planner moves towards: dead zone, quantum with hold, bounds.

    The first ``dead_zone_k`` of the raw offset is dropped; the rest is quantised,
    except that it keeps the previous offset while within ``QUANTUM_HOLD`` quanta of
    it (no flipping on a step edge).
    """
    shrunk = math.copysign(max(0.0, abs(raw) - config.dead_zone_k), raw)
    target = _quantise(shrunk, config.quantum_k)
    if abs(shrunk - previous) <= QUANTUM_HOLD * config.quantum_k:
        target = previous
    return _bounded(config, target)


def _rate_limited(config: PlannerConfig, target: float, previous: float) -> float:
    """Return ``target`` approached from ``previous`` by whole quanta, at most the rate."""
    delta = target - previous
    allowed = min(abs(delta), config.rate_k_per_slice)
    whole = math.floor(allowed / config.quantum_k + EPSILON)
    return _quantise(previous + math.copysign(whole * config.quantum_k, delta), config.quantum_k)

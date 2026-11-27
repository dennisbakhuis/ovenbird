"""Offline evaluation of a model planner: paired closed-loop runs over weather replicas.

Design
------
Every cell (scenario x planner house model x forecast variant) is simulated on the same
N weather replicas as the baseline of its scenario (ovenbird without a planner): a
replica fixes the weather, the sensor noise, the initial slab temperature and the
forecast error, so the planner is the only difference within a pair. The gate on the
paired differences is in :mod:`ovenbird_sim.evaluate.plangate`.

Replicas
--------
A replica is drawn from ``(seed, replica)``; each quantity of a day or an hour is drawn
from ``(seed, replica, quantity, day)`` alone (:func:`draw`), never from a shared
stream, so a draw does not depend on how many days are simulated or in which order
anything is called. Per replica:

* outside temperature: the scenario's mean plus a constant offset uniform in
  +-:data:`MEAN_JITTER_K`, a daily swing (sine amplitude, minimum at 03:00, maximum at
  15:00) uniform in :data:`SWING_RANGE_K` per day, and a day-to-day drift, an AR(1)
  with coefficient :data:`DRIFT_PHI` and stationary standard deviation
  :data:`DRIFT_SD_K`; swing and drift are interpolated between the day centres so the
  temperature has no steps;
* sun: a half sine of :data:`SUN_HOURS` starting at :data:`SUN_START_H` plus a shift
  uniform in +-:data:`SUN_SHIFT_H` per day; the peak of a clear day is the scenario's
  peak times a clearness uniform in :data:`CLEARNESS_RANGE`, an overcast day
  :data:`OVERCAST_PEAK` times a factor uniform in :data:`OVERCAST_RANGE`; in
  ``mixed_week`` each day is clear with probability :data:`MIXED_CLEAR_P`;
* the cold front's time is shifted uniform in +-:data:`FRONT_SHIFT_H`;
* the loop: the pump's outside sensor gets Gaussian noise of :data:`OUTSIDE_NOISE_K`
  before its rounding to whole degrees, the living-room sensor of
  :data:`ROOM_NOISE_K` before its 0.2 K grid; the initial slab (mass) temperature is
  uniform in :data:`MASS_RANGE_C`;
* the forecast error seed of the ``noisy`` forecast.

Scenarios
---------
``sunny_cold``, ``sunny_mild``, ``cloudy``, ``cold_front``, ``missing_sun`` (overcast,
forecast clear), ``unforecast_sun`` (clear, forecast overcast), ``mixed_week`` (random
clear and overcast days, forecast right) and ``false_sun_cold`` (-3 °C, no sun,
forecast 600 W/m² every day; the adversarial cell for a sun-driven feed-forward).

Planners
--------
A planner is an entry of :data:`PLANNERS`: a factory that turns an :class:`ArmContext`
(the controller configuration, the planner's house model, the planner parameters) into
an :class:`Arm` (the controller configuration to run and the closed loop's plan
provider). ``none`` issues nothing (the pairing check), ``noise`` issues nothing but
draws the sensor noise from another seed (the false-alarm calibration), ``v1`` is
:func:`~ovenbird_core.control.planner.plan_offset`, ``const_water`` lowers the water
by a constant without any gate, ``const_room`` shifts the room target by a constant
(the forecast-blind control of ``v1``), and ``v2`` is the water feed-forward
:func:`~ovenbird_core.control.planner.plan_water` (:func:`v2_arm` documents what a
planner provider receives).
"""

from __future__ import annotations

import math
import os
import zlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from typing import Any, Final

import numpy as np

from ovenbird_core.control import OvenbirdConfig, OvenbirdController
from ovenbird_core.control.curve import CurvePoint, HeatingCurve
from ovenbird_core.control.planner import (
    PlannerConfig,
    WaterPlannerConfig,
    plan_offset,
    plan_water,
)
from ovenbird_core.control.protocol import StepResult
from ovenbird_core.control.types import PlanSlice, PlanSource, ReasonCode
from ovenbird_core.housemodel import HouseModel
from ovenbird_sim.data.series import FloatArray
from ovenbird_sim.evaluate import plangate
from ovenbird_sim.evaluate.closedloop import (
    MODEL_PLAN_APPLIED_KEY,
    LoopOptions,
    PlanProvider,
    PlanRequest,
    Weather,
    simulate,
)
from ovenbird_sim.evaluate.forecast import ForecastError, TableForecast, hourly_table
from ovenbird_sim.evaluate.plangate import COMFORT_C, RunResult
from ovenbird_sim.evaluate.sensors import RoomSensorModel, SensorModel
from ovenbird_sim.heishamon.reference import REFERENCE_BUILDING, REFERENCE_PARAMS
from ovenbird_sim.model.plant import initial_state

T0: Final = 1_767_225_600.0
TICK_S: Final = 60.0
DAY_H: Final = 24.0
DEFAULT_DAYS: Final = 8
DEFAULT_REPLICAS: Final = 24
DEFAULT_SEED: Final = 0
EMITTER: Final = "mixed"
INITIAL_SETPOINT: Final = 30
INITIAL_WATER_C: Final = 28.0

MEAN_JITTER_K: Final = 1.5
SWING_RANGE_K: Final = (2.0, 5.0)
SWING_MIN_H: Final = 9.0
DRIFT_PHI: Final = 0.7
DRIFT_SD_K: Final = 1.0
SUN_START_H: Final = 8.5
SUN_HOURS: Final = 8.0
SUN_SHIFT_H: Final = 1.0
CLEARNESS_RANGE: Final = (0.75, 1.0)
OVERCAST_PEAK: Final = 80.0
OVERCAST_RANGE: Final = (0.6, 1.4)
MIXED_CLEAR_P: Final = 0.5
FRONT_DAY: Final = 4
FRONT_FROM_H: Final = 11.0
FRONT_TO_H: Final = 14.0
FRONT_SHIFT_H: Final = 1.0
FRONT_DROP_K: Final = 8.0
OUTSIDE_NOISE_K: Final = 0.3
ROOM_NOISE_K: Final = 0.05
MASS_RANGE_C: Final = (23.5, 26.5)

SALT_MEAN: Final = 1
SALT_SWING: Final = 2
SALT_DRIFT: Final = 3
SALT_CLEAR: Final = 4
SALT_SUN: Final = 5
SALT_SKY: Final = 6
SALT_MASS: Final = 7
SALT_FRONT: Final = 8
SALT_SENSOR: Final = 9
SALT_FORECAST: Final = 10

CLEAR: Final = "clear"
OVERCAST: Final = "overcast"
MIXED: Final = "mixed"
DARK: Final = "none"

CORRECT: Final = "correct"
PERFECT: Final = "perfect"
NOISY: Final = "noisy"
SHIFT_EARLY: Final = "shift_-2h"
SHIFT_LATE: Final = "shift_+2h"
FORECAST_SHIFT_H: Final[Mapping[str, float]] = {
    PERFECT: 0.0,
    NOISY: 0.0,
    SHIFT_EARLY: -2.0,
    SHIFT_LATE: 2.0,
}
BASE_FORECASTS: Final = (PERFECT, NOISY)
SHIFT_FORECASTS: Final = (SHIFT_EARLY, SHIFT_LATE)

type Scale = Mapping[str, float]
type Params = tuple[tuple[str, float], ...]


@dataclass(frozen=True, slots=True)
class Scenario:
    """A synthetic weather scenario (its character; the replicas vary it).

    Parameters
    ----------
    name
        Scenario name.
    mean_c
        Mean outside temperature (for the front: the level before it).
    sky
        Delivered sky: ``clear``, ``overcast``, ``mixed`` or ``none``.
    forecast_sky
        Sky the forecast announces (the same kinds).
    clear_peak
        Peak irradiance of a delivered clear day in W/m².
    forecast_peak
        Peak irradiance of a forecast clear day in W/m².
    front
        The outside temperature falls by :data:`FRONT_DROP_K` on day :data:`FRONT_DAY`.
    """

    name: str
    mean_c: float
    sky: str
    forecast_sky: str
    clear_peak: float = 350.0
    forecast_peak: float = 350.0
    front: bool = False

    @property
    def forecast_has_sun(self) -> bool:
        """Whether the forecast announces any sun (a shifted forecast differs)."""
        return self.forecast_sky != DARK


SCENARIOS: Final = {
    s.name: s
    for s in (
        Scenario("sunny_cold", 1.0, CLEAR, CLEAR),
        Scenario("sunny_mild", 8.0, CLEAR, CLEAR, 600.0, 600.0),
        Scenario("cloudy", 1.0, OVERCAST, OVERCAST),
        Scenario("cold_front", 8.0, DARK, DARK, front=True),
        Scenario("missing_sun", 1.0, OVERCAST, CLEAR),
        Scenario("unforecast_sun", 1.0, CLEAR, OVERCAST),
        Scenario("mixed_week", 3.0, MIXED, MIXED, 450.0, 450.0),
        Scenario("false_sun_cold", -3.0, DARK, CLEAR, 0.0, 600.0),
    )
}
SUNNY: Final = ("sunny_cold", "sunny_mild")
STRESS_SCENARIOS: Final = ("false_sun_cold",)

MODEL_VARIANTS: Final[Mapping[str, Scale]] = {
    CORRECT: {},
    "ua_x0.7": {"h_air_out": 0.7},
    "ua_x1.4": {"h_air_out": 1.4},
    "aperture_x0.5": {"solar_aperture_m2": 0.5},
    "aperture_x2": {"solar_aperture_m2": 2.0},
    "mass_x0.5": {"c_mass": 0.5, "c_air": 0.5},
    "mass_x2": {"c_mass": 2.0, "c_air": 2.0},
}
CREDIBLE_MODELS: Final = (CORRECT, "ua_x0.7", "ua_x1.4")
STRESS_MODELS: Final = ("aperture_x0.5", "aperture_x2")
DEFAULT_MODELS: Final = CREDIBLE_MODELS + STRESS_MODELS
HOUSE_FIELDS: Final = (
    "c_water",
    "c_mass",
    "c_air",
    "h_water_mass",
    "h_water_air",
    "h_mass_air",
    "h_air_out",
    "solar_aperture_m2",
    "solar_mass_fraction",
    "q_int_w",
    "q_int_modulation",
    "q_int_peak_hour",
)


def true_model() -> HouseModel:
    """Return the reference plant's building as a :class:`HouseModel`."""
    return HouseModel(**{name: getattr(REFERENCE_BUILDING, name) for name in HOUSE_FIELDS})


def variant_model(name: str) -> HouseModel:
    """Return the planner's house model of a model variant (the truth, scaled)."""
    truth = true_model()
    scaled = {field: getattr(truth, field) * k for field, k in MODEL_VARIANTS[name].items()}
    return replace(truth, **scaled)


def controller_config() -> OvenbirdConfig:
    """Return the controller configuration of every baseline run."""
    return OvenbirdConfig.preset(EMITTER, comfort_room_c=COMFORT_C)


def credible(scenario: str, model: str, forecast: str) -> bool:
    """Whether a cell is credible (must pass) rather than a stress cell (must not fail)."""
    return (
        scenario not in STRESS_SCENARIOS and model in CREDIBLE_MODELS and forecast in BASE_FORECASTS
    )


def draw(seed: int, replica: int, salt: int, index: int = 0) -> float:
    """Return a uniform draw in [0, 1) that depends only on its four arguments."""
    return float(np.random.default_rng([seed, replica, salt, index]).random())


def normal(seed: int, replica: int, salt: int, index: int = 0) -> float:
    """Return a standard-normal draw that depends only on its four arguments."""
    return float(np.random.default_rng([seed, replica, salt, index]).standard_normal())


def derived_seed(seed: int, replica: int, salt: int, extra: int = 0) -> int:
    """Return an integer seed for a whole stream (sensor noise, forecast error)."""
    return int(np.random.SeedSequence([seed, replica, salt, extra]).generate_state(1)[0])


def _between(u: float, bounds: tuple[float, float]) -> float:
    return bounds[0] + u * (bounds[1] - bounds[0])


@dataclass(frozen=True, slots=True)
class Replica:
    """The draws of one weather replica (see the module docstring).

    Parameters
    ----------
    seed, index
        Identity of the replica.
    mean_offset_k
        Offset of the outside temperature from the scenario's mean.
    swing_k
        Daily swing (sine amplitude) per day.
    drift_k
        Day-to-day drift per day (AR(1)).
    clear_u
        Uniform draw per day for the clearness (or the overcast factor).
    sun_shift_h
        Shift of the sunrise of the half sine per day.
    clear_day
        Whether a ``mixed`` day is clear.
    t_mass_c
        Initial slab (mass) temperature.
    front_shift_h
        Shift of the cold front.
    """

    seed: int
    index: int
    mean_offset_k: float
    swing_k: tuple[float, ...]
    drift_k: tuple[float, ...]
    clear_u: tuple[float, ...]
    sun_shift_h: tuple[float, ...]
    clear_day: tuple[bool, ...]
    t_mass_c: float
    front_shift_h: float

    def sensor_seed(self, salt: int = 0) -> int:
        """Return the sensor-noise seed (``salt`` != 0: another, equally likely one)."""
        return derived_seed(self.seed, self.index, SALT_SENSOR, salt)

    def forecast_seed(self) -> int:
        """Return the seed of the forecast error."""
        return derived_seed(self.seed, self.index, SALT_FORECAST)


def replica(seed: int, index: int, days: int) -> Replica:
    """Return the draws of replica ``index`` for ``days`` days.

    Parameters
    ----------
    seed
        Base seed of the evaluation (non-negative).
    index
        Replica number (non-negative).
    days
        Number of days.

    Returns
    -------
    Replica
        The draws; those of day ``d`` do not depend on ``days``.

    Raises
    ------
    ValueError
        When ``seed`` or ``index`` is negative.
    """
    if seed < 0 or index < 0:
        raise ValueError("seed and replica index must be non-negative")
    innovation = DRIFT_SD_K * math.sqrt(1.0 - DRIFT_PHI * DRIFT_PHI)
    drift: list[float] = []
    for day in range(days):
        z = normal(seed, index, SALT_DRIFT, day)
        drift.append(DRIFT_SD_K * z if day == 0 else DRIFT_PHI * drift[-1] + innovation * z)
    return Replica(
        seed=seed,
        index=index,
        mean_offset_k=MEAN_JITTER_K * (2.0 * draw(seed, index, SALT_MEAN) - 1.0),
        swing_k=tuple(
            _between(draw(seed, index, SALT_SWING, d), SWING_RANGE_K) for d in range(days)
        ),
        drift_k=tuple(drift),
        clear_u=tuple(draw(seed, index, SALT_CLEAR, d) for d in range(days)),
        sun_shift_h=tuple(
            SUN_SHIFT_H * (2.0 * draw(seed, index, SALT_SUN, d) - 1.0) for d in range(days)
        ),
        clear_day=tuple(draw(seed, index, SALT_SKY, d) < MIXED_CLEAR_P for d in range(days)),
        t_mass_c=_between(draw(seed, index, SALT_MASS), MASS_RANGE_C),
        front_shift_h=FRONT_SHIFT_H * (2.0 * draw(seed, index, SALT_FRONT) - 1.0),
    )


def _day_peaks(sky: str, clear_peak: float, rep: Replica, days: int) -> FloatArray:
    peaks = np.zeros(days)
    for day in range(days):
        u = rep.clear_u[day]
        clear = sky == CLEAR or (sky == MIXED and rep.clear_day[day])
        if clear:
            peaks[day] = clear_peak * _between(u, CLEARNESS_RANGE)
        elif sky in (OVERCAST, MIXED):
            peaks[day] = OVERCAST_PEAK * _between(u, OVERCAST_RANGE)
    return peaks


def _sun(elapsed_h: FloatArray, peaks: FloatArray, rep: Replica, shift_h: float) -> FloatArray:
    day = np.floor(elapsed_h / DAY_H).astype(np.int64)
    start = SUN_START_H + np.asarray(rep.sun_shift_h)[day] + shift_h
    local = elapsed_h - day * DAY_H
    inside = (local >= start) & (local <= start + SUN_HOURS)
    shape = np.sin(math.pi * (local - start) / SUN_HOURS)
    return np.where(inside, peaks[day] * shape, 0.0)


def _outside(scenario: Scenario, rep: Replica, elapsed_h: FloatArray, days: int) -> FloatArray:
    centres = DAY_H * (np.arange(days) + 0.5)
    swing = np.interp(elapsed_h, centres, np.asarray(rep.swing_k[:days]))
    drift = np.interp(elapsed_h, centres, np.asarray(rep.drift_k[:days]))
    hours = elapsed_h % DAY_H
    daily = swing * np.sin(2.0 * math.pi * (hours - SWING_MIN_H) / DAY_H)
    level = np.full(elapsed_h.shape, scenario.mean_c + rep.mean_offset_k)
    if scenario.front:
        start = FRONT_DAY * DAY_H + FRONT_FROM_H + rep.front_shift_h
        end = FRONT_DAY * DAY_H + FRONT_TO_H + rep.front_shift_h
        level = level - np.interp(elapsed_h, [start, end], [0.0, FRONT_DROP_K])
    return np.asarray(level + daily + drift, dtype=np.float64)


def build_weather(
    scenario: Scenario, rep: Replica, days: int, forecast_shift_h: float = 0.0
) -> tuple[Weather, FloatArray]:
    """Return the delivered weather of a replica and the irradiance its forecast announces.

    Parameters
    ----------
    scenario
        The scenario.
    rep
        The replica's draws.
    days
        Number of simulated days.
    forecast_shift_h
        Shift of the forecast sun against its own timing (negative: earlier).

    Returns
    -------
    tuple
        The weather per tick and the forecast irradiance per tick.

    Raises
    ------
    ValueError
        When the replica was drawn for fewer days.
    """
    if len(rep.swing_k) < days:
        raise ValueError(f"replica drawn for {len(rep.swing_k)} days, {days} requested")
    n = days * round(86400.0 / TICK_S)
    elapsed_h = np.arange(n, dtype=np.float64) * TICK_S / 3600.0
    truth = _sun(elapsed_h, _day_peaks(scenario.sky, scenario.clear_peak, rep, days), rep, 0.0)
    announced = _sun(
        elapsed_h,
        _day_peaks(scenario.forecast_sky, scenario.forecast_peak, rep, days),
        rep,
        forecast_shift_h,
    )
    weather = Weather(
        T0, TICK_S, _outside(scenario, rep, elapsed_h, days), truth, elapsed_h % DAY_H
    )
    return weather, announced


def forecast_view(
    forecast: str, weather: Weather, announced: FloatArray, rep: Replica
) -> TableForecast:
    """Return the forecast table a planner reads in a forecast variant."""
    if forecast not in FORECAST_SHIFT_H:
        raise ValueError(f"unknown forecast variant {forecast!r}")
    table = hourly_table(weather, announced)
    if forecast == NOISY:
        return replace(table, error=ForecastError(seed=rep.forecast_seed()))
    return table


@dataclass(frozen=True, slots=True)
class ArmContext:
    """What a planner factory gets to build its arm.

    Parameters
    ----------
    controller
        The baseline controller configuration.
    model
        The planner's house model (a model variant).
    params
        Planner parameters (``--param name=value``).
    cell
        ``scenario/model/forecast`` of the cell the arm runs in.
    """

    controller: OvenbirdConfig
    model: HouseModel
    params: Mapping[str, float]
    cell: str = ""


@dataclass(frozen=True, slots=True)
class Arm:
    """The planned side of a pair.

    Parameters
    ----------
    controller
        Controller configuration of the run.
    provider
        The closed loop's plan provider (``None``: no calls).
    sensor_salt
        Non-zero: the sensor noise is drawn from another seed of the replica.
    applied_key
        Key of the decision record's ``controller_state`` that holds the plan offset
        the controller applied (the plan-share and offset KPIs).
    fixed_offset_k
        An offset applied on every tick outside the controller's state (the
        plan-share and offset KPIs), or ``None``.
    """

    controller: OvenbirdConfig
    provider: PlanProvider | None = None
    sensor_salt: int = 0
    applied_key: str = MODEL_PLAN_APPLIED_KEY
    fixed_offset_k: float | None = None


type PlannerFactory = Callable[[ArmContext], Arm]


@dataclass(frozen=True, slots=True)
class OffsetPlanner:
    """The v1 planner call as a closed-loop provider.

    Parameters
    ----------
    model
        The planner's house model.
    config
        Planner settings.
    """

    model: HouseModel
    config: PlannerConfig

    def __call__(self, request: PlanRequest) -> PlanSlice | None:
        """Return the slice for the request, ``None`` when the planner issues none."""
        result = plan_offset(
            self.model,
            request.forecast.rows(request.now),
            request.now,
            request.outside_filtered_c,
            self.config,
            request.previous_offset_k,
        )
        return result.slice


def none_arm(ctx: ArmContext) -> Arm:
    """Return the null planner: the controller as it is, no plan calls."""
    return Arm(ctx.controller)


def noise_arm(ctx: ArmContext) -> Arm:
    """Return the noise null: no plan calls, the sensor noise from another seed.

    The other seed differs per cell (and with the parameter ``salt``), so every cell
    gets its own, independent controller-irrelevant perturbation, as every cell of a
    real planner diverges from the baseline in its own way.
    """
    salt = int(ctx.params.get("salt", 0.0))
    return Arm(ctx.controller, sensor_salt=1 + zlib.crc32(f"{ctx.cell}|{salt}".encode()))


def v1_arm(ctx: ArmContext) -> Arm:
    """Return the v1 room-target planner; parameters are :class:`PlannerConfig` fields."""
    config = PlannerConfig.for_controller(ctx.controller, **dict(ctx.params))
    return Arm(ctx.controller, OffsetPlanner(ctx.model, config))


CONST_WATER_K: Final = -3.0


def lowered_curve(curve: HeatingCurve, offset_k: float) -> HeatingCurve:
    """Return ``curve`` with every water temperature moved by ``offset_k``."""
    return HeatingCurve(tuple(CurvePoint(p.outside_c, p.water_c + offset_k) for p in curve.points))


def const_water_arm(ctx: ArmContext) -> Arm:
    """Return a constant, ungated water offset (parameter ``offset_k``, default -3 K).

    The heating curve of the controller is moved by the offset, so the offset enters
    the sum of the terms (curve + room feedback + ...) before safety, rounding and
    dwell, on every tick, whatever the room, the sun or the forecast do. The safety
    envelope stays the preset's.
    """
    offset = float(ctx.params.get("offset_k", CONST_WATER_K))
    config = replace(ctx.controller, curve=lowered_curve(ctx.controller.curve, offset))
    return Arm(config, fixed_offset_k=offset)


CONST_ROOM_K: Final = -0.3
CONST_ROOM_SLICE_S: Final = 1200.0


@dataclass(frozen=True, slots=True)
class ConstantRoomPlanner:
    """A model plan that shifts the room target by a constant on every call.

    Parameters
    ----------
    offset_k
        The room-target offset (the controller clamps it to its bounds).
    """

    offset_k: float

    def __call__(self, request: PlanRequest) -> PlanSlice | None:
        """Return the constant slice from ``request.now``."""
        reason = ReasonCode.PLAN_SETBACK if self.offset_k < 0.0 else ReasonCode.PLAN_PREHEAT
        return PlanSlice(
            self.offset_k,
            reason,
            request.now,
            request.now.shifted(CONST_ROOM_SLICE_S),
            PlanSource.MODEL,
        )


def const_room_arm(ctx: ArmContext) -> Arm:
    """Return a constant room-target shift (parameter ``offset_k``, default -0.3 K).

    The forecast-blind counterpart of ``v1``: the same channel and the same
    controller rules, but no forecast and no model, so a benefit it shows is a
    lower room target, not foresight.
    """
    return Arm(ctx.controller, ConstantRoomPlanner(float(ctx.params.get("offset_k", CONST_ROOM_K))))


V2_APPLIED_KEY: Final = "model_plan_water_applied_k"


@dataclass(frozen=True, slots=True)
class WaterPlanner:
    """The v2 water feed-forward planner call as a closed-loop provider.

    Parameters
    ----------
    model
        The planner's house model.
    config
        Water-planner settings.
    """

    model: HouseModel
    config: WaterPlannerConfig

    def __call__(self, request: PlanRequest) -> PlanSlice | None:
        """Return the slice for the request; the previous water offset is the valid slice's."""
        previous = request.previous_slice
        result = plan_water(
            self.model,
            request.forecast.rows(request.now),
            request.now,
            request.outside_filtered_c,
            self.config,
            previous.water_offset_k if previous is not None else 0.0,
        )
        return result.slice


def v2_arm(ctx: ArmContext) -> Arm:
    """Return the v2 water feed-forward planner (the extension point of new planners).

    A planner arm is ``Arm(controller, provider, applied_key=...)``. The provider
    ``(request: PlanRequest) -> PlanSlice | None`` is called every 900 s of simulated
    time with ``request.now``, ``request.forecast.rows(request.now)`` (the stored
    forecast from 25 h before ``now`` to 14 h after it), ``request.outside_filtered_c``,
    ``request.previous_slice`` (the previous call's slice while it is valid, else
    ``None``), ``request.previous_offset_k`` (its room offset) and ``request.room_c``
    (the controller's room value); ``ctx.model`` is the planner's house model and
    ``ctx.params`` its parameters. ``applied_key`` names the ``controller_state`` key
    in which the controller records the offset it applied. Here: :func:`~ovenbird_core.
    control.planner.plan_water` with :class:`WaterPlannerConfig` fields as parameters
    (``lead_h``, ``gain``, ...).
    """
    config = WaterPlannerConfig.for_controller(ctx.controller, **dict(ctx.params))
    return Arm(ctx.controller, WaterPlanner(ctx.model, config), applied_key=V2_APPLIED_KEY)


PLANNERS: Final[Mapping[str, PlannerFactory]] = {
    "none": none_arm,
    "noise": noise_arm,
    "v1": v1_arm,
    "const_water": const_water_arm,
    "const_room": const_room_arm,
    "v2": v2_arm,
}
SWEEPS: Final[Mapping[str, tuple[Mapping[str, float], ...]]] = {
    "v1": (
        {},
        {"gain": 0.3, "dead_zone_k": 0.3},
        {"max_setback_k": 0.0},
        {"max_preheat_k": 0.0},
    ),
    "v2": ({"lead_h": 0.5}, {"lead_h": 3.0}),
    "const_water": ({"offset_k": -1.0}, {"offset_k": -3.0}),
}


def params_of(values: Mapping[str, float]) -> Params:
    """Return planner parameters in their hashable, sorted form."""
    return tuple(sorted((str(k), float(v)) for k, v in values.items()))


def params_label(params: Params) -> str:
    """Return parameters as ``name=value`` text (``defaults`` when empty)."""
    return " ".join(f"{k}={v:g}" for k, v in params) or "defaults"


def build_arm(
    planner: str, model: str, params: Params, forecast: str = PERFECT, scenario: str = ""
) -> Arm:
    """Return the arm of a planner in a cell (scenario, model variant, forecast variant).

    Raises
    ------
    KeyError
        When the planner is not in :data:`PLANNERS`.
    """
    if planner not in PLANNERS:
        raise KeyError(f"unknown planner {planner!r}; known: {', '.join(PLANNERS)}")
    context = ArmContext(
        controller_config(), variant_model(model), dict(params), f"{scenario}/{model}/{forecast}"
    )
    return PLANNERS[planner](context)


@dataclass(frozen=True, slots=True)
class RunSpec:
    """One simulation (hashable: the spec is its own cache key).

    Parameters
    ----------
    scenario
        Scenario name.
    replica
        Replica number.
    days
        Simulated days (the first is dropped from the KPIs).
    seed
        Base seed.
    planner
        Planner name (``None``: the baseline).
    params
        Planner parameters.
    model
        Model variant of the planner.
    forecast
        Forecast variant.
    """

    scenario: str
    replica: int
    days: int
    seed: int = DEFAULT_SEED
    planner: str | None = None
    params: Params = ()
    model: str = CORRECT
    forecast: str = PERFECT

    @property
    def baseline(self) -> RunSpec:
        """The spec of the paired baseline run."""
        return RunSpec(self.scenario, self.replica, self.days, self.seed)


@dataclass(slots=True)
class _Applied:
    key: str
    values: FloatArray

    def __call__(self, k: int, result: StepResult[Any]) -> None:
        value = result.decision.controller_state.get(self.key)
        if isinstance(value, int | float):
            self.values[k] = float(value)


def run_one(spec: RunSpec) -> RunResult:
    """Simulate one run and return its KPIs (top-level so a process pool can run it)."""
    scenario = SCENARIOS[spec.scenario]
    rep = replica(spec.seed, spec.replica, spec.days)
    weather, announced = build_weather(
        scenario, rep, spec.days, FORECAST_SHIFT_H[spec.forecast] if spec.planner else 0.0
    )
    arm = (
        Arm(controller_config())
        if spec.planner is None
        else build_arm(spec.planner, spec.model, spec.params, spec.forecast, spec.scenario)
    )
    sensors = SensorModel(
        outside_noise_k=OUTSIDE_NOISE_K,
        seed=rep.sensor_seed(arm.sensor_salt),
        room=RoomSensorModel(noise_k=ROOM_NOISE_K),
    )
    options = LoopOptions(initial_setpoint=INITIAL_SETPOINT, sensors=sensors)
    if arm.provider is not None:
        options = replace(
            options,
            plan_provider=arm.provider,
            plan_forecast=forecast_view(spec.forecast, weather, announced, rep),
        )
    applied = _Applied(arm.applied_key, np.zeros(weather.n))
    start = initial_state(REFERENCE_PARAMS, COMFORT_C, t_mass=rep.t_mass_c, t_water=INITIAL_WATER_C)
    trace = simulate(
        OvenbirdController(arm.controller), REFERENCE_PARAMS, weather, start, options, applied
    )
    offsets = (
        np.full(weather.n, arm.fixed_offset_k) if arm.fixed_offset_k is not None else applied.values
    )
    return plangate.run_result(trace, offsets, TICK_S, T0)


def run_all(
    specs: Iterable[RunSpec],
    workers: int | None = None,
    progress: Callable[[int, int], None] | None = None,
    known: Mapping[RunSpec, RunResult] | None = None,
) -> dict[RunSpec, RunResult]:
    """Run the specs (each distinct one once), in parallel, and return the results.

    Specs in ``known`` are not repeated; the result holds them too.
    """
    results: dict[RunSpec, RunResult] = dict(known or {})
    unique = [spec for spec in dict.fromkeys(specs) if spec not in results]
    count = workers if workers is not None else available_workers()
    if count <= 1 or len(unique) <= 1:
        for done, spec in enumerate(unique, start=1):
            results[spec] = run_one(spec)
            if progress is not None:
                progress(done, len(unique))
        return results
    with ProcessPoolExecutor(max_workers=count) as pool:
        for done, (spec, result) in enumerate(
            zip(unique, pool.map(run_one, unique, chunksize=1), strict=True), start=1
        ):
            results[spec] = result
            if progress is not None:
                progress(done, len(unique))
    return results


def available_workers() -> int:
    """Return the default number of worker processes."""
    return os.cpu_count() or 1


@dataclass(frozen=True, slots=True)
class CellId:
    """A scenario x model variant x forecast variant cell.

    Parameters
    ----------
    scenario, model, forecast
        The cell's identity.
    """

    scenario: str
    model: str
    forecast: str

    @property
    def credible(self) -> bool:
        """Whether the cell must pass (otherwise it is a stress cell: must not fail)."""
        return credible(self.scenario, self.model, self.forecast)

    @property
    def label(self) -> str:
        """``scenario/model/forecast``."""
        return f"{self.scenario}/{self.model}/{self.forecast}"


def cells(
    scenarios: Sequence[str],
    models: Sequence[str],
    forecasts: Sequence[str] = BASE_FORECASTS,
    shifts: Sequence[str] = SHIFT_FORECASTS,
) -> list[CellId]:
    """Return the cells of a grid.

    Every model variant meets every forecast in ``forecasts``; the shifted forecasts
    meet only the correct model (they stress the forecast, not the model), and only
    where the forecast has sun to shift.
    """
    out = [CellId(s, m, f) for s in scenarios for m in models for f in forecasts]
    out += [
        CellId(s, CORRECT, f)
        for s in scenarios
        for f in shifts
        if SCENARIOS[s].forecast_has_sun and CORRECT in models
    ]
    return sorted(out, key=lambda c: (list(scenarios).index(c.scenario), c.label))


def specs_for(
    cell: CellId,
    replicas: range,
    days: int,
    seed: int,
    planner: str,
    params: Params,
) -> list[RunSpec]:
    """Return the planned runs of a cell and their baselines over ``replicas``."""
    planned = [
        RunSpec(cell.scenario, r, days, seed, planner, params, cell.model, cell.forecast)
        for r in replicas
    ]
    return [s.baseline for s in planned] + planned

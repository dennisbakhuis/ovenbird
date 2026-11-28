"""Offline evaluation of the sun day shift: paired closed-loop runs over weather replicas.

**Design**
Every cell (scenario x arm) is simulated on the same weather replicas as the baseline
of its scenario (ovenbird without a plan): a replica fixes the weather, the forecast
error, the sensor noise and the initial slab temperature, so the arm is the only
difference within a pair. The rule is the service's own
:func:`ovenbird_core.control.dayshift.decide`, called every quarter hour of simulated
time with the controller's filtered outside temperature, the stored forecast as the
service would hold it and the room value the controller sees; its offset reaches the
controller as a ``rule`` plan slice valid for 20 minutes, as in the service runner.

**Time**
All clocks are local time in :data:`ZONE` (not UTC), so a window evaluated in the wrong
zone shows up as an hour's shift. A run starts at local midnight of :data:`START`
(early March: mild days with real sun are common, the heating still runs), lasts
:data:`DAYS` days and the first day is warm-up: every KPI is over the
:data:`KEPT_DAYS` days after it.

**Replicas**
A replica is drawn from ``(seed, replica)``; each quantity of a day is drawn from
``(seed, replica, quantity, day)`` alone (:func:`draw`), so a draw does not depend on
the scenario, the arm or the order of the calls. Per replica:

* outside temperature: the scenario's mean plus a constant offset uniform in
  +-``jitter_k``, a daily swing (sine amplitude, minimum at 03:00 and maximum at 15:00
  local) uniform in the scenario's swing range per day and a day-to-day drift, an
  AR(1) with coefficient :data:`DRIFT_PHI` and the scenario's standard deviation,
  interpolated between the day centres;
* sun: a half sine from :data:`SUN_START_H` for :data:`SUN_HOURS` (local), shifted
  uniform in +-:data:`SUN_SHIFT_H` per day; a clear day peaks at the scenario's peak
  times a clearness uniform in :data:`CLEARNESS_RANGE`, an overcast day at
  :data:`OVERCAST_PEAK` times a factor uniform in :data:`OVERCAST_RANGE`; a ``mixed``
  day is clear with probability :data:`MIXED_CLEAR_P`;
* the forecast: the announced sky and temperature with the seeded error model of
  :class:`~ovenbird_sim.evaluate.forecast.ForecastError` (day-level sun factor, day
  bias and hourly noise of the temperature, growing with the lead time);
* the pump's outside sensor gets Gaussian noise of :data:`OUTSIDE_NOISE_K` before its
  rounding to whole degrees; the living-room sensor is the example install's
  send-on-delta device; the initial slab temperature is uniform in
  :data:`MASS_RANGE_C`.

**Scenarios (:data:`SCENARIOS`)**
``sunny_mild`` (the intended case), ``sunny_cold`` (below the outside limit: the rule
must do nothing), ``cloudy_mild`` (no sun: must do nothing), ``mixed_week``,
``sun_missing`` (sun forecast, clouds arrive), ``sun_unforecast`` (clouds forecast,
sun arrives), ``cold_snap`` (sunny mild days, and in the nights after kept days 1, 3
and 5 the outside falls by :data:`SNAP_K` without the forecast knowing), and the
sunny mild weather on four other houses: ``low_mass`` and ``high_mass`` (all heat
capacities x0.5 and x2), ``large_windows`` and ``small_windows`` (solar aperture x2
and x0.5).

**Arms (:func:`arm_names`)**
``none`` (a provider that never plans: the pairing check), ``noise`` (no plan, the
sensor noise from another seed: the false-alarm check), ``const_setback`` (a
constant -1 K rule slice day and night: the gate must fail it on comfort) and one
``rule`` arm per setting of :data:`SWEEP`. The last setting, :data:`ORIGINAL_SETTING`,
is the default setting with the evaluation's fixes off (``fixes 0``): it shows what the
fixes changed and is never a candidate for the defaults (:func:`is_candidate`).
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo

import numpy as np

from ovenbird_core.control import OvenbirdConfig, OvenbirdController
from ovenbird_core.control.dayshift import (
    DayShiftInputs,
    DayShiftMemory,
    DayShiftParams,
    decide,
    rule_slice,
)
from ovenbird_core.control.forecast import HOUR_S
from ovenbird_core.control.types import PlanSlice, PlanSource, ReasonCode
from ovenbird_sim.data.series import FloatArray
from ovenbird_sim.evaluate.closedloop import (
    LoopOptions,
    PlanProvider,
    PlanRequest,
    Trace,
    Weather,
    simulate,
)
from ovenbird_sim.evaluate.forecast import ForecastError, TableForecast, hourly_table
from ovenbird_sim.evaluate.sensors import SensorModel, example_profile, example_room_sensor
from ovenbird_sim.heishamon.reference import REFERENCE_PARAMS
from ovenbird_sim.model.plant import PlantParams, initial_state

ZONE: Final = "Europe/Amsterdam"
START: Final = datetime(2026, 3, 2, tzinfo=ZoneInfo(ZONE))
T0: Final = START.timestamp()
TICK_S: Final = 60.0
DAY_S: Final = 86400.0
DAY_H: Final = 24.0
DAYS: Final = 8
WARMUP_DAYS: Final = 1
KEPT_DAYS: Final = DAYS - WARMUP_DAYS
DEFAULT_REPLICAS: Final = 24
DEFAULT_SEED: Final = 0
COMFORT_C: Final = 21.0
EMITTER: Final = "mixed"
INITIAL_SETPOINT: Final = 30
INITIAL_WATER_C: Final = 28.0
OUTSIDE_NOISE_K: Final = 0.3
MASS_RANGE_C: Final = (23.0, 26.0)
DRIFT_PHI: Final = 0.7
SWING_MIN_H: Final = 9.0
SUN_START_H: Final = 7.5
SUN_HOURS: Final = 10.5
SUN_SHIFT_H: Final = 0.5
CLEARNESS_RANGE: Final = (0.75, 1.0)
OVERCAST_PEAK: Final = 70.0
OVERCAST_RANGE: Final = (0.5, 1.4)
MIXED_CLEAR_P: Final = 0.5
SNAP_K: Final = 7.0
SNAP_DAYS: Final = (1, 3, 5)
SNAP_FALL_H: Final = (21.0, 25.0)
SNAP_RISE_H: Final = (32.0, 36.0)
CONST_SETBACK_K: Final = -1.0

SALT_MEAN: Final = 1
SALT_SWING: Final = 2
SALT_DRIFT: Final = 3
SALT_CLEAR: Final = 4
SALT_SUN: Final = 5
SALT_SKY: Final = 6
SALT_MASS: Final = 7
SALT_SENSOR: Final = 8
SALT_FORECAST: Final = 9

CLEAR: Final = "clear"
OVERCAST: Final = "overcast"
MIXED: Final = "mixed"


@dataclass(frozen=True, slots=True)
class Scenario:
    """A synthetic weather and house scenario (its character; the replicas vary it).

    Parameters
    ----------
    name
        Scenario name.
    description
        One plain sentence for the report.
    mean_c
        Mean outside temperature.
    sky
        Delivered sky: ``clear``, ``overcast`` or ``mixed``.
    forecast_sky
        Sky the forecast announces (``mixed`` days follow the delivered ones).
    clear_peak
        Peak irradiance of a clear day in W/m².
    jitter_k
        Half-width of the replica's constant offset of the outside temperature.
    swing_k
        Range of the daily swing (sine amplitude).
    drift_sd_k
        Standard deviation of the day-to-day drift.
    snap
        Cold snaps in the nights after :data:`SNAP_DAYS`, not in the forecast.
    house
        Factors on the reference building's parameters.
    must_idle
        The rule must never shift the target in this scenario.
    """

    name: str
    description: str
    mean_c: float
    sky: str
    forecast_sky: str
    clear_peak: float = 520.0
    jitter_k: float = 1.5
    swing_k: tuple[float, float] = (2.0, 4.0)
    drift_sd_k: float = 1.0
    snap: bool = False
    house: tuple[tuple[str, float], ...] = ()
    must_idle: bool = False


MILD_C: Final = 9.0
SCENARIOS: Final[Mapping[str, Scenario]] = {
    s.name: s
    for s in (
        Scenario("sunny_mild", "clear days around 9 °C (the intended case)", MILD_C, CLEAR, CLEAR),
        Scenario(
            "sunny_cold",
            "clear days around -1 °C, below the 5 °C limit",
            -1.0,
            CLEAR,
            CLEAR,
            jitter_k=1.0,
            swing_k=(1.5, 3.0),
            drift_sd_k=0.5,
            must_idle=True,
        ),
        Scenario(
            "cloudy_mild",
            "overcast days around 9 °C",
            MILD_C,
            OVERCAST,
            OVERCAST,
            must_idle=True,
        ),
        Scenario(
            "mixed_week", "each day clear or overcast at random, around 8 °C", 8.0, MIXED, MIXED
        ),
        Scenario(
            "sun_missing", "sun forecast every day, clouds arrive (9 °C)", MILD_C, OVERCAST, CLEAR
        ),
        Scenario(
            "sun_unforecast",
            "clouds forecast every day, sun arrives (9 °C)",
            MILD_C,
            CLEAR,
            OVERCAST,
        ),
        Scenario(
            "cold_snap",
            "sunny mild days; three nights fall by 7 K the forecast does not show",
            MILD_C,
            CLEAR,
            CLEAR,
            snap=True,
        ),
        Scenario(
            "low_mass",
            "sunny mild, a house with half the heat capacity",
            MILD_C,
            CLEAR,
            CLEAR,
            house=(("c_water", 0.5), ("c_mass", 0.5), ("c_air", 0.5)),
        ),
        Scenario(
            "high_mass",
            "sunny mild, a house with twice the heat capacity",
            MILD_C,
            CLEAR,
            CLEAR,
            house=(("c_water", 2.0), ("c_mass", 2.0), ("c_air", 2.0)),
        ),
        Scenario(
            "large_windows",
            "sunny mild, a house with twice the solar aperture",
            MILD_C,
            CLEAR,
            CLEAR,
            house=(("solar_aperture_m2", 2.0),),
        ),
        Scenario(
            "small_windows",
            "sunny mild, a house with half the solar aperture",
            MILD_C,
            CLEAR,
            CLEAR,
            house=(("solar_aperture_m2", 0.5),),
        ),
    )
}
QUICK_SCENARIOS: Final = ("sunny_mild", "cloudy_mild")

type Params = tuple[tuple[str, float], ...]


def params_of(values: Mapping[str, float]) -> Params:
    """Return rule settings in their hashable, sorted form."""
    return tuple(sorted((str(k), float(v)) for k, v in values.items()))


DEFAULT_SETTING: Final = params_of({"boost_k": 0.5, "setback_k": 0.5, "recovery_h": 4.0})
SETTING_KEYS: Final = frozenset({"boost_k", "setback_k", "recovery_h"})
ORIGINAL_SETTING: Final = params_of({**dict(DEFAULT_SETTING), "fixes": 0.0})


def _sweep() -> tuple[Params, ...]:
    """Return the swept settings: both halves, each half alone, then the rule before its fixes."""
    both = [
        params_of({"boost_k": b, "setback_k": s, "recovery_h": r})
        for b in (0.5, 1.0)
        for s in (0.5, 1.0)
        for r in (4.0, 5.0)
    ]
    boost_only = [
        params_of({"boost_k": b, "setback_k": 0.0, "recovery_h": 4.0}) for b in (0.5, 1.0)
    ]
    setback_only = [
        params_of({"boost_k": 0.0, "setback_k": s, "recovery_h": r})
        for s in (0.5, 1.0)
        for r in (4.0, 5.0)
    ]
    return (*both, *boost_only, *setback_only, ORIGINAL_SETTING)


SWEEP: Final = _sweep()
NONE: Final = "none"
NOISE: Final = "noise"
CONST: Final = "const_setback"
RULE: Final = "rule"
CALIBRATION_ARMS: Final = (NONE, NOISE, CONST)


def setting_label(params: Params) -> str:
    """Return a setting as ``boost 0.5 / set-back 0.5 / lead 4 h``."""
    values = dict(params)
    base = (
        f"boost {values['boost_k']:g} / set-back {values['setback_k']:g} / "
        f"lead {values['recovery_h']:g} h"
    )
    extra = [f"{k} {v:g}" for k, v in params if k not in ("boost_k", "setback_k", "recovery_h")]
    return " / ".join([base, *extra])


def is_candidate(params: Params) -> bool:
    """Return whether a setting is one the service can be set to (no screening extras)."""
    return {name for name, _ in params} == SETTING_KEYS


def setting_kind(params: Params) -> str:
    """Return ``both``, ``boost only`` or ``set-back only``."""
    values = dict(params)
    if values["setback_k"] == 0.0:
        return "boost only"
    if values["boost_k"] == 0.0:
        return "set-back only"
    return "both"


def rule_params(params: Params, zone: str = ZONE) -> DayShiftParams:
    """Return the rule's parameters of a setting in ``zone`` (the service's other defaults).

    ``fixes 0`` turns the evaluation's fixes off (the confirmed sun, the warm stop and
    the warm-room condition of the set-back), the rule as it was before this evaluation.
    """
    values = dict(params)
    found = DayShiftParams(
        boost_k=values["boost_k"],
        setback_k=values["setback_k"],
        recovery_s=values["recovery_h"] * HOUR_S,
        timezone=zone,
    )
    if values.get("fixes") == 0.0:
        found = replace(found, confirm_sun=False, warm_stop_k=None, setback_warm_k=None)
    if "warm_stop_k" in values:
        found = replace(found, warm_stop_k=values["warm_stop_k"])
    if "setback_warm_k" in values:
        found = replace(found, setback_warm_k=values["setback_warm_k"])
    if "confirm_sun" in values:
        found = replace(found, confirm_sun=bool(values["confirm_sun"]))
    return found


def draw(seed: int, replica: int, salt: int, index: int = 0) -> float:
    """Return a uniform draw in [0, 1) that depends only on its four arguments.

    Parameters
    ----------
    seed
        Run seed.
    replica
        Replica number.
    salt
        Identifier of the drawn quantity, keeping quantities independent.
    index
        Position within the quantity (e.g. the day).
    """
    return float(np.random.default_rng([seed, replica, salt, index]).random())


def normal(seed: int, replica: int, salt: int, index: int = 0) -> float:
    """Return a standard-normal draw that depends only on its four arguments.

    Parameters
    ----------
    seed
        Run seed.
    replica
        Replica number.
    salt
        Identifier of the drawn quantity, keeping quantities independent.
    index
        Position within the quantity (e.g. the day).
    """
    return float(np.random.default_rng([seed, replica, salt, index]).standard_normal())


def derived_seed(seed: int, replica: int, salt: int, extra: int = 0) -> int:
    """Return an integer seed for a whole stream (sensor noise, forecast error).

    Parameters
    ----------
    seed
        Run seed.
    replica
        Replica number.
    salt
        Identifier of the stream.
    extra
        Further discriminator of the stream.
    """
    return int(np.random.SeedSequence([seed, replica, salt, extra]).generate_state(1)[0])


def _between(u: float, bounds: tuple[float, float]) -> float:
    """Return the point ``u`` of the way through ``bounds``."""
    return bounds[0] + u * (bounds[1] - bounds[0])


def local_hours(t0: float, n: int, dt: float, zone: str = ZONE) -> FloatArray:
    """Return the local clock hour of every tick (the zone's offset at each hour).

    Parameters
    ----------
    t0
        Unix time of the first tick (s).
    n
        Number of ticks.
    dt
        Tick length (s).
    zone
        IANA time zone name.

    Returns
    -------
    FloatArray
        Hour of day in [0, 24) per tick.
    """
    tz = ZoneInfo(zone)
    t = t0 + dt * np.arange(n, dtype=np.float64)
    hours = np.floor(t / HOUR_S).astype(np.int64)
    offsets: dict[int, float] = {}
    shift = np.empty(n)
    for k, hour in enumerate(hours.tolist()):
        if hour not in offsets:
            offset = datetime.fromtimestamp(hour * HOUR_S, tz).utcoffset()
            offsets[hour] = 0.0 if offset is None else offset.total_seconds()
        shift[k] = offsets[hour]
    return np.asarray(((t + shift) % DAY_S) / HOUR_S, dtype=np.float64)


@dataclass(frozen=True, slots=True)
class Replica:
    """The weather and noise draws of one replica.

    Parameters
    ----------
    seed, index
        Identity of the replica.
    """

    seed: int
    index: int

    def u(self, salt: int, day: int = 0) -> float:
        """Return the uniform draw of a quantity of a day."""
        return draw(self.seed, self.index, salt, day)

    def drift(self, days: int, sd_k: float) -> FloatArray:
        """Return the AR(1) drift per day with stationary standard deviation ``sd_k``."""
        innovation = sd_k * math.sqrt(1.0 - DRIFT_PHI * DRIFT_PHI)
        out = np.zeros(days)
        for day in range(days):
            z = normal(self.seed, self.index, SALT_DRIFT, day)
            out[day] = sd_k * z if day == 0 else DRIFT_PHI * out[day - 1] + innovation * z
        return out

    def sensor_seed(self, salt: int = 0) -> int:
        """Return the sensor-noise seed (``salt`` != 0: another, equally likely one)."""
        return derived_seed(self.seed, self.index, SALT_SENSOR, salt)

    def forecast_seed(self) -> int:
        """Return the seed of the forecast error."""
        return derived_seed(self.seed, self.index, SALT_FORECAST)

    def t_mass_c(self) -> float:
        """Return the initial slab temperature."""
        return _between(self.u(SALT_MASS), MASS_RANGE_C)


def _peaks(sky: str, scenario: Scenario, rep: Replica, days: int) -> FloatArray:
    """Return the peak irradiance of every day of a sky.

    Parameters
    ----------
    sky
        Sky type of the scenario (clear, overcast or mixed).
    scenario
        The scenario, giving the clear-day peak.
    rep
        Replica that supplies the daily draws.
    days
        Number of days.

    Returns
    -------
    FloatArray
        Peak irradiance per day.
    """
    peaks = np.zeros(days)
    for day in range(days):
        u = rep.u(SALT_CLEAR, day)
        clear = sky == CLEAR or (sky == MIXED and rep.u(SALT_SKY, day) < MIXED_CLEAR_P)
        if clear:
            peaks[day] = scenario.clear_peak * _between(u, CLEARNESS_RANGE)
        else:
            peaks[day] = OVERCAST_PEAK * _between(u, OVERCAST_RANGE)
    return peaks


def _sun(hours: FloatArray, peaks: FloatArray, rep: Replica) -> FloatArray:
    """Return the irradiance per tick: a half sine per day with the replica's timing."""
    elapsed_day = np.floor(np.arange(hours.size) * TICK_S / DAY_S).astype(np.int64)
    shift = np.asarray([SUN_SHIFT_H * (2.0 * rep.u(SALT_SUN, d) - 1.0) for d in range(peaks.size)])
    start = SUN_START_H + shift[elapsed_day]
    inside = (hours >= start) & (hours <= start + SUN_HOURS)
    shape = np.sin(math.pi * (hours - start) / SUN_HOURS)
    return np.asarray(np.where(inside, peaks[elapsed_day] * shape, 0.0), dtype=np.float64)


def _outside(scenario: Scenario, rep: Replica, hours: FloatArray, days: int) -> FloatArray:
    """Return the outside temperature per tick without cold snaps.

    Parameters
    ----------
    scenario
        The scenario: mean, swing and drift of the temperature.
    rep
        Replica that supplies the draws.
    hours
        Local hour of day per tick.
    days
        Number of days.

    Returns
    -------
    FloatArray
        Outside temperature per tick (degC).
    """
    elapsed_h = np.arange(hours.size) * TICK_S / HOUR_S
    centres = DAY_H * (np.arange(days) + 0.5)
    swings = [_between(rep.u(SALT_SWING, d), scenario.swing_k) for d in range(days)]
    swing = np.interp(elapsed_h, centres, swings)
    drift = np.interp(elapsed_h, centres, rep.drift(days, scenario.drift_sd_k))
    daily = swing * np.sin(2.0 * math.pi * (hours - SWING_MIN_H) / DAY_H)
    level = scenario.mean_c + scenario.jitter_k * (2.0 * rep.u(SALT_MEAN) - 1.0)
    return np.asarray(level + daily + drift, dtype=np.float64)


def _snaps(n: int) -> FloatArray:
    """Return the cold-snap drop per tick (0 outside the snap nights)."""
    elapsed_h = np.arange(n) * TICK_S / HOUR_S
    drop = np.zeros(n)
    for day in SNAP_DAYS:
        base = day * DAY_H
        xs = [base + SNAP_FALL_H[0], base + SNAP_FALL_H[1], base + SNAP_RISE_H[0]]
        xs.append(base + SNAP_RISE_H[1])
        drop += np.interp(elapsed_h, xs, [0.0, SNAP_K, SNAP_K, 0.0], left=0.0, right=0.0)
    return drop


@dataclass(frozen=True, slots=True)
class Case:
    """The delivered weather of a replica and the forecast the rule reads.

    Parameters
    ----------
    weather
        Per-tick truth.
    forecast
        The stored forecast view.
    """

    weather: Weather
    forecast: TableForecast


def build_case(scenario: Scenario, rep: Replica, days: int) -> Case:
    """Return the weather and forecast of a replica in a scenario.

    Parameters
    ----------
    scenario
        The scenario.
    rep
        The replica.
    days
        Simulated days.

    Returns
    -------
    Case
        Truth per tick and the forecast table with the replica's error model.
    """
    n = days * round(DAY_S / TICK_S)
    hours = local_hours(T0, n, TICK_S)
    base = _outside(scenario, rep, hours, days)
    truth = base - _snaps(n) if scenario.snap else base
    sun = _sun(hours, _peaks(scenario.sky, scenario, rep, days), rep)
    announced = (
        sun
        if scenario.forecast_sky == scenario.sky
        else _sun(hours, _peaks(scenario.forecast_sky, scenario, rep, days), rep)
    )
    weather = Weather(T0, TICK_S, truth, sun, hours)
    told = hourly_table(replace(weather, outside_c=base), announced)
    forecast = replace(told, error=ForecastError(seed=rep.forecast_seed()))
    return Case(weather, forecast)


def plant_of(scenario: Scenario) -> PlantParams:
    """Return the reference plant with the scenario's house factors."""
    building = REFERENCE_PARAMS.building
    changes = {name: getattr(building, name) * k for name, k in scenario.house}
    return replace(REFERENCE_PARAMS, building=building.replace(**changes))


def controller_config() -> OvenbirdConfig:
    """Return the controller configuration of every run (mixed preset, example sensor)."""
    return OvenbirdConfig.preset(EMITTER, comfort_room_c=COMFORT_C, room=example_profile())


@dataclass(slots=True)
class RuleProvider:
    """The service's day shift rule as a closed-loop plan provider.

    Parameters
    ----------
    params
        Rule parameters.
    comfort_c
        Comfort room temperature.
    memory
        What the rule remembers between evaluations.
    """

    params: DayShiftParams
    comfort_c: float = COMFORT_C
    memory: DayShiftMemory = field(default_factory=DayShiftMemory)

    def __call__(self, request: PlanRequest) -> PlanSlice | None:
        """Evaluate the rule at ``request.now`` and return its slice (``None`` at 0)."""
        guards = () if request.room_c is not None else ("room_untrusted",)
        inputs = DayShiftInputs(
            now=request.now.wall,
            outside_c=request.outside_filtered_c,
            hours=request.forecast.rows(request.now),
            room_c=request.room_c,
            comfort_c=self.comfort_c,
            guards=guards,
        )
        result = decide(self.params, inputs, self.memory)
        self.memory = result.memory
        return rule_slice(result, request.now)


def never(request: PlanRequest) -> PlanSlice | None:
    """Return no slice (the do-nothing rule)."""
    del request
    return None


@dataclass(frozen=True, slots=True)
class ConstantProvider:
    """A rule slice of a constant offset on every call.

    Parameters
    ----------
    offset_k
        The room-target offset.
    """

    offset_k: float

    def __call__(self, request: PlanRequest) -> PlanSlice | None:
        """Return the constant slice from ``request.now`` for 20 minutes."""
        reason = ReasonCode.PLAN_SETBACK if self.offset_k < 0.0 else ReasonCode.PLAN_PREHEAT
        return PlanSlice(
            self.offset_k, reason, request.now, request.now.shifted(1200.0), PlanSource.RULE
        )


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
        Simulated days.
    seed
        Base seed.
    arm
        ``None`` (the baseline), a calibration arm or :data:`RULE`.
    params
        Rule setting of a ``rule`` arm.
    """

    scenario: str
    replica: int
    days: int = DAYS
    seed: int = DEFAULT_SEED
    arm: str | None = None
    params: Params = ()

    @property
    def baseline(self) -> RunSpec:
        """The spec of the paired baseline run."""
        return RunSpec(self.scenario, self.replica, self.days, self.seed)


def _provider(spec: RunSpec) -> PlanProvider | None:
    """Return the plan provider of a spec's arm (``None``: no calls)."""
    if spec.arm == RULE:
        return RuleProvider(rule_params(spec.params))
    if spec.arm == NONE:
        return never
    if spec.arm == CONST:
        return ConstantProvider(CONST_SETBACK_K)
    return None


def simulate_spec(spec: RunSpec) -> tuple[Trace, Weather]:
    """Simulate one spec and return its trace and weather."""
    scenario = SCENARIOS[spec.scenario]
    rep = Replica(spec.seed, spec.replica)
    case = build_case(scenario, rep, spec.days)
    config = controller_config()
    salt = 1 if spec.arm == NOISE else 0
    sensors = SensorModel(
        outside_noise_k=OUTSIDE_NOISE_K,
        seed=rep.sensor_seed(salt),
        room=example_room_sensor(config.room),
    )
    options = LoopOptions(initial_setpoint=INITIAL_SETPOINT, sensors=sensors)
    provider = _provider(spec)
    if provider is not None:
        options = replace(options, plan_provider=provider, plan_forecast=case.forecast)
    plant = plant_of(scenario)
    start = initial_state(plant, COMFORT_C, t_mass=rep.t_mass_c(), t_water=INITIAL_WATER_C)
    trace = simulate(OvenbirdController(config), plant, case.weather, start, options)
    return trace, case.weather


OCCUPIED_H: Final = (7.0, 23.0)
MORNING_H: Final = (7.0, 9.0)
BAND_K: Final = 0.5
OVERHEAT_K: Final = 1.5
KPIS: Final = (
    "below_occ_kh",
    "below_band_occ_kh",
    "below_morning_kh",
    "below_band_morning_kh",
    "above_kh",
    "starts",
    "night_run_h",
    "day_run_h",
    "elec_kwh",
    "night_elec_kwh",
    "day_elec_kwh",
    "heat_kwh",
    "cop",
    "writes",
    "quiet_nights",
    "room_mean_c",
    "room_min_occ_c",
    "boost_h",
    "setback_h",
)

type Row = Mapping[str, float]


def _within(hours: FloatArray, bounds: tuple[float, float]) -> FloatArray:
    """Return 1 where the local hour lies in ``[start, end)``, else 0."""
    return np.asarray((hours >= bounds[0]) & (hours < bounds[1]), dtype=np.float64)


def kpis(trace: Trace, weather: Weather, comfort_c: float = COMFORT_C) -> dict[str, float]:
    """Return the KPIs of a run over its kept days (totals per :data:`KEPT_DAYS` days).

    Parameters
    ----------
    trace
        The run.
    weather
        Its weather (local hours).
    comfort_c
        The owner's comfort target, the reference of every comfort KPI.

    Returns
    -------
    dict
        :data:`KPIS`. Night is 23:00 to 07:00 local, occupied hours 07:00 to 23:00,
        the morning 07:00 to 09:00; ``quiet_nights`` counts the full nights in the kept
        days without a compressor run.
    """
    hours = weather.local_hour
    kept = np.asarray(trace.t >= T0 + WARMUP_DAYS * DAY_S, dtype=np.float64)
    h = weather.dt / HOUR_S
    room = trace.room_c
    occupied = _within(hours, OCCUPIED_H) * kept
    morning = _within(hours, MORNING_H) * kept
    night = (1.0 - _within(hours, OCCUPIED_H)) * kept
    below = np.clip(comfort_c - room, 0.0, None)
    below_band = np.clip(comfort_c - BAND_K - room, 0.0, None)
    running = trace.running
    kwh = weather.dt / 3.6e6
    elec = float((trace.elec_w * kept).sum() * kwh)
    heat = float((trace.heat_w * kept).sum() * kwh)
    offsets = trace.plan_room_offset_k
    return {
        "below_occ_kh": float((below * occupied).sum() * h),
        "below_band_occ_kh": float((below_band * occupied).sum() * h),
        "below_morning_kh": float((below * morning).sum() * h),
        "below_band_morning_kh": float((below_band * morning).sum() * h),
        "above_kh": float((np.clip(room - comfort_c - OVERHEAT_K, 0.0, None) * kept).sum() * h),
        "starts": float((trace.start * kept).sum()),
        "night_run_h": float((running * night).sum() * h),
        "day_run_h": float((running * occupied).sum() * h),
        "elec_kwh": elec,
        "night_elec_kwh": float((trace.elec_w * night).sum() * kwh),
        "day_elec_kwh": float((trace.elec_w * occupied).sum() * kwh),
        "heat_kwh": heat,
        "cop": heat / elec if elec > 0.0 else math.nan,
        "writes": float((trace.write * kept).sum()),
        "quiet_nights": float(_quiet_nights(trace)),
        "room_mean_c": float(room[kept > 0].mean()),
        "room_min_occ_c": float(room[occupied > 0].min()),
        "boost_h": float(((offsets > 0.0) * kept).sum() * h),
        "setback_h": float(((offsets < 0.0) * kept).sum() * h),
    }


def _quiet_nights(trace: Trace) -> int:
    """Return the full nights (23:00 to 07:00) of the kept days without a compressor run."""
    elapsed = trace.t - T0
    count = 0
    for day in range(WARMUP_DAYS, DAYS - 1):
        start = day * DAY_S + 23 * HOUR_S
        mask = (elapsed >= start) & (elapsed < start + 8 * HOUR_S)
        if mask.any() and not trace.running[mask].any():
            count += 1
    return count


def offset_by_hour(trace: Trace, weather: Weather) -> list[float]:
    """Return the mean applied offset per local hour over the kept days (24 values)."""
    kept = trace.t >= T0 + WARMUP_DAYS * DAY_S
    hours = np.floor(weather.local_hour[kept]).astype(np.int64)
    offsets = trace.plan_room_offset_k[kept]
    return [float(offsets[hours == k].mean()) if (hours == k).any() else 0.0 for k in range(24)]


@dataclass(frozen=True, slots=True)
class RunResult:
    """KPIs of one run.

    Parameters
    ----------
    row
        :data:`KPIS` over the kept days.
    by_hour
        Mean applied offset per local hour.
    """

    row: Row
    by_hour: tuple[float, ...]


def run_one(spec: RunSpec) -> RunResult:
    """Simulate one run and return its KPIs (top-level so a process pool can run it)."""
    trace, weather = simulate_spec(spec)
    return RunResult(kpis(trace, weather), tuple(offset_by_hour(trace, weather)))


def available_workers() -> int:
    """Return the default number of worker processes (all cores but one)."""
    return max(1, (os.cpu_count() or 2) - 1)


def run_all(
    specs: Iterable[RunSpec],
    workers: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict[RunSpec, RunResult]:
    """Run every distinct spec once, in parallel, and return the results by spec."""
    unique = list(dict.fromkeys(specs))
    count = workers if workers is not None else available_workers()
    results: dict[RunSpec, RunResult] = {}
    if count <= 1 or len(unique) <= 1:
        for done, spec in enumerate(unique, start=1):
            results[spec] = run_one(spec)
            if progress is not None:
                progress(done, len(unique))
        return results
    with ProcessPoolExecutor(max_workers=count) as pool:
        for done, (spec, result) in enumerate(
            zip(unique, pool.map(run_one, unique, chunksize=4), strict=True), start=1
        ):
            results[spec] = result
            if progress is not None:
                progress(done, len(unique))
    return results


@dataclass(frozen=True, slots=True)
class Arm:
    """One arm of the evaluation.

    Parameters
    ----------
    name
        Calibration arm name or :data:`RULE`.
    params
        Rule setting (empty for a calibration arm).
    """

    name: str
    params: Params = ()

    @property
    def label(self) -> str:
        """``rule: boost 0.5 / ...`` or the calibration arm's name."""
        return f"rule: {setting_label(self.params)}" if self.name == RULE else self.name

    @property
    def calibration(self) -> bool:
        """Whether the arm is a calibration arm."""
        return self.name != RULE


def arms(sweep: Sequence[Params] = SWEEP, calibration: bool = True) -> list[Arm]:
    """Return the calibration arms (optional) and one rule arm per setting."""
    out = [Arm(name) for name in CALIBRATION_ARMS] if calibration else []
    return out + [Arm(RULE, params) for params in sweep]


def arm_names(sweep: Sequence[Params] = SWEEP) -> list[str]:
    """Return the labels of every arm."""
    return [arm.label for arm in arms(sweep)]


def specs_for(
    scenario: str, arm: Arm, replicas: int, days: int = DAYS, seed: int = DEFAULT_SEED
) -> list[RunSpec]:
    """Return the runs of an arm in a scenario and their baselines.

    Parameters
    ----------
    scenario
        Scenario name.
    arm
        The arm to evaluate.
    replicas
        Number of weather replicas.
    days
        Simulated days per run (the first is warm-up).
    seed
        Run seed.

    Returns
    -------
    list[RunSpec]
        The baselines of all replicas followed by the arm's runs.
    """
    planned = [RunSpec(scenario, r, days, seed, arm.name, arm.params) for r in range(replicas)]
    return [s.baseline for s in planned] + planned

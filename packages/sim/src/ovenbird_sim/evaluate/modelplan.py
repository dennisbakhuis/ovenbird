"""Offline evaluation of the model plan: paired closed-loop runs on the reference plant.

Every scenario is simulated twice (same plant, same sensor noise, same weather): once
with ovenbird as it is and once with the model planner in the loop, called every 900 s
the way the service will call it (previous offset carried, a slice expires after its
validity). The planner sees a forecast (:mod:`ovenbird_sim.evaluate.forecast`), not
the truth, and a house model that may differ from the plant. The KPIs of a pair and
the pass/fail gate are in :mod:`ovenbird_sim.evaluate.plangate`.

Scenarios (UTC clock, the first of the simulated days is dropped from the KPIs)
    ``sunny_cold``
        mean 1 °C, daily swing 3 K, clear sky, peak 350 W/m² irradiance.
    ``sunny_mild``
        mean 8 °C, clear sky, peak 600 W/m².
    ``cloudy``
        mean 1 °C, diffuse 80 W/m² peak.
    ``cold_front``
        8 °C, falling to 0 °C between 11:00 and 14:00 on day 4, 0 °C after; no sun.
    ``missing_sun``
        as ``cloudy``, but the forecast says clear (350 W/m² peak).
    ``unforecast_sun``
        as ``sunny_cold``, but the forecast says overcast (80 W/m² peak).

Model variants are the planner's house model with one set of parameters scaled against
the plant's truth: ``correct``, UA x0.7 / x1.4, solar aperture x0.5 / x2, thermal mass
x0.5 / x2 (``c_mass`` and ``c_air`` together). Forecast variants: ``perfect`` (the
scenario's forecast as defined above) and ``noisy`` (the :class:`ForecastError` model
on top, one seed per repeat).
"""

from __future__ import annotations

import math
import os
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from typing import Any, Final

import numpy as np

from ovenbird_core.control import OvenbirdConfig, OvenbirdController
from ovenbird_core.control.planner import PlannerConfig, plan_offset
from ovenbird_core.control.types import PlanSlice
from ovenbird_core.housemodel import HouseModel
from ovenbird_sim.data.series import FloatArray
from ovenbird_sim.evaluate import plangate
from ovenbird_sim.evaluate.closedloop import LoopOptions, PlanRequest, Weather, simulate
from ovenbird_sim.evaluate.forecast import ForecastError, TableForecast, hourly_table
from ovenbird_sim.evaluate.plangate import COMFORT_C, Row, RunKpis, Verdict
from ovenbird_sim.evaluate.sensors import SensorModel
from ovenbird_sim.heishamon.reference import REFERENCE_BUILDING, REFERENCE_PARAMS
from ovenbird_sim.model.plant import initial_state

T0: Final = 1_767_225_600.0
TICK_S: Final = 60.0
DEFAULT_DAYS: Final = 8
DEFAULT_SEEDS: Final = 3
EMITTER: Final = "mixed"
SUNNY: Final = ("sunny_cold", "sunny_mild")
CORRECT: Final = "correct"
PERFECT: Final = "perfect"
NOISY: Final = "noisy"
OVERCAST_PEAK: Final = 80.0
SUN_START_H: Final = 8.5
SUN_HOURS: Final = 8.0
SWING_K: Final = 3.0
FRONT_DAY: Final = 4
FRONT_FROM_H: Final = 11.0
FRONT_TO_H: Final = 14.0
FRONT_WARM_C: Final = 8.0
FRONT_COLD_C: Final = 0.0

type Scale = Mapping[str, float]


@dataclass(frozen=True, slots=True)
class Scenario:
    """A synthetic weather scenario.

    Parameters
    ----------
    name
        Scenario name.
    mean_c
        Mean outside temperature (ignored for the front).
    truth_peak
        Peak irradiance of the delivered sun in W/m².
    forecast_peak
        Peak irradiance of the forecast sun in W/m².
    front
        The outside temperature is the cold front.
    """

    name: str
    mean_c: float
    truth_peak: float
    forecast_peak: float
    front: bool = False


SCENARIOS: Final = {
    s.name: s
    for s in (
        Scenario("sunny_cold", 1.0, 350.0, 350.0),
        Scenario("sunny_mild", 8.0, 600.0, 600.0),
        Scenario("cloudy", 1.0, OVERCAST_PEAK, OVERCAST_PEAK),
        Scenario("cold_front", FRONT_WARM_C, 0.0, 0.0, front=True),
        Scenario("missing_sun", 1.0, OVERCAST_PEAK, 350.0),
        Scenario("unforecast_sun", 1.0, 350.0, OVERCAST_PEAK),
    )
}

MODEL_VARIANTS: Final[Mapping[str, Scale]] = {
    CORRECT: {},
    "ua_x0.7": {"h_air_out": 0.7},
    "ua_x1.4": {"h_air_out": 1.4},
    "aperture_x0.5": {"solar_aperture_m2": 0.5},
    "aperture_x2": {"solar_aperture_m2": 2.0},
    "mass_x0.5": {"c_mass": 0.5, "c_air": 0.5},
    "mass_x2": {"c_mass": 2.0, "c_air": 2.0},
}
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


@dataclass(frozen=True, slots=True)
class PlanSettings:
    """Planner settings varied by the sweep (the rest stay at the defaults).

    Parameters
    ----------
    gain
        Share of the predicted drift turned into an offset.
    max_setback_k
        Largest set-back (0: pre-heat only).
    max_preheat_k
        Largest pre-heat (0: set-back only).
    dead_zone_k
        Dead zone of the offset.
    """

    gain: float = 0.6
    max_setback_k: float = 0.5
    max_preheat_k: float = 0.3
    dead_zone_k: float = 0.2

    @property
    def label(self) -> str:
        """Short label such as ``g0.6 sb0.5 ph0.3 dz0.2``."""
        return (
            f"g{self.gain:g} sb{self.max_setback_k:g} ph{self.max_preheat_k:g} "
            f"dz{self.dead_zone_k:g}"
        )


DEFAULT_SETTINGS: Final = PlanSettings()


def controller_config() -> OvenbirdConfig:
    """Return the controller configuration of every run."""
    return OvenbirdConfig.preset(EMITTER, comfort_room_c=COMFORT_C)


def _sun(hours: FloatArray, peak: float) -> FloatArray:
    inside = (hours >= SUN_START_H) & (hours <= SUN_START_H + SUN_HOURS)
    shape = np.sin(math.pi * (hours - SUN_START_H) / SUN_HOURS)
    return np.where(inside, peak * shape, 0.0)


def build_weather(
    scenario: Scenario, days: int, jitter_k: float = 0.0
) -> tuple[Weather, FloatArray]:
    """Return the truth of a scenario and the irradiance its forecast announces.

    Parameters
    ----------
    scenario
        The scenario.
    days
        Number of simulated days.
    jitter_k
        Constant shift of the outside temperature (the sensitivity floor).

    Returns
    -------
    tuple
        The weather per tick and the forecast irradiance per tick.
    """
    n = days * round(86400.0 / TICK_S)
    elapsed_h = np.arange(n, dtype=np.float64) * TICK_S / 3600.0
    hours = elapsed_h % 24.0
    if scenario.front:
        start = FRONT_DAY * 24.0 + FRONT_FROM_H
        end = FRONT_DAY * 24.0 + FRONT_TO_H
        outside = np.interp(elapsed_h, [start, end], [FRONT_WARM_C, FRONT_COLD_C])
    else:
        outside = scenario.mean_c + SWING_K * np.sin(2.0 * math.pi * (hours - 9.0) / 24.0)
    weather = Weather(T0, TICK_S, outside + jitter_k, _sun(hours, scenario.truth_peak), hours)
    return weather, _sun(hours, scenario.forecast_peak)


@dataclass(frozen=True, slots=True)
class ModelPlanner:
    """The service's planner call as a provider of the closed loop.

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


@dataclass(frozen=True, slots=True)
class RunSpec:
    """One simulation.

    Parameters
    ----------
    scenario
        Scenario name.
    seed
        Seed of the sensor noise and of the forecast error.
    days
        Simulated days.
    model
        Model variant of the planner (``None``: no planner).
    forecast
        Forecast variant (ignored without a planner).
    settings
        Planner settings (ignored without a planner).
    jitter_k
        Constant shift of the true outside temperature (the sensitivity floor).
    """

    scenario: str
    seed: int
    days: int
    model: str | None = None
    forecast: str = PERFECT
    settings: PlanSettings = DEFAULT_SETTINGS
    jitter_k: float = 0.0

    @property
    def key(self) -> tuple[Any, ...]:
        """Identity of the run."""
        if self.model is None:
            return (self.scenario, self.seed, self.days, self.jitter_k)
        return (
            self.scenario,
            self.seed,
            self.days,
            self.model,
            self.forecast,
            self.settings,
            self.jitter_k,
        )


def forecast_table(spec: RunSpec, weather: Weather, forecast_ghi: FloatArray) -> TableForecast:
    """Return the forecast view a run's planner reads."""
    table = hourly_table(weather, forecast_ghi)
    if spec.forecast == NOISY:
        return replace(table, error=ForecastError(seed=spec.seed))
    if spec.forecast != PERFECT:
        raise ValueError(f"unknown forecast variant {spec.forecast!r}")
    return table


def run_one(spec: RunSpec) -> RunKpis:
    """Simulate one run and return its KPIs (top-level so a process pool can run it)."""
    weather, forecast_ghi = build_weather(SCENARIOS[spec.scenario], spec.days, spec.jitter_k)
    config = controller_config()
    options = LoopOptions(initial_setpoint=30, sensors=SensorModel(seed=spec.seed))
    if spec.model is not None:
        planner = PlannerConfig.for_controller(
            config,
            gain=spec.settings.gain,
            max_setback_k=spec.settings.max_setback_k,
            max_preheat_k=spec.settings.max_preheat_k,
            dead_zone_k=spec.settings.dead_zone_k,
        )
        options = replace(
            options,
            plan_provider=ModelPlanner(variant_model(spec.model), planner),
            plan_forecast=forecast_table(spec, weather, forecast_ghi),
        )
    start = initial_state(REFERENCE_PARAMS, COMFORT_C, t_mass=25.0, t_water=28.0)
    trace = simulate(OvenbirdController(config), REFERENCE_PARAMS, weather, start, options)
    return plangate.run_kpis(trace, TICK_S, T0)


def run_all(
    specs: Iterable[RunSpec],
    workers: int | None = None,
    progress: Callable[[int, int], None] | None = None,
    known: Mapping[tuple[Any, ...], RunKpis] | None = None,
) -> dict[tuple[Any, ...], RunKpis]:
    """Run the specs (once per distinct key), in parallel, and return the KPIs by key.

    Runs whose key is in ``known`` are not repeated; the result holds them too.
    """
    done_before = dict(known or {})
    unique = [
        spec for spec in {spec.key: spec for spec in specs}.values() if spec.key not in done_before
    ]
    count = workers if workers is not None else (os.cpu_count() or 1)
    results: dict[tuple[Any, ...], RunKpis] = dict(done_before)
    if count <= 1:
        for done, spec in enumerate(unique, start=1):
            results[spec.key] = run_one(spec)
            if progress is not None:
                progress(done, len(unique))
        return results
    with ProcessPoolExecutor(max_workers=count) as pool:
        for done, (spec, kpis) in enumerate(
            zip(unique, pool.map(run_one, unique, chunksize=1), strict=True), start=1
        ):
            results[spec.key] = kpis
            if progress is not None:
                progress(done, len(unique))
    return results


@dataclass(frozen=True, slots=True)
class Cell:
    """A scenario x model x forecast cell over its seeds.

    Parameters
    ----------
    scenario, model, forecast
        The cell's identity.
    without, with_plan
        Seed means of the KPI rows.
    verdict
        Gate result on the seed means.
    seeds_failing
        Number of seeds whose own pair fails the gate.
    seeds
        Number of seeds.
    intervals
        95 % day-block bootstrap interval (period total of with minus without) per
        degree-hour column.
    """

    scenario: str
    model: str
    forecast: str
    without: Row
    with_plan: Row
    verdict: Verdict
    seeds_failing: int
    seeds: int
    intervals: Mapping[str, tuple[float, float]]


def benefit_required(scenario: str, model: str) -> bool:
    """Whether the benefit criterion applies (sunny scenario, correct model)."""
    return scenario in SUNNY and model == CORRECT


def seeds_for(forecast: str, seeds: int) -> range:
    """Return the seeds of a forecast variant (a perfect forecast needs one)."""
    return range(1 if forecast == PERFECT else seeds)


def grid(
    scenarios: Sequence[str],
    models: Sequence[str],
    forecasts: Sequence[str],
    seeds: int,
    days: int,
    settings: PlanSettings = DEFAULT_SETTINGS,
) -> list[RunSpec]:
    """Return every run of a grid: the baselines and the planned runs."""
    specs: list[RunSpec] = []
    for scenario in scenarios:
        for forecast in forecasts:
            for seed in seeds_for(forecast, seeds):
                specs.append(RunSpec(scenario, seed, days))
                specs.extend(
                    RunSpec(scenario, seed, days, model, forecast, settings) for model in models
                )
    return specs


def collect(
    results: Mapping[tuple[Any, ...], RunKpis],
    scenarios: Sequence[str],
    models: Sequence[str],
    forecasts: Sequence[str],
    seeds: int,
    days: int,
    settings: PlanSettings = DEFAULT_SETTINGS,
) -> list[Cell]:
    """Combine the runs of a grid into cells (seed means, gate, intervals)."""
    cells: list[Cell] = []
    for scenario in scenarios:
        for model in models:
            for forecast in forecasts:
                base = [results[RunSpec(scenario, s, days).key] for s in seeds_for(forecast, seeds)]
                planned = [
                    results[RunSpec(scenario, s, days, model, forecast, settings).key]
                    for s in seeds_for(forecast, seeds)
                ]
                required = benefit_required(scenario, model)
                failing = sum(
                    not plangate.judge(a.row, b.row, required).passed
                    for a, b in zip(base, planned, strict=True)
                )
                mean_without = plangate.mean_row([a.row for a in base])
                mean_with = plangate.mean_row([b.row for b in planned])
                intervals = {
                    name: plangate.bootstrap_interval(
                        [
                            d
                            for a, b in zip(base, planned, strict=True)
                            for d in plangate.day_differences(a.days, b.days, name)
                        ],
                        period_days=len(base[0].days),
                    )
                    for name in plangate.DAY_COLUMNS
                }
                cells.append(
                    Cell(
                        scenario,
                        model,
                        forecast,
                        mean_without,
                        mean_with,
                        plangate.judge(mean_without, mean_with, required),
                        failing,
                        len(base),
                        intervals,
                    )
                )
    return cells


def sweep_settings() -> list[PlanSettings]:
    """Return the sweep: gain x set-back bound x dead zone, plus one-sided variants."""
    grid_ = [
        PlanSettings(gain=g, max_setback_k=sb, dead_zone_k=dz)
        for g in (0.3, 0.45, 0.6)
        for sb in (0.2, 0.3, 0.5)
        for dz in (0.2, 0.3)
    ]
    one_sided = [
        PlanSettings(max_setback_k=0.0),
        PlanSettings(max_preheat_k=0.0),
    ]
    return grid_ + one_sided


@dataclass(frozen=True, slots=True)
class SweepLine:
    """Outcome of one planner setting over every cell of the sweep.

    Parameters
    ----------
    settings
        The setting.
    cells
        Number of cells.
    failing
        ``scenario/model/forecast`` of the failing cells.
    above_gain_kh
        Reduction of the degree-hours above the band, summed over the sunny scenarios
        with the correct model and the perfect forecast (positive is better).
    below_change_kh
        Change of the degree-hours below comfort over the same cells.
    """

    settings: PlanSettings
    cells: int
    failing: tuple[str, ...]
    above_gain_kh: float
    below_change_kh: float


def sweep_line(settings: PlanSettings, cells: Sequence[Cell]) -> SweepLine:
    """Summarise the cells of one setting."""
    failing = tuple(
        f"{c.scenario}/{c.model}/{c.forecast}[{','.join(c.verdict.failed)}]"
        for c in cells
        if not c.verdict.passed
    )
    headline = [c for c in cells if benefit_required(c.scenario, c.model) and c.forecast == PERFECT]
    gain = sum(c.without["above_kh"] - c.with_plan["above_kh"] for c in headline)
    below = sum(c.with_plan["below_kh"] - c.without["below_kh"] for c in headline)
    return SweepLine(settings, len(cells), failing, gain, below)


def available_workers() -> int:
    """Return the default number of worker processes."""
    return os.cpu_count() or 1


def timed[T](work: Callable[[], T]) -> tuple[T, float]:
    """Return the result of ``work`` and its wall time in seconds."""
    start = time.monotonic()
    value = work()
    return value, time.monotonic() - start


def cells_to_json(cells: Sequence[Cell]) -> list[dict[str, Any]]:
    """Return the cells as JSON-ready dictionaries."""
    return [
        {
            "scenario": c.scenario,
            "model": c.model,
            "forecast": c.forecast,
            "seeds": c.seeds,
            "seeds_failing": c.seeds_failing,
            "passed": c.verdict.passed,
            "checks": {k.name: {"passed": k.passed, "detail": k.detail} for k in c.verdict.checks},
            "without": dict(c.without),
            "with": dict(c.with_plan),
            "interval_total_kh": {k: list(v) for k, v in c.intervals.items()},
        }
        for c in cells
    ]

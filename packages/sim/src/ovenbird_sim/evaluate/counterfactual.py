"""Counterfactual replay (closed loop): ovenbird against the recorded setpoints on the fitted plant.

The baseline is controller-agnostic: the plant of :mod:`ovenbird_sim.model` driven by
the recorded applied water setpoint of every tick
(:class:`~ovenbird_sim.evaluate.closedloop.RecordedSetpoints`, whatever wrote it).
Both runs go through :mod:`~ovenbird_sim.evaluate.closedloop` over the same recorded
weather (fused outside temperature, Open-Meteo irradiance, the model's internal-gain
profile by local hour), from the same initial plant state (the Kalman-filtered state
at the first tick), the same applied setpoint and the same sensor-noise sequence
(:mod:`~ovenbird_sim.evaluate.sensors`). Ovenbird gets the living-room sensor as Home
Assistant delivers it (:mod:`~ovenbird_sim.evaluate.sensors`: send-on-delta on its
own grid with noise and hysteresis calibrated to the recorded change rate and
reversal share, no heartbeat, recorded dropouts) under the configured room sensor
profile (the recorded install's: ``on_change``, held while the device is alive, with
the recorded humidity report times as liveness - exogenous, they do not follow the
simulated room). The steps:

1. **Baseline gates** - the plant on the recorded setpoints against the measured
   room temperature, heat and starts, in-sample (all days, parameters fitted on all
   days) and held-out (the test block, parameters fitted on the training block only,
   ``plant_params_train.json``); the UTC days a known event touches (a stove fire and
   its recovery tail, :mod:`ovenbird_sim.data.events`) are left out of the scoring and
   reported, with the gate on all days alongside
   (:func:`~ovenbird_sim.evaluate.claims.baseline_gate`), with the per-KPI fidelity in
   both and the starts with the plant restarted daily from the filtered state.
2. **Equal comfort** - ovenbird's room target is calibrated so its mean room
   temperature equals the baseline's (on the point estimate by bracketing and secant
   steps, then per replicate by one Newton step with the point slope); mean,
   occupied-hours P10 and degree-hours below the baseline's P10 are compared
   (:class:`~ovenbird_sim.evaluate.claims.ComfortMatch`).
3. **Uncertainty** - both runs on every bootstrap replicate of the plant parameters
   (:mod:`~ovenbird_sim.evaluate.ensemble`: every data-driven parameter refitted on a
   day-block resample); each replicate's paired difference is taken over its own
   day-block resample of the simulated days, so the 90 % interval combines parameter
   and weather (day) uncertainty. Parameter-only and day-only intervals are reported
   too.
4. **Attribution and sensitivity** - the 16-variant term ablation of ovenbird; runs
   with the COP warm-up term off, with the old steady-only COP map (how much of a
   difference the start-up model explains) and with other steady-start rules.
5. **Room sensor variants** - ovenbird at the calibrated target on an ideal sensor
   (always fresh, no noise), on the recorded sensor with today's 1800 s staleness
   (``periodic`` profile, no liveness) and with the configured profile (the point
   run), side by side with the share of ticks under room feedback.

The baseline replays the recorded setpoints open loop: it does not react to the
simulated room, so on a replicate whose house differs from the recording the
baseline's comfort drifts while ovenbird's corrects; the equal-comfort calibration
per replicate absorbs that in the comparison.

Runs are independent and deterministic; they are spread over worker processes and
collected by run id, so the result does not depend on the number of workers.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import numpy as np

from ovenbird_core.control.config import OvenbirdConfig, PumpDutyConfig, RoomSensorProfile
from ovenbird_core.control.ovenbird import OvenbirdController
from ovenbird_core.control.protocol import StepResult
from ovenbird_core.control.record import JsonDict, JsonValue
from ovenbird_sim import local
from ovenbird_sim.data import datalake as dl
from ovenbird_sim.data.capture import load_capture
from ovenbird_sim.data.dataset import Dataset, assemble, load_datalake
from ovenbird_sim.data.events import Event, day_mask, days_touched
from ovenbird_sim.data.series import FloatArray, Series
from ovenbird_sim.data.weather import load_weather
from ovenbird_sim.evaluate import ablation, kpi, meta
from ovenbird_sim.evaluate.claims import (
    COMFORT_KPI,
    ENVELOPE_TOLERANCE,
    UNRECORDED_CLAIMS,
    ComfortMatch,
    Difference,
    Envelope,
    Fidelity,
    GateBounds,
    GateResult,
    baseline_gate,
    cycling_reasons,
    envelope,
    fidelity,
    interval,
    judge,
)
from ovenbird_sim.evaluate.closedloop import (
    RECORDED_SETPOINTS,
    LoopOptions,
    RecordedSetpoints,
    Trace,
    Weather,
    simulate,
)
from ovenbird_sim.evaluate.ensemble import replicates as get_replicates
from ovenbird_sim.evaluate.kpi import TOTAL_KPIS, KpiTable
from ovenbird_sim.evaluate.recorded import ROOM_ENTITY
from ovenbird_sim.evaluate.resultdb import ResultDB, dump
from ovenbird_sim.evaluate.sensors import (
    Calibration,
    RoomSensorModel,
    SensorModel,
    calibrate,
    install_profile,
    smooth_level,
)
from ovenbird_sim.evaluate.support import (
    HZ_STEP,
    MIN_MINUTES,
    OUTLET_STEP_K,
    OUTSIDE_STEP_K,
    UNSUPPORTED_TOLERANCE,
    CopSupport,
    cop_support,
)
from ovenbird_sim.identify import io
from ovenbird_sim.identify.building import observations
from ovenbird_sim.identify.validate import filtered, humidity, plant_days, state_at
from ovenbird_sim.model.plant import PlantParams, PlantState
from ovenbird_sim.model.simulate import run as run_open_loop

DB_NAME: Final = "counterfactual.sqlite"
SUMMARY_NAME: Final = "counterfactual_summary.json"
SECONDS_PER_DAY: Final = 86400.0
COARSEN: Final = 5
EXAMPLE_TARGET_C: Final = local.EXAMPLE_COMFORT_C
BAND_K: Final = 0.5
TEST_BLOCK_DAYS: Final = 14
DEFAULT_SETPOINT: Final = 30
DEFAULT_DUTY: Final = 102
BASELINE: Final = RECORDED_SETPOINTS
OVENBIRD: Final = "ovenbird"
ASSUMED_CONFIRM_S: Final = math.inf
LIVENESS_ENTITY: Final = "sensor.living_room_humidity"
EXAMPLE_MIN_SETPOINT_C: Final = local.EXAMPLE_MIN_SETPOINT_C
EXAMPLE_DUTY: Final = PumpDutyConfig(
    heat=local.EXAMPLE_PUMP_DUTY_HEAT, idle=local.EXAMPLE_PUMP_DUTY_IDLE
)
CALIBRATION_OFFSETS_K: Final = (-0.6, -0.3, 0.0, 0.3, 0.6)
CALIBRATION_TOLERANCE_K: Final = 0.01
CALIBRATION_STEPS: Final = 3
REPLICATE_STEP_LIMIT_K: Final = 1.0
MIN_CALIBRATION_SLOPE: Final = 0.05
DAY_RESAMPLES: Final = 200


class ComfortMeasure(StrEnum):
    """What ovenbird's room target is calibrated on to reach equal comfort."""

    CHECK = "check"
    TAIL = "tail"
    MEAN = "mean"


@dataclass(frozen=True, slots=True)
class CounterfactualOptions:
    """Options of a counterfactual replay.

    Parameters
    ----------
    start, end
        Period in unix seconds (UTC day boundaries recommended); ``None``: every
        full UTC day of the dataset.
    comfort_c
        The recorded install's room target (ovenbird's comfort target, top of the band).
    band_k
        Width of the comfort band below the target.
    bootstrap
        Number of parameter replicates (0: point estimate only, no intervals).
    seed
        Seed of the replicates.
    workers
        Worker processes (``None``: CPU count, at most the number of runs).
    ablation
        Run the 16-variant term ablation.
    gate
        Baseline gate tolerances.
    envelope_tolerance
        Share of time a run may spend outside the recorded envelope.
    keep_records
        Store the point runs' decision records.
    sensor_noise
        Calibrate and apply the dither noise of the integer sensors.
    ovenbird_target_c
        Ovenbird's room target (``None``: ``comfort_c``).
    ovenbird_min_setpoint_c
        Ovenbird's lowest water setpoint (``None``: the preset's safety minimum).
    pump_duty
        Ovenbird's pump-duty intent (example: 159 heating / 102 idle, the controller's defaults).
    calibrate_target
        Calibrate ovenbird's room target to equal comfort with the baseline.
    comfort_measure
        What the calibration matches (:class:`TargetCalibration`): the comfort check
        as a whole (``check``), the degree-hours below the baseline's 10th percentile
        (``tail``) or the mean room temperature (``mean``).
    room_confirm_s
        Assumed heartbeat of an unchanged living-room value (a send-on-delta device has
        none: ``inf``).
    room_profile
        Room sensor profile ovenbird is configured with (the recorded install's
        ``on_change`` profile with the humidity as liveness signal by default).
    room_liveness
        Use the recorded humidity report times as the liveness signal.
    room_variants
        Run the room sensor variants (ideal, 1800 s, profile).
    train_params
        Train-only parameters for the held-out gate (``None``: ``*_train.json`` next
        to the parameters when present).
    sensitivity
        Run the sensitivity variants (COP map, steady-start rule).
    known_events
        Leave the UTC days touched by known events (stove fires and their recovery
        tails, :mod:`ovenbird_sim.data.events`) out of the gates, the fidelity and the
        sensor calibration; they are reported, and the gate on all days is kept.
    """

    start: float | None = None
    end: float | None = None
    comfort_c: float = EXAMPLE_TARGET_C
    band_k: float = BAND_K
    bootstrap: int = 0
    seed: int = 0
    workers: int | None = None
    ablation: bool = True
    gate: GateBounds = field(default_factory=GateBounds)
    envelope_tolerance: float = ENVELOPE_TOLERANCE
    keep_records: bool = False
    sensor_noise: bool = True
    ovenbird_target_c: float | None = None
    ovenbird_min_setpoint_c: float | None = None
    pump_duty: PumpDutyConfig | None = EXAMPLE_DUTY
    calibrate_target: bool = True
    comfort_measure: ComfortMeasure = ComfortMeasure.CHECK
    room_confirm_s: float = ASSUMED_CONFIRM_S
    room_profile: RoomSensorProfile = field(default_factory=install_profile)
    room_liveness: bool = True
    room_variants: bool = True
    train_params: Path | None = None
    sensitivity: bool = True
    known_events: bool = True

    @property
    def ovenbird_target(self) -> float:
        """Ovenbird's room target."""
        return self.comfort_c if self.ovenbird_target_c is None else self.ovenbird_target_c

    @property
    def band_low_c(self) -> float:
        """Lower edge of the comfort band."""
        return self.comfort_c - self.band_k


@dataclass(frozen=True, slots=True)
class Setup:
    """Recorded inputs of a replay period.

    Parameters
    ----------
    ds
        Dataset on the 60 s grid.
    i0, i1
        Bin range of the period.
    weather
        Exogenous inputs per tick.
    recorded_room
        Recorded room temperature per tick.
    recorded
        Recorded KPIs.
    setpoints
        Recorded applied water setpoint per tick (the baseline's input).
    initial_setpoint, initial_duty
        Applied settings before the first tick.
    setpoint_range, room_range
        Recorded envelope.
    events
        Known events left out of the scoring.
    excluded_days
        Days of the period left out of the gates and the fidelity.
    recorded_room_all
        Recorded room per tick including the excluded days (``recorded_room`` is
        ``NaN`` on them, so the room RMSE leaves them out).
    """

    ds: Dataset
    i0: int
    i1: int
    weather: Weather
    recorded_room: FloatArray
    recorded: KpiTable
    setpoints: tuple[int, ...]
    initial_setpoint: int
    initial_duty: int
    setpoint_range: tuple[float, float]
    room_range: tuple[float, float]
    events: tuple[Event, ...] = ()
    excluded_days: tuple[str, ...] = ()
    recorded_room_all: FloatArray | None = None

    @property
    def scored_days(self) -> list[str]:
        """Days of the period the gates and the fidelity are scored on."""
        return [d for d in self.recorded.days if d not in self.excluded_days]

    def scored(self, table: KpiTable) -> Mapping[str, float]:
        """Period KPIs of ``table`` on the scored days."""
        return table.subset(self.scored_days).totals if self.excluded_days else table.totals

    @property
    def start(self) -> float:
        """First tick."""
        return self.weather.t0

    @property
    def end(self) -> float:
        """End of the last tick."""
        return self.weather.t0 + self.weather.n * self.weather.dt


def _filled(x: FloatArray, fallback: float) -> FloatArray:
    ok = np.isfinite(x)
    if not ok.any():
        return np.full(x.shape, fallback)
    return np.interp(np.arange(x.size), np.flatnonzero(ok), x[ok])


def load_dataset(
    capture: Path, datalake: Path | None, weather: Path | None
) -> tuple[Dataset, dict[str, Series]]:
    """Assemble the 60 s dataset from a capture, the Datalake and the weather cache.

    Returns
    -------
    Dataset, dict
        The dataset and the raw capture series it was built from.
    """
    series = load_capture(capture)
    dataset = assemble(
        series,
        datalake=load_datalake(datalake) if datalake is not None and datalake.is_dir() else None,
        weather=load_weather(weather) if weather is not None and weather.is_dir() else None,
        step=60.0,
    )
    return dataset, series


def period(ds: Dataset, start: float | None, end: float | None) -> tuple[int, int]:
    """Bin range of the replay: full UTC days inside the dataset unless given."""
    first = start if start is not None else math.ceil(ds.grid.start / SECONDS_PER_DAY) * 86400.0
    last = end if end is not None else math.floor(ds.grid.end / SECONDS_PER_DAY) * 86400.0
    i0 = max(1, round((first - ds.grid.start) / ds.grid.step))
    i1 = min(ds.grid.n, round((last - ds.grid.start) / ds.grid.step))
    if i1 <= i0:
        raise ValueError("the replay period is empty")
    return i0, i1


def prepare(ds: Dataset, options: CounterfactualOptions) -> Setup:
    """Cut the recorded inputs, KPIs and envelope of the replay period.

    Parameters
    ----------
    ds
        Dataset on the 60 s grid.
    options
        Replay options.

    Returns
    -------
    Setup
        The period's recorded inputs.
    """
    i0, i1 = period(ds, options.start, options.end)
    c = ds.columns
    weather = Weather(
        t0=float(ds.t[i0]),
        dt=ds.grid.step,
        outside_c=_filled(c["outside"], 10.0)[i0:i1].copy(),
        ghi_w_m2=np.nan_to_num(c.get("ghi", np.zeros(ds.grid.n)), nan=0.0)[i0:i1].copy(),
        local_hour=c["local_hour"][i0:i1].copy(),
        rh_pct=humidity(ds)[i0:i1].copy(),
    )
    _, room = observations(ds)
    target = c["z1_target"][i0:i1]
    room_cut = room[i0:i1]
    setpoint = _filled(c["z1_target"], DEFAULT_SETPOINT)
    duty = c["max_pump_duty"][: i0 + 1]
    finite_duty = duty[np.isfinite(duty)]
    known = ds.events if options.known_events else ()
    recorded = kpi.compute(kpi.from_dataset(ds, i0, i1), options.band_low_c)
    touched = set(days_touched(known))
    excluded = tuple(d for d in recorded.days if d in touched)
    left_out = day_mask(ds.t[i0:i1], known)
    return Setup(
        ds=ds,
        i0=i0,
        i1=i1,
        weather=weather,
        recorded_room=np.where(left_out, np.nan, room_cut),
        recorded=recorded,
        setpoints=tuple(int(v) for v in np.round(setpoint[i0:i1])),
        initial_setpoint=round(float(setpoint[i0 - 1])),
        initial_duty=round(float(finite_duty[-1])) if finite_duty.size else DEFAULT_DUTY,
        setpoint_range=(float(np.nanmin(target)), float(np.nanmax(target))),
        room_range=(float(np.nanmin(room_cut)), float(np.nanmax(room_cut))),
        events=tuple(e for e in known if e.tail_end > weather.t0 and e.start < float(ds.t[i1 - 1])),
        excluded_days=excluded,
        recorded_room_all=room_cut.copy(),
    )


def initial_state(ds: Dataset, params: PlantParams, i0: int) -> PlantState:
    """Plant state at bin ``i0``: Kalman-filtered temperatures and the recorded switching state.

    Parameters
    ----------
    ds
        Dataset on the 60 s grid.
    params
        Plant parameters (the building layer drives the filter).
    i0
        First bin of the replay.

    Returns
    -------
    PlantState
        Initial state (:func:`ovenbird_sim.identify.validate.state_at`).
    """
    coarse = ds.coarsen(COARSEN)
    return state_at(ds, coarse, filtered(coarse, params.building), i0)


def filtered_room(ds: Dataset, params: PlantParams) -> FloatArray:
    """Kalman-filtered air temperature per 60 s bin (the smooth room reference)."""
    coarse = ds.coarsen(COARSEN)
    states = filtered(coarse, params.building)
    return np.asarray(np.interp(ds.t, coarse.t, states[: coarse.t.size, 2]), dtype=np.float64)


def ovenbird_config(
    comfort_c: float,
    min_setpoint_c: float | None = None,
    pump_duty: PumpDutyConfig | None = None,
    emitter: str = "mixed",
    room: RoomSensorProfile | None = None,
) -> OvenbirdConfig:
    """Return the preset with the given room target, minimum setpoint and pump duty.

    Built the way the service builds it (``controller_config``): the preset with the
    comfort target, pump duty and room sensor profile, then only the safety minimum
    replaced.
    """
    config = OvenbirdConfig.preset(
        emitter, comfort_room_c=comfort_c, pump_duty=pump_duty, room=room or RoomSensorProfile()
    )
    if min_setpoint_c is None:
        return config
    return replace(config, safety=replace(config.safety, min_setpoint_c=min_setpoint_c))


@dataclass(frozen=True, slots=True)
class RunSpec:
    """One closed-loop run.

    Parameters
    ----------
    run_id
        Unique id.
    controller
        Controller (picklable).
    params
        Plant parameters.
    initial
        Initial plant state.
    keep_trace
        Return the per-tick trace.
    keep_records
        Return the decision records as result-database rows.
    sensors
        Sensor model replacing the context's (sensitivity runs).
    """

    run_id: str
    controller: Any
    params: PlantParams
    initial: PlantState
    keep_trace: bool = False
    keep_records: bool = False
    sensors: SensorModel | None = None


@dataclass(frozen=True, slots=True)
class Context:
    """What every run shares.

    Parameters
    ----------
    weather
        Exogenous inputs.
    loop
        Loop options.
    recorded_room
        Recorded room per tick (for the RMSE).
    band_low_c
        Comfort band lower edge.
    setpoint_range, room_range
        Recorded envelope.
    cop_support
        Joint support of the COP map (``None``: not checked).
    """

    weather: Weather
    loop: LoopOptions
    recorded_room: FloatArray
    band_low_c: float
    setpoint_range: tuple[float, float]
    room_range: tuple[float, float]
    cop_support: CopSupport | None = None


@dataclass(frozen=True, slots=True)
class RunOutput:
    """Result of one run.

    Parameters
    ----------
    run_id
        Run id.
    kpis
        KPIs per day and in total.
    room_rmse_k
        RMSE of the simulated against the recorded room.
    envelope
        Time outside the recorded envelope.
    trace
        Per-tick trace (point runs only).
    records
        Decision-record rows (when requested).
    seconds
        Wall time of the run.
    room
        Room temperature per tick (float32; comfort statistics).
    room_fresh_share
        Share of ticks with a fresh room input.
    feedback_share
        Share of ticks with room feedback active.
    curve_only_share
        Share of ticks on the curve-only ladder level.
    steady_start_share
        Share of starts made by the pump's steady rule (not after a setpoint change).
    running_share
        Share of ticks with the compressor running (heating or defrost).
    cop_unsupported_share
        Heat-weighted share of heating ticks outside the COP map's joint support.
    """

    run_id: str
    kpis: KpiTable
    room_rmse_k: float
    envelope: Envelope
    trace: Trace | None
    records: tuple[tuple[object, ...], ...]
    seconds: float
    room: np.ndarray = field(default_factory=lambda: np.zeros(0, np.float32))
    room_fresh_share: float = math.nan
    feedback_share: float = math.nan
    curve_only_share: float = math.nan
    steady_start_share: float = math.nan
    running_share: float = math.nan
    cop_unsupported_share: float = math.nan


_CONTEXT: list[Context] = []


def _install(context: Context) -> None:
    _CONTEXT.clear()
    _CONTEXT.append(context)


def execute(spec: RunSpec, context: Context) -> RunOutput:
    """Run one closed-loop simulation and evaluate it.

    Parameters
    ----------
    spec
        The run.
    context
        Shared inputs.

    Returns
    -------
    RunOutput
        KPIs, gate inputs and optional details.
    """
    started = time.perf_counter()
    rows: list[tuple[object, ...]] = []
    on_step: Callable[[int, StepResult[Any]], None] | None = None
    if spec.keep_records:

        def collect(k: int, result: StepResult[Any]) -> None:
            record = result.decision
            rows.append(
                (
                    spec.run_id,
                    k,
                    record.at.wall.timestamp(),
                    record.at.wall.isoformat(),
                    record.controller,
                    record.ladder.value,
                    record.reason.value,
                    record.setpoint,
                    record.pre_round,
                    record.binding,
                    dump(record.to_json_dict()),
                )
            )

        on_step = collect
    loop = context.loop if spec.sensors is None else replace(context.loop, sensors=spec.sensors)
    trace = simulate(
        spec.controller,
        spec.params,
        context.weather,
        spec.initial,
        loop,
        on_step,
    )
    table = kpi.compute(kpi.from_trace(trace, context.weather.dt), context.band_low_c)
    starts = trace.final.starts - spec.initial.starts
    steady = trace.final.steady_starts - spec.initial.steady_starts
    return RunOutput(
        run_id=spec.run_id,
        kpis=table,
        room_rmse_k=kpi.room_rmse(trace.room_c, context.recorded_room),
        envelope=envelope(trace.setpoint, trace.room_c, context.setpoint_range, context.room_range),
        trace=trace if spec.keep_trace else None,
        records=tuple(rows),
        seconds=time.perf_counter() - started,
        room=trace.room_c.astype(np.float32),
        room_fresh_share=float(np.mean(trace.room_fresh)) if trace.room_fresh.size else math.nan,
        feedback_share=float(np.mean(trace.room_feedback))
        if trace.room_feedback.size
        else math.nan,
        curve_only_share=float(np.mean([level == "curve_only" for level in trace.ladder]))
        if trace.ladder
        else math.nan,
        steady_start_share=steady / starts if starts else math.nan,
        running_share=float(np.mean(trace.running)) if trace.running.size else math.nan,
        cop_unsupported_share=context.cop_support.unsupported_share(
            context.weather.outside_c, trace.outlet_c, trace.hz, trace.heat_w
        )
        if context.cop_support is not None
        else math.nan,
    )


def _execute_installed(spec: RunSpec) -> RunOutput:
    return execute(spec, _CONTEXT[0])


def run_all(
    specs: Sequence[RunSpec], context: Context, workers: int | None
) -> dict[str, RunOutput]:
    """Execute runs, in worker processes when more than one worker is allowed.

    Parameters
    ----------
    specs
        Runs.
    context
        Shared inputs.
    workers
        Worker processes (``None``: CPU count); 1 runs in this process.

    Returns
    -------
    dict
        Output per run id.
    """
    count = min(workers or os.cpu_count() or 1, len(specs))
    if count <= 1:
        return {spec.run_id: execute(spec, context) for spec in specs}
    with ProcessPoolExecutor(count, initializer=_install, initargs=(context,)) as pool:
        outputs = list(pool.map(_execute_installed, specs))
    return {out.run_id: out for out in outputs}


@dataclass(frozen=True, slots=True)
class StartsCheck:
    """Starts per day of the recording and two ways of simulating it.

    Parameters
    ----------
    recorded
        Recorded heating starts per day.
    daily_restart
        Plant on recorded setpoints, restarted every day from the filtered state.
    continuous
        Plant on recorded setpoints, one continuous run.
    """

    recorded: float
    daily_restart: float
    continuous: float

    def to_json(self) -> JsonDict:
        """Return a JSON-friendly form with relative errors."""

        def rel(x: float) -> float | None:
            if not self.recorded or not math.isfinite(x):
                return None
            return 100.0 * (x - self.recorded) / self.recorded

        return {
            "recorded_per_day": self.recorded,
            "recorded_setpoints_daily_restart_per_day": self.daily_restart,
            "recorded_setpoints_daily_restart_error_pct": rel(self.daily_restart),
            "recorded_setpoints_continuous_per_day": self.continuous,
            "recorded_setpoints_continuous_error_pct": rel(self.continuous),
        }


def starts_check(
    setup: Setup, params: PlantParams, initial: PlantState, days: Sequence[str]
) -> StartsCheck:
    """Compare simulated starts per day on ``days`` for the two ways of running the plant.

    Parameters
    ----------
    setup
        Recorded inputs.
    params
        Point-estimate parameters.
    initial
        Initial plant state of the period.
    days
        Day labels to compare on.

    Returns
    -------
    StartsCheck
        Starts per day.
    """
    ds, i0, i1 = setup.ds, setup.i0, setup.i1
    day_set = set(days)
    starts_per_day = len(day_set) or 1
    first = min(days)
    last = max(days)
    start = datetime.fromisoformat(first).replace(tzinfo=UTC).timestamp()
    end = datetime.fromisoformat(last).replace(tzinfo=UTC).timestamp() + SECONDS_PER_DAY
    coarse = ds.coarsen(COARSEN)
    states = filtered(coarse, params.building)
    restart = plant_days(ds, params, start, end, (coarse, states))
    setpoint = np.round(_filled(ds.columns["z1_target"], DEFAULT_SETPOINT))[i0:i1]
    w = setup.weather
    traj = run_open_loop(
        params, initial, setpoint, w.outside_c, w.ghi_w_m2, w.local_hour, w.dt, w.rh_pct
    )
    per_tick = np.diff(np.r_[float(initial.starts), traj.starts])
    tick_day = np.floor(w.times() / SECONDS_PER_DAY)
    wanted = [datetime.fromisoformat(d).replace(tzinfo=UTC).timestamp() / 86400.0 for d in days]
    continuous = float(per_tick[np.isin(tick_day, wanted)].sum()) / starts_per_day
    return StartsCheck(
        recorded=setup.recorded.subset(list(days)).totals["starts_per_day"],
        daily_restart=float(restart.starts_simulated.mean())
        if restart.day_starts.size
        else math.nan,
        continuous=continuous,
    )


def ovenbird_run(
    run_id: str,
    target_c: float,
    params: PlantParams,
    initial: PlantState,
    options: CounterfactualOptions,
    *,
    point: bool = False,
    sensors: SensorModel | None = None,
) -> RunSpec:
    """Return one ovenbird run with the configured profile at ``target_c``."""
    config = ovenbird_config(
        target_c,
        options.ovenbird_min_setpoint_c,
        options.pump_duty,
        room=options.room_profile,
    )
    return RunSpec(
        run_id,
        OvenbirdController(config),
        params,
        initial,
        keep_trace=point,
        keep_records=point and options.keep_records,
        sensors=sensors,
    )


def recorded_setpoints(setup: Setup) -> RecordedSetpoints:
    """Return the baseline controller: the recorded applied setpoints of the period."""
    return RecordedSetpoints(setup.weather.t0, setup.weather.dt, setup.setpoints)


def baseline_run(
    run_id: str,
    setup: Setup,
    params: PlantParams,
    initial: PlantState,
    options: CounterfactualOptions,
    *,
    point: bool = False,
) -> RunSpec:
    """Return one baseline run: the plant on the recorded applied setpoints."""
    return RunSpec(
        run_id,
        recorded_setpoints(setup),
        params,
        initial,
        keep_trace=point,
        keep_records=point and options.keep_records,
    )


def ablation_specs(
    params: PlantParams, initial: PlantState, options: CounterfactualOptions, target_c: float
) -> list[RunSpec]:
    """Ovenbird variants for every term combination except all-on (the point run)."""
    base = ovenbird_config(
        target_c, options.ovenbird_min_setpoint_c, options.pump_duty, room=options.room_profile
    )
    return [
        RunSpec(
            f"ablation:{ablation.label(combo)}",
            OvenbirdController(ablation.ablated(base, combo)),
            params,
            initial,
        )
        for combo in ablation.combos()[1:]
    ]


@dataclass(frozen=True, slots=True)
class TargetCalibration:
    """Ovenbird's room target matched to the baseline's comfort.

    ``check`` (default) picks the target at which the comfort check
    (:class:`ovenbird_sim.evaluate.claims.ComfortMatch`) is best met: the largest of
    the mean, occupied-P10 and degree-hours differences, each over its tolerance, is
    smallest. ``tail`` matches the occupied-hours degree-hours below the baseline's
    10th percentile, ``mean`` the occupied-hours mean. The two controllers shape the
    room differently over the day (the recorded control may run warmer in cold weather
    or in the afternoon, ovenbird holds the room flatter), so one target cannot zero all three
    at once; matching the mean alone leaves ovenbird's tail colder, matching the tail
    alone leaves its mean warmer.

    Parameters
    ----------
    measure
        Calibrated measure.
    target_c
        Calibrated target.
    deltas
        ``ovenbird - baseline`` of mean, P10 and degree-hours at the target.
    worst
        The comfort check's largest difference over its tolerance at the target.
    baseline_mean_c, baseline_dh
        Baseline occupied mean and its own degree-hours below its 10th percentile.
    steer, offset, slope
        What the replicates are steered on (``mean`` or ``dh``), the point's difference
        in it and its slope over the target.
    converged
        Whether the measure is met (``check``: the comfort check passes at the point).
    trials
        ``(target, mean, p10, dh, worst)`` differences of every calibration run.
    mean_matched_target_c, tail_matched_target_c
        Targets that match the mean or the tail alone, interpolated from the trials.
    """

    measure: ComfortMeasure
    target_c: float
    deltas: Mapping[str, float]
    worst: float
    baseline_mean_c: float
    baseline_dh: float
    steer: str
    offset: float
    slope: float
    converged: bool
    trials: tuple[tuple[float, float, float, float, float], ...]
    mean_matched_target_c: float = math.nan
    tail_matched_target_c: float = math.nan

    def to_json(self) -> JsonDict:
        """Return a JSON-friendly form."""
        return {
            "measure": self.measure.value,
            "target_c": self.target_c,
            "deltas": {k: _real(v) for k, v in self.deltas.items()},
            "worst": _real(self.worst),
            "baseline_mean_c": self.baseline_mean_c,
            "baseline_dh": self.baseline_dh,
            "steer": self.steer,
            "offset": self.offset,
            "slope": self.slope,
            "converged": self.converged,
            "trials": [list(t) for t in self.trials],
            "trial_columns": ["target_c", "mean_delta_k", "p10_delta_k", "dh_delta", "worst"],
            "mean_matched_target_c": _real(self.mean_matched_target_c),
            "tail_matched_target_c": _real(self.tail_matched_target_c),
        }


CALIBRATION_TOLERANCE: Final[Mapping[ComfortMeasure, float]] = {
    ComfortMeasure.CHECK: 1.0,
    ComfortMeasure.TAIL: 0.01,
    ComfortMeasure.MEAN: CALIBRATION_TOLERANCE_K,
}
CHECK_FIRST_POINTS: Final = 4
CALIBRATION_RESOLUTION_K: Final = 0.005
_COLUMN: Final[Mapping[str, int]] = {"mean": 1, "p10": 2, "dh": 3, "worst": 4}


def comfort_check(
    baseline: RunOutput, other: RunOutput, weather: Weather
) -> tuple[ComfortMatch, kpi.Comfort]:
    """Point comfort check of ``other`` against ``baseline`` and the baseline's comfort."""
    base, ob = comfort_pair(baseline, other, kpi.occupied(weather.local_hour), weather.dt)
    d = comfort_deltas(base, ob)
    match = ComfortMatch(
        math.nan,
        (d["mean"], d["mean"], d["mean"]),
        (d["p10"], d["p10"], d["p10"]),
        (d["dh"], d["dh"], d["dh"]),
        base.degree_hours_below,
        base.mean_c,
        base.p10_c,
    )
    return match, base


def _secant(trials: Sequence[tuple[float, float]], goal: float) -> tuple[float, float]:
    ordered = sorted(trials)
    x = np.array([t for t, _ in ordered])
    y = np.array([m for _, m in ordered])
    slope = float(np.polyfit(x, y, 1)[0]) if x.size >= 2 else 1.0
    below = [k for k in range(x.size - 1) if (y[k] - goal) * (y[k + 1] - goal) <= 0]
    if below:
        k = below[0]
        local = (y[k + 1] - y[k]) / (x[k + 1] - x[k]) if x[k + 1] != x[k] else slope
        if abs(local) > 1e-6:
            return float(x[k] + (goal - y[k]) / local), float(local)
    nearest = int(np.argmin(np.abs(y - goal)))
    if abs(slope) < 1e-6:
        return float(x[nearest]), slope
    return float(x[nearest] + (goal - y[nearest]) / slope), slope


def _objective(measure: ComfortMeasure) -> str:
    return {ComfortMeasure.CHECK: "worst", ComfortMeasure.TAIL: "dh"}.get(measure, "mean")


def _proposals(
    rows: Sequence[tuple[float, float, float, float, float]], measure: ComfortMeasure, first: bool
) -> list[float]:
    def column(name: str) -> list[tuple[float, float]]:
        return [(r[0], r[_COLUMN[name]]) for r in rows]

    if measure is not ComfortMeasure.CHECK:
        return [_secant(column(_objective(measure)), 0.0)[0]]
    mean_t, _ = _secant(column("mean"), 0.0)
    tail_t, _ = _secant(column("dh"), 0.0)
    if first:
        lo, hi = sorted((mean_t, tail_t))
        return [float(t) for t in np.linspace(lo, hi, CHECK_FIRST_POINTS)]
    targets = sorted(r[0] for r in rows)
    best = min(rows, key=lambda r: r[4])[0]
    k = targets.index(best)
    out = []
    if k > 0:
        out.append(0.5 * (targets[k - 1] + best))
    if k < len(targets) - 1:
        out.append(0.5 * (best + targets[k + 1]))
    return out


def calibrate_target(
    params: PlantParams,
    initial: PlantState,
    options: CounterfactualOptions,
    context: Context,
    baseline: RunOutput,
) -> tuple[TargetCalibration, dict[str, RunOutput]]:
    """Find ovenbird's room target at equal comfort with the baseline.

    A bracket of targets around the starting target runs in parallel. ``mean`` and
    ``tail`` then take secant steps on their measure; ``check`` runs
    :data:`CHECK_FIRST_POINTS` targets from the mean-matched to the tail-matched one
    and then halves the spacing around the best. At most :data:`CALIBRATION_STEPS`
    refinements, none closer than :data:`CALIBRATION_RESOLUTION_K` to a tried target.

    Returns
    -------
    TargetCalibration, dict
        The calibration and the runs it made by run id.
    """
    start = options.ovenbird_target
    measure = options.comfort_measure
    outputs: dict[str, RunOutput] = {}
    rows: list[tuple[float, float, float, float, float]] = []
    base_comfort: kpi.Comfort | None = None

    def batch(targets: Sequence[float]) -> None:
        nonlocal base_comfort
        specs = [ovenbird_run(f"calibration:{t:.4f}", t, params, initial, options) for t in targets]
        done = run_all(specs, context, options.workers)
        outputs.update(done)
        for t in targets:
            match, base_comfort = comfort_check(
                baseline, done[f"calibration:{t:.4f}"], context.weather
            )
            rows.append((t, match.mean[0], match.p10[0], match.dh[0], match.worst))

    objective = _objective(measure)
    tolerance = CALIBRATION_TOLERANCE[measure]

    def score(row: tuple[float, float, float, float, float]) -> float:
        return abs(row[_COLUMN[objective]])

    batch([start + d for d in CALIBRATION_OFFSETS_K])
    for step in range(CALIBRATION_STEPS + 1):
        if measure is not ComfortMeasure.CHECK and score(min(rows, key=score)) <= tolerance:
            break
        fresh = [
            t
            for t in _proposals(rows, measure, first=step == 0)
            if all(abs(t - r[0]) >= CALIBRATION_RESOLUTION_K for r in rows)
        ]
        if not fresh:
            break
        batch(sorted(set(fresh)))
    best = min(rows, key=score)
    steer = "dh" if measure is ComfortMeasure.TAIL else "mean"
    _, slope = _secant([(r[0], r[_COLUMN[steer]]) for r in rows], best[_COLUMN[steer]])
    if base_comfort is None:
        raise ValueError("no calibration runs")
    return (
        TargetCalibration(
            measure=measure,
            target_c=best[0],
            deltas={"mean": best[1], "p10": best[2], "dh": best[3]},
            worst=best[4],
            baseline_mean_c=base_comfort.mean_c,
            baseline_dh=base_comfort.degree_hours_below,
            steer=steer,
            offset=best[_COLUMN[steer]],
            slope=slope,
            converged=score(best) <= tolerance,
            trials=tuple(sorted(rows)),
            mean_matched_target_c=_secant([(r[0], r[1]) for r in rows], 0.0)[0],
            tail_matched_target_c=_secant([(r[0], r[3]) for r in rows], 0.0)[0],
        ),
        outputs,
    )


def day_ticks(weather: Weather) -> dict[str, np.ndarray]:
    """Tick indices of every UTC day of a replay."""
    labels = [kpi.day_label(float(t)) for t in weather.times()]
    out: dict[str, list[int]] = {}
    for k, label in enumerate(labels):
        out.setdefault(label, []).append(k)
    return {label: np.asarray(idx, dtype=np.int64) for label, idx in out.items()}


def comfort_pair(
    base_run: RunOutput,
    ob: RunOutput,
    mask: np.ndarray,
    dt: float,
    ticks: np.ndarray | None = None,
) -> tuple[kpi.Comfort, kpi.Comfort]:
    """Comfort of both runs; ovenbird's degree-hours are below the baseline's P10."""
    idx = np.arange(base_run.room.size) if ticks is None else ticks
    base = kpi.comfort(base_run.room[idx].astype(np.float64), mask[idx], dt)
    other = kpi.comfort(ob.room[idx].astype(np.float64), mask[idx], dt, base.p10_c)
    return base, other


COMFORT_DELTAS: Final = ("mean", "p10", "dh")


def comfort_deltas(base: kpi.Comfort, other: kpi.Comfort) -> dict[str, float]:
    """``ovenbird - baseline`` of mean, P10 and degree-hours below the baseline P10."""
    own = base.degree_hours_below
    return {
        "mean": other.mean_c - base.mean_c,
        "p10": other.p10_c - base.p10_c,
        "dh": other.degree_hours_below - own,
    }


@dataclass(frozen=True, slots=True)
class Intervals:
    """Paired-difference samples by uncertainty source.

    Parameters
    ----------
    combined
        Per replicate: its parameters and its own day-block resample.
    parameters
        Per replicate over all days.
    days
        Point estimate over :data:`DAY_RESAMPLES` day-block resamples.
    """

    combined: dict[str, list[float]]
    parameters: dict[str, list[float]]
    days: dict[str, list[float]]


def paired_samples(
    point: Mapping[str, RunOutput],
    pairs: Sequence[Mapping[str, RunOutput]],
    weather: Weather,
    seed: int,
) -> Intervals:
    """Sample the paired differences of every KPI and of the comfort statistics.

    Parameters
    ----------
    point
        Point-estimate runs by controller.
    pairs
        Replicate runs by controller.
    weather
        Replay inputs (day boundaries and occupied hours).
    seed
        Seed of the day resamples.

    Returns
    -------
    Intervals
        Samples per KPI (comfort as ``comfort_mean``, ``comfort_p10``, ``comfort_dh``).
    """
    ticks = day_ticks(weather)
    labels = list(ticks)
    mask = kpi.occupied(weather.local_hour)
    rng = np.random.default_rng(seed)
    names = [*TOTAL_KPIS, *(f"comfort_{c}" for c in COMFORT_DELTAS)]

    def deltas(pair: Mapping[str, RunOutput], picked: Sequence[str] | None) -> dict[str, float]:
        bl, ob = pair[BASELINE], pair[OVENBIRD]
        if picked is None:
            a, b = bl.kpis.totals, ob.kpis.totals
            idx = None
        else:
            a, b = bl.kpis.resampled(picked), ob.kpis.resampled(picked)
            idx = np.concatenate([ticks[label] for label in picked])
        out = {name: b[name] - a[name] for name in TOTAL_KPIS}
        base, other = comfort_pair(bl, ob, mask, weather.dt, idx)
        out |= {f"comfort_{k}": v for k, v in comfort_deltas(base, other).items()}
        return out

    combined: dict[str, list[float]] = {n: [] for n in names}
    parameters: dict[str, list[float]] = {n: [] for n in names}
    days: dict[str, list[float]] = {n: [] for n in names}
    for pair in pairs:
        picked = list(rng.choice(labels, len(labels)))
        for n, v in deltas(pair, picked).items():
            combined[n].append(v)
        for n, v in deltas(pair, None).items():
            parameters[n].append(v)
    for _ in range(DAY_RESAMPLES if pairs else 0):
        picked = list(rng.choice(labels, len(labels)))
        for n, v in deltas(point, picked).items():
            days[n].append(v)
    return Intervals(combined, parameters, days)


def comfort_match(
    point: Mapping[str, RunOutput],
    samples: Intervals,
    weather: Weather,
    calibration: TargetCalibration | None,
    target_c: float,
) -> ComfortMatch:
    """Comfort of ovenbird against the baseline (point and 90 % combined intervals)."""
    mask = kpi.occupied(weather.local_hour)
    base, other = comfort_pair(point[BASELINE], point[OVENBIRD], mask, weather.dt)
    d = comfort_deltas(base, other)

    def triple(name: str) -> tuple[float, float, float]:
        lo, hi = interval(samples.combined[f"comfort_{name}"])
        return d[name], lo, hi

    return ComfortMatch(
        calibrated_target_c=calibration.target_c if calibration is not None else target_c,
        mean=triple("mean"),
        p10=triple("p10"),
        dh=triple("dh"),
        baseline_dh=base.degree_hours_below,
        baseline_mean_c=base.mean_c,
        baseline_p10_c=base.p10_c,
    )


def differences(
    point: Mapping[str, RunOutput],
    samples: Intervals,
    gate: GateResult,
    held: Sequence[HeldOut],
    tolerance: float,
    baseline: Mapping[str, Fidelity],
    comfort: ComfortMatch | None,
) -> list[Difference]:
    """Return the paired differences ``ovenbird - baseline`` with claim status per KPI."""
    bl, ob = point[BASELINE], point[OVENBIRD]
    reasons = [
        f"{name}: {reason}"
        for name, out in ((BASELINE, bl), (OVENBIRD, ob))
        for reason in out.envelope.left(tolerance)
    ]
    cycling = cycling_reasons(baseline, folds=[(h.label, h.fidelity) for h in held])
    support = support_reasons(point)
    return [
        judge(
            name,
            ob.kpis.totals[name] - bl.kpis.totals[name],
            samples.combined[name],
            gate_passed=gate.passed,
            envelope_reasons=reasons,
            comfort_interval=None,
            baseline=baseline.get(name),
            held_out_passed=all(h.gate.passed for h in held) if held else None,
            held_out_folds=[(h.label, h.fidelity[name]) for h in held if name in h.fidelity],
            cycling=cycling,
            comfort=comfort,
            cop_support=support,
        )
        for name in TOTAL_KPIS
    ]


def support_reasons(point: Mapping[str, RunOutput]) -> list[str]:
    """Return a refusal reason for every run with too much heat outside the COP support."""
    return [
        f"{name}: {100 * out.cop_unsupported_share:.1f} % of the heat outside the COP map's "
        f"joint support (tolerance {100 * UNSUPPORTED_TOLERANCE:.0f} %)"
        for name, out in point.items()
        if out.cop_unsupported_share > UNSUPPORTED_TOLERANCE
    ]


def _test_block(days: Sequence[str]) -> list[str]:
    return list(days)[-TEST_BLOCK_DAYS:]


def _context(
    setup: Setup, sensors: SensorModel, band_low_c: float, support: CopSupport | None = None
) -> Context:
    return Context(
        weather=setup.weather,
        loop=LoopOptions(
            initial_setpoint=setup.initial_setpoint,
            initial_duty=setup.initial_duty,
            sensors=sensors,
        ),
        recorded_room=setup.recorded_room,
        band_low_c=band_low_c,
        setpoint_range=setup.setpoint_range,
        room_range=setup.room_range,
        cop_support=support,
    )


def _room_states(lake: Path, entity: str = ROOM_ENTITY) -> Series | None:
    if not lake.is_dir():
        return None
    states = dl.load_state(lake, entity)
    return states if len(states) else None


def _report_time(train_path: Path, key: str) -> float | None:
    text = io.load_report(train_path).get(key)
    if not isinstance(text, str):
        return None
    return datetime.fromisoformat(text).timestamp()


@dataclass(frozen=True, slots=True)
class HeldOut:
    """Held-out baseline gate of one fold: recorded setpoints on its test block, train-only fit.

    Parameters
    ----------
    setup
        Recorded inputs of the test block.
    output
        The baseline run.
    gate
        Gate verdict on the block.
    fidelity
        Per-KPI fidelity on the block.
    params_path
        Train-only parameter file.
    """

    setup: Setup
    output: RunOutput
    gate: GateResult
    fidelity: dict[str, Fidelity]
    params_path: Path

    @property
    def label(self) -> str:
        """``held-out <first day> - <last day>``."""
        days = list(self.setup.recorded.days)
        return f"held-out {days[0]} - {days[-1]}" if days else "held-out"


def held_out_specs(
    ds: Dataset, train_paths: Sequence[Path], options: CounterfactualOptions
) -> list[tuple[Path, Setup, RunSpec]]:
    """Test block and baseline run of every fold with a train-only fit and test days."""
    out = []
    for index, path in enumerate(train_paths):
        if not path.exists():
            continue
        split = _report_time(path, "split")
        if split is None:
            continue
        test_end = _report_time(path, "test_end")
        ends = [e for e in (test_end, options.end) if e is not None]
        try:
            setup = prepare(ds, replace(options, start=split, end=min(ends) if ends else None))
        except ValueError:
            continue
        params = io.load(path)
        initial = initial_state(ds, params, setup.i0)
        run = baseline_run(f"held_out:{index}:{BASELINE}", setup, params, initial, options)
        out.append((path, setup, run))
    return out


def held_out_gates(
    ds: Dataset,
    train_paths: Sequence[Path],
    sensors: SensorModel,
    options: CounterfactualOptions,
) -> list[HeldOut]:
    """Run the held-out gate of every rolling-origin fold (latest first; empty without one)."""
    out = []
    for path, setup, run in held_out_specs(ds, train_paths, options):
        context = _context(setup, sensors, options.band_low_c)
        output = run_all([run], context, 1)[run.run_id]
        simulated, recorded = setup.scored(output.kpis), setup.scored(setup.recorded)
        gate = baseline_gate(simulated, recorded, output.room_rmse_k, options.gate)
        out.append(HeldOut(setup, output, gate, fidelity(simulated, recorded), path))
    return out


def _all_room(setup: Setup) -> FloatArray:
    return setup.recorded_room if setup.recorded_room_all is None else setup.recorded_room_all


def events_json(setup: Setup, held: Sequence[HeldOut], gate_all: GateResult) -> JsonDict:
    """Known events, the days they remove from the scoring and the gates on all days."""
    folds: list[JsonValue] = []
    for fold in held:
        all_days = baseline_gate(
            fold.output.kpis.totals,
            fold.setup.recorded.totals,
            kpi.room_rmse(fold.output.room.astype(np.float64), _all_room(fold.setup)),
            GateBounds(),
        )
        folds.append(
            {
                "period_start": meta.utc_iso(fold.setup.start),
                "excluded_days": list(fold.setup.excluded_days),
                "scored_days": len(fold.setup.scored_days),
                "gate_all_days": all_days.to_json(),
            }
        )
    return {
        "items": [event.to_json() for event in setup.events],
        "excluded_days": list(setup.excluded_days),
        "scored_days": len(setup.scored_days),
        "policy": "the UTC days an event or its recovery tail touches are left out of the "
        "baseline gates, the fidelity, the starts check and the sensor calibration; both "
        "runs are still simulated through them (without the stove) and the "
        "ovenbird - baseline differences use every day",
        "gate_all_days": gate_all.to_json(),
        "held_out_all_days": folds,
    }


def steady_cop_map(params: PlantParams, params_path: Path) -> PlantParams | None:
    """``params`` with the steady-only COP map of the identification report (no warm-up)."""
    report = io.load_report(params_path).get("heat_pump_fit", {})
    steady = report.get("cop_steady_map") if isinstance(report, dict) else None
    if not isinstance(steady, dict):
        return None
    hp = params.heat_pump.replace(
        cop0=float(steady["c0"]),
        cop_o=float(steady["c_o"]),
        cop_s=float(steady["c_s"]),
        cop_h=float(steady["c_h"]),
        cop_warmup=0.0,
    )
    return PlantParams(hp, params.building)


def counterfactual(
    capture: Path,
    params_path: Path,
    out: Path,
    *,
    datalake: Path | None = None,
    weather: Path | None = None,
    options: CounterfactualOptions | None = None,
    log: Callable[[str], None] | None = None,
) -> JsonDict:
    """Run the counterfactual replay and write ``counterfactual.sqlite`` and its summary.

    Parameters
    ----------
    capture
        Capture directory.
    params_path
        Fitted plant parameters (``plant_params.json``).
    out
        Output directory.
    datalake, weather
        Datalake root and weather cache (default: next to the capture).
    options
        Replay options.
    log
        Progress messages.

    Returns
    -------
    JsonDict
        The summary (also written as JSON).
    """
    opts = options or CounterfactualOptions()
    say = log or (lambda _: None)
    started = time.perf_counter()
    lake = datalake if datalake is not None else capture.parent / "datalake"
    wx = weather if weather is not None else capture.parent / "weather"
    ds, series = load_dataset(capture, lake, wx)
    setup = prepare(ds, opts)
    params = io.load(params_path)
    say(f"dataset ready ({time.perf_counter() - started:.0f} s): {setup.weather.n} ticks")
    calibration = (
        calibrate(
            ds,
            series,
            params.heat_pump.outside_bias_running_k,
            opts.seed,
            room_states=_room_states(lake),
            room_reference=smooth_level(filtered_room(ds, params), ds.grid.step),
            room_confirm_s=opts.room_confirm_s,
            room_profile=opts.room_profile,
            room_liveness=_room_states(lake, LIVENESS_ENTITY) if opts.room_liveness else None,
            exclude=tuple((e.start, e.tail_end) for e in ds.events) if opts.known_events else (),
        )
        if opts.sensor_noise
        else None
    )
    sensors = calibration.model if calibration is not None else SensorModel(seed=opts.seed)
    initial = initial_state(ds, params, setup.i0)
    reps, cached = get_replicates(
        params_path, ds, params, opts.bootstrap, opts.seed, series, opts.workers
    )
    if opts.bootstrap:
        say(f"{len(reps)} bootstrap replicates ({'cached' if cached else 'built'})")
    rep_initial = [initial_state(ds, p, setup.i0) for p in reps]
    support = cop_support(ds)
    context = _context(setup, sensors, opts.band_low_c, support)
    run_started = time.perf_counter()

    baseline_specs = [baseline_run(BASELINE, setup, params, initial, opts, point=True)]
    baseline_specs += [
        baseline_run(f"replicate:{i}:{BASELINE}", setup, p, s, opts)
        for i, (p, s) in enumerate(zip(reps, rep_initial, strict=True))
    ]
    outputs = run_all(baseline_specs, context, opts.workers)
    bl = outputs[BASELINE]
    say(f"baseline runs done ({time.perf_counter() - run_started:.0f} s)")

    target = opts.ovenbird_target
    target_cal: TargetCalibration | None = None
    if opts.calibrate_target:
        target_cal, made = calibrate_target(params, initial, opts, context, bl)
        outputs.update(made)
        target = target_cal.target_c
        d = target_cal.deltas
        say(
            f"ovenbird target calibrated on the {target_cal.measure.value}: {target:.3f} °C "
            f"(mean {d['mean']:+.3f} K, P10 {d['p10']:+.3f} K, degree-hours {d['dh']:+.3f}; "
            f"worst {target_cal.worst:.2f} x tolerance)"
        )

    variants = sensitivity_specs(setup, params, initial, opts, target, params_path)
    variants += room_variant_specs(params, initial, opts, target, sensors)
    second = [ovenbird_run(OVENBIRD, target, params, initial, opts, point=True)]
    if opts.ablation:
        second += ablation_specs(params, initial, opts, target)
    second += [
        ovenbird_run(f"first:{i}:{OVENBIRD}", target, p, s, opts)
        for i, (p, s) in enumerate(zip(reps, rep_initial, strict=True))
    ]
    second += variants
    outputs.update(run_all(second, context, opts.workers))

    rep_targets: list[float] = []
    if reps:
        slope = (
            target_cal.slope
            if target_cal is not None and abs(target_cal.slope) > MIN_CALIBRATION_SLOPE
            else 0.0
        )
        third = []
        for i, (p, s) in enumerate(zip(reps, rep_initial, strict=True)):
            gap = math.nan
            if target_cal is not None:
                match, _ = comfort_check(
                    outputs[f"replicate:{i}:{BASELINE}"],
                    outputs[f"first:{i}:{OVENBIRD}"],
                    setup.weather,
                )
                now = match.mean[0] if target_cal.steer == "mean" else match.dh[0]
                gap = target_cal.offset - now
            step = 0.0 if slope == 0.0 or not math.isfinite(gap) else gap / slope
            step = float(np.clip(step, -REPLICATE_STEP_LIMIT_K, REPLICATE_STEP_LIMIT_K))
            rep_targets.append(target + step)
            third.append(ovenbird_run(f"replicate:{i}:{OVENBIRD}", target + step, p, s, opts))
        outputs.update(run_all(third, context, opts.workers))
    train_paths = [opts.train_params] if opts.train_params else io.fold_paths(params_path)
    held = held_out_gates(ds, train_paths, sensors, opts)
    run_seconds = time.perf_counter() - run_started
    say(f"runs done ({run_seconds:.0f} s)")

    point = {BASELINE: bl, OVENBIRD: outputs[OVENBIRD]}
    replicate_outputs = [
        {
            BASELINE: outputs[f"replicate:{i}:{BASELINE}"],
            OVENBIRD: outputs[f"replicate:{i}:{OVENBIRD}"],
        }
        for i in range(len(reps))
    ]
    scored_recorded = setup.scored(setup.recorded)
    gate = baseline_gate(setup.scored(bl.kpis), scored_recorded, bl.room_rmse_k, opts.gate)
    gate_all = baseline_gate(
        bl.kpis.totals,
        setup.recorded.totals,
        kpi.room_rmse(bl.room.astype(np.float64), _all_room(setup)),
        opts.gate,
    )
    replicate_gates = [
        baseline_gate(
            setup.scored(pair[BASELINE].kpis),
            scored_recorded,
            pair[BASELINE].room_rmse_k,
            opts.gate,
        )
        for pair in replicate_outputs
    ]
    days = setup.scored_days
    test_days = [d for d in _test_block(list(setup.recorded.days)) if d in days]
    check = starts_check(setup, params, initial, days)
    check_test = starts_check(setup, params, initial, test_days)
    baseline = fidelity(setup.scored(bl.kpis), scored_recorded)
    samples = paired_samples(point, replicate_outputs, setup.weather, opts.seed + 1)
    comfort = comfort_match(point, samples, setup.weather, target_cal, target)
    diffs = differences(point, samples, gate, held, opts.envelope_tolerance, baseline, comfort)
    contributions: dict[str, dict[str, float]] = {}
    mains: dict[str, dict[str, float]] = {}
    ablation_totals: dict[str, dict[str, float]] = {}
    if opts.ablation:
        by_combo: dict[ablation.Combo, Mapping[str, float]] = {}
        for combo in ablation.combos():
            run_id = (
                OVENBIRD if combo == ablation.combos()[0] else f"ablation:{ablation.label(combo)}"
            )
            by_combo[combo] = outputs[run_id].kpis.totals
            ablation_totals[ablation.label(combo)] = dict(outputs[run_id].kpis.totals)
        for name in ("starts_per_day", "elec_kwh_per_day", "heat_kwh_per_day", COMFORT_KPI):
            values = {combo: totals[name] for combo, totals in by_combo.items()}
            contributions[name] = ablation.contributions(values)
            mains[name] = ablation.main_effects(values)
    summary = _summary(
        setup,
        opts,
        params_path,
        capture,
        point,
        gate,
        held,
        replicate_gates,
        check,
        check_test,
        baseline,
        diffs,
        samples,
        comfort,
        target_cal,
        target,
        rep_targets,
        contributions,
        mains,
        ablation_totals,
        len(reps),
        cached,
        calibration,
        sensitivity_summary(outputs, point),
        room_variant_summary(outputs, point),
        params.heat_pump.circulation_w,
    )
    summary["known_events"] = events_json(setup, held, gate_all)
    summary["runtime_s"] = {
        "total": time.perf_counter() - started,
        "runs": run_seconds,
        "runs_count": len(outputs) + len(held),
        "per_run_mean": float(np.mean([o.seconds for o in outputs.values()])),
    }
    for fold in held:
        outputs[fold.output.run_id] = fold.output
    _write(out, summary, outputs, setup, gate, replicate_gates, diffs, contributions)
    return summary


SENSITIVITY: Final[Mapping[str, str]] = {
    "cop_no_warmup": "both runs with the COP warm-up term off",
    "cop_steady_map": "both runs with the old steady-only COP map",
    "steady_start_documented": "both runs with the pump's steady start at the "
    "commonly quoted inlet <= SP-4 at once (fitted: SP-6 for 5 min)",
    "steady_start_shallow": "both runs with the steady start at inlet <= SP-5 for 5 min",
    "steady_start_late": "both runs with the steady start at inlet <= SP-6.5 for 10 min",
}
STEADY_START_VARIANTS: Final[Mapping[str, tuple[float, float]]] = {
    "steady_start_documented": (4.0, 0.0),
    "steady_start_shallow": (5.0, 300.0),
    "steady_start_late": (6.5, 600.0),
}


def sensitivity_specs(
    setup: Setup,
    params: PlantParams,
    initial: PlantState,
    options: CounterfactualOptions,
    target_c: float,
    params_path: Path,
) -> list[RunSpec]:
    """Point-estimate variants of :data:`SENSITIVITY` (empty when switched off)."""
    if not options.sensitivity:
        return []
    no_warm = PlantParams(params.heat_pump.replace(cop_warmup=0.0), params.building)
    specs: list[RunSpec] = []
    variants = [("cop_no_warmup", no_warm)]
    steady = steady_cop_map(params, params_path)
    if steady is not None:
        variants.append(("cop_steady_map", steady))
    for name, (margin, delay) in STEADY_START_VARIANTS.items():
        rule = params.heat_pump.replace(start_steady_margin_k=margin, start_steady_delay_s=delay)
        variants.append((name, PlantParams(rule, params.building)))
    for name, plant in variants:
        specs.append(baseline_run(f"sensitivity:{name}:{BASELINE}", setup, plant, initial, options))
        specs.append(
            ovenbird_run(f"sensitivity:{name}:{OVENBIRD}", target_c, plant, initial, options)
        )
    return specs


ROOM_VARIANTS: Final[Mapping[str, str]] = {
    "ideal": "ideal room sensor: re-sent every minute, no noise (the recorded grid)",
    "1800s": "the recorded sensor with today's staleness: periodic profile, 1800 s, no liveness",
    "profile": "the recorded sensor under the configured room profile (the point run)",
}


def room_variant_models(sensors: SensorModel) -> dict[str, SensorModel]:
    """Sensor models of the ideal and 1800 s room variants (the profile is the point run)."""
    room = sensors.room
    grid = RoomSensorProfile(step_k=room.step_k)
    ideal = RoomSensorModel(
        step_k=room.step_k, grid_offset_k=room.grid_offset_k, confirm_s=0.0, profile=grid
    )
    today = replace(room, profile=grid, liveness_times=(), humidity=None)
    return {"ideal": replace(sensors, room=ideal), "1800s": replace(sensors, room=today)}


def room_variant_specs(
    params: PlantParams,
    initial: PlantState,
    options: CounterfactualOptions,
    target_c: float,
    sensors: SensorModel,
) -> list[RunSpec]:
    """Ovenbird runs of the ideal and 1800 s room variants at ``target_c``."""
    if not options.room_variants:
        return []
    out = []
    for name, model in room_variant_models(sensors).items():
        config = ovenbird_config(
            target_c,
            options.ovenbird_min_setpoint_c,
            options.pump_duty,
            room=model.room.profile,
        )
        out.append(
            RunSpec(
                f"room_variant:{name}:{OVENBIRD}",
                OvenbirdController(config),
                params,
                initial,
                sensors=model,
            )
        )
    return out


def room_variant_summary(
    outputs: Mapping[str, RunOutput], point: Mapping[str, RunOutput]
) -> JsonDict:
    """KPIs and room input shares of the room variants side by side."""
    out: JsonDict = {}
    for name, note in ROOM_VARIANTS.items():
        run = (
            point[OVENBIRD] if name == "profile" else outputs.get(f"room_variant:{name}:{OVENBIRD}")
        )
        if run is None:
            continue
        entry: JsonDict = {
            "note": note,
            "room_fresh_share": _real(run.room_fresh_share),
            "feedback_share": _real(run.feedback_share),
            "curve_only_share": _real(run.curve_only_share),
        }
        for kpi_name in SENSITIVITY_KPIS:
            entry[kpi_name] = {
                OVENBIRD: _real(run.kpis.totals[kpi_name]),
                "difference": _real(
                    run.kpis.totals[kpi_name] - point[BASELINE].kpis.totals[kpi_name]
                ),
            }
        out[name] = entry
    return out


SENSITIVITY_KPIS: Final = (
    "heat_kwh_per_day",
    "elec_kwh_per_day",
    "cop",
    "starts_per_day",
    "run_median_min",
    "room_mean_c",
    "room_min_c",
)


def sensitivity_summary(
    outputs: Mapping[str, RunOutput], point: Mapping[str, RunOutput]
) -> JsonDict:
    """KPIs of the sensitivity variants next to the point runs they replace."""
    out: JsonDict = {}
    for name, note in SENSITIVITY.items():
        bl = outputs.get(f"sensitivity:{name}:{BASELINE}", point[BASELINE])
        ob = outputs.get(f"sensitivity:{name}:{OVENBIRD}", point[OVENBIRD])
        if bl is point[BASELINE] and ob is point[OVENBIRD]:
            continue
        entry: JsonDict = {"note": note}
        for kpi_name in SENSITIVITY_KPIS:
            entry[kpi_name] = {
                BASELINE: _real(bl.kpis.totals[kpi_name]),
                OVENBIRD: _real(ob.kpis.totals[kpi_name]),
                "difference": _real(ob.kpis.totals[kpi_name] - bl.kpis.totals[kpi_name]),
            }
        entry["steady_start_share"] = {
            BASELINE: _real(bl.steady_start_share),
            OVENBIRD: _real(ob.steady_start_share),
        }
        entry["ovenbird_curve_only_share"] = _real(ob.curve_only_share)
        entry["ovenbird_room_fresh_share"] = _real(ob.room_fresh_share)
        entry["ovenbird_feedback_share"] = _real(ob.feedback_share)
        out[name] = entry
    return out


def _intervals_json(samples: Intervals) -> JsonDict:
    out: JsonDict = {}
    for name in samples.combined:
        row: JsonDict = {}
        for label, source in (
            ("combined", samples.combined),
            ("parameters_only", samples.parameters),
            ("days_only", samples.days),
        ):
            lo, hi = interval(source[name])
            row[label] = [_real(lo), _real(hi)]
        out[name] = row
    return out


def recorded_statement(table: KpiTable, label: str = "replay period") -> str:
    """Return the recorded starts per day with the period they were counted over."""
    days = sorted(table.days)
    if not days:
        return f"no recorded days in the {label}"
    starts = table.totals["starts_per_day"]
    return (
        f"recorded heating starts {starts:.2f}/day over {len(days)} days "
        f"({days[0]} to {days[-1]}, {label})"
    )


def _summary(
    setup: Setup,
    opts: CounterfactualOptions,
    params_path: Path,
    capture: Path,
    point: Mapping[str, RunOutput],
    gate: GateResult,
    held: Sequence[HeldOut],
    replicate_gates: Sequence[GateResult],
    check: StartsCheck,
    check_test: StartsCheck,
    baseline: Mapping[str, Fidelity],
    diffs: Sequence[Difference],
    samples: Intervals,
    comfort: ComfortMatch,
    target_cal: TargetCalibration | None,
    target: float,
    rep_targets: Sequence[float],
    contributions: Mapping[str, Mapping[str, float]],
    mains: Mapping[str, Mapping[str, float]],
    ablation_totals: Mapping[str, Mapping[str, float]],
    n_replicates: int,
    cached: bool,
    calibration: Calibration | None,
    sensitivity: JsonDict,
    room_variants: JsonDict | None = None,
    circulation_w: float = 0.0,
) -> JsonDict:
    bl_id = meta.controller_identity(RecordedSetpoints(setup.weather.t0, setup.weather.dt))
    ob_id = meta.controller_identity(
        OvenbirdController(
            ovenbird_config(
                target, opts.ovenbird_min_setpoint_c, opts.pump_duty, room=opts.room_profile
            )
        )
    )
    passed_share = (
        sum(g.passed for g in replicate_gates) / len(replicate_gates) if replicate_gates else None
    )
    both = gate.passed and all(h.gate.passed for h in held)
    claim_note = (
        f"baseline gates passed (in-sample and {len(held)} held-out folds)"
        if both and held
        else "baseline gate passed in-sample; no held-out gate (no train-only fit)"
        if both
        else "BASELINE GATE FAILED: every comparison below is not claimable"
    )
    test_block = _test_block(list(setup.recorded.days))
    sensor_json: JsonDict | None = None
    if calibration is not None:
        model = calibration.model
        sensor_json = {
            "model": meta.to_jsonable(replace(model, offset_by_day=(), room=RoomSensorModel())),
            "thermostat_offset_by_day": list(model.offset_by_day),
            "room_sensor": meta.to_jsonable(replace(model.room, dropouts=(), liveness_times=())),
            "room_dropouts": [list(d) for d in model.room.dropouts],
            "room_liveness": {
                "source": f"recorded {LIVENESS_ENTITY} report times (exogenous)"
                if model.room.liveness_times
                else None,
                "reports": len(model.room.liveness_times),
            },
            "recorded_minute_end_flips_per_day": {
                "outside": calibration.outside_flips_per_day,
                "thermostat": calibration.thermostat_flips_per_day,
            },
            "recorded_room_changes_per_day": _real(calibration.room_changes_per_day),
            "recorded_room_reversal_share": _real(model.room.reversal_share),
        }
    provenance: JsonDict = {
        "mode": "counterfactual",
        "controllers": {BASELINE: bl_id, OVENBIRD: ob_id},
        "config_hash": meta.config_hash(
            {
                BASELINE: bl_id["config"],
                OVENBIRD: ob_id["config"],
                "options": meta.to_jsonable(opts),
                "params": meta.file_hash(params_path),
            }
        ),
        "options": meta.to_jsonable(opts),
        "params": {"path": str(params_path), "hash": meta.file_hash(params_path)},
        "train_params": [
            {"path": str(h.params_path), "hash": meta.file_hash(h.params_path)} for h in held
        ],
        "bootstrap": {"replicates": n_replicates, "seed": opts.seed, "cached": cached},
        "capture": str(capture),
        "period": {
            "start": meta.utc_iso(setup.start),
            "end": meta.utc_iso(setup.end),
            "days": len(setup.recorded.days),
            "test_block": list(test_block),
        },
        "comfort_band_c": [opts.band_low_c, opts.comfort_c],
        "occupied_hours_local": list(kpi.OCCUPIED_HOURS),
        "room_inputs": {BASELINE: None, OVENBIRD: "sensor"},
        "room_profile": meta.to_jsonable(opts.room_profile),
        "sensors": sensor_json,
        "git": meta.git_commit(),
    }
    held_json: JsonDict | None = None
    if held:
        held_json = {
            "passed": all(h.gate.passed for h in held),
            "method": "rolling origin: each test block is simulated with parameters fitted "
            "on the days before it only; every fold must pass",
            "folds": [_held_json(h) for h in held],
        }
    refusals: list[JsonValue] = list(
        cycling_reasons(baseline, folds=[(h.label, h.fidelity) for h in held])
    )
    room_input: JsonDict = {
        name: {
            "fresh_share": _real(out.room_fresh_share),
            "feedback_share": _real(out.feedback_share),
            "curve_only_share": _real(out.curve_only_share),
            "steady_start_share": _real(out.steady_start_share),
        }
        for name, out in point.items()
        if name == OVENBIRD
    }
    return {
        "mode": "counterfactual",
        "claims": claim_note,
        "operation": operation_json(point),
        "idle_circulation": idle_circulation_json(point, circulation_w),
        "recorded_statement": recorded_statement(setup.recorded),
        "gate": gate.to_json()
        | {
            "replicates_passed_share": passed_share,
            "held_out": held_json,
        },
        "baseline_fidelity": [f.to_json() for f in baseline.values()],
        "cycling_refusals": refusals,
        "starts_investigation": {
            "all_days": check.to_json(),
            "test_block": check_test.to_json(),
        },
        "comfort": comfort.to_json(),
        "target_calibration": None if target_cal is None else target_cal.to_json(),
        "replicate_targets_c": {
            "min": _real(min(rep_targets)) if rep_targets else None,
            "median": _real(float(np.median(rep_targets))) if rep_targets else None,
            "max": _real(max(rep_targets)) if rep_targets else None,
        },
        "room_input": room_input,
        "kpis": {
            "recorded": dict(setup.recorded.totals),
            BASELINE: dict(point[BASELINE].kpis.totals),
            OVENBIRD: dict(point[OVENBIRD].kpis.totals),
        },
        "room_rmse_k": {name: out.room_rmse_k for name, out in point.items()},
        "envelope": {name: out.envelope.to_json() for name, out in point.items()},
        "differences": [d.to_json() for d in diffs],
        "intervals": _intervals_json(samples),
        "refused_unrecorded": [
            {"claim": name, "status": "refused", "reason": reason}
            for name, reason in UNRECORDED_CLAIMS.items()
        ],
        "sensitivity": sensitivity,
        "room_variants": room_variants or {},
        "ablation": {
            "terms": list(ablation.TERMS),
            "method": "leave-one-out from the full controller; interactions as residual",
            "contributions": {k: dict(v) for k, v in contributions.items()},
            "main_effects": {k: dict(v) for k, v in mains.items()},
            "variants": {k: dict(v) for k, v in ablation_totals.items()},
        },
        "daily": {
            name: {day: dict(values) for day, values in table.days.items()}
            for name, table in (
                ("recorded", setup.recorded),
                (BASELINE, point[BASELINE].kpis),
                (OVENBIRD, point[OVENBIRD].kpis),
            )
        },
        "meta": provenance,
    }


IDLE_DRAW_STEP_W: Final = 10.0


def operation_json(point: Mapping[str, RunOutput]) -> JsonDict:
    """Return the running share, steady-rule starts and COP support per run."""
    out: JsonDict = {
        name: {
            "running_share": _real(run.running_share),
            "idle_h_per_day": _real(24.0 * (1.0 - run.running_share)),
            "steady_start_share": _real(run.steady_start_share),
            "cop_unsupported_heat_share": _real(run.cop_unsupported_share),
        }
        for name, run in point.items()
    }
    out["cop_support"] = {
        "cells_k_k_hz": [OUTSIDE_STEP_K, OUTLET_STEP_K, HZ_STEP],
        "min_minutes": MIN_MINUTES,
        "tolerance": UNSUPPORTED_TOLERANCE,
    }
    return out


def idle_circulation_json(point: Mapping[str, RunOutput], circulation_w: float) -> JsonDict:
    """Convention for the circulation pump's draw and how much it can move the result.

    Electricity is the pump's own estimate (``Heat_Power_Consumption``) in the recording
    and, through the COP map and ``circulation_w``, in the model; it reads about 0 W
    with the compressor off, so the circulation pump's idle draw is outside both. The
    convention is the same for both runs and for the recording, so it biases a
    difference only through the time each run leaves the pump idle: every
    :data:`IDLE_DRAW_STEP_W` of unmodelled idle draw shifts ``ovenbird - baseline`` by
    ``IDLE_DRAW_STEP_W x (idle hours ovenbird - idle hours baseline)``.
    """
    idle = {name: 24.0 * (1.0 - out.running_share) for name, out in point.items()}
    shift = IDLE_DRAW_STEP_W * (idle[OVENBIRD] - idle[BASELINE]) / 1000.0
    elec = point[BASELINE].kpis.totals["elec_kwh_per_day"]
    return {
        "convention": "electricity is the pump's own estimate in the recording and the model; "
        f"it reads {circulation_w:.0f} W with the compressor off, so the circulation pump's "
        "idle draw is left out for both runs alike",
        "idle_h_per_day": {name: _real(v) for name, v in idle.items()},
        "elec_difference_shift_kwh_per_day_per_10w": _real(shift),
        "shift_relative_to_baseline_elec": _real(shift / elec if elec else math.nan),
    }


def _held_json(held: HeldOut) -> JsonDict:
    extra: JsonDict = {
        "period": {
            "start": meta.utc_iso(held.setup.start),
            "end": meta.utc_iso(held.setup.end),
            "days": len(held.setup.recorded.days),
        },
        "recorded_statement": recorded_statement(held.setup.recorded, "held-out block"),
        "kpis": {
            "recorded": dict(held.setup.recorded.totals),
            BASELINE: dict(held.output.kpis.totals),
        },
        "fidelity": [f.to_json() for f in held.fidelity.values()],
        "steady_start_share": _real(held.output.steady_start_share),
        "params": str(held.params_path),
    }
    return held.gate.to_json() | extra


def _clean(value: Any) -> JsonValue:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)


def _write(
    out: Path,
    summary: JsonDict,
    outputs: Mapping[str, RunOutput],
    setup: Setup,
    gate: GateResult,
    replicate_gates: Sequence[GateResult],
    diffs: Sequence[Difference],
    contributions: Mapping[str, Mapping[str, float]],
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    clean = _clean(summary)
    with ResultDB(out / DB_NAME) as db:
        meta_entries = clean["meta"] if isinstance(clean, dict) else {}
        db.set_meta(
            {
                **(meta_entries if isinstance(meta_entries, dict) else {}),
                "created": datetime.now(UTC).isoformat(timespec="seconds"),
                "gate_passed": gate.passed,
            }
        )
        controllers = summary["meta"]
        for run_id, output in sorted(outputs.items()):
            ovenbird = run_id.endswith(OVENBIRD) or run_id.startswith(("ablation", "calibration"))
            controller = OVENBIRD if ovenbird else BASELINE
            variant = run_id.split(":")[0] if ":" in run_id else "point"
            replicate = (
                int(run_id.split(":")[1]) if run_id.startswith(("replicate:", "first:")) else None
            )
            combo = run_id.split(":", 1)[1] if run_id.startswith("ablation:") else None
            db.add("runs", (run_id, controller, variant, replicate, combo, _hash(controllers)))
            for day, values in output.kpis.days.items():
                for name, value in values.items():
                    db.add("daily", (run_id, day, name, _real(value)))
            for name, value in output.kpis.totals.items():
                db.add("totals", (run_id, name, _real(value)))
            db.add_many("decisions", output.records)
            trace = output.trace
            if trace is not None:
                for k in range(trace.t.size):
                    db.add(
                        "trajectory",
                        (
                            run_id,
                            k,
                            float(trace.t[k]),
                            int(trace.setpoint[k]),
                            float(trace.room_c[k]),
                            float(trace.outlet_c[k]),
                            float(trace.heat_w[k]),
                            float(trace.elec_w[k]),
                            int(trace.running[k]),
                            int(trace.defrost[k]),
                            trace.reasons[k],
                        ),
                    )
        db.add("runs", ("recorded", "recorded", "recorded", None, None, "recording"))
        for day, values in setup.recorded.days.items():
            for name, value in values.items():
                db.add("daily", ("recorded", day, name, _real(value)))
        for name, value in setup.recorded.totals.items():
            db.add("totals", ("recorded", name, _real(value)))
        gates = [(BASELINE, gate)] + [
            (f"replicate:{i}:{BASELINE}", g) for i, g in enumerate(replicate_gates)
        ]
        for run_id, result in gates:
            for c in result.criteria:
                db.add(
                    "gate",
                    (
                        run_id,
                        c.name,
                        _real(c.simulated),
                        _real(c.recorded),
                        _real(c.error),
                        c.bound,
                        int(c.passed),
                        c.unit,
                    ),
                )
        for d in diffs:
            db.add(
                "differences",
                (
                    d.kpi,
                    _real(d.point),
                    _real(d.lo),
                    _real(d.hi),
                    d.n,
                    d.status.value,
                    dump(list(d.reasons)),
                ),
            )
        for name, terms in contributions.items():
            for term, value in terms.items():
                db.add("contributions", (name, term, _real(value)))
        db.set_meta(
            {"summary": {k: v for k, v in clean.items() if k not in ("daily", "meta")}}
            if isinstance(clean, dict)
            else {}
        )
    (out / SUMMARY_NAME).write_text(
        json.dumps(clean, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _real(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _hash(provenance: JsonValue) -> str:
    if isinstance(provenance, dict):
        value = provenance.get("config_hash")
        if isinstance(value, str):
            return value
    return "unknown"

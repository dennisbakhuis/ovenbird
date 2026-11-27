"""End-to-end identification: data, switching rule, heat pump, building, validation.

Two fits are made. The *validation fit* uses only data before the split and is
scored on the held-out block after it (blocked split: early weeks for fitting, the
coldest last weeks for testing); it is written too (``plant_params_train.json``), so
the counterfactual can gate its baseline held-out. The *final fit* uses all data and
is what the counterfactual compares on; its intervals come from day-block bootstrap
replicates. Both fits end with :func:`calibrate_cycling` on their own span.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ovenbird_sim.data.capture import load_capture
from ovenbird_sim.data.coverage import Coverage, coverage
from ovenbird_sim.data.dataset import Dataset, assemble, load_datalake
from ovenbird_sim.data.events import Event
from ovenbird_sim.data.weather import load_weather
from ovenbird_sim.identify.building import (
    Bootstrap,
    BuildingFit,
    FitConfig,
    Priors,
    Windows,
    bootstrap_building,
    fit_building,
    make_windows,
)
from ovenbird_sim.identify.emitter import EMITTER_FIELDS, EMITTER_HELD, EmitterMatch, match_emitter
from ovenbird_sim.identify.heatpump import (
    HeatPumpFit,
    WarmupCheck,
    bootstrap_heat_pump,
    check_warmup,
    fit_heat_pump,
    with_controller,
)
from ovenbird_sim.identify.switching import (
    BaseSignals,
    SwitchingReport,
    analyse_switching,
    base_signals,
)
from ovenbird_sim.identify.validate import (
    HorizonErrors,
    PlantDays,
    PlantSpan,
    filtered,
    horizon_errors,
    plant_days,
    plant_span,
)
from ovenbird_sim.model.building import J_PER_KWH, BuildingParams
from ovenbird_sim.model.plant import PlantParams

TEST_DAYS_DEFAULT = 14
EMITTER_ROUNDS = 3
EMITTER_CONVERGED = 0.05
INTERVAL_FIELDS = (
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
    "time_constant_h",
)


@dataclass(frozen=True, slots=True)
class IdentifyOptions:
    """Pipeline options.

    Parameters
    ----------
    capture_name
        Capture sub-directory.
    split
        First second of the test block (unix s); defaults to the start of the last
        ``test_days`` full days.
    test_days
        Length of the default test block.
    bootstrap
        Day-block bootstrap replicates (0 to skip).
    seed
        Random seed for the bootstrap.
    end
        End of the data used (unix s, exclusive); defaults to the end of the capture.
    folds
        Rolling-origin validation folds: test blocks of ``test_days`` tiling the end
        of the data, each fitted on the days before it only.
    priors
        Priors and constraints of every building fit (the module constants when
        ``None``). The emitter matching and the cycling calibration that follow a
        free-run fit change the mass capacity and the water-to-mass conductance, so a
        time-constant range holds for the free-run fits, not exactly for the result.
    """

    capture_name: str = "live"
    split: float | None = None
    test_days: int = TEST_DAYS_DEFAULT
    bootstrap: int = 50
    seed: int = 0
    end: float | None = None
    folds: int = 1
    priors: Priors | None = None


DEFAULT_OPTIONS = IdentifyOptions()


@dataclass(frozen=True, slots=True)
class IdentifyResult:
    """Everything the pipeline produced.

    Parameters
    ----------
    params
        Final parameters (all data).
    coverage
        Data coverage.
    switching
        Start/stop rule evidence (all data).
    heat_pump
        Final heat-pump fit diagnostics.
    building
        Final building fit.
    building_intervals
        90 % bootstrap intervals of building parameters.
    heat_pump_intervals
        90 % bootstrap intervals of heat-pump maps at reference points.
    split
        Start of the test block.
    validation_horizons
        Held-out free-run errors (building + hydronics with measured heat).
    validation_plant
        Held-out full-plant day simulations.
    validation_train_fit
        Building fit of the validation (train-only) run.
    train_params
        Parameters fitted and calibrated on the training block only (the held-out
        baseline gate of the counterfactual uses them).
    train_calibration, final_calibration
        Cycling calibration of the train-only and the final fit.
    held_out
        Train-only plant run continuously over the test block on recorded setpoints.
    warmup_check
        Warm-up COP map (fitted on the training block) on the test block.
    folds
        Rolling-origin folds, latest first (the fields above describe the latest).
    events
        Known events (stove fires) left out of the building fit and the scoring.
    event_windows
        Start times of the daily building-fit windows left out for them.
    """

    params: PlantParams
    coverage: Coverage
    switching: SwitchingReport
    heat_pump: HeatPumpFit
    building: BuildingFit
    building_intervals: dict[str, tuple[float, float]]
    heat_pump_intervals: dict[str, tuple[float, float]]
    split: float
    validation_horizons: HorizonErrors
    validation_plant: PlantDays
    validation_train_fit: BuildingFit
    train_params: PlantParams | None = None
    train_calibration: CyclingCalibration | None = None
    final_calibration: CyclingCalibration | None = None
    held_out: PlantSpan | None = None
    warmup_check: WarmupCheck | None = None
    folds: tuple[Fold, ...] = ()
    events: tuple[Event, ...] = ()
    event_windows: tuple[float, ...] = ()

    def to_json(self) -> dict[str, Any]:
        """JSON-ready report sections (parameters are written separately)."""
        b = self.params.building
        plant = self.validation_plant
        return {
            "generated": datetime.now(UTC).isoformat(timespec="seconds"),
            "data": {
                "start": self.coverage.start.isoformat(),
                "end": self.coverage.end.isoformat(),
                "days": self.coverage.days,
                "columns": self.coverage.columns,
                "flags": self.coverage.flags,
                "spread_offset_k": self.coverage.offset_k,
            },
            "derived": {
                "h_air_out_w_per_k": b.h_air_out,
                "time_constant_h": b.time_constant_h,
                "capacities_kwh_per_k": {
                    "water": b.c_water / J_PER_KWH,
                    "mass": b.c_mass / J_PER_KWH,
                    "air": b.c_air / J_PER_KWH,
                },
            },
            "intervals_90": {
                "building": {k: list(v) for k, v in self.building_intervals.items()},
                "heat_pump": {k: list(v) for k, v in self.heat_pump_intervals.items()},
            },
            "events": {
                "items": [event.to_json() for event in self.events],
                "excluded_fit_windows": [
                    datetime.fromtimestamp(t, UTC).isoformat() for t in self.event_windows
                ],
                "policy": "building-fit windows overlapping an event or its recovery tail are "
                "left out; validation KPIs leave out the UTC days it touches",
            },
            "switching": _switching_json(self.switching),
            "heat_pump_fit": {
                "capacity_rmse_w": self.heat_pump.capacity_rmse_w,
                "cop_rmse_log": self.heat_pump.cop_rmse_log,
                "n_steady_bins": self.heat_pump.n_steady,
                "defrost_events": self.heat_pump.defrost_events,
                "defrost_rate_table": [list(r) for r in self.heat_pump.defrost_rate_table],
                "p1_step_over_pump_estimate": self.heat_pump.p1_ratio,
                "pump_heat_estimate_over_loop_heat": self.heat_pump.pump_vs_loop_heat,
                "frequency_controller": asdict(self.heat_pump.controller),
                "frequency_controller_candidates": [
                    asdict(c) for c in self.heat_pump.controller_candidates
                ],
                "capacity_map": None
                if self.heat_pump.capacity is None
                else asdict(self.heat_pump.capacity),
                "cop_map": None if self.heat_pump.cop is None else asdict(self.heat_pump.cop),
                "cop_steady_map": None
                if self.heat_pump.cop_steady is None
                else asdict(self.heat_pump.cop_steady),
                "frost": None if self.heat_pump.frost is None else asdict(self.heat_pump.frost),
            },
            "validation": {
                "split": datetime.fromtimestamp(self.split, UTC).isoformat(),
                "train_fit_rmse": {
                    "water_k": self.validation_train_fit.rmse_water,
                    "room_k": self.validation_train_fit.rmse_room,
                    "windows": self.validation_train_fit.n_windows,
                },
                "free_run": asdict(self.validation_horizons),
                "train_calibration": _calibration_json(self.train_calibration),
                "final_calibration": _calibration_json(self.final_calibration),
                "held_out_span": _span_json(self.held_out),
                "cop_warmup_held_out": None
                if self.warmup_check is None
                else asdict(self.warmup_check),
                "folds": [_fold_json(f) for f in self.folds],
                "plant_days": {
                    "days": int(plant.day_starts.size),
                    "heat_error_pct": plant.heat_error_pct,
                    "daily_heat_mape_pct": plant.daily_heat_mape_pct,
                    "starts_error_pct": plant.starts_error_pct,
                    "starts_per_day_measured": _mean(plant.starts_measured),
                    "starts_per_day_simulated": _mean(plant.starts_simulated),
                    "room_rmse_k": _mean(plant.room_rmse),
                    "outlet_rmse_k": _mean(plant.outlet_rmse),
                },
            },
        }


def _fold_json(fold: Fold) -> dict[str, Any]:
    return {
        "split": datetime.fromtimestamp(fold.split, UTC).isoformat(),
        "test_end": datetime.fromtimestamp(fold.end, UTC).isoformat(),
        "train_fit_rmse": {
            "water_k": fold.building.rmse_water,
            "room_k": fold.building.rmse_room,
            "windows": fold.building.n_windows,
        },
        "held_out_span": _span_json(fold.held_out),
        "plant_days": {
            "days": int(fold.days.day_starts.size),
            "heat_error_pct": fold.days.heat_error_pct,
            "starts_error_pct": fold.days.starts_error_pct,
        },
    }


def _span_json(span: PlantSpan | None) -> dict[str, Any] | None:
    if span is None:
        return None
    return {
        "start": datetime.fromtimestamp(span.start, UTC).isoformat(),
        "end": datetime.fromtimestamp(span.end, UTC).isoformat(),
        "days": span.days,
        "measured": span.measured,
        "simulated": span.simulated,
        "errors": {name: span.error(name) for name in span.measured},
        "room_rmse_k": span.room_rmse_k,
        "steady_start_share": span.steady_start_share,
    }


def _calibration_json(cal: CyclingCalibration | None) -> dict[str, Any] | None:
    if cal is None:
        return None
    return {
        "return_delay_s": cal.return_delay_s,
        "water_mass_scale": cal.water_mass_scale,
        "controller_index": cal.controller_index,
        "emitter": None if cal.emitter is None else asdict(cal.emitter),
        "span": _span_json(cal.span),
        "tried": [list(row) for row in cal.tried],
    }


def _mean(values: Any) -> float:
    return float(sum(values) / len(values)) if len(values) else math.nan


def _switching_json(r: SwitchingReport) -> dict[str, Any]:
    out = asdict(r)
    out["p_start_after_change"] = {f"{k:+.2f}": v for k, v in r.p_start_after_change.items()}
    out["p_start_steady"] = {f"{k:+.2f}": v for k, v in r.p_start_steady.items()}
    return out


def _building_intervals(boot: Bootstrap) -> dict[str, tuple[float, float]]:
    return {name: boot.interval(name) for name in INTERVAL_FIELDS} if boot.samples else {}


RETURN_DELAYS_S: tuple[float, ...] = (240.0, 360.0, 480.0)
WATER_MASS_SCALES: tuple[float, ...] = (0.8, 0.85, 0.9, 0.95, 1.0)
CANDIDATES_TRIED = 2


@dataclass(frozen=True, slots=True)
class CyclingCalibration:
    """Result of :func:`calibrate_cycling`.

    Parameters
    ----------
    return_delay_s
        Selected return transport delay.
    water_mass_scale
        Factor on the 5-min fit's water-mass conductance.
    controller_index
        Selected frequency-controller candidate.
    span
        Fit of the selected plant on the calibration span.
    tried
        ``(delay, scale, candidate, score)`` of every combination.
    emitter
        Emitter capacity matched to the recorded off-period cooling (before the grid).
    """

    return_delay_s: float
    water_mass_scale: float
    controller_index: int
    span: PlantSpan
    tried: tuple[tuple[float, float, int, float], ...]
    emitter: EmitterMatch | None = None


def calibrate_cycling(
    fit: HeatPumpFit,
    building: BuildingParams,
    ds: Dataset,
    coarse: Dataset,
    start: float,
    end: float,
    emitter: EmitterMatch | None = None,
) -> tuple[HeatPumpFit, BuildingParams, CyclingCalibration]:
    """Calibrate what the 5-min building fit cannot resolve on the cycling of ``[start, end)``.

    The water node's coupling to the floor mass (time constant of minutes) and the
    return transport delay decide how fast the outlet reaches the stop margin after a
    start and how fast the inlet falls to the start margin after a stop; neither is
    resolved by the 5-min free-run fit nor by the frequency replay. A small grid
    (:data:`RETURN_DELAYS_S` x :data:`WATER_MASS_SCALES` x the best
    :data:`CANDIDATES_TRIED` frequency-controller candidates) is run continuously on
    the recorded setpoints over the span (:func:`plant_span`) and the combination with
    the smallest summed error in heat, electricity, starts, median run length and
    short-run share is kept. Only data inside the span is used, so calibrating on the
    training block leaves the test block untouched.

    Parameters
    ----------
    fit
        Heat-pump fit with its controller candidates.
    building
        Building parameters of the free-run fit.
    ds, coarse
        1 min and 5 min datasets.
    start, end
        Calibration span in unix seconds.
    emitter
        Emitter match of ``building`` (:func:`fit_matched_building`), kept in the record.

    Returns
    -------
    HeatPumpFit, BuildingParams, CyclingCalibration
        The calibrated layers and the calibration record.
    """
    candidates = fit.controller_candidates or (fit.controller,)
    tried: list[tuple[float, float, int, float]] = []
    best: tuple[float, float, float, int, PlantSpan] | None = None
    for scale in WATER_MASS_SCALES:
        scaled = replace(building, h_water_mass=building.h_water_mass * scale)
        states = filtered(coarse, scaled)
        for index, candidate in enumerate(candidates[:CANDIDATES_TRIED]):
            for delay in RETURN_DELAYS_S:
                hp = with_controller(fit.params, candidate).replace(return_delay_s=delay)
                span = plant_span(ds, PlantParams(hp, scaled), start, end, (coarse, states))
                tried.append((delay, scale, index, span.score))
                if best is None or span.score < best[0]:
                    best = (span.score, delay, scale, index, span)
    if best is None:
        raise ValueError("nothing to calibrate")
    _, delay, scale, index, span = best
    chosen = candidates[index]
    params = with_controller(fit.params, chosen).replace(return_delay_s=delay)
    calibrated = replace(fit, params=params, controller=chosen)
    record = CyclingCalibration(delay, scale, index, span, tuple(tried), emitter)
    return (
        calibrated,
        replace(building, h_water_mass=building.h_water_mass * scale),
        record,
    )


def fit_matched_building(
    windows: Windows,
    config: FitConfig,
    ds: Dataset,
    coarse: Dataset,
    fit: HeatPumpFit,
    span: tuple[float, float],
    start: BuildingParams | None = None,
    priors: Priors | None = None,
) -> tuple[BuildingFit, EmitterMatch | None]:
    """Free-run building fit with the emitter capacity tied to the off-period cooling.

    The free-run fit leaves the emitter capacity nearly unconstrained, while the
    recorded off periods pin the loop's cooling time constant
    (:mod:`ovenbird_sim.identify.emitter`). The two are combined by alternation: match
    the capacity to the recorded time constant, refit the other parameters with the
    emitter held (:data:`EMITTER_FIELDS`: its capacity and its conductances to the air,
    as the first free fit found them), and repeat until the matched capacity moves
    less than :data:`EMITTER_CONVERGED` (at most :data:`EMITTER_ROUNDS` refits). The
    conductances are held with the capacity because the free fit trades the
    emitter-air path against a direct water-air path; refitting them with the capacity
    pinned re-routes the heat through the water node to a bound and undoes the matched
    cooling.

    Parameters
    ----------
    windows, config
        Free-run windows and fit configuration.
    ds, coarse
        1 min and 5 min datasets.
    fit
        Heat-pump fit (its first controller candidate drives the plant).
    span
        Span of the recording used, in unix seconds.
    start
        Warm start of the first free-run fit.
    priors
        Priors and constraints of the free-run fits.

    Returns
    -------
    BuildingFit, EmitterMatch or None
        The fit and the last emitter match.
    """
    building = fit_building(windows, config, start=start, priors=priors)
    hp = with_controller(fit.params, (fit.controller_candidates or (fit.controller,))[0])
    held = replace(config, fixed=(*config.fixed, *EMITTER_FIELDS))
    match: EmitterMatch | None = None
    for _ in range(EMITTER_ROUNDS):
        params = building.params
        matched, match = match_emitter(
            ds, PlantParams(hp, params), *span, (coarse, filtered(coarse, params))
        )
        if abs(matched.c_mass / params.c_mass - 1.0) <= EMITTER_CONVERGED:
            break
        building = fit_building(windows, held, start=matched, priors=priors)
    return building, match


def default_split(ds: Dataset, test_days: int) -> float:
    """Start of the last ``test_days`` full UTC days."""
    last_midnight = math.floor(ds.grid.end / 86400.0) * 86400.0
    return last_midnight - test_days * 86400.0


@dataclass(frozen=True, slots=True)
class Fold:
    """One rolling-origin validation fold: fit before ``split``, test on ``[split, end)``.

    Parameters
    ----------
    split, end
        Test block in unix seconds.
    params
        Parameters fitted and calibrated on the data before ``split`` only.
    building
        Building fit of the training block.
    calibration
        Cycling calibration on the training block.
    horizons
        Free-run errors on the test block.
    days
        Full-plant day simulations of the test block (daily restart).
    held_out
        Continuous run of the test block on recorded setpoints.
    warmup
        Warm-up COP map of the training block on the test block.
    """

    split: float
    end: float
    params: PlantParams
    building: BuildingFit
    calibration: CyclingCalibration
    horizons: HorizonErrors
    days: PlantDays
    held_out: PlantSpan
    warmup: WarmupCheck | None


def fold_splits(ds: Dataset, options: IdentifyOptions) -> list[tuple[float, float]]:
    """Test blocks of the rolling-origin validation, latest first.

    The latest block is the last ``test_days`` full days (or starts at
    ``options.split``); every earlier fold ends where the next one starts, so the test
    blocks tile the end of the data and each is fitted only on the days before it.
    """
    span = options.test_days * 86400.0
    first = options.split if options.split is not None else default_split(ds, options.test_days)
    last = min(first + span, math.floor(ds.grid.end / 86400.0) * 86400.0)
    out = [(first, last)]
    for k in range(1, max(options.folds, 1)):
        out.append((first - k * span, first - (k - 1) * span))
    return out


def train_fold(
    ds: Dataset,
    coarse: Dataset,
    base: BaseSignals,
    split: float,
    end: float,
    config: FitConfig,
    priors: Priors | None = None,
) -> Fold:
    """Fit on the data before ``split`` and score on ``[split, end)``."""
    burn_in = ds.grid.start + 86400.0
    train_switch = analyse_switching(base.window(end=split), base.step)
    n_train = round((split - ds.grid.start) / ds.grid.step)
    train_ds = ds.slice(0, n_train)
    train_hp = fit_heat_pump(train_ds, train_switch.start_fit, train_switch.start_phase)
    train_building, emitter = fit_matched_building(
        make_windows(coarse, config, end=split),
        config,
        ds,
        coarse,
        train_hp,
        (burn_in, split),
        priors=priors,
    )
    horizons = horizon_errors(coarse, train_building.params, split, end)
    train_hp, train_b, train_cal = calibrate_cycling(
        train_hp, train_building.params, ds, coarse, burn_in, split, emitter
    )
    params = PlantParams(train_hp.params, train_b)
    states = filtered(coarse, train_b)
    n_end = round((end - ds.grid.start) / ds.grid.step)
    warmup = (
        check_warmup(ds.slice(n_train, n_end), train_hp.cop, train_hp.cop_steady)
        if train_hp.cop is not None and train_hp.cop_steady is not None
        else None
    )
    return Fold(
        split=split,
        end=end,
        params=params,
        building=train_building,
        calibration=train_cal,
        horizons=horizons,
        days=plant_days(ds, params, split, end, (coarse, states)),
        held_out=plant_span(ds, params, split, end, (coarse, states)),
        warmup=warmup,
    )


def identify(captures: Path, options: IdentifyOptions = DEFAULT_OPTIONS) -> IdentifyResult:
    """Run the whole identification on a captures root.

    Parameters
    ----------
    captures
        Root holding the capture, ``datalake/`` and ``weather/``.
    options
        Pipeline options.

    Returns
    -------
    IdentifyResult
        Final parameters, train-only parameters per fold, intervals and validation.
    """
    capture = load_capture(captures / options.capture_name)
    ds = assemble(
        capture,
        datalake=load_datalake(captures / "datalake"),
        weather=load_weather(captures / "weather"),
        step=60.0,
        end=options.end,
    )
    return identify_dataset(ds, base_signals(capture).window(end=options.end), options)


def identify_dataset(
    ds: Dataset, base: BaseSignals, options: IdentifyOptions = DEFAULT_OPTIONS
) -> IdentifyResult:
    """Run the whole identification on an assembled dataset.

    Parameters
    ----------
    ds
        Dataset on a 60 s grid (a capture's, or the service history's 1 min rollups).
    base
        Switching signals over the same span (5 s from a capture, 60 s from history).
    options
        Pipeline options (``capture_name`` and ``end`` are not used here).

    Returns
    -------
    IdentifyResult
        Final parameters, train-only parameters per fold, intervals and validation.
    """
    coarse = ds.coarsen(5)
    config = FitConfig()
    burn_in = ds.grid.start + 86400.0
    folds = tuple(
        train_fold(ds, coarse, base, split, end, config, options.priors)
        for split, end in fold_splits(ds, options)
    )
    latest = folds[0]

    switching = analyse_switching(base, base.step)
    hp_fit = fit_heat_pump(ds, switching.start_fit, switching.start_phase)
    windows = make_windows(coarse, config)
    building, emitter = fit_matched_building(
        windows,
        config,
        ds,
        coarse,
        hp_fit,
        (burn_in, ds.grid.end),
        latest.building.params,
        options.priors,
    )
    hp_fit, final_b, final_cal = calibrate_cycling(
        hp_fit, building.params, ds, coarse, burn_in, ds.grid.end, emitter
    )
    boot = (
        bootstrap_building(
            windows, building, options.bootstrap, EMITTER_HELD, options.seed, options.priors
        )
        if options.bootstrap > 0
        else Bootstrap(())
    )
    building = replace(building, params=final_b)
    intervals = _building_intervals(boot)
    if "h_water_mass" in intervals:
        lo, hi = intervals["h_water_mass"]
        intervals["h_water_mass"] = (
            lo * final_cal.water_mass_scale,
            hi * final_cal.water_mass_scale,
        )
    hp_intervals = (
        bootstrap_heat_pump(ds, hp_fit.params, options.bootstrap, options.seed)
        if options.bootstrap > 0
        else {}
    )
    return IdentifyResult(
        params=PlantParams(hp_fit.params, building.params),
        coverage=coverage(ds),
        switching=switching,
        heat_pump=hp_fit,
        building=building,
        building_intervals=intervals,
        heat_pump_intervals=hp_intervals,
        split=latest.split,
        validation_horizons=latest.horizons,
        validation_plant=latest.days,
        validation_train_fit=latest.building,
        train_params=latest.params,
        train_calibration=latest.calibration,
        final_calibration=final_cal,
        held_out=latest.held_out,
        warmup_check=latest.warmup,
        folds=folds,
        events=ds.events,
        event_windows=windows.event_starts,
    )


def describe_building(p: BuildingParams, intervals: dict[str, tuple[float, float]]) -> list[str]:
    """Report lines for the building parameters with their intervals."""
    scale = {
        "c_water": (J_PER_KWH, "kWh/K"),
        "c_mass": (J_PER_KWH, "kWh/K"),
        "c_air": (J_PER_KWH, "kWh/K"),
        "h_water_mass": (1.0, "W/K"),
        "h_water_air": (1.0, "W/K"),
        "h_mass_air": (1.0, "W/K"),
        "h_air_out": (1.0, "W/K"),
        "solar_aperture_m2": (1.0, "m2"),
        "solar_mass_fraction": (1.0, ""),
        "q_int_w": (1.0, "W"),
        "q_int_modulation": (1.0, ""),
        "q_int_peak_hour": (1.0, "h"),
        "time_constant_h": (1.0, "h"),
    }
    lines = []
    for name, (div, unit) in scale.items():
        value = p.time_constant_h if name == "time_constant_h" else float(getattr(p, name))
        lo, hi = intervals.get(name, (math.nan, math.nan))
        lines.append(
            f"  {name:20s} {value / div:10.3f} {unit:6s} [{lo / div:.3f} .. {hi / div:.3f}]"
        )
    return lines

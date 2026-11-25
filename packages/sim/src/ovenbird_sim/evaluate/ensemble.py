"""Day-block bootstrap replicates of the plant parameters, cached next to the point fit.

The identification step stores only percentile intervals, so the replicates are
rebuilt here. Every replicate draws one day-block resample (UTC days with
replacement) and refits every layer on those same days:

* building layer: :func:`bootstrap_building_days` (the daily free-run windows of the
  picked days, refit warm-started at the free-run point; the cycling calibration's
  water-mass factor is applied afterwards). The emitter (capacity and its
  conductances to the air) is held: its cooling is identified by hundreds of recorded
  off periods (:mod:`ovenbird_sim.identify.emitter`), which the daily windows hardly
  constrain;
* heat-pump maps: capacity and COP with their start-up terms, idle draw and defrost
  rate (:func:`ovenbird_sim.identify.heatpump.refit_maps`);
* frequency controller: replayed on the resampled run segments
  (:func:`ovenbird_sim.identify.heatpump.refit_controller`);
* start rule: grid search on the off periods of the resampled days
  (:func:`ovenbird_sim.identify.switching.fit_start_rule`, base grid).

Held at the point estimate: the start phase (frequency and duration, which barely
vary between starts), the stop rule (it explains nearly all stops), the return delay
and water-mass factor of the cycling calibration (a closed-loop grid search), and
the flows and sensor offsets. Replicates are built in worker processes and cached
as ``plant_replicates.json`` keyed by the point file's hash, the count and the seed.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

import numpy as np

from ovenbird_sim.data.dataset import Dataset
from ovenbird_sim.data.series import Series
from ovenbird_sim.evaluate.meta import file_hash
from ovenbird_sim.identify.building import (
    BuildingFit,
    FitConfig,
    Windows,
    fit_building,
    make_windows,
)
from ovenbird_sim.identify.emitter import EMITTER_HELD
from ovenbird_sim.identify.heatpump import (
    day_index,
    refit_controller,
    refit_maps,
    resample_days,
    utc_days,
)
from ovenbird_sim.identify.io import load_report, params_from_dict, params_to_dict
from ovenbird_sim.identify.switching import (
    BaseSignals,
    base_signals,
    fit_start_rule,
    heating_switches,
)
from ovenbird_sim.model.building import BuildingParams
from ovenbird_sim.model.heatpump import HeatPumpParams
from ovenbird_sim.model.plant import PlantParams

SCHEMA: Final = "ovenbird.plant-replicates/3"
CACHE_NAME: Final = "plant_replicates.json"
COARSEN: Final = 5
HEAT_PUMP_SEED_OFFSET: Final = 7919
_STATE: dict[str, Any] = {}


def water_mass_scale(params_path: Path) -> float:
    """Return the cycling calibration's water-mass factor stored with the parameters."""
    try:
        report = load_report(params_path)
    except OSError, ValueError:
        return 1.0
    calibration = report.get("validation", {}).get("final_calibration") or {}
    value = calibration.get("water_mass_scale")
    return float(value) if isinstance(value, int | float) else 1.0


def _install(ds: Dataset, sig: BaseSignals | None) -> None:
    _STATE["ds"] = ds
    _STATE["sig"] = sig


def _start_rule(
    sig: BaseSignals, ds_t0: float, point: HeatPumpParams, picked: np.ndarray
) -> dict[str, float]:
    starts, stops = heating_switches(sig)
    if not starts.size:
        return {}
    day = utc_days(sig.t[starts], ds_t0)
    keep = day >= 0
    starts, day = starts[keep], day[keep]
    counts = np.bincount(picked, minlength=int(max(day.max(), picked.max())) + 1)
    chosen = np.repeat(starts, counts[day])
    if chosen.size < 10:
        return {}
    fit = fit_start_rule(sig, np.sort(chosen), stops)
    return {
        "start_trigger_margin_k": fit.trigger_margin_k,
        "start_steady_margin_k": fit.steady_margin_k,
        "start_steady_delay_s": fit.steady_delay_s,
        "min_off_s": point.min_off_s,
    }


def heat_pump_replicate(point: HeatPumpParams, picked: np.ndarray) -> HeatPumpParams:
    """Refit the heat-pump layer on one resample of days (uses the installed dataset)."""
    ds: Dataset = _STATE["ds"]
    sig: BaseSignals | None = _STATE.get("sig")
    params = refit_maps(ds, point, picked)
    params = refit_controller(ds, params, picked)
    if sig is not None:
        params = params.replace(**_start_rule(sig, ds.grid.start, point, picked))
    return params


def _replicate_task(args: tuple[HeatPumpParams, np.ndarray]) -> HeatPumpParams:
    return heat_pump_replicate(*args)


def day_picks(ds: Dataset, n: int, seed: int) -> list[np.ndarray]:
    """One day-block resample (UTC days with replacement) per replicate."""
    days = np.unique(day_index(ds))
    rng = np.random.default_rng(seed + HEAT_PUMP_SEED_OFFSET)
    return [resample_days(days, rng) for _ in range(n)]


def heat_pump_replicates(
    ds: Dataset,
    point: HeatPumpParams,
    picks: list[np.ndarray],
    capture: Mapping[str, Series] | None = None,
    workers: int | None = None,
) -> list[HeatPumpParams]:
    """Refit the heat-pump layer on day-block resamples.

    Parameters
    ----------
    ds
        Dataset on the 60 s grid.
    point
        Point estimate.
    picks
        Day numbers of every replicate (:func:`day_picks`).
    capture
        Raw capture series (the start rule is refitted on its base grid; kept at the
        point without it).
    workers
        Worker processes (``None``: CPU count).

    Returns
    -------
    list of HeatPumpParams
        One parameter set per replicate.
    """
    n = len(picks)
    if n == 0:
        return []
    sig = base_signals(capture) if capture is not None else None
    count = min(workers or os.cpu_count() or 1, n)
    if count <= 1:
        _install(ds, sig)
        return [heat_pump_replicate(point, pick) for pick in picks]
    with ProcessPoolExecutor(count, initializer=_install, initargs=(ds, sig)) as pool:
        return list(pool.map(_replicate_task, [(point, pick) for pick in picks]))


def make_replicates(
    ds: Dataset,
    point: PlantParams,
    n: int,
    seed: int,
    *,
    capture: Mapping[str, Series] | None = None,
    scale: float = 1.0,
    workers: int | None = None,
) -> list[PlantParams]:
    """Build ``n`` plant parameter replicates (see the module docstring).

    Parameters
    ----------
    ds
        Dataset on the 60 s grid.
    point
        Point estimate.
    n
        Replicates.
    seed
        Random seed.
    capture
        Raw capture series (for the start-rule refit).
    scale
        Water-mass factor of the cycling calibration in ``point``.
    workers
        Worker processes.

    Returns
    -------
    list of PlantParams
        The replicates.
    """
    if n <= 0:
        return []
    config = EMITTER_HELD
    windows = make_windows(ds.coarsen(COARSEN), config)
    free = replace(point.building, h_water_mass=point.building.h_water_mass / scale)
    anchor = BuildingFit(free, np.zeros(windows.n), 0.0, 0.0, 0.0, windows.n, True)
    picks = day_picks(ds, n, seed)
    window_days = utc_days(windows.starts, ds.grid.start)
    building = [
        replace(b, h_water_mass=b.h_water_mass * scale)
        for b in bootstrap_building_days(windows, anchor, window_days, picks, config)
    ]
    pumps = heat_pump_replicates(ds, point.heat_pump, picks, capture, workers)
    return [PlantParams(h, b) for h, b in zip(pumps, building, strict=True)]


def bootstrap_building_days(
    windows: Windows,
    anchor: BuildingFit,
    window_days: np.ndarray,
    picks: list[np.ndarray],
    config: FitConfig,
) -> list[BuildingParams]:
    """Refit the building on the windows of every replicate's picked days.

    A day picked k times contributes its window k times; days without a usable
    window contribute nothing, so the building and the heat-pump layer of one
    replicate rest on the same days.
    """
    by_day = {int(d): i for i, d in enumerate(window_days)}
    out = []
    for pick in picks:
        index = [by_day[int(d)] for d in pick if int(d) in by_day]
        if not index:
            out.append(anchor.params)
            continue
        out.append(fit_building(windows.take(index), config, start=anchor.params).params)
    return out


def cache_path(params_path: Path) -> Path:
    """Replicate cache next to a parameter file."""
    return params_path.parent / CACHE_NAME


def load_cached(params_path: Path, n: int, seed: int) -> list[PlantParams] | None:
    """Return cached replicates for this parameter file, count and seed, if present."""
    path = cache_path(params_path)
    if not path.exists():
        return None
    try:
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    key = payload.get("key", {})
    expected = {"params_hash": file_hash(params_path), "seed": seed}
    if payload.get("schema") != SCHEMA or any(key.get(k) != v for k, v in expected.items()):
        return None
    replicates = payload.get("replicates", [])
    if len(replicates) < n:
        return None
    return [params_from_dict(item) for item in replicates[:n]]


def save_cache(params_path: Path, replicates: list[PlantParams], seed: int) -> Path:
    """Write replicates to the cache next to ``params_path``."""
    path = cache_path(params_path)
    payload = {
        "schema": SCHEMA,
        "key": {"params_hash": file_hash(params_path), "seed": seed, "n": len(replicates)},
        "note": "day-block bootstrap replicates; see ovenbird_sim.evaluate.ensemble",
        "replicates": [params_to_dict(p) for p in replicates],
    }
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return path


def replicates(
    params_path: Path,
    ds: Dataset,
    point: PlantParams,
    n: int,
    seed: int,
    capture: Mapping[str, Series] | None = None,
    workers: int | None = None,
) -> tuple[list[PlantParams], bool]:
    """Return ``n`` replicates, from the cache when it matches, else built and cached.

    Parameters
    ----------
    params_path
        Point parameter file (its hash keys the cache).
    ds
        Dataset on the 60 s grid.
    point
        Point estimate.
    n
        Replicates.
    seed
        Random seed.
    capture
        Raw capture series (for the start-rule refit).
    workers
        Worker processes.

    Returns
    -------
    list of PlantParams, bool
        Replicates and whether they came from the cache.
    """
    if n <= 0:
        return [], False
    cached = load_cached(params_path, n, seed)
    if cached is not None:
        return cached, True
    built = make_replicates(
        ds,
        point,
        n,
        seed,
        capture=capture,
        scale=water_mass_scale(params_path),
        workers=workers,
    )
    save_cache(params_path, built, seed)
    return built, False

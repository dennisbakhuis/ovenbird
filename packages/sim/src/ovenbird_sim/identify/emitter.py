"""Emitter heat capacity from the loop's cooling during compressor-off periods.

With the compressor off the circulation keeps running, the water node settles onto
the emitter (the floor mass) within minutes, and loop plus emitter then cool together
towards the room through the emitter-room conductance. The loop mean minus the room
decays exponentially; its time constant is the emitter's capacity over that
conductance. The recording shows it in every off period (about 1.2 h, the same in mild
and cold weeks), while the 5-min free-run fit of :mod:`ovenbird_sim.identify.building`
leaves the emitter capacity almost free (its bootstrap interval spans two decades).
The off-period decay sets how long the pump stays off after a stop, so it decides the
cycling, and through the room a controller's setpoint changes and starts.

:func:`match_emitter` measures the time constant on the recording and on the plant
driven by the recorded setpoints with the same estimator (:func:`off_period_tau_h`)
and scales the emitter capacity until both agree;
:func:`ovenbird_sim.identify.pipeline.fit_matched_building` refits the other building
parameters around it with :data:`EMITTER_FIELDS` held.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, replace

import numpy as np

from ovenbird_sim.data.dataset import Dataset
from ovenbird_sim.data.series import FloatArray
from ovenbird_sim.identify.building import BOUNDS, FitConfig, observations
from ovenbird_sim.identify.validate import humidity, state_at
from ovenbird_sim.model.building import BuildingParams
from ovenbird_sim.model.plant import PlantParams
from ovenbird_sim.model.simulate import run

SKIP_AFTER_STOP_S = 600.0
MIN_PERIOD_S = 1800.0
MIN_EXCESS_K = 0.5
MIN_PERIODS = 10
ITERATIONS = 4
TOLERANCE = 0.02
EMITTER_FIELDS = ("c_mass", "h_mass_air", "h_water_air")
EMITTER_HELD = FitConfig(fixed=EMITTER_FIELDS)


def off_period_tau_h(
    t: FloatArray, water: FloatArray, room: FloatArray, running: np.ndarray
) -> tuple[float, int]:
    """Median cooling time constant of the loop over the room in off periods.

    Every completed off period (compressor off from a stop to the next start) of at
    least :data:`SKIP_AFTER_STOP_S` + :data:`MIN_PERIOD_S` is used from
    :data:`SKIP_AFTER_STOP_S` after the stop; ``ln(water - room)`` is fitted with a
    line and the time constant is minus its inverse slope.

    Parameters
    ----------
    t
        Bin times (60 s grid).
    water, room
        Loop mean and room temperature per bin.
    running
        Compressor flag per bin.

    Returns
    -------
    tau_h, periods
        Median time constant in hours (``NaN`` with fewer than :data:`MIN_PERIODS`
        periods) and the number of periods used.
    """
    step = float(t[1] - t[0]) if t.size > 1 else 60.0
    skip = round(SKIP_AFTER_STOP_S / step)
    shortest = round(MIN_PERIOD_S / step)
    run_flag = np.asarray(running, dtype=np.int64)
    edges = np.flatnonzero(np.diff(run_flag))
    taus = []
    for a, b in itertools.pairwise(edges):
        if run_flag[a + 1]:
            continue
        s, e = a + 1 + skip, b + 1
        if e - s < shortest:
            continue
        excess = water[s:e] - room[s:e]
        if not np.all(np.isfinite(excess)) or excess.min() <= MIN_EXCESS_K:
            continue
        slope = np.polyfit((t[s:e] - t[s]) / 3600.0, np.log(excess), 1)[0]
        if slope < 0:
            taus.append(-1.0 / slope)
    if len(taus) < MIN_PERIODS:
        return math.nan, len(taus)
    return float(np.median(taus)), len(taus)


def recorded_tau_h(ds: Dataset, start: float, end: float) -> tuple[float, int]:
    """Off-period time constant of the recording over ``[start, end)`` (known events left out)."""
    i0, i1 = _bins(ds, start, end)
    water, room = observations(ds)
    gap = ds.flags["gap"] | ds.flags["defrost"] | ds.event_mask()
    running = (np.nan_to_num(ds.columns["compressor_frac"]) > 0.0) | gap
    return off_period_tau_h(ds.t[i0:i1], water[i0:i1], room[i0:i1], running[i0:i1])


def model_tau_h(
    ds: Dataset,
    params: PlantParams,
    start: float,
    end: float,
    states_5min: tuple[Dataset, np.ndarray],
) -> tuple[float, int]:
    """Off-period time constant of the plant on the recorded setpoints over ``[start, end)``."""
    i0, i1 = _bins(ds, start, end)
    c = ds.columns
    coarse, states = states_5min
    setpoint = np.round(_held(c["target"], 30.0))[i0:i1]
    traj = run(
        params,
        state_at(ds, coarse, states, i0),
        setpoint,
        _held(c["outside"], 10.0)[i0:i1],
        np.nan_to_num(c.get("ghi", np.zeros(ds.grid.n)), nan=0.0)[i0:i1],
        c["local_hour"][i0:i1],
        ds.grid.step,
        humidity(ds)[i0:i1],
    )
    busy = (traj.running > 0) | ds.event_mask()[i0:i1]
    return off_period_tau_h(ds.t[i0:i1], traj.t_water, traj.t_air, busy)


@dataclass(frozen=True, slots=True)
class EmitterMatch:
    """Result of :func:`match_emitter`.

    Parameters
    ----------
    tau_recorded_h
        Off-period time constant of the recording.
    tau_free_h, tau_matched_h
        The plant's before and after the match.
    c_mass_free, c_mass
        Emitter capacity of the free-run fit and after the match (J/K).
    periods
        Recorded off periods used.
    """

    tau_recorded_h: float
    tau_free_h: float
    tau_matched_h: float
    c_mass_free: float
    c_mass: float
    periods: int


def match_emitter(
    ds: Dataset,
    params: PlantParams,
    start: float,
    end: float,
    filtered: tuple[Dataset, np.ndarray],
) -> tuple[BuildingParams, EmitterMatch]:
    """Scale the emitter capacity so the plant's off-period cooling matches the recording.

    The slow off-period mode has the time constant ``(c_water + c_mass) / h_mass_air``,
    so each step rescales ``c_water + c_mass`` by the ratio of recorded to simulated
    time constant (at most :data:`ITERATIONS` steps, stopping within
    :data:`TOLERANCE`), within the building fit's bounds.

    Parameters
    ----------
    ds
        Dataset on the 60 s grid.
    params
        Plant parameters with the free-run building.
    start, end
        Span used (the training block in a validation fold).
    filtered
        Coarse dataset and its filtered states (initial state).

    Returns
    -------
    BuildingParams, EmitterMatch
        The building with the matched emitter capacity and the match record.
    """
    recorded, periods = recorded_tau_h(ds, start, end)
    building = params.building
    free, _ = model_tau_h(ds, params, start, end, filtered)
    if not (math.isfinite(recorded) and math.isfinite(free)):
        return building, EmitterMatch(recorded, free, free, building.c_mass, building.c_mass, 0)
    lo, hi = BOUNDS["c_mass"]
    tau = free
    for _ in range(ITERATIONS):
        if abs(tau / recorded - 1.0) <= TOLERANCE:
            break
        total = (building.c_water + building.c_mass) * recorded / tau
        building = replace(building, c_mass=float(np.clip(total - building.c_water, lo, hi)))
        tau, _ = model_tau_h(ds, PlantParams(params.heat_pump, building), start, end, filtered)
        if not math.isfinite(tau):
            break
    return building, EmitterMatch(
        recorded, free, tau, params.building.c_mass, building.c_mass, periods
    )


def _bins(ds: Dataset, start: float, end: float) -> tuple[int, int]:
    i0 = max(1, round((start - ds.grid.start) / ds.grid.step))
    i1 = min(ds.grid.n, round((end - ds.grid.start) / ds.grid.step))
    return i0, i1


def _held(x: FloatArray, fallback: float) -> FloatArray:
    ok = np.isfinite(x)
    if not ok.any():
        return np.full(x.shape, fallback)
    return np.asarray(np.interp(np.arange(x.size), np.flatnonzero(ok), x[ok]), dtype=np.float64)

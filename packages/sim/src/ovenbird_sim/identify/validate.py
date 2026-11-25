"""Validation of the fitted plant on held-out data.

Two levels:

building + hydronics (:func:`horizon_errors`)
    From forecast origins every few hours in the test block, the Kalman-filtered state
    (:mod:`ovenbird_sim.identify.kalman`) is propagated free with the *measured* heat
    input, outside temperature and irradiance; errors of room and outlet temperature
    are pooled over each horizon (1, 6, 24 h). Persistence (room stays as it was) is
    reported as a reference.
full plant (:func:`plant_days`)
    Every test day is simulated with :func:`ovenbird_sim.model.plant.step` at 60 s,
    driven by the *recorded* water setpoint (whatever wrote it, as applied by the
    pump) and the weather, starting from the filtered state; the pump layer decides
    on/off, modulation and defrost itself. Compared per day: heat delivered, heating
    starts, room and outlet RMSE.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from ovenbird_sim.data.dataset import Dataset
from ovenbird_sim.data.events import day_mask
from ovenbird_sim.data.grid import time_since
from ovenbird_sim.data.series import BoolArray, FloatArray
from ovenbird_sim.identify.building import internal_gains, observations
from ovenbird_sim.identify.kalman import filter_states
from ovenbird_sim.model.building import BuildingParams, simulate_batch
from ovenbird_sim.model.plant import PlantParams, PlantState
from ovenbird_sim.model.simulate import run

HORIZONS_H = (1.0, 6.0, 24.0)
DEFROST_GUARD_BINS = 3


def _filled(x: FloatArray, fallback: float = 0.0) -> FloatArray:
    ok = np.isfinite(x)
    if not ok.any():
        return np.full(x.shape, fallback)
    return np.interp(np.arange(x.size), np.flatnonzero(ok), x[ok])


def humidity(ds: Dataset) -> FloatArray:
    """Outside relative humidity per bin (gaps interpolated; ``NaN`` without weather)."""
    rh = ds.columns.get("rh_wx")
    if rh is None or not np.isfinite(rh).any():
        return np.full(ds.grid.n, np.nan)
    return _filled(rh)


def inputs(ds: Dataset, p: BuildingParams) -> NDArray[np.float64]:
    """Network inputs ``[Q, T_o, I, Q_int]`` per bin (gaps filled)."""
    c = ds.columns
    return np.column_stack(
        [
            np.nan_to_num(c["heat_w"], nan=0.0),
            _filled(c["outside"], 10.0),
            np.nan_to_num(c.get("ghi", np.zeros(ds.grid.n)), nan=0.0),
            internal_gains(p, c["local_hour"]),
        ]
    )


def filtered(ds: Dataset, p: BuildingParams) -> NDArray[np.float64]:
    """Kalman-filtered states at every bin of a dataset."""
    water, room = observations(ds)
    u = inputs(ds, p)
    x0 = np.array([_filled(water, 25.0)[0], _filled(room, 21.0)[0], _filled(room, 21.0)[0]])
    return filter_states(p, ds.grid.step, u[:-1], water, room, x0)


@dataclass(frozen=True, slots=True)
class HorizonErrors:
    """Free-run errors pooled per horizon.

    Parameters
    ----------
    horizons_h
        Horizons in hours.
    room_rmse, outlet_rmse
        RMSE of room and outlet over each horizon.
    room_persistence_rmse
        RMSE of "room stays as at the origin" over each horizon.
    origins
        Number of forecast origins.
    """

    horizons_h: tuple[float, ...]
    room_rmse: tuple[float, ...]
    outlet_rmse: tuple[float, ...]
    room_persistence_rmse: tuple[float, ...]
    origins: int


def horizon_errors(
    ds: Dataset,
    p: BuildingParams,
    start: float,
    end: float,
    *,
    every_h: float = 3.0,
    horizons_h: tuple[float, ...] = HORIZONS_H,
) -> HorizonErrors:
    """Free-run forecast errors from origins in ``[start, end)``.

    Parameters
    ----------
    ds
        Dataset (5 min grid recommended).
    p
        Network parameters.
    start, end
        Test block in unix seconds.
    every_h
        Spacing of forecast origins.
    horizons_h
        Horizons to score.

    Returns
    -------
    HorizonErrors
        Pooled errors per horizon.
    """
    states = filtered(ds, p)
    _, room = observations(ds)
    c = ds.columns
    u = inputs(ds, p)
    step = ds.grid.step
    longest = round(max(horizons_h) * 3600.0 / step)
    t = ds.t
    first = int(np.searchsorted(t, start))
    last = int(np.searchsorted(t, end)) - longest - 1
    stride = max(round(every_h * 3600.0 / step), 1)
    origins = np.arange(first, max(last, first), stride)
    origins = origins[np.isfinite(room[origins])]
    if origins.size == 0:
        nan = tuple(math.nan for _ in horizons_h)
        return HorizonErrors(horizons_h, nan, nan, nan, 0)
    idx = origins[:, None] + np.arange(longest)[None, :]
    sim = simulate_batch(p, step, states[origins], u[idx])[:, 1:]
    obs_idx = idx + 1
    half = 0.5 * (c["outlet"] - c["inlet"] - ds.calibration.offset_k)
    outlet_pred = sim[:, :, 0] + half[obs_idx] + ds.calibration.offset_k
    e_room = sim[:, :, 2] - room[obs_idx]
    e_out = outlet_pred - c["outlet"][obs_idx]
    e_persist = room[origins][:, None] - room[obs_idx]
    room_r, out_r, pers_r = [], [], []
    for h in horizons_h:
        n = round(h * 3600.0 / step)
        room_r.append(_rmse(e_room[:, :n]))
        out_r.append(_rmse(e_out[:, :n]))
        pers_r.append(_rmse(e_persist[:, :n]))
    return HorizonErrors(horizons_h, tuple(room_r), tuple(out_r), tuple(pers_r), int(origins.size))


def _rmse(e: NDArray[np.float64]) -> float:
    ok = np.isfinite(e)
    return float(np.sqrt(np.mean(e[ok] ** 2))) if ok.any() else math.nan


def heating_starts(ds: Dataset) -> BoolArray:
    """Bins where a heating start happens (defrost pauses and restarts excluded)."""
    run = ds.columns["compressor_frac"] > 0.0
    start = np.r_[False, ~run[:-1] & run[1:]]
    near = np.convolve(
        ds.flags["defrost"].astype(np.int64),
        np.ones(2 * DEFROST_GUARD_BINS + 1, dtype=np.int64),
        "same",
    )
    return np.asarray(start & (near == 0), dtype=np.bool_)


@dataclass(frozen=True, slots=True)
class PlantDays:
    """Full-plant simulation of held-out days.

    Parameters
    ----------
    day_starts
        Day start times (unix s).
    heat_kwh_measured, heat_kwh_simulated
        Heat into the loop per day.
    starts_measured, starts_simulated
        Heating starts per day.
    room_rmse, outlet_rmse
        Per-day RMSE.
    """

    day_starts: FloatArray
    heat_kwh_measured: FloatArray
    heat_kwh_simulated: FloatArray
    starts_measured: FloatArray
    starts_simulated: FloatArray
    room_rmse: FloatArray
    outlet_rmse: FloatArray

    @property
    def heat_error_pct(self) -> float:
        """Total heat error over all days in percent."""
        total = float(self.heat_kwh_measured.sum())
        return 100.0 * (float(self.heat_kwh_simulated.sum()) - total) / total if total else math.nan

    @property
    def daily_heat_mape_pct(self) -> float:
        """Mean absolute daily heat error in percent."""
        ok = self.heat_kwh_measured > 1.0
        rel = (
            np.abs(self.heat_kwh_simulated[ok] - self.heat_kwh_measured[ok])
            / self.heat_kwh_measured[ok]
        )
        return float(100.0 * rel.mean()) if ok.any() else math.nan

    @property
    def starts_error_pct(self) -> float:
        """Total heating-start error in percent."""
        total = float(self.starts_measured.sum())
        return 100.0 * (float(self.starts_simulated.sum()) - total) / total if total else math.nan


def plant_days(
    ds: Dataset,
    params: PlantParams,
    start: float,
    end: float,
    states_5min: tuple[Dataset, NDArray[np.float64]] | None = None,
) -> PlantDays:
    """Simulate each full UTC day in ``[start, end)`` with the full plant at the dataset step.

    Parameters
    ----------
    ds
        Dataset on the simulation grid (60 s).
    params
        Plant parameters.
    start, end
        Test block in unix seconds.
    states_5min
        A coarser dataset and its filtered states to initialise from; computed from
        ``ds`` when omitted.

    Returns
    -------
    PlantDays
        Per-day comparison.
    """
    c = ds.columns
    step = ds.grid.step
    if states_5min is None:
        coarse = ds
        states = filtered(ds, params.building)
    else:
        coarse, states = states_5min
    _, room = observations(ds)
    per_day = round(86400.0 / step)
    day0 = math.ceil(start / 86400.0) * 86400.0
    starts_flag = heating_starts(ds)
    running = c["compressor_frac"] > 0.5
    since_run = time_since(running, step)
    setpoint = np.round(_filled(c["target"], 30.0))
    outside = _filled(c["outside"], 10.0)
    ghi = np.nan_to_num(c.get("ghi", np.zeros(ds.grid.n)), nan=0.0)
    hour = c["local_hour"]
    rh = humidity(ds)
    rows: list[tuple[float, ...]] = []
    excluded = day_mask(ds.t, ds.events)
    for d0 in np.arange(day0, end - 86400.0 + 1.0, 86400.0):
        i0 = round((d0 - ds.grid.start) / step)
        i1 = i0 + per_day
        if i0 < 1 or i1 > ds.grid.n or excluded[i0:i1].any():
            continue
        j = int(np.clip(round((d0 - coarse.grid.start) / coarse.grid.step), 0, states.shape[0] - 1))
        tw, tm, ta = states[j]
        state = PlantState(
            t_water=float(tw),
            t_mass=float(tm),
            t_air=float(ta),
            running=bool(running[i0 - 1]),
            hz=float(np.nan_to_num(c["hz"][i0 - 1])) if running[i0 - 1] else 0.0,
            heat_w=float(np.nan_to_num(c["heat_w"][i0 - 1])) if running[i0 - 1] else 0.0,
            off_s=float(since_run[i0 - 1]) if not running[i0 - 1] else 0.0,
            last_setpoint=float(setpoint[i0 - 1]),
        )
        traj = run(
            params,
            state,
            setpoint[i0:i1],
            outside[i0:i1],
            ghi[i0:i1],
            hour[i0:i1],
            step,
            rh[i0:i1],
        )
        heat_meas = float(np.nansum(c["heat_w"][i0:i1]) * step / 3.6e6)
        heat_sim = float(traj.heat_w.sum() * step / 3.6e6)
        rows.append(
            (
                d0,
                heat_meas,
                heat_sim,
                float(starts_flag[i0:i1].sum()),
                float(traj.final.starts),
                _rmse(traj.t_air - room[i0:i1]),
                _rmse(traj.outlet - c["outlet"][i0:i1]),
            )
        )
    arr = np.array(rows, dtype=np.float64).reshape(-1, 7)
    return PlantDays(*(arr[:, k].copy() for k in range(7)))


SHORT_RUN_S = 20 * 60.0


def recorded_runs(
    t: FloatArray, running: FloatArray, defrost: FloatArray, dt: float
) -> tuple[FloatArray, FloatArray]:
    """Completed runs of the recording; compressor pauses around a defrost do not split a run.

    Parameters
    ----------
    t
        Bin start times.
    running, defrost
        Per-bin flags (0/1).
    dt
        Bin length.

    Returns
    -------
    run_start, run_length_s
        Start and length of every run that starts and ends inside the span.
    """
    del dt
    kernel = np.ones(2 * DEFROST_GUARD_BINS + 1)
    near = np.convolve(defrost.astype(np.float64), kernel, "same") > 0
    starts: list[float] = []
    lengths: list[float] = []
    current: float | None = None
    for k in range(1, t.size):
        rising = running[k] > 0.5 >= running[k - 1]
        falling = running[k] <= 0.5 < running[k - 1]
        if rising and not near[k] and current is None:
            current = float(t[k])
        elif falling and not near[k] and current is not None:
            starts.append(current)
            lengths.append(float(t[k]) - current)
            current = None
    return np.asarray(starts, dtype=np.float64), np.asarray(lengths, dtype=np.float64)


def simulated_runs(t: FloatArray, running: FloatArray, dt: float) -> tuple[FloatArray, FloatArray]:
    """Completed runs of a simulated trajectory (a defrost keeps the compressor running)."""
    edges = np.flatnonzero(np.diff(np.r_[0.0, running, 0.0]))
    rises, falls = edges[::2], edges[1::2]
    keep = (rises > 0) & (falls < running.size)
    return t[rises[keep]].astype(np.float64), ((falls - rises)[keep] * dt).astype(np.float64)


def state_at(ds: Dataset, coarse: Dataset, states: NDArray[np.float64], i0: int) -> PlantState:
    """Plant state at bin ``i0``: filtered temperatures and the recorded switching state.

    Parameters
    ----------
    ds
        Dataset on the simulation grid.
    coarse, states
        Coarser dataset and its Kalman-filtered states.
    i0
        First simulated bin (at least 1).

    Returns
    -------
    PlantState
        Initial state.
    """
    c = ds.columns
    t0 = float(ds.t[i0])
    j = int(np.clip(round((t0 - coarse.grid.start) / coarse.grid.step), 0, states.shape[0] - 1))
    running = bool(np.nan_to_num(c["compressor_frac"][i0 - 1]) > 0.5)
    since_run = time_since(np.nan_to_num(c["compressor_frac"]) > 0.5, ds.grid.step)
    setpoint = np.round(_filled(c["target"], 30.0))
    tw, tm, ta = (float(x) for x in states[j])
    return PlantState(
        t_water=tw,
        t_mass=tm,
        t_air=ta,
        running=running,
        hz=float(np.nan_to_num(c["hz"][i0 - 1])) if running else 0.0,
        heat_w=float(np.nan_to_num(c["heat_w"][i0 - 1])) if running else 0.0,
        off_s=0.0 if running else float(since_run[i0 - 1]),
        since_restart_s=math.inf if running else 0.0,
        run_s=math.inf if running else 0.0,
        last_setpoint=float(setpoint[i0 - 1]),
    )


@dataclass(frozen=True, slots=True)
class PlantSpan:
    """One continuous full-plant run on recorded setpoints against the recording.

    Parameters
    ----------
    start, end
        Span in unix seconds.
    days
        Length in days.
    measured, simulated
        ``heat_kwh_per_day``, ``elec_kwh_per_day``, ``starts_per_day``,
        ``run_median_min`` and ``short_run_share`` of the recording and the model.
    room_rmse_k
        Room RMSE of the run.
    steady_start_share
        Share of the model's starts made by the steady rule.
    """

    start: float
    end: float
    days: float
    measured: dict[str, float]
    simulated: dict[str, float]
    room_rmse_k: float
    steady_start_share: float

    def error(self, name: str) -> float:
        """Relative error of a KPI (absolute for the short-run share)."""
        sim, rec = self.simulated[name], self.measured[name]
        if name == "short_run_share":
            return sim - rec
        return (sim - rec) / rec if rec else math.nan

    @property
    def score(self) -> float:
        """Sum of absolute errors in percent (selection criterion)."""
        names = ("heat_kwh_per_day", "elec_kwh_per_day", "starts_per_day", "run_median_min")
        total = sum(abs(self.error(n)) for n in names) + abs(self.error("short_run_share"))
        return 100.0 * total if math.isfinite(total) else math.inf


def run_stats(lengths_s: FloatArray) -> tuple[float, float]:
    """Median run in minutes and share of runs shorter than :data:`SHORT_RUN_S`."""
    if not lengths_s.size:
        return math.nan, math.nan
    return float(np.median(lengths_s) / 60.0), float(np.mean(lengths_s < SHORT_RUN_S))


def plant_span(
    ds: Dataset,
    params: PlantParams,
    start: float,
    end: float,
    states_5min: tuple[Dataset, NDArray[np.float64]],
) -> PlantSpan:
    """Run the full plant continuously over ``[start, end)`` on the recorded setpoint.

    The run goes through every day; UTC days touched by a known event (a stove fire
    and its recovery tail, :func:`ovenbird_sim.data.events.day_mask`) are left out of
    every KPI and the room RMSE.

    Parameters
    ----------
    ds
        Dataset on the simulation grid (60 s).
    params
        Plant parameters.
    start, end
        Span in unix seconds.
    states_5min
        Coarser dataset and its filtered states (initial state).

    Returns
    -------
    PlantSpan
        Recorded and simulated KPIs.
    """
    c = ds.columns
    step = ds.grid.step
    i0 = max(1, round((start - ds.grid.start) / step))
    i1 = min(ds.grid.n, round((end - ds.grid.start) / step))
    coarse, states = states_5min
    state = state_at(ds, coarse, states, i0)
    setpoint = np.round(_filled(c["target"], 30.0))[i0:i1]
    outside = _filled(c["outside"], 10.0)[i0:i1]
    ghi = np.nan_to_num(c.get("ghi", np.zeros(ds.grid.n)), nan=0.0)[i0:i1]
    traj = run(
        params, state, setpoint, outside, ghi, c["local_hour"][i0:i1], step, humidity(ds)[i0:i1]
    )
    t = ds.t[i0:i1]
    keep = ~day_mask(t, ds.events)
    days = float(keep.sum()) * step / 86400.0
    running = (np.nan_to_num(c["compressor_frac"][i0:i1]) > 0.0).astype(np.float64)
    rec_start, rec_len = recorded_runs(
        t, running, ds.flags["defrost"][i0:i1].astype(np.float64), step
    )
    sim_start, sim_len = simulated_runs(t, traj.running, step)
    rec_med, rec_short = run_stats(rec_len[~day_mask(rec_start, ds.events)])
    sim_med, sim_short = run_stats(sim_len[~day_mask(sim_start, ds.events)])
    _, room = observations(ds)
    sim_starts = np.diff(np.r_[float(state.starts), traj.starts])
    starts = float(sim_starts[keep].sum())
    kwh = step / 3.6e6
    return PlantSpan(
        start=float(ds.t[i0]),
        end=float(ds.t[i1 - 1]) + step,
        days=days,
        measured={
            "heat_kwh_per_day": float(np.nansum(c["heat_w"][i0:i1][keep]) * kwh / days),
            "elec_kwh_per_day": float(np.nansum(c["elec_hp_est_w"][i0:i1][keep]) * kwh / days),
            "starts_per_day": float(heating_starts(ds)[i0:i1][keep].sum() / days),
            "run_median_min": rec_med,
            "short_run_share": rec_short,
        },
        simulated={
            "heat_kwh_per_day": float(traj.heat_w[keep].sum() * kwh / days),
            "elec_kwh_per_day": float(traj.elec_w[keep].sum() * kwh / days),
            "starts_per_day": starts / days,
            "run_median_min": sim_med,
            "short_run_share": sim_short,
        },
        room_rmse_k=_rmse((traj.t_air - room[i0:i1])[keep]),
        steady_start_share=float(traj.final.steady_starts - state.steady_starts)
        / float(traj.final.starts - state.starts)
        if traj.final.starts > state.starts
        else math.nan,
    )

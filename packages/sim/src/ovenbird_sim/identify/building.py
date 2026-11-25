"""Prediction-error identification of the water/mass/air network.

Method: output-error (free-run simulation) fit over daily windows. The measured heat
into the loop (flow x spread), the outside temperature and irradiance drive the
network of :mod:`ovenbird_sim.model.building`; each window starts from the measured
loop mean and room temperature and a per-window mass temperature (a nuisance
parameter), and is simulated free for its whole length. Residuals are the loop mean
``(inlet + outlet - offset) / 2`` and the room temperature, each scaled by an
assumed noise level, plus weak Gaussian priors on the log of every capacity and
conductance (physical plausibility, not information). Capacities and conductances are
fitted in log space within hard physical bounds (the gains' peak hour is searched over
``[-12, 36]`` and wrapped, so midnight is not a boundary); ``scipy.optimize.least_squares``
(trust-region reflective) uses a sparse Jacobian because each nuisance parameter only
touches its own window.

Using the measured heat as input sidesteps the pump's switching logic, but the data
are closed loop: the recorded controller raises the water setpoint when the room cools, so the heat
input is correlated with unmodelled room disturbances, which can bias the envelope
conductance. Uncertainty is quantified by refitting on day-block bootstrap samples.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, fields

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix

from ovenbird_sim.data.dataset import Dataset
from ovenbird_sim.data.series import FloatArray
from ovenbird_sim.model.building import BuildingParams, simulate_batch

LOG_FIELDS = (
    "c_water",
    "c_mass",
    "c_air",
    "h_water_mass",
    "h_water_air",
    "h_mass_air",
    "h_air_out",
)
LIN_FIELDS = (
    "solar_aperture_m2",
    "solar_mass_fraction",
    "q_int_w",
    "q_int_modulation",
    "q_int_peak_hour",
)
BOUNDS: dict[str, tuple[float, float]] = {
    "c_water": (0.3e6, 1.5e7),
    "c_mass": (3.0e6, 5.0e8),
    "c_air": (0.3e6, 3.0e8),
    "h_water_mass": (20.0, 5000.0),
    "h_water_air": (5.0, 3000.0),
    "h_mass_air": (20.0, 1.0e4),
    "h_air_out": (30.0, 1500.0),
    "solar_aperture_m2": (0.0, 40.0),
    "solar_mass_fraction": (0.0, 1.0),
    "q_int_w": (0.0, 2000.0),
    "q_int_modulation": (0.0, 1.0),
    "q_int_peak_hour": (-12.0, 36.0),
}
PRIOR_MEAN: dict[str, float] = {
    "c_water": 2.5e6,
    "c_mass": 4.0e7,
    "c_air": 1.0e7,
    "h_water_mass": 400.0,
    "h_water_air": 150.0,
    "h_mass_air": 800.0,
    "h_air_out": 200.0,
    "solar_aperture_m2": 3.0,
    "solar_mass_fraction": 0.5,
    "q_int_w": 300.0,
    "q_int_modulation": 0.3,
    "q_int_peak_hour": 19.0,
}
PRIOR_SD: dict[str, float] = {
    **{name: math.log(5.0) for name in LOG_FIELDS},
    "solar_aperture_m2": 10.0,
    "solar_mass_fraction": 0.3,
    "q_int_w": 400.0,
    "q_int_modulation": 0.5,
    "q_int_peak_hour": 6.0,
}
NUISANCE_BOUNDS = (5.0, 45.0)


@dataclass(frozen=True, slots=True)
class FitConfig:
    """Settings of the building fit.

    Parameters
    ----------
    sigma_water_k, sigma_room_k
        Assumed noise of the loop mean and room observations (residual scaling).
    window_steps
        Steps per free-run window (288 = 24 h at 5 min).
    min_valid_share
        Minimum share of usable inputs and loop observations in a window.
    min_room_share
        Minimum share of room observations in a window.
    max_nfev
        Function evaluation budget of the optimiser.
    fixed
        Fields held at their start value.
    """

    sigma_water_k: float = 0.3
    sigma_room_k: float = 0.15
    window_steps: int = 288
    min_valid_share: float = 0.95
    min_room_share: float = 0.8
    max_nfev: int = 200
    fixed: tuple[str, ...] = ()


DEFAULT_FIT = FitConfig()


@dataclass(frozen=True, slots=True)
class Windows:
    """Free-run windows cut from a dataset.

    Parameters
    ----------
    dt
        Step in seconds.
    starts
        Window start times (unix s).
    u
        Inputs ``[Q, T_o, I]`` per window and step, shape ``(n, steps, 3)``.
    hour
        Local hour per window and step.
    y_water, y_room
        Observations (``NaN`` = missing), shape ``(n, steps + 1)``: at the window start
        and at the end of every step.
    flow_lpm
        Measured flow per step (for outlet reconstruction).
    event_starts
        Start times of the windows left out because they overlap a known event
        (:mod:`ovenbird_sim.data.events`) or its recovery tail.
    """

    dt: float
    starts: FloatArray
    u: NDArray[np.float64]
    hour: NDArray[np.float64]
    y_water: NDArray[np.float64]
    y_room: NDArray[np.float64]
    flow_lpm: NDArray[np.float64]
    event_starts: tuple[float, ...] = ()

    @property
    def n(self) -> int:
        """Number of windows."""
        return int(self.starts.size)

    def take(self, index: Sequence[int] | NDArray[np.intp]) -> Windows:
        """Return the windows at ``index`` (repeats allowed, for bootstrap)."""
        idx = np.asarray(index, dtype=np.intp)
        return Windows(
            self.dt,
            self.starts[idx],
            self.u[idx],
            self.hour[idx],
            self.y_water[idx],
            self.y_room[idx],
            self.flow_lpm[idx],
            self.event_starts,
        )


def observations(ds: Dataset) -> tuple[FloatArray, FloatArray]:
    """Loop-mean and room observations of a dataset.

    The loop mean is ``(inlet + outlet - offset) / 2``; the room is the living-room
    composite where present, else the controller's room sensor.
    """
    c = ds.columns
    water = 0.5 * (c["inlet"] + c["outlet"] - ds.calibration.offset_k)
    room = c["room_living"] if "room_living" in c else c["room"]
    room = np.where(np.isfinite(room), room, c["room"])
    return water, room


def make_windows(
    ds: Dataset,
    config: FitConfig = DEFAULT_FIT,
    *,
    start: float | None = None,
    end: float | None = None,
) -> Windows:
    """Cut a dataset into aligned, quality-checked free-run windows.

    A window that overlaps a known event or its recovery tail (the ``event`` flag) is
    left out whole: the unmodelled heat changes the state the free run carries on
    with, so masking only the flagged observations would not be enough.

    Parameters
    ----------
    ds
        Dataset (5 min grid recommended).
    config
        Window length and quality thresholds.
    start, end
        Only windows fully inside ``[start, end)`` (unix s).

    Returns
    -------
    Windows
        The usable windows.
    """
    c, f = ds.columns, ds.flags
    water, room = observations(ds)
    heat = c["heat_w"]
    t_o = c["outside"]
    ghi = np.nan_to_num(c.get("ghi", np.zeros(ds.grid.n)), nan=0.0)
    hour = c["local_hour"]
    flow = c["flow"]
    bad = (
        f["gap"]
        | f["stale"]
        | f["dhw"]
        | ~np.isfinite(heat)
        | ~np.isfinite(t_o)
        | ~np.isfinite(water)
    )
    n = config.window_steps
    t = ds.t
    day = ds.grid.step * n
    first = math.ceil(t[0] / day) * day
    rows: list[int] = []
    event = ds.event_mask()
    skipped: list[float] = []
    for w0 in np.arange(first, t[-1], day):
        i0 = round((w0 - ds.grid.start) / ds.grid.step)
        i1 = i0 + n + 1
        if i0 < 0 or i1 > ds.grid.n:
            continue
        if start is not None and t[i0] < start:
            continue
        if end is not None and t[i0] + day > end:
            continue
        if 1.0 - bad[i0:i1].mean() < config.min_valid_share:
            continue
        if np.isfinite(room[i0:i1]).mean() < config.min_room_share:
            continue
        if not (np.isfinite(water[i0]) and np.isfinite(room[i0:i1]).any()):
            continue
        if event[i0:i1].any():
            skipped.append(float(t[i0]))
            continue
        rows.append(i0)
    if not rows:
        empty = np.empty((0, n, 3))
        return Windows(
            ds.grid.step,
            np.empty(0),
            empty,
            np.empty((0, n)),
            np.empty((0, n + 1)),
            np.empty((0, n + 1)),
            np.empty((0, n)),
            tuple(skipped),
        )
    idx = np.array(rows)
    steps = idx[:, None] + np.arange(n)[None, :]
    obs_idx = idx[:, None] + np.arange(n + 1)[None, :]
    u = np.stack(
        [
            np.nan_to_num(heat[steps], nan=0.0),
            _fill(t_o[steps]),
            ghi[steps],
        ],
        axis=-1,
    )
    y_w = np.where(bad[obs_idx], np.nan, water[obs_idx])
    return Windows(
        ds.grid.step,
        t[idx],
        u,
        hour[steps],
        y_w,
        room[obs_idx],
        _fill(flow[steps]),
        tuple(skipped),
    )


def _fill(x: NDArray[np.float64]) -> NDArray[np.float64]:
    """Linearly interpolate missing values along the last axis (all-missing rows become 0)."""
    out = np.array(x, dtype=np.float64)
    for row in np.atleast_2d(out):
        ok = np.isfinite(row)
        if not ok.any():
            row[:] = 0.0
        elif not ok.all():
            row[~ok] = np.interp(np.flatnonzero(~ok), np.flatnonzero(ok), row[ok])
    return out


def _first_finite(rows: NDArray[np.float64]) -> FloatArray:
    out = np.empty(rows.shape[0])
    for i, row in enumerate(rows):
        ok = np.flatnonzero(np.isfinite(row))
        out[i] = row[ok[0]] if ok.size else 20.0
    return out


@dataclass(frozen=True, slots=True)
class _Layout:
    free: tuple[str, ...]
    base: BuildingParams

    def unpack(self, theta: FloatArray) -> BuildingParams:
        values = {f.name: getattr(self.base, f.name) for f in fields(self.base)}
        for name, value in zip(self.free, theta, strict=False):
            values[name] = math.exp(value) if name in LOG_FIELDS else float(value)
        values["q_int_peak_hour"] %= 24.0
        return BuildingParams(**values)

    def pack(self, p: BuildingParams) -> FloatArray:
        return np.array(
            [math.log(getattr(p, n)) if n in LOG_FIELDS else getattr(p, n) for n in self.free]
        )

    def bounds(self) -> tuple[FloatArray, FloatArray]:
        lo = [math.log(BOUNDS[n][0]) if n in LOG_FIELDS else BOUNDS[n][0] for n in self.free]
        hi = [math.log(BOUNDS[n][1]) if n in LOG_FIELDS else BOUNDS[n][1] for n in self.free]
        return np.array(lo), np.array(hi)

    def prior(self, theta: FloatArray) -> FloatArray:
        out = np.empty(len(self.free))
        for i, name in enumerate(self.free):
            mean = math.log(PRIOR_MEAN[name]) if name in LOG_FIELDS else PRIOR_MEAN[name]
            out[i] = (theta[i] - mean) / PRIOR_SD[name]
        return out


def internal_gains(p: BuildingParams, hour: NDArray[np.float64]) -> NDArray[np.float64]:
    """Evaluate the internal-gains profile at local hours (vectorised)."""
    angle = 2.0 * np.pi * (hour - p.q_int_peak_hour) / 24.0
    return p.q_int_w * (1.0 + p.q_int_modulation * np.cos(angle))


def simulate_windows(p: BuildingParams, win: Windows, t_mass0: FloatArray) -> NDArray[np.float64]:
    """Free-run every window from its measured start and the given mass temperatures.

    Returns
    -------
    NDArray
        States, shape ``(n, steps + 1, 3)``.
    """
    x0 = np.column_stack([_first_finite(win.y_water), t_mass0, _first_finite(win.y_room)])
    u = np.concatenate([win.u, internal_gains(p, win.hour)[..., None]], axis=-1)
    return simulate_batch(p, win.dt, x0, u)


@dataclass(frozen=True, slots=True)
class BuildingFit:
    """Result of a building fit.

    Parameters
    ----------
    params
        Fitted parameters.
    t_mass0
        Fitted initial mass temperature per window.
    rmse_water, rmse_room
        Free-run RMSE over the fitted windows.
    cost
        Final least-squares cost.
    n_windows
        Windows used.
    success
        Optimiser convergence flag.
    """

    params: BuildingParams
    t_mass0: FloatArray
    rmse_water: float
    rmse_room: float
    cost: float
    n_windows: int
    success: bool


def fit_building(
    win: Windows,
    config: FitConfig = DEFAULT_FIT,
    start: BuildingParams | None = None,
) -> BuildingFit:
    """Fit the network to free-run windows.

    Parameters
    ----------
    win
        Windows from :func:`make_windows`.
    config
        Noise levels, budget and fixed fields.
    start
        Start values (defaults to the prior means).

    Returns
    -------
    BuildingFit
        Fitted parameters and fit diagnostics.

    Raises
    ------
    ValueError
        When there are no windows.
    """
    if win.n == 0:
        raise ValueError("no usable windows to fit")
    base = start or BuildingParams()
    free = tuple(n for n in (*LOG_FIELDS, *LIN_FIELDS) if n not in config.fixed)
    layout = _Layout(free, base)
    n_g = len(free)
    room0 = _first_finite(win.y_room)
    water0 = _first_finite(win.y_water)
    theta0 = np.concatenate([layout.pack(base), np.clip(0.5 * (room0 + water0), *NUISANCE_BOUNDS)])
    lo_g, hi_g = layout.bounds()
    lo = np.concatenate([lo_g, np.full(win.n, NUISANCE_BOUNDS[0])])
    hi = np.concatenate([hi_g, np.full(win.n, NUISANCE_BOUNDS[1])])
    theta0 = np.clip(theta0, lo + 1e-9, hi - 1e-9)
    mask_w = np.isfinite(win.y_water)
    mask_a = np.isfinite(win.y_room)
    y_w = np.nan_to_num(win.y_water)
    y_a = np.nan_to_num(win.y_room)

    def residuals(theta: FloatArray) -> FloatArray:
        p = layout.unpack(theta[:n_g])
        x = simulate_windows(p, win, theta[n_g:])
        rw = np.where(mask_w, (x[:, :, 0] - y_w) / config.sigma_water_k, 0.0)
        ra = np.where(mask_a, (x[:, :, 2] - y_a) / config.sigma_room_k, 0.0)
        return np.concatenate([rw.ravel(), ra.ravel(), layout.prior(theta[:n_g])])

    steps1 = win.y_water.shape[1]
    n_res = 2 * win.n * steps1 + n_g
    sparsity = lil_matrix((n_res, n_g + win.n), dtype=np.int8)
    sparsity[:, :n_g] = 1
    for i in range(win.n):
        rows_w = np.arange(i * steps1, (i + 1) * steps1)
        rows_a = rows_w + win.n * steps1
        sparsity[rows_w, n_g + i] = 1
        sparsity[rows_a, n_g + i] = 1
    sparsity[2 * win.n * steps1 :, n_g:] = 0
    result = least_squares(
        residuals,
        theta0,
        bounds=(lo, hi),
        jac_sparsity=sparsity,
        x_scale="jac",
        method="trf",
        max_nfev=config.max_nfev,
    )
    params = layout.unpack(result.x[:n_g])
    x = simulate_windows(params, win, result.x[n_g:])
    rmse_w = float(np.sqrt(np.mean((x[:, :, 0] - win.y_water)[mask_w] ** 2)))
    rmse_a = float(np.sqrt(np.mean((x[:, :, 2] - win.y_room)[mask_a] ** 2)))
    return BuildingFit(
        params, result.x[n_g:], rmse_w, rmse_a, float(result.cost), win.n, bool(result.success)
    )


@dataclass(frozen=True, slots=True)
class Bootstrap:
    """Day-block bootstrap of the building fit.

    Parameters
    ----------
    samples
        Fitted parameters per replicate.
    """

    samples: tuple[BuildingParams, ...]

    def interval(self, name: str, level: float = 0.9) -> tuple[float, float]:
        """Percentile interval of a parameter (or derived property) across replicates."""
        values = np.array([_value(p, name) for p in self.samples])
        tail = (1.0 - level) / 2.0 * 100.0
        lo, hi = np.percentile(values, [tail, 100.0 - tail])
        return float(lo), float(hi)


def _value(p: BuildingParams, name: str) -> float:
    if name == "time_constant_h":
        return p.time_constant_h
    return float(getattr(p, name))


def bootstrap_building(
    win: Windows,
    point: BuildingFit,
    replicates: int,
    config: FitConfig = DEFAULT_FIT,
    seed: int = 0,
) -> Bootstrap:
    """Refit on windows resampled with replacement (whole days as blocks).

    Parameters
    ----------
    win
        The windows of the point fit.
    point
        The point fit (warm start).
    replicates
        Number of bootstrap replicates.
    config
        Fit settings (a smaller evaluation budget is fine with the warm start).
    seed
        Random seed (explicit for reproducibility).

    Returns
    -------
    Bootstrap
        The replicate parameter sets.
    """
    rng = np.random.default_rng(seed)
    samples = []
    for _ in range(replicates):
        idx = rng.integers(0, win.n, win.n)
        fit = fit_building(win.take(idx), config, start=point.params)
        samples.append(fit.params)
    return Bootstrap(tuple(samples))

"""Fit the heat-pump layer (capacity, modulation, COP, defrost, sensors) from a dataset.

The capacity map and the cold floor use *steady running* bins: compressor on for the
whole bin, at least 20 min after a heating start and 15 min after a defrost, all loop
signals valid. The COP map is fitted on every full running bin at least a minute after
a heating start (and 15 min after a defrost) with a warm-up term in the time since the
start (:func:`fit_cop_warmup`), so start-ups are neither extrapolated from steady
operation nor ignored. It rests on the pump's own electrical estimate
(``Heat_Power_Consumption``), which is an estimate, not a meter; :func:`p1_step_ratio`
cross-checks it against the grid meter's step at compressor starts. The frequency
controller is replayed with the measured start phase (:func:`fit_frequency_controller`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from ovenbird_sim.data.dataset import Dataset
from ovenbird_sim.data.grid import time_since
from ovenbird_sim.data.series import BoolArray, FloatArray
from ovenbird_sim.identify.switching import StartPhaseFit, StartRuleFit
from ovenbird_sim.identify.validate import humidity
from ovenbird_sim.model.heatpump import (
    HeatPumpParams,
    frost_driver_hpa,
    frost_rate_per_s,
    heat_output,
)
from ovenbird_sim.model.heatpump import cop as model_cop
from ovenbird_sim.model.heatpump import heat_per_hz as heat_per_hz_steady

CONTROLLER_STARTS = (
    (0.1, 0.3, 1.2, 1.8, 5.0),
    (0.5, 0.3, 1.5, 1.0, 6.0),
    (0.0, 0.6, 2.4, 1.7, 2.2),
    (1.0, 0.4, 0.8, 3.0, 8.0),
)
CANDIDATE_TOLERANCE = 0.05
CONTROLLER_BOUNDS = (
    (-1.0, 3.0),
    (0.0, 1.5),
    (0.05, 10.0),
    (0.05, 10.0),
    (0.5, 30.0),
    (19.0, 90.0),
    (-6.0, 2.0),
)
WARMUP_TAUS_S = (60.0, 120.0, 180.0, 300.0, 450.0, 600.0, 900.0, 1200.0, 1800.0, 2700.0)
WARMUP_WINDOW_S = 3600.0
WARMUP_REPORT_S = 900.0
STEADY_AFTER_START_S = 1200.0
STEADY_AFTER_DEFROST_S = 900.0
MIN_ELEC_W = 200.0
FROST_FREE_BEFORE_DEFROST_S = 1800.0
FROST_CAPACITY_NONE = 1.0e9
MIN_COIL_BINS = 100


@dataclass(frozen=True, slots=True)
class HeatPumpFit:
    """Fitted heat-pump parameters with diagnostics.

    Parameters
    ----------
    params
        The fitted parameters.
    capacity_rmse_w
        Residual of the heat-per-hertz fit.
    cop_rmse_log
        Residual of the log-COP fit.
    n_steady
        Steady running bins used.
    defrost_events
        Defrost starts seen.
    defrost_rate_table
        ``(outside bin low edge, running hours, defrosts)`` rows.
    p1_ratio
        Grid-meter step / pump estimate step at compressor starts (``NaN`` without P1).
    controller
        Frequency-controller fit in use and its replay skill.
    controller_candidates
        All near-equivalent replay optima (best replay first).
    cop, cop_steady
        COP map with the warm-up term (in use) and the steady-only reference map.
    capacity
        Heat-per-hertz map with its start-up term (in use).
    pump_vs_loop_heat
        Median of the pump's heat estimate over flow x spread heat.
    frost
        Coil-temperature and frost-capacity fit (``None`` without the pipe sensor).
    """

    params: HeatPumpParams
    capacity_rmse_w: float
    cop_rmse_log: float
    n_steady: int
    defrost_events: int
    defrost_rate_table: tuple[tuple[float, float, int], ...]
    p1_ratio: float
    pump_vs_loop_heat: float
    controller: ControllerFit
    controller_candidates: tuple[ControllerFit, ...] = ()
    cop: CopFit | None = None
    cop_steady: CopFit | None = None
    capacity: CapacityFit | None = None
    frost: FrostFit | None = None


def steady_running(ds: Dataset) -> BoolArray:
    """Bins of steady heating operation."""
    c, f = ds.columns, ds.flags
    full = c["compressor_frac"] >= 0.999
    since_start = time_since(np.r_[True, c["compressor_frac"][1:] < 0.999], ds.grid.step)
    since_defrost = time_since(f["defrost"], ds.grid.step)
    ok = full & (since_start >= STEADY_AFTER_START_S) & (since_defrost >= STEADY_AFTER_DEFROST_S)
    ok &= ~f["gap"] & ~f["stale"] & ~f["dhw"]
    for name in ("heat_w", "hz", "outlet", "outside"):
        ok &= np.isfinite(c[name])
    return np.asarray(ok & (c["hz"] > 0), dtype=np.bool_)


def fit_capacity(
    heat: FloatArray, hz: FloatArray, outside: FloatArray, inlet: FloatArray
) -> tuple[tuple[float, float, float], float]:
    """Least-squares ``Q = Hz (k0 + k_o T_o + k_s T)`` (``T``: the loop temperature passed).

    Returns
    -------
    coefficients, rmse
        ``(k0, k_o, k_s)`` and the residual RMS in W.
    """
    x = np.column_stack([hz, hz * outside, hz * inlet])
    coef, *_ = np.linalg.lstsq(x, heat, rcond=None)
    rmse = float(np.sqrt(np.mean((x @ coef - heat) ** 2)))
    return (float(coef[0]), float(coef[1]), float(coef[2])), rmse


def fit_cop(
    heat: FloatArray, elec: FloatArray, outside: FloatArray, outlet: FloatArray, hz: FloatArray
) -> tuple[tuple[float, float, float, float], float]:
    """Least-squares ``ln(Q / P) = c0 + c_o T_o + c_s T_out + c_h Hz``.

    The quadratic frequency term of the model is left at zero: with data mostly at low
    frequency it bends the map upwards at high frequency, which is not physical.

    Returns
    -------
    coefficients, rmse
        The four coefficients and the residual RMS of ``ln COP``.
    """
    ok = (elec >= MIN_ELEC_W) & (heat > 0)
    y = np.log(heat[ok] / elec[ok])
    x = np.column_stack([np.ones(ok.sum()), outside[ok], outlet[ok], hz[ok]])
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    rmse = float(np.sqrt(np.mean((x @ coef - y) ** 2)))
    c0, c_o, c_s, c_h = (float(v) for v in coef)
    return (c0, c_o, c_s, c_h), rmse


def heating_start_age_s(ds: Dataset) -> FloatArray:
    """Seconds since the last heating start per bin (a defrost restart is not a start)."""
    c, f = ds.columns, ds.flags
    run = np.nan_to_num(c["compressor_frac"]) > 0.0
    rise = np.r_[False, ~run[:-1] & run[1:]]
    near = np.convolve(f["defrost"].astype(np.int64), np.ones(7, dtype=np.int64), "same") > 0
    return time_since(rise & ~near, ds.grid.step)


def cop_bins(ds: Dataset) -> BoolArray:
    """Bins of the COP fit: full running bins a minute after a start, away from defrosts."""
    c, f = ds.columns, ds.flags
    full = c["compressor_frac"] >= 0.999
    since_defrost = time_since(f["defrost"], ds.grid.step)
    age = heating_start_age_s(ds)
    ok = full & (age >= ds.grid.step) & (since_defrost >= STEADY_AFTER_DEFROST_S)
    ok &= ~f["gap"] & ~f["stale"] & ~f["dhw"] & ~f["defrost"]
    for name in ("heat_w", "hz", "outlet", "outside", "elec_hp_est_w"):
        ok &= np.isfinite(c[name])
    ok &= (c["elec_hp_est_w"] >= MIN_ELEC_W) & (c["heat_w"] > 0) & (c["hz"] > 0)
    return np.asarray(ok, dtype=np.bool_)


@dataclass(frozen=True, slots=True)
class CapacityFit:
    """Heat per hertz with a start-up term in the time since the heating start.

    Parameters
    ----------
    k0, k_o, k_in
        Map coefficients in W/Hz (``k_in`` per K of the inlet temperature).
    warmup, warmup_tau_s
        Start-up term in W/Hz and its time constant.
    q0_w
        Heat offset in W.
    rmse_w
        Residual RMS of the heat in W.
    n
        Bins used.
    """

    k0: float
    k_o: float
    k_in: float
    warmup: float
    warmup_tau_s: float
    q0_w: float
    rmse_w: float
    n: int


def fit_capacity_warmup(
    heat: FloatArray,
    hz: FloatArray,
    outside: FloatArray,
    inlet: FloatArray,
    age_s: FloatArray,
    taus: tuple[float, ...] = WARMUP_TAUS_S,
) -> CapacityFit:
    """Least-squares ``Q = Hz (k0 + k_o T_o + k_in T_in + k_w exp(-t / tau)) + q0``.

    Profiled over ``tau`` as :func:`fit_cop_warmup`; bins older than
    :data:`WARMUP_WINDOW_S` carry no start-up term.

    Returns
    -------
    CapacityFit
        Coefficients and residual.
    """
    base = np.column_stack([hz, hz * outside, hz * inlet])
    best: CapacityFit | None = None
    for tau in taus:
        term = hz * np.where(age_s < WARMUP_WINDOW_S, np.exp(-age_s / tau), 0.0)
        x = np.column_stack([base, term, np.ones(heat.size)])
        coef, *_ = np.linalg.lstsq(x, heat, rcond=None)
        rmse = float(np.sqrt(np.mean((x @ coef - heat) ** 2)))
        if best is None or rmse < best.rmse_w:
            k0, k_o, k_in, w, q0 = (float(v) for v in coef)
            best = CapacityFit(k0, k_o, k_in, w, float(tau), q0, rmse, int(heat.size))
    if best is None:
        raise ValueError("no warm-up time constant to try")
    return best


@dataclass(frozen=True, slots=True)
class CopFit:
    """Log-COP map with a warm-up term in the time since the heating start.

    Parameters
    ----------
    c0, c_o, c_s, c_h
        Map coefficients (intercept, outside, outlet, frequency).
    warmup, warmup_tau_s
        Warm-up amplitude and time constant (``warmup = 0`` without the term).
    rmse_log
        Residual RMS of ``ln COP``.
    n
        Bins used.
    """

    c0: float
    c_o: float
    c_s: float
    c_h: float
    warmup: float
    warmup_tau_s: float
    rmse_log: float
    n: int

    def log_cop(
        self,
        outside: FloatArray,
        outlet: FloatArray,
        hz: FloatArray,
        age_s: FloatArray,
        *,
        warm: bool = True,
    ) -> FloatArray:
        """Predicted ``ln COP`` (``warm=False`` leaves the warm-up term out)."""
        base = self.c0 + self.c_o * outside + self.c_s * outlet + self.c_h * hz
        if not warm or self.warmup_tau_s <= 0:
            return np.asarray(base, dtype=np.float64)
        return np.asarray(base + self.warmup * np.exp(-age_s / self.warmup_tau_s), np.float64)


def fit_cop_warmup(
    heat: FloatArray,
    elec: FloatArray,
    outside: FloatArray,
    outlet: FloatArray,
    hz: FloatArray,
    age_s: FloatArray,
    taus: tuple[float, ...] = WARMUP_TAUS_S,
) -> CopFit:
    """Least-squares ``ln(Q / P) = c0 + c_o T_o + c_s T_out + c_h Hz + w exp(-t / tau)``.

    ``t`` is the time since the heating start; ``tau`` is profiled over ``taus`` (the
    linear coefficients are exact least squares for each) and the best is kept. Bins
    older than :data:`WARMUP_WINDOW_S` enter with the term at zero, so steady operation
    anchors the map and the start-ups fit the term.

    Parameters
    ----------
    heat, elec, outside, outlet, hz, age_s
        Per-bin samples.
    taus
        Candidate time constants in seconds.

    Returns
    -------
    CopFit
        Coefficients and residual.
    """
    y = np.log(heat / elec)
    base = np.column_stack([np.ones(y.size), outside, outlet, hz])
    best: CopFit | None = None
    for tau in taus:
        term = np.where(age_s < WARMUP_WINDOW_S, np.exp(-age_s / tau), 0.0)
        x = np.column_stack([base, term])
        coef, *_ = np.linalg.lstsq(x, y, rcond=None)
        rmse = float(np.sqrt(np.mean((x @ coef - y) ** 2)))
        if best is None or rmse < best.rmse_log:
            c0, c_o, c_s, c_h, w = (float(v) for v in coef)
            best = CopFit(c0, c_o, c_s, c_h, w, float(tau), rmse, int(y.size))
    if best is None:
        raise ValueError("no warm-up time constant to try")
    return best


@dataclass(frozen=True, slots=True)
class WarmupCheck:
    """The warm-up term on a block of data (held-out in the identification).

    Parameters
    ----------
    early_s
        Start-up window scored separately.
    early_share_heat
        Share of the block's heat delivered in the start-up window.
    cop_recorded_early, cop_recorded_late
        Recorded COP (heat / pump estimate) inside and after the window.
    cop_model_early, cop_model_late
        The map with the warm-up term.
    cop_steady_map_early, cop_steady_map_late
        The map fitted on steady bins only, without a warm-up term (the earlier
        approach, extrapolated to start-ups).
    rmse_log_early, rmse_log_early_without
        ``ln COP`` residual in the window of the warm-up map and of the steady map.
    n_early
        Bins in the window.
    """

    early_s: float
    early_share_heat: float
    cop_recorded_early: float
    cop_recorded_late: float
    cop_model_early: float
    cop_model_late: float
    cop_steady_map_early: float
    cop_steady_map_late: float
    rmse_log_early: float
    rmse_log_early_without: float
    n_early: int


def check_warmup(
    ds: Dataset, fit: CopFit, steady: CopFit, early_s: float = WARMUP_REPORT_S
) -> WarmupCheck:
    """Score the warm-up COP map against the steady-only map on ``ds``.

    Parameters
    ----------
    ds
        Dataset (the held-out block in the identification).
    fit
        COP map with the warm-up term.
    steady
        COP map fitted on steady bins only.
    early_s
        Start-up window.

    Returns
    -------
    WarmupCheck
        Recorded and modelled COP inside and after the window, residuals.
    """
    c = ds.columns
    ok = cop_bins(ds)
    age = heating_start_age_s(ds)
    heat, elec = c["heat_w"], c["elec_hp_est_w"]
    args = (c["outside"], c["outlet"], c["hz"], age)
    with_term = np.exp(fit.log_cop(*args))
    without = np.exp(steady.log_cop(*args, warm=False))
    early = ok & (age < early_s)
    late = ok & (age >= early_s)
    y = np.full(heat.shape, np.nan)
    y[ok] = np.log(heat[ok] / elec[ok])

    def ratio(mask: BoolArray, cop: FloatArray | None = None) -> float:
        if not mask.any():
            return math.nan
        denominator = elec[mask] if cop is None else heat[mask] / cop[mask]
        return float(np.sum(heat[mask]) / np.sum(denominator))

    def rmse(mask: BoolArray, cop: FloatArray) -> float:
        if not mask.any():
            return math.nan
        return float(np.sqrt(np.mean((np.log(cop[mask]) - y[mask]) ** 2)))

    total = float(np.sum(heat[ok])) if ok.any() else math.nan
    return WarmupCheck(
        early_s=early_s,
        early_share_heat=float(np.sum(heat[early]) / total) if total else math.nan,
        cop_recorded_early=ratio(early),
        cop_recorded_late=ratio(late),
        cop_model_early=ratio(early, with_term),
        cop_model_late=ratio(late, with_term),
        cop_steady_map_early=ratio(early, without),
        cop_steady_map_late=ratio(late, without),
        rmse_log_early=rmse(early, with_term),
        rmse_log_early_without=rmse(early, without),
        n_early=int(early.sum()),
    )


@dataclass(frozen=True, slots=True)
class ControllerFit:
    """Fitted frequency controller (see :func:`ovenbird_sim.model.heatpump.next_frequency`).

    Parameters
    ----------
    outlet_bias_k, hz_deadband_k, hz_gain, hz_rate_down, hz_rate_up
        Integral controller.
    hz_start, start_phase_s
        Start phase (measured, not optimised).
    hz_resume0, hz_resume_o
        Frequency at the end of the start phase against the pump's outdoor reading.
    rmse_hz
        Replay RMSE of the frequency.
    std_hz
        Standard deviation of the recorded frequency (the no-skill reference).
    segments
        Running segments replayed.
    """

    outlet_bias_k: float
    hz_deadband_k: float
    hz_gain: float
    hz_start: float
    hz_rate_down: float
    hz_rate_up: float
    rmse_hz: float
    std_hz: float
    segments: int
    hz_resume0: float = 0.0
    hz_resume_o: float = 0.0
    start_phase_s: float = 0.0


def running_segments(ds: Dataset, min_bins: int = 10) -> list[tuple[int, int]]:
    """Index ranges of uninterrupted heating runs (full bins, no defrost, valid readings)."""
    c, f = ds.columns, ds.flags
    ok = (c["compressor_frac"] >= 0.999) & ~f["defrost"] & ~f["gap"] & ~f["stale"]
    ok &= np.isfinite(c["target"]) & np.isfinite(c["outlet"]) & np.isfinite(c["hz"])
    edges = np.flatnonzero(np.diff(np.r_[0, ok.astype(np.int8), 0]))
    pairs = zip(edges[::2], edges[1::2], strict=True)
    return [(int(a), int(b)) for a, b in pairs if b - a >= min_bins]


def restart_age_bins(ds: Dataset) -> np.ndarray:
    """Bins since the compressor (re)started: the start bin and defrost bins are age 0."""
    c, f = ds.columns, ds.flags
    on = np.nan_to_num(c["compressor_frac"]) > 0.0
    marker = np.r_[False, on[1:] & ~on[:-1]] | f["defrost"]
    index = np.arange(ds.grid.n)
    last = np.maximum.accumulate(np.where(marker, index, -1))
    return np.where(last >= 0, index - last, ds.grid.n).astype(np.int64)


@dataclass(frozen=True, slots=True)
class ReplayInputs:
    """Recorded inputs of the frequency replay, padded per segment.

    Parameters
    ----------
    setpoint, outlet, reading, floor
        Recorded setpoint, outlet, pump outdoor reading and frequency floor per step.
    recorded
        Recorded frequency (``NaN`` where not scored).
    phase_left
        Steps of the start phase still to come at each segment's first step.
    initial
        Recorded frequency at each segment's first step.
    """

    setpoint: np.ndarray
    outlet: np.ndarray
    reading: np.ndarray
    floor: np.ndarray
    recorded: np.ndarray
    phase_left: np.ndarray
    initial: np.ndarray


def replay_inputs(
    ds: Dataset,
    segments: list[tuple[int, int]],
    hz_min: float,
    floor: tuple[float, float] | None,
    start_phase_s: float,
) -> ReplayInputs:
    """Pad the recorded segments for :func:`replay_frequency`."""
    c = ds.columns
    length = max(b - a for a, b in segments)
    shape = (len(segments), length)
    sp, out, rec, rd = (np.full(shape, np.nan) for _ in range(4))
    floors = np.full(shape, hz_min)
    reading = np.round(np.nan_to_num(c["outside_hp"], nan=99.0))
    step_floor = (
        np.where(reading <= floor[1], floor[0], hz_min) if floor else np.full(reading.size, hz_min)
    )
    age = restart_age_bins(ds)
    phase_steps = round(start_phase_s / ds.grid.step)
    phase_left = np.zeros(len(segments), dtype=np.int64)
    initial = np.zeros(len(segments))
    for i, (a, b) in enumerate(segments):
        sp[i, : b - a] = c["target"][a:b]
        out[i, : b - a] = c["outlet"][a:b]
        rec[i, : b - a] = c["hz"][a:b]
        rd[i, : b - a] = reading[a:b]
        floors[i, : b - a] = step_floor[a:b]
        phase_left[i] = max(phase_steps - int(age[a]), 0)
        initial[i] = float(c["hz"][a])
    rec[:, 0] = np.nan
    return ReplayInputs(sp, out, np.nan_to_num(rd, nan=99.0), floors, rec, phase_left, initial)


def replay_frequency(
    theta: tuple[float, ...] | np.ndarray,
    inputs: ReplayInputs,
    hz_start: float,
    hz_max: float,
    minutes: float,
) -> np.ndarray:
    """Replay the frequency controller on padded run segments (vectorised over segments).

    Segments that begin inside the start phase hold ``hz_start`` for the rest of it and
    then jump to the resume level; the others start from the recorded frequency.

    Parameters
    ----------
    theta
        ``(bias, deadband, gain, rate_down, rate_up, resume0, resume_o)``.
    inputs
        Recorded segments (:func:`replay_inputs`).
    hz_start
        Start-phase frequency.
    hz_max
        Maximum frequency.
    minutes
        Step length in minutes.

    Returns
    -------
    np.ndarray
        Replayed frequency per segment and step.
    """
    bias, deadband, gain, rate_down, rate_up, resume0, resume_o = (float(v) for v in theta)
    n_seg, n_steps = inputs.setpoint.shape
    out = np.empty((n_seg, n_steps))
    in_phase = inputs.phase_left > 0
    hz = np.where(in_phase, np.maximum(hz_start, inputs.floor[:, 0]), inputs.initial)
    for k in range(n_steps):
        out[:, k] = hz
        error = np.nan_to_num(inputs.setpoint[:, k] + bias - inputs.outlet[:, k])
        excess = np.sign(error) * np.maximum(np.abs(error) - deadband, 0.0)
        change = np.clip(gain * excess * minutes, -rate_down * minutes, rate_up * minutes)
        following = min(k + 1, n_steps - 1)
        floor = inputs.floor[:, following]
        integrated = np.clip(hz + change, floor, hz_max)
        resume = np.clip(resume0 + resume_o * inputs.reading[:, following], floor, hz_max)
        hz = np.where(
            in_phase & (k + 1 < inputs.phase_left),
            hz,
            np.where(in_phase & (k + 1 == inputs.phase_left), resume, integrated),
        )
    return out


def fit_frequency_controller(
    ds: Dataset,
    hz_min: float,
    hz_max: float,
    floor: tuple[float, float] | None = None,
    start_phase: tuple[float, float] | None = None,
    seeds: tuple[tuple[float, ...], ...] | None = None,
    maxiter: int = 600,
    segments: list[tuple[int, int]] | None = None,
) -> tuple[ControllerFit, ...]:
    """Fit the frequency controller by replaying every recorded heating run.

    The recorded outlet and setpoint drive the controller open loop; the parameters
    minimise the RMSE between replayed and recorded frequency (bounded Nelder-Mead
    from several starts, as the deadband makes the loss non-smooth). The start phase
    (plateau frequency and length) is measured beforehand and held fixed; the resume
    level after it is fitted with the controller. The first bin of each segment is
    left out of the score (partial bin). Distinct optima with nearly the same replay
    error are common - the frequency trace barely constrains the deadband against the
    gain - so every optimum within 5 % of the best is returned; they can differ in
    closed-loop cycling and are told apart by
    :func:`ovenbird_sim.identify.pipeline.select_controller`.

    Parameters
    ----------
    ds
        Dataset (1 min grid).
    hz_min, hz_max
        Frequency limits.
    floor
        ``(hz_min_cold, cold_floor_outside_c)``; without it the floor is ``hz_min``.
    start_phase
        ``(hz_start, start_phase_s)``; without it there is no start phase and runs
        start at the first starting point's frequency.
    seeds
        Starting points ``(bias, deadband, gain, rate_down, rate_up[, resume0,
        resume_o])`` (default :data:`CONTROLLER_STARTS`).
    maxiter
        Nelder-Mead iterations per start.
    segments
        Run segments to replay (default :func:`running_segments`; a bootstrap passes
        resampled ones, repeats allowed).

    Returns
    -------
    tuple of ControllerFit
        Near-equivalent optima, best replay first.
    """
    hz_start, phase_s = start_phase if start_phase is not None else (40.0, 0.0)
    segments = running_segments(ds) if segments is None else segments
    if not segments:
        bias, deadband, gain, down, up = CONTROLLER_STARTS[0]
        return (ControllerFit(bias, deadband, gain, hz_start, down, up, math.nan, math.nan, 0),)
    inputs = replay_inputs(ds, segments, hz_min, floor, phase_s)
    mask = np.isfinite(inputs.recorded)
    minutes = ds.grid.step / 60.0
    resume_guess = _resume_guess(inputs, hz_min, hz_max)

    free = len(CONTROLLER_BOUNDS) if phase_s > 0 else len(CONTROLLER_BOUNDS) - 2

    def full(theta: np.ndarray) -> np.ndarray:
        return theta if theta.size == len(CONTROLLER_BOUNDS) else np.r_[theta, resume_guess]

    def loss(theta: np.ndarray) -> float:
        sim = replay_frequency(full(theta), inputs, hz_start, hz_max, minutes)
        return float(np.sqrt(np.mean((sim[mask] - inputs.recorded[mask]) ** 2)))

    starts = [
        np.array(seed if len(seed) == 7 else (*seed, *resume_guess))[:free]
        for seed in (seeds or CONTROLLER_STARTS)
    ]
    results = [
        minimize(
            loss,
            start,
            method="Nelder-Mead",
            bounds=CONTROLLER_BOUNDS[:free],
            options={"maxiter": maxiter, "xatol": 1e-3, "fatol": 1e-4},
        )
        for start in starts
    ]
    std = float(np.std(inputs.recorded[mask]))
    fits = sorted(
        (
            _controller(full(r.x), float(r.fun), std, len(segments), hz_start, phase_s)
            for r in results
        ),
        key=_rmse,
    )
    return tuple(f for f in fits if f.rmse_hz <= fits[0].rmse_hz * (1.0 + CANDIDATE_TOLERANCE))


def _resume_guess(inputs: ReplayInputs, hz_min: float, hz_max: float) -> tuple[float, float]:
    rows = np.flatnonzero(inputs.phase_left > 0)
    steps = inputs.phase_left[rows] + 1
    keep = steps < inputs.recorded.shape[1]
    rows, steps = rows[keep], steps[keep]
    hz = inputs.recorded[rows, steps]
    reading = inputs.reading[rows, steps]
    ok = np.isfinite(hz) & (reading < 90.0)
    if ok.sum() < 3:
        return 0.5 * (hz_min + hz_max), 0.0
    x = np.column_stack([np.ones(ok.sum()), reading[ok]])
    coef, *_ = np.linalg.lstsq(x, hz[ok], rcond=None)
    return float(coef[0]), float(coef[1])


def _controller(
    x: np.ndarray, rmse: float, std: float, segments: int, hz_start: float, phase_s: float
) -> ControllerFit:
    bias, deadband, gain, rate_down, rate_up, resume0, resume_o = (float(v) for v in x)
    return ControllerFit(
        bias,
        deadband,
        gain,
        hz_start,
        rate_down,
        rate_up,
        rmse,
        std,
        segments,
        resume0,
        resume_o,
        phase_s,
    )


def _rmse(fit: ControllerFit) -> float:
    return fit.rmse_hz


def controller_seed(fit: ControllerFit) -> tuple[float, ...]:
    """Return the starting point of :func:`fit_frequency_controller` at an existing fit."""
    return (
        fit.outlet_bias_k,
        fit.hz_deadband_k,
        fit.hz_gain,
        fit.hz_rate_down,
        fit.hz_rate_up,
        fit.hz_resume0,
        fit.hz_resume_o,
    )


def with_controller(params: HeatPumpParams, controller: ControllerFit) -> HeatPumpParams:
    """Return ``params`` with the frequency-controller fields of ``controller``."""
    return params.replace(
        outlet_bias_k=controller.outlet_bias_k,
        hz_start=controller.hz_start,
        hz_gain=controller.hz_gain,
        hz_deadband_k=controller.hz_deadband_k,
        hz_rate_down=controller.hz_rate_down,
        hz_rate_up=controller.hz_rate_up,
        hz_resume0=controller.hz_resume0,
        hz_resume_o=controller.hz_resume_o,
        start_phase_s=controller.start_phase_s,
    )


def fit_cold_floor(
    hz: FloatArray, sensor: FloatArray, hz_min: float, min_bins: int = 50
) -> tuple[float, float]:
    """Find the raised minimum frequency in cold weather.

    For every integer reading of the pump's outdoor sensor the 2nd percentile of the
    steady running frequency is taken as that reading's floor. The cold threshold is
    the warmest reading whose floor exceeds ``hz_min`` by more than 5 Hz with every
    colder reading doing the same; the cold floor is the median of those floors.

    Parameters
    ----------
    hz, sensor
        Steady-running frequency and pump outdoor reading per bin.
    hz_min
        The ordinary floor.
    min_bins
        Readings with fewer bins are ignored.

    Returns
    -------
    hz_min_cold, threshold_c
        ``(hz_min, -100)`` when no raised floor is visible.
    """
    readings = np.round(sensor)
    levels = sorted({float(v) for v in readings[np.isfinite(readings)]})
    floors = {}
    for level in levels:
        values = hz[readings == level]
        if values.size >= min_bins:
            floors[level] = float(np.percentile(values, 2))
    raised = [level for level in sorted(floors) if floors[level] > hz_min + 5.0]
    threshold = None
    for level in sorted(floors):
        if floors[level] > hz_min + 5.0:
            threshold = level
        else:
            break
    if threshold is None or not raised:
        return hz_min, -100.0
    cold = [floors[level] for level in sorted(floors) if level <= threshold]
    return float(np.median(cold)), threshold


def fit_defrost_rate(
    outside_at_start: FloatArray, outside_running: FloatArray, step: float, max_outside: float
) -> tuple[float, float]:
    """Poisson fit of the defrost rate per running hour, ``exp(d0 + d_o T_o)``.

    Parameters
    ----------
    outside_at_start
        Outside temperature at each defrost start.
    outside_running
        Outside temperature of every running bin.
    step
        Bin length in seconds.
    max_outside
        Bins warmer than this are excluded (no frost there).

    Returns
    -------
    d0, d_o
        Log-rate intercept and slope.
    """
    exposure = outside_running[outside_running <= max_outside]
    events = outside_at_start[outside_at_start <= max_outside]
    hours = step / 3600.0

    def nll(theta: np.ndarray) -> float:
        d0, d_o = theta
        log_rate_events = d0 + d_o * events
        integral = hours * np.sum(np.exp(d0 + d_o * exposure))
        return float(integral - np.sum(log_rate_events))

    result = minimize(nll, np.array([0.0, -0.5]), method="Nelder-Mead", options={"xatol": 1e-6})
    return float(result.x[0]), float(result.x[1])


@dataclass(frozen=True, slots=True)
class FrostFit:
    """Frost model fit (see :func:`ovenbird_sim.model.heatpump.frost_rate_per_s`).

    Parameters
    ----------
    coil0, coil_o, coil_h
        Coil temperature map ``coil0 + coil_o T_o + coil_h Hz``.
    coil_rmse_k
        Residual of the coil map.
    n_coil
        Bins of the coil fit.
    driver_hpa_h
        Driving vapour pressure integrated over the running time of the data.
    events
        Defrosts in the data.
    capacity_hpa_h
        ``driver_hpa_h / events`` (:data:`FROST_CAPACITY_NONE` without events).
    rh_pct
        Median outside relative humidity (the default when none is supplied).
    """

    coil0: float
    coil_o: float
    coil_h: float
    coil_rmse_k: float
    n_coil: int
    driver_hpa_h: float
    events: int
    capacity_hpa_h: float
    rh_pct: float


def defrost_starts(ds: Dataset) -> np.ndarray:
    """Bins where a defrost begins."""
    d = ds.flags["defrost"]
    return np.flatnonzero(~d[:-1] & d[1:]) + 1


def frost_free_coil_bins(ds: Dataset) -> BoolArray:
    """Steady running bins with a valid pipe reading and no frost build-up yet.

    The pipe sensor drops as frost insulates the coil, so the last
    :data:`FROST_FREE_BEFORE_DEFROST_S` before every defrost are left out.
    """
    c = ds.columns
    ok = steady_running(ds) & np.isfinite(c["outside_pipe"])
    before = np.zeros(ds.grid.n, dtype=np.bool_)
    span = round(FROST_FREE_BEFORE_DEFROST_S / ds.grid.step)
    for s in defrost_starts(ds):
        before[max(0, s - span) : s] = True
    return np.asarray(ok & ~before, dtype=np.bool_)


def frost_driver_series(p: HeatPumpParams, ds: Dataset, rh: FloatArray) -> FloatArray:
    """Driving vapour pressure (hPa) per bin of heating operation (0 elsewhere)."""
    c, f = ds.columns, ds.flags
    running = (c["compressor_frac"] >= 0.999) & ~f["defrost"] & np.isfinite(c["outside"])
    out = np.zeros(ds.grid.n)
    for k in np.flatnonzero(running):
        out[k] = frost_driver_hpa(
            p, float(c["outside"][k]), float(np.nan_to_num(c["hz"][k])), rh[k]
        )
    return out


def fit_frost(ds: Dataset, rh: FloatArray, events: np.ndarray | None = None) -> FrostFit | None:
    """Fit the coil map and the frost capacity.

    The coil temperature is regressed on the outside temperature and the
    frequency over frost-free steady running (:func:`frost_free_coil_bins`). The
    capacity is the driving vapour pressure integrated over the running time of the
    data divided by the number of defrosts: the moment estimate of a process that
    defrosts each time the deposit fills the coil. Physically the deposit follows the
    vapour-pressure difference between the air and ice at the coil, so a capacity
    fitted on mild weeks extrapolates to colder, wetter ones through the driver.

    Parameters
    ----------
    ds
        Dataset (1 min grid) with ``outside_pipe``.
    rh
        Outside relative humidity per bin.
    events
        Defrost start bins to count (default: all in ``ds``).

    Returns
    -------
    FrostFit or None
        ``None`` without enough pipe readings.
    """
    c = ds.columns
    if "outside_pipe" not in c:
        return None
    sel = frost_free_coil_bins(ds)
    if sel.sum() < MIN_COIL_BINS:
        return None
    x = np.column_stack([np.ones(sel.sum()), c["outside"][sel], c["hz"][sel]])
    coef, *_ = np.linalg.lstsq(x, c["outside_pipe"][sel], rcond=None)
    rmse = float(np.sqrt(np.mean((x @ coef - c["outside_pipe"][sel]) ** 2)))
    finite = rh[np.isfinite(rh)]
    rh_default = float(np.median(finite)) if finite.size else HeatPumpParams().frost_rh_pct
    coil = HeatPumpParams().replace(
        coil0=float(coef[0]), coil_o=float(coef[1]), coil_h=float(coef[2]), frost_rh_pct=rh_default
    )
    driver = float(frost_driver_series(coil, ds, rh).sum() * ds.grid.step / 3600.0)
    n_events = int((defrost_starts(ds) if events is None else events).size)
    capacity = driver / n_events if n_events and driver > 0 else FROST_CAPACITY_NONE
    return FrostFit(
        float(coef[0]),
        float(coef[1]),
        float(coef[2]),
        rmse,
        int(sel.sum()),
        driver,
        n_events,
        capacity,
        rh_default,
    )


def frost_params(fit: FrostFit | None) -> dict[str, float]:
    """Parameter fields of a frost fit (empty without one: the empirical rate stays)."""
    if fit is None:
        return {}
    return {
        "coil0": fit.coil0,
        "coil_o": fit.coil_o,
        "coil_h": fit.coil_h,
        "frost_capacity_hpa_h": fit.capacity_hpa_h,
        "frost_rh_pct": fit.rh_pct,
    }


def p1_step_ratio(ds: Dataset) -> float:
    """Median ratio of the grid meter step to the pump-estimate step at night starts."""
    c = ds.columns
    if "p1_w" not in c or "ghi" not in c:
        return math.nan
    run = c["compressor_frac"] > 0.5
    night = (c["ghi"] < 1.0) & np.isfinite(c["p1_w"])
    starts = np.flatnonzero(~run[:-1] & run[1:]) + 1
    ratios = []
    for s in starts:
        if s < 10 or s + 15 > run.size or not night[s - 10 : s + 15].all():
            continue
        dp = np.nanmean(c["p1_w"][s + 5 : s + 15]) - np.nanmean(c["p1_w"][s - 10 : s - 1])
        de = np.nanmean(c["elec_hp_est_w"][s + 5 : s + 15]) - np.nanmean(
            c["elec_hp_est_w"][s - 10 : s - 1]
        )
        if de > 300:
            ratios.append(dp / de)
    return float(np.median(ratios)) if ratios else math.nan


def fit_heat_pump(
    ds: Dataset,
    start_rule: StartRuleFit | None = None,
    start_phase: StartPhaseFit | None = None,
) -> HeatPumpFit:
    """Fit the heat-pump layer.

    Parameters
    ----------
    ds
        Dataset (1 min grid recommended).
    start_rule
        Fitted start rule; defaults are kept without one.
    start_phase
        Measured start phase; without one (or when it is not finite) the compressor
        starts at the fitted frequency without a phase.

    Returns
    -------
    HeatPumpFit
        Parameters and diagnostics.
    """
    c, f = ds.columns, ds.flags
    steady = steady_running(ds)
    heat, hz, t_o, t_out = (
        c["heat_w"][steady],
        c["hz"][steady],
        c["outside"][steady],
        c["outlet"][steady],
    )
    sel = cop_bins(ds)
    age = heating_start_age_s(ds)
    capacity = fit_capacity_warmup(
        c["heat_w"][sel], c["hz"][sel], c["outside"][sel], c["inlet"][sel], age[sel]
    )
    k0, k_o, k_in = capacity.k0, capacity.k_o, capacity.k_in
    cap_rmse = capacity.rmse_w
    steady_coef, steady_rmse = fit_cop(heat, c["elec_hp_est_w"][steady], t_o, t_out, hz)
    cop_steady = CopFit(*steady_coef, 0.0, 0.0, steady_rmse, int(steady.sum()))
    cop_fit = fit_cop_warmup(
        c["heat_w"][sel],
        c["elec_hp_est_w"][sel],
        c["outside"][sel],
        c["outlet"][sel],
        c["hz"][sel],
        age[sel],
    )
    hz_min = float(np.floor(np.percentile(hz, 1)))
    full_run = (c["compressor_frac"] >= 0.999) & ~f["defrost"] & np.isfinite(c["hz"])
    hz_max = float(np.ceil(np.percentile(c["hz"][full_run], 99.9)))
    hz_min_cold, cold_threshold = fit_cold_floor(c["hz"][steady], c["outside_hp"][steady], hz_min)
    phase = (
        (start_phase.hz, start_phase.duration_s)
        if start_phase is not None and math.isfinite(start_phase.hz)
        else None
    )
    candidates = fit_frequency_controller(ds, hz_min, hz_max, (hz_min_cold, cold_threshold), phase)
    controller = candidates[0]
    running = c["compressor_frac"] >= 0.999
    idle = c["compressor_frac"] <= 0.0
    idle_elec = c["elec_hp_est_w"][idle & ~f["gap"] & ~f["defrost"] & ~f["dhw"]]
    idle_w = float(np.nanmean(idle_elec)) if np.isfinite(idle_elec).any() else 0.0
    flow_run = float(np.nanmedian(c["flow"][steady]))
    flow_idle = float(np.nanmedian(c["flow"][idle & ~f["gap"]]))

    defrost = f["defrost"]
    d_starts = np.flatnonzero(~defrost[:-1] & defrost[1:]) + 1
    d_lengths, d_heat = [], []
    for s in d_starts:
        e = s
        while e < defrost.size and defrost[e]:
            e += 1
        d_lengths.append((e - s) * ds.grid.step)
        d_heat.append(float(np.nanmean(c["heat_w"][s:e])))
    t_o_all = c["outside"]
    max_outside = (float(np.max(t_o_all[d_starts])) + 1.0) if d_starts.size else -50.0
    if d_starts.size >= 3:
        d0, d_o = fit_defrost_rate(
            t_o_all[d_starts], t_o_all[running & np.isfinite(t_o_all)], ds.grid.step, max_outside
        )
    else:
        d0, d_o = -10.0, 0.0
    table = []
    for lo in np.arange(-4.0, 16.0, 2.0):
        in_bin = (t_o_all >= lo) & (t_o_all < lo + 2.0)
        hours = float((running & in_bin).sum() * ds.grid.step / 3600.0)
        table.append((float(lo), hours, int(np.sum(in_bin[d_starts]))))
    defrost_elec = float(np.nanmedian(c["elec_hp_est_w"][defrost])) if defrost.any() else 1000.0

    frost = fit_frost(ds, humidity(ds))
    sensor_bias_run = float(np.nanmedian((c["outside_hp"] - c["outside"])[running]))
    defaults = HeatPumpParams()
    rule = start_rule
    params = HeatPumpParams(
        start_trigger_margin_k=rule.trigger_margin_k if rule else defaults.start_trigger_margin_k,
        start_steady_margin_k=rule.steady_margin_k if rule else defaults.start_steady_margin_k,
        start_steady_delay_s=rule.steady_delay_s if rule else defaults.start_steady_delay_s,
        min_off_s=rule.min_off_s if rule else defaults.min_off_s,
        outlet_bias_k=controller.outlet_bias_k,
        hz_start=controller.hz_start,
        hz_gain=controller.hz_gain,
        hz_deadband_k=controller.hz_deadband_k,
        hz_rate_down=controller.hz_rate_down,
        hz_rate_up=controller.hz_rate_up,
        hz_min=hz_min,
        hz_max=hz_max,
        hz_min_cold=hz_min_cold,
        cold_floor_outside_c=cold_threshold,
        k0=k0,
        k_o=k_o,
        k_s=0.0,
        k_in=k_in,
        k_warmup=capacity.warmup,
        k_warmup_tau_s=capacity.warmup_tau_s,
        q0_w=capacity.q0_w,
        hz_resume0=controller.hz_resume0,
        hz_resume_o=controller.hz_resume_o,
        start_phase_s=controller.start_phase_s,
        cop0=cop_fit.c0,
        cop_o=cop_fit.c_o,
        cop_s=cop_fit.c_s,
        cop_h=cop_fit.c_h,
        cop_hh=0.0,
        cop_warmup=cop_fit.warmup,
        cop_warmup_tau_s=cop_fit.warmup_tau_s,
        circulation_w=idle_w,
        flow_running_lpm=flow_run,
        flow_idle_lpm=flow_idle,
        defrost0=d0,
        defrost_o=d_o,
        defrost_max_outside_c=max_outside,
        defrost_duration_s=float(np.median(d_lengths))
        if d_lengths
        else defaults.defrost_duration_s,
        defrost_heat_w=min(float(np.median(d_heat)), 0.0) if d_heat else defaults.defrost_heat_w,
        defrost_elec_w=defrost_elec,
        spread_offset_k=ds.calibration.offset_k,
        outside_bias_running_k=sensor_bias_run,
    ).replace(**frost_params(frost))
    pump_ratio = float(np.nanmedian(c["heat_hp_est_w"][steady] / c["heat_w"][steady]))
    return HeatPumpFit(
        params=params,
        capacity_rmse_w=cap_rmse,
        cop_rmse_log=cop_fit.rmse_log,
        n_steady=int(steady.sum()),
        defrost_events=int(d_starts.size),
        defrost_rate_table=tuple(table),
        p1_ratio=p1_step_ratio(ds),
        pump_vs_loop_heat=pump_ratio,
        controller=controller,
        controller_candidates=candidates,
        cop=cop_fit,
        cop_steady=cop_steady,
        capacity=capacity,
        frost=frost,
    )


def day_index(ds: Dataset) -> np.ndarray:
    """UTC day number of every bin counted from the first bin's UTC day."""
    return utc_days(ds.t, ds.grid.start)


def utc_days(t: FloatArray, t0: float) -> np.ndarray:
    """UTC day numbers of ``t`` counted from the UTC day of ``t0``."""
    return np.asarray(np.floor(t / 86400.0) - math.floor(t0 / 86400.0), dtype=np.int64)


def resample_days(days: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Draw ``days.size`` days with replacement (a day-block bootstrap)."""
    return np.asarray(rng.choice(days, days.size), dtype=np.int64)


def refit_maps(ds: Dataset, point: HeatPumpParams, picked: np.ndarray) -> HeatPumpParams:
    """Refit the data-driven maps of ``point`` on the bins of the picked days.

    Capacity and COP (with their start-up terms, time constants held at the point),
    the frost capacity (coil map held) or the empirical defrost rate and the idle
    draw are refitted on the resampled bins; every other field is kept.

    Parameters
    ----------
    ds
        Dataset (1 min grid).
    point
        Point estimate.
    picked
        Day numbers of the resample (repeats allowed).

    Returns
    -------
    HeatPumpParams
        The refitted parameters.
    """
    c, f = ds.columns, ds.flags
    day = day_index(ds)
    by_day = {int(d): np.flatnonzero(day == d) for d in np.unique(day)}
    pick = np.concatenate([by_day.get(int(d), np.zeros(0, np.int64)) for d in picked])
    sel = pick[cop_bins(ds)[pick]]
    age = heating_start_age_s(ds)
    changes: dict[str, float] = {}
    if sel.size > 50:
        capacity = fit_capacity_warmup(
            c["heat_w"][sel],
            c["hz"][sel],
            c["outside"][sel],
            c["inlet"][sel],
            age[sel],
            (point.k_warmup_tau_s,) if point.k_warmup_tau_s > 0 else WARMUP_TAUS_S,
        )
        cop_fit = fit_cop_warmup(
            c["heat_w"][sel],
            c["elec_hp_est_w"][sel],
            c["outside"][sel],
            c["outlet"][sel],
            c["hz"][sel],
            age[sel],
            (point.cop_warmup_tau_s,) if point.cop_warmup_tau_s > 0 else WARMUP_TAUS_S,
        )
        changes |= {
            "k0": capacity.k0,
            "k_o": capacity.k_o,
            "k_s": 0.0,
            "k_in": capacity.k_in,
            "k_warmup": capacity.warmup,
            "q0_w": capacity.q0_w,
            "cop0": cop_fit.c0,
            "cop_o": cop_fit.c_o,
            "cop_s": cop_fit.c_s,
            "cop_h": cop_fit.c_h,
            "cop_warmup": cop_fit.warmup,
        }
    idle = pick[(c["compressor_frac"][pick] <= 0.0) & ~f["gap"][pick] & ~f["defrost"][pick]]
    idle_w = c["elec_hp_est_w"][idle]
    if np.isfinite(idle_w).any():
        changes["circulation_w"] = float(np.nanmean(idle_w))
    defrost = f["defrost"]
    d_start = np.r_[False, ~defrost[:-1] & defrost[1:]]
    running = c["compressor_frac"] >= 0.999
    events = pick[d_start[pick]]
    exposure = pick[running[pick] & np.isfinite(c["outside"][pick])]
    if point.frost_capacity_hpa_h > 0:
        driver = frost_driver_series(point, ds, humidity(ds))
        total = float(driver[pick].sum() * ds.grid.step / 3600.0)
        changes["frost_capacity_hpa_h"] = (
            total / events.size if events.size and total > 0 else FROST_CAPACITY_NONE
        )
    elif events.size >= 3:
        d0, d_o = fit_defrost_rate(
            c["outside"][events], c["outside"][exposure], ds.grid.step, point.defrost_max_outside_c
        )
        if math.isfinite(d0) and math.isfinite(d_o):
            changes |= {"defrost0": d0, "defrost_o": d_o}
    return point.replace(**changes)


def refit_controller(
    ds: Dataset, point: HeatPumpParams, picked: np.ndarray, maxiter: int = 250
) -> HeatPumpParams:
    """Refit the frequency controller on the run segments of the picked days.

    One Nelder-Mead start at the point estimate; the start phase is held.

    Parameters
    ----------
    ds
        Dataset (1 min grid).
    point
        Point estimate.
    picked
        Day numbers of the resample (repeats allowed).
    maxiter
        Iterations.

    Returns
    -------
    HeatPumpParams
        ``point`` with the refitted controller.
    """
    day = day_index(ds)
    by_day: dict[int, list[tuple[int, int]]] = {}
    for a, b in running_segments(ds):
        by_day.setdefault(int(day[a]), []).append((a, b))
    segments = [seg for d in picked for seg in by_day.get(int(d), [])]
    if not segments:
        return point
    seed = (
        point.outlet_bias_k,
        point.hz_deadband_k,
        point.hz_gain,
        point.hz_rate_down,
        point.hz_rate_up,
        point.hz_resume0,
        point.hz_resume_o,
    )
    fits = fit_frequency_controller(
        ds,
        point.hz_min,
        point.hz_max,
        (point.hz_min_cold, point.cold_floor_outside_c),
        (point.hz_start, point.start_phase_s) if point.start_phase_s > 0 else None,
        seeds=(seed,),
        maxiter=maxiter,
        segments=segments,
    )
    return with_controller(point, fits[0])


REFERENCE_POINTS: dict[str, tuple[float, float, float]] = {
    "cop_2c_35c_35hz": (2.0, 35.0, 35.0),
    "cop_7c_30c_20hz": (7.0, 30.0, 20.0),
}


def bootstrap_heat_pump(
    ds: Dataset, params: HeatPumpParams, replicates: int, seed: int = 0, level: float = 0.9
) -> dict[str, tuple[float, float]]:
    """Day-block bootstrap intervals of the heat-pump maps at reference points.

    Days are resampled with replacement and the maps are refitted on them
    (:func:`refit_maps`: capacity and COP with their start-up terms, defrost rate, idle
    draw). The counterfactual's ensemble also refits the start rule and the frequency
    controller (:mod:`ovenbird_sim.evaluate.ensemble`).

    Parameters
    ----------
    ds
        Dataset (1 min grid).
    params
        Point estimate.
    replicates
        Number of replicates.
    seed
        Random seed.
    level
        Interval level.

    Returns
    -------
    dict
        Interval per quantity: heat per hertz and minimum heat at two reference
        points, COP at two reference points, defrost rate at 0 and 3 degC.
    """
    days = np.unique(day_index(ds))
    rng = np.random.default_rng(seed)
    rows: dict[str, list[float]] = {}
    for _ in range(replicates):
        p = refit_maps(ds, params, resample_days(days, rng))
        values = {
            "heat_per_hz_7c_30c": heat_per_hz_steady(p, 7.0, 30.0, inlet_c=30.0),
            "q_min_7c_30c_w": heat_output(p, 7.0, 30.0, p.hz_min, inlet_c=30.0),
            "q_min_2c_35c_w": heat_output(p, 2.0, 35.0, p.hz_min_cold, inlet_c=35.0),
            "defrost_per_run_h_0c_90rh": 3600.0 * frost_rate_per_s(p, 0.0, 35.0, 90.0),
            "defrost_per_run_h_3c_90rh": 3600.0 * frost_rate_per_s(p, 3.0, 35.0, 90.0),
        }
        for name, (t_o, t_out, hz) in REFERENCE_POINTS.items():
            values[name] = model_cop(p, t_o, t_out, hz)
        for name, value in values.items():
            rows.setdefault(name, []).append(value)
    tail = (1.0 - level) / 2.0 * 100.0
    return {
        name: (float(np.percentile(v, tail)), float(np.percentile(v, 100.0 - tail)))
        for name, v in rows.items()
    }

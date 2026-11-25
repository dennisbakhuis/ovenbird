"""Verify and fit the pump's own compressor start/stop rule on the 5 s base grid.

The commonly quoted rule is: start at ``inlet <= SP - 4``, stop
at ``outlet >= SP + 2`` held for 3 min, with ``SP`` the applied water target
(``Main_Target_Temp``). Starts and stops are taken from ``Compressor_Freq``;
stop/start pairs around a defrost (the compressor pauses to reverse) are not
counted as heating starts.

Start timing is fitted by replaying candidate rules over every recorded off period
(from a heating stop to the next heating start) on the recorded inlet and target and
scoring the share of starts the rule predicts within +-2 min.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

from ovenbird_sim.data.grid import BASE_STEP_S, TimeGrid, hold, time_since
from ovenbird_sim.data.series import BoolArray, FloatArray, Series

MAX_AGE_S = 330.0
DEFROST_GUARD_S = 120.0
HIT_TOLERANCE_S = 120.0
TRIGGER_MARGINS = (3.25, 3.5, 3.75, 4.0, 4.25, 4.5)
STEADY_MARGINS = (4.5, 4.75, 5.0, 5.25, 5.5, 5.75, 6.0, 6.5, 99.0)
STEADY_DELAYS_S = (0.0, 300.0, 600.0, 1200.0, 1800.0, 2700.0, 3600.0)


@dataclass(frozen=True, slots=True)
class BaseSignals:
    """Pump signals on the 5 s base grid.

    Parameters
    ----------
    t
        Sample times (unix s).
    inlet, outlet, hz, target
        Held readings (``NaN`` when stale).
    defrost
        Defrost flag.
    step
        Grid step in seconds (5 s from a capture, 60 s from the service's history).
    """

    t: FloatArray
    inlet: FloatArray
    outlet: FloatArray
    hz: FloatArray
    target: FloatArray
    defrost: BoolArray
    step: float = BASE_STEP_S

    @property
    def running(self) -> BoolArray:
        """Compressor running."""
        return np.asarray(np.nan_to_num(self.hz) > 0, dtype=np.bool_)

    def window(self, start: float | None = None, end: float | None = None) -> BaseSignals:
        """Return the samples with ``start <= t < end``."""
        lo = 0 if start is None else int(np.searchsorted(self.t, start))
        hi = self.t.size if end is None else int(np.searchsorted(self.t, end))
        return BaseSignals(
            self.t[lo:hi],
            self.inlet[lo:hi],
            self.outlet[lo:hi],
            self.hz[lo:hi],
            self.target[lo:hi],
            self.defrost[lo:hi],
            self.step,
        )


def base_signals(capture: Mapping[str, Series], step: float = BASE_STEP_S) -> BaseSignals:
    """Hold the switching-relevant capture series on a regular base grid."""
    live = capture["liveness"]
    grid = TimeGrid.covering(float(live.t[0]), float(live.t[-1]), step)
    t = grid.mids

    def held(key: str) -> FloatArray:
        return hold(capture.get(key, Series.empty()), t, MAX_AGE_S)[0]

    defrost = np.asarray(np.nan_to_num(held("main/Defrosting_State")) >= 1, dtype=np.bool_)
    return BaseSignals(
        t,
        held("main/Main_Inlet_Temp"),
        held("main/Main_Outlet_Temp"),
        held("main/Compressor_Freq"),
        held("main/Main_Target_Temp"),
        defrost,
    )


@dataclass(frozen=True, slots=True)
class StartRuleFit:
    """Best start rule found by replay.

    Parameters
    ----------
    trigger_margin_k
        Start on a setpoint change when ``inlet <= SP - margin``.
    steady_margin_k, steady_delay_s
        Start with a steady setpoint after ``inlet <= SP - margin`` held for the delay.
    min_off_s
        Shortest heating off time observed (used as minimum off time).
    hit_rate
        Share of starts predicted within +-2 min.
    documented_hit_rate
        Same score for the documented rule (``inlet <= SP - 4``, no delay).
    """

    trigger_margin_k: float
    steady_margin_k: float
    steady_delay_s: float
    min_off_s: float
    hit_rate: float
    documented_hit_rate: float


@dataclass(frozen=True, slots=True)
class SwitchingReport:
    """Evidence about the start/stop rule.

    Parameters
    ----------
    days
        Span covered.
    starts, heating_starts, defrosts
        Compressor starts, starts excluding defrost restarts, defrost events.
    stop_rule_share
        Heating stops preceded by ``outlet >= SP + 2`` for at least 170 s.
    stop_hold_median_s
        Median time that condition held before a stop.
    overshoot_without_stop
        Episodes with ``outlet >= SP + 2`` for 185 s or more that did not end in a stop.
    start_doc_share
        Heating starts with ``inlet <= SP - 4`` at the start.
    start_after_change_share
        Heating starts within 60 s after a target change.
    p_start_after_change
        Probability of a start within 30 s after a target change, by ``inlet - SP``.
    p_start_steady
        Same with the target unchanged for at least 2 min (per 30 s).
    run_minutes_median, short_run_share
        Median heating run and share of runs shorter than 20 min.
    start_fit
        Fitted start rule.
    start_phase
        Fixed-frequency start phase.
    """

    days: float
    starts: int
    heating_starts: int
    defrosts: int
    stop_rule_share: float
    stop_hold_median_s: float
    overshoot_without_stop: int
    start_doc_share: float
    start_after_change_share: float
    p_start_after_change: dict[float, float] = field(default_factory=dict)
    p_start_steady: dict[float, float] = field(default_factory=dict)
    run_minutes_median: float = float("nan")
    short_run_share: float = float("nan")
    start_fit: StartRuleFit | None = None
    start_phase: StartPhaseFit | None = None


def _edges(flag: BoolArray) -> tuple[np.ndarray, np.ndarray]:
    rises = np.flatnonzero(~flag[:-1] & flag[1:]) + 1
    falls = np.flatnonzero(flag[:-1] & ~flag[1:]) + 1
    return rises, falls


def heating_switches(sig: BaseSignals, step: float = BASE_STEP_S) -> tuple[np.ndarray, np.ndarray]:
    """Heating start and stop indices (defrost pauses and restarts removed)."""
    starts, stops = _edges(sig.running)
    guard = round(DEFROST_GUARD_S / step)
    near = np.convolve(sig.defrost.astype(np.int64), np.ones(2 * guard + 1, dtype=np.int64), "same")
    near_b = near > 0
    return starts[~near_b[starts]], stops[~near_b[stops]]


def _hold_before(cond: BoolArray, index: int, also: BoolArray) -> int:
    k = index - 1
    n = 0
    while k >= 0 and cond[k] and also[k]:
        n += 1
        k -= 1
    return n


def _replay(
    inlet_minus_sp: FloatArray,
    changed: BoolArray,
    trigger: float,
    steady: float,
    delay_n: int,
    min_off_n: int,
) -> int | None:
    trig = changed & (inlet_minus_sp <= -trigger)
    cond = (inlet_minus_sp <= -steady) & ~changed
    if delay_n == 0:
        steady_fire = cond
    else:
        run = np.zeros(cond.size, dtype=np.int64)
        count = 0
        for i, c in enumerate(cond):
            count = count + 1 if c else 0
            run[i] = count
        steady_fire = run >= delay_n
    fire = (trig | steady_fire) & (np.arange(cond.size) >= min_off_n)
    hits = np.flatnonzero(fire)
    return int(hits[0]) if hits.size else None


def fit_start_rule(
    sig: BaseSignals,
    starts: np.ndarray,
    stops: np.ndarray,
    step: float = BASE_STEP_S,
) -> StartRuleFit:
    """Grid-search the start rule that best predicts the recorded start times.

    Parameters
    ----------
    sig
        Base-grid signals.
    starts, stops
        Heating start and stop indices.
    step
        Base step in seconds.

    Returns
    -------
    StartRuleFit
        The best rule and its hit rate next to the documented rule's.
    """
    changed = np.r_[False, sig.target[1:] != sig.target[:-1]]
    periods: list[tuple[FloatArray, BoolArray, int]] = []
    off_times: list[float] = []
    for s in starts:
        prev = stops[stops < s]
        if not prev.size:
            continue
        a = int(prev[-1])
        off_times.append((s - a) * step)
        d = sig.inlet[a : s + 1] - sig.target[a : s + 1]
        periods.append((np.nan_to_num(d, nan=0.0), changed[a : s + 1], int(s - a)))
    min_off = float(np.min(off_times)) if off_times else 0.0
    min_off_n = round(min_off / step)
    tol = HIT_TOLERANCE_S / step

    def score(trigger: float, steady: float, delay: float) -> float:
        delay_n = round(delay / step)
        hits = 0
        for d, ch, actual in periods:
            pred = _replay(d, ch, trigger, steady, delay_n, min_off_n)
            if pred is not None and abs(pred - actual) <= tol:
                hits += 1
        return hits / max(len(periods), 1)

    documented = sum(
        1
        for d, _, actual in periods
        if (h := np.flatnonzero(d <= -4.0)).size and abs(h[0] - actual) <= tol
    ) / max(len(periods), 1)
    best = (-1.0, 0.0, 0.0, 0.0)
    for trigger, steady, delay in itertools.product(
        TRIGGER_MARGINS, STEADY_MARGINS, STEADY_DELAYS_S
    ):
        if steady == STEADY_MARGINS[-1] and delay > 0:
            continue
        rate = score(trigger, steady, delay)
        if rate > best[0]:
            best = (rate, trigger, steady, delay)
    return StartRuleFit(best[1], best[2], best[3], min_off, best[0], documented)


def analyse_switching(
    sig: BaseSignals, step: float = BASE_STEP_S, *, fit: bool = True
) -> SwitchingReport:
    """Measure how well the documented rule explains the recorded switching.

    Parameters
    ----------
    sig
        Base-grid signals.
    step
        Base step in seconds.
    fit
        Also grid-search the start rule (a few seconds).

    Returns
    -------
    SwitchingReport
        Stop-rule verification, start statistics and the fitted start rule.
    """
    run = sig.running
    all_starts, _ = _edges(run)
    starts, stops = heating_switches(sig, step)
    over = (sig.outlet - sig.target) >= 2.0
    holds = np.array([_hold_before(over, int(s), run) * step for s in stops])
    o_rise, o_fall = _edges(over & run)
    o_fall = o_fall[o_fall > (o_rise[0] if o_rise.size else 0)]
    m = min(o_rise.size, o_fall.size)
    lengths = (o_fall[:m] - o_rise[:m]) * step
    ended_stop = ~run[o_fall[:m]]
    overshoot_without_stop = int(np.sum((lengths >= 185.0) & ~ended_stop))

    changed = np.r_[False, sig.target[1:] != sig.target[:-1]]
    since_change = time_since(changed, step)
    margin = sig.inlet - sig.target
    start_doc = float(np.mean(margin[starts - 1] <= -4.0)) if starts.size else float("nan")
    after_change = float(np.mean(since_change[starts - 1] <= 60.0)) if starts.size else float("nan")
    start_next = np.zeros(run.size, dtype=np.bool_)
    window = round(30.0 / step)
    for s in all_starts:
        start_next[max(0, s - window) : s] = True
    idle = ~run & (time_since(sig.defrost, step) > 600.0)
    p_change: dict[float, float] = {}
    p_steady: dict[float, float] = {}
    for level in np.arange(-6.0, -2.49, 0.25):
        at = idle & (np.abs(margin - level) < 0.01)
        recent = at & (since_change < 30.0)
        steady = at & (since_change >= 120.0)
        if recent.sum() >= 20:
            p_change[float(level)] = float(start_next[recent].mean())
        if steady.sum() >= 200:
            p_steady[float(level)] = float(start_next[steady].mean())

    runs = []
    for s in starts:
        nxt = stops[stops > s]
        if nxt.size:
            runs.append((nxt[0] - s) * step / 60.0)
    runs_a = np.asarray(runs)
    days = (sig.t[-1] - sig.t[0]) / 86400.0 if sig.t.size else 0.0
    d_rises, _ = _edges(sig.defrost)
    return SwitchingReport(
        days=float(days),
        starts=int(all_starts.size),
        heating_starts=int(starts.size),
        defrosts=int(d_rises.size),
        stop_rule_share=float(np.mean(holds >= 170.0)) if holds.size else float("nan"),
        stop_hold_median_s=float(np.median(holds)) if holds.size else float("nan"),
        overshoot_without_stop=overshoot_without_stop,
        start_doc_share=start_doc,
        start_after_change_share=after_change,
        p_start_after_change=p_change,
        p_start_steady=p_steady,
        run_minutes_median=float(np.median(runs_a)) if runs_a.size else float("nan"),
        short_run_share=float(np.mean(runs_a < 20.0)) if runs_a.size else float("nan"),
        start_fit=fit_start_rule(sig, starts, stops, step) if fit else None,
        start_phase=fit_start_phase(sig, starts, step),
    )


@dataclass(frozen=True, slots=True)
class StartPhaseFit:
    """The pump's fixed-frequency start phase, measured on the base grid.

    Parameters
    ----------
    hz
        Median plateau frequency after a heating start.
    duration_s
        Median time from the start until the frequency leaves the plateau.
    starts
        Starts measured (running for the whole window).
    """

    hz: float
    duration_s: float
    starts: int


START_WINDOW_S = 1200.0
PLATEAU_FROM_S = 60.0
PLATEAU_TO_S = 150.0
PLATEAU_TOLERANCE_HZ = 1.0


def fit_start_phase(
    sig: BaseSignals, starts: np.ndarray, step: float = BASE_STEP_S
) -> StartPhaseFit:
    """Measure the plateau the compressor holds after a heating start.

    For every heating start that keeps running for :data:`START_WINDOW_S` the plateau is
    the median frequency between :data:`PLATEAU_FROM_S` and :data:`PLATEAU_TO_S` after
    the start; the phase ends at the first sample after :data:`PLATEAU_FROM_S` that
    differs from the plateau by more than :data:`PLATEAU_TOLERANCE_HZ`.

    Parameters
    ----------
    sig
        Base-grid signals.
    starts
        Heating start indices.
    step
        Base step in seconds.

    Returns
    -------
    StartPhaseFit
        Median plateau and duration (``NaN`` without usable starts).
    """
    hz = np.nan_to_num(sig.hz)
    window = round(START_WINDOW_S / step)
    a, b = round(PLATEAU_FROM_S / step), round(PLATEAU_TO_S / step)
    plateaus: list[float] = []
    durations: list[float] = []
    for s in starts:
        seg = hz[int(s) : int(s) + window]
        if seg.size < window or (seg <= 0).any():
            continue
        plateau = float(np.median(seg[a:b]))
        away = np.flatnonzero(np.abs(seg[a:] - plateau) > PLATEAU_TOLERANCE_HZ)
        if not away.size:
            continue
        plateaus.append(plateau)
        durations.append(float((a + away[0]) * step))
    if not plateaus:
        return StartPhaseFit(float("nan"), float("nan"), 0)
    return StartPhaseFit(float(np.median(plateaus)), float(np.median(durations)), len(plateaus))

"""Energy signature: apparent heat-loss coefficient, balance temperature, time constant.

Daily means over local calendar days are regressed with a change-point model::

    Q = max(0, H (T_in - T_o) - A I - G + C dT_in/dt)

``Q`` is the mean heat into the loop (flow x spread, defrost draw included, as it is
heat the house gave back), ``T_in`` the indoor mean, ``T_o`` the outside mean, ``I``
mean global irradiance and ``dT_in/dt`` the indoor change over the day (storage
correction). ``H`` is the *apparent* heat-loss coefficient: with a handful of indoor
sensors it describes the house as those sensors see it. Intervals come from a
day bootstrap.

The signature's own credibility is data sufficiency for the regression: at least 30
heating days spanning at least 10 K of outside temperature. Days below 5 degC are
counted and reported but no longer required: the slope is identified by the spread of
the outside temperature, not by its absolute level, and the learner's model
credibility (:mod:`ovenbird_sim.learn.checks`) asks instead for a tight RC heat-loss
coefficient that agrees with this signature. A capacity check at the design
temperature is shown only when the data reach within 10 K of it, and the result is
flagged low-confidence when it differs from the RC model's envelope conductance by
more than 20 %.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import least_squares

from ovenbird_sim.data.dataset import Dataset

MIN_DAY_COVERAGE = 0.98
HEATING_DAY_W = 300.0
CREDIBLE_DAYS = 30
CREDIBLE_SPAN_K = 10.0
COLD_DAY_C = 5.0
DESIGN_WINDOW_K = 10.0
RC_DISAGREEMENT = 0.2


@dataclass(frozen=True, slots=True)
class DailyData:
    """Daily means over local days.

    Parameters
    ----------
    day_start
        Local-midnight start of each day (unix s).
    heat_w, indoor_c, outside_c, ghi_w_m2, d_indoor_k
        Mean heat, indoor, outside, irradiance, and indoor change over the day.
    """

    day_start: NDArray[np.float64]
    heat_w: NDArray[np.float64]
    indoor_c: NDArray[np.float64]
    outside_c: NDArray[np.float64]
    ghi_w_m2: NDArray[np.float64]
    d_indoor_k: NDArray[np.float64]

    @property
    def n(self) -> int:
        """Number of days."""
        return int(self.day_start.size)

    def take(self, idx: NDArray[np.intp]) -> DailyData:
        """Days at ``idx``."""
        return DailyData(
            self.day_start[idx],
            self.heat_w[idx],
            self.indoor_c[idx],
            self.outside_c[idx],
            self.ghi_w_m2[idx],
            self.d_indoor_k[idx],
        )


def daily(ds: Dataset, indoor: str = "house_mean") -> DailyData:
    """Aggregate a dataset into complete local days.

    Parameters
    ----------
    ds
        Dataset (any step dividing a day).
    indoor
        Indoor column (``house_mean``, ``room_living`` or ``room``).

    Returns
    -------
    DailyData
        Days with at least 98 % valid heat, indoor and outside bins.
    """
    c, f = ds.columns, ds.flags
    hour = c["local_hour"]
    midnight = np.flatnonzero(np.r_[False, np.diff(hour) < -12.0])
    rows = []
    for a, b in itertools.pairwise(int(i) for i in midnight):
        heat = c["heat_w"][a:b]
        t_in = c[indoor][a:b] if indoor in c else np.full(b - a, np.nan)
        t_o = c["outside"][a:b]
        valid = np.isfinite(heat) & np.isfinite(t_in) & np.isfinite(t_o) & ~f["gap"][a:b]
        if valid.mean() < MIN_DAY_COVERAGE:
            continue
        ghi = np.nan_to_num(c.get("ghi", np.zeros(ds.grid.n))[a:b])
        edge = max((b - a) // 24, 1)
        change = float(np.nanmean(t_in[-edge:]) - np.nanmean(t_in[:edge]))
        rows.append(
            (
                float(ds.t[a]),
                float(np.nanmean(heat)),
                float(np.nanmean(t_in)),
                float(np.nanmean(t_o)),
                float(np.mean(ghi)),
                change,
            )
        )
    arr = np.array(rows, dtype=np.float64).reshape(-1, 6)
    return DailyData(*(arr[:, k].copy() for k in range(6)))


def _predict(theta: NDArray[np.float64], d: DailyData) -> NDArray[np.float64]:
    h, a, g, cap = theta
    raw = h * (d.indoor_c - d.outside_c) - a * d.ghi_w_m2 - g + cap * d.d_indoor_k / 86400.0
    return np.asarray(np.maximum(raw, 0.0), dtype=np.float64)


def fit_signature(d: DailyData) -> NDArray[np.float64]:
    """Least-squares change-point fit; returns ``(H, A, G, C)``."""

    def residual(theta: NDArray[np.float64]) -> NDArray[np.float64]:
        return _predict(theta, d) - d.heat_w

    x0 = np.array([250.0, 5.0, 0.0, 3.0e7])
    lo = np.array([0.0, 0.0, -5000.0, 0.0])
    hi = np.array([3000.0, 100.0, 5000.0, 1.0e9])
    scale = np.array([100.0, 5.0, 300.0, 1.0e7])
    result = least_squares(residual, x0, bounds=(lo, hi), x_scale=scale)
    return np.asarray(result.x, dtype=np.float64)


@dataclass(frozen=True, slots=True)
class Signature:
    """Energy-signature result.

    Parameters
    ----------
    indoor
        Indoor column used.
    days, heating_days, cold_days
        Usable days, days with heating, days below 5 degC.
    outside_span_k
        Range of daily outside means over heating days.
    h_w_per_k, h_interval
        Apparent heat-loss coefficient and its 90 % interval.
    solar_m2, solar_interval
        Irradiance coefficient (effective aperture) and interval.
    gains_w
        Constant offset ``G`` (internal gains minus unmodelled losses).
    storage_j_per_k
        Fitted storage term ``C``.
    balance_c, balance_interval
        Outside temperature with zero heat at mean indoor and mean irradiance.
    time_constant_h
        ``C / H`` when the storage term is resolved, else ``NaN``.
    rmse_w
        Residual of the daily fit.
    credible
        Whether the signature has enough data: heating days and outside span.
    reasons
        Why it is not credible or low-confidence.
    capacity_at_design_w
        Heat needed at the design temperature, when within reach of the data.
    rc_h_w_per_k
        The RC model's envelope conductance used for the cross-check.
    low_confidence
        Signature and RC disagree by more than 20 %.
    """

    indoor: str
    days: int
    heating_days: int
    cold_days: int
    outside_span_k: float
    h_w_per_k: float
    h_interval: tuple[float, float]
    solar_m2: float
    solar_interval: tuple[float, float]
    gains_w: float
    storage_j_per_k: float
    balance_c: float
    balance_interval: tuple[float, float]
    time_constant_h: float
    rmse_w: float
    credible: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)
    capacity_at_design_w: float | None = None
    rc_h_w_per_k: float | None = None
    low_confidence: bool = False

    def lines(self) -> list[str]:
        """Human-readable report."""
        verdict = "credible" if self.credible else "NOT credible"
        if self.low_confidence:
            verdict += ", low confidence"
        out = [
            f"indoor signal: {self.indoor}; {self.days} days, {self.heating_days} heating, "
            f"{self.cold_days} below {COLD_DAY_C:.0f} degC, "
            f"outside span {self.outside_span_k:.1f} K",
            f"apparent heat-loss coefficient H = {self.h_w_per_k:.0f} W/K "
            f"[{self.h_interval[0]:.0f} .. {self.h_interval[1]:.0f}] (90 %)",
            f"solar coefficient {self.solar_m2:.1f} m2 [{self.solar_interval[0]:.1f} .. "
            f"{self.solar_interval[1]:.1f}], offset G {self.gains_w:.0f} W, "
            f"daily rmse {self.rmse_w:.0f} W",
            f"balance temperature {self.balance_c:.1f} degC [{self.balance_interval[0]:.1f} .. "
            f"{self.balance_interval[1]:.1f}]",
            f"time constant {self.time_constant_h:.0f} h"
            if math.isfinite(self.time_constant_h)
            else "time constant: not resolved by the daily data (see RC model)",
            f"verdict: {verdict}" + (f" - {'; '.join(self.reasons)}" if self.reasons else ""),
        ]
        if self.rc_h_w_per_k is not None:
            out.append(f"RC model envelope conductance {self.rc_h_w_per_k:.0f} W/K")
        out.append(
            f"capacity at design temperature: {self.capacity_at_design_w:.0f} W"
            if self.capacity_at_design_w is not None
            else "capacity at design temperature: hidden (data not within 10 K of it)"
        )
        return out


def _balance(theta: NDArray[np.float64], d: DailyData) -> float:
    h, a, g, _ = theta
    if h <= 0:
        return math.nan
    return float(np.mean(d.indoor_c) - (g + a * np.mean(d.ghi_w_m2)) / h)


def energy_signature(
    d: DailyData,
    *,
    indoor: str = "house_mean",
    rc_h_w_per_k: float | None = None,
    design_c: float = -10.0,
    replicates: int = 500,
    seed: int = 0,
) -> Signature:
    """Fit the signature with day-bootstrap intervals and apply the credibility rules.

    Parameters
    ----------
    d
        Daily data.
    indoor
        Name of the indoor signal (for the report).
    rc_h_w_per_k
        Envelope conductance of the RC model, for the cross-check.
    design_c
        Design outside temperature.
    replicates
        Bootstrap replicates.
    seed
        Random seed.

    Returns
    -------
    Signature
        The result.

    Raises
    ------
    ValueError
        With fewer than 5 usable days.
    """
    if d.n < 5:
        raise ValueError("need at least 5 usable days")
    theta = fit_signature(d)
    rng = np.random.default_rng(seed)
    boots = np.array([fit_signature(d.take(rng.integers(0, d.n, d.n))) for _ in range(replicates)])
    balances = np.array([_balance(b, d) for b in boots])
    heating = d.heat_w > HEATING_DAY_W
    span = float(np.ptp(d.outside_c[heating])) if heating.any() else 0.0
    cold = int(np.sum(heating & (d.outside_c < COLD_DAY_C)))
    reasons = []
    if heating.sum() < CREDIBLE_DAYS:
        reasons.append(f"{int(heating.sum())} heating days < {CREDIBLE_DAYS}")
    if span < CREDIBLE_SPAN_K:
        reasons.append(f"outside span {span:.1f} K < {CREDIBLE_SPAN_K:.0f} K")
    h = float(theta[0])
    low = False
    if (
        rc_h_w_per_k is not None
        and rc_h_w_per_k > 0
        and abs(h - rc_h_w_per_k) / rc_h_w_per_k > RC_DISAGREEMENT
    ):
        low = True
        reasons.append(f"signature and RC differ by {abs(h - rc_h_w_per_k) / rc_h_w_per_k:.0%}")
    cap_c = float(theta[3])
    storage_resolved = bool(np.percentile(boots[:, 3], 5) > 0.2 * cap_c) and cap_c > 0
    capacity = None
    if np.min(d.outside_c) <= design_c + DESIGN_WINDOW_K:
        capacity = h * (float(np.mean(d.indoor_c)) - design_c) - float(theta[2])
    rmse = float(np.sqrt(np.mean((_predict(theta, d) - d.heat_w) ** 2)))
    return Signature(
        indoor=indoor,
        days=d.n,
        heating_days=int(heating.sum()),
        cold_days=cold,
        outside_span_k=span,
        h_w_per_k=h,
        h_interval=(float(np.percentile(boots[:, 0], 5)), float(np.percentile(boots[:, 0], 95))),
        solar_m2=float(theta[1]),
        solar_interval=(
            float(np.percentile(boots[:, 1], 5)),
            float(np.percentile(boots[:, 1], 95)),
        ),
        gains_w=float(theta[2]),
        storage_j_per_k=cap_c,
        balance_c=_balance(theta, d),
        balance_interval=(
            float(np.nanpercentile(balances, 5)),
            float(np.nanpercentile(balances, 95)),
        ),
        time_constant_h=cap_c / h / 3600.0 if storage_resolved and h > 0 else math.nan,
        rmse_w=rmse,
        credible=not any(r for r in reasons if "differ" not in r),
        reasons=tuple(reasons),
        capacity_at_design_w=capacity,
        rc_h_w_per_k=rc_h_w_per_k,
        low_confidence=low,
    )

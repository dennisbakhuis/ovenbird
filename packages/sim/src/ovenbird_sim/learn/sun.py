"""Whether the model's response to the sun holds on held-out days (the sun gate's numbers).

Three numbers on a held-out block, all from the Kalman-filtered state of the model
(:func:`ovenbird_sim.identify.validate.filtered`), with the measured heat, outside
temperature and irradiance as inputs:

Sunny days
    Local days (from the dataset's ``local_hour``) with at least 80 % of their bins in
    the block and the room known on at least 80 % of them (event days are masked in
    the scoring view, so they drop out), on which global horizontal irradiance exceeds
    :data:`SUNNY_GHI_WM2` for at least :data:`SUNNY_HOURS` hours. 150 W/m2 is direct
    sun on a clear autumn or winter day, not a bright overcast sky; three hours of it
    happen on a clear day even near midwinter.
Ablation skill
    The room error pooled over the first :data:`ABLATION_HORIZON_H` hours from origins
    every 3 h, counted only at targets with irradiance above :data:`SUNNY_GHI_WM2`,
    of the model against the same model with the solar aperture at 0 (with its own
    filtered state): ``1 - model / no sun``. Positive when the sun term helps.
Sun-response slope (beta)
    From an origin at 09:00 local on every held-out day, the model runs
    :data:`RESPONSE_HOURS` hours; its sun part is the response to the irradiance
    alone from a zero state (the model is linear). ``beta`` regresses the measured
    change of the room minus the model's change without the sun on that sun part,
    through the origin: 1 when the model's sun response is right in size, 0.5 when it
    is twice too strong. Its 90 % interval comes from resampling the days (one origin
    per day, so a day is a block) :data:`BETA_REPLICATES` times.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

from ovenbird_sim.data.dataset import Dataset
from ovenbird_sim.identify.building import observations
from ovenbird_sim.identify.validate import filtered, inputs
from ovenbird_sim.model.building import BuildingParams, simulate_batch

SUNNY_GHI_WM2: Final = 150.0
SUNNY_HOURS: Final = 3.0
DAY_COVERAGE: Final = 0.8
ABLATION_HORIZON_H: Final = 6.0
ORIGIN_EVERY_H: Final = 3.0
RESPONSE_ORIGIN_HOUR: Final = 9.0
RESPONSE_HOURS: Final = 8.0
BETA_REPLICATES: Final = 1000
BETA_LEVEL: Final = 0.9


@dataclass(frozen=True, slots=True)
class SunCheck:
    """The sun numbers of a model on a held-out block.

    Parameters
    ----------
    days
        Local days in the block (at least 80 % of their bins inside).
    sunny_days
        Of those, the sunny ones with the room known.
    ablation_skill
        ``1 - model / no sun`` on sunny targets (``NaN`` without any).
    beta
        Sun-response slope (``NaN`` when the model has no sun response or no origin).
    beta_interval
        Its 90 % day-block bootstrap interval (``None`` with fewer than two origins).
    origins
        Days with a 09:00 origin.
    """

    days: int
    sunny_days: int
    ablation_skill: float
    beta: float
    beta_interval: tuple[float, float] | None
    origins: int


class SunEvaluator:
    """Evaluate one model's sun response on spans of a dataset (filtered states kept).

    Parameters
    ----------
    ds
        Scoring view (5 min, room masked inside events).
    p
        The model.
    seed
        Seed of the bootstrap.
    """

    def __init__(self, ds: Dataset, p: BuildingParams, seed: int = 0) -> None:
        self.ds = ds
        self.p = p
        self.seed = seed
        self._states: NDArray[np.float64] | None = None
        self._states_dark: NDArray[np.float64] | None = None

    @property
    def states(self) -> NDArray[np.float64]:
        """Filtered states of the model."""
        if self._states is None:
            self._states = filtered(self.ds, self.p)
        return self._states

    @property
    def states_dark(self) -> NDArray[np.float64]:
        """Filtered states of the model with the solar aperture at 0."""
        if self._states_dark is None:
            self._states_dark = filtered(self.ds, self.p.replace(solar_aperture_m2=0.0))
        return self._states_dark

    def check(self, start: float, end: float) -> SunCheck:
        """Return the sun numbers on ``[start, end)``."""
        t = self.ds.t
        i0 = int(np.searchsorted(t, start))
        i1 = int(np.searchsorted(t, end))
        days, sunny = sunny_days(self.ds, i0, i1)
        ablation = self._ablation(i0, i1)
        beta, interval, origins = self._response(i0, i1)
        return SunCheck(days, sunny, ablation, beta, interval, origins)

    def _ablation(self, i0: int, i1: int) -> float:
        if self.p.solar_aperture_m2 <= 0.0:
            return math.nan
        ds = self.ds
        step = ds.grid.step
        _, room = observations(ds)
        ghi = np.nan_to_num(ds.col("ghi"))
        n = round(ABLATION_HORIZON_H * 3600.0 / step)
        stride = max(round(ORIGIN_EVERY_H * 3600.0 / step), 1)
        origins = np.arange(i0, max(i1 - n - 1, i0), stride)
        origins = origins[np.isfinite(room[origins])]
        if origins.size == 0:
            return math.nan
        idx = origins[:, None] + np.arange(n)[None, :]
        target = idx + 1
        sunny = ghi[target] > SUNNY_GHI_WM2
        dark = self.p.replace(solar_aperture_m2=0.0)
        errors = []
        for params, states in ((self.p, self.states), (dark, self.states_dark)):
            sim = simulate_batch(params, step, states[origins], inputs(ds, params)[idx])[:, 1:, 2]
            e = np.where(sunny, sim - room[target], np.nan)
            ok = np.isfinite(e)
            errors.append(float(np.sqrt(np.mean(e[ok] ** 2))) if ok.any() else math.nan)
        model, reference = errors
        if not (math.isfinite(model) and math.isfinite(reference)) or reference <= 0.0:
            return math.nan
        return 1.0 - model / reference

    def _response(self, i0: int, i1: int) -> tuple[float, tuple[float, float] | None, int]:
        ds = self.ds
        step = ds.grid.step
        _, room = observations(ds)
        hour = ds.col("local_hour")
        n = round(RESPONSE_HOURS * 3600.0 / step)
        near = np.abs(hour - RESPONSE_ORIGIN_HOUR) < 0.5 * step / 3600.0
        candidates = np.flatnonzero(near[i0 : max(i1 - n - 1, i0)]) + i0
        origins = candidates[np.isfinite(room[candidates])]
        if origins.size == 0 or self.p.solar_aperture_m2 <= 0.0:
            return math.nan, None, int(origins.size)
        idx = origins[:, None] + np.arange(n)[None, :]
        u = inputs(ds, self.p)[idx]
        states = self.states[origins]
        full = simulate_batch(self.p, step, states, u)[:, 1:, 2]
        sun_only = np.zeros_like(u)
        sun_only[..., 2] = u[..., 2]
        sun = simulate_batch(self.p, step, np.zeros_like(states), sun_only)[:, 1:, 2]
        measured = room[idx + 1] - room[origins][:, None]
        without_sun = full - sun - states[:, 2][:, None]
        y = measured - without_sun
        beta = _slope(sun, y)
        if not math.isfinite(beta) or origins.size < 2:
            return beta, None, int(origins.size)
        rng = np.random.default_rng(self.seed)
        draws = rng.integers(0, origins.size, (BETA_REPLICATES, origins.size))
        slopes = np.array([_slope(sun[d], y[d]) for d in draws])
        slopes = slopes[np.isfinite(slopes)]
        if slopes.size == 0:
            return beta, None, int(origins.size)
        tail = (1.0 - BETA_LEVEL) / 2.0 * 100.0
        lo, hi = np.percentile(slopes, [tail, 100.0 - tail])
        return beta, (float(lo), float(hi)), int(origins.size)


def _slope(x: NDArray[np.float64], y: NDArray[np.float64]) -> float:
    ok = np.isfinite(y) & np.isfinite(x)
    denominator = float(np.sum(x[ok] ** 2))
    if denominator <= 1e-12:
        return math.nan
    return float(np.sum(x[ok] * y[ok])) / denominator


def sunny_days(ds: Dataset, i0: int, i1: int) -> tuple[int, int]:
    """Return the local days in bins ``[i0, i1)`` and how many of them are sunny.

    Days are cut at local midnight (``local_hour`` wrapping); a day counts when at
    least 80 % of its bins lie in the span, and is sunny when the room is known on at
    least 80 % of them and irradiance exceeds :data:`SUNNY_GHI_WM2` for at least
    :data:`SUNNY_HOURS` hours.
    """
    hour = ds.col("local_hour")
    step = ds.grid.step
    per_day = round(86400.0 / step)
    _, room = observations(ds)
    ghi = np.nan_to_num(ds.col("ghi"))
    starts = np.flatnonzero(np.r_[True, np.diff(hour) < -12.0])
    bounds = np.r_[starts, hour.size]
    days = sunny = 0
    for a, b in itertools.pairwise(bounds):
        lo, hi = max(int(a), i0), min(int(b), i1)
        if hi - lo < DAY_COVERAGE * per_day:
            continue
        days += 1
        if np.isfinite(room[lo:hi]).mean() < DAY_COVERAGE:
            continue
        if np.sum(ghi[lo:hi] > SUNNY_GHI_WM2) * step / 3600.0 >= SUNNY_HOURS:
            sunny += 1
    return days, sunny

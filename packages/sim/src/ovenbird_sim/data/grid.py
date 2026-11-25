"""Resampling irregular series onto a regular time grid.

Two grids are used. The *base grid* has a 5 s step (HeishaMon's query cadence) and
samples every signal by zero-order hold at the middle of each base interval; products
such as flow x spread are formed there. The *output grid* (60 s or 300 s) averages
the base samples of each bin, so a bin value is the time-weighted mean of the
held signal and a quantised signal (integer outside temperature) gains sub-step
resolution by dithering. A held sample older than its ``max_age`` is treated as
missing (``NaN``), which is how staleness enters every downstream number.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ovenbird_sim.data.series import BoolArray, FloatArray, Series

BASE_STEP_S = 5.0


@dataclass(frozen=True, slots=True)
class TimeGrid:
    """A regular grid of ``n`` bins ``[start + i*step, start + (i+1)*step)``.

    Parameters
    ----------
    start
        Start of the first bin in unix seconds.
    step
        Bin width in seconds.
    n
        Number of bins.
    """

    start: float
    step: float
    n: int

    def __post_init__(self) -> None:
        """Validate the grid."""
        if self.step <= 0 or self.n < 0:
            raise ValueError("step must be positive and n non-negative")

    @property
    def edges(self) -> FloatArray:
        """Bin start times."""
        return self.start + self.step * np.arange(self.n, dtype=np.float64)

    @property
    def mids(self) -> FloatArray:
        """Bin middle times."""
        return self.edges + 0.5 * self.step

    @property
    def end(self) -> float:
        """End of the last bin."""
        return self.start + self.step * self.n

    def refine(self, step: float) -> TimeGrid:
        """Return a finer grid over the same span (``self.step`` must be a multiple)."""
        factor = self.step / step
        if abs(factor - round(factor)) > 1e-9 or factor < 1:
            raise ValueError("the grid step must be an integer multiple of the finer step")
        return TimeGrid(self.start, step, self.n * round(factor))

    @classmethod
    def covering(cls, t0: float, t1: float, step: float) -> TimeGrid:
        """Return the grid aligned to multiples of ``step`` covering ``[t0, t1)``."""
        start = float(np.floor(t0 / step) * step)
        n = int(np.ceil((t1 - start) / step))
        return cls(start, step, max(n, 0))


def hold(
    series: Series, times: FloatArray, max_age: float = np.inf
) -> tuple[FloatArray, FloatArray]:
    """Sample a series by zero-order hold.

    Parameters
    ----------
    series
        Irregular samples.
    times
        Query times.
    max_age
        Held values older than this (seconds) become ``NaN``.

    Returns
    -------
    values, ages
        Held value and its age at each query time; ``NaN`` (value) and ``inf`` (age)
        before the first sample.
    """
    idx = np.searchsorted(series.t, times, side="right") - 1
    valid = idx >= 0
    safe = np.clip(idx, 0, max(series.t.size - 1, 0))
    if series.t.size == 0:
        return np.full(times.shape, np.nan), np.full(times.shape, np.inf)
    values = np.where(valid, series.v[safe], np.nan)
    ages = np.where(valid, times - series.t[safe], np.inf)
    values = np.where(ages <= max_age, values, np.nan)
    return values, ages


def interpolate(series: Series, times: FloatArray, max_gap: float = np.inf) -> FloatArray:
    """Linearly interpolate a series; ``NaN`` outside its span or across long gaps.

    Parameters
    ----------
    series
        Irregular samples (``NaN`` samples are skipped).
    times
        Query times.
    max_gap
        Interpolation across sample gaps longer than this (seconds) yields ``NaN``.

    Returns
    -------
    FloatArray
        Interpolated values.
    """
    ok = np.isfinite(series.v)
    t, v = series.t[ok], series.v[ok]
    if t.size == 0:
        return np.full(times.shape, np.nan)
    out = np.interp(times, t, v, left=np.nan, right=np.nan)
    if np.isfinite(max_gap) and t.size > 1:
        idx = np.clip(np.searchsorted(t, times, side="right"), 1, t.size - 1)
        span = t[idx] - t[idx - 1]
        out = np.where(span <= max_gap, out, np.nan)
    return out


def bin_mean(base: FloatArray, factor: int) -> FloatArray:
    """Average consecutive groups of ``factor`` base samples, ignoring ``NaN``.

    A bin is ``NaN`` when more than half of its base samples are ``NaN``.

    Parameters
    ----------
    base
        Base-grid samples; length a multiple of ``factor``.
    factor
        Base samples per output bin.

    Returns
    -------
    FloatArray
        Per-bin means.
    """
    blocks = base.reshape(-1, factor)
    finite = np.isfinite(blocks)
    count = finite.sum(axis=1)
    total = np.where(finite, blocks, 0.0).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = total / count
    return np.where(count * 2 >= factor, mean, np.nan)


def bin_any(base: BoolArray, factor: int) -> BoolArray:
    """Whether any base sample in each bin is true."""
    return np.asarray(base.reshape(-1, factor).any(axis=1), dtype=np.bool_)


def bin_fraction(base: BoolArray, factor: int) -> FloatArray:
    """Fraction of true base samples in each bin."""
    return np.asarray(base.reshape(-1, factor).mean(axis=1), dtype=np.float64)


def bin_last(base: FloatArray, factor: int) -> FloatArray:
    """Last base sample of each bin."""
    return np.asarray(base.reshape(-1, factor)[:, -1], dtype=np.float64)


def time_since(flag: BoolArray, step: float) -> FloatArray:
    """Seconds since ``flag`` was last true at each sample (0 where true, inf before any).

    Parameters
    ----------
    flag
        Boolean samples on a regular grid.
    step
        Grid step in seconds.

    Returns
    -------
    FloatArray
        Elapsed time since the most recent true sample.
    """
    idx = np.arange(flag.size)
    last = np.where(flag, idx, -1)
    last = np.maximum.accumulate(last)
    out = (idx - last) * step
    return np.where(last >= 0, out.astype(np.float64), np.inf)

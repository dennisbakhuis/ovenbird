"""Irregular time series: the common currency between loaders and the time grid."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

type FloatArray = NDArray[np.float64]
type BoolArray = NDArray[np.bool_]


@dataclass(frozen=True, slots=True)
class Series:
    """Samples of one signal at irregular times, sorted by time.

    Parameters
    ----------
    t
        Sample times in unix seconds, non-decreasing.
    v
        Sample values; a value holds until the next sample (zero-order hold).
    """

    t: FloatArray
    v: FloatArray

    def __post_init__(self) -> None:
        """Validate shapes and ordering."""
        if self.t.shape != self.v.shape or self.t.ndim != 1:
            raise ValueError("t and v must be one-dimensional arrays of equal length")
        if self.t.size > 1 and bool(np.any(np.diff(self.t) < 0)):
            raise ValueError("sample times must be sorted")

    def __len__(self) -> int:
        """Return the number of samples."""
        return int(self.t.size)

    @classmethod
    def empty(cls) -> Series:
        """Return a series without samples."""
        return cls(np.empty(0), np.empty(0))

    @classmethod
    def from_pairs(cls, t: Iterable[float], v: Iterable[float]) -> Series:
        """Build a series from unsorted times and values (stable sort by time)."""
        ta = np.asarray(list(t), dtype=np.float64)
        va = np.asarray(list(v), dtype=np.float64)
        order = np.argsort(ta, kind="stable")
        return cls(ta[order], va[order])

    def window(self, start: float, end: float) -> Series:
        """Return the samples with ``start <= t < end``."""
        lo, hi = np.searchsorted(self.t, [start, end], side="left")
        return Series(self.t[lo:hi], self.v[lo:hi])


def concat(parts: Iterable[Series]) -> Series:
    """Concatenate series and sort the result by time.

    Parameters
    ----------
    parts
        Series to join; may overlap in time.

    Returns
    -------
    Series
        The merged series.
    """
    items = [p for p in parts if len(p)]
    if not items:
        return Series.empty()
    t = np.concatenate([p.t for p in items])
    v = np.concatenate([p.v for p in items])
    order = np.argsort(t, kind="stable")
    return Series(t[order], v[order])


def merge_maps(maps: Iterable[Mapping[str, Series]]) -> dict[str, Series]:
    """Merge several signal maps, concatenating series with the same key."""
    buckets: dict[str, list[Series]] = {}
    for mapping in maps:
        for key, series in mapping.items():
            buckets.setdefault(key, []).append(series)
    return {key: concat(parts) for key, parts in buckets.items()}

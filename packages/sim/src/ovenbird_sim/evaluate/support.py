"""Joint support of the COP map: which operating points its fitting data covers.

The COP map (:mod:`ovenbird_sim.model.heatpump`) is a smooth log-linear form in the
outside temperature, the outlet temperature and the compressor frequency, fitted on
the recorded running bins (:func:`ovenbird_sim.identify.heatpump.cop_bins`). Each axis
on its own can be inside the recorded range while the combination is not (a low
outlet at a high frequency in cold weather, say); there the map extrapolates. The
support is a 3-D histogram of the fitting bins; a simulated heating tick is supported
when its cell holds at least :data:`MIN_MINUTES` minutes of fitting data. The
heat-weighted share of unsupported ticks is reported per run, and electricity and COP
differences are refused when either controller exceeds :data:`UNSUPPORTED_TOLERANCE`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

from ovenbird_sim.data.dataset import Dataset
from ovenbird_sim.data.series import FloatArray
from ovenbird_sim.identify.heatpump import cop_bins

OUTSIDE_STEP_K: Final = 2.0
OUTLET_STEP_K: Final = 2.0
HZ_STEP: Final = 5.0
MIN_MINUTES: Final = 30.0
UNSUPPORTED_TOLERANCE: Final = 0.05


@dataclass(frozen=True, slots=True)
class CopSupport:
    """Minutes of COP fitting data per (outside, outlet, frequency) cell.

    Parameters
    ----------
    origin
        Lower corner of the grid (outside, outlet, Hz).
    steps
        Cell size per axis.
    minutes
        Fitting minutes per cell.
    """

    origin: tuple[float, float, float]
    steps: tuple[float, float, float]
    minutes: NDArray[np.float64]

    def cell_minutes(self, outside: FloatArray, outlet: FloatArray, hz: FloatArray) -> FloatArray:
        """Fitting minutes of the cell of every point (0 outside the grid)."""
        idx = [
            np.floor((v - o) / s).astype(np.int64)
            for v, o, s in zip((outside, outlet, hz), self.origin, self.steps, strict=True)
        ]
        inside = np.ones(outside.shape, dtype=np.bool_)
        for axis, i in enumerate(idx):
            inside &= (i >= 0) & (i < self.minutes.shape[axis])
        out = np.zeros(outside.shape)
        out[inside] = self.minutes[idx[0][inside], idx[1][inside], idx[2][inside]]
        return out

    def unsupported_share(
        self, outside: FloatArray, outlet: FloatArray, hz: FloatArray, heat_w: FloatArray
    ) -> float:
        """Heat-weighted share of heating ticks in cells with too little fitting data."""
        heating = (hz > 0) & (heat_w > 0) & np.isfinite(outlet)
        total = float(heat_w[heating].sum())
        if total <= 0:
            return 0.0
        minutes = self.cell_minutes(outside[heating], outlet[heating], hz[heating])
        return float(heat_w[heating][minutes < MIN_MINUTES].sum() / total)


def cop_support(ds: Dataset) -> CopSupport:
    """Build the support histogram from the bins the COP map is fitted on."""
    c = ds.columns
    sel = cop_bins(ds)
    points = np.column_stack([c["outside"][sel], c["outlet"][sel], c["hz"][sel]])
    points = points[np.isfinite(points).all(axis=1)]
    steps = (OUTSIDE_STEP_K, OUTLET_STEP_K, HZ_STEP)
    origin = tuple(float(np.floor(points[:, a].min() / s) * s) for a, s in enumerate(steps))
    idx = np.floor((points - np.array(origin)) / np.array(steps)).astype(np.int64)
    shape = tuple(int(idx[:, a].max()) + 1 for a in range(3))
    minutes = np.zeros(shape)
    np.add.at(minutes, (idx[:, 0], idx[:, 1], idx[:, 2]), ds.grid.step / 60.0)
    return CopSupport((origin[0], origin[1], origin[2]), steps, minutes)

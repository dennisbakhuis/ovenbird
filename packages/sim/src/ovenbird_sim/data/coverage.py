"""Data coverage summary of a :class:`~ovenbird_sim.data.dataset.Dataset`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from ovenbird_sim.data.dataset import Dataset

KEY_COLUMNS = (
    "outlet",
    "inlet",
    "flow",
    "hz",
    "heat_w",
    "outside_hp",
    "outside_wx",
    "outside",
    "ghi",
    "room",
    "room_living",
    "house_mean",
    "p1_w",
    "pv_inverter_w",
    "pv_meter_w",
)


@dataclass(frozen=True, slots=True)
class Coverage:
    """Coverage of a dataset.

    Parameters
    ----------
    start, end
        Span in UTC.
    days
        Span length in days.
    columns
        Share of bins with a finite value, per key column.
    first_valid
        First UTC date with a finite value, per key column.
    flags
        Share of bins with each flag set.
    gap_events
        Number of liveness gaps (recorder or board outages).
    gap_minutes
        Total gap duration.
    offset_k, offset_median_k, offset_hours
        Calibrated spread offset (mean, median) and the circulation-only hours.
    """

    start: datetime
    end: datetime
    days: float
    columns: dict[str, float]
    first_valid: dict[str, str]
    flags: dict[str, float]
    gap_events: int
    gap_minutes: float
    offset_k: float
    offset_median_k: float
    offset_hours: float

    def lines(self) -> list[str]:
        """Human-readable report lines."""
        out = [
            f"span {self.start:%Y-%m-%d %H:%M} .. {self.end:%Y-%m-%d %H:%M} UTC "
            f"({self.days:.1f} d)",
            f"liveness gaps: {self.gap_events} events, {self.gap_minutes:.0f} min",
            f"spread offset {self.offset_k:+.3f} K (mean; median {self.offset_median_k:+.2f}) "
            f"from {self.offset_hours:.0f} h circulation-only",
        ]
        out.extend(
            f"  {name:16s} {share:6.1%}  from {self.first_valid.get(name, '-')}"
            for name, share in self.columns.items()
        )
        out.append("flags: " + ", ".join(f"{k} {v:.2%}" for k, v in self.flags.items()))
        return out


def coverage(ds: Dataset) -> Coverage:
    """Summarise what a dataset holds.

    Parameters
    ----------
    ds
        The dataset.

    Returns
    -------
    Coverage
        Shares of valid bins, flags and gaps.
    """
    t = ds.t
    columns: dict[str, float] = {}
    first: dict[str, str] = {}
    for name in KEY_COLUMNS:
        if name not in ds.columns:
            columns[name] = 0.0
            continue
        finite = np.isfinite(ds.columns[name])
        columns[name] = float(finite.mean())
        if finite.any():
            first[name] = datetime.fromtimestamp(float(t[np.argmax(finite)]), UTC).strftime(
                "%Y-%m-%d"
            )
    gap = ds.flags["gap"]
    events = int(np.sum(gap[1:] & ~gap[:-1]) + int(gap[0])) if gap.size else 0
    return Coverage(
        start=datetime.fromtimestamp(ds.grid.start, UTC),
        end=datetime.fromtimestamp(ds.grid.end, UTC),
        days=ds.grid.n * ds.grid.step / 86400.0,
        columns=columns,
        first_valid=first,
        flags={k: float(v.mean()) for k, v in ds.flags.items()},
        gap_events=events,
        gap_minutes=float(gap.sum() * ds.grid.step / 60.0),
        offset_k=ds.calibration.offset_k,
        offset_median_k=ds.calibration.median_k,
        offset_hours=ds.calibration.hours,
    )

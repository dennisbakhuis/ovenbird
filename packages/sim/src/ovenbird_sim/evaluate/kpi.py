"""Outcome KPIs per UTC day and over a period of a simulated run.

Per day (sums unless noted):

``heat_kwh``
    heat delivered to the heating loop;
``elec_kwh``
    electrical input (the model's COP map plus circulation);
``starts``
    heating starts (a restart after a defrost is not a start);
``runs``, ``short_runs``
    completed runs and those shorter than :data:`SHORT_RUN_S`, by start day;
``room_minutes``, ``room_mean_c``, ``room_min_c``
    room samples, their mean and minimum;
``degree_hours_below``
    K·h of the room below the comfort band's lower edge;
``writes``
    setpoint changes applied to the pump;
``defrost_min``
    minutes in defrost.

Period totals normalise the sums per day and add ``cop`` (heat / electricity),
``short_run_share`` and ``run_median_min`` (from the run lengths kept per day); room
means are weighted by samples. :func:`aggregate_rows` aggregates any list of days,
repeats allowed, for the day-block bootstrap.

Comfort statistics (:func:`comfort`) are taken on the room temperature of occupied
hours (:data:`OCCUPIED_HOURS`, local time): mean, 10th percentile and degree-hours
below a given threshold.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

import numpy as np

from ovenbird_sim.data.series import FloatArray
from ovenbird_sim.evaluate.closedloop import Trace

SECONDS_PER_DAY: Final = 86400.0
DEFROST_GUARD_BINS: Final = 3
J_PER_KWH: Final = 3.6e6
SHORT_RUN_S: Final = 20 * 60.0
DAY_KPIS: Final = (
    "heat_kwh",
    "elec_kwh",
    "starts",
    "runs",
    "short_runs",
    "room_minutes",
    "room_mean_c",
    "room_min_c",
    "degree_hours_below",
    "writes",
    "defrost_min",
)
OCCUPIED_HOURS: Final = (7.0, 23.0)
COMFORT_PERCENTILE: Final = 10.0
TOTAL_KPIS: Final = (
    "heat_kwh_per_day",
    "elec_kwh_per_day",
    "cop",
    "starts_per_day",
    "short_run_share",
    "run_median_min",
    "room_mean_c",
    "room_min_c",
    "degree_hours_below_per_day",
    "writes_per_day",
    "defrost_min_per_day",
)


@dataclass(frozen=True, slots=True)
class Series:
    """Per-tick inputs of the KPI computation.

    Parameters
    ----------
    t
        Tick times (step starts).
    dt
        Tick period.
    heat_w, elec_w
        Powers per tick (``NaN`` counts as 0).
    room_c
        Room temperature per tick (``NaN`` skipped).
    start, write, defrost
        Per-tick flags.
    run_start, run_length_s
        Completed runs.
    """

    t: FloatArray
    dt: float
    heat_w: FloatArray
    elec_w: FloatArray
    room_c: FloatArray
    start: FloatArray
    write: FloatArray
    defrost: FloatArray
    run_start: FloatArray
    run_length_s: FloatArray


@dataclass(frozen=True, slots=True)
class KpiTable:
    """KPIs per day and over the whole period.

    Parameters
    ----------
    days
        Day label (``YYYY-MM-DD``, UTC) to its KPIs.
    totals
        Period KPIs (see :data:`TOTAL_KPIS`).
    runs
        Day label to the lengths (s) of the runs started that day.
    """

    days: Mapping[str, Mapping[str, float]]
    totals: Mapping[str, float]
    runs: Mapping[str, tuple[float, ...]] = field(default_factory=dict)

    def subset(self, labels: Sequence[str]) -> KpiTable:
        """KPIs restricted to some days."""
        days = {label: self.days[label] for label in labels if label in self.days}
        runs = {label: self.runs.get(label, ()) for label in days}
        return KpiTable(days, aggregate(days, runs), runs)

    def resampled(self, labels: Sequence[str]) -> dict[str, float]:
        """Period KPIs of a list of days with repeats (a bootstrap resample)."""
        present = [label for label in labels if label in self.days]
        return aggregate_rows(
            [self.days[label] for label in present], [self.runs.get(label, ()) for label in present]
        )


def day_label(t: float) -> str:
    """UTC day of unix seconds as ``YYYY-MM-DD``."""
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d")


def from_trace(trace: Trace, dt: float) -> Series:
    """KPI inputs of a simulated run."""
    return Series(
        t=trace.t,
        dt=dt,
        heat_w=trace.heat_w,
        elec_w=trace.elec_w,
        room_c=trace.room_c,
        start=trace.start,
        write=trace.write,
        defrost=trace.defrost,
        run_start=trace.run_start,
        run_length_s=trace.run_length_s,
    )


def recorded_runs(
    t: FloatArray, running: FloatArray, defrost: FloatArray, dt: float
) -> tuple[FloatArray, FloatArray]:
    """Completed runs of a recording; compressor pauses around a defrost do not split a run.

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


def compute(series: Series, band_low_c: float) -> KpiTable:
    """KPIs per UTC day and over the period.

    Parameters
    ----------
    series
        Per-tick inputs.
    band_low_c
        Lower edge of the comfort band.

    Returns
    -------
    KpiTable
        Day and period KPIs.
    """
    tick_day = np.floor(series.t / SECONDS_PER_DAY).astype(np.int64)
    run_day = np.floor(series.run_start / SECONDS_PER_DAY).astype(np.int64)
    days: dict[str, dict[str, float]] = {}
    runs: dict[str, tuple[float, ...]] = {}
    hours_per_tick = series.dt / 3600.0
    for day in np.unique(tick_day).tolist():
        mask = tick_day == day
        room = series.room_c[mask]
        finite = room[np.isfinite(room)]
        lengths = series.run_length_s[run_day == day]
        deficit = np.clip(band_low_c - finite, 0.0, None)
        runs[day_label(day * SECONDS_PER_DAY)] = tuple(float(x) for x in lengths)
        days[day_label(day * SECONDS_PER_DAY)] = {
            "heat_kwh": float(np.nansum(series.heat_w[mask]) * series.dt / J_PER_KWH),
            "elec_kwh": float(np.nansum(series.elec_w[mask]) * series.dt / J_PER_KWH),
            "starts": float(series.start[mask].sum()),
            "runs": float(lengths.size),
            "short_runs": float(np.sum(lengths < SHORT_RUN_S)),
            "room_minutes": float(finite.size * series.dt / 60.0),
            "room_mean_c": float(finite.mean()) if finite.size else math.nan,
            "room_min_c": float(finite.min()) if finite.size else math.nan,
            "degree_hours_below": float(deficit.sum() * hours_per_tick),
            "writes": float(series.write[mask].sum()),
            "defrost_min": float(series.defrost[mask].sum() * series.dt / 60.0),
        }
    return KpiTable(days, aggregate(days, runs), runs)


def aggregate(
    days: Mapping[str, Mapping[str, float]],
    runs: Mapping[str, Sequence[float]] | None = None,
) -> dict[str, float]:
    """Period KPIs from day KPIs (sums per day, sample-weighted room mean)."""
    labels = list(days)
    lengths = [tuple((runs or {}).get(label, ())) for label in labels]
    return aggregate_rows([days[label] for label in labels], lengths)


def aggregate_rows(
    rows: Sequence[Mapping[str, float]], runs: Sequence[Sequence[float]] = ()
) -> dict[str, float]:
    """Period KPIs from a list of day KPIs (repeats allowed) and their run lengths."""
    n = len(rows)
    if n == 0:
        return dict.fromkeys(TOTAL_KPIS, math.nan)

    def total(name: str) -> float:
        """Return the sum of column ``name`` over the rows."""
        return float(sum(d[name] for d in rows))

    minutes = total("room_minutes")
    weighted = sum(d["room_mean_c"] * d["room_minutes"] for d in rows if d["room_minutes"] > 0)
    mins = [d["room_min_c"] for d in rows if math.isfinite(d["room_min_c"])]
    elec = total("elec_kwh")
    count = total("runs")
    lengths = [x for day in runs for x in day]
    return {
        "heat_kwh_per_day": total("heat_kwh") / n,
        "elec_kwh_per_day": elec / n,
        "cop": total("heat_kwh") / elec if elec > 0 else math.nan,
        "starts_per_day": total("starts") / n,
        "short_run_share": total("short_runs") / count if count else math.nan,
        "run_median_min": float(np.median(lengths)) / 60.0 if lengths else math.nan,
        "room_mean_c": weighted / minutes if minutes else math.nan,
        "room_min_c": min(mins) if mins else math.nan,
        "degree_hours_below_per_day": total("degree_hours_below") / n,
        "writes_per_day": total("writes") / n,
        "defrost_min_per_day": total("defrost_min") / n,
    }


def room_rmse(simulated: FloatArray, recorded: FloatArray) -> float:
    """RMSE of the simulated room against the recorded one where it is finite."""
    ok = np.isfinite(recorded) & np.isfinite(simulated)
    return float(np.sqrt(np.mean((simulated[ok] - recorded[ok]) ** 2))) if ok.any() else math.nan


def occupied(local_hour: FloatArray) -> np.ndarray:
    """Ticks inside :data:`OCCUPIED_HOURS`."""
    lo, hi = OCCUPIED_HOURS
    return np.asarray((local_hour >= lo) & (local_hour < hi), dtype=np.bool_)


@dataclass(frozen=True, slots=True)
class Comfort:
    """Room comfort over occupied hours.

    Parameters
    ----------
    mean_c
        Mean room temperature (all hours).
    occupied_mean_c
        Mean over occupied hours.
    p10_c
        10th percentile over occupied hours.
    degree_hours_below
        K·h per day of the occupied room below ``threshold_c``.
    threshold_c
        Threshold of the degree-hours.
    """

    mean_c: float
    occupied_mean_c: float
    p10_c: float
    degree_hours_below: float
    threshold_c: float


def comfort(
    room_c: FloatArray, mask: np.ndarray, dt: float, threshold_c: float | None = None
) -> Comfort:
    """Comfort statistics of a room trace.

    Parameters
    ----------
    room_c
        Room temperature per tick.
    mask
        Occupied ticks.
    dt
        Tick period.
    threshold_c
        Degree-hours threshold (default: this trace's own 10th percentile).

    Returns
    -------
    Comfort
        Mean, occupied mean, P10 and degree-hours below the threshold.
    """
    finite = np.isfinite(room_c)
    occ = room_c[mask & finite]
    if not occ.size:
        return Comfort(math.nan, math.nan, math.nan, math.nan, math.nan)
    p10 = float(np.percentile(occ, COMFORT_PERCENTILE))
    threshold = p10 if threshold_c is None else threshold_c
    days = room_c.size * dt / SECONDS_PER_DAY
    deficit = float(np.clip(threshold - occ, 0.0, None).sum() * dt / 3600.0)
    return Comfort(
        mean_c=float(np.mean(room_c[finite])),
        occupied_mean_c=float(np.mean(occ)),
        p10_c=p10,
        degree_hours_below=deficit / days if days else math.nan,
        threshold_c=threshold,
    )

"""KPI rows of a paired run, the pass/fail gate of the model plan and its tables.

A *row* is the set of period KPIs of one closed-loop run (:data:`ROW_KPIS`), measured
after the first simulated day (the warm-up) has been dropped. A *pair* is the same
scenario simulated without and with the planner. The gate (:func:`judge`) compares the
two rows of a pair, or the seed means of a cell, against fixed tolerances; it is not
tuned: the bounds are the constants below.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np

from ovenbird_sim.evaluate import kpi
from ovenbird_sim.evaluate.closedloop import Trace

DAY_S: Final = 86400.0
COMFORT_C: Final = 21.0
BAND_K: Final = 0.5
BELOW_BAND_TOLERANCE_KH: Final = 0.1
BELOW_RELATIVE: Final = 0.05
BELOW_ABSOLUTE_KH: Final = 0.5
STARTS_RELATIVE: Final = 0.05
STARTS_ABSOLUTE_PER_DAY: Final = 0.5
BENEFIT_EPSILON_KH: Final = 1e-6
DAY_COLUMNS: Final = ("below_kh", "below_band_kh", "above_kh")
ROW_KPIS: Final = (
    "below_kh",
    "below_band_kh",
    "above_kh",
    "starts_per_day",
    "short_runs_per_day",
    "heat_kwh_per_day",
    "elec_kwh_per_day",
    "cop",
    "room_mean_c",
    "max_setpoint_step_k",
    "plan_share",
    "offset_mean_abs_k",
    "offset_max_abs_k",
)

type Row = Mapping[str, float]


@dataclass(frozen=True, slots=True)
class RunKpis:
    """KPIs of one run over the kept days.

    Parameters
    ----------
    row
        Period KPIs (:data:`ROW_KPIS`): the degree-hours are sums over the kept days.
    days
        Per kept day: ``below_kh``, ``below_band_kh``, ``above_kh`` (for the bootstrap).
    """

    row: Row
    days: Mapping[str, Row]


def run_kpis(trace: Trace, dt: float, t0: float, comfort_c: float = COMFORT_C) -> RunKpis:
    """Return the KPIs of a closed-loop trace after dropping its first day.

    Parameters
    ----------
    trace
        The run.
    dt
        Tick period.
    t0
        Start of the first (dropped) day.
    comfort_c
        Room target; the band is :data:`BAND_K` wide around it.

    Returns
    -------
    RunKpis
        Period row and per-day degree-hours.
    """
    series = kpi.from_trace(trace, dt)
    at_target = kpi.compute(series, comfort_c)
    at_band = kpi.compute(series, comfort_c - BAND_K)
    every = list(at_target.days)
    labels = every[1:]
    day_index = np.floor((trace.t - t0) / DAY_S).astype(np.int64)
    days: dict[str, dict[str, float]] = {}
    rows: list[Row] = []
    for index, label in enumerate(every):
        if index == 0:
            continue
        over = np.clip(trace.room_c[day_index == index] - (comfort_c + BAND_K), 0.0, None)
        row = dict(at_target.days[label])
        days[label] = {
            "below_kh": row["degree_hours_below"],
            "below_band_kh": at_band.days[label]["degree_hours_below"],
            "above_kh": float(over.sum() * dt / 3600.0),
        }
        rows.append(row)
    totals = kpi.aggregate_rows(rows, [at_target.runs.get(label, ()) for label in labels])
    keep = day_index >= 1
    offsets = np.abs(trace.plan_offset_k[keep]) if trace.plan_offset_k.size else np.zeros(1)
    steps = np.abs(np.diff(trace.setpoint[keep])) if keep.sum() > 1 else np.zeros(1)
    count = max(len(labels), 1)
    row_out = {
        "below_kh": sum(d["below_kh"] for d in days.values()),
        "below_band_kh": sum(d["below_band_kh"] for d in days.values()),
        "above_kh": sum(d["above_kh"] for d in days.values()),
        "starts_per_day": totals["starts_per_day"],
        "short_runs_per_day": sum(r["short_runs"] for r in rows) / count,
        "heat_kwh_per_day": totals["heat_kwh_per_day"],
        "elec_kwh_per_day": totals["elec_kwh_per_day"],
        "cop": totals["cop"],
        "room_mean_c": totals["room_mean_c"],
        "max_setpoint_step_k": float(steps.max()),
        "plan_share": float(np.mean(offsets > 0.0)),
        "offset_mean_abs_k": float(offsets.mean()),
        "offset_max_abs_k": float(offsets.max()),
    }
    return RunKpis(row_out, days)


def mean_row(rows: Sequence[Row]) -> dict[str, float]:
    """Return the mean of every KPI over ``rows`` (the max offset stays a maximum)."""
    out = {name: float(np.nanmean([r[name] for r in rows])) for name in ROW_KPIS}
    out["offset_max_abs_k"] = max(r["offset_max_abs_k"] for r in rows)
    return out


@dataclass(frozen=True, slots=True)
class Check:
    """One gate criterion of a cell.

    Parameters
    ----------
    name
        ``below_band``, ``below``, ``starts`` or ``benefit``.
    passed
        Whether the criterion holds.
    detail
        Plain statement of the numbers.
    """

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class Verdict:
    """Gate result of one cell.

    Parameters
    ----------
    checks
        The criteria that apply to the cell.
    """

    checks: tuple[Check, ...]

    @property
    def passed(self) -> bool:
        """Whether every criterion holds."""
        return all(c.passed for c in self.checks)

    @property
    def failed(self) -> tuple[str, ...]:
        """Names of the criteria that fail."""
        return tuple(c.name for c in self.checks if not c.passed)


def judge(without: Row, with_plan: Row, benefit_required: bool = False) -> Verdict:
    """Apply the gate to the KPIs without and with the planner.

    Parameters
    ----------
    without, with_plan
        Rows of the pair (or of the seed means of a cell).
    benefit_required
        Also require the degree-hours above the band to improve (the sunny scenarios
        with the correct model).

    Returns
    -------
    Verdict
        Per-criterion result.

    Notes
    -----
    ``below_band``: degree-hours below comfort minus 0.5 K rise by at most 0.1 Kh over
    the period. ``below``: degree-hours below comfort rise by at most 5 % or 0.5 Kh,
    whichever is larger. ``starts``: compressor starts per day rise by at most 5 % or
    0.5 per day, whichever is larger. ``benefit``: degree-hours above the band fall.
    """
    d_band = with_plan["below_band_kh"] - without["below_band_kh"]
    d_below = with_plan["below_kh"] - without["below_kh"]
    d_starts = with_plan["starts_per_day"] - without["starts_per_day"]
    allowed_below = max(BELOW_RELATIVE * without["below_kh"], BELOW_ABSOLUTE_KH)
    allowed_starts = max(STARTS_RELATIVE * without["starts_per_day"], STARTS_ABSOLUTE_PER_DAY)
    checks = [
        Check(
            "below_band",
            d_band <= BELOW_BAND_TOLERANCE_KH + BENEFIT_EPSILON_KH,
            f"{d_band:+.2f} Kh (allowed {BELOW_BAND_TOLERANCE_KH:+.2f})",
        ),
        Check(
            "below",
            d_below <= allowed_below + BENEFIT_EPSILON_KH,
            f"{d_below:+.2f} Kh (allowed {allowed_below:+.2f})",
        ),
        Check(
            "starts",
            d_starts <= allowed_starts + BENEFIT_EPSILON_KH,
            f"{d_starts:+.2f}/day (allowed {allowed_starts:+.2f})",
        ),
    ]
    if benefit_required:
        d_above = with_plan["above_kh"] - without["above_kh"]
        checks.append(Check("benefit", d_above < -BENEFIT_EPSILON_KH, f"{d_above:+.2f} Kh above"))
    return Verdict(tuple(checks))


def bootstrap_interval(
    differences: Sequence[float],
    replicates: int = 1000,
    seed: int = 0,
    period_days: int | None = None,
) -> tuple[float, float]:
    """Return the 95 % day-block bootstrap interval of the summed difference.

    Parameters
    ----------
    differences
        Paired difference (with minus without) of one KPI per day (and seed).
    replicates
        Number of resamples of the days with repeats.
    seed
        Seed of the resampling.
    period_days
        Days of one run's period (default: the number of differences); with several
        seeds pooled it keeps the interval on the scale of a single run.

    Returns
    -------
    tuple
        Lower and upper bound of the mean daily difference times ``period_days``
        (the period total), or ``nan`` without days.
    """
    values = np.asarray(differences, dtype=np.float64)
    if values.size == 0:
        return math.nan, math.nan
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, values.size, size=(replicates, values.size))
    totals = values[picks].mean(axis=1) * (values.size if period_days is None else period_days)
    low, high = np.percentile(totals, [2.5, 97.5])
    return float(low), float(high)


def day_differences(
    without: Mapping[str, Row], with_plan: Mapping[str, Row], name: str
) -> list[float]:
    """Return the per-day difference with minus without of a day column."""
    return [
        with_plan[label][name] - without[label][name] for label in without if label in with_plan
    ]


def format_row_table(
    title: str,
    lines: Sequence[tuple[str, Row, Row, Verdict]],
) -> str:
    """Return a Markdown table of one scenario.

    Parameters
    ----------
    title
        Heading text (scenario name).
    lines
        ``(label, without, with, verdict)`` per model/forecast variant.

    Returns
    -------
    str
        Markdown with, per variant, the key KPIs without and with the plan, the
        difference and the gate verdict.
    """
    head = (
        f"### {title}\n\n"
        "Kh = K·h summed over the 7 kept days. Each cell: without / with / change.\n\n"
        "| variant | below 21 °C (Kh) | below 20.5 °C (Kh) | above 21.5 °C (Kh) "
        "| starts/day | heat kWh/day | COP | plan applied | mean / max abs offset (K) | gate |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
    )
    body = []
    for label, a, b, verdict in lines:
        failed = ", ".join(verdict.failed)
        gate = "pass" if verdict.passed else f"FAIL ({failed})"
        body.append(
            f"| {label} | {_triple(a, b, 'below_kh')} | {_triple(a, b, 'below_band_kh')} "
            f"| {_triple(a, b, 'above_kh')} | {_triple(a, b, 'starts_per_day')} "
            f"| {_triple(a, b, 'heat_kwh_per_day', 1)} | {_triple(a, b, 'cop')} "
            f"| {b['plan_share'] * 100:.0f} % "
            f"| {b['offset_mean_abs_k']:.2f} / {b['offset_max_abs_k']:.1f} | {gate} |"
        )
    return head + "\n".join(body) + "\n"


def _triple(a: Row, b: Row, name: str, digits: int = 2) -> str:
    x, y = a[name], b[name]
    return f"{x:.{digits}f} / {y:.{digits}f} / {y - x:+.{digits}f}"

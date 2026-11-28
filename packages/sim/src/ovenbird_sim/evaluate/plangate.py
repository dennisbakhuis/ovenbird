"""KPIs of a run, paired differences over replicas and the three-valued gate of a planner.

**KPIs (:func:`run_result`)**
Every KPI of a run is per kept day (the first simulated day is dropped as warm-up):
degree-hours below comfort minus :data:`BAND_K`, below comfort and above comfort plus
:data:`BAND_K`; compressor starts and short runs; electricity and heat; COP; setpoint
writes (setpoint changes actually sent to the pump); the largest setpoint step; the
share of ticks with a plan applied and the mean and largest absolute offset. The
comfort reference is always the owner's comfort target :data:`COMFORT_C`.

**Statistics**
A cell's statistic is the mean over its weather replicas of the paired difference
(with minus without) per day; replicas are independent, the days within a run are
not, so the interval is a bootstrap over replicas (:func:`bootstrap`). With few
replicas the plain percentile bootstrap is too narrow; the expanded percentile
interval widens its quantiles to the coverage of a t interval (:func:`expanded_alpha`).

**Gate (:func:`judge_cell`)**
Per criterion and cell, on the interval of the difference against its margin:
``PASS`` when the upper bound is within the margin, ``FAIL`` when the lower bound is
beyond it, ``INCONCLUSIVE`` otherwise. Margins are per day: :data:`CRITERIA`.

Starts are the noisiest criterion and the only one with a second look: a cell whose
starts interval straddles the margin after :data:`BASE_REPLICAS` replicas gets the
replicas up to :data:`MAX_REPLICAS` once, and the starts verdict on all of them is
final. Two looks at a fixed level would let the error rate grow, so both looks of
the starts criterion use the Pocock level for two equally spaced looks
(:data:`POCOCK_ALPHA`); every other criterion is judged on the first
:data:`BASE_REPLICAS` replicas only, at :data:`ALPHA`, extension or not.

Benefit (:func:`benefit`): per replica the mean over the pooled cells of
``delta above + 2 delta below`` per day; it holds when the upper bound of its
interval is below zero.

Combined verdict (:func:`combine`): no cell fails any criterion; every credible cell
passes the comfort criteria (``INCONCLUSIVE`` there blocks); the cost criteria
(starts, electricity, writes) pass on the mean over the credible cells; the benefit
holds. The cost criteria are not required to pass in every credible cell because
their per-cell noise is too close to the margins: with independent,
controller-irrelevant sensor noise as the only difference (the ``noise`` planner)
4 of 42 credible cells were inconclusive on starts or writes, so a rule requiring
every credible cell to pass them blocks a harmless planner almost surely, whereas no
cell was inconclusive on a comfort criterion (see the evaluation notes).
"""

from __future__ import annotations

import math
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Final

import numpy as np
from scipy import stats

from ovenbird_sim.data.series import FloatArray
from ovenbird_sim.evaluate.closedloop import Trace
from ovenbird_sim.evaluate.kpi import SHORT_RUN_S

DAY_S: Final = 86400.0
HOUR_S: Final = 3600.0
QUARTER_S: Final = 900.0
QUARTERS_PER_DAY: Final = 96
COMFORT_C: Final = 21.0
BAND_K: Final = 0.5
ALPHA: Final = 0.05
POCOCK_ALPHA: Final = 0.0294
BASE_REPLICAS: Final = 24
MAX_REPLICAS: Final = 48
RESAMPLES: Final = 4000
BENEFIT_BELOW_WEIGHT: Final = 2.0
MARGIN_EPSILON: Final = 1e-9
ROW_KPIS: Final = (
    "below_band_kh",
    "below_kh",
    "above_kh",
    "starts_per_day",
    "short_runs_per_day",
    "elec_kwh_per_day",
    "heat_kwh_per_day",
    "cop",
    "writes_per_day",
    "max_setpoint_step_k",
    "plan_share",
    "offset_mean_abs_k",
    "offset_max_abs_k",
    "room_mean_c",
)

type Row = Mapping[str, float]


@dataclass(frozen=True, slots=True)
class RunResult:
    """KPIs of one run over its kept days.

    Parameters
    ----------
    row
        :data:`ROW_KPIS`, per kept day.
    deficit_q
        Degree-hours below comfort per quarter hour of the kept days.
    active_q
        Share of the ticks of each quarter hour with a plan applied.
    days
        Number of kept days.
    """

    row: Row
    deficit_q: FloatArray
    active_q: FloatArray
    days: int


def run_result(
    trace: Trace, offsets: FloatArray, dt: float, t0: float, comfort_c: float = COMFORT_C
) -> RunResult:
    """Return the KPIs of a closed-loop run after dropping its first day.

    Parameters
    ----------
    trace
        The run.
    offsets
        Plan offset applied per tick (0: none).
    dt
        Tick period.
    t0
        Start of the first (dropped) day, a UTC midnight.
    comfort_c
        The owner's comfort target.

    Returns
    -------
    RunResult
        The per-day row and the quarter-hour comfort deficit and plan share.
    """
    day_index = np.floor((trace.t - t0) / DAY_S).astype(np.int64)
    keep = day_index >= 1
    days = max(int(day_index.max()), 1)
    hours = dt / HOUR_S
    room = trace.room_c[keep]
    deficit = np.clip(comfort_c - room, 0.0, None)
    heat = float(trace.heat_w[keep].sum() * dt / 3.6e6)
    elec = float(trace.elec_w[keep].sum() * dt / 3.6e6)
    kept_from = t0 + DAY_S
    in_kept = trace.run_start >= kept_from
    short = int(np.sum(trace.run_length_s[in_kept] < SHORT_RUN_S))
    setpoints = trace.setpoint[keep]
    steps = np.abs(np.diff(setpoints)) if setpoints.size > 1 else np.zeros(1)
    applied = np.abs(offsets[keep])
    row = {
        "below_band_kh": float(np.clip(comfort_c - BAND_K - room, 0.0, None).sum() * hours / days),
        "below_kh": float(deficit.sum() * hours / days),
        "above_kh": float(np.clip(room - comfort_c - BAND_K, 0.0, None).sum() * hours / days),
        "starts_per_day": float(trace.start[keep].sum() / days),
        "short_runs_per_day": short / days,
        "elec_kwh_per_day": elec / days,
        "heat_kwh_per_day": heat / days,
        "cop": heat / elec if elec > 0.0 else math.nan,
        "writes_per_day": float(trace.write[keep].sum() / days),
        "max_setpoint_step_k": float(steps.max()),
        "plan_share": float(np.mean(applied > 0.0)),
        "offset_mean_abs_k": float(applied.mean()),
        "offset_max_abs_k": float(applied.max()),
        "room_mean_c": float(room.mean()),
    }
    per_quarter = round(QUARTER_S / dt)
    quarters = deficit.size // per_quarter
    deficit_q = deficit[: quarters * per_quarter].reshape(quarters, per_quarter).sum(axis=1) * hours
    active_q = (applied[: quarters * per_quarter] > 0.0).reshape(quarters, per_quarter).mean(axis=1)
    return RunResult(row, deficit_q, active_q, days)


def mean_row(rows: Sequence[Row]) -> dict[str, float]:
    """Return the mean of every KPI over replicas (the largest offset stays a maximum)."""
    out = {name: float(np.nanmean([r[name] for r in rows])) for name in ROW_KPIS}
    out["offset_max_abs_k"] = max(r["offset_max_abs_k"] for r in rows)
    out["max_setpoint_step_k"] = max(r["max_setpoint_step_k"] for r in rows)
    return out


class Outcome(StrEnum):
    """Three-valued result of a criterion."""

    PASSED = "PASS"
    FAILED = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class Criterion:
    """A gate criterion on the paired difference of one KPI.

    Parameters
    ----------
    name
        Short name.
    kpi
        Row KPI.
    margin
        Largest acceptable rise: per day, or a share of the baseline when relative.
    relative
        The difference is divided by the baseline mean (at least ``floor``).
    floor
        Smallest denominator of a relative criterion.
    adaptive
        Eligible for the one extension to :data:`MAX_REPLICAS` replicas.
    cost
        A cost criterion (wear, energy, writes): judged for the verdict on the mean over
        the credible cells; per cell only a failure blocks. Otherwise a comfort
        criterion: every credible cell must pass.
    """

    name: str
    kpi: str
    margin: float
    relative: bool = False
    floor: float = 1e-9
    adaptive: bool = False
    cost: bool = False

    def statistic(self, without: FloatArray, with_plan: FloatArray) -> FloatArray:
        """Return the statistic over the last axis (replicas) of the two arrays."""
        if self.relative:
            base = without.mean(axis=-1)
            return np.asarray(
                (with_plan.mean(axis=-1) - base) / np.maximum(base, self.floor), dtype=np.float64
            )
        return np.asarray((with_plan - without).mean(axis=-1), dtype=np.float64)

    @property
    def unit(self) -> str:
        """Unit of the statistic."""
        if self.relative:
            return "share"
        return "Kh/day" if self.kpi.endswith("_kh") else "/day"


CRITERIA: Final = (
    Criterion("below_band", "below_band_kh", 0.15),
    Criterion("below", "below_kh", 0.5),
    Criterion("starts", "starts_per_day", 0.5, adaptive=True, cost=True),
    Criterion("elec", "elec_kwh_per_day", 0.02, relative=True, cost=True),
    Criterion("writes", "writes_per_day", 0.20, relative=True, floor=1.0, cost=True),
)
CRITERION: Final = {c.name: c for c in CRITERIA}


@dataclass(frozen=True, slots=True)
class Interval:
    """Estimate and bootstrap interval of a statistic.

    Parameters
    ----------
    estimate
        The statistic on all replicas.
    low, high
        Bounds of the interval.
    n
        Number of replicas.
    alpha
        Two-sided error level of the interval.
    """

    estimate: float
    low: float
    high: float
    n: int
    alpha: float


def expanded_alpha(alpha: float, n: int) -> float:
    """Return the percentile level of the expanded percentile bootstrap.

    The percentile bootstrap of a mean has the coverage of a normal interval with the
    plug-in variance, which is too narrow for small ``n``. Taking the quantiles at
    ``Phi(sqrt(n / (n - 1)) t_{alpha/2, n-1})`` instead gives the coverage of the t
    interval (Hesterberg's expanded percentile interval).
    """
    if n < 2:
        return alpha
    t = float(stats.t.ppf(alpha / 2.0, n - 1))
    return float(2.0 * stats.norm.cdf(math.sqrt(n / (n - 1)) * t))


def seed_of(label: str) -> int:
    """Return a stable resampling seed for a label."""
    return zlib.crc32(label.encode())


def bootstrap(
    criterion: Criterion,
    without: Sequence[float],
    with_plan: Sequence[float],
    alpha: float = ALPHA,
    label: str = "",
    resamples: int = RESAMPLES,
) -> Interval:
    """Return the expanded percentile bootstrap interval of a criterion's statistic.

    Parameters
    ----------
    criterion
        The criterion (its statistic).
    without, with_plan
        The KPI per replica, paired by position.
    alpha
        Two-sided error level.
    label
        Identity of the cell (seeds the resampling, so the interval is reproducible).
    resamples
        Number of bootstrap resamples of the replicas.

    Returns
    -------
    Interval
        Estimate and bounds (``nan`` without replicas).
    """
    a = np.asarray(without, dtype=np.float64)
    b = np.asarray(with_plan, dtype=np.float64)
    n = int(a.size)
    if n == 0 or n != b.size:
        return Interval(math.nan, math.nan, math.nan, n, alpha)
    estimate = float(criterion.statistic(a, b))
    rng = np.random.default_rng(seed_of(f"{label}|{criterion.name}|{n}"))
    picks = rng.integers(0, n, size=(resamples, n))
    values = criterion.statistic(a[picks], b[picks])
    level = expanded_alpha(alpha, n)
    low, high = np.quantile(values, [level / 2.0, 1.0 - level / 2.0])
    return Interval(estimate, float(low), float(high), n, alpha)


def outcome(interval: Interval, margin: float) -> Outcome:
    """Return the three-valued result of an interval against a margin."""
    if interval.high <= margin + MARGIN_EPSILON:
        return Outcome.PASSED
    if interval.low > margin + MARGIN_EPSILON:
        return Outcome.FAILED
    return Outcome.INCONCLUSIVE


@dataclass(frozen=True, slots=True)
class Check:
    """Result of one criterion in one cell.

    Parameters
    ----------
    criterion
        The criterion's name.
    interval
        The interval of its statistic.
    outcome
        ``PASS``, ``FAIL`` or ``INCONCLUSIVE``.
    extended
        Judged on the extended replicas.
    """

    criterion: str
    interval: Interval
    outcome: Outcome
    extended: bool = False

    @property
    def margin(self) -> float:
        """The criterion's margin."""
        return CRITERION[self.criterion].margin


@dataclass(frozen=True, slots=True)
class CellVerdict:
    """The checks of a cell.

    Parameters
    ----------
    checks
        One per criterion of :data:`CRITERIA`.
    """

    checks: tuple[Check, ...]

    @property
    def outcome(self) -> Outcome:
        """``FAIL`` if any check fails, else ``INCONCLUSIVE`` if any is, else ``PASS``."""
        found = {c.outcome for c in self.checks}
        if Outcome.FAILED in found:
            return Outcome.FAILED
        if Outcome.INCONCLUSIVE in found:
            return Outcome.INCONCLUSIVE
        return Outcome.PASSED

    def named(self, outcome_: Outcome) -> tuple[str, ...]:
        """Names of the criteria with this outcome."""
        return tuple(c.criterion for c in self.checks if c.outcome is outcome_)

    def check(self, name: str) -> Check:
        """Return the check of a criterion."""
        return next(c for c in self.checks if c.criterion == name)


def judge_cell(
    without: Sequence[Row],
    with_plan: Sequence[Row],
    label: str = "",
    base_n: int = BASE_REPLICAS,
) -> CellVerdict:
    """Apply the gate to the replicas of a cell.

    Parameters
    ----------
    without, with_plan
        Rows per replica, paired by position; more than ``base_n`` only after the
        extension.
    label
        Identity of the cell (resampling seed).
    base_n
        Replicas of the first look; every criterion but the adaptive one uses only these.

    Returns
    -------
    CellVerdict
        One check per criterion.
    """
    checks: list[Check] = []
    for criterion in CRITERIA:
        n = len(with_plan) if criterion.adaptive else min(base_n, len(with_plan))
        alpha = POCOCK_ALPHA if criterion.adaptive else ALPHA
        interval = bootstrap(
            criterion,
            [r[criterion.kpi] for r in without[:n]],
            [r[criterion.kpi] for r in with_plan[:n]],
            alpha,
            label,
        )
        checks.append(
            Check(criterion.name, interval, outcome(interval, criterion.margin), n > base_n)
        )
    return CellVerdict(tuple(checks))


def wants_extension(verdict: CellVerdict, base_n: int, max_n: int) -> bool:
    """Whether a cell gets the one extension: an adaptive criterion straddles its margin.

    Decided on the first look only: a check judged on more than ``base_n`` replicas
    is final.
    """
    return max_n > base_n and any(
        CRITERION[c.criterion].adaptive
        and c.outcome is Outcome.INCONCLUSIVE
        and c.interval.n == base_n
        for c in verdict.checks
    )


def pooled_check(
    criterion: Criterion,
    cells: Sequence[tuple[Sequence[Row], Sequence[Row]]],
    n: int,
    label: str = "pooled",
) -> Check:
    """Return a criterion on the mean over cells, paired by replica (the first ``n``).

    Per replica the KPI is averaged over the cells without and with the planner, and
    the criterion's statistic and interval are taken on those means (replicas are
    resampled jointly, so the cells that share a baseline stay paired).

    Parameters
    ----------
    criterion
        Criterion to judge.
    cells
        Per cell the result rows without and with the planner.
    n
        Number of replicas used.
    label
        Label of the check, for messages.
    """
    if not cells:
        empty = Interval(math.nan, math.nan, math.nan, 0, ALPHA)
        return Check(criterion.name, empty, Outcome.INCONCLUSIVE)
    without = np.mean([[r[criterion.kpi] for r in w[:n]] for w, _ in cells], axis=0)
    with_plan = np.mean([[r[criterion.kpi] for r in p[:n]] for _, p in cells], axis=0)
    interval = bootstrap(criterion, without.tolist(), with_plan.tolist(), ALPHA, label)
    return Check(criterion.name, interval, outcome(interval, criterion.margin))


BENEFIT: Final = Criterion("benefit", "benefit", 0.0)


def benefit_values(cells: Sequence[tuple[Sequence[Row], Sequence[Row]]], n: int) -> FloatArray:
    """Return per replica the mean over cells of ``delta above + 2 delta below`` per day."""
    per_cell = [
        [
            (w["above_kh"] - b["above_kh"]) + BENEFIT_BELOW_WEIGHT * (w["below_kh"] - b["below_kh"])
            for b, w in zip(without[:n], with_plan[:n], strict=True)
        ]
        for without, with_plan in cells
    ]
    return np.asarray(np.mean(np.asarray(per_cell, dtype=np.float64), axis=0), dtype=np.float64)


def benefit(
    cells: Sequence[tuple[Sequence[Row], Sequence[Row]]], n: int, label: str = "benefit"
) -> Interval:
    """Return the interval of the pooled benefit statistic (negative is better).

    Parameters
    ----------
    cells
        ``(without, with)`` rows per pooled cell, paired by replica.
    n
        Replicas used (the first look).
    label
        Resampling seed label.

    Returns
    -------
    Interval
        Estimate and bounds; the benefit holds when the upper bound is below zero.
    """
    if not cells:
        return Interval(math.nan, math.nan, math.nan, 0, ALPHA)
    values = benefit_values(cells, n)
    return bootstrap(BENEFIT, np.zeros(values.size).tolist(), values.tolist(), ALPHA, label)


@dataclass(frozen=True, slots=True)
class Verdict:
    """The combined verdict (rule in :func:`combine`).

    Parameters
    ----------
    unlocked
        Whether the planner may be switched on from this evaluation.
    credible_fail
        Credible cells with a failing criterion.
    credible_inconclusive
        Credible cells with an inconclusive comfort criterion (these block).
    credible_cost_inconclusive
        Credible cells inconclusive only on cost criteria (reported; the pooled
        cost criteria decide).
    stress_fail, stress_inconclusive
        The same for the stress cells (only a failure blocks).
    benefit
        The pooled benefit interval.
    pooled
        Every criterion on the mean over the credible cells.
    """

    unlocked: bool
    credible_fail: tuple[str, ...]
    credible_inconclusive: tuple[str, ...]
    credible_cost_inconclusive: tuple[str, ...]
    stress_fail: tuple[str, ...]
    stress_inconclusive: tuple[str, ...]
    benefit: Interval
    pooled: tuple[Check, ...] = ()

    @property
    def benefit_holds(self) -> bool:
        """Whether the upper bound of the benefit statistic is below zero."""
        return self.benefit.high < 0.0

    @property
    def pooled_blocking(self) -> tuple[Check, ...]:
        """The pooled cost criteria that do not pass."""
        return tuple(
            k
            for k in self.pooled
            if CRITERION[k.criterion].cost and k.outcome is not Outcome.PASSED
        )

    def lines(self) -> list[str]:
        """Return the verdict in plain sentences."""
        out = [
            "UNLOCK: no cell fails, every credible cell passes the comfort criteria, the "
            "cost criteria pass on the credible mean, the benefit holds."
            if self.unlocked
            else "BLOCKED: the planner may not be switched on from this evaluation."
        ]
        if self.credible_fail:
            out.append(f"{len(self.credible_fail)} credible cells FAIL.")
        if self.credible_inconclusive:
            out.append(
                f"{len(self.credible_inconclusive)} credible cells are INCONCLUSIVE on comfort; "
                "an inconclusive credible cell blocks unlocking as much as a failing one."
            )
        if self.credible_cost_inconclusive:
            out.append(
                f"{len(self.credible_cost_inconclusive)} credible cells are INCONCLUSIVE on a "
                "cost criterion only; that does not block, the credible mean decides."
            )
        for k in self.pooled_blocking:
            out.append(f"Cost criterion {k.criterion} on the credible mean is {k.outcome.value}.")
        if self.stress_fail:
            out.append(f"{len(self.stress_fail)} stress cells FAIL.")
        b = self.benefit
        state = "holds" if self.benefit_holds else "is not shown"
        out.append(
            f"Benefit (delta above + 2 delta below, Kh/day, pooled): {b.estimate:+.3f} "
            f"[{b.low:+.3f}, {b.high:+.3f}]; it {state}."
        )
        return out


def combine(
    verdicts: Sequence[tuple[str, bool, CellVerdict]],
    benefit_interval: Interval,
    pooled: Sequence[Check] = (),
) -> Verdict:
    """Return the combined verdict of the cells, the pooled cost criteria and the benefit.

    The planner is unlocked when

    1. no cell, credible or stress, fails any criterion;
    2. every credible cell passes the comfort criteria (an inconclusive one blocks);
    3. every cost criterion (:attr:`Criterion.cost`) passes on the mean over the
       credible cells (:func:`pooled_check`); a credible cell inconclusive on a cost
       criterion is reported but does not block;
    4. the benefit holds.

    Parameters
    ----------
    verdicts
        ``(label, credible, verdict)`` per cell.
    benefit_interval
        The pooled benefit interval.
    pooled
        The criteria on the mean over the credible cells.

    Returns
    -------
    Verdict
        Lists of the failing and inconclusive cells and the decision.
    """

    def text(verdict: CellVerdict, outcome_: Outcome, cost: bool | None = None) -> str:
        """Return the names of the checks of ``verdict`` with outcome ``outcome_``."""
        names = [
            c.criterion
            for c in verdict.checks
            if c.outcome is outcome_ and (cost is None or CRITERION[c.criterion].cost is cost)
        ]
        return ", ".join(names)

    def listed(credible: bool, outcome_: Outcome, cost: bool | None = None) -> tuple[str, ...]:
        """Return the cells of one credibility with ``outcome_`` checks as ``label [names]``."""
        found = [(lb, text(v, outcome_, cost)) for lb, c, v in verdicts if c is credible]
        return tuple(f"{lb} [{names}]" for lb, names in found if names)

    cf = listed(True, Outcome.FAILED)
    ci = listed(True, Outcome.INCONCLUSIVE, cost=False)
    blocking = {item.split(" [")[0] for item in ci}
    cc = tuple(
        item
        for item in listed(True, Outcome.INCONCLUSIVE, cost=True)
        if item.split(" [")[0] not in blocking
    )
    sf = listed(False, Outcome.FAILED)
    si = listed(False, Outcome.INCONCLUSIVE)
    verdict = Verdict(False, cf, ci, cc, sf, si, benefit_interval, tuple(pooled))
    costs = {k.criterion for k in pooled if CRITERION[k.criterion].cost}
    complete = costs == {c.name for c in CRITERIA if c.cost}
    unlocked = (
        not cf
        and not ci
        and not sf
        and complete
        and not verdict.pooled_blocking
        and verdict.benefit_holds
    )
    return replace(verdict, unlocked=unlocked)


def plan_split(without: Sequence[RunResult], with_plan: Sequence[RunResult]) -> dict[str, Any]:
    """Return the diagnostic split of the paired below-comfort difference (Kh/day).

    The difference of every quarter hour is attributed to the plan-active part by the
    share of its ticks with a plan applied in the planned run; the two parts add up to
    the difference. By hour of day: the mean over kept days and replicas.
    """
    active: list[float] = []
    idle: list[float] = []
    hourly: list[FloatArray] = []
    for b, w in zip(without, with_plan, strict=True):
        diff = w.deficit_q - b.deficit_q
        active.append(float((w.active_q * diff).sum() / w.days))
        idle.append(float(((1.0 - w.active_q) * diff).sum() / w.days))
        per_day = diff.reshape(w.days, QUARTERS_PER_DAY)
        hourly.append(per_day.reshape(w.days, 24, 4).sum(axis=2).mean(axis=0))
    by_hour = np.mean(np.asarray(hourly), axis=0) if hourly else np.zeros(24)
    return {
        "below_plan_active_kh": float(np.mean(active)) if active else math.nan,
        "below_plan_none_kh": float(np.mean(idle)) if idle else math.nan,
        "below_by_hour_kh": [round(float(x), 5) for x in by_hour],
    }

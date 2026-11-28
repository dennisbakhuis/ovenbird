"""The gate of the sun day shift: paired differences per scenario and the verdict of a setting.

**Statistic**
Per scenario and arm, the mean over replicas of the paired difference (arm minus
baseline) of a KPI, per :data:`~ovenbird_sim.evaluate.dayshift.KEPT_DAYS` days. The
interval is the expanded percentile bootstrap over replicas of
:func:`ovenbird_sim.evaluate.plangate.bootstrap` (replicas are independent, the days in
a run are not), two-sided at :data:`ALPHA`.

**Criteria (:data:`CRITERIA`)**
Every one is a largest acceptable rise per 7 days, fixed before the first full run:
degree-hours below comfort and below comfort - 0.5 K in the occupied hours (07:00 to
23:00) and in the morning (07:00 to 09:00), degree-hours above comfort + 1.5 K at any
hour, and compressor starts. A check is ``PASS`` when the upper bound of its interval
is within the margin, ``FAIL`` when the lower bound is beyond it and ``INCONCLUSIVE``
otherwise.

**Idle check**
In a scenario where the rule must do nothing (``must_idle``), a rule arm passes only
when no replica had any offset applied, which makes every paired difference exactly
zero.

**Verdict of an arm (:func:`verdict`)**
``PASS`` when every scenario passes every criterion and every idle check holds;
``FAIL`` when any check fails; ``INCONCLUSIVE`` otherwise (it blocks as much as a
failure). The benefit is reported, not required: the owner's goal, less compressor run
time at night, with its interval in the intended scenario.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np

from ovenbird_sim.evaluate import plangate
from ovenbird_sim.evaluate.dayshift import KPIS, SCENARIOS, Arm, Row
from ovenbird_sim.evaluate.plangate import Criterion, Interval, Outcome

ALPHA: Final = 0.05
INTENDED: Final = "sunny_mild"
CRITERIA: Final = (
    Criterion("below_occupied", "below_occ_kh", 1.0),
    Criterion("below_band_occupied", "below_band_occ_kh", 0.5),
    Criterion("below_morning", "below_morning_kh", 0.5),
    Criterion("below_band_morning", "below_band_morning_kh", 0.25),
    Criterion("overheating", "above_kh", 1.0),
    Criterion("starts", "starts", 3.5),
)
COMFORT_CRITERIA: Final = frozenset(
    {"below_occupied", "below_band_occupied", "below_morning", "below_band_morning"}
)
MARGIN_TEXT: Final = {
    "below_occupied": "Kh below comfort, 07:00-23:00",
    "below_band_occupied": "Kh below comfort - 0.5 K, 07:00-23:00",
    "below_morning": "Kh below comfort, 07:00-09:00",
    "below_band_morning": "Kh below comfort - 0.5 K, 07:00-09:00",
    "overheating": "Kh above comfort + 1.5 K, all hours",
    "starts": "compressor starts",
}
ELEC_SHARE: Final = Criterion("elec_share", "elec_kwh", math.inf, relative=True)


@dataclass(frozen=True, slots=True)
class Check:
    """One criterion in one scenario.

    Parameters
    ----------
    criterion
        The criterion's name.
    interval
        The interval of the paired difference.
    outcome
        ``PASS``, ``FAIL`` or ``INCONCLUSIVE``.
    margin
        The criterion's margin.
    """

    criterion: str
    interval: Interval
    outcome: Outcome
    margin: float


@dataclass(frozen=True, slots=True)
class Cell:
    """The judgement of an arm in a scenario.

    Parameters
    ----------
    scenario
        Scenario name.
    checks
        One per :data:`CRITERIA`.
    diffs
        The paired difference interval of every KPI (and ``elec_share``).
    idle
        Whether no replica had an offset applied (``None``: not an idle scenario).
    """

    scenario: str
    checks: tuple[Check, ...]
    diffs: Mapping[str, Interval]
    idle: bool | None

    @property
    def outcome(self) -> Outcome:
        """``FAIL`` on any failing check or a broken idle check, else the weakest outcome."""
        found = {c.outcome for c in self.checks}
        if Outcome.FAILED in found or self.idle is False:
            return Outcome.FAILED
        if Outcome.INCONCLUSIVE in found:
            return Outcome.INCONCLUSIVE
        return Outcome.PASSED

    def named(self, outcome: Outcome) -> tuple[str, ...]:
        """Return the criteria with this outcome (and ``idle`` for a broken idle check)."""
        names = tuple(c.criterion for c in self.checks if c.outcome is outcome)
        if outcome is Outcome.FAILED and self.idle is False:
            names += ("idle",)
        return names

    def check(self, name: str) -> Check:
        """Return the check of a criterion."""
        return next(c for c in self.checks if c.criterion == name)


def interval(name: str, without: Sequence[Row], with_arm: Sequence[Row], label: str) -> Interval:
    """Return the paired-difference interval of a KPI (``elec_share``: relative electricity).

    Parameters
    ----------
    name
        KPI name.
    without
        Result rows of the baseline runs.
    with_arm
        Result rows of the arm's runs, paired by replica.
    label
        Label of the cell, for messages.
    """
    criterion = ELEC_SHARE if name == ELEC_SHARE.name else Criterion(name, name, math.inf)
    return plangate.bootstrap(
        criterion,
        [r[criterion.kpi] for r in without],
        [r[criterion.kpi] for r in with_arm],
        ALPHA,
        label,
    )


def judge(
    scenario: str,
    arm: Arm,
    without: Sequence[Row],
    with_arm: Sequence[Row],
) -> Cell:
    """Return the cell of an arm in a scenario.

    Parameters
    ----------
    scenario
        Scenario name.
    arm
        The arm (a rule arm gets the idle check where the scenario asks for it).
    without, with_arm
        KPI rows per replica, paired by position.

    Returns
    -------
    Cell
        The checks, every KPI's interval and the idle check.
    """
    label = f"{scenario}|{arm.label}"
    diffs = {name: interval(name, without, with_arm, label) for name in KPIS}
    diffs[ELEC_SHARE.name] = interval(ELEC_SHARE.name, without, with_arm, label)
    checks = tuple(
        Check(c.name, diffs[c.kpi], plangate.outcome(diffs[c.kpi], c.margin), c.margin)
        for c in CRITERIA
    )
    idle: bool | None = None
    if SCENARIOS[scenario].must_idle and not arm.calibration:
        idle = all(r["boost_h"] == 0.0 and r["setback_h"] == 0.0 for r in with_arm)
    return Cell(scenario, checks, diffs, idle)


@dataclass(frozen=True, slots=True)
class Verdict:
    """The verdict of an arm over every scenario.

    Parameters
    ----------
    arm
        The arm.
    cells
        One per scenario.
    """

    arm: Arm
    cells: tuple[Cell, ...]

    @property
    def outcome(self) -> Outcome:
        """``FAIL`` if any cell fails, else ``INCONCLUSIVE`` if any is, else ``PASS``."""
        found = {c.outcome for c in self.cells}
        if Outcome.FAILED in found:
            return Outcome.FAILED
        if Outcome.INCONCLUSIVE in found:
            return Outcome.INCONCLUSIVE
        return Outcome.PASSED

    @property
    def passed(self) -> bool:
        """Whether the arm passes the gate."""
        return self.outcome is Outcome.PASSED

    def listed(self, outcome: Outcome) -> tuple[str, ...]:
        """Return ``scenario [criteria]`` for every cell with checks of this outcome."""
        out = []
        for cell in self.cells:
            names = cell.named(outcome)
            if names:
                out.append(f"{cell.scenario} [{', '.join(names)}]")
        return tuple(out)

    def cell(self, scenario: str) -> Cell:
        """Return the cell of a scenario."""
        return next(c for c in self.cells if c.scenario == scenario)

    def comfort_failed(self) -> bool:
        """Whether a comfort criterion fails in any scenario."""
        return any(
            c.outcome is Outcome.FAILED and c.criterion in COMFORT_CRITERIA
            for cell in self.cells
            for c in cell.checks
        )


def verdict(
    arm: Arm,
    rows: Mapping[str, tuple[Sequence[Row], Sequence[Row]]],
) -> Verdict:
    """Return the verdict of an arm from its rows per scenario.

    Parameters
    ----------
    arm
        The arm.
    rows
        ``(baseline rows, arm rows)`` per scenario, paired by replica.

    Returns
    -------
    Verdict
        Its cells in the order of ``rows``.
    """
    return Verdict(arm, tuple(judge(s, arm, w, p) for s, (w, p) in rows.items()))


@dataclass(frozen=True, slots=True)
class Benefit:
    """The owner's goal in the intended scenario, as paired differences.

    Parameters
    ----------
    night_run_h
        Compressor run time 23:00 to 07:00 (negative: less).
    night_elec_kwh, day_elec_kwh
        Electricity at night and in the occupied hours.
    below_occ_kh
        Degree-hours below comfort in the occupied hours (negative: warmer).
    quiet_nights
        Nights without a compressor run.
    """

    night_run_h: Interval
    night_elec_kwh: Interval
    day_elec_kwh: Interval
    below_occ_kh: Interval
    quiet_nights: Interval

    @property
    def less_night_running(self) -> bool:
        """Whether the night run time falls (upper bound of its interval below zero)."""
        return self.night_run_h.high < 0.0

    @property
    def shifted_kwh(self) -> float:
        """Electricity moved out of the night (positive: less at night)."""
        return -self.night_elec_kwh.estimate


def benefit(cell: Cell) -> Benefit:
    """Return the benefit numbers of a cell."""
    d = cell.diffs
    return Benefit(
        d["night_run_h"],
        d["night_elec_kwh"],
        d["day_elec_kwh"],
        d["below_occ_kh"],
        d["quiet_nights"],
    )


def calibration_lines(verdicts: Mapping[str, Verdict]) -> list[str]:
    """Return the calibration result in plain sentences (and whether it is as expected).

    Parameters
    ----------
    verdicts
        Verdict of every arm by label; the ``none`` and ``noise`` arms calibrate the gate.
    """
    out = []
    none = verdicts.get("none")
    if none is not None:
        zero = all(
            iv.estimate == 0.0 and iv.low == 0.0 and iv.high == 0.0
            for cell in none.cells
            for iv in cell.diffs.values()
            if not math.isnan(iv.estimate)
        )
        state = "as expected" if none.passed and zero else "NOT as expected"
        out.append(
            f"none (a provider that never plans): {none.outcome.value}, every paired "
            f"difference exactly zero: {zero} ({state})."
        )
    noise = verdicts.get("noise")
    if noise is not None:
        inc = noise.listed(Outcome.INCONCLUSIVE)
        fail = noise.listed(Outcome.FAILED)
        out.append(
            f"noise (another sensor-noise seed, no plan): {noise.outcome.value}; "
            f"{len(fail)} scenarios FAIL, {len(inc)} INCONCLUSIVE"
            + (f" ({'; '.join(inc + fail)})" if inc or fail else "")
            + "."
        )
    const = verdicts.get("const_setback")
    if const is not None:
        failing = [
            cell.scenario
            for cell in const.cells
            if any(
                c.outcome is Outcome.FAILED and c.criterion in COMFORT_CRITERIA for c in cell.checks
            )
        ]
        state = "as expected" if len(failing) == len(const.cells) else "NOT as expected"
        out.append(
            f"const_setback (-1 K day and night): FAILs comfort in {len(failing)} of "
            f"{len(const.cells)} scenarios ({state})."
        )
    return out


def calibrated(verdicts: Mapping[str, Verdict]) -> bool:
    """Whether the gate behaves as required: ``none`` passes and ``const_setback`` fails comfort."""
    none = verdicts.get("none")
    const = verdicts.get("const_setback")
    if none is None or const is None:
        return False
    every = all(
        any(c.outcome is Outcome.FAILED and c.criterion in COMFORT_CRITERIA for c in cell.checks)
        for cell in const.cells
    )
    return none.passed and every


def mean_rows(rows: Sequence[Row]) -> dict[str, float]:
    """Return the mean of every KPI over replicas."""
    return {name: float(np.nanmean([r[name] for r in rows])) for name in KPIS}

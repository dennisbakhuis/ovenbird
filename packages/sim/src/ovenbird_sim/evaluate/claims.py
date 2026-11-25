"""Baseline gate, paired differences and the refuse-to-claim rules (``docs/design.md``).

Baseline gate
    The fitted plant driven by the recorded applied water setpoints (whatever wrote
    them, :class:`~ovenbird_sim.evaluate.closedloop.RecordedSetpoints`) must
    reproduce the measurements over the same days: mean daily heat within ±10 %,
    heating starts per day within ±20 % and room RMSE within a stated bound
    (:data:`ROOM_RMSE_BOUND_K`, about twice the plant's held-out 24 h free-run
    error). It is applied twice: in-sample (all days, parameters fitted on all days)
    and held-out on rolling-origin folds (the last blocks, each tested with
    parameters fitted on the days before it only; every fold must pass). Failing
    either, every comparison is still computed but marked ``not_claimable``.

Paired differences
    ``ovenbird - baseline`` per KPI, at the point estimate and per bootstrap
    replicate of the plant parameters (both runs on the same replicate);
    the interval is the replicates' 5th to 95th percentile. It covers parameter
    uncertainty only, not the model's structure or the weather.

Refuse to claim
    A difference is refused when its interval spans zero, when either run leaves
    the recorded envelope (setpoints or room temperatures outside what was
    recorded for more than :data:`ENVELOPE_TOLERANCE` of the time: the plant model
    was never validated there), when an energy claim is not at matched comfort
    (the interval of the degree-hours-below-band difference excludes zero, in
    either direction: "equal comfort" is matched degree-hours below the band), and
    always for claims that need data not recorded for the period
    (:data:`UNRECORDED_CLAIMS`). Electricity and COP are refused when either run
    spends too much of its heat outside the joint support of the COP map
    (:mod:`ovenbird_sim.evaluate.support`). Beyond the gate, a KPI is refused when the
    baseline misses its recorded value by more than its tolerance in
    :data:`FIDELITY` (the baseline does not reproduce that outcome, so a difference
    in it says nothing about the real house), in-sample or held-out.

Cycling fidelity
    Electricity, COP, starts and the run-length KPIs (:data:`CYCLING_DEPENDENT`)
    all follow from how the pump cycles. They are refused together when the
    baseline misses any of :data:`CYCLING_FIDELITY` - electricity ±5 %, starts
    ±10 %, median run length ±20 %, share of runs under 20 min ±0.05 - in-sample
    or held-out: a plant that cycles differently from the house cannot say how much
    a controller changes cycling.

Equal comfort
    Every outcome claim needs matched comfort (:class:`ComfortMatch`): ovenbird's
    room target is calibrated so its mean room temperature equals the baseline's,
    and the remaining differences in the mean (±:data:`MEAN_TOLERANCE_K`), the
    occupied-hours 10th percentile (±:data:`P10_TOLERANCE_K`) and the degree-hours
    below the baseline's 10th percentile (±25 % of the baseline's own, at least
    :data:`DH_TOLERANCE_MIN` K·h/day) must be within tolerance.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import numpy as np

from ovenbird_core.control.record import JsonDict

HEAT_BOUND: Final = 0.10
STARTS_BOUND: Final = 0.20
ELEC_TOLERANCE: Final = 0.05
STARTS_TOLERANCE: Final = 0.10
RUN_MEDIAN_TOLERANCE: Final = 0.20
SHORT_RUN_TOLERANCE: Final = 0.05
MEAN_TOLERANCE_K: Final = 0.05
P10_TOLERANCE_K: Final = 0.10
DH_TOLERANCE_SHARE: Final = 0.25
DH_TOLERANCE_MIN: Final = 0.05
ROOM_RMSE_BOUND_K: Final = 0.5
ENVELOPE_TOLERANCE: Final = 0.01
ROOM_ENVELOPE_MARGIN_K: Final = 0.25
INTERVAL_LEVEL: Final = 0.90
ENERGY_KPIS: Final = frozenset({"heat_kwh_per_day", "elec_kwh_per_day", "cop"})
COP_MAP_KPIS: Final = frozenset({"elec_kwh_per_day", "cop"})
COMFORT_KPI: Final = "degree_hours_below_per_day"
FIDELITY: Final[Mapping[str, tuple[str, float]]] = {
    "heat_kwh_per_day": ("relative", HEAT_BOUND),
    "elec_kwh_per_day": ("relative", ELEC_TOLERANCE),
    "cop": ("relative", ELEC_TOLERANCE),
    "starts_per_day": ("relative", STARTS_TOLERANCE),
    "short_run_share": ("absolute", SHORT_RUN_TOLERANCE),
    "run_median_min": ("relative", RUN_MEDIAN_TOLERANCE),
    "room_mean_c": ("absolute", 0.30),
    "room_min_c": ("absolute", 0.50),
    "degree_hours_below_per_day": ("relative", 0.50),
    "writes_per_day": ("relative", 0.30),
    "defrost_min_per_day": ("relative", 0.30),
}
CYCLING_FIDELITY: Final = (
    "elec_kwh_per_day",
    "starts_per_day",
    "run_median_min",
    "short_run_share",
)
CYCLING_DEPENDENT: Final = frozenset(
    {
        "elec_kwh_per_day",
        "cop",
        "starts_per_day",
        "short_run_share",
        "run_median_min",
        "defrost_min_per_day",
    }
)
COMFORT_KPIS: Final = frozenset(
    {"room_mean_c", "room_min_c", "degree_hours_below_per_day", "room_p10_c"}
)
UNRECORDED_CLAIMS: Final[Mapping[str, str]] = {
    "energy_cost": "no tariff or price data was recorded for this period",
    "pv_self_consumption": "PV production covers about a third of the period only",
    "grid_import": "grid import depends on the household load; only the pump's own "
    "electricity estimate is modelled",
}


class ClaimStatus(StrEnum):
    """Whether a difference may be claimed."""

    CLAIMABLE = "claimable"
    REFUSED = "refused"
    NOT_CLAIMABLE = "not_claimable"


@dataclass(frozen=True, slots=True)
class GateBounds:
    """Tolerances of the baseline gate.

    Parameters
    ----------
    heat
        Relative tolerance on mean daily heat.
    starts
        Relative tolerance on starts per day.
    room_rmse_k
        Bound on the room RMSE.
    """

    heat: float = HEAT_BOUND
    starts: float = STARTS_BOUND
    room_rmse_k: float = ROOM_RMSE_BOUND_K


@dataclass(frozen=True, slots=True)
class GateCriterion:
    """One gate criterion.

    Parameters
    ----------
    name
        Criterion.
    simulated, recorded
        Compared values (``recorded`` is ``NaN`` for the RMSE).
    error
        Relative error, or the RMSE itself.
    bound
        Allowed magnitude of ``error``.
    unit
        Unit of the compared values.
    """

    name: str
    simulated: float
    recorded: float
    error: float
    bound: float
    unit: str

    @property
    def passed(self) -> bool:
        """Whether the criterion holds (a ``NaN`` error fails)."""
        return math.isfinite(self.error) and abs(self.error) <= self.bound


@dataclass(frozen=True, slots=True)
class GateResult:
    """Outcome of the baseline gate.

    Parameters
    ----------
    criteria
        Criteria in report order.
    """

    criteria: tuple[GateCriterion, ...]

    @property
    def passed(self) -> bool:
        """Whether every criterion holds."""
        return all(c.passed for c in self.criteria)

    def to_json(self) -> JsonDict:
        """Return a JSON-friendly form."""
        return {
            "passed": self.passed,
            "criteria": [
                {
                    "name": c.name,
                    "simulated": _num(c.simulated),
                    "recorded": _num(c.recorded),
                    "error": _num(c.error),
                    "bound": c.bound,
                    "unit": c.unit,
                    "passed": c.passed,
                }
                for c in self.criteria
            ],
        }


def _relative(simulated: float, recorded: float) -> float:
    if not (math.isfinite(simulated) and math.isfinite(recorded)) or recorded == 0:
        return math.nan
    return (simulated - recorded) / recorded


def baseline_gate(
    simulated: Mapping[str, float],
    recorded: Mapping[str, float],
    room_rmse_k: float,
    bounds: GateBounds | None = None,
) -> GateResult:
    """Check the baseline (the plant on the recorded setpoints) against the measurements.

    Parameters
    ----------
    simulated, recorded
        Period KPIs (``heat_kwh_per_day``, ``starts_per_day``).
    room_rmse_k
        RMSE of the simulated room against the recorded one.
    bounds
        Tolerances.

    Returns
    -------
    GateResult
        The criteria and the verdict.
    """
    b = bounds or GateBounds()
    heat_sim, heat_rec = simulated["heat_kwh_per_day"], recorded["heat_kwh_per_day"]
    starts_sim, starts_rec = simulated["starts_per_day"], recorded["starts_per_day"]
    return GateResult(
        (
            GateCriterion(
                "daily_heat", heat_sim, heat_rec, _relative(heat_sim, heat_rec), b.heat, "kWh/day"
            ),
            GateCriterion(
                "starts_per_day",
                starts_sim,
                starts_rec,
                _relative(starts_sim, starts_rec),
                b.starts,
                "1/day",
            ),
            GateCriterion("room_rmse", room_rmse_k, math.nan, room_rmse_k, b.room_rmse_k, "K"),
        )
    )


@dataclass(frozen=True, slots=True)
class Fidelity:
    """How well the baseline reproduces one recorded KPI.

    Parameters
    ----------
    kpi
        KPI name.
    simulated, recorded
        Period values.
    error
        Relative or absolute error (see ``kind``).
    kind
        ``relative`` or ``absolute``.
    tolerance
        Allowed magnitude of ``error``.
    """

    kpi: str
    simulated: float
    recorded: float
    error: float
    kind: str
    tolerance: float

    @property
    def ok(self) -> bool:
        """Whether the error is within the tolerance (``NaN`` fails)."""
        return math.isfinite(self.error) and abs(self.error) <= self.tolerance

    def reason(self) -> str:
        """Refusal reason when not ok."""
        unit = "%" if self.kind == "relative" else ""
        scale = 100.0 if self.kind == "relative" else 1.0
        return (
            f"baseline does not reproduce it: simulated {self.simulated:.3g} vs "
            f"recorded {self.recorded:.3g} ({scale * self.error:+.3g}{unit}, tolerance "
            f"{scale * self.tolerance:.3g}{unit})"
        )

    def to_json(self) -> JsonDict:
        """Return a JSON-friendly form."""
        return {
            "kpi": self.kpi,
            "simulated": _num(self.simulated),
            "recorded": _num(self.recorded),
            "error": _num(self.error),
            "kind": self.kind,
            "tolerance": self.tolerance,
            "ok": self.ok,
        }


def fidelity(simulated: Mapping[str, float], recorded: Mapping[str, float]) -> dict[str, Fidelity]:
    """Compare the baseline with the recording per KPI (see :data:`FIDELITY`)."""
    out: dict[str, Fidelity] = {}
    for name, (kind, tolerance) in FIDELITY.items():
        sim, rec = simulated.get(name, math.nan), recorded.get(name, math.nan)
        error = _relative(sim, rec) if kind == "relative" else sim - rec
        out[name] = Fidelity(name, sim, rec, error, kind, tolerance)
    return out


def cycling_reasons(
    in_sample: Mapping[str, Fidelity],
    held_out: Mapping[str, Fidelity] | None = None,
    folds: Sequence[tuple[str, Mapping[str, Fidelity]]] = (),
) -> list[str]:
    """Failures of :data:`CYCLING_FIDELITY` as refusal reasons.

    Parameters
    ----------
    in_sample
        In-sample fidelity.
    held_out
        Held-out fidelity of a single test block (labelled ``held-out``).
    folds
        ``(label, fidelity)`` of every rolling-origin fold.

    Returns
    -------
    list of str
        One reason per failing KPI and block.
    """
    out = []
    blocks = [("in-sample", in_sample), ("held-out", held_out or {}), *folds]
    for label, checks in blocks:
        for name in CYCLING_FIDELITY:
            check = checks.get(name)
            if check is not None and not check.ok:
                out.append(f"cycling not reproduced ({label}, {name}): {check.reason()}")
    return out


@dataclass(frozen=True, slots=True)
class ComfortMatch:
    """Comfort of ovenbird against the baseline after calibrating ovenbird's target.

    Differences are ``ovenbird - baseline`` at the point estimate with the 90 %
    interval over the replicates.

    Parameters
    ----------
    calibrated_target_c
        Ovenbird room target that matches the baseline's mean room temperature.
    mean, p10, dh
        ``(point, lo, hi)`` of the mean room temperature, the occupied-hours 10th
        percentile and the degree-hours per day below the baseline's 10th percentile.
    baseline_dh
        The baseline's own degree-hours per day below its 10th percentile.
    baseline_mean_c, baseline_p10_c
        Baseline mean and 10th percentile at the point estimate.
    """

    calibrated_target_c: float
    mean: tuple[float, float, float]
    p10: tuple[float, float, float]
    dh: tuple[float, float, float]
    baseline_dh: float
    baseline_mean_c: float
    baseline_p10_c: float

    @property
    def dh_tolerance(self) -> float:
        """Allowed degree-hours difference."""
        base = self.baseline_dh if math.isfinite(self.baseline_dh) else 0.0
        return max(DH_TOLERANCE_SHARE * base, DH_TOLERANCE_MIN)

    def _checks(self) -> tuple[tuple[str, float, float, str], ...]:
        return (
            ("mean room temperature", self.mean[0], MEAN_TOLERANCE_K, "K"),
            ("occupied-hours P10", self.p10[0], P10_TOLERANCE_K, "K"),
            ("degree-hours below the baseline P10", self.dh[0], self.dh_tolerance, "K·h/day"),
        )

    @property
    def worst(self) -> float:
        """Largest point difference as a multiple of its tolerance (matched at <= 1)."""
        ratios = [abs(value) / tolerance for _, value, tolerance, _ in self._checks()]
        return max(ratios) if all(math.isfinite(r) for r in ratios) else math.inf

    def reasons(self) -> list[str]:
        """Why comfort is not matched (empty when it is)."""
        out = []
        for name, value, tolerance, unit in self._checks():
            if not (math.isfinite(value) and abs(value) <= tolerance):
                out.append(
                    f"comfort not matched: {name} differs by {value:+.3f} {unit} "
                    f"(tolerance ±{tolerance:.3f})"
                )
        return out

    @property
    def matched(self) -> bool:
        """Whether every comfort difference is within tolerance."""
        return not self.reasons()

    def to_json(self) -> JsonDict:
        """Return a JSON-friendly form."""

        def triple(values: tuple[float, float, float]) -> JsonDict:
            return {"point": _num(values[0]), "lo": _num(values[1]), "hi": _num(values[2])}

        return {
            "calibrated_target_c": _num(self.calibrated_target_c),
            "mean_delta_k": triple(self.mean),
            "p10_delta_k": triple(self.p10),
            "dh_below_baseline_p10_delta": triple(self.dh),
            "baseline_dh_below_own_p10": _num(self.baseline_dh),
            "baseline_mean_c": _num(self.baseline_mean_c),
            "baseline_p10_c": _num(self.baseline_p10_c),
            "tolerances": {
                "mean_k": MEAN_TOLERANCE_K,
                "p10_k": P10_TOLERANCE_K,
                "dh_k_h_per_day": self.dh_tolerance,
            },
            "matched": self.matched,
            "reasons": list(self.reasons()),
        }


@dataclass(frozen=True, slots=True)
class Envelope:
    """The recorded operating envelope and a run's share of time outside it.

    Parameters
    ----------
    setpoint_range
        Lowest and highest recorded applied setpoint.
    room_range
        Lowest and highest recorded room temperature.
    setpoint_outside
        Share of ticks with an applied setpoint outside ``setpoint_range``.
    room_outside
        Share of ticks with the room more than :data:`ROOM_ENVELOPE_MARGIN_K`
        outside ``room_range``.
    setpoint_below, setpoint_above
        Shares below and above the setpoint range.
    """

    setpoint_range: tuple[float, float]
    room_range: tuple[float, float]
    setpoint_outside: float
    room_outside: float
    setpoint_below: float = 0.0
    setpoint_above: float = 0.0

    def left(self, tolerance: float = ENVELOPE_TOLERANCE) -> list[str]:
        """Reasons the run left the envelope (empty when it stayed inside)."""
        out = []
        if self.setpoint_outside > tolerance:
            lo, hi = self.setpoint_range
            out.append(
                f"setpoint outside the recorded {lo:g}-{hi:g} °C for "
                f"{100 * self.setpoint_outside:.1f} % of the time "
                f"({100 * self.setpoint_below:.1f} % below, "
                f"{100 * self.setpoint_above:.1f} % above)"
            )
        if self.room_outside > tolerance:
            lo, hi = self.room_range
            out.append(
                f"room outside the recorded {lo:.1f}-{hi:.1f} °C for "
                f"{100 * self.room_outside:.1f} % of the time"
            )
        return out

    def to_json(self) -> JsonDict:
        """Return a JSON-friendly form."""
        return {
            "setpoint_range": list(self.setpoint_range),
            "room_range": list(self.room_range),
            "setpoint_outside_share": self.setpoint_outside,
            "setpoint_below_share": self.setpoint_below,
            "setpoint_above_share": self.setpoint_above,
            "room_outside_share": self.room_outside,
        }


def envelope(
    setpoint: np.ndarray,
    room: np.ndarray,
    setpoint_range: tuple[float, float],
    room_range: tuple[float, float],
) -> Envelope:
    """Measure a run against the recorded envelope.

    Parameters
    ----------
    setpoint, room
        Per-tick applied setpoint and room temperature of the run.
    setpoint_range, room_range
        Recorded ranges.

    Returns
    -------
    Envelope
        Shares outside.
    """
    lo, hi = setpoint_range
    rlo, rhi = room_range
    below = float(np.mean(setpoint < lo)) if setpoint.size else 0.0
    above = float(np.mean(setpoint > hi)) if setpoint.size else 0.0
    room_out = (
        float(
            np.mean((room < rlo - ROOM_ENVELOPE_MARGIN_K) | (room > rhi + ROOM_ENVELOPE_MARGIN_K))
        )
        if room.size
        else 0.0
    )
    return Envelope(setpoint_range, room_range, below + above, room_out, below, above)


def interval(samples: Sequence[float], level: float = INTERVAL_LEVEL) -> tuple[float, float]:
    """Central percentile interval of finite samples (``NaN`` without any)."""
    values = np.asarray([s for s in samples if math.isfinite(s)], dtype=np.float64)
    if values.size == 0:
        return math.nan, math.nan
    tail = (1.0 - level) / 2.0 * 100.0
    lo, hi = np.percentile(values, [tail, 100.0 - tail])
    return float(lo), float(hi)


@dataclass(frozen=True, slots=True)
class Difference:
    """A paired difference ``ovenbird - baseline`` with its claim status.

    Parameters
    ----------
    kpi
        KPI name.
    point
        Difference at the point-estimate parameters.
    lo, hi
        90 % interval over the bootstrap replicates (``NaN`` without replicates).
    n
        Number of replicates.
    status
        Claim status.
    reasons
        Why it is refused or not claimable.
    """

    kpi: str
    point: float
    lo: float
    hi: float
    n: int
    status: ClaimStatus
    reasons: tuple[str, ...]

    def to_json(self) -> JsonDict:
        """Return a JSON-friendly form."""
        return {
            "kpi": self.kpi,
            "point": _num(self.point),
            "lo": _num(self.lo),
            "hi": _num(self.hi),
            "n": self.n,
            "status": self.status.value,
            "reasons": list(self.reasons),
        }


def spans_zero(lo: float, hi: float) -> bool:
    """Whether ``[lo, hi]`` contains zero (an unknown interval counts as spanning)."""
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return True
    return lo <= 0.0 <= hi


def judge(
    kpi: str,
    point: float,
    samples: Sequence[float],
    *,
    gate_passed: bool,
    envelope_reasons: Sequence[str],
    comfort_interval: tuple[float, float] | None,
    baseline: Fidelity | None = None,
    level: float = INTERVAL_LEVEL,
    held_out_passed: bool | None = None,
    held_out_baseline: Fidelity | None = None,
    cycling: Sequence[str] = (),
    comfort: ComfortMatch | None = None,
    held_out_folds: Sequence[tuple[str, Fidelity]] = (),
    cop_support: Sequence[str] = (),
) -> Difference:
    """Apply the gate and the refuse-to-claim rules to one KPI difference.

    Parameters
    ----------
    kpi
        KPI name.
    point
        Point-estimate difference.
    samples
        Differences per bootstrap replicate.
    gate_passed
        Baseline gate verdict.
    envelope_reasons
        Envelope violations of either run (empty when inside).
    comfort_interval
        Interval of the degree-hours-below difference (for energy KPIs).
    baseline
        How well the baseline reproduces this KPI.
    level
        Interval level.
    held_out_passed
        Held-out baseline gate verdict (``None``: not run).
    held_out_baseline
        Fidelity of this KPI on the held-out block.
    cycling
        Cycling-fidelity failures (:func:`cycling_reasons`); they refuse the
        :data:`CYCLING_DEPENDENT` KPIs.
    comfort
        Comfort match; outcome claims other than the comfort KPIs need it matched.
    held_out_folds
        ``(label, fidelity)`` of this KPI in every rolling-origin fold.
    cop_support
        Runs whose operating points leave the COP map's joint support; they refuse
        :data:`COP_MAP_KPIS`.

    Returns
    -------
    Difference
        The difference with its status and reasons.
    """
    lo, hi = interval(samples, level)
    reasons: list[str] = []
    if not gate_passed:
        reasons.append("baseline gate failed")
    held_out_failed = held_out_passed is False
    if held_out_failed:
        reasons.append("held-out baseline gate failed")
    if spans_zero(lo, hi):
        reasons.append(
            "no bootstrap interval" if not math.isfinite(lo) else "90 % interval spans zero"
        )
    if baseline is not None and not baseline.ok:
        reasons.append(baseline.reason())
    if held_out_baseline is not None and not held_out_baseline.ok:
        reasons.append(f"held-out: {held_out_baseline.reason()}")
    reasons.extend(f"{label}: {check.reason()}" for label, check in held_out_folds if not check.ok)
    if kpi in CYCLING_DEPENDENT:
        reasons.extend(cycling)
    if kpi in COP_MAP_KPIS:
        reasons.extend(cop_support)
    if comfort is not None and kpi not in COMFORT_KPIS:
        reasons.extend(comfort.reasons())
    reasons.extend(f"leaves the recorded envelope: {r}" for r in envelope_reasons)
    if kpi in ENERGY_KPIS and comfort_interval is not None and not spans_zero(*comfort_interval):
        side = "more" if comfort_interval[0] > 0.0 else "fewer"
        reasons.append(f"comfort not matched: {side} degree-hours below the band")
    if not gate_passed or held_out_failed:
        status = ClaimStatus.NOT_CLAIMABLE
    elif reasons:
        status = ClaimStatus.REFUSED
    else:
        status = ClaimStatus.CLAIMABLE
    finite = [s for s in samples if math.isfinite(s)]
    return Difference(kpi, point, lo, hi, len(finite), status, tuple(reasons))


def _num(value: float) -> float | None:
    return value if math.isfinite(value) else None

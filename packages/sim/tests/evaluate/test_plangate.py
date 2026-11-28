"""The paired-replica gate: margins, the starts extension, the combined verdict, the bootstrap."""

import numpy as np
import pytest

from ovenbird_sim.evaluate import plangate
from ovenbird_sim.evaluate.plangate import CRITERION, Outcome

PASS, FAIL, INCONCLUSIVE = Outcome.PASSED, Outcome.FAILED, Outcome.INCONCLUSIVE


def _rows(n: int, **values: float) -> list[dict[str, float]]:
    """Return ``n`` identical KPI rows with typical values, overridden by ``values``."""
    row = dict.fromkeys(plangate.ROW_KPIS, 0.0)
    row.update(starts_per_day=2.0, below_kh=1.0, above_kh=3.0, elec_kwh_per_day=10.0)
    row.update(writes_per_day=10.0)
    row.update(values)
    return [dict(row) for _ in range(n)]


def _shifted(
    rows: list[dict[str, float]], name: str, deltas: list[float]
) -> list[dict[str, float]]:
    """Return ``rows`` with ``deltas`` added to the KPI ``name``, row by row."""
    return [{**r, name: r[name] + d} for r, d in zip(rows, deltas, strict=True)]


@pytest.mark.parametrize(
    ("name", "delta", "expected"),
    [
        ("below_band_kh", 0.1, PASS),
        ("below_band_kh", 0.2, FAIL),
        ("below_kh", 0.45, PASS),
        ("below_kh", 0.55, FAIL),
        ("starts_per_day", 0.4, PASS),
        ("starts_per_day", 0.6, FAIL),
        ("elec_kwh_per_day", 0.15, PASS),
        ("elec_kwh_per_day", 0.25, FAIL),
        ("writes_per_day", 1.9, PASS),
        ("writes_per_day", 2.1, FAIL),
    ],
)
def test_gate_margins_on_constant_differences(name: str, delta: float, expected: Outcome) -> None:
    """A constant rise of a KPI passes within its margin and fails beyond it."""
    without = _rows(24)
    verdict = plangate.judge_cell(without, _shifted(without, name, [delta] * 24), "c", 24)
    criterion = next(c for c in plangate.CRITERIA if c.kpi == name)
    assert verdict.check(criterion.name).outcome is expected
    assert verdict.outcome is expected


def test_gate_is_inconclusive_when_the_interval_straddles_the_margin() -> None:
    """A criterion whose interval straddles the margin is inconclusive and wants more replicas."""
    rng = np.random.default_rng(1)
    deltas = (0.5 + rng.normal(0.0, 1.0, 24)).tolist()
    without = _rows(24)
    verdict = plangate.judge_cell(without, _shifted(without, "below_kh", deltas), "c", 24)
    check = verdict.check("below")
    assert check.interval.low < 0.5 < check.interval.high
    assert check.outcome is INCONCLUSIVE
    assert verdict.outcome is INCONCLUSIVE
    assert not plangate.wants_extension(verdict, 24, 48)


def test_starts_extension_rule() -> None:
    """Only the starts criterion is extended to more replicas, with a wider alpha."""
    rng = np.random.default_rng(2)
    without = _rows(48)
    deltas = (0.3 + rng.normal(0.0, 1.2, 48)).tolist()
    with_plan = _shifted(without, "starts_per_day", deltas)
    first = plangate.judge_cell(without[:24], with_plan[:24], "c", 24)
    assert first.check("starts").outcome is INCONCLUSIVE
    assert first.check("starts").interval.alpha == plangate.POCOCK_ALPHA
    assert first.check("below").interval.alpha == plangate.ALPHA
    assert plangate.wants_extension(first, 24, 48)
    assert not plangate.wants_extension(first, 24, 24)
    second = plangate.judge_cell(without, with_plan, "c", 24)
    assert second.check("starts").interval.n == 48
    assert second.check("starts").extended
    assert second.check("below").interval.n == 24
    assert not second.check("below").extended
    assert not plangate.wants_extension(second, 24, 48)


def test_combined_verdict() -> None:
    """The verdict unlocks only with passing credible cells, a benefit and passing pooled checks."""
    without = _rows(24)
    good = plangate.judge_cell(without, without, "good", 24)
    bad = plangate.judge_cell(without, _shifted(without, "below_kh", [1.0] * 24), "bad", 24)
    rng = np.random.default_rng(3)
    unsure = plangate.judge_cell(
        without, _shifted(without, "below_kh", (0.5 + rng.normal(0, 1, 24)).tolist()), "u", 24
    )
    noisy_starts = _shifted(without, "starts_per_day", (0.3 + rng.normal(0, 1.5, 24)).tolist())
    unsure_cost = plangate.judge_cell(without, noisy_starts, "s", 24)
    assert unsure_cost.named(INCONCLUSIVE) == ("starts",)
    better = plangate.benefit([(without, _shifted(without, "above_kh", [-1.0] * 24))], 24)
    none = plangate.benefit([(without, without)], 24)
    pooled_ok = [plangate.pooled_check(k, [(without, without)], 24) for k in plangate.CRITERIA]
    pooled_bad = [
        plangate.pooled_check(k, [(without, _shifted(without, "starts_per_day", [1.0] * 24))], 24)
        for k in plangate.CRITERIA
    ]
    assert better.high < 0.0
    ok = plangate.combine([("a", True, good), ("b", False, unsure)], better, pooled_ok)
    assert ok.unlocked
    assert not plangate.combine([("a", True, good)], better).unlocked
    assert not plangate.combine([("a", True, good)], none, pooled_ok).unlocked
    assert not plangate.combine([("a", True, good)], better, pooled_bad).unlocked
    blocked = plangate.combine([("a", True, unsure), ("b", False, good)], better, pooled_ok)
    assert not blocked.unlocked
    assert blocked.credible_inconclusive == ("a [below]",)
    assert any("INCONCLUSIVE" in line for line in blocked.lines())
    cost_only = plangate.combine([("a", True, unsure_cost)], better, pooled_ok)
    assert cost_only.unlocked
    assert cost_only.credible_cost_inconclusive == ("a [starts]",)
    assert not plangate.combine([("a", True, good), ("b", False, bad)], better, pooled_ok).unlocked


def test_bootstrap_interval_sanity() -> None:
    """The bootstrap interval is exact for constant differences, reproducible and calibrated."""
    below = CRITERION["below"]
    flat = plangate.bootstrap(below, [1.0] * 10, [1.5] * 10, label="x")
    assert (flat.estimate, flat.low, flat.high) == (0.5, 0.5, 0.5)
    rng = np.random.default_rng(4)
    a = rng.normal(0, 1, 24).tolist()
    b = rng.normal(0, 1, 24).tolist()
    assert plangate.bootstrap(below, a, b, label="y") == plangate.bootstrap(below, a, b, label="y")
    assert np.isnan(plangate.bootstrap(below, [], []).low)
    assert plangate.expanded_alpha(0.05, 24) == pytest.approx(0.0346, abs=5e-4)
    assert plangate.expanded_alpha(0.05, 100_000) == pytest.approx(0.05, abs=1e-4)
    covered = 0
    trials = 300
    for k in range(trials):
        d = rng.normal(0.2, 1.0, 24)
        i = plangate.bootstrap(
            below, np.zeros(24).tolist(), d.tolist(), label=str(k), resamples=800
        )
        covered += i.low <= 0.2 <= i.high
    assert 0.91 <= covered / trials <= 0.99


def test_relative_criteria_use_the_baseline_mean() -> None:
    """Relative criteria divide the difference by the baseline mean."""
    writes = CRITERION["writes"]
    assert float(writes.statistic(np.array([10.0, 10.0]), np.array([12.0, 12.0]))) == pytest.approx(
        0.2
    )
    assert float(writes.statistic(np.array([0.0, 0.0]), np.array([0.5, 0.5]))) == pytest.approx(0.5)

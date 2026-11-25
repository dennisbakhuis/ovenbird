"""Baseline gate, refuse-to-claim rules, ablation arithmetic and the replicate cache."""

import math
from pathlib import Path

import numpy as np
import pytest

from ovenbird_core.control import OvenbirdConfig
from ovenbird_sim.evaluate import ablation, kpi
from ovenbird_sim.evaluate.claims import (
    COP_MAP_KPIS,
    CYCLING_DEPENDENT,
    ClaimStatus,
    ComfortMatch,
    GateBounds,
    baseline_gate,
    cycling_reasons,
    envelope,
    fidelity,
    interval,
    judge,
    spans_zero,
)
from ovenbird_sim.evaluate.ensemble import load_cached, save_cache
from ovenbird_sim.identify import io
from ovenbird_sim.model.building import BuildingParams
from ovenbird_sim.model.heatpump import HeatPumpParams
from ovenbird_sim.model.plant import PlantParams

RECORDED = {"heat_kwh_per_day": 100.0, "starts_per_day": 10.0}


def _sim(heat: float, starts: float) -> dict[str, float]:
    return {"heat_kwh_per_day": heat, "starts_per_day": starts}


@pytest.mark.parametrize(
    ("heat", "starts", "rmse", "passed"),
    [
        (109.9, 11.9, 0.49, True),
        (90.1, 8.1, 0.0, True),
        (110.1, 10.0, 0.1, False),
        (100.0, 12.1, 0.1, False),
        (100.0, 10.0, 0.51, False),
        (math.nan, 10.0, 0.1, False),
    ],
)
def test_baseline_gate_bounds(heat: float, starts: float, rmse: float, passed: bool) -> None:
    gate = baseline_gate(_sim(heat, starts), RECORDED, rmse)
    assert gate.passed is passed
    assert [c.name for c in gate.criteria] == ["daily_heat", "starts_per_day", "room_rmse"]
    assert gate.to_json()["passed"] is passed


def test_gate_bounds_are_configurable() -> None:
    gate = baseline_gate(_sim(100.0, 10.0), RECORDED, 0.6, GateBounds(room_rmse_k=0.7))
    assert gate.passed


def test_interval_and_spans_zero() -> None:
    lo, hi = interval(list(np.linspace(-1.0, 9.0, 101)))
    assert lo == pytest.approx(-0.5)
    assert hi == pytest.approx(8.5)
    assert spans_zero(lo, hi)
    assert not spans_zero(0.1, 2.0)
    assert spans_zero(math.nan, math.nan)
    assert math.isnan(interval([math.nan])[0])


def test_judge_claimable_when_every_rule_holds() -> None:
    d = judge(
        "starts_per_day",
        -5.0,
        [-6.0, -5.5, -5.0, -4.0],
        gate_passed=True,
        envelope_reasons=[],
        comfort_interval=(-0.1, 0.1),
    )
    assert d.status is ClaimStatus.CLAIMABLE
    assert d.reasons == ()
    assert d.n == 4


def test_judge_refuses_an_interval_spanning_zero() -> None:
    d = judge(
        "starts_per_day",
        -1.0,
        [-2.0, 0.5],
        gate_passed=True,
        envelope_reasons=[],
        comfort_interval=None,
    )
    assert d.status is ClaimStatus.REFUSED
    assert "90 % interval spans zero" in d.reasons


def test_judge_refuses_without_replicates() -> None:
    d = judge("cop", 0.3, [], gate_passed=True, envelope_reasons=[], comfort_interval=None)
    assert d.status is ClaimStatus.REFUSED
    assert d.reasons == ("no bootstrap interval",)


def test_failed_gate_makes_everything_not_claimable() -> None:
    d = judge(
        "starts_per_day",
        -5.0,
        [-6.0, -4.0],
        gate_passed=False,
        envelope_reasons=[],
        comfort_interval=None,
    )
    assert d.status is ClaimStatus.NOT_CLAIMABLE
    assert d.reasons[0] == "baseline gate failed"


def test_leaving_the_envelope_refuses() -> None:
    env = envelope(
        np.array([24.0, 25.0, 30.0, 37.0] * 25), np.full(100, 22.0), (25.0, 36.0), (21.5, 23.5)
    )
    assert env.setpoint_below == pytest.approx(0.25)
    assert env.setpoint_above == pytest.approx(0.25)
    assert env.room_outside == 0.0
    reasons = env.left()
    assert len(reasons) == 1
    d = judge(
        "starts_per_day",
        -5.0,
        [-6.0, -4.0],
        gate_passed=True,
        envelope_reasons=reasons,
        comfort_interval=None,
    )
    assert d.status is ClaimStatus.REFUSED
    assert d.reasons[0].startswith("leaves the recorded envelope")
    inside = envelope(np.full(100, 30.0), np.full(100, 23.7), (25.0, 36.0), (21.5, 23.5))
    assert inside.left() == []


@pytest.mark.parametrize(
    ("kpi", "comfort", "refused"),
    [
        ("elec_kwh_per_day", (0.2, 1.0), True),
        ("heat_kwh_per_day", (-1.0, -0.2), True),
        ("elec_kwh_per_day", (-0.2, 0.3), False),
        ("starts_per_day", (0.2, 1.0), False),
    ],
)
def test_energy_claims_need_matched_comfort(
    kpi: str, comfort: tuple[float, float], refused: bool
) -> None:
    d = judge(
        kpi, -1.0, [-2.0, -1.5], gate_passed=True, envelope_reasons=[], comfort_interval=comfort
    )
    assert (d.status is ClaimStatus.REFUSED) is refused
    assert any("comfort not matched" in r for r in d.reasons) is refused


def test_baseline_fidelity_refuses_unreproduced_kpis() -> None:
    checks = fidelity(
        {"short_run_share": 0.6, "elec_kwh_per_day": 10.4, "room_mean_c": 22.1},
        {"short_run_share": 0.07, "elec_kwh_per_day": 10.0, "room_mean_c": 22.0},
    )
    assert not checks["short_run_share"].ok
    assert checks["elec_kwh_per_day"].ok
    assert checks["room_mean_c"].ok
    assert not checks["writes_per_day"].ok
    d = judge(
        "short_run_share",
        -0.5,
        [-0.6, -0.4],
        gate_passed=True,
        envelope_reasons=[],
        comfort_interval=None,
        baseline=checks["short_run_share"],
    )
    assert d.status is ClaimStatus.REFUSED
    assert "baseline does not reproduce it" in d.reasons[0]


def test_ablation_combinations_and_configs() -> None:
    combos = ablation.combos()
    assert len(set(combos)) == 16
    assert combos[0] == (True, True, True, True)
    assert combos[-1] == (False, False, False, False)
    base = OvenbirdConfig.preset("mixed")
    off = ablation.ablated(base, combos[-1])
    assert not off.ramp.enabled
    assert not off.cycling.enabled
    assert off.feedback.kp == 0.0
    assert off.stages.dwell_s == 0.0
    assert off.stages.deadband_k == base.stages.deadband_k
    assert ablation.ablated(base, combos[0]) == base
    assert ablation.label(combos[0]) == "+ramp+fb+dwell+cyc"


def test_ablation_main_effects_and_residual() -> None:
    weights = dict(zip(ablation.TERMS, (1.0, -2.0, 0.5, 3.0), strict=True))

    def additive(combo: ablation.Combo) -> float:
        return sum(w for w, on in zip(weights.values(), combo, strict=True) if on)

    effects = ablation.contributions({c: additive(c) for c in ablation.combos()})
    for name, weight in weights.items():
        assert effects[name] == pytest.approx(weight)
    assert effects[ablation.RESIDUAL] == pytest.approx(0.0)

    def interacting(combo: ablation.Combo) -> float:
        return additive(combo) + (4.0 if combo[0] and combo[3] else 0.0)

    results = {c: interacting(c) for c in ablation.combos()}
    effects = ablation.contributions(results)
    assert effects["start_ramp"] == pytest.approx(5.0)
    assert effects["cycling"] == pytest.approx(7.0)
    assert effects[ablation.RESIDUAL] == pytest.approx(-4.0)
    mains = ablation.main_effects(results)
    assert mains["start_ramp"] == pytest.approx(3.0)
    assert mains["cycling"] == pytest.approx(5.0)
    with pytest.raises(ValueError, match="missing"):
        ablation.contributions({})


def test_replicate_cache_round_trip(tmp_path: Path) -> None:
    point = PlantParams(HeatPumpParams(), BuildingParams())
    params_path = io.save(tmp_path / "plant_params.json", point)
    replicates = [
        PlantParams(HeatPumpParams(k0=250.0 + i), BuildingParams(h_air_out=200.0 + i))
        for i in range(3)
    ]
    save_cache(params_path, replicates, seed=1)
    assert load_cached(params_path, 2, seed=1) == replicates[:2]
    assert load_cached(params_path, 4, seed=1) is None
    assert load_cached(params_path, 2, seed=2) is None
    io.save(params_path, PlantParams(HeatPumpParams(k0=1.0), BuildingParams()))
    assert load_cached(params_path, 2, seed=1) is None


GOOD_CYCLING = {
    "heat_kwh_per_day": 70.0,
    "elec_kwh_per_day": 14.0,
    "cop": 5.0,
    "starts_per_day": 7.7,
    "run_median_min": 57.0,
    "short_run_share": 0.07,
}


@pytest.mark.parametrize(
    ("name", "simulated", "fails"),
    [
        ("elec_kwh_per_day", 14.6, False),
        ("elec_kwh_per_day", 14.8, True),
        ("starts_per_day", 8.4, False),
        ("starts_per_day", 8.6, True),
        ("run_median_min", 68.0, False),
        ("run_median_min", 69.0, True),
        ("short_run_share", 0.115, False),
        ("short_run_share", 0.125, True),
    ],
)
def test_cycling_fidelity_tolerances(name: str, simulated: float, fails: bool) -> None:
    checks = fidelity(GOOD_CYCLING | {name: simulated}, GOOD_CYCLING)
    assert bool(cycling_reasons(checks)) is fails


def test_cycling_failure_refuses_electricity_cop_and_starts_but_not_heat() -> None:
    in_sample = fidelity(GOOD_CYCLING, GOOD_CYCLING)
    held_out = fidelity(GOOD_CYCLING | {"short_run_share": 0.64}, GOOD_CYCLING)
    reasons = cycling_reasons(in_sample, held_out)
    assert reasons
    assert all("held-out" in r for r in reasons)
    for name in ("elec_kwh_per_day", "cop", "starts_per_day", "heat_kwh_per_day"):
        d = judge(
            name,
            -1.0,
            [-1.2, -0.8],
            gate_passed=True,
            envelope_reasons=[],
            comfort_interval=None,
            cycling=reasons,
        )
        assert (d.status is ClaimStatus.REFUSED) is (name in CYCLING_DEPENDENT)


def test_held_out_gate_failure_makes_everything_not_claimable() -> None:
    d = judge(
        "heat_kwh_per_day",
        -1.0,
        [-1.2, -0.8],
        gate_passed=True,
        envelope_reasons=[],
        comfort_interval=None,
        held_out_passed=False,
    )
    assert d.status is ClaimStatus.NOT_CLAIMABLE
    assert "held-out baseline gate failed" in d.reasons
    held = fidelity({"heat_kwh_per_day": 80.0}, {"heat_kwh_per_day": 70.0})
    d = judge(
        "heat_kwh_per_day",
        -1.0,
        [-1.2, -0.8],
        gate_passed=True,
        envelope_reasons=[],
        comfort_interval=None,
        held_out_passed=True,
        held_out_baseline=held["heat_kwh_per_day"],
    )
    assert d.status is ClaimStatus.REFUSED
    assert d.reasons[0].startswith("held-out: baseline does not reproduce it")


def _comfort(mean: float, p10: float, dh: float, baseline_dh: float = 0.4) -> ComfortMatch:
    return ComfortMatch(
        21.7, (mean, mean, mean), (p10, p10, p10), (dh, dh, dh), baseline_dh, 22.0, 21.5
    )


@pytest.mark.parametrize(
    ("mean", "p10", "dh", "matched"),
    [
        (0.0, 0.0, 0.0, True),
        (0.039, -0.099, 0.099, True),
        (0.06, 0.0, 0.0, False),
        (0.0, -0.11, 0.0, False),
        (0.0, 0.0, 0.11, False),
        (0.0, 0.0, -0.11, False),
    ],
)
def test_comfort_match_tolerances(mean: float, p10: float, dh: float, matched: bool) -> None:
    match = _comfort(mean, p10, dh)
    assert match.dh_tolerance == pytest.approx(0.1)
    assert match.matched is matched
    d = judge(
        "elec_kwh_per_day",
        -1.0,
        [-1.2, -0.8],
        gate_passed=True,
        envelope_reasons=[],
        comfort_interval=None,
        comfort=match,
    )
    assert (d.status is ClaimStatus.CLAIMABLE) is matched
    room = judge(
        "room_mean_c",
        0.1,
        [0.05, 0.2],
        gate_passed=True,
        envelope_reasons=[],
        comfort_interval=None,
        comfort=match,
    )
    assert not any("comfort not matched" in r for r in room.reasons)
    assert _comfort(0.0, 0.0, 0.0, baseline_dh=0.0).dh_tolerance == pytest.approx(0.05)
    assert match.to_json()["matched"] is matched


def test_comfort_statistics_and_threshold() -> None:
    hours = np.tile(np.arange(24.0), 2)
    room = np.where((hours >= 7) & (hours < 23), 21.0, 18.0)
    room[7] = 20.0
    mask = kpi.occupied(hours)
    assert mask.sum() == 32
    own = kpi.comfort(room, mask, 3600.0)
    assert own.p10_c == pytest.approx(21.0)
    assert own.occupied_mean_c == pytest.approx((31 * 21.0 + 20.0) / 32)
    below = kpi.comfort(room, mask, 3600.0, threshold_c=21.5)
    assert below.degree_hours_below == pytest.approx((31 * 0.5 + 1.5) / 2)


def test_kpi_tables_keep_run_lengths_for_subsets_and_resamples() -> None:
    day = dict.fromkeys(kpi.DAY_KPIS, 1.0) | {"room_mean_c": 21.0, "room_min_c": 20.0}
    runs = {"2026-11-01": (600.0, 3600.0), "2026-11-02": (7200.0,)}
    days = {label: dict(day) for label in runs}
    table = kpi.KpiTable(days, kpi.aggregate(days, runs), runs)
    assert table.totals["run_median_min"] == pytest.approx(60.0)
    assert table.subset(["2026-11-02"]).totals["run_median_min"] == pytest.approx(120.0)
    resampled = table.resampled(["2026-11-01", "2026-11-01", "2026-11-02"])
    assert resampled["run_median_min"] == pytest.approx(60.0)
    assert resampled["heat_kwh_per_day"] == pytest.approx(1.0)


def test_every_rolling_origin_fold_is_checked() -> None:
    good = fidelity(GOOD_CYCLING, GOOD_CYCLING)
    bad = fidelity(GOOD_CYCLING | {"starts_per_day": 5.0}, GOOD_CYCLING)
    reasons = cycling_reasons(good, folds=[("fold A", good), ("fold B", bad)])
    assert len(reasons) == 1
    assert "fold B" in reasons[0]
    d = judge(
        "starts_per_day",
        -1.0,
        [-1.2, -0.8],
        gate_passed=True,
        envelope_reasons=[],
        comfort_interval=None,
        held_out_passed=True,
        held_out_folds=[("fold A", good["starts_per_day"]), ("fold B", bad["starts_per_day"])],
    )
    assert d.status is ClaimStatus.REFUSED
    assert any(r.startswith("fold B: ") for r in d.reasons)
    assert not any(r.startswith("fold A: ") for r in d.reasons)


def test_cop_support_refuses_only_cop_map_kpis() -> None:
    support = ["ovenbird: 9.0 % of the heat outside the COP map's joint support"]
    for name in ("elec_kwh_per_day", "cop", "heat_kwh_per_day", "starts_per_day"):
        d = judge(
            name,
            -1.0,
            [-1.2, -0.8],
            gate_passed=True,
            envelope_reasons=[],
            comfort_interval=None,
            cop_support=support,
        )
        assert (d.status is ClaimStatus.REFUSED) is (name in COP_MAP_KPIS)


def test_comfort_worst_is_the_largest_difference_over_its_tolerance() -> None:
    assert _comfort(0.025, -0.02, 0.01).worst == pytest.approx(0.5)
    assert _comfort(0.0, -0.15, 0.0).worst == pytest.approx(1.5)
    assert _comfort(0.0, 0.0, 0.2).worst == pytest.approx(2.0)
    assert _comfort(0.04, 0.09, 0.09).matched
    assert _comfort(math.nan, 0.0, 0.0).worst == math.inf

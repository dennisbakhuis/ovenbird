"""Planner evaluation: replicas, pairing, the three-valued gate, the bootstrap and a quick run."""

from dataclasses import replace
from itertools import pairwise

import numpy as np
import pytest

from ovenbird_core.control import OvenbirdConfig, OvenbirdController
from ovenbird_core.control.types import PlanSlice, PlanSource, ReasonCode
from ovenbird_core.instant import Instant
from ovenbird_sim.data.series import FloatArray
from ovenbird_sim.evaluate import modelplan, plangate
from ovenbird_sim.evaluate.closedloop import LoopOptions, PlanRequest, Trace, Weather, simulate
from ovenbird_sim.evaluate.forecast import ForecastError, hourly_table
from ovenbird_sim.evaluate.modelplan import RunSpec
from ovenbird_sim.evaluate.modelplan_run import (
    EvalOptions,
    evaluate,
    parse_params,
    render_markdown,
    to_json,
)
from ovenbird_sim.evaluate.plangate import CRITERION, Outcome
from ovenbird_sim.evaluate.sensors import SensorModel
from ovenbird_sim.heishamon.reference import REFERENCE_PARAMS
from ovenbird_sim.model.plant import initial_state

DAYS = 2
PASS, FAIL, INCONCLUSIVE = Outcome.PASSED, Outcome.FAILED, Outcome.INCONCLUSIVE


def _weather(scenario: str = "sunny_cold", days: int = DAYS) -> tuple[Weather, FloatArray]:
    rep = modelplan.replica(0, 0, days)
    return modelplan.build_weather(modelplan.SCENARIOS[scenario], rep, days)


def _run(options: LoopOptions) -> Trace:
    weather, _ = _weather()
    config = OvenbirdConfig.preset("mixed", comfort_room_c=21.0)
    start = initial_state(REFERENCE_PARAMS, 21.0, t_mass=25.0, t_water=28.0)
    return simulate(OvenbirdController(config), REFERENCE_PARAMS, weather, start, options)


def test_default_hook_leaves_the_run_unchanged() -> None:
    plain = _run(LoopOptions(initial_setpoint=30, sensors=SensorModel(seed=2)))
    inert = _run(
        LoopOptions(
            initial_setpoint=30, sensors=SensorModel(seed=2), plan_provider=None, plan_every_s=300.0
        )
    )
    for name in ("setpoint", "room_c", "heat_w", "elec_w", "start", "write", "plan_offset_k"):
        assert np.array_equal(getattr(plain, name), getattr(inert, name))
    assert plain.reasons == inert.reasons


def test_provider_gets_the_previous_slice_and_the_room_every_period() -> None:
    weather, announced = _weather()
    calls: list[PlanRequest] = []

    def provider(request: PlanRequest) -> PlanSlice:
        calls.append(request)
        return PlanSlice(
            -0.2,
            ReasonCode.PLAN_SETBACK,
            request.now,
            request.now.shifted(1200.0),
            PlanSource.MODEL,
        )

    trace = _run(
        LoopOptions(
            initial_setpoint=30,
            plan_provider=provider,
            plan_forecast=hourly_table(weather, announced),
        )
    )
    stamps = [c.now.wall.timestamp() for c in calls]
    assert all(b - a == 900.0 for a, b in pairwise(stamps))
    assert calls[0].previous_offset_k == 0.0
    assert calls[0].previous_slice is None
    assert all(c.previous_offset_k == -0.2 for c in calls[1:])
    assert all(
        c.previous_slice is not None and c.previous_slice.room_offset_k == -0.2 for c in calls[1:]
    )
    assert all(c.room_c is not None for c in calls[1:])
    assert trace.ladder.count("model_plan") > 0


def test_replica_draws_are_reproducible_and_independent_of_order_and_length() -> None:
    a = modelplan.replica(3, 5, 8)
    later = [modelplan.replica(3, r, 8) for r in (7, 6, 5)]
    assert later[-1] == a
    short = modelplan.replica(3, 5, 4)
    assert short.swing_k == a.swing_k[:4]
    assert short.drift_k == a.drift_k[:4]
    assert short.clear_u == a.clear_u[:4]
    assert short.sun_shift_h == a.sun_shift_h[:4]
    assert short.t_mass_c == a.t_mass_c
    forward = [modelplan.draw(3, 5, modelplan.SALT_SWING, d) for d in range(4)]
    backward = [modelplan.draw(3, 5, modelplan.SALT_SWING, d) for d in reversed(range(4))]
    assert forward == backward[::-1]
    assert modelplan.replica(3, 6, 8) != a
    assert a.sensor_seed() != a.sensor_seed(1)
    with pytest.raises(ValueError, match="non-negative"):
        modelplan.replica(-1, 0, 2)


def test_replica_weather_stays_in_the_scenario_character() -> None:
    swings = []
    for r in range(6):
        rep = modelplan.replica(0, r, 8)
        assert all(2.0 <= s <= 5.0 for s in rep.swing_k)
        assert abs(rep.mean_offset_k) <= 1.5
        assert 23.5 <= rep.t_mass_c <= 26.5
        swings.append(rep.mean_offset_k)
        dark, announced = modelplan.build_weather(modelplan.SCENARIOS["false_sun_cold"], rep, 3)
        assert dark.ghi_w_m2.max() == 0.0
        assert 400.0 < announced.max() <= 600.0
        missing, forecast_missing = modelplan.build_weather(
            modelplan.SCENARIOS["missing_sun"], rep, 3
        )
        assert forecast_missing.max() > missing.ghi_w_m2.max()
    assert len(set(swings)) == len(swings)
    rep = modelplan.replica(0, 1, 4)
    _, plain = modelplan.build_weather(modelplan.SCENARIOS["sunny_cold"], rep, 4)
    _, early = modelplan.build_weather(modelplan.SCENARIOS["sunny_cold"], rep, 4, -2.0)
    first_sun = int(np.argmax(plain > 0.0))
    assert int(np.argmax(early > 0.0)) == pytest.approx(first_sun - 120, abs=1)


def test_null_planner_pairs_to_exactly_zero() -> None:
    base = modelplan.run_one(RunSpec("sunny_mild", 1, DAYS))
    null = modelplan.run_one(RunSpec("sunny_mild", 1, DAYS, planner="none", model="aperture_x2"))
    assert dict(null.row) == dict(base.row)
    assert np.array_equal(null.deficit_q, base.deficit_q)
    verdict = plangate.judge_cell([base.row] * 4, [null.row] * 4, "null", 4)
    assert verdict.outcome is PASS
    assert all(c.interval.low == c.interval.high == 0.0 for c in verdict.checks)


def test_planner_registry_builds_the_arms() -> None:
    const = modelplan.build_arm("const_water", "correct", ())
    base = modelplan.controller_config().curve
    assert [p.water_c - 3.0 for p in base.points] == [
        p.water_c for p in const.controller.curve.points
    ]
    assert const.fixed_offset_k == -3.0
    assert modelplan.build_arm("none", "correct", ()).provider is None
    assert modelplan.build_arm("const_room", "correct", ()).provider is not None
    noise = modelplan.build_arm("noise", "correct", ())
    assert noise.provider is None
    assert noise.sensor_salt > 0
    assert noise.sensor_salt != modelplan.build_arm("noise", "correct", (), "noisy").sensor_salt
    salts = {
        modelplan.build_arm("noise", "correct", (), "noisy", s).sensor_salt for s in ("a", "b")
    }
    assert len(salts) == 2
    assert modelplan.build_arm("v1", "ua_x0.7", (("gain", 0.3),)).provider is not None
    water = modelplan.build_arm("v2", "aperture_x2", (("lead_h", 3.0),))
    assert water.applied_key == modelplan.V2_APPLIED_KEY
    assert water.provider is not None
    with pytest.raises(KeyError):
        modelplan.build_arm("v9", "correct", ())
    assert parse_params(["lead_h=3", "gain=0.5"]) == (("gain", 0.5), ("lead_h", 3.0))
    with pytest.raises(ValueError, match="name=value"):
        parse_params(["lead_h"])


def test_grid_marks_credible_and_stress_cells() -> None:
    ids = modelplan.cells(tuple(modelplan.SCENARIOS), modelplan.DEFAULT_MODELS)
    assert len(ids) == 94
    credible = [c for c in ids if c.credible]
    assert len(credible) == 42
    assert not any(c.scenario == "false_sun_cold" for c in credible)
    assert not any(c.forecast.startswith("shift") for c in credible)
    assert not any(c.scenario == "cold_front" and c.forecast.startswith("shift") for c in ids)


def test_forecast_error_is_seeded_and_leaves_the_past_alone() -> None:
    weather, announced = _weather("sunny_mild", 4)
    base = hourly_table(weather, announced)
    now = weather.t0 + 2 * 86400.0 + 3 * 3600.0
    at = Instant.from_unix(now)
    a = replace(base, error=ForecastError(seed=4))
    assert a.rows(at) == replace(base, error=ForecastError(seed=4)).rows(at)
    assert a.rows(at) != replace(base, error=ForecastError(seed=5)).rows(at)
    past = [r for r in a.rows(at) if r.target_ts <= now]
    assert past == [r for r in base.rows(at) if r.target_ts <= now]


def _rows(n: int, **values: float) -> list[dict[str, float]]:
    row = dict.fromkeys(plangate.ROW_KPIS, 0.0)
    row.update(starts_per_day=2.0, below_kh=1.0, above_kh=3.0, elec_kwh_per_day=10.0)
    row.update(writes_per_day=10.0)
    row.update(values)
    return [dict(row) for _ in range(n)]


def _shifted(
    rows: list[dict[str, float]], name: str, deltas: list[float]
) -> list[dict[str, float]]:
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
    without = _rows(24)
    verdict = plangate.judge_cell(without, _shifted(without, name, [delta] * 24), "c", 24)
    criterion = next(c for c in plangate.CRITERIA if c.kpi == name)
    assert verdict.check(criterion.name).outcome is expected
    assert verdict.outcome is expected


def test_gate_is_inconclusive_when_the_interval_straddles_the_margin() -> None:
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
    writes = CRITERION["writes"]
    assert float(writes.statistic(np.array([10.0, 10.0]), np.array([12.0, 12.0]))) == pytest.approx(
        0.2
    )
    assert float(writes.statistic(np.array([0.0, 0.0]), np.array([0.5, 0.5]))) == pytest.approx(0.5)


@pytest.mark.slow
def test_quick_run_is_deterministic_and_shares_the_baseline() -> None:
    options = EvalOptions.quick()
    first = evaluate(options)
    second = evaluate(options)
    a, b = to_json(first), to_json(second)
    for doc in (a, b):
        doc.pop("runtime_s")
    assert a == b
    assert len(first.cells) == len(options.cell_ids()) == 4
    by_scenario: dict[str, tuple[object, ...]] = {}
    for cell in first.cells:
        assert len(cell.with_plan) >= options.replicas
        shared = by_scenario.setdefault(cell.cell.scenario, cell.without[: options.replicas])
        assert cell.without[: options.replicas] == shared
        assert {c.criterion for c in cell.verdict.checks} == {c.name for c in plangate.CRITERIA}
    assert set(a["verdict"]) >= {"unlocked", "credible_inconclusive", "lines"}
    assert set(a["baseline"]) == set(options.scenarios)
    text = render_markdown(first)
    assert "## Verdict" in text
    assert "### sunny_cold" in text

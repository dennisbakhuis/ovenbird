"""Model-plan evaluation: the closed-loop hook, forecast errors, the gate and a quick paired run."""

from dataclasses import replace
from itertools import pairwise

import numpy as np
import pytest

from ovenbird_core.control import OvenbirdConfig, OvenbirdController
from ovenbird_core.control.types import PlanSlice, PlanSource, ReasonCode
from ovenbird_core.instant import Instant
from ovenbird_sim.evaluate import modelplan, plangate
from ovenbird_sim.evaluate.closedloop import LoopOptions, PlanRequest, Trace, simulate
from ovenbird_sim.evaluate.forecast import ForecastError, hourly_table
from ovenbird_sim.evaluate.modelplan_run import EvalOptions, evaluate, render_markdown
from ovenbird_sim.evaluate.sensors import SensorModel
from ovenbird_sim.heishamon.reference import REFERENCE_PARAMS
from ovenbird_sim.model.plant import initial_state

DAYS = 2


def _run(options: LoopOptions) -> Trace:
    weather, _ = modelplan.build_weather(modelplan.SCENARIOS["sunny_cold"], DAYS)
    config = OvenbirdConfig.preset("mixed", comfort_room_c=21.0)
    start = initial_state(REFERENCE_PARAMS, 21.0, t_mass=25.0, t_water=28.0)
    return simulate(OvenbirdController(config), REFERENCE_PARAMS, weather, start, options)


def test_default_hook_leaves_the_run_unchanged() -> None:
    plain = _run(LoopOptions(initial_setpoint=30, sensors=SensorModel(seed=2)))
    inert = _run(
        LoopOptions(
            initial_setpoint=30,
            sensors=SensorModel(seed=2),
            plan_provider=None,
            plan_every_s=300.0,
        )
    )
    for name in ("setpoint", "room_c", "heat_w", "elec_w", "start", "write", "plan_offset_k"):
        assert np.array_equal(getattr(plain, name), getattr(inert, name))
    assert plain.reasons == inert.reasons
    assert not plain.plan_offset_k.any()


def test_provider_is_called_every_period_with_the_previous_offset() -> None:
    weather, forecast_ghi = modelplan.build_weather(modelplan.SCENARIOS["sunny_cold"], DAYS)
    table = hourly_table(weather, forecast_ghi)
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

    trace = _run(LoopOptions(initial_setpoint=30, plan_provider=provider, plan_forecast=table))
    stamps = [c.now.wall.timestamp() for c in calls]
    assert all(b - a == 900.0 for a, b in pairwise(stamps))
    assert calls[0].previous_offset_k == 0.0
    assert all(c.previous_offset_k == -0.2 for c in calls[1:])
    assert len(calls[0].forecast.rows(calls[0].now)) > 36
    assert trace.ladder.count("model_plan") > 0
    assert set(np.unique(trace.plan_offset_k)) <= {0.0, -0.2}
    assert trace.room_feedback[trace.t > trace.t[0] + 86400].all()


def test_forecast_error_is_seeded_and_reproducible() -> None:
    weather, forecast_ghi = modelplan.build_weather(modelplan.SCENARIOS["sunny_mild"], 4)
    base = hourly_table(weather, forecast_ghi)
    now = weather.t0 + 2 * 86400.0 + 3 * 3600.0
    at = Instant.from_unix(now)
    a = replace(base, error=ForecastError(seed=4))
    b = replace(base, error=ForecastError(seed=4))
    c = replace(base, error=ForecastError(seed=5))
    assert a.rows(at) == b.rows(at)
    assert a.rows(at) != c.rows(at)
    assert a.rows(at) != base.rows(at)
    past = [r for r in a.rows(at) if r.target_ts <= now]
    assert past == [r for r in base.rows(at) if r.target_ts <= now]


def test_forecast_error_factors_have_unit_mean_and_follow_the_day() -> None:
    error = ForecastError(ghi_sigma=0.4, seed=1)
    factors = [error.ghi_factor(day) for day in range(2000)]
    assert abs(float(np.mean(factors)) - 1.0) < 0.05
    assert error.ghi_factor(3) == error.ghi_factor(3)
    assert error.weight(-3600.0) == 0.0
    assert error.weight(3 * 3600.0) == pytest.approx(0.5)
    assert error.weight(12 * 3600.0) == 1.0


def test_scenario_forecasts_encode_the_mismatch() -> None:
    missing, forecast_missing = modelplan.build_weather(modelplan.SCENARIOS["missing_sun"], 2)
    assert forecast_missing.max() > missing.ghi_w_m2.max()
    unforecast, forecast_unforecast = modelplan.build_weather(
        modelplan.SCENARIOS["unforecast_sun"], 2
    )
    assert forecast_unforecast.max() < unforecast.ghi_w_m2.max()


def _row(**kw: float) -> dict[str, float]:
    base = dict.fromkeys(plangate.ROW_KPIS, 0.0)
    base.update(starts_per_day=2.0, below_kh=2.0, above_kh=5.0)
    base.update(kw)
    return base


def test_gate_passes_an_equal_pair_and_requires_benefit_only_when_asked() -> None:
    row = _row()
    assert plangate.judge(row, row).passed
    verdict = plangate.judge(row, row, benefit_required=True)
    assert verdict.failed == ("benefit",)
    assert plangate.judge(row, _row(above_kh=4.0), benefit_required=True).passed


@pytest.mark.parametrize(
    ("change", "failed"),
    [
        ({"below_band_kh": 0.05}, ()),
        ({"below_band_kh": 0.2}, ("below_band",)),
        ({"below_kh": 2.4}, ()),
        ({"below_kh": 2.6}, ("below",)),
        ({"starts_per_day": 2.4}, ()),
        ({"starts_per_day": 2.6}, ("starts",)),
    ],
)
def test_gate_tolerances(change: dict[str, float], failed: tuple[str, ...]) -> None:
    assert plangate.judge(_row(), _row(**change)).failed == failed


def test_gate_uses_the_relative_allowance_when_it_is_larger() -> None:
    base = _row(below_kh=20.0, starts_per_day=20.0)
    assert plangate.judge(base, _row(below_kh=20.9, starts_per_day=20.9)).passed
    assert plangate.judge(base, _row(below_kh=21.2, starts_per_day=21.2)).failed == (
        "below",
        "starts",
    )


def test_bootstrap_interval_is_seeded_and_brackets_a_constant() -> None:
    values = [-0.5] * 7
    assert plangate.bootstrap_interval(values, seed=1) == (-3.5, -3.5)
    noisy = [0.1, -0.4, 0.3, -0.2, 0.0, 0.5, -0.3]
    assert plangate.bootstrap_interval(noisy, seed=2) == plangate.bootstrap_interval(noisy, seed=2)
    assert np.isnan(plangate.bootstrap_interval([])[0])
    assert plangate.bootstrap_interval([-1.0] * 21, period_days=7) == (-7.0, -7.0)


def test_quick_paired_run_is_deterministic_and_renders_the_table() -> None:
    options = EvalOptions.quick()
    first = evaluate(options)
    second = evaluate(options)
    assert [c.with_plan for c in first.cells] == [c.with_plan for c in second.cells]
    assert [c.without for c in first.cells] == [c.without for c in second.cells]
    assert len(first.cells) == len(options.scenarios) * len(options.models)
    shared = {c.scenario: c.without for c in first.cells}
    assert all(c.without == shared[c.scenario] for c in first.cells)
    assert any(c.with_plan["plan_share"] > 0.0 for c in first.cells)
    text = render_markdown(first)
    assert "### sunny_cold" in text
    assert "## Gate verdict" in text

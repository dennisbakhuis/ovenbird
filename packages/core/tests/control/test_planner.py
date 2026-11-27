"""The model planner: bounds, dead zone, quantum, rate limit, gaps, scenarios, robustness."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ovenbird_core.control import OvenbirdConfig, PlanSource, ReasonCode
from ovenbird_core.control.config import ModelPlanConfig
from ovenbird_core.control.planner import (
    ForecastHour,
    PlannerConfig,
    PlannerResult,
    PlannerStatus,
    _target,
    plan_offset,
)
from ovenbird_core.housemodel import DiscreteHouse, HouseModel
from ovenbird_core.instant import Instant

DAY0 = datetime(2026, 1, 6, tzinfo=UTC).timestamp()
HOUSE = HouseModel(
    c_water=5.0e5,
    c_mass=4.5e6,
    c_air=2.1e7,
    h_water_mass=540.0,
    h_water_air=40.0,
    h_mass_air=450.0,
    h_air_out=145.0,
    solar_aperture_m2=3.5,
    solar_mass_fraction=0.3,
)
CONFIG = PlannerConfig()
WRONG = {
    "ua x0.7": replace(HOUSE, h_air_out=HOUSE.h_air_out * 0.7),
    "ua x1.4": replace(HOUSE, h_air_out=HOUSE.h_air_out * 1.4),
    "aperture x0.5": replace(HOUSE, solar_aperture_m2=HOUSE.solar_aperture_m2 * 0.5),
    "aperture x2": replace(HOUSE, solar_aperture_m2=HOUSE.solar_aperture_m2 * 2.0),
    "mass x0.5": replace(HOUSE, c_mass=HOUSE.c_mass * 0.5, c_air=HOUSE.c_air * 0.5),
    "mass x2": replace(HOUSE, c_mass=HOUSE.c_mass * 2.0, c_air=HOUSE.c_air * 2.0),
}

type Profile = Callable[[float], float]


def at(hour: float) -> Instant:
    return Instant.from_unix(DAY0 + hour * 3600.0)


def sunny(peak: float = 500.0) -> Profile:
    def ghi(hour: float) -> float:
        h = hour % 24.0
        return peak * math.sin(math.pi * (h - 8.0) / 8.0) if 8.0 < h < 16.0 else 0.0

    return ghi


def constant(value: float) -> Profile:
    return lambda _hour: value


def cold_front(hour: float) -> float:
    if hour <= 12.0:
        return 8.0
    if hour >= 15.0:
        return 0.0
    return 8.0 - 8.0 * (hour - 12.0) / 3.0


def mild(_hour: float) -> float:
    return 3.0


def winter_sun(hour: float) -> float:
    return sunny()(hour)


def forecast(
    outside: Profile = mild, ghi: Profile = winter_sun, first: int = -48, last: int = 48
) -> list[ForecastHour]:
    return [
        ForecastHour(DAY0 + 3600.0 * h, outside(float(h)), ghi(float(h)))
        for h in range(first, last + 1)
    ]


def plan(
    hour: float,
    rows: list[ForecastHour],
    previous: float = 0.0,
    model: HouseModel = HOUSE,
    config: PlannerConfig = CONFIG,
    outside_filtered: float | None = None,
) -> PlannerResult:
    filtered = rows[0].outside_c if outside_filtered is None else outside_filtered
    assert filtered is not None
    return plan_offset(model, rows, at(hour), filtered, config, previous)


@dataclass(frozen=True)
class Day:
    hours: tuple[float, ...]
    results: tuple[PlannerResult, ...]

    def offset_at(self, hour: float) -> float:
        return self.results[self.hours.index(hour)].offset_k

    def offsets(self, start: float, end: float) -> list[float]:
        pairs = zip(self.hours, self.results, strict=True)
        return [r.offset_k for h, r in pairs if start <= h < end]


def day(
    rows: list[ForecastHour],
    model: HouseModel = HOUSE,
    config: PlannerConfig = CONFIG,
    start: float = 0.0,
    end: float = 24.0,
) -> Day:
    hours: list[float] = []
    results: list[PlannerResult] = []
    previous = 0.0
    hour = start
    while hour < end:
        result = plan(hour, rows, previous, model, config)
        hours.append(hour)
        results.append(result)
        previous = result.offset_k
        hour += config.slice_s / 3600.0
    return Day(tuple(hours), tuple(results))


def on_grid(value: float, quantum: float = 0.1) -> bool:
    return abs(value / quantum - round(value / quantum)) < 1e-9


class TestScenarios:
    def test_sunny_day_sets_back_in_the_morning_and_returns_to_zero(self) -> None:
        result = day(forecast())
        morning = result.offsets(6.0, 11.0)
        assert min(morning) <= -0.3
        assert all(o <= 0.0 for o in result.offsets(4.0, 13.0))
        assert result.offsets(14.0, 24.0) == [0.0] * 40
        assert result.offsets(0.0, 5.0) == [0.0] * 20

    def test_a_set_back_slice_is_a_model_slice(self) -> None:
        result = plan(8.0, forecast(), previous=-0.2)
        assert result.status is PlannerStatus.ISSUED
        assert result.slice is not None
        assert result.slice.source is PlanSource.MODEL
        assert result.slice.reason is ReasonCode.PLAN_SETBACK
        assert result.slice.room_offset_k == result.offset_k == -0.3
        assert result.slice.valid_from == at(8.0)
        assert result.slice.valid_until == at(8.0).shifted(CONFIG.slice_s + CONFIG.grace_s)
        assert result.peak_change_k is not None
        assert result.peak_change_k > 0.5
        assert result.solar_k == result.peak_change_k
        assert result.outside_k == 0.0
        assert result.rise_k == result.peak_change_k
        assert result.fall_k == 0.0
        assert result.fall_at_ts is None
        assert result.rise_at_ts is not None
        assert result.rise_at_ts > at(8.0).wall.timestamp()

    def test_cold_front_pre_heats_before_and_during_it(self) -> None:
        result = day(forecast(outside=cold_front, ghi=constant(0.0)))
        assert result.offsets(0.0, 10.0) == [0.0] * 40
        assert max(result.offsets(10.0, 16.0)) >= 0.2
        assert all(0.0 <= o <= CONFIG.max_preheat_k for o in result.offsets(0.0, 24.0))
        assert result.offsets(19.0, 24.0) == [0.0] * 20
        front = plan(12.0, forecast(outside=cold_front, ghi=constant(0.0)), previous=0.1)
        assert front.slice is not None
        assert front.slice.reason is ReasonCode.PLAN_PREHEAT
        assert front.solar_k == 0.0

    def test_night_with_steady_weather_issues_nothing(self) -> None:
        result = plan(2.0, forecast(ghi=constant(0.0)))
        assert result.status is PlannerStatus.INSIDE_DEAD_ZONE
        assert result.slice is None
        assert result.peak_change_k == 0.0
        assert result.offset_k == 0.0

    def test_a_constant_outside_temperature_has_no_outside_part(self) -> None:
        result = plan(9.0, forecast(outside=constant(-5.0)), outside_filtered=-5.0)
        assert result.outside_k == 0.0

    def test_a_constant_forecast_bias_changes_nothing(self) -> None:
        rows = forecast(outside=cold_front, ghi=sunny())
        biased = forecast(outside=lambda h: cold_front(h) + 3.0, ghi=sunny())
        for hour in (6.0, 10.0, 13.0):
            plain, shifted = plan(hour, rows, -0.1), plan(hour, biased, -0.1)
            assert shifted.peak_change_k == plain.peak_change_k
            assert shifted.offset_k == plain.offset_k

    def test_without_weather_compensation_the_whole_outside_change_counts(self) -> None:
        rows = forecast(outside=cold_front, ghi=constant(0.0))
        curve = plan(10.0, rows)
        fixed = plan(10.0, rows, config=replace(CONFIG, weather_compensation=False))
        assert curve.outside_k is not None
        assert fixed.outside_k is not None
        assert fixed.outside_k < curve.outside_k < 0.0

    def test_the_outside_part_can_be_switched_off(self) -> None:
        rows = forecast(outside=cold_front, ghi=constant(0.0))
        result = plan(12.0, rows, 0.1, config=replace(CONFIG, outside_weight=0.0))
        assert result.outside_k == 0.0
        assert result.peak_change_k == 0.0
        assert result.status is PlannerStatus.INSIDE_DEAD_ZONE
        assert result.slice is None


class TestShaping:
    def test_dead_zone(self) -> None:
        result = plan(7.0, forecast(ghi=sunny(120.0)))
        assert result.raw_offset_k is not None
        assert 0.0 < -result.raw_offset_k <= CONFIG.dead_zone_k
        assert result.status is PlannerStatus.INSIDE_DEAD_ZONE
        assert result.slice is None

    def test_the_rate_limit_moves_one_quantum_per_slice(self) -> None:
        result = day(forecast(ghi=sunny(900.0)), start=4.0, end=10.0)
        offsets = [r.offset_k for r in result.results]
        steps = [b - a for a, b in zip([0.0, *offsets], offsets, strict=False)]
        assert all(abs(step) <= CONFIG.rate_k_per_slice + 1e-9 for step in steps)
        assert min(offsets) == -CONFIG.max_setback_k

    @pytest.mark.parametrize(
        ("setback", "preheat"), [(0.5, 0.3), (0.2, 0.1), (1.0, 0.5), (0.0, 0.0)]
    )
    def test_bounds(self, setback: float, preheat: float) -> None:
        config = replace(CONFIG, max_setback_k=setback, max_preheat_k=preheat, rate_k_per_slice=1.0)
        strong = plan(7.0, forecast(ghi=sunny(2000.0)), config=config)
        front = plan(12.0, forecast(outside=lambda h: cold_front(h) * 3.0), config=config)
        assert strong.offset_k == -setback
        assert front.offset_k == preheat

    def test_offsets_lie_on_the_quantum_grid(self) -> None:
        config = replace(CONFIG, quantum_k=0.05, dead_zone_k=0.0, rate_k_per_slice=0.15)
        for result in day(forecast(), config=config).results:
            assert on_grid(result.offset_k, 0.05)
            assert result.target_offset_k is None or on_grid(result.target_offset_k, 0.05)

    def test_crossing_zero_stops_at_zero_for_a_slice(self) -> None:
        result = plan(9.0, forecast(), previous=0.1)
        assert result.target_offset_k is not None
        assert result.target_offset_k < 0.0
        assert result.offset_k == 0.0
        assert result.status is PlannerStatus.CROSSING_ZERO
        assert result.slice is None

    def test_a_value_on_a_step_edge_keeps_the_previous_offset(self) -> None:
        assert _target(CONFIG, -0.34, 0.0) == -0.1
        assert _target(CONFIG, -0.34, -0.2) == -0.2
        assert _target(CONFIG, -0.27, 0.0) == 0.0
        assert _target(CONFIG, -0.28, 0.0) == -0.1
        assert _target(CONFIG, -0.36, -0.1) == -0.1
        assert _target(CONFIG, -0.38, -0.1) == -0.2


class TestHorizonRoll:
    def test_moving_on_by_one_slice_changes_the_raw_offset_little(self) -> None:
        rows = forecast(outside=cold_front)
        results = [plan(h / 4.0, rows) for h in range(96)]
        raws = [r.raw_offset_k for r in results if r.raw_offset_k is not None]
        assert len(raws) == len(results)
        assert max(abs(b - a) for a, b in pairwise(raws)) < 0.1

    def test_the_issued_offset_does_not_chatter(self) -> None:
        result = day(forecast(outside=cold_front))
        offsets = [r.offset_k for r in result.results]
        moves = [b - a for a, b in pairwise(offsets) if b != a]
        reversals = sum(1 for a, b in pairwise(moves) if a * b < 0.0)
        assert reversals <= 3
        assert all(abs(m) <= CONFIG.rate_k_per_slice + 1e-9 for m in moves)


class TestFailures:
    def test_a_missing_hour_in_the_window_is_a_gap(self) -> None:
        rows = [r for r in forecast() if r.target_ts != at(10.0).wall.timestamp()]
        result = plan(8.0, rows, previous=-0.3)
        assert result.status is PlannerStatus.FORECAST_GAP
        assert result.slice is None
        assert result.offset_k == 0.0
        assert result.peak_change_k is None

    def test_a_missing_value_is_a_gap(self) -> None:
        rows = [
            replace(r, ghi_w_m2=None) if r.target_ts == at(-20.0).wall.timestamp() else r
            for r in forecast()
        ]
        assert plan(2.0, rows).status is PlannerStatus.FORECAST_GAP
        assert plan(5.0, rows).status is not PlannerStatus.FORECAST_GAP

    def test_a_forecast_that_does_not_reach_the_horizon_is_a_gap(self) -> None:
        rows = forecast(last=12)
        assert plan(5.0, rows).status is not PlannerStatus.FORECAST_GAP
        assert plan(7.0, rows).status is PlannerStatus.FORECAST_GAP

    def test_a_forecast_without_a_day_of_history_is_a_gap(self) -> None:
        assert plan(2.0, forecast(first=-20)).status is PlannerStatus.FORECAST_GAP

    def test_a_forecast_far_from_the_measured_outside_is_refused(self) -> None:
        result = plan(8.0, forecast(), previous=-0.2, outside_filtered=15.0)
        assert result.status is PlannerStatus.FORECAST_MISMATCH
        assert result.slice is None
        assert result.offset_k == 0.0
        assert result.forecast_outside_c == 3.0

    def test_a_model_that_cannot_be_discretised_is_invalid(self) -> None:
        @dataclass(frozen=True)
        class Broken(HouseModel):
            def discretise(self, dt_s: float) -> DiscreteHouse:
                raise ValueError("broken")

        assert plan(8.0, forecast(), model=Broken()).status is PlannerStatus.MODEL_INVALID

    def test_bad_rows_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="whole hours"):
            ForecastHour(DAY0 + 60.0, 3.0, 0.0)
        with pytest.raises(ValueError, match="non-negative"):
            ForecastHour(DAY0, 3.0, -1.0)
        with pytest.raises(ValueError, match="finite"):
            ForecastHour(DAY0, math.nan, 0.0)
        rows = forecast()
        with pytest.raises(ValueError, match="twice"):
            plan(8.0, [*rows, rows[10]])


class TestConfig:
    def test_defaults(self) -> None:
        assert (CONFIG.max_setback_k, CONFIG.max_preheat_k, CONFIG.horizon_h) == (0.5, 0.3, 6.0)
        assert (CONFIG.dead_zone_k, CONFIG.quantum_k, CONFIG.rate_k_per_slice) == (0.2, 0.1, 0.1)
        assert (CONFIG.slice_s, CONFIG.grace_s, CONFIG.gain) == (900.0, 300.0, 0.6)

    def test_for_controller_takes_the_controller_settings(self) -> None:
        cfg = OvenbirdConfig.preset(
            "screed_floor",
            weather_compensation=False,
            model_plan=ModelPlanConfig(max_setback_k=0.8, max_preheat_k=0.1),
        )
        config = PlannerConfig.for_controller(cfg, horizon_h=4.0)
        assert (config.max_setback_k, config.max_preheat_k) == (0.8, 0.1)
        assert config.outside_filter_tau_s == cfg.outside_filter_tau_s
        assert config.weather_compensation is False
        assert config.horizon_h == 4.0

    @pytest.mark.parametrize(
        ("changes", "message"),
        [
            ({"max_setback_k": 1.01}, "max_setback_k"),
            ({"max_preheat_k": 0.51}, "max_preheat_k"),
            ({"horizon_h": 13.0}, "horizon_h"),
            ({"rate_k_per_slice": 0.05}, "at least one quantum"),
            ({"slice_s": 3600.0, "grace_s": 300.0}, "MODEL_PLAN_MAX_SLICE_S"),
            ({"gain": 0.0}, "gain"),
        ],
    )
    def test_out_of_range_settings_are_refused(self, changes: dict[str, Any], message: str) -> None:
        with pytest.raises(ValueError, match=message):
            replace(CONFIG, **changes)


class TestDeterminism:
    def test_same_inputs_same_result(self) -> None:
        rows = forecast(outside=cold_front)
        assert plan(9.0, rows, -0.1) == plan(9.0, list(reversed(rows)), -0.1)

    def test_pinned_numbers(self) -> None:
        result = plan(8.0, forecast(outside=cold_front), previous=-0.2)
        pinned = (
            result.status,
            result.peak_change_k,
            result.solar_k,
            result.outside_k,
            result.raw_offset_k,
            result.offset_k,
            result.forecast_outside_c,
        )
        assert pinned == (PlannerStatus.ISSUED, 0.796, 0.917, -0.121, -0.478, -0.3, 8.0)


class TestWrongModels:
    @pytest.mark.parametrize("name", sorted(WRONG))
    def test_a_wrong_model_keeps_the_bounds_and_the_sign(self, name: str) -> None:
        model = WRONG[name]
        sun = day(forecast(), model=model)
        assert all(-CONFIG.max_setback_k <= o <= 0.0 for o in sun.offsets(0.0, 13.0))
        assert min(sun.offsets(6.0, 11.0)) < 0.0
        front = day(forecast(outside=cold_front, ghi=constant(0.0)), model=model)
        assert all(0.0 <= o <= CONFIG.max_preheat_k for o in front.offsets(0.0, 24.0))
        raws = [r.raw_offset_k for r in front.results[40:64]]
        assert all(raw is not None and raw >= 0.0 for raw in raws)
        assert max(raw for raw in raws if raw is not None) > 0.1


hours = st.integers(-6, 18)
rows_strategy = st.lists(
    st.tuples(st.floats(-15.0, 25.0), st.floats(0.0, 900.0)), min_size=80, max_size=80
)


@settings(max_examples=60, deadline=None)
@given(
    weather=rows_strategy,
    hour=st.integers(0, 95),
    previous=st.integers(-10, 6).map(lambda q: q / 10.0),
    gain=st.sampled_from([0.3, 0.6, 1.0]),
)
def test_any_forecast_gives_a_bounded_quantised_rate_limited_offset(
    weather: list[tuple[float, float]], hour: int, previous: float, gain: float
) -> None:
    rows = [
        ForecastHour(DAY0 + 3600.0 * (h - 30), outside, sun)
        for h, (outside, sun) in enumerate(weather)
    ]
    config = replace(CONFIG, gain=gain)
    result = plan_offset(HOUSE, rows, at(hour / 4.0), weather[30][0], config, previous)
    assert -config.max_setback_k <= result.offset_k <= config.max_preheat_k
    assert on_grid(result.offset_k)
    bounded_previous = min(max(previous, -config.max_setback_k), config.max_preheat_k)
    assert abs(result.offset_k - previous) <= config.rate_k_per_slice + 1e-9 or (
        result.offset_k == bounded_previous or result.slice is None
    )
    assert (result.slice is not None) == (result.status is PlannerStatus.ISSUED)
    if result.slice is not None:
        assert result.slice.room_offset_k == result.offset_k != 0.0
        assert result.slice.source is PlanSource.MODEL
    assert result == plan_offset(HOUSE, rows, at(hour / 4.0), weather[30][0], config, previous)

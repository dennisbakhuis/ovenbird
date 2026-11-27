"""The water planner: formula, lead window, quantum, rate limit, bounds, statuses, recovery."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ovenbird_core.control import OvenbirdConfig, PlanSource, ReasonCode
from ovenbird_core.control.config import ModelPlanConfig
from ovenbird_core.control.curve import HeatingCurve
from ovenbird_core.control.planner import (
    ForecastHour,
    WaterPlannerConfig,
    WaterPlanStatus,
    plan_water,
)
from ovenbird_core.housemodel import HouseModel
from ovenbird_core.instant import Instant

DAY0 = datetime(2026, 1, 6, tzinfo=UTC).timestamp()
HOUSE = HouseModel(h_air_out=200.0, solar_aperture_m2=2.0)
MIXED = OvenbirdConfig.preset("mixed")
CONFIG = WaterPlannerConfig.for_controller(MIXED)
OUTSIDE = 5.0
SLOPE = MIXED.curve.sensitivity(OUTSIDE)

type Sun = Callable[[float], float | None]


def at(hour: float) -> Instant:
    return Instant.from_unix(DAY0 + hour * 3600.0)


def table(sun: Sun, first: int = -30, last: int = 30) -> list[ForecastHour]:
    """Hourly rows ``first`` to ``last`` hours after DAY0; ``sun(h)`` is the hour before h."""
    return [ForecastHour(DAY0 + h * 3600.0, OUTSIDE, sun(float(h))) for h in range(first, last + 1)]


def flat(value: float) -> Sun:
    return lambda _hour: value


def daytime(peak: float) -> Sun:
    def ghi(hour: float) -> float:
        h = hour % 24.0
        return peak if 10.0 <= h <= 16.0 else 0.0

    return ghi


def water(
    sun: Sun,
    now_h: float = 10.0,
    previous: float = 0.0,
    config: WaterPlannerConfig = CONFIG,
    model: HouseModel = HOUSE,
) -> float:
    return plan_water(model, table(sun), at(now_h), OUTSIDE, config, previous).water_k


class TestFormula:
    def test_hand_numbers(self) -> None:
        result = plan_water(HOUSE, table(flat(300.0)), at(10.0), OUTSIDE, CONFIG, -2.0)
        assert pytest.approx(0.6) == SLOPE
        assert result.status is WaterPlanStatus.ISSUED
        assert result.ghi_w_m2 == 300.0
        assert result.sun_eq_k == pytest.approx(2.0 * 300.0 / 200.0)
        assert result.slope_k_per_k == pytest.approx(0.6)
        assert result.raw_water_k == pytest.approx(-1.8)
        assert result.target_water_k == -2.0
        assert result.water_k == -2.0
        assert result.previous_water_k == -2.0
        assert result.lead_h == 1.5
        assert result.trailing_sun_eq_k is None

    def test_gain_scales_the_raw_offset(self) -> None:
        config = replace(CONFIG, gain=0.5)
        result = plan_water(HOUSE, table(flat(300.0)), at(10.0), OUTSIDE, config)
        assert result.raw_water_k == pytest.approx(-0.9)

    def test_slope_is_read_at_the_filtered_outside_temperature(self) -> None:
        cold = plan_water(HOUSE, table(flat(300.0)), at(10.0), -5.0, CONFIG)
        assert cold.slope_k_per_k == pytest.approx(0.5)
        assert cold.raw_water_k == pytest.approx(-1.5)

    def test_slice_is_a_model_water_slice(self) -> None:
        result = plan_water(HOUSE, table(flat(300.0)), at(10.0), OUTSIDE, CONFIG)
        plan = result.slice
        assert plan is not None
        assert plan.source is PlanSource.MODEL
        assert plan.reason is ReasonCode.PLAN_SETBACK
        assert plan.room_offset_k == 0.0
        assert plan.water_offset_k == result.water_k == -0.5
        assert plan.valid_from == at(10.0)
        assert plan.valid_until == at(10.0).shifted(1200.0)


class TestLeadWindow:
    def test_window_starts_lead_after_now_and_weights_the_hours(self) -> None:
        def sun(hour: float) -> float:
            return 400.0 if hour == 12.0 else 0.0

        result = plan_water(HOUSE, table(sun), at(10.0), OUTSIDE, CONFIG)
        assert result.ghi_w_m2 == pytest.approx(200.0)

    def test_sun_beyond_the_window_does_not_count(self) -> None:
        def sun(hour: float) -> float:
            return 800.0 if hour >= 14.0 else 0.0

        result = plan_water(HOUSE, table(sun), at(10.0), OUTSIDE, CONFIG)
        assert result.ghi_w_m2 == 0.0
        assert result.status is WaterPlanStatus.ZERO

    @pytest.mark.parametrize(("lead", "expected"), [(0.0, 0.0), (1.0, 0.0), (2.0, 600.0)])
    def test_lead_moves_the_window(self, lead: float, expected: float) -> None:
        def sun(hour: float) -> float:
            return 600.0 if hour >= 12.0 + 1.0 else 0.0

        config = replace(CONFIG, lead_h=lead)
        result = plan_water(HOUSE, table(sun), at(10.0), OUTSIDE, config)
        assert result.ghi_w_m2 == pytest.approx(expected)
        assert result.lead_h == lead


class TestStepsAndBounds:
    @pytest.mark.parametrize(
        ("ghi", "previous", "expected"),
        [
            (50.0, 0.0, 0.0),
            (70.0, 0.0, -0.5),
            (300.0, -1.5, -1.5),
            (300.0, -1.0, -1.5),
        ],
    )
    def test_quantum_with_hold(self, ghi: float, previous: float, expected: float) -> None:
        assert water(flat(ghi), previous=previous) == expected

    @pytest.mark.parametrize(
        ("previous", "expected"), [(0.0, -0.5), (-1.0, -1.5), (-2.5, -3.0), (-3.0, -3.0)]
    )
    def test_rate_limit_towards_more_lowering(self, previous: float, expected: float) -> None:
        assert water(flat(2000.0), previous=previous) == expected

    @pytest.mark.parametrize(("previous", "expected"), [(-3.0, -2.5), (-0.5, 0.0)])
    def test_rate_limit_back_to_zero(self, previous: float, expected: float) -> None:
        assert water(flat(0.0), previous=previous) == expected

    def test_wider_rate_moves_in_whole_quanta(self) -> None:
        config = replace(CONFIG, rate_k_per_slice=1.2)
        assert water(flat(2000.0), config=config) == -1.0

    def test_clamped_to_the_lowering_bound_on_the_grid(self) -> None:
        config = replace(CONFIG, max_lower_water_k=2.2, rate_k_per_slice=3.0)
        assert water(flat(5000.0), config=config) == -2.0

    def test_previous_beyond_the_bound_is_cut_to_it(self) -> None:
        result = plan_water(HOUSE, table(flat(5000.0)), at(10.0), OUTSIDE, CONFIG, -4.0)
        assert result.previous_water_k == -3.0
        assert result.water_k == -3.0

    def test_never_raises_without_recovery(self) -> None:
        config = replace(CONFIG, rate_k_per_slice=3.0)
        assert water(flat(0.0), previous=1.0, config=config) == 0.0


class TestStatuses:
    def test_night_is_zero(self) -> None:
        result = plan_water(HOUSE, table(daytime(500.0)), at(22.0), OUTSIDE, CONFIG)
        assert result.status is WaterPlanStatus.ZERO
        assert result.slice is None
        assert result.water_k == 0.0
        assert result.raw_water_k == 0.0
        assert math.copysign(1.0, result.raw_water_k) == 1.0

    def test_no_sun_is_zero(self) -> None:
        result = plan_water(HOUSE, table(flat(0.0)), at(10.0), OUTSIDE, CONFIG)
        assert result.status is WaterPlanStatus.ZERO

    def test_zero_aperture_is_zero(self) -> None:
        model = replace(HOUSE, solar_aperture_m2=0.0)
        result = plan_water(model, table(flat(600.0)), at(10.0), OUTSIDE, CONFIG)
        assert result.status is WaterPlanStatus.ZERO

    def test_missing_hour_is_a_gap(self) -> None:
        rows = [row for row in table(flat(300.0)) if row.target_ts != DAY0 + 12 * 3600.0]
        result = plan_water(HOUSE, rows, at(10.0), OUTSIDE, CONFIG, -1.0)
        assert result.status is WaterPlanStatus.FORECAST_GAP
        assert result.slice is None
        assert result.water_k == 0.0
        assert result.previous_water_k == -1.0
        assert result.sun_eq_k is None

    def test_missing_irradiance_is_a_gap(self) -> None:
        def sun(hour: float) -> float | None:
            return None if hour == 12.0 else 300.0

        result = plan_water(HOUSE, table(sun), at(10.0), OUTSIDE, CONFIG)
        assert result.status is WaterPlanStatus.FORECAST_GAP

    def test_only_the_window_needs_rows(self) -> None:
        rows = table(flat(300.0), first=12, last=13)
        result = plan_water(HOUSE, rows, at(10.0), OUTSIDE, CONFIG)
        assert result.status is WaterPlanStatus.ISSUED

    def test_no_curve_without_weather_compensation(self) -> None:
        fixed = OvenbirdConfig.preset("mixed", weather_compensation=False)
        config = WaterPlannerConfig.for_controller(fixed)
        assert config.curve is None
        result = plan_water(HOUSE, table(flat(600.0)), at(10.0), OUTSIDE, config)
        assert result.status is WaterPlanStatus.NO_CURVE
        assert result.slice is None
        assert result.slope_k_per_k is None

    def test_non_finite_sun_equivalent_is_model_invalid(self) -> None:
        model = replace(HOUSE, h_air_out=1e-308, solar_aperture_m2=1000.0)
        result = plan_water(model, table(flat(1000.0)), at(10.0), OUTSIDE, CONFIG)
        assert result.status is WaterPlanStatus.MODEL_INVALID
        assert result.slice is None

    def test_a_flat_curve_segment_is_zero(self) -> None:
        curve = HeatingCurve.of((-10.0, 35.0), (15.0, 35.0))
        config = replace(CONFIG, curve=curve)
        result = plan_water(HOUSE, table(flat(600.0)), at(10.0), OUTSIDE, config)
        assert result.status is WaterPlanStatus.ZERO

    def test_duplicate_hour_is_rejected(self) -> None:
        rows = table(flat(300.0))
        with pytest.raises(ValueError, match="twice"):
            plan_water(HOUSE, [*rows, rows[0]], at(10.0), OUTSIDE, CONFIG)

    @pytest.mark.parametrize(("outside", "previous"), [(math.nan, 0.0), (5.0, math.inf)])
    def test_non_finite_arguments_are_rejected(self, outside: float, previous: float) -> None:
        with pytest.raises(ValueError, match="finite"):
            plan_water(HOUSE, table(flat(300.0)), at(10.0), outside, CONFIG, previous)


class TestRecovery:
    def test_off_by_default(self) -> None:
        assert not CONFIG.recovery
        assert CONFIG.max_raise_water_k == 0.0
        result = plan_water(HOUSE, table(daytime(500.0)), at(20.0), OUTSIDE, CONFIG)
        assert result.status is WaterPlanStatus.ZERO
        assert result.trailing_sun_eq_k is None

    def test_off_needs_no_history(self) -> None:
        rows = table(flat(300.0), first=12, last=13)
        assert plan_water(HOUSE, rows, at(10.0), OUTSIDE, CONFIG).status is WaterPlanStatus.ISSUED

    def test_on_raises_after_the_sun(self) -> None:
        config = WaterPlannerConfig.for_controller(
            OvenbirdConfig.preset("mixed", model_plan=ModelPlanConfig(max_raise_water_k=1.0))
        )
        assert config.recovery
        result = plan_water(HOUSE, table(daytime(500.0)), at(20.0), OUTSIDE, config)
        assert result.status is WaterPlanStatus.ISSUED
        assert result.sun_eq_k == 0.0
        trailing = 2.0 * 500.0 * 7.0 / 24.0 / 200.0
        assert result.trailing_sun_eq_k == pytest.approx(trailing, abs=1e-3)
        assert result.raw_water_k == pytest.approx(SLOPE * trailing, abs=1e-3)
        assert result.water_k == 0.5
        assert result.slice is not None
        assert result.slice.reason is ReasonCode.PLAN_PREHEAT
        assert plan_water(
            HOUSE, table(daytime(500.0)), at(20.0), OUTSIDE, config, 1.0
        ).water_k == pytest.approx(1.0)

    def test_on_lowers_less_in_the_sun(self) -> None:
        config = replace(CONFIG, max_raise_water_k=1.0)
        off = plan_water(HOUSE, table(daytime(200.0)), at(10.0), OUTSIDE, CONFIG)
        on = plan_water(HOUSE, table(daytime(200.0)), at(10.0), OUTSIDE, config)
        assert on.raw_water_k is not None
        assert off.raw_water_k is not None
        assert off.raw_water_k < on.raw_water_k < 0.0

    def test_on_needs_the_trailing_day(self) -> None:
        config = replace(CONFIG, max_raise_water_k=1.0)
        rows = table(flat(300.0), first=12, last=13)
        result = plan_water(HOUSE, rows, at(10.0), OUTSIDE, config)
        assert result.status is WaterPlanStatus.FORECAST_GAP


class TestConfig:
    def test_for_controller_carries_curve_and_bounds(self) -> None:
        cfg = OvenbirdConfig.preset(
            "radiators", model_plan=ModelPlanConfig(max_lower_water_k=2.0, max_raise_water_k=0.5)
        )
        config = WaterPlannerConfig.for_controller(cfg, lead_h=2.0)
        assert config.curve == cfg.curve
        assert config.max_lower_water_k == 2.0
        assert config.max_raise_water_k == 0.5
        assert config.lead_h == 2.0

    def test_defaults(self) -> None:
        assert (CONFIG.gain, CONFIG.lead_h, CONFIG.window_h) == (1.0, 1.5, 1.0)
        assert (CONFIG.quantum_k, CONFIG.rate_k_per_slice) == (0.5, 0.5)
        assert (CONFIG.slice_s, CONFIG.grace_s) == (900.0, 300.0)
        assert CONFIG.max_lower_water_k == 3.0

    @pytest.mark.parametrize(
        ("name", "value", "message"),
        [
            ("rate_k_per_slice", 0.25, "at least one quantum"),
            ("grace_s", 3000.0, "MODEL_PLAN_MAX_SLICE_S"),
            ("max_lower_water_k", 4.5, "max_lower_water_k must be in"),
            ("max_raise_water_k", 2.5, "max_raise_water_k must be in"),
            ("gain", 0.0, "gain must be in"),
        ],
    )
    def test_rejects_invalid_settings(self, name: str, value: float, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            WaterPlannerConfig(**{name: value})  # type: ignore[arg-type]


@settings(max_examples=300, deadline=None)
@given(
    ghi=st.floats(0.0, 1500.0),
    aperture=st.floats(0.0, 50.0),
    ua=st.floats(20.0, 600.0),
    previous=st.floats(-10.0, 10.0),
    outside=st.floats(-25.0, 25.0),
    lower=st.floats(0.0, 4.0),
    raise_=st.floats(0.0, 2.0),
    rate=st.sampled_from([0.5, 1.0, 1.5]),
)
def test_issued_offset_stays_on_the_grid_within_bounds_and_rate(
    ghi: float,
    aperture: float,
    ua: float,
    previous: float,
    outside: float,
    lower: float,
    raise_: float,
    rate: float,
) -> None:
    config = replace(
        CONFIG, max_lower_water_k=lower, max_raise_water_k=raise_, rate_k_per_slice=rate
    )
    model = replace(HOUSE, solar_aperture_m2=aperture, h_air_out=ua)
    result = plan_water(model, table(daytime(ghi)), at(10.0), outside, config, previous)
    assert result.status in (WaterPlanStatus.ISSUED, WaterPlanStatus.ZERO)
    value = result.water_k
    assert -lower - 1e-9 <= value <= raise_ + 1e-9
    assert value / config.quantum_k == pytest.approx(round(value / config.quantum_k))
    assert abs(value - result.previous_water_k) <= rate + 1e-9
    assert (result.slice is None) == (value == 0.0)

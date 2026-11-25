from __future__ import annotations

from dataclasses import replace

import pytest

from ovenbird_core.control import (
    OvenbirdConfig,
    OvenbirdController,
    Override,
    OverrideKind,
    ReasonCode,
)
from ovenbird_core.control.safety import Bound, SafetyBounds
from ovenbird_core.control.stages import Stages, hard_constraints, soften
from ovenbird_core.control.synthetic import PlantView, synthetic_inputs
from ovenbird_core.instant import Instant

T0 = 1_794_528_000.0
MIXED = OvenbirdConfig.preset("mixed")
CTRL = OvenbirdController(MIXED)
STAGES = MIXED.stages
BOUNDS = SafetyBounds(24.0, 30.0, Bound.MIN_SETPOINT, Bound.ENVELOPE_MAX)
RUNNING = PlantView(compressor_hz=35, outlet=33.0)


def lower(**flags: bool) -> Stages:
    values = {"defrost": False, "dhw": False, "manual": False, **flags}
    return soften(STAGES, 30.0, 33, None, 10_000.0, STAGES.dwell_s, **values)


class TestNoDecreaseHolds:
    def test_a_decrease_is_held_during_a_defrost(self) -> None:
        assert lower(defrost=True) == Stages(33, "defrost_hold")

    def test_a_decrease_is_held_during_a_dhw_run(self) -> None:
        assert lower(dhw=True) == Stages(33, "dhw_hold")

    def test_the_defrost_names_the_hold_when_both_run(self) -> None:
        assert lower(defrost=True, dhw=True) == Stages(33, "defrost_hold")

    def test_without_either_the_decrease_goes_through(self) -> None:
        assert lower() == Stages(30, None)

    def test_a_manual_setpoint_is_not_held(self) -> None:
        assert lower(defrost=True, dhw=True, manual=True) == Stages(30, None)

    @pytest.mark.parametrize(("defrost", "dhw"), [(True, False), (False, True)])
    def test_an_increase_is_not_held(self, defrost: bool, dhw: bool) -> None:
        assert soften(STAGES, 36.0, 33, None, 10_000.0, 0.0, defrost, dhw, False) == Stages(
            36, None
        )

    def test_inside_the_deadband_the_deadband_binds(self) -> None:
        inside = 33 - (STAGES.deadband_k + 0.5 + STAGES.rounding_hysteresis_k) / 2
        held = soften(STAGES, inside, 33, None, 10_000.0, 0.0, True, True, False)
        assert held.candidate == 33
        assert held.binding in {"rounding", "deadband"}

    def test_the_controller_holds_through_a_dhw_run(self) -> None:
        first = CTRL.step(
            CTRL.initial_state(), synthetic_inputs(at(0.0), replace(RUNNING, room=20.0))
        )
        assert first.decision.setpoint == 33
        dhw = replace(RUNNING, room=22.0, valve=1)
        held = CTRL.step(first.state, synthetic_inputs(at(10_000.0), dhw))
        assert held.decision.setpoint == 33
        assert held.decision.binding == "dhw_hold"
        assert held.decision.reason is ReasonCode.DHW_FREEZE
        after = CTRL.step(held.state, synthetic_inputs(at(10_060.0), replace(RUNNING, room=22.0)))
        assert after.decision.setpoint == 29


def at(seconds: float) -> Instant:
    return Instant.from_unix(T0 + seconds)


class TestIntegerClampAfterTheFloor:
    def test_the_envelope_clamps_a_floor_raise(self) -> None:
        final, binding, clamp = hard_constraints(MIXED, Stages(28, None), 33.5, 28, BOUNDS)
        assert (final, binding, clamp) == (30, Bound.ENVELOPE_MAX.value, (34, 30))

    def test_a_floor_raise_inside_the_bounds_is_kept(self) -> None:
        wide = replace(BOUNDS, high=40.0, high_source=Bound.MAX_SUPPLY)
        final, binding, clamp = hard_constraints(MIXED, Stages(28, None), 33.5, 28, wide)
        assert (final, binding, clamp) == (34, "cycling_floor", None)

    def test_the_minimum_clamps_a_held_value_below_it(self) -> None:
        final, binding, clamp = hard_constraints(MIXED, Stages(22, "dwell"), None, 22, BOUNDS)
        assert (final, binding, clamp) == (24, Bound.MIN_SETPOINT.value, (22, 24))

    def test_a_held_decrease_inside_the_min_run_window_is_clamped_too(self) -> None:
        final, binding, clamp = hard_constraints(MIXED, Stages(31, None), 31.0, 33, BOUNDS)
        assert (final, binding, clamp) == (30, Bound.ENVELOPE_MAX.value, (32, 30))

    def test_the_controller_clamps_a_floor_above_the_maximum_supply(self) -> None:
        boost = Override(OverrideKind.BOOST, 20.0)
        cold = PlantView(outside=-25.0, outlet=25.0, room=None)
        result = CTRL.step(CTRL.initial_state(), synthetic_inputs(at(0.0), cold, override=boost))
        for minute, outlet in enumerate((25.0, 46.0), start=1):
            running = replace(cold, compressor_hz=30, outlet=outlet)
            inputs = synthetic_inputs(at(60.0 * minute), running, override=boost)
            result = CTRL.step(result.state, inputs)
        decision = result.decision
        floor = decision.term("cycling_floor")
        assert floor is not None
        assert "keep ≥ 44.50 °C" in floor.note
        assert decision.pre_round == pytest.approx(40.0)
        assert decision.setpoint == 40
        assert decision.binding == Bound.MAX_SUPPLY.value
        assert "safety bound safety_max clamps 45 → 40 °C" in decision.note

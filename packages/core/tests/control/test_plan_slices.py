"""Rule plan slices: the hard bound, the pauses and their interplay with every stage."""

from __future__ import annotations

import math
from dataclasses import replace
from itertools import pairwise

import pytest

from ovenbird_core.control import (
    LadderLevel,
    OvenbirdConfig,
    OvenbirdController,
    OvenbirdState,
    Override,
    OverrideKind,
    PlanSlice,
    PlanSource,
    ReasonCode,
    StartRampConfig,
    StepResult,
    StoveConfig,
    StoveTrigger,
)
from ovenbird_core.control.config import DEFAULT_PLAN_RULE_MAX_K, PLAN_RULE_MAX_K
from ovenbird_core.control.synthetic import ROOM_SIGNAL, PlantView, synthetic_inputs
from ovenbird_core.instant import Instant

T0 = 1_794_528_000.0
COMFORT = 21.0
MINUTE = 60.0
MIXED = OvenbirdConfig.preset("mixed", comfort_room_c=COMFORT)
CTRL = OvenbirdController(MIXED)
STOVE = OvenbirdController(replace(MIXED, stove=StoveConfig()))
NO_RAMP = OvenbirdController(replace(MIXED, ramp=StartRampConfig(enabled=False)))
KP = MIXED.feedback.kp
IDLE = PlantView()
RUNNING = PlantView(compressor_hz=35, outlet=33.0)


def at(seconds: float) -> Instant:
    """Return the instant ``seconds`` after the test epoch."""
    return Instant.from_unix(T0 + seconds)


def rule(
    offset: float,
    start: float = 0.0,
    length: float = 24 * 3600.0,
    source: PlanSource = PlanSource.RULE,
) -> PlanSlice:
    """Return a plan slice valid from ``start`` for ``length`` seconds."""
    reason = ReasonCode.PLAN_PREHEAT if offset > 0 else ReasonCode.PLAN_SETBACK
    return PlanSlice(offset, reason, at(start), at(start + length), source)


def step(
    ctrl: OvenbirdController,
    state: OvenbirdState | None,
    t: float,
    plant: PlantView = IDLE,
    plan: PlanSlice | None = None,
    **kwargs: object,
) -> StepResult[OvenbirdState]:
    """Step ``ctrl`` once at ``t`` with ``plant`` and ``plan``."""
    inputs = synthetic_inputs(at(t), plant, plan=plan, **kwargs)  # type: ignore[arg-type]
    return ctrl.step(state or ctrl.initial_state(), inputs)


def run(
    ctrl: OvenbirdController,
    plants: list[PlantView],
    plan: PlanSlice | None = None,
    state: OvenbirdState | None = None,
    start: float = 0.0,
    **kwargs: object,
) -> list[StepResult[OvenbirdState]]:
    """Step ``ctrl`` once a minute through ``plants`` from ``start``."""
    current = state or ctrl.initial_state()
    results = []
    for index, plant in enumerate(plants):
        result = step(ctrl, current, start + index * MINUTE, plant, plan, **kwargs)
        results.append(result)
        current = result.state
    return results


def target(result: StepResult[OvenbirdState]) -> float:
    """Return the room target the PI worked on."""
    value = result.decision.controller_state["room_target_c"]
    assert isinstance(value, float)
    return value


def plan_note(result: StepResult[OvenbirdState]) -> str:
    """Return the note of the ``plan`` term."""
    term = result.decision.term("plan")
    assert term is not None
    return term.note


class TestBound:
    """A rule slice never shifts the room target beyond ``plan_rule_max_k``."""

    @pytest.mark.parametrize(
        ("offset", "expected", "note"),
        [
            (3.0, 22.0, "shifts room target by +1.0 K (slice +3.0 K clamped to ±1 K)"),
            (-3.0, 20.0, "shifts room target by -1.0 K (slice -3.0 K clamped to ±1 K)"),
            (1.0, 22.0, "shifts room target by +1.0 K"),
            (-0.5, 20.5, "shifts room target by -0.5 K"),
        ],
    )
    def test_a_slice_beyond_the_bound_is_clamped_and_says_so(
        self, offset: float, expected: float, note: str
    ) -> None:
        """The target moves at most the bound and the decision tells a clamp apart."""
        result = step(CTRL, None, 0, plan=rule(offset))
        assert target(result) == pytest.approx(expected)
        assert plan_note(result) == note
        assert ("clamped" in result.decision.note) == (abs(offset) > 1.0)
        assert result.decision.ladder is LadderLevel.RULE_PLAN
        assert result.decision.reason is rule(offset).reason

    def test_the_default_bound_is_one_kelvin(self) -> None:
        """The default bound is 1 K and the hard maximum 1.5 K."""
        assert MIXED.plan_rule_max_k == DEFAULT_PLAN_RULE_MAX_K == 1.0
        assert PLAN_RULE_MAX_K == 1.5

    @pytest.mark.parametrize(("bound", "expected"), [(0.5, 21.5), (1.5, 22.5), (0.0, 21.0)])
    def test_the_bound_is_configurable(self, bound: float, expected: float) -> None:
        """The bound can be lowered to 0 (rule slices off) and raised to 1.5 K."""
        ctrl = OvenbirdController(replace(MIXED, plan_rule_max_k=bound))
        result = step(ctrl, None, 0, plan=rule(3.0))
        assert target(result) == pytest.approx(expected)
        assert f"clamped to ±{bound:g} K" in plan_note(result)

    def test_a_zero_bound_leaves_the_setpoint_as_without_a_slice(self) -> None:
        """With a bound of 0 a rule slice moves nothing but the notes."""
        ctrl = OvenbirdController(replace(MIXED, plan_rule_max_k=0.0))
        shifted = step(ctrl, None, 0, plan=rule(3.0)).decision
        plain = step(ctrl, None, 0).decision
        assert shifted.pre_round == plain.pre_round
        assert shifted.setpoint == plain.setpoint

    @pytest.mark.parametrize("bound", [1.6, -0.1, math.nan, math.inf])
    def test_the_bound_never_exceeds_one_and_a_half_kelvin(self, bound: float) -> None:
        """A bound outside ``[0, 1.5]`` K is refused."""
        with pytest.raises(ValueError, match="plan_rule_max_k"):
            replace(MIXED, plan_rule_max_k=bound)

    def test_optimiser_slices_keep_their_offset(self) -> None:
        """The rule bound does not apply to an optimiser slice."""
        result = step(CTRL, None, 0, plan=rule(2.0, source=PlanSource.OPTIMISER))
        assert target(result) == pytest.approx(23.0)
        assert result.decision.ladder is LadderLevel.OPTIMISER_PLAN

    def test_without_a_room_sensor_the_bounded_offset_maps_to_water(self) -> None:
        """Without a room sensor the clamped offset is what maps through the curve."""
        result = step(CTRL, None, 0, plan=rule(5.0), room_signal=None)
        term = result.decision.term("plan")
        assert term is not None
        assert term.raw == pytest.approx(1.6)
        assert term.value == pytest.approx(1.6)
        assert "(slice +5.0 K clamped to ±1 K)" in term.note
        assert result.decision.ladder is LadderLevel.RULE_PLAN

    @pytest.mark.parametrize(
        "plan",
        [
            rule(1.0, start=-3600.0, length=3600.0),
            rule(-1.0, start=-7200.0, length=60.0),
            rule(1.0, start=60.0),
        ],
        ids=["ended-now", "ended-before", "not-yet"],
    )
    def test_an_inactive_slice_has_no_effect(self, plan: PlanSlice) -> None:
        """An expired or future slice yields the very decision of no slice."""
        shifted = step(CTRL, None, 0, plan=plan)
        plain = step(CTRL, None, 0)
        assert shifted.decision == plain.decision
        assert shifted.state == plain.state
        assert plan_note(shifted) == "no plan"


class TestStoveEntry:
    """A raised room target lifts the stove entry; a set-back does not lower it."""

    def test_a_room_following_a_raised_target_is_no_stove(self) -> None:
        """At 22.6 °C with +1 K the room follows its target: no episode."""
        result = step(STOVE, None, 0, replace(IDLE, room=22.6), rule(1.0))
        assert not result.state.stove_active
        assert result.decision.controller_state["stove_enter_c"] == pytest.approx(23.5)
        assert target(result) == pytest.approx(22.0)
        assert "enters at 23.5 °C" in (result.decision.term("stove").note)  # type: ignore[union-attr]

    def test_without_a_slice_the_same_room_is_a_stove(self) -> None:
        """Without a slice the threshold is the comfort's, as before."""
        result = step(STOVE, None, 0, replace(IDLE, room=22.6))
        assert result.state.stove_active
        assert result.decision.controller_state["stove_enter_c"] == pytest.approx(22.5)

    def test_a_room_above_the_raised_threshold_enters_and_pauses_the_slice(self) -> None:
        """Above the raised threshold the episode starts and the slice pauses."""
        result = step(STOVE, None, 0, replace(IDLE, room=23.5), rule(1.0))
        assert result.state.stove_active
        assert result.state.stove_trigger is StoveTrigger.LEVEL
        assert plan_note(result) == "paused by wood-stove mode"
        assert result.decision.ladder is LadderLevel.SCHEDULE_CURVE_FEEDBACK
        assert result.decision.reason is ReasonCode.STOVE

    def test_a_set_back_does_not_lower_the_threshold(self) -> None:
        """A negative slice keeps the comfort's threshold."""
        result = step(STOVE, None, 0, replace(IDLE, room=22.0), rule(-1.0))
        assert not result.state.stove_active
        assert result.decision.controller_state["stove_enter_c"] == pytest.approx(22.5)

    def test_the_raise_is_bounded_like_the_slice(self) -> None:
        """A slice beyond the bound lifts the threshold only by the bound."""
        result = step(STOVE, None, 0, replace(IDLE, room=23.6), rule(3.0))
        assert result.state.stove_active
        assert result.decision.controller_state["stove_enter_c"] == pytest.approx(23.5)

    def test_a_fast_rise_to_a_raised_target_is_no_stove(self) -> None:
        """A rise of 1 K that only reaches the raised target does not enter."""
        rising = [replace(IDLE, room=round(21.0 + i / 20, 2)) for i in range(21)]
        plain = run(STOVE, [IDLE] * 5 + rising)
        assert plain[-1].state.stove_trigger is StoveTrigger.RISE
        shifted = run(STOVE, [IDLE] * 5 + rising, rule(1.0))
        assert not any(r.state.stove_active for r in shifted)


class TestInteractions:
    """A slice acts through the room target; every other stage keeps its rule."""

    def test_the_start_ramp_still_caps_a_raised_target(self) -> None:
        """After a start the ramp's cap binds with or without a +1 K slice."""
        plants = [IDLE] + [replace(RUNNING, outlet=26.0)] * 5
        plain = run(CTRL, plants)
        shifted = run(CTRL, plants, rule(1.0))
        for a, b in zip(plain[1:], shifted[1:], strict=True):
            assert b.decision.binding == "start_ramp"
            assert b.decision.setpoint == a.decision.setpoint == 26
            assert b.decision.term("start_ramp").value < 0.0  # type: ignore[union-attr]

    def test_the_min_run_floor_holds_against_a_set_back(self) -> None:
        """Inside the minimum-run window a set-back cannot pull below the cycling floor."""
        results = run(NO_RAMP, [IDLE, RUNNING, RUNNING], rule(-1.0))
        last = results[-1].decision
        floor = last.term("cycling_floor")
        assert floor is not None
        assert floor.value > 0.0
        assert last.binding == "cycling_floor"
        assert last.setpoint is not None
        assert last.setpoint >= 33.0 - NO_RAMP.config.cycling.stop_delta_k

    def test_a_slice_waits_for_the_dwell(self) -> None:
        """A set-back right after a change waits for the dwell, then moves."""
        first = step(CTRL, None, 0)
        held = step(CTRL, first.state, MINUTE, plan=rule(-1.0))
        assert held.decision.setpoint == first.decision.setpoint == 31
        assert held.decision.binding == "dwell"
        assert held.decision.pre_round == pytest.approx(31.0 - KP)
        dwell = CTRL.config.stages.dwell_s
        moved = step(CTRL, held.state, dwell, plan=rule(-1.0))
        assert moved.decision.setpoint == 29

    def test_a_small_slice_stays_inside_the_deadband(self) -> None:
        """A 0.3 K shift (0.6 K water) does not move the setpoint."""
        steady = run(CTRL, [IDLE] * 30)
        result = step(CTRL, steady[-1].state, 30 * MINUTE, plan=rule(0.3))
        assert result.decision.setpoint == steady[-1].decision.setpoint
        assert result.decision.binding in ("rounding", "deadband")

    @pytest.mark.parametrize(
        ("outside", "room", "integral", "offset"),
        [(-10.0, 15.0, 3.0, 3.0), (15.0, 30.0, -3.0, -3.0), (5.0, 15.0, 3.0, 3.0)],
    )
    def test_the_shift_never_leaves_the_safety_envelope(
        self, outside: float, room: float, integral: float, offset: float
    ) -> None:
        """At the largest bound and a saturated PI the setpoint stays inside the envelope."""
        ctrl = OvenbirdController(replace(MIXED, plan_rule_max_k=PLAN_RULE_MAX_K))
        state = replace(ctrl.initial_state(), integral_k=integral)
        result = step(ctrl, state, 0, PlantView(outside=outside, room=room), rule(offset))
        bounds = ctrl.config.safety.bounds(outside)
        assert result.decision.setpoint is not None
        assert bounds.low_int <= result.decision.setpoint <= bounds.high_int
        assert result.decision.pre_round is not None
        assert bounds.low - 1e-9 <= result.decision.pre_round <= bounds.high + 1e-9
        assert abs(target(result) - COMFORT) == pytest.approx(PLAN_RULE_MAX_K)

    @pytest.mark.parametrize(
        ("plant", "frozen"),
        [(replace(RUNNING, defrost=1), "defrost"), (replace(RUNNING, valve=1), "dhw")],
    )
    def test_a_set_back_never_lowers_during_defrost_or_hot_water(
        self, plant: PlantView, frozen: str
    ) -> None:
        """During defrost and DHW the setpoint does not fall and the integrator is frozen."""
        steady = run(CTRL, [RUNNING] * 40)[-1]
        results = run(CTRL, [plant] * 20, rule(-1.0), state=steady.state, start=40 * MINUTE)
        for result in results:
            assert result.decision.setpoint is not None
            assert steady.decision.setpoint is not None
            assert result.decision.setpoint >= steady.decision.setpoint
            assert result.state.integral_k == steady.state.integral_k
            assert frozen in str(result.decision.controller_state["frozen_by"])
            assert target(result) == pytest.approx(COMFORT - 1.0)

    def test_an_untrusted_room_value_pauses_the_slice(self) -> None:
        """A stale room value: the slice has no effect, not even through water."""
        stale = replace(IDLE, stale=frozenset({ROOM_SIGNAL}))
        state = run(CTRL, [IDLE] * 30)[-1].state
        shifted = step(CTRL, state, 30 * MINUTE, stale, rule(1.0))
        plain = step(CTRL, state, 30 * MINUTE, stale)
        assert shifted.decision.pre_round == plain.decision.pre_round
        assert shifted.decision.setpoint == plain.decision.setpoint
        assert shifted.state == plain.state
        assert plan_note(shifted) == "paused: room value not trusted"
        assert shifted.decision.reason is ReasonCode.ROOM_STALE
        assert shifted.decision.ladder is LadderLevel.CURVE_ONLY
        plan = shifted.decision.term("plan")
        assert plan is not None
        assert plan.value == 0.0

    def test_an_episode_pauses_the_slice_and_holds_the_integrator(self) -> None:
        """In stove mode the PI is frozen at comfort; the slice is only noted."""
        hot = replace(IDLE, room=24.0)
        results = run(STOVE, [hot] * 10, rule(-1.0))
        for before, result in pairwise(results):
            assert result.state.stove_active
            assert result.state.integral_k == before.state.integral_k
            assert plan_note(result) == "paused by wood-stove mode"
            assert "plan -1.0 K room paused by wood-stove mode" in result.decision.note
            assert result.decision.controller_state["room_target_c"] == pytest.approx(COMFORT)

    def test_the_recovery_tail_pauses_the_slice_until_the_room_has_cooled(self) -> None:
        """After a manual stop with a warm room the slice waits until the room cooled."""
        warm = replace(IDLE, room=22.0)
        stop = Override(OverrideKind.STOVE, 0.0)
        stopped = step(STOVE, None, 0, warm, rule(1.0), override=stop)
        assert stopped.state.stove_blocked
        tail = step(STOVE, stopped.state, MINUTE, warm, rule(1.0))
        for result in (stopped, tail):
            assert plan_note(result).startswith("paused: the room is still warm")
            assert target(result) == pytest.approx(COMFORT)
            assert result.decision.ladder is LadderLevel.SCHEDULE_CURVE_FEEDBACK
        cooled = step(STOVE, tail.state, 2 * MINUTE, replace(IDLE, room=21.0), rule(1.0))
        assert not cooled.state.stove_blocked
        assert target(cooled) == pytest.approx(COMFORT + 1.0)
        assert cooled.decision.ladder is LadderLevel.RULE_PLAN

    def test_a_reached_set_back_target_leaves_the_integrator_alone(self) -> None:
        """Once the room sits at the set-back target the integrator stops winding."""
        cold = replace(IDLE, room=COMFORT - 1.0)
        results = run(CTRL, [cold] * (8 * 60), rule(-1.0))
        assert all(r.state.integral_k == 0.0 for r in results)
        assert all(r.decision.controller_state["room_error_k"] == 0.0 for r in results)

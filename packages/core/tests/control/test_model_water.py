"""A model water slice in the controller: bounds, authority, blocks, order, integrator, replay."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ovenbird_core.control import (
    DecisionRecord,
    LadderLevel,
    ModelPlanBlock,
    ModelPlanConfig,
    OvenbirdConfig,
    OvenbirdController,
    OvenbirdState,
    PlanSlice,
    PlanSource,
    ReasonCode,
    RoomSensorProfile,
    StepResult,
    StoveConfig,
    control_inputs,
    recorded_model_plan,
    replay_inputs,
)
from ovenbird_core.control.config import MODEL_PLAN_MAX_LOWER_WATER_K
from ovenbird_core.control.synthetic import ROOM_SIGNAL, PlantView, synthetic_snapshot
from ovenbird_core.control.types import RoomProfile
from ovenbird_core.instant import Instant

T0 = 1_794_528_000.0
MIXED = OvenbirdConfig.preset("mixed")
CTRL = OvenbirdController(MIXED)
ON_CHANGE = replace(MIXED, room=RoomSensorProfile(kind=RoomProfile.ON_CHANGE))
STOVE_CTRL = OvenbirdController(OvenbirdConfig.preset("mixed", stove=StoveConfig()))
IDLE = PlantView()
MODEL_KEYS = (
    "model_plan_requested_k",
    "model_plan_applied_k",
    "model_plan_ignored",
    "model_plan_water_requested_k",
    "model_plan_water_applied_k",
    "model_plan_authority",
)


def at(seconds: float) -> Instant:
    return Instant.from_unix(T0 + seconds)


def water_plan(offset: float, start: float = 0.0, length: float = 1200.0) -> PlanSlice:
    reason = ReasonCode.PLAN_SETBACK if offset < 0.0 else ReasonCode.PLAN_PREHEAT
    return PlanSlice(
        0.0, reason, at(start), at(start + length), PlanSource.MODEL, water_offset_k=offset
    )


def tick(
    state: OvenbirdState,
    t: float,
    plant: PlantView = IDLE,
    controller: OvenbirdController = CTRL,
    plan: PlanSlice | None = None,
    room_signal: str | None = ROOM_SIGNAL,
) -> StepResult[OvenbirdState]:
    snapshot = synthetic_snapshot(at(t), plant)
    inputs = control_inputs(
        snapshot,
        room_signal=room_signal,
        room_profile=controller.config.room,
        plan=plan,
    )
    return controller.step(state, inputs)


def run(
    plants: Sequence[tuple[float, PlantView]],
    controller: OvenbirdController = CTRL,
    plan: PlanSlice | None = None,
    state: OvenbirdState | None = None,
) -> list[StepResult[OvenbirdState]]:
    current = state or controller.initial_state()
    out = []
    for t, plant in plants:
        result = tick(current, t, plant, controller, plan)
        out.append(result)
        current = result.state
    return out


def state_of(result: StepResult[OvenbirdState]) -> dict[str, object]:
    return dict(result.decision.controller_state)


class TestPlanSlice:
    def test_water_offset_defaults_to_zero(self) -> None:
        plan = PlanSlice(-0.3, ReasonCode.PLAN_SETBACK, at(0), at(900), PlanSource.MODEL)
        assert plan.water_offset_k == 0.0
        assert not plan.water

    def test_only_a_model_slice_carries_water(self) -> None:
        with pytest.raises(ValueError, match="model"):
            PlanSlice(0.0, ReasonCode.PLAN_SETBACK, at(0), at(900), water_offset_k=-1.0)

    def test_room_and_water_offsets_are_exclusive(self) -> None:
        with pytest.raises(ValueError, match="not both"):
            PlanSlice(
                -0.2, ReasonCode.PLAN_SETBACK, at(0), at(900), PlanSource.MODEL, water_offset_k=-1.0
            )

    def test_water_offset_must_be_finite(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            water_plan(float("nan"))


class TestAuthority:
    @pytest.mark.parametrize(
        ("room", "expected"),
        [(21.3, 1.0), (21.0, 1.0), (20.9, 1.0), (20.8, 2 / 3), (20.7, 1 / 3), (20.6, 0.0)],
    )
    def test_fine_sensor_fades_in_its_steps(self, room: float, expected: float) -> None:
        authority = ModelPlanConfig().authority(room, 21.0, -1.0, 0.1)
        assert authority == pytest.approx(expected)

    @pytest.mark.parametrize(
        ("room", "expected"), [(21.0, 1.0), (20.8, 1.0), (20.7, 0.5), (20.6, 0.0), (20.4, 0.0)]
    )
    def test_full_edge_is_at_least_one_sensor_step(self, room: float, expected: float) -> None:
        authority = ModelPlanConfig().authority(room, 21.0, -1.0, 0.2)
        assert authority == pytest.approx(expected)

    def test_coarse_sensor_switches_at_one_step(self) -> None:
        mp = ModelPlanConfig()
        assert mp.authority(20.5, 21.0, -1.0, 0.5) == 1.0
        assert mp.authority(20.4, 21.0, -1.0, 0.5) == 0.0

    @pytest.mark.parametrize(
        ("room", "expected"), [(20.0, 1.0), (21.1, 1.0), (21.2, 2 / 3), (21.4, 0.0)]
    )
    def test_raise_mirrors_above_comfort(self, room: float, expected: float) -> None:
        assert ModelPlanConfig().authority(room, 21.0, 1.0) == pytest.approx(expected)

    def test_no_sign_is_full(self) -> None:
        assert ModelPlanConfig().authority(15.0, 21.0, 0.0) == 1.0

    def test_edges_must_be_ordered(self) -> None:
        with pytest.raises(ValueError, match="authority_full_k"):
            ModelPlanConfig(authority_full_k=0.4, authority_zero_k=0.4)

    @pytest.mark.parametrize("overrides", [{"max_lower_water_k": 4.1}, {"max_raise_water_k": 2.1}])
    def test_water_bounds_have_ceilings(self, overrides: dict[str, float]) -> None:
        with pytest.raises(ValueError, match="water_k must be in"):
            ModelPlanConfig(**overrides)

    def test_v1_defaults_are_unchanged(self) -> None:
        mp = ModelPlanConfig()
        assert (mp.max_setback_k, mp.max_preheat_k) == (0.5, 0.3)
        assert (mp.max_lower_water_k, mp.max_raise_water_k) == (3.0, 0.0)
        assert (mp.authority_full_k, mp.authority_zero_k) == (0.1, 0.4)


class TestApplied:
    def test_lowers_the_water_and_leaves_the_room_target(self) -> None:
        plain = tick(CTRL.initial_state(), 0).decision
        decision = tick(CTRL.initial_state(), 0, plan=water_plan(-2.5)).decision
        assert decision.ladder is LadderLevel.MODEL_PLAN
        assert decision.reason is ReasonCode.PLAN_SETBACK
        assert decision.controller_state["room_target_c"] == pytest.approx(21.0)
        assert decision.term("room_feedback") == plain.term("room_feedback")
        plan = decision.term("plan")
        assert plan is not None
        assert (plan.raw, plan.value) == (-2.5, -2.5)
        assert plan.note == "model plan -2.5 K water for the forecast sun"
        assert decision.pre_round == pytest.approx(plain.pre_round - 2.5)  # type: ignore[operator]
        assert decision.setpoint == 29
        assert "model plan -2.5 K water for the forecast sun" in decision.note
        state = decision.controller_state
        assert state["model_plan_water_requested_k"] == -2.5
        assert state["model_plan_water_applied_k"] == -2.5
        assert state["model_plan_authority"] == 1.0
        assert state["model_plan_requested_k"] == 0.0
        assert state["model_plan_applied_k"] == 0.0
        assert state["model_plan_ignored"] is None

    def test_scaled_by_the_room_authority(self) -> None:
        cool = replace(IDLE, room=20.8)
        plain = tick(CTRL.initial_state(), 0, cool).decision
        decision = tick(CTRL.initial_state(), 0, cool, plan=water_plan(-3.0)).decision
        state = decision.controller_state
        assert state["model_plan_authority"] == pytest.approx(2 / 3)
        assert state["model_plan_water_applied_k"] == pytest.approx(-2.0)
        assert decision.binding == "plan_limit"
        assert "room authority 66 %" in decision.note
        assert decision.pre_round == pytest.approx(plain.pre_round - 2.0)  # type: ignore[operator]

    def test_no_authority_is_no_plan(self) -> None:
        cold = replace(IDLE, room=20.6)
        plain = tick(CTRL.initial_state(), 0, cold).decision
        decision = tick(CTRL.initial_state(), 0, cold, plan=water_plan(-3.0)).decision
        assert decision.ladder is LadderLevel.SCHEDULE_CURVE_FEEDBACK
        assert decision.reason is plain.reason
        assert decision.pre_round == plain.pre_round
        assert decision.setpoint == plain.setpoint
        assert decision.binding == plain.binding
        assert decision.controller_state["model_plan_authority"] == 0.0
        assert decision.controller_state["model_plan_water_applied_k"] == 0.0
        assert decision.controller_state["model_plan_ignored"] is None
        assert "room authority 0 %" in decision.note

    def test_clamped_to_the_lowering_bound(self) -> None:
        decision = tick(CTRL.initial_state(), 0, plan=water_plan(-10.0)).decision
        plan = decision.term("plan")
        assert plan is not None
        assert (plan.raw, plan.value) == (-10.0, -3.0)
        assert decision.controller_state["model_plan_water_applied_k"] == -3.0
        assert decision.binding == "plan_limit"

    def test_a_raise_is_cut_to_zero_by_default(self) -> None:
        plain = tick(CTRL.initial_state(), 0).decision
        decision = tick(CTRL.initial_state(), 0, plan=water_plan(1.0)).decision
        assert decision.ladder is LadderLevel.SCHEDULE_CURVE_FEEDBACK
        assert decision.pre_round == plain.pre_round
        assert decision.controller_state["model_plan_water_applied_k"] == 0.0
        assert "cut to 0 by the model water bounds" in decision.note

    def test_a_raise_applies_when_allowed_and_fades_above_comfort(self) -> None:
        cfg = OvenbirdConfig.preset("mixed", model_plan=ModelPlanConfig(max_raise_water_k=1.0))
        ctrl = OvenbirdController(cfg)
        decision = tick(ctrl.initial_state(), 0, controller=ctrl, plan=water_plan(1.5)).decision
        assert decision.ladder is LadderLevel.MODEL_PLAN
        assert decision.reason is ReasonCode.PLAN_PREHEAT
        assert decision.controller_state["model_plan_water_applied_k"] == 1.0
        warm = replace(IDLE, room=21.4)
        decision = tick(ctrl.initial_state(), 0, warm, ctrl, water_plan(1.5)).decision
        assert decision.controller_state["model_plan_water_applied_k"] == 0.0

    def test_on_change_sensor_keeps_full_authority_one_step_below(self) -> None:
        ctrl = OvenbirdController(ON_CHANGE)
        cool = replace(IDLE, room=20.8)
        decision = tick(ctrl.initial_state(), 0, cool, ctrl, water_plan(-3.0)).decision
        assert decision.controller_state["model_plan_authority"] == 1.0
        assert decision.controller_state["model_plan_water_applied_k"] == -3.0


RECOVERY = {
    "stove_blocked": replace(STOVE_CTRL.initial_state(), stove_blocked=True),
    "stove_level_blocked": replace(STOVE_CTRL.initial_state(), stove_level_blocked=True),
    "stove_fault": replace(STOVE_CTRL.initial_state(), stove_fault=True),
    "stove_reentry_wait": replace(STOVE_CTRL.initial_state(), stove_reentry_wait=True),
}


class TestIgnored:
    def test_without_a_room_sensor(self) -> None:
        plain = tick(CTRL.initial_state(), 0, room_signal=None).decision
        decision = tick(CTRL.initial_state(), 0, plan=water_plan(-2.0), room_signal=None).decision
        assert decision.ladder is LadderLevel.CURVE_ONLY
        assert decision.pre_round == plain.pre_round
        state = decision.controller_state
        assert state["model_plan_ignored"] == ModelPlanBlock.ROOM_UNTRUSTED.value
        assert state["model_plan_water_applied_k"] == 0.0
        assert state["model_plan_authority"] is None
        assert "model plan -2.0 K water ignored" in decision.note

    def test_from_the_tick_the_room_value_goes_stale(self) -> None:
        fresh = replace(IDLE, room=21.0)
        lost = replace(fresh, stale=frozenset({ROOM_SIGNAL}))
        planned = run([(0, fresh), (60, lost)], plan=water_plan(-2.0))
        plain = run([(0, fresh), (60, lost)])
        assert planned[0].decision.ladder is LadderLevel.MODEL_PLAN
        last = planned[-1].decision
        assert last.controller_state["model_plan_ignored"] == "room_untrusted"
        assert last.pre_round == pytest.approx(plain[-1].decision.pre_round)

    def test_during_a_stove_episode(self) -> None:
        hot = replace(IDLE, room=22.6)
        result = tick(STOVE_CTRL.initial_state(), 0, hot, STOVE_CTRL, water_plan(-3.0))
        assert result.state.stove_active
        assert result.decision.controller_state["model_plan_ignored"] == "stove_active"
        assert result.decision.ladder is not LadderLevel.MODEL_PLAN
        plan = result.decision.term("plan")
        assert plan is not None
        assert plan.value == 0.0

    @pytest.mark.parametrize(
        "flag", ["stove_blocked", "stove_level_blocked", "stove_fault", "stove_reentry_wait"]
    )
    def test_while_the_stove_detection_recovers(self, flag: str) -> None:
        state = RECOVERY[flag]
        warm = replace(IDLE, room=22.2)
        result = tick(state, 0, warm, STOVE_CTRL, water_plan(-3.0))
        assert result.decision.controller_state["model_plan_ignored"] == "stove_recovery"
        assert result.decision.ladder is LadderLevel.SCHEDULE_CURVE_FEEDBACK

    def test_a_slice_valid_for_too_long(self) -> None:
        decision = tick(CTRL.initial_state(), 0, plan=water_plan(-2.0, length=7200.0)).decision
        assert decision.controller_state["model_plan_ignored"] == "slice_too_long"
        assert decision.ladder is LadderLevel.SCHEDULE_CURVE_FEEDBACK

    def test_an_expired_slice_is_no_plan(self) -> None:
        decision = tick(CTRL.initial_state(), 1300, plan=water_plan(-2.0)).decision
        assert not any(key.startswith("model_plan") for key in decision.controller_state)


class TestExtras:
    def test_absent_without_a_slice(self) -> None:
        decision = tick(CTRL.initial_state(), 0).decision
        assert not any(key.startswith("model_plan") for key in decision.controller_state)

    def test_a_room_target_slice_has_no_water_extras(self) -> None:
        plan = PlanSlice(-0.4, ReasonCode.PLAN_SETBACK, at(0), at(1200), PlanSource.MODEL)
        state = tick(CTRL.initial_state(), 0, plan=plan).decision.controller_state
        assert set(MODEL_KEYS[:3]) <= set(state)
        assert not set(MODEL_KEYS[3:]) & set(state)

    def test_a_water_slice_has_every_extra(self) -> None:
        state = tick(CTRL.initial_state(), 0, plan=water_plan(-1.0)).decision.controller_state
        assert set(MODEL_KEYS) <= set(state)


RUNNING = PlantView(compressor_hz=35, outlet=33.0)


class TestOrder:
    def test_minimum_setpoint_wins_and_cooling_does_not_wind(self) -> None:
        warm = PlantView(outside=15.0, room=21.8)
        start = replace(CTRL.initial_state(), integral_k=-1.0)
        plain = run([(0, warm), (60, warm)], state=start)
        planned = run([(0, warm), (60, warm)], plan=water_plan(-3.0), state=start)
        decision = planned[-1].decision
        low = decision.controller_state["safety_low_c"]
        assert isinstance(low, float)
        assert decision.pre_round == pytest.approx(low)
        assert decision.reason is ReasonCode.SAFETY_CLAMP
        assert "anti_windup" in str(decision.controller_state["frozen_by"])
        assert planned[-1].state.integral_k == -1.0
        assert plain[-1].state.integral_k < -1.0

    def test_cycling_floor_wins_inside_the_min_run_window(self) -> None:
        warm = replace(RUNNING, room=21.2)
        sequence = [(0, replace(IDLE, room=21.2)), (60, warm), (120, warm)]
        planned = run(sequence, plan=water_plan(-3.0, length=1200.0))
        decision = planned[-1].decision
        floor = decision.term("cycling_floor")
        assert floor is not None
        assert floor.value > 0.0
        assert decision.controller_state["model_plan_water_applied_k"] == -3.0
        assert decision.binding == "cycling_floor"
        assert "anti_windup" in str(decision.controller_state["frozen_by"])
        assert planned[-1].state.integral_k == planned[0].state.integral_k

    def test_the_term_sits_before_the_ramp_floor_and_safety(self) -> None:
        names = [
            term.name
            for term in tick(CTRL.initial_state(), 0, plan=water_plan(-1.0)).decision.terms
        ]
        assert names.index("room_feedback") < names.index("plan") < names.index("start_ramp")
        assert names.index("plan") < names.index("cycling_floor") < names.index("safety")

    def test_an_authority_drop_waits_for_the_dwell(self) -> None:
        fine = replace(IDLE, room=21.0)
        cold = replace(IDLE, room=20.6)
        sequence = [(0, fine), (60, cold), (960, cold)]
        planned = run(sequence, plan=water_plan(-3.0, length=1200.0))
        plain = run(sequence)
        assert planned[0].decision.setpoint == 28
        assert planned[1].decision.binding == "dwell"
        assert planned[1].decision.setpoint == 28
        assert planned[2].decision.pre_round == plain[2].decision.pre_round
        assert planned[2].decision.setpoint == round(plain[2].decision.pre_round or 0.0)
        assert planned[2].decision.controller_state["model_plan_authority"] == 0.0


class TestIntegrator:
    def test_a_correct_plan_leaves_the_integrator_alone(self) -> None:
        sequence = [(60.0 * i, replace(IDLE, room=21.0)) for i in range(20)]
        planned = run(sequence, plan=water_plan(-2.0, length=1200.0))
        assert all(result.state.integral_k == 0.0 for result in planned)

    def test_the_offset_does_not_enter_the_integrator(self) -> None:
        sequence = [(60.0 * i, replace(IDLE, room=20.9)) for i in range(20)]
        planned = run(sequence, plan=water_plan(-1.5, length=1200.0))
        plain = run(sequence)
        assert [r.state.integral_k for r in planned] == [r.state.integral_k for r in plain]
        assert planned[-1].state.integral_k > 0.0


class TestReplay:
    def test_a_water_decision_is_reproduced_from_its_record(self) -> None:
        cfg = OvenbirdConfig.preset("mixed")
        controller = OvenbirdController(cfg)
        state = controller.initial_state()
        rooms = [21.0, 21.0, 20.8, 20.8, 20.7, 20.6, 20.9, 21.0]
        records: list[DecisionRecord] = []
        for index, room in enumerate(rooms):
            plan = water_plan(-0.5 * (index + 1), start=120.0 * index, length=1200.0)
            snapshot = synthetic_snapshot(at(120.0 * index), replace(IDLE, room=room))
            inputs = control_inputs(
                snapshot, room_signal=ROOM_SIGNAL, room_profile=cfg.room, plan=plan
            )
            result = controller.step(state, inputs)
            state = result.state
            text = json.dumps(result.decision.to_json_dict())
            records.append(DecisionRecord.from_json_dict(json.loads(text)))
        replayed = controller.initial_state()
        for record in records:
            rebuilt = recorded_model_plan(record)
            assert rebuilt is not None
            assert rebuilt.water
            inputs = replace(
                replay_inputs(record, room_signal=ROOM_SIGNAL, room_profile=cfg.room), plan=rebuilt
            )
            result = controller.step(replayed, inputs)
            replayed = result.state
            assert result.decision.setpoint == record.setpoint
            assert result.decision.pre_round == record.pre_round
            assert result.decision.reason is record.reason
            assert result.decision.ladder is record.ladder
            for key in MODEL_KEYS:
                assert result.decision.controller_state[key] == record.controller_state[key]

    def test_records_without_a_model_slice_rebuild_none(self) -> None:
        record = tick(CTRL.initial_state(), 0).decision
        assert recorded_model_plan(record) is None

    def test_a_room_target_record_rebuilds_a_room_target_slice(self) -> None:
        plan = PlanSlice(-0.4, ReasonCode.PLAN_SETBACK, at(0), at(1200), PlanSource.MODEL)
        rebuilt = recorded_model_plan(tick(CTRL.initial_state(), 0, plan=plan).decision)
        assert rebuilt is not None
        assert (rebuilt.room_offset_k, rebuilt.water_offset_k) == (-0.4, 0.0)


CONTROLLERS = (CTRL, OvenbirdController(ON_CHANGE))
WATER = st.floats(-1e3, 1e3, allow_nan=False).filter(lambda value: value != 0.0)
ROOMS = st.floats(17.0, 25.0).map(lambda value: round(value, 1))


@settings(max_examples=300, deadline=None)
@given(
    controller=st.sampled_from(CONTROLLERS),
    requested=WATER,
    room=ROOMS,
    lower=st.floats(0.0, MODEL_PLAN_MAX_LOWER_WATER_K),
    raise_=st.floats(0.0, 2.0),
    outside=st.integers(-15, 18),
)
def test_applied_offset_stays_within_the_bounds_whatever_the_slice(
    controller: OvenbirdController,
    requested: float,
    room: float,
    lower: float,
    raise_: float,
    outside: int,
) -> None:
    mp = ModelPlanConfig(max_lower_water_k=lower, max_raise_water_k=raise_)
    ctrl = OvenbirdController(replace(controller.config, model_plan=mp))
    plant = PlantView(outside=float(outside), room=room)
    decision = tick(ctrl.initial_state(), 0, plant, ctrl, water_plan(requested)).decision
    applied = decision.controller_state["model_plan_water_applied_k"]
    assert isinstance(applied, float)
    assert applied >= -MODEL_PLAN_MAX_LOWER_WATER_K
    assert -lower - 1e-12 <= applied <= raise_ + 1e-12
    plan = decision.term("plan")
    assert plan is not None
    assert plan.value == applied
    plain = tick(ctrl.initial_state(), 0, plant, ctrl).decision
    low = decision.controller_state["safety_low_c"]
    high = decision.controller_state["safety_high_c"]
    assert isinstance(low, float)
    assert isinstance(high, float)
    assert decision.pre_round is not None
    assert low - 1e-9 <= decision.pre_round <= high + 1e-9
    if applied == 0.0:
        assert decision.pre_round == plain.pre_round
        assert decision.setpoint == plain.setpoint
        assert decision.ladder is plain.ladder


@settings(max_examples=200, deadline=None)
@given(
    controller=st.sampled_from(CONTROLLERS),
    requested=st.floats(-1e3, -1e-6),
    shortfall=st.floats(0.4, 4.0),
)
def test_no_authority_below_the_fade(
    controller: OvenbirdController, requested: float, shortfall: float
) -> None:
    room = round(controller.config.comfort_room_c - shortfall, 1)
    if controller.config.comfort_room_c - room < 0.4:
        room = round(room - 0.1, 1)
    plant = PlantView(room=room)
    decision = tick(
        controller.initial_state(), 0, plant, controller, water_plan(requested)
    ).decision
    plain = tick(controller.initial_state(), 0, plant, controller).decision
    assert decision.controller_state["model_plan_authority"] == 0.0
    assert decision.controller_state["model_plan_water_applied_k"] == 0.0
    assert decision.pre_round == plain.pre_round
    assert decision.setpoint == plain.setpoint
    assert decision.ladder is plain.ladder
    assert decision.reason is plain.reason


@settings(max_examples=100, deadline=None)
@given(
    rooms=st.lists(ROOMS, min_size=1, max_size=12),
    requested=WATER,
    after=st.floats(1201.0, 5000.0),
)
def test_an_expired_or_absent_slice_is_identical_to_no_plan(
    rooms: list[float], requested: float, after: float
) -> None:
    plants = [(60.0 * i + after, PlantView(room=room)) for i, room in enumerate(rooms)]
    expired = run(plants, plan=water_plan(requested))
    plain = run(plants)
    for a, b in zip(expired, plain, strict=True):
        assert a.decision.to_json_dict() == b.decision.to_json_dict()
        assert a.state == b.state

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from dataclasses import fields as dataclass_fields
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from ovenbird_core.catalogue import HeishaSignal
from ovenbird_core.control import (
    ControlInputs,
    DecisionRecord,
    IntentKind,
    LadderLevel,
    Mode,
    OvenbirdConfig,
    OvenbirdController,
    OvenbirdState,
    Override,
    OverrideKind,
    PlanSlice,
    PlanSource,
    PumpDutyConfig,
    RampPhase,
    ReasonCode,
    StepResult,
    StoveConfig,
)
from ovenbird_core.control.synthetic import ROOM_SIGNAL, PlantView, synthetic_inputs
from ovenbird_core.instant import Instant

T0 = 1_794_528_000.0
FIXTURES = Path(__file__).parent / "fixtures"
CONTROLLERS = (
    *(
        OvenbirdController(replace(OvenbirdConfig.preset(emitter), pump_duty=PumpDutyConfig()))
        for emitter in ("screed_floor", "radiators", "mixed")
    ),
    OvenbirdController(OvenbirdConfig.preset("mixed")),
    OvenbirdController(OvenbirdConfig.preset("mixed", stove=StoveConfig(min_active_s=0.0))),
    OvenbirdController(
        OvenbirdConfig.preset(
            "screed_floor", stove=StoveConfig(to_minimum=True, rise_k=None, max_active_s=3600.0)
        )
    ),
)
STOVE_CONTROLLERS = tuple(c for c in CONTROLLERS if c.config.stove is not None)
HARD_BINDINGS = frozenset(
    {"safety_max", "safety_min", "envelope_max", "envelope_min", "cycling_floor", "override"}
)
STALEABLE = (
    HeishaSignal.OUTSIDE_TEMP,
    HeishaSignal.OUTLET_TEMP,
    HeishaSignal.HEATING_MODE,
    HeishaSignal.DEFROSTING_STATE,
    ROOM_SIGNAL,
)

plants = st.builds(
    PlantView,
    outside=st.one_of(st.integers(-25, 25).map(float), st.none()),
    outlet=st.integers(60, 220).map(lambda q: q / 4),
    inlet=st.integers(60, 200).map(lambda q: q / 4),
    compressor_hz=st.one_of(st.just(0), st.integers(16, 90)),
    defrost=st.sampled_from([0, 0, 0, 1]),
    valve=st.sampled_from([0, 0, 0, 1]),
    heating_mode=st.sampled_from([1] * 9 + [0]),
    operating_mode=st.sampled_from([0] * 18 + [1, 3]),
    water_target=st.one_of(st.none(), st.integers(20, 45)),
    max_pump_duty=st.one_of(st.none(), st.integers(60, 254)),
    room=st.one_of(st.none(), st.integers(150, 260).map(lambda q: q / 10)),
    alive=st.sampled_from([True] * 9 + [False]),
    stale=st.one_of(
        st.just(frozenset[str]()),
        st.just(frozenset[str]()),
        st.frozensets(st.sampled_from(STALEABLE), max_size=2),
    ),
)


@dataclass(frozen=True)
class Tick:
    dt: float
    plant: PlantView
    mode: Mode
    override: Override | None
    plan_offset: float | None
    plan_source: PlanSource = PlanSource.RULE


ticks = st.builds(
    Tick,
    dt=st.sampled_from([30.0, 60.0, 60.0, 60.0, 120.0, 600.0, 3600.0]),
    plant=plants,
    mode=st.sampled_from([Mode.AUTO] * 8 + [Mode.SHADOW, Mode.MANUAL, Mode.OFF]),
    override=st.one_of(
        st.none(),
        st.none(),
        st.builds(
            Override,
            kind=st.sampled_from(OverrideKind),
            value=st.integers(-30, 80).map(float),
        ),
    ),
    plan_offset=st.one_of(st.none(), st.floats(-3.0, 3.0, allow_nan=False)),
)


@st.composite
def steady(draw: st.DrawFn) -> list[Tick]:
    """A controllable plant drifting slowly: outside and room as random walks."""
    outside = draw(st.integers(-15, 15))
    room = draw(st.integers(185, 235)) / 10
    outlet = draw(st.integers(100, 160)) / 4
    running = draw(st.booleans())
    sequence = []
    for _ in range(draw(st.integers(2, 90))):
        outside = min(25, max(-25, outside + draw(st.sampled_from([-1, 0, 0, 0, 0, 0, 1]))))
        room = round(room + draw(st.sampled_from([-0.1, 0.0, 0.0, 0.0, 0.1])), 1)
        outlet = min(55.0, max(15.0, outlet + draw(st.sampled_from([-1.0, -0.25, 0.0, 0.25, 1.0]))))
        if draw(st.integers(0, 19)) == 0:
            running = not running
        defrost = running and draw(st.integers(0, 29)) == 0
        plant = PlantView(
            outside=float(outside),
            outlet=outlet,
            compressor_hz=40 if running else 0,
            defrost=int(defrost),
            room=room,
        )
        sequence.append(Tick(60.0, plant, Mode.AUTO, None, None))
    return sequence


def inputs_for(t: float, tick: Tick) -> ControlInputs:
    now = Instant.from_unix(T0 + t)
    plan = None
    if tick.plan_offset is not None:
        reason = ReasonCode.PLAN_PREHEAT if tick.plan_offset > 0 else ReasonCode.PLAN_SETBACK
        plan = PlanSlice(tick.plan_offset, reason, now, now.shifted(900), tick.plan_source)
    return synthetic_inputs(now, tick.plant, mode=tick.mode, override=tick.override, plan=plan)


def drive(
    controller: OvenbirdController, sequence: list[Tick]
) -> list[tuple[OvenbirdState, ControlInputs, StepResult[OvenbirdState]]]:
    state = controller.initial_state()
    t = 0.0
    out = []
    for tick in sequence:
        t += tick.dt
        inputs = inputs_for(t, tick)
        result = controller.step(state, inputs)
        out.append((state, inputs, result))
        state = result.state
    return out


@settings(max_examples=150, deadline=None)
@given(controller=st.sampled_from(CONTROLLERS), sequence=st.lists(ticks, min_size=1, max_size=40))
def test_setpoint_always_within_safety_limits(
    controller: OvenbirdController, sequence: list[Tick]
) -> None:
    safety = controller.config.safety
    for _, inputs, result in drive(controller, sequence):
        decision = result.decision
        for intent in result.intents:
            if intent.kind is IntentKind.WATER_SETPOINT:
                assert safety.min_setpoint_c <= intent.value <= safety.max_supply_c
                assert intent.value == decision.setpoint
        outside = inputs.snapshot.fresh_value(HeishaSignal.OUTSIDE_TEMP)
        if (
            decision.ladder is LadderLevel.HOLD
            and decision.setpoint is not None
            and isinstance(outside, float)
        ):
            held = safety.bounds(outside)
            assert held.low_int <= decision.setpoint <= held.high_int
        if decision.ladder in (LadderLevel.HOLD, LadderLevel.REFUSE):
            continue
        assert decision.setpoint is not None
        assert isinstance(outside, float)
        bounds = safety.bounds(outside)
        assert bounds.low_int <= decision.setpoint <= bounds.high_int
        assert decision.pre_round is not None
        assert bounds.low - 1e-9 <= decision.pre_round <= bounds.high + 1e-9


@settings(max_examples=150, deadline=None)
@given(controller=st.sampled_from(CONTROLLERS), sequence=st.lists(ticks, min_size=1, max_size=40))
def test_refusal_and_hold_semantics(controller: OvenbirdController, sequence: list[Tick]) -> None:
    for before, inputs, result in drive(controller, sequence):
        decision = result.decision
        if decision.ladder is LadderLevel.REFUSE:
            assert result.intents == ()
            assert decision.setpoint is None
            assert result.state.integral_k == before.integral_k
        if not inputs.snapshot.heishamon.alive or inputs.mode is Mode.OFF:
            assert decision.ladder is LadderLevel.REFUSE
        if inputs.actual.heating_mode is not None and inputs.actual.heating_mode.value != 1:
            assert decision.ladder is LadderLevel.REFUSE
        if decision.ladder is LadderLevel.HOLD:
            outside = inputs.snapshot.fresh_value(HeishaSignal.OUTSIDE_TEMP)
            expected = before.setpoint
            if expected is not None and isinstance(outside, float):
                bounds = controller.config.safety.bounds(outside)
                expected = bounds.clamp_int(expected)
                sources = {bounds.low_source.value, bounds.high_source.value}
                if expected != before.setpoint:
                    assert decision.binding in sources
                    assert "clamps the held" in decision.note
            assert decision.setpoint == expected
            assert (decision.binding is None) == (expected == before.setpoint)
            assert result.state.integral_k == before.integral_k
        limit = controller.config.feedback
        assert abs(result.state.integral_k) <= limit.integral_limit_k + 1e-12
        feedback = decision.term("room_feedback")
        if feedback is not None:
            assert abs(feedback.value) <= limit.output_limit_k + 1e-12


@settings(max_examples=150, deadline=None)
@given(
    controller=st.sampled_from(STOVE_CONTROLLERS), sequence=st.lists(ticks, min_size=1, max_size=40)
)
def test_stove_episode_holds_the_integrator(
    controller: OvenbirdController, sequence: list[Tick]
) -> None:
    for before, _, result in drive(controller, sequence):
        state = result.state
        if before.stove_active and state.stove_active:
            assert state.integral_k == before.integral_k
            assert state.stove_integral_k == before.stove_integral_k
        if state.stove_active and result.decision.ladder not in (
            LadderLevel.HOLD,
            LadderLevel.REFUSE,
        ):
            assert result.decision.reason is not ReasonCode.ROOM_IMPLAUSIBLE
            term = result.decision.term("stove")
            assert term is not None
            assert term.value <= 0.0


@settings(max_examples=150, deadline=None)
@given(controller=st.sampled_from(CONTROLLERS), sequence=steady())
def test_changes_respect_dwell_and_deadband(
    controller: OvenbirdController, sequence: list[Tick]
) -> None:
    assert_dwell_and_deadband(controller, sequence)


def test_dwell_after_a_ramp_that_releases_at_once() -> None:
    data = json.loads((FIXTURES / "dwell_ramp_release.json").read_text())
    fields = {f.name for f in dataclass_fields(PlantView)}
    sequence = [
        Tick(
            60.0,
            PlantView(**{k: v for k, v in plant.items() if k in fields and k != "stale"}),
            Mode.AUTO,
            None,
            None,
        )
        for plant in data["plants"]
    ]
    assert_dwell_and_deadband(CONTROLLERS[data["controller"]], sequence)


def assert_dwell_and_deadband(controller: OvenbirdController, sequence: list[Tick]) -> None:
    """Assert that every soft setpoint change respects the deadband and the dwell."""
    stages = controller.config.stages
    shortest_dwell = min(stages.dwell_s, stages.ramp_dwell_s)
    for before, inputs, result in drive(controller, sequence):
        decision = result.decision
        previous = before.setpoint
        if previous is None or decision.setpoint is None or decision.setpoint == previous:
            continue
        if decision.binding in HARD_BINDINGS:
            continue
        ramp_onset = before.ramp_cap is None and result.state.ramp_phase is not RampPhase.IDLE
        assert decision.pre_round is not None
        assert abs(decision.pre_round - previous) >= stages.deadband_k - 1e-9
        if not ramp_onset and before.last_change_at is not None:
            assert inputs.now.monotonic - before.last_change_at >= shortest_dwell
            ramping = (
                before.ramp_phase is not RampPhase.IDLE
                or result.state.ramp_phase is not RampPhase.IDLE
            )
            if not ramping:
                assert inputs.now.monotonic - before.last_change_at >= stages.dwell_s


MODEL_OFFSETS = st.sampled_from([None, -2.0, -1.0, -0.5, -0.2, 0.3, 0.5, 2.0])
model_ticks = st.builds(
    lambda tick, offset: replace(tick, plan_offset=offset, plan_source=PlanSource.MODEL),
    ticks,
    MODEL_OFFSETS,
)


@st.composite
def steady_with_model_plan(draw: st.DrawFn) -> list[Tick]:
    """A steady plant with a model plan that comes, goes and jumps to its bounds."""
    sequence = draw(steady())
    offsets = draw(st.lists(MODEL_OFFSETS, min_size=len(sequence), max_size=len(sequence)))
    return [
        replace(tick, plan_offset=offset, plan_source=PlanSource.MODEL)
        for tick, offset in zip(sequence, offsets, strict=True)
    ]


@settings(max_examples=150, deadline=None)
@given(
    controller=st.sampled_from(CONTROLLERS), sequence=st.lists(model_ticks, min_size=1, max_size=40)
)
def test_a_model_plan_keeps_the_safety_envelope_and_its_bounds(
    controller: OvenbirdController, sequence: list[Tick]
) -> None:
    cfg = controller.config
    safety = cfg.safety
    for _, inputs, result in drive(controller, sequence):
        decision = result.decision
        if decision.ladder in (LadderLevel.HOLD, LadderLevel.REFUSE):
            continue
        outside = inputs.snapshot.fresh_value(HeishaSignal.OUTSIDE_TEMP)
        assert isinstance(outside, float)
        bounds = safety.bounds(outside)
        assert decision.setpoint is not None
        assert bounds.low_int <= decision.setpoint <= bounds.high_int
        assert decision.pre_round is not None
        assert bounds.low - 1e-9 <= decision.pre_round <= bounds.high + 1e-9
        plan = decision.term("plan")
        assert plan is not None
        assert plan.value == 0.0
        target = decision.controller_state["room_target_c"]
        if isinstance(target, float):
            low = cfg.comfort_room_c - cfg.model_plan.max_setback_k
            high = cfg.comfort_room_c + cfg.model_plan.max_preheat_k
            assert low - 1e-9 <= target <= high + 1e-9
        if decision.ladder is LadderLevel.MODEL_PLAN:
            assert inputs.room is not None
            assert decision.controller_state["model_plan_ignored"] is None
            assert not result.state.stove_active


@settings(max_examples=150, deadline=None)
@given(controller=st.sampled_from(CONTROLLERS), sequence=steady_with_model_plan())
def test_a_model_plan_coming_and_going_respects_dwell_and_deadband(
    controller: OvenbirdController, sequence: list[Tick]
) -> None:
    assert_dwell_and_deadband(controller, sequence)


@settings(max_examples=100, deadline=None)
@given(controller=st.sampled_from(CONTROLLERS), sequence=st.lists(ticks, min_size=1, max_size=30))
def test_step_is_a_pure_function(controller: OvenbirdController, sequence: list[Tick]) -> None:
    for before, inputs, result in drive(controller, sequence):
        again = controller.step(before, inputs)
        assert again.state == result.state
        assert again.intents == result.intents
        assert again.decision.to_json_dict() == result.decision.to_json_dict()


@settings(max_examples=100, deadline=None)
@given(controller=st.sampled_from(CONTROLLERS), sequence=st.lists(ticks, min_size=1, max_size=30))
def test_decision_json_round_trip_is_stable(
    controller: OvenbirdController, sequence: list[Tick]
) -> None:
    for _, _, result in drive(controller, sequence):
        data = result.decision.to_json_dict()
        text = json.dumps(data, allow_nan=False, sort_keys=True)
        restored = DecisionRecord.from_json_dict(json.loads(text))
        assert restored == result.decision
        assert json.dumps(restored.to_json_dict(), allow_nan=False, sort_keys=True) == text


@settings(max_examples=100, deadline=None)
@given(sequence=steady())
def test_no_intent_ever_switches_the_pump_off(sequence: list[Tick]) -> None:
    for _, _, result in drive(CONTROLLERS[2], sequence):
        kinds = {intent.kind for intent in result.intents}
        assert kinds <= set(IntentKind)
        setpoint = result.intent(IntentKind.WATER_SETPOINT)
        assert setpoint is None or setpoint.value >= 20

from __future__ import annotations

from dataclasses import replace
from datetime import time

import pytest

from ovenbird_core.catalogue import HeishaSignal
from ovenbird_core.control import (
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
    QuietModeConfig,
    QuietWindow,
    RampPhase,
    ReasonCode,
    StepResult,
)
from ovenbird_core.control.synthetic import ROOM_SIGNAL, PlantView, synthetic_inputs
from ovenbird_core.instant import Instant

T0 = 1_794_528_000.0
MIXED = OvenbirdConfig.preset("mixed")
CTRL = OvenbirdController(MIXED)
KP = MIXED.feedback.kp
IDLE = PlantView()
RUNNING = PlantView(compressor_hz=35, outlet=33.0)


def at(seconds: float) -> Instant:
    return Instant.from_unix(T0 + seconds)


def tick(
    state: OvenbirdState,
    t: float,
    plant: PlantView = IDLE,
    controller: OvenbirdController = CTRL,
    **kwargs: object,
) -> StepResult[OvenbirdState]:
    return controller.step(state, synthetic_inputs(at(t), plant, **kwargs))  # type: ignore[arg-type]


def run(
    plants: list[tuple[float, PlantView]],
    controller: OvenbirdController = CTRL,
    state: OvenbirdState | None = None,
    **kwargs: object,
) -> list[StepResult[OvenbirdState]]:
    current = state or controller.initial_state()
    results = []
    for t, plant in plants:
        result = tick(current, t, plant, controller, **kwargs)
        results.append(result)
        current = result.state
    return results


def every_minute(
    plant: PlantView, minutes: int, start: float = 0.0
) -> list[tuple[float, PlantView]]:
    return [(start + 60.0 * i, plant) for i in range(minutes)]


class TestCurveAndFeedback:
    def test_curve_only_without_room_sensor(self) -> None:
        result = tick(CTRL.initial_state(), 0, room_signal=None)
        decision = result.decision
        assert decision.setpoint == 31
        assert decision.ladder is LadderLevel.CURVE_ONLY
        assert decision.reason is ReasonCode.CURVE
        assert decision.term("curve") is not None
        assert decision.term("room_feedback").value == 0.0  # type: ignore[union-attr]
        assert result.intent(IntentKind.WATER_SETPOINT).value == 31  # type: ignore[union-attr]

    def test_proportional_term(self) -> None:
        decision = tick(CTRL.initial_state(), 0, replace(IDLE, room=20.0)).decision
        assert decision.ladder is LadderLevel.SCHEDULE_CURVE_FEEDBACK
        assert decision.term("room_feedback").value == pytest.approx(KP)  # type: ignore[union-attr]
        assert decision.pre_round == pytest.approx(31.0 + KP)
        assert decision.setpoint == 33
        assert decision.reason is ReasonCode.ROOM_FEEDBACK
        assert "below target" in decision.note

    def test_feedback_output_is_clamped(self) -> None:
        decision = tick(CTRL.initial_state(), 0, replace(IDLE, room=17.0)).decision
        term = decision.term("room_feedback")
        assert term is not None
        assert term.raw == pytest.approx(4 * KP)
        assert term.value == pytest.approx(3.0)
        assert decision.binding == "room_feedback_limit"

    def test_integrator_accumulates_with_exact_gain(self) -> None:
        results = run(every_minute(replace(IDLE, room=20.5), 61))
        expected = MIXED.feedback.ki_per_s * 0.5 * 60.0 * 60
        assert results[-1].state.integral_k == pytest.approx(expected)

    def test_integration_step_is_capped_after_a_gap(self) -> None:
        results = run([(0, replace(IDLE, room=20.0)), (7200, replace(IDLE, room=20.0))])
        cap = MIXED.feedback.max_integration_step_s
        assert results[-1].state.integral_k == pytest.approx(MIXED.feedback.ki_per_s * cap)

    def test_integrator_is_clamped(self) -> None:
        state = replace(CTRL.initial_state(), integral_k=2.999)
        results = run(every_minute(replace(IDLE, room=20.8), 200), state=state)
        assert max(r.state.integral_k for r in results) <= MIXED.feedback.integral_limit_k

    def test_anti_windup_when_feedback_saturated(self) -> None:
        results = run(every_minute(replace(IDLE, room=18.0), 30))
        assert all(r.state.integral_k == 0.0 for r in results)
        assert "anti_windup" in str(results[-1].decision.controller_state["frozen_by"])

    def test_anti_windup_when_safety_maximum_binds(self) -> None:
        cold = replace(IDLE, outside=-20.0, room=20.0)
        results = run(every_minute(cold, 30))
        assert all(r.decision.setpoint == 40 for r in results)
        assert all(r.state.integral_k == 0.0 for r in results)
        assert results[-1].decision.binding == "safety_max"
        assert results[-1].decision.reason is ReasonCode.SAFETY_CLAMP

    def test_integrator_unwinds_when_error_reverses_under_saturation(self) -> None:
        state = replace(CTRL.initial_state(), integral_k=2.0)
        cold = replace(IDLE, outside=-20.0, room=22.0)
        results = run(every_minute(cold, 10), state=state)
        assert results[-1].state.integral_k < 2.0


class TestFreezes:
    @pytest.mark.parametrize(
        ("plant", "frozen"),
        [
            (replace(RUNNING, room=20.0, defrost=1), "defrost"),
            (replace(RUNNING, room=20.0, valve=1), "dhw"),
            (replace(IDLE, room=20.0, stale=frozenset({ROOM_SIGNAL})), "room_stale"),
        ],
    )
    def test_integrator_frozen(self, plant: PlantView, frozen: str) -> None:
        state = replace(CTRL.initial_state(), integral_k=0.7)
        results = run(every_minute(plant, 10), state=state)
        assert all(r.state.integral_k == 0.7 for r in results)
        assert frozen in str(results[-1].decision.controller_state["frozen_by"])

    def test_integrator_frozen_during_setpoint_override(self) -> None:
        state = replace(CTRL.initial_state(), integral_k=0.7)
        override = Override(OverrideKind.SETPOINT, 28)
        results = run(every_minute(replace(IDLE, room=20.0), 10), state=state, override=override)
        assert all(r.state.integral_k == 0.7 for r in results)

    @pytest.mark.parametrize(
        ("plant", "mode", "reason"),
        [
            (replace(IDLE, room=20.0, alive=False), Mode.AUTO, ReasonCode.HEISHAMON_DEAD),
            (replace(IDLE, room=20.0, heating_mode=0), Mode.AUTO, ReasonCode.MODE_MISMATCH),
            (replace(IDLE, room=20.0, operating_mode=1), Mode.AUTO, ReasonCode.MODE_MISMATCH),
            (
                replace(IDLE, room=20.0, stale=frozenset({HeishaSignal.HEATING_MODE})),
                Mode.AUTO,
                ReasonCode.MODE_UNKNOWN,
            ),
            (replace(IDLE, room=20.0, operating_mode=None), Mode.AUTO, ReasonCode.MODE_UNKNOWN),
            (replace(IDLE, room=20.0), Mode.OFF, ReasonCode.MODE_OFF),
        ],
    )
    def test_refusal_freezes_and_sends_nothing(
        self, plant: PlantView, mode: Mode, reason: ReasonCode
    ) -> None:
        state = replace(CTRL.initial_state(), integral_k=0.7, setpoint=31)
        results = run(every_minute(plant, 5), state=state, mode=mode)
        for result in results:
            assert result.intents == ()
            assert result.decision.ladder is LadderLevel.REFUSE
            assert result.decision.reason is reason
            assert result.decision.setpoint is None
            assert result.state.integral_k == 0.7


class TestHoldAndModes:
    def test_hold_repeats_last_intents_when_outside_is_stale(self) -> None:
        stale = replace(IDLE, stale=frozenset({HeishaSignal.OUTSIDE_TEMP}))
        first, held = run([(0, IDLE), (60, stale)])
        assert held.decision.ladder is LadderLevel.HOLD
        assert held.decision.reason is ReasonCode.INPUTS_MISSING
        assert held.decision.setpoint == first.decision.setpoint
        assert [i.value for i in held.intents] == [i.value for i in first.intents]
        assert "Outside_Temp" in held.decision.note

    def test_hold_without_history_sends_nothing(self) -> None:
        result = tick(CTRL.initial_state(), 0, replace(IDLE, outlet=None))
        assert result.decision.ladder is LadderLevel.HOLD
        assert result.intents == ()

    def test_manual_setpoint_applies_at_once_and_bypasses_dwell(self) -> None:
        override = Override(OverrideKind.SETPOINT, 28, actor="alex")
        first = tick(CTRL.initial_state(), 0)
        result = tick(first.state, 60, mode=Mode.MANUAL, override=override)
        assert result.decision.setpoint == 28
        assert result.decision.binding == "override"
        assert result.decision.reason is ReasonCode.OVERRIDE
        assert result.decision.actor == "alex"

    def test_manual_setpoint_is_still_safety_clamped(self) -> None:
        override = Override(OverrideKind.SETPOINT, 15)
        result = tick(CTRL.initial_state(), 0, mode=Mode.MANUAL, override=override)
        assert result.decision.setpoint == 25
        assert result.decision.binding == "envelope_min"

    def test_manual_without_override_holds(self) -> None:
        first = tick(CTRL.initial_state(), 0)
        result = tick(first.state, 60, mode=Mode.MANUAL)
        assert result.decision.ladder is LadderLevel.HOLD
        assert result.decision.reason is ReasonCode.OVERRIDE_MISSING
        assert result.decision.setpoint == 31

    def test_a_held_setpoint_is_clamped_to_the_bounds_at_the_current_outside(self) -> None:
        state = replace(CTRL.initial_state(), setpoint=40)
        warm = replace(IDLE, outside=20.0)
        result = tick(state, 60, warm, mode=Mode.MANUAL)
        bounds = MIXED.safety.bounds(20.0)
        assert result.decision.ladder is LadderLevel.HOLD
        assert result.decision.reason is ReasonCode.OVERRIDE_MISSING
        assert result.decision.setpoint == bounds.high_int < 40
        assert result.decision.binding == bounds.high_source.value
        assert [i.value for i in result.intents if i.kind is IntentKind.WATER_SETPOINT] == [
            bounds.high_int
        ]
        assert result.state.setpoint == bounds.high_int
        assert result.state.last_change_at == at(60).monotonic
        assert f"clamps the held 40 → {bounds.high_int} °C" in result.decision.note
        assert result.decision.controller_state["safety_high_c"] == bounds.high

    def test_a_held_setpoint_inside_the_bounds_is_repeated_unchanged(self) -> None:
        state = replace(CTRL.initial_state(), setpoint=31, last_change_at=at(0).monotonic)
        result = tick(state, 60, mode=Mode.MANUAL)
        assert result.decision.setpoint == 31
        assert result.decision.binding is None
        assert result.state.last_change_at == at(0).monotonic

    def test_expired_override_is_ignored(self) -> None:
        override = Override(OverrideKind.SETPOINT, 28, until=at(30))
        result = tick(CTRL.initial_state(), 60, override=override)
        assert result.decision.setpoint == 31

    def test_boost_adds_to_the_setpoint(self) -> None:
        override = Override(OverrideKind.BOOST, 2.0)
        result = tick(CTRL.initial_state(), 0, override=override)
        assert result.decision.setpoint == 33
        assert result.decision.term("boost") is not None
        assert result.decision.reason is ReasonCode.OVERRIDE

    def test_shadow_decides_like_auto(self) -> None:
        plant = replace(IDLE, room=20.3)
        auto = tick(CTRL.initial_state(), 0, plant)
        shadow = tick(CTRL.initial_state(), 0, plant, mode=Mode.SHADOW)
        assert shadow.intents == auto.intents
        assert shadow.state == auto.state


class TestPlan:
    def plan(self, offset: float, source: PlanSource = PlanSource.RULE) -> PlanSlice:
        reason = ReasonCode.PLAN_PREHEAT if offset > 0 else ReasonCode.PLAN_SETBACK
        return PlanSlice(offset, reason, at(0), at(3600), source)

    def test_plan_shifts_the_room_target_with_a_room_sensor(self) -> None:
        decision = tick(CTRL.initial_state(), 0, plan=self.plan(1.0)).decision
        assert decision.ladder is LadderLevel.RULE_PLAN
        assert decision.reason is ReasonCode.PLAN_PREHEAT
        assert decision.term("plan").value == 0.0  # type: ignore[union-attr]
        assert decision.term("room_feedback").value == pytest.approx(KP)  # type: ignore[union-attr]
        assert decision.controller_state["room_target_c"] == pytest.approx(22.0)

    def test_plan_maps_through_the_curve_slope_without_room_sensor(self) -> None:
        plan = self.plan(-1.0, PlanSource.OPTIMISER)
        decision = tick(CTRL.initial_state(), 0, plan=plan, room_signal=None).decision
        assert decision.ladder is LadderLevel.OPTIMISER_PLAN
        assert decision.reason is ReasonCode.PLAN_SETBACK
        assert decision.term("plan").value == pytest.approx(-1.6)  # type: ignore[union-attr]
        assert decision.pre_round == pytest.approx(29.4)

    def test_plan_water_term_is_clamped(self) -> None:
        decision = tick(CTRL.initial_state(), 0, plan=self.plan(5.0), room_signal=None).decision
        term = decision.term("plan")
        assert term is not None
        assert term.raw == pytest.approx(8.0)
        assert term.value == pytest.approx(MIXED.plan_max_water_k)

    def test_inactive_plan_is_ignored(self) -> None:
        decision = tick(CTRL.initial_state(), 4000, plan=self.plan(1.0)).decision
        assert decision.ladder is LadderLevel.SCHEDULE_CURVE_FEEDBACK
        assert decision.setpoint == 31


class TestStages:
    def test_dwell_holds_a_change(self) -> None:
        cold = replace(IDLE, room=20.0)
        results = run([(0, IDLE), (60, cold), (MIXED.stages.dwell_s, cold)])
        assert results[0].decision.setpoint == 31
        assert results[1].decision.setpoint == 31
        assert results[1].decision.binding == "dwell"
        assert results[1].decision.reason is ReasonCode.DWELL_HOLD
        assert results[2].decision.setpoint == 33

    def test_deadband_and_rounding_hysteresis(self) -> None:
        first = tick(CTRL.initial_state(), 0)
        later = 10_000.0
        rounding = tick(first.state, later, replace(IDLE, room=21.0 - 0.6 / KP))
        assert rounding.decision.setpoint == 31
        assert rounding.decision.binding == "rounding"
        deadband = tick(first.state, later, replace(IDLE, room=21.0 - 0.9 / KP))
        assert deadband.decision.setpoint == 31
        assert deadband.decision.binding == "deadband"
        assert deadband.decision.reason is ReasonCode.DEADBAND_HOLD
        moved = tick(first.state, later, replace(IDLE, room=21.0 - 1.0 / KP))
        assert moved.decision.setpoint == 32

    def test_reference_starts_from_the_reported_target(self) -> None:
        plant = replace(IDLE, water_target=32, room=21.0 - 0.6 / KP)
        result = tick(CTRL.initial_state(), 0, plant)
        assert result.decision.pre_round == pytest.approx(31.6)
        assert result.decision.setpoint == 32
        assert result.state.last_change_at is None

    def test_no_decrease_during_defrost(self) -> None:
        warm = replace(RUNNING, room=22.0)
        first = tick(CTRL.initial_state(), 0, replace(RUNNING, room=20.0))
        assert first.decision.setpoint == 33
        held = tick(first.state, 10_000, replace(warm, defrost=1))
        assert held.decision.setpoint == 33
        assert held.decision.binding == "defrost_hold"
        assert held.decision.reason is ReasonCode.DEFROST_FREEZE
        assert "defrost in progress: integrator frozen, no decrease" in held.decision.note
        assert "no decrease during defrost" in held.decision.note
        after = tick(held.state, 10_060, warm)
        assert after.decision.setpoint == 29

    def test_flip_distance_in_room_kelvin(self) -> None:
        decision = tick(CTRL.initial_state(), 0).decision
        assert decision.flip_input == ROOM_SIGNAL
        assert decision.flip_distance == pytest.approx(MIXED.stages.deadband_k / KP)

    def test_flip_distance_in_outside_kelvin_on_the_curve(self) -> None:
        decision = tick(CTRL.initial_state(), 0, room_signal=None).decision
        assert decision.flip_input == HeishaSignal.OUTSIDE_TEMP
        assert decision.flip_distance == pytest.approx(1.0 / 0.6)


def start_sequence(
    outlets: list[float], controller: OvenbirdController = CTRL, defrost: int = 0
) -> list[StepResult[OvenbirdState]]:
    plants = [(0.0, replace(IDLE, outlet=25.0, room=None))]
    for i, outlet in enumerate(outlets, start=1):
        running = replace(IDLE, compressor_hz=30, outlet=outlet, room=None, defrost=defrost)
        plants.append((60.0 * i, running))
    return run(plants, controller)


class TestStartRamp:
    def test_start_caps_just_under_outlet_but_not_below_curve_minus_k(self) -> None:
        results = start_sequence([25.0])
        start = results[-1]
        assert start.state.ramp_phase is RampPhase.HOLD
        assert start.decision.term("start_ramp").value == pytest.approx(26.0 - 31.0)  # type: ignore[union-attr]
        assert start.decision.setpoint == 26
        assert start.decision.binding == "start_ramp"
        assert start.decision.reason is ReasonCode.START_RAMP

    def test_cap_tracks_the_outlet(self) -> None:
        results = start_sequence([25.0, 26.0, 27.0, 28.0, 29.0])
        assert results[-1].state.ramp_cap == pytest.approx(28.0)
        assert results[-1].decision.setpoint == 28

    def test_releases_after_hold_at_the_configured_rate(self) -> None:
        minutes = int(MIXED.ramp.hold_s / 60) + 31
        results = start_sequence([25.0] * minutes)
        hold_end = int(MIXED.ramp.hold_s / 60)
        assert results[hold_end].state.ramp_phase is RampPhase.HOLD
        assert results[hold_end + 2].state.ramp_phase is RampPhase.RELEASE
        released = results[-1].state.ramp_cap
        assert released is not None
        assert released == pytest.approx(26.0 + MIXED.ramp.release_k_per_h * 30 / 60, abs=0.1)

    def test_ends_when_the_outlet_reaches_the_target(self) -> None:
        results = start_sequence([25.0, 33.0])
        assert results[-1].state.ramp_phase is RampPhase.IDLE
        assert results[-1].decision.term("start_ramp").value == 0.0  # type: ignore[union-attr]

    def test_defrost_pauses_the_clock_and_never_ramps_down(self) -> None:
        results = start_sequence([27.0, 28.0])
        state = results[-1].state
        cap = state.ramp_cap
        elapsed = state.ramp_elapsed_s
        defrost = run(
            [
                (180.0 + 60 * i, replace(IDLE, compressor_hz=30, outlet=20.0, defrost=1, room=None))
                for i in range(5)
            ],
            state=state,
        )
        for result in defrost:
            assert result.state.ramp_cap == cap
            assert result.state.ramp_elapsed_s == elapsed
            assert result.decision.setpoint is not None
            assert result.decision.setpoint >= results[-1].decision.setpoint  # type: ignore[operator]

    def test_no_ramp_for_radiators(self) -> None:
        radiators = OvenbirdController(OvenbirdConfig.preset("radiators"))
        results = start_sequence([25.0], radiators)
        assert results[-1].state.ramp_phase is RampPhase.IDLE

    def test_no_ramp_when_the_start_is_a_defrost(self) -> None:
        results = start_sequence([25.0], defrost=1)
        assert results[-1].state.ramp_phase is RampPhase.IDLE

    def test_no_ramp_or_window_when_the_start_was_not_seen(self) -> None:
        result = tick(CTRL.initial_state(), 0, replace(RUNNING, outlet=36.0, room=None))
        assert result.state.ramp_phase is RampPhase.IDLE
        assert result.state.run_started_at is None
        assert result.decision.term("cycling_floor").value == 0.0  # type: ignore[union-attr]


class TestCyclingProtection:
    def test_floor_keeps_setpoint_off_the_stop_rule(self) -> None:
        results = start_sequence([25.0, 34.0, 35.0])
        decision = results[-1].decision
        assert decision.setpoint is not None
        assert 35.0 - decision.setpoint < MIXED.cycling.stop_delta_k
        assert decision.binding == "cycling_floor"
        assert decision.reason is ReasonCode.CYCLING_PROTECT

    def test_floor_raise_is_bounded(self) -> None:
        results = start_sequence([25.0, 40.0])
        decision = results[-1].decision
        assert decision.setpoint == 34

    def test_decrease_keeps_headroom(self) -> None:
        results = start_sequence([25.0, 35.5])
        assert results[-1].decision.setpoint == 34
        later = tick(
            results[-1].state, 1200.0, replace(IDLE, compressor_hz=30, outlet=34.5, room=None)
        )
        assert later.decision.pre_round == pytest.approx(33.0)
        assert later.decision.setpoint == 34
        assert later.decision.binding == "cycling_floor"
        assert "stop rule" in later.decision.note
        assert "cycling floor 33.00 °C limits the decrease" not in later.decision.note
        assert "limits the decrease" in later.decision.note
        assert "raises to" not in later.decision.note

    def test_floor_raise_is_narrated_as_a_raise(self) -> None:
        results = start_sequence([25.0, 34.0, 35.0])
        decision = results[-1].decision
        assert decision.binding == "cycling_floor"
        before = results[-2].decision.setpoint
        assert before is not None
        assert decision.setpoint is not None
        assert decision.setpoint > before
        assert f"cycling floor raises to {decision.setpoint} °C" in decision.note
        assert "limits the decrease" not in decision.note

    def test_no_floor_after_the_min_run_window(self) -> None:
        results = start_sequence([25.0])
        later = tick(
            results[-1].state,
            60 + MIXED.cycling.min_run_s + 60,
            replace(IDLE, compressor_hz=30, outlet=34.0, room=None),
        )
        assert later.decision.term("cycling_floor").value == 0.0  # type: ignore[union-attr]
        assert later.decision.setpoint == 31


class TestSafety:
    def test_boost_cannot_exceed_the_envelope(self) -> None:
        result = tick(CTRL.initial_state(), 0, override=Override(OverrideKind.BOOST, 20.0))
        assert result.decision.setpoint == 36
        assert result.decision.binding == "envelope_max"
        safety = result.decision.term("safety")
        assert safety is not None
        assert safety.raw == pytest.approx(51.0)
        assert safety.value == pytest.approx(36.0)

    def test_hard_maximum_in_the_cold(self) -> None:
        plant = replace(IDLE, outside=-25.0)
        result = tick(CTRL.initial_state(), 0, plant, override=Override(OverrideKind.BOOST, 20.0))
        assert result.decision.setpoint == 40

    def test_held_setpoint_is_clamped_when_the_envelope_moves(self) -> None:
        first = tick(CTRL.initial_state(), 0, replace(IDLE, outside=-10.0))
        assert first.decision.setpoint == 39
        warm = tick(first.state, 60, replace(IDLE, outside=20.0))
        assert warm.decision.setpoint is not None
        assert warm.decision.setpoint <= 30
        assert warm.decision.binding == "envelope_max"
        assert f"safety bound envelope_max clamps 39 → {warm.decision.setpoint} °C" in (
            warm.decision.note
        )


class TestOptionalIntents:
    def test_off_by_default(self) -> None:
        result = tick(CTRL.initial_state(), 0, RUNNING)
        assert [i.kind for i in result.intents] == [IntentKind.WATER_SETPOINT]

    def test_pump_duty(self) -> None:
        controller = OvenbirdController(replace(MIXED, pump_duty=PumpDutyConfig()))
        idle = replace(IDLE, max_pump_duty=102)
        results = run(
            [
                (0, idle),
                (60, replace(RUNNING, max_pump_duty=102)),
                (120, replace(RUNNING, max_pump_duty=200)),
                (180, idle),
                (420, idle),
                (480, idle),
            ],
            controller,
        )
        duties = [r.intent(IntentKind.MAX_PUMP_DUTY).value for r in results]  # type: ignore[union-attr]
        assert duties == [102, 159, 200, 200, 200, 102]
        assert results[1].intent(IntentKind.MAX_PUMP_DUTY).reason is ReasonCode.PUMP_DUTY_HEAT  # type: ignore[union-attr]
        assert results[-1].intent(IntentKind.MAX_PUMP_DUTY).reason is ReasonCode.PUMP_DUTY_IDLE  # type: ignore[union-attr]

    def test_no_pump_duty_intent_during_defrost(self) -> None:
        controller = OvenbirdController(replace(MIXED, pump_duty=PumpDutyConfig()))
        defrost = replace(RUNNING, defrost=1, max_pump_duty=159)
        results = run(
            [
                (0, replace(RUNNING, max_pump_duty=159)),
                (60, defrost),
                (120, replace(defrost, compressor_hz=0)),
                (1000, replace(defrost, compressor_hz=0)),
                (1060, replace(RUNNING, max_pump_duty=159)),
            ],
            controller,
        )
        assert results[0].intent(IntentKind.MAX_PUMP_DUTY).value == 159  # type: ignore[union-attr]
        for result in results[1:4]:
            assert result.intent(IntentKind.MAX_PUMP_DUTY) is None
            assert result.state.pump_duty == 159
            assert "defrost: the pump sets its own duty; no duty command" in result.decision.note
            assert "defrost in progress: integrator frozen, no decrease" in result.decision.note
        after = results[-1].intent(IntentKind.MAX_PUMP_DUTY)
        assert after is not None
        assert after.value == 159
        assert after.reason is ReasonCode.PUMP_DUTY_HEAT
        assert "no duty command" not in results[-1].decision.note

    def test_after_defrost_the_next_intent_is_the_normal_one(self) -> None:
        controller = OvenbirdController(replace(MIXED, pump_duty=PumpDutyConfig()))
        results = run(
            [
                (0, RUNNING),
                (60, replace(RUNNING, defrost=1)),
                (120, RUNNING),
                (180, IDLE),
                (600, IDLE),
            ],
            controller,
        )
        assert results[1].intent(IntentKind.MAX_PUMP_DUTY) is None
        assert results[1].state.pump_duty == 159
        assert results[2].intent(IntentKind.MAX_PUMP_DUTY).value == 159  # type: ignore[union-attr]
        assert results[3].intent(IntentKind.MAX_PUMP_DUTY).value == 159  # type: ignore[union-attr]
        idle = results[4].intent(IntentKind.MAX_PUMP_DUTY)
        assert idle is not None
        assert idle.value == 102
        assert idle.reason is ReasonCode.PUMP_DUTY_IDLE

    def test_hold_in_defrost_repeats_no_pump_duty(self) -> None:
        controller = OvenbirdController(replace(MIXED, pump_duty=PumpDutyConfig()))
        first = tick(controller.initial_state(), 0, RUNNING, controller)
        stale = replace(RUNNING, defrost=1, stale=frozenset({HeishaSignal.OUTSIDE_TEMP}))
        held = tick(first.state, 60, stale, controller)
        assert held.decision.ladder is LadderLevel.HOLD
        assert held.intent(IntentKind.WATER_SETPOINT) is not None
        assert held.intent(IntentKind.MAX_PUMP_DUTY) is None

    def test_dhw_keeps_the_heat_duty_after_the_compressor_stops(self) -> None:
        controller = OvenbirdController(replace(MIXED, pump_duty=PumpDutyConfig()))
        dhw = replace(IDLE, valve=1)
        results = run([(0, RUNNING), (60, dhw), (420, dhw), (1200, dhw)], controller)
        duties = [r.intent(IntentKind.MAX_PUMP_DUTY).value for r in results]  # type: ignore[union-attr]
        assert duties == [159, 159, 159, 159]
        assert "DHW run in progress: integrator frozen, no decrease" in results[-1].decision.note

    def test_quiet_schedule(self) -> None:
        quiet = QuietModeConfig(windows=(QuietWindow(time(0), time(23, 59), 2),))
        controller = OvenbirdController(replace(MIXED, quiet=quiet))
        result = tick(controller.initial_state(), 0, controller=controller)
        intent = result.intent(IntentKind.QUIET_MODE)
        assert intent is not None
        assert intent.value == 2
        assert intent.reason is ReasonCode.QUIET_SCHEDULE


class TestNotes:
    def test_no_negative_zero(self) -> None:
        decision = tick(CTRL.initial_state(), 0, replace(IDLE, room=21.02)).decision
        assert "PI adds -0.0 K" not in decision.note
        assert "PI adds +0.0 K" in decision.note

    def test_periodic_note_has_no_cooling_authority(self) -> None:
        decision = tick(CTRL.initial_state(), 0, replace(IDLE, room=20.5)).decision
        assert "authority" not in decision.note


class TestRecord:
    def test_terms_and_state_are_complete(self) -> None:
        decision = tick(CTRL.initial_state(), 0, replace(IDLE, room=20.4)).decision
        names = [term.name for term in decision.terms]
        assert names == ["curve", "room_feedback", "plan", "start_ramp", "cycling_floor", "safety"]
        assert decision.controller == "ovenbird"
        assert decision.pre_round is not None
        assert {"integral_k", "ramp_phase", "dwell_remaining_s", "frozen_by"} <= set(
            decision.controller_state
        )
        signals = {ref.signal for ref in decision.inputs_used}
        assert {
            HeishaSignal.OUTSIDE_TEMP,
            HeishaSignal.HEATING_MODE,
            ROOM_SIGNAL,
            "stats",
        } <= signals
        assert decision.note.endswith(".")
        assert decision.intents == tick(CTRL.initial_state(), 0, replace(IDLE, room=20.4)).intents

    def test_terms_add_up_to_the_safety_input(self) -> None:
        decision = start_sequence([25.0, 34.0])[-1].decision
        additive = sum(t.value for t in decision.terms if t.unit == "K")
        curve = decision.term("curve")
        safety = decision.term("safety")
        assert curve is not None
        assert safety is not None
        assert curve.value + additive == pytest.approx(safety.raw)

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

import pytest

from ovenbird_core.catalogue import HeishaSignal
from ovenbird_core.control import (
    ControlInputs,
    LadderLevel,
    OvenbirdConfig,
    OvenbirdController,
    OvenbirdState,
    ReasonCode,
    RoomInput,
    RoomProfile,
    RoomSensorProfile,
    StepResult,
    carry_state,
)
from ovenbird_core.control.integrator import integral_at_life, rollback
from ovenbird_core.control.notes import duration_text, liveness_label, room_status
from ovenbird_core.control.synthetic import ROOM_SIGNAL, PlantView, synthetic_inputs
from ovenbird_core.instant import Instant
from ovenbird_core.readings import SourceKind
from ovenbird_core.store import SignalView

T0 = 1_794_528_000.0
TARGET = 21.0
HOUR = 3600.0
ON_CHANGE = RoomSensorProfile(kind=RoomProfile.ON_CHANGE)
PERIODIC_02 = RoomSensorProfile(step_k=0.2)
CROSS = HeishaSignal.ROOM_THERMOSTAT_TEMP.value
HUMIDITY = "ha/sensor.living_room_humidity"
STEP_P = 2.0 * 0.2


def controller(profile: RoomSensorProfile) -> OvenbirdController:
    """Return a mixed-preset controller with the 21 °C target and the given room sensor profile."""
    return OvenbirdController(OvenbirdConfig.preset("mixed", comfort_room_c=TARGET, room=profile))


def room_value(
    value: float,
    profile: RoomSensorProfile,
    held_s: float | None = 0.0,
    age: float = 60.0,
    alive_by: str | None = None,
) -> RoomInput:
    """Return a room input of ``value`` °C, last reported ``age`` s ago, unchanged ``held_s`` s."""
    return RoomInput(
        value,
        age,
        True,
        ROOM_SIGNAL,
        quantum_k=profile.quantum_k,
        held_s=held_s,
        alive_by=alive_by,
        profile=profile.kind,
    )


def inputs(t: float, room: RoomInput, thermostat: float | None = None) -> ControlInputs:
    """Return control inputs at ``t`` s with ``room`` and an optional thermostat reading in °C."""
    base = synthetic_inputs(Instant.from_unix(T0 + t), PlantView(room=room.value))
    snapshot = base.snapshot
    if thermostat is not None:
        view = SignalView(
            signal=CROSS,
            value=thermostat,
            unit="°C",
            source=SourceKind.HEISHAMON,
            observed=snapshot.now,
            age=1.0,
            max_age=330.0,
            fresh=True,
            retained=False,
            source_timestamp=None,
        )
        signals = dict(snapshot.signals) | {CROSS: view}
        snapshot = replace(snapshot, signals=MappingProxyType(signals))
    return replace(base, snapshot=snapshot, room=room)


def defrosting(t: float, room: RoomInput) -> ControlInputs:
    """Return control inputs at ``t`` s with the room input and a running defrost."""
    base = synthetic_inputs(Instant.from_unix(T0 + t), PlantView(room=room.value, defrost=1))
    return replace(base, room=room)


def stale_room(profile: RoomSensorProfile, age: float = 25 * HOUR) -> RoomInput:
    """Return a room input that is no longer fresh, last reported ``age`` s ago."""
    return replace(room_value(TARGET, profile, age=age), fresh=False)


def hold(
    ctrl: OvenbirdController,
    value: float,
    hours: float,
    step_s: float = 300.0,
    state: OvenbirdState | None = None,
) -> list[StepResult[OvenbirdState]]:
    """Step ``ctrl`` with a constant room ``value`` for ``hours``, ``step_s`` apart."""
    profile = ctrl.config.room
    current = state or ctrl.initial_state()
    out = []
    for k in range(int(hours * HOUR / step_s) + 1):
        t = k * step_s
        result = ctrl.step(current, inputs(t, room_value(value, profile, held_s=t)))
        out.append(result)
        current = result.state
    return out


class TestDeadZone:
    """Dead zone of a stepped room sensor: integrate beyond one step only, bounded wind-up."""

    def test_symmetric_on_the_offset_grid(self) -> None:
        """Readings equally far above and below the target integrate to opposite values."""
        ctrl = controller(PERIODIC_02)
        for below, above in ((20.9, 21.1), (20.7, 21.3), (20.5, 21.5)):
            low = hold(ctrl, below, 2.0)[-1].state.integral_k
            high = hold(ctrl, above, 2.0)[-1].state.integral_k
            assert low == pytest.approx(-high, abs=1e-12)
        assert hold(ctrl, 20.9, 2.0)[-1].state.integral_k == 0.0
        assert hold(ctrl, 21.1, 2.0)[-1].state.integral_k == 0.0

    def test_integrates_only_beyond_one_step(self) -> None:
        """Integration counts only the error beyond one sensor step."""
        ctrl = controller(PERIODIC_02)
        results = hold(ctrl, 20.7, 1.0)
        ki = ctrl.config.feedback.ki_per_s
        assert results[-1].state.integral_k == pytest.approx(ki * 0.1 * HOUR)

    def test_proportional_part_sees_the_full_error(self) -> None:
        """The proportional part uses the full error, not the dead-zone error."""
        ctrl = controller(PERIODIC_02)
        term = hold(ctrl, 20.9, 0.0)[0].decision.term("room_feedback")
        assert term is not None
        assert term.raw == pytest.approx(ctrl.config.feedback.kp * 0.1)

    def test_bounded_windup_on_a_41_hour_hold(self) -> None:
        """A 41 h held reading winds up a small integral with the dead zone, far more without it."""
        warm = TARGET + 0.243
        dead_zone = hold(controller(PERIODIC_02), warm, 41.0)[-1].state.integral_k
        ki = OvenbirdConfig.preset("mixed").feedback.ki_per_s
        assert dead_zone == pytest.approx(-ki * 0.043 * 41.0 * HOUR, rel=1e-6)
        assert abs(dead_zone) < 0.6
        unguarded = OvenbirdController(OvenbirdConfig.preset("mixed", comfort_room_c=TARGET))
        state = unguarded.initial_state()
        for k in range(int(41.0 * HOUR / 300.0) + 1):
            room = RoomInput(warm, 60.0, True, ROOM_SIGNAL)
            state = unguarded.step(state, inputs(k * 300.0, room)).state
        assert state.integral_k < -2.0

    def test_on_change_hold_stops_integrating_once_authority_decays(self) -> None:
        """An on-change sensor held for 41 h stops integrating once its authority has decayed."""
        results = hold(controller(ON_CHANGE), TARGET + 0.243, 41.0)
        ki = OvenbirdConfig.preset("mixed").feedback.ki_per_s
        assert results[-1].state.integral_k == pytest.approx(-ki * 0.043 * 12.0 * HOUR, rel=0.02)
        assert "room_authority" in str(results[-1].decision.controller_state["frozen_by"])


class TestStuckWarm:
    """Authority of a held on-change reading decays with its age and scales cooling feedback."""

    def test_authority_profile(self) -> None:
        """Authority is 1 up to 12 h held, 0.5 at 18 h, 0 from 24 h; periodic sensors always 1."""
        assert ON_CHANGE.authority(0.0, 0.0) == 1.0
        assert ON_CHANGE.authority(12 * HOUR, 60.0) == 1.0
        assert ON_CHANGE.authority(18 * HOUR, 60.0) == pytest.approx(0.5)
        assert ON_CHANGE.authority(24 * HOUR, 60.0) == 0.0
        assert ON_CHANGE.authority(41 * HOUR, 60.0) == 0.0
        assert ON_CHANGE.authority(None, None) == 1.0
        assert RoomSensorProfile().authority(41 * HOUR, 41 * HOUR) == 1.0

    def test_authority_follows_the_proof_of_life_age(self) -> None:
        """With a proof of life the authority follows the shorter proof age ramp."""
        assert ON_CHANGE.authority(3 * HOUR, 3 * HOUR) == 1.0
        assert ON_CHANGE.authority(5.5 * HOUR, 5.5 * HOUR) == pytest.approx(0.5)
        assert ON_CHANGE.authority(8 * HOUR, 8 * HOUR) == 0.0
        assert ON_CHANGE.authority(20 * HOUR, 7 * HOUR) == pytest.approx(min(0.2, 1 / 3))

    def test_alive_ramp_validation(self) -> None:
        """An alive-decay end before its start is rejected."""
        with pytest.raises(ValueError, match="alive_decay_start_s"):
            RoomSensorProfile(alive_decay_start_s=5 * HOUR, alive_decay_end_s=4 * HOUR)

    def test_cooling_feedback_is_scaled(self) -> None:
        """Cooling feedback is scaled by the authority, the rest falls back to the held offset."""
        ctrl = controller(ON_CHANGE)
        room = room_value(TARGET + 1.0, ON_CHANGE, held_s=18 * HOUR)
        decision = ctrl.step(ctrl.initial_state(), inputs(0.0, room)).decision
        term = decision.term("room_feedback")
        assert term is not None
        assert term.raw == pytest.approx(-2.0)
        assert term.value == pytest.approx(-2.0 * 0.5 + 0.5 * STEP_P)
        assert decision.binding == "room_authority"
        assert decision.controller_state["room_authority"] == pytest.approx(0.5)

    def test_heating_feedback_is_not_scaled(self) -> None:
        """Heating feedback keeps full strength even at reduced authority."""
        ctrl = controller(ON_CHANGE)
        room = room_value(TARGET - 1.0, ON_CHANGE, held_s=20 * HOUR)
        term = ctrl.step(ctrl.initial_state(), inputs(0.0, room)).decision.term("room_feedback")
        assert term is not None
        assert term.value == pytest.approx(2.0)

    def test_silent_sensor_loses_its_grip_within_eight_hours(self) -> None:
        """A silent sensor reading warm loses its cooling effect within eight hours."""
        ctrl = controller(ON_CHANGE)
        state = ctrl.initial_state()
        terms = []
        for k in range(int(9 * HOUR / 300.0) + 1):
            t = k * 300.0
            room = room_value(TARGET + 1.5, ON_CHANGE, held_s=t, age=t)
            result = ctrl.step(state, inputs(t, room))
            state = result.state
            terms.append(result.decision.term("room_feedback"))
        assert terms[0] is not None
        assert terms[0].value == pytest.approx(-3.0)
        assert terms[-1] is not None
        assert terms[-1].value == pytest.approx(STEP_P)

    def test_dead_sensor_at_a_warm_reading_loses_its_grip(self) -> None:
        """A sensor held at a warm reading for 24 h ends with only the held-offset feedback."""
        ctrl = controller(ON_CHANGE)
        results = hold(ctrl, TARGET + 1.5, 24.0)
        start = results[0].decision.term("room_feedback")
        end = results[-1].decision.term("room_feedback")
        assert start is not None
        assert end is not None
        assert start.value == pytest.approx(-3.0)
        assert end.value == pytest.approx(STEP_P)


class TestCrosscheck:
    """Cross-check of the room sensor against the thermostat: offset, verdict and latch."""

    PROFILE = RoomSensorProfile(kind=RoomProfile.ON_CHANGE, crosscheck=CROSS)

    def run(self, steps: list[tuple[float, float, float]]) -> list[StepResult[OvenbirdState]]:
        """Step a controller through (time, room value, thermostat) ``steps``."""
        ctrl = controller(self.PROFILE)
        state = ctrl.initial_state()
        out = []
        held_from = 0.0
        last = None
        for t, value, thermostat in steps:
            if value != last:
                held_from, last = t, value
            room = room_value(value, self.PROFILE, held_s=t - held_from)
            result = ctrl.step(state, inputs(t, room, thermostat))
            out.append(result)
            state = result.state
        return out

    def test_implausible_after_two_hours_of_disagreement(self) -> None:
        """A learned offset is applied; two hours of disagreement make the room implausible."""
        learn = [(k * 300.0, 21.1 if k % 2 else 20.9, 22.2) for k in range(24)]
        start = learn[-1][0] + 300.0
        stuck = [(start + k * 300.0, 20.9, 20.2) for k in range(30)]
        results = self.run(learn + stuck)
        learned = results[len(learn) - 1].state.crosscheck_offset_k
        assert learned is not None
        assert 1.1 < learned < 1.3
        first = results[len(learn)].decision
        assert first.ladder is LadderLevel.SCHEDULE_CURVE_FEEDBACK
        late = results[-1].decision
        assert late.ladder is LadderLevel.CURVE_ONLY
        assert late.reason is ReasonCode.ROOM_IMPLAUSIBLE
        assert "room_implausible" in str(late.controller_state["frozen_by"])
        assert late.controller_state["room_plausible"] is False
        before = results[len(learn) + 22].decision
        assert before.ladder is LadderLevel.SCHEDULE_CURVE_FEEDBACK

    def test_latched_until_the_room_value_changes(self) -> None:
        """An implausible verdict stays latched until the room value changes and agrees again."""
        learn = [(k * 300.0, 20.9, 22.2) for k in range(4)]
        start = learn[-1][0] + 300.0
        stuck = [(start + k * 300.0, 20.9, 19.2) for k in range(30)]
        agree = [(stuck[-1][0] + 300.0 * (k + 1), 20.9, 22.2) for k in range(3)]
        moved = [(agree[-1][0] + 300.0, 21.1, 22.2)]
        results = self.run(learn + stuck + agree + moved)
        assert results[len(learn) + len(stuck) - 1].decision.reason is ReasonCode.ROOM_IMPLAUSIBLE
        assert results[len(learn) + len(stuck) - 1].state.crosscheck_latched == 20.9
        for result in results[-4:-1]:
            assert result.decision.reason is ReasonCode.ROOM_IMPLAUSIBLE
            assert result.decision.controller_state["room_plausible"] is False
        assert results[-1].decision.ladder is LadderLevel.SCHEDULE_CURVE_FEEDBACK
        assert results[-1].decision.controller_state["room_plausible"] is True
        assert results[-1].state.crosscheck_latched is None

    def test_a_sensor_that_keeps_reporting_far_off_stays_latched(self) -> None:
        """A sensor that keeps reporting far off the thermostat stays latched."""
        learn = [(k * 300.0, 20.9, 22.2) for k in range(4)]
        start = learn[-1][0] + 300.0
        high = [(start + k * 300.0, 24.7 + 0.1 * (k % 3), 22.2) for k in range(60)]
        results = self.run(learn + high)
        latched = [r for r in results[len(learn) :] if r.state.crosscheck_latched is not None]
        assert latched
        first = results.index(latched[0])
        assert all(r.state.crosscheck_latched is not None for r in results[first:])
        assert all(r.decision.reason is ReasonCode.ROOM_IMPLAUSIBLE for r in results[first:])

    def test_an_integer_flip_does_not_restart_the_disagreement(self) -> None:
        """A thermostat that flips by one integer step does not restart the disagreement timer."""
        learn = [(k * 300.0, 20.9, 22.2) for k in range(4)]
        start = learn[-1][0] + 300.0
        flips = [(start + k * 300.0, 20.9, 20.2 if k % 2 else 21.2) for k in range(30)]
        results = self.run(learn + flips)
        assert results[len(learn)].decision.controller_state["room_plausible"] is True
        assert results[-1].decision.reason is ReasonCode.ROOM_IMPLAUSIBLE
        assert results[-1].state.crosscheck_offset_k == pytest.approx(1.3)

    def test_integer_flip_back_does_not_end_the_verdict(self) -> None:
        """A flip back of the thermostat does not end an implausible verdict."""
        learn = [(k * 300.0, 20.9, 22.2) for k in range(4)]
        start = learn[-1][0] + 300.0
        flips = [(start + k * 300.0, 20.9, 20.2 if k < 26 or k % 2 else 21.2) for k in range(34)]
        results = self.run(learn + flips)
        late = [r.decision.reason for r in results[len(learn) + 26 :]]
        assert all(reason is ReasonCode.ROOM_IMPLAUSIBLE for reason in late)

    def test_offset_not_learned_from_a_long_held_value(self) -> None:
        """The offset is not learned while the room value is held for many hours."""
        ctrl = controller(self.PROFILE)
        state = replace(ctrl.initial_state(), crosscheck_offset_k=1.0)
        room = room_value(20.9, self.PROFILE, held_s=8 * HOUR)
        result = ctrl.step(state, inputs(0.0, room, 22.2))
        result = ctrl.step(result.state, inputs(300.0, room, 22.2))
        assert result.state.crosscheck_offset_k == 1.0


class TestRecordText:
    """Wording of the room status in the decision note and state."""

    def test_held_value_note(self) -> None:
        """The held-value note names value, duration, liveness and step, plus any authority."""
        room = room_value(22.1, ON_CHANGE, held_s=2 * HOUR + 600.0, age=240.0, alive_by=HUMIDITY)
        assert room_status(room, 1.0) == (
            "held value 22.1 °C (2 h 10 m), device alive (humidity 4 min ago), ±0.2 K"
        )
        assert room_status(room, 1.0, cooling=True).endswith(", cooling authority 100 %")
        assert room_status(room, 0.4).endswith(", cooling authority 40 %")

    def test_without_a_liveness_report_the_note_never_claims_life(self) -> None:
        """Without a liveness report the note names the last report age and never says alive."""
        room = room_value(22.1, ON_CHANGE, held_s=2 * HOUR, age=2 * HOUR)
        text = room_status(room, 1.0)
        assert text == "held value 22.1 °C (2 h 00 m), last report 2 h 00 m ago, ±0.2 K"
        assert "alive" not in text

    def test_decision_note_and_state(self) -> None:
        """The decision note and state carry profile, held seconds and liveness source."""
        ctrl = controller(ON_CHANGE)
        room = room_value(20.7, ON_CHANGE, held_s=600.0, age=30.0, alive_by=HUMIDITY)
        decision = ctrl.step(ctrl.initial_state(), inputs(0.0, room)).decision
        assert "held value 20.7 °C (10 min), device alive (humidity 30 s ago)" in decision.note
        assert decision.controller_state["room_profile"] == "on_change"
        assert decision.controller_state["room_held_s"] == 600.0
        assert decision.controller_state["room_alive_by"] == HUMIDITY

    def test_stale_note_names_the_silence(self) -> None:
        """A stale room names the silence in the feedback term and gives reason ROOM_STALE."""
        ctrl = controller(ON_CHANGE)
        room = replace(room_value(20.7, ON_CHANGE, age=25 * HOUR), fresh=False)
        decision = ctrl.step(ctrl.initial_state(), inputs(0.0, room)).decision
        term = decision.term("room_feedback")
        assert term is not None
        assert "25 h 00 m ago" in term.note
        assert decision.reason is ReasonCode.ROOM_STALE

    def test_helpers(self) -> None:
        """duration_text and liveness_label format durations and signal names."""
        assert duration_text(None) == "unknown"
        assert duration_text(45.0) == "45 s"
        assert duration_text(3599.0) == "59 min"
        assert liveness_label(HUMIDITY, ROOM_SIGNAL) == "humidity"
        assert liveness_label("mqtt/x/linkquality", "mqtt/x/temperature") == "linkquality"


class TestUntrustedFallback:
    """Fallback to the held offset when the room value is untrusted, stale or implausible."""

    def test_reduced_authority_blends_in_the_held_offset(self) -> None:
        """Reduced authority blends the clamped PI output with the held offset."""
        ctrl = controller(ON_CHANGE)
        state = replace(ctrl.initial_state(), integral_k=0.8)
        room = room_value(TARGET + 1.5, ON_CHANGE, held_s=5.5 * HOUR, age=5.5 * HOUR)
        decision = ctrl.step(state, inputs(0.0, room)).decision
        term = decision.term("room_feedback")
        assert term is not None
        u_lim = max(-3.0, 2.0 * -1.5 + 0.8)
        assert term.value == pytest.approx(u_lim * 0.5 + 0.5 * (0.8 + STEP_P))
        assert decision.binding == "room_authority"

    def test_zero_authority_keeps_the_held_offset_like_a_stale_value(self) -> None:
        """Zero authority gives the same held offset as a stale value."""
        ctrl = controller(ON_CHANGE)
        state = replace(ctrl.initial_state(), integral_k=0.8)
        held = room_value(TARGET + 1.5, ON_CHANGE, held_s=9 * HOUR, age=9 * HOUR)
        gone = ctrl.step(state, inputs(0.0, held)).decision.term("room_feedback")
        stale = replace(held, fresh=False, age=25 * HOUR)
        lost = ctrl.step(state, inputs(0.0, stale)).decision.term("room_feedback")
        assert gone is not None
        assert lost is not None
        assert gone.value == pytest.approx(0.8 + STEP_P)
        assert lost.value == pytest.approx(0.8 + STEP_P)

    def test_a_negative_integrator_is_not_blended_in(self) -> None:
        """A negative integrator is not carried into the fallback offset."""
        ctrl = controller(ON_CHANGE)
        state = replace(ctrl.initial_state(), integral_k=-0.5)
        room = room_value(TARGET + 1.5, ON_CHANGE, held_s=9 * HOUR, age=9 * HOUR)
        term = ctrl.step(state, inputs(0.0, room)).decision.term("room_feedback")
        assert term is not None
        assert term.value == pytest.approx(STEP_P)

    def test_the_held_offset_is_bounded_by_the_feedback_clamp(self) -> None:
        """The held offset never exceeds the feedback output limit."""
        ctrl = controller(ON_CHANGE)
        limit = ctrl.config.feedback.output_limit_k
        state = replace(ctrl.initial_state(), integral_k=limit - 0.1)
        stale = replace(room_value(TARGET, ON_CHANGE, age=25 * HOUR), fresh=False)
        term = ctrl.step(state, inputs(0.0, stale)).decision.term("room_feedback")
        assert term is not None
        assert term.value == pytest.approx(limit)

    def test_a_coarse_step_is_bounded(self) -> None:
        """The sensor step added to the held offset is capped by held_step_max_k."""
        ctrl = controller(RoomSensorProfile(kind=RoomProfile.ON_CHANGE, step_k=2.0))
        bound = ctrl.config.feedback.held_step_max_k
        for integral, held in ((-1.5, bound), (0.6, 0.6 + bound)):
            state = replace(ctrl.initial_state(), integral_k=integral)
            stale = stale_room(ctrl.config.room)
            term = ctrl.step(state, inputs(0.0, stale)).decision.term("room_feedback")
            assert term is not None
            assert term.value == pytest.approx(held)

    def test_the_step_bound_is_a_controller_setting(self) -> None:
        """A zero held_step_max_k removes the step from the held offset."""
        feedback = replace(OvenbirdConfig.preset("mixed").feedback, held_step_max_k=0.0)
        config = OvenbirdConfig.preset("mixed", comfort_room_c=TARGET, room=ON_CHANGE)
        ctrl = OvenbirdController(replace(config, feedback=feedback))
        state = replace(ctrl.initial_state(), integral_k=-0.3)
        term = ctrl.step(state, inputs(0.0, stale_room(ON_CHANGE))).decision.term("room_feedback")
        assert term is not None
        assert term.value == pytest.approx(0.0)

    def test_without_a_known_step_only_the_positive_integrator_is_held(self) -> None:
        """Without a known sensor step only the positive integrator is held."""
        ctrl = controller(PERIODIC_02)
        state = replace(ctrl.initial_state(), integral_k=0.6)
        stale = replace(room_value(TARGET, PERIODIC_02, age=2 * HOUR), fresh=False, quantum_k=0.0)
        term = ctrl.step(state, inputs(0.0, stale)).decision.term("room_feedback")
        assert term is not None
        assert term.value == pytest.approx(0.6)

    def test_a_value_stuck_high_never_winds_the_water_up(self) -> None:
        """A reading stuck high for 30 h never raises the integrator beyond the held offset."""
        ctrl = controller(ON_CHANGE)
        state = replace(ctrl.initial_state(), integral_k=0.5)
        results = hold(ctrl, TARGET + 3.7, 30.0, state=state)
        integrals = [r.state.integral_k for r in results]
        feedback = [r.decision.term("room_feedback") for r in results]
        assert max(integrals) <= 0.5 + 1e-9
        assert all(t is not None and t.value <= 0.5 + STEP_P + 1e-9 for t in feedback)

    def test_an_implausible_value_keeps_the_positive_integrator_fading(self) -> None:
        """An implausible value keeps the positive integrator as held offset and fades it."""
        profile = TestCrosscheck.PROFILE
        ctrl = controller(profile)
        state = replace(
            ctrl.initial_state(),
            integral_k=0.6,
            crosscheck_offset_k=1.0,
            crosscheck_latched=22.5,
        )
        room = room_value(22.5, profile, held_s=3 * HOUR)
        first = ctrl.step(state, inputs(0.0, room, 21.2))
        later = ctrl.step(first.state, inputs(12 * HOUR, room, 21.2))
        assert first.decision.reason is ReasonCode.ROOM_IMPLAUSIBLE
        assert first.state.room_lost_at is not None
        term = first.decision.term("room_feedback")
        assert term is not None
        assert term.value == pytest.approx(0.6 + STEP_P)
        assert "keeps the held offset +1.0 K" in term.note
        late = later.decision.term("room_feedback")
        assert late is not None
        assert late.value == pytest.approx((0.6 + STEP_P) / 2)
        assert "plus the held offset" in later.decision.note


class TestSilentRollback:
    """Rollback of cooling integrated since the last proof of life once the sensor is silent."""

    PROFILE = RoomSensorProfile(kind=RoomProfile.ON_CHANGE, liveness=(HUMIDITY,))

    def run(
        self, hours: float, value: float, state: OvenbirdState
    ) -> list[StepResult[OvenbirdState]]:
        """Hold ``value`` for ``hours`` without proof of life from ``state``."""
        ctrl = controller(self.PROFILE)
        out = []
        for k in range(int(hours * HOUR / 300.0) + 1):
            t = k * 300.0
            room = room_value(value, self.PROFILE, held_s=t, age=t)
            result = ctrl.step(state, inputs(t, room))
            out.append(result)
            state = result.state
        return out

    def test_cooling_since_the_last_proof_of_life_is_undone_once_silent(self) -> None:
        """Cooling integrated since the last proof of life is undone after three silent hours."""
        ctrl = controller(self.PROFILE)
        start = replace(ctrl.initial_state(), integral_k=0.9)
        results = self.run(4.0, TARGET + 0.7, start)
        lowest = min(r.state.integral_k for r in results)
        assert lowest < 0.9 - 0.1
        before, at_three = results[36], results[37]
        assert before.state.integral_k < 0.9 - 0.1
        assert at_three.state.integral_k == pytest.approx(0.9)
        assert "room_silent_rollback" in str(at_three.decision.controller_state["frozen_by"])
        assert results[-1].state.integral_k == pytest.approx(0.9)

    def test_heating_integration_is_kept(self) -> None:
        """Heating integrated while silent is kept."""
        ctrl = controller(self.PROFILE)
        start = replace(ctrl.initial_state(), integral_k=0.2)
        results = self.run(4.0, TARGET - 0.7, start)
        assert results[-1].state.integral_k > 0.2

    def test_a_proof_of_life_moves_the_mark(self) -> None:
        """A proof of life moves the integrator mark to the current integrator."""
        ctrl = controller(self.PROFILE)
        state = replace(ctrl.initial_state(), integral_k=0.9)
        for k in range(12):
            room = room_value(TARGET + 0.7, self.PROFILE, held_s=k * 300.0, age=30.0)
            state = ctrl.step(state, inputs(k * 300.0, room)).state
        assert state.integral_at_life_k is not None
        assert state.integral_at_life_k < 0.9
        assert state.integral_at_life_k == pytest.approx(state.integral_k, abs=0.02)

    def test_a_stuck_reading_flagged_implausible_keeps_no_cooling(self) -> None:
        """A stuck reading flagged implausible has its cooling rolled back; the offset fades."""
        profile = TestCrosscheck.PROFILE
        ctrl = controller(profile)
        state = replace(ctrl.initial_state(), integral_k=0.5, crosscheck_offset_k=1.0)
        results = []
        for k in range(int(3 * HOUR / 300.0)):
            t = k * 300.0
            room = room_value(TARGET + 1.5, profile, held_s=t, age=t + 60.0)
            result = ctrl.step(state, inputs(t, room, 21.2))
            results.append(result)
            state = result.state
        flagged = next(
            i for i, r in enumerate(results) if r.decision.reason is ReasonCode.ROOM_IMPLAUSIBLE
        )
        assert results[flagged - 1].state.integral_k < 0.5 - 0.2
        assert results[flagged].state.integral_k == pytest.approx(0.5)
        frozen = str(results[flagged].decision.controller_state["frozen_by"])
        assert "room_lost_rollback" in frozen
        assert results[-1].state.integral_k == pytest.approx(0.5)
        late = results[-1].decision.term("room_feedback")
        assert late is not None
        fade = 1.0 - (len(results) - 1 - flagged) * 300.0 / (24 * HOUR)
        assert late.value == pytest.approx((0.5 + STEP_P) * fade)

    def test_the_mark_is_kept_while_the_value_is_lost(self) -> None:
        """The mark is kept and restored while the room value is lost."""
        ctrl = controller(self.PROFILE)
        state = replace(ctrl.initial_state(), integral_k=0.2, integral_at_life_k=0.7)
        stale = replace(room_value(TARGET, self.PROFILE, age=25 * HOUR), fresh=False)
        result = ctrl.step(state, inputs(0.0, stale))
        assert result.state.integral_at_life_k == pytest.approx(0.7)
        assert result.state.integral_k == pytest.approx(0.7)
        assert "room_lost_rollback" in str(result.decision.controller_state["frozen_by"])

    def test_the_lost_rollback_waits_out_defrost_and_dhw(self) -> None:
        """The lost-value rollback waits until defrost and DHW runs have ended."""
        cfg = controller(self.PROFILE).config
        for defrost, dhw in ((True, False), (False, True)):
            kept, frozen = rollback(cfg, 0.2, 0.7, None, [], defrost=defrost, dhw=dhw, lost=True)
            assert kept == 0.2
            assert frozen == []
        restored, frozen = rollback(cfg, 0.2, 0.7, None, [], defrost=False, dhw=False, lost=True)
        assert restored == 0.7
        assert frozen == ["room_lost_rollback"]

    def test_a_trusted_value_drops_the_mark_only_when_not_lost(self) -> None:
        """A trusted value drops the mark unless the value is lost."""
        ctrl = controller(self.PROFILE)
        state = replace(ctrl.initial_state(), integral_k=0.2, integral_at_life_k=0.7)
        assert integral_at_life(ctrl.config, state, None, 60.0) is None
        assert integral_at_life(ctrl.config, state, None, 60.0, lost=True) == 0.7

    def test_the_lost_rollback_through_a_defrost_waits_for_its_end(self) -> None:
        """A rollback requested during a defrost happens on the first tick after it."""
        ctrl = controller(self.PROFILE)
        state = replace(ctrl.initial_state(), integral_k=0.2, integral_at_life_k=0.7)
        stale = stale_room(self.PROFILE)
        during = ctrl.step(state, defrosting(0.0, stale))
        assert during.state.integral_k == pytest.approx(0.2)
        assert during.state.integral_at_life_k == pytest.approx(0.7)
        after = ctrl.step(during.state, inputs(60.0, stale))
        assert after.state.integral_k == pytest.approx(0.7)
        assert "room_lost_rollback" in str(after.decision.controller_state["frozen_by"])

    def test_the_recovery_tick_moves_the_mark_without_a_rollback(self) -> None:
        """The first fresh report after a loss moves the mark without rolling back."""
        ctrl = controller(self.PROFILE)
        state = replace(ctrl.initial_state(), integral_k=0.7, integral_at_life_k=0.7)
        lost = ctrl.step(state, inputs(0.0, stale_room(self.PROFILE)))
        assert lost.state.room_lost_at is not None
        report = room_value(TARGET + 0.5, self.PROFILE, held_s=0.0, age=10.0)
        back = ctrl.step(lost.state, inputs(60.0, report))
        assert back.state.room_lost_at is None
        assert back.decision.ladder is LadderLevel.SCHEDULE_CURVE_FEEDBACK
        assert back.state.integral_at_life_k == pytest.approx(0.7)
        assert "rollback" not in str(back.decision.controller_state["frozen_by"])
        term = back.decision.term("room_feedback")
        assert term is not None
        assert term.value == pytest.approx(2.0 * -0.5 + 0.7)

    def test_fresh_and_stale_flapping_never_keeps_unconfirmed_cooling(self) -> None:
        """Alternating fresh and stale reports never keep unconfirmed cooling."""
        ctrl = controller(self.PROFILE)
        state = replace(ctrl.initial_state(), integral_k=0.7, integral_at_life_k=0.7)
        for k in range(1, 41):
            t = k * 300.0
            room = room_value(TARGET + 1.0, self.PROFILE, held_s=t, age=t)
            result = ctrl.step(state, inputs(t, room if k % 2 else replace(room, fresh=False)))
            state = result.state
            assert state.integral_at_life_k == pytest.approx(0.7)
            if k % 2 == 0:
                assert state.room_lost_at is not None
                assert state.integral_k == pytest.approx(0.7)
            else:
                assert state.room_lost_at is None
                assert state.integral_k <= 0.7

    def test_a_config_change_carries_the_mark_like_the_integrator(self) -> None:
        """Carrying state to a new config clamps or clears the mark like the integrator."""
        old = OvenbirdConfig.preset("mixed", comfort_room_c=TARGET, room=self.PROFILE)
        state = replace(OvenbirdState(), integral_k=0.2, integral_at_life_k=0.9)
        tight = replace(old, feedback=replace(old.feedback, integral_limit_k=0.5))
        clamped = carry_state(state, old, tight)
        assert clamped.integral_at_life_k == pytest.approx(0.5)
        lost = OvenbirdController(tight).step(clamped, inputs(0.0, stale_room(self.PROFILE)))
        assert lost.state.integral_k == pytest.approx(0.5)
        p_only = replace(old, feedback=replace(old.feedback, ti_s=0.0))
        cleared = carry_state(state, old, p_only)
        assert cleared.integral_k == 0.0
        assert cleared.integral_at_life_k is None
        after = OvenbirdController(p_only).step(cleared, inputs(0.0, stale_room(self.PROFILE)))
        assert after.state.integral_k == 0.0

    def test_the_rollback_never_exceeds_the_integrator_clamp(self) -> None:
        """A rollback target above the integral limit is clamped to the limit."""
        cfg = controller(self.PROFILE).config
        limit = cfg.feedback.integral_limit_k
        restored, _ = rollback(cfg, 0.2, limit + 1.0, None, [], defrost=False, dhw=False, lost=True)
        assert restored == pytest.approx(limit)

    def test_periodic_sensors_keep_no_mark(self) -> None:
        """A periodic sensor keeps no integrator mark."""
        ctrl = controller(PERIODIC_02)
        result = ctrl.step(ctrl.initial_state(), inputs(0.0, room_value(20.7, PERIODIC_02)))
        assert result.state.integral_at_life_k is None

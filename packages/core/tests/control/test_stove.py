"""Wood-stove mode: detection, back-off, held integrator, exits and the reference guard."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from types import MappingProxyType
from typing import Any

import pytest

from ovenbird_core.catalogue import HeishaSignal
from ovenbird_core.control import (
    ControlInputs,
    OvenbirdConfig,
    OvenbirdController,
    OvenbirdState,
    Override,
    OverrideKind,
    ReasonCode,
    RoomInput,
    RoomProfile,
    RoomSensorProfile,
    StepResult,
    StoveConfig,
    StoveExit,
    StoveSource,
    StoveTrigger,
    carry_state,
    state_from_flat,
)
from ovenbird_core.control.synthetic import ROOM_SIGNAL, PlantView, synthetic_inputs
from ovenbird_core.instant import Instant
from ovenbird_core.readings import SourceKind
from ovenbird_core.store import SignalView

T0 = 1_794_528_000.0
COMFORT = 21.0
ENTER = COMFORT + 1.5
EXIT = ENTER - 1.0
MINUTE = 60.0
HOUR = 3600.0
HALL = "ha/sensor.hall_temperature"
CROSS = HeishaSignal.ROOM_THERMOSTAT_TEMP.value
CURVE_AT_5 = 31.0
SAFETY_LOW_AT_5 = 25.0

type Room = float | RoomInput | None


def config(stove: StoveConfig | None = None, **overrides: object) -> OvenbirdConfig:
    return OvenbirdConfig.preset(
        "mixed",
        comfort_room_c=COMFORT,
        stove=StoveConfig() if stove is None else stove,
        **overrides,
    )


def _view(signal: str, value: float, now: Instant, fresh: bool = True) -> SignalView:
    return SignalView(
        signal=signal,
        value=value,
        unit="°C",
        source=SourceKind.HA,
        observed=now,
        age=10.0 if fresh else 7200.0,
        max_age=1800.0,
        fresh=fresh,
        retained=False,
        source_timestamp=None,
    )


def tick_inputs(
    t: float,
    room: Room,
    *,
    hall: float | None = None,
    hall_fresh: bool = True,
    thermostat: float | None = None,
    override: Override | None = None,
    outside: float = 5.0,
) -> ControlInputs:
    now = Instant.from_unix(T0 + t)
    value = room.value if isinstance(room, RoomInput) else room
    base = synthetic_inputs(
        now, PlantView(room=value, outside=outside), override=override, room_signal=ROOM_SIGNAL
    )
    signals = dict(base.snapshot.signals)
    if hall is not None:
        signals[HALL] = _view(HALL, hall, now, hall_fresh)
    if thermostat is not None:
        signals[CROSS] = _view(CROSS, thermostat, now)
    snapshot = replace(base.snapshot, signals=MappingProxyType(signals))
    chosen = room if isinstance(room, RoomInput) else base.room
    return replace(base, snapshot=snapshot, room=chosen)


class Run:
    """Step a controller through a room profile at one tick per minute."""

    def __init__(self, ctrl: OvenbirdController, state: OvenbirdState | None = None) -> None:
        self.ctrl = ctrl
        self.state = state or ctrl.initial_state()
        self.t = 0.0
        self.results: list[StepResult[OvenbirdState]] = []

    def step(self, room: Room, **kwargs: Any) -> StepResult[OvenbirdState]:
        result = self.ctrl.step(self.state, tick_inputs(self.t, room, **kwargs))
        self.state = result.state
        self.results.append(result)
        self.t += MINUTE
        return result

    def hold(
        self, room: Room | Callable[[float], Room], minutes: float, **kwargs: Any
    ) -> list[StepResult[OvenbirdState]]:
        out = []
        for _ in range(int(minutes)):
            value = room(self.t) if callable(room) else room
            out.append(self.step(value, **kwargs))
        return out


def warm(
    run: Run, start: float, end: float, minutes: int = 30, **kwargs: Any
) -> list[StepResult[OvenbirdState]]:
    """Warm the room linearly from ``start`` to ``end`` (a stove, not a sensor-fault step)."""
    return [run.step(start + (end - start) * i / minutes, **kwargs) for i in range(1, minutes + 1)]


def stove_term(result: StepResult[OvenbirdState]) -> float:
    term = result.decision.term("stove")
    assert term is not None
    return term.value


def frozen(result: StepResult[OvenbirdState]) -> str:
    return str(result.decision.controller_state.get("frozen_by"))


class TestDisabled:
    def test_no_stove_term_or_fields_without_config(self) -> None:
        ctrl = OvenbirdController(OvenbirdConfig.preset("mixed", comfort_room_c=COMFORT))
        run = Run(ctrl)
        result = run.hold(25.1, 30)[-1]
        assert result.decision.term("stove") is None
        assert "stove_state" not in result.decision.controller_state
        assert result.decision.reason is not ReasonCode.STOVE
        assert not result.state.stove_active

    def test_manual_request_is_ignored_without_config(self) -> None:
        ctrl = OvenbirdController(OvenbirdConfig.preset("mixed", comfort_room_c=COMFORT))
        request = Override(OverrideKind.STOVE, 1.0, Instant.from_unix(T0 + HOUR))
        result = Run(ctrl).step(21.0, override=request)
        assert not result.state.stove_active
        assert result.decision.term("stove") is None

    def test_inactive_term_says_where_it_enters(self) -> None:
        result = Run(OvenbirdController(config())).step(21.0)
        term = result.decision.term("stove")
        assert term is not None
        assert term.value == 0.0
        assert term.raw == 0.0
        assert "enters at 22.5 °C" in term.note
        assert result.decision.controller_state["stove_state"] == "inactive"


class TestEntry:
    def test_level_entry_backs_off_the_curve(self) -> None:
        run = Run(OvenbirdController(config()))
        run.hold(21.0, 5)
        result = run.step(ENTER)
        state = result.decision.controller_state
        assert result.state.stove_source is StoveSource.AUTO
        assert result.state.stove_trigger is StoveTrigger.LEVEL
        assert result.state.stove_entry_c == ENTER
        assert state["stove_event"] == "entered"
        assert state["stove_enter_c"] == pytest.approx(ENTER)
        assert state["stove_exit_c"] == pytest.approx(EXIT)
        assert stove_term(result) == pytest.approx(-3.0)
        feedback = result.decision.term("room_feedback")
        assert feedback is not None
        assert feedback.value == 0.0
        assert result.decision.pre_round == pytest.approx(CURVE_AT_5 - 3.0)
        assert "stove" in frozen(result)
        assert result.decision.note.startswith("Wood-stove mode (auto, level at 22.5 °C")

    def test_just_below_the_threshold_does_not_enter(self) -> None:
        run = Run(OvenbirdController(config()))
        result = run.hold(ENTER - 0.1, 30)[-1]
        assert not result.state.stove_active

    def test_reason_is_stove_once_the_setpoint_follows(self) -> None:
        run = Run(OvenbirdController(config()))
        results = run.hold(24.2, 40)
        assert results[-1].decision.setpoint == 28
        assert {r.decision.reason for r in results[-10:]} == {ReasonCode.STOVE}

    def test_needs_a_fresh_room_value(self) -> None:
        stale = RoomInput(25.1, 7200.0, False, ROOM_SIGNAL)
        result = Run(OvenbirdController(config())).hold(stale, 30)[-1]
        assert not result.state.stove_active

    def test_needs_a_plausible_room_value(self) -> None:
        cfg = config(room=RoomSensorProfile(crosscheck=CROSS, crosscheck_sustain_s=0.0))
        run = Run(OvenbirdController(cfg))
        run.hold(21.0, 5, thermostat=20.2)
        result = run.hold(lambda t: 21.0 if t < 600 else ENTER, 20, thermostat=18.0)[-1]
        assert not result.state.stove_active

    def test_needs_full_cooling_authority(self) -> None:
        profile = RoomSensorProfile(kind=RoomProfile.ON_CHANGE)
        silent = RoomInput(
            23.7,
            4 * HOUR,
            True,
            ROOM_SIGNAL,
            quantum_k=0.2,
            held_s=4 * HOUR,
            profile=RoomProfile.ON_CHANGE,
        )
        result = Run(OvenbirdController(config(room=profile))).hold(silent, 10)[-1]
        assert not result.state.stove_active

    def test_fast_rise_enters_above_comfort(self) -> None:
        run = Run(OvenbirdController(config()))
        results = run.hold(lambda t: 21.1 + t / (25 * MINUTE), 28)
        entered = [r for r in results if r.state.stove_active]
        assert entered
        assert entered[0].state.stove_trigger is StoveTrigger.RISE
        assert entered[0].state.stove_entry_c is not None
        assert entered[0].state.stove_entry_c < ENTER

    def test_fast_rise_below_comfort_does_not_enter(self) -> None:
        run = Run(OvenbirdController(config()))
        results = run.hold(lambda t: 19.2 + t / (20 * MINUTE), 20)
        assert not any(r.state.stove_active for r in results)

    def test_slow_rise_does_not_enter(self) -> None:
        run = Run(OvenbirdController(config()))
        results = run.hold(lambda t: 21.1 + t / (90 * MINUTE), 85)
        assert not any(r.state.stove_active for r in results)

    def test_fast_rise_can_be_switched_off(self) -> None:
        run = Run(OvenbirdController(config(StoveConfig(rise_k=None))))
        results = run.hold(lambda t: 21.1 + t / (25 * MINUTE), 25)
        assert not any(r.state.stove_active for r in results)

    def test_auto_off_still_takes_manual_requests(self) -> None:
        ctrl = OvenbirdController(config(StoveConfig(auto=False)))
        run = Run(ctrl)
        assert not run.hold(25.1, 30)[-1].state.stove_active
        request = Override(OverrideKind.STOVE, 1.0, Instant.from_unix(T0 + 10 * HOUR))
        assert run.step(25.1, override=request).state.stove_source is StoveSource.MANUAL


class TestHeldIntegrator:
    def test_integrator_held_through_the_episode_and_restored_after(self) -> None:
        run = Run(OvenbirdController(config()))
        run.hold(20.4, 240)
        warming = warm(run, 20.4, 24.7)
        entered = next(r for r in warming if r.state.stove_active)
        before = entered.state.stove_integral_k
        assert before is not None
        assert before > 0.1
        episode = run.hold(24.7, 300)
        assert all(r.state.stove_active for r in episode)
        assert {r.state.integral_k for r in episode} == {before}
        assert all(r.state.stove_integral_k == before for r in episode)
        after = run.hold(20.8, 2)
        assert not after[0].state.stove_active
        assert after[0].decision.controller_state["stove_exit"] == StoveExit.COOLED.value
        assert after[0].state.integral_k == pytest.approx(before, abs=0.01)

    def test_held_where_the_plain_pi_winds_down(self) -> None:
        plain = Run(OvenbirdController(OvenbirdConfig.preset("mixed", comfort_room_c=COMFORT)))
        stove = Run(OvenbirdController(config()))
        for run in (plain, stove):
            run.hold(20.4, 240)
            warm(run, 20.4, ENTER + 0.1)
        before = plain.state.integral_k
        plain.hold(ENTER + 0.1, 300)
        stove.hold(ENTER + 0.1, 300)
        assert plain.state.integral_k < before - 0.5
        assert stove.state.stove_active
        assert stove.state.integral_k == stove.state.stove_integral_k
        assert stove.state.integral_k > before - 0.2

    def test_no_silent_device_rollback_during_the_episode(self) -> None:
        profile = RoomSensorProfile(kind=RoomProfile.ON_CHANGE)
        run = Run(OvenbirdController(config(room=profile)))
        warm = RoomInput(
            23.2,
            60.0,
            True,
            ROOM_SIGNAL,
            quantum_k=0.2,
            held_s=60.0,
            profile=RoomProfile.ON_CHANGE,
        )
        run.hold(warm, 30)
        assert "room_silent_rollback" not in frozen(run.results[-1])


class TestCrosscheckInStoveMode:
    def test_no_implausible_latch_from_the_stove(self) -> None:
        cfg = config(room=RoomSensorProfile(crosscheck=CROSS))
        run = Run(OvenbirdController(cfg))
        run.hold(21.0, 60, thermostat=22.0)
        warm(run, 21.0, 25.1, thermostat=22.0)
        results = run.hold(25.1, 5 * 60, thermostat=22.0)
        assert all(r.state.stove_active for r in results)
        assert all(r.state.crosscheck_since is None for r in results)
        assert all(r.state.crosscheck_latched is None for r in results)
        assert all(r.decision.reason is not ReasonCode.ROOM_IMPLAUSIBLE for r in results)
        assert {r.decision.controller_state["room_plausible"] for r in results} == {True}
        thresholds = {r.decision.controller_state["room_crosscheck_threshold_k"] for r in results}
        assert thresholds == {5.5}
        assert all("room_implausible" not in frozen(r) for r in results)
        assert results[-1].state.crosscheck_offset_k == pytest.approx(1.0)

    def test_check_resumes_after_the_episode(self) -> None:
        cfg = config(room=RoomSensorProfile(crosscheck=CROSS))
        run = Run(OvenbirdController(cfg))
        run.hold(21.0, 60, thermostat=22.0)
        run.hold(25.1, 120, thermostat=22.0)
        after = run.hold(21.2, 3, thermostat=22.0)
        assert not after[-1].state.stove_active
        assert after[-1].decision.controller_state["room_plausible"] is True


class TestExit:
    def test_minimum_duration_then_hysteresis(self) -> None:
        run = Run(OvenbirdController(config()))
        run.step(ENTER)
        early = run.hold(20.2, 30)
        assert all(r.state.stove_active for r in early)
        band = run.hold(EXIT + 0.1, 40)
        assert all(r.state.stove_active for r in band)
        ended = run.step(EXIT - 0.1)
        assert not ended.state.stove_active
        assert ended.decision.controller_state["stove_event"] == "exited"
        assert ended.decision.controller_state["stove_exit"] == "cooled"

    def test_stale_room_ends_auto_mode_at_once(self) -> None:
        run = Run(OvenbirdController(config()))
        run.hold(24.2, 10)
        result = run.step(RoomInput(24.2, 7200.0, False, ROOM_SIGNAL))
        assert not result.state.stove_active
        assert result.decision.controller_state["stove_exit"] == "room_untrusted"

    def test_stays_active_while_warm_up_to_the_cap(self) -> None:
        assert StoveConfig().max_active_s == 8 * HOUR
        run = Run(OvenbirdController(config()))
        results = run.hold(lambda t: 24.2 if (t // MINUTE) % 2 else 24.4, 8 * 60 + 1)
        assert all(r.state.stove_active for r in results[:-1])
        assert results[-1].decision.controller_state["stove_exit"] == "max_active"

    def test_maximum_duration_blocks_the_level_trigger_until_cooled(self) -> None:
        cfg = config(StoveConfig(max_active_s=2 * HOUR))
        run = Run(OvenbirdController(cfg))
        results = run.hold(24.2, 2 * 60 + 1)
        assert results[-2].state.stove_active
        assert not results[-1].state.stove_active
        assert results[-1].decision.controller_state["stove_exit"] == "max_active"
        assert results[-1].state.stove_level_blocked
        assert not results[-1].state.stove_blocked
        hot = run.hold(24.2, 60)
        assert not any(r.state.stove_active for r in hot)
        assert all(r.state.stove_level_blocked for r in hot)
        assert "only a new fast rise" in hot[-1].decision.term("stove").note  # type: ignore[union-attr]
        cooled = run.step(EXIT - 0.2)
        assert not cooled.state.stove_level_blocked
        assert run.step(ENTER + 0.5).state.stove_active

    def test_a_new_fast_rise_enters_after_the_cap(self) -> None:
        cfg = config(StoveConfig(max_active_s=2 * HOUR))
        run = Run(OvenbirdController(cfg))
        run.hold(23.2, 2 * 60 + 1)
        assert run.state.stove_level_blocked
        assert not any(r.state.stove_active for r in run.hold(23.7, 35))
        start = run.t
        steps = run.hold(lambda t: 23.7 + (t - start) / (20 * MINUTE), 25)
        entered = next(r for r in steps if r.state.stove_active)
        assert entered.state.stove_trigger is StoveTrigger.RISE
        assert entered.decision.controller_state["stove_event"] == "entered"

    def test_reentry_waits_until_the_room_is_trusted_again(self) -> None:
        run = Run(OvenbirdController(config()))
        run.hold(24.2, 10)
        lost = run.step(RoomInput(24.2, 7200.0, False, ROOM_SIGNAL))
        assert lost.decision.controller_state["stove_exit"] == "room_untrusted"
        assert lost.state.stove_reentry_wait
        waiting = run.hold(24.2, 14)
        assert not any(r.state.stove_active for r in waiting)
        assert "trusted for 15 min" in waiting[-1].decision.term("stove").note  # type: ignore[union-attr]
        run.step(RoomInput(24.2, 7200.0, False, ROOM_SIGNAL))
        again = run.hold(24.2, 15)
        assert not any(r.state.stove_active for r in again)
        back = run.step(24.2)
        assert back.state.stove_active
        assert not back.state.stove_reentry_wait
        assert back.state.stove_trusted_since is None

    def test_reentry_hold_zero_enters_at_once(self) -> None:
        run = Run(OvenbirdController(config(StoveConfig(reentry_hold_s=0.0))))
        run.hold(24.2, 10)
        run.step(RoomInput(24.2, 7200.0, False, ROOM_SIGNAL))
        assert run.step(24.2).state.stove_active

    def test_manual_request_ignores_the_reentry_hold(self) -> None:
        run = Run(OvenbirdController(config()))
        run.hold(24.2, 10)
        run.step(RoomInput(24.2, 7200.0, False, ROOM_SIGNAL))
        request = Override(OverrideKind.STOVE, 1.0, Instant.from_unix(T0 + 5 * HOUR))
        assert run.step(24.2, override=request).state.stove_source is StoveSource.MANUAL


class TestLostRoomValue:
    def test_a_lost_value_keeps_its_mark_through_a_manual_episode(self) -> None:
        on_change = RoomSensorProfile(kind=RoomProfile.ON_CHANGE)
        ctrl = OvenbirdController(config(room=on_change))
        start = replace(ctrl.initial_state(), integral_k=0.2, integral_at_life_k=0.7)
        run = Run(ctrl, start)
        stale = RoomInput(COMFORT, 25 * HOUR, False, ROOM_SIGNAL, quantum_k=0.2)
        request = Override(OverrideKind.STOVE, 1.0, Instant.from_unix(T0 + 30 * MINUTE))
        during = run.hold(stale, 30, override=request)
        assert all(r.state.stove_active for r in during)
        assert all(r.state.integral_k == pytest.approx(0.2) for r in during)
        assert all(r.state.integral_at_life_k == pytest.approx(0.7) for r in during)
        assert not any("rollback" in str(r.decision.controller_state["frozen_by"]) for r in during)
        after = run.step(stale)
        assert not after.state.stove_active
        assert after.state.integral_k == pytest.approx(0.7)
        assert "room_lost_rollback" in str(after.decision.controller_state["frozen_by"])


class TestManual:
    def test_manual_on_until(self) -> None:
        run = Run(OvenbirdController(config()))
        until = Instant.from_unix(T0 + 30 * MINUTE)
        request = Override(OverrideKind.STOVE, 1.0, until, actor="owner")
        on = run.step(21.0, override=request)
        assert on.state.stove_source is StoveSource.MANUAL
        assert on.state.stove_trigger is StoveTrigger.MANUAL
        assert on.decision.controller_state["stove_until"] == until.wall.isoformat()
        assert on.decision.reason is ReasonCode.STOVE
        assert on.decision.actor == "owner"
        rest = run.hold(21.0, 30, override=request)
        assert rest[-2].state.stove_active
        assert not rest[-1].state.stove_active
        assert rest[-1].decision.controller_state["stove_exit"] == "manual_ended"

    def test_manual_end_hands_a_warm_room_to_the_detection(self) -> None:
        run = Run(OvenbirdController(config()))
        until = Instant.from_unix(T0 + 10 * MINUTE)
        request = Override(OverrideKind.STOVE, 1.0, until)
        run.hold(22.2, 11, override=request)
        result = run.step(22.2, override=request)
        assert result.state.stove_source is StoveSource.AUTO
        assert result.state.stove_trigger is StoveTrigger.HANDOVER

    def test_manual_stop_ends_and_blocks_until_cooled(self) -> None:
        run = Run(OvenbirdController(config()))
        run.hold(24.2, 10)
        stop = Override(OverrideKind.STOVE, 0.0)
        stopped = run.step(24.2, override=stop)
        assert not stopped.state.stove_active
        assert stopped.decision.controller_state["stove_exit"] == "manual_stop"
        assert stopped.state.stove_blocked
        later = run.hold(24.2, 30)
        assert not any(r.state.stove_active for r in later)
        run.step(EXIT - 0.3)
        assert run.step(ENTER).state.stove_active

    def test_manual_request_takes_over_an_auto_episode(self) -> None:
        run = Run(OvenbirdController(config()))
        first = run.step(24.2)
        request = Override(OverrideKind.STOVE, 1.0, Instant.from_unix(T0 + 5 * HOUR))
        result = run.step(24.2, override=request)
        assert result.state.stove_source is StoveSource.MANUAL
        assert result.state.stove_since == first.state.stove_since


class TestBackoff:
    def test_reference_room_below_its_floor_shrinks_the_backoff(self) -> None:
        cfg = config(StoveConfig(reference=HALL, reference_floor_c=19.0))
        run = Run(OvenbirdController(cfg))
        assert stove_term(run.step(24.2, hall=19.5)) == pytest.approx(-3.0)
        half = run.step(24.2, hall=18.5)
        assert stove_term(half) == pytest.approx(-1.5)
        assert half.decision.controller_state["stove_backoff_k"] == pytest.approx(1.5)
        assert half.decision.controller_state["stove_reference_c"] == 18.5
        assert stove_term(run.step(24.2, hall=17.9)) == 0.0
        stale = run.step(24.2, hall=17.0, hall_fresh=False)
        assert stove_term(stale) == pytest.approx(-1.5)
        assert stale.decision.controller_state["stove_reference_c"] is None
        assert stale.decision.controller_state["stove_reference_share"] == 0.5
        note = stale.decision.term("stove").note  # type: ignore[union-attr]
        assert "no fresh temperature, 50 % kept" in note
        refs = {ref.signal for ref in half.decision.inputs_used}
        assert HALL in refs

    def test_to_the_safety_minimum(self) -> None:
        cfg = config(StoveConfig(to_minimum=True))
        result = Run(OvenbirdController(cfg)).step(24.2)
        assert stove_term(result) == pytest.approx(SAFETY_LOW_AT_5 - CURVE_AT_5)
        assert result.decision.pre_round == pytest.approx(SAFETY_LOW_AT_5)
        assert result.decision.setpoint == 25

    @pytest.mark.parametrize("outside", [-10.0, 0.0, 5.0, 12.0, 18.0])
    def test_never_below_the_safety_minimum(self, outside: float) -> None:
        for stove in (StoveConfig(backoff_k=15.0), StoveConfig(to_minimum=True)):
            ctrl = OvenbirdController(config(stove))
            results = Run(ctrl).hold(25.1, 60, outside=outside)
            low = ctrl.config.safety.bounds(outside).low_int
            assert all(r.decision.setpoint is not None for r in results)
            assert min(r.decision.setpoint or 0 for r in results) >= low


class TestStateHandling:
    def test_flat_round_trip(self) -> None:
        run = Run(OvenbirdController(config()))
        state = run.hold(24.2, 5)[-1].state
        assert state_from_flat(state.as_flat()) == state
        run.step(RoomInput(24.2, 7200.0, False, ROOM_SIGNAL))
        waiting = run.hold(24.2, 3)[-1].state
        assert waiting.stove_reentry_wait
        assert waiting.stove_trusted_since is not None
        assert state_from_flat(waiting.as_flat()) == waiting

    def test_config_without_stove_ends_the_episode(self) -> None:
        cfg = config()
        run = Run(OvenbirdController(cfg))
        state = run.hold(24.2, 5)[-1].state
        plain = replace(cfg, stove=None)
        carried = carry_state(state, cfg, plain)
        assert not carried.stove_active
        assert carried.stove_since is None
        kept = carry_state(state, cfg, config(StoveConfig(backoff_k=5.0)))
        assert kept.stove_active

    def test_episode_survives_a_hold_tick(self) -> None:
        run = Run(OvenbirdController(config()))
        run.hold(24.2, 5)
        inputs = tick_inputs(run.t, 24.2)
        held = replace(inputs, snapshot=replace(inputs.snapshot, signals=MappingProxyType({})))
        result = run.ctrl.step(run.state, held)
        assert result.state.stove_active


def test_config_validation() -> None:
    with pytest.raises(ValueError, match="exit_hysteresis_k"):
        StoveConfig(enter_above_k=1.0, exit_hysteresis_k=1.5)
    with pytest.raises(ValueError, match="max_active_s"):
        StoveConfig(max_active_s=10 * 60.0)
    with pytest.raises(ValueError, match="backoff_k"):
        StoveConfig(backoff_k=0.0)
    with pytest.raises(ValueError, match="rise_k"):
        StoveConfig(rise_k=-1.0)
    with pytest.raises(ValueError, match="reentry_hold_s"):
        StoveConfig(reentry_hold_s=4 * HOUR)
    assert StoveConfig().reference_share(None) == 1.0
    assert StoveConfig().reference_share(18.25) == 1.0
    guarded = StoveConfig(reference=HALL)
    assert guarded.reference_share(None) == 0.5
    assert guarded.reference_share(18.25) == pytest.approx(0.25)
    assert guarded.reference_share(19.5) == 1.0
    with pytest.raises(ValueError, match="fault_step_k"):
        StoveConfig(fault_step_k=0.0)
    with pytest.raises(ValueError, match="crosscheck_allow_k"):
        StoveConfig(crosscheck_allow_k=-1.0)


class TestPlausibility:
    def test_a_sensor_failing_high_is_not_a_stove(self) -> None:
        cfg = config(room=RoomSensorProfile(crosscheck=CROSS))
        run = Run(OvenbirdController(cfg))
        run.hold(21.0, 180, thermostat=21.0)
        results = run.hold(24.7, 24 * 60, thermostat=21.0)
        assert not any(r.state.stove_active for r in results)
        first = results[0].decision.controller_state
        assert first["stove_fault"] is True
        assert first["stove_jump_k"] == pytest.approx(3.7)
        assert "sensor fault rather than a stove" in results[0].decision.term("stove").note  # type: ignore[union-attr]
        plausible = [r.decision.controller_state["room_plausible"] for r in results]
        latched = plausible.index(False)
        assert latched <= 2 * 60 + 1
        assert all(r.state.stove_fault for r in results)

    def test_a_step_ends_an_automatic_episode(self) -> None:
        run = Run(OvenbirdController(config()))
        run.hold(21.0, 10)
        warm(run, 21.0, 23.2)
        assert run.hold(23.2, 10)[-1].state.stove_active
        jumped = run.step(26.5)
        assert not jumped.state.stove_active
        assert jumped.decision.controller_state["stove_exit"] == StoveExit.ROOM_JUMP.value
        assert jumped.state.stove_fault
        assert not any(r.state.stove_active for r in run.hold(26.5, 60))

    def test_the_fault_clears_once_the_room_has_cooled(self) -> None:
        run = Run(OvenbirdController(config()))
        run.hold(21.0, 10)
        assert run.step(23.7).state.stove_fault
        assert not run.hold(23.7, 30)[-1].state.stove_active
        cooled = run.step(EXIT - 0.2)
        assert not cooled.state.stove_fault
        assert any(r.state.stove_active for r in warm(run, EXIT - 0.2, 23.2))

    def test_a_manual_episode_continues_through_a_step(self) -> None:
        run = Run(OvenbirdController(config()))
        request = Override(OverrideKind.STOVE, 1.0, Instant.from_unix(T0 + 5 * HOUR))
        run.hold(21.0, 10, override=request)
        result = run.step(24.7, override=request)
        assert result.state.stove_source is StoveSource.MANUAL
        assert result.state.stove_fault

    def test_a_step_blocks_the_handover(self) -> None:
        run = Run(OvenbirdController(config()))
        request = Override(OverrideKind.STOVE, 1.0, Instant.from_unix(T0 + 10 * MINUTE))
        run.hold(21.0, 5, override=request)
        results = run.hold(23.7, 10, override=request)
        assert results[0].state.stove_fault
        ended = next(r for r in results if not r.state.stove_active)
        assert ended.decision.controller_state["stove_exit"] == StoveExit.MANUAL_ENDED.value
        assert not any(r.state.stove_active for r in run.hold(23.7, 30))

    def test_the_crosscheck_still_flags_a_sensor_far_off_during_an_episode(self) -> None:
        cfg = config(room=RoomSensorProfile(crosscheck=CROSS))
        run = Run(OvenbirdController(cfg))
        run.hold(21.0, 60, thermostat=21.0)
        warm(run, 21.0, 24.2, thermostat=21.0)
        warm(run, 24.2, 30.0, minutes=60, thermostat=21.0)
        assert run.state.stove_active
        results = run.hold(30.0, 3 * 60, thermostat=21.0)
        lost = next(r for r in results if not r.state.stove_active)
        assert lost.decision.controller_state["stove_exit"] == StoveExit.ROOM_UNTRUSTED.value
        assert lost.decision.controller_state["room_plausible"] is False
        assert lost.state.crosscheck_latched == 30.0

    def test_entry_needs_the_room_clearly_above_the_reference(self) -> None:
        cfg = config(StoveConfig(reference=HALL))
        run = Run(OvenbirdController(cfg))
        run.hold(21.0, 10, hall=21.2)
        results = warm(run, 21.0, 23.0, hall=22.4)
        results += run.hold(23.0, 30, hall=22.4)
        assert not any(r.state.stove_active for r in results)
        last = results[-1].decision
        assert last.controller_state["stove_reference_gap_k"] == pytest.approx(0.6)
        assert "above the reference room" in last.term("stove").note  # type: ignore[union-attr]
        assert run.step(23.0, hall=21.2).state.stove_active

    def test_an_episode_ends_when_the_reference_has_warmed_up(self) -> None:
        cfg = config(StoveConfig(reference=HALL))
        run = Run(OvenbirdController(cfg))
        run.hold(21.0, 10, hall=19.2)
        warm(run, 21.0, 24.2, hall=19.2)
        early = run.hold(24.2, 10, hall=24.0)
        assert all(r.state.stove_active for r in early)
        rest = run.hold(24.2, 60, hall=24.0)
        ended = next(r for r in rest if not r.state.stove_active)
        assert ended.decision.controller_state["stove_exit"] == StoveExit.REFERENCE_WARM.value

    def test_a_reference_that_is_not_a_temperature_counts_as_missing(self) -> None:
        cfg = config(StoveConfig(reference=HALL))
        run = Run(OvenbirdController(cfg))
        inputs = tick_inputs(run.t, 24.2, hall=55.0)
        view = replace(inputs.snapshot.signals[HALL], unit="%")
        signals = dict(inputs.snapshot.signals) | {HALL: view}
        inputs = replace(
            inputs, snapshot=replace(inputs.snapshot, signals=MappingProxyType(signals))
        )
        result = run.ctrl.step(run.state, inputs)
        assert result.state.stove_active
        assert result.decision.controller_state["stove_reference_c"] is None
        assert stove_term(result) == pytest.approx(-1.5)


class TestManualAndTheCrosscheck:
    def _latched(self) -> Run:
        cfg = config(StoveConfig(rise_k=None), room=RoomSensorProfile(crosscheck=CROSS))
        run = Run(OvenbirdController(cfg))
        run.hold(20.2, 180, thermostat=20.2)
        warm(run, 20.2, 22.2, thermostat=20.2)
        run.hold(22.2, 2 * 60 + 5, thermostat=20.2)
        assert run.state.crosscheck_latched == 22.2
        return run

    def test_a_manual_request_keeps_the_latch_and_no_auto_takes_over(self) -> None:
        run = self._latched()
        until = Instant.from_unix(T0 + run.t + 5 * MINUTE)
        request = Override(OverrideKind.STOVE, 1.0, until, "op")
        manual = run.hold(22.2, 5, thermostat=20.2, override=request)
        assert manual[0].state.stove_source is StoveSource.MANUAL
        assert all(r.state.crosscheck_latched == 22.2 for r in manual)
        assert {r.decision.controller_state["room_plausible"] for r in manual} == {False}
        after = run.hold(22.2, 600, thermostat=20.2)
        assert after[0].decision.controller_state["stove_exit"] == StoveExit.MANUAL_ENDED.value
        assert not any(r.state.stove_active for r in after)
        assert all(r.decision.controller_state["room_plausible"] is False for r in after)

    def test_the_latch_holds_through_value_changes_until_they_agree(self) -> None:
        run = self._latched()
        request = Override(OverrideKind.STOVE, 1.0, Instant.from_unix(T0 + run.t + 3 * HOUR))
        run.hold(22.2, 2, thermostat=20.2, override=request)
        moved = run.step(22.4, thermostat=20.2, override=request)
        assert moved.state.crosscheck_latched == 22.2
        agreed = run.step(20.4, thermostat=20.2, override=request)
        assert agreed.state.crosscheck_latched is None
        assert agreed.decision.controller_state["room_plausible"] is True

    def test_without_stove_mode_too_only_agreement_unlatches(self) -> None:
        run = self._latched()
        assert run.step(22.4, thermostat=20.2).state.crosscheck_latched == 22.2
        assert run.step(20.4, thermostat=20.2).state.crosscheck_latched is None


class TestFastRiseAfterAiring:
    @pytest.mark.parametrize("level", [21.2, 22.1])
    def test_the_rebound_does_not_enter(self, level: float) -> None:
        run = Run(OvenbirdController(config()))
        run.hold(level, 120)
        run.hold(19.0, 10)
        rebound = run.hold(level, 61)
        assert not any(r.state.stove_active for r in rebound)
        assert not any(r.state.stove_fault for r in rebound)

    def test_rise_is_measured_from_the_comfort_target(self) -> None:
        run = Run(OvenbirdController(config()))
        run.hold(19.2, 60)
        results = warm(run, 19.2, 21.7, minutes=20)
        assert not any(r.state.stove_active for r in results)
        assert results[-1].decision.controller_state["stove_rise_k"] == pytest.approx(0.7)

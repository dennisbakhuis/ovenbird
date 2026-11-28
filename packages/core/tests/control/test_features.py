"""Optional controller features: manual room target, away, summer switch, quiet after a start.

Each feature is off unless configured or requested; with it off the decision record is
the one the controller made before the feature existed (the golden streams prove that on
whole runs, these tests on single ticks).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import time

import pytest

from ovenbird_core.control import (
    IntentKind,
    OvenbirdConfig,
    OvenbirdController,
    OvenbirdState,
    Override,
    OverrideKind,
    PlanSlice,
    PlanSource,
    QuietModeConfig,
    QuietStartConfig,
    QuietWindow,
    ReasonCode,
    StepResult,
    StoveConfig,
    SummerConfig,
    carry_state,
    room_offset_to_water,
    state_from_flat,
)
from ovenbird_core.control.synthetic import PlantView, synthetic_inputs
from ovenbird_core.instant import Instant

T0 = 1_794_528_000.0
MIXED = OvenbirdConfig.preset("mixed")
CTRL = OvenbirdController(MIXED)
KP = MIXED.feedback.kp
IDLE = PlantView()
RUNNING = PlantView(compressor_hz=35, outlet=33.0)
HOUR = 3600.0
DAY = 24 * HOUR


def at(seconds: float) -> Instant:
    """Return the instant ``seconds`` after the test origin."""
    return Instant.from_unix(T0 + seconds)


def tick(
    state: OvenbirdState,
    t: float,
    plant: PlantView = IDLE,
    controller: OvenbirdController = CTRL,
    **kwargs: object,
) -> StepResult[OvenbirdState]:
    """Run one controller tick at ``t`` seconds on ``plant``."""
    inputs = synthetic_inputs(at(t), plant, **kwargs)  # type: ignore[arg-type]
    return controller.step(state, inputs)


def run(
    plants: list[tuple[float, PlantView]],
    controller: OvenbirdController = CTRL,
    state: OvenbirdState | None = None,
    **kwargs: object,
) -> list[StepResult[OvenbirdState]]:
    """Run consecutive ticks and return every result."""
    current = state or controller.initial_state()
    results = []
    for t, plant in plants:
        result = tick(current, t, plant, controller, **kwargs)
        results.append(result)
        current = result.state
    return results


def every(
    plant: PlantView, count: int, step: float = 60.0, start: float = 0.0
) -> list[tuple[float, PlantView]]:
    """Return ``count`` ticks of ``plant``, ``step`` seconds apart."""
    return [(start + step * i, plant) for i in range(count)]


def boost(value: float, until: float = 2 * HOUR, actor: str = "admin") -> Override:
    """Return a manual room target of ``value`` K ending ``until`` seconds after the origin."""
    return Override(OverrideKind.ROOM_TARGET, value, at(until), actor)


def away(value: float, until: float = DAY) -> Override:
    """Return an away override of ``value`` K ending ``until`` seconds after the origin."""
    return Override(OverrideKind.AWAY, value, at(until), "admin")


class TestFeaturesOff:
    """With every optional feature off the record has no feature keys, terms or reasons."""

    def test_no_new_keys_terms_or_reasons(self) -> None:
        """A plain tick has no room_target or summer term, no feature keys, and plain feedback."""
        record = tick(CTRL.initial_state(), 0, replace(IDLE, room=20.5)).decision
        names = [term.name for term in record.terms]
        assert "room_target" not in names
        assert "summer" not in names
        state = record.controller_state
        assert not any(key.startswith(("summer_", "room_override", "quiet_start")) for key in state)
        assert record.reason is ReasonCode.ROOM_FEEDBACK

    def test_an_absent_room_override_equals_none(self) -> None:
        """Running without a room override gives the same records as passing room_override=None."""
        plant = replace(IDLE, room=20.5)
        plain = run(every(plant, 30))
        explicit = run(every(plant, 30), room_override=None)
        assert [r.decision.to_json_dict() for r in plain] == [
            r.decision.to_json_dict() for r in explicit
        ]

    def test_a_setpoint_or_boost_kind_in_the_room_slot_is_ignored(self) -> None:
        """A water-side override kind in the room-override slot leaves the decision unchanged."""
        plant = replace(IDLE, room=20.5)
        plain = tick(CTRL.initial_state(), 0, plant).decision
        water = Override(OverrideKind.BOOST, 2.0, at(HOUR))
        ignored = tick(CTRL.initial_state(), 0, plant, room_override=water).decision
        assert ignored.to_json_dict() == plain.to_json_dict()


class TestRoomTarget:
    """Manual room target and away: shift the PI target, expire, and yield to other modes."""

    def test_raises_the_room_target_through_the_pi(self) -> None:
        """A +1 K room target raises the feedback by kp and records term, state keys and reason."""
        plain = tick(CTRL.initial_state(), 0, replace(IDLE, room=21.0)).decision
        result = tick(CTRL.initial_state(), 0, replace(IDLE, room=21.0), room_override=boost(1.0))
        record = result.decision
        assert record.controller_state["room_target_c"] == pytest.approx(22.0)
        assert record.term("room_feedback").value == pytest.approx(KP)  # type: ignore[union-attr]
        assert record.pre_round == pytest.approx(plain.pre_round + KP)  # type: ignore[operator]
        assert record.reason is ReasonCode.ROOM_TARGET
        term = record.term("room_target")
        assert term is not None
        assert term.value == 0.0
        assert "manual room target +1.0 K by admin" in term.note
        assert record.controller_state["room_override"] == "room_target"
        assert record.controller_state["room_override_k"] == 1.0
        assert record.actor is None

    def test_a_cooler_room_lowers_the_target(self) -> None:
        """A -1 K room target lowers the target to 20 °C and the feedback by kp."""
        record = tick(
            CTRL.initial_state(), 0, replace(IDLE, room=21.0), room_override=boost(-1.0)
        ).decision
        assert record.controller_state["room_target_c"] == pytest.approx(20.0)
        assert record.term("room_feedback").value == pytest.approx(-KP)  # type: ignore[union-attr]

    def test_away_has_its_own_reason(self) -> None:
        """An away override of -5 K gives reason AWAY, a 16 °C target and a note naming it."""
        record = tick(
            CTRL.initial_state(), 0, replace(IDLE, room=21.0), room_override=away(-5.0)
        ).decision
        assert record.reason is ReasonCode.AWAY
        assert record.controller_state["room_target_c"] == pytest.approx(16.0)
        assert "away -5.0 K room" in record.note

    def test_expires_by_itself(self) -> None:
        """After its end time the room target no longer changes the decision."""
        plant = replace(IDLE, room=21.0)
        expired = tick(CTRL.initial_state(), 3 * HOUR, plant, room_override=boost(1.0)).decision
        plain = tick(CTRL.initial_state(), 3 * HOUR, plant).decision
        assert expired.to_json_dict() == plain.to_json_dict()

    def test_maps_to_water_without_a_room_sensor(self) -> None:
        """Without a room sensor the offset is mapped to water via the curve slope."""
        record = tick(CTRL.initial_state(), 0, room_signal=None, room_override=boost(1.0)).decision
        term = record.term("room_target")
        assert term is not None
        assert term.value == pytest.approx(room_offset_to_water(MIXED.curve, 5.0, 1.0))
        assert "mapped via curve slope" in term.note

    def test_replaces_an_active_plan_slice(self) -> None:
        """An active room target pauses a plan slice and takes over the target."""
        plan = PlanSlice(0.5, ReasonCode.PLAN_PREHEAT, at(0), at(HOUR), PlanSource.RULE)
        record = tick(
            CTRL.initial_state(), 0, replace(IDLE, room=21.0), plan=plan, room_override=boost(1.0)
        ).decision
        assert record.controller_state["room_target_c"] == pytest.approx(22.0)
        assert "paused: a manual room target or away is active" in record.term("plan").note  # type: ignore[union-attr]

    def test_respects_the_safety_maximum(self) -> None:
        """A large room target in the cold is clamped at the safety maximum (SAFETY_CLAMP)."""
        cold = replace(IDLE, outside=-20.0, room=18.0)
        record = tick(CTRL.initial_state(), 0, cold, room_override=boost(2.0)).decision
        assert record.setpoint == int(MIXED.safety.max_supply_c)
        assert record.reason is ReasonCode.SAFETY_CLAMP

    def test_is_paused_during_a_stove_episode(self) -> None:
        """A requested wood-stove episode pauses the room target and wins the reason."""
        cfg = replace(MIXED, stove=StoveConfig())
        ctrl = OvenbirdController(cfg)
        stove = Override(OverrideKind.STOVE, 1.0, at(HOUR), "admin")
        record = tick(
            ctrl.initial_state(),
            0,
            replace(IDLE, room=21.0),
            ctrl,
            override=stove,
            room_override=boost(1.0),
        ).decision
        assert record.reason is ReasonCode.STOVE
        assert record.controller_state["room_override_paused"] == "stove"
        assert "paused by wood-stove mode" in record.term("room_target").note  # type: ignore[union-attr]

    def test_a_raised_target_lifts_the_stove_entry(self) -> None:
        """A raised room target lifts the stove entry threshold by the same amount."""
        cfg = replace(MIXED, stove=StoveConfig())
        ctrl = OvenbirdController(cfg)
        plain = tick(ctrl.initial_state(), 0, replace(IDLE, room=21.0), ctrl).decision
        raised = tick(
            ctrl.initial_state(), 0, replace(IDLE, room=21.0), ctrl, room_override=boost(1.0)
        ).decision
        enter = plain.controller_state["stove_enter_c"]
        assert raised.controller_state["stove_enter_c"] == pytest.approx(enter + 1.0)  # type: ignore[operator]

    def test_integrator_winds_on_the_shifted_target(self) -> None:
        """The integrator winds up against the shifted target over an hour."""
        results = run(every(replace(IDLE, room=21.0), 61), room_override=boost(1.0))
        assert results[-1].state.integral_k > 0.0


def summer_controller(**overrides: float) -> OvenbirdController:
    """Return a controller with the summer switch on (``overrides`` for its settings)."""
    return OvenbirdController(replace(MIXED, summer=SummerConfig(**overrides)))


class TestSummer:
    """Summer switch: slow outside mean switches heating to the safety minimum and back."""

    def test_waits_one_time_constant_before_switching(self) -> None:
        """The switch turns on only after about one mean time constant of warm outside air."""
        ctrl = summer_controller(mean_tau_s=6 * HOUR)
        warm = replace(IDLE, outside=22.0, room=21.0)
        results = run(every(warm, 8, step=HOUR), ctrl)
        active = [r.state.summer_active for r in results]
        assert active[:6] == [False] * 6
        assert active[6] is True

    def test_requests_the_safety_minimum_and_holds_the_integrator(self) -> None:
        """Active summer mode requests the lower safety bound, holds the integrator and says so."""
        ctrl = summer_controller(mean_tau_s=6 * HOUR)
        state = replace(ctrl.initial_state(), integral_k=1.2)
        warm = replace(IDLE, outside=22.0, room=20.0)
        results = run(every(warm, 10, step=HOUR), ctrl, state=state)
        record = results[-1].decision
        bounds = MIXED.safety.bounds(22.0)
        assert record.setpoint == bounds.low_int
        assert record.reason is ReasonCode.SUMMER
        assert results[-1].state.integral_k == pytest.approx(1.2)
        assert "summer" in str(record.controller_state["frozen_by"])
        assert record.controller_state["summer_state"] == "active"
        assert record.note.startswith("Summer switch: slow outside mean")
        summer = record.term("summer")
        assert summer is not None
        assert summer.value < 0.0

    def test_resumes_below_the_hysteresis(self) -> None:
        """The switch holds just below the off threshold and ends once the mean is cold enough."""
        ctrl = summer_controller(mean_tau_s=6 * HOUR, off_c=18.0, hysteresis_k=2.0)
        state = replace(
            ctrl.initial_state(),
            summer_mean_c=18.5,
            summer_mean_at=T0 - 60.0,
            summer_mean_from=T0 - DAY,
            summer_active=True,
        )
        mild = replace(IDLE, outside=17.0, room=21.0)
        first = tick(state, 0, mild, ctrl)
        assert first.state.summer_active is True
        cold = replace(IDLE, outside=5.0, room=21.0)
        results = run(every(cold, 6, step=HOUR, start=HOUR), ctrl, state=first.state)
        assert results[-1].state.summer_active is False
        assert results[-1].decision.reason is ReasonCode.ROOM_FEEDBACK

    def test_pauses_a_plan_and_a_room_target(self) -> None:
        """An active summer switch pauses a plan slice and a manual room target."""
        ctrl = summer_controller()
        state = replace(
            ctrl.initial_state(),
            summer_mean_c=20.0,
            summer_mean_at=T0 - 60.0,
            summer_mean_from=T0 - 2 * DAY,
            summer_active=True,
        )
        plan = PlanSlice(0.5, ReasonCode.PLAN_PREHEAT, at(0), at(HOUR), PlanSource.RULE)
        record = tick(
            state,
            0,
            replace(IDLE, outside=20.0, room=21.0),
            ctrl,
            plan=plan,
            room_override=boost(1.0),
        ).decision
        assert record.term("plan").note == "paused by the summer switch"  # type: ignore[union-attr]
        assert record.controller_state["room_override_paused"] == "summer"
        assert record.reason is ReasonCode.SUMMER

    def test_the_cycling_floor_still_protects_a_run(self) -> None:
        """During a running compressor the cycling floor still binds in summer mode."""
        ctrl = summer_controller()
        state = replace(
            ctrl.initial_state(),
            summer_mean_c=20.0,
            summer_mean_at=T0 - 60.0,
            summer_mean_from=T0 - 2 * DAY,
            summer_active=True,
            running=True,
            run_started_at=T0 - 300.0,
            setpoint=30,
        )
        record = tick(state, 0, replace(RUNNING, outside=20.0, outlet=31.0), ctrl).decision
        assert record.binding == "cycling_floor"

    def test_state_survives_the_flat_round_trip(self) -> None:
        """Summer state round-trips through the flat serialisation."""
        ctrl = summer_controller(mean_tau_s=6 * HOUR)
        results = run(every(replace(IDLE, outside=22.0), 8, step=HOUR), ctrl)
        state = results[-1].state
        assert state_from_flat(state.as_flat()) == state

    def test_carry_state_forgets_the_switch(self) -> None:
        """Carrying state to a config without summer clears the mean and the active flag."""
        cfg = replace(MIXED, summer=SummerConfig())
        state = replace(OvenbirdState(), summer_mean_c=20.0, summer_active=True)
        carried = carry_state(state, cfg, MIXED)
        assert carried.summer_mean_c is None
        assert carried.summer_active is False


def quiet_controller(windows: tuple[QuietWindow, ...] = ()) -> OvenbirdController:
    """Return a controller with quiet mode after a start (and the given schedule)."""
    quiet = QuietModeConfig(windows, "UTC") if windows else None
    return OvenbirdController(
        replace(MIXED, quiet=quiet, quiet_start=QuietStartConfig(duration_s=600.0, level=2))
    )


def quiet_levels(results: list[StepResult[OvenbirdState]]) -> list[int | None]:
    """Return the quiet-mode intent of every tick."""
    levels: list[int | None] = []
    for result in results:
        intent = result.intent(IntentKind.QUIET_MODE)
        levels.append(None if intent is None else intent.value)
    return levels


class TestQuietStart:
    """Quiet mode for a fixed time after a compressor start, alone and with a schedule."""

    def test_quiet_for_the_window_after_a_start(self) -> None:
        """Quiet level 2 is requested for ten ticks after the start and then released."""
        ctrl = quiet_controller()
        plants = every(IDLE, 2) + every(RUNNING, 14, start=120.0)
        results = run(plants, ctrl)
        levels = quiet_levels(results)
        assert levels[:2] == [0, 0]
        assert levels[2:12] == [2] * 10
        assert levels[12:] == [0] * 4
        start = results[2].intent(IntentKind.QUIET_MODE)
        assert start is not None
        assert start.reason is ReasonCode.QUIET_START
        assert results[2].decision.controller_state["quiet_start"] is True

    def test_takes_the_quieter_of_start_and_schedule(self) -> None:
        """When a schedule window is active the quieter of start and schedule level wins."""
        ctrl = quiet_controller((QuietWindow(time(0, 0), time(23, 59), 3),))
        plants = every(IDLE, 1) + every(RUNNING, 3, start=60.0)
        levels = quiet_levels(run(plants, ctrl))
        assert levels == [3, 3, 3, 3]

    def test_keeps_the_level_during_a_defrost(self) -> None:
        """The quiet level is kept through a defrost that follows the start."""
        ctrl = quiet_controller()
        defrost = replace(RUNNING, defrost=1)
        plants = every(IDLE, 1) + every(RUNNING, 2, start=60.0) + every(defrost, 12, start=180.0)
        levels = quiet_levels(run(plants, ctrl))
        assert levels[1:] == [2] * 14

    def test_without_the_feature_no_quiet_intent(self) -> None:
        """Without the feature no quiet-mode intent is produced."""
        plants = every(IDLE, 1) + every(RUNNING, 3, start=60.0)
        assert quiet_levels(run(plants)) == [None] * 4

"""Scenario tests over synthetic minute-by-minute sequences."""

from __future__ import annotations

from dataclasses import replace
from itertools import pairwise

import pytest

from ovenbird_core.catalogue import HeishaSignal
from ovenbird_core.control import (
    IntentKind,
    LadderLevel,
    OvenbirdConfig,
    OvenbirdController,
    OvenbirdState,
    PlanSlice,
    PlanSource,
    RampPhase,
    ReasonCode,
    StepResult,
)
from ovenbird_core.control.synthetic import ROOM_SIGNAL, PlantView, synthetic_inputs
from ovenbird_core.housemodel import HouseModel
from ovenbird_core.instant import Instant

T0 = 1_794_528_000.0
MIXED = OvenbirdConfig.preset("mixed")
CTRL = OvenbirdController(MIXED)


def drive(
    plants: list[PlantView], state: OvenbirdState | None = None, start_minute: int = 0
) -> list[StepResult[OvenbirdState]]:
    current = state or CTRL.initial_state()
    results = []
    for minute, plant in enumerate(plants, start=start_minute):
        result = CTRL.step(current, synthetic_inputs(Instant.from_unix(T0 + 60 * minute), plant))
        results.append(result)
        current = result.state
    return results


def setpoints(results: list[StepResult[OvenbirdState]]) -> list[int | None]:
    return [r.decision.setpoint for r in results]


def changes(results: list[StepResult[OvenbirdState]]) -> int:
    values = [s for s in setpoints(results) if s is not None]
    return sum(1 for a, b in pairwise(values) if a != b)


def settled(minutes: int = 120, **values: object) -> list[PlantView]:
    return [PlantView(**values)] * minutes  # type: ignore[arg-type]


def test_cold_morning_raises_the_setpoint_gradually() -> None:
    plants = []
    for minute in range(8 * 60):
        outside = 6.0 - min(10, minute // 30)
        room = round(21.0 - min(0.6, minute / 400), 1)
        running = (minute // 40) % 3 != 2
        plants.append(
            PlantView(
                outside=outside,
                outlet=33.0 if running else 28.0,
                compressor_hz=45 if running else 0,
                room=room,
            )
        )
    results = drive(plants)
    values = [s for s in setpoints(results) if s is not None]
    assert values[0] <= 31
    assert values[-1] >= 36
    assert all(20 <= s <= 40 for s in values)
    filtered = results[-1].state.outside_filtered
    assert filtered is not None
    assert filtered > -4.0
    assert results[-1].state.integral_k > 0.0
    assert changes(results) <= 8 * 4


def test_defrost_burst_never_lowers_the_setpoint() -> None:
    steady = PlantView(outside=0.0, outlet=34.0, compressor_hz=40, room=20.8)
    burst = [
        replace(steady, defrost=1, outlet=outlet, compressor_hz=hz)
        for outlet, hz in ((31.0, 0), (28.0, 35), (25.0, 42), (22.5, 40), (24.0, 30))
    ]
    after = [replace(steady, outlet=outlet) for outlet in (36.0, 37.0, 36.5, 35.0)]
    warmup = drive([steady] * 60)
    before = warmup[-1]
    results = drive(burst + after + [steady] * 30, before.state, start_minute=60)
    during = results[: len(burst)]
    floor = before.decision.setpoint
    assert floor is not None
    for result in during:
        assert result.decision.setpoint is not None
        assert result.decision.setpoint >= floor
        assert result.state.integral_k == before.state.integral_k
        assert result.state.ramp_phase is RampPhase.IDLE
        assert "defrost" in str(result.decision.controller_state["frozen_by"])
    for result, plant in zip(results[len(burst) : len(burst) + 4], after, strict=True):
        setpoint = result.decision.setpoint
        assert setpoint is not None
        assert plant.outlet is not None
        assert plant.outlet - setpoint < MIXED.cycling.stop_delta_k


def test_room_sensor_dropout_falls_back_to_curve_only_and_recovers() -> None:
    cool = PlantView(outside=5.0, room=20.5)
    dropout = replace(cool, stale=frozenset({ROOM_SIGNAL}))
    first = drive([cool] * 120)
    with_feedback = first[-1]
    assert with_feedback.decision.ladder is LadderLevel.SCHEDULE_CURVE_FEEDBACK
    assert with_feedback.decision.setpoint == 32
    integral = with_feedback.state.integral_k
    stale = drive([dropout] * 120, with_feedback.state, start_minute=120)
    assert all(r.decision.ladder is LadderLevel.CURVE_ONLY for r in stale)
    assert all(r.state.integral_k == integral for r in stale)
    assert integral > 0.0
    held = [r.decision.term("room_feedback") for r in stale]
    assert held[0] is not None
    assert held[0].value == pytest.approx(integral)
    assert held[-1] is not None
    assert held[-1].value == pytest.approx(integral * (1.0 - 119 * 60.0 / 86400.0))
    assert "fading to 0 over 24 h" in held[-1].note
    assert stale[-1].decision.controller_state["frozen_by"] == "room_stale"
    faded = drive([dropout] * 2, stale[-1].state, start_minute=120 + 24 * 60)
    assert faded[-1].decision.term("room_feedback").value == 0.0  # type: ignore[union-attr]
    assert faded[-1].decision.reason is ReasonCode.ROOM_STALE
    assert faded[-1].decision.setpoint == 31
    back = drive([cool] * 30, stale[-1].state, start_minute=240)
    assert back[-1].decision.ladder is LadderLevel.SCHEDULE_CURVE_FEEDBACK
    assert back[-1].state.integral_k > integral


def test_heishamon_death_refuses_and_resumes() -> None:
    healthy = PlantView(outside=3.0, room=20.7)
    dead = replace(healthy, alive=False, stale=frozenset({HeishaSignal.OUTSIDE_TEMP}))
    before = drive([healthy] * 30)
    gone = drive([dead] * 20, before[-1].state, start_minute=30)
    assert all(r.intents == () for r in gone)
    assert all(r.decision.ladder is LadderLevel.REFUSE for r in gone)
    assert all(r.decision.reason is ReasonCode.HEISHAMON_DEAD for r in gone)
    assert gone[-1].state.integral_k == before[-1].state.integral_k
    resumed = drive([healthy] * 5, gone[-1].state, start_minute=50)
    assert resumed[0].decision.ladder is LadderLevel.SCHEDULE_CURVE_FEEDBACK
    assert resumed[0].intent(IntentKind.WATER_SETPOINT) is not None


def test_switch_to_compensation_mode_refuses() -> None:
    direct = PlantView(outside=3.0, room=21.0)
    compensation = replace(direct, heating_mode=0)
    results = drive([direct] * 10 + [compensation] * 10 + [direct] * 5)
    refused = results[10:20]
    assert all(r.intents == () for r in refused)
    assert all(r.decision.reason is ReasonCode.MODE_MISMATCH for r in refused)
    assert all("Heating_Mode" in r.decision.note for r in refused)
    assert results[20].decision.ladder is LadderLevel.SCHEDULE_CURVE_FEEDBACK


def test_dhw_run_freezes_and_does_not_start_a_ramp() -> None:
    idle = PlantView(outside=2.0, outlet=27.0, room=20.6)
    dhw = replace(idle, compressor_hz=50, valve=1, outlet=48.0)
    results = drive([idle] * 30 + [dhw] * 20 + [idle] * 5)
    run = results[30:50]
    assert all(r.state.ramp_phase is RampPhase.IDLE for r in run)
    assert all(r.state.integral_k == results[29].state.integral_k for r in run)
    assert all(r.decision.term("cycling_floor").value == 0.0 for r in run)  # type: ignore[union-attr]
    held = results[29].decision.setpoint
    assert held is not None
    assert all((r.decision.setpoint or 0) >= held for r in run)


HOUSE = HouseModel(h_air_out=250.0, h_water_air=150.0, solar_mass_fraction=0.5)
HOUSE_OUTSIDE_C = 5.0
PUMP_W_PER_K = 1500.0
PUMP_MAX_W = 8000.0


def house_run(
    window: tuple[float, float] | None, offset: float, hours: float
) -> list[StepResult[OvenbirdState]]:
    """Drive the controller against the house model; a model plan renewed every 15 min."""
    discrete = HOUSE.discretise(60.0)
    start = HOUSE.steady_state(21.0, HOUSE_OUTSIDE_C)
    water, mass, air = start.loop_mean_c, start.mass_c, 21.0
    state = CTRL.initial_state()
    results = []
    for minute in range(int(hours * 60)):
        t = 60.0 * minute
        plan = None
        if window is not None and window[0] * 3600.0 <= t < window[1] * 3600.0:
            begin = Instant.from_unix(T0 + t // 900.0 * 900.0)
            reason = ReasonCode.PLAN_SETBACK if offset < 0 else ReasonCode.PLAN_PREHEAT
            plan = PlanSlice(offset, reason, begin, begin.shifted(1200.0), PlanSource.MODEL)
        plant = PlantView(
            outside=HOUSE_OUTSIDE_C,
            outlet=round(water * 4.0) / 4.0,
            compressor_hz=35,
            room=round(air, 1),
        )
        result = CTRL.step(state, synthetic_inputs(Instant.from_unix(T0 + t), plant, plan=plan))
        results.append(result)
        state = result.state
        setpoint = result.decision.setpoint
        assert setpoint is not None
        heat = min(max(PUMP_W_PER_K * (setpoint - water), 0.0), PUMP_MAX_W)
        water, mass, air = discrete.step(
            (water, mass, air), (heat, HOUSE_OUTSIDE_C, 0.0, HOUSE.q_int_w)
        )
    return results


@pytest.mark.parametrize("offset", [-0.5, 0.3])
def test_a_model_plan_at_its_bound_comes_and_goes_softly(offset: float) -> None:
    plain = house_run(None, 0.0, 72.0)
    planned = house_run((24.0, 30.0), offset, 72.0)
    bounds = MIXED.safety.bounds(HOUSE_OUTSIDE_C)
    window = planned[24 * 60 : 30 * 60]
    assert all(r.decision.ladder is LadderLevel.MODEL_PLAN for r in window)
    assert all(
        r.decision.controller_state["room_target_c"] == pytest.approx(21.0 + offset) for r in window
    )
    values = setpoints(planned)
    assert all(v is not None and bounds.low_int <= v <= bounds.high_int for v in values)
    changes = [
        (minute, b - a)
        for minute, (a, b) in enumerate(pairwise(values), start=1)
        if a is not None and b is not None and a != b
    ]
    assert all(abs(step) == 1 for _, step in changes)
    gaps = [b - a for (a, _), (b, _) in pairwise(changes)]
    assert all(gap >= MIXED.stages.dwell_s / 60.0 for gap in gaps)
    after = range(30 * 60, 72 * 60)
    plain_values = setpoints(plain)
    assert all(abs((values[i] or 0) - (plain_values[i] or 0)) <= 1 for i in after)
    targets = [r.decision.controller_state["room_target_c"] for r in planned[30 * 60 :]]
    assert all(target == pytest.approx(21.0) for target in targets)
    gap = abs(planned[-1].state.integral_k - plain[-1].state.integral_k)
    assert gap < 0.3

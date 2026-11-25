from __future__ import annotations

from dataclasses import replace

from hypothesis import given
from hypothesis import strategies as st

from ovenbird_core.control import (
    HeatingCurve,
    OvenbirdConfig,
    OvenbirdState,
    RampPhase,
    RoomFeedbackConfig,
    RoomSensorProfile,
    StartRampConfig,
    carry_state,
    envelope_violations,
)

MIXED = OvenbirdConfig.preset("mixed")
STATE = OvenbirdState(
    setpoint=33,
    last_change_at=1234.0,
    integral_k=2.5,
    outside_filtered=1.7,
    outside_at=1200.0,
    last_tick_at=1260.0,
    running=True,
    run_started_at=900.0,
    ramp_phase=RampPhase.HOLD,
    ramp_elapsed_s=300.0,
    ramp_cap=31.5,
    pump_duty=159,
    crosscheck_offset_k=0.8,
    crosscheck_since=1100.0,
)


@given(
    integral=st.floats(-3.0, 3.0),
    limit=st.floats(0.0, 3.0),
    kp=st.floats(0.0, 6.0),
)
def test_integrator_lands_inside_the_new_clamp(integral: float, limit: float, kp: float) -> None:
    new = replace(
        MIXED, feedback=RoomFeedbackConfig(kp=kp, output_limit_k=3.0, integral_limit_k=limit)
    )
    carried = carry_state(replace(STATE, integral_k=integral), MIXED, new)
    assert abs(carried.integral_k) <= limit + 1e-12
    assert carried.setpoint == STATE.setpoint
    assert carried.last_change_at == STATE.last_change_at


def test_setpoint_dwell_timer_filter_and_run_survive() -> None:
    new = replace(MIXED, comfort_room_c=22.4, curve=HeatingCurve.of((-10, 40), (15, 26)))
    carried = carry_state(STATE, MIXED, new)
    assert carried == STATE


def test_no_integral_part_resets_the_integrator() -> None:
    new = replace(MIXED, feedback=RoomFeedbackConfig(kp=0.0, ti_s=0.0))
    assert carry_state(STATE, MIXED, new).integral_k == 0.0


def test_disabled_ramp_ends_a_running_ramp() -> None:
    new = replace(MIXED, ramp=StartRampConfig(enabled=False))
    carried = carry_state(STATE, MIXED, new)
    assert (carried.ramp_phase, carried.ramp_elapsed_s, carried.ramp_cap) == (
        RampPhase.IDLE,
        0.0,
        None,
    )
    assert carried.run_started_at == STATE.run_started_at


def test_changed_crosscheck_forgets_the_learned_offset() -> None:
    old = replace(MIXED, room=RoomSensorProfile(crosscheck="main/Room_Thermostat_Temp"))
    new = replace(MIXED, room=RoomSensorProfile(crosscheck="ha/sensor.other"))
    carried = carry_state(STATE, old, new)
    assert carried.crosscheck_offset_k is None
    assert carried.crosscheck_since is None
    assert carry_state(STATE, old, old).crosscheck_offset_k == STATE.crosscheck_offset_k


def test_envelope_violations_checks_every_break_point() -> None:
    safety = MIXED.safety
    assert envelope_violations(MIXED.curve, safety) == []
    inside = HeatingCurve.of((-10, 44), (0, 39), (15, 19))
    assert envelope_violations(inside, safety) == []
    above = HeatingCurve.of((-10, 39), (5, 37), (15, 25))
    found = envelope_violations(above, safety)
    assert [outside for outside, _ in found] == [5.0]
    assert found[0][1] > 0
    below = HeatingCurve.of((-20, 30), (15, 25))
    assert [outside for outside, _ in envelope_violations(below, safety)] == [-20.0, -10.0, 0.0]

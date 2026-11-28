"""Replay of decision records: inputs and state rebuilt from the record reproduce the tick."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from ovenbird_core.catalogue import HeishaSignal
from ovenbird_core.control import (
    DecisionRecord,
    HeatingCurve,
    OvenbirdConfig,
    OvenbirdController,
    OvenbirdState,
    RampPhase,
    RoomSensorProfile,
    clock_offset,
    control_inputs,
    replay_inputs,
    shift_state,
    state_from_flat,
)
from ovenbird_core.control.synthetic import ROOM_SIGNAL, PlantView, synthetic_snapshot
from ovenbird_core.control.types import RoomProfile
from ovenbird_core.instant import Instant

START = datetime(2026, 11, 10, 0, 0, tzinfo=UTC)
TICK_S = 60.0


def _plant(index: int) -> PlantView:
    """Return the synthetic plant at minute ``index`` (swinging outside, cycles, defrosts)."""
    hour = index / 60.0
    running = (index // 50) % 3 != 2
    return PlantView(
        outside=float(round(3.0 + 4.0 * math.sin(hour / 4.0))),
        outlet=31.0 + 2.0 * math.sin(index / 7.0) if running else 27.0,
        inlet=27.0,
        compressor_hz=40 if running else 0,
        defrost=1 if index % 97 in (5, 6, 7) else 0,
        water_target=32,
        max_pump_duty=159,
        room=round(20.6 + 0.6 * math.sin(hour / 3.0), 1),
    )


def _config() -> OvenbirdConfig:
    """Return the mixed preset with an on-change room sensor cross-checked on the inlet."""
    base = OvenbirdConfig.preset("mixed")
    room = RoomSensorProfile(kind=RoomProfile.ON_CHANGE, crosscheck=HeishaSignal.INLET_TEMP)
    return replace(base, room=room, comfort_room_c=21.0)


def _run(config: OvenbirdConfig, ticks: int, shift_at: int | None = None) -> list[DecisionRecord]:
    """Run ``ticks`` minutes on the synthetic plant, shifting the clock at ``shift_at``."""
    controller = OvenbirdController(config)
    state = controller.initial_state()
    origin = 1000.0
    records: list[DecisionRecord] = []
    for index in range(ticks):
        if shift_at is not None and index == shift_at:
            state = shift_state(state, 5000.0)
            origin += 5000.0
        now = Instant(origin + index * TICK_S, START + timedelta(seconds=index * TICK_S))
        snapshot = synthetic_snapshot(now, _plant(index))
        inputs = control_inputs(snapshot, room_signal=ROOM_SIGNAL, room_profile=config.room)
        result = controller.step(state, inputs)
        state = result.state
        text = json.dumps(result.decision.to_json_dict())
        records.append(DecisionRecord.from_json_dict(json.loads(text)))
    return records


def _replay(config: OvenbirdConfig, records: list[DecisionRecord]) -> list[DecisionRecord]:
    """Replay ``records`` through a fresh controller on ``config``, following clock shifts."""
    controller = OvenbirdController(config)
    state = controller.initial_state()
    previous: DecisionRecord | None = None
    out: list[DecisionRecord] = []
    for record in records:
        if previous is not None:
            delta = clock_offset(previous.at) - clock_offset(record.at)
            if abs(delta) > 1.0:
                state = shift_state(state, delta)
        inputs = replay_inputs(record, room_signal=ROOM_SIGNAL, room_profile=config.room)
        result = controller.step(state, inputs)
        state = result.state
        out.append(result.decision)
        previous = record
    return out


def test_state_round_trips_through_the_flat_form() -> None:
    """A fully populated state survives the flat form; an empty dict gives the default."""
    state = OvenbirdState(
        setpoint=31,
        last_change_at=12.5,
        integral_k=-0.4,
        outside_filtered=2.25,
        outside_at=11.0,
        last_tick_at=11.0,
        running=True,
        run_started_at=3.0,
        ramp_phase=RampPhase.RELEASE,
        ramp_elapsed_s=420.0,
        ramp_cap=29.5,
        pump_duty=159,
        quiet_level=1,
        crosscheck_offset_k=0.8,
        crosscheck_latched=20.8,
    )
    assert state_from_flat(state.as_flat()) == state
    assert state_from_flat({}) == OvenbirdState()


def test_shift_state_moves_only_times() -> None:
    """shift_state moves the time fields and leaves the integrator and unset times alone."""
    state = OvenbirdState(setpoint=30, last_change_at=10.0, integral_k=0.3, last_tick_at=20.0)
    moved = shift_state(state, 100.0)
    assert moved.last_change_at == 110.0
    assert moved.last_tick_at == 120.0
    assert moved.integral_k == 0.3
    assert moved.stopped_at is None


def test_replay_with_the_same_configuration_reproduces_every_tick() -> None:
    """Replaying 480 ticks on the same configuration reproduces every decision."""
    config = _config()
    records = _run(config, 480)
    replayed = _replay(config, records)
    assert [r.setpoint for r in replayed] == [r.setpoint for r in records]
    assert [r.pre_round for r in replayed] == [r.pre_round for r in records]
    assert [r.reason for r in replayed] == [r.reason for r in records]
    assert [r.intents for r in replayed] == [r.intents for r in records]


def test_replay_follows_a_restart_onto_a_new_monotonic_axis() -> None:
    """Replay reproduces setpoints across a restart that moved the monotonic clock."""
    config = _config()
    records = _run(config, 300, shift_at=150)
    replayed = _replay(config, records)
    assert [r.setpoint for r in replayed] == [r.setpoint for r in records]


def test_inputs_used_carry_the_pump_duty_and_the_crosscheck_signal() -> None:
    """A record's inputs_used lists the pump duty and the cross-check signal."""
    records = _run(_config(), 3)
    signals = {ref.signal for ref in records[-1].inputs_used}
    assert HeishaSignal.MAX_PUMP_DUTY in signals
    assert HeishaSignal.INLET_TEMP in signals


def test_a_shifted_curve_moves_the_curve_term_by_the_shift() -> None:
    """Replaying with a curve raised by 1 K raises the curve term by exactly 1 K in every tick."""
    config = _config()
    records = _run(config, 120)
    shifted = HeatingCurve.of(*((p.outside_c, p.water_c + 1.0) for p in config.curve.points))
    candidate = _replay(replace(config, curve=shifted), records)
    for original, moved in zip(records, candidate, strict=True):
        before = original.term("curve")
        after = moved.term("curve")
        if before is None or after is None:
            assert before is None
            assert after is None
            continue
        assert math.isclose(after.value, before.value + 1.0, abs_tol=1e-9)


def test_a_different_room_signal_drops_the_room_input() -> None:
    """Replaying with another room signal drops the room input; the same signal keeps it."""
    config = _config()
    record = _run(config, 2)[-1]
    inputs = replay_inputs(record, room_signal="ha/sensor.other", room_profile=config.room)
    assert inputs.room is None
    same = replay_inputs(record, room_signal=ROOM_SIGNAL, room_profile=config.room)
    assert same.room is not None
    assert same.room.quantum_k == config.room.quantum_k

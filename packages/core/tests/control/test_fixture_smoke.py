"""Drive the controller with snapshots from a two-hour capture slice at 60 s ticks.

Open loop (the pump followed whatever controlled it when the slice was made, not this
controller with this configuration), so this checks robustness on the data's quirks and
plausibility, not outcomes. The slices: the committed synthetic one (the simulated
board under ovenbird's own closed loop) and, where present locally, a slice of the live
recording.
"""

from __future__ import annotations

import gzip
import json
from collections import Counter
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

import pytest

from ovenbird_core.capture import CaptureRecord, parse_capture_line, replay_results
from ovenbird_core.control import (
    DecisionRecord,
    EmitterType,
    LadderLevel,
    OvenbirdConfig,
    OvenbirdController,
    OvenbirdState,
    StepResult,
    control_inputs,
)
from ovenbird_core.heishamon import Heartbeat
from ovenbird_core.inputs import InputRouter, MqttSignal
from ovenbird_core.instant import Instant
from ovenbird_core.store import StateStore

ROOM_TOPIC = "climate_manager_capture/room_temp"
ROOM_SIGNAL = "room_temperature"
ROUTER = InputRouter(mqtt_signals={ROOM_TOPIC: MqttSignal(ROOM_SIGNAL, "°C", -10, 45)})
TICK_S = 60.0
MAX_CHANGES_PER_HOUR = 6


def records(path: Path) -> list[CaptureRecord]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [r for r in (parse_capture_line(line) for line in fh) if r is not None]


@dataclass
class Replay:
    config: OvenbirdConfig
    results: list[StepResult[OvenbirdState]]

    @property
    def decisions(self) -> list[DecisionRecord]:
        return [r.decision for r in self.results]

    def setpoints(self) -> list[int]:
        return [d.setpoint for d in self.decisions if d.setpoint is not None]

    def changes(self) -> int:
        values = self.setpoints()
        return sum(1 for a, b in pairwise(values) if a != b)

    def hours(self) -> float:
        return len(self.results) * TICK_S / 3600.0


def replay(controller: OvenbirdController, path: Path) -> Replay:
    recs = records(path)
    store = StateStore()
    state = controller.initial_state()
    results: list[StepResult[OvenbirdState]] = []
    next_tick: float | None = None
    for record, item in zip(recs, replay_results(recs, ROUTER), strict=True):
        while next_tick is not None and next_tick < record.t:
            snapshot = store.snapshot(Instant.from_unix(next_tick))
            result = controller.step(state, control_inputs(snapshot, room_signal=ROOM_SIGNAL))
            results.append(result)
            state = result.state
            next_tick += TICK_S
        if next_tick is None and isinstance(item, Heartbeat) and not item.retained:
            next_tick = record.t + 1.0
        store.apply(item)
    return Replay(controller.config, results)


@pytest.fixture(scope="module", params=list(EmitterType), ids=str)
def run(request: pytest.FixtureRequest, capture_slice: Path) -> Replay:
    return replay(OvenbirdController(OvenbirdConfig.preset(request.param)), capture_slice)


def test_runs_for_two_hours(run: Replay) -> None:
    assert len(run.results) >= 115


def test_setpoints_are_plausible(run: Replay) -> None:
    values = run.setpoints()
    assert len(values) >= 110
    assert all(20 <= v <= run.config.safety.max_supply_c for v in values)
    if run.config.emitter is not EmitterType.RADIATORS:
        assert all(20 <= v <= 40 for v in values)


def test_setpoint_changes_are_bounded(run: Replay) -> None:
    assert run.changes() <= MAX_CHANGES_PER_HOUR * run.hours()


def test_degradation_ladder_follows_the_data(run: Replay) -> None:
    ladders = Counter(d.ladder for d in run.decisions)
    assert ladders[LadderLevel.REFUSE] <= 3
    assert ladders[LadderLevel.SCHEDULE_CURVE_FEEDBACK] >= 10
    assert ladders[LadderLevel.CURVE_ONLY] >= 60
    assert run.decisions[0].ladder is LadderLevel.REFUSE


def test_every_record_serialises(run: Replay) -> None:
    for decision in run.decisions:
        text = json.dumps(decision.to_json_dict(), allow_nan=False)
        assert DecisionRecord.from_json_dict(json.loads(text)) == decision
        assert decision.note


def test_mixed_preset_engages_ramp_and_cycling_protection(capture_slice: Path) -> None:
    result = replay(OvenbirdController(OvenbirdConfig.preset("mixed")), capture_slice)
    bindings = Counter(d.binding for d in result.decisions)
    assert bindings["start_ramp"] >= 1
    if capture_slice.parent.name != "synthetic":
        assert bindings["cycling_floor"] >= 1
    assert min(result.setpoints()) >= 28
    assert max(result.setpoints()) <= 38

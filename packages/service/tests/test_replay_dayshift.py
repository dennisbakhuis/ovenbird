"""Replay of a day with the sun day shift on: the rule slice is rebuilt from the record."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest

from ovenbird.config import Settings
from ovenbird.control.dayshift import recorded_slice
from ovenbird.replay.stepping import step_tick
from ovenbird_core.control import (
    DecisionRecord,
    LadderLevel,
    OvenbirdConfig,
    OvenbirdController,
    PlanSlice,
    PlanSource,
    ReasonCode,
)
from ovenbird_core.control.synthetic import ROOM_SIGNAL, PlantView, synthetic_inputs
from ovenbird_core.instant import Instant

T0 = 1_794_528_000.0
MINUTE = 60.0
COMFORT = 21.0


def _slice(offset: float, start: float, source: PlanSource = PlanSource.RULE) -> PlanSlice:
    """Return a slice of ``offset`` valid for an hour from ``start``."""
    reason = ReasonCode.PLAN_PREHEAT if offset > 0 else ReasonCode.PLAN_SETBACK
    begin = Instant.from_unix(T0 + start)
    return PlanSlice(offset, reason, begin, begin.shifted(3600.0), source)


def _plant(minute: int) -> PlantView:
    """Return a plant whose room and outside drift slowly through the run."""
    return PlantView(
        outside=6.0 + (minute // 90),
        room=20.6 + 0.1 * ((minute // 40) % 5),
        compressor_hz=35 if (minute // 50) % 2 == 0 else 0,
        outlet=32.0,
    )


def _record(
    controller: OvenbirdController, plans: dict[int, PlanSlice], minutes: int, room: bool
) -> list[DecisionRecord]:
    """Run ``controller`` once a minute with the slices of ``plans`` (by start minute)."""
    state = controller.initial_state()
    records: list[DecisionRecord] = []
    plan: PlanSlice | None = None
    for minute in range(minutes):
        plan = plans.get(minute, plan)
        now = Instant.from_unix(T0 + minute * MINUTE)
        inputs = synthetic_inputs(
            now, _plant(minute), plan=plan, room_signal=ROOM_SIGNAL if room else None
        )
        result = controller.step(state, inputs)
        state = result.state
        records.append(result.decision)
    return records


@pytest.fixture
def config() -> OvenbirdConfig:
    """Return the mixed preset at the test comfort target."""
    return OvenbirdConfig.preset("mixed", comfort_room_c=COMFORT)


@pytest.mark.parametrize("room", [True, False])
def test_an_on_day_replays_to_its_recorded_setpoints(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    config: OvenbirdConfig,
    room: bool,
) -> None:
    """Replaying an ``on`` day reproduces it; without the rebuilt slice it does not."""
    monkeypatch.setenv("OVENBIRD_HA_URL", "https://ha.example")
    monkeypatch.setenv("OVENBIRD_HA_TOKEN", "t")
    settings = make_settings(control_room_signal=ROOM_SIGNAL)
    controller = OvenbirdController(config)
    plans = {30: _slice(0.75, 30 * MINUTE), 200: _slice(-1.0, 200 * MINUTE)}
    records = _record(controller, plans, 330, room)
    assert any(r.ladder is LadderLevel.RULE_PLAN for r in records)
    state = controller.initial_state()
    replayed: list[int | None] = []
    for record in records:
        state, decision = step_tick(controller, state, record, settings)
        replayed.append(decision.setpoint)
    assert replayed == [r.setpoint for r in records]
    plain = controller.initial_state()
    without: list[int | None] = []
    for record in records:
        plain, decision = _step_without_slice(controller, plain, record, settings)
        without.append(decision.setpoint)
    assert without != [r.setpoint for r in records]


def _step_without_slice(
    controller: OvenbirdController, state: Any, record: DecisionRecord, settings: Settings
) -> tuple[Any, DecisionRecord]:
    """Step like the replay did before it rebuilt slices: a record that hides its ladder."""
    hidden = replace(record, ladder=LadderLevel.SCHEDULE_CURVE_FEEDBACK)
    return step_tick(controller, state, hidden, settings)


def test_the_rebuilt_slice_is_the_applied_offset(config: OvenbirdConfig) -> None:
    """The rebuilt offset is the bounded, applied one, against the recorded comfort."""
    controller = OvenbirdController(config)
    records = _record(controller, {0: _slice(2.0, 0.0)}, 5, room=True)
    rebuilt = recorded_slice(records[-1], config)
    assert rebuilt is not None
    assert rebuilt.room_offset_k == config.plan_rule_max_k
    assert rebuilt.source is PlanSource.RULE
    assert rebuilt.active(records[-1].at)
    shifted = replace(config, comfort_room_c=COMFORT + 0.5)
    other = recorded_slice(records[-1], shifted)
    assert other is not None
    assert other.room_offset_k == config.plan_rule_max_k - 0.5


def test_ticks_without_an_applied_rule_slice_rebuild_nothing(config: OvenbirdConfig) -> None:
    """Ticks without a slice, or with an optimiser slice, rebuild no rule slice."""
    controller = OvenbirdController(config)
    plain = _record(controller, {}, 3, room=True)
    assert all(recorded_slice(record, config) is None for record in plain)
    optimiser = _record(controller, {0: _slice(0.5, 0.0, PlanSource.OPTIMISER)}, 3, room=True)
    assert all(recorded_slice(record, config) is None for record in optimiser)

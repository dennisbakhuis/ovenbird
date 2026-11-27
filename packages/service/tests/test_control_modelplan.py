"""The model plan in the service: settings, guards, cadence, shadow, on, recording, API, replay."""

from __future__ import annotations

import json
import math
import subprocess
import sys
import textwrap
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ovenbird.api.app import create_app
from ovenbird.clock import ScaledClock
from ovenbird.config import ConfigError, Settings
from ovenbird.config.validation import modelplan as lock
from ovenbird.configstore import Actor, ConfigManager, ConfigRefusedError, provided_sources
from ovenbird.control.alarms import MODEL_PLAN_JOURNAL_CODE
from ovenbird.control.modelplan import (
    APPLIED_SIGNAL,
    OFFSET_SIGNAL,
    PLANNER_ERROR,
    ForecastWindow,
    Guard,
    ModelPlanRunner,
)
from ovenbird.history import HistoryDatabase, Sample, SampleKind, open_history
from ovenbird.history.journal import AlarmRow, DecisionRow, StateRow, write_journal
from ovenbird.insight.whatif import ModelChoice
from ovenbird.mqtt import MqttIngest
from ovenbird.replay.stepping import IdentityStepper, parse_row, recorded_model_plan
from ovenbird.runtime import Runtime
from ovenbird.service import build_control
from ovenbird.testing import FakeClock, pump_messages
from ovenbird_core import StateStore, ha_reading
from ovenbird_core.control import LadderLevel, PlanSource
from ovenbird_core.control.planner import ForecastHour
from ovenbird_core.housemodel import HouseModel

T0 = 1_800_000_000.0
ROOM = "sensor.living_room_temperature"
ROOM_ID = f"ha/{ROOM}"
HA: dict[str, Any] = {
    "ha_url": "http://ha.local:8123",
    "ha_token": "token",
    "ha_entities": (ROOM,),
    "control_room_signal": ROOM_ID,
    "control_comfort_c": 21.0,
}
HOUSE = HouseModel(
    c_water=5.0e5,
    c_mass=4.5e6,
    c_air=2.1e7,
    h_water_mass=540.0,
    h_water_air=40.0,
    h_mass_air=450.0,
    h_air_out=145.0,
    solar_aperture_m2=3.5,
    solar_mass_fraction=0.3,
)
HOUR_S = 3600.0


def set_lock(value: bool) -> None:
    vars(lock)["ON_LOCKED"] = value


async def no_sleep(_: float) -> None:
    return None


def sunny(hour_utc: float) -> float:
    local = hour_utc % 24.0
    return 700.0 * math.sin(math.pi * (local - 8.0) / 8.0) if 8.0 < local < 16.0 else 0.0


@dataclass
class Journal:
    alarms: list[AlarmRow]
    states: list[StateRow]
    path: Path | None = None

    def offer_decision(self, row: Any) -> None:
        return None

    def offer_command(self, row: Any) -> None:
        return None

    def offer_alarm(self, row: AlarmRow) -> None:
        self.alarms.append(row)
        if self.path is not None:
            conn = open_history(self.path)
            try:
                write_journal(conn, [], [], [row])
            finally:
                conn.close()

    def offer_state(self, row: StateRow) -> None:
        self.states.append(row)


class Samples:
    def __init__(self) -> None:
        self.items: list[Sample] = []

    def offer(self, sample: Sample) -> None:
        self.items.append(sample)

    def healthy(self) -> bool:
        return True

    def starting(self) -> bool:
        return True

    def of(self, signal: str) -> list[Sample]:
        return [item for item in self.items if item.signal == signal]


class SimClock:
    """A scaled clock stepped by hand: 15 simulated minutes per real second."""

    def __init__(self, start: datetime) -> None:
        self.real = 1000.0
        self.clock = ScaledClock(900.0, start, monotonic=lambda: self.real)

    def __call__(self) -> Any:
        return self.clock()

    def advance(self, seconds: float) -> None:
        self.real += seconds / self.clock.speed


class Rig:
    def __init__(
        self,
        tmp_path: Path,
        make_settings: Callable[..., Settings],
        *,
        use: str = "shadow",
        start: float = T0,
        clock: Any = None,
        real_loaders: bool = False,
        **overrides: Any,
    ) -> None:
        self.tmp = tmp_path
        values = {**HA, "control_model_use": use, **overrides}
        if use == "on":
            set_lock(False)
        self.settings = make_settings(**values)
        self.clock = clock or FakeClock(start)
        self.runtime = Runtime(
            StateStore(self.settings.staleness_policy()), clock=self.clock, ha_enabled=True
        )
        self.ingest = MqttIngest(self.settings, self.runtime)
        self.journal = Journal([], [], self.settings.history_path if real_loaders else None)
        if real_loaders:
            self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.loop, _ = build_control(
            self.settings,
            self.runtime,
            self.journal,  # type: ignore[arg-type]
            sleep=no_sleep,
        )
        self.models = tmp_path / "models"
        self.models.mkdir(parents=True, exist_ok=True)
        self.status_at = datetime.fromtimestamp(start, UTC).isoformat()
        self.champion: ModelChoice | None = ModelChoice(HOUSE, "model", "house-20261101", True, 0.3)
        self.weather = True
        self.issue_age = 1800.0
        self.stove_end: float | None = None
        self.forecast_error: Exception | None = None
        self.samples = Samples()
        self.notified: list[Any] = []
        self.loop.alarms.listeners.append(self.notified.append)
        self.runner = ModelPlanRunner(
            self.settings,
            lambda: self.models,
            weather_enabled=lambda: self.weather,
            sink=self.samples,
            alarms=self.loop.alarms,
        )
        if not real_loaders:
            self.runner.load_champion = lambda _: self.champion
            self.runner.load_forecast = self.forecast
            self.runner.load_stove_end = lambda _path, _now: self.stove_end
        else:
            self.runner.load_champion = lambda _: self.champion
            self.runner.load_forecast = self.forecast
        self.loop.model_plan = self.runner
        self.loop.reconfigure_hooks.append(self.runner.reconfigure)
        self.room: float | None = 20.8
        self.write_status(start)

    def write_status(
        self, now: float, age_h: float = 1.0, interval_h: float | None = 168.0
    ) -> None:
        at = datetime.fromtimestamp(now - age_h * HOUR_S, UTC).isoformat()
        body: dict[str, Any] = {"at": at, "outcome": "promoted"}
        if interval_h is not None:
            body["interval_h"] = interval_h
        (self.models / "status.json").write_text(json.dumps(body), encoding="utf-8")

    def forecast(self, _path: Path, now_ts: float, horizon_h: float) -> ForecastWindow:
        if self.forecast_error is not None:
            raise self.forecast_error
        first = math.floor((now_ts - 27 * HOUR_S) / HOUR_S) * HOUR_S
        last = now_ts + (horizon_h + 3) * HOUR_S
        hours = []
        target = first
        while target <= last:
            hours.append(ForecastHour(target, 3.0, sunny((target % 86_400.0) / HOUR_S)))
            target += HOUR_S
        return ForecastWindow(tuple(hours), now_ts - self.issue_age)

    def tick(self, minutes: int = 1, **pump: str) -> list[DecisionRow]:
        rows = []
        for _ in range(minutes):
            for message in pump_messages(**pump):
                self.ingest.ingest(message)
            if self.room is not None:
                self.runtime.apply(ha_reading(ROOM, f"{self.room:.1f}", instant=self.clock()))
            rows.append(self.loop.tick())
            self.clock.advance(60.0)
        return rows

    def plan_rows(self, rows: list[DecisionRow]) -> list[DecisionRow]:
        return [row for row in rows if row.ladder == LadderLevel.MODEL_PLAN.value]


@pytest.fixture(autouse=True)
def restore_lock() -> Any:
    before = lock.ON_LOCKED
    yield
    set_lock(before)


@pytest.fixture
def rig(tmp_path: Path, make_settings: Callable[..., Settings]) -> Callable[..., Rig]:
    def build(**kwargs: Any) -> Rig:
        return Rig(tmp_path, make_settings, **kwargs)

    return build


class TestSettings:
    def test_defaults_and_ranges(self, make_settings: Callable[..., Settings]) -> None:
        settings = make_settings()
        assert settings.control_model_use == "off"
        assert settings.control_model_max_setback_k == 0.5
        assert settings.control_model_max_preheat_k == 0.3
        assert settings.control_model_horizon_h == 6.0
        assert settings.control_model_max_rmse_k == 0.6
        for name, low, high in (
            ("control_model_max_setback_k", 0.1, 1.0),
            ("control_model_max_preheat_k", 0.0, 0.5),
            ("control_model_horizon_h", 2.0, 12.0),
            ("control_model_max_rmse_k", 0.2, 1.5),
        ):
            make_settings(**{name: low})
            make_settings(**{name: high})
            with pytest.raises(ConfigError):
                make_settings(**{name: low - 0.05 if low else -0.1})
            with pytest.raises(ConfigError):
                make_settings(**{name: high + 0.1})

    def test_the_bounds_reach_the_controller_configuration(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        config = make_settings(
            control_model_max_setback_k=0.8, control_model_max_preheat_k=0.1
        ).controller_config()
        assert config.model_plan.max_setback_k == 0.8
        assert config.model_plan.max_preheat_k == 0.1

    def test_on_is_refused_by_load_and_by_validation(
        self, make_settings: Callable[..., Settings], tmp_path: Path
    ) -> None:
        with pytest.raises(ConfigError, match="shadow period"):
            make_settings(control_model_use="on")
        manager = ConfigManager.open(make_settings(), FakeClock(), locked=provided_sources())
        result = manager.validate({"control_model_use": "on"})
        assert not result.valid
        assert [(e.field, e.code) for e in result.errors] == [
            ("control_model_use", "model_use_on_locked")
        ]
        assert manager.validate({"control_model_use": "shadow"}).valid

    def test_on_is_refused_by_apply(self, make_settings: Callable[..., Settings]) -> None:
        clock = FakeClock()
        manager = ConfigManager.open(make_settings(), clock, locked=provided_sources())
        with pytest.raises(ConfigRefusedError) as refused:
            manager.apply(
                manager.version or 0,
                {"control_model_use": "on"},
                Actor("admin from 127.0.0.1", "127.0.0.1"),
                acknowledge=[],
            )
        assert refused.value.status == 422
        assert manager.settings.control_model_use == "off"

    def test_lifting_the_lock_is_the_only_change_for_on(
        self, make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(lock, "ON_LOCKED", False)
        assert make_settings(control_model_use="on").control_model_use == "on"
        manager = ConfigManager.open(make_settings(), FakeClock(), locked=provided_sources())
        assert manager.validate({"control_model_use": "on"}).valid

    def test_changing_the_settings_changes_no_decision_while_off(
        self, tmp_path: Path, make_settings: Callable[..., Settings]
    ) -> None:
        plain = Rig(tmp_path / "a", make_settings, use="off", data_dir=tmp_path / "da")
        other = Rig(
            tmp_path / "b",
            make_settings,
            use="off",
            data_dir=tmp_path / "db",
            control_model_max_setback_k=1.0,
            control_model_max_preheat_k=0.5,
            control_model_horizon_h=12.0,
            control_model_max_rmse_k=1.5,
        )
        left = [row.record for row in plain.tick(90)]
        right = [row.record for row in other.tick(90)]
        assert left == right
        assert plain.runner.calls == other.runner.calls == 0


class TestGuards:
    def blocks(self, rig: Rig) -> tuple[Guard, ...]:
        rig.tick(3)
        return rig.runner._blocks

    def test_nothing_blocks_by_default(self, rig: Callable[..., Rig]) -> None:
        run = rig()
        assert self.blocks(run) == ()
        assert run.runner.evaluation is not None
        assert run.runner.evaluation.status in {"issued", "inside_dead_zone"}

    def test_weather_off(self, rig: Callable[..., Rig]) -> None:
        run = rig()
        run.weather = False
        assert self.blocks(run) == (Guard.WEATHER_OFF,)

    def test_model_missing_skips_the_model_guards(self, rig: Callable[..., Rig]) -> None:
        run = rig()
        run.champion = None
        assert self.blocks(run) == (Guard.MODEL_MISSING,)

    def test_model_not_credible(self, rig: Callable[..., Rig]) -> None:
        run = rig()
        assert run.champion is not None
        run.champion = replace(run.champion, credible=False)
        assert self.blocks(run) == (Guard.MODEL_NOT_CREDIBLE,)

    def test_model_stale(self, rig: Callable[..., Rig]) -> None:
        run = rig()
        run.write_status(T0, age_h=400.0)
        assert self.blocks(run) == (Guard.MODEL_STALE,)

    def test_a_missing_status_counts_as_stale(self, rig: Callable[..., Rig]) -> None:
        run = rig()
        (run.models / "status.json").unlink()
        assert self.blocks(run) == (Guard.MODEL_STALE,)

    def test_the_embedded_learner_interval_sets_the_stale_limit(
        self, rig: Callable[..., Rig]
    ) -> None:
        run = rig(house_learn_interval_h=24.0)
        run.runner.embedded = lambda: True
        run.write_status(T0, age_h=60.0, interval_h=None)
        assert self.blocks(run) == (Guard.MODEL_STALE,)

    @pytest.mark.parametrize("rmse", [None, 0.61, 2.0])
    def test_model_error_high(self, rig: Callable[..., Rig], rmse: float | None) -> None:
        run = rig()
        assert run.champion is not None
        run.champion = replace(run.champion, rmse_k=rmse)
        assert self.blocks(run) == (Guard.MODEL_ERROR_HIGH,)

    def test_the_error_limit_is_a_setting(self, rig: Callable[..., Rig]) -> None:
        run = rig(control_model_max_rmse_k=1.0)
        assert run.champion is not None
        run.champion = replace(run.champion, rmse_k=0.9)
        assert self.blocks(run) == ()

    def test_forecast_stale(self, rig: Callable[..., Rig]) -> None:
        run = rig()
        run.issue_age = 3 * HOUR_S + 60.0
        assert self.blocks(run) == (Guard.FORECAST_STALE,)

    def test_room_untrusted(self, rig: Callable[..., Rig]) -> None:
        run = rig()
        run.room = None
        assert self.blocks(run) == (Guard.ROOM_UNTRUSTED,)

    def test_stove_active_and_tail(self, rig: Callable[..., Rig]) -> None:
        run = rig(control_stove_enabled=True)
        run.tick(3)
        run.loop.request_stove(True, None, "test")
        run.tick(2)
        assert Guard.STOVE_ACTIVE in run.runner._blocks
        run.loop.request_stove(False, None, "test")
        run.tick(3)
        assert Guard.STOVE_ACTIVE not in run.runner._blocks
        assert Guard.STOVE_TAIL in run.runner._blocks
        run.clock.advance(12 * HOUR_S)
        run.tick(2)
        assert Guard.STOVE_TAIL not in run.runner._blocks

    def test_the_stove_tail_survives_a_restart(self, rig: Callable[..., Rig]) -> None:
        first = rig(real_loaders=True, control_stove_enabled=True)
        first.tick(3)
        first.loop.request_stove(True, None, "test")
        first.tick(3)
        first.loop.request_stove(False, None, "test")
        first.tick(3)
        assert [row.event for row in first.journal.alarms if row.code == "stove_mode"] == [
            "started",
            "released",
        ]
        first.clock.advance(3600.0)
        runner = ModelPlanRunner(
            first.settings,
            lambda: first.models,
            weather_enabled=lambda: True,
            load_champion=lambda _: first.champion,
            load_forecast=first.forecast,
        )
        facts = runner.read_facts(first.clock().wall)
        assert facts.stove_end is not None
        runner._stove_end = facts.stove_end
        ctx = first.loop.live_plan_context()
        assert Guard.STOVE_TAIL in runner.blocks_for(facts, ctx)
        first.clock.advance(12 * HOUR_S)
        later = first.loop.live_plan_context()
        assert Guard.STOVE_TAIL not in runner.live_blocks(later)

    def test_every_guard_is_reported_in_the_fixed_order(self, rig: Callable[..., Rig]) -> None:
        run = rig(control_stove_enabled=True)
        run.weather = False
        run.issue_age = 5 * HOUR_S
        run.write_status(T0, age_h=500.0)
        assert run.champion is not None
        run.champion = replace(run.champion, credible=False, rmse_k=1.0)
        run.room = None
        run.stove_end = T0 - 3600.0
        run.tick(3)
        assert run.runner._blocks == (
            Guard.WEATHER_OFF,
            Guard.MODEL_NOT_CREDIBLE,
            Guard.MODEL_STALE,
            Guard.MODEL_ERROR_HIGH,
            Guard.FORECAST_STALE,
            Guard.ROOM_UNTRUSTED,
            Guard.STOVE_TAIL,
        )

    def test_weather_compensation_off_needs_no_guard(self, rig: Callable[..., Rig]) -> None:
        run = rig(control_weather_compensation=False)
        assert self.blocks(run) == ()


class TestCadence:
    def evaluations(self, run: Rig, minutes: int) -> list[datetime]:
        seen: list[datetime] = []
        for _ in range(minutes):
            run.tick()
            evaluation = run.runner.evaluation
            if evaluation is not None and (not seen or evaluation.at.wall != seen[-1]):
                seen.append(evaluation.at.wall)
        return seen

    def test_once_per_wall_clock_quarter_hour(self, rig: Callable[..., Rig]) -> None:
        run = rig(start=T0 + 7 * 60)
        seen = self.evaluations(run, 125)
        assert run.runner.calls == len(seen)
        assert seen[0].minute == 8 or seen[0].minute == 7 or seen[0].minute == 9
        assert [moment.minute for moment in seen[1:]] == [(15 * k) % 60 for k in range(1, 9)][
            : len(seen) - 1
        ]
        assert len(seen) == 9

    def test_the_simulated_clock_follows_its_own_quarter_hours(
        self, tmp_path: Path, make_settings: Callable[..., Settings]
    ) -> None:
        clock = SimClock(datetime.fromtimestamp(T0, UTC))
        run = Rig(tmp_path, make_settings, clock=clock)
        seen = self.evaluations(run, 125)
        assert len(seen) == 9
        assert {moment.minute for moment in seen[1:]} <= {0, 15, 30, 45}
        assert run.clock().wall.timestamp() == pytest.approx(T0 + 125 * 60)

    def test_no_call_while_off(self, rig: Callable[..., Rig]) -> None:
        run = rig(use="off")
        run.tick(60)
        assert run.runner.calls == 0
        assert run.runner.evaluation is None
        assert run.samples.items == []


class TestShadow:
    def test_decisions_equal_those_of_off(
        self, tmp_path: Path, make_settings: Callable[..., Settings]
    ) -> None:
        off = Rig(tmp_path / "a", make_settings, use="off", data_dir=tmp_path / "da")
        shadow = Rig(tmp_path / "b", make_settings, use="shadow", data_dir=tmp_path / "db")
        left = [row.record for row in off.tick(240)]
        right = [row.record for row in shadow.tick(240)]
        assert left == right
        assert off.runner.calls == 0
        assert shadow.runner.calls >= 15
        evaluation = shadow.runner.evaluation
        assert evaluation is not None
        assert any(sample.value not in (None, 0.0) for sample in shadow.samples.of(OFFSET_SIGNAL))
        assert all(sample.value == 0.0 for sample in shadow.samples.of(APPLIED_SIGNAL))
        assert all('"model_plan' not in record for record in right)

    def test_the_plan_is_computed_but_never_passed(self, rig: Callable[..., Rig]) -> None:
        run = rig(use="shadow")
        rows = run.tick(120)
        assert run.runner.calls > 0
        assert run.runner._slice is not None or run.runner._issued is not None
        assert run.plan_rows(rows) == []
        assert run.runner.applied is False


class TestOn:
    def test_the_slice_reaches_the_controller(self, rig: Callable[..., Rig]) -> None:
        run = rig(use="on")
        rows = run.tick(120)
        planned = run.plan_rows(rows)
        assert planned
        record = json.loads(planned[-1].record)
        state = record["controller_state"]
        assert state["model_plan_requested_k"] < 0.0
        assert state["model_plan_applied_k"] == state["model_plan_requested_k"]
        assert state["model_plan_ignored"] is None
        assert record["ladder"] == "model_plan"
        assert record["reason"] in {"plan_setback", "plan_preheat"}
        assert run.runner.applied
        assert any(sample.value == 1.0 for sample in run.samples.of(APPLIED_SIGNAL))

    def test_the_offset_ramps_by_the_rate_limit_across_calls(self, rig: Callable[..., Rig]) -> None:
        run = rig(use="on")
        offsets: list[float] = []
        for _ in range(100):
            run.tick()
            evaluation = run.runner.evaluation
            if evaluation is not None and (not offsets or evaluation.offset_k != offsets[-1]):
                offsets.append(evaluation.offset_k)
        assert offsets[0] in (-0.1, 0.0)
        steps = [round(abs(b - a), 6) for a, b in pairwise(offsets)]
        assert steps
        assert max(steps) <= 0.1 + 1e-9

    def test_it_is_withdrawn_at_once_when_the_room_goes_untrusted(
        self, rig: Callable[..., Rig]
    ) -> None:
        run = rig(use="on")
        run.tick(90)
        assert run.runner._offered is not None
        run.room = None
        withdrawn = None
        for _ in range(120):
            row = run.tick()[0]
            if Guard.ROOM_UNTRUSTED in run.runner._blocks:
                withdrawn = row
                break
        assert withdrawn is not None
        assert withdrawn.ladder != LadderLevel.MODEL_PLAN.value
        assert run.runner._offered is None
        offsets = run.samples.of(OFFSET_SIGNAL)
        assert offsets[-1].value is None

    def test_it_is_withdrawn_at_once_when_a_stove_episode_starts(
        self, rig: Callable[..., Rig]
    ) -> None:
        run = rig(use="on", control_stove_enabled=True)
        run.tick(90)
        assert run.runner._offered is not None
        run.loop.request_stove(True, None, "test")
        rows = run.tick(3)
        assert all(row.ladder != LadderLevel.MODEL_PLAN.value for row in rows[1:])
        assert Guard.STOVE_ACTIVE in run.runner._blocks

    def test_it_is_withdrawn_when_the_switch_changes(
        self, rig: Callable[..., Rig], make_settings: Callable[..., Settings]
    ) -> None:
        run = rig(use="on")
        run.tick(80)
        assert run.runner._offered is not None
        run.loop.reconfigure(replace_use(run, "shadow"), 2)
        rows = run.tick(2)
        assert all(row.ladder != LadderLevel.MODEL_PLAN.value for row in rows)
        assert run.runner._slice is None
        assert run.runner.use == "shadow"

    def test_a_changed_configuration_withdraws_the_slice_until_the_next_call(
        self, rig: Callable[..., Rig]
    ) -> None:
        run = rig(use="on")
        run.tick(80)
        assert run.runner._offered is not None
        calls = run.runner.calls
        run.loop.reconfigure(replace_bounds(run), 2)
        row = run.tick()[0]
        assert row.ladder != LadderLevel.MODEL_PLAN.value
        assert run.runner.calls == calls
        run.tick(16)
        assert run.runner.calls == calls + 1

    def test_no_plan_after_the_planner_stops(self, rig: Callable[..., Rig]) -> None:
        run = rig(use="on")
        run.tick(90)
        assert run.runner._offered is not None
        run.champion = None
        rows = run.tick(20)
        assert run.plan_rows(rows[-3:]) == []
        assert run.runner._issued is None

    def test_after_a_block_the_offset_ramps_from_zero(self, rig: Callable[..., Rig]) -> None:
        run = rig(use="on")
        run.tick(90)
        before = run.runner.evaluation
        assert before is not None
        run.weather = False
        run.tick(46)
        run.weather = True
        run.tick(16)
        after = run.runner.evaluation
        assert after is not None
        assert after.result is not None
        assert after.result.previous_offset_k == 0.0
        assert abs(after.offset_k) <= 0.1 + 1e-9

    def test_the_lock_demotes_on_to_shadow(self, rig: Callable[..., Rig]) -> None:
        run = rig(use="on")
        set_lock(True)
        assert run.runner.use == "shadow"
        rows = run.tick(120)
        assert run.plan_rows(rows) == []


def replace_use(run: Rig, use: str) -> Settings:
    from ovenbird.config import load_settings

    return load_settings(
        **{
            **HA,
            "control_model_use": use,
            "data_dir": run.settings.data_dir,
            "ui_dir": run.tmp / "ui",
            "http_port": 0,
        }
    )


def replace_bounds(run: Rig) -> Settings:
    from ovenbird.config import load_settings

    return load_settings(
        **{
            **HA,
            "control_model_use": "on",
            "control_model_max_setback_k": 0.4,
            "data_dir": run.settings.data_dir,
            "ui_dir": run.tmp / "ui",
            "http_port": 0,
        }
    )


class TestContainment:
    def test_a_planner_exception_means_no_plan_and_no_failed_tick(
        self, rig: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = rig(use="on")

        def boom(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("planner failed")

        monkeypatch.setattr("ovenbird.control.modelplan.plan_offset", boom)
        rows = run.tick(40)
        assert len(rows) == 40
        assert run.plan_rows(rows) == []
        assert run.runner.evaluation is not None
        assert run.runner.evaluation.status == PLANNER_ERROR
        assert run.runner._slice is None
        assert all(sample.value is None for sample in run.samples.of(OFFSET_SIGNAL)[-5:])

    def test_a_failing_forecast_read_means_no_plan(self, rig: Callable[..., Rig]) -> None:
        run = rig(use="on")
        run.forecast_error = OSError("disk")
        rows = run.tick(40)
        assert run.plan_rows(rows) == []
        assert run.runner.evaluation is not None
        assert run.runner.evaluation.status == PLANNER_ERROR

    def test_a_failing_runner_never_disturbs_the_tick(
        self, rig: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = rig(use="on")

        def boom(*_args: Any) -> Any:
            raise RuntimeError("context failed")

        monkeypatch.setattr(run.loop, "plan_context", boom)
        rows = run.tick(5)
        assert len(rows) == 5
        assert run.plan_rows(rows) == []


class TestRecording:
    def test_nothing_is_written_while_off(self, rig: Callable[..., Rig]) -> None:
        run = rig(use="off")
        run.tick(30)
        assert run.samples.items == []
        assert [a for a in run.journal.alarms if a.code == MODEL_PLAN_JOURNAL_CODE] == []

    def test_both_signals_are_written_every_tick_in_shadow_and_on(
        self, rig: Callable[..., Rig]
    ) -> None:
        for use in ("shadow", "on"):
            run = rig(use=use)
            run.tick(30)
            assert len(run.samples.of(OFFSET_SIGNAL)) == 30
            assert len(run.samples.of(APPLIED_SIGNAL)) == 30
            assert run.samples.of(OFFSET_SIGNAL)[0].unit == "K"

    def test_a_blocked_planner_is_a_gap_and_a_quiet_one_is_zero(
        self, rig: Callable[..., Rig]
    ) -> None:
        run = rig(use="shadow")
        run.tick(5)
        values = [sample.value for sample in run.samples.of(OFFSET_SIGNAL)]
        assert values[-1] is not None
        run.weather = False
        run.tick(16)
        assert run.samples.of(OFFSET_SIGNAL)[-1].value is None

    def test_the_signals_never_reach_the_state_the_controller_reads(
        self, rig: Callable[..., Rig]
    ) -> None:
        run = rig(use="shadow")
        run.tick(30)
        snapshot = run.runtime.store.snapshot(run.clock())
        assert not [name for name in snapshot.signals if name.startswith("derived/")]

    def test_the_verdict_changes_are_journalled_without_notifying(
        self, rig: Callable[..., Rig]
    ) -> None:
        run = rig(use="shadow")
        run.tick(20)
        run.weather = False
        run.tick(40)
        run.weather = True
        run.tick(50)
        rows = [a for a in run.journal.alarms if a.code == MODEL_PLAN_JOURNAL_CODE]
        assert [row.event for row in rows] == ["released", "started", "released"]
        assert {row.severity for row in rows} == {"info"}
        assert json.loads(rows[1].detail)["blocks"] == ["weather_off"]
        assert run.notified == []
        assert run.loop.alarms.active() == ()


def model_plan_rows(run: Rig) -> list[AlarmRow]:
    return [a for a in run.journal.alarms if a.code == MODEL_PLAN_JOURNAL_CODE]


def flap(run: Rig, ticks: int) -> None:
    state = {"n": 0}

    def alternating(_: Any) -> tuple[Guard, ...]:
        state["n"] += 1
        return (Guard.ROOM_UNTRUSTED,) if state["n"] % 2 else ()

    run.runner.live_blocks = alternating  # type: ignore[assignment,method-assign]
    run.tick(ticks)


class TestJournalDebounce:
    def test_flapping_for_an_hour_writes_few_rows_with_flap_counts(
        self, rig: Callable[..., Rig]
    ) -> None:
        run = rig(use="shadow")
        flap(run, 60)
        rows = model_plan_rows(run)
        assert 1 < len(rows) <= 5
        flaps = [json.loads(row.detail)["flaps"] for row in rows]
        assert flaps[0] == 0
        assert all(count > 0 for count in flaps[1:])
        assert sum(flaps) >= 40

    def test_flapping_does_not_displace_alarm_history(self, rig: Callable[..., Rig]) -> None:
        run = rig(use="shadow")
        flap(run, 60)
        assert model_plan_rows(run)
        assert [e for e in run.loop.alarms.history if e.code == MODEL_PLAN_JOURNAL_CODE] == []

    def test_a_stable_change_is_written_once(self, rig: Callable[..., Rig]) -> None:
        run = rig(use="shadow")
        run.tick(20)
        run.weather = False
        run.tick(120)
        events = [(row.event, json.loads(row.detail)["flaps"]) for row in model_plan_rows(run)]
        assert events == [("released", 0), ("started", 0)]

    def test_a_restart_with_the_same_verdict_writes_nothing(self, rig: Callable[..., Rig]) -> None:
        run = rig(use="shadow", real_loaders=True)
        run.tick(20)
        before = len(model_plan_rows(run))
        assert before == 1
        again = ModelPlanRunner(
            run.settings,
            lambda: run.models,
            weather_enabled=lambda: True,
            sink=run.samples,
            alarms=run.loop.alarms,
            load_champion=lambda _: run.champion,
            load_forecast=run.forecast,
        )
        run.loop.model_plan = again
        run.tick(40)
        assert len(model_plan_rows(run)) == before


class TestStoveTailAfterDowntime:
    def restarted(self, run: Rig, *, active: bool = False) -> ModelPlanRunner:
        runner = ModelPlanRunner(
            run.settings,
            lambda: run.models,
            weather_enabled=lambda: True,
            sink=run.samples,
            alarms=run.loop.alarms,
            load_champion=lambda _: run.champion,
            load_forecast=run.forecast,
        )
        runner.step(replace(run.loop.live_plan_context(), stove_active=active))
        return runner

    def stove_rows(self, run: Rig) -> list[AlarmRow]:
        return [row for row in run.journal.alarms if row.code == "stove_mode"]

    def episode(self, rig: Callable[..., Rig]) -> Rig:
        run = rig(real_loaders=True, control_stove_enabled=True)
        run.tick(3)
        run.loop.request_stove(True, None, "test")
        run.tick(3)
        assert [row.event for row in self.stove_rows(run)] == ["started"]
        return run

    def test_a_long_restart_during_an_episode_gives_a_tail(self, rig: Callable[..., Rig]) -> None:
        run = self.episode(rig)
        run.clock.advance(3600.0)
        runner = self.restarted(run)
        rows = self.stove_rows(run)
        assert [row.event for row in rows] == ["started", "expired"]
        assert json.loads(rows[1].detail) == {"exit": "service_restart"}
        assert Guard.STOVE_TAIL in runner._blocks
        assert runner._stove_end == rows[1].ts

    def test_a_second_restart_keeps_the_same_tail(self, rig: Callable[..., Rig]) -> None:
        run = self.episode(rig)
        run.clock.advance(3600.0)
        first = self.restarted(run)
        closed = self.stove_rows(run)[1].ts
        run.clock.advance(3600.0)
        second = self.restarted(run)
        rows = self.stove_rows(run)
        assert [row.event for row in rows] == ["started", "expired"]
        assert first._stove_end == closed
        assert second._stove_end == closed
        assert Guard.STOVE_TAIL in second._blocks

    def test_a_short_restart_with_the_episode_restored_writes_nothing(
        self, rig: Callable[..., Rig]
    ) -> None:
        run = self.episode(rig)
        run.clock.advance(300.0)
        runner = self.restarted(run, active=True)
        assert [row.event for row in self.stove_rows(run)] == ["started"]
        assert Guard.STOVE_ACTIVE in runner._blocks


class TestApi:
    def client(self, run: Rig) -> TestClient:
        return TestClient(create_app(run.runtime, run.settings, control=run.loop))

    def test_off_reports_the_guards_without_an_evaluation(self, rig: Callable[..., Rig]) -> None:
        run = rig(use="off")
        run.weather = False
        run.tick(3)
        body = self.client(run).get("/api/v1/insight/house/control").json()
        assert body["use"] == "off"
        assert body["now"] is None
        assert body["history"]["points"] == []
        assert body["history"]["step_s"] == 900
        assert body["bounds"] == {
            "max_setback_k": 0.5,
            "max_preheat_k": 0.3,
            "horizon_h": 6.0,
            "max_rmse_k": 0.6,
        }
        assert "weather_off" in body["verdict"]["blocks"]
        assert body["verdict"]["ok"] is False

    def test_shadow_reports_the_latest_evaluation_and_history(
        self, rig: Callable[..., Rig]
    ) -> None:
        run = rig(use="shadow")
        run.tick(150)
        run.settings.data_dir.mkdir(parents=True, exist_ok=True)
        database = HistoryDatabase(open_history(run.settings.history_path))
        now = run.clock().wall.timestamp()
        samples = []
        ts = now - 3600.0
        while ts < now:
            samples.append(
                Sample(
                    OFFSET_SIGNAL,
                    "K",
                    SampleKind.NUMBER,
                    ts,
                    -0.2 if ts < now - 1800 else None,
                    120.0,
                )
            )
            samples.append(Sample(APPLIED_SIGNAL, "1", SampleKind.NUMBER, ts, 0.0, 120.0))
            ts += 60.0
        database.write_batch(samples)
        database.close()
        body = self.client(run).get("/api/v1/insight/house/control").json()
        assert body["use"] == "shadow"
        assert body["model"] == "house-20261101"
        assert body["model_rmse_k"] == 0.3
        assert set(body["now"]) == {
            "at",
            "status",
            "offset_k",
            "applied",
            "reason",
            "valid_until",
            "rise_k",
            "rise_at",
            "fall_k",
            "fall_at",
            "solar_k",
            "outside_k",
        }
        assert body["now"]["status"] in {"issued", "inside_dead_zone", "crossing_zero"}
        assert body["now"]["applied"] is False
        history = body["history"]
        assert set(history) == {"step_s", "from", "to", "points"}
        assert history["points"]
        stamp, offset, applied = history["points"][-5]
        assert stamp.endswith("Z")
        assert offset in (None, -0.2)
        assert applied in (None, 0)
        assert len(history["points"]) == 7 * 96 + 1 or len(history["points"]) >= 7 * 96


class TestReplay:
    def test_a_decision_with_a_model_plan_is_reproduced(self, rig: Callable[..., Rig]) -> None:
        run = rig(use="on")
        rows = run.tick(150)
        planned = run.plan_rows(rows)
        assert planned
        ticks = [parse_row(row) for row in rows]
        assert all(tick is not None for tick in ticks)
        record = ticks[rows.index(planned[-1])]
        assert record is not None
        slice_ = recorded_model_plan(record.record)
        assert slice_ is not None
        assert slice_.source is PlanSource.MODEL
        assert slice_.room_offset_k == record.record.controller_state["model_plan_requested_k"]
        config = run.loop.controller.config
        stepper = IdentityStepper(None, lambda _v: run.settings, lambda _v: config)
        outcomes = [stepper.feed(tick) for tick in ticks if tick is not None]
        assert None not in outcomes
        assert stepper.result().mismatches == 0
        assert stepper.result().ticks == len(rows)

    def test_a_record_without_a_model_plan_gets_none(self, rig: Callable[..., Rig]) -> None:
        run = rig(use="shadow")
        rows = run.tick(10)
        tick = parse_row(rows[-1])
        assert tick is not None
        assert recorded_model_plan(tick.record) is None


def test_the_service_modules_load_without_numpy_or_scipy() -> None:
    code = textwrap.dedent(
        """
        import sys
        import ovenbird.control.modelplan
        import ovenbird.service
        import ovenbird_core.control.planner
        loaded = [m for m in ("numpy", "scipy") if m in sys.modules]
        assert not loaded, loaded
        """
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=False, timeout=120
    )
    assert result.returncode == 0, result.stderr

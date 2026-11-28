"""The sun day shift in the service: switch, acknowledgement, cadence, slices, restart, API."""

from __future__ import annotations

import base64
import json
import math
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from ovenbird.api.app import create_app
from ovenbird.api.models.control import DayShift
from ovenbird.config import ConfigError, Settings
from ovenbird.config.validation.issues import control_issues
from ovenbird.configstore import ConfigManager
from ovenbird.control.dayshift import SLICE_VALID_S, Phase
from ovenbird.control.dayshiftrun import (
    JOURNAL_CODE,
    MEMORY_KEY,
    OFFSET_SIGNAL,
    SHADOW_SIGNAL,
    DayShiftRunner,
    JournalEvent,
    load_memory,
    transitions,
)
from ovenbird.control.forecastread import ForecastWindow, PlanContext
from ovenbird.control.monitors import monitor_config
from ovenbird.history import Sample, open_history
from ovenbird.history.journal import AlarmRow, DecisionRow, StateRow, write_journal
from ovenbird.mqtt import MqttIngest
from ovenbird.runtime import Runtime
from ovenbird.service import build_control
from ovenbird.testing import FakeClock, inbound, pump_messages
from ovenbird_core.control import DecisionRecord, LadderLevel, PlanSlice, PlanSource, ReasonCode
from ovenbird_core.control.forecast import HOUR_S, ForecastHour

ROOM = "room_temperature"
WARM_ROOM = 21.6
BASE: dict[str, Any] = {
    "control_room_signal": ROOM,
    "mqtt_inputs": [{"topic": "sim/room", "signal": ROOM, "unit": "°C"}],
    "control_comfort_c": 21.0,
    "control_timezone": "UTC",
}
ON: dict[str, Any] = {"use": "on", "control_dayshift_experimental_ok": True}
MORNING = datetime(2026, 3, 10, 8, 45, tzinfo=UTC).timestamp()
ADMIN = base64.b64encode(b"admin:pw-123").decode()


async def no_sleep(_: float) -> None:
    """Return at once (the loops here are ticked by hand)."""


def sunny_hours(
    now_ts: float, *, peak: float = 500.0, night_c: float = 6.0
) -> tuple[ForecastHour, ...]:
    """Return stored-forecast hours around ``now_ts``: mild sunny days, cool nights."""
    first = math.floor((now_ts - 26 * HOUR_S) / HOUR_S) * HOUR_S
    hours = []
    for index in range(60):
        ts = first + index * HOUR_S
        hour = (ts % 86_400.0) / HOUR_S
        mid = hour - 0.5
        sun = peak * math.sin(math.pi * (mid - 7.0) / 10.0) if 7.0 < mid < 17.0 else 0.0
        hours.append(ForecastHour(ts, 8.0 if 7.0 <= hour < 20.0 else night_c, sun))
    return tuple(hours)


class Journal:
    """A history writer stand-in: keeps every row, stores alarms and states in the database."""

    def __init__(self, path: Path) -> None:
        """Create empty row lists for the history database at the given path."""
        self.path = path
        self.decisions: list[DecisionRow] = []
        self.alarms: list[AlarmRow] = []
        self.states: list[StateRow] = []
        self.samples: list[Sample] = []

    def offer(self, sample: Sample) -> None:
        """Keep a sample."""
        self.samples.append(sample)

    def offer_decision(self, row: DecisionRow) -> None:
        """Keep a decision row."""
        self.decisions.append(row)

    def offer_command(self, row: Any) -> None:
        """Ignore a command row."""

    def offer_alarm(self, row: AlarmRow) -> None:
        """Keep and store an alarm row."""
        self.alarms.append(row)
        self._store(alarms=[row])

    def offer_state(self, row: StateRow) -> None:
        """Keep and store a state row."""
        self.states.append(row)
        self._store(states=[row])

    def _store(
        self, *, alarms: list[AlarmRow] | None = None, states: list[StateRow] | None = None
    ) -> None:
        """Write rows to the history database."""
        conn = open_history(self.path)
        try:
            write_journal(conn, [], [], alarms or [], states or [])
        finally:
            conn.close()

    def of(self, signal: str) -> list[float | None]:
        """Return the values of one derived signal."""
        return [sample.value for sample in self.samples if sample.signal == signal]

    def events(self) -> list[str]:
        """Return the day shift journal events in order."""
        return [json.loads(row.detail)["event"] for row in self.alarms if row.code == JOURNAL_CODE]


class Rig:
    """A control loop built like the service's, ticked by hand on a fake clock."""

    def __init__(
        self,
        make_settings: Callable[..., Settings],
        data_dir: Path,
        *,
        use: str = "shadow",
        start: float = MORNING,
        **overrides: Any,
    ) -> None:
        """Build a control loop with the day shift runner on a fake clock and settings overrides."""
        values = {**BASE, "data_dir": data_dir, "control_dayshift_use": use, **overrides}
        self.settings = make_settings(**values)
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.clock = FakeClock(start)
        self.runtime = Runtime(clock=self.clock)
        self.journal = Journal(self.settings.history_path)
        self.loop, _ = build_control(
            self.settings,
            self.runtime,
            self.journal,  # type: ignore[arg-type]
            sleep=no_sleep,
        )
        runner = self.loop.dayshift
        assert runner is not None
        self.runner = runner
        self.runner.load_forecast = self.forecast
        self.ingest = MqttIngest(self.settings, self.runtime)
        self.room = 21.0
        self.issue_age = 1800.0
        self.peak = 500.0
        self.night_c = 6.0
        self.reads = 0

    def forecast(self, _path: Path, now_ts: float, _horizon_h: float) -> ForecastWindow:
        """Return the forecast the weather component would have stored."""
        self.reads += 1
        hours = sunny_hours(now_ts, peak=self.peak, night_c=self.night_c)
        return ForecastWindow(hours, now_ts - self.issue_age)

    def tick(self, minutes: int = 1) -> list[DecisionRow]:
        """Feed the pump and the room, tick once a minute and return the decisions."""
        rows = []
        for _ in range(minutes):
            for message in pump_messages(Outside_Temp="8"):
                self.ingest.ingest(message)
            self.ingest.ingest(inbound("sim/room", f"{self.room:.1f}"))
            rows.append(self.loop.tick())
            self.clock.advance(60.0)
        return rows

    def until(self, hour: float) -> list[DecisionRow]:
        """Tick to ``hour`` o'clock UTC (the next day when it has passed)."""
        now = self.clock.t
        target = math.floor(now / 86_400.0) * 86_400.0 + hour * HOUR_S
        if target <= now:
            target += 86_400.0
        return self.tick(round((target - now) / 60.0))

    def warm_evening(self, hour: float) -> list[DecisionRow]:
        """Tick to 18:00 at comfort, then to ``hour`` with the room the sun left warm."""
        rows = self.until(18)
        self.room = WARM_ROOM
        return rows + self.until(hour)


def target_offsets(rows: list[DecisionRow]) -> list[float]:
    """Return the room target minus comfort of each decision."""
    return [
        round(json.loads(row.record)["controller_state"]["room_target_c"] - 21.0, 4) for row in rows
    ]


@pytest.fixture
def rig(make_settings: Callable[..., Settings], tmp_path: Path) -> Callable[..., Rig]:
    """Return a factory of rigs, each with its own data directory."""
    count = iter(range(100))

    def build(**kwargs: Any) -> Rig:
        """Create a rig with its own data directory unless one is given."""
        directory = kwargs.pop("data_dir", None) or tmp_path / f"rig{next(count)}"
        return Rig(make_settings, directory, **kwargs)

    return build


class TestSettings:
    """Day shift settings: defaults, bounds, window order and the acknowledgement of "on"."""

    def test_defaults(self, make_settings: Callable[..., Settings]) -> None:
        """The defaults are off, a 09-17 h day window, half-kelvin shifts and a 1 K bound."""
        settings = make_settings()
        assert settings.control_dayshift_use == "off"
        assert settings.control_dayshift_experimental_ok is False
        assert (settings.control_dayshift_day_start, settings.control_dayshift_day_end) == (
            "09:00",
            "17:00",
        )
        assert (settings.control_dayshift_boost_k, settings.control_dayshift_setback_k) == (
            0.5,
            0.5,
        )
        assert settings.control_dayshift_min_outside_c == 5.0
        assert settings.control_dayshift_min_sun_wm2 == 150.0
        assert settings.control_dayshift_recovery_s == 4 * HOUR_S
        assert settings.control_plan_rule_max_k == 1.0
        assert settings.controller_config().plan_rule_max_k == 1.0

    def test_the_rule_bound_reaches_controller_and_monitor(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        """The configured rule bound reaches the controller config and the safety monitor."""
        settings = make_settings(control_plan_rule_max_k=0.6)
        assert settings.controller_config().plan_rule_max_k == 0.6
        assert monitor_config(settings, 40.0).room_setback_max_k == 0.6

    @pytest.mark.parametrize(
        ("changes", "field"),
        [
            ({"control_dayshift_boost_k": 1.5}, "control_dayshift_boost_k"),
            ({"control_dayshift_setback_k": -0.1}, "control_dayshift_setback_k"),
            ({"control_dayshift_day_start": "9:00"}, "control_dayshift_day_start"),
            ({"control_plan_rule_max_k": 2.0}, "control_plan_rule_max_k"),
        ],
    )
    def test_field_bounds(
        self, make_settings: Callable[..., Settings], changes: dict[str, Any], field: str
    ) -> None:
        """Out-of-range or malformed day shift values are refused naming the field."""
        with pytest.raises(ConfigError, match=field):
            make_settings(**changes)

    def test_windows_out_of_order_are_refused(self, make_settings: Callable[..., Settings]) -> None:
        """Window settings that are out of order are reported as a configuration issue."""
        settings = make_settings()
        bad = settings.model_copy(update={"control_dayshift_night_start": "12:00"})
        issues = control_issues(bad)
        assert [(issue.field, issue.code) for issue in issues] == [
            ("control_dayshift_night_start", "dayshift_windows")
        ]

    def test_on_is_refused_without_the_acknowledgement(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        """Switching to "on" without accepting that it is experimental is refused."""
        with pytest.raises(ConfigError, match="experimental"):
            make_settings(control_dayshift_use="on")
        forced = make_settings().model_copy(update={"control_dayshift_use": "on"})
        assert [(i.field, i.code) for i in control_issues(forced)] == [
            ("control_dayshift_use", "dayshift_on_needs_ack")
        ]

    def test_on_is_accepted_with_the_acknowledgement(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        """Switching to "on" is accepted together with the acknowledgement."""
        settings = make_settings(control_dayshift_use="on", control_dayshift_experimental_ok=True)
        assert control_issues(settings) == []
        assert DayShiftRunner(settings).use == "on"

    @pytest.mark.parametrize("use", ["off", "shadow"])
    def test_the_acknowledgement_alone_changes_nothing(
        self, make_settings: Callable[..., Settings], use: str
    ) -> None:
        """The acknowledgement is valid with off and shadow and leaves the switch alone."""
        settings = make_settings(control_dayshift_use=use, control_dayshift_experimental_ok=True)
        assert control_issues(settings) == []
        assert DayShiftRunner(settings).use == use

    def test_the_configuration_api_asks_for_the_acknowledgement(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        """The configuration API refuses "on" alone and taking the acknowledgement back."""
        settings = make_settings(admin_password="pw-123")
        manager = ConfigManager.open(settings, FakeClock(MORNING), locked={})
        app = create_app(Runtime(clock=FakeClock(MORNING)), settings, config=manager)
        headers = {"Authorization": f"Basic {ADMIN}", "X-Ovenbird-Request": "1"}
        both = {"control_dayshift_use": "on", "control_dayshift_experimental_ok": True}

        with TestClient(app) as client:

            def validate(changes: dict[str, Any]) -> list[tuple[str, str]]:
                """Return the errors of validating ``changes`` as (field, code) pairs."""
                body = client.post(
                    "/api/v1/config/validate", json={"changes": changes}, headers=headers
                ).json()
                return [(e["field"], e["code"]) for e in body["errors"]]

            refused = [("control_dayshift_use", "dayshift_on_needs_ack")]
            assert validate({"control_dayshift_use": "on"}) == refused
            assert validate(both) == []
            stored = client.put(
                "/api/v1/config", json={"base_version": 0, "changes": both}, headers=headers
            )
            assert stored.status_code == 200
            assert validate({"control_dayshift_experimental_ok": False}) == refused
            assert validate({"control_dayshift_experimental_ok": None}) == refused
            assert (
                validate(
                    {"control_dayshift_use": "shadow", "control_dayshift_experimental_ok": False}
                )
                == []
            )
            taken_back = client.put(
                "/api/v1/config",
                json={"base_version": 1, "changes": {"control_dayshift_experimental_ok": False}},
                headers=headers,
            )
            assert taken_back.status_code == 422
            assert manager.settings.control_dayshift_use == "on"
            assert manager.settings.control_dayshift_experimental_ok is True


class TestRunner:
    """The runner in off and shadow mode: recording, cadence, journal and stale input."""

    def test_off_reads_records_and_journals_nothing(self, rig: Callable[..., Rig]) -> None:
        """With the rule off nothing is read, recorded or journalled."""
        off = rig(use="off")
        off.until(23.5)
        assert off.reads == 0
        assert off.journal.samples == []
        assert off.journal.events() == []
        assert [row for row in off.journal.states if row.key == MEMORY_KEY] == []
        status = off.runner.status()
        assert (status["mode"], status["phase"], status["reasons"]) == ("off", "idle", ["off"])
        assert status["forecast"] is None

    @pytest.mark.slow
    def test_off_and_shadow_decide_exactly_like_no_rule(self, rig: Callable[..., Rig]) -> None:
        """Off and shadow decide exactly like no rule; shadow records the plan."""
        bare, off, shadow = rig(use="off"), rig(use="off"), rig(use="shadow")
        bare.loop.plan_rule = None
        runs = [item.warm_evening(7.25) for item in (bare, off, shadow)]
        assert len(runs[0]) == 22 * 60 + 30
        for name in ("record", "arbiter", "commands", "setpoint", "ladder", "reason"):
            values = [[getattr(row, name) for row in run] for run in runs]
            assert values[0] == values[1] == values[2], name
        planned = shadow.journal.of(SHADOW_SIGNAL)
        assert max(value or 0.0 for value in planned) == 0.5
        assert min(value or 0.0 for value in planned) == -0.5
        assert set(shadow.journal.of(OFFSET_SIGNAL)) == {0.0}
        assert set(target_offsets(runs[2])) == {0.0}

    def test_shadow_evaluates_every_quarter_hour_once_the_outside_is_known(
        self, rig: Callable[..., Rig]
    ) -> None:
        """Shadow evaluates once per quarter hour, as soon as the outside temperature is known."""
        shadow = rig()
        shadow.tick(1)
        assert shadow.runner.evaluations == 1
        shadow.tick(59)
        assert shadow.runner.evaluations == 5
        assert shadow.reads == 5

    def test_shadow_journals_boost_and_setback(self, rig: Callable[..., Rig]) -> None:
        """Shadow journals boost and set-back starts and ends with the local hour and reasons."""
        shadow = rig()
        shadow.warm_evening(7.25)
        assert shadow.journal.events() == [
            JournalEvent.BOOST_START,
            JournalEvent.BOOST_END,
            JournalEvent.SETBACK_START,
            JournalEvent.SETBACK_END,
        ]
        rows = [row for row in shadow.journal.alarms if row.code == JOURNAL_CODE]
        assert {row.severity for row in rows} == {"info"}
        assert [row.event for row in rows] == ["started", "released", "started", "released"]
        first = json.loads(rows[0].detail)
        assert first["use"] == "shadow"
        assert first["reasons"] == ["sun_forecast", "outside_mild"]
        assert datetime.fromtimestamp(rows[0].ts, UTC).hour == 9
        assert datetime.fromtimestamp(rows[2].ts, UTC).hour == 23

    def test_a_stale_forecast_cancels_and_is_journalled(self, rig: Callable[..., Rig]) -> None:
        """A stale forecast cancels the boost and is journalled with its reason."""
        shadow = rig()
        shadow.until(10)
        shadow.issue_age = 4 * HOUR_S
        shadow.tick(1)
        assert shadow.journal.events() == [JournalEvent.BOOST_START, JournalEvent.CANCEL]
        cancel = json.loads(shadow.journal.alarms[-1].detail)
        assert cancel["reasons"] == ["forecast_stale"]
        status = shadow.runner.status()
        assert (status["phase"], status["guards"]) == ("blocked", ["forecast_stale"])
        assert shadow.journal.of(SHADOW_SIGNAL)[-1] == 0.0

    def test_a_live_guard_reevaluates_between_slots(self, rig: Callable[..., Rig]) -> None:
        """A guard that can change at any moment is re-evaluated between quarter-hour slots."""
        shadow = rig()
        shadow.until(9.5)
        before = shadow.runner.evaluations
        moment = shadow.clock()
        ctx = PlanContext(moment, False, False, 8.0, shadow.loop.controller.config)
        assert shadow.runner.step(ctx) is None
        assert shadow.runner.evaluations == before + 1
        result = shadow.runner.result
        assert result is not None
        assert (result.phase, result.guards) == (Phase.BLOCKED, ("room_untrusted",))

    def test_a_failing_forecast_read_means_no_plan(self, rig: Callable[..., Rig]) -> None:
        """A failing forecast read means no plan without breaking the control loop."""
        shadow = rig()

        def broken(_path: Path, _now: float, _horizon: float) -> ForecastWindow:
            """Raise an error as an unreadable forecast store would."""
            raise OSError("disk gone")

        shadow.runner.load_forecast = broken
        rows = shadow.tick(20)
        assert len(rows) == 20
        assert shadow.runner.result is None

    def test_off_after_shadow_forgets_the_evaluation(self, rig: Callable[..., Rig]) -> None:
        """Switching off after shadow forgets the last evaluation."""
        shadow = rig()
        shadow.until(10)
        assert shadow.runner.result is not None
        shadow.loop.reconfigure(
            shadow.settings.model_copy(update={"control_dayshift_use": "off"}), None
        )
        shadow.tick(1)
        assert shadow.runner.result is None
        assert shadow.runner.status()["mode"] == "off"


class TestOn:
    """The runner in on mode: it shifts the room target through plan slices."""

    def test_on_shifts_the_room_target_in_steps(self, rig: Callable[..., Rig]) -> None:
        """On shifts the room target in quarter-kelvin steps and offers a rule plan slice."""
        on = rig(**ON)
        morning = on.until(9.5)
        assert target_offsets(morning[:15]) == [0.0] * 15
        assert target_offsets(morning[15:30]) == [0.25] * 15
        assert target_offsets(morning[30:]) == [0.5] * 15
        assert {row.ladder for row in morning[15:]} == {LadderLevel.RULE_PLAN.value}
        offered = on.runner._slice
        assert offered is not None
        assert (offered.source, offered.reason) == (PlanSource.RULE, ReasonCode.PLAN_PREHEAT)
        assert offered.valid_until.since(offered.valid_from) == SLICE_VALID_S
        assert on.journal.of(OFFSET_SIGNAL)[-1] == 0.5
        status = on.runner.status()
        assert (status["mode"], status["applied_k"], status["phase"]) == ("on", 0.5, "boost")
        assert status["valid_until"] is not None

    def test_on_sets_back_and_the_monitor_floor_follows(self, rig: Callable[..., Rig]) -> None:
        """On sets the night back, and the safety monitor's room floor follows the shift."""
        on = rig(**ON)
        on.warm_evening(23.75)
        offered = on.runner._slice
        assert offered is not None
        assert offered.reason is ReasonCode.PLAN_SETBACK
        assert on.loop.room_shift() == -0.5
        safety = on.loop.safety
        assert safety is not None
        assert safety.room_shift is not None
        assert safety.room_shift() == -0.5

    def test_a_live_guard_withdraws_the_slice_at_once(self, rig: Callable[..., Rig]) -> None:
        """A live guard withdraws the offered slice at once."""
        on = rig(**ON)
        on.until(9.5)
        ctx = PlanContext(on.clock(), False, False, 8.0, on.loop.controller.config)
        assert on.runner.step(ctx) is None

    @pytest.mark.slow
    def test_a_sunny_mild_day_applies_a_boost_through_the_slice_only(
        self, rig: Callable[..., Rig]
    ) -> None:
        """On applies the boost on a sunny, mild day and differs from off only by its slices.

        The off run gets on's slices replayed into its plan slot tick by tick: every
        decision is then identical, so the slice is the day shift's only way in.
        """
        on, off, replayed = rig(**ON), rig(use="off"), rig(use="off")
        slices = Recorder(on.runner)
        on.loop.plan_rule = slices
        on_rows = on.warm_evening(7.25)
        off_rows = off.warm_evening(7.25)
        replayed.loop.plan_rule = Replay(slices.offered)
        replayed_rows = replayed.warm_evening(7.25)
        offsets = target_offsets(on_rows)
        assert max(offsets) == 0.5
        assert min(offsets) == -0.5
        assert max(value or 0.0 for value in on.journal.of(OFFSET_SIGNAL)) == 0.5
        assert set(target_offsets(off_rows)) == {0.0}
        assert [row.record for row in on_rows] != [row.record for row in off_rows]
        boosted = [row for row, k in zip(on_rows, offsets, strict=True) if k > 0.0]
        assert {row.ladder for row in boosted} == {LadderLevel.RULE_PLAN.value}
        for name in ("record", "arbiter", "commands", "setpoint", "ladder", "reason"):
            assert [getattr(row, name) for row in on_rows] == [
                getattr(row, name) for row in replayed_rows
            ], name
        first = next(index for index, value in enumerate(slices.offered) if value is not None)
        for name in ("record", "arbiter", "commands", "setpoint"):
            assert [getattr(row, name) for row in on_rows[:first]] == [
                getattr(row, name) for row in off_rows[:first]
            ], name

    def test_the_status_says_on_needs_the_acknowledgement(self, rig: Callable[..., Rig]) -> None:
        """The status says the day shift is experimental and whether on is available."""
        shadow, on = rig(), rig(**ON)
        assert (shadow.runner.status()["on_available"], on.runner.status()["on_available"]) == (
            False,
            True,
        )
        assert shadow.runner.status()["experimental"] is True
        on.until(9.5)
        assert (on.runner.status()["mode"], on.runner.status()["configured"]) == ("on", "on")


class Recorder:
    """A plan slot that passes the runner's slices through and keeps each one."""

    def __init__(self, runner: DayShiftRunner) -> None:
        """Wrap ``runner`` and start an empty list of offered slices."""
        self.runner = runner
        self.offered: list[PlanSlice | None] = []

    def step(self, ctx: PlanContext) -> PlanSlice | None:
        """Return the runner's slice for this tick and keep it."""
        plan = self.runner.step(ctx)
        self.offered.append(plan)
        return plan

    def after(self, decision: DecisionRecord) -> None:
        """Pass the decision on to the runner."""
        self.runner.after(decision)


class Replay:
    """A plan slot that hands out recorded slices, one per tick."""

    def __init__(self, slices: list[PlanSlice | None]) -> None:
        """Keep the slices to hand out in order."""
        self.slices = iter(slices)

    def step(self, _ctx: PlanContext) -> PlanSlice | None:
        """Return the next recorded slice."""
        return next(self.slices)

    def after(self, decision: DecisionRecord) -> None:
        """Ignore the decision."""


class TestRestart:
    """Restoring the rule's memory after a restart."""

    def test_the_night_after_a_boost_survives_a_restart(
        self, rig: Callable[..., Rig], tmp_path: Path
    ) -> None:
        """The night set-back after a day with a boost survives a restart."""
        first = rig(data_dir=tmp_path / "house")
        first.until(18)
        saved = load_memory(first.settings.history_path)
        assert saved is not None
        assert saved[0].boost_day is not None
        second = rig(data_dir=tmp_path / "house", start=first.clock.t + 4 * HOUR_S)
        second.room = WARM_ROOM
        second.until(23.5)
        assert min(value or 0.0 for value in second.journal.of(SHADOW_SIGNAL)) == -0.5
        assert second.journal.events() == [JournalEvent.SETBACK_START]

    def test_a_quick_restart_keeps_the_offset_and_the_phase(
        self, rig: Callable[..., Rig], tmp_path: Path
    ) -> None:
        """A quick restart keeps the offset and the phase."""
        first = rig(data_dir=tmp_path / "house")
        first.until(9.75)
        second = rig(data_dir=tmp_path / "house", start=first.clock.t + 120.0)
        second.tick(1)
        assert second.journal.of(SHADOW_SIGNAL) == [0.5]
        assert second.journal.events() == []

    def test_a_late_restart_ramps_from_zero(self, rig: Callable[..., Rig], tmp_path: Path) -> None:
        """A late restart ramps up again from zero."""
        first = rig(data_dir=tmp_path / "house")
        first.until(9.75)
        second = rig(data_dir=tmp_path / "house", start=first.clock.t + 2 * HOUR_S)
        second.tick(2)
        assert second.journal.of(SHADOW_SIGNAL) == [0.0, 0.25]
        assert second.runner.evaluations == 2

    def test_an_unreadable_memory_starts_afresh(self, tmp_path: Path) -> None:
        """An unreadable or missing memory starts afresh."""
        path = tmp_path / "history.db"
        conn = open_history(path)
        try:
            write_journal(conn, [], [], [], [StateRow(MEMORY_KEY, MORNING, '{"v": 7}')])
        finally:
            conn.close()
        assert load_memory(path) is None
        assert load_memory(tmp_path / "missing.db") is None


class TestTransitions:
    """Journal events derived from phase transitions."""

    @pytest.mark.parametrize(
        ("before", "after", "events"),
        [
            (Phase.IDLE, Phase.BOOST, (JournalEvent.BOOST_START,)),
            (Phase.BOOST, Phase.IDLE, (JournalEvent.BOOST_END,)),
            (Phase.BOOST, Phase.BLOCKED, (JournalEvent.CANCEL,)),
            (Phase.SETBACK, Phase.BLOCKED, (JournalEvent.CANCEL,)),
            (Phase.SETBACK, Phase.RECOVERY, (JournalEvent.SETBACK_END,)),
            (Phase.IDLE, Phase.SETBACK, (JournalEvent.SETBACK_START,)),
            (Phase.BLOCKED, Phase.BOOST, (JournalEvent.BOOST_START,)),
            (Phase.IDLE, Phase.BLOCKED, ()),
            (Phase.RECOVERY, Phase.IDLE, ()),
            (Phase.BOOST, Phase.BOOST, ()),
        ],
    )
    def test_journal_events(
        self, before: Phase, after: Phase, events: tuple[JournalEvent, ...]
    ) -> None:
        """Phase transitions map to the expected journal events, or none."""
        assert transitions(before, after) == events


class TestApi:
    """The day shift route."""

    def test_the_route_answers_the_model(self, rig: Callable[..., Rig]) -> None:
        """The route returns the model with the current phase, offsets, windows and forecast."""
        shadow = rig()
        shadow.until(9.5)
        app = create_app(shadow.runtime, shadow.settings, control=shadow.loop)
        with TestClient(app) as client:
            response = client.get("/api/v1/control/dayshift")
        assert response.status_code == 200
        body = response.json()
        TypeAdapter(DayShift).validate_python(body)
        assert list(body) == list(DayShift.model_fields)
        assert body["mode"] == "shadow"
        assert body["phase"] == "boost"
        assert (body["offset_k"], body["desired_k"], body["applied_k"]) == (0.5, 0.5, 0.0)
        assert body["reasons"] == ["sun_forecast", "outside_mild"]
        assert body["next_change"] == {"at": "2026-03-10T17:00:00Z", "phase": "idle"}
        assert body["boosted_today"] is True
        assert body["windows"]["setback_end"] == "2026-03-11T03:00:00Z"
        assert body["forecast"]["sun_limit_wm2"] == 75.0
        assert body["forecast"]["outside_c"] == 8.0
        assert body["evaluated_at"] == "2026-03-10T09:15:00Z"
        assert body["forecast"]["issued_at"] == "2026-03-10T08:45:00Z"

    def test_without_a_control_loop_the_route_refuses(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        """Without a control loop the route answers with a conflict."""
        settings = make_settings()
        app = create_app(Runtime(clock=FakeClock(MORNING)), settings)
        with TestClient(app) as client:
            assert client.get("/api/v1/control/dayshift").status_code == 409

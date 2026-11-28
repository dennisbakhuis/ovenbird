"""Boost, away, the summer switch, quiet after a start, the start alarm and the feature list."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ovenbird.api.app import create_app
from ovenbird.config import Settings
from ovenbird.configstore import ConfigManager, schema_payload
from ovenbird.configstore.fields import EDITABLE, FIELDS, Feature, feature_of
from ovenbird.control import AlarmCode, ControlLoop
from ovenbird.control.features import FeatureState, feature_views
from ovenbird.control.forecastread import Guard, live_guards
from ovenbird.control.monitors import MonitorConfig, MonitorStatus, room_floor
from ovenbird.control.roomtarget import (
    AWAY_JOURNAL_CODE,
    AWAY_KEY,
    BOOST_JOURNAL_CODE,
    BOOST_KEY,
    AwayPhase,
    RoomTargetError,
    load_away,
    load_boost,
)
from ovenbird.control.starts import (
    STARTS_FACT,
    StartCounter,
    StartCounts,
    start_counter,
    starts_exceeded,
)
from ovenbird.history import AlarmRow, StateRow, open_history
from ovenbird.history.journal import write_journal
from ovenbird.insight.basics import Exclusions, _qualify, away_spans
from ovenbird.insight.daily import DayFigures, LocalDay
from ovenbird.mqtt import MqttIngest
from ovenbird.runtime import Runtime
from ovenbird.service import build_control
from ovenbird.system.facts import Facts
from ovenbird.testing import FakeClock, pump_messages
from ovenbird_core import StateStore, ha_reading
from ovenbird_core.control import OverrideKind, ReasonCode, control_inputs

T0 = 1_800_000_000.0
HOUR = 3600.0
ROOM = "sensor.living_room_temperature"
HA: dict[str, Any] = {
    "ha_url": "http://ha.local:8123",
    "ha_token": "token",
    "ha_entities": (ROOM,),
    "control_room_signal": f"ha/{ROOM}",
    "control_comfort_c": 21.0,
}
TOKEN = "operate-token-" + "x" * 24
OPERATE = {"Authorization": f"Bearer {TOKEN}", "X-Ovenbird-Request": "1"}


async def no_sleep(_: float) -> None:
    """Replace the loop's sleep so ticks run without waiting."""
    return


class Journal:
    """Collects what the loop journals; optionally saves state rows to the history."""

    def __init__(self, path: Path | None = None) -> None:
        """Create an empty journal, saving rows to the history database at ``path`` when given."""
        self.path = path
        self.states: list[StateRow] = []
        self.alarms: list[AlarmRow] = []

    def offer_decision(self, row: Any) -> None:
        """Ignore decision rows, which these tests do not need."""
        return

    def offer_command(self, row: Any) -> None:
        """Ignore command rows, which these tests do not need."""
        return

    def offer_alarm(self, row: AlarmRow) -> None:
        """Record an alarm row and persist it when a history path is set."""
        self.alarms.append(row)
        if self.path is not None:
            write(self.path, alarms=[row])

    def offer_state(self, row: StateRow) -> None:
        """Record a state row and persist it when a history path is set."""
        self.states.append(row)
        if self.path is not None:
            write(self.path, states=[row])

    def events(self, code: str) -> list[str]:
        """Return the events of the journalled alarm rows with the given code, in order."""
        return [row.event for row in self.alarms if row.code == code]


def write(
    path: Path, *, alarms: list[AlarmRow] | None = None, states: list[StateRow] | None = None
) -> None:
    """Write alarm and state rows into the history database at ``path``.

    Parameters
    ----------
    path
        History database file.
    alarms
        Alarm rows to journal.
    states
        State rows to journal.
    """
    conn = open_history(path)
    try:
        write_journal(conn, [], [], alarms or [], states or [])
    finally:
        conn.close()


class Rig:
    """A control loop on a fake clock fed with pump messages and a room value."""

    def __init__(
        self,
        settings: Settings,
        journal: Journal | None = None,
        start: float = T0,
        facts: Facts | None = None,
    ) -> None:
        """Build the runtime, ingest and control loop on a fake clock.

        Parameters
        ----------
        settings
            Service settings the controller is built from.
        journal
            Journal receiving the loop's rows; a fresh in-memory one when omitted.
        start
            Initial fake clock time (epoch s).
        facts
            Persisted facts handed to the controller, such as start times.
        """
        self.settings = settings
        self.clock = FakeClock(start)
        self.runtime = Runtime(
            StateStore(settings.staleness_policy()), clock=self.clock, ha_enabled=True
        )
        self.ingest = MqttIngest(settings, self.runtime)
        self.journal = journal or Journal()
        self.loop, _ = build_control(
            settings,
            self.runtime,
            self.journal,  # type: ignore[arg-type]
            sleep=no_sleep,
            facts=facts,
        )

    def feed(self, room: float = 21.0, **pump: str) -> None:
        """Ingest pump messages given as keyword fields and apply a room temperature reading."""
        for message in pump_messages(**pump):
            self.ingest.ingest(message)
        self.runtime.apply(ha_reading(ROOM, f"{room:.1f}", instant=self.clock()))

    def tick(self, room: float = 21.0, minutes: int = 1, step: float = 60.0, **pump: str) -> None:
        """Feed the inputs, run one control tick and advance the clock, ``minutes`` times.

        Parameters
        ----------
        room
            Room temperature (°C) to report on every tick.
        minutes
            Number of ticks to run.
        step
            Seconds the clock advances after each tick.
        **pump
            Heat pump readings fed with every tick, by HeishaMon topic name.
        """
        for _ in range(minutes):
            self.feed(room, **pump)
            self.loop.tick()
            self.clock.advance(step)

    @property
    def state(self) -> dict[str, Any]:
        """Return the latest control state record, or an empty dict before the first tick."""
        return self.loop.latest_state or {}

    @property
    def wall(self) -> datetime:
        """Return the current wall-clock time of the fake clock."""
        return self.clock().wall


def iso(wall: datetime) -> str:
    """Format a datetime as an ISO 8601 UTC string ending in ``Z``."""
    return wall.astimezone(UTC).isoformat().replace("+00:00", "Z")


class TestSettings:
    """Defaults, switch wiring and bounds of the feature settings."""

    def test_defaults(self, make_settings: Callable[..., Settings]) -> None:
        """Boost, away, summer, quiet and start-alarm settings have their documented defaults."""
        settings = make_settings()
        assert settings.control_boost_enabled is True
        assert settings.control_boost_default_s == 7200.0
        assert settings.control_boost_default_k == 1.0
        assert settings.control_away_enabled is True
        assert settings.control_away_target_c == 16.0
        assert settings.control_away_comfort_lead_s == 21_600.0
        assert settings.control_summer_enabled is False
        assert settings.control_summer_off_c == 18.0
        assert settings.control_summer_hysteresis_k == 2.0
        assert settings.control_summer_mean_s == 86_400.0
        assert settings.control_quiet_enabled is True
        assert settings.control_quiet_start_enabled is False
        assert settings.control_quiet_start_minutes == 10
        assert settings.control_quiet_start_level == 2
        assert settings.safety_starts_alarm_enabled is True
        assert settings.safety_starts_per_hour_max == 4
        assert settings.safety_starts_per_day_max == 30
        config = settings.controller_config()
        assert config.summer is None
        assert config.quiet_start is None

    def test_switches_reach_the_controller(self, make_settings: Callable[..., Settings]) -> None:
        """Enabled summer and quiet-start settings appear in the controller configuration."""
        window = {"start": "22:00", "end": "07:00", "level": 2}
        settings = make_settings(
            control_summer_enabled=True,
            control_summer_off_c=17.0,
            control_quiet_start_enabled=True,
            control_quiet_start_minutes=15,
            control_quiet_start_level=3,
            control_quiet_windows=[window],
        )
        config = settings.controller_config()
        assert config.summer is not None
        assert config.summer.off_c == 17.0
        assert config.summer.on_c == 15.0
        assert config.quiet_start is not None
        assert config.quiet_start.duration_s == 900.0
        assert config.quiet_start.level == 3
        assert config.quiet is not None
        ignored = make_settings(control_quiet_windows=[window], control_quiet_enabled=False)
        assert ignored.controller_config().quiet is None

    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("control_quiet_start_minutes", 31),
            ("control_quiet_start_level", 4),
            ("control_away_target_c", 21.0),
            ("control_boost_default_k", 2.5),
            ("control_boost_default_s", 600.0),
            ("control_summer_off_c", 30.0),
        ],
    )
    def test_bounds(self, make_settings: Callable[..., Settings], name: str, value: Any) -> None:
        """Out-of-range values are rejected with an error naming the setting."""
        with pytest.raises(Exception, match=name):
            make_settings(**{name: value})


class TestFieldMeta:
    """Feature metadata of the editable configuration fields."""

    def test_every_feature_has_fields(self) -> None:
        """Every feature owns at least one configuration field."""
        named = {meta.feature for meta in FIELDS.values()}
        assert set(Feature) <= named

    def test_mapping(self) -> None:
        """Field names map to their feature, and unrelated fields map to none."""
        assert feature_of("control_stove_backoff_k") is Feature.STOVE
        assert feature_of("control_quiet_start_level") is Feature.QUIET
        assert feature_of("safety_starts_per_day_max") is Feature.STARTS_ALARM
        assert feature_of("control_cycling_max_raise_k") is Feature.MINIMUM_RUN
        assert feature_of("control_comfort_c") is None

    def test_max_raise_is_advanced(self, make_settings: Callable[..., Settings]) -> None:
        """The cycling max-raise field is editable, advanced and part of the minimum-run feature."""
        assert "control_cycling_max_raise_k" in EDITABLE
        entry = schema_payload(make_settings())["fields"]["control_cycling_max_raise_k"]
        assert entry["tier"] == "advanced"
        assert entry["feature"] == "minimum_run"

    def test_expert_fields_are_flagged_read_only(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        """Expert fields are read-only and every field is either read-only or editable."""
        fields = schema_payload(make_settings())["fields"]
        assert fields["control_interval_s"]["read_only"] is True
        assert fields["control_interval_s"]["tier"] == "expert"
        assert fields["control_comfort_c"]["read_only"] is False
        for entry in fields.values():
            assert entry["read_only"] is not entry["editable"]


class TestBoost:
    """The temporary room target boost."""

    def test_shifts_the_room_target_and_ends_by_itself(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        """A boost shifts the room target, reports its owner and expires after its duration."""
        rig = Rig(make_settings(**HA))
        rig.tick(minutes=2)
        rig.loop.request_boost(
            offset_k=1.0, target_c=None, duration_s=900.0, until=None, actor="owner from 10.0.0.2"
        )
        rig.tick()
        assert rig.state["room_override"] == OverrideKind.ROOM_TARGET.value
        assert rig.state["room_target_c"] == pytest.approx(22.0)
        status = rig.loop.boost_status()
        assert status["active"] is True
        assert status["request"]["actor"] == "owner"
        rig.tick(minutes=15)
        assert "room_override" not in rig.state
        assert rig.loop.targets.boost is None
        assert rig.journal.events(BOOST_JOURNAL_CODE) == ["started", "expired"]

    def test_an_absolute_target(self, make_settings: Callable[..., Settings]) -> None:
        """A boost with an absolute target defaults to two hours and lowers the room target."""
        rig = Rig(make_settings(**HA))
        request = rig.loop.request_boost(
            offset_k=None, target_c=20.0, duration_s=None, until=None, actor="owner"
        )
        assert request.until == rig.wall + timedelta(hours=2)
        rig.tick()
        assert rig.state["room_override_k"] == pytest.approx(-1.0)
        assert rig.loop.lowered_target() == pytest.approx(20.0)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"offset_k": 2.5},
            {"offset_k": -3.5},
            {"offset_k": 0.0},
            {"target_c": 25.0},
            {"offset_k": 1.0, "target_c": 22.0},
            {"offset_k": 1.0, "duration_s": 600.0},
            {"offset_k": 1.0, "duration_s": 13 * HOUR},
        ],
    )
    def test_refused_values(
        self, make_settings: Callable[..., Settings], kwargs: dict[str, Any]
    ) -> None:
        """Out-of-range or contradictory boost requests are refused with status 400."""
        rig = Rig(make_settings(**HA))
        values = {"offset_k": None, "target_c": None, "duration_s": None, "until": None, **kwargs}
        with pytest.raises(RoomTargetError) as caught:
            rig.loop.request_boost(actor="owner", **values)
        assert caught.value.status == 400

    def test_switched_off(self, make_settings: Callable[..., Settings]) -> None:
        """A disabled boost feature refuses requests with status 409."""
        rig = Rig(make_settings(**HA, control_boost_enabled=False))
        with pytest.raises(RoomTargetError) as caught:
            rig.loop.request_boost(
                offset_k=1.0, target_c=None, duration_s=None, until=None, actor="owner"
            )
        assert caught.value.status == 409

    def test_a_manual_stove_start_ends_it(self, make_settings: Callable[..., Settings]) -> None:
        """Starting the stove manually releases an active boost."""
        rig = Rig(make_settings(**HA, control_stove_enabled=True))
        rig.loop.request_boost(
            offset_k=1.0, target_c=None, duration_s=None, until=None, actor="owner"
        )
        rig.tick()
        rig.loop.request_stove(True, None, "owner")
        assert rig.loop.targets.boost is None
        assert rig.journal.events(BOOST_JOURNAL_CODE) == ["started", "released"]

    def test_an_automatic_stove_episode_pauses_it(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        """An automatic stove episode pauses the boost without ending it."""
        rig = Rig(make_settings(**HA, control_stove_enabled=True))
        rig.tick(minutes=2)
        rig.loop.request_boost(
            offset_k=0.5, target_c=None, duration_s=None, until=None, actor="owner"
        )
        for step in range(1, 31):
            rig.tick(room=21.0 + 3.5 * step / 30)
        assert rig.loop.state.stove_active
        assert rig.state["room_override_paused"] == "stove"
        assert rig.loop.boost_status()["paused"] == "stove"
        assert rig.loop.targets.boost is not None

    def test_survives_a_restart(self, make_settings: Callable[..., Settings]) -> None:
        """An active boost is restored after a restart, unless it expired or is disabled."""
        settings = make_settings(**HA)
        path = settings.history_path
        first = Rig(settings, Journal(path))
        first.tick()
        request = first.loop.request_boost(
            offset_k=1.5, target_c=None, duration_s=HOUR, until=None, actor="owner"
        )
        second = Rig(settings, Journal(path), start=T0 + 600.0)
        assert second.loop.targets.boost == request
        second.tick()
        assert second.state["room_override_k"] == 1.5
        assert load_boost(path, FakeClock(T0 + 2 * HOUR)()) is None
        disabled = Rig(make_settings(**HA, control_boost_enabled=False), start=T0 + 600.0)
        assert disabled.loop.targets.boost is None

    def test_switching_off_drops_it(self, make_settings: Callable[..., Settings]) -> None:
        """Switching the feature off drops an active boost and journals its removal."""
        rig = Rig(make_settings(**HA))
        rig.loop.request_boost(
            offset_k=1.0, target_c=None, duration_s=None, until=None, actor="owner"
        )
        rig.loop.reconfigure(make_settings(**HA, control_boost_enabled=False), 2)
        rig.tick()
        assert rig.loop.targets.boost is None
        stored = [row for row in rig.journal.states if row.key == BOOST_KEY]
        assert json.loads(stored[-1].value) is None


class TestAway:
    """The away mode that lowers the room target."""

    def test_lowers_the_target_then_returns_before_the_end(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        """Away lowers the target, then raises it ahead of the return time and finally expires."""
        rig = Rig(make_settings(**HA))
        rig.tick()
        until = rig.wall + timedelta(hours=8)
        rig.loop.request_away(target_c=None, until=until, lead_s=None, actor="owner")
        rig.tick()
        assert rig.state["room_override"] == OverrideKind.AWAY.value
        assert rig.state["room_target_c"] == pytest.approx(16.0)
        assert rig.loop.latest is not None
        terms = {term["name"]: term for term in rig.loop.latest["record"]["terms"]}
        assert "away -5.0 K by owner" in terms["room_target"]["note"]
        assert rig.loop.away_status()["phase"] == AwayPhase.AWAY.value
        assert rig.loop.lowered_target() == pytest.approx(16.0)
        rig.clock.advance(2 * HOUR)
        rig.tick()
        assert "room_override" not in rig.state
        assert rig.state["room_target_c"] == pytest.approx(21.0)
        assert rig.loop.away_status()["phase"] == AwayPhase.RETURNING.value
        assert rig.loop.lowered_target() == pytest.approx(16.0)
        rig.clock.advance(6 * HOUR)
        rig.tick()
        assert rig.loop.targets.away is None
        assert rig.loop.lowered_target() is None
        assert rig.journal.events(AWAY_JOURNAL_CODE) == ["started", "expired"]

    def test_pauses_the_day_shift(self, make_settings: Callable[..., Settings]) -> None:
        """An active away period makes the plan context mark away and raises the away guard."""
        rig = Rig(make_settings(**HA))
        rig.tick()
        rig.loop.request_away(
            target_c=15.0, until=rig.wall + timedelta(days=2), lead_s=0.0, actor="owner"
        )
        snapshot = rig.runtime.store.snapshot(rig.clock())
        inputs = control_inputs(snapshot, room_signal=rig.loop.room_signal)
        ctx = rig.loop.plan_context(rig.clock(), inputs)
        assert ctx.away is True
        assert Guard.AWAY in live_guards(ctx, None)

    def test_ends_a_boost_and_refuses_a_new_one(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        """Away releases an active boost and then refuses a new one with status 409."""
        rig = Rig(make_settings(**HA))
        rig.loop.request_boost(
            offset_k=1.0, target_c=None, duration_s=None, until=None, actor="owner"
        )
        rig.loop.request_away(
            target_c=None, until=rig.wall + timedelta(days=1), lead_s=None, actor="owner"
        )
        assert rig.loop.targets.boost is None
        with pytest.raises(RoomTargetError) as caught:
            rig.loop.request_boost(
                offset_k=1.0, target_c=None, duration_s=None, until=None, actor="owner"
            )
        assert caught.value.status == 409
        assert rig.journal.events(BOOST_JOURNAL_CODE) == ["started", "released"]

    @pytest.mark.parametrize(
        ("target", "hours", "lead"),
        [(21.0, 24, None), (9.0, 24, None), (16.0, 5, None), (16.0, 61 * 24, None), (16.0, 24, -1)],
    )
    def test_refused_values(
        self,
        make_settings: Callable[..., Settings],
        target: float,
        hours: int,
        lead: float | None,
    ) -> None:
        """Away targets, durations and lead times out of range are refused."""
        rig = Rig(make_settings(**HA))
        with pytest.raises(RoomTargetError):
            rig.loop.request_away(
                target_c=target,
                until=rig.wall + timedelta(hours=hours),
                lead_s=lead,
                actor="owner",
            )

    def test_survives_a_restart(self, make_settings: Callable[..., Settings]) -> None:
        """An active away period is restored from the journal after a restart, unless expired."""
        settings = make_settings(**HA)
        path = settings.history_path
        first = Rig(settings, Journal(path))
        request = first.loop.request_away(
            target_c=17.0, until=first.wall + timedelta(days=3), lead_s=None, actor="owner"
        )
        second = Rig(settings, Journal(path), start=T0 + 3600.0)
        assert second.loop.targets.away == request
        second.tick()
        assert second.state["room_target_c"] == pytest.approx(17.0)
        assert load_away(path, FakeClock(T0 + 4 * 86_400.0)()) is None
        stored = [row for row in first.journal.states if row.key == AWAY_KEY]
        assert json.loads(stored[-1].value)["target_c"] == 17.0

    def test_the_floor_follows_the_away_target(self) -> None:
        """The room floor drops with the lowered target but never exceeds the configured floor."""
        config = MonitorConfig(55.0, room_floor_c=19.5, room_floor_k=1.5)
        assert room_floor(config) == 19.5
        assert room_floor(config, lowered_target_c=16.0) == 14.5
        assert room_floor(config, lowered_target_c=21.0) == 19.5
        assert room_floor(MonitorConfig(55.0), lowered_target_c=16.0) is None

    def test_the_monitor_uses_the_lowered_floor(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        """A room above the lowered floor does not trigger the floor alarm."""
        rig = Rig(make_settings(**HA))
        rig.loop.request_away(
            target_c=None, until=rig.wall + timedelta(days=1), lead_s=None, actor="owner"
        )
        rig.tick(room=17.0, minutes=2)
        assert rig.loop.safety is not None
        findings = {f.code: f for f in rig.loop.safety.check()}
        assert findings[AlarmCode.ROOM_BELOW_FLOOR].status is MonitorStatus.OK

    def test_away_days_leave_the_basics(self, tmp_path: Path) -> None:
        """Days overlapping an away span are excluded from the insight basics."""
        path = tmp_path / "history.db"
        start = T0
        rows = [
            AlarmRow(start + 3 * HOUR, AWAY_JOURNAL_CODE, "info", "started", "away", "{}"),
            AlarmRow(start + 30 * HOUR, AWAY_JOURNAL_CODE, "info", "expired", "away", "{}"),
        ]
        write(path, alarms=rows)
        spans = away_spans(path, start, start + 5 * 86_400.0)
        assert spans == [(start + 3 * HOUR, start + 30 * HOUR)]
        days = [
            DayFigures(
                LocalDay(date(2027, 1, 15 + i), start + i * 86_400.0, start + (i + 1) * 86_400.0),
                1.0,
                1.0,
                1500.0,
                400.0,
                2.0,
                21.0,
            )
            for i in range(3)
        ]
        qualified, excluded = _qualify(days, [], start + 4 * 86_400.0, spans)
        assert excluded == Exclusions(away=2)
        assert [item is not None for item in qualified] == [False, False, True]


def frequency(rig: Rig, hz: int, defrost: int = 0) -> None:
    """Feed a compressor frequency (Hz) and defrost state to the rig."""
    rig.feed(Compressor_Freq=str(hz), Defrosting_State=str(defrost))


class TestStarts:
    """Counting compressor starts and the start-count alarm."""

    def observe(self, rig: Rig, counter: StartCounter, hz: int, defrost: int = 0) -> bool:
        """Feed one compressor reading, advance a minute and return whether a start was counted."""
        frequency(rig, hz, defrost)
        seen = counter.observe(rig.runtime.store.snapshot(rig.clock()))
        rig.clock.advance(60.0)
        return seen

    def test_counts_a_start_not_a_defrost_restart(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        """A start counts when the compressor switches on, not when it restarts after a defrost."""
        rig = Rig(make_settings())
        counter = StartCounter()
        assert self.observe(rig, counter, 30) is False
        assert self.observe(rig, counter, 0) is False
        assert self.observe(rig, counter, 30) is True
        assert self.observe(rig, counter, 0, defrost=1) is False
        assert self.observe(rig, counter, 30, defrost=1) is False
        assert self.observe(rig, counter, 0) is False
        assert self.observe(rig, counter, 0, defrost=1) is False
        assert self.observe(rig, counter, 30) is False
        assert self.observe(rig, counter, 0) is False
        assert self.observe(rig, counter, 30) is True
        counts = counter.counts(rig.clock().wall.timestamp())
        assert counts == StartCounts(2, 0, 2)

    def test_windows(self) -> None:
        """Starts are counted over the last hour and day, and the limits trigger separately."""
        now = T0
        starts = [now - 30.0 * i for i in range(5)] + [now - HOUR - 60.0 * i for i in range(5)]
        counter = StartCounter([*starts, now - 25 * HOUR])
        counts = counter.counts(now)
        assert counts == StartCounts(5, 5, 10)
        assert starts_exceeded(counts, 4, 30) is not None
        assert starts_exceeded(StartCounts(5, 4, 9), 4, 30) is None
        assert starts_exceeded(StartCounts(0, 0, 31), 4, 30) is not None

    def test_the_start_times_survive_a_restart(self) -> None:
        """Start times are restored from the stored facts and invalid or old entries are dropped."""
        facts = Facts()
        counter = start_counter(facts, T0, 1.0)
        assert counter.starts == type(counter.starts)()
        facts.set(STARTS_FACT, [T0 - 100.0, T0 - 2 * 86_400.0, "x", True])
        restored = start_counter(facts, T0, 1.0)
        assert list(restored.starts) == [T0 - 100.0]

    def test_the_monitor_raises_a_warning(self, make_settings: Callable[..., Settings]) -> None:
        """Too many recent starts raise the starts warning unless the alarm is disabled."""
        facts = Facts()
        recent = [T0 - 60.0 * i for i in range(1, 6)] + [T0 - HOUR - 60.0 * i for i in range(5)]
        facts.set(STARTS_FACT, recent)
        rig = Rig(make_settings(), facts=facts)
        rig.feed()
        assert rig.loop.safety is not None
        findings = {f.code: f for f in rig.loop.safety.check()}
        assert findings[AlarmCode.COMPRESSOR_STARTS].status is MonitorStatus.ACTIVE
        assert findings[AlarmCode.COMPRESSOR_STARTS].value == 5
        quiet = Rig(make_settings(safety_starts_alarm_enabled=False), facts=facts)
        quiet.feed()
        assert quiet.loop.safety is not None
        codes = {f.code for f in quiet.loop.safety.check()}
        assert AlarmCode.COMPRESSOR_STARTS not in codes


class TestSummer:
    """The summer switch that turns heating off in warm weather."""

    def test_journal_and_status(self, make_settings: Callable[..., Settings]) -> None:
        """A warm outside mean turns summer mode on and a cold one off again, both journalled."""
        settings = make_settings(**HA, control_summer_enabled=True, control_summer_mean_s=6 * HOUR)
        rig = Rig(settings)
        rig.tick(minutes=8, step=HOUR, Outside_Temp="24")
        status = rig.loop.summer_status()
        assert status["enabled"] is True
        assert status["active"] is True
        assert status["warming_up"] is False
        assert status["off_c"] == 18.0
        assert rig.loop.latest is not None
        assert rig.loop.latest["reason"] == ReasonCode.SUMMER.value
        assert rig.journal.events("summer_mode") == ["started"]
        rig.tick(minutes=12, step=HOUR, Outside_Temp="2")
        assert rig.loop.summer_status()["active"] is False
        assert rig.journal.events("summer_mode") == ["started", "expired"]

    def test_off_by_default(self, make_settings: Callable[..., Settings]) -> None:
        """With summer mode disabled the status is empty and no summer state is reported."""
        rig = Rig(make_settings(**HA))
        rig.tick()
        assert rig.loop.summer_status() == {
            "enabled": False,
            "active": False,
            "mean_c": None,
            "off_c": None,
            "on_c": None,
            "mean_tau_s": None,
            "warming_up": False,
        }
        assert not any(key.startswith("summer_") for key in rig.state)


class TestQuietStart:
    """The quiet period after a compressor start."""

    def test_quiet_after_a_start_reaches_the_intents(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        """A compressor start activates quiet start at the configured level."""
        rig = Rig(make_settings(**HA, control_quiet_start_enabled=True))
        rig.tick(Compressor_Freq="0")
        rig.tick(Compressor_Freq="30")
        assert rig.state["quiet_start"] is True
        assert rig.loop.state.quiet_level == 2


class TestFeatures:
    """The feature overview."""

    def test_states(self, make_settings: Callable[..., Settings]) -> None:
        """Feature views list every feature in order with its state for the active setup."""
        settings = make_settings(**HA, control_mode="auto", control_summer_enabled=True)
        rig = Rig(settings)
        rig.tick()
        rig.loop.request_away(
            target_c=None, until=rig.wall + timedelta(days=1), lead_s=None, actor="owner"
        )
        rig.tick()
        states = {view.feature: view.state for view in feature_views(rig.loop, settings)}
        assert list(states) == list(Feature)
        assert states[Feature.AWAY] is FeatureState.ACTIVE_NOW
        assert states[Feature.BOOST] is FeatureState.ON
        assert states[Feature.STOVE] is FeatureState.OFF
        assert states[Feature.SUMMER] is FeatureState.ON
        assert states[Feature.DAYSHIFT] is FeatureState.OFF

    def test_shadow_mode(self, make_settings: Callable[..., Settings]) -> None:
        """In shadow mode weather compensation shows as shadow and the start alarm as on."""
        settings = make_settings(**HA)
        rig = Rig(settings)
        rig.tick()
        states = {view.feature: view.state for view in feature_views(rig.loop, settings)}
        assert states[Feature.WEATHER_COMPENSATION] is FeatureState.SHADOW
        assert states[Feature.STARTS_ALARM] is FeatureState.ON


class TestApi:
    """The boost, away and features HTTP endpoints."""

    def rig(self, settings: Settings) -> tuple[TestClient, ControlLoop, ConfigManager]:
        """Build a test client, control loop and config manager around ``settings``."""
        clock = FakeClock(T0)
        manager = ConfigManager.open(settings, clock)
        runtime = Runtime(clock=clock)
        loop, _ = build_control(manager.settings, runtime, None, sleep=no_sleep)
        app = create_app(runtime, manager.settings, control=loop, config=manager)
        return TestClient(app), loop, manager

    def test_boost_and_away(self, make_settings: Callable[..., Settings]) -> None:
        """Boost and away endpoints validate input, need authentication and are audited."""
        settings = make_settings(**HA, operate_token=TOKEN)
        client, loop, manager = self.rig(settings)
        until = iso(datetime.fromtimestamp(T0 + 2 * 86_400.0, UTC))
        with client:
            assert client.get("/api/v1/control/boost").json()["active"] is False
            ok = client.post("/api/v1/control/boost", json={"offset_k": 0.5}, headers=OPERATE)
            assert ok.status_code == 200
            assert ok.json()["boost"]["shift_k"] == 0.5
            assert client.get("/api/v1/control/boost").json()["active"] is True
            for bad in ({"offset_k": "1"}, {"offset_k": True}, {"until": "soon"}, {"offset_k": 9}):
                response = client.post("/api/v1/control/boost", json=bad, headers=OPERATE)
                assert response.status_code == 400
            away = client.put("/api/v1/control/away", json={"until": until}, headers=OPERATE)
            assert away.status_code == 200
            assert away.json()["away"]["phase"] == "away"
            assert loop.targets.boost is None
            refused = client.post("/api/v1/control/boost", json={}, headers=OPERATE)
            assert refused.status_code == 409
            assert client.put("/api/v1/control/away", json={}, headers=OPERATE).status_code == 400
            features = client.get("/api/v1/control/features").json()
            assert [entry["id"] for entry in features["features"]] == [f.value for f in Feature]
            ended = client.request("DELETE", "/api/v1/control/away", json={}, headers=OPERATE)
            assert ended.status_code == 200
            assert ended.json()["request"]["target_c"] == 16.0
            assert ended.json()["away"]["active"] is False
            none = client.request("DELETE", "/api/v1/control/boost", json={}, headers=OPERATE)
            assert none.json()["request"] is None
            status = client.get("/api/v1/decisions/latest").json()
            unauthorised = client.post("/api/v1/control/boost", json={}, headers={})
        assert unauthorised.status_code in (401, 403)
        assert status is not None
        actions = [e.action for e in manager.store.audit_events(0.0, T0 + 86_400.0, 100)]
        assert actions.count("boost") == 1
        assert actions.count("away") == 1
        assert actions.count("away_end") == 1

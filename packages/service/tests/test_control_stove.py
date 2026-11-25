"""Wood-stove mode in the service: settings, the manual request, journal, alarms, API."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ovenbird.api.app import create_app
from ovenbird.config import ConfigError, Settings
from ovenbird.configstore import ConfigManager
from ovenbird.control import AlarmCode, ControlLoop
from ovenbird.control.alarms import AlarmBoard, AlarmEventKind
from ovenbird.control.persist import decode_state, encode_state
from ovenbird.history import AlarmRow, StateRow, open_history
from ovenbird.history.journal import write_journal
from ovenbird.mqtt import MqttIngest
from ovenbird.runtime import Runtime
from ovenbird.service import build_control
from ovenbird.stove.request import (
    STOVE_JOURNAL_CODE,
    STOVE_KEY,
    StoveRequest,
    StoveRequestError,
    encode_request,
    load_request,
)
from ovenbird.testing import FakeClock, pump_messages
from ovenbird_core import StateStore, ha_reading
from ovenbird_core.control import StoveSource

T0 = 1_800_000_000.0
ROOM = "sensor.living_room_temperature"
HALL = "sensor.hall_temperature"
ROOM_ID = f"ha/{ROOM}"
HALL_ID = f"ha/{HALL}"
HA: dict[str, Any] = {
    "ha_url": "http://ha.local:8123",
    "ha_token": "token",
    "ha_entities": (ROOM,),
    "control_room_signal": ROOM_ID,
    "control_comfort_c": 21.0,
}
STOVE: dict[str, Any] = {**HA, "control_stove_enabled": True}
TOKEN = "operate-token-" + "x" * 24
BEARER = {"Authorization": f"Bearer {TOKEN}"}
MARK = {"X-Ovenbird-Request": "1"}
ALL_TIME = {"from": "2000-01-01T00:00:00Z", "to": "2100-01-01T00:00:00Z"}


async def no_sleep(_: float) -> None:
    return None


class Journal:
    def __init__(self) -> None:
        self.states: list[StateRow] = []
        self.alarms: list[AlarmRow] = []

    def offer_decision(self, row: Any) -> None:
        return None

    def offer_command(self, row: Any) -> None:
        return None

    def offer_alarm(self, row: AlarmRow) -> None:
        self.alarms.append(row)

    def offer_state(self, row: StateRow) -> None:
        self.states.append(row)


class SavingJournal(Journal):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    def offer_state(self, row: StateRow) -> None:
        super().offer_state(row)
        write(self.path, row)


class Rig:
    def __init__(
        self, settings: Settings, journal: Journal | None = None, start: float = T0
    ) -> None:
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
        )

    def tick(self, room: float, minutes: int = 1, **pump: str) -> None:
        for _ in range(minutes):
            for message in pump_messages(**pump):
                self.ingest.ingest(message)
            self.runtime.apply(ha_reading(ROOM, f"{room:.1f}", instant=self.clock()))
            self.loop.tick()
            self.clock.advance(60.0)

    def warm(self, start: float, end: float, minutes: int = 30, **pump: str) -> None:
        for step in range(1, minutes + 1):
            self.tick(start + (end - start) * step / minutes, 1, **pump)

    def hall(self, value: float) -> None:
        self.runtime.apply(ha_reading(HALL, f"{value:.1f}", instant=self.clock()))

    @property
    def state(self) -> dict[str, Any]:
        return self.loop.latest_state or {}


class TestSettings:
    def test_off_by_default(self, make_settings: Callable[..., Settings]) -> None:
        settings = make_settings(**HA)
        assert settings.controller_config().stove is None
        assert settings.stove_config() is None

    def test_fields_reach_the_controller(self, make_settings: Callable[..., Settings]) -> None:
        settings = make_settings(
            **STOVE,
            control_stove_backoff_k=4.0,
            control_stove_rise_enabled=False,
            control_stove_max_active_s=6 * 3600.0,
            control_stove_reference_signal=HALL_ID,
            control_stove_reference_floor_c=19.2,
        )
        stove = settings.controller_config().stove
        assert stove is not None
        assert stove.backoff_k == 4.0
        assert stove.rise_k is None
        assert stove.max_active_s == 6 * 3600.0
        assert stove.reentry_hold_s == 900.0
        assert make_settings(**STOVE).controller_config().stove.max_active_s == 8 * 3600.0  # type: ignore[union-attr]
        assert stove.reference == HALL_ID
        assert stove.reference_floor_c == 19.2
        assert settings.ha_subscriptions == (ROOM, HALL)

    @pytest.mark.parametrize(
        ("overrides", "match"),
        [
            (
                {"control_stove_enter_above_k": 1.0, "control_stove_exit_hysteresis_k": 1.5},
                "exit_hysteresis_k must not exceed",
            ),
            (
                {
                    "control_stove_min_active_s": 5 * 3600.0,
                    "control_stove_max_active_s": 4 * 3600.0,
                },
                "min_active_s must not exceed",
            ),
            ({"control_stove_reference_signal": ROOM_ID}, "another room"),
            ({"control_stove_reference_signal": "hall_temperature"}, "stove reference signal"),
            (
                {"control_stove_reference_signal": "ha/binary_sensor.hall_door"},
                "not a room temperature",
            ),
            (
                {
                    "mqtt_inputs": [{"topic": "hall/humidity", "signal": "hall", "unit": "%"}],
                    "control_stove_reference_signal": "hall",
                },
                "not a room temperature",
            ),
        ],
    )
    def test_rejected(
        self, make_settings: Callable[..., Settings], overrides: dict[str, Any], match: str
    ) -> None:
        with pytest.raises(ConfigError, match=match):
            make_settings(**STOVE, **overrides)

    def test_detection_needs_a_room_signal(self, make_settings: Callable[..., Settings]) -> None:
        with pytest.raises(ConfigError, match="needs control_room_signal"):
            make_settings(control_stove_enabled=True)
        manual = make_settings(control_stove_enabled=True, control_stove_auto=False)
        stove = manual.controller_config().stove
        assert stove is not None
        assert not stove.auto


class TestLoop:
    def test_entry_and_exit_are_journalled(self, make_settings: Callable[..., Settings]) -> None:
        rig = Rig(make_settings(**STOVE))
        rig.tick(21.7, 40)
        rig.tick(23.2, 70)
        assert rig.loop.state.stove_source is StoveSource.AUTO
        assert rig.loop.stove_status()["active"] is True
        assert rig.loop.status()["stove"]["backoff_k"] == pytest.approx(3.0)
        rig.tick(21.2, 2)
        assert not rig.loop.state.stove_active
        events = [a for a in rig.journal.alarms if a.code == STOVE_JOURNAL_CODE]
        assert [e.event for e in events] == [
            AlarmEventKind.STARTED.value,
            AlarmEventKind.EXPIRED.value,
        ]
        assert events[0].severity == "info"
        assert "wood-stove mode on (auto, level at 23.2 °C)" in events[0].message
        assert json.loads(events[1].detail)["exit"] == "cooled"

    def test_no_room_implausible_alarm_from_the_stove(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        rig = Rig(
            make_settings(
                **STOVE,
                control_room_crosscheck_signal="main/Room_Thermostat_Temp",
            )
        )
        rig.tick(21.0, 30, Room_Thermostat_Temp="22")
        rig.warm(21.0, 25.1, Room_Thermostat_Temp="22")
        rig.tick(25.1, 3 * 60, Room_Thermostat_Temp="22")
        assert rig.loop.state.stove_active
        assert not rig.loop.alarms.is_active(AlarmCode.ROOM_IMPLAUSIBLE)
        assert rig.state["room_plausible"] is True

    def test_a_manual_request_keeps_room_implausible(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        rig = Rig(
            make_settings(
                **STOVE,
                control_stove_rise_enabled=False,
                control_room_crosscheck_signal="main/Room_Thermostat_Temp",
            )
        )
        rig.tick(20.2, 60, Room_Thermostat_Temp="21")
        rig.warm(20.2, 22.2, Room_Thermostat_Temp="21")
        rig.tick(22.2, 2 * 60 + 5, Room_Thermostat_Temp="21")
        assert rig.loop.alarms.is_active(AlarmCode.ROOM_IMPLAUSIBLE)
        rig.loop.request_stove(True, rig.clock().wall + timedelta(minutes=5), "owner")
        rig.tick(22.2, 5, Room_Thermostat_Temp="21")
        assert rig.loop.state.stove_source is StoveSource.MANUAL
        assert rig.loop.alarms.is_active(AlarmCode.ROOM_IMPLAUSIBLE)
        rig.tick(22.2, 60, Room_Thermostat_Temp="21")
        assert not rig.loop.state.stove_active
        assert rig.loop.alarms.is_active(AlarmCode.ROOM_IMPLAUSIBLE)

    def test_a_missing_reference_room_halves_the_backoff_and_raises_an_alarm(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        code = AlarmCode.STOVE_REFERENCE_MISSING
        rig = Rig(make_settings(**STOVE, control_stove_reference_signal=HALL_ID))
        rig.tick(21.7, 10)
        assert not rig.loop.alarms.is_active(code)
        rig.tick(23.2, 3)
        assert rig.loop.state.stove_active
        assert rig.state["stove_backoff_k"] == pytest.approx(1.5)
        alarm = rig.loop.alarms.get(code)
        assert alarm is not None
        assert alarm.severity.value == "warning"
        assert HALL_ID in alarm.message
        assert "50 %" in alarm.message
        rig.hall(19.7)
        rig.tick(23.2)
        assert not rig.loop.alarms.is_active(code)
        assert rig.state["stove_backoff_k"] == pytest.approx(3.0)
        rig.tick(23.2, 40)
        assert rig.loop.alarms.is_active(code)
        rig.tick(20.2, 70)
        assert not rig.loop.state.stove_active
        assert not rig.loop.alarms.is_active(code)

    def test_manual_request_until_and_persistence(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        rig = Rig(make_settings(**STOVE))
        rig.tick(21.0, 2)
        until = rig.clock().wall + timedelta(minutes=30)
        request = rig.loop.request_stove(True, until, "owner")
        assert rig.journal.states[-1].key == STOVE_KEY
        assert json.loads(rig.journal.states[-1].value) == request.to_json()
        rig.tick(21.0)
        assert rig.loop.state.stove_source is StoveSource.MANUAL
        assert rig.state["stove_until"] == until.isoformat()
        rig.tick(21.0, 31)
        assert not rig.loop.state.stove_active
        assert rig.loop.stove_request is None
        stored = [row for row in rig.journal.states if row.key == STOVE_KEY]
        assert json.loads(stored[-1].value) is None

    def test_the_request_carries_no_client_address(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        rig = Rig(make_settings(**STOVE))
        rig.tick(21.0, 2)
        request = rig.loop.request_stove(True, None, "operate from 192.168.1.20")
        assert request.actor == "operate"
        assert "192.168" not in json.dumps(rig.loop.stove_status())
        assert "192.168" not in rig.journal.states[-1].value
        row = rig.loop.tick()
        assert "192.168" not in row.record
        stored = StoveRequest.from_json(
            {**request.to_json(), "actor": "admin from fe80::1ff:fe23:4567:890a"}
        )
        assert stored.actor == "admin"

    def test_a_start_without_an_end_lasts_eight_hours_at_most_the_cap(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        rig = Rig(make_settings(**STOVE))
        request = rig.loop.request_stove(True, None, "owner")
        assert request.until == rig.clock().wall + timedelta(hours=8)
        capped = Rig(make_settings(**STOVE, control_stove_max_active_s=2 * 3600.0))
        request = capped.loop.request_stove(True, None, "owner")
        assert request.until == capped.clock().wall + timedelta(hours=2)

    def test_one_shot_stop(self, make_settings: Callable[..., Settings]) -> None:
        rig = Rig(make_settings(**STOVE))
        rig.tick(24.2, 10)
        assert rig.loop.state.stove_active
        rig.loop.request_stove(False, None, "owner")
        rig.tick(24.2)
        assert not rig.loop.state.stove_active
        assert rig.loop.state.stove_blocked
        assert rig.loop.stove_request is None
        rig.tick(24.2, 30)
        assert not rig.loop.state.stove_active
        events = [a for a in rig.journal.alarms if a.code == STOVE_JOURNAL_CODE]
        assert events[-1].event == AlarmEventKind.RELEASED.value

    def test_refused_requests(self, make_settings: Callable[..., Settings]) -> None:
        disabled = Rig(make_settings(**HA))
        with pytest.raises(StoveRequestError, match="not enabled"):
            disabled.loop.request_stove(True, None, "owner")
        rig = Rig(make_settings(**STOVE))
        now = rig.clock().wall
        with pytest.raises(StoveRequestError, match="future"):
            rig.loop.request_stove(True, now - timedelta(minutes=1), "owner")
        with pytest.raises(StoveRequestError, match="24 h"):
            rig.loop.request_stove(True, now + timedelta(hours=25), "owner")


class TestSession:
    def test_a_rebound_state_sink_and_alarm_board_are_used(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        rig = Rig(make_settings(**STOVE))
        rig.tick(21.0, 2)
        later = Journal()
        board = AlarmBoard()
        rig.loop.state_sink = later.offer_state
        rig.loop.alarms = board
        before = len(rig.journal.states)
        until = rig.clock().wall + timedelta(minutes=10)
        request = rig.loop.request_stove(True, until, "owner")
        assert [row.key for row in later.states] == [STOVE_KEY]
        assert json.loads(later.states[0].value) == request.to_json()
        rig.tick(21.0)
        assert rig.loop.state.stove_source is StoveSource.MANUAL
        started = [e for e in board.history if e.code == STOVE_JOURNAL_CODE]
        assert [e.event for e in started] == [AlarmEventKind.STARTED]
        rig.tick(21.0, 11)
        assert rig.loop.stove_request is None
        stove_rows = [row for row in later.states if row.key == STOVE_KEY]
        assert json.loads(stove_rows[-1].value) is None
        assert len(rig.journal.states) == before
        assert not [a for a in rig.journal.alarms if a.code == STOVE_JOURNAL_CODE]

    def test_assigning_the_request_does_not_save_it(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        rig = Rig(make_settings(**STOVE))
        now = rig.clock().wall
        request = StoveRequest(True, now + timedelta(minutes=5), "owner", now)
        rig.loop.stove_request = request
        assert rig.loop.stove_request is request
        assert rig.loop.stove.request is request
        assert not rig.journal.states


class TestPersistence:
    def test_a_saved_request_survives_a_restart_and_expires_after_it(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        settings = make_settings(**STOVE)
        path = settings.history_path
        first = Rig(settings, SavingJournal(path))
        first.tick(21.0, 2)
        until = first.clock().wall + timedelta(minutes=30)
        request = first.loop.request_stove(True, until, "owner")
        first.tick(21.0, 5)
        assert first.loop.state.stove_source is StoveSource.MANUAL
        restart = first.clock().wall.timestamp() + 600.0
        second = Rig(settings, SavingJournal(path), start=restart)
        assert second.loop.stove_request == request
        second.tick(21.0)
        assert second.loop.state.stove_source is StoveSource.MANUAL
        assert second.state["stove_until"] == until.isoformat()
        second.tick(21.0, 14)
        assert second.loop.stove_request == request
        second.tick(21.0, 2)
        assert second.loop.stove_request is None
        assert not second.loop.state.stove_active
        stored = [row for row in second.journal.states if row.key == STOVE_KEY]
        assert json.loads(stored[-1].value) is None
        assert load_request(path, second.clock()) is None
        third = Rig(settings, Journal(), start=restart + 60.0)
        assert third.loop.stove_request is None

    def test_state_round_trip(self, make_settings: Callable[..., Settings]) -> None:
        rig = Rig(make_settings(**STOVE))
        rig.tick(24.2, 5)
        saved = rig.loop.state
        restored, _ = decode_state(encode_state(saved, rig.clock()), rig.clock(), 900.0)
        assert restored is not None
        assert restored.stove_source is StoveSource.AUTO
        assert restored.stove_trigger == saved.stove_trigger
        assert restored.stove_since == pytest.approx(saved.stove_since or 0.0)
        assert restored.stove_integral_k == saved.stove_integral_k

    def test_request_survives_a_restart(self, tmp_path: Path) -> None:
        path = tmp_path / "history.db"
        now = FakeClock(T0)()
        live = StoveRequest(True, now.wall + timedelta(hours=1), "owner", now.wall)
        write(path, StateRow(STOVE_KEY, T0, encode_request(live)))
        assert load_request(path, now) == live
        later = FakeClock(T0 + 2 * 3600.0)()
        assert load_request(path, later) is None
        write(path, StateRow(STOVE_KEY, T0, encode_request(None)))
        assert load_request(path, now) is None
        write(path, StateRow(STOVE_KEY, T0, "{not json"))
        assert load_request(path, now) is None


def write(path: Path, row: StateRow) -> None:
    conn = open_history(path)
    try:
        write_journal(conn, [], [], [], [row])
    finally:
        conn.close()


class TestApi:
    def rig(self, settings: Settings) -> tuple[TestClient, ControlLoop]:
        clock = FakeClock(T0)
        manager = ConfigManager.open(settings, clock)
        runtime = Runtime(clock=clock)
        loop, _ = build_control(manager.settings, runtime, None, sleep=no_sleep)
        app = create_app(runtime, manager.settings, control=loop, config=manager)
        return TestClient(app), loop

    def test_request_and_audit(self, make_settings: Callable[..., Settings]) -> None:
        settings = make_settings(**STOVE, operate_token=TOKEN)
        client, loop = self.rig(settings)
        headers = {**BEARER, **MARK}
        with client:
            until = datetime.fromtimestamp(T0 + 3600.0, UTC).isoformat().replace("+00:00", "Z")
            ok = client.post(
                "/api/v1/control/stove", json={"on": True, "until": until}, headers=headers
            )
            assert ok.status_code == 200
            body = ok.json()
            assert body["request"]["on"] is True
            assert body["request"]["until"] == until
            assert body["stove"]["enabled"] is True
            assert body["stove"]["request"] == body["request"]
            assert loop.stove_request is not None
            stop = client.post("/api/v1/control/stove", json={"on": False}, headers=headers)
            assert stop.status_code == 200
            assert stop.json()["request"]["until"] is None
            for bad in ({}, {"on": "yes"}, {"on": True, "until": "tomorrow"}):
                assert (
                    client.post("/api/v1/control/stove", json=bad, headers=headers).status_code
                    == 400
                )
            past = {"on": True, "until": "2000-01-01T00:00:00Z"}
            assert (
                client.post("/api/v1/control/stove", json=past, headers=headers).status_code == 400
            )
            latest = client.get("/api/v1/decisions/latest").json()
            assert latest["control"]["stove"]["enabled"] is True
            audit = client.get("/api/v1/audit", params=ALL_TIME, headers=BEARER)
        assert audit.status_code == 403
        events = loop_audit(settings)
        assert [e for e in events if e == "stove_request"] == ["stove_request", "stove_request"]

    def test_disabled_is_a_conflict(self, make_settings: Callable[..., Settings]) -> None:
        client, _ = self.rig(make_settings(**HA, operate_token=TOKEN))
        with client:
            response = client.post(
                "/api/v1/control/stove", json={"on": True}, headers={**BEARER, **MARK}
            )
        assert response.status_code == 409


def loop_audit(settings: Settings) -> list[str]:
    manager = ConfigManager.open(settings, FakeClock(T0))
    return [event.action for event in manager.store.audit_events(0.0, T0 + 86_400.0, 100)]

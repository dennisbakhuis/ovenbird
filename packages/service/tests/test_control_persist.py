from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ovenbird.config import Settings
from ovenbird.control.alarms import HOLD_JOURNAL_CODE, AlarmCode, AlarmEventKind
from ovenbird.control.persist import (
    STATE_KEY,
    decode_state,
    encode_state,
    load_state,
    restore_adapter,
)
from ovenbird.history import AlarmRow, CommandRow, StateRow, open_history
from ovenbird.history.journal import (
    HOLD_CODE,
    HOLD_RELEASED,
    delete_journal_before,
    read_state,
    write_journal,
)
from ovenbird.mqtt import MqttIngest
from ovenbird.runtime import Runtime
from ovenbird.service import build_control
from ovenbird.testing import FakeClock, pump_messages
from ovenbird_core import Instant
from ovenbird_core.control import OvenbirdState, RampPhase

T0 = datetime(2026, 1, 14, 12, tzinfo=UTC).timestamp()
PUBLISH: dict[str, Any] = {
    "control_mode": "auto",
    "allow_commands": True,
    "mqtt_host": "mosquitto",
    "command_brokers": ("mosquitto",),
}


def state(clock: FakeClock) -> OvenbirdState:
    now = clock.t
    return OvenbirdState(
        setpoint=31,
        last_change_at=now - 600.0,
        integral_k=1.25,
        outside_filtered=2.5,
        outside_at=now - 60.0,
        last_tick_at=now,
        running=True,
        run_started_at=now - 1800.0,
        stopped_at=None,
        ramp_phase=RampPhase.RELEASE,
        ramp_elapsed_s=900.0,
        ramp_cap=33.0,
        pump_duty=159,
        quiet_level=None,
    )


def test_state_round_trip_reanchors_times() -> None:
    saved_at = FakeClock(T0)
    text = encode_state(state(saved_at), saved_at())
    later = FakeClock(T0 + 120.0)
    later_mono = 5_000.0
    now = Instant(later_mono, later().wall)
    restored, why = decode_state(text, now, 900.0)
    assert restored is not None
    assert "120 s ago" in why
    assert restored.integral_k == 1.25
    assert restored.setpoint == 31
    assert restored.ramp_phase is RampPhase.RELEASE
    assert restored.running is True
    assert restored.stopped_at is None
    assert restored.last_tick_at == pytest.approx(later_mono - 120.0)
    assert restored.run_started_at == pytest.approx(later_mono - 1920.0)
    assert restored.last_change_at == pytest.approx(later_mono - 720.0)


def test_the_mark_of_a_lost_room_value_survives_a_restart() -> None:
    saved_at = FakeClock(T0)
    lost = replace(
        state(saved_at), integral_k=0.2, integral_at_life_k=0.9, room_lost_at=saved_at.t - 3600.0
    )
    text = encode_state(lost, saved_at())
    now = Instant(5_000.0, FakeClock(T0 + 60.0)().wall)
    restored, _ = decode_state(text, now, 900.0)
    assert restored is not None
    assert restored.integral_at_life_k == 0.9
    assert restored.room_lost_at == pytest.approx(5_000.0 - 3660.0)


@pytest.mark.parametrize(
    ("offset", "reason"),
    [(901.0, "old"), (-5.0, "future")],
)
def test_stale_or_future_state_is_ignored(offset: float, reason: str) -> None:
    clock = FakeClock(T0)
    text = encode_state(state(clock), clock())
    restored, why = decode_state(text, FakeClock(T0 + offset)(), 900.0)
    assert restored is None
    assert reason in why


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        json.dumps({"schema": 9}),
        json.dumps({"schema": 1, "wall": T0, "state": {"integral_k": "x"}}),
        json.dumps({"schema": 1, "wall": T0, "state": {"ramp_phase": "nope"}}),
        json.dumps({"schema": 1, "wall": T0}),
    ],
)
def test_unreadable_state_is_ignored(text: str) -> None:
    restored, _ = decode_state(text, FakeClock(T0)(), 900.0)
    assert restored is None


def write(path: Path, **rows: Any) -> None:
    conn = open_history(path)
    try:
        write_journal(
            conn,
            [],
            rows.get("commands", []),
            rows.get("alarms", []),
            rows.get("states", []),
        )
    finally:
        conn.close()


def sent(ts: float) -> CommandRow:
    return CommandRow(ts, "water_setpoint", 31, "sent", 1, "t", "31", "published")


def hold(ts: float, event: str, *, until: float | None = None, latched: bool = False) -> AlarmRow:
    detail = {"reason": "foreign writer", "until": until, "latched": latched, "incident": 1}
    return AlarmRow(ts, "command_hold", "warning", event, "hold", json.dumps(detail))


def test_restore_adapter_from_the_journal(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    midnight = datetime(2026, 1, 14, tzinfo=UTC).timestamp()
    write(
        path,
        commands=[sent(midnight - 10.0), sent(midnight + 10.0), sent(T0 - 5.0), sent(T0 + 99.0)],
        alarms=[
            hold(T0 - 7200.0, "started", until=T0 - 3600.0),
            hold(T0 - 3600.0, "expired"),
            hold(T0 - 600.0, "started", latched=True),
        ],
    )
    restored = restore_adapter(path, FakeClock(T0)())
    assert restored.sent_today == 2
    assert restored.day is not None
    assert restored.day.isoformat() == "2026-01-14"
    assert restored.incidents == (T0 - 7200.0, T0 - 600.0)
    assert restored.hold is not None
    assert restored.hold.latched


def test_a_release_resets_the_incidents(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    write(
        path,
        alarms=[
            hold(T0 - 7200.0, "started", latched=True),
            hold(T0 - 3600.0, "released"),
            hold(T0 - 60.0, "started", until=T0 + 540.0),
        ],
    )
    restored = restore_adapter(path, FakeClock(T0)())
    assert restored.incidents == (T0 - 60.0,)
    assert restored.hold is not None
    assert restored.hold.until is not None
    assert restored.hold.until.timestamp() == T0 + 540.0


def test_retention_keeps_an_unreleased_hold(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    day = 86_400.0
    write(
        path,
        alarms=[
            hold(T0 - 30 * day, "started", latched=True),
            hold(T0 - 29 * day, "released"),
            hold(T0 - 20 * day, "started", until=T0 - 19 * day),
            hold(T0 - 19 * day, "expired"),
            hold(T0 - 10 * day, "started", latched=True),
            AlarmRow(T0 - 10 * day, "low_flow", "critical", "raised", "low flow", "{}"),
        ],
    )
    conn = open_history(path)
    try:
        deleted = delete_journal_before(conn, T0 - day)
        conn.commit()
    finally:
        conn.close()
    assert deleted == 2
    restored = restore_adapter(path, FakeClock(T0)())
    assert restored.hold is not None
    assert restored.hold.latched
    assert restored.incidents == (T0 - 20 * day, T0 - 10 * day)


def test_the_retention_hold_codes_match_the_alarm_board() -> None:
    assert HOLD_CODE == HOLD_JOURNAL_CODE
    assert AlarmEventKind.RELEASED.value == HOLD_RELEASED


def test_no_journal_restores_nothing(tmp_path: Path) -> None:
    restored = restore_adapter(tmp_path / "missing.db", FakeClock(T0)())
    assert restored.sent_today == 0
    assert restored.hold is None
    assert load_state(tmp_path / "missing.db", FakeClock(T0)(), 900.0) is None


def test_state_rows_are_replaced_per_key(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    write(path, states=[StateRow(STATE_KEY, T0, "a"), StateRow(STATE_KEY, T0 + 1, "b")])
    write(path, states=[StateRow(STATE_KEY, T0 + 2, "c")])
    row = read_state(path, STATE_KEY)
    assert row is not None
    assert (row.ts, row.value) == (T0 + 2, "c")


async def no_sleep(_: float) -> None:
    return None


def test_build_control_restores_state_budget_and_latched_hold(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(**PUBLISH)
    settings.data_dir.mkdir(parents=True)
    clock = FakeClock(T0)
    saved = FakeClock(T0 - 120.0)
    write(
        settings.history_path,
        commands=[sent(T0 - 100.0), sent(T0 - 50.0)],
        alarms=[hold(T0 - 300.0, "started", latched=True)],
        states=[StateRow(STATE_KEY, saved.t, encode_state(state(saved), saved()))],
    )
    loop, worker = build_control(settings, Runtime(clock=clock), None, sleep=no_sleep)
    assert worker is not None
    assert loop.restored
    assert loop.state.integral_k == 1.25
    adapter = loop.adapter
    assert adapter is not None
    assert adapter.status()["budget"]["used"] == 2
    assert adapter.status()["hold_latched"] is True
    assert loop.alarms.is_active(AlarmCode.HOLD_LATCHED)
    assert loop.status()["restored_state"] is True


def test_build_control_ignores_a_stale_state(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(control_state_max_age_s=60.0)
    settings.data_dir.mkdir(parents=True)
    saved = FakeClock(T0 - 120.0)
    write(
        settings.history_path,
        states=[StateRow(STATE_KEY, saved.t, encode_state(state(saved), saved()))],
    )
    loop, _ = build_control(settings, Runtime(clock=FakeClock(T0)), None, sleep=no_sleep)
    assert not loop.restored
    assert loop.state == OvenbirdState()


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


def test_every_tick_saves_the_state_and_a_restart_continues_from_it(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings()
    clock = FakeClock(T0)
    runtime = Runtime(clock=clock)
    ingest = MqttIngest(settings, runtime)
    journal = Journal()
    loop, _ = build_control(settings, runtime, journal, sleep=no_sleep)  # type: ignore[arg-type]
    for _ in range(3):
        for message in pump_messages():
            ingest.ingest(message)
        loop.tick()
        clock.advance(60.0)
    assert len(journal.states) == 3
    assert journal.states[-1].key == STATE_KEY
    restored, _ = decode_state(journal.states[-1].value, clock(), 900.0)
    assert restored is not None
    assert restored.setpoint == loop.state.setpoint
    assert restored.outside_filtered == loop.state.outside_filtered
    assert restored.last_tick_at == pytest.approx(loop.state.last_tick_at or 0.0)

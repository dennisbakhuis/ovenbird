from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ovenbird.api.app import create_app
from ovenbird.api.ws import Broadcaster, Channel
from ovenbird.clock import ScaledClock, build_clock, sleeper, system_clock
from ovenbird.config import Settings
from ovenbird.control import AlarmBoard, ControlLoop, PublishGuard, controller_config
from ovenbird.history import (
    CommandRow,
    DecisionRow,
    HistoryWriter,
    Retention,
    latest_decision,
    open_history,
    query_commands,
    query_decisions,
)
from ovenbird.history.journal import write_journal
from ovenbird.history.schema import bundled_migrations, user_version
from ovenbird.mqtt import MqttIngest
from ovenbird.runtime import Runtime
from ovenbird.testing import FakeClock, inbound, pump_messages
from ovenbird_core import Instant
from ovenbird_core.control import (
    DecisionRecord,
    LadderLevel,
    Mode,
    OvenbirdController,
    ReasonCode,
    control_inputs,
)

T0 = 1_800_000_000.0


class Sink:
    """Journal sink that records offered decision and command rows in memory."""

    def __init__(self) -> None:
        """Start with empty decision and command lists."""
        self.decisions: list[DecisionRow] = []
        self.commands: list[CommandRow] = []

    def offer_decision(self, row: DecisionRow) -> None:
        """Record a decision row."""
        self.decisions.append(row)

    def offer_command(self, row: CommandRow) -> None:
        """Record a command row."""
        self.commands.append(row)


def decision_row(ts: float, setpoint: int = 30) -> DecisionRow:
    """Build a shadow-mode curve-only decision row with the given setpoint."""
    record = DecisionRecord(
        at=Instant(ts, datetime.fromtimestamp(ts, UTC)),
        controller="ovenbird",
        mode=Mode.SHADOW,
        ladder=LadderLevel.CURVE_ONLY,
        terms=(),
        pre_round=float(setpoint),
        setpoint=setpoint,
        binding=None,
        flip_distance=None,
        inputs_used=(),
        controller_state={},
        reason=ReasonCode.CURVE,
        note=f"setpoint {setpoint}",
    ).to_json_dict()
    return DecisionRow(
        ts, "ovenbird", "shadow", "curve_only", "curve", setpoint, json.dumps(record), "[]", "[]"
    )


def command_row(ts: float, status: str = "sent") -> CommandRow:
    """Build a water setpoint command row with the given status."""
    return CommandRow(ts, "water_setpoint", 31, status, 1, "t", "31", "detail")


def make_loop(
    settings: Settings, clock: FakeClock, sink: Sink | None = None, **kwargs: Any
) -> tuple[ControlLoop, Runtime]:
    """Build a control loop and its runtime from settings.

    Parameters
    ----------
    settings
        Service settings that select mode, guard and room signal.
    clock
        Fake clock driving the runtime.
    sink
        Optional journal sink receiving decisions and commands.
    **kwargs
        Extra ``ControlLoop`` arguments such as ``on_decision`` or ``adapter``.

    Returns
    -------
    tuple[ControlLoop, Runtime]
        The loop and the runtime it reads from.
    """
    runtime = Runtime(clock=clock)
    loop = ControlLoop(
        runtime,
        OvenbirdController(controller_config(settings)),
        mode=Mode(settings.control_mode),
        guard=PublishGuard.from_settings(settings),
        alarms=AlarmBoard(),
        sink=sink,
        room_signal=settings.control_room_signal,
        **kwargs,
    )
    return loop, runtime


def feed(settings: Settings, runtime: Runtime, **overrides: str) -> None:
    """Ingest the standard simulated pump messages, with optional payload overrides."""
    ingest = MqttIngest(settings, runtime)
    for message in pump_messages(**overrides):
        ingest.ingest(message)


def test_migration_adds_decision_and_command_tables(tmp_path: Path) -> None:
    """Opening a history database creates the journal tables at the latest schema version."""
    conn = open_history(tmp_path / "history.db")
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"decision", "command", "sample", "signal", "rollup"} <= tables
    assert user_version(conn) == len(bundled_migrations())
    conn.close()


def test_writer_stores_journal_rows_and_applies_retention(tmp_path: Path) -> None:
    """The writer stores journal rows and prunes decisions older than the journal retention."""
    path = tmp_path / "history.db"
    writer = HistoryWriter(
        path, Retention(), min_free_bytes=0, wall=lambda: T0 + 40 * 86_400, journal_days=30
    )
    writer.offer_decision(decision_row(T0, 30))
    writer.offer_decision(decision_row(T0 + 35 * 86_400, 31))
    writer.offer_command(command_row(T0 + 35 * 86_400))
    writer.offer_decision(decision_row(T0 + 35 * 86_400 + 60, 32))
    writer.run_once([])
    batch = []
    while len(writer._queue):
        batch += writer._queue.drain(0.0, 100)
    writer._next_retention = float("inf")
    writer.run_once(batch)
    assert writer.stats.journal_written == 4
    writer._next_retention = 0.0
    writer.run_once([])
    writer._close()
    rows = query_decisions(path, 0.0, T0 + 50 * 86_400, 10)
    assert [r.setpoint for r in rows] == [31, 32]
    assert [r.setpoint for r in query_decisions(path, 0.0, T0 + 50 * 86_400, 1)] == [32]
    latest = latest_decision(path)
    assert latest is not None
    assert latest.setpoint == 32
    assert [c.status for c in query_commands(path, 0.0, T0 + 50 * 86_400, 10)] == ["sent"]


def test_queries_on_a_missing_database(tmp_path: Path) -> None:
    """Journal queries on a missing database return empty results."""
    assert query_decisions(tmp_path / "none.db", 0, 1, 10) == []
    assert latest_decision(tmp_path / "none.db") is None
    assert query_commands(tmp_path / "none.db", 0, 1, 10) == []


def test_tick_records_a_decision_and_broadcasts_it(make_settings: Callable[..., Settings]) -> None:
    """A tick journals and pushes a decision, and reports refusals while not publishing."""
    settings = make_settings()
    clock = FakeClock(T0)
    sink = Sink()
    pushed: list[dict[str, Any]] = []
    loop, runtime = make_loop(settings, clock, sink, on_decision=pushed.append)
    refused = loop.tick()
    assert refused.ladder == "refuse"
    assert refused.reason == "heishamon_dead"
    feed(settings, runtime, Z1_Water_Target_Temp="28")
    row = loop.tick()
    assert row.mode == "shadow"
    assert row.ladder == "curve_only"
    assert row.setpoint is not None
    payload = pushed[-1]
    assert payload == loop.latest
    assert payload["at"] == "2027-01-15T08:00:00Z"
    assert payload["record"]["controller"] == "ovenbird"
    assert payload["note"] == payload["record"]["note"]
    entries = {entry["kind"]: entry for entry in payload["arbiter"]}
    assert set(entries) <= {"water_setpoint", "max_pump_duty"}
    arbiter = entries["water_setpoint"]
    assert arbiter["actual"] == 28
    assert arbiter["action"] == "send"
    assert payload["commands"] == []
    assert len(sink.decisions) == 2
    status = loop.status()
    assert status["ticks"] == 2
    assert status["publishing"] is False
    assert len(status["refusals"]) == 3


def test_room_signal_is_used(make_settings: Callable[..., Settings]) -> None:
    """A configured room signal moves the ladder to feedback and is listed among the inputs used."""
    settings = make_settings(
        control_room_signal="room_temperature",
        mqtt_inputs=[{"topic": "sim/room", "signal": "room_temperature", "unit": "°C"}],
    )
    clock = FakeClock(T0)
    loop, runtime = make_loop(settings, clock)
    feed(settings, runtime)
    ingest = MqttIngest(settings, runtime)
    ingest.ingest(inbound("sim/room", "20.2"))
    row = loop.tick()
    assert row.ladder == "schedule_curve_feedback"
    record = json.loads(row.record)
    assert any(ref["signal"] == "room_temperature" for ref in record["inputs_used"])


def test_loop_rejects_an_adapter_without_permission(make_settings: Callable[..., Settings]) -> None:
    """A loop refuses an adapter when no adapter is permitted by the settings."""
    settings = make_settings()
    with pytest.raises(ValueError, match="adapter"):
        make_loop(settings, FakeClock(), adapter=object())


@pytest.fixture
def api(
    make_settings: Callable[..., Settings], tmp_path: Path
) -> Iterator[tuple[TestClient, ControlLoop, Settings]]:
    """Yield a test client, loop and settings over a journal seeded with decisions and commands."""
    settings = make_settings()
    clock = FakeClock(T0 + 3600)
    loop, runtime = make_loop(settings, clock)
    conn = open_history(settings.history_path)
    write_journal(
        conn,
        [decision_row(T0 + i * 60, 30 + i % 3) for i in range(30)],
        [command_row(T0 + 120), command_row(T0 + 125, "verified")],
    )
    conn.close()
    with TestClient(create_app(runtime, settings, control=loop)) as client:
        yield client, loop, settings


def test_decisions_endpoint(api: tuple[TestClient, ControlLoop, Settings]) -> None:
    """The decisions endpoint serves windowed rows with limits and rejects invalid parameters."""
    client, _, _ = api
    body = client.get("/api/v1/decisions").json()
    assert body["to"] == "2027-01-15T09:00:00Z"
    assert body["limit"] == 500
    assert len(body["decisions"]) == 30
    assert body["decisions"][0]["at"] == "2027-01-15T08:00:00Z"
    windowed = client.get(
        "/api/v1/decisions",
        params={"from": "2027-01-15T08:10:00Z", "to": "2027-01-15T08:20:00Z", "limit": 3},
    ).json()
    assert [d["at"] for d in windowed["decisions"]] == [
        "2027-01-15T08:17:00Z",
        "2027-01-15T08:18:00Z",
        "2027-01-15T08:19:00Z",
    ]
    assert set(windowed["decisions"][0]) == {
        "at",
        "controller",
        "mode",
        "ladder",
        "reason",
        "setpoint",
        "note",
        "arbiter",
        "commands",
        "config_version",
        "record",
    }
    assert client.get("/api/v1/decisions", params={"limit": 0}).status_code == 422
    assert client.get("/api/v1/decisions", params={"limit": 5001}).status_code == 422
    bad = client.get("/api/v1/decisions", params={"from": "2027-01-16", "to": "2027-01-15"})
    assert bad.status_code == 400


def test_latest_prefers_the_live_loop_then_the_database(
    api: tuple[TestClient, ControlLoop, Settings],
) -> None:
    """The latest decision comes from the database until the live loop has ticked."""
    client, loop, _ = api
    body = client.get("/api/v1/decisions/latest").json()
    assert body["decision"]["at"] == "2027-01-15T08:29:00Z"
    assert body["control"]["mode"] == "shadow"
    assert body["control"]["alarms"] == []
    loop.tick()
    live = client.get("/api/v1/decisions/latest").json()
    assert live["decision"]["at"] == "2027-01-15T09:00:00Z"
    assert live["decision"]["reason"] == "heishamon_dead"


def test_commands_endpoint(api: tuple[TestClient, ControlLoop, Settings]) -> None:
    """The commands endpoint lists journalled commands in time order."""
    client, _, _ = api
    body = client.get("/api/v1/commands").json()
    assert [c["status"] for c in body["commands"]] == ["sent", "verified"]
    assert body["commands"][0]["at"] == "2027-01-15T08:02:00Z"


def test_latest_without_a_control_loop(
    make_settings: Callable[..., Settings],
) -> None:
    """Without a control loop the decision endpoints answer empty."""
    settings = make_settings()
    with TestClient(create_app(Runtime(), settings)) as client:
        assert client.get("/api/v1/decisions/latest").json() == {"decision": None, "control": None}
        assert client.get("/api/v1/decisions").json()["decisions"] == []


def test_decisions_are_pushed_on_the_websocket() -> None:
    """A published decision is queued on websocket channels as a decision message."""
    broadcaster = Broadcaster(Runtime())
    channel = Channel()
    broadcaster.channels.add(channel)
    broadcaster.publish_decision({"setpoint": 31})
    assert json.loads(channel.pending["decision"]) == {"type": "decision", "data": {"setpoint": 31}}


def test_scaled_clock() -> None:
    """A scaled clock multiplies elapsed time and validates its speed and construction."""
    real = [100.0]
    start = datetime(2026, 11, 7, tzinfo=UTC)
    clock = ScaledClock(60.0, start, monotonic=lambda: real[0])
    assert clock().wall == start
    real[0] += 2.0
    assert clock().wall == datetime(2026, 11, 7, 0, 2, tzinfo=UTC)
    assert clock().monotonic == 100.0 + 120.0
    assert build_clock(1.0, None) is system_clock
    assert isinstance(build_clock(60.0, None), ScaledClock)
    assert isinstance(build_clock(1.0, start), ScaledClock)
    assert sleeper(system_clock) is asyncio.sleep
    with pytest.raises(ValueError, match="speed"):
        ScaledClock(0.0)


async def test_scaled_sleep_is_shorter() -> None:
    """Sleeping on a scaled clock waits for the scaled duration."""
    clock = ScaledClock(1000.0)
    before = clock()
    await sleeper(clock)(5.0)
    assert clock().since(before) >= 5.0


def test_history_window_uses_the_service_clock(make_settings: Callable[..., Settings]) -> None:
    """The history endpoint ends its default window at the service clock's now."""
    settings = make_settings()
    clock = FakeClock(T0)
    with TestClient(create_app(Runtime(clock=clock), settings)) as client:
        body = client.get("/api/v1/history", params={"signals": "main/Outside_Temp"}).json()
    assert body["to"] == "2027-01-15T08:00:00Z"


def test_decision_table_survives_reopen(tmp_path: Path) -> None:
    """Reopening a history database keeps the schema version."""
    path = tmp_path / "history.db"
    open_history(path).close()
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(bundled_migrations())
    conn.close()
    open_history(path).close()


def test_plan_context_trusts_a_fresh_plausible_room_and_gets_no_plan(
    make_settings: Callable[..., Settings],
) -> None:
    """Plan context trusts a fresh plausible room, then distrusts it once marked implausible."""
    settings = make_settings(
        control_room_signal="room_temperature",
        mqtt_inputs=[{"topic": "sim/room", "signal": "room_temperature", "unit": "°C"}],
    )
    clock = FakeClock(T0)
    loop, runtime = make_loop(settings, clock)
    feed(settings, runtime)
    MqttIngest(settings, runtime).ingest(inbound("sim/room", "20.2"))
    row = loop.tick()
    plan = next(t for t in json.loads(row.record)["terms"] if t["name"] == "plan")
    assert plan["note"] == "no plan"
    moment = clock()
    inputs = control_inputs(
        runtime.store.snapshot(moment), room_signal="room_temperature", mode=loop.effective_mode
    )
    ctx = loop.plan_context(moment, inputs)
    assert ctx.room_trusted
    assert not ctx.stove_active
    assert ctx.outside_filtered_c == loop.state.outside_filtered
    assert ctx.config is loop.controller.config
    loop.latest_state = {**(loop.latest_state or {}), "room_plausible": False}
    assert not loop.plan_context(moment, inputs).room_trusted

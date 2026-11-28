"""Open-loop run invariants: nothing is sent, records are valid, re-runs are identical."""

import json
import socket
from dataclasses import dataclass
from pathlib import Path

import pytest

from ovenbird_core.capture import CaptureRecord
from ovenbird_core.control import (
    DECISION_SCHEMA_VERSION,
    CommandIntent,
    DecisionRecord,
    IntentKind,
    LadderLevel,
    OvenbirdConfig,
    OvenbirdController,
    ReasonCode,
    StepResult,
)
from ovenbird_core.control.types import ControlInputs
from ovenbird_core.instant import Instant
from ovenbird_core.readings import Reading, SourceKind
from ovenbird_sim.evaluate.meta import NO_CLAIMS_BANNER
from ovenbird_sim.evaluate.openloop import (
    DB_NAME,
    SUMMARY_NAME,
    OpenLoopOptions,
    Tick,
    drive,
    open_loop_run,
)
from ovenbird_sim.evaluate.recorded import DATALAKE_SIGNAL, RoomSource
from ovenbird_sim.evaluate.report import render_open_loop
from ovenbird_sim.evaluate.resultdb import read_meta, read_table

TABLES = ("decisions", "intents", "inputs", "reference")


def _controller() -> OvenbirdController:
    """Return the ovenbird controller with the comfort target the open-loop tests use."""
    return OvenbirdController(OvenbirdConfig.preset("mixed", comfort_room_c=22.5))


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test when the open-loop run tries to open a network connection."""

    def refuse(*args: object, **kwargs: object) -> None:
        """Raise instead of connecting."""
        raise AssertionError("the open-loop run must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.mark.usefixtures("no_network")
def test_open_loop_sends_nothing_and_stores_valid_records(
    tmp_path: Path, capture_slice: Path
) -> None:
    """An open-loop run sends nothing and stores consistent decision and intent records."""
    summary = open_loop_run(
        _controller(), capture_slice, tmp_path, options=OpenLoopOptions(room=RoomSource.MIRROR)
    )
    decisions = read_table(tmp_path / DB_NAME, "decisions", ("tick",))
    ticks = summary["ticks"]
    assert isinstance(ticks, int)
    assert len(decisions) == ticks > 100
    intents = read_table(tmp_path / DB_NAME, "intents", ("tick",))
    stored: dict[object, list[tuple[object, ...]]] = {}
    for row in intents:
        stored.setdefault(row[1], []).append((row[2], row[3], row[4]))
    for row in decisions:
        data = json.loads(str(row[-1]))
        assert data["schema"] == DECISION_SCHEMA_VERSION
        record = DecisionRecord.from_json_dict(data)
        assert record.to_json_dict() == data
        assert record.controller == "ovenbird"
        expected = [(i.kind.value, i.value, i.reason.value) for i in record.intents]
        assert stored.get(row[1], []) == expected
    reference = read_table(tmp_path / DB_NAME, "reference", ("tick",))
    assert len(reference) == len(decisions)
    assert {row[2] for row in reference if row[3]} <= set(range(20, 50))


def test_open_loop_outputs_say_no_outcome_claims(tmp_path: Path, capture_slice: Path) -> None:
    """Open-loop summaries, database and report all carry the no-outcome-claims banner."""
    summary = open_loop_run(_controller(), capture_slice, tmp_path)
    assert summary["banner"] == NO_CLAIMS_BANNER
    written = json.loads((tmp_path / SUMMARY_NAME).read_text(encoding="utf-8"))
    assert written["banner"] == NO_CLAIMS_BANNER
    meta = read_meta(tmp_path / DB_NAME)
    assert meta["banner"] == NO_CLAIMS_BANNER
    text = render_open_loop(summary)
    assert text.count(NO_CLAIMS_BANNER) == 2
    controller = meta["controller"]
    assert isinstance(controller, dict)
    assert controller["name"] == "ovenbird"
    assert isinstance(meta["config_hash"], str)
    assert len(meta["config_hash"]) == 16
    assert "commit" in str(meta["git"])


def test_open_loop_is_deterministic(tmp_path: Path, capture_slice: Path) -> None:
    """Two open-loop runs over the same capture produce identical tables, summaries and metadata."""
    first = open_loop_run(_controller(), capture_slice, tmp_path / "a")
    second = open_loop_run(_controller(), capture_slice, tmp_path / "b")
    for table in TABLES:
        a = read_table(tmp_path / "a" / DB_NAME, table, ("rowid",))
        b = read_table(tmp_path / "b" / DB_NAME, table, ("rowid",))
        assert a == b
    for summary in (first, second):
        summary.pop("runtime_s")
    assert first == second
    meta_a = read_meta(tmp_path / "a" / DB_NAME)
    meta_b = read_meta(tmp_path / "b" / DB_NAME)
    meta_a.pop("created")
    meta_b.pop("created")
    assert meta_a == meta_b


@dataclass(frozen=True)
class _Spy:
    """Controller that records the inputs it is given and always requests the same setpoint."""

    name: str = "spy"

    def initial_state(self) -> list[ControlInputs]:
        """Return an empty list of inputs seen so far."""
        return []

    def step(
        self, state: list[ControlInputs], inputs: ControlInputs
    ) -> StepResult[list[ControlInputs]]:
        """Return the constant setpoint decision (setpoint 30) without changing anything."""
        record = DecisionRecord(
            at=inputs.now,
            controller=self.name,
            mode=inputs.mode,
            ladder=LadderLevel.CURVE_ONLY,
            terms=(),
            pre_round=None,
            setpoint=30,
            binding=None,
            flip_distance=None,
            inputs_used=(),
            controller_state={},
            reason=ReasonCode.CURVE,
            note="spy",
        )
        intent = CommandIntent(IntentKind.WATER_SETPOINT, 30, ReasonCode.CURVE)
        return StepResult([*state, inputs], (intent,), record)


def _capture(t: float, topic: str, payload: str) -> CaptureRecord:
    """Return a capture record of ``topic`` under the HeishaMon base topic at time ``t``."""
    return CaptureRecord(t, f"panasonic_heat_pump/{topic}", payload)


def test_ticks_follow_the_capture_and_never_see_later_readings() -> None:
    """Ticks follow the capture clock and each tick only sees readings from before it."""
    stream: list[CaptureRecord | Reading] = []
    for k in range(121):
        stream.append(_capture(5.0 * k + 1000.0, "stats", '{"uptime":1}'))
    stream.insert(
        30, Reading(DATALAKE_SIGNAL, 21.5, "°C", Instant.from_unix(1100.0), SourceKind.HA)
    )
    stream.append(Reading(DATALAKE_SIGNAL, 23.0, "°C", Instant.from_unix(5000.0), SourceKind.HA))
    stream.sort(
        key=lambda item: (
            item.t if isinstance(item, CaptureRecord) else item.observed.wall.timestamp()
        )
    )
    ticks: list[Tick] = []
    drive(_Spy(), stream, OpenLoopOptions(room=RoomSource.DATALAKE), ticks.append)
    times = [tick.t for tick in ticks]
    assert times == [1020.0 + 60.0 * k for k in range(10)]
    rooms = [None if tick.room is None else tick.room.value for tick in ticks]
    assert rooms[:2] == [None, None]
    assert set(rooms[2:]) == {21.5}


def test_open_loop_judges_the_room_by_the_live_policy() -> None:
    """The room value is stale after the live maximum age unless a longer one is configured."""
    from ovenbird_core.store import HA_MAX_AGE_S

    assert OpenLoopOptions().room_max_age_s == HA_MAX_AGE_S
    stream: list[CaptureRecord | Reading] = [
        _capture(5.0 * k + 1000.0, "stats", '{"uptime":1}') for k in range(1000)
    ]
    stream.insert(5, Reading(DATALAKE_SIGNAL, 21.5, "°C", Instant.from_unix(1010.0), SourceKind.HA))
    ticks: list[Tick] = []
    drive(_Spy(), stream, OpenLoopOptions(room=RoomSource.DATALAKE), ticks.append)
    fresh = [tick.room is not None and tick.room.fresh for tick in ticks]
    ages = [tick.t - 1010.0 for tick in ticks]
    assert all(f == (age <= HA_MAX_AGE_S) for f, age in zip(fresh, ages, strict=True))
    assert not fresh[-1]
    lenient: list[Tick] = []
    drive(
        _Spy(),
        stream,
        OpenLoopOptions(room=RoomSource.DATALAKE, room_max_age_s=86400.0),
        lenient.append,
    )
    assert all(tick.room is not None and tick.room.fresh for tick in lenient[1:])

from __future__ import annotations

import sqlite3
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from ovenbird.history.journal import AlarmRow, StateRow
from ovenbird_core import Instant
from ovenbird_core.control import OverrideKind
from ovenbird_harness.drills import DRILLS, ManualRequest
from ovenbird_harness.fullrun import FullRun
from ovenbird_harness.golden import (
    CAPTURES,
    CAPTURES_ENV,
    OPENLOOP_FILE,
    REAL_DIR,
    GoldenError,
    attach_drill,
    default_captures,
    differences,
    drill_config,
    dump,
    has_recorded,
    journal_alarm,
    openloop_day,
    openloop_lines,
    openloop_skipped,
    persisted_state,
    stable,
    write_lines,
)


def test_floats_are_rounded_and_negative_zero_is_removed() -> None:
    """Floats are rounded to six decimals, negative zero becomes zero, and the dump is canonical."""
    assert stable({"a": [1.23456789, -0.0000000001], "b": 3}) == {"a": [1.234568, 0.0], "b": 3}
    assert dump({"b": 1.5, "a": "é"}) == '{"a":"é","b":1.5}'


def test_differences_name_the_first_changed_lines(tmp_path: Path) -> None:
    """Differences report the count and the first changed lines of each differing file."""
    golden, fresh = tmp_path / "golden", tmp_path / "fresh"
    write_lines(golden / "a.jsonl", ['{"x":1}', '{"x":2}'])
    write_lines(fresh / "a.jsonl", ['{"x":1}', '{"x":3}'])
    write_lines(golden / "sweep" / "s.jsonl.gz", ["one"])
    write_lines(fresh / "sweep" / "s.jsonl.gz", ["one"])
    found = differences(golden, fresh)
    assert found[0].startswith("a.jsonl: 1 lines differ")
    assert any('{"x":3}' in item for item in found)
    assert len(found) == 3


def test_a_skipped_stream_is_not_a_difference(tmp_path: Path) -> None:
    """A stream listed as skipped is not reported when absent from the fresh output."""
    golden, fresh = tmp_path / "golden", tmp_path / "fresh"
    write_lines(golden / OPENLOOP_FILE, ["x"])
    fresh.mkdir()
    assert differences(golden, fresh, skipped=[OPENLOOP_FILE]) == []


def test_alarm_and_state_rows_are_recorded_whole() -> None:
    """Alarm and state rows are serialised whole, with sorted keys and rounded detail."""
    alarm = AlarmRow(1.0, "hold_latched", "warning", "raised", "latched", '{"a":0.1234567}')
    assert journal_alarm(alarm) == (
        '{"code":"hold_latched","detail":{"a":0.123457},"event":"raised","kind":"alarm",'
        '"message":"latched","severity":"warning","ts":1.0}'
    )
    state = StateRow("stove_request", 2.0, "null")
    assert persisted_state(state) == '{"key":"stove_request","kind":"state","ts":2.0,"value":null}'


def test_the_skipped_open_loop_run_says_so(tmp_path: Path) -> None:
    """The note for the skipped open-loop run says so and names the live captures folder."""
    line = openloop_skipped(tmp_path)
    assert line.startswith("golden: real-data streams SKIPPED")
    assert str(tmp_path / "live") in line


def test_real_streams_need_the_recorded_capture(tmp_path: Path) -> None:
    """Real-data streams are available once the ``live`` capture folder exists."""
    assert not has_recorded(tmp_path)
    (tmp_path / "live").mkdir()
    assert has_recorded(tmp_path)


def test_a_missing_local_real_stream_is_a_difference(tmp_path: Path) -> None:
    """A real stream produced locally but missing from the committed set is a difference."""
    fresh = tmp_path / "fresh"
    write_lines(fresh / OPENLOOP_FILE, ["x"])
    assert differences(tmp_path / REAL_DIR, fresh) == [
        f"{OPENLOOP_FILE}: produced but not committed"
    ]


def test_the_captures_directory_follows_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The captures folder comes from the environment variable, else the default."""
    monkeypatch.setenv(CAPTURES_ENV, str(tmp_path))
    assert default_captures() == tmp_path
    monkeypatch.delenv(CAPTURES_ENV)
    assert default_captures() == CAPTURES


def _recorded_days(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return a captures folder with two recorded days and no local settings."""
    captures = tmp_path / "captures"
    (captures / "live").mkdir(parents=True)
    for day in ("2026-01-05", "2026-01-06"):
        (captures / "live" / f"{day}.jsonl.gz").write_bytes(b"")
    monkeypatch.setenv(CAPTURES_ENV, str(captures))
    return captures


def test_the_open_loop_day_is_the_first_full_recorded_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The open-loop day is the second recorded day, the first one that is complete."""
    assert openloop_day(_recorded_days(tmp_path, monkeypatch)) == "2026-01-06"


def _fake_open_loop(monkeypatch: pytest.MonkeyPatch, rows: int) -> None:
    """Replace the open-loop evaluation with one that writes ``rows`` decisions."""

    def main(argv: list[str]) -> int:
        """Write an open-loop database with ``rows`` decisions into the ``--out`` directory."""
        out = Path(argv[argv.index("--out") + 1])
        out.mkdir(parents=True)
        with sqlite3.connect(out / "openloop.sqlite") as db:
            db.execute("CREATE TABLE decisions (tick INTEGER, record TEXT)")
            db.executemany(
                "INSERT INTO decisions VALUES (?, ?)", [(i, '{"x":1}') for i in range(rows)]
            )
        return 0

    module = types.ModuleType("ovenbird_sim.evaluate.__main__")
    module.main = main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ovenbird_sim.evaluate.__main__", module)


def test_an_open_loop_run_without_decisions_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An open-loop run that produced no decisions raises a golden error."""
    _fake_open_loop(monkeypatch, 0)
    with pytest.raises(GoldenError, match="no decisions"):
        openloop_lines(_recorded_days(tmp_path, monkeypatch), tmp_path / "work")


def test_an_open_loop_run_with_decisions_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An open-loop run with decisions is recorded as one decision line per row."""
    _fake_open_loop(monkeypatch, 2)
    lines = openloop_lines(_recorded_days(tmp_path, monkeypatch), tmp_path / "work")
    assert lines[1:] == ['{"kind":"decision","x":1}'] * 2


def test_a_manual_request_hands_its_override_to_the_controller() -> None:
    """A manual request turns into an override of its kind, value and actor, expiring on time."""
    wall = datetime(2026, 11, 10, 12, tzinfo=UTC)
    now = Instant(1000.0, wall)
    request = ManualRequest(True, wall + timedelta(hours=1), "drill", wall, OverrideKind.BOOST, 2.0)
    override = request.override(now)
    assert (override.kind, override.value, override.actor) == (OverrideKind.BOOST, 2.0, "drill")
    assert override.until is not None
    assert override.until.monotonic == pytest.approx(4600.0)
    assert not request.expired(wall)


@pytest.mark.slow
@pytest.mark.parametrize("name", sorted(DRILLS))
def test_every_drill_reaches_its_path(tmp_path: Path, name: str) -> None:
    """Each drill runs on the example house and passes its own checks."""
    run = FullRun(drill_config(tmp_path, name))
    drill = attach_drill(run, name)
    run.run()
    outcome: dict[str, Any] = drill.outcome(run)
    assert outcome["status"] == "pass", outcome["checks"]

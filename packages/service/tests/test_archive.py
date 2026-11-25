"""The yearly archive: months frozen progressively, catch-up, gaps, bundles and deletion."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import zipfile
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ovenbird.config import Settings
from ovenbird.control.alarms import AlarmCode
from ovenbird.history import HistoryDatabase, Retention, Sample, SampleKind, open_history
from ovenbird.history.archive import (
    ALARM_FAILING,
    ALARM_REBUILT,
    FAILING_AFTER,
    LAG_S,
    MAX_WAIT_S,
    REWIND_S,
    ArchiveError,
    ArchiveFolder,
    Month,
    MonthArchiver,
    bundle_manifest,
    clean_build_folders,
    listing,
    parse_season,
    read_zip_manifest,
    season_label,
    season_months,
    write_bundle,
    write_open_month,
    year_months,
)
from ovenbird.history.forecast import ForecastRow, write_forecast
from ovenbird.history.journal import (
    AlarmRow,
    CommandRow,
    DecisionRow,
    iter_decisions,
    write_journal,
)
from ovenbird.history.writer import HistoryWriter
from ovenbird.service import build_service
from ovenbird.testing import FakeMqttClient

HOUR = 3600.0
DAY = 86_400.0
JAN = datetime(2027, 1, 1, tzinfo=UTC).timestamp()
FEB = datetime(2027, 2, 1, tzinfo=UTC).timestamp()
MAR = datetime(2027, 3, 1, tzinfo=UTC).timestamp()
SETTLED = LAG_S + REWIND_S + 60.0


def minutes(start: float, end: float, signal: str = "main/Outlet_Temp") -> list[Sample]:
    count = int((end - start) // 60)
    return [
        Sample(signal, "°C", SampleKind.NUMBER, start + 60 * i, 30.0 + (i % 5), 600.0)
        for i in range(count + 1)
    ]


def decision(ts: float, version: int | None = 3) -> DecisionRow:
    record = json.dumps({"note": "tick", "setpoint": 31}, sort_keys=True)
    return DecisionRow(
        ts, "ovenbird", "shadow", "curve_only", "curve", 31, record, "[]", "[]", version
    )


def fill(path: Path, start: float, end: float, *, every: float = 600.0) -> None:
    conn = open_history(path)
    db = HistoryDatabase(conn)
    db.write_batch(minutes(start, end))
    ticks = [start + every * i for i in range(int((end - start) // every))]
    write_journal(
        conn,
        [decision(ts) for ts in ticks],
        [CommandRow(start + 90, "water_setpoint", 31, "sent", 1, "t", "31", "ok")],
        [AlarmRow(start + 120, "room_stale", "warning", "raised", "room stale", "{}")],
    )
    write_forecast(
        conn, [ForecastRow(start + 30, start + HOUR * h, 5.0, 0.0, 50.0, 3.0) for h in range(3)]
    )
    conn.close()


def count(path: Path, sql: str, params: Sequence[Any] = ()) -> int:
    conn = sqlite3.connect(path)
    try:
        return int(conn.execute(sql, params).fetchone()[0])
    finally:
        conn.close()


def unpack(zip_path: Path, folder: Path) -> tuple[Path, dict[str, Any], dict[str, Any] | None]:
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(folder)
        names = set(zf.namelist())
    manifest = json.loads((folder / "manifest.json").read_text())
    config = json.loads((folder / "config.json").read_text()) if "config.json" in names else None
    return folder / "history.db", manifest, config


def config_source(start: float, end: float, used: Sequence[int | None]) -> dict[str, Any]:
    return {"ovenbird_config": 1, "version": 3, "values": {}, "used": list(used)}


@pytest.fixture
def history(tmp_path: Path) -> Path:
    return tmp_path / "data" / "history.db"


@pytest.fixture
def archiver(history: Path) -> MonthArchiver:
    return MonthArchiver(
        history,
        history.parent / "archive",
        timezone="UTC",
        config_source=config_source,
        budget_s=600.0,
    )


def test_month_bounds_follow_the_local_time_zone() -> None:
    start, end = Month(2026, 10).bounds("Europe/Amsterdam")
    assert datetime.fromtimestamp(start, UTC).isoformat() == "2026-09-30T22:00:00+00:00"
    assert datetime.fromtimestamp(end, UTC).isoformat() == "2026-10-31T23:00:00+00:00"
    assert Month.of(end - 1, "Europe/Amsterdam") == Month(2026, 10)
    assert Month(2026, 12).next() == Month(2027, 1)
    assert len(Month(2028, 2).days()) == 29


def test_periods_parse_and_seasons_run_august_to_july() -> None:
    assert str(Month.parse("2026-03")) == "2026-03"
    with pytest.raises(ArchiveError):
        Month.parse("2026-13")
    assert parse_season("2026-27") == 2026
    assert parse_season("1999-00") == 1999
    with pytest.raises(ArchiveError):
        parse_season("2026-28")
    assert season_label(2026) == "2026/27"
    months = season_months(2026)
    assert (str(months[0]), str(months[-1]), len(months)) == ("2026-08", "2027-07", 12)
    assert Month(2027, 7).season == 2026
    assert Month(2027, 8).season == 2027
    assert len(year_months(2026)) == 12


def test_a_finished_month_is_frozen_with_its_data_only(
    history: Path, archiver: MonthArchiver, tmp_path: Path
) -> None:
    fill(history, JAN + 10 * DAY, FEB + 2 * DAY)
    assert archiver.step(FEB + 2 * DAY) is False
    folder = archiver.folder
    assert list(folder.frozen()) == [Month(2027, 1)]
    assert list(folder.open_months()) == [Month(2027, 2)]
    database, manifest, config = unpack(folder.frozen_path(Month(2027, 1)), tmp_path / "jan")
    inside = count(
        database, "SELECT count(*) FROM rollup WHERE bucket < ? OR bucket >= ?", (JAN, FEB)
    )
    assert inside == 0
    assert count(database, "SELECT count(*) FROM rollup WHERE step = 60") == int(21 * DAY / 60)
    assert count(database, "SELECT count(*) FROM decision") == int(21 * DAY / 600)
    assert count(database, "SELECT count(*) FROM decision_dictionary") >= 1
    assert count(database, "SELECT count(*) FROM command") == 1
    assert count(database, "SELECT count(*) FROM forecast") == 3
    assert count(database, "SELECT count(*) FROM sample") == 0
    assert manifest["kind"] == "month"
    assert manifest["period"] == "2027-01"
    assert manifest["frozen"] is True
    assert manifest["complete"] is False
    assert manifest["coverage"]["60"]["days"] == 21
    assert manifest["coverage"]["60"]["missing_days"][:2] == ["2027-01-01", "2027-01-02"]
    assert len(manifest["coverage"]["60"]["missing_days"]) == 10
    assert manifest["config_versions"] == [3]
    assert manifest["signals"] == [{"id": "main/Outlet_Temp", "unit": "°C", "kind": "number"}]
    assert config is not None
    assert config["used"] == [3]
    assert set(manifest["files"]) == {"history.db", "config.json", "manifest.json"}


def test_rows_read_back_like_the_live_history(
    history: Path, archiver: MonthArchiver, tmp_path: Path
) -> None:
    fill(history, JAN, FEB + DAY)
    archiver.step(FEB + DAY)
    database, _, _ = unpack(archiver.folder.frozen_path(Month(2027, 1)), tmp_path / "jan")
    live = [row.payload() for row in iter_decisions(history, JAN, FEB)]
    frozen = [row.payload() for row in iter_decisions(database, JAN, FEB)]
    assert frozen == live
    assert len(frozen) == int(31 * DAY / 600)


def test_steps_are_idempotent_and_progressive(history: Path, archiver: MonthArchiver) -> None:
    fill(history, JAN, JAN + 5 * DAY)
    archiver.step(JAN + 3 * DAY)
    working = archiver.folder.open_path(Month(2027, 1))
    first = count(working, "SELECT count(*) FROM rollup WHERE step = 60")
    assert first == int((3 * DAY - LAG_S) / 60)
    archiver.step(JAN + 3 * DAY)
    assert count(working, "SELECT count(*) FROM rollup WHERE step = 60") == first
    archiver.step(JAN + 4 * DAY)
    assert count(working, "SELECT count(*) FROM rollup WHERE step = 60") == first + 1440
    assert count(working, "SELECT count(*) FROM decision") == int((4 * DAY - LAG_S) / 600)
    assert archiver.state.archived_to == JAN + 4 * DAY - LAG_S


def test_a_month_waits_until_it_has_settled(history: Path, archiver: MonthArchiver) -> None:
    fill(history, JAN + 20 * DAY, FEB + DAY)
    archiver.step(FEB + HOUR)
    assert not archiver.folder.frozen()
    archiver.step(FEB + SETTLED)
    assert list(archiver.folder.frozen()) == [Month(2027, 1)]
    assert not archiver.folder.open_path(Month(2027, 1)).exists()


def test_a_late_rollup_update_is_copied_again(history: Path, archiver: MonthArchiver) -> None:
    fill(history, JAN, JAN + DAY)
    archiver.step(JAN + DAY)
    conn = sqlite3.connect(history)
    conn.execute(
        "UPDATE rollup SET maximum = 99 WHERE step = 60 AND bucket = ?", (JAN + DAY - HOUR,)
    )
    conn.commit()
    conn.close()
    archiver.step(JAN + DAY + 60)
    working = archiver.folder.open_path(Month(2027, 1))
    assert count(working, "SELECT max(maximum) FROM rollup WHERE step = 60") == 99


def test_catch_up_runs_within_its_budget_oldest_first(history: Path) -> None:
    fill(history, JAN + 20 * DAY, MAR + DAY)
    slow = MonthArchiver(history, history.parent / "archive", timezone="UTC", budget_s=0.0)
    steps = 0
    while slow.step(MAR + DAY):
        steps += 1
        assert steps < 100
    assert steps > 3
    assert list(slow.folder.frozen()) == [Month(2027, 1), Month(2027, 2)]
    assert list(slow.folder.open_months()) == [Month(2027, 3)]


def test_crash_leftovers_are_cleaned_and_frozen_months_kept(
    history: Path, archiver: MonthArchiver
) -> None:
    fill(history, JAN, FEB + DAY)
    archiver.step(FEB + DAY)
    folder = archiver.folder
    frozen = folder.frozen_path(Month(2027, 1))
    before = frozen.stat().st_mtime_ns
    stale = folder.path / "2027-01.zip.tmp"
    stale.write_bytes(b"torn")
    leftover = folder.open_path(Month(2027, 1))
    leftover.write_bytes(b"")
    archiver.step(FEB + DAY + 60)
    assert not stale.exists()
    assert not leftover.exists()
    assert frozen.stat().st_mtime_ns == before


def test_an_interrupted_freeze_is_redone(history: Path, archiver: MonthArchiver) -> None:
    fill(history, JAN, FEB + DAY)
    archiver.step(JAN + 20 * DAY)
    (archiver.folder.path / "2027-01.zip.tmp").write_bytes(b"half")
    archiver.step(FEB + DAY)
    assert read_zip_manifest(archiver.folder.frozen_path(Month(2027, 1))) is not None


def test_months_without_data_are_skipped(history: Path, archiver: MonthArchiver) -> None:
    fill(history, JAN, JAN + DAY)
    fill(history, MAR, MAR + DAY)
    archiver.step(MAR + DAY)
    assert list(archiver.folder.frozen()) == [Month(2027, 1)]
    assert archiver.folder.state()["empty"] == ["2027-02"]
    archiver.step(MAR + DAY + 60)
    assert not archiver.folder.open_path(Month(2027, 2)).exists()


def test_deleted_months_are_not_frozen_again(history: Path, archiver: MonthArchiver) -> None:
    fill(history, JAN, FEB + DAY)
    archiver.step(FEB + DAY)
    assert archiver.folder.delete([Month(2027, 1)]) == ["2027-01"]
    archiver.step(FEB + DAY + 60)
    assert not archiver.folder.frozen()
    assert archiver.folder.state()["deleted"] == ["2027-01"]


def test_a_disabled_archive_does_nothing(history: Path, archiver: MonthArchiver) -> None:
    fill(history, JAN, FEB + DAY)
    archiver.configure(enabled=False, timezone="UTC")
    assert archiver.step(FEB + DAY) is False
    assert not archiver.folder.path.exists()


def test_low_disk_space_is_reported_and_skipped(history: Path) -> None:
    fill(history, JAN, FEB + DAY)
    archiver = MonthArchiver(
        history,
        history.parent / "archive",
        timezone="UTC",
        min_free_bytes=10**6,
        disk_free=lambda _path: 10,
    )
    assert archiver.step(FEB + DAY) is False
    assert archiver.state.error is not None
    assert "free" in archiver.state.error
    assert not archiver.folder.frozen()


def test_retention_waits_until_the_archive_has_caught_up(history: Path) -> None:
    fill(history, JAN, JAN + 10 * DAY)
    wall = {"now": JAN + 10 * DAY}
    archiver = MonthArchiver(history, history.parent / "archive", timezone="UTC", budget_s=0.0)
    writer = HistoryWriter(
        history,
        Retention(raw_days=1.0, minute_days=1.0, quarter_days=1.0, hour_days=1.0),
        journal_days=1.0,
        wall=lambda: wall["now"],
        archiver=archiver,
        archive_interval=0.0,
        disk_free=lambda _path: 10**12,
    )
    writer.run_once([])
    assert archiver.state.behind
    assert writer.stats.retention_deleted == 0
    for _ in range(100):
        writer.run_once([])
        if not archiver.state.behind:
            break
    writer.run_once([])
    assert writer.stats.retention_deleted > 0
    working = archiver.folder.open_path(Month(2027, 1))
    assert count(working, "SELECT count(*) FROM rollup WHERE step = 60") == int(
        (10 * DAY - LAG_S) / 60
    )
    assert count(history, "SELECT count(*) FROM rollup WHERE step = 60") < 1500
    writer._close()


@pytest.mark.slow
def test_a_one_day_retention_loses_nothing_in_daily_operation(history: Path) -> None:
    conn = open_history(history)
    conn.close()
    wall = {"now": JAN}
    archiver = MonthArchiver(history, history.parent / "archive", timezone="UTC", budget_s=600.0)
    writer = HistoryWriter(
        history,
        Retention(raw_days=1.0, minute_days=1.0, quarter_days=1.0, hour_days=1.0),
        journal_days=1.0,
        wall=lambda: wall["now"],
        archiver=archiver,
        archive_interval=0.0,
        retention_interval=0.0,
        disk_free=lambda _path: 10**12,
    )
    t = JAN
    while t < FEB + SETTLED:
        batch: list[Any] = minutes(t, t + 900 - 60)
        batch.append(decision(t))
        wall["now"] = t + 900
        writer.run_once(batch)
        t += 900
    writer._close()
    database = archiver.folder.frozen_path(Month(2027, 1))
    manifest = read_zip_manifest(database)
    assert manifest is not None
    assert manifest["complete"] is True
    assert manifest["coverage"]["60"]["rows"] == int(31 * DAY / 60)
    assert manifest["coverage"]["decisions"]["rows"] == int(31 * DAY / 900)


def test_listing_groups_years_and_seasons(history: Path, archiver: MonthArchiver) -> None:
    fill(history, JAN, MAR + DAY)
    archiver.step(MAR + DAY)
    body = listing(archiver.folder, "UTC")
    assert [item["period"] for item in body["months"]] == ["2027-03", "2027-02", "2027-01"]
    assert body["months"][0]["state"] == "open"
    assert body["months"][1]["state"] == "frozen"
    assert body["months"][1]["complete"] is True
    year = body["years"][0]
    assert (year["id"], year["months"], year["open_months"]) == (
        "2027",
        ["2027-01", "2027-02"],
        ["2027-03"],
    )
    assert year["complete"] is False
    assert [season["period"] for season in body["seasons"]] == ["2026/27"]
    assert body["bytes_per_year"] > 0
    assert body["total_bytes"] == sum(item["bytes"] for item in body["months"])


def test_a_bundle_holds_the_months_and_a_combined_manifest(
    history: Path, archiver: MonthArchiver, tmp_path: Path
) -> None:
    fill(history, JAN, MAR + DAY)
    archiver.step(MAR + DAY)
    frozen = archiver.folder.frozen()
    months = year_months(2027)
    found = {month: (path, read_zip_manifest(path)) for month, path in frozen.items()}
    manifest = bundle_manifest("year", "2027", months, found, "UTC", MAR + DAY)
    target = tmp_path / "2027.zip"
    write_bundle(target, list(frozen.values()), manifest)
    with zipfile.ZipFile(target) as zf:
        assert sorted(zf.namelist()) == ["2027-01.zip", "2027-02.zip", "manifest.json"]
        combined = json.loads(zf.read("manifest.json"))
    assert combined["kind"] == "year"
    assert combined["coverage"] == {"months": 2, "of": 12, "first": "2027-01", "last": "2027-02"}
    assert combined["partial"] is True
    assert combined["missing_months"][0] == "2027-03"
    assert [item["days"] for item in combined["months"]] == [31, 28]


def test_the_open_month_downloads_as_it_stands(
    history: Path, archiver: MonthArchiver, tmp_path: Path
) -> None:
    fill(history, JAN, JAN + 5 * DAY)
    archiver.step(JAN + 5 * DAY)
    out = tmp_path / "out"
    out.mkdir()
    target = write_open_month(
        archiver.folder.open_path(Month(2027, 1)),
        out,
        Month(2027, 1),
        "UTC",
        JAN + 5 * DAY,
        config_source,
    )
    _, manifest, config = unpack(target, tmp_path / "open")
    assert manifest["frozen"] is False
    assert manifest["complete"] is False
    assert manifest["coverage"]["60"]["days"] == 5
    assert manifest["coverage"]["60"]["missing_days"] == []
    assert config is not None


def test_reused_journal_ids_are_still_archived(history: Path, archiver: MonthArchiver) -> None:
    fill(history, JAN, JAN + DAY)
    archiver.step(JAN + DAY)
    working = archiver.folder.open_path(Month(2027, 1))
    before = count(working, "SELECT count(*) FROM decision")
    conn = sqlite3.connect(history)
    for table in ("decision", "command", "alarm"):
        conn.execute(f"DELETE FROM {table}")  # noqa: S608
    conn.commit()
    conn.close()
    later = JAN + DAY + HOUR
    conn = open_history(history)
    write_journal(
        conn,
        [decision(later + 600 * i) for i in range(6)],
        [CommandRow(later + 90, "water_setpoint", 32, "sent", 1, "t", "32", "ok")],
        [AlarmRow(later + 120, "low_flow", "critical", "raised", "flow low", "{}")],
    )
    assert conn.execute("SELECT min(id) FROM decision").fetchone()[0] == 1
    conn.close()
    archiver.step(JAN + 2 * DAY)
    assert count(working, "SELECT count(*) FROM decision") == before + 6
    assert count(working, "SELECT count(*) FROM command") == 2
    assert count(working, "SELECT count(*) FROM alarm") == 2


def rollups_of(path: Path, name: str, lo: float, hi: float) -> int:
    return count(
        path,
        "SELECT count(*) FROM rollup JOIN signal ON signal.id = rollup.signal_id "
        "WHERE step = 60 AND name = ? AND bucket >= ? AND bucket < ?",
        (name, lo, hi),
    )


def test_a_new_history_with_other_ids_is_archived_by_name(
    history: Path, archiver: MonthArchiver
) -> None:
    fill(history, JAN, JAN + DAY)
    archiver.step(JAN + DAY)
    working = archiver.folder.open_path(Month(2027, 1))
    day_one = rollups_of(working, "main/Outlet_Temp", JAN, JAN + DAY)
    decisions = count(working, "SELECT count(*) FROM decision")
    for suffix in ("", "-wal", "-shm"):
        history.with_name(history.name + suffix).unlink(missing_ok=True)
    conn = open_history(history)
    db = HistoryDatabase(conn)
    db.write_batch(minutes(JAN + DAY, JAN + 2 * DAY, "main/Inlet_Temp"))
    db.write_batch(minutes(JAN + DAY, JAN + 2 * DAY))
    write_journal(conn, [decision(JAN + DAY + 600 * i, 4) for i in range(144)], [], [])
    conn.close()
    archiver.step(JAN + 2 * DAY)
    assert rollups_of(working, "main/Outlet_Temp", JAN, JAN + DAY) == day_one
    assert rollups_of(working, "main/Inlet_Temp", JAN, JAN + DAY) == 0
    inlet = rollups_of(working, "main/Inlet_Temp", JAN + DAY, JAN + 2 * DAY)
    assert inlet == int((DAY - LAG_S) / 60)
    assert rollups_of(working, "main/Outlet_Temp", JAN + DAY, JAN + 2 * DAY) == inlet
    assert count(working, "SELECT count(*) FROM decision") == decisions + 143
    window = (JAN + DAY, JAN + 2 * DAY - LAG_S)
    live = [row.payload() for row in iter_decisions(history, *window)]
    copied = [row.payload() for row in iter_decisions(working, *window)]
    assert copied == live


def failing_archiver(
    history: Path, free: dict[str, int], events: list[tuple[str, bool, str]], **options: Any
) -> MonthArchiver:
    return MonthArchiver(
        history,
        history.parent / "archive",
        timezone="UTC",
        min_free_bytes=10**6,
        disk_free=lambda _path: free["bytes"],
        alarm=lambda code, active, text: events.append((code, active, text)),
        **options,
    )


def test_a_failed_step_keeps_retention_waiting_up_to_its_bound(history: Path) -> None:
    fill(history, JAN, JAN + 10 * DAY)
    wall = {"now": JAN + 10 * DAY}
    free = {"bytes": 10}
    archiver = failing_archiver(history, free, [], budget_s=600.0)
    writer = HistoryWriter(
        history,
        Retention(raw_days=1.0, minute_days=1.0, quarter_days=1.0, hour_days=1.0),
        journal_days=1.0,
        wall=lambda: wall["now"],
        archiver=archiver,
        archive_interval=0.0,
        retention_interval=0.0,
        disk_free=lambda _path: 10**12,
    )
    for _ in range(3):
        writer.run_once([])
    assert archiver.state.error is not None
    assert archiver.state.behind
    assert writer.stats.retention_deleted == 0
    wall["now"] += MAX_WAIT_S - 1
    writer.run_once([])
    assert writer.stats.retention_deleted == 0
    wall["now"] += 1
    writer.run_once([])
    assert not archiver.state.behind
    assert writer.stats.retention_deleted > 0
    writer._close()


def test_repeated_failures_raise_an_alarm_that_a_success_clears(history: Path) -> None:
    fill(history, JAN, JAN + DAY)
    free = {"bytes": 10}
    events: list[tuple[str, bool, str]] = []
    archiver = failing_archiver(history, free, events)
    now = JAN + DAY
    for n in range(FAILING_AFTER - 1):
        assert archiver.step(now + n) is False
    assert events == []
    assert archiver.state.failures == FAILING_AFTER - 1
    archiver.step(now + FAILING_AFTER)
    archiver.step(now + FAILING_AFTER + 1)
    assert [(code, active) for code, active, _ in events] == [(ALARM_FAILING, True)]
    assert "free" in events[0][2]
    free["bytes"] = 10**12
    archiver.step(now + 600)
    assert [(code, active) for code, active, _ in events][-1] == (ALARM_FAILING, False)
    assert archiver.state.failures == 0
    assert archiver.state.error is None
    assert AlarmCode(ALARM_FAILING) is AlarmCode.ARCHIVE_FAILING
    assert AlarmCode(ALARM_REBUILT) is AlarmCode.ARCHIVE_REBUILT


def test_a_damaged_working_copy_is_quarantined_and_rebuilt(history: Path) -> None:
    fill(history, JAN, JAN + 3 * DAY)
    events: list[tuple[str, bool, str]] = []
    archiver = failing_archiver(history, {"bytes": 10**12}, events, budget_s=600.0)
    archiver.step(JAN + 2 * DAY)
    working = archiver.folder.open_path(Month(2027, 1))
    working.write_bytes(b"not a database " * 1000)
    while archiver.step(JAN + 3 * DAY):
        pass
    archiver.step(JAN + 3 * DAY)
    moved = list(archiver.folder.path.glob("2027-01.db.corrupt-*"))
    assert len(moved) == 1
    assert moved[0].read_bytes().startswith(b"not a database")
    assert count(working, "SELECT count(*) FROM rollup WHERE step = 60") == int(
        (3 * DAY - LAG_S) / 60
    )
    assert [(code, active) for code, active, _ in events] == [(ALARM_REBUILT, True)]
    assert "2027-01" in events[0][2]
    assert list(archiver.folder.open_months()) == [Month(2027, 1)]


def test_damaged_pages_are_found_when_the_service_starts(history: Path) -> None:
    fill(history, JAN, JAN + 3 * DAY)
    first = MonthArchiver(history, history.parent / "archive", timezone="UTC", budget_s=600.0)
    first.step(JAN + 2 * DAY)
    working = first.folder.open_path(Month(2027, 1))
    data = bytearray(working.read_bytes())
    for offset in range(4096 * 3, min(len(data), 4096 * 8)):
        data[offset] = 0xFF
    working.write_bytes(bytes(data))
    events: list[tuple[str, bool, str]] = []
    restarted = failing_archiver(history, {"bytes": 10**12}, events, budget_s=600.0)
    restarted.step(JAN + 3 * DAY)
    assert len(list(restarted.folder.path.glob("2027-01.db.corrupt-*"))) == 1
    assert events[0][:2] == (ALARM_REBUILT, True)
    assert count(working, "SELECT count(*) FROM rollup WHERE step = 60") == int(
        (3 * DAY - LAG_S) / 60
    )


def test_a_damaged_live_history_leaves_the_working_copy_alone(
    history: Path, archiver: MonthArchiver
) -> None:
    fill(history, JAN, JAN + 2 * DAY)
    archiver.step(JAN + DAY)
    working = archiver.folder.open_path(Month(2027, 1))
    before = working.read_bytes()
    for suffix in ("-wal", "-shm"):
        history.with_name(history.name + suffix).unlink(missing_ok=True)
    history.write_bytes(b"garbage " * 4096)
    assert archiver.step(JAN + 2 * DAY) is False
    assert archiver.state.error is not None
    assert working.read_bytes() == before
    assert not list(archiver.folder.path.glob("*.corrupt-*"))


def freeze_in_slices(archiver: MonthArchiver, now: float, *, until_verifying: bool) -> int:
    steps = 0
    while True:
        build = archiver.zip_build
        if build is not None and until_verifying and build.verifying:
            return steps
        if not archiver.step(now):
            return steps
        steps += 1
        assert steps < 5000


def test_freezing_runs_in_slices_while_retention_waits(history: Path, tmp_path: Path) -> None:
    fill(history, JAN, FEB + DAY)
    archiver = MonthArchiver(
        history, history.parent / "archive", timezone="UTC", budget_s=0.0, zip_slice=4096
    )
    working = archiver.folder.open_path(Month(2027, 1))
    building = 0
    size = 0
    for _ in range(5000):
        if not archiver.step(FEB + DAY):
            break
        if archiver.zip_build is not None:
            size = size or working.stat().st_size
            building += 1
            assert archiver.holds_retention()
    assert building > size // 4096
    frozen = archiver.folder.frozen_path(Month(2027, 1))
    database, manifest, _ = unpack(frozen, tmp_path / "jan")
    assert manifest["complete"] is True
    assert count(database, "SELECT count(*) FROM rollup WHERE step = 60") == int(31 * DAY / 60)
    conn = sqlite3.connect(database)
    assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    conn.close()
    assert not working.exists()
    with zipfile.ZipFile(frozen) as zf:
        assert zf.getinfo("history.db").compress_type == zipfile.ZIP_DEFLATED


def test_a_zip_that_does_not_verify_keeps_the_working_copy(history: Path) -> None:
    fill(history, JAN, FEB + DAY)
    archiver = MonthArchiver(
        history, history.parent / "archive", timezone="UTC", budget_s=0.0, zip_slice=4096
    )
    freeze_in_slices(archiver, FEB + DAY, until_verifying=True)
    tmp = archiver.folder.path / "2027-01.zip.tmp"
    working = archiver.folder.open_path(Month(2027, 1))
    data = bytearray(tmp.read_bytes())
    middle = len(data) // 2
    for offset in range(middle, middle + 400):
        data[offset] ^= 0x5A
    with tmp.open("r+b") as handle:
        handle.write(bytes(data))
    for _ in range(5000):
        if archiver.state.error is not None:
            break
        archiver.step(FEB + DAY)
    assert archiver.state.error is not None
    assert working.exists()
    assert not tmp.exists()
    assert not archiver.folder.frozen()
    assert archiver.holds_retention()
    freeze_in_slices(archiver, FEB + DAY + 60, until_verifying=False)
    assert list(archiver.folder.frozen()) == [Month(2027, 1)]
    assert not working.exists()


def test_leftover_build_folders_are_removed_at_start(tmp_path: Path) -> None:
    data = tmp_path / "data"
    leftover = data / ".archive-k2j3h4"
    leftover.mkdir(parents=True)
    (leftover / "history.db").write_bytes(b"half a download")
    (data / "archive").mkdir()
    (data / "archive" / "2027-01.zip").write_bytes(b"kept")
    other = data / "notes"
    other.mkdir()
    assert clean_build_folders(data) == [leftover]
    assert not leftover.exists()
    assert (data / "archive" / "2027-01.zip").exists()
    assert other.exists()
    assert clean_build_folders(tmp_path / "missing") == []


async def test_the_service_cleans_up_at_start_and_shows_archive_alarms(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings()
    service = build_service(settings, mqtt_connect=FakeMqttClient)
    leftover = settings.data_dir / ".archive-abc123"
    leftover.mkdir(parents=True)
    (leftover / "2027.zip").write_bytes(b"half")
    archiver = service.writer.archiver
    assert archiver is not None
    assert archiver.alarm is not None
    board = service.control.alarms
    archiver.alarm(ALARM_FAILING, True, "the monthly archive failed 4 times")
    alarm = board.get(AlarmCode.ARCHIVE_FAILING)
    assert alarm is not None
    assert alarm.severity == "warning"
    archiver.alarm(ALARM_FAILING, False, "an archive step succeeded")
    assert not board.is_active(AlarmCode.ARCHIVE_FAILING)
    stop = asyncio.Event()
    task = asyncio.create_task(service.run(stop))
    await asyncio.wait_for(service.server.ready.wait(), 5)
    assert not leftover.exists()
    stop.set()
    await asyncio.wait_for(task, 10)


def test_folder_state_survives_a_broken_file(tmp_path: Path) -> None:
    folder = ArchiveFolder(tmp_path / "archive")
    folder.path.mkdir()
    (folder.path / "state.json").write_text("{not json")
    assert folder.state() == {"deleted": [], "empty": []}
    folder.remember("deleted", [Month(2026, 1)])
    assert folder.state()["deleted"] == ["2026-01"]

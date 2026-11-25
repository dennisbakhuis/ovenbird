from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest

from ovenbird.history import (
    HistoryDatabase,
    HistoryQueryError,
    HistoryWriter,
    Retention,
    Sample,
    SampleKind,
    SchemaTooNewError,
    default_step,
    open_history,
    query_series,
    sample_from_reading,
    schema,
)
from ovenbird.history.database import gap_sample
from ovenbird.history.schema import Migration, bundled_migrations, migrate, user_version
from ovenbird.history.snapshot import restore_snapshot, write_snapshot
from ovenbird.history.writer import DropOldestQueue
from ovenbird.testing import FakeClock
from ovenbird_core import ParseError, ParseErrorKind, Reading, SourceKind, StalenessPolicy

T0 = 1_800_000_000.0
OUTLET = "main/Main_Outlet_Temp"
MODE = "main/Operating_Mode_State"
DAY = 86_400.0


def number(ts: float, value: float, signal: str = OUTLET, hold: float = 330.0) -> Sample:
    return Sample(signal, "°C", SampleKind.NUMBER, ts, value, hold)


def enum(ts: float, value: int) -> Sample:
    return Sample(MODE, None, SampleKind.ENUM, ts, float(value), 330.0)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "history.db"


@pytest.fixture
def db(db_path: Path) -> Iterator[HistoryDatabase]:
    database = HistoryDatabase(open_history(db_path))
    yield database
    database.close()


def rollup(path: Path, step: int, signal: str = OUTLET) -> list[tuple[int, float, float]]:
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT bucket, weighted_sum, duration FROM rollup "
            "JOIN signal ON signal.id = signal_id WHERE step = ? AND name = ? ORDER BY bucket",
            (step, signal),
        ).fetchall()
    return [(int(bucket), float(wsum), float(duration)) for bucket, wsum, duration in rows]


def raw_count(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        return int(conn.execute("SELECT count(*) FROM sample").fetchone()[0])


def test_bundled_migrations_are_numbered() -> None:
    migrations = bundled_migrations()
    assert [m.version for m in migrations] == list(range(1, len(migrations) + 1))
    assert migrations[0].name == "0001_initial.sql"


def test_open_creates_schema_with_wal(db_path: Path) -> None:
    conn = open_history(db_path)
    try:
        assert user_version(conn) == len(bundled_migrations())
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert {"signal", "sample", "rollup"} <= tables
    finally:
        conn.close()
    again = open_history(db_path)
    assert user_version(again) == len(bundled_migrations())
    again.close()


def test_migrations_apply_in_order_and_roll_back_on_failure(db_path: Path) -> None:
    conn = sqlite3.connect(db_path, isolation_level=None)
    first = Migration(1, "0001_a.sql", "CREATE TABLE a (x INTEGER);")
    second = Migration(2, "0002_b.sql", "CREATE TABLE b (y INTEGER);")
    broken = Migration(3, "0003_c.sql", "CREATE TABLE c (z INTEGER); INSERT INTO nope VALUES (1);")
    assert migrate(conn, [first]) == 1
    assert migrate(conn, [first, second]) == 2
    with pytest.raises(sqlite3.OperationalError):
        migrate(conn, [first, second, broken])
    assert user_version(conn) == 2
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert tables == {"a", "b"}
    conn.close()


def test_newer_schema_is_refused_and_left_alone(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(SchemaTooNewError):
        open_history(db_path)
    assert db_path.exists()
    assert not list(db_path.parent.glob("*.corrupt-*"))


def test_corrupt_database_is_quarantined(db_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    db_path.write_bytes(b"this is not a sqlite database at all" * 200)
    with caplog.at_level(logging.CRITICAL, logger="ovenbird.history"):
        conn = open_history(db_path)
    try:
        assert user_version(conn) == len(bundled_migrations())
        assert conn.execute("SELECT count(*) FROM sample").fetchone()[0] == 0
    finally:
        conn.close()
    quarantined = list(db_path.parent.glob("history.db.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes().startswith(b"this is not")
    assert any("CORRUPT" in record.message for record in caplog.records)


def test_damaged_pages_are_quarantined(db_path: Path) -> None:
    db = HistoryDatabase(open_history(db_path))
    db.write_batch([number(T0 + i, float(i)) for i in range(2000)])
    db.close()
    data = bytearray(db_path.read_bytes())
    page = 4096
    for offset in range(page * 2, min(len(data), page * 6)):
        data[offset] = 0xFF
    db_path.write_bytes(bytes(data))
    for suffix in ("-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
    conn = open_history(db_path)
    conn.close()
    assert list(db_path.parent.glob("history.db.corrupt-*"))


def test_a_locked_database_is_not_quarantined(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = HistoryDatabase(open_history(db_path))
    db.write_batch([number(T0, 30.0)])
    db.close()
    monkeypatch.setattr(schema, "BUSY_TIMEOUT_MS", 0)
    holder = sqlite3.connect(db_path, isolation_level=None)
    holder.execute("PRAGMA locking_mode = EXCLUSIVE")
    holder.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            open_history(db_path)
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert not list(db_path.parent.glob("*.corrupt-*"))
    assert raw_count(db_path) == 1


def test_a_full_disk_is_not_taken_for_corruption(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    HistoryDatabase(open_history(db_path)).close()

    def full(conn: sqlite3.Connection) -> None:
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(schema, "check_integrity", full)
    with pytest.raises(sqlite3.OperationalError, match="full"):
        open_history(db_path)
    assert db_path.exists()
    assert not list(db_path.parent.glob("*.corrupt-*"))


def test_raw_samples_only_on_change(db: HistoryDatabase, db_path: Path) -> None:
    result = db.write_batch([number(T0, 30.0), number(T0 + 10, 30.0), number(T0 + 20, 31.0)])
    assert result.samples == 2
    db.write_batch([number(T0 + 30, 31.0), number(T0 + 25, 99.0)])
    assert raw_count(db_path) == 2


def test_rollups_are_time_weighted_across_buckets(db: HistoryDatabase, db_path: Path) -> None:
    db.write_batch([number(T0, 0.0), number(T0 + 15, 60.0)])
    db.write_batch([number(T0 + 60, 60.0), number(T0 + 90, 0.0), number(T0 + 120, 0.0)])
    minutes = rollup(db_path, 60)
    assert minutes[0] == (int(T0), 0.0 * 15 + 60.0 * 45, 60.0)
    assert minutes[1] == (int(T0) + 60, 60.0 * 30, 60.0)
    hour = rollup(db_path, 3600)
    assert hour == [(int(T0), 60.0 * 75, 120.0)]
    series = query_series(db_path, [OUTLET], T0, T0 + 180, 60)[OUTLET]
    assert series.unit == "°C"
    assert series.points == ((T0, 45.0), (T0 + 60, 30.0), (T0 + 120, 0.0))


def test_value_is_held_at_most_max_hold(db: HistoryDatabase, db_path: Path) -> None:
    db.write_batch([number(T0, 10.0, hold=120.0), number(T0 + 600, 10.0, hold=120.0)])
    total = sum(duration for _, _, duration in rollup(db_path, 60))
    assert total == pytest.approx(120.0)


def test_enum_series_take_last_value(db: HistoryDatabase, db_path: Path) -> None:
    db.write_batch([enum(T0, 0), enum(T0 + 50, 3), enum(T0 + 70, 0)])
    series = query_series(db_path, [MODE], T0, T0 + 120, 60)[MODE]
    assert series.points == ((T0, 3.0), (T0 + 60, 0.0))


def test_query_grid_has_gaps_and_raw_points(db: HistoryDatabase, db_path: Path) -> None:
    db.write_batch([number(T0, 20.0, hold=60), number(T0 + 30, 21.0, hold=60)])
    db.write_batch([number(T0 + 300, 25.0, hold=60)])
    grid = query_series(db_path, [OUTLET, "unknown/signal"], T0, T0 + 360, 60)
    values = [value for _, value in grid[OUTLET].points]
    assert len(values) == 6
    assert values[0] == pytest.approx(20.5)
    assert values[1] == 21.0
    assert values[2:5] == [None, None, None]
    assert values[5] == 25.0
    assert [value for _, value in grid["unknown/signal"].points] == [None] * 6
    raw = query_series(db_path, [OUTLET], T0, T0 + 360, 0)[OUTLET]
    assert raw.points == ((T0, 20.0), (T0 + 30, 21.0), (T0 + 300, 25.0))


def test_query_validation_and_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "none.db"
    assert query_series(missing, [OUTLET], T0, T0 + 60, 60)[OUTLET].points == ((T0, None),)
    assert query_series(missing, [OUTLET], T0, T0 + 60, 0)[OUTLET].points == ()
    with pytest.raises(HistoryQueryError):
        query_series(missing, [OUTLET], T0, T0 + 60, 30)
    with pytest.raises(HistoryQueryError):
        query_series(missing, [OUTLET], T0, T0 + 400 * DAY, 60)


def test_default_step_targets_1500_points() -> None:
    assert default_step(0, DAY) == 60
    assert default_step(0, 7 * DAY) == 900
    assert default_step(0, 60 * DAY) == 3600
    assert default_step(0, 400 * DAY) == 3600


def test_retention_caps(db: HistoryDatabase, db_path: Path) -> None:
    now = T0 + 200 * DAY
    old, middle, recent = now - 100 * DAY, now - 30 * DAY, now - 1 * DAY
    for ts in (old, middle, recent):
        db.forget_held()
        db.write_batch([number(ts, 1.0), number(ts + 30, 2.0)])
    deleted = db.apply_retention(Retention(), now)
    assert deleted > 0
    with sqlite3.connect(db_path) as conn:
        raw_ts = [row[0] for row in conn.execute("SELECT ts FROM sample ORDER BY ts")]
        minute = [row[0] for row in conn.execute("SELECT bucket FROM rollup WHERE step = 60")]
        hour = [row[0] for row in conn.execute("SELECT bucket FROM rollup WHERE step = 3600")]
    assert raw_ts == [recent, recent + 30]
    assert min(minute) >= middle - 60
    assert len(hour) == 3
    db.apply_retention(Retention(hour_days=50), now)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT count(*) FROM rollup WHERE step = 3600").fetchone()[0] == 2


def test_sample_from_reading_kinds() -> None:
    clock = FakeClock(T0)
    policy = StalenessPolicy()
    live = Reading(OUTLET, 31.5, "°C", clock(), SourceKind.HEISHAMON)
    sample = sample_from_reading(live, policy)
    assert sample is not None
    assert (sample.kind, sample.ts, sample.value, sample.max_hold) == (
        SampleKind.NUMBER,
        T0,
        31.5,
        policy.heishamon_max_age_s,
    )
    mode = sample_from_reading(Reading(MODE, 0, None, clock(), SourceKind.HEISHAMON), policy)
    assert mode is not None
    assert mode.kind is SampleKind.ENUM
    flag = sample_from_reading(Reading("x", True, None, clock(), SourceKind.MQTT), policy)
    assert flag is not None
    assert flag.kind is SampleKind.BOOL
    assert (
        sample_from_reading(Reading("t", "No error", None, clock(), SourceKind.HEISHAMON), policy)
        is None
    )
    retained = Reading(OUTLET, 31.5, "°C", clock(), SourceKind.HEISHAMON, retained=True)
    assert sample_from_reading(retained, policy) is None


def test_drop_oldest_queue_counts_overflow() -> None:
    queue: DropOldestQueue[int] = DropOldestQueue(3)
    for item in range(5):
        queue.put(item)
    assert queue.dropped == 2
    assert queue.drain(0.0, 10) == [2, 3, 4]
    assert queue.drain(0.01, 10) == []


def wait_for(condition: object, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if callable(condition) and condition():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met")


def test_writer_thread_batches_and_flushes_on_stop(db_path: Path) -> None:
    writer = HistoryWriter(db_path, Retention(), flush_interval=0.05)
    writer.start()
    wait_for(writer.healthy)
    for i in range(500):
        writer.offer(number(T0 + i, float(i % 7)))
    writer.stop()
    assert not writer.is_alive()
    assert raw_count(db_path) == 500
    assert 1 <= writer.stats.batches < 500
    assert writer.dropped_overflow == 0


def test_writer_drops_oldest_on_overflow(db_path: Path) -> None:
    writer = HistoryWriter(db_path, Retention(), queue_size=100)
    for i in range(250):
        writer.offer(number(T0 + i, float(i)))
    assert writer.dropped_overflow == 150
    writer.start()
    writer.stop()
    assert raw_count(db_path) == 100


def test_free_space_guard_pauses_and_resumes(db_path: Path) -> None:
    free = {"bytes": 10}
    writer = HistoryWriter(
        db_path,
        Retention(),
        min_free_bytes=1000,
        disk_check_interval=0.0,
        disk_free=lambda _path: free["bytes"],
    )
    writer.run_once([number(T0, 1.0), number(T0 + 1, 2.0)])
    assert writer.stats.paused
    assert not writer.healthy()
    assert writer.stats.dropped_paused == 2
    assert raw_count(db_path) == 0
    free["bytes"] = 1050
    writer.run_once([number(T0 + 2, 3.0)])
    assert writer.stats.paused
    free["bytes"] = 2000
    writer.run_once([number(T0 + 3, 4.0)])
    assert not writer.stats.paused
    assert raw_count(db_path) == 1
    writer.stop()


def test_writer_reports_error_when_database_cannot_open(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    writer = HistoryWriter(db_path, Retention(), disk_free=lambda _path: 10**12)
    writer.run_once([number(T0, 1.0)])
    assert writer.stats.error is not None
    assert "SchemaTooNewError" in writer.stats.error
    assert writer.stats.dropped_failed == 1


def test_raw_query_is_seeded_with_the_value_held_at_start(
    db: HistoryDatabase, db_path: Path
) -> None:
    db.write_batch([number(T0, 20.0), number(T0 + 100, 21.0), number(T0 + 400, 21.0)])
    unchanged = query_series(db_path, [OUTLET], T0 + 200, T0 + 300, 0)[OUTLET]
    assert unchanged.points == ((T0 + 200, 21.0),)
    later = query_series(db_path, [OUTLET], T0 + 50, T0 + 300, 0)[OUTLET]
    assert later.points == ((T0 + 50, 20.0), (T0 + 100, 21.0))
    exact = query_series(db_path, [OUTLET], T0 + 100, T0 + 300, 0)[OUTLET]
    assert exact.points == ((T0 + 100, 21.0),)
    before = query_series(db_path, [OUTLET], T0 - 100, T0 - 50, 0)[OUTLET]
    assert before.points == ()


def test_retention_keeps_the_newest_sample_of_each_signal(
    db: HistoryDatabase, db_path: Path
) -> None:
    now = T0 + 100 * DAY
    db.write_batch([number(T0, 1.0), number(T0 + 10, 2.0), enum(T0, 0)])
    db.forget_held()
    db.write_batch([number(now - DAY, 3.0)])
    db.apply_retention(Retention(raw_days=14), now)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name, ts, value FROM sample JOIN signal ON signal.id = signal_id ORDER BY name"
        ).fetchall()
    assert rows == [(OUTLET, now - DAY, 3.0), (MODE, T0, 0.0)]
    seeded = query_series(db_path, [MODE], now - 3600, now, 0)[MODE]
    assert seeded.points == ()


def test_gap_sample_ends_the_held_value(db: HistoryDatabase, db_path: Path) -> None:
    db.write_batch([number(T0, 10.0, hold=1800.0)])
    db.write_batch([Sample(OUTLET, None, SampleKind.NUMBER, T0 + 30, None, 0.0)])
    db.write_batch([number(T0 + 600, 10.0, hold=1800.0)])
    total = sum(duration for _, _, duration in rollup(db_path, 60))
    assert total == pytest.approx(30.0)
    db.write_batch([Sample("never/seen", None, SampleKind.NUMBER, T0, None, 0.0)])
    assert raw_count(db_path) == 2


def test_gap_sample_from_errors() -> None:
    clock = FakeClock(T0)
    live = ParseError(OUTLET, ParseErrorKind.MALFORMED, "x", "bad", clock())
    gap = gap_sample(live)
    assert gap is not None
    assert (gap.signal, gap.ts, gap.value) == (OUTLET, T0, None)
    retained = ParseError(OUTLET, ParseErrorKind.MALFORMED, "x", "bad", clock(), retained=True)
    assert gap_sample(retained) is None


def test_snapshot_is_consistent_and_restores_a_missing_database(
    db_path: Path, tmp_path: Path
) -> None:
    snapshot = tmp_path / "history.snapshot.db"
    db = HistoryDatabase(open_history(db_path))
    db.write_batch([number(T0 + i, float(i)) for i in range(100)])
    db.write_snapshot(snapshot)
    assert not snapshot.with_name(snapshot.name + ".tmp").exists()
    db.write_batch([number(T0 + 1000, 5000.0)])
    with sqlite3.connect(snapshot) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT count(*) FROM sample").fetchone()[0] == 100
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert restore_snapshot(db_path, snapshot) is False
    db.close()
    for suffix in ("", "-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
    assert restore_snapshot(db_path, snapshot) is True
    assert raw_count(db_path) == 100
    assert restore_snapshot(tmp_path / "other.db", tmp_path / "none.db") is False


def test_writer_writes_snapshots_and_restores_from_them(db_path: Path, tmp_path: Path) -> None:
    snapshot = tmp_path / "history.snapshot.db"
    writer = HistoryWriter(
        db_path,
        Retention(),
        snapshot_path=snapshot,
        snapshot_interval=3600.0,
        disk_free=lambda _path: 10**12,
    )
    writer.run_once([number(T0, 1.0), number(T0 + 1, 2.0)])
    assert writer.stats.snapshots == 1
    assert snapshot.is_file()
    writer.run_once([number(T0 + 2, 3.0)])
    assert writer.stats.snapshots == 1
    writer.stop()
    writer._close()
    for suffix in ("", "-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
    restored = HistoryWriter(
        db_path, Retention(), snapshot_path=snapshot, disk_free=lambda _path: 10**12
    )
    restored.run_once([])
    assert restored.stats.open
    assert restored.stats.snapshots == 0
    assert raw_count(db_path) == 2
    restored._close()


def test_writer_thread_death_is_detected_and_restarted(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = HistoryWriter(db_path, Retention(), flush_interval=0.01)
    original = writer.run_once
    crashes = {"left": 1}

    def crash_once(batch: list[Sample]) -> None:
        if crashes["left"] and batch:
            crashes["left"] -= 1
            raise RuntimeError("disk on fire")
        original(batch)

    monkeypatch.setattr(writer, "run_once", crash_once)
    writer.start()
    wait_for(writer.healthy)
    writer.offer(number(T0, 1.0))
    wait_for(lambda: not writer.is_alive())
    assert writer.stats.error == "writer crashed"
    assert not writer.healthy()
    writer.start()
    wait_for(writer.healthy)
    writer.offer(number(T0 + 10, 2.0))
    writer.stop()
    assert raw_count(db_path) == 1


class BrokenBackup:
    def backup(self, dest: sqlite3.Connection) -> None:
        dest.execute("CREATE TABLE junk (x)")
        raise sqlite3.OperationalError("database or disk is full")


def test_failed_snapshot_removes_its_temp_file(tmp_path: Path) -> None:
    snapshot = tmp_path / "history.snapshot.db"
    tmp = snapshot.with_name(snapshot.name + ".tmp")
    with pytest.raises(sqlite3.OperationalError):
        write_snapshot(cast(sqlite3.Connection, BrokenBackup()), snapshot)
    assert not tmp.exists()
    assert not snapshot.exists()


def test_snapshot_is_skipped_without_room_and_leftover_temp_never_pauses(
    db_path: Path, tmp_path: Path
) -> None:
    snapshot = tmp_path / "history.snapshot.db"
    tmp = snapshot.with_name(snapshot.name + ".tmp")
    tmp.write_bytes(b"leftover")
    free = {"bytes": 10**12}
    writer = HistoryWriter(
        db_path,
        Retention(),
        min_free_bytes=1000,
        snapshot_path=snapshot,
        snapshot_interval=0.0,
        disk_check_interval=10**9,
        disk_free=lambda _path: free["bytes"],
    )
    writer.run_once([number(T0, 1.0)])
    assert writer.stats.snapshots == 1
    assert not tmp.exists()
    size = db_path.stat().st_size
    free["bytes"] = 1000 + size - 1
    tmp.write_bytes(b"leftover")
    writer.run_once([number(T0 + 1, 2.0)])
    assert writer.stats.snapshots == 1
    assert writer.stats.snapshots_skipped == 1
    assert not tmp.exists()
    assert not writer.stats.paused
    assert writer.stats.error is None
    free["bytes"] = 10**12
    writer.run_once([number(T0 + 2, 3.0)])
    assert writer.stats.snapshots == 2
    writer.stop()


def test_first_snapshot_waits_for_the_first_commit(db_path: Path, tmp_path: Path) -> None:
    snapshot = tmp_path / "history.snapshot.db"
    writer = HistoryWriter(
        db_path,
        Retention(),
        snapshot_path=snapshot,
        snapshot_interval=0.0,
        disk_free=lambda _path: 10**12,
    )
    writer.run_once([])
    assert writer.stats.open
    assert writer.stats.snapshots == 0
    assert not snapshot.exists()
    writer.run_once([number(T0, 1.0)])
    assert writer.stats.snapshots == 1
    with sqlite3.connect(snapshot) as conn:
        assert conn.execute("SELECT count(*) FROM sample").fetchone()[0] == 1
    writer.stop()


def test_raw_seed_respects_the_staleness_limit(db: HistoryDatabase, db_path: Path) -> None:
    db.write_batch([number(T0, 20.0)])
    fresh = query_series(db_path, [OUTLET], T0 + 300, T0 + 600, 0)[OUTLET]
    assert fresh.points == ((T0 + 300, 20.0),)
    stale = query_series(db_path, [OUTLET], T0 + 331, T0 + 600, 0)[OUTLET]
    assert stale.points == ()
    custom = query_series(
        db_path,
        [OUTLET],
        T0 + 331,
        T0 + 600,
        0,
        StalenessPolicy(heishamon_max_age_s=1000.0),
    )[OUTLET]
    assert custom.points == ((T0 + 331, 20.0),)


def test_writer_health_is_starting_until_open(db_path: Path) -> None:
    writer = HistoryWriter(db_path, Retention(), disk_free=lambda _path: 10**12)
    assert writer.starting()
    assert not writer.healthy()
    writer.run_once([])
    assert not writer.starting()
    assert writer.stats.open
    writer.stop()
    assert not writer.starting()

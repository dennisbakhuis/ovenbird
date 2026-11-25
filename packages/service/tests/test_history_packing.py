"""Packed decision journal, its migration, live retention changes and compaction."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from ovenbird.history import Retention
from ovenbird.history.journal import (
    CommandRow,
    DecisionRow,
    decision_state_series,
    delete_journal_before,
    iter_decisions,
    query_decisions,
    write_journal,
)
from ovenbird.history.packing import DecisionPacker, dictionary_from, pack, unpack
from ovenbird.history.schema import bundled_migrations, migrate, open_history
from ovenbird.history.writer import HistoryWriter

T0 = 1_800_000_000.0
DAY = 86_400.0


def row(ts: float, setpoint: int = 30, note: str = "ok") -> DecisionRow:
    record = json.dumps(
        {
            "at": ts,
            "note": note,
            "setpoint": setpoint,
            "controller_state": {"outside_filtered_c": setpoint / 10},
            "terms": [{"name": "curve", "raw": 30.0, "value": 30.0}],
        },
        sort_keys=True,
    )
    arbiter = json.dumps([{"kind": "water_setpoint", "value": setpoint}])
    return DecisionRow(
        ts, "ovenbird", "shadow", "curve_only", "curve", setpoint, record, arbiter, "[]", 3
    )


def test_pack_round_trips_texts_byte_for_byte() -> None:
    record = '{"a": "é\\n", "b": [1, 2.50]}'
    dictionary = dictionary_from(record, "[]")
    for zdict in (None, dictionary):
        body = pack(record, "[]", '[{"x": 1}]', zdict)
        assert unpack(body, zdict) == (record, "[]", '[{"x": 1}]')


def test_unpack_refuses_a_foreign_body() -> None:
    with pytest.raises(ValueError, match="not a packed decision"):
        unpack(b"plain text", None)


def test_a_dictionary_makes_similar_records_much_smaller() -> None:
    first, second = row(T0, 30), row(T0 + 60, 31)
    zdict = dictionary_from(first.record, first.arbiter)
    plain = pack(second.record, second.arbiter, second.commands, None)
    primed = pack(second.record, second.arbiter, second.commands, zdict)
    assert len(primed) < len(plain) / 2


def test_journal_reads_back_what_was_written(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    conn = open_history(path)
    rows = [row(T0 + 60 * i, 30 + i % 3, note=f"tick {i}") for i in range(10)]
    write_journal(conn, rows, [])
    conn.close()
    assert query_decisions(path, 0, T0 + DAY, 100) == rows
    assert list(iter_decisions(path, 0, T0 + DAY, batch=3)) == rows
    assert list(iter_decisions(path, T0 + 120, T0 + 300, batch=2)) == rows[2:5]


def test_the_packer_starts_a_new_dictionary_once_a_day(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    conn = open_history(path)
    packer = DecisionPacker()
    write_journal(conn, [row(T0), row(T0 + 60)], [], packer=packer)
    write_journal(conn, [row(T0 + DAY + 60)], [], packer=packer)
    ids = [r[0] for r in conn.execute("SELECT dictionary_id FROM decision ORDER BY id")]
    assert ids == [1, 1, 2]
    assert delete_journal_before(conn, T0 + DAY) == 2
    remaining = [r[0] for r in conn.execute("SELECT id FROM decision_dictionary")]
    assert remaining == [2]
    conn.close()
    assert [r.ts for r in query_decisions(path, 0, T0 + 2 * DAY, 10)] == [T0 + DAY + 60]


def test_a_rolled_back_batch_forgets_the_new_dictionary(tmp_path: Path) -> None:
    conn = open_history(tmp_path / "history.db")
    packer = DecisionPacker()
    broken = DecisionRow(T0, "ovenbird", "shadow", "curve_only", "curve", 30, "{}", "[]", "[]")
    conn.execute(
        "CREATE TRIGGER refuse BEFORE INSERT ON command BEGIN SELECT RAISE(ABORT, 'no'); END"
    )

    with pytest.raises(sqlite3.IntegrityError):
        write_journal(
            conn, [broken], [CommandRow(T0, "k", 1, "sent", 1, None, None, "")], packer=packer
        )
    conn.execute("DROP TRIGGER refuse")
    write_journal(conn, [row(T0)], [], packer=packer)
    assert conn.execute("SELECT id FROM decision_dictionary").fetchall() == [(1,)]
    conn.close()


def test_state_series_reads_packed_records(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    conn = open_history(path)
    write_journal(conn, [row(T0 + 60 * i, 30 + i) for i in range(4)], [])
    conn.close()
    series = decision_state_series(path, "outside_filtered_c", T0, T0 + 600, 120)
    assert series == [(T0, 3.1), (T0 + 120, 3.3)]


def legacy_database(path: Path, rows: list[DecisionRow]) -> None:
    conn = sqlite3.connect(path, isolation_level=None)
    migrate(conn, bundled_migrations()[:5])
    conn.executemany(
        "INSERT INTO decision (ts, controller, mode, ladder, reason, setpoint, record, arbiter, "
        "commands, config_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                r.ts,
                r.controller,
                r.mode,
                r.ladder,
                r.reason,
                r.setpoint,
                r.record,
                r.arbiter,
                r.commands,
                r.config_version,
            )
            for r in rows
        ],
    )
    conn.close()


def test_migration_packs_existing_rows_without_changing_them(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    rows = [row(T0 + 60 * i, 30 + i % 4, note=f"n{i}") for i in range(50)]
    legacy_database(path, rows)
    assert query_decisions(path, 0, T0 + DAY, 100) == rows
    open_history(path).close()
    with sqlite3.connect(path) as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(decision)")}
        assert {"body", "dictionary_id"} <= columns
        assert "record" not in columns
        assert conn.execute("SELECT count(*) FROM decision_dictionary").fetchone() == (1,)
    assert query_decisions(path, 0, T0 + DAY, 100) == rows


def test_migration_of_an_empty_journal(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    legacy_database(path, [])
    conn = open_history(path)
    assert conn.execute("SELECT count(*) FROM decision_dictionary").fetchone() == (0,)
    write_journal(conn, [row(T0)], [])
    conn.close()
    assert query_decisions(path, 0, T0 + DAY, 10) == [row(T0)]


def test_a_new_database_uses_incremental_auto_vacuum(tmp_path: Path) -> None:
    conn = open_history(tmp_path / "history.db")
    assert conn.execute("PRAGMA auto_vacuum").fetchone() == (2,)
    conn.close()


def make_writer(path: Path, **kwargs: object) -> HistoryWriter:
    return HistoryWriter(path, Retention(), min_free_bytes=0, wall=lambda: T0 + 40 * DAY, **kwargs)  # type: ignore[arg-type]


def test_a_retention_change_applies_at_the_next_batch(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    writer = make_writer(path, journal_days=None)
    writer.run_once([row(T0 + DAY * day) for day in range(40)])
    writer.run_once([])
    assert len(query_decisions(path, 0, T0 + 50 * DAY, 100)) == 40
    writer.set_retention(Retention(), 10.0)
    writer.run_once([])
    kept = query_decisions(path, 0, T0 + 50 * DAY, 100)
    assert [r.ts for r in kept] == [T0 + DAY * day for day in range(30, 40)]
    writer._close()


def test_compaction_converts_and_shrinks_the_file(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    legacy_database(path, [row(T0 + 60 * i, note=f"{i} " + "x" * 2000) for i in range(3000)])
    before = path.stat().st_size
    writer = make_writer(path)
    writer.run_once([])
    assert writer.compaction.last_at == T0 + 40 * DAY
    assert writer.compaction.freed_bytes is not None
    assert writer.compaction.freed_bytes > 0
    writer._close()
    assert path.stat().st_size < before / 2
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA auto_vacuum").fetchone() == (2,)


def test_compaction_on_request_and_refused_without_space(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    writer = HistoryWriter(
        path, Retention(), min_free_bytes=10, disk_free=lambda _: 10**12, wall=lambda: T0
    )
    writer.run_once([row(T0)])
    assert writer.request_compaction() is True
    assert writer.request_compaction() is False
    writer.run_once([])
    assert writer.compaction.last_at == T0
    assert writer.compaction.error is None
    writer._disk_free = lambda _: 0
    writer.request_compaction()
    writer.run_once([])
    assert writer.compaction.error is not None
    assert "not enough free space" in writer.compaction.error
    writer._close()

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from climate_manager_capture.capture import (
    CaptureReader,
    CaptureWriter,
    Record,
    day_of,
    is_retained,
    parse_when,
    topic_suffix,
)
from climate_manager_capture.testing import FakeClock

DAY1 = datetime(2026, 3, 1, 23, 59, 50, tzinfo=UTC).timestamp()
DAY2 = datetime(2026, 3, 2, 0, 0, 5, tzinfo=UTC).timestamp()


def test_record_json_roundtrip() -> None:
    record = Record(1700000000.1234, "a/b", "1.5", retained=True)
    parsed = Record.from_json(record.to_json())
    assert parsed == Record(1700000000.123, "a/b", "1.5", retained=True)
    assert Record.from_json('{"v":1,"name":"x"}') is None
    assert Record.from_json("   ") is None
    assert '"r"' not in Record(1.0, "a", "b").to_json()


@pytest.mark.parametrize(
    ("topic", "payload", "expected"),
    [
        ("panasonic_heat_pump/main/Outside_Temp", "3", True),
        ("panasonic_heat_pump/commands/SetHeatpump", "1", False),
        ("panasonic_heat_pump/log", "x", False),
        ("panasonic_heat_pump/LWT", "Online", False),
        ("panasonic_heat_pump/LWT", "Offline", True),
        ("panasonic_heat_pump/stats", "{}", True),
        ("climate_manager_capture/room_temp", "20.1", True),
    ],
)
def test_is_retained(topic: str, payload: str, expected: bool) -> None:
    assert is_retained(topic, payload) is expected


def test_topic_suffix() -> None:
    assert topic_suffix("base/main/X", "base") == "main/X"
    assert topic_suffix("other/main/X", "base") is None


def test_parse_when_offsets_and_iso() -> None:
    start = 1000.0
    assert parse_when("+90", start) == 1090.0
    assert parse_when("+1h30m", start) == 1000.0 + 5400.0
    assert parse_when("+2d", start) == 1000.0 + 172800.0
    iso = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert parse_when(iso.isoformat(), start) == iso.timestamp()
    with pytest.raises(ValueError, match="invalid offset"):
        parse_when("+abc", start)


def test_writer_rotates_and_gzips_previous_day(tmp_path: Path) -> None:
    clock = FakeClock(DAY1)
    writer = CaptureWriter(tmp_path, "cap", header={"broker": "x"}, clock=clock)
    writer.write(Record(DAY1, "b/main/A", "1"))
    writer.write(Record(DAY1 + 5, "b/main/A", "2"))
    clock.now = DAY2
    writer.write(Record(DAY2, "b/main/A", "3"))
    writer.close()

    names = sorted(p.name for p in (tmp_path / "cap").iterdir())
    assert names == ["2026-03-01.jsonl.gz", "2026-03-02.jsonl", "meta.json"]
    with gzip.open(tmp_path / "cap" / "2026-03-01.jsonl.gz", "rt") as fh:
        lines = fh.read().splitlines()
    assert json.loads(lines[0])["v"] == 1
    assert json.loads(lines[0])["broker"] == "x"
    assert len(lines) == 3
    meta = json.loads((tmp_path / "cap" / "meta.json").read_text())
    assert meta["name"] == "cap"

    reader = CaptureReader(tmp_path / "cap")
    records = list(reader.iter_records())
    assert [r.payload for r in records] == ["1", "2", "3"]
    assert reader.bounds() == (DAY1, DAY2)


def test_writer_resumes_active_day_without_second_header(tmp_path: Path) -> None:
    clock = FakeClock(DAY2)
    first = CaptureWriter(tmp_path, "cap", clock=clock)
    first.write(Record(DAY2, "b/main/A", "1"))
    first.close()
    second = CaptureWriter(tmp_path, "cap", clock=clock)
    second.write(Record(DAY2 + 1, "b/main/A", "2"))
    second.close()
    lines = (tmp_path / "cap" / "2026-03-02.jsonl").read_text().splitlines()
    assert sum(1 for line in lines if '"v":1' in line) == 1
    assert len(lines) == 3
    assert "resumed" in json.loads((tmp_path / "cap" / "meta.json").read_text())


def test_writer_compresses_leftover_days_on_start(tmp_path: Path) -> None:
    stale = tmp_path / "cap" / "2026-02-28.jsonl"
    stale.parent.mkdir()
    stale.write_text('{"v":1}\n{"t":1,"k":"a","p":"b"}\n')
    writer = CaptureWriter(tmp_path, "cap", clock=FakeClock(DAY2))
    writer.close()
    assert not stale.exists()
    assert stale.with_suffix(".jsonl.gz").exists()


def test_reader_prefers_plain_over_gzip_twin(tmp_path: Path) -> None:
    directory = tmp_path / "cap"
    directory.mkdir()
    (directory / "2026-03-02.jsonl").write_text('{"t":5,"k":"a","p":"plain"}\n')
    with gzip.open(directory / "2026-03-02.jsonl.gz", "wt") as fh:
        fh.write('{"t":5,"k":"a","p":"gz"}\n')
    assert [r.payload for r in CaptureReader(directory).iter_records()] == ["plain"]


def test_reader_window_and_snapshot(tmp_path: Path) -> None:
    writer = CaptureWriter(tmp_path, "cap", clock=FakeClock(DAY1))
    base = "panasonic_heat_pump"
    writer.write(Record(DAY1, f"{base}/main/A", "1", retained=True))
    writer.write(Record(DAY1 + 1, f"{base}/LWT", "Offline", retained=True))
    writer.write(Record(DAY1 + 2, f"{base}/LWT", "Online"))
    writer.write(Record(DAY1 + 3, f"{base}/commands/SetHeatpump", "1"))
    writer.write(Record(DAY1 + 4, f"{base}/main/A", "2"))
    writer.write(Record(DAY1 + 6, f"{base}/main/A", "3"))
    writer.close()
    reader = CaptureReader(tmp_path / "cap")

    window = list(reader.iter_records(DAY1 + 2, DAY1 + 6))
    assert [r.t - DAY1 for r in window] == [2, 3, 4]

    snapshot = reader.snapshot_at(DAY1 + 5)
    assert snapshot == {f"{base}/main/A": "2", f"{base}/LWT": "Offline"}


def test_day_of_is_utc() -> None:
    assert day_of(DAY1) == "2026-03-01"
    assert day_of(DAY2) == "2026-03-02"


def test_reader_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        CaptureReader(tmp_path / "nope")

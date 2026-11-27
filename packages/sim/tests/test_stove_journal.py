"""The learner's reading of the stove journal: orphan episodes are capped."""

from __future__ import annotations

from pathlib import Path

import pytest

from ovenbird_sim.data import events as ev
from ovenbird_sim.data.historydb import OPEN_EPISODE_MAX_S, read_stove_journal

history = pytest.importorskip("ovenbird.history")
from ovenbird.history import open_history  # noqa: E402
from ovenbird.history.journal import AlarmRow, write_journal  # noqa: E402

T0 = 1_800_000_000.0
HOUR = 3600.0
DAY = 86_400.0


def journal(tmp_path: Path, rows: list[tuple[float, str]]) -> list[AlarmRow]:
    return [AlarmRow(ts, "stove_mode", "info", event, "", "{}") for ts, event in rows]


def read(
    tmp_path: Path, rows: list[tuple[float, str]], end: float
) -> tuple[tuple[ev.Event, ...], list[float]]:
    conn = open_history(tmp_path / "history.db")
    try:
        write_journal(conn, [], [], journal(tmp_path, rows))
        capped: list[float] = []
        found = read_stove_journal(conn, T0, end, capped)
    finally:
        conn.close()
    return found, capped


def test_normal_pairs_are_unchanged(tmp_path: Path) -> None:
    found, capped = read(
        tmp_path,
        [
            (T0 + HOUR, "started"),
            (T0 + 5 * HOUR, "expired"),
            (T0 + DAY, "started"),
            (T0 + DAY + 2 * HOUR, "released"),
        ],
        T0 + 10 * DAY,
    )
    assert [(e.start, e.end) for e in found] == [
        (T0 + HOUR, T0 + 5 * HOUR),
        (T0 + DAY, T0 + DAY + 2 * HOUR),
    ]
    assert found[0].tail_end == T0 + 5 * HOUR + ev.TAIL_S
    assert capped == []


def test_an_orphan_started_is_closed_at_the_next_started(tmp_path: Path) -> None:
    found, capped = read(
        tmp_path,
        [(T0 + HOUR, "started"), (T0 + 3 * HOUR, "started"), (T0 + 6 * HOUR, "expired")],
        T0 + 30 * DAY,
    )
    assert [(e.start, e.end) for e in found] == [
        (T0 + HOUR, T0 + 3 * HOUR),
        (T0 + 3 * HOUR, T0 + 6 * HOUR),
    ]
    assert capped == [T0 + HOUR]


def test_an_orphan_started_masks_at_most_a_day_plus_the_tail(tmp_path: Path) -> None:
    found, capped = read(
        tmp_path,
        [(T0 + HOUR, "started"), (T0 + 20 * DAY, "started"), (T0 + 20 * DAY + HOUR, "expired")],
        T0 + 30 * DAY,
    )
    assert found[0].end == T0 + HOUR + OPEN_EPISODE_MAX_S
    assert found[0].tail_end == found[0].end + ev.TAIL_S
    assert found[1].start == T0 + 20 * DAY
    assert capped == [T0 + HOUR]


def test_an_open_episode_at_the_dataset_end_is_capped(tmp_path: Path) -> None:
    found, capped = read(tmp_path, [(T0 + HOUR, "started")], T0 + 30 * DAY)
    assert found[0].end == T0 + HOUR + OPEN_EPISODE_MAX_S
    assert capped == [T0 + HOUR]


def test_a_running_episode_at_the_dataset_end_keeps_the_end(tmp_path: Path) -> None:
    found, capped = read(tmp_path, [(T0 + HOUR, "started")], T0 + 3 * HOUR)
    assert found[0].end == T0 + 3 * HOUR
    assert capped == []

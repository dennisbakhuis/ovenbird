from __future__ import annotations

from pathlib import Path

import pytest

from ovenbird.control.alarms import AlarmBoard, AlarmEvent
from ovenbird.control.forecastread import (
    FORECAST_STALE_S,
    STOVE_TAIL_S,
    ForecastWindow,
    Guard,
    PlanContext,
    StoveTail,
    forecast_stale,
    guards,
    in_stove_tail,
    live_guards,
    load_forecast,
    load_stove_end,
)
from ovenbird.history import open_history
from ovenbird.history.forecast import ForecastRow, write_forecast
from ovenbird.history.journal import AlarmRow, write_journal
from ovenbird.stove.request import STOVE_JOURNAL_CODE
from ovenbird_core import Instant
from ovenbird_core.control import OvenbirdConfig
from ovenbird_core.control.forecast import HOUR_S, ForecastHour

T0 = 1_794_009_600.0
CONFIG = OvenbirdConfig.preset("mixed")


def context(
    ts: float = T0,
    *,
    room: bool = True,
    stove: bool = False,
    outside: float | None = 3.0,
    away: bool = False,
) -> PlanContext:
    """Build a plan context with room trust, stove, outside temperature and away flags."""
    return PlanContext(Instant.from_unix(ts), room, stove, outside, CONFIG, away=away)


def fresh() -> ForecastWindow:
    """Return a forecast window issued ten minutes ago, hence not stale."""
    return ForecastWindow((), T0 - 600.0)


def history(tmp_path: Path) -> Path:
    """Create an empty history database in tmp_path and return its path."""
    path = tmp_path / "history.db"
    open_history(path).close()
    return path


def write_issue(path: Path, issued: float, hours: range, sun: float = 100.0) -> None:
    """Write one forecast issue with a row per given hour offset and the given solar irradiance."""
    conn = open_history(path)
    try:
        rows = [ForecastRow(issued, T0 + HOUR_S * h, 2.0 + h, sun, 40.0, 3.0) for h in hours]
        write_forecast(conn, rows)
    finally:
        conn.close()


def write_stove(path: Path, *rows: tuple[float, str]) -> None:
    """Write stove journal entries, given as (timestamp, event) pairs, to the history database."""
    conn = open_history(path)
    try:
        alarms = [
            AlarmRow(ts, STOVE_JOURNAL_CODE, "info", event, "stove", "{}") for ts, event in rows
        ]
        write_journal(conn, [], [], alarms)
    finally:
        conn.close()


class TestLoadForecast:
    """Reading the forecast window from the history database."""

    def test_reads_the_shortest_lead_row_per_hour(self, tmp_path: Path) -> None:
        """The newest issue wins per target hour, falling back to older issues for earlier hours."""
        path = history(tmp_path)
        write_issue(path, T0 - 7200.0, range(-2, 8), sun=50.0)
        write_issue(path, T0 - 600.0, range(8), sun=100.0)
        window = load_forecast(path, T0, horizon_h=6.0)
        assert window.newest_issue == T0 - 600.0
        by_hour = {row.target_ts: row for row in window.hours}
        assert by_hour[T0 - HOUR_S].ghi_w_m2 == 50.0
        assert by_hour[T0 + HOUR_S].ghi_w_m2 == 100.0
        assert by_hour[T0 + HOUR_S].outside_c == 3.0
        assert all(row.target_ts % HOUR_S == 0.0 for row in window.hours)

    def test_ignores_issues_made_after_now(self, tmp_path: Path) -> None:
        """Forecast issues dated after the current time are ignored."""
        path = history(tmp_path)
        write_issue(path, T0 + 600.0, range(4))
        window = load_forecast(path, T0, horizon_h=6.0)
        assert window == ForecastWindow((), None)

    def test_a_value_it_cannot_use_is_missing(self, tmp_path: Path) -> None:
        """A forecast value outside the usable range is read as missing."""
        path = history(tmp_path)
        write_issue(path, T0 - 600.0, range(2), sun=-5.0)
        window = load_forecast(path, T0, horizon_h=6.0)
        assert window.hours == (ForecastHour(T0, None, None), ForecastHour(T0 + HOUR_S, None, None))

    def test_an_empty_history_has_no_forecast(self, tmp_path: Path) -> None:
        """A history without forecasts yields an empty window with no issue time."""
        assert load_forecast(history(tmp_path), T0, horizon_h=6.0) == ForecastWindow((), None)


class TestGuards:
    """Guards that block the planned control: stale forecast, untrusted room, stove, away."""

    def test_nothing_blocks_a_fresh_forecast_and_a_trusted_room(self) -> None:
        """A fresh forecast with a trusted room triggers no guard."""
        assert guards(context(), fresh(), None) == ()

    @pytest.mark.parametrize(
        ("issued", "stale"),
        [(None, True), (T0 - FORECAST_STALE_S, False), (T0 - FORECAST_STALE_S - 1.0, True)],
    )
    def test_forecast_stale(self, issued: float | None, stale: bool) -> None:
        """The forecast is stale when missing or older than the stale limit."""
        window = ForecastWindow((), issued)
        assert forecast_stale(window, T0) is stale
        assert (Guard.FORECAST_STALE in guards(context(), window, None)) is stale

    def test_room_untrusted(self) -> None:
        """An untrusted room signal raises the room guard."""
        assert live_guards(context(room=False), None) == (Guard.ROOM_UNTRUSTED,)

    def test_stove_active(self) -> None:
        """An active stove raises the stove guard."""
        assert live_guards(context(stove=True), None) == (Guard.STOVE_ACTIVE,)

    def test_stove_tail(self) -> None:
        """The stove tail guard holds for the tail period after the stove ended, no longer."""
        assert in_stove_tail(T0 - STOVE_TAIL_S + 1.0, T0)
        assert not in_stove_tail(T0 - STOVE_TAIL_S, T0)
        assert not in_stove_tail(T0 + 60.0, T0)
        assert not in_stove_tail(None, T0)
        assert live_guards(context(), T0 - 3600.0) == (Guard.STOVE_TAIL,)

    def test_away(self) -> None:
        """The away flag raises the away guard."""
        assert live_guards(context(away=True), None) == (Guard.AWAY,)

    def test_every_guard_is_reported_in_the_fixed_order(self) -> None:
        """All guards are reported together, in the fixed enum order."""
        ctx = context(room=False, stove=True, away=True)
        found = guards(ctx, ForecastWindow((), None), T0 - 60.0)
        assert found == tuple(Guard)


class TestStoveTail:
    """Tracking when the last stove episode ended, in memory and from the journal."""

    def test_the_end_is_noted_when_an_episode_ends(self) -> None:
        """Tracking notes the end time when the stove goes from active to inactive and keeps it."""
        tail = StoveTail()
        assert tail.track(context(stove=True)) is None
        assert tail.track(context(T0 + 60.0)) == T0 + 60.0
        assert tail.track(context(T0 + 120.0)) == T0 + 60.0

    def test_the_end_is_read_back_from_the_journal(self, tmp_path: Path) -> None:
        """The end of the last episode is restored from the journal and drives the tail guard."""
        path = history(tmp_path)
        write_stove(path, (T0 - 7200.0, "started"), (T0 - 3600.0, "expired"))
        assert load_stove_end(path, T0) == T0 - 3600.0
        tail = StoveTail()
        tail.restore(path, AlarmBoard(), context())
        assert tail.end == T0 - 3600.0
        assert live_guards(context(), tail.track(context())) == (Guard.STOVE_TAIL,)

    def test_an_end_older_than_the_tail_is_not_read(self, tmp_path: Path) -> None:
        """An episode that ended longer ago than the tail period is not restored."""
        path = history(tmp_path)
        write_stove(
            path, (T0 - STOVE_TAIL_S - 7200.0, "started"), (T0 - STOVE_TAIL_S - 60.0, "released")
        )
        assert load_stove_end(path, T0) is None

    def test_an_orphaned_episode_is_closed_once_at_start(self, tmp_path: Path) -> None:
        """An episode left open in the journal is closed once at start, not on a second restore."""
        path = history(tmp_path)
        write_stove(path, (T0 - 7200.0, "started"))
        journal: list[AlarmEvent] = []
        board = AlarmBoard(journal.append)
        tail = StoveTail()
        tail.restore(path, board, context())
        tail.restore(path, board, context())
        assert tail.end == T0
        assert [(e.code, e.event.value) for e in journal] == [(STOVE_JOURNAL_CODE, "expired")]
        assert not board.history

    def test_a_restored_active_episode_is_left_open(self, tmp_path: Path) -> None:
        """An episode still active at restore stays open and leaves the journal untouched."""
        path = history(tmp_path)
        write_stove(path, (T0 - 7200.0, "started"))
        journal: list[AlarmEvent] = []
        tail = StoveTail()
        tail.restore(path, AlarmBoard(journal.append), context(stove=True))
        assert tail.end is None
        assert journal == []

    def test_a_journal_that_cannot_be_read_leaves_the_end_unknown(self, tmp_path: Path) -> None:
        """An unreadable history leaves the end unknown instead of failing."""
        tail = StoveTail()
        tail.restore(tmp_path / "missing" / "history.db", AlarmBoard(), context())
        assert tail.end is None

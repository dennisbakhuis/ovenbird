from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from ovenbird_core.instant import Instant


def test_from_capture_uses_unix_time_on_both_axes() -> None:
    instant = Instant.from_capture(1794528003.813)
    assert instant.monotonic == 1794528003.813
    assert instant.wall == datetime.fromtimestamp(1794528003.813, UTC)
    assert instant.wall.tzinfo is UTC


def test_wall_clock_is_normalised_to_utc() -> None:
    cet = timezone(timedelta(hours=1))
    instant = Instant(10.0, datetime(2026, 11, 13, 8, 0, tzinfo=cet))
    assert instant.wall == datetime(2026, 11, 13, 7, 0, tzinfo=UTC)
    assert instant.wall.tzinfo is UTC


def test_naive_wall_clock_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Instant(0.0, datetime(2026, 11, 13, 8, 0))


def test_non_finite_monotonic_is_rejected() -> None:
    with pytest.raises(ValueError, match="finite"):
        Instant(float("nan"), datetime(2026, 11, 13, tzinfo=UTC))


def test_ordering_and_elapsed_follow_the_monotonic_axis() -> None:
    wall = datetime(2026, 11, 13, tzinfo=UTC)
    early = Instant(100.0, wall)
    late = Instant(160.0, wall - timedelta(hours=1))
    assert early < late
    assert late.since(early) == 60.0
    assert Instant(100.0, wall + timedelta(days=1)) == early


def test_shifted_moves_both_axes() -> None:
    start = Instant.from_unix(1_000.0)
    later = start.shifted(30.0)
    assert later.since(start) == 30.0
    assert later.wall - start.wall == timedelta(seconds=30)

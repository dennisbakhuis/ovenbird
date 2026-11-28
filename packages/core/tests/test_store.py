"""Tests for the state store: freshness, liveness, invalidation and snapshots."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ovenbird_core.catalogue import HeishaSignal
from ovenbird_core.heishamon import Heartbeat, LwtNotice
from ovenbird_core.inputs import ha_reading, ha_signal
from ovenbird_core.instant import Instant
from ovenbird_core.readings import Ignored, ParseError, ParseErrorKind, Reading, SourceKind, Value
from ovenbird_core.store import (
    HEISHAMON_LIVENESS_S,
    HEISHAMON_MAX_AGE_S,
    StalenessPolicy,
    StateStore,
)

T0 = 1_794_528_000.0
OUTLET = HeishaSignal.OUTLET_TEMP
ROOM = "sensor.living_room_temperature"


def at(seconds: float) -> Instant:
    """Return the instant ``seconds`` after the test epoch."""
    return Instant.from_unix(T0 + seconds)


def hp(signal: str, value: Value, seconds: float, *, retained: bool = False) -> Reading:
    """Build a HeishaMon reading of ``signal`` at ``seconds`` after the test epoch."""
    return Reading(signal, value, "°C", at(seconds), SourceKind.HEISHAMON, retained)


def heartbeat(seconds: float, *, retained: bool = False) -> Heartbeat:
    """Build a HeishaMon stats heartbeat at ``seconds`` after the test epoch."""
    return Heartbeat(at(seconds), retained, uptime_s=seconds, version="v4.2.3")


def test_unknown_signal_has_no_age_and_is_stale() -> None:
    """A signal never seen has no age, is not fresh and has no latest value."""
    store = StateStore()
    assert store.age(OUTLET, at(0)) is None
    assert store.is_fresh(OUTLET, at(0)) is False
    assert store.latest(OUTLET) is None
    assert store.snapshot(at(0)).get(OUTLET) is None


def test_heishamon_value_goes_stale_after_330_seconds() -> None:
    """A HeishaMon value is fresh for 330 s after its reading."""
    store = StateStore()
    assert store.apply(hp(OUTLET, 30.0, 0))
    assert store.age(OUTLET, at(100)) == 100
    assert store.is_fresh(OUTLET, at(HEISHAMON_MAX_AGE_S))
    assert not store.is_fresh(OUTLET, at(HEISHAMON_MAX_AGE_S + 0.1))


def test_periodic_dump_keeps_unchanged_values_fresh() -> None:
    """Repeated unchanged values from periodic dumps keep a signal fresh."""
    store = StateStore()
    for dump in range(0, 3600, 300):
        store.apply(hp(OUTLET, 30.0, dump))
        assert store.is_fresh(OUTLET, at(dump + 299))
    assert store.age(OUTLET, at(3600)) == 300


def test_retained_delivery_never_refreshes_freshness() -> None:
    """A retained redelivery of the same value does not refresh the signal."""
    store = StateStore()
    store.apply(hp(OUTLET, 30.0, 0))
    assert store.apply(hp(OUTLET, 30.0, 200, retained=True)) is False
    assert store.age(OUTLET, at(400)) == 400
    assert not store.is_fresh(OUTLET, at(400))


def test_retained_delivery_with_a_new_value_has_unknown_age() -> None:
    """A retained value that differs is stored but is stale with unknown age."""
    store = StateStore()
    store.apply(hp(OUTLET, 30.0, 0))
    assert store.apply(hp(OUTLET, 32.0, 10, retained=True))
    view = store.snapshot(at(11)).get(OUTLET)
    assert view is not None
    assert view.value == 32.0
    assert view.age is None
    assert view.fresh is False
    assert view.retained is True


def test_startup_from_retained_store_is_stale_until_a_live_update() -> None:
    """A value known only from retained messages stays stale until a live update arrives."""
    store = StateStore()
    store.apply(hp(OUTLET, 30.0, 0, retained=True))
    assert store.latest(OUTLET) is not None
    assert not store.is_fresh(OUTLET, at(1))
    store.apply(hp(OUTLET, 30.0, 120))
    assert store.is_fresh(OUTLET, at(121))
    assert store.age(OUTLET, at(121)) == 1


def test_out_of_order_reading_is_dropped() -> None:
    """A reading older than the stored one is dropped."""
    store = StateStore()
    store.apply(hp(OUTLET, 31.0, 10))
    assert store.apply(hp(OUTLET, 30.0, 5)) is False
    latest = store.latest(OUTLET)
    assert latest is not None
    assert latest.value == 31.0


def test_age_is_never_negative() -> None:
    """Asking for the age before the reading time gives zero."""
    store = StateStore()
    store.apply(hp(OUTLET, 30.0, 10))
    assert store.age(OUTLET, at(5)) == 0


def test_room_temperature_defaults_to_thirty_minutes() -> None:
    """A Home Assistant value stays fresh for 30 minutes by default."""
    store = StateStore()
    store.apply(ha_reading(ROOM, "20.5", instant=at(0)))
    assert store.is_fresh(ha_signal(ROOM), at(1800))
    assert not store.is_fresh(ha_signal(ROOM), at(1801))


def test_room_temperature_max_age_is_configurable() -> None:
    """A per-signal override changes the maximum age."""
    policy = StalenessPolicy().with_override(ha_signal(ROOM), 600.0)
    store = StateStore(policy)
    store.apply(ha_reading(ROOM, "20.5", instant=at(0)))
    assert store.max_age(ha_signal(ROOM)) == 600
    assert not store.is_fresh(ha_signal(ROOM), at(601))


def test_ha_age_counts_from_last_reported_not_receipt() -> None:
    """The age of a Home Assistant value counts from its last-reported time, not from receipt."""
    store = StateStore()
    received = at(0)
    reported = received.wall - timedelta(minutes=20)
    store.apply(ha_reading(ROOM, "20.5", instant=received, last_reported=reported))
    assert store.age(ha_signal(ROOM), at(0)) == pytest.approx(1200)
    assert not store.is_fresh(ha_signal(ROOM), at(601))


def test_ha_source_clock_ahead_counts_as_no_lag() -> None:
    """A last-reported time in the future counts as zero lag."""
    store = StateStore()
    received = at(0)
    store.apply(
        ha_reading(ROOM, "20.5", instant=received, last_reported=received.wall + timedelta(hours=1))
    )
    assert store.age(ha_signal(ROOM), at(0)) == 0


def test_ha_reconnect_replay_of_same_state_keeps_older_confirmation() -> None:
    """A replayed unchanged state after reconnect does not make the value look older."""
    store = StateStore()
    store.apply(ha_reading(ROOM, "20.5", instant=at(0)))
    reported = at(0).wall - timedelta(minutes=5)
    store.apply(ha_reading(ROOM, "20.5", instant=at(60), last_reported=reported))
    assert store.age(ha_signal(ROOM), at(60)) == 60


def test_liveness_follows_live_stats_within_fifteen_seconds() -> None:
    """HeishaMon counts as alive for the liveness window after each live heartbeat."""
    store = StateStore()
    assert not store.heishamon_alive(at(0))
    for t in range(0, 60, 5):
        store.apply(heartbeat(t))
        assert store.heishamon_alive(at(t + 4.9))
    assert store.heishamon_alive(at(55 + HEISHAMON_LIVENESS_S))
    assert not store.heishamon_alive(at(55 + HEISHAMON_LIVENESS_S + 0.1))


def test_retained_stats_do_not_prove_liveness() -> None:
    """A retained stats message does not make HeishaMon alive."""
    store = StateStore()
    assert store.apply(heartbeat(0, retained=True)) is False
    assert not store.heishamon_alive(at(1))


def test_lwt_is_informational_only() -> None:
    """The last-will message is reported but does not determine liveness."""
    store = StateStore()
    store.apply(LwtNotice(True, at(0), False))
    status = store.heishamon_status(at(1))
    assert status.lwt_online is True
    assert status.alive is False
    store.apply(heartbeat(2))
    store.apply(LwtNotice(False, at(3), True))
    status = store.heishamon_status(at(4))
    assert status.lwt_online is False
    assert status.alive is True
    assert status.version == "v4.2.3"


def test_heishamon_dies_values_age_out_and_liveness_drops_first() -> None:
    """When HeishaMon stops, liveness drops first and values stay fresh until their max age."""
    store = StateStore()
    store.apply(heartbeat(0))
    store.apply(hp(OUTLET, 30.0, 0))
    snapshot = store.snapshot(at(20))
    assert snapshot.heishamon.alive is False
    assert snapshot.fresh_value(OUTLET) == 30.0
    assert store.snapshot(at(331)).fresh_value(OUTLET) is None


def test_parse_errors_are_counted_and_invalidate_the_value() -> None:
    """A parse error counts, invalidates the value and ignored messages are tallied."""
    store = StateStore()
    store.apply(hp(OUTLET, 30.0, 0))
    bad = ParseError(OUTLET, ParseErrorKind.MALFORMED, "x", "not a decimal number", at(1))
    assert store.apply(bad) is True
    assert store.apply(bad) is False
    store.apply(Ignored("panasonic_heat_pump/log", "not_used"))
    snapshot = store.snapshot(at(2))
    assert snapshot.value(OUTLET) == 30.0
    assert snapshot.fresh_value(OUTLET) is None
    assert snapshot.errors[OUTLET] == bad
    assert snapshot.error_counts[OUTLET] == 2
    assert store.ignored == 1


def test_ha_unavailable_invalidates_the_value_immediately() -> None:
    """An unavailable Home Assistant state makes the value not fresh until a new value arrives."""
    store = StateStore()
    store.apply(ha_reading(ROOM, "20.5", instant=at(0)))
    assert store.is_fresh(ha_signal(ROOM), at(10))
    assert store.apply(ha_reading(ROOM, "unavailable", instant=at(10)))
    view = store.snapshot(at(11)).get(ha_signal(ROOM))
    assert view is not None
    assert (view.value, view.fresh, view.age) == (20.5, False, 11)
    assert view.reason == "unavailable: entity has no state"
    assert not store.is_fresh(ha_signal(ROOM), at(11))
    store.apply(ha_reading(ROOM, "20.5", instant=at(20)))
    view = store.snapshot(at(21)).get(ha_signal(ROOM))
    assert view is not None
    assert (view.fresh, view.age, view.reason) == (True, 1, None)


def test_heishamon_unknown_enum_invalidates_the_value() -> None:
    """An unknown enum value from HeishaMon invalidates the signal."""
    store = StateStore()
    store.apply(hp(HeishaSignal.DEFROSTING_STATE, 0, 0))
    unknown = ParseError(
        HeishaSignal.DEFROSTING_STATE,
        ParseErrorKind.UNKNOWN_ENUM,
        "-1",
        "firmware reports -1 (unknown)",
        at(5),
    )
    store.apply(unknown)
    view = store.snapshot(at(6)).get(HeishaSignal.DEFROSTING_STATE)
    assert view is not None
    assert view.fresh is False
    assert view.reason is not None
    assert view.reason.startswith("unknown_enum")


def test_retained_or_older_errors_do_not_invalidate() -> None:
    """Retained or older parse errors do not invalidate a newer value."""
    store = StateStore()
    store.apply(hp(OUTLET, 30.0, 10))
    replayed = ParseError(OUTLET, ParseErrorKind.MALFORMED, "x", "bad", at(11), retained=True)
    assert store.apply(replayed) is False
    older = ParseError(OUTLET, ParseErrorKind.MALFORMED, "x", "bad", at(5))
    assert store.apply(older) is False
    assert store.is_fresh(OUTLET, at(12))


def test_reading_older_than_the_invalidation_is_dropped() -> None:
    """A reading older than a recorded invalidation is dropped."""
    store = StateStore()
    store.apply(hp(OUTLET, 30.0, 0))
    store.apply(ParseError(OUTLET, ParseErrorKind.MALFORMED, "x", "bad", at(10)))
    assert store.apply(hp(OUTLET, 30.0, 5)) is False
    assert not store.is_fresh(OUTLET, at(11))


def test_liveness_window_follows_a_slow_stats_cadence() -> None:
    """The liveness window adapts to a slower stats cadence."""
    store = StateStore()
    for t in range(0, 300, 30):
        store.apply(heartbeat(t))
    assert store.liveness_window() == 90
    assert store.heishamon_alive(at(270 + 89))
    assert not store.heishamon_alive(at(270 + 91))
    assert store.heishamon_status(at(271)).window_s == 90


def test_liveness_window_is_clamped_and_ignores_outages() -> None:
    """The liveness window is clamped to its floor and ceiling and ignores outage gaps."""
    fast = StateStore()
    for t in range(20):
        fast.apply(heartbeat(t))
    assert fast.liveness_window() == 15
    slow = StateStore()
    for t in range(0, 3000, 600):
        slow.apply(heartbeat(t))
    assert slow.liveness_window() == HEISHAMON_LIVENESS_S
    very_slow = StateStore(StalenessPolicy(liveness_ceiling_s=1000))
    for t in range(0, 4000, 900):
        very_slow.apply(heartbeat(t))
    assert very_slow.liveness_window() == 1000


def test_snapshot_exposes_value_age_freshness_and_source() -> None:
    """A snapshot exposes each signal's value, age, freshness and source."""
    store = StateStore()
    store.apply(hp(OUTLET, 30.0, 0))
    store.apply(ha_reading(ROOM, "20.5", instant=at(0), unit="°C"))
    snapshot = store.snapshot(at(400))
    outlet = snapshot.get(OUTLET)
    room = snapshot.get(ha_signal(ROOM))
    assert outlet is not None
    assert room is not None
    assert (outlet.value, outlet.age, outlet.fresh, outlet.source) == (
        30.0,
        400,
        False,
        SourceKind.HEISHAMON,
    )
    assert (room.value, room.age, room.fresh, room.source) == (20.5, 400, True, SourceKind.HA)
    assert OUTLET in snapshot
    assert {view.signal for view in snapshot} == {OUTLET, ha_signal(ROOM)}
    assert snapshot.now == at(400)


def test_snapshot_is_isolated_from_later_updates() -> None:
    """A snapshot is immutable and unaffected by later store updates."""
    store = StateStore()
    store.apply(hp(OUTLET, 30.0, 0))
    snapshot = store.snapshot(at(1))
    store.apply(hp(OUTLET, 31.0, 2))
    assert snapshot.value(OUTLET) == 30.0
    assert not hasattr(snapshot.signals, "__setitem__")


def test_copy_is_independent() -> None:
    """A copied store can be updated without changing the original."""
    store = StateStore()
    store.apply(hp(OUTLET, 30.0, 0))
    fork = store.copy()
    fork.apply(hp(OUTLET, 35.0, 1))
    original = store.latest(OUTLET)
    assert original is not None
    assert original.value == 30.0


def test_wall_clock_does_not_affect_age() -> None:
    """A jump of the wall clock does not change a signal's age."""
    store = StateStore()
    store.apply(hp(OUTLET, 30.0, 0))
    jumped = Instant(T0 + 10, datetime(2030, 1, 1, tzinfo=UTC))
    assert store.age(OUTLET, jumped) == 10

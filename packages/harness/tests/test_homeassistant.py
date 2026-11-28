from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np

from ovenbird.runtime import Runtime
from ovenbird_core import SourceKind, StateStore
from ovenbird_harness.clock import ManualClock
from ovenbird_harness.homeassistant import (
    UNAVAILABLE,
    DeviceFeed,
    FakeHomeAssistant,
    ReportTrack,
    SensorReport,
    dropouts,
    room_feed,
)
from ovenbird_harness.settings import HUMIDITY_ENTITY, ROOM_ENTITY, harness_settings
from ovenbird_sim.evaluate.sensors import example_room_sensor

T0 = 1_794_200_000.0
ROOM = "ha/" + ROOM_ENTITY
HUMIDITY = "ha/" + HUMIDITY_ENTITY


def rig(tmp_path: Path) -> tuple[FakeHomeAssistant, Runtime, ManualClock]:
    """Build a fake Home Assistant on a real runtime and a manual clock at ``T0``."""
    settings = harness_settings(tmp_path)
    clock = ManualClock(T0)
    runtime = Runtime(StateStore(settings.staleness_policy()), clock=clock, ha_enabled=True)
    feed = room_feed(T0, T0 + 86400.0, ROOM_ENTITY, HUMIDITY_ENTITY)[0]
    return FakeHomeAssistant(settings, runtime, feed.units), runtime, clock


def test_states_reach_the_store_through_the_real_ha_input(tmp_path: Path) -> None:
    """Reports reach the store through the real HA input once connected, fresh and counted."""
    ha, runtime, clock = rig(tmp_path)
    ha.tick(T0, [SensorReport(ROOM_ENTITY, "21.7"), SensorReport(HUMIDITY_ENTITY, "55.0")])
    ha.connect(T0)
    assert runtime.ha_connected
    assert runtime.store.link_up(SourceKind.HA, clock())
    view = runtime.store.view(ROOM, clock())
    assert view is not None
    assert view.value == 21.7
    assert view.fresh
    assert ha.refreshes == 1


def test_an_unchanged_report_is_seen_only_by_the_re_read(tmp_path: Path) -> None:
    """An unchanged report emits no event; only the periodic re-read refreshes its age."""
    ha, runtime, clock = rig(tmp_path)
    ha.tick(T0, [SensorReport(HUMIDITY_ENTITY, "55.0")])
    ha.connect(T0)
    events = ha.events
    later = clock.set(T0 + 120.0)
    ha.tick(later.wall.timestamp(), [SensorReport(HUMIDITY_ENTITY, "55.0")])
    assert ha.events == events
    view = runtime.store.view(HUMIDITY, later)
    assert view is not None
    assert view.age == 120.0
    reread = clock.set(T0 + 300.0)
    ha.tick(reread.wall.timestamp())
    view = runtime.store.view(HUMIDITY, reread)
    assert view is not None
    assert view.age == 180.0


def test_unavailable_invalidates_and_disconnect_drops_the_link(tmp_path: Path) -> None:
    """An unavailable state invalidates the value; a disconnect drops the HA link."""
    ha, runtime, clock = rig(tmp_path)
    ha.tick(T0, [SensorReport(ROOM_ENTITY, "21.7")])
    ha.connect(T0)
    now = clock.set(T0 + 10.0)
    ha.tick(T0 + 10.0, [SensorReport(ROOM_ENTITY, UNAVAILABLE)])
    view = runtime.store.view(ROOM, now)
    assert view is not None
    assert not view.fresh
    ha.disconnect()
    assert not runtime.ha_connected
    assert not runtime.store.link_up(SourceKind.HA, now)


def test_the_example_device_reports_on_change_only() -> None:
    """The example device reports the room only on change, in 0.1 steps."""
    feed = DeviceFeed(example_room_sensor(), ROOM_ENTITY, HUMIDITY_ENTITY)
    room = [
        r
        for k in range(24 * 60)
        for r in feed.reports(T0 + 60.0 * k, 21.5 + 0.3 * np.sin(k / 200.0))
        if r.entity_id == ROOM_ENTITY
    ]
    values = [float(r.state) for r in room]
    assert 2 <= len(values) < 60
    assert all(abs(a - b) > 0.05 for a, b in itertools.pairwise(values))
    assert all(round(v / 0.1, 6) == round(v / 0.1) for v in values)


def test_mute_and_stick() -> None:
    """A muted or stuck device stops reporting, or reports the stuck value once."""
    feed = DeviceFeed(example_room_sensor(), ROOM_ENTITY, HUMIDITY_ENTITY)
    assert feed.reports(T0, 21.0)
    feed.stick(23.3, T0 + 60.0, T0 + 3600.0)
    assert feed.reports(T0 + 60.0, 21.0)[0] == SensorReport(ROOM_ENTITY, "23.3")
    assert all(not feed.reports(T0 + 60.0 * k, 18.0) for k in range(2, 60))


def test_recorded_dropouts() -> None:
    """Dropouts of a recorded report track are found and coverage respects the tolerance."""
    track = ReportTrack(np.array([0.0, 10.0, 20.0, 30.0]), np.array([21.5, np.nan, 21.7, np.nan]))
    assert dropouts(track) == ((10.0, 20.0), (30.0, float("inf")))
    assert track.covers(5.0, 25.0, tolerance_s=5.0)
    assert not track.covers(-10.0, 25.0, tolerance_s=5.0)

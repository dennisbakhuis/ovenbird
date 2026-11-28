"""Replay a two-hour capture slice through the core.

Each slice (the committed synthetic one and, where present locally, a slice of the
live recording) holds a compressor start, a defrost and a compressor stop.
"""

from __future__ import annotations

import gzip
import json
import statistics
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from ovenbird_core.capture import CaptureRecord, parse_capture_line, replay_results
from ovenbird_core.catalogue import CATALOGUE, HeishaSignal
from ovenbird_core.derived import compressor_running, defrost_active, heat_delivered_w
from ovenbird_core.heishamon import Heartbeat
from ovenbird_core.inputs import InputRouter, MqttSignal
from ovenbird_core.instant import Instant
from ovenbird_core.readings import Ignored, ParseError, ParseErrorKind, Reading
from ovenbird_core.store import StateStore

ROOM_TOPIC = "climate_manager_capture/room_temp"
ROUTER = InputRouter(mqtt_signals={ROOM_TOPIC: MqttSignal("room_temperature", "°C", -10, 45)})
NOT_ON_THIS_MODEL = frozenset({HeishaSignal.HEATING_CONTROL, HeishaSignal.QUIET_MODE_PRIORITY})


def records(path: Path) -> Iterator[CaptureRecord]:
    """Yield the capture records of a gzipped capture file, skipping headers and garbage."""
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            record = parse_capture_line(line)
            if record is not None:
                yield record


def reported_version(path: Path) -> str:
    """Return the HeishaMon firmware version from the last stats message of a capture."""
    stats = [r for r in records(path) if r.topic.endswith("/stats")]
    version = json.loads(stats[-1].payload)["version"]
    assert isinstance(version, str)
    return version


@dataclass
class ReplaySummary:
    """Counts and samples collected while replaying a capture at 60 s ticks."""

    readings: Counter[str]
    errors: list[ParseError]
    ignored: Counter[str]
    heartbeats: int
    alive_ticks: int
    total_ticks: int
    running_ticks: int
    defrost_ticks: int
    compressor_starts: int
    compressor_stops: int
    heat_ratios: list[float]
    heat_values: list[float]
    first_live_tick: Instant | None
    final_store: StateStore


@pytest.fixture(scope="module")
def summary(capture_slice: Path) -> ReplaySummary:
    """Replay the capture slice through router and store, sampling derived values every minute."""
    store = StateStore()
    readings: Counter[str] = Counter()
    ignored: Counter[str] = Counter()
    errors: list[ParseError] = []
    heartbeats = 0
    alive_ticks = total_ticks = running_ticks = defrost_ticks = 0
    starts = stops = 0
    previous_running: bool | None = None
    heat_ratios: list[float] = []
    heat_values: list[float] = []
    next_tick: float | None = None
    first_live: Instant | None = None
    last_instant: Instant | None = None
    for record, result in zip(
        records(capture_slice), replay_results(records(capture_slice), ROUTER), strict=True
    ):
        instant = Instant.from_capture(record.t)
        while next_tick is not None and next_tick < instant.monotonic:
            tick = Instant.from_unix(next_tick)
            snapshot = store.snapshot(tick)
            total_ticks += 1
            alive_ticks += snapshot.heishamon.alive
            running = compressor_running(snapshot)
            defrost = defrost_active(snapshot)
            heat = heat_delivered_w(snapshot)
            if running.value is not None:
                if previous_running is False and running.value:
                    starts += 1
                if previous_running is True and not running.value:
                    stops += 1
                previous_running = running.value
                running_ticks += running.value
            defrost_ticks += bool(defrost.value)
            produced = snapshot.fresh_value(HeishaSignal.HEAT_POWER_PRODUCTION)
            if running.value and defrost.value is False and heat.value is not None:
                heat_values.append(heat.value)
                if isinstance(produced, int) and produced >= 2000:
                    heat_ratios.append(heat.value / produced)
            next_tick += 60.0
        match result:
            case Reading():
                readings[result.signal] += 1
            case ParseError():
                errors.append(result)
            case Ignored():
                ignored[result.reason] += 1
            case Heartbeat() if not result.retained:
                heartbeats += 1
                if next_tick is None:
                    first_live = instant
                    next_tick = instant.monotonic + 1.0
            case _:
                pass
        store.apply(result)
        last_instant = instant
    assert last_instant is not None
    return ReplaySummary(
        readings,
        errors,
        ignored,
        heartbeats,
        alive_ticks,
        total_ticks,
        running_ticks,
        defrost_ticks,
        starts,
        stops,
        heat_ratios,
        heat_values,
        first_live,
        store,
    )


def test_fixture_is_small(capture_slice: Path) -> None:
    """The committed capture slice stays below one megabyte."""
    assert capture_slice.stat().st_size < 1_000_000


def test_no_parse_errors_on_catalogued_topics(summary: ReplaySummary) -> None:
    """Only signals this model lacks give parse errors; every other catalogued signal is read."""
    unexpected = [
        error
        for error in summary.errors
        if not (
            error.signal in NOT_ON_THIS_MODEL
            and error.kind is ParseErrorKind.UNKNOWN_ENUM
            and error.payload == "-1"
        )
    ]
    assert unexpected == []
    assert {error.signal for error in summary.errors} <= NOT_ON_THIS_MODEL
    assert set(summary.readings) >= set(CATALOGUE) - NOT_ON_THIS_MODEL
    assert summary.readings["room_temperature"] >= 1


def test_uncatalogued_topics_are_ignored_not_errors(summary: ReplaySummary) -> None:
    """Uncatalogued topics and command echoes are ignored rather than reported as errors."""
    assert summary.ignored["uncatalogued"] > 0
    assert summary.ignored["command"] > 0


def test_heishamon_alive_throughout(summary: ReplaySummary) -> None:
    """Heartbeats arrive at the expected rate and HeishaMon counts as alive on every tick."""
    assert summary.heartbeats >= 2 * 3600 / 5 * 0.95
    assert summary.total_ticks >= 115
    assert summary.alive_ticks == summary.total_ticks


def test_compressor_runs_and_defrost_are_detected(summary: ReplaySummary) -> None:
    """The slice shows compressor starts, stops, running time and defrost ticks."""
    assert summary.compressor_starts >= 1
    assert summary.compressor_stops >= 1
    assert summary.running_ticks >= 60
    assert summary.defrost_ticks >= 3


def test_heat_delivered_is_plausible(summary: ReplaySummary) -> None:
    """Delivered heat is within physical bounds and close to the pump's own production figure."""
    assert len(summary.heat_values) >= 30
    assert all(-2000 < value < 20000 for value in summary.heat_values)
    assert 2000 < statistics.median(summary.heat_values) < 15000
    assert len(summary.heat_ratios) >= 30
    assert 0.7 < statistics.median(summary.heat_ratios) < 1.3


def test_final_snapshot_is_fresh_and_consistent(
    summary: ReplaySummary, capture_slice: Path
) -> None:
    """The final snapshot is alive, has the reported version and no stale signals."""
    last = max(record.t for record in records(capture_slice))
    snapshot = summary.final_store.snapshot(Instant.from_capture(last))
    assert snapshot.heishamon.alive
    assert snapshot.heishamon.version == reported_version(capture_slice)
    stale = [view.signal for view in snapshot if view.signal in CATALOGUE and not view.fresh]
    assert stale == []
    assert snapshot.fresh_value(HeishaSignal.HEATING_MODE) == 1
    assert snapshot.fresh_value(HeishaSignal.OPERATING_MODE_STATE) == 0

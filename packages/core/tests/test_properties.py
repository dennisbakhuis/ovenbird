from __future__ import annotations

from datetime import timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ovenbird_core.capture import capture_input, parse_capture_line
from ovenbird_core.catalogue import CATALOGUE, ValueKind
from ovenbird_core.heishamon import (
    DEFAULT_BASE,
    Heartbeat,
    HeishaMonParser,
    LwtNotice,
)
from ovenbird_core.inputs import ha_reading, parse_ha_payload
from ovenbird_core.instant import Instant
from ovenbird_core.readings import Ignored, ParseError, Reading, SourceKind
from ovenbird_core.store import StateStore

T0 = 1_794_528_000.0
PARSER = HeishaMonParser()
RESULT_TYPES = (Reading, Heartbeat, LwtNotice, ParseError, Ignored)
SUFFIXES = st.sampled_from([*CATALOGUE, "stats", "LWT", "main/Unknown", "commands/SetCurves"])
NUMERIC_TEXT = st.one_of(
    st.integers(-500, 70000).map(str),
    st.floats(allow_nan=True, allow_infinity=True).map(str),
    st.from_regex(r"\A[ +\-0-9.eE_]{0,12}\Z"),
)
PAYLOADS = st.one_of(st.text(max_size=300), st.binary(max_size=300), NUMERIC_TEXT)
TIMES = st.floats(0, 1e6, allow_nan=False)
SIGNAL = "main/Main_Outlet_Temp"


def at(seconds: float) -> Instant:
    """Return the instant ``seconds`` after the test origin."""
    return Instant.from_unix(T0 + seconds)


@given(suffix=SUFFIXES, payload=PAYLOADS, retained=st.booleans(), t=TIMES)
def test_parser_never_raises(suffix: str, payload: str | bytes, retained: bool, t: float) -> None:
    """The parser never raises on arbitrary payloads and every Reading respects the catalogue."""
    result = PARSER.parse(f"{DEFAULT_BASE}/{suffix}", payload, retained=retained, instant=at(t))
    assert isinstance(result, RESULT_TYPES)
    if isinstance(result, Reading):
        assert result.retained is retained
        assert result.signal == suffix
        spec = CATALOGUE[suffix]
        if spec.kind is ValueKind.ENUM:
            assert isinstance(result.value, int)
            assert spec.meaning(result.value) is not None
        elif isinstance(result.value, int | float):
            if spec.minimum is not None:
                assert result.value >= spec.minimum
            if spec.maximum is not None:
                assert result.value <= spec.maximum


@given(topic=st.text(max_size=80), payload=PAYLOADS)
def test_parser_never_raises_on_any_topic(topic: str, payload: str | bytes) -> None:
    """The parser returns a result for any topic and payload."""
    assert isinstance(PARSER.parse(topic, payload, retained=False, instant=at(0)), RESULT_TYPES)


@given(payload=st.text(max_size=400), state=st.text(max_size=40))
def test_ha_parsing_never_raises(payload: str, state: str) -> None:
    """Home Assistant payload and state parsing never raise."""
    assert isinstance(parse_ha_payload("sensor.x", payload, instant=at(0)), Reading | ParseError)
    assert isinstance(ha_reading("sensor.x", state, instant=at(0)), Reading | ParseError)


@given(line=st.text(max_size=300))
def test_capture_line_parsing_never_raises(line: str) -> None:
    """Capture-line parsing never raises and a parsed record can be turned into an input."""
    record = parse_capture_line(line)
    if record is not None:
        capture_input(record)


EVENTS = st.lists(
    st.tuples(st.floats(0, 600, allow_nan=False), st.sampled_from([30.0, 31.0]), st.booleans()),
    max_size=40,
)


@given(events=EVENTS, probe=st.floats(0, 1000, allow_nan=False))
def test_retained_never_refreshes_freshness(
    events: list[tuple[float, float, bool]], probe: float
) -> None:
    """A retained message never makes a signal fresher or younger."""
    store = StateStore()
    t = 0.0
    for dt, value, retained in events:
        t += dt
        now = at(t + probe)
        age_before = store.age(SIGNAL, now)
        fresh_before = store.is_fresh(SIGNAL, now)
        store.apply(Reading(SIGNAL, value, "°C", at(t), SourceKind.HEISHAMON, retained))
        if retained:
            age_after = store.age(SIGNAL, now)
            if age_before is None:
                assert age_after is None
            else:
                assert age_after is None or age_after >= age_before
            assert fresh_before or not store.is_fresh(SIGNAL, now)


@given(events=EVENTS, t1=TIMES, t2=TIMES)
def test_age_is_monotonic_in_time(
    events: list[tuple[float, float, bool]], t1: float, t2: float
) -> None:
    """The age of a signal never decreases as the probe time moves later."""
    store = StateStore()
    t = 0.0
    for dt, value, retained in events:
        t += dt
        store.apply(Reading(SIGNAL, value, "°C", at(t), SourceKind.HEISHAMON, retained))
    early, late = sorted((t1, t2))
    age_early = store.age(SIGNAL, at(early))
    age_late = store.age(SIGNAL, at(late))
    assert (age_early is None) == (age_late is None)
    if age_early is not None and age_late is not None:
        assert 0 <= age_early <= age_late


@given(
    lags=st.lists(st.floats(-3600, 3600, allow_nan=False), min_size=1, max_size=20),
    step=st.floats(0, 120, allow_nan=False),
)
def test_ha_age_never_below_reported_lag(lags: list[float], step: float) -> None:
    """The age of a Home Assistant reading is never negative, whatever lag it reports."""
    store = StateStore()
    t = 0.0
    for lag in lags:
        t += step
        received = at(t)
        reported = received.wall - timedelta(seconds=lag)
        store.apply(ha_reading("sensor.x", "20", instant=received, last_reported=reported))
        age = store.age("ha/sensor.x", received)
        assert age is not None
        assert age >= 0


@given(beats=st.lists(st.tuples(st.floats(0, 30, allow_nan=False), st.booleans()), max_size=30))
def test_only_live_stats_make_heishamon_alive(beats: list[tuple[float, bool]]) -> None:
    """Only live, non-retained stats heartbeats make HeishaMon alive, within the liveness window."""
    store = StateStore()
    t = 0.0
    last_live: float | None = None
    for dt, retained in beats:
        t += dt
        store.apply(Heartbeat(at(t), retained))
        if not retained:
            last_live = t
        alive = store.heishamon_alive(at(t))
        window = store.liveness_window()
        age = store.heartbeat_age(at(t))
        assert 15.0 <= window <= 120.0
        assert (age is None) == (last_live is None)
        if age is not None and last_live is not None:
            assert age == pytest.approx(t - last_live, abs=1e-6)
        assert alive == (age is not None and age <= window)

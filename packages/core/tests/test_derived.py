from __future__ import annotations

import pytest

from ovenbird_core.catalogue import HeishaSignal
from ovenbird_core.derived import (
    compressor_running,
    defrost_active,
    dhw_active,
    heat_delivered_w,
    heat_power_w,
)
from ovenbird_core.instant import Instant
from ovenbird_core.readings import ParseError, ParseErrorKind, Reading, SourceKind, Value
from ovenbird_core.store import Snapshot, StateStore

T0 = 1_794_528_000.0


def at(seconds: float) -> Instant:
    """Return the instant ``seconds`` after the test epoch."""
    return Instant.from_unix(T0 + seconds)


def snapshot_of(values: dict[str, Value], *, now: float = 1.0, retained: bool = False) -> Snapshot:
    """Build a snapshot at ``now`` seconds from heat pump readings taken at time zero."""
    store = StateStore()
    for signal, value in values.items():
        store.apply(Reading(signal, value, None, at(0), SourceKind.HEISHAMON, retained))
    return store.snapshot(at(now))


@pytest.mark.parametrize(("frequency", "running"), [(0, False), (1, True), (48, True)])
def test_compressor_running(frequency: int, running: bool) -> None:
    """The compressor counts as running at any positive frequency."""
    result = compressor_running(snapshot_of({HeishaSignal.COMPRESSOR_FREQ: frequency}))
    assert result.value is running
    assert result.ok
    assert result.inputs == (HeishaSignal.COMPRESSOR_FREQ,)
    assert result.age == 1
    assert result.reason == ""


def test_compressor_running_threshold_is_configurable() -> None:
    """The minimum running frequency can be raised."""
    snapshot = snapshot_of({HeishaSignal.COMPRESSOR_FREQ: 15})
    assert compressor_running(snapshot, min_frequency_hz=20).value is False


def test_missing_input_gives_no_value() -> None:
    """A missing input gives no value and names the missing signal."""
    result = compressor_running(snapshot_of({}))
    assert result.value is None
    assert not result.ok
    assert result.missing == (HeishaSignal.COMPRESSOR_FREQ,)
    assert "missing" in result.reason
    assert result.age is None


def test_stale_input_gives_no_value_unless_allowed() -> None:
    """A stale input gives no value unless allowed, and is reported as stale either way."""
    snapshot = snapshot_of({HeishaSignal.COMPRESSOR_FREQ: 30}, now=400)
    strict = compressor_running(snapshot)
    assert strict.value is None
    assert strict.stale == (HeishaSignal.COMPRESSOR_FREQ,)
    assert "stale" in strict.reason
    lenient = compressor_running(snapshot, allow_stale=True)
    assert lenient.value is True
    assert lenient.stale == (HeishaSignal.COMPRESSOR_FREQ,)
    assert lenient.age == 400


def test_retained_only_input_is_stale_with_unknown_age() -> None:
    """A value known only from a retained message is stale with unknown age."""
    result = defrost_active(snapshot_of({HeishaSignal.DEFROSTING_STATE: 1}, retained=True))
    assert result.value is None
    assert result.stale == (HeishaSignal.DEFROSTING_STATE,)
    assert result.age is None


def test_non_numeric_value_counts_as_missing() -> None:
    """A non-numeric value is treated as missing."""
    result = compressor_running(snapshot_of({HeishaSignal.COMPRESSOR_FREQ: "fast"}))
    assert result.value is None
    assert result.missing == (HeishaSignal.COMPRESSOR_FREQ,)


@pytest.mark.parametrize(("state", "active"), [(0, False), (1, True)])
def test_defrost_and_dhw(state: int, active: bool) -> None:
    """Defrost and DHW activity follow their state signals."""
    snapshot = snapshot_of(
        {HeishaSignal.DEFROSTING_STATE: state, HeishaSignal.THREEWAY_VALVE_STATE: state}
    )
    assert defrost_active(snapshot).value is active
    assert dhw_active(snapshot).value is active


def test_heat_power_formula() -> None:
    """Heat power is flow times temperature difference times heat capacity, minus an offset."""
    assert heat_power_w(60.0, 30.0, 35.0, density_kg_per_l=1.0, cp_j_per_kg_k=4000.0) == 20000.0
    assert heat_power_w(25.55, 28.0, 34.5) == pytest.approx(11_520, rel=0.01)
    assert heat_power_w(20.0, 30.0, 30.5, offset_k=0.5) == 0.0
    assert heat_power_w(20.0, 30.0, 28.0) < 0


HEATING: dict[str, Value] = {
    HeishaSignal.COMPRESSOR_FREQ: 40,
    HeishaSignal.THREEWAY_VALVE_STATE: 0,
}
LOOP: dict[str, Value] = {
    HeishaSignal.PUMP_FLOW: 25.55,
    HeishaSignal.INLET_TEMP: 28.0,
    HeishaSignal.OUTLET_TEMP: 34.5,
}


def test_heat_delivered_from_snapshot() -> None:
    """Delivered heat is computed from snapshot flow and loop temperatures and lists all inputs."""
    result = heat_delivered_w(snapshot_of({**HEATING, **LOOP}))
    assert result.value == pytest.approx(heat_power_w(25.55, 28.0, 34.5))
    assert set(result.inputs) == {
        HeishaSignal.COMPRESSOR_FREQ,
        HeishaSignal.THREEWAY_VALVE_STATE,
        HeishaSignal.PUMP_FLOW,
        HeishaSignal.INLET_TEMP,
        HeishaSignal.OUTLET_TEMP,
    }
    assert result.reason == ""


def test_heat_delivered_without_inlet_is_unknown() -> None:
    """Without the inlet temperature delivered heat is unknown."""
    values: dict[str, Value] = {
        **HEATING,
        HeishaSignal.PUMP_FLOW: 25.0,
        HeishaSignal.OUTLET_TEMP: 34.0,
    }
    result = heat_delivered_w(snapshot_of(values))
    assert result.value is None
    assert result.missing == (HeishaSignal.INLET_TEMP,)
    assert result.age is None


def test_heat_delivered_with_zero_flow_is_zero() -> None:
    """Zero flow gives zero delivered heat."""
    values: dict[str, Value] = {**HEATING, **LOOP, HeishaSignal.PUMP_FLOW: 0.0}
    assert heat_delivered_w(snapshot_of(values)).value == 0.0


def test_heat_delivered_is_zero_while_the_compressor_is_stopped() -> None:
    """With the compressor stopped delivered heat is zero regardless of loop readings."""
    values: dict[str, Value] = {**LOOP, HeishaSignal.COMPRESSOR_FREQ: 0}
    result = heat_delivered_w(snapshot_of(values))
    assert result.value == 0.0
    assert result.inputs == (HeishaSignal.COMPRESSOR_FREQ,)


def test_heat_delivered_has_no_value_during_dhw() -> None:
    """During DHW the delivered heating power is not defined."""
    values: dict[str, Value] = {
        **LOOP,
        HeishaSignal.COMPRESSOR_FREQ: 40,
        HeishaSignal.THREEWAY_VALVE_STATE: 1,
    }
    result = heat_delivered_w(snapshot_of(values))
    assert result.value is None
    assert result.missing == ()
    assert result.reason.startswith("dhw active")


def test_heat_delivered_is_negative_during_defrost() -> None:
    """Heat extracted from the loop during defrost shows as negative delivered heat."""
    values: dict[str, Value] = {
        **HEATING,
        **LOOP,
        HeishaSignal.DEFROSTING_STATE: 1,
        HeishaSignal.OUTLET_TEMP: 20.0,
    }
    result = heat_delivered_w(snapshot_of(values))
    assert result.value is not None
    assert result.value < 0


def test_heat_delivered_needs_the_running_state() -> None:
    """Without compressor and valve state delivered heat cannot be determined."""
    result = heat_delivered_w(snapshot_of(dict(LOOP)))
    assert result.value is None
    assert HeishaSignal.COMPRESSOR_FREQ in result.missing
    assert HeishaSignal.THREEWAY_VALVE_STATE in result.missing


def test_invalidated_input_counts_as_missing_even_when_stale_is_allowed() -> None:
    """A parse error invalidating an input makes it missing even if stale values are allowed."""
    store = StateStore()
    store.apply(Reading(HeishaSignal.COMPRESSOR_FREQ, 40, "Hz", at(0), SourceKind.HEISHAMON))
    store.apply(
        ParseError(HeishaSignal.COMPRESSOR_FREQ, ParseErrorKind.OUT_OF_RANGE, "-1", "bad", at(1))
    )
    result = compressor_running(store.snapshot(at(2)), allow_stale=True)
    assert result.value is None
    assert result.missing == (HeishaSignal.COMPRESSOR_FREQ,)

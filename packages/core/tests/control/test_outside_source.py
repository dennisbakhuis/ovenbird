from __future__ import annotations

import math
from dataclasses import replace
from types import MappingProxyType

import pytest

from ovenbird_core.catalogue import HeishaSignal
from ovenbird_core.control import (
    DecisionRecord,
    OutsideSource,
    OvenbirdConfig,
    OvenbirdController,
    OvenbirdState,
    curve_outside,
)
from ovenbird_core.control.observe import control_inputs
from ovenbird_core.control.synthetic import ROOM_SIGNAL, PlantView, synthetic_snapshot
from ovenbird_core.instant import Instant
from ovenbird_core.readings import SignalId, SourceKind
from ovenbird_core.store import HA_MAX_AGE_S, SignalView, Snapshot

T0 = 1_794_528_000.0
GARDEN: SignalId = "ha/sensor.garden_temperature"
MIXED = OvenbirdConfig.preset("mixed")
CHOSEN = OvenbirdConfig.preset("mixed", outside=OutsideSource(GARDEN, max_age_s=1800.0))


def snapshot_with(
    pump: float,
    garden: float | None,
    age: float = 60.0,
    *,
    at: float = T0,
    reason: str | None = None,
) -> Snapshot:
    """Build a synthetic snapshot with the pump outside temperature and optionally a garden sensor.

    Parameters
    ----------
    pump
        Outside temperature of the pump's own sensor, in °C.
    garden
        Value of the chosen garden sensor in °C, or None to leave it out.
    age
        Age of the garden reading in seconds.
    at
        Unix time of the snapshot.
    reason
        Reason marking the garden value as unusable, if any.

    Returns
    -------
    Snapshot
        The snapshot including the garden signal view.
    """
    now = Instant.from_unix(at)
    snapshot = synthetic_snapshot(now, PlantView(outside=pump, room=20.5))
    if garden is None:
        return snapshot
    view = SignalView(
        signal=GARDEN,
        value=garden,
        unit="°C",
        source=SourceKind.HA,
        observed=now.shifted(-age),
        age=age,
        max_age=HA_MAX_AGE_S,
        fresh=age <= HA_MAX_AGE_S and reason is None,
        retained=False,
        source_timestamp=None,
        reason=reason,
    )
    return replace(snapshot, signals=MappingProxyType({**snapshot.signals, GARDEN: view}))


def decide(config: OvenbirdConfig, snapshot: Snapshot) -> DecisionRecord:
    """Return the first decision of a fresh controller for the given snapshot."""
    controller = OvenbirdController(config)
    inputs = control_inputs(snapshot, room_signal=ROOM_SIGNAL)
    return controller.step(controller.initial_state(), inputs).decision


def test_without_a_chosen_sensor_the_pump_sensor_drives_the_curve() -> None:
    """Without a chosen sensor the pump's outside sensor is used."""
    result = curve_outside(None, snapshot_with(5.0, 0.0), 5.0)
    assert result.value == 5.0
    assert result.source == HeishaSignal.OUTSIDE_TEMP
    assert result.note is None


def test_a_fresh_chosen_sensor_drives_the_curve() -> None:
    """A fresh chosen sensor replaces the pump's outside sensor."""
    result = curve_outside(CHOSEN.outside, snapshot_with(5.0, 0.0), 5.0)
    assert result.value == 0.0
    assert result.source == GARDEN
    assert not result.fallback


@pytest.mark.parametrize(
    ("garden", "age", "reason"), [(None, 0.0, "missing"), (0.0, 2400.0, "stale")]
)
def test_a_missing_or_old_chosen_sensor_falls_back_to_the_pump(
    garden: float | None, age: float, reason: str
) -> None:
    """A missing or stale chosen sensor falls back to the pump sensor with a note."""
    result = curve_outside(CHOSEN.outside, snapshot_with(5.0, garden, age), 5.0)
    assert result.value == 5.0
    assert result.fallback
    assert result.reason == reason
    assert result.note is not None
    assert result.note.startswith("from the pump")


def test_a_refused_value_is_named_as_unusable_not_stale() -> None:
    """A value refused at ingestion falls back as missing, naming the refusal reason."""
    snapshot = snapshot_with(5.0, 0.0, reason="unit: no temperature unit")
    result = curve_outside(CHOSEN.outside, snapshot, 5.0)
    assert result.value == 5.0
    assert result.reason == "missing"
    assert result.note == f"from the pump: {GARDEN} has no usable value, unit: no temperature unit"


@pytest.mark.parametrize("garden", [-40.5, 50.5, math.nan, math.inf])
def test_an_implausible_chosen_value_falls_back_to_the_pump(garden: float) -> None:
    """A chosen value outside the plausible range or non-finite falls back as implausible."""
    result = curve_outside(CHOSEN.outside, snapshot_with(5.0, garden), 5.0)
    assert result.value == 5.0
    assert result.source == HeishaSignal.OUTSIDE_TEMP
    assert result.fallback
    assert result.reason == "implausible"
    assert result.note is not None
    assert result.note.startswith(f"from the pump: {GARDEN} is implausible")
    assert "stale" not in result.note


@pytest.mark.parametrize("garden", [-40.0, 50.0])
def test_the_plausible_range_includes_its_ends(garden: float) -> None:
    """The plausible range limits themselves are accepted."""
    result = curve_outside(CHOSEN.outside, snapshot_with(garden, garden), garden)
    assert result.value == garden
    assert not result.fallback


def test_a_chosen_value_too_far_from_the_pump_falls_back() -> None:
    """A chosen value deviating too far from the pump sensor falls back with an explanatory note."""
    result = curve_outside(CHOSEN.outside, snapshot_with(5.0, 15.5), 5.0)
    assert result.value == 5.0
    assert result.fallback
    assert result.reason == "deviates"
    assert result.note == (
        f"from the pump: {GARDEN} is too far from the pump, 15.5 °C against 5 °C, "
        "more than 10 K apart"
    )


def test_a_chosen_value_within_the_deviation_is_used() -> None:
    """A chosen value within the allowed deviation is used."""
    result = curve_outside(CHOSEN.outside, snapshot_with(5.0, 15.0), 5.0)
    assert result.value == 15.0
    assert not result.fallback
    assert result.reason is None


def test_without_a_pump_value_only_the_range_applies() -> None:
    """Without a pump value only the plausible range is checked."""
    result = curve_outside(CHOSEN.outside, snapshot_with(5.0, 30.0), None)
    assert result.value == 30.0
    assert not result.fallback


def test_the_limits_are_settings() -> None:
    """Plausible range and maximum deviation come from the source settings."""
    narrow = OutsideSource(GARDEN, plausible_min_c=-20.0, plausible_max_c=30.0, max_deviation_k=3.0)
    assert curve_outside(narrow, snapshot_with(5.0, -21.0), -21.0).reason == "implausible"
    assert curve_outside(narrow, snapshot_with(25.0, 31.0), 31.0).reason == "implausible"
    assert curve_outside(narrow, snapshot_with(5.0, 8.5), 5.0).reason == "deviates"
    assert curve_outside(narrow, snapshot_with(5.0, 8.0), 5.0).value == 8.0


def test_the_default_limits() -> None:
    """The default plausible range is -40 to 50 °C and the default deviation 10 K."""
    source = OutsideSource(GARDEN)
    assert (source.plausible_min_c, source.plausible_max_c) == (-40.0, 50.0)
    assert source.max_deviation_k == 10.0


@pytest.mark.parametrize(
    "overrides",
    [
        {"plausible_min_c": 5.0},
        {"plausible_max_c": 10.0},
        {"max_deviation_k": 0.5},
    ],
)
def test_the_limits_are_range_checked(overrides: dict[str, float]) -> None:
    """Inconsistent limit settings are rejected naming the offending field."""
    with pytest.raises(ValueError, match=next(iter(overrides))):
        OutsideSource(GARDEN, **overrides)


def test_the_curve_follows_the_chosen_sensor_and_says_so() -> None:
    """The curve term uses the chosen sensor, notes it, and records it as an input."""
    pump = decide(MIXED, snapshot_with(10.0, 0.0))
    chosen = decide(CHOSEN, snapshot_with(10.0, 0.0))
    curve = chosen.term("curve")
    assert curve is not None
    assert f"from {GARDEN}" in curve.note
    assert chosen.terms[0].value > pump.terms[0].value
    assert any(ref.signal == GARDEN for ref in chosen.inputs_used)
    assert not any(ref.signal == GARDEN for ref in pump.inputs_used)


def test_the_safety_envelope_keeps_the_pump_sensor() -> None:
    """The safety envelope is evaluated on the pump sensor, not the chosen sensor."""
    tolerant = OvenbirdConfig.preset("mixed", outside=OutsideSource(GARDEN, max_deviation_k=50.0))
    warm_garden = decide(tolerant, snapshot_with(-10.0, 15.0))
    curve = warm_garden.term("curve")
    floor = MIXED.safety.envelope.water(-10.0) - MIXED.safety.envelope_below_k
    assert curve is not None
    assert curve.value < floor
    assert warm_garden.setpoint is not None
    assert warm_garden.setpoint >= round(floor)


def test_a_stale_chosen_sensor_gives_the_pump_curve_and_a_note() -> None:
    """A stale chosen sensor yields the same setpoint as the pump sensor, with a note."""
    stale = decide(CHOSEN, snapshot_with(10.0, 0.0, age=4000.0))
    pump = decide(MIXED, snapshot_with(10.0, None))
    curve = stale.term("curve")
    assert curve is not None
    assert "from the pump" in curve.note
    assert stale.setpoint == pump.setpoint


def test_one_bad_sample_never_enters_the_outside_filter() -> None:
    """Implausible or deviating chosen samples are kept out of the outside filter."""
    controller = OvenbirdController(CHOSEN)

    def run(second: float | None) -> OvenbirdState:
        """Step twice, with the second garden sample as given, and return the final state."""
        state = controller.initial_state()
        for at, garden in ((T0, 2.0), (T0 + 60.0, second)):
            inputs = control_inputs(snapshot_with(3.0, garden, at=at), room_signal=ROOM_SIGNAL)
            state = controller.step(state, inputs).state
        return state

    spiked = run(80.0)
    far = run(14.0)
    missing = run(None)
    assert spiked.outside_filtered == missing.outside_filtered
    assert far.outside_filtered == missing.outside_filtered


@pytest.mark.parametrize(
    ("garden", "reason"), [(2.0, None), (80.0, "implausible"), (14.0, "deviates")]
)
def test_the_controller_state_carries_the_reason(garden: float, reason: str | None) -> None:
    """The decision's controller state records the outside fallback and its reason."""
    record = decide(CHOSEN, snapshot_with(3.0, garden))
    assert record.controller_state["outside_reason"] == reason
    assert record.controller_state["outside_fallback"] is (reason is not None)


def test_without_a_chosen_sensor_no_reason_key() -> None:
    """Without a chosen sensor the controller state has no outside reason key."""
    record = decide(MIXED, snapshot_with(3.0, 80.0))
    assert "outside_reason" not in record.controller_state


def test_the_age_limit_must_be_positive() -> None:
    """A non-positive maximum age is rejected."""
    with pytest.raises(ValueError, match="max_age_s"):
        OutsideSource(GARDEN, max_age_s=0.0)

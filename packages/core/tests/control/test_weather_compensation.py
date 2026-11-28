from __future__ import annotations

import pytest

from ovenbird_core.control import DecisionRecord, OvenbirdConfig, OvenbirdController
from ovenbird_core.control.synthetic import PlantView, synthetic_inputs
from ovenbird_core.instant import Instant

T0 = 1_794_528_000.0
MIXED = OvenbirdConfig.preset("mixed")
FIXED = OvenbirdConfig.preset("mixed", weather_compensation=False, fixed_water_c=30.0)


def first_decision(config: OvenbirdConfig, plant: PlantView, **kwargs: object) -> DecisionRecord:
    """Return the decision of a fresh controller's first step on synthetic inputs."""
    controller = OvenbirdController(config)
    inputs = synthetic_inputs(Instant.from_unix(T0), plant, **kwargs)  # type: ignore[arg-type]
    return controller.step(controller.initial_state(), inputs).decision


def test_weather_compensation_is_on_by_default() -> None:
    """By default the base water temperature comes from the heating curve."""
    assert MIXED.weather_compensation is True
    assert MIXED.base_water(5.0) == MIXED.curve.water(5.0)


def test_off_the_base_is_the_fixed_temperature_at_any_outside_temperature() -> None:
    """With compensation off the base is the fixed temperature and has no outside sensitivity."""
    assert FIXED.base_water(-3.0) == FIXED.base_water(12.0) == 30.0
    assert FIXED.base_sensitivity(0.0) == 0.0


@pytest.mark.parametrize("outside", [0.0, 5.0, 12.0])
def test_off_without_room_sensor_sends_the_fixed_temperature(outside: float) -> None:
    """With compensation off and no room sensor the setpoint is the fixed temperature."""
    decision = first_decision(FIXED, PlantView(outside=outside), room_signal=None)
    assert decision.setpoint == 30
    curve = decision.term("curve")
    assert curve is not None
    assert "fixed water temperature" in curve.note
    assert decision.controller_state["base"] == "fixed"
    assert "fixed 30.0 °C" in decision.note


def test_on_the_curve_still_applies() -> None:
    """With compensation on the setpoint follows the curve rather than a fixed value."""
    decision = first_decision(MIXED, PlantView(outside=12.0), room_signal=None)
    assert decision.setpoint != 30
    assert "base" not in decision.controller_state


def test_off_the_safety_envelope_still_lifts_the_setpoint_in_the_cold() -> None:
    """With compensation off the safety envelope still raises the setpoint in severe cold."""
    decision = first_decision(FIXED, PlantView(outside=-10.0), room_signal=None)
    envelope = MIXED.safety.envelope.water(-10.0) - MIXED.safety.envelope_below_k
    assert decision.setpoint == round(envelope)


def test_off_the_room_correction_still_works_around_the_fixed_temperature() -> None:
    """With compensation off room feedback still moves the setpoint around the fixed value."""
    cold_room = first_decision(FIXED, PlantView(outside=5.0, room=19.5))
    warm_room = first_decision(FIXED, PlantView(outside=5.0, room=22.5))
    assert cold_room.setpoint is not None
    assert warm_room.setpoint is not None
    assert cold_room.setpoint > 30 > warm_room.setpoint


def test_off_a_fixed_temperature_below_the_minimum_setpoint_is_rejected() -> None:
    """With compensation off a fixed temperature below the minimum setpoint is rejected."""
    with pytest.raises(ValueError, match="fixed water temperature"):
        OvenbirdConfig.preset("mixed", weather_compensation=False, fixed_water_c=15.0)


def test_on_the_fixed_temperature_is_not_checked() -> None:
    """With compensation on the fixed temperature is ignored and not validated."""
    config = OvenbirdConfig.preset("mixed", fixed_water_c=15.0)
    assert config.base_water(5.0) == MIXED.curve.water(5.0)

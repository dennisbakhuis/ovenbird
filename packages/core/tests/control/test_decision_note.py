"""Characterisation of the decision note text, term by term."""

from __future__ import annotations

from typing import Any

import pytest

from ovenbird_core.control import RoomInput
from ovenbird_core.control.notes import NoteInputs, decision_note
from ovenbird_core.control.synthetic import ROOM_SIGNAL

CURVE = "the curve's 31.0 °C at 5.0 °C outside"
FIXED = "the fixed 31.0 °C (weather-dependent control off)"
ROOM = RoomInput(20.5, 60.0, True, ROOM_SIGNAL)


def note(**fields: Any) -> str:
    """Return the decision note for a plain curve tick at 31 °C changed by ``fields``."""
    base: dict[str, Any] = {
        "curve_sp": 31.0,
        "outside_f": 5.0,
        "final": 31,
        "reference": 31,
        "binding": None,
        "pre_clamp": 31.0,
        "pre_round": 31.0,
    }
    return decision_note(NoteInputs(**(base | fields)))


class TestLead:
    """The first sentence: summer, stove, room feedback or the curve alone."""

    def test_curve_alone(self) -> None:
        """Without a room value the curve is alone."""
        assert note() == f"No usable room temperature, so {CURVE} alone; setpoint 31 °C."

    def test_fixed_curve(self) -> None:
        """Without weather compensation the fixed setpoint is named."""
        assert note(fixed=True) == f"No usable room temperature, so {FIXED} alone; setpoint 31 °C."

    def test_held_offset(self) -> None:
        """A held offset is named while it fades."""
        assert note(held_offset=0.44) == (
            f"No usable room temperature, so {CURVE} plus the held offset +0.4 K (fading); "
            "setpoint 31 °C."
        )

    def test_implausible(self) -> None:
        """An implausible room value leaves the curve alone."""
        assert note(implausible=True) == (
            f"Room value implausible (cross-check), so {CURVE} alone; setpoint 31 °C."
        )

    def test_implausible_with_held_offset(self) -> None:
        """An implausible room value keeps the held offset."""
        assert note(implausible=True, held_offset=0.5, fixed=True) == (
            f"Room value implausible (cross-check), so {FIXED} plus the held offset +0.5 K "
            "(fading); setpoint 31 °C."
        )

    def test_room_without_error_is_no_feedback(self) -> None:
        """A room value without an error does not lead."""
        assert note(room=ROOM, pi_k=1.0) == (
            f"No usable room temperature, so {CURVE} alone; setpoint 31 °C."
        )

    @pytest.mark.parametrize(
        ("error", "side"), [(0.5, "0.5 K below"), (-0.26, "0.3 K above"), (0.0, "0.0 K above")]
    )
    def test_room_feedback(self, error: float, side: str) -> None:
        """The room feedback names the error and the PI's share."""
        assert note(room=ROOM, error=error, pi_k=-0.04) == (
            f"Room {side} target; PI adds +0.0 K to {CURVE}; setpoint 31 °C."
        )

    def test_room_feedback_with_status(self) -> None:
        """An on-change status follows the feedback sentence."""
        assert note(room=ROOM, error=0.5, pi_k=1.25, status="held value", fixed=True) == (
            f"Room 0.5 K below target; PI adds +1.2 K to {FIXED}; held value; setpoint 31 °C."
        )

    def test_stove_leads(self) -> None:
        """The stove sentence replaces the room feedback."""
        assert note(stove="Wood-stove mode", room=ROOM, error=0.5, status="held value") == (
            "Wood-stove mode; setpoint 31 °C."
        )

    def test_summer_leads(self) -> None:
        """The summer sentence replaces the stove sentence."""
        assert note(summer="Summer switch on", stove="Wood-stove mode", implausible=True) == (
            "Summer switch on; setpoint 31 °C."
        )


class TestClauses:
    """Freezes, plan, manual room target, boost, start ramp and the cycling floor."""

    def test_freezes(self) -> None:
        """Defrost, DHW and the skipped duty command are named in that order."""
        assert note(defrost=True, dhw=True, duty_skipped=True) == (
            f"No usable room temperature, so {CURVE} alone; "
            "defrost in progress: integrator frozen, no decrease; "
            "DHW run in progress: integrator frozen, no decrease; "
            "defrost: the pump sets its own duty; no duty command; setpoint 31 °C."
        )

    def test_plan_room_target_and_boost(self) -> None:
        """The plan clause, the room target clause and the boost follow in that order."""
        assert note(plan="plan +1.0 K", room_target="room target +0.5 K", boost=-1.04) == (
            f"No usable room temperature, so {CURVE} alone; plan +1.0 K; room target +0.5 K; "
            "boost -1.0 K; setpoint 31 °C."
        )

    def test_zero_boost_is_silent(self) -> None:
        """A zero boost is not named."""
        assert note(boost=0.0) == note()

    def test_start_ramp(self) -> None:
        """A start ramp below the target names its cap."""
        assert note(ramp_k=-2.0, ramp_cap_c=29.04) == (
            f"No usable room temperature, so {CURVE} alone; start ramp caps at 29.0 °C; "
            "setpoint 31 °C."
        )

    @pytest.mark.parametrize(("ramp_k", "cap"), [(-2.0, None), (0.0, 29.0)])
    def test_start_ramp_silent(self, ramp_k: float, cap: float | None) -> None:
        """Without a lowering ramp or without a cap the ramp is not named."""
        assert note(ramp_k=ramp_k, ramp_cap_c=cap) == note()

    def test_cycling_floor_limits_the_decrease(self) -> None:
        """A binding floor at or below the last setpoint limits the decrease."""
        assert note(binding="cycling_floor", floor_c=30.96, final=31, reference=32) == (
            f"No usable room temperature, so {CURVE} alone; "
            "cycling floor 31.0 °C limits the decrease; setpoint 32 → 31 °C."
        )

    @pytest.mark.parametrize("reference", [30, None])
    def test_cycling_floor_raises(self, reference: int | None) -> None:
        """A binding floor above the last setpoint (or without one) raises it."""
        text = note(binding="cycling_floor", floor_c=31.0, final=31, reference=reference)
        assert text.startswith(
            f"No usable room temperature, so {CURVE} alone; cycling floor raises to 31 °C; "
        )

    def test_cycling_floor_without_a_floor(self) -> None:
        """A cycling-floor binding without a floor names no floor, even while lifting."""
        assert note(binding="cycling_floor", cycling_lift_k=1.0) == (
            f"No usable room temperature, so {CURVE} alone; setpoint stays 31 °C, "
            "the min-run window keeps headroom to the pump's stop rule."
        )

    def test_min_run_window(self) -> None:
        """A lift of the min-run window names the lifted target."""
        assert note(cycling_lift_k=0.5, floor_c=31.5) == (
            f"No usable room temperature, so {CURVE} alone; "
            "min-run window lifts the target to 31.5 °C; setpoint 31 °C."
        )

    def test_min_run_window_needs_a_floor(self) -> None:
        """A lift without a floor is not named."""
        assert note(cycling_lift_k=0.5) == note()


class TestClampsAndOutcome:
    """The safety clamps and the final clause on the setpoint."""

    def test_continuous_clamp(self) -> None:
        """A clamp of the continuous value is named."""
        assert note(pre_clamp=47.26, pre_round=45.0, final=45, reference=40) == (
            f"No usable room temperature, so {CURVE} alone; safety clamps 47.3 to 45.0 °C; "
            "setpoint 40 → 45 °C."
        )

    def test_integer_clamp(self) -> None:
        """A clamp of the integer setpoint names its bound."""
        assert note(binding="max_supply", integer_clamp=(46, 45), final=45, reference=None) == (
            f"No usable room temperature, so {CURVE} alone; "
            "safety bound max_supply clamps 46 → 45 °C; setpoint 45 °C."
        )

    @pytest.mark.parametrize(
        ("binding", "held"),
        [
            ("rounding", "within rounding hysteresis"),
            ("deadband", "within the deadband"),
            ("dwell", "dwell time not over (8 min left)"),
            ("defrost_hold", "no decrease during defrost"),
            ("dhw_hold", "no decrease during DHW"),
            ("cycling_floor", "the min-run window keeps headroom to the pump's stop rule"),
        ],
    )
    def test_hold(self, binding: str, held: str) -> None:
        """A holding binding explains why the setpoint stays."""
        assert note(binding=binding, dwell_left_s=480.0) == (
            f"No usable room temperature, so {CURVE} alone; setpoint stays 31 °C, {held}."
        )

    def test_other_binding_at_the_reference(self) -> None:
        """A binding without a hold explanation gives the plain setpoint."""
        assert note(binding="start_ramp") == (
            f"No usable room temperature, so {CURVE} alone; setpoint 31 °C."
        )

    def test_change(self) -> None:
        """A change names both setpoints even with a holding binding."""
        assert note(binding="dwell", final=32, reference=31) == (
            f"No usable room temperature, so {CURVE} alone; setpoint 31 → 32 °C."
        )

    def test_no_reference(self) -> None:
        """Without a last setpoint the plain setpoint is named."""
        assert note(binding="dwell", reference=None) == (
            f"No usable room temperature, so {CURVE} alone; setpoint 31 °C."
        )


def test_every_clause_in_order() -> None:
    """All clauses together keep their order."""
    text = note(
        room=ROOM,
        error=-0.3,
        pi_k=-0.6,
        status="value 20.5 °C (1 min old), ±0.1 K",
        defrost=True,
        dhw=True,
        duty_skipped=True,
        plan="plan +1.0 K",
        room_target="room target -2.0 K",
        boost=1.5,
        ramp_k=-1.0,
        ramp_cap_c=30.0,
        binding="dwell",
        cycling_lift_k=1.0,
        floor_c=30.5,
        pre_clamp=24.0,
        pre_round=25.0,
        integer_clamp=(24, 25),
        final=25,
        reference=27,
        dwell_left_s=300.0,
    )
    assert text == (
        f"Room 0.3 K above target; PI adds -0.6 K to {CURVE}; "
        "value 20.5 °C (1 min old), ±0.1 K; "
        "defrost in progress: integrator frozen, no decrease; "
        "DHW run in progress: integrator frozen, no decrease; "
        "defrost: the pump sets its own duty; no duty command; "
        "plan +1.0 K; room target -2.0 K; boost +1.5 K; start ramp caps at 30.0 °C; "
        "min-run window lifts the target to 30.5 °C; safety clamps 24.0 to 25.0 °C; "
        "safety bound dwell clamps 24 → 25 °C; setpoint 27 → 25 °C."
    )

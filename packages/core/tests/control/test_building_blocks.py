from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import UTC, datetime, time

import pytest

from ovenbird_core.catalogue import HeishaSignal
from ovenbird_core.control import (
    DECISION_SCHEMA_VERSION,
    Bound,
    CommandIntent,
    DecisionRecord,
    EmitterType,
    HeatingCurve,
    InputRef,
    IntentKind,
    LadderLevel,
    Mode,
    OvenbirdConfig,
    Override,
    OverrideKind,
    PlanSlice,
    QuietModeConfig,
    QuietWindow,
    ReasonCode,
    RoomFeedbackConfig,
    SafetyLimits,
    SetpointStageConfig,
    StartRampConfig,
    Term,
    filter_outside,
    pump_actual,
    room_input,
    room_offset_to_water,
    round_half_up,
)
from ovenbird_core.inputs import ha_reading
from ovenbird_core.instant import Instant
from ovenbird_core.readings import Reading, SourceKind
from ovenbird_core.store import StateStore

T0 = 1_794_528_000.0
CURVE = HeatingCurve.of((-10, 39), (0, 34), (15, 25))


def at(seconds: float) -> Instant:
    return Instant.from_unix(T0 + seconds)


class TestCurve:
    def test_interpolates_between_points(self) -> None:
        assert CURVE.water(0) == 34
        assert CURVE.water(5) == pytest.approx(31.0)
        assert CURVE.water(-5) == pytest.approx(36.5)

    def test_clamped_at_the_ends(self) -> None:
        assert CURVE.water(-30) == 39
        assert CURVE.water(30) == 25

    def test_sensitivity_uses_segment_and_end_segments_beyond(self) -> None:
        assert CURVE.sensitivity(5) == pytest.approx(0.6)
        assert CURVE.sensitivity(-5) == pytest.approx(0.5)
        assert CURVE.sensitivity(-20) == pytest.approx(0.5)
        assert CURVE.sensitivity(25) == pytest.approx(0.6)

    def test_room_offset_maps_with_one_plus_slope(self) -> None:
        assert room_offset_to_water(CURVE, 5, 1.0) == pytest.approx(1.6)
        assert room_offset_to_water(CURVE, 5, -0.5) == pytest.approx(-0.8)

    @pytest.mark.parametrize(
        "pairs",
        [
            ((0, 30),),
            ((0, 30), (0, 25)),
            ((5, 30), (0, 25)),
            ((0, 25), (10, 30)),
            ((0, math.nan), (10, 25)),
        ],
    )
    def test_rejects_invalid_curves(self, pairs: tuple[tuple[float, float], ...]) -> None:
        with pytest.raises(ValueError, match="curve"):
            HeatingCurve.of(*pairs)


class TestOutsideFilter:
    def test_first_sample_initialises(self) -> None:
        assert filter_outside(None, None, 3.0, 0.0, 3600.0) == 3.0

    def test_exact_discretisation_is_tick_independent(self) -> None:
        one = filter_outside(0.0, 0.0, 10.0, 3600.0, 3600.0)
        many = 0.0
        for i in range(60):
            many = filter_outside(many, i * 60.0, 10.0, (i + 1) * 60.0, 3600.0)
        assert one == pytest.approx(10 * (1 - math.exp(-1)))
        assert many == pytest.approx(one)

    def test_integer_toggling_averages_out(self) -> None:
        value, last = 1.0, 0.0
        for i in range(1, 24 * 60):
            sample = 1.0 if i % 2 else 2.0
            value = filter_outside(value, last, sample, i * 60.0, 4 * 3600.0)
            last = i * 60.0
        assert value == pytest.approx(1.5, abs=0.01)

    def test_no_time_no_change_and_zero_tau_passes_through(self) -> None:
        assert filter_outside(4.0, 10.0, 8.0, 10.0, 3600.0) == 4.0
        assert filter_outside(4.0, 10.0, 8.0, 5.0, 3600.0) == 4.0
        assert filter_outside(4.0, 10.0, 8.0, 70.0, 0.0) == 8.0


class TestSafety:
    LIMITS = SafetyLimits(max_supply_c=40.0, envelope=CURVE)

    def test_envelope_band(self) -> None:
        bounds = self.LIMITS.bounds(5)
        assert bounds.low == pytest.approx(25.0)
        assert bounds.high == pytest.approx(36.0)
        assert bounds.low_source is Bound.ENVELOPE_MIN
        assert bounds.high_source is Bound.ENVELOPE_MAX

    def test_absolute_limits_win(self) -> None:
        cold = self.LIMITS.bounds(-20)
        assert cold.high == 40.0
        assert cold.high_source is Bound.MAX_SUPPLY
        warm = self.LIMITS.bounds(30)
        assert warm.low == 20.0
        assert warm.low_source is Bound.MIN_SETPOINT

    def test_max_supply_wins_over_envelope_minimum(self) -> None:
        hot = HeatingCurve.of((-10, 60), (10, 50))
        bounds = SafetyLimits(max_supply_c=40.0, envelope=hot).bounds(0)
        assert bounds.low == bounds.high == 40.0
        assert bounds.low_int == bounds.high_int == 40

    def test_min_setpoint_wins_over_low_envelope_maximum(self) -> None:
        cold_curve = HeatingCurve.of((-10, 15), (10, 12))
        bounds = SafetyLimits(max_supply_c=40.0, envelope=cold_curve).bounds(0)
        assert bounds.high == 20.0
        assert bounds.clamp_int(35) == 20

    def test_integer_bounds_round_inwards(self) -> None:
        bounds = SafetyLimits(max_supply_c=40.0, envelope=CURVE).bounds(4)
        assert bounds.low == pytest.approx(25.6)
        assert bounds.low_int == 26
        assert bounds.high_int == 36

    def test_the_envelope_rule_writes_the_envelope_curve(self) -> None:
        assert self.LIMITS.fallback_setpoint(5) == pytest.approx(31.0)
        assert self.LIMITS.fallback_values(5) == {31}
        assert self.LIMITS.fallback_setpoint(4) == pytest.approx(31.6)
        assert self.LIMITS.fallback_values(4) == {31, 32}

    def test_the_envelope_rule_stays_within_the_absolute_limits(self) -> None:
        hot = SafetyLimits(max_supply_c=40.0, envelope=HeatingCurve.of((-10, 60), (10, 50)))
        assert hot.fallback_values(0) == {40}
        cold = SafetyLimits(max_supply_c=40.0, envelope=HeatingCurve.of((-10, 15), (10, 12)))
        assert cold.fallback_values(0) == {20}

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"max_supply_c": 70.0},
            {"max_supply_c": 40.0, "min_setpoint_c": 5.0},
            {"max_supply_c": 20.5},
            {"max_supply_c": 40.0, "envelope_below_k": -1.0},
            {"max_supply_c": math.inf},
        ],
    )
    def test_rejects_invalid_limits(self, kwargs: dict[str, float]) -> None:
        with pytest.raises(ValueError, match="must"):
            SafetyLimits(envelope=CURVE, **kwargs)


class TestConfig:
    def test_presets_differ_by_emitter(self) -> None:
        screed = OvenbirdConfig.preset("screed_floor")
        radiators = OvenbirdConfig.preset(EmitterType.RADIATORS)
        mixed = OvenbirdConfig.preset("mixed")
        assert screed.safety.max_supply_c == 40.0
        assert mixed.safety.max_supply_c == 40.0
        assert radiators.safety.max_supply_c == 55.0
        assert screed.ramp.enabled
        assert mixed.ramp.enabled
        assert not radiators.ramp.enabled
        assert screed.feedback.ti_s > mixed.feedback.ti_s > radiators.feedback.ti_s
        assert screed.stages.dwell_s > mixed.stages.dwell_s > radiators.stages.dwell_s
        for config in (screed, radiators, mixed):
            assert config.stages.deadband_k >= 1.0
            assert config.feedback.output_limit_k == 3.0
            assert config.safety.min_setpoint_c == 20.0
            assert config.pump_duty is None
            assert config.quiet is None

    def test_curve_override_keeps_the_preset_envelope(self) -> None:
        curve = HeatingCurve.of((-10, 35), (15, 26))
        config = OvenbirdConfig.preset("mixed", curve=curve)
        assert config.curve is curve
        assert config.safety.envelope == OvenbirdConfig.preset("mixed").curve

    def test_curve_outside_the_envelope_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="envelope"):
            OvenbirdConfig.preset("mixed", curve=HeatingCurve.of((-10, 46), (15, 25)))

    def test_rejects_small_deadband(self) -> None:
        with pytest.raises(ValueError, match="deadband"):
            SetpointStageConfig(deadband_k=0.5)

    def test_rejects_ramp_reaching_below_envelope(self) -> None:
        with pytest.raises(ValueError, match="envelope"):
            OvenbirdConfig.preset("mixed", ramp=StartRampConfig(max_below_curve_k=8.0))

    def test_rejects_large_feedback_limit(self) -> None:
        with pytest.raises(ValueError, match="limit"):
            RoomFeedbackConfig(output_limit_k=8.0)

    def test_ki(self) -> None:
        assert RoomFeedbackConfig(kp=2.0, ti_s=7200.0).ki_per_s == pytest.approx(2.0 / 7200.0)
        assert RoomFeedbackConfig(kp=2.0, ti_s=0.0).ki_per_s == 0.0

    def test_quiet_windows(self) -> None:
        quiet = QuietModeConfig(
            windows=(QuietWindow(time(22), time(6), 2),), timezone="Europe/Amsterdam"
        )
        assert quiet.level_at(datetime(2026, 11, 14, 22, 30, tzinfo=UTC)) == 2
        assert quiet.level_at(datetime(2026, 11, 14, 4, 30, tzinfo=UTC)) == 2
        assert quiet.level_at(datetime(2026, 11, 14, 5, 30, tzinfo=UTC)) == 0
        assert quiet.level_at(datetime(2026, 11, 14, 12, 0, tzinfo=UTC)) == 0


class TestInputs:
    def test_plan_slice_interval_is_half_open(self) -> None:
        plan = PlanSlice(0.5, ReasonCode.PLAN_PREHEAT, at(0), at(900))
        assert plan.active(at(0))
        assert plan.active(at(899))
        assert not plan.active(at(900))
        assert not plan.active(at(-1))
        with pytest.raises(ValueError, match="interval"):
            PlanSlice(0.5, ReasonCode.PLAN_PREHEAT, at(10), at(10))

    def test_override_expiry(self) -> None:
        assert Override(OverrideKind.SETPOINT, 30, until=None).active(at(1e6))
        expiring = Override(OverrideKind.BOOST, 2, until=at(60))
        assert expiring.active(at(59))
        assert not expiring.active(at(60))

    def test_round_half_up(self) -> None:
        assert [round_half_up(x) for x in (30.49, 30.5, 31.5, -0.5)] == [30, 31, 32, 0]

    def test_actual_and_room_from_a_real_store(self) -> None:
        store = StateStore()
        for signal, value in (
            (HeishaSignal.HEATING_MODE, 1),
            (HeishaSignal.Z1_WATER_TARGET_TEMP, 33),
            (HeishaSignal.MAX_PUMP_DUTY, 159),
        ):
            store.apply(Reading(signal, value, None, at(0), SourceKind.HEISHAMON))
        store.apply(ha_reading("sensor.room", "21.4", instant=at(0)))
        snapshot = store.snapshot(at(60))
        actual = pump_actual(snapshot)
        assert actual.heating_mode is not None
        assert actual.heating_mode.value == 1
        assert actual.water_target is not None
        assert actual.water_target.fresh
        assert actual.max_pump_duty is not None
        assert actual.max_pump_duty.value == 159
        assert actual.quiet_mode is None
        room = room_input(snapshot, "ha/sensor.room")
        assert room is not None
        assert room.value == pytest.approx(21.4)
        assert room.fresh
        assert room_input(snapshot, None) is None
        assert room_input(snapshot, "ha/sensor.other") is None

    def test_room_invalidated_by_unavailable(self) -> None:
        store = StateStore()
        store.apply(ha_reading("sensor.room", "21.4", instant=at(0)))
        store.apply(ha_reading("sensor.room", "unavailable", instant=at(30)))
        room = room_input(store.snapshot(at(60)), "ha/sensor.room")
        assert room is not None
        assert not room.fresh
        assert room.reason is not None
        assert "unavailable" in room.reason

    def test_room_stale_after_max_age(self) -> None:
        store = StateStore()
        store.apply(ha_reading("sensor.room", "21.4", instant=at(0)))
        room = room_input(store.snapshot(at(3600)), "ha/sensor.room")
        assert room is not None
        assert not room.fresh


class TestRecordJson:
    def record(self) -> DecisionRecord:
        return DecisionRecord(
            at=at(0),
            controller="ovenbird",
            mode=Mode.AUTO,
            ladder=LadderLevel.CURVE_ONLY,
            terms=(Term("curve", 31.0, 31.0, "°C", "curve"), Term("room_feedback", 0.5, 0.5)),
            pre_round=31.5,
            setpoint=32,
            binding=None,
            flip_distance=0.25,
            flip_input="main/Outside_Temp",
            inputs_used=(
                InputRef("main/Outside_Temp", 5, 10.0, True, "heishamon"),
                InputRef("forecast", 4.5, None, True, "provider", datetime(2026, 1, 1, tzinfo=UTC)),
            ),
            controller_state={"integral_k": 0.1, "ramp_phase": "idle", "setpoint": None},
            reason=ReasonCode.CURVE,
            note="Curve only.",
            intents=(CommandIntent(IntentKind.WATER_SETPOINT, 32, ReasonCode.CURVE),),
        )

    def test_round_trip_through_json_text(self) -> None:
        record = self.record()
        data = record.to_json_dict()
        assert data["schema"] == DECISION_SCHEMA_VERSION
        restored = DecisionRecord.from_json_dict(json.loads(json.dumps(data)))
        assert restored == record
        assert restored.to_json_dict() == data

    def test_rejects_other_schema(self) -> None:
        data = self.record().to_json_dict()
        data["schema"] = DECISION_SCHEMA_VERSION + 1
        with pytest.raises(ValueError, match="schema"):
            DecisionRecord.from_json_dict(data)

    def test_rejects_non_finite_numbers(self) -> None:
        record = replace(self.record(), pre_round=math.inf)
        with pytest.raises(ValueError, match="finite"):
            record.to_json_dict()

    def test_controller_state_is_read_only(self) -> None:
        state = self.record().controller_state
        with pytest.raises(TypeError):
            state["x"] = 1  # type: ignore[index]

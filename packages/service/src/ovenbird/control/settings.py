"""Controller settings (``control_*``, ``command_*``, ``safety_*``) and the configuration they give.

The fields that mirror a controller setting are built from it
(:func:`~ovenbird.config.fromcore.core_field`): default, range, unit and description
live on the core dataclass (:class:`~ovenbird_core.control.RoomSensorProfile`,
:class:`~ovenbird_core.control.RoomFeedbackConfig`, ...). :func:`controller_config`
turns the settings into the controller configuration: the emitter preset with every
set field applied. The wood-stove settings are in :mod:`ovenbird.stove.settings`; the
cross-field rules are in :mod:`ovenbird.config.validation`.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_core import PydanticCustomError
from pydantic_settings import NoDecode

from ovenbird.config.fromcore import FeatureSettings, core_field
from ovenbird.config.network import normalise_broker
from ovenbird.config.sources import split_list
from ovenbird.config.validation.curve import check_curve_pairs, check_integral_time
from ovenbird.config.validation.quiet import check_clock_time
from ovenbird.config.values import (
    MAX_QUIET_WINDOWS,
    ControlModeName,
    CurvePairs,
    DefrostLowFlowMode,
    EmitterName,
    QuietWindowSetting,
    RoomProfileName,
    SetpointRegister,
    curve_from_pairs,
    pick,
)
from ovenbird.control.dayshift import DEFAULT_MIN_SUN_WM2, DEFAULT_RECOVERY_S
from ovenbird_core.control import (
    CyclingConfig,
    OutsideSource,
    OvenbirdConfig,
    PumpDutyConfig,
    QuietModeConfig,
    QuietStartConfig,
    RoomFeedbackConfig,
    RoomProfile,
    RoomSensorProfile,
    SafetyLimits,
    SetpointStageConfig,
    StartRampConfig,
    SummerConfig,
    default_curve,
)
from ovenbird_core.control.safety import DEFAULT_MAX_SUPPLY_C

if TYPE_CHECKING:
    from ovenbird.config.settings import Settings


class ControlSettings(FeatureSettings):
    """Controller mode, emitter, room sensor, comfort target, minimum setpoint and pump duty.

    Parameters
    ----------
    control_mode
        ``shadow`` (default), ``auto`` or ``off``.
    control_interval_s
        Seconds between controller ticks.
    control_emitter
        Emitter preset of the controller (curve, safety limits, tuning).
    control_room_signal
        Signal id of the room temperature.
    control_outside_signal, control_outside_max_age_s, control_outside_plausible_min_c,
    control_outside_plausible_max_c, control_outside_max_deviation_k
        :class:`~ovenbird_core.control.OutsideSource`: the outside thermometer the
        heating curve uses instead of the pump's sensor, its age limit, its plausible
        range and how far it may be from the pump's sensor.
    control_pump_duty
        Let the controller set the maximum pump duty (off by default).
    """

    control_mode: ControlModeName = "shadow"
    control_interval_s: float = Field(default=60.0, ge=5.0, le=3600.0)
    control_emitter: EmitterName = "mixed"
    control_room_signal: str | None = None
    control_room_profile: RoomProfileName = core_field(RoomSensorProfile, "kind")
    control_room_step_k: float | None = core_field(RoomSensorProfile, "step_k")
    control_room_report_interval_s: float = core_field(RoomSensorProfile, "report_interval_s")
    control_room_silence_limit_s: float = core_field(RoomSensorProfile, "silence_limit_s")
    control_room_liveness_signals: Annotated[tuple[str, ...], NoDecode] = core_field(
        RoomSensorProfile, "liveness"
    )
    control_room_crosscheck_signal: str | None = core_field(RoomSensorProfile, "crosscheck")
    control_outside_signal: str | None = core_field(OutsideSource, "signal", unset=True)
    control_outside_max_age_s: float = core_field(OutsideSource, "max_age_s")
    control_outside_plausible_min_c: float = core_field(OutsideSource, "plausible_min_c")
    control_outside_plausible_max_c: float = core_field(OutsideSource, "plausible_max_c")
    control_outside_max_deviation_k: float = core_field(OutsideSource, "max_deviation_k")
    control_comfort_c: float = core_field(OvenbirdConfig, "comfort_room_c")
    control_min_setpoint_c: float | None = core_field(SafetyLimits, "min_setpoint_c", unset=True)
    control_pump_duty: bool = False
    control_pump_duty_heat: int = core_field(PumpDutyConfig, "heat")
    control_pump_duty_idle: int = core_field(PumpDutyConfig, "idle")
    control_pump_duty_idle_delay_s: float = core_field(PumpDutyConfig, "idle_delay_s")

    @field_validator("control_room_liveness_signals", mode="before")
    @classmethod
    def _split_liveness(cls, value: Any) -> Any:
        """Read the liveness signals from a comma-separated text, none when unset."""
        return () if value is None else split_list(value)

    @field_validator("control_room_liveness_signals")
    @classmethod
    def _unique_liveness(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Strip the liveness signals and drop blanks and repeats, keeping the order."""
        return tuple(dict.fromkeys(item.strip() for item in value if item.strip()))

    @field_validator(
        "control_room_signal",
        "control_room_crosscheck_signal",
        "control_outside_signal",
        mode="before",
    )
    @classmethod
    def _empty_room_is_unset(cls, value: Any) -> Any:
        """Treat an empty room signal as unset."""
        if isinstance(value, str) and not value.strip():
            return None
        return value


type DayShiftUse = Literal["off", "shadow", "on"]


class DayShiftSettings(FeatureSettings):
    """The sun day shift (``control_dayshift_*``) and the bound on every rule plan slice.

    Local times are ``HH:MM`` in ``control_timezone``; see :mod:`ovenbird.control.dayshift`
    for the rule.

    Parameters
    ----------
    control_dayshift_use
        ``off`` (default): nothing runs. ``shadow``: the rule runs and records what it
        would do without changing any decision. ``on``: its offset shifts the room
        target; experimental, so valid only with ``control_dayshift_experimental_ok``
        (``dayshift_on_needs_ack``).
    control_dayshift_experimental_ok
        The owner accepts that the day shift is experimental (default off): in the
        simulator it made houses with large sun-facing windows too warm. Required for
        ``on``; it cannot be taken back while ``on`` is set.
    control_dayshift_day_start, control_dayshift_day_end
        Day window of the boost (09:00 to 17:00).
    control_dayshift_boost_k
        How much a sunny, mild day raises the room target (0 to 1 K, 0.5 K).
    control_dayshift_setback_k
        How much the night after a boosted day lowers it (0 to 1 K, 0.5 K).
    control_dayshift_min_outside_c
        Lowest outside temperature, now and forecast, at which the shift runs (-10 to
        15 °C, 5 °C); 1 K lower once it runs.
    control_dayshift_min_sun_wm2
        Lowest forecast mean irradiance over the rest of the day window for a boost (0 to
        600 W/m², 150 W/m²); half of it keeps a running boost.
    control_dayshift_night_start, control_dayshift_night_end
        Night window of the set-back (23:00 to 05:00).
    control_dayshift_comfort_at
        When the room must be back at comfort after a set-back (07:00).
    control_dayshift_recovery_s
        How long before ``control_dayshift_comfort_at`` a set-back has ended at the
        latest (0 to 8 h, 4 h): the under-floor heating needs that long to bring the room
        back.
    control_plan_rule_max_k
        Largest room-target shift of any rule plan slice
        (:attr:`~ovenbird_core.control.OvenbirdConfig.plan_rule_max_k`); it also bounds how
        far a set-back lowers the comfort-floor alarm.
    """

    control_dayshift_use: DayShiftUse = "off"
    control_dayshift_experimental_ok: bool = False
    control_dayshift_day_start: str = "09:00"
    control_dayshift_day_end: str = "17:00"
    control_dayshift_boost_k: float = Field(default=0.5, ge=0.0, le=1.0)
    control_dayshift_setback_k: float = Field(default=0.5, ge=0.0, le=1.0)
    control_dayshift_min_outside_c: float = Field(default=5.0, ge=-10.0, le=15.0)
    control_dayshift_min_sun_wm2: float = Field(default=DEFAULT_MIN_SUN_WM2, ge=0.0, le=600.0)
    control_dayshift_night_start: str = "23:00"
    control_dayshift_night_end: str = "05:00"
    control_dayshift_comfort_at: str = "07:00"
    control_dayshift_recovery_s: float = Field(default=DEFAULT_RECOVERY_S, ge=0.0, le=28_800.0)
    control_plan_rule_max_k: float = core_field(OvenbirdConfig, "plan_rule_max_k")

    @field_validator(
        "control_dayshift_day_start",
        "control_dayshift_day_end",
        "control_dayshift_night_start",
        "control_dayshift_night_end",
        "control_dayshift_comfort_at",
    )
    @classmethod
    def _clock_time(cls, value: str) -> str:
        """Refuse a local time that is not ``HH:MM`` (``clock_time``)."""
        return check_clock_time(value)


class ManualTargetSettings(FeatureSettings):
    """Manual boost and away (``control_boost_*``, ``control_away_*``).

    Both act only on request (``POST api/v1/control/boost``, ``PUT api/v1/control/away``),
    so they are on by default; see :mod:`ovenbird.control.roomtarget`.

    Parameters
    ----------
    control_boost_enabled
        Accept a boost (a temporary room target, warmer or cooler).
    control_boost_default_s
        Length of a boost asked without one (15 min to 12 h, 2 h).
    control_boost_default_k
        Room offset of a boost asked without one (0.5 to 2 K, 1 K).
    control_away_enabled
        Accept an away period.
    control_away_target_c
        Room target while away (10 to 20 °C, 16 °C).
    control_away_comfort_lead_s
        How long before the end of an away period the comfort target returns (0 to 24 h,
        6 h), so the under-floor heating has the house warm on return.
    """

    control_boost_enabled: bool = True
    control_boost_default_s: float = Field(default=7200.0, ge=900.0, le=43_200.0)
    control_boost_default_k: float = Field(default=1.0, ge=0.5, le=2.0)
    control_away_enabled: bool = True
    control_away_target_c: float = Field(default=16.0, ge=10.0, le=20.0)
    control_away_comfort_lead_s: float = Field(default=21_600.0, ge=0.0, le=86_400.0)


class SummerSettings(FeatureSettings):
    """The summer switch (``control_summer_*``): no space heating in warm weather.

    Parameters
    ----------
    control_summer_enabled
        Summer switch on (off by default).
    control_summer_off_c, control_summer_hysteresis_k, control_summer_mean_s
        :class:`~ovenbird_core.control.SummerConfig`: the limit of the slow outside mean,
        how far below it heating resumes and the mean's time constant.
    """

    control_summer_enabled: bool = False
    control_summer_off_c: float = core_field(SummerConfig, "off_c")
    control_summer_hysteresis_k: float = core_field(SummerConfig, "hysteresis_k")
    control_summer_mean_s: float = core_field(SummerConfig, "mean_tau_s")

    def summer_config(self) -> SummerConfig | None:
        """Return the summer switch configuration (``None`` when it is off)."""
        if not self.control_summer_enabled:
            return None
        return SummerConfig(
            off_c=self.control_summer_off_c,
            hysteresis_k=self.control_summer_hysteresis_k,
            mean_tau_s=self.control_summer_mean_s,
        )


class TuningSettings(FeatureSettings):
    """Curve, feedback, stages, ramp, cycling, quiet windows, envelope and expert constants.

    The fields that default to ``None`` take the emitter preset's (or the core
    default) value when unset.

    Parameters
    ----------
    control_curve, control_envelope_curve
        Heating curve and safety envelope curve as ``[outside_c, water_c]`` points.
    control_weather_compensation, control_fixed_water_c
        Weather-dependent control (WAR) on: the water follows the curve; off: the
        fixed water temperature. Independent of the room feedback.
    control_feedback_enabled
        Room feedback (PI) on; off leaves the curve (or fixed temperature) only.
    control_quiet_windows
        Up to four daily quiet-mode windows.
    control_quiet_enabled
        Quiet windows in use (on by default); off ignores them.
    control_quiet_start_enabled, control_quiet_start_minutes, control_quiet_start_level
        Quiet mode for the first minutes after a compressor start (off by default; 1 to
        30 min, 10 min; level 1 to 3, 2), the quieter of it and a window.
    """

    control_curve: CurvePairs | None = None
    control_weather_compensation: bool = core_field(OvenbirdConfig, "weather_compensation")
    control_fixed_water_c: float = core_field(OvenbirdConfig, "fixed_water_c")
    control_outside_filter_s: float | None = core_field(
        OvenbirdConfig, "outside_filter_tau_s", unset=True
    )
    control_feedback_enabled: bool = True
    control_feedback_kp: float | None = core_field(RoomFeedbackConfig, "kp", unset=True)
    control_feedback_ti_s: float | None = core_field(RoomFeedbackConfig, "ti_s", unset=True)
    control_feedback_output_limit_k: float | None = core_field(
        RoomFeedbackConfig, "output_limit_k", unset=True
    )
    control_feedback_integral_limit_k: float | None = core_field(
        RoomFeedbackConfig, "integral_limit_k", unset=True
    )
    control_max_supply_c: float | None = core_field(SafetyLimits, "max_supply_c", unset=True)
    control_deadband_k: float | None = core_field(SetpointStageConfig, "deadband_k", unset=True)
    control_dwell_s: float | None = core_field(SetpointStageConfig, "dwell_s", unset=True, ge=300.0)
    control_ramp_enabled: bool | None = core_field(StartRampConfig, "enabled", unset=True)
    control_ramp_hold_s: float | None = core_field(StartRampConfig, "hold_s", unset=True)
    control_ramp_max_below_curve_k: float | None = core_field(
        StartRampConfig, "max_below_curve_k", unset=True
    )
    control_ramp_release_k_per_h: float | None = core_field(
        StartRampConfig, "release_k_per_h", unset=True
    )
    control_cycling_enabled: bool | None = core_field(CyclingConfig, "enabled", unset=True)
    control_cycling_min_run_s: float | None = core_field(CyclingConfig, "min_run_s", unset=True)
    control_quiet_windows: tuple[QuietWindowSetting, ...] = Field(
        default=(), max_length=MAX_QUIET_WINDOWS
    )
    control_quiet_enabled: bool = True
    control_quiet_start_enabled: bool = False
    control_quiet_start_minutes: int = Field(default=10, ge=1, le=30)
    control_quiet_start_level: int = core_field(QuietStartConfig, "level")
    control_timezone: str = core_field(QuietModeConfig, "timezone")
    control_envelope_curve: CurvePairs | None = None
    control_envelope_below_k: float | None = core_field(
        SafetyLimits, "envelope_below_k", unset=True
    )
    control_envelope_above_k: float | None = core_field(
        SafetyLimits, "envelope_above_k", unset=True
    )
    control_rounding_hysteresis_k: float | None = core_field(
        SetpointStageConfig, "rounding_hysteresis_k", unset=True
    )
    control_ramp_dwell_s: float | None = core_field(SetpointStageConfig, "ramp_dwell_s", unset=True)
    control_ramp_below_outlet_k: float | None = core_field(
        StartRampConfig, "below_outlet_k", unset=True
    )
    control_cycling_stop_delta_k: float | None = core_field(
        CyclingConfig, "stop_delta_k", unset=True
    )
    control_cycling_margin_k: float | None = core_field(CyclingConfig, "margin_k", unset=True)
    control_cycling_max_raise_k: float | None = core_field(CyclingConfig, "max_raise_k", unset=True)
    control_cycling_decrease_headroom_k: float | None = core_field(
        CyclingConfig, "decrease_headroom_k", unset=True
    )
    control_feedback_max_integration_step_s: float | None = core_field(
        RoomFeedbackConfig, "max_integration_step_s", unset=True
    )
    control_room_decay_start_s: float | None = core_field(
        RoomSensorProfile, "decay_start_s", unset=True
    )
    control_room_alive_decay_start_s: float | None = core_field(
        RoomSensorProfile, "alive_decay_start_s", unset=True
    )
    control_room_alive_decay_end_s: float | None = core_field(
        RoomSensorProfile, "alive_decay_end_s", unset=True
    )
    control_room_crosscheck_threshold_k: float | None = core_field(
        RoomSensorProfile, "crosscheck_threshold_k", unset=True
    )
    control_room_crosscheck_sustain_s: float | None = core_field(
        RoomSensorProfile, "crosscheck_sustain_s", unset=True
    )
    control_room_crosscheck_tau_s: float | None = core_field(
        RoomSensorProfile, "crosscheck_tau_s", unset=True
    )

    @field_validator("control_curve", "control_envelope_curve")
    @classmethod
    def _valid_curve(cls, value: CurvePairs | None) -> CurvePairs | None:
        """Check the heating-curve points, if any."""
        return None if value is None else check_curve_pairs(value)

    @field_validator("control_feedback_ti_s")
    @classmethod
    def _integral_time(cls, value: float | None) -> float | None:
        """Check the feedback integral time."""
        return check_integral_time(value)

    @field_validator("control_timezone")
    @classmethod
    def _valid_zone(cls, value: str) -> str:
        """Require an IANA time zone name."""
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError, ValueError:
            raise PydanticCustomError("timezone", "not an IANA time zone") from None
        return value


class CommandSettings(FeatureSettings):
    """Command publishing, holds, the envelope fallback rule and the saved controller state."""

    envelope_rule_installed: bool = False
    allow_commands: bool = False
    command_brokers: Annotated[tuple[str, ...], NoDecode] = ()
    command_setpoint_register: SetpointRegister = "setcurves_target_high"
    command_min_spacing_s: float = Field(default=7.0, ge=1.0)
    command_verify_timeout_s: float = Field(default=30.0, ge=5.0)
    command_max_retries: int = Field(default=3, ge=0, le=10)
    command_daily_budget: int = Field(default=150, ge=1, le=2000)
    command_hold_s: float = Field(default=3600.0, ge=60.0)
    command_pump_duty_min: int = Field(default=80, ge=1, le=254)
    command_pump_duty_max: int = Field(default=200, ge=1, le=254)
    command_escalation_hours: float = Field(default=12.0, gt=0.0, le=168.0)
    command_escalation_factor: float = Field(default=4.0, ge=1.0, le=48.0)
    command_latch_after: int = Field(default=3, ge=2, le=20)
    control_state_max_age_s: float = Field(default=900.0, ge=0.0, le=86_400.0)

    @field_validator("command_brokers", mode="before")
    @classmethod
    def _split_brokers(cls, value: Any) -> Any:
        """Read the broker list from a comma-separated text, none when unset."""
        return () if value is None else split_list(value)

    @field_validator("command_brokers")
    @classmethod
    def _valid_brokers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Normalise every broker entry and drop repeats, keeping the order."""
        return tuple(dict.fromkeys(normalise_broker(entry) for entry in value))


class SafetySettings(FeatureSettings):
    """Safety monitors (``safety_*``)."""

    safety_interval_s: float = Field(default=5.0, ge=1.0, le=60.0)
    safety_outlet_margin_k: float = Field(default=5.0, ge=0.0, le=20.0)
    safety_outlet_sustain_s: float = Field(default=600.0, ge=0.0, le=7200.0)
    safety_min_flow_lpm: float = Field(default=8.0, ge=0.0, le=60.0)
    safety_flow_sustain_s: float = Field(default=120.0, ge=0.0, le=3600.0)
    safety_defrost_low_flow: DefrostLowFlowMode = "auto"
    safety_defrost_max_s: float = Field(default=1200.0, ge=60.0, le=14_400.0)
    safety_room_floor_k: float | None = Field(default=1.5, gt=0.0, le=10.0)
    safety_room_floor_sustain_s: float = Field(default=1800.0, ge=0.0, le=86_400.0)
    safety_starts_alarm_enabled: bool = True
    safety_starts_per_hour_max: int = Field(default=4, ge=1, le=20)
    safety_starts_per_day_max: int = Field(default=30, ge=1, le=200)


def room_profile(settings: Settings) -> RoomSensorProfile:
    """Return the room sensor profile the settings describe."""
    base = RoomSensorProfile()
    return RoomSensorProfile(
        kind=RoomProfile(settings.control_room_profile),
        step_k=settings.control_room_step_k,
        report_interval_s=settings.control_room_report_interval_s,
        silence_limit_s=settings.control_room_silence_limit_s,
        liveness=settings.control_room_liveness_signals,
        crosscheck=settings.control_room_crosscheck_signal,
        decay_start_s=pick(settings.control_room_decay_start_s, base.decay_start_s),
        alive_decay_start_s=pick(
            settings.control_room_alive_decay_start_s, base.alive_decay_start_s
        ),
        alive_decay_end_s=pick(settings.control_room_alive_decay_end_s, base.alive_decay_end_s),
        crosscheck_threshold_k=pick(
            settings.control_room_crosscheck_threshold_k, base.crosscheck_threshold_k
        ),
        crosscheck_sustain_s=pick(
            settings.control_room_crosscheck_sustain_s, base.crosscheck_sustain_s
        ),
        crosscheck_tau_s=pick(settings.control_room_crosscheck_tau_s, base.crosscheck_tau_s),
    )


def safety_limits(settings: Settings) -> SafetyLimits:
    """Return the safety limits: the emitter's, with the configured overrides."""
    emitter = settings.emitter
    preset = OvenbirdConfig.preset(emitter).safety
    envelope = (
        default_curve(emitter)
        if settings.control_envelope_curve is None
        else curve_from_pairs(settings.control_envelope_curve)
    )
    return SafetyLimits(
        max_supply_c=pick(settings.control_max_supply_c, DEFAULT_MAX_SUPPLY_C[emitter]),
        envelope=envelope,
        min_setpoint_c=pick(settings.control_min_setpoint_c, preset.min_setpoint_c),
        envelope_below_k=pick(settings.control_envelope_below_k, preset.envelope_below_k),
        envelope_above_k=pick(settings.control_envelope_above_k, preset.envelope_above_k),
    )


def controller_config(settings: Settings) -> OvenbirdConfig:
    """Return the controller configuration: the emitter preset with every set field applied.

    Raises
    ------
    ValueError
        When the controller's own checks reject the combination.
    """
    preset = OvenbirdConfig.preset(settings.emitter)
    fb, ramp, cyc, stages = preset.feedback, preset.ramp, preset.cycling, preset.stages
    enabled = settings.control_feedback_enabled
    feedback = RoomFeedbackConfig(
        kp=pick(settings.control_feedback_kp, fb.kp) if enabled else 0.0,
        ti_s=pick(settings.control_feedback_ti_s, fb.ti_s) if enabled else 0.0,
        output_limit_k=pick(settings.control_feedback_output_limit_k, fb.output_limit_k),
        integral_limit_k=pick(settings.control_feedback_integral_limit_k, fb.integral_limit_k),
        max_integration_step_s=pick(
            settings.control_feedback_max_integration_step_s, fb.max_integration_step_s
        ),
    )
    return replace(
        preset,
        curve=preset.curve
        if settings.control_curve is None
        else curve_from_pairs(settings.control_curve),
        safety=safety_limits(settings),
        weather_compensation=settings.control_weather_compensation,
        fixed_water_c=settings.control_fixed_water_c,
        comfort_room_c=settings.control_comfort_c,
        outside_filter_tau_s=pick(settings.control_outside_filter_s, preset.outside_filter_tau_s),
        feedback=feedback,
        ramp=StartRampConfig(
            enabled=pick(settings.control_ramp_enabled, ramp.enabled),
            hold_s=pick(settings.control_ramp_hold_s, ramp.hold_s),
            below_outlet_k=pick(settings.control_ramp_below_outlet_k, ramp.below_outlet_k),
            max_below_curve_k=pick(settings.control_ramp_max_below_curve_k, ramp.max_below_curve_k),
            release_k_per_h=pick(settings.control_ramp_release_k_per_h, ramp.release_k_per_h),
        ),
        cycling=CyclingConfig(
            enabled=pick(settings.control_cycling_enabled, cyc.enabled),
            min_run_s=pick(settings.control_cycling_min_run_s, cyc.min_run_s),
            stop_delta_k=pick(settings.control_cycling_stop_delta_k, cyc.stop_delta_k),
            margin_k=pick(settings.control_cycling_margin_k, cyc.margin_k),
            max_raise_k=pick(settings.control_cycling_max_raise_k, cyc.max_raise_k),
            decrease_headroom_k=pick(
                settings.control_cycling_decrease_headroom_k, cyc.decrease_headroom_k
            ),
        ),
        stages=SetpointStageConfig(
            rounding_hysteresis_k=pick(
                settings.control_rounding_hysteresis_k, stages.rounding_hysteresis_k
            ),
            deadband_k=pick(settings.control_deadband_k, stages.deadband_k),
            dwell_s=pick(settings.control_dwell_s, stages.dwell_s),
            ramp_dwell_s=pick(settings.control_ramp_dwell_s, stages.ramp_dwell_s),
        ),
        pump_duty=(
            PumpDutyConfig(
                heat=settings.control_pump_duty_heat,
                idle=settings.control_pump_duty_idle,
                idle_delay_s=settings.control_pump_duty_idle_delay_s,
            )
            if settings.control_pump_duty
            else None
        ),
        quiet=(
            QuietModeConfig(
                tuple(window.to_core() for window in settings.control_quiet_windows),
                settings.control_timezone,
            )
            if settings.control_quiet_windows and settings.control_quiet_enabled
            else None
        ),
        quiet_start=(
            QuietStartConfig(
                duration_s=settings.control_quiet_start_minutes * 60.0,
                level=settings.control_quiet_start_level,
            )
            if settings.control_quiet_start_enabled
            else None
        ),
        summer=settings.summer_config(),
        room=room_profile(settings),
        stove=settings.stove_config(),
        outside=outside_source(settings),
        plan_rule_max_k=settings.control_plan_rule_max_k,
    )


def outside_source(settings: Settings) -> OutsideSource | None:
    """Return the chosen outside thermometer for the curve (``None``: the pump's sensor)."""
    if settings.control_outside_signal is None:
        return None
    return OutsideSource(
        settings.control_outside_signal,
        settings.control_outside_max_age_s,
        settings.control_outside_plausible_min_c,
        settings.control_outside_plausible_max_c,
        settings.control_outside_max_deviation_k,
    )

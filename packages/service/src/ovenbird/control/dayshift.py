"""The sun day shift in the service: the core rule and its parameters from the settings.

The rule itself is pure and lives in :mod:`ovenbird_core.control.dayshift`, so the
simulator evaluates the very function the service runs. This module re-exports it and
adds :func:`params_from_settings`, which reads the ``control_dayshift_*`` settings, the
controller's bound ``control_plan_rule_max_k`` and the installation's local zone
``control_timezone`` (every window is a local time in that zone).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ovenbird_core.control.dayshift import (
    DEFAULT_MIN_BOOST_S,
    DEFAULT_MIN_SUN_WM2,
    DEFAULT_RECOVERY_S,
    DEFAULT_SETBACK_WARM_K,
    DEFAULT_WARM_STOP_K,
    HYSTERESIS_K,
    MEMORY_VERSION,
    OFFSET_DIGITS,
    ROOM_MARGIN_K,
    SLICE_VALID_S,
    SLOT_S,
    STEP_K,
    SUN_HOLD_SHARE,
    DayShiftInputs,
    DayShiftMemory,
    DayShiftParams,
    DayShiftResult,
    ForecastSummary,
    NextChange,
    Night,
    Phase,
    Reason,
    Schedule,
    clock_time,
    coldest,
    decide,
    next_change,
    recorded_slice,
    rule_slice,
    sun_over,
    window_problem,
)

if TYPE_CHECKING:
    from ovenbird.config import Settings

__all__ = [
    "DEFAULT_MIN_BOOST_S",
    "DEFAULT_MIN_SUN_WM2",
    "DEFAULT_RECOVERY_S",
    "DEFAULT_SETBACK_WARM_K",
    "DEFAULT_WARM_STOP_K",
    "HYSTERESIS_K",
    "MEMORY_VERSION",
    "OFFSET_DIGITS",
    "ROOM_MARGIN_K",
    "SLICE_VALID_S",
    "SLOT_S",
    "STEP_K",
    "SUN_HOLD_SHARE",
    "DayShiftInputs",
    "DayShiftMemory",
    "DayShiftParams",
    "DayShiftResult",
    "ForecastSummary",
    "NextChange",
    "Night",
    "Phase",
    "Reason",
    "Schedule",
    "clock_time",
    "coldest",
    "decide",
    "next_change",
    "params_from_settings",
    "recorded_slice",
    "rule_slice",
    "sun_over",
    "window_problem",
]


def params_from_settings(settings: Settings) -> DayShiftParams:
    """Return the rule parameters the settings describe, in ``control_timezone``."""
    return DayShiftParams(
        day_start=clock_time(settings.control_dayshift_day_start),
        day_end=clock_time(settings.control_dayshift_day_end),
        night_start=clock_time(settings.control_dayshift_night_start),
        night_end=clock_time(settings.control_dayshift_night_end),
        comfort_at=clock_time(settings.control_dayshift_comfort_at),
        boost_k=settings.control_dayshift_boost_k,
        setback_k=settings.control_dayshift_setback_k,
        min_outside_c=settings.control_dayshift_min_outside_c,
        min_sun_wm2=settings.control_dayshift_min_sun_wm2,
        recovery_s=settings.control_dayshift_recovery_s,
        max_k=settings.control_plan_rule_max_k,
        timezone=settings.control_timezone,
    )

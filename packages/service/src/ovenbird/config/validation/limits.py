"""Cross-field rules of the safety limits, the heating curve, the feedback and the ramp."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ovenbird.config.values import Issue, curve_from_pairs, pick

if TYPE_CHECKING:
    from ovenbird.config.settings import Settings


from ovenbird_core.control import (
    OvenbirdConfig,
    envelope_violations,
)
from ovenbird_core.control.safety import DEFAULT_MAX_SUPPLY_C


def limit_issues(settings: Settings) -> list[Issue]:
    """Return the violated rules of the safety limits, curve, feedback and start ramp.

    Parameters
    ----------
    settings
        Settings to check.
    """
    issues: list[Issue] = []
    try:
        safety = settings.safety_limits()
    except ValueError as exc:
        field = (
            "control_min_setpoint_c"
            if settings.control_min_setpoint_c is not None
            else "control_max_supply_c"
        )
        return [
            Issue(
                field,
                "min_above_max",
                f"{exc} (max_supply_c and min_setpoint_c)",
                {
                    "min": pick(
                        settings.control_min_setpoint_c,
                        OvenbirdConfig.preset(settings.emitter).safety.min_setpoint_c,
                    ),
                    "max": pick(
                        settings.control_max_supply_c, DEFAULT_MAX_SUPPLY_C[settings.emitter]
                    ),
                },
            )
        ]
    if settings.control_curve is not None:
        waters = [water for _, water in settings.control_curve]
        if min(waters) < safety.min_setpoint_c or max(waters) > safety.max_supply_c:
            issues.append(
                Issue(
                    "control_curve",
                    "curve_range",
                    f"curve water temperatures must lie within [{safety.min_setpoint_c:g}, "
                    f"{safety.max_supply_c:g}] °C (minimum setpoint, maximum supply)",
                    {"min": safety.min_setpoint_c, "max": safety.max_supply_c},
                )
            )
        curve = curve_from_pairs(settings.control_curve)
        outside = envelope_violations(curve, safety)
        if outside:
            issues.append(
                Issue(
                    "control_curve",
                    "outside_envelope",
                    "the heating curve leaves the safety envelope at "
                    + ", ".join(f"{o:g} °C outside ({d:+.1f} K)" for o, d in outside),
                    {"at": [o for o, _ in outside], "by_k": [round(d, 2) for _, d in outside]},
                )
            )
    fixed = settings.control_fixed_water_c
    if not settings.control_weather_compensation and not (
        safety.min_setpoint_c <= fixed <= safety.max_supply_c
    ):
        issues.append(
            Issue(
                "control_fixed_water_c",
                "fixed_range",
                f"the fixed water temperature must lie within [{safety.min_setpoint_c:g}, "
                f"{safety.max_supply_c:g}] °C (minimum setpoint, maximum supply)",
                {"min": safety.min_setpoint_c, "max": safety.max_supply_c},
            )
        )
    output = settings.control_feedback_output_limit_k
    integral = settings.control_feedback_integral_limit_k
    preset_output = OvenbirdConfig.preset(settings.emitter).feedback.output_limit_k
    if integral is not None and integral > pick(output, preset_output):
        issues.append(
            Issue(
                "control_feedback_integral_limit_k",
                "integral_above_output",
                "the integrator limit must not exceed the feedback output limit",
            )
        )
    ramp_below = settings.control_ramp_max_below_curve_k
    if ramp_below is not None and ramp_below > safety.envelope_below_k:
        issues.append(
            Issue(
                "control_ramp_max_below_curve_k",
                "ramp_below_envelope",
                f"the start ramp may not reach below the safety envelope "
                f"({safety.envelope_below_k:g} K below its curve)",
                {"max": safety.envelope_below_k},
            )
        )
    return issues

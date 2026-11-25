"""Field rules of the heating curves and the room feedback's integral time."""

from __future__ import annotations

import itertools
import math

from pydantic_core import PydanticCustomError

from ovenbird.config.values import (
    CURVE_OUTSIDE_MAX_C,
    CURVE_OUTSIDE_MIN_C,
    MAX_CURVE_POINTS,
    MIN_CURVE_POINTS,
    MIN_INTEGRAL_TIME_S,
    CurvePairs,
)


def check_curve_pairs(value: CurvePairs) -> CurvePairs:
    """Return a curve's ``(outside_c, water_c)`` points as floats once they are valid.

    Raises
    ------
    PydanticCustomError
        ``curve_points``, ``curve_outside_range`` or ``curve_order``.
    """
    if not MIN_CURVE_POINTS <= len(value) <= MAX_CURVE_POINTS:
        raise PydanticCustomError(
            "curve_points",
            "a curve needs {min} to {max} points",
            {"min": MIN_CURVE_POINTS, "max": MAX_CURVE_POINTS},
        )
    for outside, water in value:
        if not (math.isfinite(outside) and math.isfinite(water)):
            raise PydanticCustomError("curve_points", "curve points must be finite")
        if not CURVE_OUTSIDE_MIN_C <= outside <= CURVE_OUTSIDE_MAX_C:
            raise PydanticCustomError(
                "curve_outside_range",
                "curve outside temperatures must lie within [{min}, {max}] °C",
                {"min": CURVE_OUTSIDE_MIN_C, "max": CURVE_OUTSIDE_MAX_C},
            )
    for (o1, w1), (o2, w2) in itertools.pairwise(value):
        if not o1 < o2:
            raise PydanticCustomError(
                "curve_order", "curve outside temperatures must strictly increase"
            )
        if w2 > w1:
            raise PydanticCustomError(
                "curve_order", "curve water temperatures must not increase with outside"
            )
    return tuple((float(o), float(w)) for o, w in value)


def check_integral_time(value: float | None) -> float | None:
    """Return the integral time when it is 0 (no integral part) or long enough.

    Raises
    ------
    PydanticCustomError
        ``integral_time`` for a value between 0 and :data:`MIN_INTEGRAL_TIME_S`.
    """
    if value is not None and 0.0 < value < MIN_INTEGRAL_TIME_S:
        raise PydanticCustomError(
            "integral_time",
            "the integral time is 0 (no integral part) or at least {min} s",
            {"min": MIN_INTEGRAL_TIME_S},
        )
    return value

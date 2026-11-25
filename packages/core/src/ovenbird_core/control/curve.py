"""Heating curve and the outside-temperature filter that feeds it."""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass

MIN_CURVE_POINTS = 2


@dataclass(frozen=True, slots=True)
class CurvePoint:
    """One point of a heating curve.

    Parameters
    ----------
    outside_c
        Outside temperature in °C.
    water_c
        Water setpoint in °C at that outside temperature.
    """

    outside_c: float
    water_c: float


@dataclass(frozen=True, slots=True)
class HeatingCurve:
    """Piecewise-linear water setpoint over outside temperature, clamped at the ends.

    Parameters
    ----------
    points
        At least two points with strictly increasing outside temperature and
        non-increasing water temperature (a heating curve never asks for warmer
        water when it gets warmer outside).

    Raises
    ------
    ValueError
        When the points violate the rules above or are not finite.
    """

    points: tuple[CurvePoint, ...]

    def __post_init__(self) -> None:
        """Validate the points."""
        if len(self.points) < MIN_CURVE_POINTS:
            raise ValueError("a heating curve needs at least two points")
        for point in self.points:
            if not (math.isfinite(point.outside_c) and math.isfinite(point.water_c)):
                raise ValueError("curve points must be finite")
        for left, right in zip(self.points, self.points[1:], strict=False):
            if not left.outside_c < right.outside_c:
                raise ValueError("curve outside temperatures must strictly increase")
            if right.water_c > left.water_c:
                raise ValueError("curve water temperatures must not increase with outside")

    @classmethod
    def of(cls, *pairs: tuple[float, float]) -> HeatingCurve:
        """Build a curve from ``(outside_c, water_c)`` pairs."""
        return cls(tuple(CurvePoint(float(o), float(w)) for o, w in pairs))

    def _segment(self, outside_c: float) -> tuple[CurvePoint, CurvePoint]:
        keys = [point.outside_c for point in self.points]
        index = min(max(bisect_right(keys, outside_c), 1), len(self.points) - 1)
        return self.points[index - 1], self.points[index]

    def water(self, outside_c: float) -> float:
        """Return the water setpoint at ``outside_c`` (flat beyond the end points)."""
        first, last = self.points[0], self.points[-1]
        if outside_c <= first.outside_c:
            return first.water_c
        if outside_c >= last.outside_c:
            return last.water_c
        left, right = self._segment(outside_c)
        share = (outside_c - left.outside_c) / (right.outside_c - left.outside_c)
        return left.water_c + share * (right.water_c - left.water_c)

    def sensitivity(self, outside_c: float) -> float:
        """Return ``|d water / d outside|`` of the segment at ``outside_c``.

        Beyond the end points the curve output is flat, but the house's heat demand
        still follows the nearest segment, so the end segment's slope is used. This
        is what the plan term needs to map a room offset to water (see
        :func:`room_offset_to_water`).
        """
        left, right = self._segment(outside_c)
        return abs((right.water_c - left.water_c) / (right.outside_c - left.outside_c))


def room_offset_to_water(curve: HeatingCurve, outside_c: float, room_offset_k: float) -> float:
    """Map a room-temperature offset to a water-setpoint offset without a room sensor.

    A heating curve encodes ``water - room ≈ s * (room - outside)`` with ``s`` its
    slope, so ``d water / d room = 1 + s``: raising the room target by 1 K costs
    the 1 K itself plus the extra heat loss that 1 K causes, which the curve prices
    at ``s`` per K. Evaluated at the current (filtered) outside temperature.

    Parameters
    ----------
    curve
        The heating curve.
    outside_c
        Filtered outside temperature.
    room_offset_k
        Desired room offset in K.

    Returns
    -------
    float
        Water offset in K.
    """
    return (1.0 + curve.sensitivity(outside_c)) * room_offset_k


def filter_outside(
    previous: float | None,
    previous_at: float | None,
    sample: float,
    at: float,
    tau_s: float,
) -> float:
    """First-order exponential filter on the outside temperature.

    ``Outside_Temp`` is an integer that toggles between neighbours; an exact
    discretisation ``y += (1 - exp(-dt / tau)) * (x - y)`` turns the toggling into
    its time-weighted mean and is independent of the tick length and of gaps
    (a long gap simply weighs the new sample fully).

    Parameters
    ----------
    previous
        Filtered value before this sample; ``None`` on the first sample.
    previous_at
        Monotonic time of the previous update.
    sample
        New raw outside temperature.
    at
        Monotonic time of the sample.
    tau_s
        Time constant in seconds; ``0`` disables filtering.

    Returns
    -------
    float
        The filtered value.
    """
    if previous is None or previous_at is None or tau_s <= 0.0:
        return sample
    dt = at - previous_at
    if dt <= 0.0:
        return previous
    alpha = 1.0 - math.exp(-dt / tau_s)
    return previous + alpha * (sample - previous)

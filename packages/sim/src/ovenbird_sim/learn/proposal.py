"""Curve proposal: the water temperature the house model needs to hold comfort.

At steady state with no sun (night or overcast, the conservative case) and the
model's mean internal gains ``Q_int``, holding the air node at the comfort
temperature ``T_a`` at outside temperature ``T_o`` needs::

    Q   = max(0, UA (T_a - T_o) - Q_int)
    T_w = T_a + Q / K,   K = H_wa + H_wm H_ma / (H_wm + H_ma)

``T_w`` is the loop mean; the water setpoint is the supply ``T_w + Q / (2 m c_p)`` at
the median flow while running (continuous operation; the room feedback trims what
the steady state misses, such as cycling and sun). Values are rounded to 0.5 degC,
kept non-increasing with outside temperature and inside the installation's limits
(minimum setpoint, maximum supply and the safety envelope), each clamp named in
``limited_by``. Points colder than the data reached are flagged ``extrapolated``.
The proposal is a suggestion for the owner: the service turns it into a draft that
goes through the normal validate / preview / apply flow and is never applied by
itself.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from ovenbird_core.derived import WATER_CP_J_PER_KG_K, WATER_DENSITY_KG_PER_L
from ovenbird_sim.model.building import BuildingParams

ROUND_TO_C: Final = 0.5
W_PER_LPM_K: Final = WATER_DENSITY_KG_PER_L * WATER_CP_J_PER_KG_K / 60.0
DEFAULT_FLOW_LPM: Final = 15.0
EXTRAPOLATION_MARGIN_K: Final = 2.0


@dataclass(frozen=True, slots=True)
class CurveLimits:
    """Installation limits a proposed curve must respect.

    Parameters
    ----------
    min_setpoint_c, max_supply_c
        Water range.
    envelope
        Safety envelope curve as ``(outside, water)`` pairs.
    below_k, above_k
        Allowed band around the envelope.
    """

    min_setpoint_c: float
    max_supply_c: float
    envelope: tuple[tuple[float, float], ...] = ()
    below_k: float = math.inf
    above_k: float = math.inf

    def band(self, outside_c: float) -> tuple[float, float]:
        """Return the allowed water range at an outside temperature."""
        lo, hi = self.min_setpoint_c, self.max_supply_c
        if self.envelope:
            centre = interpolate(self.envelope, outside_c)
            lo, hi = max(lo, centre - self.below_k), min(hi, centre + self.above_k)
        return lo, hi


def interpolate(curve: Sequence[tuple[float, float]], outside_c: float) -> float:
    """Piecewise-linear value of a curve, held flat beyond its ends."""
    points = sorted(curve)
    if outside_c <= points[0][0]:
        return points[0][1]
    if outside_c >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in itertools.pairwise(points):
        if x0 <= outside_c <= x1:
            return y0 + (y1 - y0) * (outside_c - x0) / (x1 - x0)
    return points[-1][1]


def steady_state(p: BuildingParams, comfort_c: float, outside_c: float) -> tuple[float, float]:
    """Heat need (W) and loop mean temperature to hold ``comfort_c`` without sun."""
    heat = max(0.0, p.h_air_out * (comfort_c - outside_c) - p.q_int_w)
    k = p.h_water_air + p.h_water_mass * p.h_mass_air / (p.h_water_mass + p.h_mass_air)
    return heat, comfort_c + heat / k


def propose_curve(
    p: BuildingParams,
    comfort_c: float,
    current: Sequence[tuple[float, float]],
    limits: CurveLimits,
    *,
    flow_lpm: float | None = None,
    coldest_c: float | None = None,
) -> dict[str, Any]:
    """Return the proposal object of the insight JSON.

    Parameters
    ----------
    p
        Building parameters of the model.
    comfort_c
        Comfort temperature to hold.
    current
        The current curve (its outside temperatures are the proposal's points).
    limits
        Installation limits.
    flow_lpm
        Median loop flow while running.
    coldest_c
        Coldest outside temperature in the data (points below it are extrapolated).

    Returns
    -------
    dict
        ``curve`` (pairs ready for ``control_curve``), ``points`` with the
        current value, change, heat need and clamps, ``mean_change_k`` and the
        assumptions.
    """
    flow = flow_lpm if flow_lpm is not None and flow_lpm > 0 else DEFAULT_FLOW_LPM
    points = sorted((float(o), float(w)) for o, w in current)
    rows: list[dict[str, Any]] = []
    for outside_c, water_now in points:
        heat, loop = steady_state(p, comfort_c, outside_c)
        supply = loop + heat / (2.0 * flow * W_PER_LPM_K)
        rows.append(
            {
                "outside_c": outside_c,
                "model_c": round(supply, 2),
                "current_c": water_now,
                "heat_w": round(heat),
                "extrapolated": coldest_c is not None
                and outside_c < coldest_c - EXTRAPOLATION_MARGIN_K,
            }
        )
    water = [round(row["model_c"] / ROUND_TO_C) * ROUND_TO_C for row in rows]
    for i in range(len(water) - 2, -1, -1):
        water[i] = max(water[i], water[i + 1])
    for row, value in zip(rows, water, strict=True):
        lo, hi = limits.band(row["outside_c"])
        lo_r = math.ceil(lo / ROUND_TO_C - 1e-9) * ROUND_TO_C
        hi_r = math.floor(hi / ROUND_TO_C + 1e-9) * ROUND_TO_C
        limited = None
        if value < lo_r:
            value, limited = lo_r, _which(limits, row["outside_c"], low=True)
        elif value > hi_r:
            value, limited = hi_r, _which(limits, row["outside_c"], low=False)
        row["water_c"] = value
        row["change_k"] = round(value - row["current_c"], 2)
        row["limited_by"] = limited
    for i in range(len(rows) - 2, -1, -1):
        if rows[i]["water_c"] < rows[i + 1]["water_c"]:
            rows[i]["water_c"] = rows[i + 1]["water_c"]
            rows[i]["change_k"] = round(rows[i]["water_c"] - rows[i]["current_c"], 2)
    changes = [row["change_k"] for row in rows]
    return {
        "comfort_c": comfort_c,
        "flow_lpm": round(flow, 1),
        "based_on_curve": [[o, w] for o, w in points],
        "curve": [[row["outside_c"], row["water_c"]] for row in rows],
        "points": rows,
        "mean_change_k": round(sum(changes) / len(changes), 2) if changes else 0.0,
        "max_change_k": max(changes, key=abs) if changes else 0.0,
        "method": "steady state without sun at the model's mean internal gains; supply at "
        "the median running flow; rounded to 0.5 degC within the installation's limits",
    }


def _which(limits: CurveLimits, outside_c: float, *, low: bool) -> str:
    if not limits.envelope:
        return "min_setpoint" if low else "max_supply"
    centre = interpolate(limits.envelope, outside_c)
    if low:
        return "envelope" if centre - limits.below_k > limits.min_setpoint_c else "min_setpoint"
    return "envelope" if centre + limits.above_k < limits.max_supply_c else "max_supply"

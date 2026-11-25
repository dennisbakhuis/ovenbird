"""Indicative insulation score: heat loss at design conditions per floor area, band A-G.

``heat_loss_w = UA x (DESIGN_INDOOR_C - DESIGN_OUTSIDE_C)`` (20 degC in, -10 degC out)
and ``w_per_m2 = heat_loss_w / floor_area_m2``. ``UA`` is the house model's envelope
conductance: with one room sensor it is an *apparent* value that includes ventilation
and infiltration and sees the house through that sensor. The band follows
:data:`BANDS` (upper limits in W/m2, the last band open-ended). It is indicative and
not the official energielabel, which is an asset rating of the building under
standard use (primary energy per m2 per year), not a measured heat-loss rate.

The service repeats these constants (``ovenbird.insight.house``) because it reads
the learner's JSON without the scientific stack; a test keeps them equal.
"""

from __future__ import annotations

import math
from typing import Any, Final

DESIGN_INDOOR_C: Final = 20.0
DESIGN_OUTSIDE_C: Final = -10.0
BANDS: Final[tuple[tuple[str, float], ...]] = (
    ("A", 30.0),
    ("B", 45.0),
    ("C", 60.0),
    ("D", 80.0),
    ("E", 100.0),
    ("F", 125.0),
    ("G", math.inf),
)
NOTE: Final = (
    "Indicative: heat loss per m2 at 20 degC inside and -10 degC outside from the "
    "apparent heat-loss coefficient (ventilation included). Not the official energielabel."
)


def band(w_per_m2: float) -> str:
    """Return the band letter of a heat loss per m2."""
    for letter, limit in BANDS:
        if w_per_m2 < limit:
            return letter
    return BANDS[-1][0]


def score(
    ua_w_per_k: float,
    ua_interval: tuple[float, float] | None,
    floor_area_m2: float | None,
    *,
    credible: bool,
    needed: str | None = None,
) -> dict[str, Any]:
    """Return the score object of the insight JSON.

    Parameters
    ----------
    ua_w_per_k
        Envelope conductance.
    ua_interval
        Its 90 % interval.
    floor_area_m2
        Heated floor area; ``None`` when not configured.
    credible
        Whether the credibility rules pass (otherwise no number is given).
    needed
        What is still missing when not credible.

    Returns
    -------
    dict
        ``state`` (``ready``, ``learning`` or ``no_floor_area``), the design
        conditions, the bands and, when ready, the heat loss, W/m2, band and intervals.
    """
    delta = DESIGN_INDOOR_C - DESIGN_OUTSIDE_C
    out: dict[str, Any] = {
        "design_indoor_c": DESIGN_INDOOR_C,
        "design_outside_c": DESIGN_OUTSIDE_C,
        "floor_area_m2": floor_area_m2,
        "bands": [
            {"band": letter, "below_w_per_m2": None if math.isinf(limit) else limit}
            for letter, limit in BANDS
        ],
        "indicative": True,
        "note": NOTE,
    }
    if not credible:
        return out | {"state": "learning", "message": needed or "insufficient data"}
    if floor_area_m2 is None or not floor_area_m2 > 0:
        return out | {
            "state": "no_floor_area",
            "heat_loss_w": round(ua_w_per_k * delta),
            "message": "set the heated floor area (house_floor_area_m2) to get W/m2 and a band",
        }
    w_per_m2 = ua_w_per_k * delta / floor_area_m2
    result = out | {
        "state": "ready",
        "heat_loss_w": round(ua_w_per_k * delta),
        "w_per_m2": round(w_per_m2, 1),
        "band": band(w_per_m2),
    }
    if ua_interval is not None:
        lo, hi = (v * delta / floor_area_m2 for v in ua_interval)
        result["interval_90"] = [round(lo, 1), round(hi, 1)]
        result["band_interval"] = [band(lo), band(hi)]
    return result

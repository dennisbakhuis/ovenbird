"""The room series of a model: measured against the free-run 24 h-ahead prediction.

``series-<model>.json`` holds the last ``SERIES_DAYS`` days of the 5 min history at
``SERIES_STEP_S`` resolution. ``room_predicted_24h`` at time ``t`` is what the model
foretold for ``t`` at ``t - 24 h``: the Kalman-filtered state at that origin run free
for 24 h with the *measured* heat, outside temperature and irradiance, exactly the
forecast :func:`ovenbird_sim.identify.validate.horizon_errors` scores. The model used
is the challenger fitted before the held-out block, so a prediction exists only for
origins inside that block (``predicted_from`` says where it starts) and is ``null``
before; the measured room is the raw sensor, also inside known events (a stove fire
shows as the room running above its prediction).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any, Final

import numpy as np

from ovenbird_sim.data.dataset import Dataset
from ovenbird_sim.identify.building import observations
from ovenbird_sim.identify.validate import filtered, inputs
from ovenbird_sim.model.building import BuildingParams, simulate_batch

SERIES_SCHEMA: Final = "ovenbird.house-series/1"
SERIES_DAYS: Final = 14
SERIES_STEP_S: Final = 900
HORIZON_H: Final = 24.0
COLUMNS: Final = ("ts", "room_measured", "room_predicted_24h")
DIGITS: Final = 2


def _number(value: float) -> float | None:
    return round(float(value), DIGITS) if math.isfinite(value) else None


def room_series(
    scored: Dataset,
    raw: Dataset,
    p: BuildingParams,
    held_out_from: float,
    iso: Callable[[float], str],
) -> dict[str, Any]:
    """Return the series object of a model.

    Parameters
    ----------
    scored
        The 5 min dataset the validation scores on (room masked inside events).
    raw
        The same grid with the room observations unmasked.
    p
        The building the predictions come from (the challenger).
    held_out_from
        Start of the held-out block in unix seconds; origins before it are not
        predicted.
    iso
        Function turning unix seconds into the ISO time written to the file.

    Returns
    -------
    dict
        ``schema``, ``step_s``, ``horizon_h``, ``from``, ``to``, ``predicted_from``,
        ``columns`` and ``rows`` (oldest first, ``null`` where a value is missing).
    """
    step = scored.grid.step
    stride = round(SERIES_STEP_S / step)
    ahead = round(HORIZON_H * 3600.0 / step)
    count = SERIES_DAYS * 86400 // SERIES_STEP_S
    last = scored.grid.n - 1
    targets = last - stride * np.arange(count - 1, -1, -1)
    targets = targets[targets >= 0]
    t = scored.t
    _, room_scored = observations(scored)
    _, room_raw = observations(raw)
    origins = targets - ahead
    usable = (origins >= 1) & (t[np.maximum(origins, 0)] >= held_out_from)
    usable &= np.isfinite(room_scored[np.maximum(origins, 0)])
    predicted = np.full(targets.size, np.nan)
    if usable.any():
        states = filtered(scored, p)
        u = inputs(scored, p)
        picked = origins[usable]
        idx = picked[:, None] + np.arange(ahead)[None, :]
        sim = simulate_batch(p, step, states[picked], u[idx])
        predicted[usable] = sim[:, ahead, 2]
    rows = [
        [iso(float(t[j])), _number(room_raw[j]), _number(predicted[k])]
        for k, j in enumerate(targets)
    ]
    first_predicted = next((row[0] for row in rows if row[2] is not None), None)
    return {
        "schema": SERIES_SCHEMA,
        "step_s": SERIES_STEP_S,
        "horizon_h": HORIZON_H,
        "from": rows[0][0] if rows else None,
        "to": rows[-1][0] if rows else None,
        "predicted_from": first_predicted,
        "columns": list(COLUMNS),
        "rows": rows,
    }

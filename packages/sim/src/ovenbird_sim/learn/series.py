"""The room series of a model: measured against the free-run 24 h-ahead prediction.

``series-<model>.json`` holds up to the last ``SERIES_DAYS`` days of the 5 min history
at ``SERIES_STEP_S`` resolution. ``room_predicted_24h`` at time ``t`` is what the model
foretold for ``t`` at ``t - 24 h``: the Kalman-filtered state at that origin run free
for 24 h with the *measured* heat, outside temperature and irradiance, exactly the
forecast :func:`ovenbird_sim.identify.validate.horizon_errors` scores.

Two uses, told apart by ``out_of_sample_from`` (the first origin the model had not
seen when it was fitted):

* a new model (every run): the challenger fitted before the held-out block predicts
  from origins inside that block only, so ``out_of_sample_from`` is the block's start;
* the champion (every run, also when it is kept): its own parameters predict over the
  newest data from every origin; ``out_of_sample_from`` is the end of the data it was
  fitted on, and rows before it are in-sample.

Rows start at the first target with a prediction (no empty first day) unless nothing
can be predicted. The measured room is the raw sensor, also inside known events (a
stove fire shows as the room), but the prediction is ``null`` where its 24 h path
touches an event or its tail (the model knows nothing of the stove heat or of what
made the owner leave a day out), and ``events`` lists the events in reach (at most
:data:`MAX_EVENTS`; ``kind``, ``from``, ``to``, ``tail_to``) so a chart can shade them.
``rmse_k``, ``bias_k`` (predicted minus measured) and ``points`` summarise the
out-of-sample rows with both values: the error of a prediction made one day ahead.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any, Final

import numpy as np

from ovenbird_sim.data import events as ev
from ovenbird_sim.data.dataset import Dataset
from ovenbird_sim.data.series import BoolArray, FloatArray
from ovenbird_sim.identify.building import observations
from ovenbird_sim.identify.validate import filtered, inputs
from ovenbird_sim.model.building import BuildingParams, simulate_batch

SERIES_SCHEMA: Final = "ovenbird.house-series/1"
SERIES_DAYS: Final = 14
SERIES_STEP_S: Final = 900
HORIZON_H: Final = 24.0
COLUMNS: Final = ("ts", "room_measured", "room_predicted_24h")
DIGITS: Final = 2
MAX_EVENTS: Final = 50


def _number(value: float) -> float | None:
    return round(float(value), DIGITS) if math.isfinite(value) else None


def _crossing(t: FloatArray, found: Sequence[ev.Event]) -> BoolArray:
    """Targets whose 24 h prediction path ``[t - 24 h, t]`` overlaps an event or its tail."""
    origin = t - HORIZON_H * 3600.0
    mask = np.zeros(t.size, dtype=np.bool_)
    for event in found:
        mask |= (event.start <= t) & (event.tail_end > origin)
    return mask


def room_series(
    scored: Dataset,
    raw: Dataset,
    p: BuildingParams,
    held_out_from: float,
    iso: Callable[[float], str],
    *,
    out_of_sample_from: float | None = None,
) -> dict[str, Any]:
    """Return the series object of a model.

    Parameters
    ----------
    scored
        The 5 min dataset the validation scores on (room masked inside events).
    raw
        The same grid with the room observations unmasked.
    p
        The building the predictions come from.
    held_out_from
        Origins before this unix time are not predicted (``-inf``: every origin).
    iso
        Function turning unix seconds into the ISO time written to the file.
    out_of_sample_from
        First origin the model had not seen (defaults to ``held_out_from``).

    Returns
    -------
    dict
        ``schema``, ``step_s``, ``horizon_h``, ``from``, ``to``, ``predicted_from``,
        ``out_of_sample_from``, ``columns``, ``rows`` (oldest first, ``null`` where a
        value is missing), ``events``, ``rmse_k``, ``bias_k`` and ``points``.
    """
    unseen = held_out_from if out_of_sample_from is None else out_of_sample_from
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
    safe = np.maximum(origins, 0)
    usable = (origins >= 1) & (t[safe] >= held_out_from) & np.isfinite(room_scored[safe])
    predicted = np.full(targets.size, np.nan)
    if usable.any():
        states = filtered(scored, p)
        u = inputs(scored, p)
        picked = origins[usable]
        idx = picked[:, None] + np.arange(ahead)[None, :]
        sim = simulate_batch(p, step, states[picked], u[idx])
        predicted[usable] = sim[:, ahead, 2]
    target_t = t[targets]
    reach = target_t[0] - HORIZON_H * 3600.0
    found = [e for e in scored.events if e.tail_end > reach and e.start <= target_t[-1]]
    predicted[_crossing(target_t, found)] = np.nan
    has = np.isfinite(predicted)
    if has.any():
        first = int(np.argmax(has))
        targets, predicted, target_t = targets[first:], predicted[first:], target_t[first:]
    measured = room_raw[targets]
    rows = [
        [iso(float(t[j])), _number(measured[k]), _number(predicted[k])]
        for k, j in enumerate(targets)
    ]
    both = (
        np.isfinite(measured) & np.isfinite(predicted) & (target_t - HORIZON_H * 3600.0 >= unseen)
    )
    error = predicted[both] - measured[both]
    first_predicted = next((row[0] for row in rows if row[2] is not None), None)
    return {
        "schema": SERIES_SCHEMA,
        "step_s": SERIES_STEP_S,
        "horizon_h": HORIZON_H,
        "from": rows[0][0] if rows else None,
        "to": rows[-1][0] if rows else None,
        "predicted_from": first_predicted,
        "out_of_sample_from": iso(unseen) if math.isfinite(unseen) else None,
        "columns": list(COLUMNS),
        "rows": rows,
        "events": [
            {
                "kind": e.kind,
                "from": iso(e.start),
                "to": iso(e.end),
                "tail_to": iso(e.tail_end),
            }
            for e in found[-MAX_EVENTS:]
        ],
        "rmse_k": round(float(np.sqrt(np.mean(error**2))), 3) if error.size else None,
        "bias_k": round(float(np.mean(error)), 3) if error.size else None,
        "points": int(error.size),
    }

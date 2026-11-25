"""Term ablation of the ovenbird controller in counterfactual replay (outcome attribution).

Four terms are switched on and off in a full 2⁴ factorial on the point-estimate plant:

``start_ramp``
    the start ramp (off: ``ramp.enabled = False``);
``room_feedback``
    the PI room feedback (off: zero gains and limits, the curve alone);
``dwell``
    the minimum time between setpoint changes and the rounding hysteresis (off:
    no dwell, no hysteresis). The 1 K deadband stays: it is a design floor that
    the configuration cannot remove, so it is part of every variant;
``cycling``
    the cycling protection inside the minimum-run window.

A term's contribution is what the full controller loses without it:
``KPI(all on) - KPI(all on except the term)``. The interactions are the residual
``(all on - all off) - sum of contributions``: zero for purely additive terms. The
factorial main effects (the mean, over the eight settings of the other terms, of
the KPI with the term on minus off) are reported as a second view; in 0/1 coding
they split every two-term interaction equally between its terms.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Final

from ovenbird_core.control.config import OvenbirdConfig, RoomFeedbackConfig

TERMS: Final = ("start_ramp", "room_feedback", "dwell", "cycling")
RESIDUAL: Final = "interactions"

type Combo = tuple[bool, ...]


def combos() -> list[Combo]:
    """All 16 on/off combinations of :data:`TERMS` (all on first)."""
    return [tuple(not x for x in bits) for bits in itertools.product((False, True), repeat=4)]


def label(combo: Combo) -> str:
    """Short label such as ``ramp+fb+dwell-cyc``: ``+`` on, ``-`` off per term."""
    names = ("ramp", "fb", "dwell", "cyc")
    return "".join(("+" if on else "-") + name for name, on in zip(names, combo, strict=True))


def ablated(config: OvenbirdConfig, combo: Combo) -> OvenbirdConfig:
    """Return ``config`` with the terms that are off in ``combo`` disabled.

    Parameters
    ----------
    config
        Full configuration.
    combo
        On/off per term in :data:`TERMS` order.

    Returns
    -------
    OvenbirdConfig
        The ablated configuration.
    """
    ramp_on, feedback_on, dwell_on, cycling_on = combo
    out = config
    if not ramp_on:
        out = replace(out, ramp=replace(out.ramp, enabled=False))
    if not feedback_on:
        out = replace(
            out,
            feedback=RoomFeedbackConfig(kp=0.0, ti_s=0.0, output_limit_k=0.0, integral_limit_k=0.0),
        )
    if not dwell_on:
        out = replace(
            out,
            stages=replace(out.stages, dwell_s=0.0, ramp_dwell_s=0.0, rounding_hysteresis_k=0.0),
        )
    if not cycling_on:
        out = replace(out, cycling=replace(out.cycling, enabled=False))
    return out


def _check(results: Mapping[Combo, float]) -> list[Combo]:
    every = combos()
    missing = [c for c in every if c not in results]
    if missing:
        raise ValueError(f"missing combinations: {[label(c) for c in missing]}")
    return every


def contributions(results: Mapping[Combo, float]) -> dict[str, float]:
    """Return each term's leave-one-out contribution and the interaction residual.

    Parameters
    ----------
    results
        KPI value per combination (all 16).

    Returns
    -------
    dict
        Contribution per term name plus :data:`RESIDUAL`.

    Raises
    ------
    ValueError
        When a combination is missing.
    """
    every = _check(results)
    full = every[0]
    effects: dict[str, float] = {}
    for index, name in enumerate(TERMS):
        without = tuple(on and k != index for k, on in enumerate(full))
        effects[name] = results[full] - results[without]
    total = results[full] - results[every[-1]]
    effects[RESIDUAL] = total - sum(effects[name] for name in TERMS)
    return effects


def main_effects(results: Mapping[Combo, float]) -> dict[str, float]:
    """Return the factorial main effect per term (mean KPI with the term on minus off).

    Raises
    ------
    ValueError
        When a combination is missing.
    """
    every = _check(results)
    effects: dict[str, float] = {}
    for index, name in enumerate(TERMS):
        on = [results[c] for c in every if c[index]]
        off = [results[c] for c in every if not c[index]]
        effects[name] = _mean(on) - _mean(off)
    return effects


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)

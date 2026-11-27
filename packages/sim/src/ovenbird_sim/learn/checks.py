"""What a learner run checks before its model is believed.

Excitation (:func:`excitation`)
    Whether the fit window held enough heating weather for the heat-loss coefficient
    to be learned, on local days with at least 80 % of their minutes usable (room,
    outside, not inside a known event or its tail). A *heating day* is one with a mean
    indoor-outdoor difference of at least 5 K and the heat pump running at least 20 %
    of the time: the loss then dwarfs the unknown gains (at 300 W/K, 5 K is 1.5 kW
    against a few hundred watts of people and appliances) and the measured heat
    carries the information. The window needs 20 heating days (the fewest blocks for
    which the 5th and 95th percentile of the day-block bootstrap mean something), the
    daily outside means of those days must span 10 K (the slope of loss against
    temperature, not its intercept, is the heat-loss coefficient) and the 90 %
    bootstrap interval of the heat-loss coefficient may be at most 30 % of its value
    (about +-15 %). Mean indoor-outdoor difference, the spread of the outside means,
    the run share and the heat per day (days with at least 20 kWh) are reported, not
    required: a kWh threshold depends on the size of the house, the others follow
    from the rules above.

Model credibility (:func:`model_credibility`): three gates, one per use
    *U, heat loss* (:func:`heat_loss_gate`; the insulation score, the curve proposal,
    the what-if steady state and the live balance): the energy signature has enough
    data (30 heating days, 10 K of outside span; :mod:`ovenbird_sim.insight.signature`),
    the fit window is excited, the reported UA range (the envelope of the bootstrap
    interval and the train-window UAs, :func:`ua_range`) is at most 30 % of the UA, the
    RC heat-loss coefficient agrees with the signature's within 20 % (two independent
    estimators, a daily steady-state regression and the dynamic network), and every
    rolling-origin train-window fit gives a UA within 15 % of the full fit's (the UA
    does not depend on which weeks it was learned from). No room-prediction term: the
    room's skill says nothing about the steady-state loss. The old rule of 10 days
    below 5 degC is gone: the cold days are still counted, but a tight and consistent
    heat-loss coefficient is the direct evidence the rule stood in for.

    *D, dynamics* (:func:`dynamics_gate`; the what-if cool-down and the room-target
    planner): the model predicts the room on held-out days better than persistence
    ("it stays as it is") over the planner's default horizon of 6 h, pooled. The 24 h
    skill is reported and never gated.

    *S, sun* (:func:`sun_gate`; the water planner): at least 5 sunny held-out days,
    the sun term improves the 6 h room prediction on sunny hours, and the slope of the
    room's measured sun response on the model's has a 90 % interval overlapping
    0.67-1.5 (:mod:`ovenbird_sim.learn.sun`): a model whose sun response is off by
    more than a factor of 1.5 either way fails.

    ``credible`` is gate U, as before for the score and the proposal.

Skill (:func:`skill_json`)
    Free-run room errors pooled over the first 1, 3, 6, 12 and 24 h from origins every
    3 h on held-out days, against persistence and against diurnal persistence (the
    room as it was 24 h before each target), on the same origins. ``skill`` is
    ``1 - model / persistence``: positive when the model is better. In a room the
    controller holds flat, persistence is strong at 24 h; it cannot say what a change
    of heating would do, which is what the planner asks of the model.

Bounds (:func:`at_bound`)
    Parameters that ended within 2 % of a limit, in the fit's own space: within 2 %
    of the limit's value for the capacities, conductances and the time constant
    (fitted in log space), within 2 % of the parameter's full range for the solar
    and gains parameters. Limits the owner set (bounds, pins, the time-constant
    range) are ``owner``; the model's hard bounds are ``structural`` (a parameter
    there is not identified by the data, or the data want to go beyond physics).
    Parameters the structure holds are never listed, and internal gains at 0 are not
    a bound problem: they are net free heat, not separable from the heat loss, and
    the insight reports them as not identified.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from typing import Any, Final

import numpy as np

from ovenbird_sim.data.dataset import Dataset
from ovenbird_sim.data.series import FloatArray
from ovenbird_sim.identify.building import BOUNDS, LIN_FIELDS, LOG_FIELDS, Priors, observations
from ovenbird_sim.identify.validate import HorizonErrors
from ovenbird_sim.insight.signature import (
    COLD_DAY_C,
    CREDIBLE_DAYS,
    CREDIBLE_SPAN_K,
    HEATING_DAY_W,
    RC_DISAGREEMENT,
    Signature,
)
from ovenbird_sim.learn.sun import (
    ABLATION_HORIZON_H,
    SUNNY_GHI_WM2,
    SUNNY_HOURS,
    SunCheck,
)
from ovenbird_sim.model.building import BuildingParams

MIN_DAY_COVERAGE: Final = 0.8
EXCITED_DELTA_T_K: Final = 5.0
EXCITED_RUN_SHARE: Final = 0.2
EXCITED_DAYS: Final = 20
EXCITED_RANGE_K: Final = 10.0
UA_RELATIVE_WIDTH: Final = 0.30
HEAT_DAY_KWH: Final = 20.0
SKILL_HORIZONS_H: Final = (1.0, 3.0, 6.0, 12.0, 24.0)
SKILL_HORIZON_H: Final = 6.0
MIN_SKILL: Final = 0.0
ORIGIN_EVERY_H: Final = 3.0
DAY_S: Final = 86400.0
BOUND_SHARE: Final = 0.02
PERIODIC: Final = frozenset({"q_int_peak_hour"})
NOT_IDENTIFIED_AT: Final = frozenset({("q_int_w", "lower")})
CONSTRAINT_COST_K: Final = 0.05
CONSTRAINT_COST_SHARE: Final = 0.15
SIGNATURE_MIN_DAYS: Final = 5
UA_STABILITY: Final = 0.15
SUNNY_DAYS: Final = 5
MIN_SUN_SKILL: Final = 0.0
BETA_RANGE: Final = (0.67, 1.5)
GATES: Final = ("heat_loss", "dynamics", "sun")
HEAT_LOSS_USES: Final = ("insulation_score", "curve_proposal", "whatif_steady_state", "balance")
DYNAMICS_USES: Final = ("whatif_cool_down", "room_target_planner")
SUN_USES: Final = ("water_planner",)
NEEDS: Final = frozenset(
    {
        "no_signature",
        "more_heating_days",
        "more_outside_spread",
        "ua_interval_wide",
        "ua_disagrees",
        "ua_unstable",
        "no_dynamics_skill",
        "more_sunny_days",
        "no_sun_skill",
        "sun_response_off",
        "legacy_model",
    }
)
SKILL_24H_NOTE: Final = (
    "reported, not gated: in a room the controller holds at a flat temperature, "
    "'no change' is hard to beat a day ahead"
)


def _round(value: float | None, digits: int = 3) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(float(value), digits)


def day_table(ds: Dataset) -> dict[str, FloatArray]:
    """Return per local day the means the excitation looks at.

    Days with less than :data:`MIN_DAY_COVERAGE` of their bins usable (room and outside
    known, outside any known event or its tail) are left out.

    Returns
    -------
    dict
        ``delta_t_k``, ``outside_c``, ``run_share`` and ``heat_kwh`` per kept day.
    """
    hour = ds.col("local_hour")
    midnight = np.flatnonzero(np.r_[False, np.diff(hour) < -12.0])
    _, room = observations(ds)
    outside = ds.col("outside")
    heat = ds.col("heat_w")
    share = ds.col("compressor_frac")
    event = ds.event_mask()
    rows: list[tuple[float, float, float, float]] = []
    for a, b in itertools.pairwise(int(i) for i in midnight):
        valid = np.isfinite(room[a:b]) & np.isfinite(outside[a:b]) & ~event[a:b]
        if valid.mean() < MIN_DAY_COVERAGE:
            continue
        hours = (b - a) * ds.grid.step / 3600.0
        heat_ok = valid & np.isfinite(heat[a:b])
        share_ok = valid & np.isfinite(share[a:b])
        rows.append(
            (
                float(np.mean(room[a:b][valid] - outside[a:b][valid])),
                float(np.mean(outside[a:b][valid])),
                float(np.mean(share[a:b][share_ok])) if share_ok.any() else math.nan,
                float(np.mean(heat[a:b][heat_ok])) * hours / 1000.0 if heat_ok.any() else math.nan,
            )
        )
    table = np.array(rows, dtype=np.float64).reshape(-1, 4)
    return {
        "delta_t_k": table[:, 0],
        "outside_c": table[:, 1],
        "run_share": table[:, 2],
        "heat_kwh": table[:, 3],
    }


def excitation_rules() -> dict[str, float]:
    """Return the thresholds of the excitation rules (``heat_day_kwh`` is reported only)."""
    return {
        "heating_days": EXCITED_DAYS,
        "delta_t_k": EXCITED_DELTA_T_K,
        "run_share": EXCITED_RUN_SHARE,
        "outside_range_k": EXCITED_RANGE_K,
        "ua_relative_width": UA_RELATIVE_WIDTH,
        "heat_day_kwh": HEAT_DAY_KWH,
    }


def excitation(
    ds: Dataset, ua_w_per_k: float, ua_interval: tuple[float, float] | None
) -> dict[str, Any]:
    """Return the excitation block of a run's insight.

    Parameters
    ----------
    ds
        The fit window (any step dividing a day), events flagged.
    ua_w_per_k
        The fitted heat-loss coefficient.
    ua_interval
        Its 90 % bootstrap interval (``None`` without a bootstrap: not excited).

    Returns
    -------
    dict
        ``excited``, the day counts and means, ``rules``, ``needed`` (``heating_days``,
        ``outside_range_k``), ``ua_tight`` and ``reasons``.
    """
    table = day_table(ds)
    delta = table["delta_t_k"]
    outside = table["outside_c"]
    share = np.nan_to_num(table["run_share"])
    heat = table["heat_kwh"]
    heating = (delta >= EXCITED_DELTA_T_K) & (share >= EXCITED_RUN_SHARE)
    days = int(delta.size)
    heating_days = int(heating.sum())
    span = float(np.ptp(outside[heating])) if heating.any() else 0.0
    width = (
        (ua_interval[1] - ua_interval[0]) / ua_w_per_k
        if ua_interval is not None and ua_w_per_k > 0
        else None
    )
    tight = width is not None and math.isfinite(width) and width <= UA_RELATIVE_WIDTH
    needed = {
        "heating_days": max(0, EXCITED_DAYS - heating_days),
        "outside_range_k": round(max(0.0, EXCITED_RANGE_K - span), 1),
    }
    reasons = []
    if needed["heating_days"]:
        reasons.append(
            f"{heating_days} heating days in the fit window < {EXCITED_DAYS} (at least "
            f"{EXCITED_DELTA_T_K:.0f} K colder outside than inside with the heat pump running "
            f"{EXCITED_RUN_SHARE:.0%} of the day)"
        )
    if needed["outside_range_k"]:
        reasons.append(
            f"daily outside means of the heating days span {span:.1f} K < {EXCITED_RANGE_K:.0f} K"
        )
    if width is None:
        reasons.append("no bootstrap interval of the heat-loss coefficient")
    elif not tight:
        reasons.append(
            f"heat-loss coefficient interval {width:.0%} of its value > {UA_RELATIVE_WIDTH:.0%}"
        )
    finite_heat = heat[np.isfinite(heat)]
    return {
        "excited": not reasons,
        "days": days,
        "heating_days": heating_days,
        "delta_t_days": int(np.sum(delta >= EXCITED_DELTA_T_K)),
        "run_share_days": int(np.sum(share >= EXCITED_RUN_SHARE)),
        "heat_days": int(np.sum(finite_heat >= HEAT_DAY_KWH)),
        "mean_delta_t_k": _round(float(np.mean(delta)) if days else None, 2),
        "mean_run_share": _round(float(np.mean(share)) if days else None, 3),
        "heat_kwh_per_day": _round(float(np.mean(finite_heat)) if finite_heat.size else None, 1),
        "outside_sd_k": _round(float(np.std(outside)) if days else None, 2),
        "outside_range_k": round(span, 2),
        "ua_relative_width": _round(width, 3),
        "ua_tight": tight,
        "rules": excitation_rules(),
        "needed": needed,
        "reasons": reasons,
    }


def skill_at(errors: HorizonErrors, hours: float) -> float:
    """Return ``1 - model / persistence`` at a scored horizon (``NaN`` when undefined)."""
    if hours not in errors.horizons_h:
        return math.nan
    k = errors.horizons_h.index(hours)
    model, reference = errors.room_rmse[k], errors.room_persistence_rmse[k]
    if not (math.isfinite(model) and math.isfinite(reference)) or reference <= 0.0:
        return math.nan
    return 1.0 - model / reference


def diurnal_persistence(
    ds: Dataset,
    start: float,
    end: float,
    *,
    every_h: float = ORIGIN_EVERY_H,
    horizons_h: Sequence[float] = SKILL_HORIZONS_H,
) -> tuple[float, ...]:
    """Room RMSE of "as 24 h before" per horizon, on the origins of ``horizon_errors``.

    The origins are those :func:`ovenbird_sim.identify.validate.horizon_errors` picks
    for the same arguments (every ``every_h`` from ``start``, the longest horizon inside
    ``end``, a room value at the origin), so both baselines share them.
    """
    _, room = observations(ds)
    step = ds.grid.step
    longest = round(max(horizons_h) * 3600.0 / step)
    day = round(DAY_S / step)
    t = ds.t
    first = int(np.searchsorted(t, start))
    last = int(np.searchsorted(t, end)) - longest - 1
    stride = max(round(every_h * 3600.0 / step), 1)
    origins = np.arange(first, max(last, first), stride)
    origins = origins[np.isfinite(room[origins])]
    if origins.size == 0:
        return tuple(math.nan for _ in horizons_h)
    idx = origins[:, None] + np.arange(1, longest + 1)[None, :]
    past = idx - day
    reference = np.where(past >= 0, room[np.maximum(past, 0)], np.nan)
    error = reference - room[idx]
    out = []
    for h in horizons_h:
        n = round(h * 3600.0 / step)
        part = error[:, :n]
        ok = np.isfinite(part)
        out.append(float(np.sqrt(np.mean(part[ok] ** 2))) if ok.any() else math.nan)
    return tuple(out)


def skill_json(errors: HorizonErrors, diurnal: Sequence[float]) -> dict[str, Any]:
    """Return the skill block: errors per horizon against persistence and diurnal persistence."""
    horizons = list(errors.horizons_h)
    skill = [_round(skill_at(errors, h)) for h in horizons]
    diurnal_skill = [
        _round(1.0 - m / d) if math.isfinite(m) and math.isfinite(d) and d > 0 else None
        for m, d in zip(errors.room_rmse, diurnal, strict=True)
    ]
    return {
        "horizons_h": horizons,
        "room_rmse_k": [_round(v) for v in errors.room_rmse],
        "persistence_rmse_k": [_round(v) for v in errors.room_persistence_rmse],
        "diurnal_rmse_k": [_round(v) for v in diurnal],
        "skill": skill,
        "skill_diurnal": diurnal_skill,
        "origins": errors.origins,
    }


def ua_range(
    ua_w_per_k: float,
    bootstrap: tuple[float, float] | None,
    fold_uas: Sequence[float] = (),
) -> tuple[float, float] | None:
    """Return the reported 90 % range of the heat-loss coefficient.

    The envelope of the day-block bootstrap interval and the heat-loss coefficients of
    the rolling-origin train-window fits: on real data the train windows move the UA
    about twice as far as the bootstrap interval says, so the bootstrap alone is too
    narrow. ``None`` without a bootstrap interval.
    """
    if bootstrap is None:
        return None
    values = [bootstrap[0], bootstrap[1], ua_w_per_k]
    values.extend(v for v in fold_uas if math.isfinite(v) and v > 0.0)
    return float(min(values)), float(max(values))


def ua_stability(ua_w_per_k: float, fold_uas: Sequence[float]) -> float | None:
    """Return the largest ``|UA_fold / UA - 1|`` of the train-window fits (``None`` without one)."""
    shifts = [abs(v / ua_w_per_k - 1.0) for v in fold_uas if math.isfinite(v) and ua_w_per_k > 0.0]
    return max(shifts) if shifts else None


def _check(ok: bool, value: float | None, limit: Any, **extra: Any) -> dict[str, Any]:
    return {"ok": bool(ok), "value": _round(value), "limit": limit, **extra}


def _gate(
    ok: bool,
    uses: Sequence[str],
    checks: Mapping[str, Mapping[str, Any]],
    needed: Sequence[str],
    reasons: Sequence[str],
    message: str | None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "ok": bool(ok),
        "uses": list(uses),
        "checks": {name: dict(check) for name, check in checks.items()},
        "needed": list(dict.fromkeys(needed)),
        "reasons": list(reasons),
        "message": None if ok else message,
        **extra,
    }


def heat_loss_gate(
    sig: Signature | None,
    sig_days: int,
    excited: Mapping[str, Any],
    ua_w_per_k: float,
    reported: tuple[float, float] | None,
    fold_uas: Sequence[float],
) -> dict[str, Any]:
    """Return gate U, the heat loss (insulation score, curve proposal, steady state, balance).

    Checks: the energy signature has enough data (:data:`CREDIBLE_DAYS` heating days and
    :data:`CREDIBLE_SPAN_K` of outside span), the fit window is excited
    (:func:`excitation`), the reported UA range (:func:`ua_range`) is at most
    :data:`UA_RELATIVE_WIDTH` of the UA, the signature's UA agrees within
    :data:`RC_DISAGREEMENT` and every rolling-origin train-window UA lies within
    :data:`UA_STABILITY` of the UA.
    """
    heating = 0 if sig is None else sig.heating_days
    span = 0.0 if sig is None else sig.outside_span_k
    agreement = (
        abs(sig.h_w_per_k - ua_w_per_k) / ua_w_per_k if sig is not None and ua_w_per_k > 0 else None
    )
    width = (
        (reported[1] - reported[0]) / ua_w_per_k
        if reported is not None and ua_w_per_k > 0
        else None
    )
    shift = ua_stability(ua_w_per_k, fold_uas)
    exc_needed = excited["needed"]
    checks = {
        "signature": _check(
            sig is not None and sig.credible,
            heating,
            CREDIBLE_DAYS,
            outside_span_k=round(span, 2),
            outside_span_limit_k=CREDIBLE_SPAN_K,
        ),
        "excitation": _check(
            bool(excited["excited"]),
            excited.get("heating_days"),
            EXCITED_DAYS,
            outside_range_k=excited.get("outside_range_k"),
            outside_range_limit_k=EXCITED_RANGE_K,
        ),
        "ua_interval": _check(
            width is not None and math.isfinite(width) and width <= UA_RELATIVE_WIDTH,
            width,
            UA_RELATIVE_WIDTH,
        ),
        "ua_agreement": _check(
            agreement is not None and agreement <= RC_DISAGREEMENT, agreement, RC_DISAGREEMENT
        ),
        "ua_stability": _check(
            shift is not None and shift <= UA_STABILITY,
            shift,
            UA_STABILITY,
            folds=len(fold_uas),
            fold_ua_w_per_k=[round(v, 1) for v in fold_uas if math.isfinite(v)],
        ),
    }
    shortfall = {
        "heating_days": max(CREDIBLE_DAYS - heating, int(exc_needed["heating_days"]), 0),
        "outside_span_k": round(
            max(CREDIBLE_SPAN_K - span, float(exc_needed["outside_range_k"]), 0.0), 1
        ),
    }
    needed: list[str] = []
    reasons: list[str] = []
    if sig is None:
        needed.append("no_signature")
        reasons.append(f"{sig_days} complete days < {SIGNATURE_MIN_DAYS} for a signature")
    else:
        reasons.extend(r for r in sig.reasons if "differ" not in r)
    reasons.extend(excited["reasons"])
    if shortfall["heating_days"]:
        needed.append("more_heating_days")
    if shortfall["outside_span_k"]:
        needed.append("more_outside_spread")
    if not checks["ua_interval"]["ok"]:
        needed.append("ua_interval_wide")
        if width is not None:
            reasons.append(f"heat-loss range {width:.0%} of its value > {UA_RELATIVE_WIDTH:.0%}")
    if agreement is None:
        reasons.append("no signature to cross-check the heat-loss coefficient")
    elif not checks["ua_agreement"]["ok"]:
        needed.append("ua_disagrees")
        reasons.append(
            f"signature and RC heat-loss coefficient differ by {agreement:.0%} "
            f"> {RC_DISAGREEMENT:.0%}"
        )
    if shift is None:
        needed.append("ua_unstable")
        reasons.append("no train-window fit to check the heat-loss coefficient's stability")
    elif not checks["ua_stability"]["ok"]:
        needed.append("ua_unstable")
        reasons.append(
            f"a train-window fit moves the heat-loss coefficient by {shift:.0%} "
            f"> {UA_STABILITY:.0%}"
        )
    if not checks["excitation"]["ok"] and not needed:
        needed.append("ua_interval_wide")
    ok = all(check["ok"] for check in checks.values())
    return _gate(
        ok,
        HEAT_LOSS_USES,
        checks,
        needed,
        reasons,
        heat_loss_message(shortfall, checks),
        shortfall=shortfall,
    )


def heat_loss_message(
    shortfall: Mapping[str, float], checks: Mapping[str, Mapping[str, Any]]
) -> str:
    """Return the one-line explanation of what the heat-loss gate still lacks."""
    parts = []
    if shortfall["heating_days"]:
        parts.append(f"{shortfall['heating_days']:g} more heating days")
    if shortfall["outside_span_k"]:
        parts.append(f"{shortfall['outside_span_k']:g} K more spread in daily outside temperature")
    if parts:
        return "insufficient data: " + ", ".join(parts) + " needed"
    if not checks["excitation"]["ok"] or not checks["ua_interval"]["ok"]:
        return "insufficient data: the heat-loss coefficient is not yet known well enough"
    if not checks["ua_agreement"]["ok"]:
        return "the heat-loss coefficient of the model and of the energy signature disagree"
    if not checks["ua_stability"]["ok"]:
        return "the heat-loss coefficient still moves when the model is fitted on fewer weeks"
    return "insufficient data"


def dynamics_gate(skill: float, skill_24h: float = math.nan) -> dict[str, Any]:
    """Return gate D, the dynamics (what-if cool-down, the room-target planner).

    The model must predict the room better than persistence over the first
    :data:`SKILL_HORIZON_H` hours on held-out days (pooled). The 24 h skill is reported
    and never gated: in a room the controller holds flat, "no change" is hard to beat
    a day ahead.
    """
    ok = math.isfinite(skill) and skill > MIN_SKILL
    reasons = []
    if not ok:
        reasons.append(
            f"the model does not predict the room {SKILL_HORIZON_H:.0f} h ahead better than "
            "persistence on held-out days"
            + (f" (skill {skill:+.2f})" if math.isfinite(skill) else " (no scored origins)")
        )
    return _gate(
        ok,
        DYNAMICS_USES,
        {"skill_6h": _check(ok, skill, MIN_SKILL)},
        [] if ok else ["no_dynamics_skill"],
        reasons,
        f"the model does not yet predict the room {SKILL_HORIZON_H:.0f} h ahead better "
        "than 'no change'",
        diagnostics={"skill_24h": _round(skill_24h), "note": SKILL_24H_NOTE},
    )


def sun_gate(sun: SunCheck | None) -> dict[str, Any]:
    """Return gate S, the sun response (the water planner).

    At least :data:`SUNNY_DAYS` sunny held-out days, a positive ablation skill on sunny
    hours and a sun-response slope whose 90 % interval overlaps :data:`BETA_RANGE`
    (:mod:`ovenbird_sim.learn.sun`).
    """
    days = 0 if sun is None else sun.sunny_days
    skill = math.nan if sun is None else sun.ablation_skill
    beta = math.nan if sun is None else sun.beta
    interval = None if sun is None else sun.beta_interval
    lo, hi = BETA_RANGE
    enough = days >= SUNNY_DAYS
    helps = math.isfinite(skill) and skill > MIN_SUN_SKILL
    right = interval is not None and interval[1] > lo and interval[0] < hi
    checks = {
        "sunny_days": _check(enough, days, SUNNY_DAYS, days=0 if sun is None else sun.days),
        "sun_skill": _check(helps, skill, MIN_SUN_SKILL),
        "sun_response": _check(
            right,
            beta,
            [lo, hi],
            interval=None if interval is None else [_round(v) for v in interval],
            origins=0 if sun is None else sun.origins,
        ),
    }
    needed, reasons = [], []
    if not enough:
        needed.append("more_sunny_days")
        reasons.append(f"{days} sunny held-out days < {SUNNY_DAYS}")
    if not helps:
        needed.append("no_sun_skill")
        reasons.append(
            "on sunny held-out hours the model's sun term does not improve the "
            f"{ABLATION_HORIZON_H:.0f} h room prediction"
        )
    if not right:
        needed.append("sun_response_off")
        reasons.append(
            "the room's response to the sun on held-out days does not match the model's"
            + (
                f" (slope {beta:.2f}, 90 % {interval[0]:.2f}-{interval[1]:.2f}, "
                f"expected to overlap {lo:g}-{hi:g})"
                if interval is not None and math.isfinite(beta)
                else " (no sun response to compare)"
            )
        )
    ok = enough and helps and right
    message = (
        f"{SUNNY_DAYS - days} more sunny days needed to check the model's sun response"
        if not enough
        else "the model's response to the sun does not match the held-out days"
    )
    return _gate(ok, SUN_USES, checks, needed, reasons, message)


def model_credibility(
    sig: Signature | None,
    sig_days: int,
    excited: Mapping[str, Any],
    ua_w_per_k: float,
    skill: float,
    *,
    skill_24h: float = math.nan,
    reported_ua: tuple[float, float] | None = None,
    fold_uas: Sequence[float] = (),
    sun: SunCheck | None = None,
) -> dict[str, Any]:
    """Return the credibility block: the three gates and the heat-loss summary.

    Parameters
    ----------
    sig
        The energy signature (``None`` with fewer than 5 usable days).
    sig_days
        Its usable days.
    excited
        :func:`excitation`.
    ua_w_per_k
        The RC model's heat-loss coefficient.
    skill
        The model's held-out skill over :data:`SKILL_HORIZON_H` against persistence.
    skill_24h
        The same at 24 h (reported only).
    reported_ua
        The reported UA range (:func:`ua_range`).
    fold_uas
        The heat-loss coefficients of the rolling-origin train-window fits.
    sun
        The sun numbers of the held-out block (``None``: not evaluated).

    Returns
    -------
    dict
        ``gates`` (``heat_loss``, ``dynamics``, ``sun``: ``ok``, ``uses``, ``checks``
        with values and limits, ``needed`` codes, ``reasons``, ``message``);
        ``credible`` is gate U (kept for older readers), ``checks`` the old flags plus
        ``ua_stable`` and ``sun``, the signature counts, ``rules``, ``needed``
        (``heating_days``, ``outside_span_k``), ``reasons`` and ``message`` of gate U,
        ``low_confidence``, ``agreement`` and ``skill``.
    """
    heat_loss = heat_loss_gate(sig, sig_days, excited, ua_w_per_k, reported_ua, fold_uas)
    dynamics = dynamics_gate(skill, skill_24h)
    sunny = sun_gate(sun)
    u = heat_loss["checks"]
    checks = {
        "signature": u["signature"]["ok"],
        "excitation": u["excitation"]["ok"],
        "ua_consistent": u["ua_agreement"]["ok"],
        "ua_stable": u["ua_stability"]["ok"],
        "predictive": dynamics["ok"],
        "sun": sunny["ok"],
    }
    credible = bool(heat_loss["ok"])
    return {
        "credible": credible,
        "gates": {"heat_loss": heat_loss, "dynamics": dynamics, "sun": sunny},
        "checks": checks,
        "days": sig_days if sig is None else sig.days,
        "heating_days": 0 if sig is None else sig.heating_days,
        "cold_days": 0 if sig is None else sig.cold_days,
        "outside_span_k": round(0.0 if sig is None else sig.outside_span_k, 2),
        "agreement": u["ua_agreement"]["value"],
        "skill": _round(skill),
        "rules": {
            "heating_days": CREDIBLE_DAYS,
            "heating_day_w": HEATING_DAY_W,
            "outside_span_k": CREDIBLE_SPAN_K,
            "cold_day_below_c": COLD_DAY_C,
            "ua_agreement": RC_DISAGREEMENT,
            "ua_relative_width": UA_RELATIVE_WIDTH,
            "ua_stability": UA_STABILITY,
            "skill_horizon_h": SKILL_HORIZON_H,
            "min_skill": MIN_SKILL,
            "sunny_days": SUNNY_DAYS,
            "sunny_ghi_wm2": SUNNY_GHI_WM2,
            "sunny_hours": SUNNY_HOURS,
            "sun_response": list(BETA_RANGE),
        },
        "needed": heat_loss["shortfall"],
        "reasons": list(heat_loss["reasons"]),
        "low_confidence": False if sig is None else sig.low_confidence,
        "message": heat_loss["message"],
    }


def _near(name: str, value: float, limit: float) -> bool:
    if name in LOG_FIELDS or name == "time_constant_h":
        if value <= 0.0 or limit <= 0.0:
            return False
        return abs(math.log(value / limit)) <= BOUND_SHARE
    lo, hi = BOUNDS[name]
    return abs(value - limit) <= BOUND_SHARE * (hi - lo)


def at_bound(p: BuildingParams, priors: Priors) -> list[dict[str, Any]]:
    """Return the parameters within 2 % (fit space) of an owner limit or a hard bound.

    Returns
    -------
    list
        ``{"parameter", "value", "side", "limit", "kind"}`` with ``side`` ``lower``,
        ``upper`` or ``pinned`` and ``kind`` ``owner`` or ``structural``.
    """
    out: list[dict[str, Any]] = []
    for name in (*LOG_FIELDS, *LIN_FIELDS):
        if name in PERIODIC or name in priors.fixed:
            continue
        value = float(getattr(p, name))
        if name in priors.pinned:
            out.append(_bound_row(name, value, "pinned", priors.pinned[name], "owner"))
            continue
        prior = priors.params[name]
        hard = BOUNDS[name]
        for side, limit, hard_limit in (
            ("lower", prior.lower, hard[0]),
            ("upper", prior.upper, hard[1]),
        ):
            if _near(name, value, limit):
                kind = "structural" if limit == hard_limit else "owner"
                if kind == "structural" and (name, side) in NOT_IDENTIFIED_AT:
                    break
                out.append(_bound_row(name, value, side, limit, kind))
                break
    tau_range = priors.time_constant_h
    if tau_range is not None:
        tau = p.time_constant_h
        lo, hi = tau_range
        if lo == hi:
            out.append(_bound_row("time_constant_h", tau, "pinned", lo, "owner"))
        elif lo > 0.0 and (tau <= lo or _near("time_constant_h", tau, lo)):
            out.append(_bound_row("time_constant_h", tau, "lower", lo, "owner"))
        elif math.isfinite(hi) and (tau >= hi or _near("time_constant_h", tau, hi)):
            out.append(_bound_row("time_constant_h", tau, "upper", hi, "owner"))
    return out


def _bound_row(name: str, value: float, side: str, limit: float, kind: str) -> dict[str, Any]:
    digits = 6 if abs(limit) < 10.0 else 1
    return {
        "parameter": name,
        "value": float(f"{value:.6g}"),
        "side": side,
        "limit": round(limit, digits),
        "kind": kind,
    }


def constraint_cost(constrained_k: float, unconstrained_k: float) -> dict[str, Any]:
    """Compare the held-out error with and without the owner's bounds and pins.

    ``worse`` is true when the constrained error exceeds the unconstrained one by more
    than ``max(0.05 K, 15 %)`` of the unconstrained error.
    """
    if not (math.isfinite(constrained_k) and math.isfinite(unconstrained_k)):
        return {"excess_k": None, "limit_k": None, "worse": False}
    limit = max(CONSTRAINT_COST_K, CONSTRAINT_COST_SHARE * unconstrained_k)
    excess = constrained_k - unconstrained_k
    return {"excess_k": round(excess, 3), "limit_k": round(limit, 3), "worse": excess > limit}

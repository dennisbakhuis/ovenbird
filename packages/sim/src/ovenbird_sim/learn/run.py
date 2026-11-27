"""One learner run: refit, validate, compare with the champion, write the model and insight.

Steps (each timed in the log and in ``status.json``):

1. **Data**: the last ``fit_days`` of 1 min rollups (:mod:`ovenbird_sim.data.historydb`)
   with the configuration's room, reference room and time zone; known events (the
   stove detector and the service's wood-stove journal) are flagged.
2. **Fit**: the full plant identification (:func:`ovenbird_sim.identify.pipeline.
   identify_dataset`: heat pump and building, emitter matching, cycling calibration,
   rolling-origin folds of ``test_days``, day-block bootstrap); when the heat-pump
   layer cannot be fitted on this history (missing signals), the building alone
   with the same folds and bootstrap. Windows overlapping an event are left out.
3. **Scoring**: the challenger is the latest fold's train-only building (fitted
   before the latest ``test_days``); its free-run room errors over the first 1, 3, 6,
   12 and 24 h from origins every 3 h on those days (events masked) are compared with
   persistence and diurnal persistence on the same origins
   (:mod:`ovenbird_sim.learn.checks`). The champion is re-scored every run on the
   held-out days it has not seen either (from the end of its own data, when that
   leaves at least ``MIN_COMPARE_ORIGINS`` origins; else on the whole block, marked
   ``champion_in_sample``); that re-validation recomputes all three gates for the
   champion (heat loss: its frozen checks with the UA agreement against this run's
   signature; dynamics and sun on the compared days) and goes to ``status.json`` as
   ``champion_revalidation``.
4. **Insight**: the energy signature over the whole 15 min history (kept forever;
   event days left out), the excitation of the fit window, the reported UA range (the
   envelope of the bootstrap interval and the train-window UAs of the folds) and the
   three credibility gates (:func:`ovenbird_sim.learn.checks.model_credibility`: heat
   loss, dynamics, sun; the sun numbers from :mod:`ovenbird_sim.learn.sun` on the
   held-out block), the insulation score (:mod:`ovenbird_sim.learn.score`, on the
   heat-loss gate and the reported range), the curve proposal
   (:mod:`ovenbird_sim.learn.proposal`) and the parameters at a limit. With bounds or
   pins set by the owner, the train split is fitted once more without them (facts
   kept, no bootstrap) and scored on the same held-out block.
5. **Promotion** (:func:`decide_promotion`, in this order; "credible" is the heat-loss
   gate U): no finite challenger error keeps the champion; no champion promotes; a
   credible challenger replaces a champion that is not credible (as re-validated); a
   challenger that is not credible never replaces a credible champion, not even after
   a change of the house settings; a challenger that fails the dynamics or the sun gate
   the champion passes on the same compared days never replaces it either (a champion
   does not lose D or S silently); changed house settings (facts or bounds) promote
   otherwise, whatever the error (the owner's intent; both errors kept); a refit on at
   least a day of newer data whose
   heat-loss coefficient and time constant lie inside the champion's 90 % intervals
   is the same house and is promoted (the challenger's error comes from its train-only
   fit, which has seen less recent data than the champion, so the error comparison
   leans towards the champion); else the challenger is promoted when its error is at
   most the champion's plus ``tolerance_k``. Both errors cover the same days.
6. **Series**: the new model's room series, and the champion's on the newest data
   (rewritten every run, also when it is kept), with the events marked
   (:mod:`ovenbird_sim.learn.series`).

The ``house_*`` settings of the configuration (:mod:`ovenbird_sim.learn.priors`)
add weak priors from the owner's facts, bounds and pins on four learned quantities,
the learning options and the days the owner left out (masked like wood-stove
periods in the fit, the scoring and the signature). Invalid settings stop the run
before the fit (outcome ``failed``, the error names the setting).

Runtime is bounded by ``fit_days``, the folds, the bootstrap replicates and the
optimisers' evaluation budgets; results are deterministic for a given database,
configuration and seed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

import numpy as np

from ovenbird_core.control import OvenbirdConfig
from ovenbird_sim.data import events as ev
from ovenbird_sim.data.dataset import Dataset
from ovenbird_sim.data.historydb import (
    MINUTE,
    QUARTER,
    HistoryData,
    HistoryRoles,
    connect,
    history_dataset,
    roles_from_config,
    rollup_span,
)
from ovenbird_sim.data.series import Series
from ovenbird_sim.identify import io
from ovenbird_sim.identify.building import (
    BOUNDS,
    DEFAULT_PRIORS,
    FitConfig,
    Priors,
    bootstrap_building,
    derived_value,
    emitter_time_constant_h,
    fit_building,
    make_windows,
)
from ovenbird_sim.identify.pipeline import (
    INTERVAL_FIELDS,
    IdentifyOptions,
    fold_splits,
    identify_dataset,
)
from ovenbird_sim.identify.validate import HorizonErrors, horizon_errors
from ovenbird_sim.insight.signature import RC_DISAGREEMENT, Signature, daily, energy_signature
from ovenbird_sim.learn import models as store
from ovenbird_sim.learn.checks import (
    GATES,
    HEAT_LOSS_USES,
    SIGNATURE_MIN_DAYS,
    SKILL_HORIZON_H,
    SKILL_HORIZONS_H,
    at_bound,
    constraint_cost,
    diurnal_persistence,
    dynamics_gate,
    excitation,
    model_credibility,
    skill_at,
    skill_json,
    sun_gate,
    ua_range,
)
from ovenbird_sim.learn.priors import (
    MIN_TRAIN_DAYS,
    HouseSettings,
    LearnSettings,
    SettingError,
    house_settings,
    told_json,
    unconstrained,
)
from ovenbird_sim.learn.proposal import CurveLimits, propose_curve
from ovenbird_sim.learn.score import DESIGN_OUTSIDE_C, score
from ovenbird_sim.learn.series import room_series
from ovenbird_sim.learn.sun import SunCheck, SunEvaluator
from ovenbird_sim.model.building import J_PER_KWH, BuildingParams
from ovenbird_sim.model.heatpump import HeatPumpParams
from ovenbird_sim.model.plant import PlantParams

LOGGER = logging.getLogger("ovenbird_sim.learn")
DAY_S: Final = 86400.0
SCORE_HORIZON_H: Final = 24.0
MIN_COMPARE_ORIGINS: Final = 16
NEWER_DATA_S: Final = DAY_S
SAME_HOUSE_FIELDS: Final = ("h_air_out", "time_constant_h")
WARNING_NOTES: Final = ("stove_journal",)
LEGACY_REASON: Final = (
    "the model was fitted before the credibility gates and its credibility did not pass"
)
INDOOR: Final = "house_mean"
LIMITS: Final = (
    "single room sensor: the UA is apparent (ventilation and infiltration included, the "
    "house as the room sensor sees it)",
    "weather: forecast temperature and global horizontal irradiance only; the solar "
    "aperture is an effective GHI aperture without orientation",
    "wood-stove periods and their recovery tail are left out of the fit, the scoring "
    "and the signature, and so are the days the owner left out (without a tail)",
    "house facts are weak priors the data can overrule; bounds and pins are kept",
    "the proposal is a steady-state estimate without sun; the room feedback trims it",
)


@dataclass(frozen=True, slots=True)
class LearnOptions:
    """Learner options.

    Parameters
    ----------
    floor_area_m2
        Heated floor area; overrides ``house_floor_area_m2`` of the configuration.
    fit_days
        Days of 1 min history used for the identification (the latest ones);
        ``house_learn_fit_days`` replaces it unless it is in ``explicit``.
    test_days
        Held-out block of the champion/challenger comparison
        (``house_learn_test_days`` likewise).
    folds
        Rolling-origin folds (fewer when the history is short).
    bootstrap
        Day-block bootstrap replicates of the building fit.
    signature_replicates
        Bootstrap replicates of the energy signature.
    seed
        Random seed.
    tolerance_k
        Promote when the challenger's error is at most the champion's plus this
        (``house_learn_tolerance_k`` likewise).
    weather
        Weather series replacing the stored forecasts (an Open-Meteo cache).
    full_plant
        Try the full plant identification (heat pump included) first.
    interval_h
        Hours between runs when the learner repeats (``--every-h``), written to
        ``status.json`` so the service can tell a learner that stopped running.
    explicit
        Fields given explicitly (command-line flags): they win over the
        configuration's ``house_learn_*`` settings.
    """

    floor_area_m2: float | None = None
    fit_days: float = 60.0
    test_days: int = 14
    folds: int = 2
    bootstrap: int = 20
    signature_replicates: int = 200
    seed: int = 0
    tolerance_k: float = 0.0
    weather: Mapping[str, Series] | None = None
    full_plant: bool = True
    interval_h: float | None = None
    explicit: frozenset[str] = frozenset()


DEFAULT_LEARN: Final = LearnOptions()


@dataclass(frozen=True, slots=True)
class FitOutcome:
    """The building (and plant) fit of one run, whichever path produced it.

    Parameters
    ----------
    method
        ``full_plant`` or ``building_only``.
    building
        Final building parameters (all data).
    intervals
        90 % bootstrap intervals of the building parameters.
    plant
        Full plant parameters when the heat pump was fitted.
    split, end
        Latest test block.
    train_building
        Building fitted before ``split`` only (the challenger).
    folds
        Per fold: split, test end, train-only room RMSE, heat-loss coefficient and
        time constant, and held-out horizons.
    fit_rmse_room_k, windows
        Final fit diagnostics.
    report
        The identification report (full plant only).
    fallback_reason
        Why the full plant path was not used.
    priors
        Priors and structure of the fits (``None``: the module defaults).
    """

    method: str
    building: BuildingParams
    intervals: dict[str, tuple[float, float]]
    plant: PlantParams | None
    split: float
    end: float
    train_building: BuildingParams
    folds: list[dict[str, Any]]
    fit_rmse_room_k: float
    windows: int
    report: dict[str, Any] = field(default_factory=dict)
    fallback_reason: str | None = None
    priors: Priors | None = None

    @property
    def fold_uas(self) -> tuple[float, ...]:
        """The heat-loss coefficients of the rolling-origin train-window fits."""
        return tuple(
            float(fold["ua_w_per_k"])
            for fold in self.folds
            if isinstance(fold.get("ua_w_per_k"), int | float)
        )


class NotReadyError(Exception):
    """The history cannot support a fit yet; ``missing`` says what is needed."""

    def __init__(self, missing: list[str]) -> None:
        super().__init__("; ".join(missing))
        self.missing = missing


def iso(ts: float) -> str:
    """UTC ISO time of a unix time."""
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")


def config_hash(config: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON of the configuration (first 16 hex digits)."""
    text = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def code_version() -> str:
    """Installed version of ``ovenbird-sim``."""
    try:
        return metadata.version("ovenbird-sim")
    except metadata.PackageNotFoundError:
        return "unknown"


def _pairs(value: Any) -> tuple[tuple[float, float], ...] | None:
    if not isinstance(value, list | tuple) or len(value) < 2:
        return None
    try:
        return tuple((float(p[0]), float(p[1])) for p in value)
    except TypeError, ValueError, IndexError:
        return None


def curve_settings(
    config: Mapping[str, Any],
) -> tuple[float, tuple[tuple[float, float], ...], CurveLimits]:
    """Comfort, current curve and limits from the configuration (emitter presets filled in)."""
    preset = OvenbirdConfig.preset(str(config.get("control_emitter") or "mixed"))
    safety = preset.safety

    def number(name: str, default: float) -> float:
        value = config.get(name)
        return float(value) if isinstance(value, int | float) else default

    curve = _pairs(config.get("control_curve")) or tuple(
        (p.outside_c, p.water_c) for p in preset.curve.points
    )
    envelope = _pairs(config.get("control_envelope_curve")) or tuple(
        (p.outside_c, p.water_c) for p in safety.envelope.points
    )
    limits = CurveLimits(
        min_setpoint_c=number("control_min_setpoint_c", safety.min_setpoint_c),
        max_supply_c=number("control_max_supply_c", safety.max_supply_c),
        envelope=envelope,
        below_k=number("control_envelope_below_k", safety.envelope_below_k),
        above_k=number("control_envelope_above_k", safety.envelope_above_k),
    )
    return number("control_comfort_c", 21.0), curve, limits


SETTINGS_CHANGED: Final = "promoted because the house settings changed"


def decide_promotion(
    challenger_k: float,
    champion_k: float | None,
    tolerance_k: float = 0.0,
    *,
    settings_changed: bool = False,
    challenger_credible: bool | None = None,
    champion_credible: bool | None = None,
    same_house: str | None = None,
    challenger_gates: Mapping[str, bool] | None = None,
    champion_gates: Mapping[str, bool] | None = None,
) -> tuple[bool, str]:
    """Apply the promotion rule to the held-out room errors.

    The rules, in order: no finite challenger error keeps the champion; no champion
    (or none scored on these days) promotes; a credible challenger replaces a champion
    that is not credible; a challenger that is not credible never replaces a credible
    champion (also when the settings changed); a challenger that fails the dynamics or
    the sun gate the champion passes on the same days never replaces it (also when the
    settings changed); changed settings promote; the same house on newer data promotes
    (``same_house``); else the challenger is promoted when its error is at most the
    champion's plus ``tolerance_k``. "Credible" is the heat-loss gate U.

    The challenger's error is that of its train-only fit, which has seen less recent
    data than the champion, so the error comparison leans towards the champion; a
    refit whose heat-loss coefficient and time constant lie inside the champion's
    90 % intervals describes the same house and takes over, so the model keeps
    tracking the house.

    Parameters
    ----------
    challenger_k
        The new model's free-run room RMSE at 24 h on the compared held-out days.
    champion_k
        The champion's on the same days; ``None`` without a champion.
    tolerance_k
        Allowed excess of the challenger (the owner's ``house_learn_tolerance_k``).
    settings_changed
        The owner's house facts or bounds differ from the champion's.
    challenger_credible, champion_credible
        Heat-loss gate of each (``None``: unknown, the credibility rules are skipped).
    same_house
        Why the new model is the champion's house on at least a day of newer data (its
        heat-loss coefficient and time constant inside the champion's 90 % intervals),
        ``None`` when it is not.
    challenger_gates, champion_gates
        ``dynamics`` and ``sun`` of each on the compared days (``None``: unknown, the
        rule is skipped).

    Returns
    -------
    tuple
        Whether to promote, and the rule as applied (for the report).
    """
    if not math.isfinite(challenger_k):
        return False, "the challenger has no held-out error (no scored origins)"
    if champion_k is None or not math.isfinite(champion_k):
        if settings_changed:
            return True, f"{SETTINGS_CHANGED} (challenger {challenger_k:.3f} K, champion none)"
        return True, "no champion yet"
    errors = (
        f"challenger {challenger_k:.3f} K, champion {champion_k:.3f} K on the same held-out "
        "days, room, 24 h"
    )
    if challenger_credible is True and champion_credible is False:
        return True, f"a credible model replaces one that is not ({errors})"
    if challenger_credible is False and champion_credible is True:
        why = " although the house settings changed" if settings_changed else ""
        return False, f"kept: the new model is not credible and the champion is{why} ({errors})"
    lost = lost_gates(challenger_gates, champion_gates)
    if lost:
        why = " although the house settings changed" if settings_changed else ""
        return False, (
            f"kept: the new model does not pass the {' and '.join(lost)} gate the champion "
            f"passes on the same days{why} ({errors})"
        )
    if settings_changed:
        return True, f"{SETTINGS_CHANGED} ({errors})"
    if same_house is not None:
        return True, f"the same house on newer data: {same_house} ({errors})"
    promote = challenger_k <= champion_k + tolerance_k
    return promote, (
        f"challenger {challenger_k:.3f} K {'<=' if promote else '>'} champion "
        f"{champion_k:.3f} K + {tolerance_k:.2f} K (room, 24 h, held out)"
    )


KEPT_GATES: Final = ("dynamics", "sun")


def lost_gates(
    challenger: Mapping[str, bool] | None, champion: Mapping[str, bool] | None
) -> list[str]:
    """Return the dynamics and sun gates the champion passes and the challenger fails."""
    if challenger is None or champion is None:
        return []
    return [g for g in KEPT_GATES if champion.get(g) is True and challenger.get(g) is False]


def _horizon(errors: HorizonErrors, hours: float = SCORE_HORIZON_H) -> float:
    if hours not in errors.horizons_h:
        return math.nan
    return float(errors.room_rmse[errors.horizons_h.index(hours)])


def _persistence(errors: HorizonErrors, hours: float = SCORE_HORIZON_H) -> float:
    if hours not in errors.horizons_h:
        return math.nan
    return float(errors.room_persistence_rmse[errors.horizons_h.index(hours)])


def _horizons_json(errors: HorizonErrors) -> dict[str, Any]:
    return {
        "horizons_h": list(errors.horizons_h),
        "room_rmse_k": list(errors.room_rmse),
        "room_persistence_rmse_k": list(errors.room_persistence_rmse),
        "outlet_rmse_k": list(errors.outlet_rmse),
        "origins": errors.origins,
    }


def scoring_view(coarse: Dataset) -> Dataset:
    """Dataset with the room observations masked inside known events (for scoring)."""
    event = coarse.event_mask()
    if not event.any():
        return coarse
    columns = dict(coarse.columns)
    for name in ("room", "room_living"):
        if name in columns:
            columns[name] = np.where(event, np.nan, columns[name])
    return replace(coarse, columns=columns)


def _intervals(boot_samples: tuple[BuildingParams, ...]) -> dict[str, tuple[float, float]]:
    if not boot_samples:
        return {}
    out = {}
    for name in INTERVAL_FIELDS:
        values = np.array([derived_value(p, name) for p in boot_samples])
        lo, hi = np.percentile(values, [5.0, 95.0])
        out[name] = (float(lo), float(hi))
    return out


def fit_building_only(ds: Dataset, options: IdentifyOptions) -> FitOutcome:
    """Fit the building with the pipeline's folds and bootstrap, without the heat-pump layer.

    Every fit (folds, final, bootstrap replicates) uses ``options.priors``.
    """
    coarse = ds.coarsen(5)
    config = FitConfig()
    priors = options.priors
    folds: list[dict[str, Any]] = []
    first: tuple[float, float, BuildingParams] | None = None
    for split, end in fold_splits(ds, options):
        train = fit_building(make_windows(coarse, config, end=split), config, priors=priors)
        held = horizon_errors(coarse, train.params, split, end)
        folds.append(
            {
                "split": iso(split),
                "test_end": iso(end),
                "train_room_rmse_k": train.rmse_room,
                "ua_w_per_k": train.params.h_air_out,
                "time_constant_h": train.params.time_constant_h,
                "windows": train.n_windows,
                "held_out": _horizons_json(held),
            }
        )
        if first is None:
            first = (split, end, train.params)
    if first is None:
        raise ValueError("no validation fold")
    windows = make_windows(coarse, config)
    final = fit_building(windows, config, start=first[2], priors=priors)
    boot = (
        bootstrap_building(windows, final, options.bootstrap, config, options.seed, priors)
        if options.bootstrap > 0
        else None
    )
    return FitOutcome(
        method="building_only",
        building=final.params,
        intervals=_intervals(boot.samples) if boot is not None else {},
        plant=None,
        split=first[0],
        end=first[1],
        train_building=first[2],
        folds=folds,
        fit_rmse_room_k=final.rmse_room,
        windows=final.n_windows,
        priors=priors,
    )


def fit_full_plant(ds: Dataset, history: HistoryData, options: IdentifyOptions) -> FitOutcome:
    """Full plant identification on the history dataset."""
    result = identify_dataset(ds, history.base, options)
    latest = result.folds[0]
    folds = [
        {
            "split": iso(fold.split),
            "test_end": iso(fold.end),
            "train_room_rmse_k": fold.building.rmse_room,
            "ua_w_per_k": fold.params.building.h_air_out,
            "time_constant_h": fold.params.building.time_constant_h,
            "windows": fold.building.n_windows,
            "held_out": _horizons_json(fold.horizons),
        }
        for fold in result.folds
    ]
    report = result.to_json()
    report.pop("data", None)
    return FitOutcome(
        method="full_plant",
        building=result.params.building,
        intervals=result.building_intervals,
        plant=result.params,
        split=latest.split,
        end=latest.end,
        train_building=latest.params.building,
        folds=folds,
        fit_rmse_room_k=result.building.rmse_room,
        windows=result.building.n_windows,
        report=report,
        priors=options.priors,
    )


def _fit(ds: Dataset, history: HistoryData, options: IdentifyOptions, full: bool) -> FitOutcome:
    if full:
        try:
            return fit_full_plant(ds, history, options)
        except Exception as exc:
            LOGGER.warning("full plant identification failed (%s); fitting the building only", exc)
            reason = f"{type(exc).__name__}: {exc}"
            return replace(fit_building_only(ds, options), fallback_reason=reason)
    return fit_building_only(ds, options)


def _readiness(ds: Dataset, options: LearnOptions) -> list[str]:
    missing = []
    days = (ds.grid.end - ds.grid.start) / DAY_S
    need = options.test_days + MIN_TRAIN_DAYS
    if days < need:
        missing.append(
            f"{math.ceil(need - days)} more days of 1 min history "
            f"(have {days:.1f}, the fit needs {need})"
        )
    room = np.isfinite(ds.col("room")).mean()
    if room < 0.5:
        missing.append(f"room temperature history (only {room:.0%} of the span)")
    heat = np.isfinite(ds.col("heat_w")).mean()
    if heat < 0.5:
        missing.append(f"loop heat history (only {heat:.0%} of the span)")
    return missing


@dataclass(frozen=True, slots=True)
class _Champion:
    """The champion as the learner reads it back: building, data end, frozen credibility."""

    name: str
    building: BuildingParams
    data_to: float | None
    credible: bool
    intervals: Mapping[str, tuple[float, float]] = field(default_factory=dict)
    heat_loss: Mapping[str, Any] | None = None
    needed: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _Scores:
    """The held-out errors of one run: the challenger's, the champion's, the baselines'."""

    coarse: Dataset
    challenger: HorizonErrors
    diurnal: tuple[float, ...]
    champ: dict[str, Any] | None
    champion: _Champion | None
    compared_from: float
    compared_challenger: HorizonErrors
    compared_champion: HorizonErrors | None
    champion_in_sample: bool
    settings_changed: bool


def _signature(
    history: Path,
    roles: HistoryRoles,
    weather: Mapping[str, Series] | None,
    ua: float,
    options: LearnOptions,
    owner_days: tuple[ev.Event, ...] = (),
) -> tuple[Signature | None, int, list[str], dict[str, Any]]:
    data = history_dataset(history, roles, step=QUARTER, weather=weather, excluded=owner_days)
    ds = data.dataset
    event = ds.event_mask()
    columns = dict(ds.columns)
    columns["heat_w"] = np.where(event, np.nan, columns["heat_w"])
    days = daily(replace(ds, columns=columns), INDOOR)
    excluded = list(ev.days_touched(ds.events))
    if days.n < SIGNATURE_MIN_DAYS:
        return None, days.n, excluded, {"days": days, "notes": data.notes}
    sig = energy_signature(
        days,
        indoor=INDOOR,
        rc_h_w_per_k=ua,
        design_c=DESIGN_OUTSIDE_C,
        replicates=options.signature_replicates,
        seed=options.seed,
    )
    return sig, days.n, excluded, {"days": days, "notes": data.notes}


def _signature_json(sig: Signature | None, extra: Mapping[str, Any], tz: str) -> dict[str, Any]:
    days = extra["days"]
    points = [
        {
            "date": datetime.fromtimestamp(float(days.day_start[i]), ZoneInfo(tz))
            .date()
            .isoformat(),
            "outside_c": round(float(days.outside_c[i]), 2),
            "heat_w": round(float(days.heat_w[i]), 1),
            "indoor_c": round(float(days.indoor_c[i]), 2),
            "ghi_w_m2": round(float(days.ghi_w_m2[i]), 1),
        }
        for i in range(days.n)
    ]
    fit = None
    if sig is not None:
        fit = {
            "h_w_per_k": sig.h_w_per_k,
            "h_interval_90": list(sig.h_interval),
            "gains_w": sig.gains_w,
            "solar_m2": sig.solar_m2,
            "balance_c": sig.balance_c,
            "balance_interval_90": list(sig.balance_interval),
            "rmse_w": sig.rmse_w,
            "mean_indoor_c": float(np.mean(days.indoor_c)) if days.n else None,
            "mean_ghi_w_m2": float(np.mean(days.ghi_w_m2)) if days.n else None,
            "model": "Q = max(0, H (T_in - T_o) - A I - G + C dT_in/dt), daily means",
        }
    return {"indoor": INDOOR, "points": points, "fit": fit}


def _daily_errors(
    coarse: Dataset, p: BuildingParams, split: float, end: float
) -> list[dict[str, Any]]:
    out = []
    day = split
    while day + DAY_S <= end:
        errors = horizon_errors(coarse, p, day, day + DAY_S + SCORE_HORIZON_H * 3600.0 + 600.0)
        out.append(
            {"date": iso(day)[:10], "room_rmse_24h_k": _horizon(errors), "origins": errors.origins}
        )
        day += DAY_S
    return out


def _value(p: BuildingParams, name: str) -> float:
    return derived_value(p, name)


def _with_interval(
    p: BuildingParams, intervals: Mapping[str, tuple[float, float]], name: str, digits: int = 1
) -> dict[str, Any]:
    lo_hi = intervals.get(name)
    return {
        "value": round(_value(p, name), digits),
        "interval_90": None
        if lo_hi is None
        else [round(lo_hi[0], digits), round(lo_hi[1], digits)],
    }


@dataclass
class Timer:
    """Stage timings for the log and the status file."""

    stages: dict[str, float] = field(default_factory=dict)
    clock: Callable[[], float] = time.perf_counter

    def run[T](self, name: str, fn: Callable[[], T]) -> T:
        """Run ``fn`` and record its duration under ``name``."""
        began = self.clock()
        try:
            return fn()
        finally:
            self.stages[name] = round(self.clock() - began, 2)
            LOGGER.info("%s: %.1f s", name, self.stages[name])


def learn(
    history: Path,
    config: Mapping[str, Any],
    models: Path,
    options: LearnOptions = DEFAULT_LEARN,
) -> dict[str, Any]:
    """Run the learner once and write its files (see :mod:`ovenbird_sim.learn.models`).

    Parameters
    ----------
    history
        ``history.snapshot.db`` (or a closed ``history.db``).
    config
        Effective configuration (``control_*`` fields, ``house_floor_area_m2``).
    models
        Models directory.
    options
        Learner options.

    Returns
    -------
    dict
        The status written to ``status.json`` (outcome ``promoted``,
        ``kept_champion``, ``learning`` or ``failed``; ``failed`` with the setting
        named when a ``house_*`` setting is invalid).
    """
    began = time.perf_counter()
    timer = Timer()
    roles = roles_from_config(config)
    run_at = datetime.now(UTC).isoformat(timespec="seconds")
    status: dict[str, Any] = {
        "at": run_at,
        "history": str(history),
        "code_version": code_version(),
        "interval_h": options.interval_h,
    }
    try:
        settings = house_settings(config)
        options = apply_learning(options, settings.learning)
        outcome = _learn(history, config, models, options, roles, timer, status, settings)
    except SettingError as exc:
        LOGGER.error("invalid house settings: %s", exc)
        outcome = {
            "outcome": "failed",
            "error": f"invalid house settings: {exc}",
            "setting": exc.setting,
        }
    except NotReadyError as exc:
        LOGGER.warning("not ready: %s", exc)
        outcome = {"outcome": "learning", "missing": exc.missing}
    except Exception as exc:
        LOGGER.exception("learner run failed")
        outcome = {"outcome": "failed", "error": f"{type(exc).__name__}: {exc}"}
    status |= outcome
    status["stages_s"] = timer.stages
    status["runtime_s"] = round(time.perf_counter() - began, 1)
    store.write_status(models, status)
    LOGGER.info("learner %s in %.1f s", status["outcome"], status["runtime_s"])
    return status


def apply_learning(options: LearnOptions, learning: LearnSettings) -> LearnOptions:
    """Return ``options`` with the configuration's learning options where they are set.

    Fields named in ``options.explicit`` keep their value.
    """
    changes: dict[str, Any] = {
        name: value
        for name, value in (
            ("fit_days", learning.fit_days),
            ("test_days", learning.test_days),
            ("tolerance_k", learning.tolerance_k),
        )
        if value is not None and name not in options.explicit
    }
    return replace(options, **changes) if changes else options


@dataclass(frozen=True, slots=True)
class _Loaded:
    """The history of one run: the 1 min dataset, its span in days and the folds."""

    data: HistoryData
    ds: Dataset
    days: float
    folds: int


@dataclass(frozen=True, slots=True)
class _Verdict:
    """The promotion decision of a run and the champion's re-validation."""

    scores: _Scores
    challenger_err: float
    champion_err: float | None
    challenger_credible: bool
    champion_credible: bool | None
    same_house: str | None
    promote: bool
    rule: str
    challenger_gates: dict[str, bool] = field(default_factory=dict)
    champion_gates: dict[str, Any] | None = None

    @property
    def coarse(self) -> Dataset:
        """The 5 min scoring view (room masked inside events)."""
        return self.scores.coarse

    @property
    def settings_changed(self) -> bool:
        """Whether the owner's house settings differ from the champion's."""
        return self.scores.settings_changed

    @property
    def champion_name(self) -> Any:
        """The champion's model name (``None`` without a champion)."""
        champ = self.scores.champ
        return None if champ is None else champ.get("model")


@dataclass(frozen=True, slots=True)
class _House:
    """The energy signature, excitation, credibility, score and curve proposal of one run."""

    sig: Signature | None
    sig_days: int
    excluded_days: list[str]
    sig_extra: dict[str, Any]
    excitation: dict[str, Any]
    credibility: dict[str, Any]
    ua_interval: tuple[float, float] | None
    score: dict[str, Any]
    proposal: dict[str, Any]
    ua_bootstrap: tuple[float, float] | None = None
    sun: SunEvaluator | None = None

    @property
    def gates(self) -> dict[str, bool]:
        """Whether each gate passes."""
        return gate_flags(self.credibility)


def _learn(
    history: Path,
    config: Mapping[str, Any],
    models: Path,
    options: LearnOptions,
    roles: HistoryRoles,
    timer: Timer,
    status: dict[str, Any],
    settings: HouseSettings,
) -> dict[str, Any]:
    excluded = ev.excluded_days(settings.learning.excluded_days, roles.timezone)
    loaded = _load(history, options, roles, timer, excluded)
    ds = loaded.ds
    id_options = IdentifyOptions(
        test_days=options.test_days,
        bootstrap=options.bootstrap,
        seed=options.seed,
        folds=loaded.folds,
        priors=settings.priors,
    )
    fit = timer.run("fit", lambda: _fit(ds, loaded.data, id_options, options.full_plant))
    scores = timer.run("scoring", lambda: _score(ds, fit, models, settings.constraints))
    house = _house(history, config, options, roles, timer, ds, fit, excluded, scores)
    verdict = timer.run("champion gates", lambda: _decide(ds, fit, scores, house, options))
    house.proposal["credible"] = bool(house.credibility["credible"]) and verdict.promote
    day = iso(ds.grid.end - 1.0)[:10]
    model = store.free_name(
        models, store.model_name(day), verdict.champion_name, promote=verdict.promote
    )
    chash = config_hash(config)
    provenance = _provenance(history, chash, loaded, fit, options, status["at"], settings)
    series = timer.run(
        "series",
        lambda: _series(verdict.coarse, ds, fit.train_building, fit.split, None),
    )
    reference = timer.run("reference", lambda: _reference(ds, fit, settings, verdict.coarse))
    validation = _validation(verdict, fit, options, ds, roles, series, reference)
    daily_errors = timer.run(
        "daily errors",
        lambda: _daily_errors(verdict.coarse, fit.train_building, fit.split, fit.end),
    )
    p = fit.building
    bounds = at_bound(p, settings.priors)
    warnings = _warnings(loaded.data.notes)
    plant = fit.plant or PlantParams(HeatPumpParams(), p)
    io.save(
        models / f"{model}.json",
        plant,
        _house_extra(model, fit, validation, house, provenance, bounds),
    )
    runs = store.index_runs(models)
    entry = {
        "model": model,
        "data_to": iso(ds.grid.end),
        "generated": status["at"],
        "promoted": verdict.promote,
        "ua_w_per_k": p.h_air_out,
        "ua_interval_90": None if house.ua_interval is None else list(house.ua_interval),
        "time_constant_h": p.time_constant_h,
        "credible": house.credibility["credible"],
        "gates": house.gates,
        "challenger_room_rmse_k": verdict.challenger_err,
        "champion_room_rmse_k": verdict.champion_err,
        "held_out_room_rmse_k": validation["held_out_room_rmse_k"],
        "skill": validation["skill_at_horizon"],
        "config_hash": chash,
    }
    trend = _trend(runs, model, entry)
    insight = _insight(
        model,
        status["at"],
        fit,
        house,
        validation,
        provenance,
        trend,
        daily_errors,
        ds,
        roles,
        bounds,
        warnings,
    )
    store.write_json(models / store.insight_name(model), insight)
    entry["series"] = _write_series(models, model, series)
    entry["w_per_m2"] = house.score.get("w_per_m2")
    entry["band"] = house.score.get("band")
    store.append_index(models, entry)
    revalidation: dict[str, Any] | None
    if verdict.promote:
        store.promote(models, model, status["at"])
        revalidation = _promoted_check(model, status["at"], ds, fit, verdict, house, series)
    else:
        revalidation = _champion_check(models, status["at"], ds, fit, verdict, timer)
    _log_model(model, p, house, verdict)
    message = house.credibility["message"]
    if verdict.promote and verdict.settings_changed:
        message = SETTINGS_CHANGED if message is None else f"{SETTINGS_CHANGED}; {message}"
    return {
        "outcome": "promoted" if verdict.promote else "kept_champion",
        "model": model,
        "champion": model if verdict.promote else verdict.champion_name,
        "ua_w_per_k": p.h_air_out,
        "ua_interval_90": None if house.ua_interval is None else list(house.ua_interval),
        "credible": house.credibility["credible"],
        "gates": house.gates,
        "message": message,
        "warnings": warnings,
        "validation": {
            k: validation[k]
            for k in (
                "challenger_room_rmse_k",
                "champion_room_rmse_k",
                "held_out_room_rmse_k",
                "skill_at_horizon",
                "rule",
                "settings_changed",
            )
        },
        "champion_revalidation": revalidation,
    }


def _warnings(notes: Mapping[str, Any]) -> list[str]:
    """Return the data notes the owner should see (a capped wood-stove episode)."""
    return [str(notes[key]) for key in WARNING_NOTES if isinstance(notes.get(key), str)]


def _series(
    scored: Dataset,
    ds: Dataset,
    p: BuildingParams,
    held_out_from: float,
    out_of_sample_from: float | None,
) -> dict[str, Any] | None:
    """Return a room series body; ``None`` (logged) when it cannot be built."""
    try:
        return room_series(
            scored, ds.coarsen(5), p, held_out_from, iso, out_of_sample_from=out_of_sample_from
        )
    except (ValueError, ArithmeticError, IndexError, KeyError) as exc:
        LOGGER.warning("no room series: %s", exc)
        return None


def _write_series(models: Path, model: str, body: dict[str, Any] | None) -> str | None:
    """Write ``series-<model>.json``; return its name (``None`` without a body)."""
    if body is None:
        return None
    name = store.series_name(model)
    store.write_json(models / name, body | {"model": model})
    return name


def _promoted_check(
    model: str,
    at: str,
    ds: Dataset,
    fit: FitOutcome,
    verdict: _Verdict,
    house: _House,
    series: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return the new champion's check: its own held-out validation of this run."""
    errors = verdict.scores.challenger
    credibility = house.credibility
    return {
        "model": model,
        "at": at,
        "source": "held_out",
        "data_to": iso(ds.grid.end),
        "fitted_to": iso(ds.grid.end),
        "from": iso(fit.split),
        "to": iso(fit.end),
        "origins": errors.origins,
        "in_sample": False,
        "room_rmse_k": _horizon(errors),
        "persistence_room_rmse_k": _persistence(errors),
        "skill_horizon_h": SKILL_HORIZON_H,
        "skill": skill_at(errors, SKILL_HORIZON_H),
        "series_rmse_k": None if series is None else series.get("rmse_k"),
        "series_bias_k": None if series is None else series.get("bias_k"),
        "credible": bool(credibility["credible"]),
        "reasons": list(credibility["reasons"]),
        "gates": credibility["gates"],
    }


def _champion_check(
    models: Path, at: str, ds: Dataset, fit: FitOutcome, verdict: _Verdict, timer: Timer
) -> dict[str, Any] | None:
    """Re-validate the kept champion on the newest data and rewrite its series.

    ``gates`` are the champion's three gates as of this run (:func:`champion_gates`);
    ``credible`` and ``reasons`` are its heat-loss gate's.
    """
    scores = verdict.scores
    champion = scores.champion
    errors = scores.compared_champion
    gates = verdict.champion_gates
    if champion is None or errors is None or gates is None:
        return None
    skill = skill_at(errors, SKILL_HORIZON_H)
    series = timer.run(
        "champion series",
        lambda: _series(scores.coarse, ds, champion.building, -math.inf, champion.data_to),
    )
    _write_series(models, champion.name, series)
    return {
        "model": champion.name,
        "at": at,
        "source": "revalidated",
        "data_to": iso(ds.grid.end),
        "fitted_to": None if champion.data_to is None else iso(champion.data_to),
        "from": iso(scores.compared_from),
        "to": iso(fit.end),
        "origins": errors.origins,
        "in_sample": scores.champion_in_sample,
        "room_rmse_k": _horizon(errors),
        "persistence_room_rmse_k": _persistence(errors),
        "skill_horizon_h": SKILL_HORIZON_H,
        "skill": skill,
        "series_rmse_k": None if series is None else series.get("rmse_k"),
        "series_bias_k": None if series is None else series.get("bias_k"),
        "credible": bool(gates["heat_loss"]["ok"]),
        "reasons": list(gates["heat_loss"]["reasons"]),
        "gates": gates,
    }


def _load(
    history: Path,
    options: LearnOptions,
    roles: HistoryRoles,
    timer: Timer,
    excluded: tuple[ev.Event, ...] = (),
) -> _Loaded:
    """Load the fit span of 1 min history; raise :class:`NotReadyError` when it is too thin."""
    if roles.room is None:
        raise NotReadyError(["a room temperature signal (control_room_signal)"])
    with connect(history) as conn:
        span = rollup_span(conn, MINUTE)
    if span is None:
        raise NotReadyError(["1 min history (none stored yet)"])
    end = span[1]
    start = max(span[0], math.floor((end - options.fit_days * DAY_S) / DAY_S) * DAY_S)
    data = timer.run(
        "load",
        lambda: history_dataset(
            history,
            roles,
            step=MINUTE,
            start=start,
            end=end,
            weather=options.weather,
            excluded=excluded,
        ),
    )
    ds = data.dataset
    missing = _readiness(ds, options)
    if missing:
        raise NotReadyError(missing)
    days = (ds.grid.end - ds.grid.start) / DAY_S
    folds = min(options.folds, max(1, int((days - MIN_TRAIN_DAYS) // options.test_days)))
    return _Loaded(data, ds, days, folds)


def _timestamp(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)).timestamp()


def read_champion(champ: Mapping[str, Any] | None) -> _Champion | None:
    """Return the champion's building, data end and frozen credibility (``None`` if unreadable).

    ``heat_loss`` is the champion's frozen heat-loss gate (``None`` for a model fitted
    before the gates; ``credible`` and ``needed`` then stand for it).
    """
    if champ is None:
        return None
    payload = champ.get("house_payload")
    try:
        if not isinstance(payload, Mapping):
            raise TypeError("no house file")
        building = io.params_from_dict(payload["params"]).building
    except (KeyError, TypeError, ValueError) as exc:
        LOGGER.warning("champion %s unreadable (%s); treating as absent", champ.get("model"), exc)
        return None
    provenance = payload.get("provenance")
    credibility = payload.get("credibility")
    intervals = payload.get("intervals_90")
    building_intervals = intervals.get("building") if isinstance(intervals, Mapping) else None
    cred = credibility if isinstance(credibility, Mapping) else {}
    gates = cred.get("gates")
    heat_loss = gates.get("heat_loss") if isinstance(gates, Mapping) else None
    needed = cred.get("needed")
    return _Champion(
        name=str(champ.get("model")),
        building=building,
        data_to=_timestamp(provenance.get("data_to")) if isinstance(provenance, Mapping) else None,
        credible=cred.get("credible") is True,
        intervals=_pairs_of(building_intervals),
        heat_loss=heat_loss
        if isinstance(heat_loss, Mapping) and isinstance(heat_loss.get("checks"), Mapping)
        else None,
        needed=needed if isinstance(needed, Mapping) else {},
    )


def _pairs_of(value: Any) -> dict[str, tuple[float, float]]:
    if not isinstance(value, Mapping):
        return {}
    out = {}
    for name in SAME_HOUSE_FIELDS:
        pair = value.get(name)
        if (
            isinstance(pair, list | tuple)
            and len(pair) == 2
            and all(isinstance(v, int | float) and math.isfinite(v) for v in pair)
        ):
            out[name] = (float(pair[0]), float(pair[1]))
    return out


def same_house(champion: _Champion | None, p: BuildingParams, data_end: float) -> str | None:
    """Return why ``p`` is the champion's house on newer data, or ``None``.

    True when the data end at least :data:`NEWER_DATA_S` after the champion's and the
    heat-loss coefficient and time constant of ``p`` lie inside the champion's 90 %
    intervals.
    """
    if champion is None or champion.data_to is None:
        return None
    if data_end - champion.data_to < NEWER_DATA_S:
        return None
    if any(name not in champion.intervals for name in SAME_HOUSE_FIELDS):
        return None
    parts = []
    for name in SAME_HOUSE_FIELDS:
        lo, hi = champion.intervals[name]
        value = _value(p, name)
        if not lo <= value <= hi:
            return None
        parts.append(f"{name} {value:.4g} in [{lo:.4g}, {hi:.4g}]")
    return ", ".join(parts)


def _score(
    ds: Dataset,
    fit: FitOutcome,
    models: Path,
    constraints: Mapping[str, Any] | None = None,
) -> _Scores:
    """Score the challenger and the champion on the latest test block.

    The challenger is scored on the whole block; both are compared on the days after
    the end of the champion's own data when at least :data:`MIN_COMPARE_ORIGINS`
    origins lie there (neither has seen them), else on the whole block.
    """
    coarse = scoring_view(ds.coarsen(5))
    train = fit.train_building

    def errors(p: BuildingParams, start: float) -> HorizonErrors:
        return horizon_errors(coarse, p, start, fit.end, horizons_h=SKILL_HORIZONS_H)

    challenger = errors(train, fit.split)
    diurnal = diurnal_persistence(coarse, fit.split, fit.end, horizons_h=challenger.horizons_h)
    champ = store.champion(models)
    recorded = champion_constraints(champ)
    changed = recorded is not None and recorded != dict(constraints or {})
    champion = read_champion(champ)
    start, compared, champion_errors, in_sample = fit.split, challenger, None, False
    if champion is not None:
        seen = champion.data_to
        if seen is not None and seen > fit.split:
            later = errors(champion.building, seen)
            if later.origins >= MIN_COMPARE_ORIGINS:
                start, champion_errors, compared = seen, later, errors(train, seen)
            else:
                in_sample = True
        if champion_errors is None:
            champion_errors = errors(champion.building, fit.split)
    return _Scores(
        coarse,
        challenger,
        diurnal,
        champ,
        champion,
        start,
        compared,
        champion_errors,
        in_sample,
        changed,
    )


def _decide(
    ds: Dataset, fit: FitOutcome, scores: _Scores, house: _House, options: LearnOptions
) -> _Verdict:
    """Apply :func:`decide_promotion` to the scores and the gates of both models.

    The champion's gates are re-validated on the compared days (:func:`champion_gates`);
    the challenger's dynamics and sun gates for the comparison are taken on the same
    days (its own credibility judges the whole held-out block).
    """
    champion = scores.champion
    champion_errors = scores.compared_champion
    champion_credible: bool | None = None
    revalidated: dict[str, Any] | None = None
    if champion is not None and champion_errors is not None:
        revalidated = champion_gates(champion, scores, fit, house.sig, options.seed)
        champion_credible = bool(revalidated["heat_loss"]["ok"])
    same = same_house(champion, fit.building, ds.grid.end)
    challenger_err = _horizon(scores.compared_challenger)
    champion_err = None if champion_errors is None else _horizon(champion_errors)
    challenger_credible = bool(house.credibility["credible"])
    compared = _compared_gates(fit, scores, house)
    promote, rule = decide_promotion(
        challenger_err,
        champion_err,
        options.tolerance_k,
        settings_changed=scores.settings_changed,
        challenger_credible=challenger_credible,
        champion_credible=champion_credible,
        same_house=same,
        challenger_gates=compared,
        champion_gates=None if revalidated is None else gate_flags({"gates": revalidated}),
    )
    LOGGER.info("promotion: %s (%s)", promote, rule)
    return _Verdict(
        scores,
        challenger_err,
        champion_err,
        challenger_credible,
        champion_credible,
        same,
        promote,
        rule,
        compared,
        revalidated,
    )


def _compared_gates(fit: FitOutcome, scores: _Scores, house: _House) -> dict[str, bool]:
    """Return the challenger's gates on the days it is compared with the champion."""
    flags = house.gates
    if scores.compared_from == fit.split:
        return flags
    skill = skill_at(scores.compared_challenger, SKILL_HORIZON_H)
    sun = _sun_check(house.sun, scores.compared_from, fit.end)
    return flags | {
        "dynamics": bool(dynamics_gate(skill)["ok"]),
        "sun": bool(sun_gate(sun)["ok"]),
    }


def _reference(
    ds: Dataset, fit: FitOutcome, settings: HouseSettings, scored: Dataset
) -> float | None:
    """Fit the train split without the owner's bounds and pins; its held-out 24 h error.

    ``None`` when the owner set no bounds or pins, or the reference cannot be fitted.
    The facts' priors are kept and there is no bootstrap.
    """
    if not settings.bounds.ranges:
        return None
    config = FitConfig()
    try:
        windows = make_windows(ds.coarsen(5), config, end=fit.split)
        train = fit_building(windows, config, priors=unconstrained(settings.priors))
        return _horizon(horizon_errors(scored, train.params, fit.split, fit.end))
    except (ValueError, ArithmeticError) as exc:
        LOGGER.warning("no unconstrained reference fit: %s", exc)
        return None


def champion_constraints(champ: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return the house settings the champion was fitted with (``{}`` for older models).

    ``None`` without a champion.
    """
    if champ is None:
        return None
    payload = champ.get("house_payload")
    provenance = payload.get("provenance") if isinstance(payload, Mapping) else None
    recorded = provenance.get("constraints") if isinstance(provenance, Mapping) else None
    return dict(recorded) if isinstance(recorded, Mapping) else {}


def _house(
    history: Path,
    config: Mapping[str, Any],
    options: LearnOptions,
    roles: HistoryRoles,
    timer: Timer,
    ds: Dataset,
    fit: FitOutcome,
    excluded: tuple[ev.Event, ...] = (),
    scores: _Scores | None = None,
) -> _House:
    """Return the signature, excitation, credibility gates, house score and curve proposal.

    The dynamics and sun gates judge the challenger (the train-only fit) on the
    held-out block of ``scores``; without scores they do not pass.
    """
    p = fit.building
    ua = p.h_air_out
    sig, sig_days, excluded_days, sig_extra = timer.run(
        "signature", lambda: _signature(history, roles, options.weather, ua, options, excluded)
    )
    bootstrap = fit.intervals.get("h_air_out")
    reported = ua_range(ua, bootstrap, fit.fold_uas)
    excited = excitation(ds, ua, bootstrap)
    challenger = None if scores is None else scores.challenger
    evaluator = (
        None if scores is None else SunEvaluator(scores.coarse, fit.train_building, options.seed)
    )
    sun = timer.run("sun", lambda: _sun_check(evaluator, fit.split, fit.end))
    credibility = model_credibility(
        sig,
        sig_days,
        excited,
        ua,
        math.nan if challenger is None else skill_at(challenger, SKILL_HORIZON_H),
        skill_24h=math.nan if challenger is None else skill_at(challenger, SCORE_HORIZON_H),
        reported_ua=reported,
        fold_uas=fit.fold_uas,
        sun=sun,
    )
    ua_interval = reported
    floor = options.floor_area_m2
    if floor is None and isinstance(config.get("house_floor_area_m2"), int | float):
        floor = float(config["house_floor_area_m2"])
    house_score = score(
        ua,
        ua_interval,
        floor,
        credible=bool(credibility["credible"]),
        needed=credibility["message"],
    )
    comfort, curve, limits = curve_settings(config)
    running = ds.col("compressor_frac") >= 0.999
    flow_run = ds.col("flow")[running & np.isfinite(ds.col("flow"))]
    coldest = ds.col("outside")
    proposal = propose_curve(
        p,
        comfort,
        curve,
        limits,
        flow_lpm=float(np.median(flow_run)) if flow_run.size else None,
        coldest_c=float(np.nanmin(coldest)) if np.isfinite(coldest).any() else None,
    )
    proposal["credible"] = bool(credibility["credible"])
    return _House(
        sig,
        sig_days,
        excluded_days,
        sig_extra,
        excited,
        credibility,
        ua_interval,
        house_score,
        proposal,
        bootstrap,
        evaluator,
    )


def _sun_check(evaluator: SunEvaluator | None, start: float, end: float) -> SunCheck | None:
    """Return the sun numbers on ``[start, end)``; ``None`` (logged) when they cannot be made."""
    if evaluator is None:
        return None
    try:
        return evaluator.check(start, end)
    except (ValueError, ArithmeticError, IndexError, KeyError, np.linalg.LinAlgError) as exc:
        LOGGER.warning("no sun check: %s", exc)
        return None


def gate_flags(credibility: Mapping[str, Any]) -> dict[str, bool]:
    """Return whether each gate of a credibility block passes."""
    gates = credibility.get("gates")
    gates = gates if isinstance(gates, Mapping) else {}
    return {
        name: isinstance(gates.get(name), Mapping) and gates[name].get("ok") is True
        for name in GATES
    }


def champion_heat_loss(champion: _Champion, sig: Signature | None) -> dict[str, Any]:
    """Return the champion's heat-loss gate as of this run.

    Its frozen checks (for a model fitted before the gates, its old credibility as one
    check, ``fitted``), with the agreement of its heat-loss coefficient re-checked
    against this run's energy signature, which has seen the newest days; without a
    signature this run the frozen agreement stands.
    """
    if champion.heat_loss is not None:
        frozen = champion.heat_loss
        checks = {
            name: dict(value)
            for name, value in frozen["checks"].items()
            if isinstance(value, Mapping)
        }
        needed = [n for n in frozen.get("needed") or [] if isinstance(n, str)]
        reasons = [r for r in frozen.get("reasons") or [] if isinstance(r, str)]
    else:
        checks = {"fitted": {"ok": champion.credible, "value": None, "limit": None}}
        needed = []
        if (champion.needed.get("heating_days") or 0) > 0:
            needed.append("more_heating_days")
        if (champion.needed.get("outside_span_k") or 0) > 0:
            needed.append("more_outside_spread")
        if not champion.credible and not needed:
            needed.append("legacy_model")
        reasons = [] if champion.credible else [LEGACY_REASON]
    ua = champion.building.h_air_out
    if sig is not None and ua > 0:
        agreement = abs(sig.h_w_per_k - ua) / ua
        agrees = agreement <= RC_DISAGREEMENT
        checks["ua_agreement"] = {
            "ok": agrees,
            "value": round(agreement, 3),
            "limit": RC_DISAGREEMENT,
            "signature": "this run",
        }
        needed = [n for n in needed if n != "ua_disagrees"]
        reasons = [r for r in reasons if "differ" not in r]
        if not agrees:
            needed.append("ua_disagrees")
            reasons.append(
                f"signature and RC heat-loss coefficient differ by {agreement:.0%} "
                f"> {RC_DISAGREEMENT:.0%}"
            )
    ok = all(value.get("ok") is True for value in checks.values())
    return {
        "ok": ok,
        "uses": list(HEAT_LOSS_USES),
        "checks": checks,
        "needed": list(dict.fromkeys(needed)) if not ok else [],
        "reasons": reasons if not ok else [],
        "message": None if ok else "; ".join(reasons) or "the heat-loss checks did not pass",
    }


def champion_gates(
    champion: _Champion,
    scores: _Scores,
    fit: FitOutcome,
    sig: Signature | None,
    seed: int,
) -> dict[str, Any]:
    """Return the three gates of the champion on the compared held-out days of this run."""
    errors = scores.compared_champion
    evaluator = SunEvaluator(scores.coarse, champion.building, seed)
    return {
        "heat_loss": champion_heat_loss(champion, sig),
        "dynamics": dynamics_gate(
            math.nan if errors is None else skill_at(errors, SKILL_HORIZON_H),
            math.nan if errors is None else skill_at(errors, SCORE_HORIZON_H),
        ),
        "sun": sun_gate(_sun_check(evaluator, scores.compared_from, fit.end)),
    }


def _provenance(
    history: Path,
    chash: str,
    loaded: _Loaded,
    fit: FitOutcome,
    options: LearnOptions,
    generated: str,
    settings: HouseSettings | None = None,
) -> dict[str, Any]:
    """Return where the model came from: data span, configuration, code and method.

    ``constraints`` are the owner's fact and bound settings that shaped the fit,
    ``told`` the rough values the facts imply, ``learning`` the learning options in
    force with the days the owner left out.
    """
    ds = loaded.ds
    learning = None if settings is None else settings.learning
    return {
        "history": str(history),
        "data_from": iso(ds.grid.start),
        "data_to": iso(ds.grid.end),
        "fit_days": round(loaded.days, 2),
        "step_s": loaded.data.step,
        "config_hash": chash,
        "code_version": code_version(),
        "method": fit.method,
        "fallback_reason": fit.fallback_reason,
        "seed": options.seed,
        "bootstrap": options.bootstrap,
        "folds": loaded.folds,
        "generated": generated,
        "constraints": {} if settings is None else dict(settings.constraints),
        "told": None if settings is None else told_json(settings.told),
        "learning": {
            "fit_days": options.fit_days,
            "test_days": options.test_days,
            "tolerance_k": options.tolerance_k,
            "excluded_days": [] if learning is None else list(learning.excluded_days),
            "excluded_days_in_fit": sum(1 for e in ds.events if e.kind == ev.EXCLUDED_DAY),
        },
        "notes": loaded.data.notes,
    }


def _validation(
    verdict: _Verdict,
    fit: FitOutcome,
    options: LearnOptions,
    ds: Dataset,
    roles: HistoryRoles,
    series: Mapping[str, Any] | None = None,
    reference: float | None = None,
) -> dict[str, Any]:
    """Return the held-out validation of the run (challenger, champion, skill, folds, events).

    ``held_out_room_rmse_k`` is the new model's error on the whole held-out block;
    ``challenger_room_rmse_k`` and ``champion_room_rmse_k`` are the errors the promotion
    compared (both on ``compared``). ``series_*`` summarise the 24 h-ahead series.
    """
    scores = verdict.scores
    challenger = scores.challenger
    champion_errors = scores.compared_champion
    held_out = _horizon(challenger)
    summary: Mapping[str, Any] = series or {}
    return {
        "test_from": iso(fit.split),
        "test_to": iso(fit.end),
        "score_horizon_h": SCORE_HORIZON_H,
        "held_out_room_rmse_k": held_out,
        "persistence_room_rmse_k": _persistence(challenger),
        "skill_horizon_h": SKILL_HORIZON_H,
        "skill_at_horizon": skill_at(challenger, SKILL_HORIZON_H),
        "skill": skill_json(challenger, scores.diurnal),
        "series_rmse_k": summary.get("rmse_k"),
        "series_bias_k": summary.get("bias_k"),
        "series_points": summary.get("points", 0),
        "challenger_room_rmse_k": verdict.challenger_err,
        "champion_room_rmse_k": verdict.champion_err,
        "compared": {
            "from": iso(scores.compared_from),
            "to": iso(fit.end),
            "origins": scores.compared_challenger.origins,
            "champion_in_sample": scores.champion_in_sample,
        },
        "champion": verdict.champion_name,
        "challenger_credible": verdict.challenger_credible,
        "champion_credible": verdict.champion_credible,
        "challenger_gates": verdict.challenger_gates,
        "champion_gates": None
        if verdict.champion_gates is None
        else gate_flags({"gates": verdict.champion_gates}),
        "same_house": verdict.same_house,
        "promoted": verdict.promote,
        "rule": verdict.rule,
        "settings_changed": verdict.settings_changed,
        "tolerance_k": options.tolerance_k,
        "unconstrained_room_rmse_k": reference,
        "constraint_cost": None if reference is None else constraint_cost(held_out, reference),
        "challenger": _horizons_json(challenger),
        "champion_horizons": None if champion_errors is None else _horizons_json(champion_errors),
        "folds": fit.folds,
        "fit_room_rmse_k": fit.fit_rmse_room_k,
        "windows": fit.windows,
        "events_masked": [e.to_json(roles.timezone) for e in ds.events],
    }


def _house_extra(
    model: str,
    fit: FitOutcome,
    validation: dict[str, Any],
    house: _House,
    provenance: dict[str, Any],
    bounds: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the extra fields of the model's house file next to its parameters."""
    p = fit.building
    return {
        "model": model,
        "heat_pump_fitted": fit.plant is not None,
        "derived": {
            "h_air_out_w_per_k": p.h_air_out,
            "ua_range_90": None if house.ua_interval is None else list(house.ua_interval),
            "time_constant_h": p.time_constant_h,
            "emitter_time_constant_h": emitter_time_constant_h(p),
            "capacities_kwh_per_k": capacities(p),
            "heat_capacity_kwh_per_k": (p.c_water + p.c_mass + p.c_air) / J_PER_KWH,
        },
        "structure": structure_json(fit.priors),
        "intervals_90": {"building": {k: list(v) for k, v in fit.intervals.items()}},
        "validation": validation,
        "credibility": house.credibility,
        "excitation": house.excitation,
        "at_bound": bounds or [],
        "provenance": provenance,
        "identification": fit.report,
    }


def _trend(
    runs: list[dict[str, Any]], model: str, entry: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Return the error trend over the earlier runs and this one (``entry``).

    ``room_rmse_24h_k`` is each run's error on its whole held-out block (older runs:
    the error they were compared with).
    """
    return [
        {
            "model": r.get("model"),
            "data_to": r.get("data_to"),
            "promoted": r.get("promoted"),
            "ua_w_per_k": r.get("ua_w_per_k"),
            "room_rmse_24h_k": r.get("held_out_room_rmse_k", r.get("challenger_room_rmse_k")),
        }
        for r in [*(r for r in runs if r.get("model") != model), entry]
    ]


INSIGHT_VALIDATION: Final = (
    "test_from",
    "test_to",
    "score_horizon_h",
    "held_out_room_rmse_k",
    "persistence_room_rmse_k",
    "skill_horizon_h",
    "skill_at_horizon",
    "skill",
    "series_rmse_k",
    "series_bias_k",
    "series_points",
    "challenger_room_rmse_k",
    "champion_room_rmse_k",
    "compared",
    "champion",
    "challenger_credible",
    "champion_credible",
    "challenger_gates",
    "champion_gates",
    "same_house",
    "promoted",
    "rule",
    "settings_changed",
    "tolerance_k",
    "unconstrained_room_rmse_k",
    "constraint_cost",
)


def _insight(
    model: str,
    generated: str,
    fit: FitOutcome,
    house: _House,
    validation: dict[str, Any],
    provenance: dict[str, Any],
    trend: list[dict[str, Any]],
    daily_errors: list[dict[str, Any]],
    ds: Dataset,
    roles: HistoryRoles,
    bounds: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Return the insight JSON of the run (what the House page shows)."""
    p = fit.building
    sig = house.sig
    ua_interval = house.ua_interval
    credibility = house.credibility
    return {
        "schema": store.INSIGHT_SCHEMA,
        "model": model,
        "generated": generated,
        "data": {
            "from": provenance["data_from"],
            "to": provenance["data_to"],
            "fit_days": provenance["fit_days"],
            "signature_days": house.sig_days,
            "excluded_days": house.excluded_days,
            "owner_excluded_days": provenance["learning"]["excluded_days"],
            "warnings": list(warnings or []),
        },
        "ua": {
            "w_per_k": round(p.h_air_out, 1),
            "interval_90": None if ua_interval is None else [round(v, 1) for v in ua_interval],
            "interval_source": UA_RANGE_SOURCE,
            "bootstrap_interval_90": None
            if house.ua_bootstrap is None
            else [round(v, 1) for v in house.ua_bootstrap],
            "fold_w_per_k": [round(v, 1) for v in fit.fold_uas],
            "source": "rc_model",
            "signature_w_per_k": None if sig is None else round(sig.h_w_per_k, 1),
            "signature_interval_90": None if sig is None else [round(v, 1) for v in sig.h_interval],
            "low_confidence": credibility["low_confidence"],
        },
        "time_constant_h": _with_interval(p, fit.intervals, "time_constant_h"),
        "heat_capacity_kwh_per_k": round((p.c_water + p.c_mass + p.c_air) / J_PER_KWH, 1),
        "capacities_kwh_per_k": {k: round(v, 2) for k, v in capacities(p).items()},
        "emitter_time_constant_h": _with_interval(p, fit.intervals, "emitter_time_constant_h", 2),
        "structure": structure_json(fit.priors),
        "solar_aperture_m2": _with_interval(p, fit.intervals, "solar_aperture_m2", 2),
        "internal_gains_w": internal_gains_json(p, fit, house),
        "balance_temperature_c": None
        if sig is None
        else {
            "value": round(sig.balance_c, 1),
            "interval_90": [round(v, 1) for v in sig.balance_interval],
        },
        "signature": _signature_json(sig, house.sig_extra, roles.timezone),
        "excitation": house.excitation,
        "credibility": credibility,
        "score": house.score,
        "validation": {k: validation[k] for k in INSIGHT_VALIDATION},
        "at_bound": list(bounds or []),
        "error_trend": trend,
        "daily_error": daily_errors,
        "proposal": house.proposal,
        "events": [e.to_json(roles.timezone) for e in ds.events],
        "limits": list(LIMITS),
        "provenance": {k: provenance[k] for k in provenance if k != "notes"},
    }


UA_RANGE_SOURCE: Final = "bootstrap_and_folds"
GAINS_LABEL: Final = "net_free_heat"
GAINS_NOTE: Final = (
    "net free heat (people, appliances and whatever else warms the house), not separable "
    "from the heat loss: the data fix the balance temperature, so more gains means a "
    "larger heat-loss coefficient"
)
NODE_LABELS: Final = {"c_water": "loop", "c_mass": "emitter", "c_air": "building"}


def capacities(p: BuildingParams) -> dict[str, float]:
    """Return the node capacities in kWh/K under their labels (loop, emitter, building)."""
    return {label: float(getattr(p, name)) / J_PER_KWH for name, label in NODE_LABELS.items()}


def structure_json(priors: Priors | None) -> dict[str, Any]:
    """Return the model structure: the held parameters and what the nodes are."""
    fixed = dict((DEFAULT_PRIORS if priors is None else priors).fixed)
    return {
        "name": "chain" if fixed else "free",
        "fixed": fixed,
        "free": [name for name in BOUNDS if name not in fixed],
        "nodes": dict(NODE_LABELS),
    }


def internal_gains_json(p: BuildingParams, fit: FitOutcome, house: _House) -> dict[str, Any]:
    """Return the internal gains: value, interval and how they trade against the heat loss.

    ``ua_w_per_k_per_100_w`` is how much the heat-loss coefficient moves with 100 W
    more gains at the fit window's mean indoor-outdoor difference (``100 / dT``, the
    steady-state balance), what a pin on the gains costs or gives the heat loss.
    """
    body = _with_interval(p, fit.intervals, "q_int_w", 0)
    delta = house.excitation.get("mean_delta_t_k")
    shift = 100.0 / delta if isinstance(delta, int | float) and delta > 1.0 else None
    return body | {
        "identified": False,
        "label": GAINS_LABEL,
        "note": GAINS_NOTE,
        "at_zero": p.q_int_w <= BOUNDS["q_int_w"][0] + 1e-6 * BOUNDS["q_int_w"][1],
        "ua_w_per_k_per_100_w": None if shift is None else round(shift, 1),
    }


def _log_model(model: str, p: BuildingParams, house: _House, verdict: _Verdict) -> None:
    """Log the run's model in one line."""
    ua_interval = house.ua_interval
    champion_err = verdict.champion_err
    LOGGER.info(
        "model %s: UA %.0f W/K %s, tau %.0f h, %s; held-out room 24 h %.3f K (champion %s)",
        model,
        p.h_air_out,
        "" if ua_interval is None else f"[{ua_interval[0]:.0f}-{ua_interval[1]:.0f}]",
        p.time_constant_h,
        "credible" if house.credibility["credible"] else house.credibility["message"],
        verdict.challenger_err,
        "none" if champion_err is None else f"{champion_err:.3f} K",
    )

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
3. **Champion / challenger**: the challenger is the latest fold's train-only
   building (fitted before the latest ``test_days``); its free-run room error at
   24 h on those days is compared with the champion's on the same days (events
   masked; the champion is re-scored on the newest held-out days every run). The new
   model is promoted when its error is not worse (``<=`` champion + ``tolerance_k``),
   or when there is no champion. The champion has usually seen part of these days
   (it was fitted up to its own run), so the rule leans towards keeping it; both
   errors are reported. When the owner's house facts or bounds differ from those the
   champion was fitted with, the new model is promoted whenever its held-out error is
   finite: the changed settings are the owner's intent, and both errors are kept so a
   worse fit shows.
4. **Insight**: the energy signature over the whole 15 min history (kept forever;
   event days left out) with its credibility rules, the insulation score
   (:mod:`ovenbird_sim.learn.score`) and the curve proposal
   (:mod:`ovenbird_sim.learn.proposal`).

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
    FitConfig,
    bootstrap_building,
    fit_building,
    make_windows,
)
from ovenbird_sim.identify.pipeline import (
    INTERVAL_FIELDS,
    IdentifyOptions,
    fold_splits,
    identify_dataset,
)
from ovenbird_sim.identify.validate import HORIZONS_H, HorizonErrors, horizon_errors
from ovenbird_sim.insight.signature import (
    COLD_DAY_C,
    CREDIBLE_COLD_DAYS,
    CREDIBLE_DAYS,
    CREDIBLE_SPAN_K,
    HEATING_DAY_W,
    Signature,
    daily,
    energy_signature,
)
from ovenbird_sim.learn import models as store
from ovenbird_sim.learn.priors import (
    HouseSettings,
    LearnSettings,
    SettingError,
    house_settings,
    told_json,
)
from ovenbird_sim.learn.proposal import CurveLimits, propose_curve
from ovenbird_sim.learn.score import DESIGN_OUTSIDE_C, score
from ovenbird_sim.model.building import J_PER_KWH, BuildingParams
from ovenbird_sim.model.heatpump import HeatPumpParams
from ovenbird_sim.model.plant import PlantParams

LOGGER = logging.getLogger("ovenbird_sim.learn")
DAY_S: Final = 86400.0
MIN_TRAIN_DAYS: Final = 7
SCORE_HORIZON_H: Final = 24.0
SIGNATURE_MIN_DAYS: Final = 5
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
        Per fold: split, test end, train-only room RMSE and held-out horizons.
    fit_rmse_room_k, windows
        Final fit diagnostics.
    report
        The identification report (full plant only).
    fallback_reason
        Why the full plant path was not used.
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
) -> tuple[bool, str]:
    """Apply the promotion rule to the held-out room errors.

    Parameters
    ----------
    challenger_k
        The new model's free-run room RMSE at 24 h on the latest held-out days.
    champion_k
        The champion's on the same days; ``None`` without a champion.
    tolerance_k
        Allowed excess of the challenger.
    settings_changed
        The owner's house facts or bounds differ from the champion's: the challenger
        is promoted whenever its error is finite.

    Returns
    -------
    tuple
        Whether to promote, and the rule as applied (for the report).
    """
    if not math.isfinite(challenger_k):
        return False, "the challenger has no held-out error (no scored origins)"
    if settings_changed:
        champion = (
            "none" if champion_k is None or not math.isfinite(champion_k) else f"{champion_k:.3f} K"
        )
        return True, (
            f"{SETTINGS_CHANGED} (challenger {challenger_k:.3f} K, champion {champion} "
            "on the same held-out days, room, 24 h)"
        )
    if champion_k is None or not math.isfinite(champion_k):
        return True, "no champion yet"
    promote = challenger_k <= champion_k + tolerance_k
    return promote, (
        f"challenger {challenger_k:.3f} K {'<=' if promote else '>'} champion "
        f"{champion_k:.3f} K + {tolerance_k:.2f} K (room, 24 h, held out)"
    )


def _horizon(errors: HorizonErrors, hours: float = SCORE_HORIZON_H) -> float:
    return float(errors.room_rmse[HORIZONS_H.index(hours)])


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
        values = np.array(
            [
                p.time_constant_h if name == "time_constant_h" else getattr(p, name)
                for p in boot_samples
            ]
        )
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
    need = options.test_days + MIN_TRAIN_DAYS + 1
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


def _credibility(sig: Signature | None, days: int) -> dict[str, Any]:
    if sig is None:
        needed = {
            "heating_days": CREDIBLE_DAYS,
            "cold_days": CREDIBLE_COLD_DAYS,
            "outside_span_k": CREDIBLE_SPAN_K,
        }
        return {
            "credible": False,
            "days": days,
            "heating_days": 0,
            "cold_days": 0,
            "outside_span_k": 0.0,
            "rules": _rules(),
            "needed": needed,
            "reasons": [f"{days} complete days < {SIGNATURE_MIN_DAYS} for a signature"],
            "low_confidence": False,
            "message": _needed_message(needed),
        }
    needed = {
        "heating_days": max(0, CREDIBLE_DAYS - sig.heating_days),
        "cold_days": max(0, CREDIBLE_COLD_DAYS - sig.cold_days),
        "outside_span_k": round(max(0.0, CREDIBLE_SPAN_K - sig.outside_span_k), 1),
    }
    return {
        "credible": sig.credible,
        "days": sig.days,
        "heating_days": sig.heating_days,
        "cold_days": sig.cold_days,
        "outside_span_k": round(sig.outside_span_k, 2),
        "rules": _rules(),
        "needed": needed,
        "reasons": list(sig.reasons),
        "low_confidence": sig.low_confidence,
        "message": None if sig.credible else _needed_message(needed),
    }


def _rules() -> dict[str, Any]:
    return {
        "heating_days": CREDIBLE_DAYS,
        "heating_day_w": HEATING_DAY_W,
        "cold_days": CREDIBLE_COLD_DAYS,
        "cold_day_below_c": COLD_DAY_C,
        "outside_span_k": CREDIBLE_SPAN_K,
    }


def _needed_message(needed: Mapping[str, float]) -> str:
    parts = []
    if needed["cold_days"]:
        parts.append(f"{needed['cold_days']} more cold days (daily mean below {COLD_DAY_C:.0f} °C)")
    if needed["heating_days"]:
        parts.append(f"{needed['heating_days']} more heating days")
    if needed["outside_span_k"]:
        parts.append(f"{needed['outside_span_k']} K more spread in daily outside temperature")
    return "insufficient data: " + (", ".join(parts) or "more days") + " needed"


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
    return p.time_constant_h if name == "time_constant_h" else float(getattr(p, name))


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
    """The challenger against the champion on the latest test block."""

    coarse: Dataset
    challenger: HorizonErrors
    champ: dict[str, Any] | None
    champion_errors: HorizonErrors | None
    challenger_err: float
    champion_err: float | None
    promote: bool
    rule: str
    settings_changed: bool = False

    @property
    def champion_name(self) -> Any:
        """The champion's model name (``None`` without a champion)."""
        return None if self.champ is None else self.champ.get("model")


@dataclass(frozen=True, slots=True)
class _House:
    """The energy signature, credibility, score and curve proposal of one run."""

    sig: Signature | None
    sig_days: int
    excluded_days: list[str]
    sig_extra: dict[str, Any]
    credibility: dict[str, Any]
    ua_interval: tuple[float, float] | None
    score: dict[str, Any]
    proposal: dict[str, Any]


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
    verdict = _compare(ds, fit, models, options, settings.constraints)
    house = _house(history, config, options, roles, timer, ds, fit, verdict.promote, excluded)
    day = iso(ds.grid.end - 1.0)[:10]
    model = store.free_name(
        models, store.model_name(day), verdict.champion_name, promote=verdict.promote
    )
    chash = config_hash(config)
    provenance = _provenance(history, chash, loaded, fit, options, status["at"], settings)
    validation = _validation(verdict, fit, options, ds, roles)
    daily_errors = timer.run(
        "daily errors",
        lambda: _daily_errors(verdict.coarse, fit.train_building, fit.split, fit.end),
    )
    p = fit.building
    plant = fit.plant or PlantParams(HeatPumpParams(), p)
    io.save(
        models / f"{model}.json",
        plant,
        _house_extra(model, fit, validation, house.credibility, provenance),
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
        "challenger_room_rmse_k": verdict.challenger_err,
        "champion_room_rmse_k": verdict.champion_err,
        "config_hash": chash,
    }
    trend = _trend(runs, model, entry)
    insight = _insight(
        model, status["at"], fit, house, validation, provenance, trend, daily_errors, ds, roles
    )
    store.write_json(models / store.insight_name(model), insight)
    entry["w_per_m2"] = house.score.get("w_per_m2")
    entry["band"] = house.score.get("band")
    store.append_index(models, entry)
    if verdict.promote:
        store.promote(models, model, status["at"])
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
        "message": message,
        "validation": {
            k: validation[k]
            for k in (
                "challenger_room_rmse_k",
                "champion_room_rmse_k",
                "rule",
                "settings_changed",
            )
        },
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
    folds = min(options.folds, max(1, int((days - 1 - MIN_TRAIN_DAYS) // options.test_days)))
    return _Loaded(data, ds, days, folds)


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


def _compare(
    ds: Dataset,
    fit: FitOutcome,
    models: Path,
    options: LearnOptions,
    constraints: Mapping[str, Any] | None = None,
) -> _Verdict:
    """Score the challenger and the champion on the latest test block and decide promotion.

    The champion is re-scored on the newest held-out days of this run, so both errors
    cover the same days.
    """
    coarse = scoring_view(ds.coarsen(5))
    challenger = horizon_errors(coarse, fit.train_building, fit.split, fit.end)
    champ = store.champion(models)
    recorded = champion_constraints(champ)
    changed = recorded is not None and recorded != dict(constraints or {})
    champion_errors: HorizonErrors | None = None
    if champ is not None:
        try:
            champion_b = io.params_from_dict(champ["house_payload"]["params"]).building
            champion_errors = horizon_errors(coarse, champion_b, fit.split, fit.end)
        except (KeyError, TypeError, ValueError) as exc:
            LOGGER.warning(
                "champion %s unreadable (%s); treating as absent", champ.get("model"), exc
            )
    challenger_err = _horizon(challenger)
    champion_err = None if champion_errors is None else _horizon(champion_errors)
    promote, rule = decide_promotion(
        challenger_err, champion_err, options.tolerance_k, settings_changed=changed
    )
    LOGGER.info("promotion: %s (%s)", promote, rule)
    return _Verdict(
        coarse,
        challenger,
        champ,
        champion_errors,
        challenger_err,
        champion_err,
        promote,
        rule,
        changed,
    )


def _house(
    history: Path,
    config: Mapping[str, Any],
    options: LearnOptions,
    roles: HistoryRoles,
    timer: Timer,
    ds: Dataset,
    fit: FitOutcome,
    promote: bool,
    excluded: tuple[ev.Event, ...] = (),
) -> _House:
    """Return the energy signature, its credibility, the house score and the curve proposal."""
    p = fit.building
    ua = p.h_air_out
    sig, sig_days, excluded_days, sig_extra = timer.run(
        "signature", lambda: _signature(history, roles, options.weather, ua, options, excluded)
    )
    credibility = _credibility(sig, sig_days)
    floor = options.floor_area_m2
    if floor is None and isinstance(config.get("house_floor_area_m2"), int | float):
        floor = float(config["house_floor_area_m2"])
    ua_interval = fit.intervals.get("h_air_out")
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
    proposal["credible"] = bool(credibility["credible"]) and promote
    return _House(
        sig,
        sig_days,
        excluded_days,
        sig_extra,
        credibility,
        ua_interval,
        house_score,
        proposal,
    )


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
) -> dict[str, Any]:
    """Return the held-out validation of the run (challenger, champion, folds, events)."""
    champion_errors = verdict.champion_errors
    return {
        "test_from": iso(fit.split),
        "test_to": iso(fit.end),
        "score_horizon_h": SCORE_HORIZON_H,
        "challenger_room_rmse_k": verdict.challenger_err,
        "champion_room_rmse_k": verdict.champion_err,
        "champion": verdict.champion_name,
        "promoted": verdict.promote,
        "rule": verdict.rule,
        "settings_changed": verdict.settings_changed,
        "tolerance_k": options.tolerance_k,
        "challenger": _horizons_json(verdict.challenger),
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
    credibility: dict[str, Any],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    """Return the extra fields of the model's house file next to its parameters."""
    p = fit.building
    return {
        "model": model,
        "heat_pump_fitted": fit.plant is not None,
        "derived": {
            "h_air_out_w_per_k": p.h_air_out,
            "time_constant_h": p.time_constant_h,
            "capacities_kwh_per_k": {
                "water": p.c_water / J_PER_KWH,
                "mass": p.c_mass / J_PER_KWH,
                "air": p.c_air / J_PER_KWH,
            },
        },
        "intervals_90": {"building": {k: list(v) for k, v in fit.intervals.items()}},
        "validation": validation,
        "credibility": credibility,
        "provenance": provenance,
        "identification": fit.report,
    }


def _trend(
    runs: list[dict[str, Any]], model: str, entry: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Return the error trend over the earlier runs and this one (``entry``)."""
    return [
        {
            "model": r.get("model"),
            "data_to": r.get("data_to"),
            "promoted": r.get("promoted"),
            "ua_w_per_k": r.get("ua_w_per_k"),
            "room_rmse_24h_k": r.get("challenger_room_rmse_k"),
        }
        for r in [*(r for r in runs if r.get("model") != model), entry]
    ]


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
        },
        "ua": {
            "w_per_k": round(p.h_air_out, 1),
            "interval_90": None if ua_interval is None else [round(v, 1) for v in ua_interval],
            "source": "rc_model",
            "signature_w_per_k": None if sig is None else round(sig.h_w_per_k, 1),
            "signature_interval_90": None if sig is None else [round(v, 1) for v in sig.h_interval],
            "low_confidence": credibility["low_confidence"],
        },
        "time_constant_h": _with_interval(p, fit.intervals, "time_constant_h"),
        "solar_aperture_m2": _with_interval(p, fit.intervals, "solar_aperture_m2", 2),
        "internal_gains_w": _with_interval(p, fit.intervals, "q_int_w", 0),
        "balance_temperature_c": None
        if sig is None
        else {
            "value": round(sig.balance_c, 1),
            "interval_90": [round(v, 1) for v in sig.balance_interval],
        },
        "signature": _signature_json(sig, house.sig_extra, roles.timezone),
        "credibility": credibility,
        "score": house.score,
        "validation": {
            k: validation[k]
            for k in (
                "test_from",
                "test_to",
                "score_horizon_h",
                "challenger_room_rmse_k",
                "champion_room_rmse_k",
                "champion",
                "promoted",
                "rule",
                "settings_changed",
            )
        },
        "error_trend": trend,
        "daily_error": daily_errors,
        "proposal": house.proposal,
        "events": [e.to_json(roles.timezone) for e in ds.events],
        "limits": list(LIMITS),
        "provenance": {k: provenance[k] for k in provenance if k != "notes"},
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

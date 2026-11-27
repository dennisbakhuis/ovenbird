"""What the learned house model says: what-if, live heat balance and the room series.

Three read-only views on the model the learner promoted (or, without one, on a rough
model built from the owner's facts), all in pure Python (:mod:`ovenbird_core.housemodel`),
so the service never imports numpy or scipy:

* :func:`whatif_payload` (``GET insight/house/whatif``): the heat the loop must deliver
  to hold a comfort temperature at an outside temperature, sun and extra heat, the loop
  and supply temperatures that needs, what the owner's curve gives, and how the room
  drifts with the heating off;
* :func:`balance_payload` (``GET insight/house/balance``): the heat flows of the house
  right now (heat pump, loss, sun, internal gains, storage);
* :func:`series_payload` (``GET insight/house/series``): the room, measured and as the
  model predicted it 24 h earlier, from the learner's ``series-<model>.json``.

The champion's building parameters are read from its house file (``params.building``)
through :func:`ovenbird.insight.house.read_untrusted`, checked field by field by
:meth:`HouseModel.from_json`; the series file is read the same way with its own bounds
(:data:`SERIES_MAX_BYTES`, :data:`SERIES_MAX_ROWS`, a plausible temperature range).
Anything refused is logged and treated as absent.
"""

from __future__ import annotations

import logging
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

from ovenbird.clock import iso_z
from ovenbird.config import Settings
from ovenbird.history.forecast import issue_rows, latest_issue
from ovenbird.insight import house
from ovenbird.runtime import Runtime
from ovenbird.weather.service import WeatherService
from ovenbird_core import HeishaSignal, derived
from ovenbird_core.control.config import OvenbirdConfig
from ovenbird_core.control.observe import as_number
from ovenbird_core.housefacts import estimate, facts_from_config
from ovenbird_core.housemodel import (
    NOMINAL_FLOW_LPM,
    HouseModel,
    supply_c,
    with_defaults_from_estimate,
)

LOGGER = logging.getLogger("ovenbird.insight")
MODEL_MISSING: Final = "house_model_missing"
SERIES_MISSING: Final = "house_series_missing"
ERROR_CODES: Final = (SERIES_MISSING, MODEL_MISSING)
SERIES_SCHEMA: Final = "ovenbird.house-series/1"
SERIES_MAX_BYTES: Final = 1024 * 1024
SERIES_MAX_ROWS: Final = 2000
SERIES_COLUMNS: Final = ["ts", "room_measured", "room_predicted_24h"]
SERIES_TEMPERATURE_RANGE: Final = (-40.0, 60.0)
SERIES_STEP_RANGE_S: Final = (60, 86400)
MODEL_NAME: Final = re.compile(r"^house-\d{8}(-\d{1,3})?$")
DRIFT_HOURS: Final = 8
DRIFT_STEP_S: Final = 900
HOUR_S: Final = 3600.0
NO_MODEL: Final = (
    "no house model has been learned yet and the facts do not give a heat-loss estimate: "
    "state the build period (house_build_period) and the heated floor area "
    "(house_floor_area_m2) or the volume (house_volume_m3) in the house settings"
)

type Json = dict[str, Any]


class InsightError(Exception):
    """A request the insight views cannot answer; carries the status and the error code."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def to_json(self) -> Json:
        """Return the standard error body ``{"detail": {"code", "message", "params"}}``."""
        return {"detail": {"code": self.code, "message": self.message, "params": {}}}


@dataclass(frozen=True, slots=True)
class ModelChoice:
    """The house model a view answers from.

    Parameters
    ----------
    model
        The model.
    source
        ``model`` (the learner's champion) or ``estimate`` (the owner's facts).
    name
        The champion's name (``None`` for an estimate).
    credible
        Whether the learner's credibility rules pass (always ``False`` for an estimate).
    """

    model: HouseModel
    source: str
    name: str | None
    credible: bool


def _champion_model(models: Path) -> ModelChoice | None:
    """Return the champion, or ``None`` when there is none or its files are refused."""
    try:
        found = house.champion(models)
    except house.LearnerFileError as exc:
        LOGGER.warning("what-if: the champion cannot be read: %s", exc)
        return None
    if found is None:
        return None
    current, insight = found
    name = current.get("model")
    if not isinstance(name, str) or not MODEL_NAME.fullmatch(name):
        LOGGER.warning("what-if: current.json names no usable model")
        return None
    try:
        raw = house.read_untrusted(models / f"{name}.json")
        params = raw.get("params") if isinstance(raw, dict) else None
        building = params.get("building") if isinstance(params, dict) else None
        if not isinstance(building, dict):
            raise ValueError("the house file holds no building parameters")
        model = HouseModel.from_json(house.bounded(building))
    except (house.LearnerFileError, ValueError) as exc:
        LOGGER.warning("what-if: the champion's parameters are refused: %s", exc)
        return None
    credibility = insight.get("credibility")
    credible = isinstance(credibility, dict) and credibility.get("credible") is True
    return ModelChoice(model, "model", name, credible)


def _estimated_model(settings: Settings) -> ModelChoice | None:
    facts = facts_from_config(
        {
            name: getattr(settings, name)
            for name in Settings.model_fields
            if name.startswith("house_")
        }
    )
    told = estimate(facts)
    if told.ua_w_per_k is None:
        return None
    return ModelChoice(with_defaults_from_estimate(told), "estimate", None, False)


def choose_model(models: Path, settings: Settings) -> ModelChoice:
    """Return the champion, else a model from the owner's facts.

    Raises
    ------
    InsightError
        ``404`` ``house_model_missing`` when there is neither.
    """
    choice = _champion_model(models) if house.models_ok(models) else None
    if choice is None:
        choice = _estimated_model(settings)
    if choice is None:
        raise InsightError(404, MODEL_MISSING, NO_MODEL)
    return choice


def _rounded(value: float, digits: int = 1) -> float:
    return round(value, digits)


def whatif_payload(
    choice: ModelChoice,
    config: OvenbirdConfig,
    *,
    outside_c: float,
    comfort_c: float,
    sun_wm2: float,
    stove_w: float,
) -> Json:
    """Return the body of ``GET api/v1/insight/house/whatif``.

    Parameters
    ----------
    choice
        The model the answer comes from.
    config
        The controller configuration (the owner's curve and the supply limit).
    outside_c, comfort_c, sun_wm2, stove_w
        The scenario: outside temperature, room temperature to hold, global horizontal
        irradiance and heat a wood stove puts into the room.

    Returns
    -------
    dict
        See ``docs/api-v1.md``. The drift starts at the steady state that holds the
        comfort temperature and continues without the loop; the stove is not part of it.
    """
    model = choice.model
    state = model.steady_state(comfort_c, outside_c, sun_wm2, stove_w)
    supply = supply_c(state.loop_mean_c, state.heat_w, NOMINAL_FLOW_LPM)
    max_supply = config.safety.max_supply_c
    limited: list[str] = []
    if state.heat_w <= 0.0:
        limited.append("no_heat_needed")
    if supply > max_supply:
        limited.append("max_supply")
    drift = model.free_drift(comfort_c, outside_c, sun_wm2, DRIFT_HOURS, DRIFT_STEP_S)
    tau = model.time_constant_h
    return {
        "source": choice.source,
        "model": choice.name,
        "credible": choice.credible,
        "inputs": {
            "outside_c": outside_c,
            "comfort_c": comfort_c,
            "sun_wm2": sun_wm2,
            "stove_w": stove_w,
        },
        "heat_demand_w": round(state.heat_w),
        "free_heat_w": round(model.free_heat_w(sun_wm2, stove_w)),
        "loss_w": round(model.loss_w(comfort_c, outside_c)),
        "loop_mean_c": _rounded(state.loop_mean_c),
        "supply_c": _rounded(supply),
        "curve_c": _rounded(config.base_water(outside_c)),
        "max_supply_c": _rounded(max_supply),
        "limited_by": limited,
        "balance_outside_c": _rounded(model.balance_outside_c(comfort_c, sun_wm2, stove_w)),
        "drift": {
            "hours": DRIFT_HOURS,
            "step_s": DRIFT_STEP_S,
            "room_c": [_rounded(value, 2) for value in drift],
        },
        "time_constant_h": None if math.isinf(tau) else _rounded(tau),
    }


def current_sun_wm2(
    weather: WeatherService | None, history_path: Path, now: datetime
) -> float | None:
    """Return the stored forecast's irradiance for the current hour (``None`` when unknown)."""
    if weather is None or not weather.enabled:
        return None
    moment = now.timestamp()
    hour = math.floor(moment / HOUR_S) * HOUR_S
    try:
        issued = latest_issue(history_path, moment)
        rows = issue_rows(history_path, issued) if issued is not None else []
    except sqlite3.Error as exc:
        LOGGER.warning("balance: the stored forecast cannot be read: %s", exc)
        rows = []
    for row in rows:
        if row.target_ts == hour and row.radiation_wm2 is not None:
            return float(row.radiation_wm2)
    latest = weather.latest
    if latest is not None:
        for hour_row in latest.hours:
            if hour_row.target_ts == hour and hour_row.radiation_wm2 is not None:
                return float(hour_row.radiation_wm2)
    return None


@dataclass(frozen=True, slots=True)
class LiveReading:
    """What the balance needs from the running service.

    Parameters
    ----------
    at
        Wall time of the reading.
    room_c, outside_c
        Fresh room and outside temperatures (``None`` when unknown).
    sun_wm2
        Irradiance of the current hour from the stored forecast (``None`` when unknown).
    heat_pump_w
        ``derived/heat_delivered_w`` (``None`` during hot water or when unknown).
    dhw
        Whether the pump is on hot water.
    stove_active
        Whether wood-stove mode is active.
    local_hour
        Local hour of day (for the internal gains).
    """

    at: datetime
    room_c: float | None
    outside_c: float | None
    sun_wm2: float | None
    heat_pump_w: float | None
    dhw: bool
    stove_active: bool
    local_hour: float


def read_live(
    runtime: Runtime,
    settings: Settings,
    weather: WeatherService | None,
    stove_active: bool,
) -> LiveReading:
    """Gather the live inputs of the balance from the store and the stored forecast."""
    moment = runtime.clock()
    snapshot = runtime.store.snapshot(moment)

    def temperature(signal: str | None) -> float | None:
        if signal is None:
            return None
        view = snapshot.get(signal)
        return as_number(view.value) if view is not None and view.fresh else None

    heat = derived.heat_delivered_w(snapshot)
    dhw = derived.dhw_active(snapshot).value is True
    wall = moment.wall
    local = wall.astimezone(ZoneInfo(settings.control_timezone))
    return LiveReading(
        at=wall,
        room_c=temperature(settings.control_room_signal),
        outside_c=temperature(settings.control_outside_signal or HeishaSignal.OUTSIDE_TEMP),
        sun_wm2=current_sun_wm2(weather, settings.history_path, wall),
        heat_pump_w=heat.value,
        dhw=dhw,
        stove_active=stove_active,
        local_hour=local.hour + local.minute / 60.0,
    )


def outside_now(runtime: Runtime, settings: Settings) -> float | None:
    """Return the fresh outside temperature the service measures (``None`` when unknown)."""
    moment = runtime.clock()
    signal = settings.control_outside_signal or HeishaSignal.OUTSIDE_TEMP
    view = runtime.store.view(signal, moment)
    return as_number(view.value) if view is not None and view.fresh else None


def balance_payload(choice: ModelChoice, live: LiveReading) -> Json:
    """Return the body of ``GET api/v1/insight/house/balance``.

    Parameters
    ----------
    choice
        The model the flows come from.
    live
        The live inputs.

    Returns
    -------
    dict
        See ``docs/api-v1.md``. ``storage_w`` is the heat pump plus the sun plus the
        internal gains minus the loss; ``null`` when one of them is unknown or a wood
        stove burns (its heat is not measured).
    """
    model = choice.model
    notes: list[str] = []
    if choice.source == "estimate":
        notes.append("estimate")
    elif not choice.credible:
        notes.append("not_credible")
    loss = (
        None
        if live.room_c is None or live.outside_c is None
        else model.loss_w(live.room_c, live.outside_c)
    )
    if live.room_c is None:
        notes.append("room_unknown")
    if live.outside_c is None:
        notes.append("outside_unknown")
    sun_w = None if live.sun_wm2 is None else model.solar_aperture_m2 * live.sun_wm2
    if live.sun_wm2 is None:
        notes.append("sun_unknown")
    internal = model.internal_gain_w(live.local_hour)
    heat = live.heat_pump_w
    if live.dhw:
        notes.append("dhw_active")
    elif heat is None:
        notes.append("heat_unknown")
    elif heat < 0.0:
        notes.append("defrost")
    if live.stove_active:
        notes.append("stove_active")
    parts = (heat, sun_w, loss)
    storage = (
        None
        if live.stove_active or any(part is None for part in parts)
        else (heat or 0.0) + (sun_w or 0.0) + internal - (loss or 0.0)
    )
    return {
        "at": iso_z(live.at),
        "source": choice.source,
        "credible": choice.credible,
        "room_c": None if live.room_c is None else _rounded(live.room_c),
        "outside_c": None if live.outside_c is None else _rounded(live.outside_c),
        "sun_wm2": None if live.sun_wm2 is None else _rounded(live.sun_wm2, 0),
        "flows": {
            "heat_pump_w": None if heat is None else round(heat),
            "loss_w": None if loss is None else round(loss),
            "sun_w": None if sun_w is None else round(sun_w),
            "internal_w": round(internal),
            "stove_active": live.stove_active,
            "storage_w": None if storage is None else round(storage),
        },
        "ua_w_per_k": _rounded(model.h_air_out),
        "notes": notes,
    }


def _series_time(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("a row has no time")
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError("a row time has no zone")
    return moment.astimezone(UTC)


def _series_value(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("a row value is not a number")
    number = float(value)
    low, high = SERIES_TEMPERATURE_RANGE
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError("a row value is outside the plausible range")
    return round(number, 2)


def checked_series(raw: Any, model: str) -> Json:
    """Return the body of ``GET insight/house/series`` from a learner series file.

    Raises
    ------
    ValueError
        When the file is not a series of ``model``: other schema or columns, too many
        rows, a row that is not ``[time, number|null, number|null]`` within the
        plausible range, or times that do not increase.
    """
    if not isinstance(raw, dict) or raw.get("schema") != SERIES_SCHEMA:
        raise ValueError("not a house series")
    if raw.get("model") != model:
        raise ValueError("the series belongs to another model")
    if raw.get("columns") != SERIES_COLUMNS:
        raise ValueError("unexpected columns")
    step = raw.get("step_s")
    if isinstance(step, bool) or not isinstance(step, int):
        raise ValueError("step_s is not an integer")
    if not SERIES_STEP_RANGE_S[0] <= step <= SERIES_STEP_RANGE_S[1]:
        raise ValueError("step_s is out of range")
    rows = raw.get("rows")
    if not isinstance(rows, list) or not 0 < len(rows) <= SERIES_MAX_ROWS:
        raise ValueError("rows is not a list of 1 to 2000 rows")
    points: list[list[Any]] = []
    previous: datetime | None = None
    for row in rows:
        if not isinstance(row, list) or len(row) != 3:
            raise ValueError("a row is not [time, measured, predicted]")
        moment = _series_time(row[0])
        if previous is not None and moment <= previous:
            raise ValueError("row times do not increase")
        previous = moment
        points.append([iso_z(moment), _series_value(row[1]), _series_value(row[2])])
    return {
        "model": model,
        "step_s": step,
        "from": points[0][0],
        "to": points[-1][0],
        "points": points,
    }


def series_payload(models: Path) -> Json:
    """Return the champion's room series.

    Raises
    ------
    InsightError
        ``404`` ``house_series_missing`` without a champion, without its series file
        or when that file is refused.
    """
    if not house.models_ok(models):
        raise InsightError(404, SERIES_MISSING, "no house model has been promoted yet")
    try:
        found = house.champion(models)
    except house.LearnerFileError as exc:
        raise InsightError(404, SERIES_MISSING, f"the house model cannot be read: {exc}") from None
    if found is None:
        raise InsightError(404, SERIES_MISSING, "no house model has been promoted yet")
    name = found[0].get("model")
    if not isinstance(name, str) or not MODEL_NAME.fullmatch(name):
        raise InsightError(404, SERIES_MISSING, "the champion has no usable name")
    path = models / (name.replace("house-", "series-", 1) + ".json")
    try:
        raw = house.read_untrusted(path, SERIES_MAX_BYTES)
        if raw is None:
            raise InsightError(
                404, SERIES_MISSING, f"{path.name} has not been written; it comes with the next run"
            )
        return checked_series(raw, name)
    except (house.LearnerFileError, ValueError) as exc:
        LOGGER.warning("ignoring a series file: %s", exc)
        raise InsightError(
            404, SERIES_MISSING, f"{path.name} is not usable ({exc}); waiting for the next run"
        ) from None

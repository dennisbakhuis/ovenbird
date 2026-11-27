"""Bodies of the insight router (:mod:`ovenbird.api.insight_api`) and ``insight/runs``.

The house model is the learner's (``ovenbird_sim.learn``): the service passes the
allow-listed keys of its insight file through after a bounds check, so their inner
format belongs to the learner and is documented here as plain JSON. What the service
computes itself (the score, the learner's health, the draft) is modelled. A value the
service copies from a learner file without checking its type is documented with the
type the learner writes and passed through unchanged (:data:`LearnedText`).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, WithJsonSchema

from ovenbird.api.models.base import NUMBER_SCHEMA, ApiModel, JsonObject, Number, absent
from ovenbird.api.models.config import ValidateResult

TEXT_OR_NULL: dict[str, Any] = {"anyOf": [{"type": "string"}, {"type": "null"}]}
BOOL_OR_NULL: dict[str, Any] = {"anyOf": [{"type": "boolean"}, {"type": "null"}]}
NUMBER_OR_NULL: dict[str, Any] = {"anyOf": [NUMBER_SCHEMA, {"type": "null"}]}
PAIR_OR_NULL: dict[str, Any] = {
    "anyOf": [
        {
            "type": "array",
            "prefixItems": [NUMBER_SCHEMA, NUMBER_SCHEMA],
            "minItems": 2,
            "maxItems": 2,
        },
        {"type": "null"},
    ]
}

LearnedText = Annotated[Any, WithJsonSchema(TEXT_OR_NULL)]
LearnedBool = Annotated[Any, WithJsonSchema(BOOL_OR_NULL)]
LearnedNumber = Annotated[Any, WithJsonSchema(NUMBER_OR_NULL)]
LearnedPair = Annotated[Any, WithJsonSchema(PAIR_OR_NULL)]

type ScoreState = Literal["learning", "no_floor_area", "ready"]
type ModelUse = Literal["off", "shadow", "on"]
type ModelGuard = Literal[
    "weather_off",
    "model_missing",
    "model_not_credible",
    "model_stale",
    "model_error_high",
    "forecast_stale",
    "room_untrusted",
    "stove_active",
    "stove_tail",
]
type ModelPlanStatus = Literal[
    "issued",
    "inside_dead_zone",
    "crossing_zero",
    "forecast_gap",
    "forecast_mismatch",
    "model_invalid",
    "planner_error",
]
type ModelPlanReason = Literal["plan_setback", "plan_preheat"]


class InsightDay(ApiModel):
    """One local day of energy, runs, temperatures and comfort."""

    date: str
    from_: str = Field(alias="from")
    to: str
    hours: Number
    partial: bool
    coverage: Number
    electric_kwh: Number | None
    heat_kwh: Number | None
    cop: Number | None
    dhw_electric_kwh: Number | None
    dhw_heat_kwh: Number | None
    compressor_starts: int | None
    run_s: int | None
    defrosts: int | None
    defrost_s: int | None
    dhw_runs: int | None
    dhw_s: int | None
    outside_mean_c: Number | None
    outside_min_c: Number | None
    room_mean_c: Number | None
    room_min_c: Number | None
    comfort_c: Number
    below_comfort_kh: Number | None
    setpoint_mean_c: Number | None
    setpoint_changes: int | None
    writes: int


class InsightDaily(ApiModel):
    """``GET insight/daily``: the last days, oldest first."""

    timezone: str
    band_below_k: Number
    room_signal: str | None
    days: list[InsightDay]


class RunBin(ApiModel):
    """A histogram bin of run lengths (``to_min`` ``null`` for the last, open bin)."""

    from_min: int
    to_min: int | None
    runs: int


class RunStats(ApiModel):
    """Compressor run statistics of a span."""

    runs: int
    censored: int
    short_runs: int
    short_share: Number | None
    median_min: Number | None
    mean_min: Number | None
    longest_min: Number | None
    min_off_min: Number | None
    histogram: list[RunBin]


class RunDay(ApiModel):
    """The run statistics of one local day."""

    date: str
    from_: str = Field(alias="from")
    to: str
    partial: bool
    runs: int
    censored: int
    short_runs: int
    short_share: Number | None
    median_min: Number | None
    mean_min: Number | None
    longest_min: Number | None
    min_off_min: Number | None
    histogram: list[RunBin]


class InsightRuns(ApiModel):
    """``GET insight/runs``: compressor runs per local day and in total."""

    timezone: str
    short_run_min: Number
    signal: str
    total: RunStats
    days: list[RunDay]


class ScoreBand(ApiModel):
    """An indicative band and the heat loss per m2 it lies below."""

    band: str
    below_w_per_m2: Number | None


class HouseScore(ApiModel):
    """The indicative insulation score, recomputed for the current floor area."""

    design_indoor_c: Number
    design_outside_c: Number
    floor_area_m2: Number | None
    bands: list[ScoreBand]
    indicative: bool
    note: str
    state: ScoreState
    heat_loss_w: int = absent()
    w_per_m2: Number = absent()
    band: str = absent()
    interval_90: tuple[Number, Number] = absent()
    band_interval: tuple[str, str] = absent()
    message: str = absent()


class LastRun(ApiModel):
    """The allow-listed essentials of the learner's last run (``status.json``)."""

    at: str | None = absent()
    outcome: str | None = absent()
    model: str | None = absent()
    champion: str | None = absent()
    missing: list[str] | None = absent()
    message: str | None = absent()
    error: str | None = absent()
    runtime_s: Number | None = absent()
    interval_h: Number | None = absent()


class LearnerHealth(ApiModel):
    """When the learner last ran and whether that is too long ago."""

    last_run_at: str | None
    age_h: Number | None
    interval_h: Number
    stale_after_h: Number
    stale: bool


class Champion(ApiModel):
    """The promoted model named by the learner's ``current.json``."""

    model: LearnedText
    promoted_at: LearnedText


class HouseWaiting(ApiModel):
    """``GET insight/house`` before a model is promoted: what is missing."""

    state: Literal["learning", "not_run"]
    missing: list[str]
    last_run: LastRun | None
    learner: LearnerHealth


class HouseReady(ApiModel):
    """``GET insight/house`` with a promoted model: the learner's insight and the score.

    The learner's keys are passed through; ``proposal`` gains ``current_curve`` and
    ``stale`` (whether the curve changed since the run).
    """

    schema_: Any = absent("schema")
    model: Any = absent()
    data: Any = absent()
    ua: JsonObject = absent()
    time_constant_h: Any = absent()
    solar_aperture_m2: Any = absent()
    internal_gains_w: Any = absent()
    balance_temperature_c: Any = absent()
    signature: Any = absent()
    credibility: JsonObject = absent()
    validation: Any = absent()
    error_trend: Any = absent()
    daily_error: Any = absent()
    proposal: JsonObject = absent()
    events: Any = absent()
    limits: Any = absent()
    provenance: Any = absent()
    score: HouseScore
    state: Literal["ready"]
    champion: Champion
    last_run: LastRun | None
    learner: LearnerHealth


type HouseReport = HouseWaiting | HouseReady


class HouseHistoryModel(ApiModel):
    """A promoted model of the learner's index and its score at the current floor area."""

    model: LearnedText
    data_to: LearnedText
    generated: LearnedText
    champion: bool
    ua_w_per_k: LearnedNumber
    ua_interval_90: LearnedPair
    time_constant_h: LearnedNumber
    credible: LearnedBool
    room_rmse_24h_k: LearnedNumber
    score: HouseScore


class HouseHistory(ApiModel):
    """``GET insight/house/history``: every promoted model."""

    floor_area_m2: Number | None
    models: list[HouseHistoryModel]


class CurveChange(ApiModel):
    """A heating curve as a configuration change (``null`` when there is none)."""

    control_curve: list[tuple[Number, Number]] | None


class ProposalDraft(ApiModel):
    """``POST insight/house/proposal/draft``: the proposal as a configuration draft.

    ``points`` is the learner's; ``validation`` is ``null`` without a configuration store.
    """

    label: str
    model: str
    comment: str
    changes: CurveChange
    current: CurveChange
    stale: bool
    credible: bool
    points: Any
    validation: ValidateResult | None


type RunState = Literal["idle", "running", "unavailable"]
type RunFailureReason = Literal["timeout", "memory", "exit", "spawn"]


class HouseRunLast(ApiModel):
    """The learner's last run as ``status.json`` reports it."""

    at: str
    outcome: str
    message: str | None
    runtime_s: Number | None
    model: str | None


class HouseRunFailure(ApiModel):
    """The service's last failed attempt to run the learner."""

    at: str
    reason: RunFailureReason
    detail: str


class HouseRun(ApiModel):
    """``GET`` and ``POST insight/house/run``: the embedded learner's state and schedule."""

    state: RunState
    enabled: bool
    started_at: str | None
    next_due_at: str | None
    interval_h: Number
    last: HouseRunLast | None
    failure: HouseRunFailure | None


type HouseSource = Literal["model", "estimate"]
type WhatIfLimit = Literal["max_supply", "no_heat_needed"]
type BalanceNote = Literal[
    "estimate",
    "not_credible",
    "room_unknown",
    "outside_unknown",
    "sun_unknown",
    "dhw_active",
    "heat_unknown",
    "defrost",
    "stove_active",
]


class HouseSeries(ApiModel):
    """``GET insight/house/series``: the room, measured and as predicted 24 h earlier.

    ``points`` are ``[time, measured, predicted]`` rows, oldest first; either value is
    ``null`` where it is unknown (the prediction exists only inside the learner's
    held-out block).
    """

    model: str
    step_s: int
    from_: str = Field(alias="from")
    to: str
    points: list[tuple[str, Number | None, Number | None]]


class WhatIfInputs(ApiModel):
    """The scenario of a what-if, with the defaults filled in."""

    outside_c: Number
    comfort_c: Number
    sun_wm2: Number
    stove_w: Number


class WhatIfDrift(ApiModel):
    """The room temperature with the heating off, from the comfort steady state."""

    hours: int
    step_s: int
    room_c: list[Number]


class HouseWhatIf(ApiModel):
    """``GET insight/house/whatif``: what the house needs to hold comfort in a scenario."""

    source: HouseSource
    model: str | None
    credible: bool
    inputs: WhatIfInputs
    heat_demand_w: Number
    free_heat_w: Number
    loss_w: Number
    loop_mean_c: Number
    supply_c: Number
    curve_c: Number
    max_supply_c: Number
    limited_by: list[WhatIfLimit]
    balance_outside_c: Number
    drift: WhatIfDrift
    time_constant_h: Number | None


class BalanceFlows(ApiModel):
    """The heat flows of the house in W; ``null`` where an input is unknown."""

    heat_pump_w: Number | None
    loss_w: Number | None
    sun_w: Number | None
    internal_w: Number
    stove_active: bool
    storage_w: Number | None


class HouseBalance(ApiModel):
    """``GET insight/house/balance``: the heat balance of the house right now."""

    at: str
    source: HouseSource
    credible: bool
    room_c: Number | None
    outside_c: Number | None
    sun_wm2: Number | None
    flows: BalanceFlows
    ua_w_per_k: Number
    notes: list[BalanceNote]


class ModelPlanVerdict(ApiModel):
    """The guards of the model plan: ``ok`` when none blocks, else the failing ones in order."""

    ok: bool
    blocks: list[ModelGuard]


class ModelPlanBounds(ApiModel):
    """The model plan bounds, the planner horizon and the error limit of the model."""

    max_setback_k: Number
    max_preheat_k: Number
    horizon_h: Number
    max_rmse_k: Number


class ModelPlanNow(ApiModel):
    """The latest planner evaluation.

    ``offset_k`` is the offset the planner issued (``0`` without a slice); ``applied`` is
    true only when the controller applied a model offset at its latest tick (never in
    ``shadow``). ``rise_*``, ``fall_*``, ``solar_k`` and ``outside_k`` are the predicted
    drift of the room (K) and when it peaks; ``null`` when the planner could not predict.
    """

    at: str
    status: ModelPlanStatus
    offset_k: Number
    applied: bool
    reason: ModelPlanReason | None
    valid_until: str | None
    rise_k: Number | None
    rise_at: str | None
    fall_k: Number | None
    fall_at: str | None
    solar_k: Number | None
    outside_k: Number | None


class ModelPlanHistory(ApiModel):
    """The computed offsets of the last 7 days from the 15 min rollups.

    ``points`` are ``[time, offset_k, applied]`` rows, oldest first: ``offset_k`` is
    ``null`` where a guard blocked or nothing was recorded, ``applied`` is ``1`` when the
    controller applied the offset for most of the interval, else ``0``; empty when
    nothing was recorded.
    """

    step_s: int
    from_: str = Field(alias="from")
    to: str
    points: list[tuple[str, Number | None, int | None]]


class HouseControl(ApiModel):
    """``GET insight/house/control``: the model plan switch, its guards, latest result, history."""

    use: ModelUse
    verdict: ModelPlanVerdict
    model: str | None
    model_rmse_k: Number | None
    bounds: ModelPlanBounds
    now: ModelPlanNow | None
    history: ModelPlanHistory

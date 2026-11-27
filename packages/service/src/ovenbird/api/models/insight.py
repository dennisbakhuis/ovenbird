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


type GateNeed = Literal[
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
]
type GateSource = Literal["fitted", "revalidated", "legacy"]


class LearnedGate(ApiModel):
    """One credibility gate as the learner wrote it (checked by the service).

    ``checks`` maps each check to ``{ok, value, limit, ...}`` (the learner's format);
    ``needed`` holds the codes of what fails (codes the service does not know are
    dropped); ``uses`` names what the gate guards.
    """

    ok: bool
    needed: list[GateNeed]
    message: str | None
    reasons: list[str]
    uses: list[str]
    checks: JsonObject


class LearnedGates(ApiModel):
    """The three credibility gates of a model as the learner judged it."""

    heat_loss: LearnedGate
    dynamics: LearnedGate
    sun: LearnedGate


class ModelGate(ApiModel):
    """One gate of the champion now.

    ``source`` is ``revalidated`` (the last run's check of this model), ``fitted``
    (its own gates when it was fitted) or ``legacy`` (a model fitted before the gates:
    its old credibility as the heat-loss gate, its old prediction check as the dynamics
    gate, the sun gate not judged until the next run). ``message`` says what fails
    (``null`` when ``ok``).
    """

    ok: bool
    needed: list[GateNeed]
    message: str | None
    source: GateSource


class HouseGates(ApiModel):
    """The champion's gates now, one per use.

    ``heat_loss`` (U) guards the insulation score, the curve proposal, the what-if
    steady state and the live balance; ``dynamics`` (D) the what-if cool-down and the
    room-target planner; ``sun`` (S) the water planner.
    """

    heat_loss: ModelGate
    dynamics: ModelGate
    sun: ModelGate


class ChampionRevalidation(ApiModel):
    """The latest run's check of the model ``current.json`` names (``status.json``).

    ``source`` is ``held_out`` when that run promoted the model (its own held-out
    validation) and ``revalidated`` when the run kept it and scored it again on the
    newest held-out days (``from`` to ``to``; ``in_sample`` when the model had seen
    part of them). ``gates`` are the model's three gates as of that run (``null`` from
    a learner before the gates); ``credible`` is its heat-loss gate and ``reasons``
    say what fails there. Errors are room RMSE in K over the first 24 h, ``skill`` is
    ``1 - model / persistence`` over ``skill_horizon_h``, ``series_*`` the 24 h-ahead
    error and bias of the model's room series.
    """

    model: str
    at: str | None
    source: Literal["held_out", "revalidated"]
    data_to: str | None
    fitted_to: str | None
    from_: str | None = Field(alias="from")
    to: str | None
    origins: int
    in_sample: bool
    room_rmse_k: Number | None
    persistence_room_rmse_k: Number | None
    skill_horizon_h: Number | None
    skill: Number | None
    series_rmse_k: Number | None
    series_bias_k: Number | None
    credible: bool
    reasons: list[str]
    gates: LearnedGates | None


class LastRun(ApiModel):
    """The allow-listed essentials of the learner's last run (``status.json``).

    ``warnings`` are data notes the owner should see (a wood-stove episode without a
    recorded end that was capped); ``champion_revalidation`` is ``null`` when the run
    had no champion or the learner wrote none that the service accepts.
    """

    at: str | None = absent()
    outcome: str | None = absent()
    model: str | None = absent()
    champion: str | None = absent()
    missing: list[str] | None = absent()
    message: str | None = absent()
    error: str | None = absent()
    runtime_s: Number | None = absent()
    interval_h: Number | None = absent()
    warnings: list[str] | None = absent()
    champion_revalidation: ChampionRevalidation | None = absent()


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
    ``stale`` (whether the curve changed since the run). ``revalidation`` is the last
    run's check of this model (``null`` when the last run checked another or none).
    ``gates`` are the model's three gates now (:class:`HouseGates`): the
    re-validation's when there is one, else the insight's frozen
    ``credibility.gates``. ``credible`` is the heat-loss gate; the score and the
    proposal follow it. The learner's ``credibility`` holds ``credible`` (the heat-loss
    gate as fitted), ``gates`` (:class:`LearnedGates`) and the detail.
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
    heat_capacity_kwh_per_k: Any = absent()
    capacities_kwh_per_k: Any = absent()
    emitter_time_constant_h: Any = absent()
    structure: Any = absent()
    excitation: JsonObject = absent()
    credibility: JsonObject = absent()
    validation: Any = absent()
    at_bound: Any = absent()
    error_trend: Any = absent()
    daily_error: Any = absent()
    proposal: JsonObject = absent()
    events: Any = absent()
    limits: Any = absent()
    provenance: Any = absent()
    score: HouseScore
    state: Literal["ready"]
    credible: bool
    gates: HouseGates
    revalidation: ChampionRevalidation | None
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
    "stove_tail",
]
type SeriesEventKind = Literal["stove", "stove_mode", "excluded_day"]


class SeriesEvent(ApiModel):
    """A known event in reach of the series: the anomaly ``from``-``to`` and its tail."""

    kind: SeriesEventKind
    from_: str = Field(alias="from")
    to: str
    tail_to: str


class HouseSeries(ApiModel):
    """``GET insight/house/series``: the room, measured and as predicted 24 h earlier.

    ``points`` are ``[time, measured, predicted]`` rows, oldest first, starting at the
    first prediction; either value is ``null`` where it is unknown. The prediction is
    also ``null`` where its 24 h path touches an event of ``events`` (shade them).
    Predictions from origins before ``out_of_sample_from`` are in-sample (the model had
    seen those days). ``rmse_k`` and ``bias_k`` (predicted minus measured) summarise
    the ``compared_points`` out-of-sample points with both values; ``null`` without any
    (and for files of older learners).
    """

    model: str
    step_s: int
    from_: str = Field(alias="from")
    to: str
    points: list[tuple[str, Number | None, Number | None]]
    events: list[SeriesEvent]
    out_of_sample_from: str | None
    rmse_k: Number | None
    bias_k: Number | None
    compared_points: int


class WhatIfInputs(ApiModel):
    """The scenario of a what-if, with the defaults filled in."""

    outside_c: Number
    comfort_c: Number
    sun_wm2: Number
    stove_w: Number


class WhatIfDrift(ApiModel):
    """The room temperature with the heating off, from the comfort steady state.

    ``credible`` is the model's dynamics gate (always ``false`` for an estimate).
    """

    credible: bool
    hours: int
    step_s: int
    room_c: list[Number]


class HouseWhatIf(ApiModel):
    """``GET insight/house/whatif``: what the house needs to hold comfort in a scenario.

    ``credible`` is the model's heat-loss gate (the steady state);
    ``drift.credible`` its dynamics gate (the cool-down).
    """

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
    """``GET insight/house/balance``: the heat balance of the house right now.

    ``credible`` is the model's heat-loss gate.
    """

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

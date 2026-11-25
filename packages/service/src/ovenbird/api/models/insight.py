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

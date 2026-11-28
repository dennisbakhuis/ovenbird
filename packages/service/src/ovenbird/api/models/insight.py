"""Bodies of the insight router (:mod:`ovenbird.api.insight_api`) and ``insight/runs``."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ovenbird.api.models.base import ApiModel, Number


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


type BasicsStatusName = Literal["collecting", "provisional", "credible"]
type HeatLossReasonName = Literal[
    "no_room_signal",
    "too_few_days",
    "span_too_small",
    "slope_not_positive",
    "slope_implausible",
    "too_uncertain",
    "few_days",
    "narrow_span",
]
type EmitterReasonName = Literal[
    "no_room_signal",
    "too_few_hours",
    "slope_not_positive",
    "slope_implausible",
    "too_uncertain",
    "few_hours",
    "narrow_span",
]
type PointUseName = Literal["used", "outlier", "near_balance"]
type RoomSourceName = Literal["measured", "comfort"]
type OutsideSourceName = Literal["filtered", "measured"]
type HeatNowReasonName = Literal["hot_water", "unknown"]


class HeatLossPoint(ApiModel):
    """One 48 h window (two consecutive local days) of the heat-loss fit."""

    first_date: str
    last_date: str
    delta_k: Number
    heat_w: Number
    outside_c: Number
    room_c: Number
    use: PointUseName


class HeatLossExclusions(ApiModel):
    """Complete days with data left out of the heat-loss fit, by reason."""

    low_coverage: int
    stove: int
    no_heating: int
    away: int


class HeatLoss(ApiModel):
    """The heat-loss fit ``P = H x dT - G``; the figures are ``null`` while collecting."""

    status: BasicsStatusName
    reasons: list[HeatLossReasonName]
    h_w_per_k: Number | None
    h_low_w_per_k: Number | None
    h_high_w_per_k: Number | None
    offset_w: Number | None
    balance_offset_k: Number | None
    balance_c: Number | None
    days_used: int
    points_used: int
    outlier_points: int
    near_balance_points: int
    span_k: Number | None
    outside_min_c: Number | None
    outside_max_c: Number | None
    room_mean_c: Number | None
    residual_w: Number | None
    first_date: str | None
    last_date: str | None
    excluded: HeatLossExclusions
    points: list[HeatLossPoint]


class LossEstimate(ApiModel):
    """The heat loss at one outside and room temperature, with its 95 % band."""

    at: str | None
    outside_c: Number
    room_c: Number
    delta_k: Number
    loss_w: Number
    low_w: Number
    high_w: Number
    beyond_data: bool


class LossNow(ApiModel):
    """The heat loss now, at the coming night's forecast minimum and at the design temperature."""

    room_source: RoomSourceName
    outside_source: OutsideSourceName | None
    forecast_available: bool
    now: LossEstimate | None
    night: LossEstimate | None
    design: LossEstimate | None


class HeatDelivered(ApiModel):
    """Heat into the space-heating loop now and over the last 24 h."""

    now_w: Number | None
    now_reason: HeatNowReasonName | None
    mean_24h_w: Number | None
    coverage_24h: Number


class EmitterRow(ApiModel):
    """Expected steady heat at one supply temperature, next to the heat loss now."""

    supply_c: Number
    mean_water_c: Number
    heat_w: Number
    low_w: Number
    high_w: Number
    loss_now_w: Number | None
    margin_w: Number | None


class Emitter(ApiModel):
    """The emitter figure ``Q = K x (T_water - T_room)`` and what it implies."""

    status: BasicsStatusName
    reasons: list[EmitterReasonName]
    k_w_per_k: Number | None
    k_low_w_per_k: Number | None
    k_high_w_per_k: Number | None
    hours_used: int
    days_used: int
    span_k: Number | None
    flow_l_min: Number | None
    room_c: Number
    setpoint_min_c: Number
    setpoint_max_c: Number
    table: list[EmitterRow]
    balance_supply_c: Number | None
    balance_mean_water_c: Number | None
    balance_in_range: bool | None


class HeatPumpHeat(ApiModel):
    """How much heat the house gets from the heat pump."""

    delivered: HeatDelivered
    emitter: Emitter


class WeatherBinRow(ApiModel):
    """Heat production in one 2 K bin of the daily outside mean."""

    from_c: Number
    to_c: Number
    days: int
    heat_w: Number
    electric_w: Number | None
    cop: Number | None
    few_days: bool


class InsightBasics(ApiModel):
    """``GET insight/basics``: heat loss and heat from the heat pump (``null`` parts when off)."""

    enabled: bool
    computed_at: str | None
    timezone: str
    room_signal: str | None
    design_outside_c: Number
    heat_loss: HeatLoss | None
    loss_now: LossNow | None
    heat_pump: HeatPumpHeat | None
    by_weather: list[WeatherBinRow] | None

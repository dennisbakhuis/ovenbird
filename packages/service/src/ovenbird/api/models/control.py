"""Decisions, alarms, commands and the control state: the models several routers share.

Also the bodies of the control router (:mod:`ovenbird.api.control_api`): pause and
resume, wood-stove mode, boost, away, the feature list, releasing a hold, the audit
trail and the decision series.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ovenbird.api.models.base import ApiModel, JsonObject, Number, Scalar

type ModeName = Literal["off", "shadow", "auto", "manual"]
type SeverityName = Literal["info", "warning", "critical"]
type MonitorState = Literal["ok", "pending", "active", "unknown"]
type AlarmEventName = Literal["raised", "cleared", "started", "expired", "released", "recognised"]
type StoveSourceName = Literal["auto", "manual"]
type StoveTriggerName = Literal["level", "rise", "manual", "handover"]
type DirectionName = Literal["above", "below"]
type DayShiftUseName = Literal["off", "shadow", "on"]
type DayShiftPhaseName = Literal["idle", "boost", "setback", "recovery", "blocked"]
type DayShiftReasonName = Literal[
    "off",
    "outside_windows",
    "sun_forecast",
    "sun_low",
    "outside_mild",
    "outside_cold",
    "outside_unknown",
    "forecast_missing",
    "night_after_boost",
    "no_boost_today",
    "night_cold",
    "recovery_lead",
    "room_below_target",
    "room_warm",
    "forecast_stale",
    "room_untrusted",
    "stove_active",
    "stove_tail",
    "away",
]
type AwayPhaseName = Literal["away", "returning"]
type FeatureName = Literal[
    "weather_compensation",
    "room_feedback",
    "slow_start",
    "minimum_run",
    "pump_duty",
    "quiet",
    "stove",
    "dayshift",
    "summer",
    "away",
    "boost",
    "house_basics",
    "starts_alarm",
]
type FeatureStateName = Literal["off", "shadow", "on", "active_now"]
type PlanGuardName = Literal[
    "forecast_stale", "room_untrusted", "stove_active", "stove_tail", "away"
]


class Term(ApiModel):
    """One named contribution to the water setpoint."""

    name: str
    raw: Number
    value: Number
    unit: str
    note: str


class InputRef(ApiModel):
    """An input a decision used, with its provenance."""

    signal: str
    value: Scalar
    age: Number | None
    fresh: bool
    source: str | None
    issued: str | None


class Intent(ApiModel):
    """A command intent returned with a decision record."""

    kind: str
    value: int
    reason: str


class RecordInstant(ApiModel):
    """The tick's instant on both clock axes."""

    monotonic: Number
    wall: str


class DecisionRecord(ApiModel):
    """The core's complete explanation of one controller tick (schema 1)."""

    schema_: int = Field(alias="schema")
    at: RecordInstant
    controller: str
    mode: ModeName
    ladder: str
    terms: list[Term]
    pre_round: Number | None
    setpoint: int | None
    binding: str | None
    flip_distance: Number | None
    flip_input: str | None
    inputs_used: list[InputRef]
    controller_state: dict[str, Scalar]
    reason: str
    note: str
    intents: list[Intent]
    actor: str | None


class ArbiterEntry(ApiModel):
    """What the arbiter decided for one intent."""

    kind: str
    intent: int | None
    actual: int | None
    action: str
    reason: str


class CommandEvent(ApiModel):
    """A command life-cycle event as the adapter reports it (with a decision, a write)."""

    at: str
    kind: str
    value: int
    status: str
    attempt: int
    detail: str
    topic: str | None
    payload: str | None


class Decision(ApiModel):
    """One journalled decision: the summary columns, the arbiter, commands and the record."""

    at: str
    controller: str
    mode: ModeName
    ladder: str
    reason: str
    setpoint: int | None
    note: str
    arbiter: list[ArbiterEntry]
    commands: list[CommandEvent]
    config_version: int | None
    record: DecisionRecord


class Alarm(ApiModel):
    """An active alarm."""

    code: str
    severity: SeverityName
    message: str
    since: str
    detail: JsonObject


class AlarmEvent(ApiModel):
    """A journalled alarm or hold transition."""

    at: str
    code: str
    severity: SeverityName
    event: AlarmEventName
    message: str
    detail: JsonObject


class Monitor(ApiModel):
    """The result of one safety monitor."""

    code: str
    severity: SeverityName
    status: MonitorState
    message: str
    value: Number | str | None
    since: str | None
    limit: Number | None
    unit: str | None
    direction: DirectionName | None


class Safety(ApiModel):
    """The safety monitor: overall level and every monitor."""

    level: str
    interval_s: Number
    monitors: list[Monitor]


class Corrections(ApiModel):
    """Recent corrective writes against their limit."""

    recent: int
    limit: int
    window_s: Number


class InFlight(ApiModel):
    """The command published and not yet verified."""

    kind: str
    value: int
    attempt: int
    sent_at: str
    corrective: bool


class Budget(ApiModel):
    """Today's write budget."""

    day: str | None
    used: int
    limit: int
    safety_reserve: int


class AdapterStatus(ApiModel):
    """The command adapter: holds, queue, verification, budget and counters."""

    setpoint_register: str
    hold: str | None
    hold_until: str | None
    hold_latched: bool
    hold_incidents: int
    safety_hold: list[str]
    corrections: Corrections
    in_flight: InFlight | None
    queued: dict[str, int]
    verified: dict[str, int | None]
    budget: Budget
    counters: dict[str, int]


class RoomStatus(ApiModel):
    """The room input: profile, held and alive ages, link."""

    signal: str
    profile: str
    step_k: Number | None
    max_age_s: Number | None
    report_interval_s: Number | None
    silence_limit_s: Number | None
    liveness: list[str]
    crosscheck: str | None
    value: Number | None
    fresh: bool
    held_s: Number | None
    alive_s: Number | None
    alive_by: str | None
    link_up: bool | None
    authority: Number | None
    plausible: bool | None


class StoveRequest(ApiModel):
    """A manual wood-stove request."""

    on: bool
    until: str | None
    actor: str
    at: str


class StoveStatus(ApiModel):
    """Wood-stove mode: configuration, state and the request."""

    enabled: bool
    auto: bool
    active: bool
    source: StoveSourceName | None
    trigger: StoveTriggerName | None
    since: str | None
    entry_c: Number | None
    integral_k: Number | None
    blocked: bool
    level_blocked: bool
    reentry_wait: bool
    backoff_k: Number | None
    enter_c: Number | None
    exit_c: Number | None
    reference_c: Number | None
    request: StoveRequest | None


class BoostRequest(ApiModel):
    """A manual boost: an offset to comfort or an absolute room target, until a time."""

    offset_k: Number | None
    target_c: Number | None
    until: str
    actor: str
    at: str


class BoostStatus(ApiModel):
    """The boost: settings, whether it runs (or is paused, and why) and the request."""

    enabled: bool
    active: bool
    paused: str | None
    shift_k: Number | None
    target_c: Number | None
    remaining_s: Number | None
    default_s: Number
    default_k: Number
    request: BoostRequest | None


class AwayRequest(ApiModel):
    """An away period."""

    target_c: Number
    until: str
    comfort_lead_s: Number
    comfort_from: str
    actor: str
    at: str


class AwayStatus(ApiModel):
    """Away: settings, phase (away or returning to comfort) and the request."""

    enabled: bool
    active: bool
    phase: AwayPhaseName | None
    paused: str | None
    target_c: Number | None
    until: str | None
    comfort_from: str | None
    default_target_c: Number
    default_lead_s: Number
    request: AwayRequest | None


class SummerStatus(ApiModel):
    """The summer switch: settings, the slow outside mean and whether heating is off."""

    enabled: bool
    active: bool
    mean_c: Number | None
    off_c: Number | None
    on_c: Number | None
    mean_tau_s: Number | None
    warming_up: bool


class ControlStatus(ApiModel):
    """The control loop's state."""

    mode: ModeName
    configured_mode: ModeName
    paused: bool
    reset_pending: bool
    releasing: bool
    config_version: int | None
    controller: str
    interval_s: Number
    ticks: int
    restored_state: bool
    publishing: bool
    refusals: list[str]
    alarms: list[Alarm]
    safety: Safety | None
    adapter: AdapterStatus | None
    room: RoomStatus | None
    stove: StoveStatus
    boost: BoostStatus
    away: AwayStatus
    summer: SummerStatus


class ConfigMode(ApiModel):
    """The configured and effective mode, pause and pending reset."""

    configured: ModeName
    effective: ModeName
    paused: bool
    reset_pending: bool


class ModeChange(ApiModel):
    """``POST control/pause`` and ``control/resume``: the new mode and the control state."""

    mode: ConfigMode
    control: ControlStatus | None


class StoveResult(ApiModel):
    """``POST control/stove``: the accepted request and wood-stove mode."""

    request: StoveRequest
    stove: StoveStatus


class BoostResult(ApiModel):
    """``POST`` and ``DELETE control/boost``: the request accepted or ended, and the boost."""

    request: BoostRequest | None
    boost: BoostStatus


class AwayResult(ApiModel):
    """``PUT`` and ``DELETE control/away``: the request accepted or ended, and away."""

    request: AwayRequest | None
    away: AwayStatus


class FeatureEntry(ApiModel):
    """One switchable feature and its state."""

    id: FeatureName
    state: FeatureStateName
    enabled: bool
    active: bool
    experimental: bool
    on_available: bool


class Features(ApiModel):
    """``GET control/features``: every feature with its state."""

    mode: ModeName
    features: list[FeatureEntry]


class ReleasedHold(ApiModel):
    """The hold an operator released."""

    reason: str
    until: str | None
    latched: bool
    incident: int


class ReleaseHoldResult(ApiModel):
    """``POST control/release-hold``: the released hold and what still holds."""

    released: ReleasedHold
    by: str
    hold: str | None
    safety_hold: list[str]
    control: ControlStatus


class AuditEvent(ApiModel):
    """One audit row."""

    at: str
    actor: str
    source_ip: str | None
    action: str
    detail: JsonObject


class AuditPage(ApiModel):
    """``GET audit``: audit events in a window."""

    from_: str = Field(alias="from")
    to: str
    limit: int
    events: list[AuditEvent]


class DecisionSeries(ApiModel):
    """``GET decisions/series``: the controller's decisions as columns over time."""

    from_: str = Field(alias="from")
    to: str
    step: int
    at: list[str]
    setpoint: list[Number | None]
    pre_round: list[Number | None]
    curve: list[Number | None]
    room_feedback: list[Number | None]
    plan: list[Number | None]
    start_ramp: list[Number | None]
    cycling_floor: list[Number | None]
    stove: list[Number | None]
    other: list[Number | None]
    safety_delta: list[Number | None]
    safety_low: list[Number | None]
    safety_high: list[Number | None]
    reason: list[str | None]
    binding: list[str | None]
    ladder: list[str | None]
    config_version: list[int | None]


class DayShiftNext(ApiModel):
    """The next change of phase the day shift's schedule allows."""

    at: str
    phase: DayShiftPhaseName


class DayShiftWindows(ApiModel):
    """The local windows of the day shift and the end of the coming set-back."""

    day_start: str
    day_end: str
    night_start: str
    night_end: str
    comfort_at: str
    setback_end: str | None
    timezone: str


class DayShiftForecast(ApiModel):
    """What the day shift read of the forecast at its latest evaluation."""

    issued_at: str | None
    hours: int
    sun_wm2: Number | None
    sun_limit_wm2: Number
    outside_c: Number | None
    outside_min_c: Number | None
    outside_limit_c: Number
    night_min_c: Number | None
    night_limit_c: Number


class DayShift(ApiModel):
    """``GET control/dayshift``: the sun day shift's mode, phase, offset and reasons."""

    mode: DayShiftUseName
    configured: DayShiftUseName
    on_available: bool
    experimental: bool
    phase: DayShiftPhaseName
    offset_k: Number
    desired_k: Number
    applied_k: Number
    reasons: list[DayShiftReasonName]
    guards: list[PlanGuardName]
    evaluated_at: str | None
    valid_until: str | None
    next_change: DayShiftNext | None
    boosted_today: bool
    windows: DayShiftWindows
    forecast: DayShiftForecast | None

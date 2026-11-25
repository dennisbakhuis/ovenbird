"""Bodies of the supervision routers: trial and release, shadow, notifications, system.

Some objects come back from the facts store, which keeps them with sorted keys, so
their key order depends on where they were read; they are passed through as they
are and documented with the model they follow (:func:`kept`).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, WithJsonSchema

from ovenbird.api.models.base import REF_PREFIX, ApiModel, JsonObject, Number, Scalar, absent
from ovenbird.api.models.control import ControlStatus, ModeName
from ovenbird.api.models.insight import RunStats

type CheckStatusName = Literal["ok", "warn", "fail"]
type CheckPhaseName = Literal["go_live", "trial"]
type CriterionStatusName = Literal["ok", "fail", "info", "unknown"]
type TrialStateName = Literal["no_trial", "running", "ended_early", "complete", "not_a_trial"]
type EnvelopeStateName = Literal["not_declared", "declared", "proven"]
type NotifyStateName = Literal["not_configured", "untested", "ok", "failing"]
type CaptureRefusalName = Literal["controlling", "in_use", "in_progress"]
type ReleaseOutcomeName = Literal["running", "ok", "incomplete", "interrupted"]
type ReleaseItemStatusName = Literal[
    "pending",
    "queued",
    "sent",
    "retry",
    "verified",
    "unchanged",
    "not_managed",
    "planned",
    "missing",
    "refused",
    "failed",
    "dropped",
    "timeout",
    "changed",
]


def kept(name: str) -> WithJsonSchema:
    """Document a stored object passed through unchanged: the model ``name`` or ``null``."""
    return WithJsonSchema({"anyOf": [{"$ref": f"{REF_PREFIX}{name}"}, {"type": "null"}]})


class TrialCheck(ApiModel):
    """One item of the go-live checklist; ``evidence`` differs per item."""

    id: str
    phase: CheckPhaseName
    status: CheckStatusName
    message: str
    evidence: JsonObject


class NotReady(ApiModel):
    """A go-live item that is not ok."""

    id: str
    message: str


class CheckCounts(ApiModel):
    """Checklist items per status."""

    ok: int
    warn: int
    fail: int


class CheckGroup(ApiModel):
    """One phase of the checklist: readiness, counts and item ids."""

    ready: bool
    counts: CheckCounts
    ids: list[str]


class CheckGroups(ApiModel):
    """The checklist per phase."""

    go_live: CheckGroup
    trial: CheckGroup


class TrialPeriod(ApiModel):
    """One period's figures: room, outside, runs and writes."""

    from_: str = Field(alias="from")
    to: str
    days: Number
    room_mean_c: Number | None
    room_min_c: Number | None
    room_hours: Number | None
    outside_mean_c: Number | None
    runs: RunStats | None
    pump_errors: int | None
    writes: int | None
    writes_per_day: Number | None
    setpoint_changes_per_day: Number | None


class TrialCriterion(ApiModel):
    """A cut-over criterion: the trial against the baseline."""

    id: str
    trial: Number | None
    baseline: Number | None
    delta: Number | None
    limit: Number | None
    status: CriterionStatusName


class TrialSummary(ApiModel):
    """The trial against the baseline, the trial's state and length."""

    source: Literal["go_live", "default", "query"]
    state: TrialStateName
    days: Number
    min_days: Number
    trial: TrialPeriod
    baseline: TrialPeriod
    criteria: list[TrialCriterion]
    criteria_met: bool
    met: bool


class TrialStatus(ApiModel):
    """``GET trial/status``: the go-live checklist and the trial summary."""

    at: str
    mode: ModeName | None
    configured_mode: ModeName | None
    ready: bool
    ready_for_cutover: bool
    not_ready: list[NotReady]
    counts: CheckCounts
    groups: CheckGroups
    checklist: list[TrialCheck]
    summary: TrialSummary | None


class SnapshotItem(ApiModel):
    """A pump value the snapshot holds."""

    kind: str
    signal: str
    value: Scalar


class PumpSnapshot(ApiModel):
    """The pump's own settings, captured at go-live or by hand."""

    taken_at: str
    origin: str
    by: str | None
    previous_mode: str | None
    own_values_possible: bool
    register_: str | None = Field(alias="register")
    complete: bool
    released_at: str | None
    outside_c: Number | None
    age_s: Number | None
    stale: bool | None
    stale_after_s: Number | None
    items: list[SnapshotItem]
    facts: dict[str, Scalar]


class SnapshotState(ApiModel):
    """``GET`` and ``POST control/snapshot``: the snapshot and whether one can be captured."""

    snapshot: PumpSnapshot | None
    armed: bool
    publishing: bool
    can_capture: bool
    capture_refusal: CaptureRefusalName | None


class ReleaseItem(ApiModel):
    """One pump value a release restores."""

    kind: str
    signal: str
    snapshot: Scalar
    before: Scalar
    target: Scalar
    clamped: str | None
    waited_for: str | None
    status: ReleaseItemStatusName
    ok: bool
    detail: str | None
    at: str | None


class ReleaseRun(ApiModel):
    """A release of control to the pump, or a rehearsal of it."""

    started_at: str
    finished_at: str | None
    done: bool
    outcome: ReleaseOutcomeName
    rehearsal: bool
    dry: bool
    by: str | None
    reason: str | None
    paused_before: bool
    duration_s: Number | None
    within_limit: bool | None
    snapshot_taken_at: str | None
    snapshot_origin: str | None
    snapshot_age_s: Number | None
    outside_c: Number | None
    interrupted: bool
    items: list[ReleaseItem]


class ReleaseState(ApiModel):
    """``GET control/release``: the running or last release and the last rehearsals."""

    release: Annotated[JsonObject | None, kept("ReleaseRun")]
    last_rehearsal: Annotated[JsonObject | None, kept("ReleaseRun")]
    last_dry_rehearsal: Annotated[JsonObject | None, kept("ReleaseRun")]
    timeout_s: Number | None


class ReleaseStarted(ApiModel):
    """``POST control/release``: the started release (``202`` while it runs)."""

    release: ReleaseRun
    control: ControlStatus


class DivergenceSummary(ApiModel):
    """Ovenbird against the pump's setpoint over the window."""

    minutes: int
    compared_minutes: int
    gap_minutes: int
    coverage: Number
    mean_abs_k: Number | None
    max_abs_k: Number | None
    bias_k: Number | None
    hours_over: Number
    episodes: int
    longest_episode_min: int


class DivergenceDay(ApiModel):
    """The divergence of one local day."""

    date: str
    from_: str = Field(alias="from")
    to: str
    minutes: int
    compared_minutes: int
    gap_minutes: int
    coverage: Number
    mean_abs_k: Number | None
    max_abs_k: Number | None
    bias_k: Number | None
    hours_over: Number
    episodes: int
    longest_episode_min: int


class EpisodeNote(ApiModel):
    """Why an episode is explained, by whom and when."""

    note: str | None
    by: str | None
    at: str | None
    start: str | None


class Episode(ApiModel):
    """A run of minutes with a divergence above the threshold."""

    start: str
    end: str
    minutes: int
    max_abs_k: Number
    max_diff_k: Number
    ovenbird_c: Number | None
    pump_c: Number | None
    reason: str | None
    reason_at_max: str | None
    mode: str | None
    writer: str | None
    ended_by: Literal["open", "gap", "converged"]
    explained: EpisodeNote | None


class DivergenceSeries(ApiModel):
    """Ovenbird's and the pump's setpoints as columns over time."""

    at: list[str]
    ovenbird: list[Number | None]
    pump: list[Number | None]
    diff: list[Number | None]
    max_abs: list[Number | None]
    writer: list[str | None]
    mode: list[str | None]


class Divergence(ApiModel):
    """``GET shadow/divergence``: ovenbird against the pump's setpoint, with episodes."""

    from_: str = Field(alias="from")
    to: str
    step: int
    threshold_k: Number
    timezone: str
    signal: str
    summary: DivergenceSummary
    days: list[DivergenceDay]
    episodes_total: int
    episodes: list[Episode]
    series: DivergenceSeries


class EpisodeMark(ApiModel):
    """A stored explanation of an episode."""

    start: str
    start_ts: Number
    note: str
    by: str | None
    at: str


class ExplainResult(ApiModel):
    """``POST shadow/episodes/explain``: the mark, ``null`` after a removal."""

    explained: EpisodeMark | None


class NotifyTest(ApiModel):
    """The outcome of a test notification."""

    at: str
    ok: bool
    error: str | None
    by: str | None


class Delivery(ApiModel):
    """The last notification ntfy accepted."""

    at: str
    title: str


class DeliveryError(ApiModel):
    """The last failed send or ping."""

    at: str
    error: str


class NtfyStatus(ApiModel):
    """The ntfy channel; only ``configured`` without a notifier."""

    configured: bool
    server: str | None = absent()
    token: bool = absent()
    min_severity: str = absent()
    events: bool = absent()
    language: str = absent()
    sent: int = absent()
    suppressed: int = absent()
    dropped: int = absent()
    deferred: int = absent()
    retries: int = absent()
    queued: int = absent()
    last_sent: Delivery | None = absent()
    last_error: DeliveryError | None = absent()
    last_test: Annotated[JsonObject | None, kept("NotifyTest")] = absent()
    rate_limit_per_hour: int = absent()
    rate_limits: dict[str, int] = absent()
    clear_hold_s: Number = absent()
    test_spacing_s: Number = absent()


class DeadmanStatus(ApiModel):
    """The dead-man ping; only ``configured`` without a notifier."""

    configured: bool
    server: str | None = absent()
    interval_s: Number = absent()
    pings: int = absent()
    last_ok: str | None = absent()
    last_error: DeliveryError | None = absent()
    last_skip: str | None = absent()
    healthy: bool = absent()
    unhealthy_reason: str | None = absent()


class NotifyHealth(ApiModel):
    """Whether alarms reach the phone."""

    state: NotifyStateName
    reason: str | None
    failing_since: str | None
    failures_in_row: int
    pending: list[str]
    deadman_state: str


class NotificationStatus(ApiModel):
    """``GET notifications/status``: what is configured, sent and failing (no secrets)."""

    ntfy: NtfyStatus
    deadman: DeadmanStatus
    health: NotifyHealth = absent()


class NotifyTestResult(ApiModel):
    """``POST notifications/test``: the test's outcome and the status after it."""

    test: NotifyTest
    status: NotificationStatus


class AboutControl(ApiModel):
    """The control loop's mode, ticks and state."""

    mode: ModeName
    configured_mode: ModeName
    interval_s: Number
    ticks: int
    last_tick_at: str | None
    publishing: bool
    paused: bool
    releasing: bool
    restored_state: bool


class MqttConnection(ApiModel):
    """The MQTT link and HeishaMon."""

    connected: bool
    tls: bool
    heishamon_base: str
    heishamon_alive: bool


class HaConnection(ApiModel):
    """The Home Assistant link (``connected`` ``null`` when not configured)."""

    configured: bool
    connected: bool | None


class Connections(ApiModel):
    """The service's connections."""

    mqtt: MqttConnection
    ha: HaConnection
    integration_token: bool


class EnvelopeEvidence(ApiModel):
    """The last correction of the pump's envelope rule ovenbird recognised."""

    at: str | None
    from_c: Number
    to_c: Number
    outside_c: Number | None
    low_c: Number
    high_c: Number


class EnvelopeRule(ApiModel):
    """Whether the pump's own envelope rule is declared and seen acting."""

    installed: bool
    state: EnvelopeStateName
    count: int
    first_at: str | None
    last: Annotated[JsonObject | None, kept("EnvelopeEvidence")]
    adopted: int | None


class EnvelopeBand(ApiModel):
    """The envelope band at the current outside temperature."""

    outside_c: Number
    low_c: Number
    high_c: Number


class EnvelopeCorrections(ApiModel):
    """Ovenbird's corrective writes against their limit, and in total."""

    recent: int
    limit: int
    window_s: Number
    total: int


class SafetyNet(ApiModel):
    """The safety net: the envelope rule, the band now and the hard limits."""

    envelope_rule: EnvelopeRule
    envelope_now: EnvelopeBand | None
    max_supply_c: Number
    min_setpoint_c: Number
    envelope_below_k: Number
    envelope_above_k: Number
    ovenbird_corrections: EnvelopeCorrections | None


class SystemAbout(ApiModel):
    """``GET system/about``: version, uptime, connections and the control state."""

    version: str
    api_version: int
    service_time: str
    timezone: str
    started_at: str
    uptime_s: Number
    service_starts: int | None
    previous_start: str | None
    failing_components: dict[str, Any]
    restored_state: bool | None
    setpoint_register: str
    control_interval_s: Number
    control: AboutControl | None
    connections: Connections
    simulation: bool
    clock_speed: Number
    safety_net: SafetyNet | None


KEPT_MODELS: tuple[type[ApiModel], ...] = (ReleaseRun, NotifyTest, EnvelopeEvidence)

"""Response models of the replay endpoints (``replay/coverage``, ``replay``, ``replay/{id}``)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ovenbird.api.models.base import ApiModel, JsonObject, Number, absent

type ReplayKindName = Literal["active", "version", "draft"]
type ReplayStateName = Literal["running", "done", "failed", "cancelled"]
type EpisodeEndName = Literal["open", "gap", "converged"]


class CoverageDay(ApiModel):
    """Stored decisions of one local day of the window."""

    date: str
    from_: str = Field(alias="from")
    to: str
    decisions: int
    expected: int
    first: str | None
    last: str | None


class CoverageVersion(ApiModel):
    """Stored decisions of one configuration version in the window."""

    version: int | None
    from_: str = Field(alias="from")
    to: str
    decisions: int


class ReplayCoverage(ApiModel):
    """``GET replay/coverage``: where stored decisions exist, per day and version."""

    from_: str = Field(alias="from")
    to: str
    timezone: str
    interval_s: Number
    retention_days: Number
    max_days: Number
    oldest: str | None
    newest: str | None
    days: list[CoverageDay]
    versions: list[CoverageVersion]


class ReplayConfig(ApiModel):
    """The configuration a replay ran with: the active one, a stored version or a draft."""

    kind: ReplayKindName
    version: int | None
    changes: JsonObject = absent()


class VersionIdentityModel(ApiModel):
    """The identity check of one configuration version."""

    version: int | None
    ticks: int
    mismatches: int
    first_mismatch: str | None


class ReplayIdentity(ApiModel):
    """Whether replaying each tick with its own version reproduced every recorded setpoint.

    ``ok`` is ``null`` when no tick could be compared.
    """

    ok: bool | None
    ticks: int
    mismatches: int
    first_mismatch: str | None
    unknown: int
    versions: list[VersionIdentityModel]


class ReplaySummary(ApiModel):
    """What the chosen configuration would have done, against the pump and the recording."""

    minutes: int
    compared_minutes: int
    gap_minutes: int
    coverage: Number
    mean_abs_k: Number | None
    max_abs_k: Number | None
    bias_k: Number | None
    hours_over: Number
    above_pump_min: int
    below_pump_min: int
    differs_recorded_min: int
    above_recorded_min: int
    below_recorded_min: int
    mean_diff_recorded_k: Number
    changes_recorded: int
    changes_replayed: int
    changes_pump: int
    writes: int
    writes_per_day: Number
    max_writes_day: int
    days_over_budget: int
    budget: int
    budget_use: Number | None
    sent_recorded: int
    share_safety_clamped: Number
    share_feedback_limited: Number
    ladder: dict[str, Number]
    reason: dict[str, Number]
    binding: dict[str, Number]
    episodes: int
    longest_episode_min: int


class ReplayDay(ApiModel):
    """Writes of one local day: replayed, recorded setpoint changes and commands sent."""

    date: str
    from_: str = Field(alias="from")
    to: str
    writes: int
    changes_recorded: int
    sent_recorded: int


class ReplayEpisode(ApiModel):
    """A run of minutes with the replayed setpoint away from the pump's target."""

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
    ended_by: EpisodeEndName
    recorded_c: Number | None


class ReplaySeries(ApiModel):
    """The recorded, replayed and pump setpoints per step (the last value of each step)."""

    at: list[str]
    recorded: list[Number | None]
    replayed: list[Number | None]
    pump: list[Number | None]


class ReplayResult(ApiModel):
    """A finished replay (open loop: no comfort or energy claim follows from it)."""

    from_: str = Field(alias="from")
    to: str
    config: ReplayConfig
    ticks: int
    skipped: int
    open_loop: bool
    threshold_k: Number
    step: int
    timezone: str
    signal: str
    identity: ReplayIdentity
    summary: ReplaySummary
    days: list[ReplayDay]
    episodes_total: int
    episodes: list[ReplayEpisode]
    series: ReplaySeries
    limitations: list[str]
    run_s: Number


class ReplayJob(ApiModel):
    """``POST replay`` and ``GET replay/{id}``: a replay job and, when done, its result."""

    id: str
    state: ReplayStateName
    phase: str
    progress: Number
    from_: str = Field(alias="from")
    to: str
    config: ReplayConfig
    started_at: str
    finished_at: str | None
    error: str | None
    result: ReplayResult | None

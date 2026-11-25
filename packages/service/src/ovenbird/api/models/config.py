"""Bodies of the configuration router (:mod:`ovenbird.api.config_api`)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from ovenbird.api.models.app import SourceName
from ovenbird.api.models.base import ApiModel, JsonObject, Number, absent
from ovenbird.api.models.control import ConfigMode, DecisionRecord

type ValueSourceName = Literal["env", "file", "store", "preset", "default"]
type TierName = Literal["basic", "advanced", "expert"]
type OriginName = Literal["ui", "rollback", "seed", "reset"]
type FieldTypeName = Literal[
    "number",
    "integer",
    "boolean",
    "string",
    "enum",
    "curve",
    "windows",
    "list",
    "secret",
    "signal",
    "signal_list",
    "mqtt_inputs",
    "retention",
]


class ConfigField(ApiModel):
    """One field of the configuration: effective value, source, lock, stored value, default."""

    value: Any
    source: ValueSourceName
    locked: bool
    stored: Any
    default: Any


class HotWaterState(ApiModel):
    """Whether the UI shows hot water: the setting, the pump's report and the outcome."""

    setting: Literal["auto", "on", "off"]
    installed: bool | None
    shown: bool


class ConfigDoc(ApiModel):
    """``GET config``: the effective configuration."""

    version: int
    applied_version: int
    updated_at: str | None
    updated_by: str | None
    mode: ConfigMode
    reset_pending: bool
    fields: dict[str, ConfigField]
    hot_water: HotWaterState


class FieldDef(ApiModel):
    """The schema of one configuration field."""

    type: FieldTypeName
    nullable: bool
    min: Number | None
    max: Number | None
    exclusive_min: bool
    exclusive_max: bool
    step: Number | None
    soft_min: Number | None
    soft_max: Number | None
    unit: str | None
    display: str | None
    tier: TierName
    group: str
    editable: bool
    env: str
    preset_default: bool
    options: list[str] = absent()
    min_points: int = absent()
    max_points: int = absent()
    max_items: int = absent()
    outside_min: Number = absent()
    outside_max: Number = absent()
    level_min: int = absent()
    level_max: int = absent()


class SchemaGroup(ApiModel):
    """A settings group and its fields, in display order."""

    id: str
    fields: list[str]


class Envelope(ApiModel):
    """The safety envelope around the heating curve."""

    curve: list[tuple[Number, Number]]
    below_k: Number
    above_k: Number


class ConfigSchema(ApiModel):
    """``GET config/schema``: field definitions, groups, presets per emitter, envelope."""

    schema_: int = Field(alias="schema")
    groups: list[SchemaGroup]
    fields: dict[str, FieldDef]
    presets: dict[str, JsonObject]
    envelope: Envelope


class ValidationIssue(ApiModel):
    """An error or warning of a configuration change."""

    field: str | None
    code: str
    message: str
    params: JsonObject


class ValidateResult(ApiModel):
    """``POST config/validate``: errors, warnings and the changed fields' effective values."""

    valid: bool
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]
    effective: JsonObject


class PreviewNow(ApiModel):
    """The current tick decided with the active and the candidate configuration."""

    current: DecisionRecord
    candidate: DecisionRecord
    delta_setpoint: int | None


class OpenLoopSeries(ApiModel):
    """The recorded and replayed setpoints of the window."""

    at: list[str]
    recorded: list[int | None]
    candidate: list[int | None]
    candidate_pre_round: list[Number | None]


class OpenLoopSummary(ApiModel):
    """How the candidate differs from what was recorded."""

    mean_diff_k: Number
    min_diff_k: Number
    max_diff_k: Number
    changes_recorded: int
    changes_candidate: int
    writes_per_day: Number
    budget: int
    share_safety_clamped: Number
    share_feedback_limited: Number
    ladder: dict[str, Number]
    binding: dict[str, Number]


class OpenLoopRun(ApiModel):
    """The candidate replayed over the recorded decisions (open loop)."""

    from_: str = Field(alias="from")
    to: str
    ticks: int
    skipped: int
    identity_ok: bool
    identity_ticks: int
    identity_mismatches: int
    identity_first_mismatch: str | None
    open_loop: bool
    series: OpenLoopSeries
    summary: OpenLoopSummary
    limitations: list[str]


class PreviewResult(ValidateResult):
    """``POST config/preview``: the validation, and for a valid candidate *now* and the open loop.

    ``now`` is ``null`` without a control loop.
    """

    now: PreviewNow | None = absent()
    open_loop_run: OpenLoopRun = absent()


class ApplyResult(ApiModel):
    """``PUT config`` and ``POST config/rollback``: the new version and configuration."""

    version: int
    applies: Literal["next_tick"]
    config: ConfigDoc


class VersionChange(ApiModel):
    """A field's stored value before and after a version (absent is ``null``)."""

    field: str
    from_: Any = Field(alias="from")
    to: Any


class ConfigVersion(ApiModel):
    """A stored configuration version; ``values`` only from ``config/versions/{number}``."""

    version: int
    created_at: str
    actor: str
    origin: OriginName
    comment: str | None
    applied_at: str | None
    changed: list[VersionChange]
    values: JsonObject = absent()


class ConfigVersions(ApiModel):
    """``GET config/versions``: the newest versions first."""

    versions: list[ConfigVersion]


class ConfigExport(ApiModel):
    """``GET config/export``: the stored values and every non-secret effective value."""

    ovenbird_config: int
    app_version: str
    exported_at: str
    version: int
    values: JsonObject
    effective: JsonObject


class ResetAckResult(ApiModel):
    """``POST config/reset-ack``: the mode and the configuration after the acknowledgement."""

    mode: ConfigMode
    config: ConfigDoc


class HaLinkState(ApiModel):
    """Whether Home Assistant is configured and connected, and its temperature unit."""

    enabled: bool
    link_up: bool
    temperature_unit: str | None = absent()


class SignalCandidate(ApiModel):
    """A signal the room, liveness or cross-check picker offers.

    Home Assistant candidates also carry their entity id and, when Home Assistant's
    registry could be read, the area name and the device id (the liveness picker
    lists the room sensor's own device first).
    """

    signal: str
    name: str | None
    unit: str | None
    value: Number | None
    held_s: Number | None
    source: SourceName
    entity_id: str | None = absent()
    area: str | None = absent()
    device_id: str | None = absent()


class ConfigSignals(ApiModel):
    """``GET config/signals``: the signal picker's candidates."""

    ha: HaLinkState
    room: list[SignalCandidate]
    liveness: list[SignalCandidate]
    crosscheck: list[SignalCandidate]


class HaConnectionResult(ApiModel):
    """``PUT config/ha``: the configuration after the connection change."""

    config: ConfigDoc


class HaEntityCheck(ApiModel):
    """What a connection test found for one ``ha/`` signal."""

    signal: str
    entity_id: str
    found: bool
    state: str | None
    value: Number | None
    unit: str | None
    problem: str | None


type HaTestErrorCode = Literal[
    "invalid_url",
    "not_configured",
    "token_required",
    "unreachable",
    "auth_failed",
    "http_error",
    "protocol",
    "timeout",
    "websocket",
]


class HaTestResult(ApiModel):
    """``POST config/ha/test``: the outcome of a read-only connection test."""

    ok: bool
    url: str | None
    reachable: bool
    auth_ok: bool | None
    ha_version: str | None
    latency_ms: Number | None
    temperature_unit: str | None
    metric: bool | None
    entities: list[HaEntityCheck]
    error: str | None
    error_code: HaTestErrorCode | None


type MqttTestErrorCode = Literal[
    "invalid",
    "unreachable",
    "tls",
    "auth_failed",
    "refused",
    "timeout",
    "no_heishamon",
]


class MqttTestResult(ApiModel):
    """``POST config/mqtt/test``: the outcome of a subscribe-only broker test."""

    ok: bool
    host: str
    port: int
    base: str
    connected: bool
    heishamon: bool
    topic: str | None
    latency_ms: Number | None
    error: str | None
    error_code: MqttTestErrorCode | None


class MqttApplyState(ApiModel):
    """The last broker change: ``idle``, ``applying``, ``applied``, ``reverted`` or ``failed``.

    ``failed``: the change gave no live HeishaMon data and putting the previous broker
    back failed (alarm ``mqtt_revert_failed``).
    """

    state: Literal["idle", "applying", "applied", "reverted", "failed"]
    message: str | None
    at: str | None


class MqttStatus(ApiModel):
    """``GET config/mqtt``: the broker link and the last change made in the app."""

    connected: bool
    host: str
    port: int
    base: str
    heishamon_messages: int
    apply: MqttApplyState
    commands_enabled: bool


class MqttConnectionResult(ApiModel):
    """``PUT config/mqtt``: the configuration and the link after the change."""

    config: ConfigDoc
    mqtt: MqttStatus

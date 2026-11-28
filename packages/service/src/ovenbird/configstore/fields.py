"""What the configuration API knows about each settings field: tier, group, unit, ranges.

Bounds come from the settings model (``Field(ge=, le=)``) and, for a field built from
a controller setting, the unit comes from core (:mod:`ovenbird.config.fromcore`), so
neither is duplicated here; this module adds what the model cannot say: the tier
(``basic`` and ``advanced`` are editable, ``expert`` is displayed only), the UI group,
the unit of a service-only field, the display unit, the input step, the soft range (a
warning that must be acknowledged on apply), whether the default comes from the
emitter preset and the feature the field belongs to (:class:`Feature`, also the ids of
``GET api/v1/control/features``). :func:`schema_payload` turns it into
``GET api/v1/config/schema``; every entry says ``read_only`` for a field the API does
not change (the expert tier), so a UI can show the expert values without offering them.
"""

from __future__ import annotations

import types
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Literal, Union, get_args, get_origin

import annotated_types
from pydantic import SecretStr
from pydantic.fields import FieldInfo

from ovenbird.config import (
    CURVE_OUTSIDE_MAX_C,
    CURVE_OUTSIDE_MIN_C,
    MAX_CURVE_POINTS,
    MAX_MQTT_INPUTS,
    MAX_QUIET_WINDOWS,
    MIN_CURVE_POINTS,
    SECRET_FIELDS,
    QuietWindowSetting,
    Settings,
)
from ovenbird.config.fromcore import core_source
from ovenbird_core.control import EmitterType, HeatingCurve, OvenbirdConfig, RoomSensorProfile
from ovenbird_core.control.safety import DEFAULT_MAX_SUPPLY_C

SCHEMA_VERSION: Final = 1
KP_SOFT_FACTORS: Final = (0.5, 2.0)


class Feature(StrEnum):
    """A switchable controller or service feature; settings fields name the one they tune."""

    WEATHER_COMPENSATION = "weather_compensation"
    ROOM_FEEDBACK = "room_feedback"
    SLOW_START = "slow_start"
    MINIMUM_RUN = "minimum_run"
    PUMP_DUTY = "pump_duty"
    QUIET = "quiet"
    STOVE = "stove"
    DAYSHIFT = "dayshift"
    SUMMER = "summer"
    AWAY = "away"
    BOOST = "boost"
    HOUSE_BASICS = "house_basics"
    STARTS_ALARM = "starts_alarm"


FEATURE_PREFIXES: Final[tuple[tuple[str, Feature], ...]] = (
    ("control_curve", Feature.WEATHER_COMPENSATION),
    ("control_weather_compensation", Feature.WEATHER_COMPENSATION),
    ("control_fixed_water_c", Feature.WEATHER_COMPENSATION),
    ("control_outside_", Feature.WEATHER_COMPENSATION),
    ("control_feedback_", Feature.ROOM_FEEDBACK),
    ("control_ramp_", Feature.SLOW_START),
    ("control_cycling_", Feature.MINIMUM_RUN),
    ("control_pump_duty", Feature.PUMP_DUTY),
    ("control_quiet_", Feature.QUIET),
    ("control_stove_", Feature.STOVE),
    ("control_dayshift_", Feature.DAYSHIFT),
    ("control_plan_rule_max_k", Feature.DAYSHIFT),
    ("control_summer_", Feature.SUMMER),
    ("control_away_", Feature.AWAY),
    ("control_boost_", Feature.BOOST),
    ("house_basics_enabled", Feature.HOUSE_BASICS),
    ("safety_starts_", Feature.STARTS_ALARM),
)
"""Which feature a field tunes, by name prefix (first match wins)."""


def feature_of(name: str) -> Feature | None:
    """Return the feature field ``name`` tunes (``None`` for a general field)."""
    return next((feature for prefix, feature in FEATURE_PREFIXES if name.startswith(prefix)), None)


class Tier(StrEnum):
    """How a field is offered in the UI."""

    BASIC = "basic"
    ADVANCED = "advanced"
    EXPERT = "expert"


@dataclass(frozen=True, slots=True)
class FieldMeta:
    """UI metadata of one settings field.

    Parameters
    ----------
    group
        UI group id.
    tier
        ``basic`` / ``advanced`` (editable) or ``expert`` (displayed only).
    unit
        Unit of the stored value of a service-only field (a field built from a
        controller setting takes the core unit, see :func:`unit_of`).
    display
        Unit the UI shows (``min``, ``h``) when it differs from ``unit``.
    step
        Input step in the stored unit.
    soft_min, soft_max
        Soft range: a value outside it is a warning.
    preset
        The default (``None``) means "the emitter preset's value".
    kind
        Value type when it is not a plain scalar (``curve``, ``signal``,
        ``signal_list``, ``windows``, ``retention``: days where ``0`` keeps data forever).
    feature
        The feature the field tunes (filled from :data:`FEATURE_PREFIXES`).
    """

    group: str
    tier: Tier
    unit: str | None = None
    display: str | None = None
    step: float | None = None
    soft_min: float | None = None
    soft_max: float | None = None
    preset: bool = False
    kind: str | None = None
    feature: Feature | None = None


B: Final = Tier.BASIC
A: Final = Tier.ADVANCED
X: Final = Tier.EXPERT

FIELDS: Final[dict[str, FieldMeta]] = {
    "control_curve": FieldMeta("curve", B, "°C", step=0.5, preset=True, kind="curve"),
    "control_weather_compensation": FieldMeta("curve", B),
    "control_fixed_water_c": FieldMeta("curve", B, step=0.5),
    "control_outside_filter_s": FieldMeta(
        "curve", A, display="h", step=600.0, soft_min=1800.0, preset=True
    ),
    "control_outside_signal": FieldMeta("curve", B, kind="signal"),
    "control_outside_max_age_s": FieldMeta("curve", A, display="min", step=60.0),
    "control_outside_plausible_min_c": FieldMeta("curve", A, step=1.0),
    "control_outside_plausible_max_c": FieldMeta("curve", A, step=1.0),
    "control_outside_max_deviation_k": FieldMeta("curve", A, step=0.5),
    "control_room_signal": FieldMeta("room", B, kind="signal"),
    "control_room_profile": FieldMeta("room", B),
    "control_room_step_k": FieldMeta("room", B, step=0.05, preset=True),
    "control_room_report_interval_s": FieldMeta("room", B, display="min", step=10.0),
    "control_room_silence_limit_s": FieldMeta("room", B, display="h", step=1800.0),
    "control_room_liveness_signals": FieldMeta("room", B, kind="signal_list"),
    "control_room_crosscheck_signal": FieldMeta("room", B, kind="signal"),
    "control_comfort_c": FieldMeta("room", B, step=0.1, soft_min=18.0, soft_max=24.0),
    "control_feedback_enabled": FieldMeta("feedback", B),
    "control_feedback_kp": FieldMeta("feedback", A, step=0.1, preset=True),
    "control_feedback_ti_s": FieldMeta("feedback", A, display="h", step=600.0, preset=True),
    "control_feedback_output_limit_k": FieldMeta("feedback", A, step=0.1, preset=True),
    "control_feedback_integral_limit_k": FieldMeta("feedback", A, step=0.1, preset=True),
    "control_min_setpoint_c": FieldMeta(
        "limits", B, step=0.5, soft_min=20.0, soft_max=30.0, preset=True
    ),
    "control_max_supply_c": FieldMeta("limits", B, step=0.5, preset=True),
    "control_deadband_k": FieldMeta("behaviour", A, step=0.1, preset=True),
    "control_dwell_s": FieldMeta(
        "behaviour", A, display="min", step=60.0, soft_min=600.0, preset=True
    ),
    "control_ramp_enabled": FieldMeta("ramp", A, preset=True),
    "control_ramp_hold_s": FieldMeta("ramp", A, display="min", step=60.0, preset=True),
    "control_ramp_max_below_curve_k": FieldMeta("ramp", A, step=0.5, preset=True),
    "control_ramp_release_k_per_h": FieldMeta("ramp", A, step=0.5, preset=True),
    "control_cycling_enabled": FieldMeta("cycling", A, preset=True),
    "control_cycling_min_run_s": FieldMeta("cycling", A, display="min", step=60.0, preset=True),
    "control_pump_duty": FieldMeta("pump_duty", B),
    "control_pump_duty_heat": FieldMeta("pump_duty", B, step=1.0),
    "control_pump_duty_idle": FieldMeta("pump_duty", B, step=1.0),
    "control_pump_duty_idle_delay_s": FieldMeta("pump_duty", B, display="min", step=30.0),
    "hot_water": FieldMeta("pump", B),
    "control_stove_enabled": FieldMeta("stove", B),
    "control_stove_auto": FieldMeta("stove", B),
    "control_stove_backoff_k": FieldMeta("stove", B, step=0.5, soft_max=6.0),
    "control_stove_to_minimum": FieldMeta("stove", B),
    "control_stove_reference_signal": FieldMeta("stove", B, kind="signal"),
    "control_stove_reference_floor_c": FieldMeta(
        "stove", B, step=0.5, soft_min=16.0, soft_max=21.0
    ),
    "control_stove_enter_above_k": FieldMeta("stove", A, step=0.1, soft_min=1.0),
    "control_stove_exit_hysteresis_k": FieldMeta("stove", A, step=0.1, soft_min=0.5),
    "control_stove_rise_enabled": FieldMeta("stove", A),
    "control_stove_rise_k": FieldMeta("stove", A, step=0.1, soft_min=0.5),
    "control_stove_rise_window_s": FieldMeta("stove", A, display="min", step=300.0),
    "control_stove_min_active_s": FieldMeta("stove", A, display="min", step=300.0),
    "control_stove_max_active_s": FieldMeta("stove", A, display="h", step=1800.0),
    "control_stove_reentry_hold_s": FieldMeta("stove", A, display="min", step=300.0),
    "control_stove_reference_band_k": FieldMeta("stove", A, step=0.1),
    "control_dayshift_use": FieldMeta("dayshift", B),
    "control_dayshift_experimental_ok": FieldMeta("dayshift", B),
    "control_dayshift_day_start": FieldMeta("dayshift", B),
    "control_dayshift_day_end": FieldMeta("dayshift", B),
    "control_dayshift_boost_k": FieldMeta("dayshift", B, "K", step=0.05, soft_max=0.75),
    "control_dayshift_setback_k": FieldMeta("dayshift", B, "K", step=0.05, soft_max=0.75),
    "control_dayshift_min_outside_c": FieldMeta("dayshift", A, "°C", step=0.5, soft_min=0.0),
    "control_dayshift_min_sun_wm2": FieldMeta(
        "dayshift", A, "W/m²", step=10.0, soft_min=80.0, soft_max=300.0
    ),
    "control_dayshift_night_start": FieldMeta("dayshift", A),
    "control_dayshift_night_end": FieldMeta("dayshift", A),
    "control_dayshift_comfort_at": FieldMeta("dayshift", A),
    "control_dayshift_recovery_s": FieldMeta(
        "dayshift", A, "s", "h", step=1800.0, soft_min=10_800.0
    ),
    "control_plan_rule_max_k": FieldMeta("dayshift", A, step=0.1),
    "control_quiet_enabled": FieldMeta("quiet", B),
    "control_quiet_windows": FieldMeta("quiet", B, kind="windows"),
    "control_quiet_start_enabled": FieldMeta("quiet", B),
    "control_quiet_start_minutes": FieldMeta("quiet", A, "min", step=1.0),
    "control_quiet_start_level": FieldMeta("quiet", A, step=1.0),
    "control_summer_enabled": FieldMeta("summer", B),
    "control_summer_off_c": FieldMeta("summer", B, step=0.5, soft_min=14.0, soft_max=22.0),
    "control_summer_hysteresis_k": FieldMeta("summer", A, step=0.5),
    "control_summer_mean_s": FieldMeta("summer", A, display="h", step=3600.0),
    "control_boost_enabled": FieldMeta("manual", B),
    "control_boost_default_s": FieldMeta("manual", B, "s", "h", step=900.0),
    "control_boost_default_k": FieldMeta("manual", B, "K", step=0.5),
    "control_away_enabled": FieldMeta("manual", B),
    "control_away_target_c": FieldMeta("manual", B, "°C", step=0.5),
    "control_away_comfort_lead_s": FieldMeta("manual", A, "s", "h", step=1800.0),
    "control_timezone": FieldMeta("quiet", B),
    "control_emitter": FieldMeta("emitter", B),
    "safety_room_floor_k": FieldMeta("monitors", A, "K", step=0.1),
    "safety_room_floor_sustain_s": FieldMeta("monitors", A, "s", "min", step=60.0),
    "safety_defrost_low_flow": FieldMeta("monitors", A),
    "safety_starts_alarm_enabled": FieldMeta("monitors", A),
    "safety_starts_per_hour_max": FieldMeta("monitors", A, "starts", step=1.0),
    "safety_starts_per_day_max": FieldMeta("monitors", A, "starts", step=1.0),
    "weather_enabled": FieldMeta("weather", B),
    "weather_latitude": FieldMeta("weather", B, "°", step=0.01),
    "weather_longitude": FieldMeta("weather", B, "°", step=0.01),
    "weather_location_source": FieldMeta("weather", B),
    "house_floor_area_m2": FieldMeta("house", B, "m²", step=1.0, soft_min=30.0, soft_max=1000.0),
    "house_volume_m3": FieldMeta("house", A, "m³", step=10.0),
    "house_build_period": FieldMeta("house", B),
    "house_window_area_m2": FieldMeta("house", A, "m²", step=1.0),
    "house_window_orientation": FieldMeta("house", A),
    "house_occupants": FieldMeta("house", B, step=1.0),
    "house_basics_enabled": FieldMeta("house", B),
    "history_raw_days": FieldMeta(
        "history", A, "d", step=1.0, soft_min=1.0, soft_max=90.0, kind="retention"
    ),
    "history_1m_days": FieldMeta(
        "history", A, "d", step=1.0, soft_min=7.0, soft_max=730.0, kind="retention"
    ),
    "history_15m_days": FieldMeta("history", A, "d", step=1.0, soft_min=90.0, kind="retention"),
    "history_1h_days": FieldMeta("history", A, "d", step=1.0, soft_min=365.0, kind="retention"),
    "history_decision_days": FieldMeta(
        "history", A, "d", step=1.0, soft_min=7.0, soft_max=730.0, kind="retention"
    ),
    "history_archive_enabled": FieldMeta("history", A),
    "ha_url": FieldMeta("ha", B),
    "ha_token": FieldMeta("ha", B),
    "mqtt_host": FieldMeta("mqtt", B),
    "mqtt_port": FieldMeta("mqtt", B),
    "mqtt_username": FieldMeta("mqtt", B),
    "mqtt_password": FieldMeta("mqtt", B),
    "mqtt_tls": FieldMeta("mqtt", B),
    "mqtt_ca_file": FieldMeta("mqtt", B),
    "mqtt_client_id": FieldMeta("mqtt", B),
    "heishamon_base": FieldMeta("mqtt", B),
    "mqtt_inputs": FieldMeta("mqtt", B, kind="mqtt_inputs"),
    "control_envelope_curve": FieldMeta("controller", X, "°C", preset=True, kind="curve"),
    "control_envelope_below_k": FieldMeta("controller", X, preset=True),
    "control_envelope_above_k": FieldMeta("controller", X, preset=True),
    "control_rounding_hysteresis_k": FieldMeta("controller", X, preset=True),
    "control_ramp_dwell_s": FieldMeta("controller", X, display="min", preset=True),
    "control_ramp_below_outlet_k": FieldMeta("controller", X, preset=True),
    "control_cycling_stop_delta_k": FieldMeta("controller", X, preset=True),
    "control_cycling_margin_k": FieldMeta("controller", X, preset=True),
    "control_cycling_max_raise_k": FieldMeta("cycling", A, step=0.5, preset=True),
    "control_cycling_decrease_headroom_k": FieldMeta("controller", X, preset=True),
    "control_feedback_max_integration_step_s": FieldMeta("controller", X, preset=True),
    "control_room_decay_start_s": FieldMeta("controller", X, display="h", preset=True),
    "control_room_alive_decay_start_s": FieldMeta("controller", X, display="h", preset=True),
    "control_room_alive_decay_end_s": FieldMeta("controller", X, display="h", preset=True),
    "control_room_crosscheck_threshold_k": FieldMeta("controller", X, preset=True),
    "control_room_crosscheck_sustain_s": FieldMeta("controller", X, display="h", preset=True),
    "control_room_crosscheck_tau_s": FieldMeta("controller", X, display="h", preset=True),
    "control_interval_s": FieldMeta("controller", X, "s"),
    "control_state_max_age_s": FieldMeta("controller", X, "s", "min"),
}
FIELDS.update({name: replace(item, feature=feature_of(name)) for name, item in FIELDS.items()})

EXPERT_GROUPS: Final[dict[str, str]] = {
    "command_": "commands",
    "allow_commands": "commands",
    "safety_": "safety",
    "history_": "history",
}

CONNECTION_FIELDS: Final = ("ha_url", "ha_token")
"""Set with ``PUT api/v1/config/ha`` and kept in the store's ``connection`` table, never in a
configuration version (see :mod:`ovenbird.configstore.store`); the schema shows them as
editable."""

MQTT_FIELDS: Final = (
    "mqtt_host",
    "mqtt_port",
    "mqtt_username",
    "mqtt_password",
    "mqtt_tls",
    "mqtt_ca_file",
    "mqtt_client_id",
    "heishamon_base",
)
"""The broker connection: set with ``PUT api/v1/config/mqtt`` after a successful
``POST api/v1/config/mqtt/test`` and kept in the ``connection`` table like the HA
connection."""

STORED_CONNECTION: Final = (*CONNECTION_FIELDS, *MQTT_FIELDS)
"""Every field kept in the ``connection`` table instead of a configuration version."""

EDITABLE: Final = frozenset(
    name for name, meta in FIELDS.items() if meta.tier is not X and name not in STORED_CONNECTION
)

NEVER_IN_STORE: Final = frozenset(
    {
        "allow_commands",
        "command_brokers",
        "command_setpoint_register",
        "simulation",
        "clock_speed",
        "clock_start",
        "control_mode",
        *SECRET_FIELDS,
        "mqtt_host",
        "mqtt_port",
        "mqtt_username",
        "mqtt_tls",
        "mqtt_ca_file",
        "mqtt_client_id",
        "heishamon_base",
        "ha_url",
        "ha_entities",
        "data_dir",
        "ui_dir",
        "http_host",
        "http_port",
        "http_allowed_origins",
        "admin_username",
        "ingress",
        "config_seed",
        "weather_sim_file",
        "notify_ntfy_url",
        "notify_min_severity",
        "notify_events",
        "notify_deadman_interval_s",
        "notify_deadman_allow_http",
        "notify_language",
        "envelope_rule_installed",
    }
)

GROUP_ORDER: Final = (
    "curve",
    "room",
    "feedback",
    "limits",
    "behaviour",
    "ramp",
    "cycling",
    "pump_duty",
    "pump",
    "stove",
    "dayshift",
    "summer",
    "manual",
    "quiet",
    "emitter",
    "monitors",
    "weather",
    "house",
    "ha",
    "mqtt",
    "controller",
    "commands",
    "safety",
    "history",
    "installation",
)


def _pairs(curve: HeatingCurve) -> list[list[float]]:
    """Return the curve as ``[outside, water]`` pairs in degrees Celsius."""
    return [[point.outside_c, point.water_c] for point in curve.points]


PRESET_VALUES: Final[dict[str, Callable[[OvenbirdConfig], Any]]] = {
    "control_curve": lambda c: _pairs(c.curve),
    "control_outside_filter_s": lambda c: c.outside_filter_tau_s,
    "control_feedback_kp": lambda c: c.feedback.kp,
    "control_feedback_ti_s": lambda c: c.feedback.ti_s,
    "control_feedback_output_limit_k": lambda c: c.feedback.output_limit_k,
    "control_feedback_integral_limit_k": lambda c: c.feedback.integral_limit_k,
    "control_feedback_max_integration_step_s": lambda c: c.feedback.max_integration_step_s,
    "control_min_setpoint_c": lambda c: c.safety.min_setpoint_c,
    "control_max_supply_c": lambda c: c.safety.max_supply_c,
    "control_envelope_curve": lambda c: _pairs(c.safety.envelope),
    "control_envelope_below_k": lambda c: c.safety.envelope_below_k,
    "control_envelope_above_k": lambda c: c.safety.envelope_above_k,
    "control_deadband_k": lambda c: c.stages.deadband_k,
    "control_dwell_s": lambda c: c.stages.dwell_s,
    "control_rounding_hysteresis_k": lambda c: c.stages.rounding_hysteresis_k,
    "control_ramp_dwell_s": lambda c: c.stages.ramp_dwell_s,
    "control_ramp_enabled": lambda c: c.ramp.enabled,
    "control_ramp_hold_s": lambda c: c.ramp.hold_s,
    "control_ramp_below_outlet_k": lambda c: c.ramp.below_outlet_k,
    "control_ramp_max_below_curve_k": lambda c: c.ramp.max_below_curve_k,
    "control_ramp_release_k_per_h": lambda c: c.ramp.release_k_per_h,
    "control_cycling_enabled": lambda c: c.cycling.enabled,
    "control_cycling_min_run_s": lambda c: c.cycling.min_run_s,
    "control_cycling_stop_delta_k": lambda c: c.cycling.stop_delta_k,
    "control_cycling_margin_k": lambda c: c.cycling.margin_k,
    "control_cycling_max_raise_k": lambda c: c.cycling.max_raise_k,
    "control_cycling_decrease_headroom_k": lambda c: c.cycling.decrease_headroom_k,
    "control_room_decay_start_s": lambda c: c.room.decay_start_s,
    "control_room_alive_decay_start_s": lambda c: c.room.alive_decay_start_s,
    "control_room_alive_decay_end_s": lambda c: c.room.alive_decay_end_s,
    "control_room_crosscheck_threshold_k": lambda c: c.room.crosscheck_threshold_k,
    "control_room_crosscheck_sustain_s": lambda c: c.room.crosscheck_sustain_s,
    "control_room_crosscheck_tau_s": lambda c: c.room.crosscheck_tau_s,
}


def meta(name: str) -> FieldMeta:
    """Return the metadata of ``name`` (expert ``installation`` for unlisted fields)."""
    found = FIELDS.get(name)
    if found is not None:
        return found
    group = next(
        (group for prefix, group in EXPERT_GROUPS.items() if name.startswith(prefix)),
        "installation",
    )
    return FieldMeta(group, X, feature=feature_of(name))


def unit_of(name: str) -> str | None:
    """Return the unit of field ``name``: the core setting's, or the one listed here."""
    source = core_source(name)
    return meta(name).unit if source is None else source.spec.unit


def preset_values(emitter: EmitterType | str) -> dict[str, Any]:
    """Return the preset value of every preset-derived field for ``emitter``."""
    config = OvenbirdConfig.preset(emitter)
    return {name: getter(config) for name, getter in PRESET_VALUES.items()}


def preset_value(settings: Settings, name: str) -> Any:
    """Return the value field ``name`` takes when unset, for the current emitter and profile."""
    if name == "control_room_step_k":
        return RoomSensorProfile(kind=settings.room_profile().kind).quantum_k
    getter = PRESET_VALUES.get(name)
    if getter is None:
        return None
    return getter(OvenbirdConfig.preset(settings.emitter))


def to_json(value: Any) -> Any:
    """Return the JSON form of a settings value (secrets must be handled by the caller)."""
    if isinstance(value, tuple | list):
        return [to_json(item) for item in value]
    if isinstance(value, QuietWindowSetting):
        return value.model_dump()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, SecretStr):
        return "set"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def secret_state(settings: Settings, name: str) -> str:
    """Return ``set`` or ``unset`` for a secret field."""
    return "unset" if getattr(settings, name) is None else "set"


def effective_value(settings: Settings, name: str) -> Any:
    """Return the JSON value field ``name`` has in ``settings`` (presets resolved)."""
    if name in SECRET_FIELDS:
        return secret_state(settings, name)
    value = getattr(settings, name)
    if value is None and meta(name).preset:
        return preset_value(settings, name)
    return to_json(value)


def default_value(settings: Settings, name: str) -> Any:
    """Return the value without environment, options file or store (preset resolved)."""
    if name in SECRET_FIELDS:
        return None
    if meta(name).preset:
        return preset_value(settings, name)
    info = Settings.model_fields[name]
    if info.default_factory is not None:
        return None
    return to_json(info.default)


def _bound(info: FieldInfo, kinds: tuple[type, ...]) -> float | None:
    """Return the first numeric bound of a field's metadata, if it has one."""
    for item in info.metadata:
        if isinstance(item, kinds):
            raw = next(
                getattr(item, attr) for attr in ("ge", "gt", "le", "lt") if hasattr(item, attr)
            )
            return float(raw)
    return None


def _strip_optional(annotation: Any) -> tuple[Any, bool]:
    """Return the annotation without ``None`` and whether it was optional."""
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        return (args[0] if len(args) == 1 else annotation), True
    return annotation, False


def _value_type(name: str, annotation: Any) -> tuple[str, list[str] | None]:
    """Return the UI value kind of a field and its enum choices, if it is an enum.

    Parameters
    ----------
    name
        Settings field name.
    annotation
        Type annotation of the field.
    """
    kind = meta(name).kind
    if kind is not None:
        return kind, None
    if name in SECRET_FIELDS:
        return "secret", None
    base = getattr(annotation, "__value__", annotation)
    if get_origin(base) is Literal:
        return "enum", [str(arg) for arg in get_args(base)]
    if base is bool:
        return "boolean", None
    if base is int:
        return "integer", None
    if base is float:
        return "number", None
    if get_origin(base) is tuple:
        return "list", None
    return "string", None


def _dynamic(settings: Settings, name: str, entry: dict[str, Any]) -> None:
    """Narrow the limits of a field entry to the emitter and the safety limits in force."""
    emitter = settings.emitter
    preset = OvenbirdConfig.preset(emitter)
    safety = settings.safety_limits()
    match name:
        case "control_max_supply_c":
            entry["max"] = DEFAULT_MAX_SUPPLY_C[emitter]
        case "control_min_setpoint_c":
            entry["max"] = min(float(entry["max"]), safety.max_supply_c - 1.0)
        case "control_ramp_max_below_curve_k":
            entry["max"] = safety.envelope_below_k
        case "control_feedback_kp":
            low, high = KP_SOFT_FACTORS
            entry["soft_min"] = round(preset.feedback.kp * low, 3)
            entry["soft_max"] = round(preset.feedback.kp * high, 3)
        case "control_curve":
            entry |= {
                "min_points": MIN_CURVE_POINTS,
                "max_points": MAX_CURVE_POINTS,
                "max_items": MAX_CURVE_POINTS,
                "outside_min": CURVE_OUTSIDE_MIN_C,
                "outside_max": CURVE_OUTSIDE_MAX_C,
                "min": safety.min_setpoint_c,
                "max": safety.max_supply_c,
            }
        case "control_quiet_windows":
            entry |= {"max_items": MAX_QUIET_WINDOWS, "level_min": 1, "level_max": 3}
        case "mqtt_inputs":
            entry["max_items"] = MAX_MQTT_INPUTS


def field_schema(settings: Settings, name: str) -> dict[str, Any]:
    """Return the schema entry of field ``name`` (see ``GET api/v1/config/schema``)."""
    info = Settings.model_fields[name]
    annotation, nullable = _strip_optional(info.annotation)
    value_type, options = _value_type(name, annotation)
    info_meta = meta(name)
    unit = unit_of(name)
    entry: dict[str, Any] = {
        "type": value_type,
        "nullable": nullable,
        "min": _bound(info, (annotated_types.Ge, annotated_types.Gt)),
        "max": _bound(info, (annotated_types.Le, annotated_types.Lt)),
        "exclusive_min": any(isinstance(item, annotated_types.Gt) for item in info.metadata),
        "exclusive_max": any(isinstance(item, annotated_types.Lt) for item in info.metadata),
        "step": info_meta.step,
        "soft_min": info_meta.soft_min,
        "soft_max": info_meta.soft_max,
        "unit": unit,
        "display": info_meta.display or unit,
        "tier": info_meta.tier.value,
        "group": info_meta.group,
        "editable": name in EDITABLE or name in STORED_CONNECTION,
        "read_only": name not in EDITABLE and name not in STORED_CONNECTION,
        "feature": None if info_meta.feature is None else info_meta.feature.value,
        "env": f"OVENBIRD_{name.upper()}",
        "preset_default": info_meta.preset,
    }
    if options is not None:
        entry["options"] = options
    _dynamic(settings, name, entry)
    return entry


def schema_payload(settings: Settings) -> dict[str, Any]:
    """Return the body of ``GET api/v1/config/schema`` for the current configuration.

    Parameters
    ----------
    settings
        Effective settings (the dynamic bounds depend on the emitter and limits).

    Returns
    -------
    dict
        ``schema``, ``groups`` (ordered), ``fields``, ``presets`` per emitter and
        the current ``envelope``.
    """
    names = list(Settings.model_fields)
    fields = {name: field_schema(settings, name) for name in names}
    groups = [
        {"id": group, "fields": [name for name in names if fields[name]["group"] == group]}
        for group in GROUP_ORDER
    ]
    safety = settings.safety_limits()
    return {
        "schema": SCHEMA_VERSION,
        "groups": [group for group in groups if group["fields"]],
        "fields": fields,
        "presets": {emitter.value: preset_values(emitter) for emitter in EmitterType},
        "envelope": {
            "curve": _pairs(safety.envelope),
            "below_k": safety.envelope_below_k,
            "above_k": safety.envelope_above_k,
        },
    }

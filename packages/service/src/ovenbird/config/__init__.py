"""Bootstrap settings: the :class:`Settings` model, its sources and its validation.

``from ovenbird.config import Settings`` (and every other name below) is the public
interface; the modules of this package are its implementation. :class:`Settings`,
:func:`describe_errors` and :func:`load_settings` load on first use: the settings
model combines the feature packages' models, which import
:mod:`ovenbird.config.fromcore`, so importing this package must not import them.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from ovenbird.config.network import (
    DEFAULT_PORTS,
    DEV_BROKER_NAMES,
    LOOPBACK_NAMES,
    WILDCARDS,
    is_loopback,
    is_simulation_broker,
    normalise_broker,
    normalise_origin,
)
from ovenbird.config.sources import (
    DATA_DIR_ENV,
    DEFAULT_DATA_DIR,
    DEFAULT_HTTP_PORT,
    DEFAULT_OPTIONS_FILE,
    DEFAULT_UI_DIR,
    ENV_ONLY_FIELDS,
    ENV_PREFIX,
    INGRESS_BIND_HOST,
    INGRESS_SOURCE,
    OPTIONS_FILE_ENV,
    SECRET_FIELDS,
    SUPERVISOR_HA_URL,
    SUPERVISOR_TOKEN_ENV,
    OptionsFileSource,
    options_file,
)
from ovenbird.config.validation.issues import (
    control_issues,
)
from ovenbird.config.validation.quiet import (
    CLOCK_TIME_RE,
)
from ovenbird.config.values import (
    CELSIUS,
    CURVE_OUTSIDE_MAX_C,
    CURVE_OUTSIDE_MIN_C,
    ENTITY_ID_RE,
    LOCATION_DECIMALS,
    MAX_CLOCK_SPEED,
    MAX_CURVE_POINTS,
    MAX_MQTT_INPUTS,
    MAX_QUIET_WINDOWS,
    MIN_CURVE_POINTS,
    MIN_INTEGRAL_TIME_S,
    MIN_OPERATE_TOKEN,
    NTFY_TOPIC_RE,
    SNAPSHOT_NAME,
    TEMPERATURE_DOMAINS,
    ConfigError,
    ControlModeName,
    CurvePairs,
    EmitterName,
    Issue,
    LocationSource,
    LogLevel,
    MqttInput,
    NotifyLanguage,
    NotifySeverity,
    QuietWindowSetting,
    RoomProfileName,
    SetpointRegister,
    curve_from_pairs,
)

if TYPE_CHECKING:
    from ovenbird.config.settings import Settings, describe_errors, load_settings

LAZY = frozenset({"Settings", "describe_errors", "load_settings"})

__all__ = [
    "CELSIUS",
    "CLOCK_TIME_RE",
    "CURVE_OUTSIDE_MAX_C",
    "CURVE_OUTSIDE_MIN_C",
    "DATA_DIR_ENV",
    "DEFAULT_DATA_DIR",
    "DEFAULT_HTTP_PORT",
    "DEFAULT_OPTIONS_FILE",
    "DEFAULT_PORTS",
    "DEFAULT_UI_DIR",
    "DEV_BROKER_NAMES",
    "ENTITY_ID_RE",
    "ENV_ONLY_FIELDS",
    "ENV_PREFIX",
    "INGRESS_BIND_HOST",
    "INGRESS_SOURCE",
    "LOCATION_DECIMALS",
    "LOOPBACK_NAMES",
    "MAX_CLOCK_SPEED",
    "MAX_CURVE_POINTS",
    "MAX_MQTT_INPUTS",
    "MAX_QUIET_WINDOWS",
    "MIN_CURVE_POINTS",
    "MIN_INTEGRAL_TIME_S",
    "MIN_OPERATE_TOKEN",
    "NTFY_TOPIC_RE",
    "OPTIONS_FILE_ENV",
    "SECRET_FIELDS",
    "SNAPSHOT_NAME",
    "SUPERVISOR_HA_URL",
    "SUPERVISOR_TOKEN_ENV",
    "TEMPERATURE_DOMAINS",
    "WILDCARDS",
    "ConfigError",
    "ControlModeName",
    "CurvePairs",
    "EmitterName",
    "Issue",
    "LocationSource",
    "LogLevel",
    "MqttInput",
    "NotifyLanguage",
    "NotifySeverity",
    "OptionsFileSource",
    "QuietWindowSetting",
    "RoomProfileName",
    "SetpointRegister",
    "Settings",
    "control_issues",
    "curve_from_pairs",
    "describe_errors",
    "is_loopback",
    "is_simulation_broker",
    "load_settings",
    "normalise_broker",
    "normalise_origin",
    "options_file",
]


def __getattr__(name: str) -> Any:
    """Load the settings model and its loaders on first use."""
    if name in LAZY:
        return getattr(importlib.import_module("ovenbird.config.settings"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

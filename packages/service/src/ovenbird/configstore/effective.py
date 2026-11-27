"""Merge the stored configuration with the installation's settings; sources, locks, checks.

Precedence, highest first: environment, options file, configuration store (its
newest version, and for ``ha_url`` and ``ha_token`` its connection table), then the
installation's base (keyword arguments of :func:`~ovenbird.config.load_settings`,
used by tests and the harness) and the defaults (emitter preset where a field
defaults to ``None``). A field provided by the environment or the options file is
**locked**: the API refuses to change it and a stored value under it is kept but
inactive. Only :data:`~ovenbird.configstore.fields.EDITABLE` fields can be stored;
:data:`~ovenbird.configstore.fields.NEVER_IN_STORE` (publish gates, secrets,
connections, bind addresses) never reach the store, whatever a document contains.

Validation runs the real settings model on the merged values (field bounds, the
cross-field :class:`~ovenbird.config.Issue` rules, the controller's own checks), then
the store-only rules (the maximum supply may only be lowered from the emitter's
default; a room signal the service can receive) and computes the soft-range warnings
of the changed fields.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError
from pydantic_settings import BaseSettings, EnvSettingsSource, PydanticBaseSettingsSource

from ovenbird.config import (
    ENV_PREFIX,
    SECRET_FIELDS,
    Issue,
    OptionsFileSource,
    Settings,
    options_file,
)
from ovenbird.config.validation.ha import check_ha_url
from ovenbird.configstore.fields import (
    CONNECTION_FIELDS,
    EDITABLE,
    KP_SOFT_FACTORS,
    MQTT_FIELDS,
    NEVER_IN_STORE,
    STORED_CONNECTION,
    default_value,
    effective_value,
    meta,
    to_json,
)
from ovenbird_core.control import OvenbirdConfig
from ovenbird_core.control.safety import DEFAULT_MAX_SUPPLY_C

LOGGER = logging.getLogger("ovenbird.configstore")
STORABLE: Final = EDITABLE - NEVER_IN_STORE
MAX_TOKEN: Final = 4096
CURVE_SHIFT_LIMIT_K: Final = 3.0
CURVE_SHIFT_RANGE_C: Final = (-15.0, 20.0)
CURVE_SHIFT_STEP_C: Final = 0.5
PYDANTIC_CODES: Final = {
    "greater_than_equal": "below_min",
    "greater_than": "below_min",
    "less_than_equal": "above_max",
    "less_than": "above_max",
    "literal_error": "not_allowed",
    "enum": "not_allowed",
    "too_long": "too_many",
    "string_too_long": "too_long",
    "too_short": "too_few",
    "missing": "missing",
    "extra_forbidden": "unknown_field",
    "value_error": "invalid",
}
TYPE_SUFFIXES: Final = ("_type", "_parsing")
CUSTOM_CODES: Final = frozenset(
    {
        "curve_points",
        "curve_outside_range",
        "curve_order",
        "integral_time",
        "timezone",
        "clock_time",
        "window_empty",
        "retention_min",
        "input_bounds",
        "date_format",
        "date_future",
        "date_repeated",
    }
)
VALIDATION_ERRORS: Final = (
    "unknown_field",
    "not_editable",
    "locked",
    "type",
    "missing",
    "below_min",
    "above_max",
    "not_allowed",
    "too_many",
    "too_few",
    "too_long",
    "invalid",
    *sorted(CUSTOM_CODES),
    "input_topic_reserved",
    "input_topic_repeated",
    "input_signal_reserved",
    "input_signal_repeated",
    "room_signal_required",
    "liveness_is_room",
    "crosscheck_is_room",
    "signal_unknown",
    "pump_duty_order",
    "pump_duty_clamp",
    "stove_hysteresis",
    "stove_min_above_max",
    "stove_reference_is_room",
    "signal_not_temperature",
    "min_above_max",
    "house_bounds_order",
    "house_fit_days_short",
    "curve_range",
    "outside_envelope",
    "integral_above_output",
    "ramp_below_envelope",
    "fixed_range",
    "location_pair",
    "location_required",
    "max_supply_raise",
    "connection_field",
    "ca_file_missing",
    "password_locked",
    "warning_not_acknowledged",
    "no_change",
    "comment_too_long",
)
VALIDATION_WARNINGS: Final = (
    "below_soft_min",
    "above_soft_max",
    "curve_shift_large",
    "cycling_disabled",
    "emitter_changed",
    "weather_compensation_off",
    "fixed_outside_envelope",
)


class Source(StrEnum):
    """Where an effective value comes from."""

    ENV = "env"
    FILE = "file"
    STORE = "store"
    PRESET = "preset"
    DEFAULT = "default"


def provided_sources() -> dict[str, Source]:
    """Return the fields the environment and the options file provide (they are locked).

    An empty Home Assistant URL or token (``OVENBIRD_HA_URL=``, as a compose file passes an
    unset variable) provides nothing, so the connection stays settable in the app.

    Returns
    -------
    dict
        Field name to ``env`` or ``file`` (the environment wins).
    """
    found: dict[str, Source] = {}
    try:
        from_file = OptionsFileSource(Settings, json_file=options_file())()
    except OSError, ValueError:
        from_file = {}
    from_env = EnvSettingsSource(Settings, case_sensitive=False, env_prefix=ENV_PREFIX)()
    for values, source in ((from_file, Source.FILE), (from_env, Source.ENV)):
        for name, value in values.items():
            if name in STORED_CONNECTION and value in (None, ""):
                continue
            if name in Settings.model_fields:
                found[name] = source
    return found


def storable(values: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``values`` without the fields that may never be stored (logged when dropped)."""
    kept = {name: value for name, value in values.items() if name in STORABLE}
    dropped = sorted(set(values) - set(kept))
    if dropped:
        LOGGER.warning("ignoring stored values of fields that are not editable: %s", dropped)
    return kept


class MergedSettings(Settings):
    """Settings built from explicit values only (no environment or options file re-read)."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Read the keyword arguments only."""
        return (init_settings,)


def connection_values(
    locked: Mapping[str, Source], connection: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Return the stored connection values that apply (the unlocked ones)."""
    return {
        name: value
        for name, value in (connection or {}).items()
        if name in STORED_CONNECTION and name not in locked
    }


def merge(
    base: Settings,
    locked: Mapping[str, Source],
    doc: Mapping[str, Any],
    connection: Mapping[str, Any] | None = None,
) -> Settings:
    """Return the settings with the stored document applied under the locked fields.

    Parameters
    ----------
    base
        Settings from the environment, the options file and keyword arguments.
    locked
        Fields provided by the environment or the options file.
    doc
        Stored values.
    connection
        Stored connection values (``ha_url``, ``ha_token``); a locked one is ignored.

    Returns
    -------
    Settings
        The validated, merged settings. The environment and the options file are not
        read again: ``base`` already holds every value they provide.

    Raises
    ------
    pydantic.ValidationError
        When the merged values are invalid.
    """
    explicit = {name: getattr(base, name) for name in base.model_fields_set}
    active = {name: value for name, value in storable(doc).items() if name not in locked}
    return MergedSettings(**{**explicit, **active, **connection_values(locked, connection)})


@dataclass(frozen=True, slots=True)
class Validation:
    """Outcome of validating a candidate document.

    Parameters
    ----------
    errors
        Violations; the candidate is valid only without them.
    warnings
        Soft-range and change warnings (must be acknowledged on apply).
    doc
        The candidate document, normalised (values as the model parsed them).
    settings
        The merged candidate settings; ``None`` when invalid.
    effective
        Effective JSON values of the changed fields.
    """

    errors: list[Issue]
    warnings: list[Issue]
    doc: dict[str, Any]
    settings: Settings | None
    effective: dict[str, Any] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        """Whether there are no errors."""
        return not self.errors

    def to_json(self) -> dict[str, Any]:
        """Return the body of ``POST api/v1/config/validate``."""
        return {
            "valid": self.valid,
            "errors": [issue.to_json() for issue in self.errors],
            "warnings": [issue.to_json() for issue in self.warnings],
            "effective": self.effective,
        }


def _code(kind: str) -> str:
    if kind in CUSTOM_CODES:
        return kind
    if kind in PYDANTIC_CODES:
        return PYDANTIC_CODES[kind]
    if kind.endswith(TYPE_SUFFIXES):
        return "type"
    return "invalid"


def validation_issues(exc: ValidationError) -> list[Issue]:
    """Map a settings validation error to issues with stable codes (no input values)."""
    issues: list[Issue] = []
    for error in exc.errors(include_input=False, include_url=False, include_context=True):
        ctx = dict(error.get("ctx") or {})
        if error["type"] == "config_issues":
            for item in ctx.get("issues", ()):
                issues.append(
                    Issue(item["field"], item["code"], item["message"], dict(item["params"]))
                )
            continue
        loc = [str(part) for part in error["loc"]]
        params: dict[str, Any] = {}
        for key, value in ctx.items():
            if key in {"ge", "gt"}:
                params["min"] = value
            elif key in {"le", "lt"}:
                params["max"] = value
            elif key == "expected":
                params["allowed"] = str(value)
            elif isinstance(value, int | float | str | bool):
                params[key] = value
        if len(loc) > 1:
            params["path"] = ".".join(loc[1:])
        issues.append(Issue(loc[0] if loc else None, _code(error["type"]), error["msg"], params))
    return issues


def store_rules(
    candidate: Settings, doc: Mapping[str, Any], locked: Mapping[str, Source]
) -> list[Issue]:
    """Return the violations of the rules that apply to stored values only."""
    issues: list[Issue] = []
    active = {name for name in doc if name not in locked}
    emitter_max = DEFAULT_MAX_SUPPLY_C[candidate.emitter]
    supply = candidate.control_max_supply_c
    if "control_max_supply_c" in active and supply is not None and supply > emitter_max:
        issues.append(
            Issue(
                "control_max_supply_c",
                "max_supply_raise",
                f"the maximum supply temperature can only be lowered here (emitter default "
                f"{emitter_max:g} °C); raising it needs OVENBIRD_CONTROL_MAX_SUPPLY_C",
                {"max": emitter_max},
            )
        )
    room = candidate.control_room_signal
    if (
        "control_room_signal" in active
        and room is not None
        and not candidate.signal_known(room, heishamon=True)
    ):
        issues.append(
            Issue(
                "control_room_signal",
                "signal_unknown",
                f"room signal {room!r} is neither ha/<entity_id> with HA configured, a "
                "HeishaMon main/* signal, nor the signal of a configured MQTT input",
                {"signal": room},
            )
        )
    return issues


def _soft(candidate: Settings, name: str) -> tuple[float | None, float | None]:
    info = meta(name)
    if name == "control_feedback_kp":
        kp = OvenbirdConfig.preset(candidate.emitter).feedback.kp
        return kp * KP_SOFT_FACTORS[0], kp * KP_SOFT_FACTORS[1]
    return info.soft_min, info.soft_max


def _curve_shift(old: Settings, new: Settings) -> tuple[float, float]:
    a, b = old.controller_config().curve, new.controller_config().curve
    worst, at = 0.0, CURVE_SHIFT_RANGE_C[0]
    outside = CURVE_SHIFT_RANGE_C[0]
    while outside <= CURVE_SHIFT_RANGE_C[1] + 1e-9:
        shift = b.water(outside) - a.water(outside)
        if abs(shift) > abs(worst):
            worst, at = shift, outside
        outside += CURVE_SHIFT_STEP_C
    return worst, at


def _fixed_clamped(candidate: Settings) -> tuple[float, float] | None:
    """Return the outside range where the safety envelope overrides the fixed temperature."""
    safety = candidate.controller_config().safety
    fixed = candidate.control_fixed_water_c
    clamped: list[float] = []
    outside = CURVE_SHIFT_RANGE_C[0]
    while outside <= CURVE_SHIFT_RANGE_C[1] + 1e-9:
        reference = safety.envelope.water(outside)
        low = reference - safety.envelope_below_k
        high = reference + safety.envelope_above_k
        if fixed < low - 1e-9 or fixed > high + 1e-9:
            clamped.append(outside)
        outside += CURVE_SHIFT_STEP_C
    return (clamped[0], clamped[-1]) if clamped else None


def change_warnings(
    previous: Settings, candidate: Settings, changes: Mapping[str, Any]
) -> list[Issue]:
    """Return the warnings of the changed fields (soft range, curve shift, switches).

    Parameters
    ----------
    previous
        Effective settings before the change.
    candidate
        Merged candidate settings.
    changes
        The requested changes (``None`` resets a field and warns about nothing).

    Returns
    -------
    list of Issue
        One warning per finding; codes ``below_soft_min``, ``above_soft_max``,
        ``curve_shift_large``, ``cycling_disabled``, ``emitter_changed``,
        ``weather_compensation_off`` and ``fixed_outside_envelope``.
    """
    warnings: list[Issue] = []
    for name, requested in changes.items():
        if requested is None or isinstance(requested, bool) or name not in EDITABLE:
            continue
        value = getattr(candidate, name, None)
        if not isinstance(value, int | float) or isinstance(value, bool):
            continue
        if meta(name).kind == "retention" and value == 0:
            continue
        low, high = _soft(candidate, name)
        if low is not None and value < low - 1e-9:
            warnings.append(
                Issue(
                    name,
                    "below_soft_min",
                    f"{name} {value:g} is below the usual range (from {low:g})",
                    {"value": value, "soft_min": round(low, 3)},
                )
            )
        if high is not None and value > high + 1e-9:
            warnings.append(
                Issue(
                    name,
                    "above_soft_max",
                    f"{name} {value:g} is above the usual range (up to {high:g})",
                    {"value": value, "soft_max": round(high, 3)},
                )
            )
    if "control_curve" in changes or "control_emitter" in changes:
        shift, at = _curve_shift(previous, candidate)
        if abs(shift) > CURVE_SHIFT_LIMIT_K:
            warnings.append(
                Issue(
                    "control_curve",
                    "curve_shift_large",
                    f"the curve moves by {shift:+.1f} K at {at:g} °C outside "
                    f"(more than {CURVE_SHIFT_LIMIT_K:g} K)",
                    {"shift_k": round(shift, 2), "at": at, "limit_k": CURVE_SHIFT_LIMIT_K},
                )
            )
    if (
        changes.get("control_cycling_enabled") is False
        and previous.controller_config().cycling.enabled
    ):
        warnings.append(
            Issue(
                "control_cycling_enabled",
                "cycling_disabled",
                "without cycling protection the pump may stop early in a run",
            )
        )
    if (
        changes.get("control_weather_compensation") is False
        and previous.control_weather_compensation
    ):
        warnings.append(
            Issue(
                "control_weather_compensation",
                "weather_compensation_off",
                "without weather-dependent control the water temperature no longer follows "
                "the outside temperature",
            )
        )
    war_fields = ("control_weather_compensation", "control_fixed_water_c")
    if not candidate.control_weather_compensation and any(f in changes for f in war_fields):
        clamped = _fixed_clamped(candidate)
        if clamped is not None:
            low, high = clamped
            warnings.append(
                Issue(
                    "control_fixed_water_c",
                    "fixed_outside_envelope",
                    f"the safety envelope overrides the fixed water temperature between "
                    f"{low:g} and {high:g} °C outside",
                    {"from": low, "to": high},
                )
            )
    if "control_emitter" in changes and candidate.control_emitter != previous.control_emitter:
        warnings.append(
            Issue(
                "control_emitter",
                "emitter_changed",
                f"changing the emitter from {previous.control_emitter} to "
                f"{candidate.control_emitter} changes every preset value and the safety limits",
                {"from": previous.control_emitter, "to": candidate.control_emitter},
            )
        )
    return warnings


def validate_doc(
    base: Settings,
    locked: Mapping[str, Source],
    current: Mapping[str, Any],
    changes: Mapping[str, Any],
    previous: Settings,
    connection: Mapping[str, Any] | None = None,
) -> Validation:
    """Validate ``changes`` on top of the stored document ``current``.

    Parameters
    ----------
    base
        Installation settings (environment, options file, keyword arguments).
    locked
        Fields provided by the environment or the options file.
    current
        The stored document now.
    changes
        Field to new value; ``None`` removes the stored value.
    previous
        Effective settings now (for the warnings).
    connection
        The stored connection values.

    Returns
    -------
    Validation
        Errors, warnings, the normalised candidate document and its settings.
    """
    errors: list[Issue] = []
    doc = dict(current)
    for name, value in changes.items():
        if name not in Settings.model_fields:
            errors.append(Issue(name, "unknown_field", f"{name} is not a setting"))
        elif name in STORED_CONNECTION:
            where = "config/ha" if name in CONNECTION_FIELDS else "config/mqtt"
            errors.append(
                Issue(
                    name,
                    "connection_field",
                    f"{name} is part of a connection; set it with PUT api/v1/{where}",
                )
            )
        elif name not in STORABLE:
            errors.append(
                Issue(name, "not_editable", f"{name} can only be set by the installation")
            )
        elif name in locked:
            source = locked[name].value
            errors.append(
                Issue(
                    name,
                    "locked",
                    f"{name} is set by the {'environment' if source == 'env' else 'options file'}"
                    f" (OVENBIRD_{name.upper()})",
                    {"source": source, "env": f"OVENBIRD_{name.upper()}"},
                )
            )
        elif value is None:
            doc.pop(name, None)
        else:
            doc[name] = value
    if errors:
        return Validation(errors, [], doc, None)
    try:
        candidate = merge(base, locked, doc, connection)
    except ValidationError as exc:
        return Validation(validation_issues(exc), [], doc, None)
    errors = store_rules(candidate, doc, locked)
    normalised = {
        name: (value if name in locked else to_json(getattr(candidate, name)))
        for name, value in storable(doc).items()
    }
    effective = {name: effective_value(candidate, name) for name in changes if name in STORABLE}
    if errors:
        return Validation(errors, [], normalised, None, effective)
    warnings = change_warnings(previous, candidate, changes)
    return Validation([], warnings, normalised, candidate, effective)


def _token_follows_url(
    connection: Mapping[str, Any],
    candidate: Mapping[str, Any],
    changes: Mapping[str, Any],
    locked: Mapping[str, Source],
) -> bool:
    """Return whether a URL change would hand a token the request did not bring to the new host."""
    url = candidate.get("ha_url")
    if url is None or url == connection.get("ha_url"):
        return False
    if "ha_token" not in locked and candidate.get("ha_token") is None:
        return False
    token = changes.get("ha_token")
    return not (isinstance(token, str) and token.strip())


def _connection_change(
    name: str, value: Any, locked: Mapping[str, Source]
) -> tuple[str | None, Issue | None]:
    if name in locked:
        return None, _locked(name, locked)
    if value is None:
        return None, None
    if not isinstance(value, str):
        return None, Issue(name, "type", f"{name} must be a string or null")
    if name == "ha_url":
        try:
            return check_ha_url(value), None
        except ValueError as exc:
            return None, Issue(name, "invalid", str(exc))
    text = value.strip()
    if not text:
        return None, None
    if len(text) > MAX_TOKEN or any(char.isspace() for char in text):
        return None, Issue(
            name, "invalid", f"{name} must be one word of at most {MAX_TOKEN} characters"
        )
    return text, None


def validate_connection(
    base: Settings,
    locked: Mapping[str, Source],
    doc: Mapping[str, Any],
    connection: Mapping[str, str],
    changes: Mapping[str, Any],
) -> tuple[list[Issue], dict[str, str], Settings | None]:
    """Validate a change of the Home Assistant connection on top of the stored one.

    Parameters
    ----------
    base
        Installation settings.
    locked
        Fields provided by the environment or the options file.
    doc
        The stored document now.
    connection
        The stored connection now.
    changes
        ``ha_url`` and/or ``ha_token`` to new values; ``None`` (or a blank string)
        removes the stored value, an absent field keeps it.

    Returns
    -------
    tuple
        The errors, the candidate connection and its merged settings (``None`` when
        invalid). The URL and the token must come together, and a new URL needs its
        token in the same change (``token_required``), so a stored or environment
        token never follows the URL to another host; removing the connection is
        refused while the configuration still reads ``ha/`` signals.
    """
    errors: list[Issue] = []
    candidate = dict(connection)
    for name, value in changes.items():
        if name not in CONNECTION_FIELDS:
            errors.append(Issue(name, "unknown_field", f"{name} is not part of the HA connection"))
            continue
        cleaned, issue = _connection_change(name, value, locked)
        if issue is not None:
            errors.append(issue)
        elif cleaned is None:
            candidate.pop(name, None)
        else:
            candidate[name] = cleaned
    if not errors and _token_follows_url(connection, candidate, changes, locked):
        errors.append(
            Issue(
                "ha_token",
                "token_required",
                "a new Home Assistant URL needs its token in the same request",
            )
        )
    if errors:
        return errors, candidate, None
    try:
        settings = merge(base, locked, doc, candidate)
    except ValidationError as exc:
        issues = validation_issues(exc)
        for issue in issues:
            if issue.field is None and "ha_token is missing" in issue.message:
                issue = Issue("ha_token", "missing", "a Home Assistant URL needs a token")
            elif issue.field is None and "ha_url is missing" in issue.message:
                issue = Issue("ha_url", "missing", "a Home Assistant token needs the URL")
            errors.append(issue)
        return errors, candidate, None
    errors = store_rules(settings, doc, locked)
    return errors, candidate, None if errors else settings


def field_views(
    settings: Settings,
    locked: Mapping[str, Source],
    doc: Mapping[str, Any],
    connection: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return the ``fields`` of ``GET api/v1/config``: value, source, lock and stored value.

    Parameters
    ----------
    settings
        Effective settings.
    locked
        Fields provided by the environment or the options file.
    doc
        The stored document.
    connection
        The stored connection (``ha_url``, ``ha_token``); the token appears as
        ``set`` only.

    Returns
    -------
    dict
        Per field ``value`` (presets resolved; secrets ``set``/``unset``),
        ``source``, ``locked`` (also for every field that is not editable),
        ``stored`` (the stored value, active or not; ``set`` for a stored token)
        and ``default``.
    """
    stored_connection = dict(connection or {})
    views: dict[str, dict[str, Any]] = {}
    for name in Settings.model_fields:
        if name in locked:
            source = locked[name]
        elif (name in STORABLE and name in doc) or name in stored_connection:
            source = Source.STORE
        elif getattr(settings, name) is None and meta(name).preset:
            source = Source.PRESET
        else:
            source = Source.DEFAULT
        if name in STORED_CONNECTION:
            stored = stored_connection.get(name)
            if name in SECRET_FIELDS and stored is not None:
                stored = "set"
        else:
            stored = doc.get(name) if name in STORABLE else None
        views[name] = {
            "value": effective_value(settings, name),
            "source": source.value,
            "locked": name in locked or (name not in STORABLE and name not in STORED_CONNECTION),
            "stored": stored,
            "default": default_value(settings, name),
        }
    return views


MAX_HOST: Final = 253
MAX_MQTT_TEXT: Final = 128


def validate_mqtt(
    base: Settings,
    locked: Mapping[str, Source],
    doc: Mapping[str, Any],
    connection: Mapping[str, Any],
    changes: Mapping[str, Any],
    *,
    restoring: bool = False,
) -> tuple[list[Issue], dict[str, Any], Settings | None]:
    """Validate a change of the broker connection (``mqtt_*``, ``heishamon_base``).

    Parameters
    ----------
    base
        Installation settings.
    locked
        Fields provided by the environment or the options file.
    doc
        The stored document now.
    connection
        The stored connection now (HA and MQTT values).
    changes
        New values per field; ``None`` (or a blank string) removes the stored value, an
        absent field keeps it.
    restoring
        Whether the change puts a connection back that ran before (a revert): the
        password rules below do not apply.

    The password never follows the connection to another broker: when the effective
    host or port changes, TLS is switched off or the CA file changes
    (:func:`broker_moved`), a stored password is dropped unless the change brings
    ``mqtt_password`` again, and a password set by the deployment refuses the change
    (``password_locked``).

    Returns
    -------
    tuple
        The errors, the candidate connection (stored text values) and its merged
        settings (``None`` when invalid).
    """
    errors: list[Issue] = []
    candidate = dict(connection)
    for name, value in changes.items():
        if name not in MQTT_FIELDS:
            errors.append(Issue(name, "unknown_field", f"{name} is not part of the broker"))
            continue
        if name in locked:
            errors.append(_locked(name, locked))
            continue
        cleaned, issue = _mqtt_text(name, value)
        if issue is not None:
            errors.append(issue)
        elif cleaned is None:
            candidate.pop(name, None)
        else:
            candidate[name] = cleaned
    if errors:
        return errors, candidate, None
    try:
        settings = merge(base, locked, doc, candidate)
    except ValidationError as exc:
        return validation_issues(exc), candidate, None
    if not restoring and _moved(base, locked, doc, connection, settings):
        if "mqtt_password" in locked:
            return [_password_locked(locked)], candidate, None
        if "mqtt_password" not in changes and candidate.pop("mqtt_password", None) is not None:
            try:
                settings = merge(base, locked, doc, candidate)
            except ValidationError as exc:
                return validation_issues(exc), candidate, None
    errors = store_rules(settings, doc, locked)
    return errors, candidate, None if errors else settings


def broker_moved(before: Settings, after: Settings) -> bool:
    """Whether a password for ``before`` must not go to ``after``.

    That is when the host or the port differs, TLS is switched off or the CA file
    changes.
    """
    return (
        (before.mqtt_host, before.mqtt_port) != (after.mqtt_host, after.mqtt_port)
        or (before.mqtt_tls and not after.mqtt_tls)
        or before.mqtt_ca_file != after.mqtt_ca_file
    )


def _moved(
    base: Settings,
    locked: Mapping[str, Source],
    doc: Mapping[str, Any],
    connection: Mapping[str, Any],
    after: Settings,
) -> bool:
    try:
        before = merge(base, locked, doc, connection)
    except ValidationError:
        return True
    return broker_moved(before, after)


def _password_locked(locked: Mapping[str, Source]) -> Issue:
    source = locked["mqtt_password"].value
    return Issue(
        "mqtt_password",
        "password_locked",
        "the broker password is set by the deployment (OVENBIRD_MQTT_PASSWORD) and never "
        "goes to another host or port, without TLS or with another CA file: change the "
        "broker in the deployment",
        {"source": source, "env": "OVENBIRD_MQTT_PASSWORD"},
    )


def typed_mqtt(stored: Mapping[str, str | None]) -> dict[str, Any]:
    """Return stored broker text values as a change takes them (port int, TLS bool).

    Parameters
    ----------
    stored
        Broker fields as the connection table holds them (``None`` for unset).

    Returns
    -------
    dict
        The same fields for :func:`validate_mqtt`; a port or TLS text that does not
        parse stays text, so the validation reports it.
    """
    typed: dict[str, Any] = {}
    for name, value in stored.items():
        if value is not None and name == "mqtt_port" and value.strip().isdigit():
            typed[name] = int(value)
        elif value is not None and name == "mqtt_tls" and value in ("true", "false"):
            typed[name] = value == "true"
        else:
            typed[name] = value
    return typed


def _locked(name: str, locked: Mapping[str, Source]) -> Issue:
    source = locked[name].value
    return Issue(
        name,
        "locked",
        f"{name} is set by the {'environment' if source == 'env' else 'options file'}"
        f" (OVENBIRD_{name.upper()})",
        {"source": source, "env": f"OVENBIRD_{name.upper()}"},
    )


def _mqtt_text(name: str, value: Any) -> tuple[str | None, Issue | None]:
    """Return the stored text of one broker field, or the issue with it."""
    if value is None:
        return None, None
    if name == "mqtt_tls":
        if not isinstance(value, bool):
            return None, Issue(name, "type", f"{name} must be true or false")
        return ("true" if value else "false"), None
    if name == "mqtt_port":
        if isinstance(value, bool) or not isinstance(value, int):
            return None, Issue(name, "type", f"{name} must be a whole number")
        return str(value), None
    if not isinstance(value, str):
        return None, Issue(name, "type", f"{name} must be a string or null")
    text = value.strip()
    if not text:
        return None, None
    limit = MAX_HOST if name == "mqtt_host" else MAX_MQTT_TEXT
    spaced = name != "mqtt_ca_file" and any(char.isspace() for char in text)
    if len(text) > limit or spaced:
        return None, Issue(
            name, "invalid", f"{name} must be one word of at most {limit} characters"
        )
    if name == "mqtt_ca_file" and not Path(text).is_file():
        return None, Issue(name, "ca_file_missing", f"{name} {text!r} is not a readable file")
    return (value if name == "mqtt_password" else text), None

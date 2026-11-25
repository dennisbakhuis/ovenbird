"""The redacted diagnostics bundle (``GET api/v1/diagnostics``) for issue reports.

One JSON document (or a zip of its parts): version and "about", health, the
effective configuration without secrets, the control status with the safety
monitors, the last decisions, commands and alarm transitions, the notification
status, the trial status and the current signals.

Never in it: any secret field (passwords, tokens, the ntfy topic, the dead-man URL;
they appear as ``set``/``unset``), the audit trail, and what identifies the home or
the people in it: the location fields (:data:`PRIVATE_FIELDS`: latitude, longitude,
MQTT host, user and client id, the Home Assistant URL, the admin user name, allowed
origins, command brokers, other file paths; ``[removed]`` when set), the data and UI
directories (``<data_dir>``, ``<ui_dir>`` wherever they appear), every
``by``/``actor`` value (``[removed]``), the actor named in command details
(``release: [removed]: ...``), every IPv4/IPv6 address in any string (``[address]``)
and any key named like a coordinate. As a second line, every string anywhere in the
bundle that contains a configured secret value is replaced by ``[redacted]``.

What is left: the version, the effective control settings (curve, limits, room
signal and entity ids, HeishaMon base topic, ports, time zone), health, the
decision, command and alarm journals (values, reasons, the alarm messages), the
notification counters and host names of the ntfy and dead-man servers, the release
and trial status (snapshot values, outside temperatures) and the current signals.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final

from ovenbird import __version__
from ovenbird.clock import iso_z
from ovenbird.config import SECRET_FIELDS, Settings
from ovenbird.configstore.fields import effective_value
from ovenbird.history.journal import query_alarms, query_commands, query_decisions
from ovenbird.system.privacy import scrub_addresses

if TYPE_CHECKING:
    from ovenbird.trial.supervision import Supervision

FORMAT: Final = 1
DEFAULT_ITEMS: Final = 100
MAX_ITEMS: Final = 1000
REDACTED: Final = "[redacted]"
MIN_SECRET: Final = 4
REMOVED: Final = "[removed]"
PRIVATE_FIELDS: Final = frozenset(
    {
        "weather_latitude",
        "weather_longitude",
        "mqtt_host",
        "mqtt_username",
        "mqtt_client_id",
        "mqtt_ca_file",
        "ha_url",
        "admin_username",
        "http_allowed_origins",
        "command_brokers",
        "config_seed",
        "weather_sim_file",
    }
)
PERSON_KEYS: Final = frozenset({"by", "actor", "user", "username", "source_ip"})
COORDINATE_KEYS: Final = frozenset({"latitude", "longitude", "lat", "lon", "lng"})
ACTOR_PREFIX: Final = re.compile(r"^(release|operator): .*?: ")


def secret_values(settings: Settings) -> list[str]:
    """Return every configured secret value (longest first)."""
    found: list[str] = []
    for name in SECRET_FIELDS:
        value = getattr(settings, name, None)
        if value is None:
            continue
        text = value.get_secret_value() if hasattr(value, "get_secret_value") else str(value)
        if len(text) >= MIN_SECRET:
            found.append(text)
    return sorted(set(found), key=len, reverse=True)


def redact(value: Any, secrets: list[str]) -> Any:
    """Return ``value`` with every string containing a secret replaced by ``[redacted]``."""
    if isinstance(value, dict):
        return {key: redact(item, secrets) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str) and any(secret in value for secret in secrets):
        return REDACTED
    return value


def effective_config(settings: Settings) -> dict[str, Any]:
    """Return every effective setting; secrets as ``set``/``unset``, private fields removed."""
    values = {name: effective_value(settings, name) for name in Settings.model_fields}
    for name in PRIVATE_FIELDS & values.keys():
        value = values[name]
        values[name] = None if value in (None, [], "") else REMOVED
    return values


def scrub(value: Any, key: str | None = None, paths: Mapping[str, str] | None = None) -> Any:
    """Return ``value`` without names, addresses, coordinates and local paths.

    Parameters
    ----------
    value
        Any JSON value.
    key
        The key ``value`` is stored under (``by``, ``actor``, coordinates are removed).
    paths
        Local directories to replace by a placeholder (``{"/home/x/data": "<data_dir>"}``).

    Returns
    -------
    Any
        The scrubbed copy.
    """
    if key in PERSON_KEYS and value is not None:
        return REMOVED
    if key in COORDINATE_KEYS and value is not None:
        return REMOVED
    if isinstance(value, dict):
        return {name: scrub(item, name, paths) for name, item in value.items()}
    if isinstance(value, list | tuple):
        return [scrub(item, None, paths) for item in value]
    if isinstance(value, str):
        for path, placeholder in (paths or {}).items():
            value = value.replace(path, placeholder)
        return ACTOR_PREFIX.sub(r"\1: [removed]: ", scrub_addresses(value))
    return value


def bundle(
    supervision: Supervision,
    items: int = DEFAULT_ITEMS,
    history: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the diagnostics bundle (redacted).

    Parameters
    ----------
    supervision
        The service's supervision view.
    items
        How many of the newest decisions, commands and alarm transitions to include.
    history
        :meth:`~ovenbird.trial.supervision.Supervision.history_facts`, computed when omitted.

    Returns
    -------
    dict
        The bundle; see the module docstring.
    """
    now = supervision.now()
    settings = supervision.current()
    path = settings.history_path
    end = now.wall.timestamp() + 1.0
    loop = supervision.control
    config = supervision.config
    decisions = query_decisions(path, 0.0, end, items)
    commands = query_commands(path, 0.0, end, items)
    alarms = query_alarms(path, 0.0, end, items)
    body: dict[str, Any] = {
        "ovenbird_diagnostics": FORMAT,
        "generated_at": iso_z(now.wall),
        "version": __version__,
        "about": supervision.about(now),
        "health": supervision.runtime.health(now),
        "config": {
            "version": None if config is None else config.version,
            "applied_version": None if config is None else config.applied_version,
            "locked": [] if config is None else sorted(config.locked),
            "effective": effective_config(settings),
        },
        "control": None if loop is None else loop.status(),
        "decisions": [row.payload() for row in decisions],
        "commands": [row.to_json() for row in commands],
        "alarms": {
            "active": [] if loop is None else [a.to_json() for a in loop.alarms.active()],
            "events": [row.to_json() for row in alarms],
        },
        "notifications": None if supervision.notifier is None else supervision.notifier.status(),
        "release": None
        if loop is None or loop.release is None
        else {
            **loop.release.snapshot_payload(),
            "last": loop.release.last(),
            "last_rehearsal": loop.release.last_rehearsal(),
        },
        "trial": supervision.status(now, history=history),
        "signals": supervision.runtime.snapshot(now),
    }
    secrets = secret_values(settings)
    if supervision.notifier is not None:
        secrets = sorted({*secrets, *supervision.notifier.secrets()}, key=len, reverse=True)
    paths = {
        str(settings.data_dir.resolve()): "<data_dir>",
        str(settings.data_dir): "<data_dir>",
        str(settings.ui_dir): "<ui_dir>",
    }
    redacted: dict[str, Any] = scrub(redact(body, secrets), None, paths)
    return redacted


def to_zip(body: dict[str, Any]) -> bytes:
    """Return the bundle as a zip with one JSON file per top-level part."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, part in body.items():
            text = json.dumps(part, indent=2, ensure_ascii=False, default=str)
            archive.writestr(f"{name}.json", text)
    return buffer.getvalue()

"""Where the settings come from: environment names, the options file and ingress defaults.

Enabling commands must be an explicit, local decision, so :data:`ENV_ONLY_FIELDS` are
never read from the options file. Secrets are listed in :data:`SECRET_FIELDS`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Final

from pydantic_settings import (
    JsonConfigSettingsSource,
)

ENV_PREFIX: Final = "OVENBIRD_"
OPTIONS_FILE_ENV: Final = "OVENBIRD_OPTIONS_FILE"
DATA_DIR_ENV: Final = "OVENBIRD_DATA_DIR"
DEFAULT_OPTIONS_FILE: Final = Path("/data/options.json")
DEFAULT_DATA_DIR: Final = Path("/data")
DEFAULT_UI_DIR: Final = Path("/opt/ovenbird/ui")
DEFAULT_HTTP_PORT: Final = 8099
SUPERVISOR_TOKEN_ENV: Final = "SUPERVISOR_TOKEN"  # noqa: S105
SUPERVISOR_HA_URL: Final = "http://supervisor/core"
INGRESS_SOURCE: Final = "172.30.32.2"
INGRESS_BIND_HOST: Final = "0.0.0.0"  # noqa: S104
ENV_ONLY_FIELDS: Final = frozenset(
    {"allow_commands", "command_brokers", "simulation", "operate_token"}
)
SECRET_FIELDS: Final = frozenset(
    {
        "mqtt_password",
        "ha_token",
        "admin_password",
        "operate_token",
        "notify_ntfy_topic",
        "notify_ntfy_token",
        "notify_deadman_url",
    }
)


def options_file() -> Path:
    """Return the options file path (``OVENBIRD_OPTIONS_FILE`` or ``/data/options.json``)."""
    raw = os.environ.get(OPTIONS_FILE_ENV)
    return Path(raw) if raw else DEFAULT_OPTIONS_FILE


def split_list(raw: Any) -> Any:
    """Split a comma-separated or JSON list from the environment; other values pass."""
    if not isinstance(raw, str):
        return raw
    text = raw.strip()
    if not text:
        return ()
    if text.startswith("["):
        return json.loads(text)
    return tuple(part.strip() for part in text.split(",") if part.strip())


class OptionsFileSource(JsonConfigSettingsSource):
    """The options file, without the fields that may only come from the environment.

    Enabling commands must be an explicit, local decision (``OVENBIRD_ALLOW_COMMANDS``
    and ``OVENBIRD_COMMAND_BROKERS``); an options file written by an app supervisor or
    copied from another installation can never switch publishing on.
    """

    def __call__(self) -> dict[str, Any]:
        """Return the options without :data:`ENV_ONLY_FIELDS`."""
        return {k: v for k, v in super().__call__().items() if k not in ENV_ONLY_FIELDS}


def apply_ingress_mode(data: Any) -> Any:
    """Return the raw settings with the Home Assistant app's ingress defaults applied.

    Ingress is on when ``ingress`` says so, or by default when the supervisor token is
    present. It binds all interfaces and, with no HA connection configured, uses the
    supervisor's proxy and token.

    Parameters
    ----------
    data
        The raw settings before field validation.

    Returns
    -------
    Any
        ``data`` unchanged outside ingress mode, else a copy with the defaults.
    """
    if not isinstance(data, dict):
        return data
    token = os.environ.get(SUPERVISOR_TOKEN_ENV)
    enabled = data.get("ingress")
    if enabled is None:
        enabled = bool(token)
    if enabled is not True and str(enabled).lower() not in {"true", "1", "yes", "on"}:
        return data
    values = dict(data)
    values["ingress"] = True
    values.setdefault("http_host", INGRESS_BIND_HOST)
    if token and not values.get("ha_url") and not values.get("ha_token"):
        values["ha_url"] = SUPERVISOR_HA_URL
        values["ha_token"] = token
    return values

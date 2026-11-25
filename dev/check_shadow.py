"""Check a deployed ovenbird in shadow mode through its API, read-only.

Usage::

    OVENBIRD_ADMIN_PASSWORD=... uv run python dev/check_shadow.py --url https://ovenbird.example
        [--user admin] [--window-h 1] [--min-compared 5]

Only ``GET`` requests to ovenbird itself; it never talks to the broker or Home Assistant.
Exits 0 when the health check is live and ready with MQTT connected, HeishaMon alive,
Home Assistant connected (or disabled) and history written; the configured and effective
mode are ``shadow``; ``allow_commands`` is off, ``command_brokers`` is empty, the
installation is not a simulation and runs on the real clock; the latest decision reports
no publishing and no command adapter; a decision was recorded; the room input is fresh;
the shadow divergence compared at least ``--min-compared`` minutes in the window; and
the UI index is served. The admin password comes from ``OVENBIRD_ADMIN_PASSWORD`` so it
never shows in the process list.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Final

PASSWORD_ENV: Final = "OVENBIRD_ADMIN_PASSWORD"  # noqa: S105
TIMEOUT_S: Final = 30


def fetch(url: str, path: str, auth: str | None, params: dict[str, Any] | None = None) -> Any:
    """Return the decoded JSON (or text) of ``GET url/path``.

    Parameters
    ----------
    url
        Base URL of the service, without a trailing slash.
    path
        Path below the base URL.
    auth
        Base64 Basic credentials, or ``None`` for an unauthenticated request.
    params
        Query parameters.

    Returns
    -------
    Any
        Parsed JSON for a JSON response, the body text otherwise.
    """
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    headers = {"Authorization": f"Basic {auth}"} if auth else {}
    request = urllib.request.Request(f"{url}/{path}{query}", headers=headers)  # noqa: S310
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
        body = response.read().decode("utf-8")
        if "json" in response.headers.get("Content-Type", ""):
            return json.loads(body)
        return body


def field_value(config: dict[str, Any], name: str) -> Any:
    """Return the effective value of one field of ``GET api/v1/config``."""
    return (config.get("fields", {}).get(name) or {}).get("value")


def evaluate(
    health: dict[str, Any],
    config: dict[str, Any],
    latest: dict[str, Any],
    about: dict[str, Any],
    divergence: dict[str, Any],
    index: Any,
    min_compared: int,
) -> dict[str, bool]:
    """Return every shadow check by name with its outcome.

    Parameters
    ----------
    health, config, latest, about, divergence
        Bodies of ``api/v1/health``, ``api/v1/config``, ``api/v1/decisions/latest``,
        ``api/v1/system/about`` and ``api/v1/shadow/divergence``.
    index
        Body of the UI index.
    min_compared
        Compared minutes the divergence window needs.

    Returns
    -------
    dict
        Check name to ``True`` (pass) or ``False`` (fail).
    """
    checks = health.get("checks", {})
    mode = config.get("mode", {})
    control = latest.get("control") or {}
    room = control.get("room") or {}
    summary = divergence.get("summary") or {}
    return {
        "health live and ready": health.get("live") is True and health.get("ready") is True,
        "MQTT connected, HeishaMon alive": checks.get("mqtt") == "connected"
        and checks.get("heishamon") == "alive",
        "Home Assistant connected": checks.get("ha") in {"connected", "disabled"},
        "history written": checks.get("history") == "ok",
        "configured mode shadow": mode.get("configured") == "shadow",
        "effective mode shadow": mode.get("effective") == "shadow"
        and control.get("mode") == "shadow",
        "allow_commands off": field_value(config, "allow_commands") is False,
        "command_brokers empty": not field_value(config, "command_brokers"),
        "real clock, no simulation": about.get("simulation") is False
        and about.get("clock_speed") == 1.0,
        "not publishing, no command adapter": control.get("publishing") is False
        and control.get("adapter") is None,
        "a decision recorded": latest.get("decision") is not None,
        "room input fresh": room.get("signal") is None or room.get("fresh") is True,
        f"divergence compared at least {min_compared} min": (summary.get("compared_minutes") or 0)
        >= min_compared,
        "UI index served": isinstance(index, str) and "<" in index,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the checks and print them; return the exit code."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--url", required=True, help="base URL, e.g. https://ovenbird.example")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--window-h", type=float, default=1.0, help="divergence window (hours)")
    parser.add_argument("--min-compared", type=int, default=5, help="compared minutes needed")
    args = parser.parse_args(argv)
    password = os.environ.get(PASSWORD_ENV)
    if not password:
        parser.error(f"set {PASSWORD_ENV} to the admin password")
    url = args.url.rstrip("/")
    auth = base64.b64encode(f"{args.user}:{password}".encode()).decode()
    now = datetime.now(UTC)
    window = {
        "from": (now - timedelta(hours=args.window_h)).isoformat().replace("+00:00", "Z"),
        "to": now.isoformat().replace("+00:00", "Z"),
    }
    try:
        health = fetch(url, "api/v1/health", None)
        config = fetch(url, "api/v1/config", auth)
        latest = fetch(url, "api/v1/decisions/latest", auth)
        about = fetch(url, "api/v1/system/about", auth)
        divergence = fetch(url, "api/v1/shadow/divergence", auth, window)
        index = fetch(url, "", auth)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"FAIL  cannot read {url}: {exc}")
        return 1

    control = latest.get("control") or {}
    room = control.get("room") or {}
    summary = divergence.get("summary") or {}
    print(f"version          {health.get('version')} (api {health.get('api_version')})")
    print(f"health           live={health.get('live')} ready={health.get('ready')}")
    print(f"checks           {health.get('checks')}")
    print(f"mode             {config.get('mode')}")
    print(f"refusals         {control.get('refusals')}")
    print(
        f"room input       {room.get('signal')} value {room.get('value')} "
        f"fresh {room.get('fresh')} alive by {room.get('alive_by')}"
    )
    print(
        f"divergence       {summary.get('compared_minutes')} of {summary.get('minutes')} min "
        f"compared, mean |diff| {summary.get('mean_abs_k')} K, episodes {summary.get('episodes')}"
    )
    decision = latest.get("decision") or {}
    print(f"latest note      {decision.get('note')}")

    checks = evaluate(health, config, latest, about, divergence, index, args.min_compared)
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())

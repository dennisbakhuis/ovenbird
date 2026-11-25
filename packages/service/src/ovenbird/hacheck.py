"""Test a Home Assistant connection (``POST api/v1/config/ha/test``), read-only.

The check makes three kinds of read-only calls with a short timeout and returns a
structured result; it never changes anything in Home Assistant and never logs or
returns the token:

1. ``GET <base>/api/`` with the token (reachable, token accepted, latency).
2. The WebSocket API: ``auth`` (Home Assistant's version), ``get_config`` (its
   temperature unit) and ``get_states``.
3. The chosen ``ha/`` signals against those states: found, value, unit and, for a
   room temperature input, whether the unit rule of :mod:`ovenbird.ha` accepts it.

Neither the HTTP request nor the WebSocket handshake follows a redirect (the token
would go to another URL), no proxy is used, and the whole check, name lookups
included, ends within :func:`check_deadline` seconds.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final
from urllib.parse import urlsplit, urlunsplit

from pydantic import SecretStr
from websockets.exceptions import WebSocketException

from ovenbird.config.validation.ha import check_ha_url
from ovenbird.ha import WS_LOGGER, Connector, EntityState, NoRedirectConnect, websocket_url
from ovenbird_core.inputs import (
    CELSIUS,
    HA_UNAVAILABLE,
    attribute_supported,
    parse_number,
    split_ha_signal,
    temperature_unit,
)

CHECK_TIMEOUT_S: Final = 5.0
MAX_BODY_BYTES: Final = 64 * 1024
MAX_MESSAGE_BYTES: Final = 32 * 1024 * 1024
WEBSOCKET_SUFFIX: Final = "/websocket"
CONFIG_ID: Final = 1
STATES_ID: Final = 2
HTTP_OK: Final = 200
HTTP_UNAUTHORIZED: Final = frozenset({401, 403})
ERROR_CODES: Final = (
    "invalid_url",
    "not_configured",
    "token_required",
    "unreachable",
    "auth_failed",
    "http_error",
    "protocol",
    "timeout",
    "websocket",
)
"""Every ``error_code`` of a failed test, in the order of the steps."""

type HttpGet = Callable[[str, str, float], Awaitable[tuple[int, bytes]]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def rest_url(base_url: str) -> str:
    """Return the REST API root (``<base>/api/``) of an HA base or WebSocket URL."""
    parts = urlsplit(websocket_url(base_url))
    path = parts.path[: -len(WEBSOCKET_SUFFIX)]
    if not path.endswith("/api"):
        path += "/api"
    scheme = "https" if parts.scheme == "wss" else "http"
    return urlunsplit((scheme, parts.netloc, path + "/", "", ""))


def _get(url: str, token: str, timeout: float) -> tuple[int, bytes]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request(  # noqa: S310
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            return int(response.status), response.read(MAX_BODY_BYTES)
    except urllib.error.HTTPError as exc:
        return int(exc.code), b""


async def http_get(url: str, token: str, limit_s: float) -> tuple[int, bytes]:
    """GET ``url`` with the bearer token in a worker thread; ``OSError`` when unreachable."""
    return await asyncio.to_thread(_get, url, token, limit_s)


def check_deadline(limit_s: float) -> float:
    """Return the overall limit of a check: the HTTP step, the WebSocket step and a margin."""
    return limit_s * 3 + 1.0


def _connector(timeout: float) -> Connector:
    def open_connection(url: str) -> Any:
        return NoRedirectConnect(
            url,
            open_timeout=timeout,
            close_timeout=1,
            max_size=MAX_MESSAGE_BYTES,
            proxy=None,
            logger=WS_LOGGER,
        )

    return open_connection


@dataclass
class EntityCheck:
    """What the check found for one ``ha/`` signal."""

    signal: str
    entity_id: str
    found: bool = False
    state: str | None = None
    value: float | None = None
    unit: str | None = None
    problem: str | None = None

    def to_json(self) -> dict[str, Any]:
        """Return the JSON form."""
        return {
            "signal": self.signal,
            "entity_id": self.entity_id,
            "found": self.found,
            "state": self.state,
            "value": self.value,
            "unit": self.unit,
            "problem": self.problem,
        }


@dataclass
class CheckResult:
    """The structured outcome of a connection test."""

    url: str | None
    reachable: bool = False
    auth_ok: bool | None = None
    ha_version: str | None = None
    latency_ms: float | None = None
    temperature_unit: str | None = None
    entities: list[EntityCheck] = field(default_factory=list)
    error: str | None = None
    error_code: str | None = None

    @property
    def ok(self) -> bool:
        """Reachable, the token accepted, and every entity found without a problem."""
        return (
            self.error is None
            and self.reachable
            and self.auth_ok is True
            and all(item.found and item.problem is None for item in self.entities)
        )

    def fail(self, code: str, message: str) -> CheckResult:
        """Record the first failure and return the result."""
        if self.error is None:
            self.error_code, self.error = code, message
        return self

    def to_json(self) -> dict[str, Any]:
        """Return the body of ``POST api/v1/config/ha/test``."""
        return {
            "ok": self.ok,
            "url": self.url,
            "reachable": self.reachable,
            "auth_ok": self.auth_ok,
            "ha_version": self.ha_version,
            "latency_ms": self.latency_ms,
            "temperature_unit": self.temperature_unit,
            "metric": None if self.temperature_unit is None else self.temperature_unit == CELSIUS,
            "entities": [item.to_json() for item in self.entities],
            "error": self.error,
            "error_code": self.error_code,
        }


def _scrubbed(text: str, token: str) -> str:
    return text.replace(token, "[token]") if token else text


def _entity_check(
    signal: str, states: dict[str, EntityState], temperature: bool, unit_system: str | None
) -> EntityCheck:
    parts = split_ha_signal(signal)
    entity_id, attribute = parts if parts is not None else (signal, None)
    check = EntityCheck(signal, entity_id)
    state = states.get(entity_id)
    if state is None:
        check.problem = "not found in Home Assistant"
        return check
    check.found = True
    check.state = state.state
    if attribute is not None:
        if not attribute_supported(entity_id, attribute):
            check.problem = f"attribute {attribute} is not supported"
            return check
        raw = state.attributes.get(attribute)
        number = float(raw) if isinstance(raw, int | float) and not isinstance(raw, bool) else None
        check.value, check.unit = number, unit_system
        if number is None:
            check.problem = f"no numeric {attribute}"
        unit = unit_system
    else:
        check.value, check.unit = parse_number(state.state), state.unit
        unit = state.unit
        if state.state.strip().lower() in HA_UNAVAILABLE:
            check.problem = "unavailable"
        elif temperature and check.value is None:
            check.problem = "not a number"
    if (
        check.problem is None
        and temperature
        and temperature_unit(unit) is None
        and unit_system != CELSIUS
    ):
        check.problem = (
            "no temperature unit and Home Assistant's unit system is not metric; "
            "it would not be used as a room temperature"
        )
    return check


async def _websocket(
    result: CheckResult,
    url: str,
    token: str,
    signals: Sequence[str],
    temperature: frozenset[str],
    connector: Connector,
) -> None:
    async with connector(websocket_url(url)) as ws:
        hello = json.loads(await ws.recv())
        if not isinstance(hello, dict) or hello.get("type") != "auth_required":
            result.fail("protocol", "the WebSocket API did not ask for authentication")
            return
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        reply = json.loads(await ws.recv())
        kind = reply.get("type") if isinstance(reply, dict) else None
        if kind == "auth_invalid":
            result.auth_ok = False
            result.fail("auth_failed", "Home Assistant rejected the token (WebSocket API)")
            return
        if kind != "auth_ok":
            result.fail("protocol", f"unexpected WebSocket answer {kind!r}")
            return
        version = reply.get("ha_version") or hello.get("ha_version")
        result.ha_version = version if isinstance(version, str) else result.ha_version
        await ws.send(json.dumps({"id": CONFIG_ID, "type": "get_config"}))
        await ws.send(json.dumps({"id": STATES_ID, "type": "get_states"}))
        states: dict[str, EntityState] | None = None
        while states is None:
            message = json.loads(await ws.recv())
            if not isinstance(message, dict):
                continue
            if message.get("id") == CONFIG_ID and isinstance(message.get("result"), dict):
                units = message["result"].get("unit_system")
                unit = units.get("temperature") if isinstance(units, dict) else None
                result.temperature_unit = unit if isinstance(unit, str) else None
            elif message.get("id") == STATES_ID:
                items = message.get("result") if message.get("success") else None
                if not isinstance(items, list):
                    result.fail("protocol", "Home Assistant did not return its states")
                    return
                states = {
                    str(item["entity_id"]): EntityState.from_full(item)
                    for item in items
                    if isinstance(item, dict) and isinstance(item.get("entity_id"), str)
                }
    result.entities = [
        _entity_check(signal, states, signal in temperature, result.temperature_unit)
        for signal in signals
    ]


async def check_connection(
    url: str | None,
    token: SecretStr | None,
    signals: Sequence[str] = (),
    *,
    temperature: frozenset[str] = frozenset(),
    limit_s: float = CHECK_TIMEOUT_S,
    get: HttpGet | None = None,
    connector: Connector | None = None,
) -> dict[str, Any]:
    """Test a Home Assistant URL and token without changing anything.

    Parameters
    ----------
    url
        HA base URL (or WebSocket URL).
    token
        Long-lived access token; never logged or returned.
    signals
        ``ha/`` signals whose entities must exist.
    temperature
        Those of ``signals`` that are read as a room temperature (unit rule).
    limit_s
        Seconds for each step; the whole check ends within :func:`check_deadline`.
    get
        HTTP GET (tests pass a fake); the stdlib one otherwise.
    connector
        WebSocket connector (tests pass a fake server's).

    Returns
    -------
    dict
        The body of ``POST api/v1/config/ha/test``.
    """
    try:
        base = check_ha_url(url)
    except ValueError as exc:
        return CheckResult(None).fail("invalid_url", str(exc)).to_json()
    if base is None:
        return CheckResult(None).fail("not_configured", "no Home Assistant URL").to_json()
    result = CheckResult(base)
    secret = "" if token is None else token.get_secret_value()
    if not secret:
        return result.fail("token_required", "no access token to test with").to_json()
    fetch = get or http_get
    deadline = check_deadline(limit_s)
    try:
        async with asyncio.timeout(deadline):
            await _steps(result, base, secret, signals, temperature, limit_s, fetch, connector)
    except TimeoutError:
        result.fail("timeout", f"the check did not finish within {deadline:g} s")
    return result.to_json()


async def _steps(
    result: CheckResult,
    base: str,
    secret: str,
    signals: Sequence[str],
    temperature: frozenset[str],
    limit_s: float,
    fetch: HttpGet,
    connector: Connector | None,
) -> None:
    started = time.monotonic()
    try:
        status, _ = await asyncio.wait_for(fetch(rest_url(base), secret, limit_s), limit_s + 1.0)
    except (OSError, TimeoutError, ValueError) as exc:
        reason = getattr(exc, "reason", None) or exc
        message = f"cannot reach {rest_url(base)}: {type(reason).__name__}: {reason}"
        result.fail("unreachable", _scrubbed(message, secret))
        return
    result.latency_ms = round((time.monotonic() - started) * 1000.0, 1)
    result.reachable = True
    if status in HTTP_UNAUTHORIZED:
        result.auth_ok = False
        result.fail("auth_failed", "Home Assistant rejected the token")
        return
    if status != HTTP_OK:
        result.fail(
            "http_error",
            f"{rest_url(base)} answered HTTP {status} (not Home Assistant's API, or a "
            "redirect: use the final URL)",
        )
        return
    result.auth_ok = True
    try:
        await asyncio.wait_for(
            _websocket(
                result, base, secret, signals, temperature, connector or _connector(limit_s)
            ),
            limit_s * 2,
        )
    except TimeoutError:
        result.fail("timeout", f"the WebSocket API did not answer within {limit_s * 2:g} s")
    except (WebSocketException, OSError, ValueError) as exc:
        message = f"WebSocket API failed: {type(exc).__name__}: {exc}"
        result.fail("websocket", _scrubbed(message, secret))

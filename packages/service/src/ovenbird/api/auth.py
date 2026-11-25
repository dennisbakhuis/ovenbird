"""Authentication (admin Basic, operate bearer token), roles, lockout and the Origin check.

Requests from trusted source addresses (the Home Assistant ingress proxy) skip the
credential check and act as admin. Every other source presents either the admin's
HTTP Basic credentials (role ``admin``) or ``Authorization: Bearer
<OVENBIRD_OPERATE_TOKEN>`` (role ``operate``); without a configured admin password a
loopback-only service also serves requests without credentials (role ``read``). The
role is stamped into the ASGI scope for the endpoints (:func:`scope_role`). A source
that keeps sending wrong credentials for a username (or a wrong token) is locked out
for that key with an exponential backoff; correct credentials are never blocked by
failures under another username.
WebSocket handshakes from browsers must come from the service's own origin or a
configured one, so a foreign web page cannot open the live feed with the user's
credentials (cross-site WebSocket hijacking). Safari never sends the login on a WebSocket,
so the page first fetches a short-lived single-use pass (:class:`LiveTickets`) and opens
the live connection with it.
"""

from __future__ import annotations

import base64
import math
import secrets
import time
from collections import OrderedDict
from collections.abc import Callable, Collection, Hashable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final
from urllib.parse import parse_qs, urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

REALM: Final = "ovenbird"
POLICY_VIOLATION: Final = 1008
FREE_ATTEMPTS: Final = 5
BASE_LOCKOUT_S: Final = 1.0
MAX_LOCKOUT_S: Final = 300.0
FORGET_AFTER_S: Final = 900.0
MAX_TRACKED_SOURCES: Final = 4096
MAX_USERNAME_KEY: Final = 128
DEFAULT_PORTS: Final = {"http": 80, "https": 443, "ws": 80, "wss": 443}
ROLE_SCOPE_KEY: Final = "ovenbird.role"
BEARER_KEY: Final = "\x00bearer"
TICKET_TTL_S: Final = 30.0
MAX_TICKETS: Final = 256
TICKET_PARAM: Final = "ticket"


class Role(StrEnum):
    """What a request may do: ``read`` < ``operate`` < ``admin``."""

    READ = "read"
    OPERATE = "operate"
    ADMIN = "admin"

    @property
    def rank(self) -> int:
        """Position in the order read < operate < admin."""
        return ROLE_RANK[self]


ROLE_RANK: Final = {Role.READ: 0, Role.OPERATE: 1, Role.ADMIN: 2}


def scope_role(scope: Mapping[str, Any]) -> Role:
    """Return the role the authentication middleware stamped on a request (``read`` if none)."""
    role = scope.get(ROLE_SCOPE_KEY)
    return role if isinstance(role, Role) else Role.READ


@dataclass(slots=True)
class _Failures:
    count: int
    last: float
    locked_until: float


class FailedAuthLimiter:
    """Per-key failed-login counter with exponential lockout.

    A key is typically ``(source, username)``.

    The first ``free_attempts`` failures are free; every further failure locks the
    key out for ``base_lockout * 2**(n - free_attempts)`` seconds, capped at
    ``max_lockout``. A success, or ``forget_after`` seconds without failures,
    resets the key. At most ``max_sources`` keys are tracked (the least
    recently failing one is forgotten first).

    Parameters
    ----------
    free_attempts, base_lockout, max_lockout, forget_after, max_sources
        Policy, see above.
    clock
        Monotonic time source.
    """

    def __init__(
        self,
        *,
        free_attempts: int = FREE_ATTEMPTS,
        base_lockout: float = BASE_LOCKOUT_S,
        max_lockout: float = MAX_LOCKOUT_S,
        forget_after: float = FORGET_AFTER_S,
        max_sources: int = MAX_TRACKED_SOURCES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.free_attempts = free_attempts
        self.base_lockout = base_lockout
        self.max_lockout = max_lockout
        self.forget_after = forget_after
        self.max_sources = max_sources
        self._clock = clock
        self._sources: OrderedDict[Hashable, _Failures] = OrderedDict()

    def _current(self, source: Hashable, now: float) -> _Failures | None:
        entry = self._sources.get(source)
        if entry is not None and now - entry.last > self.forget_after and now >= entry.locked_until:
            del self._sources[source]
            return None
        return entry

    def retry_after(self, source: Hashable) -> float:
        """Seconds ``source`` is still locked out (0 when it may try)."""
        now = self._clock()
        entry = self._current(source, now)
        return 0.0 if entry is None else max(0.0, entry.locked_until - now)

    def failure(self, source: Hashable) -> None:
        """Count a failed login from ``source``."""
        now = self._clock()
        entry = self._current(source, now) or _Failures(0, now, now)
        entry.count += 1
        entry.last = now
        excess = entry.count - self.free_attempts
        if excess >= 0:
            delay = min(self.max_lockout, self.base_lockout * 2.0 ** min(excess, 32))
            entry.locked_until = now + delay
        self._sources[source] = entry
        self._sources.move_to_end(source)
        while len(self._sources) > self.max_sources:
            self._sources.popitem(last=False)

    def success(self, source: Hashable) -> None:
        """Reset ``source`` after a successful login."""
        self._sources.pop(source, None)


class LiveTickets:
    """Single-use passes that open the live connection (WebSocket) for an authenticated page.

    A pass carries the role of the request that got it, is valid for ``ttl`` seconds and
    for one handshake. At most ``capacity`` passes are outstanding; the oldest is dropped
    first.

    Parameters
    ----------
    ttl
        Seconds a pass stays valid.
    capacity
        Most outstanding passes.
    clock
        Monotonic time source.
    """

    def __init__(
        self,
        *,
        ttl: float = TICKET_TTL_S,
        capacity: int = MAX_TICKETS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl = ttl
        self.capacity = capacity
        self._clock = clock
        self._tickets: OrderedDict[str, tuple[float, Role]] = OrderedDict()

    def _prune(self, now: float) -> None:
        while self._tickets and next(iter(self._tickets.values()))[0] <= now:
            self._tickets.popitem(last=False)

    def issue(self, role: Role) -> str:
        """Return a new pass for ``role``."""
        now = self._clock()
        self._prune(now)
        ticket = secrets.token_urlsafe(32)
        self._tickets[ticket] = (now + self.ttl, role)
        while len(self._tickets) > self.capacity:
            self._tickets.popitem(last=False)
        return ticket

    def redeem(self, ticket: str | None) -> Role | None:
        """Use up ``ticket`` and return its role, or ``None`` when it is unknown or expired."""
        if not ticket:
            return None
        now = self._clock()
        self._prune(now)
        entry = self._tickets.pop(ticket, None)
        return None if entry is None else entry[1]


def _query_ticket(scope: Scope) -> str | None:
    raw = bytes(scope.get("query_string") or b"").decode("latin-1")
    values = parse_qs(raw).get(TICKET_PARAM)
    return values[0] if values else None


def _decode_basic(header: bytes | None) -> tuple[bytes, bytes] | None:
    if header is None:
        return None
    scheme, _, encoded = header.partition(b" ")
    if scheme.lower() != b"basic":
        return None
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True)
    except ValueError:
        return None
    user, sep, password = decoded.partition(b":")
    return (user, password) if sep else None


def credentials_match(header: bytes | None, username: str, password: str) -> bool:
    """Whether an ``Authorization`` header carries the expected Basic credentials.

    Parameters
    ----------
    header
        Raw header value, if present.
    username, password
        Expected credentials.

    Returns
    -------
    bool
        ``True`` only for a well-formed Basic header with matching credentials;
        the comparison is constant-time.
    """
    given = _decode_basic(header)
    if given is None:
        return False
    user_ok = secrets.compare_digest(given[0], username.encode("utf-8"))
    password_ok = secrets.compare_digest(given[1], password.encode("utf-8"))
    return user_ok and password_ok


def bearer_matches(header: bytes | None, token: str) -> bool:
    """Whether an ``Authorization`` header carries ``Bearer <token>`` (constant-time)."""
    if header is None:
        return False
    scheme, _, given = header.partition(b" ")
    if scheme.lower() != b"bearer":
        return False
    return secrets.compare_digest(given.strip(), token.encode("utf-8"))


def is_bearer(header: bytes | None) -> bool:
    """Whether an ``Authorization`` header uses the ``Bearer`` scheme."""
    return header is not None and header.partition(b" ")[0].lower() == b"bearer"


def limiter_key(source: str, header: bytes | None) -> tuple[str, str]:
    """Return the ``(source, username)`` key a login attempt is rate limited under.

    Bearer tokens share one key per source, apart from every Basic username.
    """
    if is_bearer(header):
        return source, BEARER_KEY
    given = _decode_basic(header)
    name = "" if given is None else given[0].decode("utf-8", "replace")[:MAX_USERNAME_KEY]
    return source, name


def _source(scope: Scope) -> str:
    client = scope.get("client")
    return str(client[0]) if client else "unknown"


def _header(scope: Scope, name: bytes) -> bytes | None:
    for key, value in scope.get("headers") or ():
        if key.lower() == name:
            return bytes(value)
    return None


async def _reject(
    send: Send, scope: Scope, status: int, detail: str, headers: list[tuple[bytes, bytes]]
) -> None:
    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": POLICY_VIOLATION})
        return
    body = f'{{"detail":"{detail}"}}'.encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                *headers,
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class BasicAuthMiddleware:
    """ASGI middleware authenticating HTTP and WebSocket requests and stamping their role.

    Admin Basic credentials give ``admin``, the operate bearer token ``operate``, a
    trusted source (ingress) ``admin``. A request that carries wrong credentials (or
    a wrong token) counts as a failed login of its ``(source address, username)``
    key; a locked-out key gets ``429`` (WebSocket: close ``1008``) without its
    credentials being checked until the lockout ends. Failures under other usernames
    never lock out the configured one. With ``required`` (an admin password or app
    mode) requests without credentials get the ``401`` challenge and do not count;
    without it they are served as ``read`` (a Basic header is then ignored, a wrong
    bearer token still refused). A WebSocket handshake with a valid ``?ticket=`` pass
    (:class:`LiveTickets`) is served with the pass's role; an invalid pass falls back to
    the checks above.

    Parameters
    ----------
    app
        Wrapped application.
    username, password
        Expected admin credentials.
    exempt
        Paths served without authentication.
    trusted_sources
        Client addresses served as admin without authentication.
    limiter
        Failed-login rate limiter; a default one when omitted.
    operate_token
        Bearer token of the operate role; ``None`` disables it.
    required
        Whether every other request must authenticate.
    tickets
        Live-connection passes accepted on WebSocket handshakes; ``None`` accepts none.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        username: str,
        password: str | None,
        exempt: Collection[str],
        trusted_sources: Collection[str] = (),
        limiter: FailedAuthLimiter | None = None,
        operate_token: str | None = None,
        required: bool = True,
        tickets: LiveTickets | None = None,
    ) -> None:
        self.app = app
        self._tickets = tickets
        self._username = username
        self._password = password
        self._token = operate_token
        self._required = required
        self._exempt = frozenset(exempt)
        self._trusted = frozenset(trusted_sources)
        self.limiter = limiter or FailedAuthLimiter()

    async def _serve(self, scope: Scope, receive: Receive, send: Send, role: Role) -> None:
        scope[ROLE_SCOPE_KEY] = role
        await self.app(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Reject unauthenticated requests before they reach the application."""
        if scope["type"] not in ("http", "websocket") or scope["path"] in self._exempt:
            await self.app(scope, receive, send)
            return
        source = _source(scope)
        if source in self._trusted:
            await self._serve(scope, receive, send, Role.ADMIN)
            return
        if scope["type"] == "websocket" and self._tickets is not None:
            granted = self._tickets.redeem(_query_ticket(scope))
            if granted is not None:
                await self._serve(scope, receive, send, granted)
                return
        header = _header(scope, b"authorization")
        if header is not None and (self._required or is_bearer(header)):
            key = limiter_key(source, header)
            wait = self.limiter.retry_after(key)
            if wait > 0:
                retry = str(math.ceil(wait)).encode()
                await _reject(send, scope, 429, "too many failed logins", [(b"retry-after", retry)])
                return
            if self._password is not None and credentials_match(
                header, self._username, self._password
            ):
                self.limiter.success(key)
                await self._serve(scope, receive, send, Role.ADMIN)
                return
            if self._token is not None and bearer_matches(header, self._token):
                self.limiter.success(key)
                await self._serve(scope, receive, send, Role.OPERATE)
                return
            self.limiter.failure(key)
        elif not self._required:
            await self._serve(scope, receive, send, Role.READ)
            return
        challenge = f'Basic realm="{REALM}", charset="UTF-8"'.encode()
        headers = [(b"www-authenticate", challenge)] if _may_prompt(scope) else []
        await _reject(send, scope, 401, "authentication required", headers)


SILENT_DESTINATIONS: Final = frozenset(
    {b"image", b"font", b"manifest", b"websocket", b"audio", b"video", b"track"}
)


def _may_prompt(scope: Scope) -> bool:
    """Whether a 401 may carry the Basic challenge that makes a browser ask for the login.

    A browser loads icons, fonts and the live connection in the background, and Safari does
    so without the login it already has; a challenge there pops the login dialog up again
    over a page that is already open and blocks it. Navigations, page requests and clients
    without fetch metadata keep the challenge.
    """
    return _header(scope, b"sec-fetch-dest") not in SILENT_DESTINATIONS


def origin_key(origin: str) -> tuple[str, str, int] | None:
    """Return ``(scheme, host, port)`` of an origin, or ``None`` when it is not one."""
    parts = urlsplit(origin.strip())
    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORTS or not parts.hostname:
        return None
    try:
        port = parts.port or DEFAULT_PORTS[scheme]
    except ValueError:
        return None
    return scheme, parts.hostname.lower(), port


def host_key(host: str, scheme: str) -> tuple[str, int] | None:
    """Return ``(host, port)`` of a ``Host`` header, defaulting the port by ``scheme``."""
    parts = urlsplit(f"//{host.strip()}")
    if not parts.hostname:
        return None
    try:
        port = parts.port or DEFAULT_PORTS.get(scheme, 80)
    except ValueError:
        return None
    return parts.hostname.lower(), port


def own_origin_host(
    headers: Mapping[str, str], trusted: bool, request_scheme: str
) -> tuple[str | None, str]:
    """Return the ``Host`` and scheme a request's own origin is compared with.

    Behind the trusted ingress proxy the browser's origin is Home Assistant's, which
    the proxy forwards as ``X-Forwarded-Host`` and ``X-Forwarded-Proto``; these
    headers are honoured only from the trusted source.

    Parameters
    ----------
    headers
        Request headers (case-insensitive mapping).
    trusted
        Whether the request comes from a trusted source.
    request_scheme
        Scheme of the request itself.

    Returns
    -------
    tuple
        Host header value (or ``None``) and scheme.
    """
    if trusted:
        forwarded = headers.get("x-forwarded-host")
        if forwarded:
            proto = headers.get("x-forwarded-proto") or request_scheme
            return forwarded.split(",")[0].strip(), proto.split(",")[0].strip().lower()
    return headers.get("host"), request_scheme


def origin_allowed(
    origin: str,
    host: str | None,
    allowed: Collection[tuple[str, str, int]],
    request_scheme: str = "http",
) -> bool:
    """Whether a browser ``Origin`` may open the WebSocket.

    Parameters
    ----------
    origin
        The ``Origin`` header.
    host
        The ``Host`` header of the handshake, if any.
    allowed
        Extra allowed origins as :func:`origin_key` tuples.
    request_scheme
        Scheme of the request itself (``http``/``ws`` or ``https``/``wss``); there
        is no trusted-proxy setting, so ``X-Forwarded-Proto`` is not consulted.

    Returns
    -------
    bool
        ``True`` when the origin is the request's own origin (same host and port as
        the ``Host`` header, same scheme) or one of ``allowed``.
    """
    key = origin_key(origin)
    if key is None:
        return False
    if key in allowed:
        return True
    if host is None:
        return False
    secure = request_scheme.lower() in ("https", "wss")
    if (key[0] in ("https", "wss")) != secure:
        return False
    return host_key(host, key[0]) == key[1:]


class OriginCheckMiddleware:
    """ASGI middleware refusing cross-origin WebSocket handshakes.

    Handshakes without an ``Origin`` header (non-browser clients such as the Home
    Assistant integration) and handshakes from trusted sources (the ingress proxy,
    which Home Assistant authenticates with its own same-site session) pass; every
    other handshake must come from the service's own origin or an allowed one,
    otherwise it is closed with ``1008`` before it is accepted.

    Parameters
    ----------
    app
        Wrapped application.
    allowed_origins
        Extra allowed origins (``https://ha.example:8123``).
    trusted_sources
        Client addresses exempt from the check.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed_origins: Collection[str] = (),
        trusted_sources: Collection[str] = (),
    ) -> None:
        self.app = app
        self._allowed = frozenset(
            key for key in (origin_key(origin) for origin in allowed_origins) if key is not None
        )
        self._trusted = frozenset(trusted_sources)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Close cross-origin WebSocket handshakes; pass everything else on."""
        if scope["type"] != "websocket" or _source(scope) in self._trusted:
            await self.app(scope, receive, send)
            return
        origin = _header(scope, b"origin")
        if origin is None:
            await self.app(scope, receive, send)
            return
        host = _header(scope, b"host")
        if origin_allowed(
            origin.decode("latin-1"),
            host.decode("latin-1") if host is not None else None,
            self._allowed,
            str(scope.get("scheme", "http")),
        ):
            await self.app(scope, receive, send)
            return
        await send({"type": "websocket.close", "code": POLICY_VIOLATION})

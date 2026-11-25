"""Roles and the request rules every state-changing request must pass.

Roles (stamped by :class:`~ovenbird.api.auth.BasicAuthMiddleware`): ``read`` (any
authenticated request), ``operate`` (the bearer token) and ``admin`` (HTTP Basic
admin, or the ingress proxy). :func:`require_role` checks a request against a role
and, for every non-``GET`` request, the cross-site rules:

1. a body of at most 64 kB (``413``);
2. ``Sec-Fetch-Site``, when the browser sends it, is ``same-origin`` (``403``);
3. ``Origin``, when sent, is the service's own (behind ingress: the forwarded Home
   Assistant origin) or one in ``OVENBIRD_HTTP_ALLOWED_ORIGINS`` (``403``);
4. ``Content-Type: application/json`` (``415``);
5. the header ``X-Ovenbird-Request: 1`` (``403``), which a cross-site form cannot set
   and which forces a CORS preflight that is never granted (no CORS headers exist).

These apply behind ingress as well. A refusal of a state-changing request is
audited as ``auth_refused`` (at most a few per source and minute).
"""

from __future__ import annotations

import json
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING, Any, Final

from fastapi import HTTPException, Request

from ovenbird.api.auth import Role, origin_allowed, origin_key, own_origin_host, scope_role
from ovenbird.config import Settings
from ovenbird.configstore import Actor

if TYPE_CHECKING:
    from ovenbird.trial.supervision import Supervision

type Window = Callable[[str | None, str | None], tuple[datetime, datetime]]

MAX_BODY: Final = 64 * 1024
REQUEST_HEADER: Final = "x-ovenbird-request"
INGRESS_USER_HEADER: Final = "x-remote-user-name"
INGRESS_ACTOR: Final = "ingress (Home Assistant admin)"
MAX_ACTOR: Final = 100
AUDIT_WINDOW_S: Final = 60.0
AUDIT_PER_WINDOW: Final = 5
SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True, slots=True)
class Principal:
    """The role and audit identity of a request.

    Parameters
    ----------
    role
        ``read``, ``operate`` or ``admin``.
    actor
        Audit name and client address.
    """

    role: Role
    actor: Actor


@dataclass
class RefusalAudit:
    """Audits refused state-changing requests, a few per source and minute.

    Parameters
    ----------
    sink
        Writes one audit row (``None`` disables auditing).
    clock
        Monotonic time source.
    """

    sink: Callable[[Actor, str, dict[str, Any]], None] | None = None
    clock: Callable[[], float] = time.monotonic
    _recent: dict[str, deque[float]] = field(default_factory=dict)

    def __call__(self, actor: Actor, status: int, reason: str, path: str) -> None:
        """Audit one refusal unless its source exceeded its quota."""
        if self.sink is None:
            return
        source = actor.source_ip or "unknown"
        now = self.clock()
        recent = self._recent.setdefault(source, deque())
        while recent and now - recent[0] > AUDIT_WINDOW_S:
            recent.popleft()
        if len(recent) >= AUDIT_PER_WINDOW:
            return
        recent.append(now)
        self.sink(actor, "auth_refused", {"status": status, "reason": reason, "path": path})


def bound(handler: Callable[..., Any], deps: object) -> Callable[..., Any]:
    """Return ``handler`` with ``deps`` bound, keeping its name and docstring for the schema."""
    route = partial(handler, deps)
    route.__name__ = handler.__name__  # type: ignore[attr-defined]
    route.__doc__ = handler.__doc__
    return route


def client_host(request: Request) -> str:
    """Return the client address of a request."""
    return request.client.host if request.client is not None else "unknown"


def principal(request: Request, settings: Settings) -> Principal:
    """Return the role and the audit name of ``request``.

    Under ingress the actor is the ``X-Remote-User-Name`` the Supervisor sends,
    trusted only from the ingress source.
    """
    source = client_host(request)
    if source in settings.trusted_sources:
        user = request.headers.get(INGRESS_USER_HEADER, "").strip()[:MAX_ACTOR]
        name = f"{user} (Home Assistant via ingress)" if user else INGRESS_ACTOR
        return Principal(Role.ADMIN, Actor(name, source))
    role = scope_role(request.scope)
    match role:
        case Role.ADMIN:
            name = f"{settings.admin_username} from {source}"
        case Role.OPERATE:
            name = f"operate token from {source}"
        case Role.READ:
            name = f"anonymous from {source}"
    return Principal(role, Actor(name, source))


def check_request_rules(request: Request, settings: Settings) -> None:
    """Apply the cross-site rules of a state-changing request.

    Raises
    ------
    HTTPException
        ``413``, ``403`` or ``415`` as listed in the module docstring.
    """
    length = request.headers.get("content-length")
    if length is not None and (not length.isdigit() or int(length) > MAX_BODY):
        raise HTTPException(413, f"the body must be at most {MAX_BODY} bytes")
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site is not None and fetch_site.strip().lower() != "same-origin":
        raise HTTPException(403, "cross-site request refused")
    origin = request.headers.get("origin")
    if origin is not None:
        trusted = client_host(request) in settings.trusted_sources
        host, scheme = own_origin_host(request.headers, trusted, request.url.scheme)
        allowed = frozenset(
            key
            for key in (origin_key(item) for item in settings.http_allowed_origins)
            if key is not None
        )
        if not origin_allowed(origin, host, allowed, scheme):
            raise HTTPException(403, "cross-origin request refused")
    content_type = request.headers.get("content-type", "")
    if content_type.split(";")[0].strip().lower() != "application/json":
        raise HTTPException(415, "send a JSON body (Content-Type: application/json)")
    if request.headers.get(REQUEST_HEADER, "").strip() != "1":
        raise HTTPException(403, "missing the X-Ovenbird-Request: 1 header")


def require_role(
    request: Request, settings: Settings, needed: Role, audit: RefusalAudit | None = None
) -> Principal:
    """Check ``request`` against ``needed`` and, unless it is a ``GET``, the request rules.

    Parameters
    ----------
    request
        The request.
    settings
        Settings (trusted sources, allowed origins, admin configuration).
    needed
        Lowest role allowed.
    audit
        Records refusals of state-changing requests.

    Returns
    -------
    Principal
        Who made the request.

    Raises
    ------
    HTTPException
        A request-rule refusal, or ``403`` when the role is too low.
    """
    who = principal(request, settings)
    state_changing = request.method.upper() not in SAFE_METHODS
    try:
        if state_changing:
            check_request_rules(request, settings)
        if who.role.rank < needed.rank:
            if (
                needed is Role.ADMIN
                and settings.admin_password is None
                and not settings.ingress_mode
            ):
                raise HTTPException(
                    403, "this action requires OVENBIRD_ADMIN_PASSWORD to be configured"
                )
            raise HTTPException(403, f"this action needs the {needed.value} role")
    except HTTPException as exc:
        if state_changing and audit is not None:
            audit(who.actor, exc.status_code, str(exc.detail), request.url.path)
        raise
    return who


async def read_json(request: Request) -> dict[str, Any]:
    """Return the JSON object body of a request (an empty body is ``{}``).

    Raises
    ------
    HTTPException
        ``413`` over 64 kB, ``400`` when it is not a JSON object.
    """
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(413, f"the body must be at most {MAX_BODY} bytes")
    if not raw.strip():
        return {}
    try:
        body = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "body is not JSON") from None
    if not isinstance(body, dict):
        raise HTTPException(400, "body must be a JSON object")
    return body


def optional_text(body: dict[str, Any], key: str, limit: int) -> str | None:
    """Return the optional string ``key`` of a body (stripped, empty is ``None``).

    Raises
    ------
    HTTPException
        ``400`` when it is not a string of at most ``limit`` characters.
    """
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise HTTPException(400, f"{key} must be a string of at most {limit} characters")
    return value.strip() or None


def integer(body: dict[str, Any], key: str) -> int:
    """Return the required non-negative integer ``key`` of a body.

    Raises
    ------
    HTTPException
        ``400`` when it is missing or not a non-negative integer.
    """
    value = body.get(key)
    if type(value) is not int or value < 0:
        raise HTTPException(400, f"{key} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class SupervisionDeps:
    """What the shadow, trial, notification and system handlers need.

    Parameters
    ----------
    settings
        Settings (roles and request rules).
    supervision
        What the endpoints read and act on.
    audit
        Records refused state-changing requests.
    window
        Resolves ``from``/``to`` query parameters.
    """

    settings: Settings
    supervision: Supervision
    audit: RefusalAudit
    window: Window

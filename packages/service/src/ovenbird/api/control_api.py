"""Control endpoints: pause/resume, wood-stove mode, release a hold, audit, series.

``POST control/pause`` and ``control/stove`` need ``operate``, ``control/resume`` and
``release-hold`` need ``admin``; all follow the request rules of
:mod:`ovenbird.api.deps`. ``GET audit`` (also ``?format=csv``) is admin-only;
``GET decisions/series`` is open to every role.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Final

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from ovenbird.api.auth import Role
from ovenbird.api.deps import RefusalAudit, bound, optional_text, read_json, require_role
from ovenbird.api.export import AUDIT_COLUMNS, Format, csv_response
from ovenbird.api.models.base import returns
from ovenbird.api.models.control import (
    AuditPage,
    DecisionSeries,
    ModeChange,
    ReleaseHoldResult,
    StoveResult,
)
from ovenbird.clock import iso_from_unix, iso_z
from ovenbird.config import Settings
from ovenbird.configstore import ConfigManager, ConfigRefusedError
from ovenbird.control.loop import ControlLoop
from ovenbird.history.journal import query_decision_series, series_step
from ovenbird.payloads import Json
from ovenbird.stove.request import StoveRequestError, parse_wall

LOGGER = logging.getLogger("ovenbird.api")
MAX_REASON: Final = 200
MAX_UNTIL: Final = 64
DEFAULT_AUDIT: Final = 500
MAX_AUDIT: Final = 5000

type Window = Callable[[str | None, str | None], tuple[datetime, datetime]]


@dataclass(frozen=True, slots=True)
class ControlDeps:
    """What the control handlers need.

    Parameters
    ----------
    settings
        Settings (roles, request rules, history path).
    control
        The control loop (``None`` without one).
    config
        The configuration manager (``None`` without a store: no pause, no audit).
    audit
        Records refused state-changing requests.
    window
        Resolves ``from``/``to`` query parameters.
    """

    settings: Settings
    control: ControlLoop | None
    config: ConfigManager | None
    audit: RefusalAudit
    window: Window


def control_status(deps: ControlDeps) -> Json | None:
    """Return the control loop's status, ``None`` without one."""
    return deps.control.status() if deps.control is not None else None


async def pause(deps: ControlDeps, request: Request) -> Json | JSONResponse:
    """``POST control/pause``: pause control (nothing is sent until resumed)."""
    who = require_role(request, deps.settings, Role.OPERATE, deps.audit)
    body = await read_json(request)
    reason = optional_text(body, "reason", MAX_REASON)
    if deps.config is None:
        raise HTTPException(409, "this service has no configuration store")
    try:
        result = deps.config.pause(who.actor, reason)
    except ConfigRefusedError as exc:
        return JSONResponse(exc.body, status_code=exc.status)
    return {**result, "control": control_status(deps)}


async def resume(deps: ControlDeps, request: Request) -> Json | JSONResponse:
    """``POST control/resume``: resume control."""
    who = require_role(request, deps.settings, Role.ADMIN, deps.audit)
    await read_json(request)
    if deps.config is None:
        raise HTTPException(409, "this service has no configuration store")
    try:
        result = deps.config.resume(who.actor)
    except ConfigRefusedError as exc:
        return JSONResponse(exc.body, status_code=exc.status)
    return {**result, "control": control_status(deps)}


async def stove(deps: ControlDeps, request: Request) -> Json:
    """``POST control/stove``: switch wood-stove mode on or off."""
    who = require_role(request, deps.settings, Role.OPERATE, deps.audit)
    body = await read_json(request)
    on = body.get("on")
    if not isinstance(on, bool):
        raise HTTPException(400, "on must be true or false")
    raw = optional_text(body, "until", MAX_UNTIL)
    try:
        until = None if raw is None else parse_wall(raw)
    except ValueError:
        raise HTTPException(400, "until must be an ISO 8601 time") from None
    if deps.control is None:
        raise HTTPException(409, "this service has no control loop")
    try:
        accepted = deps.control.request_stove(on, until, who.actor.name)
    except StoveRequestError as exc:
        status_code = 409 if deps.control.controller.config.stove is None else 400
        raise HTTPException(status_code, str(exc)) from None
    if deps.config is not None:
        deps.config.audit(who.actor, "stove_request", accepted.to_json())
    return {"request": accepted.to_json(), "stove": deps.control.stove_status()}


async def release_hold(deps: ControlDeps, request: Request) -> Json:
    """``POST control/release-hold``: release a foreign-writer or verification hold."""
    who = require_role(request, deps.settings, Role.ADMIN, deps.audit)
    body = await read_json(request)
    reason = optional_text(body, "reason", MAX_REASON)
    adapter = deps.control.adapter if deps.control is not None else None
    if deps.control is None or adapter is None:
        raise HTTPException(409, "publishing is not enabled, so there is no command hold")
    by = who.actor.name if reason is None else f"{who.actor.name}: {reason}"
    now = deps.control.runtime.clock()
    released = adapter.release_hold(now, by)
    if released is None:
        raise HTTPException(409, "no foreign-writer or verification hold is active")
    LOGGER.warning("command hold released by %s", by)
    if deps.config is not None:
        deps.config.audit(who.actor, "hold_release", {"reason": reason, **released.to_json()})
    return {
        "released": released.to_json(),
        "by": by,
        "hold": adapter.hold_reason,
        "safety_hold": sorted(code.value for code in adapter.safety_hold),
        "control": deps.control.status(),
    }


async def audit_events(
    deps: ControlDeps,
    request: Request,
    start: Annotated[str | None, Query(alias="from")] = None,
    end: Annotated[str | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_AUDIT)] = DEFAULT_AUDIT,
    output: Annotated[Format, Query(alias="format")] = "json",
) -> Json | Response:
    """``GET audit``: audit events (JSON or CSV)."""
    require_role(request, deps.settings, Role.ADMIN)
    since, until = deps.window(start, end)
    events = (
        []
        if deps.config is None
        else deps.config.store.audit_events(since.timestamp(), until.timestamp(), limit)
    )
    rows = [
        {
            "at": iso_from_unix(event.ts),
            "actor": event.actor,
            "source_ip": event.source_ip,
            "action": event.action,
            "detail": event.detail,
        }
        for event in events
    ]
    if output == "csv":
        return csv_response("audit", AUDIT_COLUMNS, rows, iso_z(since))
    return {"from": iso_z(since), "to": iso_z(until), "limit": limit, "events": rows}


def decision_series(
    deps: ControlDeps,
    start: Annotated[str | None, Query(alias="from")] = None,
    end: Annotated[str | None, Query(alias="to")] = None,
    step: Annotated[int | None, Query()] = None,
) -> Json:
    """``GET decisions/series``: the controller's decisions over time."""
    since, until = deps.window(start, end)
    t0, t1 = since.timestamp(), until.timestamp()
    resolved = series_step(t0, t1) if step is None else step
    try:
        columns = query_decision_series(deps.settings.history_path, t0, t1, resolved)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    columns["at"] = [iso_from_unix(ts) for ts in columns["at"]]
    return {"from": iso_z(since), "to": iso_z(until), "step": resolved, **columns}


def build_control_router(
    settings: Settings,
    control: ControlLoop | None,
    config: ConfigManager | None,
    audit: RefusalAudit,
    window: Window,
) -> APIRouter:
    """Return the control, audit and decision-series routes.

    Parameters
    ----------
    settings
        Settings (roles, request rules, history path).
    control
        The control loop (``None`` without one).
    config
        The configuration manager (``None`` without a store: no pause, no audit).
    audit
        Records refused state-changing requests.
    window
        Resolves ``from``/``to`` query parameters.

    Returns
    -------
    APIRouter
        Routes without prefix (the caller adds ``/api/v1``).
    """
    deps = ControlDeps(settings, control, config, audit, window)
    router = APIRouter()
    router.post("/control/pause", **returns(ModeChange, encoder=True))(bound(pause, deps))
    router.post("/control/resume", **returns(ModeChange, encoder=True))(bound(resume, deps))
    router.post("/control/stove", **returns(StoveResult))(bound(stove, deps))
    router.post("/control/release-hold", **returns(ReleaseHoldResult))(bound(release_hold, deps))
    router.get("/audit", **returns(AuditPage, encoder=True))(bound(audit_events, deps))
    router.get("/decisions/series", **returns(DecisionSeries))(bound(decision_series, deps))
    return router

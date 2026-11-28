"""Control endpoints: pause/resume, wood-stove mode, boost, away, features, holds, audit.

``POST control/pause``, ``control/stove``, ``POST``/``DELETE control/boost`` and
``PUT``/``DELETE control/away`` need ``operate``, ``control/resume`` and
``release-hold`` need ``admin``; all follow the request rules of
:mod:`ovenbird.api.deps`. ``GET audit`` (also ``?format=csv``) is admin-only;
``GET decisions/series``, ``control/dayshift``, ``control/boost``, ``control/away`` and
``control/features`` are open to every role.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Final

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from ovenbird.api.auth import Role
from ovenbird.api.deps import RefusalAudit, bound, optional_text, read_json, require_role
from ovenbird.api.export import AUDIT_COLUMNS, Format, csv_response
from ovenbird.api.models.base import returns
from ovenbird.api.models.control import (
    AuditPage,
    AwayResult,
    AwayStatus,
    BoostResult,
    BoostStatus,
    DayShift,
    DecisionSeries,
    Features,
    ModeChange,
    ReleaseHoldResult,
    StoveResult,
)
from ovenbird.clock import iso_from_unix, iso_z
from ovenbird.config import Settings
from ovenbird.configstore import ConfigManager, ConfigRefusedError
from ovenbird.control.features import features_payload
from ovenbird.control.loop import ControlLoop
from ovenbird.control.roomtarget import RoomTargetError
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
    """``POST control/stove``: switch wood-stove mode on or off.

    Parameters
    ----------
    deps
        Control dependencies.
    request
        Request carrying the JSON body (``on``, optional ``until``).
    """
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


def _loop(deps: ControlDeps) -> ControlLoop:
    """Return the control loop.

    Raises
    ------
    HTTPException
        ``409`` without one.
    """
    if deps.control is None:
        raise HTTPException(409, "this service has no control loop")
    return deps.control


def _number(body: dict[str, Any], key: str) -> float | None:
    """Return the optional finite number ``key`` of a body.

    Raises
    ------
    HTTPException
        ``400`` when it is set and no finite number.
    """
    value = body.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise HTTPException(400, f"{key} must be a number")
    return float(value)


def _until(body: dict[str, Any]) -> datetime | None:
    """Return the optional ISO 8601 ``until`` of a body.

    Raises
    ------
    HTTPException
        ``400`` when it is set and no ISO 8601 time.
    """
    raw = optional_text(body, "until", MAX_UNTIL)
    try:
        return None if raw is None else parse_wall(raw)
    except ValueError:
        raise HTTPException(400, "until must be an ISO 8601 time") from None


async def boost_get(deps: ControlDeps) -> Json:
    """``GET control/boost``: the boost in force, if any, and its settings."""
    return _loop(deps).boost_status()


async def boost_post(deps: ControlDeps, request: Request) -> Json:
    """``POST control/boost``: raise (or lower) the room target for a while."""
    who = require_role(request, deps.settings, Role.OPERATE, deps.audit)
    body = await read_json(request)
    offset_k, target_c = _number(body, "offset_k"), _number(body, "target_c")
    duration_s, until = _number(body, "duration_s"), _until(body)
    loop = _loop(deps)
    try:
        accepted = loop.request_boost(
            offset_k=offset_k,
            target_c=target_c,
            duration_s=duration_s,
            until=until,
            actor=who.actor.name,
        )
    except RoomTargetError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    if deps.config is not None:
        deps.config.audit(who.actor, "boost", accepted.to_json())
    return {"request": accepted.to_json(), "boost": loop.boost_status()}


async def boost_delete(deps: ControlDeps, request: Request) -> Json:
    """``DELETE control/boost``: end the boost now."""
    who = require_role(request, deps.settings, Role.OPERATE, deps.audit)
    loop = _loop(deps)
    ended = loop.end_boost(who.actor.name)
    if ended is not None and deps.config is not None:
        deps.config.audit(who.actor, "boost_end", ended.to_json())
    return {"request": None if ended is None else ended.to_json(), "boost": loop.boost_status()}


async def away_get(deps: ControlDeps) -> Json:
    """``GET control/away``: the away period, if any, and its settings."""
    return _loop(deps).away_status()


async def away_put(deps: ControlDeps, request: Request) -> Json:
    """``PUT control/away``: set an away period until a time."""
    who = require_role(request, deps.settings, Role.OPERATE, deps.audit)
    body = await read_json(request)
    until = _until(body)
    if until is None:
        raise HTTPException(400, "until is required")
    target_c, lead_s = _number(body, "target_c"), _number(body, "comfort_lead_s")
    loop = _loop(deps)
    try:
        accepted = loop.request_away(
            target_c=target_c, until=until, lead_s=lead_s, actor=who.actor.name
        )
    except RoomTargetError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    if deps.config is not None:
        deps.config.audit(who.actor, "away", accepted.to_json())
    return {"request": accepted.to_json(), "away": loop.away_status()}


async def away_delete(deps: ControlDeps, request: Request) -> Json:
    """``DELETE control/away``: end the away period now (comfort applies again)."""
    who = require_role(request, deps.settings, Role.OPERATE, deps.audit)
    loop = _loop(deps)
    ended = loop.end_away(who.actor.name)
    if ended is not None and deps.config is not None:
        deps.config.audit(who.actor, "away_end", ended.to_json())
    return {"request": None if ended is None else ended.to_json(), "away": loop.away_status()}


async def features(deps: ControlDeps) -> Json:
    """``GET control/features``: every switchable feature with its state."""
    settings = deps.config.settings if deps.config is not None else deps.settings
    return features_payload(_loop(deps), settings)


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
    """``GET audit``: audit events (JSON or CSV).

    Parameters
    ----------
    deps
        Control dependencies.
    request
        Incoming request (admin only).
    start, end
        Period bounds (ISO 8601); defaults apply when omitted.
    limit
        Most events to return.
    output
        ``json`` or ``csv``.
    """
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
    """``GET decisions/series``: the controller's decisions over time.

    Parameters
    ----------
    deps
        Control dependencies.
    start, end
        Period bounds (ISO 8601); defaults apply when omitted.
    step
        Bucket width in seconds; chosen from the period when omitted.
    """
    since, until = deps.window(start, end)
    t0, t1 = since.timestamp(), until.timestamp()
    resolved = series_step(t0, t1) if step is None else step
    try:
        columns = query_decision_series(deps.settings.history_path, t0, t1, resolved)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    columns["at"] = [iso_from_unix(ts) for ts in columns["at"]]
    return {"from": iso_z(since), "to": iso_z(until), "step": resolved, **columns}


def dayshift(deps: ControlDeps) -> Json:
    """``GET control/dayshift``: the sun day shift's mode, phase, offset, reasons and guards."""
    runner = deps.control.dayshift if deps.control is not None else None
    if runner is None:
        raise HTTPException(409, "this service has no control loop")
    return runner.status()


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
    router.get("/control/boost", **returns(BoostStatus))(bound(boost_get, deps))
    router.post("/control/boost", **returns(BoostResult))(bound(boost_post, deps))
    router.delete("/control/boost", **returns(BoostResult))(bound(boost_delete, deps))
    router.get("/control/away", **returns(AwayStatus))(bound(away_get, deps))
    router.put("/control/away", **returns(AwayResult))(bound(away_put, deps))
    router.delete("/control/away", **returns(AwayResult))(bound(away_delete, deps))
    router.get("/control/features", **returns(Features))(bound(features, deps))
    router.post("/control/release-hold", **returns(ReleaseHoldResult))(bound(release_hold, deps))
    router.get("/audit", **returns(AuditPage, encoder=True))(bound(audit_events, deps))
    router.get("/decisions/series", **returns(DecisionSeries))(bound(decision_series, deps))
    router.get("/control/dayshift", **returns(DayShift))(bound(dayshift, deps))
    return router

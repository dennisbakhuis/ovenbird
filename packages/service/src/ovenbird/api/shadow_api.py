"""Shadow endpoints: the divergence from the previous controller and its explained episodes.

``GET shadow/divergence`` is open to every role; ``POST shadow/episodes/explain``
needs ``admin``, follows the request rules of :mod:`ovenbird.api.deps` and is audited.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from ovenbird.api.auth import Role
from ovenbird.api.deps import SupervisionDeps, bound, optional_text, read_json, require_role
from ovenbird.api.models.base import returns
from ovenbird.api.models.supervision import Divergence, ExplainResult
from ovenbird.clock import iso_z
from ovenbird.payloads import Json
from ovenbird.trial.divergence import DEFAULT_THRESHOLD_K, divergence_payload
from ovenbird.trial.explained import MAX_NOTE, annotate


async def divergence(
    deps: SupervisionDeps,
    start: Annotated[str | None, Query(alias="from")] = None,
    end: Annotated[str | None, Query(alias="to")] = None,
    step: Annotated[int | None, Query()] = None,
    threshold_k: Annotated[float, Query(gt=0.0, le=20.0)] = DEFAULT_THRESHOLD_K,
) -> Json:
    """``GET shadow/divergence``: ovenbird against the pump's setpoint, with episodes."""
    since, until = deps.window(start, end)
    current = deps.supervision.current()
    try:
        body = await asyncio.to_thread(
            divergence_payload,
            current.history_path,
            start=since.timestamp(),
            end=until.timestamp(),
            step=step,
            timezone=current.control_timezone,
            threshold_k=threshold_k,
            interval_s=current.control_interval_s,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    annotate(body, deps.supervision.explanations())
    return {"from": iso_z(since), "to": iso_z(until), **body}


async def explain(deps: SupervisionDeps, request: Request) -> Json:
    """``POST shadow/episodes/explain``: mark (or unmark) an episode as explained."""
    who = require_role(request, deps.settings, Role.ADMIN, deps.audit)
    body = await read_json(request)
    start = body.get("start")
    if not isinstance(start, str):
        raise HTTPException(400, "start must be the episode's start (ISO 8601)")
    try:
        moment = datetime.fromisoformat(start.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "start must be the episode's start (ISO 8601)") from None
    if moment.tzinfo is None:
        raise HTTPException(400, "start must carry a time zone")
    note = optional_text(body, "note", MAX_NOTE)
    if note is None and body.get("explained", True) is not False:
        raise HTTPException(400, "note is required; send explained: false to remove a mark")
    return deps.supervision.explain(who.actor, moment, note)


def build_shadow_router(deps: SupervisionDeps) -> APIRouter:
    """Return the shadow routes without prefix (the caller adds ``/api/v1``)."""
    router = APIRouter()
    router.get("/shadow/divergence", **returns(Divergence))(bound(divergence, deps))
    router.post("/shadow/episodes/explain", **returns(ExplainResult, encoder=True))(
        bound(explain, deps)
    )
    return router

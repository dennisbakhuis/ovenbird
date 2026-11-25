"""Trial endpoints: the go-live checklist and summary, compressor runs and the release.

Read (every role): ``trial/status``, ``insight/runs``, ``control/snapshot`` and
``control/release``. ``POST control/release`` and ``POST control/snapshot`` need
``admin``, follow the request rules of :mod:`ovenbird.api.deps` and are audited. The
shadow, notification and system endpoints are in :mod:`ovenbird.api.shadow_api`,
:mod:`ovenbird.api.notify_api` and :mod:`ovenbird.api.system_api`.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ovenbird.api.auth import Role
from ovenbird.api.deps import SupervisionDeps, Window, bound, optional_text, read_json, require_role
from ovenbird.api.models.base import returns
from ovenbird.api.models.insight import InsightRuns
from ovenbird.api.models.supervision import ReleaseStarted, ReleaseState, SnapshotState, TrialStatus
from ovenbird.payloads import Json
from ovenbird.trial.release import MAX_REASON, ReleaseRefusedError
from ovenbird.trial.runs import MAX_DAYS, runs_payload


def span(window: Window, start: str | None, end: str | None) -> tuple[float, float] | None:
    """Return the ``from``/``to`` query span in unix seconds, ``None`` when both are absent."""
    if start is None and end is None:
        return None
    since, until = window(start, end)
    return since.timestamp(), until.timestamp()


async def trial_status(
    deps: SupervisionDeps,
    start: Annotated[str | None, Query(alias="from")] = None,
    end: Annotated[str | None, Query(alias="to")] = None,
    baseline_start: Annotated[str | None, Query(alias="baseline_from")] = None,
    baseline_end: Annotated[str | None, Query(alias="baseline_to")] = None,
) -> Json:
    """``GET trial/status``: the go-live checklist and the trial summary."""
    supervision = deps.supervision
    trial = span(deps.window, start, end)
    baseline = span(deps.window, baseline_start, baseline_end)
    now = supervision.now()
    facts = await asyncio.to_thread(supervision.history_facts, now, trial, baseline)
    return supervision.status(now, trial, baseline, facts)


async def runs(deps: SupervisionDeps, days: Annotated[int, Query(ge=1, le=MAX_DAYS)] = 7) -> Json:
    """``GET insight/runs``: compressor runs per local day."""
    current = deps.supervision.current()
    return await asyncio.to_thread(
        runs_payload,
        current.history_path,
        now=deps.supervision.now().wall,
        days=days,
        timezone=current.control_timezone,
    )


async def snapshot(deps: SupervisionDeps) -> Json:
    """``GET control/snapshot``: the go-live snapshot and whether one can be captured."""
    loop = deps.supervision.control
    if loop is None or loop.release is None:
        return {
            "snapshot": None,
            "armed": False,
            "publishing": False,
            "can_capture": False,
            "capture_refusal": None,
        }
    return loop.release.snapshot_payload()


async def capture(deps: SupervisionDeps, request: Request) -> JSONResponse:
    """``POST control/snapshot``: capture the pump's settings by hand."""
    who = require_role(request, deps.settings, Role.ADMIN, deps.audit)
    await read_json(request)
    loop = deps.supervision.control
    if loop is None or loop.release is None:
        raise HTTPException(409, "this service has no control loop")
    try:
        loop.release.capture(who.actor)
    except ReleaseRefusedError as exc:
        return JSONResponse({"detail": exc.to_json()}, status_code=exc.status)
    return JSONResponse(loop.release.snapshot_payload())


async def release_status(deps: SupervisionDeps) -> Json:
    """``GET control/release``: the last release and rehearsals."""
    loop = deps.supervision.control
    if loop is None or loop.release is None:
        return {
            "release": None,
            "last_rehearsal": None,
            "last_dry_rehearsal": None,
            "timeout_s": None,
        }
    manager = loop.release
    manager.poll(deps.supervision.now())
    return {
        "release": manager.last(),
        "last_rehearsal": manager.last_rehearsal(),
        "last_dry_rehearsal": manager.last_dry_rehearsal(),
        "timeout_s": manager.timeout_s,
    }


async def release(deps: SupervisionDeps, request: Request) -> JSONResponse:
    """``POST control/release``: hand control back to the pump (or rehearse it)."""
    who = require_role(request, deps.settings, Role.ADMIN, deps.audit)
    body = await read_json(request)
    rehearsal = body.get("rehearsal", False)
    if not isinstance(rehearsal, bool):
        raise HTTPException(400, "rehearsal must be true or false")
    dry = body.get("dry", False)
    if not isinstance(dry, bool):
        raise HTTPException(400, "dry must be true or false")
    reason = optional_text(body, "reason", MAX_REASON)
    loop = deps.supervision.control
    if loop is None or loop.release is None:
        raise HTTPException(409, "this service has no control loop")
    try:
        run = loop.release.start(who.actor, rehearsal=rehearsal, reason=reason, dry=dry)
    except ReleaseRefusedError as exc:
        return JSONResponse({"detail": exc.to_json()}, status_code=exc.status)
    payload = {"release": run.to_json(deps.supervision.now()), "control": loop.status()}
    return JSONResponse(payload, status_code=200 if run.done else 202)


def build_trial_router(deps: SupervisionDeps) -> APIRouter:
    """Return the trial, runs, snapshot and release routes (the caller adds ``/api/v1``)."""
    router = APIRouter()
    router.get("/trial/status", **returns(TrialStatus))(bound(trial_status, deps))
    router.get("/insight/runs", **returns(InsightRuns))(bound(runs, deps))
    router.get("/control/snapshot", **returns(SnapshotState))(bound(snapshot, deps))
    router.post("/control/snapshot", **returns(SnapshotState, encoder=True))(bound(capture, deps))
    router.get("/control/release", **returns(ReleaseState))(bound(release_status, deps))
    router.post(
        "/control/release",
        responses={202: {"model": ReleaseStarted, "description": "The release runs."}},
        **returns(ReleaseStarted, encoder=True),
    )(bound(release, deps))
    return router

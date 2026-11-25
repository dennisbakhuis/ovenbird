"""Notification endpoints: the ntfy and dead-man status, and a test message.

``GET notifications/status`` is open to every role. ``POST notifications/test`` needs
``operate`` (at most one per 30 s and ten per hour, ``429`` otherwise), follows the
request rules of :mod:`ovenbird.api.deps` and is audited.
"""

from __future__ import annotations

import math
from typing import Final

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ovenbird.api.auth import Role
from ovenbird.api.deps import SupervisionDeps, bound, read_json, require_role
from ovenbird.api.models.base import returns
from ovenbird.api.models.supervision import NotificationStatus, NotifyTestResult
from ovenbird.notify.notifier import TestLimitError
from ovenbird.payloads import Json

NOTIFY_AUDIT: Final = "notify_test"


async def notifications(deps: SupervisionDeps) -> Json:
    """``GET notifications/status``: what is configured, sent and failing (no secrets)."""
    notifier = deps.supervision.notifier
    if notifier is None:
        return {"ntfy": {"configured": False}, "deadman": {"configured": False}}
    return notifier.status()


async def notifications_test(deps: SupervisionDeps, request: Request) -> Json | JSONResponse:
    """``POST notifications/test``: send a test notification at once."""
    supervision = deps.supervision
    who = require_role(request, deps.settings, Role.OPERATE, deps.audit)
    await read_json(request)
    notifier = supervision.notifier
    if notifier is None or not notifier.configured:
        raise HTTPException(409, "ntfy is not configured (OVENBIRD_NOTIFY_NTFY_URL and _TOPIC)")
    try:
        result = await notifier.send_test(who.actor)
    except TestLimitError as exc:
        wait = max(1, math.ceil(exc.retry_after_s))
        return JSONResponse(
            {"detail": {"code": "test_rate", "message": str(exc), "retry_after_s": wait}},
            status_code=429,
            headers={"Retry-After": str(wait)},
        )
    if supervision.config is not None:
        supervision.config.audit(
            who.actor, NOTIFY_AUDIT, {"ok": result["ok"], "error": result["error"]}
        )
    return {"test": result, "status": notifier.status()}


def build_notify_router(deps: SupervisionDeps) -> APIRouter:
    """Return the notification routes without prefix (the caller adds ``/api/v1``)."""
    router = APIRouter()
    router.get("/notifications/status", **returns(NotificationStatus))(bound(notifications, deps))
    router.post("/notifications/test", **returns(NotifyTestResult, encoder=True))(
        bound(notifications_test, deps)
    )
    return router

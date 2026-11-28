"""System endpoints: the about page and the diagnostics bundle.

``GET system/about`` is open to every role; ``GET diagnostics`` (JSON or a zip, as an
attachment) needs ``admin``.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from ovenbird.api.auth import Role
from ovenbird.api.deps import SupervisionDeps, bound, require_role
from ovenbird.api.models.base import returns
from ovenbird.api.models.supervision import SystemAbout
from ovenbird.payloads import Json
from ovenbird.system.diagnostics import DEFAULT_ITEMS, MAX_ITEMS, bundle, to_zip


async def about(deps: SupervisionDeps) -> Json:
    """``GET system/about``: version, uptime, connections and the control state."""
    return deps.supervision.about()


async def diagnostics(
    deps: SupervisionDeps,
    request: Request,
    output: Annotated[Literal["json", "zip"], Query(alias="format")] = "json",
    items: Annotated[int, Query(ge=1, le=MAX_ITEMS)] = DEFAULT_ITEMS,
) -> Response:
    """``GET diagnostics``: the redacted diagnostics bundle as a download.

    Parameters
    ----------
    deps
        Supervision dependencies (settings, supervision facade).
    request
        Incoming request; it needs the admin role.
    output
        Download format: ``json`` or ``zip``.
    items
        Number of newest journal items per section in the bundle.
    """
    supervision = deps.supervision
    require_role(request, deps.settings, Role.ADMIN)
    facts = await asyncio.to_thread(supervision.history_facts, supervision.now())
    body = bundle(supervision, items, facts)
    name = "ovenbird-diagnostics-" + body["generated_at"].replace(":", "-")
    if output == "zip":
        return Response(
            await asyncio.to_thread(to_zip, body),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{name}.zip"'},
        )
    return JSONResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{name}.json"'}
    )


def build_system_router(deps: SupervisionDeps) -> APIRouter:
    """Return the system routes without prefix (the caller adds ``/api/v1``)."""
    router = APIRouter()
    router.get("/system/about", **returns(SystemAbout))(bound(about, deps))
    router.get("/diagnostics", response_model=None)(bound(diagnostics, deps))
    return router

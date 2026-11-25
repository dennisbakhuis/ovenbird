"""Pump settings endpoints: what HeishaMon reports, and the operator's three writable settings.

``GET pump/settings`` is open to every role; ``POST pump/settings/{id}`` needs ``admin``
and follows the request rules of :mod:`ovenbird.api.deps`. Refusals answer with
``{"detail": {"code", "message", "params"}}`` (see ``docs/api-v1.md``).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ovenbird.api.auth import Role
from ovenbird.api.deps import RefusalAudit, read_json, require_role
from ovenbird.api.models.base import returns
from ovenbird.api.models.pump import PumpSettingsPage, PumpWriteResult
from ovenbird.config import Settings
from ovenbird.control.adapter import SettingRefusedError
from ovenbird.payloads import Json
from ovenbird.pump.settings import PumpSettings


def build_pump_router(settings: Settings, pumps: PumpSettings, audit: RefusalAudit) -> APIRouter:
    """Return the ``api/v1/pump`` routes.

    Parameters
    ----------
    settings
        Settings (roles and request rules).
    pumps
        The pump settings service.
    audit
        Records refused state-changing requests.

    Returns
    -------
    APIRouter
        Routes without prefix (the caller adds ``/api/v1``).
    """
    router = APIRouter()

    @router.get("/pump/settings", **returns(PumpSettingsPage))
    async def read() -> Json:
        return pumps.payload()

    @router.post(
        "/pump/settings/{setting_id}", status_code=202, **returns(PumpWriteResult, encoder=True)
    )
    async def write(setting_id: str, request: Request) -> JSONResponse:
        who = require_role(request, settings, Role.ADMIN, audit)
        body = await read_json(request)
        try:
            result = pumps.write(setting_id, body, who.actor)
        except SettingRefusedError as exc:
            return JSONResponse({"detail": exc.to_json()}, status_code=exc.status)
        return JSONResponse(result, status_code=202)

    return router

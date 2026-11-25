"""Configuration endpoints: schema, values, validate, preview, apply, versions, export, reset.

See ``docs/api-v1.md``. Reading is open to every authenticated role; validating and
previewing need ``operate``; applying, rolling back, exporting, acknowledging a reset,
changing or testing the Home Assistant or broker connection and listing the signal
candidates need
``admin`` (a test makes the service connect to a URL the client chooses, while a token
is stored). Handlers run on the event loop, so
a new configuration reaches the control loop between two ticks without locking; the
preview's open-loop run reads ``history.db`` in a worker thread, one preview at a time.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Annotated, Any, Final

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import SecretStr

from ovenbird.api.auth import Role
from ovenbird.api.deps import RefusalAudit, integer, optional_text, read_json, require_role
from ovenbird.api.models.base import returns
from ovenbird.api.models.config import (
    ApplyResult,
    ConfigDoc,
    ConfigExport,
    ConfigSchema,
    ConfigSignals,
    ConfigVersion,
    ConfigVersions,
    HaConnectionResult,
    HaTestResult,
    MqttConnectionResult,
    MqttStatus,
    MqttTestResult,
    PreviewResult,
    ResetAckResult,
    ValidateResult,
)
from ovenbird.config import Settings
from ovenbird.configstore import ConfigManager, ConfigRefusedError, schema_payload
from ovenbird.configstore.apply import MAX_COMMENT
from ovenbird.configstore.fields import CONNECTION_FIELDS
from ovenbird.configstore.preview import (
    DEFAULT_HOURS,
    preview_now,
    run_open_loop,
    valid_hours,
    window,
)
from ovenbird.hacheck import check_connection
from ovenbird.payloads import Json

if TYPE_CHECKING:
    from ovenbird.control.loop import ControlLoop
    from ovenbird.mqttsetup import MqttSetup

DEFAULT_VERSIONS: Final = 50
MAX_VERSIONS: Final = 500
NO_CACHE: Final = {"Cache-Control": "no-cache"}
MAX_TEST_SIGNALS: Final = 32

type HaCheck = Callable[..., Awaitable[dict[str, Any]]]


def changes_of(body: dict[str, Any]) -> dict[str, Any]:
    """Return the ``changes`` object of a request body.

    Raises
    ------
    HTTPException
        ``400`` when it is missing or not an object.
    """
    changes = body.get("changes")
    if not isinstance(changes, dict):
        raise HTTPException(400, "changes must be a JSON object of field: value")
    return changes


def acknowledged(body: dict[str, Any]) -> list[str]:
    """Return the ``acknowledge`` list of warning codes of a request body.

    Raises
    ------
    HTTPException
        ``400`` when it is not a list of strings.
    """
    value = body.get("acknowledge", [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise HTTPException(400, "acknowledge must be a list of warning codes")
    return value


def ha_test_target(
    body: dict[str, Any], settings: Settings
) -> tuple[str | None, SecretStr | None, tuple[str, ...]]:
    """Return the URL, token and signals a connection test uses.

    An omitted URL or token takes the effective one, but the effective token is only
    sent to the effective URL: testing another URL needs its token in the body.

    Raises
    ------
    HTTPException
        ``400`` when a value has the wrong type or there are too many signals.
    """
    url = body.get("url")
    token = body.get("token")
    signals = body.get("signals")
    if url is not None and not isinstance(url, str):
        raise HTTPException(400, "url must be a string")
    if token is not None and not isinstance(token, str):
        raise HTTPException(400, "token must be a string")
    if signals is not None and (
        not isinstance(signals, list)
        or len(signals) > MAX_TEST_SIGNALS
        or not all(isinstance(item, str) for item in signals)
    ):
        raise HTTPException(400, f"signals must be a list of at most {MAX_TEST_SIGNALS} strings")
    target = url.strip() if url and url.strip() else settings.ha_url
    secret: SecretStr | None
    if token and token.strip():
        secret = SecretStr(token.strip())
    elif target == settings.ha_url:
        secret = settings.ha_token
    else:
        secret = None
    chosen = settings.ha_signals if signals is None else tuple(signals)
    return target, secret, tuple(s for s in dict.fromkeys(chosen) if s.startswith("ha/"))


def refused(exc: ConfigRefusedError) -> JSONResponse:
    """Return the response of a refused configuration request."""
    return JSONResponse(exc.body, status_code=exc.status)


def build_config_router(
    settings: Settings,
    config: ConfigManager,
    audit: RefusalAudit,
    *,
    control: ControlLoop | None = None,
    signals: Callable[[], dict[str, Any]] | None = None,
    ha_check: HaCheck = check_connection,
    mqtt: MqttSetup | None = None,
) -> APIRouter:
    """Return the ``api/v1/config`` routes.

    Parameters
    ----------
    settings
        Settings (roles and request rules, history path).
    config
        The configuration manager.
    audit
        Records refused state-changing requests.
    control
        The control loop (the preview's *now* part); ``None`` without one.
    signals
        Returns the signal picker candidates (``config/signals``).
    ha_check
        Tests a Home Assistant connection (``config/ha/test``; tests pass a fake).
    mqtt
        Tests and applies a broker connection (``config/mqtt``); ``None`` without
        an MQTT ingest.

    Returns
    -------
    APIRouter
        Routes without prefix (the caller adds ``/api/v1``).
    """
    router = APIRouter()
    previewing = asyncio.Lock()
    testing = asyncio.Lock()

    @router.get("/config/schema", **returns(ConfigSchema))
    async def schema() -> JSONResponse:
        return JSONResponse(schema_payload(config.settings), headers=NO_CACHE)

    @router.get("/config", **returns(ConfigDoc))
    async def current() -> Json:
        return config.payload()

    @router.post("/config/validate", **returns(ValidateResult))
    async def validate(request: Request) -> Json:
        require_role(request, settings, Role.OPERATE, audit)
        body = await read_json(request)
        return config.validate(changes_of(body)).to_json()

    @router.post("/config/preview", **returns(PreviewResult))
    async def preview(request: Request) -> Json:
        require_role(request, settings, Role.OPERATE, audit)
        body = await read_json(request)
        changes = changes_of(body)
        hours = valid_hours(body.get("hours", DEFAULT_HOURS))
        if hours is None:
            raise HTTPException(400, "hours must be a number from 1 to 72")
        async with previewing:
            validation = config.validate(changes)
            result = validation.to_json()
            candidate = validation.settings
            if not validation.valid or candidate is None:
                return result
            now = config.clock()
            if control is not None:
                result["now"] = preview_now(
                    control.runtime.store.snapshot(now),
                    control.state,
                    control.effective_mode,
                    control.room_signal,
                    control.controller.config,
                    candidate,
                )
            else:
                result["now"] = None
            result["open_loop_run"] = await asyncio.to_thread(
                run_open_loop,
                config.settings.history_path,
                config.settings,
                config.version,
                candidate,
                config.config_of,
                window(now, hours),
            )
        return result

    @router.get("/config/signals", **returns(ConfigSignals))
    async def signal_candidates(request: Request) -> Json:
        require_role(request, settings, Role.ADMIN)
        if signals is None:
            return {
                "ha": {"enabled": False, "link_up": False},
                "room": [],
                "liveness": [],
                "crosscheck": [],
            }
        return signals()

    @router.put("/config", **returns(ApplyResult, encoder=True))
    async def apply(request: Request) -> Json | JSONResponse:
        who = require_role(request, settings, Role.ADMIN, audit)
        body = await read_json(request)
        try:
            return config.apply(
                integer(body, "base_version"),
                changes_of(body),
                who.actor,
                comment=optional_text(body, "comment", MAX_COMMENT),
                acknowledge=acknowledged(body),
            )
        except ConfigRefusedError as exc:
            return refused(exc)

    @router.put("/config/ha", **returns(HaConnectionResult, encoder=True))
    async def ha_connection(request: Request) -> Json | JSONResponse:
        who = require_role(request, settings, Role.ADMIN, audit)
        body = await read_json(request)
        changes = {name: body[name] for name in body if name in ("url", "token")}
        unknown = sorted(set(body) - {"url", "token"})
        if unknown:
            raise HTTPException(400, f"unknown fields: {', '.join(unknown)}")
        try:
            return config.set_connection(
                {
                    name: changes[key]
                    for name, key in zip(CONNECTION_FIELDS, ("url", "token"), strict=True)
                    if key in changes
                },
                who.actor,
            )
        except ConfigRefusedError as exc:
            return refused(exc)

    @router.post("/config/ha/test", **returns(HaTestResult))
    async def ha_test(request: Request) -> Json:
        require_role(request, settings, Role.ADMIN, audit)
        body = await read_json(request)
        current = config.settings
        url, token, chosen = ha_test_target(body, current)
        async with testing:
            return await ha_check(url, token, chosen, temperature=current.ha_temperature_signals)

    @router.get("/config/mqtt", **returns(MqttStatus))
    async def mqtt_status() -> Json:
        if mqtt is None:
            raise HTTPException(404, "no MQTT ingest in this service")
        return mqtt.status()

    @router.post("/config/mqtt/test", **returns(MqttTestResult))
    async def mqtt_test(request: Request) -> Json | JSONResponse:
        require_role(request, settings, Role.ADMIN, audit)
        if mqtt is None:
            raise HTTPException(404, "no MQTT ingest in this service")
        body = await read_json(request)
        async with testing:
            try:
                return await mqtt.test(body)
            except ConfigRefusedError as exc:
                return refused(exc)

    @router.put("/config/mqtt", **returns(MqttConnectionResult, encoder=True))
    async def mqtt_connection(request: Request) -> Json | JSONResponse:
        who = require_role(request, settings, Role.ADMIN, audit)
        if mqtt is None:
            raise HTTPException(404, "no MQTT ingest in this service")
        body = await read_json(request)
        try:
            return mqtt.apply(body, who.actor)
        except ConfigRefusedError as exc:
            return refused(exc)

    @router.get("/config/versions", **returns(ConfigVersions))
    async def versions(
        limit: Annotated[int, Query(ge=1, le=MAX_VERSIONS)] = DEFAULT_VERSIONS,
    ) -> Json:
        return config.versions_payload(limit)

    @router.get("/config/versions/{number}", **returns(ConfigVersion))
    async def version(number: int) -> Json:
        item = config.store.get(number)
        if item is None:
            raise HTTPException(404, f"no configuration version {number}")
        return config.version_payload(item, values=True)

    @router.post("/config/rollback", **returns(ApplyResult, encoder=True))
    async def rollback(request: Request) -> Json | JSONResponse:
        who = require_role(request, settings, Role.ADMIN, audit)
        body = await read_json(request)
        try:
            return config.rollback(
                integer(body, "version"),
                integer(body, "base_version"),
                who.actor,
                comment=optional_text(body, "comment", MAX_COMMENT),
                acknowledge=acknowledged(body),
            )
        except ConfigRefusedError as exc:
            return refused(exc)

    @router.get("/config/export", **returns(ConfigExport))
    async def export(request: Request) -> JSONResponse:
        require_role(request, settings, Role.ADMIN)
        body = config.export()
        name = f"ovenbird-config-v{body['version']}.json"
        return JSONResponse(
            body,
            headers={**NO_CACHE, "Content-Disposition": f'attachment; filename="{name}"'},
        )

    @router.post("/config/reset-ack", **returns(ResetAckResult, encoder=True))
    async def reset_ack(request: Request) -> Json | JSONResponse:
        who = require_role(request, settings, Role.ADMIN, audit)
        await read_json(request)
        try:
            return config.reset_ack(who.actor)
        except ConfigRefusedError as exc:
            return refused(exc)

    return router

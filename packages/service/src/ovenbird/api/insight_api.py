"""Insight endpoints: daily figures and the learned house model.

``GET insight/daily`` (open to every role): per local day energy, COP, cycles and
comfort in the service's time zone (``control_timezone``), ending with today on the
service clock (the simulated time when the dev stack runs a scaled clock); see
:mod:`ovenbird.insight.daily`.

``GET insight/house`` and ``GET insight/house/history`` (every role) read the house
model the optional learner wrote to ``<data_dir>/models`` (always ``200``: a ``state``
says ``ready``, ``learning`` or ``not_run``); ``POST
insight/house/proposal/draft`` (operate) turns its curve proposal into a validated
configuration draft for the normal preview and apply flow. See
:mod:`ovenbird.insight.house`.

``GET insight/house/run`` (every role) reports the learner run the service itself
starts (:mod:`ovenbird.insight.learnrun`); ``POST insight/house/run`` (operate, audited
as ``house_learn_run``) starts one at once: ``202`` with the same body, ``409`` with
``{"detail": {"code", "message", "params"}}`` and code ``learner_running`` or
``learner_unavailable``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, Annotated, Final

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ovenbird.api.auth import Role
from ovenbird.api.deps import RefusalAudit, read_json, require_role
from ovenbird.api.models.base import returns
from ovenbird.api.models.insight import (
    HouseHistory,
    HouseReport,
    HouseRun,
    InsightDaily,
    ProposalDraft,
)
from ovenbird.config import Settings
from ovenbird.insight import house
from ovenbird.insight.daily import MAX_DAYS, daily_payload
from ovenbird.insight.learnrun import (
    REFUSAL_CODES,
    LearnerRunningError,
    LearnerUnavailableError,
    LearnRunner,
)
from ovenbird.payloads import Json
from ovenbird.runtime import Runtime
from ovenbird.system.facts import Facts

RUN_AUDIT: Final = "house_learn_run"
RUNNING: Final = REFUSAL_CODES[0]
UNAVAILABLE: Final = REFUSAL_CODES[1]

if TYPE_CHECKING:
    from ovenbird.configstore import ConfigManager


def build_insight_router(
    runtime: Runtime,
    current: Callable[[], Settings],
    *,
    settings: Settings | None = None,
    config: ConfigManager | None = None,
    audit: RefusalAudit | None = None,
    learn: LearnRunner | None = None,
) -> APIRouter:
    """Return the ``api/v1/insight`` routes.

    Parameters
    ----------
    runtime
        Service clock.
    current
        Returns the effective settings (history path, time zone, room signal,
        comfort target, journal retention, floor area, curve).
    settings
        Installation settings for the request rules of ``POST`` routes; the
        effective settings when omitted.
    config
        Configuration manager: validates the proposal draft (the learner's
        configuration file is kept by :func:`ovenbird.insight.learner.keep_learner_config`).
    audit
        Records refused state-changing requests.
    learn
        The learner runner; without it the learner counts as unavailable.

    Returns
    -------
    APIRouter
        Routes without prefix (the caller adds ``/api/v1``).
    """
    router = APIRouter()
    runner = learn or LearnRunner(current, Facts(), available=lambda: False)

    @router.get("/insight/daily", **returns(InsightDaily))
    async def daily(days: Annotated[int, Query(ge=1, le=MAX_DAYS)] = 7) -> Json:
        now = runtime.clock().wall
        effective = current()
        return await asyncio.to_thread(
            daily_payload,
            effective.history_path,
            now=now,
            days=days,
            timezone=effective.control_timezone,
            room_signal=effective.control_room_signal,
            comfort_c=effective.control_comfort_c,
            journal_days=effective.history_decision_days,
        )

    @router.get("/insight/house", **returns(HouseReport))
    async def house_model() -> JSONResponse:
        effective = current()
        status, body = await asyncio.to_thread(
            partial(house.house_payload, embedded=runner.available),
            house.models_dir(effective),
            effective,
        )
        return JSONResponse(body, status_code=status)

    @router.get("/insight/house/history", **returns(HouseHistory))
    async def house_history() -> Json:
        effective = current()
        return await asyncio.to_thread(
            house.history_payload, house.models_dir(effective), effective
        )

    @router.post("/insight/house/proposal/draft", **returns(ProposalDraft))
    async def proposal_draft(request: Request) -> JSONResponse:
        effective = current()
        require_role(request, settings or effective, Role.OPERATE, audit)
        await read_json(request)
        status, body = await asyncio.to_thread(
            house.proposal_changes, house.models_dir(effective), effective
        )
        if status == 200:
            body["validation"] = (
                config.validate(body["changes"]).to_json() if config is not None else None
            )
        return JSONResponse(body, status_code=status)

    @router.get("/insight/house/run", **returns(HouseRun))
    async def house_run() -> Json:
        return await asyncio.to_thread(runner.payload)

    @router.post("/insight/house/run", status_code=202, **returns(HouseRun, encoder=True))
    async def start_house_run(request: Request) -> JSONResponse:
        who = require_role(request, settings or current(), Role.OPERATE, audit)
        await read_json(request)
        try:
            runner.start()
        except LearnerUnavailableError as exc:
            return _refusal(UNAVAILABLE, str(exc))
        except LearnerRunningError as exc:
            return _refusal(RUNNING, str(exc))
        if config is not None:
            config.audit(who.actor, RUN_AUDIT, {})
        return JSONResponse(await asyncio.to_thread(runner.payload), status_code=202)

    return router


def _refusal(code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"detail": {"code": code, "message": message, "params": {}}}, status_code=409
    )

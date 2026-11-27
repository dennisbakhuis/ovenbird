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

``GET insight/house/series``, ``GET insight/house/whatif`` and ``GET insight/house/balance``
(every role) answer from the learned house model, or from the owner's facts without one;
errors are ``404`` with ``{"detail": {"code", "message", "params"}}`` and code
``house_series_missing`` or ``house_model_missing``, out-of-range query values ``422``;
see :mod:`ovenbird.insight.whatif`.

``GET insight/house/control`` (every role) reports the model plan: the ``control_model_use``
switch, the guard verdict, the latest planner evaluation and the computed offsets of the last
7 days; see :mod:`ovenbird.control.modelplan`.

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
from ovenbird.api.deps import RefusalAudit, principal, read_json, require_role
from ovenbird.api.models.base import returns
from ovenbird.api.models.insight import (
    HouseBalance,
    HouseControl,
    HouseHistory,
    HouseReport,
    HouseRun,
    HouseSeries,
    HouseWhatIf,
    InsightDaily,
    ProposalDraft,
)
from ovenbird.config import Settings
from ovenbird.control.loop import ControlLoop
from ovenbird.control.modelplan import ModelPlanRunner, PlanContext
from ovenbird.insight import house, whatif
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
from ovenbird.weather.service import WeatherService

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
    control: ControlLoop | None = None,
    weather: WeatherService | None = None,
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
    control
        The control loop (the owner's curve and supply limit, wood-stove state); the
        effective settings stand in without it.
    weather
        The weather component (the stored forecast's irradiance for the balance).

    Returns
    -------
    APIRouter
        Routes without prefix (the caller adds ``/api/v1``).
    """
    router = APIRouter()
    runner = learn or LearnRunner(current, Facts(), available=lambda: False)
    runner_available = runner.available

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

    @router.get("/insight/house/series", **returns(HouseSeries))
    async def house_series() -> JSONResponse:
        effective = current()
        try:
            body = await asyncio.to_thread(whatif.series_payload, house.models_dir(effective))
        except whatif.InsightError as exc:
            return JSONResponse(exc.to_json(), status_code=exc.status)
        return JSONResponse(body)

    @router.get("/insight/house/whatif", **returns(HouseWhatIf))
    async def house_whatif(
        outside_c: Annotated[float | None, Query(ge=-30.0, le=30.0)] = None,
        comfort_c: Annotated[float | None, Query(ge=5.0, le=30.0)] = None,
        sun_wm2: Annotated[float, Query(ge=0.0, le=1000.0)] = 0.0,
        stove_w: Annotated[float, Query(ge=0.0, le=15000.0)] = 0.0,
    ) -> JSONResponse:
        effective = current()
        outside = outside_c if outside_c is not None else whatif.outside_now(runtime, effective)

        def answer() -> Json:
            choice = whatif.choose_model(house.models_dir(effective), effective)
            return whatif.whatif_payload(
                choice,
                control.controller.config if control is not None else effective.controller_config(),
                outside_c=0.0 if outside is None else outside,
                comfort_c=effective.control_comfort_c if comfort_c is None else comfort_c,
                sun_wm2=sun_wm2,
                stove_w=stove_w,
            )

        try:
            return JSONResponse(await asyncio.to_thread(answer))
        except whatif.InsightError as exc:
            return JSONResponse(exc.to_json(), status_code=exc.status)

    @router.get("/insight/house/balance", **returns(HouseBalance))
    async def house_balance() -> JSONResponse:
        effective = current()
        stove = control is not None and control.stove_status().get("active") is True

        def answer() -> Json:
            choice = whatif.choose_model(house.models_dir(effective), effective)
            live = whatif.read_live(runtime, effective, weather, stove)
            return whatif.balance_payload(choice, live)

        try:
            return JSONResponse(await asyncio.to_thread(answer))
        except whatif.InsightError as exc:
            return JSONResponse(exc.to_json(), status_code=exc.status)

    @router.get("/insight/house/control", **returns(HouseControl))
    async def house_control() -> Json:
        effective = current()
        runner = control.model_plan if control is not None else None
        if control is not None:
            ctx = control.live_plan_context()
        else:
            ctx = PlanContext(runtime.clock(), False, False, None, effective.controller_config())
        if runner is None:
            runner = ModelPlanRunner(
                effective,
                lambda: house.models_dir(effective),
                weather_enabled=lambda: weather is not None and weather.enabled,
                embedded=lambda: runner_available,
            )
        return await asyncio.to_thread(runner.report, ctx)

    @router.get("/insight/house/run", **returns(HouseRun))
    async def house_run(request: Request) -> Json:
        who = principal(request, settings or current())
        full = who.role.rank >= Role.OPERATE.rank
        return await asyncio.to_thread(partial(runner.payload, full_detail=full))

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
        return JSONResponse(
            await asyncio.to_thread(partial(runner.payload, full_detail=True)), status_code=202
        )

    return router


def _refusal(code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"detail": {"code": code, "message": message, "params": {}}}, status_code=409
    )

"""Weather endpoint: measured, filtered and forecast outside temperature (``GET weather``).

Open to every role. The forecast is a controller input only through the model plan
(``control_model_use`` ``on``, see :mod:`ovenbird.control.modelplan`); otherwise it is shown
only. See :mod:`ovenbird.weather.report` for the fields.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Final

from fastapi import APIRouter, Query

from ovenbird.api.models.base import returns
from ovenbird.api.models.weather import WeatherReport
from ovenbird.config import Settings
from ovenbird.control.loop import ControlLoop
from ovenbird.payloads import Json
from ovenbird.runtime import Runtime
from ovenbird.weather.report import weather_payload
from ovenbird.weather.service import WeatherService
from ovenbird_core import HeishaSignal
from ovenbird_core.control.observe import as_number

MAX_BACK_H: Final = 168.0
MAX_AHEAD_H: Final = 72.0


def build_weather_router(
    settings: Settings,
    runtime: Runtime,
    weather: WeatherService,
    control: ControlLoop | None = None,
) -> APIRouter:
    """Return the ``api/v1/weather`` route.

    Parameters
    ----------
    settings
        Settings (history path).
    runtime
        State store and clock.
    weather
        The weather component.
    control
        The control loop (active curve, current filtered outside temperature).

    Returns
    -------
    APIRouter
        Routes without prefix (the caller adds ``/api/v1``).
    """
    router = APIRouter()

    @router.get("/weather", **returns(WeatherReport))
    async def read(
        back_h: Annotated[float, Query(gt=0, le=MAX_BACK_H)] = 24.0,
        ahead_h: Annotated[float, Query(gt=0, le=MAX_AHEAD_H)] = 48.0,
    ) -> Json:
        now = runtime.clock()
        config = (
            control.controller.config
            if control is not None
            else weather.settings.controller_config()
        )
        filtered = control.state.outside_filtered if control is not None else None
        view = runtime.store.view(HeishaSignal.OUTSIDE_TEMP, now)
        measured = as_number(view.value) if view is not None and view.fresh else None
        return await asyncio.to_thread(
            weather_payload,
            weather,
            settings.history_path,
            config,
            now=now,
            back_h=back_h,
            ahead_h=ahead_h,
            filtered_now=filtered,
            staleness=runtime.store.policy,
            measured_now=measured,
        )

    return router

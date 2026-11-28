"""Insight endpoints: daily figures and the house basics.

``GET insight/daily`` (open to every role): per local day energy, COP, cycles and
comfort in the service's time zone (``control_timezone``), ending with today on the
service clock (the simulated time when the dev stack runs a scaled clock); see
:mod:`ovenbird.insight.daily`.

``GET insight/basics`` (open to every role): the heat loss of the house and the heat
the heat pump puts in, with the live room, outside and heat values; the fits are
cached for up to an hour (:mod:`ovenbird.insight.basics`). With
``house_basics_enabled`` off it answers the disabled body without reading the
history.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Query

from ovenbird.api.models.base import returns
from ovenbird.api.models.insight import InsightBasics, InsightDaily
from ovenbird.config import Settings
from ovenbird.control.loop import ControlLoop
from ovenbird.insight.basics import (
    BasicsCache,
    LiveInputs,
    OutsideSource,
    basics_payload,
    disabled_payload,
)
from ovenbird.insight.daily import MAX_DAYS, daily_payload
from ovenbird.payloads import Json
from ovenbird.runtime import Runtime
from ovenbird_core import HeishaSignal, Instant, dhw_active, heat_delivered_w
from ovenbird_core.control.observe import as_number


def _fresh_number(runtime: Runtime, signal: str | None, now: Instant) -> float | None:
    """Return the fresh numeric value of ``signal`` in the state store, else ``None``."""
    if signal is None:
        return None
    view = runtime.store.view(signal, now)
    return as_number(view.value) if view is not None and view.fresh else None


def live_inputs(runtime: Runtime, effective: Settings, control: ControlLoop | None) -> LiveInputs:
    """Read the live values the house basics combine with the fits.

    Parameters
    ----------
    runtime
        State store and clock.
    effective
        Effective settings (room signal, comfort, setpoint range).
    control
        Control loop for the filtered outside temperature (``None``: the measured one).

    Returns
    -------
    LiveInputs
        Room, outside, heat now and the setpoint range.
    """
    now = runtime.clock()
    filtered = control.state.outside_filtered if control is not None else None
    outside = filtered
    source: OutsideSource | None = "filtered" if filtered is not None else None
    if outside is None:
        outside = _fresh_number(runtime, HeishaSignal.OUTSIDE_TEMP.value, now)
        source = "measured" if outside is not None else None
    snapshot = runtime.store.snapshot(now)
    limits = effective.safety_limits()
    return LiveInputs(
        room_c=_fresh_number(runtime, effective.control_room_signal, now),
        comfort_c=effective.control_comfort_c,
        outside_c=outside,
        outside_source=source,
        heat_now_w=heat_delivered_w(snapshot).value,
        hot_water=dhw_active(snapshot).value is True,
        setpoint_min_c=limits.min_setpoint_c,
        setpoint_max_c=limits.max_supply_c,
    )


def build_insight_router(
    runtime: Runtime,
    current: Callable[[], Settings],
    control: ControlLoop | None = None,
) -> APIRouter:
    """Return the ``api/v1/insight`` routes.

    Parameters
    ----------
    runtime
        Service clock and state store.
    current
        Returns the effective settings (history path, time zone, room signal,
        comfort target, journal retention, the house basics switch).
    control
        Control loop (filtered outside temperature); ``None`` uses the measured one.

    Returns
    -------
    APIRouter
        Routes without prefix (the caller adds ``/api/v1``).
    """
    router = APIRouter()
    cache = BasicsCache()

    @router.get("/insight/daily", **returns(InsightDaily))
    async def daily(days: Annotated[int, Query(ge=1, le=MAX_DAYS)] = 7) -> Json:
        """``GET insight/daily``: the last ``days`` local days."""
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

    @router.get("/insight/basics", **returns(InsightBasics))
    async def basics() -> Json:
        """``GET insight/basics``: heat loss and heat from the heat pump."""
        effective = current()
        if not effective.house_basics_enabled:
            return disabled_payload(effective.control_timezone, effective.control_room_signal)
        now = runtime.clock().wall
        live = live_inputs(runtime, effective, control)
        return await asyncio.to_thread(
            basics_payload,
            effective.history_path,
            now=now,
            timezone=effective.control_timezone,
            room_signal=effective.control_room_signal,
            live=live,
            cache=cache,
        )

    return router

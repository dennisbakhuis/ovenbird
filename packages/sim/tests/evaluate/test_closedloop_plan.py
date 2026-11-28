"""Closed loop with a plan-slice provider: the hook, the period, the forecast view."""

from dataclasses import replace
from itertools import pairwise

import numpy as np

from ovenbird_core.control import OvenbirdConfig, OvenbirdController
from ovenbird_core.control.types import PlanSlice, PlanSource, ReasonCode
from ovenbird_core.instant import Instant
from ovenbird_sim.evaluate.closedloop import LoopOptions, PlanRequest, Weather, simulate
from ovenbird_sim.evaluate.forecast import ForecastError, hourly_table
from ovenbird_sim.model.building import BuildingParams
from ovenbird_sim.model.heatpump import HeatPumpParams
from ovenbird_sim.model.plant import PlantParams, initial_state

PARAMS = PlantParams(
    HeatPumpParams(),
    BuildingParams(c_air=3.0e7, h_air_out=250.0, q_int_w=200.0),
)
T0 = 1_793_232_000.0
OFFSET_K = 0.5


def _weather(days: float) -> Weather:
    """Return a ``days`` long weather with a constant 3 degC outside temperature."""
    n = int(days * 1440)
    hours = (np.arange(n) / 60.0) % 24.0
    return Weather(T0, 60.0, np.full(n, 3.0), np.zeros(n), hours.astype(np.float64))


def _preheat(request: PlanRequest) -> PlanSlice:
    """Return a plan slice that raises the room target by ``OFFSET_K`` for 15 minutes."""
    return PlanSlice(
        OFFSET_K,
        ReasonCode.PLAN_PREHEAT,
        request.now,
        request.now.shifted(900.0),
        PlanSource.RULE,
    )


def _run(provider: bool) -> tuple[np.ndarray, tuple[str, ...], tuple[str, ...]]:
    """Return the plan offset, ladder levels and reasons of a day, with or without a provider."""
    weather = _weather(1.0)
    options = LoopOptions(
        initial_setpoint=30,
        plan_provider=_preheat if provider else None,
        plan_forecast=hourly_table(weather) if provider else None,
    )
    controller = OvenbirdController(OvenbirdConfig.preset("mixed", comfort_room_c=21.5))
    start = initial_state(PARAMS, 21.0, t_mass=23.0, t_water=26.0)
    trace = simulate(controller, PARAMS, weather, start, options)
    return trace.plan_room_offset_k, trace.ladder, trace.reasons


def test_closed_loop_runs_a_rule_plan_slice_provider() -> None:
    """A plan provider's slices reach the controller as a rule plan with the plan reason."""
    offsets, ladder, reasons = _run(provider=True)
    assert np.all((offsets == 0.0) | (offsets == OFFSET_K))
    assert np.mean(offsets == OFFSET_K) > 0.5
    assert "rule_plan" in ladder
    assert "plan_preheat" in reasons


def test_closed_loop_runs_without_a_plan_provider() -> None:
    """Without a plan provider the controller never uses a plan."""
    offsets, ladder, reasons = _run(provider=False)
    assert not offsets.any()
    assert "rule_plan" not in ladder
    assert "plan_preheat" not in reasons


def test_provider_gets_the_previous_slice_and_the_room_every_period() -> None:
    """The provider is called every planning period with the previous slice and the room value."""
    weather = _weather(1.0)
    calls: list[PlanRequest] = []

    def provider(request: PlanRequest) -> PlanSlice:
        """Return a 20 minute setback slice from the request time and record the request."""
        calls.append(request)
        return PlanSlice(
            -0.2,
            ReasonCode.PLAN_SETBACK,
            request.now,
            request.now.shifted(1200.0),
            PlanSource.RULE,
        )

    controller = OvenbirdController(OvenbirdConfig.preset("mixed", comfort_room_c=21.5))
    start = initial_state(PARAMS, 21.0, t_mass=23.0, t_water=26.0)
    options = LoopOptions(
        initial_setpoint=30, plan_provider=provider, plan_forecast=hourly_table(weather)
    )
    simulate(controller, PARAMS, weather, start, options)
    stamps = [c.now.wall.timestamp() for c in calls]
    assert all(b - a == 900.0 for a, b in pairwise(stamps))
    assert calls[0].previous_offset_k == 0.0
    assert calls[0].previous_slice is None
    assert all(c.previous_offset_k == -0.2 for c in calls[1:])
    assert all(c.room_c is not None for c in calls[1:])


def test_forecast_error_is_seeded_and_leaves_the_past_alone() -> None:
    """The forecast error depends on its seed and leaves hours up to now untouched."""
    weather = _weather(4.0)
    ghi = np.where((weather.local_hour > 9.0) & (weather.local_hour < 15.0), 300.0, 0.0)
    base = hourly_table(weather, ghi.astype(np.float64))
    now = weather.t0 + 2 * 86400.0 + 3 * 3600.0
    at = Instant.from_unix(now)
    a = replace(base, error=ForecastError(seed=4))
    assert a.rows(at) == replace(base, error=ForecastError(seed=4)).rows(at)
    assert a.rows(at) != replace(base, error=ForecastError(seed=5)).rows(at)
    past = [r for r in a.rows(at) if r.target_ts <= now]
    assert past == [r for r in base.rows(at) if r.target_ts <= now]

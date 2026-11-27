"""The pure-Python house model of the core agrees with the learner's numpy/scipy model."""

from __future__ import annotations

import math
import random
from dataclasses import asdict

import numpy as np
import pytest

from ovenbird_core.derived import WATER_CP_J_PER_KG_K, WATER_DENSITY_KG_PER_L
from ovenbird_core.housemodel import (
    DEFAULTS,
    NOMINAL_FLOW_LPM,
    SHARE_LIMITS,
    W_PER_LPM_K,
    HouseModel,
    supply_c,
)
from ovenbird_sim.identify.building import PRIOR_MEAN
from ovenbird_sim.learn.priors import SHARE_LIMITS as SIM_SHARE_LIMITS
from ovenbird_sim.learn.proposal import DEFAULT_FLOW_LPM, steady_state
from ovenbird_sim.learn.proposal import W_PER_LPM_K as SIM_W_PER_LPM_K
from ovenbird_sim.model.building import BuildingParams, continuous, discretise

PARAMETER_SETS = (
    BuildingParams(),
    BuildingParams(h_air_out=90.0, c_air=2.5e7, c_mass=1.2e8, solar_aperture_m2=6.0),
    BuildingParams(
        c_water=1.0e6,
        c_mass=1.5e7,
        c_air=4.0e6,
        h_water_mass=900.0,
        h_water_air=60.0,
        h_mass_air=300.0,
        h_air_out=420.0,
        solar_mass_fraction=0.2,
        q_int_w=150.0,
        q_int_modulation=0.6,
    ),
)
STEPS = (60.0, 900.0, 3600.0)


def model_of(p: BuildingParams) -> HouseModel:
    return HouseModel.from_json(asdict(p))


def test_defaults_equal_the_learners_prior_means() -> None:
    assert dict(DEFAULTS) == PRIOR_MEAN


def test_constants_equal_the_learners() -> None:
    assert SHARE_LIMITS == SIM_SHARE_LIMITS
    assert NOMINAL_FLOW_LPM == DEFAULT_FLOW_LPM
    assert W_PER_LPM_K == SIM_W_PER_LPM_K
    assert W_PER_LPM_K == WATER_DENSITY_KG_PER_L * WATER_CP_J_PER_KG_K / 60.0


@pytest.mark.parametrize("p", PARAMETER_SETS)
def test_continuous_matrices_equal(p: BuildingParams) -> None:
    a, b = continuous(p)
    mine_a, mine_b = model_of(p).continuous()
    assert np.allclose(mine_a, a, rtol=1e-12, atol=0.0)
    assert np.allclose(mine_b, b, rtol=1e-12, atol=0.0)


@pytest.mark.parametrize("p", PARAMETER_SETS)
@pytest.mark.parametrize("dt", list(STEPS))
def test_discretisation_matches_scipy(p: BuildingParams, dt: float) -> None:
    ad, bd = discretise(p, dt)
    mine = model_of(p).discretise(dt)
    assert np.abs(np.array(mine.ad) - ad).max() < 1e-9
    assert np.abs(np.array(mine.bd) - bd).max() < 1e-9


@pytest.mark.parametrize("p", PARAMETER_SETS)
def test_stepping_over_a_day_matches(p: BuildingParams) -> None:
    rng = random.Random(7)
    dt = 900.0
    ad, bd = discretise(p, dt)
    mine = model_of(p).discretise(dt)
    x_ref = np.array([30.0, 22.0, 21.0])
    x_own: tuple[float, float, float] = (30.0, 22.0, 21.0)
    for _ in range(96):
        u = [rng.uniform(0, 5000), rng.uniform(-10, 15), rng.uniform(0, 600), rng.uniform(0, 800)]
        x_ref = ad @ x_ref + bd @ np.array(u)
        x_own = mine.step(x_own, u)
    assert np.abs(np.array(x_own) - x_ref).max() < 1e-9


@pytest.mark.parametrize("p", PARAMETER_SETS)
@pytest.mark.parametrize("outside", [-12.0, 0.0, 8.0, 20.0])
def test_steady_state_matches_the_curve_proposal(p: BuildingParams, outside: float) -> None:
    heat, loop = steady_state(p, 21.0, outside)
    mine = model_of(p).steady_state(21.0, outside)
    assert mine.heat_w == pytest.approx(heat, rel=1e-12, abs=1e-9)
    assert mine.loop_mean_c == pytest.approx(loop, rel=1e-12)


@pytest.mark.parametrize("p", PARAMETER_SETS)
def test_steady_state_with_sun_is_a_fixed_point_of_the_model(p: BuildingParams) -> None:
    model = model_of(p)
    state = model.steady_state(21.0, -2.0, sun_wm2=150.0, extra_air_w=100.0)
    assert state.heat_w > 0
    step = model.discretise(3600.0)
    inputs = (state.heat_w, -2.0, 150.0, p.q_int_w + 100.0)
    after = step.step((state.loop_mean_c, state.mass_c, 21.0), inputs)
    assert after == pytest.approx((state.loop_mean_c, state.mass_c, 21.0), abs=1e-6)


@pytest.mark.parametrize("p", PARAMETER_SETS)
def test_time_constant_matches(p: BuildingParams) -> None:
    assert model_of(p).time_constant_h == pytest.approx(p.time_constant_h, rel=1e-6)


def test_supply_matches_the_proposal_arithmetic() -> None:
    heat, loop = steady_state(BuildingParams(), 21.0, -5.0)
    expected = loop + heat / (2.0 * DEFAULT_FLOW_LPM * SIM_W_PER_LPM_K)
    assert supply_c(loop, heat) == pytest.approx(expected, rel=1e-12)
    assert math.isfinite(expected)

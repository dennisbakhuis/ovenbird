"""The pure-Python house model: validation, conservation, steady state and drift."""

from __future__ import annotations

import math
from dataclasses import replace
from itertools import pairwise

import pytest

from ovenbird_core.housefacts import FactEstimate
from ovenbird_core.housemodel import (
    DEFAULTS,
    DiscreteHouse,
    HouseModel,
    matrix_exponential,
    supply_c,
    with_defaults_from_estimate,
)


def building() -> dict[str, float]:
    return dict(DEFAULTS)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("c_air", 0.0, "c_air"),
        ("c_mass", -1.0, "c_mass"),
        ("c_water", math.nan, "c_water"),
        ("h_mass_air", -5.0, "h_mass_air"),
        ("h_water_air", math.inf, "h_water_air"),
        ("h_air_out", 0.0, "h_air_out"),
        ("h_air_out", -3.0, "h_air_out"),
        ("solar_mass_fraction", 1.5, "solar_mass_fraction"),
        ("q_int_w", -1.0, "q_int_w"),
        ("q_int_modulation", 2.0, "q_int_modulation"),
        ("solar_aperture_m2", True, "solar_aperture_m2"),
        ("h_water_mass", "400", "h_water_mass"),
    ],
)
def test_from_json_names_the_field(field: str, value: object, message: str) -> None:
    data: dict[str, object] = dict(building())
    data[field] = value
    with pytest.raises(ValueError, match=message):
        HouseModel.from_json(data)


@pytest.mark.parametrize("field", ["c_water", "c_mass", "c_air", "h_air_out", "h_mass_air"])
def test_from_json_requires_the_network(field: str) -> None:
    data = building()
    del data[field]
    with pytest.raises(ValueError, match=field):
        HouseModel.from_json(data)


def test_from_json_defaults_the_optional_parameters_and_ignores_unknown_keys() -> None:
    data = {k: v for k, v in building().items() if not k.startswith(("q_int", "solar"))}
    data["unknown"] = 1.0
    model = HouseModel.from_json(data)
    assert model.q_int_w == DEFAULTS["q_int_w"]
    assert model.solar_aperture_m2 == DEFAULTS["solar_aperture_m2"]


def test_from_json_rejects_a_non_object() -> None:
    with pytest.raises(ValueError, match="object"):
        HouseModel.from_json([1, 2])  # type: ignore[arg-type]


def test_zero_ua_is_rejected() -> None:
    with pytest.raises(ValueError, match="UA"):
        HouseModel(h_air_out=0.0)


@pytest.mark.parametrize("dt", [60.0, 900.0, 3600.0, 43200.0])
def test_discrete_model_conserves_energy(dt: float) -> None:
    discrete = HouseModel().discretise(dt)
    for i, row in enumerate(discrete.ad):
        assert all(x >= 0.0 for x in row)
        assert sum(row) + discrete.bd[i][1] == pytest.approx(1.0, abs=1e-9)


def test_a_uniform_temperature_is_a_fixed_point_without_other_inputs() -> None:
    discrete = HouseModel().discretise(900.0)
    after = discrete.step((12.0, 12.0, 12.0), (0.0, 12.0, 0.0, 0.0))
    assert after == pytest.approx((12.0, 12.0, 12.0), abs=1e-9)


def test_discrete_model_refuses_a_violation() -> None:
    good = HouseModel().discretise(900.0)
    broken = tuple(tuple(x * 0.9 for x in row) for row in good.ad)
    with pytest.raises(ValueError, match="conserve"):
        DiscreteHouse(900.0, broken, good.bd)
    negative = ((-0.1, *good.ad[0][1:]), good.ad[1], good.ad[2])
    with pytest.raises(ValueError, match="negative"):
        DiscreteHouse(900.0, negative, good.bd)


@pytest.mark.parametrize("dt", [0.0, -1.0, 1e6])
def test_discretise_refuses_a_bad_step(dt: float) -> None:
    with pytest.raises(ValueError, match="step"):
        HouseModel().discretise(dt)


def test_matrix_exponential_of_known_matrices() -> None:
    assert matrix_exponential([[0.0, 0.0], [0.0, 0.0]]) == [[1.0, 0.0], [0.0, 1.0]]
    result = matrix_exponential([[1.0, 0.0], [0.0, -2.0]])
    assert result[0][0] == pytest.approx(math.e, rel=1e-14)
    assert result[1][1] == pytest.approx(math.exp(-2.0), rel=1e-14)
    rotation = matrix_exponential([[0.0, -3.0], [3.0, 0.0]])
    assert rotation[0][0] == pytest.approx(math.cos(3.0), abs=1e-14)
    assert rotation[1][0] == pytest.approx(math.sin(3.0), abs=1e-14)
    with pytest.raises(ValueError, match="square"):
        matrix_exponential([[1.0, 2.0]])


def test_steady_state_balances_loss_and_gains() -> None:
    model = HouseModel(h_air_out=200.0, q_int_w=300.0)
    state = model.steady_state(21.0, 1.0)
    assert state.heat_w == pytest.approx(200.0 * 20.0 - 300.0)
    warm = model.steady_state(21.0, 20.0)
    assert warm.heat_w == 0.0
    assert warm.loop_mean_c == 21.0
    sunny = model.steady_state(21.0, 1.0, sun_wm2=200.0, extra_air_w=500.0)
    assert sunny.heat_w == pytest.approx(state.heat_w - 3.0 * 200.0 - 500.0)
    assert sunny.heat_w < state.heat_w


def test_balance_outside_temperature() -> None:
    model = HouseModel(h_air_out=200.0, q_int_w=300.0)
    balance = model.balance_outside_c(21.0)
    assert balance == pytest.approx(19.5)
    assert model.steady_state(21.0, balance).heat_w == pytest.approx(0.0, abs=1e-9)
    assert model.balance_outside_c(21.0, sun_wm2=100.0) < balance


def test_supply_is_above_the_loop_mean_by_half_the_spread() -> None:
    assert supply_c(30.0, 0.0) == 30.0
    assert supply_c(30.0, 3000.0, 10.0) > 30.0
    assert supply_c(30.0, 3000.0, 20.0) < supply_c(30.0, 3000.0, 10.0)
    with pytest.raises(ValueError, match="flow"):
        supply_c(30.0, 100.0, 0.0)


def test_time_constant_is_long_and_finite() -> None:
    assert 20.0 < HouseModel().time_constant_h < 200.0
    assert HouseModel(h_air_out=400.0).time_constant_h < HouseModel(h_air_out=100.0).time_constant_h


def test_drift_cools_towards_the_outside_without_gains() -> None:
    model = HouseModel(q_int_w=0.0, solar_aperture_m2=0.0)
    room = model.free_drift(21.0, 0.0, 0.0, 12.0, 900.0)
    assert len(room) == 12 * 4 + 1
    assert room[0] == 21.0
    assert all(later < earlier for earlier, later in pairwise(room))
    assert all(value > 0.0 for value in room)


def test_drift_warms_towards_a_warm_outside_without_gains() -> None:
    model = HouseModel(q_int_w=0.0, solar_aperture_m2=0.0)
    room = model.free_drift(18.0, 25.0, 0.0, 8.0, 900.0)
    assert all(later > earlier for earlier, later in pairwise(room))


def test_gains_slow_the_drift() -> None:
    cold = HouseModel(q_int_w=0.0, solar_aperture_m2=0.0)
    gains = replace(cold, q_int_w=300.0)
    assert (
        gains.free_drift(21.0, 0.0, 0.0, 8.0, 900.0)[-1]
        > cold.free_drift(21.0, 0.0, 0.0, 8.0, 900.0)[-1]
    )


def test_a_bigger_ua_cools_faster() -> None:
    leaky = HouseModel(h_air_out=400.0).free_drift(21.0, 0.0, 0.0, 8.0, 900.0)[-1]
    tight = HouseModel(h_air_out=100.0).free_drift(21.0, 0.0, 0.0, 8.0, 900.0)[-1]
    assert leaky < tight


def test_defaults_from_an_estimate() -> None:
    model = with_defaults_from_estimate(
        FactEstimate(
            ua_w_per_k=310.0, solar_aperture_m2=4.5, internal_gain_w=440.0, floor_share=1.0
        )
    )
    assert model.h_air_out == 310.0
    assert model.solar_aperture_m2 == 4.5
    assert model.q_int_w == 440.0
    assert model.h_water_mass == pytest.approx(0.95 * 550.0)
    assert model.h_water_air == pytest.approx(0.05 * 550.0)
    assert model.c_air == DEFAULTS["c_air"]


def test_defaults_without_other_facts_use_the_prior_means() -> None:
    model = with_defaults_from_estimate(FactEstimate(ua_w_per_k=250.0))
    assert model == HouseModel(h_air_out=250.0)


def test_defaults_need_a_heat_loss() -> None:
    with pytest.raises(ValueError, match="heat-loss"):
        with_defaults_from_estimate(FactEstimate(solar_aperture_m2=3.0))

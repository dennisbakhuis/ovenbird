"""Frost deposition model, rolling-origin fold files and the off-period emitter estimator."""

import math
from pathlib import Path

import numpy as np
import pytest

from ovenbird_sim.identify import io
from ovenbird_sim.identify.emitter import off_period_tau_h
from ovenbird_sim.model import heatpump as hp
from ovenbird_sim.model.heatpump import HeatPumpParams

FROST = HeatPumpParams(
    coil0=-2.0, coil_o=0.75, coil_h=-0.05, frost_capacity_hpa_h=2.0, frost_rh_pct=85.0
)


def test_saturation_pressures_meet_at_the_triple_point() -> None:
    assert hp.vapour_pressure_water_hpa(0.0) == pytest.approx(6.112)
    assert hp.vapour_pressure_ice_hpa(0.0) == pytest.approx(6.112)
    assert hp.vapour_pressure_ice_hpa(-5.0) < hp.vapour_pressure_water_hpa(-5.0)


def test_frost_driver_needs_a_coil_below_freezing_and_humid_air() -> None:
    assert hp.coil_temperature(FROST, 4.0, 40.0) == pytest.approx(-1.0)
    assert hp.frost_driver_hpa(FROST, 12.0, 30.0, 95.0) == 0.0
    assert hp.frost_driver_hpa(FROST, 2.0, 40.0, 20.0) == 0.0
    humid = hp.frost_driver_hpa(FROST, 2.0, 40.0, 95.0)
    drier = hp.frost_driver_hpa(FROST, 2.0, 40.0, 80.0)
    assert humid > drier > 0.0
    assert hp.frost_driver_hpa(FROST, 2.0, 60.0, 95.0) > humid
    assert hp.frost_driver_hpa(FROST, 2.0, 40.0, math.nan) == pytest.approx(
        hp.frost_driver_hpa(FROST, 2.0, 40.0, 85.0)
    )


def test_frost_rate_is_driver_over_capacity_or_legacy() -> None:
    driver = hp.frost_driver_hpa(FROST, 1.0, 45.0, 90.0)
    assert hp.frost_rate_per_s(FROST, 1.0, 45.0, 90.0) == pytest.approx(driver / 7200.0)
    legacy = HeatPumpParams(defrost0=0.0, defrost_o=0.0, defrost_max_outside_c=10.0)
    assert hp.frost_rate_per_s(legacy, 1.0, 45.0, 90.0) == pytest.approx(1.0 / 3600.0)


def test_negative_frost_capacity_is_rejected() -> None:
    with pytest.raises(ValueError, match="frost capacity"):
        HeatPumpParams(frost_capacity_hpa_h=-1.0)


def test_fold_paths_list_existing_train_files_latest_first(tmp_path: Path) -> None:
    params = tmp_path / "plant_params.json"
    assert io.fold_path(params, 0) == tmp_path / "plant_params_train.json"
    assert io.fold_path(params, 1) == tmp_path / "plant_params_train_2.json"
    assert io.fold_paths(params) == []
    for k in (0, 1, 3):
        io.fold_path(params, k).write_text("{}", encoding="utf-8")
    assert io.fold_paths(params) == [io.fold_path(params, 0), io.fold_path(params, 1)]


def _cycling(tau_h: float, periods: int = 12) -> tuple[np.ndarray, ...]:
    on, off = 60, 90
    running = np.tile(np.r_[np.ones(on), np.zeros(off)], periods + 1)
    t = np.arange(running.size) * 60.0
    water = np.full(running.size, 30.0)
    room = np.full(running.size, 21.0)
    for k in range(periods + 1):
        stop = k * (on + off) + on
        minutes = np.arange(off)
        water[stop : stop + off] = 21.0 + 9.0 * np.exp(-minutes / 60.0 / tau_h)
    return t, water, room, running


def test_off_period_tau_recovers_an_exponential_decay() -> None:
    tau, n = off_period_tau_h(*_cycling(1.2))
    assert n == 12
    assert tau == pytest.approx(1.2, rel=1e-6)


def test_off_period_tau_needs_enough_periods() -> None:
    tau, n = off_period_tau_h(*_cycling(1.2, periods=5))
    assert n == 5
    assert math.isnan(tau)

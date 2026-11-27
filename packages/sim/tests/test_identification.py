import json
import math
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pytest

from ovenbird_core.housefacts import HouseFacts, estimate
from ovenbird_sim.data.dataset import Dataset
from ovenbird_sim.data.synthetic import simulated_dataset
from ovenbird_sim.identify import io
from ovenbird_sim.identify.building import (
    BOUNDS,
    LIN_FIELDS,
    LOG_FIELDS,
    PRIOR_MEAN,
    PRIOR_SD,
    BuildingFit,
    FitConfig,
    ParamPrior,
    Priors,
    Windows,
    bootstrap_building,
    fit_building,
    internal_gains,
)
from ovenbird_sim.identify.heatpump import (
    check_warmup,
    fit_capacity,
    fit_cold_floor,
    fit_cop,
    fit_defrost_rate,
    fit_heat_pump,
)
from ovenbird_sim.identify.kalman import filter_states
from ovenbird_sim.identify.pipeline import IdentifyOptions, identify_dataset
from ovenbird_sim.identify.switching import BaseSignals, StartPhaseFit, analyse_switching
from ovenbird_sim.identify.validate import plant_days
from ovenbird_sim.insight.signature import DailyData, energy_signature
from ovenbird_sim.learn.priors import HouseBounds, build_priors, house_settings
from ovenbird_sim.model.building import BuildingParams, simulate_batch
from ovenbird_sim.model.heatpump import HeatPumpParams
from ovenbird_sim.model.plant import PlantParams, PlantState

DT = 300.0
STEPS = 288
TRUE_BUILDING = BuildingParams(
    c_water=1.0e6,
    c_mass=1.0e7,
    c_air=6.0e7,
    h_water_mass=900.0,
    h_water_air=60.0,
    h_mass_air=700.0,
    h_air_out=280.0,
    solar_aperture_m2=6.0,
    solar_mass_fraction=0.3,
    q_int_w=350.0,
    q_int_modulation=0.0,
    q_int_peak_hour=19.0,
)


def _excitation(days: int, seed: int = 3) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    n = days * STEPS
    t = np.arange(n) * DT
    hour = (t / 3600.0) % 24.0
    period = rng.integers(18, 48, size=n // 18 + 1).repeat(18)[:n]
    phase = (np.arange(n) % period) < (period * rng.uniform(0.3, 0.7))
    level = rng.uniform(4000.0, 9000.0, size=n // 36 + 1).repeat(36)[:n]
    heat = np.where(phase, level, 0.0)
    outside = 6.0 + 4.0 * np.sin(2 * np.pi * (hour - 9.0) / 24.0) + 3.0 * np.sin(t / 86400.0 / 3.0)
    ghi = np.clip(400.0 * np.sin(np.pi * (hour - 7.0) / 10.0), 0.0, None)
    return heat, outside, ghi, hour


def _windows(
    p: BuildingParams, days: int, noise: float, seed: int = 4
) -> tuple[Windows, np.ndarray]:
    heat, outside, ghi, hour = _excitation(days)
    u = np.column_stack([heat, outside, ghi, internal_gains(p, hour)])[None]
    x = simulate_batch(p, DT, np.array([[28.0, 24.0, 21.0]]), u)[0]
    rng = np.random.default_rng(seed)
    y_w = x[:, 0] + rng.normal(0.0, noise, x.shape[0])
    y_a = x[:, 2] + rng.normal(0.0, noise / 3.0, x.shape[0])
    idx = np.arange(days)[:, None] * STEPS
    steps = idx + np.arange(STEPS)[None]
    obs = idx + np.arange(STEPS + 1)[None]
    win = Windows(
        DT,
        (idx[:, 0] * DT).astype(np.float64),
        np.stack([heat[steps], outside[steps], ghi[steps]], axis=-1),
        hour[steps],
        y_w[obs],
        y_a[obs],
        np.full(steps.shape, 25.0),
    )
    return win, x


def test_building_fit_recovers_known_parameters() -> None:
    win, _ = _windows(TRUE_BUILDING, days=12, noise=0.05)
    config = FitConfig(
        fixed=("q_int_modulation", "q_int_peak_hour", "solar_mass_fraction", "h_water_air")
    )
    start = BuildingParams(h_water_air=60.0, solar_mass_fraction=0.3)
    fit = fit_building(win, config, start=start)
    p = fit.params
    assert fit.success
    assert p.h_air_out == pytest.approx(TRUE_BUILDING.h_air_out, rel=0.1)
    assert p.c_water == pytest.approx(TRUE_BUILDING.c_water, rel=0.15)
    assert p.h_water_mass == pytest.approx(TRUE_BUILDING.h_water_mass, rel=0.15)
    assert p.time_constant_h == pytest.approx(TRUE_BUILDING.time_constant_h, rel=0.25)
    assert fit.rmse_room < 0.05


def test_kalman_filter_tracks_unmeasured_mass() -> None:
    win, x = _windows(TRUE_BUILDING, days=4, noise=0.05)
    u = np.concatenate(
        [win.u, internal_gains(TRUE_BUILDING, win.hour)[..., None]], axis=-1
    ).reshape(-1, 4)
    y_w = np.concatenate([win.y_water[0], *(row[1:] for row in win.y_water[1:])])
    y_a = np.concatenate([win.y_room[0], *(row[1:] for row in win.y_room[1:])])
    states = filter_states(TRUE_BUILDING, DT, u, y_w, y_a, np.array([28.0, 20.0, 21.0]))
    late = slice(STEPS * 2, None)
    assert np.sqrt(np.mean((states[late, 1] - x[late, 1]) ** 2)) < 0.3


def test_capacity_cop_and_defrost_regressions_recover_coefficients() -> None:
    rng = np.random.default_rng(0)
    n = 5000
    hz = rng.uniform(19.0, 60.0, n)
    t_o = rng.uniform(-3.0, 12.0, n)
    t_out = rng.uniform(28.0, 38.0, n)
    heat = hz * (20.0 + 9.0 * t_o + 6.0 * t_out)
    (k0, k_o, k_s), rmse = fit_capacity(heat, hz, t_o, t_out)
    assert (k0, k_o, k_s) == pytest.approx((20.0, 9.0, 6.0), rel=1e-6)
    assert rmse < 1e-6
    cop = np.exp(1.5 + 0.04 * t_o - 0.02 * t_out - 0.01 * hz)
    coef, _ = fit_cop(heat, heat / cop, t_o, t_out, hz)
    assert coef == pytest.approx((1.5, 0.04, -0.02, -0.01), abs=1e-6)
    exposure = rng.uniform(-3.0, 6.0, 200_000)
    rate = np.exp(-0.2 - 0.5 * exposure) / 60.0
    events = exposure[rng.random(exposure.size) < rate]
    d0, d_o = fit_defrost_rate(events, exposure, 60.0, 6.0)
    assert d0 == pytest.approx(-0.2, abs=0.15)
    assert d_o == pytest.approx(-0.5, abs=0.06)


def test_cold_floor_detection() -> None:
    sensor = np.repeat(np.arange(-2.0, 10.0), 200)
    hz = np.where(sensor <= 4, 34.3, 19.4) + np.random.default_rng(1).uniform(
        0.0, 10.0, sensor.size
    )
    floor, threshold = fit_cold_floor(hz, sensor, 19.0)
    assert threshold == 4.0
    assert floor == pytest.approx(34.5, abs=0.5)


TRUE_PUMP = HeatPumpParams(
    start_trigger_margin_k=3.75,
    start_steady_margin_k=6.0,
    start_steady_delay_s=300.0,
    min_off_s=180.0,
    outlet_bias_k=0.2,
    hz_start=40.0,
    hz_gain=1.2,
    hz_deadband_k=0.4,
    hz_rate_down=1.5,
    hz_rate_up=5.0,
    k0=0.0,
    k_o=10.0,
    k_in=6.0,
    cop0=1.4,
    cop_o=0.04,
    cop_s=0.02,
    cop_h=-0.025,
    circulation_w=15.0,
    flow_running_lpm=24.0,
    hz_min_cold=36.0,
    defrost0=-0.3,
    defrost_o=-0.35,
    defrost_max_outside_c=7.0,
    defrost_duration_s=420.0,
    defrost_heat_w=-4800.0,
    spread_offset_k=0.3,
    outside_bias_running_k=-1.0,
)


STARTUP_PUMP = TRUE_PUMP.replace(
    hz_max=70.0,
    k_warmup=-40.0,
    k_warmup_tau_s=600.0,
    start_phase_s=240.0,
    hz_resume0=42.0,
    hz_resume_o=-0.5,
    cop_warmup=-0.3,
    cop_warmup_tau_s=300.0,
)


def _setpoint_schedule(n: int, seed: int = 5) -> np.ndarray:
    rng = np.random.default_rng(seed)
    blocks = rng.integers(28, 36, size=n // 45 + 1).astype(float)
    return blocks.repeat(45)[:n]


def _plant_dataset(days: int, pump: HeatPumpParams = TRUE_PUMP) -> tuple[PlantParams, Dataset]:
    n = days * 1440
    minutes = np.arange(n)
    outside = 6.0 + 6.0 * np.sin(2 * np.pi * minutes / 1440.0) - 4.0 * (minutes / n)
    ghi = np.clip(300.0 * np.sin(np.pi * ((minutes / 60.0) % 24 - 7.0) / 10.0), 0.0, None)
    params = PlantParams(pump, TRUE_BUILDING)
    state = PlantState(t_water=27.0, t_mass=25.0, t_air=21.0, off_s=3600.0)
    ds = simulated_dataset(
        params, state, _setpoint_schedule(n), outside, ghi, start=1_789_999_200.0
    )
    return params, ds


@pytest.mark.slow
def test_heat_pump_fit_recovers_start_up_behaviour() -> None:
    _, ds = _plant_dataset(days=6, pump=STARTUP_PUMP)
    truth = STARTUP_PUMP
    fit = fit_heat_pump(ds, start_phase=StartPhaseFit(truth.hz_start, truth.start_phase_s, 10))
    p = fit.params
    assert (p.k_o, p.k_in) == pytest.approx((truth.k_o, truth.k_in), rel=0.05)
    assert p.k_warmup == pytest.approx(truth.k_warmup, rel=0.2)
    assert p.cop_warmup == pytest.approx(truth.cop_warmup, abs=0.05)
    assert p.cop_warmup_tau_s == truth.cop_warmup_tau_s
    assert p.start_phase_s == truth.start_phase_s
    assert p.hz_resume0 == pytest.approx(truth.hz_resume0, abs=2.5)
    assert p.hz_resume_o == pytest.approx(truth.hz_resume_o, abs=0.3)
    assert fit.cop is not None
    assert fit.cop_steady is not None
    check = check_warmup(ds, fit.cop, fit.cop_steady)
    assert abs(check.cop_model_early - check.cop_recorded_early) < abs(
        check.cop_steady_map_early - check.cop_recorded_early
    )
    assert check.rmse_log_early < check.rmse_log_early_without


def test_heat_pump_fit_recovers_simulated_pump() -> None:
    params, ds = _plant_dataset(days=6)
    fit = fit_heat_pump(ds)
    p = fit.params
    assert fit.n_steady > 200
    assert p.k_s == 0.0
    assert (p.k_o, p.k_in) == pytest.approx((TRUE_PUMP.k_o, TRUE_PUMP.k_in), rel=0.05)
    assert p.cop_o == pytest.approx(TRUE_PUMP.cop_o, abs=0.005)
    assert p.cop_h == pytest.approx(TRUE_PUMP.cop_h, abs=0.003)
    assert p.circulation_w == pytest.approx(TRUE_PUMP.circulation_w, abs=1.0)
    assert -2.0 <= p.cold_floor_outside_c <= TRUE_PUMP.cold_floor_outside_c
    assert p.hz_min_cold == pytest.approx(TRUE_PUMP.hz_min_cold, abs=0.5)
    assert fit.controller.rmse_hz < 1.25
    assert p.hz_rate_down == pytest.approx(TRUE_PUMP.hz_rate_down, rel=0.2)
    assert p.outlet_bias_k == pytest.approx(TRUE_PUMP.outlet_bias_k, abs=0.1)
    assert p.flow_running_lpm == pytest.approx(TRUE_PUMP.flow_running_lpm)
    assert fit.defrost_events > 3
    assert p.outside_bias_running_k == pytest.approx(TRUE_PUMP.outside_bias_running_k, abs=0.5)
    assert params.heat_pump.spread_offset_k == p.spread_offset_k


def test_switching_analysis_recovers_stop_rule_and_trigger() -> None:
    params, ds = _plant_dataset(days=4)
    c = ds.columns
    sig = BaseSignals(ds.t, c["inlet"], c["outlet"], c["hz"], c["target"], ds.flags["defrost"])
    report = analyse_switching(sig, step=60.0)
    assert report.heating_starts > 10
    assert report.stop_rule_share > 0.8
    assert report.start_fit is not None
    assert report.start_fit.trigger_margin_k == pytest.approx(
        TRUE_PUMP.start_trigger_margin_k, abs=0.3
    )
    assert report.start_fit.hit_rate > 0.8
    del params


def test_plant_days_reproduce_a_simulated_recording() -> None:
    params, ds = _plant_dataset(days=3)
    start = ds.grid.start + 86400.0
    days = plant_days(ds, params, start, ds.grid.end)
    assert days.day_starts.size >= 1
    assert abs(days.heat_error_pct) < 5.0
    assert np.all(days.room_rmse < 0.3)


def test_energy_signature_recovers_and_applies_credibility_rules() -> None:
    rng = np.random.default_rng(2)
    n = 60
    outside = rng.uniform(-4.0, 14.0, n)
    indoor = 21.0 + rng.normal(0.0, 0.2, n)
    ghi = rng.uniform(10.0, 120.0, n)
    heat = np.maximum(320.0 * (indoor - outside) - 9.0 * ghi - 400.0, 0.0) + rng.normal(
        0.0, 80.0, n
    )
    days = (np.arange(n) * 86400.0).astype(np.float64)
    d = DailyData(days, heat, indoor, outside, ghi, np.zeros(n))
    sig = energy_signature(d, rc_h_w_per_k=310.0, replicates=100)
    assert sig.h_w_per_k == pytest.approx(320.0, rel=0.05)
    width = sig.h_interval[1] - sig.h_interval[0]
    assert sig.h_interval[0] - width < 320.0 < sig.h_interval[1] + width
    assert sig.credible
    assert not sig.low_confidence
    assert sig.capacity_at_design_w is not None
    few = d.take(np.flatnonzero(outside > 6.0)[:12])
    weak = energy_signature(few, rc_h_w_per_k=200.0, replicates=50)
    assert not weak.credible
    assert weak.low_confidence
    assert weak.capacity_at_design_w is None
    assert any("heating days" in r for r in weak.reasons)


def test_params_round_trip(tmp_path: Path) -> None:
    params = PlantParams(
        replace(HeatPumpParams(), k_o=9.5), replace(BuildingParams(), h_air_out=210.0)
    )
    path = io.save(tmp_path / "models" / "p.json", params, {"note": float("nan")})
    assert io.load(path) == params
    assert json.loads(path.read_text())["note"] is None


@pytest.mark.slow
def test_identify_dataset_pipeline_runs_on_a_synthetic_recording() -> None:
    params, ds = _plant_dataset(days=8)
    c = ds.columns
    base = BaseSignals(ds.t, c["inlet"], c["outlet"], c["hz"], c["target"], ds.flags["defrost"])
    result = identify_dataset(ds, base, IdentifyOptions(bootstrap=0, test_days=2, folds=1))

    assert len(result.folds) == 1
    assert result.switching.heating_starts > 10
    assert result.params.heat_pump.k_o == pytest.approx(params.heat_pump.k_o, rel=0.1)
    assert result.params.building.h_air_out == pytest.approx(params.building.h_air_out, rel=0.5)
    assert result.building_intervals == {}
    assert result.heat_pump_intervals == {}
    assert ds.grid.start < result.split < ds.grid.end
    payload = result.to_json()
    report = json.loads(json.dumps(payload))
    assert {"data", "derived", "events"} <= report.keys()
    assert report["data"]["days"] == pytest.approx(8, abs=1)


HELD = FitConfig(
    fixed=("q_int_modulation", "q_int_peak_hour", "solar_mass_fraction", "h_water_air")
)
START = BuildingParams(h_water_air=60.0, solar_mass_fraction=0.3)


@pytest.fixture(scope="module")
def windows() -> Windows:
    win, _ = _windows(TRUE_BUILDING, days=12, noise=0.05)
    return win


@pytest.fixture(scope="module")
def free_fit(windows: Windows) -> BuildingFit:
    return fit_building(windows, HELD, start=START)


def bounds(**ranges: tuple[float | None, float | None]) -> HouseBounds:
    names = {
        "ua": "house_ua_min_w_per_k",
        "tau": "house_time_constant_min_h",
        "solar": "house_solar_aperture_min_m2",
        "gains": "house_internal_gain_min_w",
    }
    return HouseBounds({names[k]: v for k, v in ranges.items()})


def priors_of(facts: HouseFacts | None = None, limits: HouseBounds | None = None) -> Priors:
    return build_priors(facts or HouseFacts(), limits or HouseBounds())[0]


def test_defaults_reproduce_todays_fit_exactly(windows: Windows, free_fit: BuildingFit) -> None:
    rebuilt = Priors(
        {
            n: ParamPrior(PRIOR_MEAN[n], PRIOR_SD[n], BOUNDS[n][0], BOUNDS[n][1])
            for n in (*LOG_FIELDS, *LIN_FIELDS)
        }
    )
    for priors in (rebuilt, priors_of(), house_settings({}).priors):
        fit = fit_building(windows, HELD, start=START, priors=priors)
        assert asdict(fit.params) == asdict(free_fit.params)
        assert np.array_equal(fit.t_mass0, free_fit.t_mass0)
        assert fit.cost == free_fit.cost


def test_pinned_ua_is_kept_and_the_rest_still_moves(
    windows: Windows, free_fit: BuildingFit
) -> None:
    priors = priors_of(limits=bounds(ua=(200.0, 200.0)))
    assert priors.pinned == {"h_air_out": 200.0}
    fit = fit_building(windows, HELD, start=START, priors=priors)
    assert fit.params.h_air_out == 200.0
    assert fit.params.q_int_w != pytest.approx(free_fit.params.q_int_w, rel=0.05)
    assert fit.params.c_air != pytest.approx(START.c_air, rel=0.05)
    assert fit.rmse_room > free_fit.rmse_room


def test_ua_range_is_respected_at_the_bound(windows: Windows, free_fit: BuildingFit) -> None:
    assert free_fit.params.h_air_out > 250.0
    priors = priors_of(limits=bounds(ua=(None, 220.0)))
    assert priors.params["h_air_out"] == ParamPrior(200.0, math.log(5.0), 30.0, 220.0)
    fit = fit_building(windows, HELD, start=START, priors=priors)
    assert fit.params.h_air_out <= 220.0 * (1 + 1e-9)
    assert fit.params.h_air_out == pytest.approx(220.0, rel=0.01)


def test_time_constant_range_and_pin(windows: Windows, free_fit: BuildingFit) -> None:
    tau = free_fit.params.time_constant_h
    assert tau > 65.0
    ranged = fit_building(
        windows, HELD, start=START, priors=priors_of(limits=bounds(tau=(30.0, 55.0)))
    )
    assert ranged.params.time_constant_h <= 55.0 * 1.03
    assert ranged.params.time_constant_h >= 30.0
    pinned = fit_building(
        windows, HELD, start=START, priors=priors_of(limits=bounds(tau=(100.0, 100.0)))
    )
    assert pinned.params.time_constant_h == pytest.approx(100.0, rel=0.03)
    loose = fit_building(
        windows, HELD, start=START, priors=priors_of(limits=bounds(tau=(20.0, 200.0)))
    )
    assert loose.params.h_air_out == pytest.approx(free_fit.params.h_air_out, rel=1e-4)
    assert loose.params.time_constant_h == pytest.approx(tau, rel=1e-4)


def test_bootstrap_replicates_apply_the_constraints(windows: Windows) -> None:
    priors = priors_of(limits=bounds(ua=(250.0, 250.0), tau=(None, 60.0)))
    point = fit_building(windows, HELD, start=START, priors=priors)
    boot = bootstrap_building(windows, point, 2, HELD, seed=1, priors=priors)
    assert [p.h_air_out for p in boot.samples] == [250.0, 250.0]
    assert all(p.time_constant_h <= 60.0 * 1.03 for p in boot.samples)


@pytest.mark.parametrize("factor", [2.0, 0.5])
def test_wrong_facts_by_a_factor_two_are_overruled(
    windows: Windows, free_fit: BuildingFit, factor: float
) -> None:
    true_ua = TRUE_BUILDING.h_air_out
    area = true_ua * factor / 2.043
    facts = HouseFacts(
        floor_area_m2=area,
        build_period="1975_1991",
        window_area_m2=TRUE_BUILDING.solar_aperture_m2 * factor / (1.1 * 0.3),
        window_orientation="south",
        occupants=round((TRUE_BUILDING.q_int_w * factor - 120.0) / 80.0),
    )
    told = estimate(facts)
    assert told.ua_w_per_k == pytest.approx(true_ua * factor, rel=0.01)
    fit = fit_building(windows, HELD, start=START, priors=priors_of(facts))
    p = fit.params
    assert p.h_air_out == pytest.approx(true_ua, rel=0.1)
    assert p.c_water == pytest.approx(TRUE_BUILDING.c_water, rel=0.15)
    assert p.h_water_mass == pytest.approx(TRUE_BUILDING.h_water_mass, rel=0.15)
    assert p.time_constant_h == pytest.approx(TRUE_BUILDING.time_constant_h, rel=0.25)
    assert p.solar_aperture_m2 == pytest.approx(TRUE_BUILDING.solar_aperture_m2, rel=0.1)
    assert p.q_int_w == pytest.approx(free_fit.params.q_int_w, rel=0.25)
    assert fit.rmse_room < 0.05

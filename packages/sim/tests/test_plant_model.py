import math
from dataclasses import replace

import numpy as np
import pytest

from ovenbird_sim.model import heatpump as hp
from ovenbird_sim.model.building import BuildingParams, discretise, stored_energy_j
from ovenbird_sim.model.heatpump import HeatPumpParams
from ovenbird_sim.model.plant import Exogenous, PlantParams, PlantState, initial_state, step
from ovenbird_sim.model.simulate import Trajectory, run

PARAMS = PlantParams(HeatPumpParams(), BuildingParams())


def _run_days(
    params: PlantParams, days: float, setpoint: float, outside: float, dt: float = 60.0
) -> Trajectory:
    """Simulate ``days`` at a constant setpoint and outside temperature; return the trajectory."""
    n = int(days * 86400 / dt)
    state = initial_state(params, 21.0, t_mass=23.0, t_water=25.0)
    hour = ((np.arange(n) * dt / 3600.0) % 24.0).astype(np.float64)
    return run(params, state, np.full(n, setpoint), np.full(n, outside), np.zeros(n), hour, dt)


def test_step_is_deterministic_and_pure() -> None:
    """A step is deterministic and does not change its input state."""
    state = initial_state(PARAMS, 21.0)
    exo = Exogenous(2.0, 100.0, 9.0)
    a = step(state, PARAMS, 32.0, exo, 60.0)
    b = step(state, PARAMS, 32.0, exo, 60.0)
    assert a == b
    assert state == initial_state(PARAMS, 21.0)


def test_step_rejects_bad_inputs() -> None:
    """A step refuses a non-positive time step and a non-finite setpoint."""
    state = initial_state(PARAMS, 21.0)
    with pytest.raises(ValueError, match="dt"):
        step(state, PARAMS, 30.0, Exogenous(2.0), 0.0)
    with pytest.raises(ValueError, match="finite"):
        step(state, PARAMS, math.nan, Exogenous(2.0), 60.0)


def test_energy_balance_closes() -> None:
    """Over a long run the stored energy changes by the delivered heat minus the losses."""
    b = BuildingParams()
    params = PlantParams(HeatPumpParams(defrost0=-50.0), b)
    dt = 10.0
    n = 6 * 360
    state = initial_state(params, 20.0, t_mass=22.0, t_water=24.0)
    e0 = stored_energy_j(b, state.t_water, state.t_mass, state.t_air)
    loss = 0.0
    solar = 50.0
    s = state
    for k in range(n):
        hour = (k * dt / 3600.0) % 24
        before = s.t_air
        s, _ = step(s, params, 33.0, Exogenous(3.0, solar, hour), dt)
        loss += b.h_air_out * (0.5 * (before + s.t_air) - 3.0) * dt
        loss -= (b.internal_gain(hour) + b.solar_aperture_m2 * solar) * dt
    e1 = stored_energy_j(b, s.t_water, s.t_mass, s.t_air)
    assert s.heat_j > 0
    assert (e1 - e0) == pytest.approx(s.heat_j - loss, rel=1e-3, abs=2e5)


def test_temperatures_stay_physical_without_heat() -> None:
    """Without heating the room cools towards the outside temperature but stays physical."""
    params = replace(PARAMS, heat_pump=replace(PARAMS.heat_pump, start_steady_margin_k=200.0))
    traj = _run_days(params, 10, setpoint=-50.0, outside=-15.0)
    assert traj.final.starts == 0
    assert (traj.t_air > -273.15).all()
    assert traj.t_air.min() >= -15.0 - 1e-6
    assert np.all(np.diff(traj.t_air[-100:]) <= 1e-9)


def test_stop_rule_needs_overshoot_for_stop_delay() -> None:
    """The compressor stops only after the outlet has exceeded the setpoint for the stop delay."""
    p = PARAMS.heat_pump
    state = PlantState(
        t_water=40.0, t_mass=30.0, t_air=21.0, running=True, hz=30.0, heat_w=0.0, run_s=600.0
    )
    s = state
    stops = []
    for _ in range(4):
        s, _ = step(s, PARAMS, 30.0, Exogenous(8.0), 60.0)
        stops.append(s.running)
    assert stops[:2] == [True, True]
    assert not stops[2]
    assert p.stop_delay_s == 180.0


def test_start_on_setpoint_change_needs_margin() -> None:
    """A setpoint change starts the compressor only when it exceeds the start margin."""
    p = PARAMS.heat_pump
    idle = PlantState(t_water=26.0, t_mass=25.0, t_air=21.0, off_s=3600.0, last_setpoint=29.0)
    s_small, _ = step(idle, PARAMS, 29.0 + 0.5, Exogenous(8.0), 60.0)
    assert not s_small.running
    trigger_sp = 26.0 + p.start_trigger_margin_k + 0.25
    s_big, obs = step(idle, PARAMS, trigger_sp, Exogenous(8.0), 60.0)
    assert s_big.running
    assert s_big.starts == 1
    assert obs.compressor_freq >= p.hz_min


def test_min_off_time_blocks_restart() -> None:
    """The compressor does not restart before its minimum off time."""
    idle = PlantState(t_water=20.0, t_mass=25.0, t_air=21.0, off_s=0.0, last_setpoint=29.0)
    s, _ = step(idle, PARAMS, 35.0, Exogenous(8.0), 60.0)
    assert not s.running


def test_cold_floor_raises_minimum_frequency() -> None:
    """A cold outside temperature raises the minimum frequency and lowers the capacity."""
    p = PARAMS.heat_pump
    assert hp.min_frequency(p, p.cold_floor_outside_c) == p.hz_min_cold
    assert hp.min_frequency(p, p.cold_floor_outside_c + 1) == p.hz_min
    q_cold, _ = hp.capacity_range(p, 2.0, 35.0)
    q_warm, _ = hp.capacity_range(p, 8.0, 35.0)
    assert q_cold > q_warm


def test_frequency_controller_respects_rate_limits() -> None:
    """The frequency controller moves up and down at its rate limits and holds near the target."""
    p = PARAMS.heat_pump
    up = hp.next_frequency(p, 30.0, 35.0, 25.0, 60.0)
    down = hp.next_frequency(p, 30.0, 25.0, 35.0, 60.0)
    hold = hp.next_frequency(p, 30.0, 30.0, 30.0 + p.outlet_bias_k, 60.0)
    assert up == pytest.approx(30.0 + p.hz_rate_up)
    assert down == pytest.approx(30.0 - p.hz_rate_down)
    assert hold == 30.0


def test_defrost_draws_heat_and_lowers_delivered_heat() -> None:
    """Defrost draws heat from the loop and lowers the heat delivered per running minute."""
    frosty = replace(PARAMS.heat_pump, defrost0=1.0, defrost_o=0.0, defrost_max_outside_c=10.0)
    clean = replace(PARAMS.heat_pump, defrost0=-50.0)
    with_defrost = _run_days(replace(PARAMS, heat_pump=frosty), 1.0, setpoint=34.0, outside=0.0)
    without = _run_days(replace(PARAMS, heat_pump=clean), 1.0, setpoint=34.0, outside=0.0)
    assert with_defrost.final.defrosts > 0
    assert without.final.defrosts == 0
    assert with_defrost.heat_w[with_defrost.defrosting > 0].max() < 0
    in_defrost = with_defrost.defrosting > 0
    assert (with_defrost.elec_w[in_defrost] == frosty.defrost_elec_w).all()
    run_minutes = (with_defrost.running > 0).sum()
    heat_per_run_minute = with_defrost.heat_w.sum() / run_minutes
    clean_per_run_minute = without.heat_w.sum() / (without.running > 0).sum()
    assert heat_per_run_minute < clean_per_run_minute


def test_observation_resolution_and_topics() -> None:
    """Observations are quantised, the outside reading is an integer and the topics are complete."""
    state = PlantState(t_water=30.0, t_mass=28.0, t_air=21.234, running=True, hz=30.0, run_s=600.0)
    _, obs = step(state, PARAMS, 31.0, Exogenous(2.3), 60.0)
    assert (obs.inlet_temp * 4) % 1 == 0
    assert (obs.outlet_temp * 4) % 1 == 0
    assert isinstance(obs.outside_temp, int)
    assert obs.outside_temp == round(2.3 + PARAMS.heat_pump.outside_bias_running_k)
    topics = obs.main_topics()
    assert topics["Main_Target_Temp"] == "31"
    assert set(topics) >= {"Main_Inlet_Temp", "Main_Outlet_Temp", "Compressor_Freq", "Pump_Flow"}


def test_discretisation_matches_fine_integration() -> None:
    """The discretised model over 60 s equals sixty steps of 1 s."""
    b = BuildingParams()
    ad60, bd60 = discretise(b, 60.0)
    ad1, bd1 = discretise(b, 1.0)
    x = np.array([30.0, 25.0, 21.0])
    u = np.array([5000.0, 2.0, 100.0, 300.0])
    fine = x.copy()
    for _ in range(60):
        fine = ad1 @ fine + bd1 @ u
    assert np.allclose(ad60 @ x + bd60 @ u, fine)


def test_parameter_validation() -> None:
    """Invalid building and heat pump parameters are refused."""
    with pytest.raises(ValueError, match="positive"):
        BuildingParams(c_air=0.0)
    with pytest.raises(ValueError, match="hz_min"):
        HeatPumpParams(hz_min=40.0, hz_max=30.0)
    with pytest.raises(ValueError, match="defrost_heat_w"):
        HeatPumpParams(defrost_heat_w=10.0)


def test_time_constant_is_hours_scale() -> None:
    """The building time constant is of the order of hours."""
    assert 10.0 < BuildingParams().time_constant_h < 1000.0


STARTUP = HeatPumpParams(
    k0=300.0,
    hz_start=35.0,
    start_phase_s=240.0,
    hz_resume0=50.0,
    hz_resume_o=-1.0,
    cop_warmup=-0.5,
    cop_warmup_tau_s=300.0,
    k_warmup=-50.0,
    k_warmup_tau_s=600.0,
    circulation_w=5.0,
)


def _started(p: HeatPumpParams, steps: int, outside: float = 5.0) -> list[tuple[PlantState, float]]:
    """Return the plant states and inlet temperatures of ``steps`` minutes after a cold start."""
    params = PlantParams(p, BuildingParams())
    state = replace(initial_state(params, 21.0, t_mass=23.0, t_water=24.0), last_setpoint=30.0)
    out = []
    for _ in range(steps):
        state, obs = step(state, params, 32.0, Exogenous(outside), 60.0)
        out.append((state, obs.inlet_temp))
    return out


def test_start_phase_holds_the_plateau_then_jumps_to_the_resume_level() -> None:
    """The start phase holds a frequency plateau and then jumps to the resume level."""
    states = _started(STARTUP, 8)
    assert all(s.running for s, _ in states)
    hz = [s.hz for s, _ in states]
    assert hz[:4] == [35.0, 35.0, 35.0, 35.0]
    reading = hp.sensor_outside(STARTUP, 5.0, running=True)
    assert hz[4] == pytest.approx(50.0 - reading)
    assert states[0][0].steady_starts == 0


def test_return_delay_keeps_the_inlet_cold_after_a_start() -> None:
    """The return delay keeps the inlet cold for a while after a start."""
    delayed = _started(STARTUP.replace(return_delay_s=360.0), 10)
    plain = _started(STARTUP, 10)
    inlets = [inlet for _, inlet in delayed]
    assert max(inlets[:5]) - min(inlets[:5]) <= 0.25
    assert inlets[8] > max(inlets[:5])
    early = [inlet for _, inlet in plain][:5]
    assert max(early) - min(early) > 0.25


def test_warm_up_terms_lower_start_up_heat_and_cop() -> None:
    """Warm-up terms lower the heat and COP right after the start and fade out."""
    assert hp.cop(STARTUP, 5.0, 35.0, 30.0, 0.0) == pytest.approx(
        hp.cop(STARTUP, 5.0, 35.0, 30.0) * math.exp(-0.5)
    )
    assert hp.cop(STARTUP, 5.0, 35.0, 30.0, 3600.0) == pytest.approx(
        hp.cop(STARTUP, 5.0, 35.0, 30.0), rel=1e-4
    )
    cold = hp.heat_output(STARTUP, 5.0, 35.0, 30.0, 0.0)
    warm = hp.heat_output(STARTUP, 5.0, 35.0, 30.0)
    assert warm - cold == pytest.approx(50.0 * 30.0)
    params = PlantParams(STARTUP, BuildingParams())
    idle = initial_state(params, 21.0, t_mass=23.0, t_water=30.0)
    _, obs = step(idle, params, 25.0, Exogenous(5.0), 60.0)
    assert obs.elec_w == pytest.approx(STARTUP.circulation_w)
    first, _ = _started(STARTUP, 1)[0]
    params_off = PlantParams(STARTUP.replace(cop_warmup=0.0), BuildingParams())
    state = replace(initial_state(params_off, 21.0, t_mass=23.0, t_water=24.0), last_setpoint=30.0)
    _, off = step(state, params_off, 32.0, Exogenous(5.0), 60.0)
    _, on = step(
        replace(initial_state(params, 21.0, t_mass=23.0, t_water=24.0), last_setpoint=30.0),
        params,
        32.0,
        Exogenous(5.0),
        60.0,
    )
    assert first.running
    assert on.heat_w == pytest.approx(off.heat_w)
    assert on.elec_w == pytest.approx(off.elec_w * math.exp(0.5))


def test_inlet_capacity_term_and_outlet_term_stay_separate() -> None:
    """The inlet and outlet terms of the capacity are separate."""
    p = HeatPumpParams(k0=100.0, k_o=5.0, k_s=2.0, k_in=-1.0)
    assert hp.heat_per_hz(p, 4.0, 35.0) == pytest.approx(100.0 + 20.0 + 70.0)
    assert hp.heat_per_hz(p, 4.0, 35.0, inlet_c=30.0) == pytest.approx(160.0)

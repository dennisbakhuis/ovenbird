"""The plant: heat pump + hydronics + building, advanced in fixed steps.

:func:`step` is pure and deterministic: ``step(state, params, setpoint, exogenous, dt)``
returns the next :class:`PlantState` and an :class:`Observation` shaped like the
HeishaMon readings at the end of the step, so a simulated HeishaMon can publish them.

Per step, in order:

1. the pump looks at its readings at the start of the step (inlet/outlet from the loop
   mean and the current heat) and applies the switching rule and defrost logic of
   :mod:`ovenbird_sim.model.heatpump`;
2. the delivered heat follows from the compressor frequency and the capacity map
   (or is the defrost draw, or zero when idle) and is held over the step;
3. the thermal network of :mod:`ovenbird_sim.model.building` is integrated exactly;
   the return temperature enters the inlet sensor's delay line (``return_delay_s``);
4. electrical input follows from the COP map with its warm-up term while running
   (the idle draw otherwise); counters are updated.

The water setpoint is the integer the controller writes (Main_Target_Temp). The loop
flow is the running or idle flow of the parameters (the controller's duty switching).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

from ovenbird_sim.model import heatpump as hp
from ovenbird_sim.model.building import BuildingParams, discretise

KELVIN_OFFSET = 273.15


@dataclass(frozen=True, slots=True)
class PlantParams:
    """All plant parameters.

    Parameters
    ----------
    heat_pump
        Heat-pump layer.
    building
        Thermal network.
    """

    heat_pump: hp.HeatPumpParams
    building: BuildingParams


@dataclass(frozen=True, slots=True)
class Exogenous:
    """Inputs the controller does not choose, held over one step.

    Parameters
    ----------
    outside_c
        True outside air temperature.
    solar_w_m2
        Global horizontal irradiance.
    local_hour
        Local clock hour in ``[0, 24)`` for the internal-gains profile.
    rh_pct
        Outside relative humidity (frost build-up; ``NaN``: the parameters' default).
    extra_heat_w
        Heat from a source the controller does not know (a wood stove, a party) released
        into the air node, in W, on top of the internal-gains profile.
    """

    outside_c: float
    solar_w_m2: float = 0.0
    local_hour: float = 12.0
    rh_pct: float = math.nan
    extra_heat_w: float = 0.0


@dataclass(frozen=True, slots=True)
class PlantState:
    """Complete plant state.

    Parameters
    ----------
    t_water, t_mass, t_air
        Node temperatures in degC.
    running
        Compressor on (including a defrost in progress).
    hz
        Compressor frequency of the heating controller (0 when stopped).
    heat_w
        Heat delivered to the loop during the last step.
    defrost_left_s
        Remaining defrost time (0 when not defrosting).
    frost
        Frost build-up; a defrost starts at 1.
    stop_timer_s, start_timer_s
        Time the stop / steady-start condition has held.
    off_s, run_s
        Time since the last stop / heating start.
    since_restart_s
        Running time since the last start or defrost end (the start phase).
    returns
        Recent return temperatures, oldest first (the inlet sensor reads the oldest;
        empty without a return delay).
    last_setpoint
        Setpoint seen at the previous step (``None`` before the first step).
    starts, defrosts
        Counters (defrost restarts are not starts).
    steady_starts
        Starts by the steady rule (the others followed a setpoint change).
    heat_j, elec_j
        Cumulative heat delivered and electricity used in J.
    time_s
        Simulated seconds since the initial state.
    """

    t_water: float
    t_mass: float
    t_air: float
    running: bool = False
    hz: float = 0.0
    heat_w: float = 0.0
    defrost_left_s: float = 0.0
    frost: float = 0.0
    stop_timer_s: float = 0.0
    start_timer_s: float = 0.0
    off_s: float = math.inf
    run_s: float = 0.0
    since_restart_s: float = 0.0
    returns: tuple[float, ...] = ()
    last_setpoint: float | None = None
    starts: int = 0
    defrosts: int = 0
    steady_starts: int = 0
    heat_j: float = 0.0
    elec_j: float = 0.0
    time_s: float = 0.0

    @property
    def defrosting(self) -> bool:
        """Whether a defrost is in progress."""
        return self.defrost_left_s > 0


@dataclass(frozen=True, slots=True)
class Observation:
    """What the plant reports at the end of a step, in HeishaMon's units and resolution.

    Parameters
    ----------
    outside_temp
        Outdoor-unit sensor, integer degC (biased while running).
    inlet_temp, outlet_temp
        Loop return and supply in 0.25 K steps.
    target_temp
        Applied water setpoint (integer).
    compressor_freq
        Compressor frequency in Hz (integer).
    pump_flow
        Loop flow in l/min.
    heat_power_production, heat_power_consumption
        Heat output and electrical input in W (integers).
    defrosting_state, threeway_valve_state
        0/1 flags (the valve never switches to DHW in this model).
    room_temp
        Room sensor in 0.1 K steps.
    heat_w, elec_w
        Unrounded heat and electrical power.
    """

    outside_temp: int
    inlet_temp: float
    outlet_temp: float
    target_temp: int
    compressor_freq: int
    pump_flow: float
    heat_power_production: int
    heat_power_consumption: int
    defrosting_state: int
    threeway_valve_state: int
    room_temp: float
    heat_w: float
    elec_w: float

    def main_topics(self) -> dict[str, str]:
        """Payloads keyed by HeishaMon ``main/*`` topic name."""
        return {
            "Outside_Temp": str(self.outside_temp),
            "Main_Inlet_Temp": f"{self.inlet_temp:.2f}",
            "Main_Outlet_Temp": f"{self.outlet_temp:.2f}",
            "Main_Target_Temp": str(self.target_temp),
            "Z1_Water_Target_Temp": str(self.target_temp),
            "Compressor_Freq": str(self.compressor_freq),
            "Pump_Flow": f"{self.pump_flow:.2f}",
            "Heat_Power_Production": str(self.heat_power_production),
            "Heat_Power_Consumption": str(self.heat_power_consumption),
            "Defrosting_State": str(self.defrosting_state),
            "ThreeWay_Valve_State": str(self.threeway_valve_state),
        }


def initial_state(
    params: PlantParams,
    t_air: float,
    *,
    t_mass: float | None = None,
    t_water: float | None = None,
) -> PlantState:
    """Return an idle plant state.

    Parameters
    ----------
    params
        Plant parameters (unused today; kept for parameter-dependent defaults).
    t_air
        Room temperature.
    t_mass, t_water
        Mass and loop temperatures; default to ``t_air``.

    Returns
    -------
    PlantState
        Idle state with empty counters.
    """
    del params
    return PlantState(
        t_water=t_air if t_water is None else t_water,
        t_mass=t_air if t_mass is None else t_mass,
        t_air=t_air,
    )


def loop_temperatures(params: PlantParams, state: PlantState) -> tuple[float, float]:
    """Inlet and outlet *sensor* readings implied by the loop mean and the current heat.

    The loop mean sits halfway between the true inlet and outlet; the outlet sensor
    reads ``spread_offset_k`` high (the calibrated zero-heat spread), and the pump's own
    decisions use these sensor readings, as the thresholds were measured on them.
    """
    return _readings(params.heat_pump, state)


def _switch(
    p: hp.HeatPumpParams,
    s: PlantState,
    setpoint: float,
    outside_c: float,
    dt: float,
    rh_pct: float = math.nan,
) -> PlantState:
    """Return the state after a step: defrost progress, compressor stop or start.

    Parameters
    ----------
    p
        Heat pump parameters.
    s
        Plant state before the step.
    setpoint
        Water setpoint (degC) the pump regulates to.
    outside_c
        Outside temperature (degC).
    dt
        Step length (s).
    rh_pct
        Outside relative humidity (%); NaN uses the default frosting humidity.
    """
    inlet, outlet = _readings(p, s)
    changed = s.last_setpoint is not None and setpoint != s.last_setpoint
    if s.defrosting:
        left = s.defrost_left_s - dt
        if left <= 0:
            return replace(
                s,
                defrost_left_s=0.0,
                frost=0.0,
                heat_w=0.0,
                hz=_start_frequency(p, outside_c),
                run_s=s.run_s + dt,
                since_restart_s=0.0,
            )
        return replace(s, defrost_left_s=left, run_s=s.run_s + dt)
    if s.running:
        stop_timer = s.stop_timer_s + dt if outlet >= setpoint + p.stop_margin_k else 0.0
        if stop_timer >= p.stop_delay_s:
            return replace(
                s,
                running=False,
                hz=0.0,
                heat_w=0.0,
                stop_timer_s=0.0,
                start_timer_s=0.0,
                off_s=0.0,
            )
        frost = s.frost + hp.frost_rate_per_s(p, outside_c, s.hz, rh_pct) * dt
        if frost >= 1.0:
            return replace(
                s,
                defrost_left_s=p.defrost_duration_s,
                frost=frost,
                stop_timer_s=0.0,
                defrosts=s.defrosts + 1,
                run_s=s.run_s + dt,
            )
        reading = hp.sensor_outside(p, outside_c, running=True)
        floor = hp.min_frequency(p, reading)
        restart = s.since_restart_s + dt
        if s.since_restart_s < p.start_phase_s:
            hz = s.hz if restart < p.start_phase_s else hp.resume_frequency(p, reading, floor)
        else:
            hz = hp.next_frequency(p, s.hz, setpoint, outlet, dt, floor)
        return replace(
            s,
            hz=hz,
            stop_timer_s=stop_timer,
            frost=frost,
            run_s=s.run_s + dt,
            since_restart_s=restart,
        )
    off = s.off_s + dt
    steady = inlet <= setpoint - p.start_steady_margin_k
    start_timer = s.start_timer_s + dt if steady and not changed else 0.0
    allowed = off >= p.min_off_s
    trigger = changed and inlet <= setpoint - p.start_trigger_margin_k
    if allowed and (trigger or start_timer >= p.start_steady_delay_s):
        return replace(
            s,
            running=True,
            hz=_start_frequency(p, outside_c),
            heat_w=0.0,
            run_s=0.0,
            since_restart_s=0.0,
            off_s=off,
            start_timer_s=0.0,
            stop_timer_s=0.0,
            starts=s.starts + 1,
            steady_starts=s.steady_starts + (0 if trigger else 1),
        )
    return replace(s, off_s=off, start_timer_s=start_timer)


def _start_frequency(p: hp.HeatPumpParams, outside_c: float) -> float:
    """Return the compressor start frequency (Hz) at ``outside_c``, at least the minimum."""
    return max(p.hz_start, hp.min_frequency(p, hp.sensor_outside(p, outside_c, running=True)))


def _readings(p: hp.HeatPumpParams, s: PlantState) -> tuple[float, float]:
    """Return the inlet and outlet water temperatures (degC) implied by heat and flow."""
    flow = p.flow_running_lpm if s.running else p.flow_idle_lpm
    half = s.heat_w / (2.0 * hp.mass_flow_cp(flow))
    inlet = s.returns[0] if s.returns else s.t_water - half
    return inlet, inlet + 2.0 * half + p.spread_offset_k


def _returns(p: hp.HeatPumpParams, s: PlantState, dt: float) -> tuple[float, ...]:
    """Return the return temperatures extended by the current one, cut to the return delay."""
    if p.return_delay_s <= 0:
        return ()
    flow = p.flow_running_lpm if s.running else p.flow_idle_lpm
    current = s.t_water - s.heat_w / (2.0 * hp.mass_flow_cp(flow))
    keep = round(p.return_delay_s / dt) + 1
    return (*s.returns, current)[-keep:]


def _heat(p: hp.HeatPumpParams, s: PlantState, outside_c: float) -> float:
    """Return ``value`` rounded to the nearest multiple of ``step``."""
    if not s.running:
        return 0.0
    if s.defrosting:
        return p.defrost_heat_w
    inlet, outlet = _readings(p, s)
    return hp.heat_output(p, outside_c, outlet, s.hz, s.run_s, inlet)


def _quantise(value: float, step: float) -> float:
    """Round ``value`` to the nearest multiple of ``step``."""
    return round(value / step) * step


def step(
    state: PlantState,
    params: PlantParams,
    setpoint: float,
    exogenous: Exogenous,
    dt: float,
) -> tuple[PlantState, Observation]:
    """Advance the plant by ``dt`` seconds.

    Parameters
    ----------
    state
        Current state.
    params
        Plant parameters.
    setpoint
        Water setpoint in degC applied by the pump (an integer in practice).
    exogenous
        Weather and time of day, held over the step.
    dt
        Step in seconds (60 for the simulator).

    Returns
    -------
    state, observation
        Next state and the HeishaMon-like readings at the end of the step.

    Raises
    ------
    ValueError
        When ``dt`` is not positive or an input is not finite.
    """
    if not dt > 0:
        raise ValueError("dt must be positive")
    if not all(map(math.isfinite, (setpoint, exogenous.outside_c, exogenous.solar_w_m2))):
        raise ValueError("setpoint and exogenous inputs must be finite")
    p = params.heat_pump
    t_o = exogenous.outside_c
    switched = _switch(p, state, setpoint, t_o, dt, exogenous.rh_pct)
    heat = _heat(p, switched, t_o)
    q_int = params.building.internal_gain(exogenous.local_hour) + max(exogenous.extra_heat_w, 0.0)
    ad, bd = discretise(params.building, dt)
    x = np.array([switched.t_water, switched.t_mass, switched.t_air])
    u = np.array([heat, t_o, max(exogenous.solar_w_m2, 0.0), q_int])
    x_next = ad @ x + bd @ u
    after = replace(switched, heat_w=heat)
    returns = _returns(p, replace(after, t_water=float(x_next[0])), dt)
    inlet, outlet = _readings(p, replace(after, t_water=float(x_next[0]), returns=returns))
    if after.running and after.defrosting:
        hz, elec = p.hz_min * 2.0, p.defrost_elec_w
    elif after.running:
        hz = after.hz
        elec = heat / hp.cop(p, t_o, outlet, hz, after.run_s)
    else:
        hz, elec = 0.0, p.circulation_w
    new = replace(
        after,
        t_water=float(x_next[0]),
        returns=returns,
        t_mass=float(x_next[1]),
        t_air=float(x_next[2]),
        last_setpoint=setpoint,
        heat_j=after.heat_j + heat * dt,
        elec_j=after.elec_j + elec * dt,
        time_s=after.time_s + dt,
    )
    flow = p.flow_running_lpm if new.running else p.flow_idle_lpm
    observation = Observation(
        outside_temp=hp.sensor_outside(p, t_o, new.running),
        inlet_temp=_quantise(inlet, 0.25),
        outlet_temp=_quantise(outlet, 0.25),
        target_temp=round(setpoint),
        compressor_freq=round(hz),
        pump_flow=round(flow, 2),
        heat_power_production=max(round(heat), 0),
        heat_power_consumption=round(elec),
        defrosting_state=int(new.defrosting),
        threeway_valve_state=0,
        room_temp=_quantise(new.t_air, 0.1),
        heat_w=heat,
        elec_w=elec,
    )
    return new, observation

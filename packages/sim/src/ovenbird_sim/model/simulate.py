"""Drive the plant over recorded inputs (setpoint and weather series)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ovenbird_sim.data.series import FloatArray
from ovenbird_sim.model.plant import Exogenous, PlantParams, PlantState, loop_temperatures, step


@dataclass(frozen=True, slots=True)
class Trajectory:
    """Per-step plant outputs of a simulation run (end-of-step values).

    Parameters
    ----------
    t_air, t_water, t_mass
        Node temperatures.
    inlet, outlet
        Loop sensor readings (unquantised; the outlet includes the sensor offset).
    heat_w, elec_w
        Heat into the loop and electrical input.
    hz
        Reported compressor frequency.
    running, defrosting
        Compressor state flags (as 0/1).
    starts
        Cumulative start counter.
    final
        State after the last step.
    """

    t_air: FloatArray
    t_water: FloatArray
    t_mass: FloatArray
    inlet: FloatArray
    outlet: FloatArray
    heat_w: FloatArray
    elec_w: FloatArray
    hz: FloatArray
    running: FloatArray
    defrosting: FloatArray
    starts: FloatArray
    final: PlantState


def run(
    params: PlantParams,
    state: PlantState,
    setpoint: FloatArray,
    outside_c: FloatArray,
    solar_w_m2: FloatArray,
    local_hour: FloatArray,
    dt: float,
    rh_pct: FloatArray | None = None,
) -> Trajectory:
    """Simulate the plant step by step.

    Parameters
    ----------
    params
        Plant parameters.
    state
        Initial state.
    setpoint, outside_c, solar_w_m2, local_hour
        Inputs per step (equal lengths, finite).
    dt
        Step in seconds.
    rh_pct
        Outside relative humidity per step (``None``: the parameters' default).

    Returns
    -------
    Trajectory
        Outputs per step.
    """
    n = setpoint.size
    cols = {k: np.empty(n) for k in Trajectory.__dataclass_fields__ if k != "final"}
    s = state
    rh = np.full(n, np.nan) if rh_pct is None else rh_pct
    for k in range(n):
        exo = Exogenous(
            float(outside_c[k]), float(solar_w_m2[k]), float(local_hour[k]), float(rh[k])
        )
        s, obs = step(s, params, float(setpoint[k]), exo, dt)
        cols["t_air"][k] = s.t_air
        cols["t_water"][k] = s.t_water
        cols["t_mass"][k] = s.t_mass
        cols["inlet"][k], cols["outlet"][k] = loop_temperatures(params, s)
        cols["heat_w"][k] = obs.heat_w
        cols["elec_w"][k] = obs.elec_w
        cols["hz"][k] = obs.compressor_freq
        cols["running"][k] = float(s.running)
        cols["defrosting"][k] = float(s.defrosting)
        cols["starts"][k] = float(s.starts)
    return Trajectory(final=s, **cols)

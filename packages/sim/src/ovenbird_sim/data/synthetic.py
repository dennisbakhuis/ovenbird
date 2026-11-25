"""Synthetic recordings: simulate the plant and lay the result out as a :class:`Dataset`.

Used by the recovery tests (simulate with known parameters, fit, compare) and handy
for trying the identification without data. Values are end-of-step readings, the
heat input is exact, and optional Gaussian noise can be added to the room and loop
temperatures.
"""

from __future__ import annotations

import numpy as np

from ovenbird_sim.data.dataset import FLAGS, Dataset, OffsetCalibration
from ovenbird_sim.data.grid import TimeGrid
from ovenbird_sim.data.series import FloatArray
from ovenbird_sim.model import heatpump as hp
from ovenbird_sim.model.plant import PlantParams, PlantState
from ovenbird_sim.model.simulate import run


def simulated_dataset(
    params: PlantParams,
    state: PlantState,
    setpoint: FloatArray,
    outside: FloatArray,
    ghi: FloatArray,
    *,
    start: float = 1_790_000_000.0,
    dt: float = 60.0,
    room_noise_k: float = 0.0,
    loop_noise_k: float = 0.0,
    seed: int = 0,
) -> Dataset:
    """Simulate and return the run as a dataset with the real dataset's column names.

    Parameters
    ----------
    params
        True plant parameters.
    state
        Initial state.
    setpoint, outside, ghi
        Inputs per step.
    start
        Unix time of the first step (local hour is taken as UTC hour).
    dt
        Step in seconds.
    room_noise_k, loop_noise_k
        Standard deviation of added measurement noise.
    seed
        Noise seed.

    Returns
    -------
    Dataset
        Columns ``heat_w``, ``hz``, ``inlet``, ``outlet``, ``flow``, ``target``,
        ``outside``, ``outside_hp``, ``outside_wx``, ``ghi``, ``local_hour``, ``room``,
        ``room_living``, ``house_mean``, ``elec_hp_est_w``, ``heat_hp_est_w``,
        ``compressor_frac``, ``defrost_frac`` and all flags.
    """
    n = setpoint.size
    grid = TimeGrid(start, dt, n)
    hour = (grid.edges % 86400.0) / 3600.0
    traj = run(params, state, setpoint, outside, ghi, hour, dt)
    p = params.heat_pump
    rng = np.random.default_rng(seed)
    room = traj.t_air + rng.normal(0.0, room_noise_k, n) if room_noise_k > 0 else traj.t_air.copy()
    noise_in = rng.normal(0.0, loop_noise_k, n) if loop_noise_k > 0 else np.zeros(n)
    noise_out = rng.normal(0.0, loop_noise_k, n) if loop_noise_k > 0 else np.zeros(n)
    running = traj.running > 0.5
    sensor = np.array(
        [hp.sensor_outside(p, float(t), bool(r)) for t, r in zip(outside, running, strict=True)],
        dtype=np.float64,
    )
    columns: dict[str, FloatArray] = {
        "heat_w": traj.heat_w.copy(),
        "hz": traj.hz.copy(),
        "inlet": traj.inlet + noise_in,
        "outlet": traj.outlet + noise_out,
        "flow": np.where(running, p.flow_running_lpm, p.flow_idle_lpm),
        "target": setpoint.astype(np.float64).copy(),
        "outside": outside.astype(np.float64).copy(),
        "outside_wx": outside.astype(np.float64).copy(),
        "outside_hp": sensor,
        "ghi": ghi.astype(np.float64).copy(),
        "local_hour": hour,
        "room": room,
        "room_living": room.copy(),
        "house_mean": room.copy(),
        "elec_hp_est_w": traj.elec_w.copy(),
        "heat_hp_est_w": np.maximum(traj.heat_w, 0.0),
        "compressor_frac": running.astype(np.float64),
        "defrost_frac": traj.defrosting.copy(),
    }
    flags = {name: np.zeros(n, dtype=np.bool_) for name in FLAGS}
    flags["defrost"] = traj.defrosting > 0.5
    flags["compressor_on"] = running
    calibration = OffsetCalibration(p.spread_offset_k, p.spread_offset_k, 0.0, 0, 0.0)
    return Dataset(grid, columns, flags, calibration, {"source": "synthetic"})

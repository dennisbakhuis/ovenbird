"""Thermal network of the emitters and the building (three linear nodes).

Nodes (temperatures in degC, capacities in J/K, conductances in W/K):

``water``
    the heating loop (water, radiator iron, pipes) at its mean temperature
    ``(inlet + outlet) / 2``; receives the heat pump's heat ``Q``.
``mass``
    floor screed and the structure coupled to it.
``air``
    room air together with the interior mass it equilibrates with within minutes
    (furniture, inner walls); observed by the room sensor. Fits on real data put most
    of the building's capacity here.

Energy balances::

    C_w dT_w/dt = Q - H_wm (T_w - T_m) - H_wa (T_w - T_a)
    C_m dT_m/dt = H_wm (T_w - T_m) - H_ma (T_m - T_a) + f_m A_sol I
    C_a dT_a/dt = H_wa (T_w - T_a) + H_ma (T_m - T_a) - H_ao (T_a - T_o)
                  + (1 - f_m) A_sol I + Q_int(h)

``H_wm`` is the floor loop (water to screed), ``H_wa`` the radiators (water to air),
``H_ao`` the whole envelope including ventilation, ``A_sol`` the solar aperture applied
to global horizontal irradiance ``I`` and ``Q_int(h) = q0 (1 + m cos(2 pi (h - h_peak) /
24))`` the internal gains over the local hour ``h``; with ``0 <= m <= 1`` they are never
negative.

With ``Q``, ``T_o``, ``I`` and ``Q_int`` held over a step the system is linear and
time-invariant, so :func:`discretise` integrates it exactly (zero-order hold, matrix
exponential of the augmented system) and caches the result per parameter set and step.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from functools import lru_cache

import numpy as np
from numpy.typing import NDArray
from scipy.linalg import expm

N_STATES = 3
N_INPUTS = 4
SECONDS_PER_HOUR = 3600.0
J_PER_KWH = 3.6e6


@dataclass(frozen=True, slots=True)
class BuildingParams:
    """Parameters of the water/mass/air network.

    Parameters
    ----------
    c_water, c_mass, c_air
        Heat capacities in J/K.
    h_water_mass, h_water_air, h_mass_air, h_air_out
        Conductances in W/K.
    solar_aperture_m2
        Effective aperture applied to global horizontal irradiance.
    solar_mass_fraction
        Share of solar gain absorbed by the mass node.
    q_int_w
        Mean internal gains in W.
    q_int_modulation
        Relative daily swing of the internal gains, within ``[0, 1]``.
    q_int_peak_hour
        Local hour of the internal-gains peak.
    """

    c_water: float = 2.5e6
    c_mass: float = 4.0e7
    c_air: float = 1.0e7
    h_water_mass: float = 400.0
    h_water_air: float = 150.0
    h_mass_air: float = 800.0
    h_air_out: float = 200.0
    solar_aperture_m2: float = 3.0
    solar_mass_fraction: float = 0.5
    q_int_w: float = 300.0
    q_int_modulation: float = 0.0
    q_int_peak_hour: float = 19.0

    def __post_init__(self) -> None:
        """Validate physical ranges."""
        for name in ("c_water", "c_mass", "c_air"):
            if not getattr(self, name) > 0:
                raise ValueError(f"{name} must be positive")
        for name in ("h_water_mass", "h_water_air", "h_mass_air", "h_air_out", "solar_aperture_m2"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if not 0.0 <= self.solar_mass_fraction <= 1.0:
            raise ValueError("solar_mass_fraction must be within [0, 1]")
        if self.q_int_w < 0 or not 0.0 <= self.q_int_modulation <= 1.0:
            raise ValueError("internal gains must be non-negative with modulation in [0, 1]")

    def replace(self, **changes: float) -> BuildingParams:
        """Return a copy with some fields changed."""
        values = {f.name: getattr(self, f.name) for f in fields(self)}
        values.update(changes)
        return BuildingParams(**values)

    @property
    def time_constant_h(self) -> float:
        """Slowest time constant of the network with the loop idle, in hours."""
        a, _ = continuous(self)
        eig = np.linalg.eigvals(a)
        slow = float(np.min(np.abs(eig.real)))
        return 1.0 / slow / SECONDS_PER_HOUR if slow > 0 else math.inf

    def internal_gain(self, local_hour: float) -> float:
        """Return the internal gains in W at a local hour of day."""
        angle = 2.0 * math.pi * (local_hour - self.q_int_peak_hour) / 24.0
        return self.q_int_w * (1.0 + self.q_int_modulation * math.cos(angle))


def continuous(p: BuildingParams) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Continuous-time ``A`` (3x3) and ``B`` (3x4) for inputs ``[Q, T_o, I, Q_int]``.

    Parameters
    ----------
    p
        Network parameters.

    Returns
    -------
    a, b
        State and input matrices of ``dx/dt = A x + B u`` with ``x = [T_w, T_m, T_a]``.
    """
    cw, cm, ca = p.c_water, p.c_mass, p.c_air
    hwm, hwa, hma, hao = p.h_water_mass, p.h_water_air, p.h_mass_air, p.h_air_out
    fm = p.solar_mass_fraction
    a = np.array(
        [
            [-(hwm + hwa) / cw, hwm / cw, hwa / cw],
            [hwm / cm, -(hwm + hma) / cm, hma / cm],
            [hwa / ca, hma / ca, -(hwa + hma + hao) / ca],
        ]
    )
    b = np.array(
        [
            [1.0 / cw, 0.0, 0.0, 0.0],
            [0.0, 0.0, fm * p.solar_aperture_m2 / cm, 0.0],
            [0.0, hao / ca, (1.0 - fm) * p.solar_aperture_m2 / ca, 1.0 / ca],
        ]
    )
    return a, b


@lru_cache(maxsize=256)
def discretise(p: BuildingParams, dt: float) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Exact zero-order-hold discretisation ``x+ = Ad x + Bd u`` over ``dt`` seconds.

    Parameters
    ----------
    p
        Network parameters.
    dt
        Step in seconds.

    Returns
    -------
    ad, bd
        Discrete state (3x3) and input (3x4) matrices (read-only).
    """
    a, b = continuous(p)
    m = np.zeros((N_STATES + N_INPUTS, N_STATES + N_INPUTS))
    m[:N_STATES, :N_STATES] = a
    m[:N_STATES, N_STATES:] = b
    e = expm(m * dt)
    ad = np.ascontiguousarray(e[:N_STATES, :N_STATES])
    bd = np.ascontiguousarray(e[:N_STATES, N_STATES:])
    ad.setflags(write=False)
    bd.setflags(write=False)
    return ad, bd


def stored_energy_j(p: BuildingParams, t_water: float, t_mass: float, t_air: float) -> float:
    """Energy stored relative to 0 degC in J (for balance checks)."""
    return p.c_water * t_water + p.c_mass * t_mass + p.c_air * t_air


def simulate_batch(
    p: BuildingParams,
    dt: float,
    x0: NDArray[np.float64],
    u: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Free-run many windows at once with known inputs.

    Parameters
    ----------
    p
        Network parameters.
    dt
        Step in seconds.
    x0
        Initial states, shape ``(n_windows, 3)``.
    u
        Inputs ``[Q, T_o, I, Q_int]`` per step, shape ``(n_windows, n_steps, 4)``.

    Returns
    -------
    NDArray
        States at the start of every step and after the last, shape
        ``(n_windows, n_steps + 1, 3)``.
    """
    ad, bd = discretise(p, dt)
    n_win, n_steps, _ = u.shape
    forced = u @ bd.T
    out = np.empty((n_win, n_steps + 1, N_STATES))
    x = np.array(x0, dtype=np.float64)
    out[:, 0] = x
    adt = ad.T
    for k in range(n_steps):
        x = x @ adt + forced[:, k]
        out[:, k + 1] = x
    return out

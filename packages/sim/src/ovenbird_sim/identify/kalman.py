"""Kalman filter for the linear water/mass/air network.

Used to estimate the unmeasured mass temperature (and to smooth the measured nodes)
at the origin of every validation forecast. The network is discretised exactly
(:func:`ovenbird_sim.model.building.discretise`), so this is the discrete form of a
continuous-discrete filter with piecewise-constant inputs. Process noise is diagonal
per step; observations are the loop mean and the room temperature, either of which
may be missing (``NaN``) at a step.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from ovenbird_sim.data.series import FloatArray
from ovenbird_sim.model.building import BuildingParams, discretise


@dataclass(frozen=True, slots=True)
class KalmanNoise:
    """Noise levels of the filter.

    Parameters
    ----------
    process_k
        Per-step process noise standard deviation of ``[T_w, T_m, T_a]``.
    measurement_k
        Measurement noise standard deviation of ``[loop mean, room]``.
    """

    process_k: tuple[float, float, float] = (0.3, 0.02, 0.03)
    measurement_k: tuple[float, float] = (0.3, 0.1)


DEFAULT_NOISE = KalmanNoise()


def filter_states(
    p: BuildingParams,
    dt: float,
    u: NDArray[np.float64],
    y_water: FloatArray,
    y_room: FloatArray,
    x0: FloatArray,
    noise: KalmanNoise = DEFAULT_NOISE,
) -> NDArray[np.float64]:
    """Return the filtered state at every sample.

    Parameters
    ----------
    p
        Network parameters.
    dt
        Step in seconds.
    u
        Inputs ``[Q, T_o, I, Q_int]`` per step, shape ``(n, 4)``; step ``k`` moves the
        state from sample ``k`` to sample ``k + 1``.
    y_water, y_room
        Observations per sample, shape ``(n + 1,)``.
    x0
        Initial state guess.
    noise
        Noise levels.

    Returns
    -------
    NDArray
        Filtered states, shape ``(n + 1, 3)``.
    """
    ad, bd = discretise(p, dt)
    q = np.diag(np.square(noise.process_k))
    r_full = np.square(noise.measurement_k)
    h_full = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    x = np.array(x0, dtype=np.float64)
    cov = np.diag([1.0, 4.0, 1.0])
    n = u.shape[0]
    out = np.empty((n + 1, 3))
    ys = np.column_stack([y_water, y_room])
    for k in range(n + 1):
        y = ys[k]
        ok = np.isfinite(y)
        if ok.any():
            h = h_full[ok]
            s = h @ cov @ h.T + np.diag(r_full[ok])
            gain = cov @ h.T @ np.linalg.inv(s)
            x = x + gain @ (y[ok] - h @ x)
            cov = (np.eye(3) - gain @ h) @ cov
        out[k] = x
        if k < n:
            x = ad @ x + bd @ u[k]
            cov = ad @ cov @ ad.T + q
    return out

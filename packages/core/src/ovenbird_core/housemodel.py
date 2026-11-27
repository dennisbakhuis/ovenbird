"""Three-node RC model of the house in pure Python (what-if and heat-balance maths).

The learner (``ovenbird_sim.learn``) fits the model with numpy and scipy; the service
only needs to *use* it, so this module repeats the physics with the standard library
alone. Nodes (temperatures in degC, capacities in J/K, conductances in W/K; the
field names are the learner's, the labels what the app shows):

``water`` (loop)
    the heating loop at its mean temperature; receives the heat ``Q`` the pump delivers;
``mass`` (emitter)
    the floor loop and screed, the fast node (a time constant of about an hour);
``air`` (building)
    the room air with the bulk of the building's heat capacity, the slow node (days);
    observed by the room sensor.

The learner fits a chain (water to mass to air to outside) and holds the direct
water-to-air conductance, the solar share into the mass and the daily swing of the
internal gains (``h_water_air`` 5 W/K, ``solar_mass_fraction`` 0, ``q_int_modulation``
0); a model file with other values is used as it is, the maths here are the general
network.

Energy balances::

    C_w dT_w/dt = Q - H_wm (T_w - T_m) - H_wa (T_w - T_a)
    C_m dT_m/dt = H_wm (T_w - T_m) - H_ma (T_m - T_a) + f_m A_sol I
    C_a dT_a/dt = H_wa (T_w - T_a) + H_ma (T_m - T_a) - H_ao (T_a - T_o)
                  + (1 - f_m) A_sol I + Q_int

with the inputs ``[Q, T_o, I, Q_int]`` (heat into the loop, outside temperature, global
horizontal irradiance, internal gains). ``H_ao`` is the heat-loss coefficient (UA).

:meth:`HouseModel.discretise` integrates exactly over a step for inputs held constant
(zero-order hold): the matrix exponential of the augmented matrix ``[[A, B], [0, 0]]``
by scaling and squaring with a Taylor series. The exact discrete model conserves
energy: ``Ad`` is non-negative and every row of ``[Ad | outside column of Bd]`` sums to
one, which :class:`DiscreteHouse` checks on construction.

The numbers of :data:`DEFAULTS` repeat the learner's prior means with the values its
structure holds, and a test in ``packages/sim/tests`` keeps them equal.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from functools import lru_cache
from types import MappingProxyType
from typing import Final

from ovenbird_core.derived import WATER_CP_J_PER_KG_K, WATER_DENSITY_KG_PER_L
from ovenbird_core.housefacts import FactEstimate

type Matrix = list[list[float]]
type Rows = tuple[tuple[float, ...], ...]

N_STATES: Final = 3
N_INPUTS: Final = 4
SECONDS_PER_HOUR: Final = 3600.0
W_PER_LPM_K: Final = WATER_DENSITY_KG_PER_L * WATER_CP_J_PER_KG_K / 60.0
NOMINAL_FLOW_LPM: Final = 15.0
CONSERVATION_TOLERANCE: Final = 1e-9
NEGATIVE_TOLERANCE: Final = 1e-12
TAYLOR_TERMS: Final = 18
SCALED_NORM: Final = 0.5
MAX_STEP_S: Final = 86400.0
CAPACITY_RANGE: Final = (1e3, 1e11)
MAX_CONDUCTANCE: Final = 1e6
MAX_SOLAR_APERTURE_M2: Final = 1e3
MAX_INTERNAL_GAIN_W: Final = 1e5
DEFAULTS: Final[Mapping[str, float]] = MappingProxyType(
    {
        "c_water": 2.5e6,
        "c_mass": 4.0e7,
        "c_air": 1.0e7,
        "h_water_mass": 400.0,
        "h_water_air": 5.0,
        "h_mass_air": 800.0,
        "h_air_out": 200.0,
        "solar_aperture_m2": 3.0,
        "solar_mass_fraction": 0.0,
        "q_int_w": 300.0,
        "q_int_modulation": 0.0,
        "q_int_peak_hour": 19.0,
    }
)
REQUIRED: Final = (
    "c_water",
    "c_mass",
    "c_air",
    "h_water_mass",
    "h_water_air",
    "h_mass_air",
    "h_air_out",
)
CAPACITIES: Final = ("c_water", "c_mass", "c_air")
CONDUCTANCES: Final = ("h_water_mass", "h_water_air", "h_mass_air", "h_air_out")


def _finite_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


@dataclass(frozen=True, slots=True)
class SteadyState:
    """The steady state that holds a room temperature.

    Parameters
    ----------
    heat_w
        Heat the loop must deliver (never negative).
    loop_mean_c
        Mean water temperature of the loop.
    mass_c
        Temperature of the mass node.
    """

    heat_w: float
    loop_mean_c: float
    mass_c: float


@dataclass(frozen=True, slots=True)
class HouseModel:
    """Parameters of the water/mass/air network.

    Parameters
    ----------
    c_water, c_mass, c_air
        Heat capacities in J/K (positive).
    h_water_mass, h_water_air, h_mass_air
        Conductances in W/K (non-negative).
    h_air_out
        Heat-loss coefficient (UA) in W/K, ventilation included (positive).
    solar_aperture_m2
        Effective aperture applied to global horizontal irradiance.
    solar_mass_fraction
        Share of the solar gain absorbed by the mass node, within ``[0, 1]``.
    q_int_w
        Mean internal gains in W.
    q_int_modulation
        Relative daily swing of the internal gains, within ``[0, 1]``.
    q_int_peak_hour
        Local hour of the internal-gains peak.
    """

    c_water: float = DEFAULTS["c_water"]
    c_mass: float = DEFAULTS["c_mass"]
    c_air: float = DEFAULTS["c_air"]
    h_water_mass: float = DEFAULTS["h_water_mass"]
    h_water_air: float = DEFAULTS["h_water_air"]
    h_mass_air: float = DEFAULTS["h_mass_air"]
    h_air_out: float = DEFAULTS["h_air_out"]
    solar_aperture_m2: float = DEFAULTS["solar_aperture_m2"]
    solar_mass_fraction: float = DEFAULTS["solar_mass_fraction"]
    q_int_w: float = DEFAULTS["q_int_w"]
    q_int_modulation: float = DEFAULTS["q_int_modulation"]
    q_int_peak_hour: float = DEFAULTS["q_int_peak_hour"]

    def __post_init__(self) -> None:
        """Validate every field; the error names the field."""
        for name in (f.name for f in fields(self)):
            _finite_number(name, getattr(self, name))
        for name in CAPACITIES:
            if not CAPACITY_RANGE[0] <= getattr(self, name) <= CAPACITY_RANGE[1]:
                raise ValueError(
                    f"{name} must be within {CAPACITY_RANGE[0]:g} and {CAPACITY_RANGE[1]:g} J/K"
                )
        for name in CONDUCTANCES:
            if getattr(self, name) < 0 or getattr(self, name) > MAX_CONDUCTANCE:
                raise ValueError(f"{name} must be within 0 and {MAX_CONDUCTANCE:g} W/K")
        if not self.h_air_out > 0:
            raise ValueError("h_air_out (the heat loss UA) must be positive")
        if not 0.0 <= self.solar_aperture_m2 <= MAX_SOLAR_APERTURE_M2:
            raise ValueError("solar_aperture_m2 must be within 0 and 1000")
        if not 0.0 <= self.solar_mass_fraction <= 1.0:
            raise ValueError("solar_mass_fraction must be within [0, 1]")
        if not 0.0 <= self.q_int_w <= MAX_INTERNAL_GAIN_W:
            raise ValueError("q_int_w must be within 0 and 100000 W")
        if not 0.0 <= self.q_int_modulation <= 1.0:
            raise ValueError("q_int_modulation must be within [0, 1]")

    @classmethod
    def from_json(cls, data: Mapping[str, object]) -> HouseModel:
        """Build a model from the building parameters a learner file holds.

        Capacities and conductances are required; the solar and internal-gain
        parameters fall back to :data:`DEFAULTS` when absent. Unknown keys are ignored.

        Parameters
        ----------
        data
            ``params.building`` of the learner's house file.

        Returns
        -------
        HouseModel
            The validated model.

        Raises
        ------
        ValueError
            Naming the field that is missing, not a finite number or out of range.
        """
        if not isinstance(data, Mapping):
            raise ValueError("building parameters must be an object")
        values: dict[str, float] = {}
        for name in (f.name for f in fields(cls)):
            if name not in data or data[name] is None:
                if name in REQUIRED:
                    raise ValueError(f"{name} is missing")
                continue
            values[name] = _finite_number(name, data[name])
        return cls(**values)

    def internal_gain_w(self, local_hour: float) -> float:
        """Return the internal gains in W at a local hour of day."""
        angle = 2.0 * math.pi * (local_hour - self.q_int_peak_hour) / 24.0
        return self.q_int_w * (1.0 + self.q_int_modulation * math.cos(angle))

    def free_heat_w(self, sun_wm2: float = 0.0, extra_air_w: float = 0.0) -> float:
        """Return the heat that reaches the house without the loop: sun, gains and extra."""
        return self.solar_aperture_m2 * sun_wm2 + self.q_int_w + extra_air_w

    def loss_w(self, room_c: float, outside_c: float) -> float:
        """Return the heat loss ``UA (room - outside)`` in W."""
        return self.h_air_out * (room_c - outside_c)

    def continuous(self) -> tuple[Matrix, Matrix]:
        """Return ``A`` (3x3) and ``B`` (3x4) of ``dx/dt = A x + B u``, ``x = [T_w, T_m, T_a]``."""
        cw, cm, ca = self.c_water, self.c_mass, self.c_air
        hwm, hwa, hma, hao = (
            self.h_water_mass,
            self.h_water_air,
            self.h_mass_air,
            self.h_air_out,
        )
        fm, aperture = self.solar_mass_fraction, self.solar_aperture_m2
        a = [
            [-(hwm + hwa) / cw, hwm / cw, hwa / cw],
            [hwm / cm, -(hwm + hma) / cm, hma / cm],
            [hwa / ca, hma / ca, -(hwa + hma + hao) / ca],
        ]
        b = [
            [1.0 / cw, 0.0, 0.0, 0.0],
            [0.0, 0.0, fm * aperture / cm, 0.0],
            [0.0, hao / ca, (1.0 - fm) * aperture / ca, 1.0 / ca],
        ]
        return a, b

    def discretise(self, dt_s: float) -> DiscreteHouse:
        """Return the exact zero-order-hold model over ``dt_s`` seconds.

        Raises
        ------
        ValueError
            For a step outside ``(0, 86400]`` s, or when the discrete model violates
            energy conservation.
        """
        return _discretise(self, float(dt_s))

    @property
    def time_constant_h(self) -> float:
        """Slowest time constant of the network with the loop idle, in hours.

        The generator is similar to a symmetric matrix (``C^-1/2 L C^-1/2`` with the
        conductance Laplacian ``L``), so its eigenvalues are real; the smallest rate
        comes from a Jacobi eigenvalue iteration. ``inf`` when a node is isolated.
        """
        cw, cm, ca = self.c_water, self.c_mass, self.c_air
        hwm, hwa, hma, hao = (
            self.h_water_mass,
            self.h_water_air,
            self.h_mass_air,
            self.h_air_out,
        )
        laplacian = [
            [hwm + hwa, -hwm, -hwa],
            [-hwm, hwm + hma, -hma],
            [-hwa, -hma, hwa + hma + hao],
        ]
        caps = (cw, cm, ca)
        sym = [
            [laplacian[i][j] / math.sqrt(caps[i] * caps[j]) for j in range(N_STATES)]
            for i in range(N_STATES)
        ]
        eig = _symmetric_eigenvalues(sym)
        slowest = min(abs(value) for value in eig)
        largest = max(abs(value) for value in eig)
        if slowest <= 1e-12 * largest:
            return math.inf
        return 1.0 / slowest / SECONDS_PER_HOUR

    def steady_state(
        self,
        room_c: float,
        outside_c: float,
        sun_wm2: float = 0.0,
        extra_air_w: float = 0.0,
    ) -> SteadyState:
        """Return the steady state that holds ``room_c``.

        The loop heat balances the loss: ``max(0, UA (room - outside) - sun - gains -
        extra)``. With the sun off and no extra heat this is the learner's curve
        proposal (loop mean ``room + Q / K``, ``K = H_wa + H_wm H_ma / (H_wm + H_ma)``).
        The sun's share into the mass lifts the loop a little (``H_wm f_m A I /
        (H_wm + H_ma)`` over ``K``). When no heat is needed the loop sits at the room
        temperature.

        Parameters
        ----------
        room_c
            Air temperature to hold.
        outside_c
            Outside temperature.
        sun_wm2
            Global horizontal irradiance.
        extra_air_w
            Other heat into the room (a wood stove).

        Returns
        -------
        SteadyState
            Heat the loop delivers, the loop mean temperature and the mass temperature.
        """
        hwm, hwa, hma = self.h_water_mass, self.h_water_air, self.h_mass_air
        sun_to_mass = self.solar_mass_fraction * self.solar_aperture_m2 * sun_wm2
        heat = max(
            0.0,
            self.loss_w(room_c, outside_c) - self.free_heat_w(sun_wm2, extra_air_w),
        )
        series = hwm + hma
        k = hwa + (hwm * hma / series if series > 0 else 0.0)
        if heat > 0 and k > 0:
            lift = (heat + (hwm * sun_to_mass / series if series > 0 else 0.0)) / k
            mass_lift = (hwm * lift + sun_to_mass) / series if series > 0 else 0.0
        else:
            lift = 0.0
            mass_lift = sun_to_mass / series if series > 0 else 0.0
        return SteadyState(heat, room_c + lift, room_c + mass_lift)

    def balance_outside_c(
        self, comfort_c: float, sun_wm2: float = 0.0, extra_air_w: float = 0.0
    ) -> float:
        """Return the outside temperature above which no heating is needed to hold comfort."""
        return comfort_c - self.free_heat_w(sun_wm2, extra_air_w) / self.h_air_out

    def free_drift(
        self,
        room_c: float,
        outside_c: float,
        sun_wm2: float,
        hours: float,
        step_s: float,
    ) -> list[float]:
        """Return the room temperature with the loop switched off.

        The house starts at the steady state that holds ``room_c`` (:meth:`steady_state`
        without extra heat); the loop heat is then zero while the sun and the mean
        internal gains continue.

        Parameters
        ----------
        room_c
            Room temperature at the start.
        outside_c
            Outside temperature (held).
        sun_wm2
            Irradiance (held).
        hours
            Length of the drift.
        step_s
            Output step.

        Returns
        -------
        list[float]
            The room temperature at the start and after every step
            (``round(hours * 3600 / step_s) + 1`` values).
        """
        start = self.steady_state(room_c, outside_c, sun_wm2)
        discrete = self.discretise(step_s)
        state: Sequence[float] = (start.loop_mean_c, start.mass_c, room_c)
        inputs = (0.0, outside_c, sun_wm2, self.q_int_w)
        out = [room_c]
        for _ in range(round(hours * SECONDS_PER_HOUR / step_s)):
            state = discrete.step(state, inputs)
            out.append(state[2])
        return out


@dataclass(frozen=True, slots=True)
class DiscreteHouse:
    """The exact discrete model ``x+ = Ad x + Bd u`` for inputs held over ``dt_s``.

    Parameters
    ----------
    dt_s
        Step in seconds.
    ad, bd
        State (3x3) and input (3x4) matrices as tuples of rows. Entries of ``Ad`` and
        ``Bd`` must be non-negative and every row of ``[Ad | outside column of Bd]``
        must sum to one within ``1e-9``.
    """

    dt_s: float
    ad: Rows
    bd: Rows

    def __post_init__(self) -> None:
        """Check non-negativity and energy conservation."""
        for name, matrix in (("Ad", self.ad), ("Bd", self.bd)):
            for row in matrix:
                if any(not math.isfinite(x) or x < -NEGATIVE_TOLERANCE for x in row):
                    raise ValueError(f"{name} has a negative or non-finite entry")
        for i, row in enumerate(self.ad):
            total = sum(row) + self.bd[i][1]
            if abs(total - 1.0) > CONSERVATION_TOLERANCE:
                raise ValueError(f"row {i} of the discrete model does not conserve energy")

    def step(self, state: Sequence[float], inputs: Sequence[float]) -> tuple[float, float, float]:
        """Advance ``[T_w, T_m, T_a]`` one step with the inputs ``[Q, T_o, I, Q_int]``."""
        out = [
            sum(a * x for a, x in zip(self.ad[i], state, strict=True))
            + sum(b * u for b, u in zip(self.bd[i], inputs, strict=True))
            for i in range(N_STATES)
        ]
        return out[0], out[1], out[2]


@lru_cache(maxsize=64)
def _discretise(model: HouseModel, dt_s: float) -> DiscreteHouse:
    if not 0.0 < dt_s <= MAX_STEP_S:
        raise ValueError("the step must be within 0 and 86400 s")
    a, b = model.continuous()
    size = N_STATES + N_INPUTS
    augmented = [[0.0] * size for _ in range(size)]
    for i in range(N_STATES):
        for j in range(N_STATES):
            augmented[i][j] = a[i][j] * dt_s
        for j in range(N_INPUTS):
            augmented[i][N_STATES + j] = b[i][j] * dt_s
    e = matrix_exponential(augmented)
    ad = tuple(tuple(_snap(x) for x in e[i][:N_STATES]) for i in range(N_STATES))
    bd = tuple(tuple(_snap(x) for x in e[i][N_STATES:]) for i in range(N_STATES))
    return DiscreteHouse(dt_s, ad, bd)


def _snap(x: float) -> float:
    return 0.0 if -NEGATIVE_TOLERANCE <= x < 0.0 else x


def _multiply(a: Matrix, b: Matrix) -> Matrix:
    columns = list(zip(*b, strict=True))
    return [[sum(x * y for x, y in zip(row, col, strict=True)) for col in columns] for row in a]


def matrix_exponential(m: Matrix) -> Matrix:
    """Return ``exp(m)`` by scaling and squaring with a Taylor series.

    ``m`` is scaled by a power of two until its infinity norm is at most ``0.5``, the
    series runs to the 18th term (truncation error below ``1e-20`` there) and the
    result is squared back.

    Raises
    ------
    ValueError
        When ``m`` is not square or holds a non-finite entry.
    """
    size = len(m)
    if any(len(row) != size for row in m) or any(not math.isfinite(x) for row in m for x in row):
        raise ValueError("matrix must be square and finite")
    norm = max((sum(abs(x) for x in row) for row in m), default=0.0)
    squarings = 0 if norm <= SCALED_NORM else math.ceil(math.log2(norm / SCALED_NORM))
    scale = 2.0**squarings
    scaled = [[x / scale for x in row] for row in m]
    identity = [[1.0 if i == j else 0.0 for j in range(size)] for i in range(size)]
    result = [row[:] for row in identity]
    term = [row[:] for row in identity]
    for k in range(1, TAYLOR_TERMS + 1):
        term = [[x / k for x in row] for row in _multiply(term, scaled)]
        result = [
            [r + t for r, t in zip(rr, tr, strict=True)]
            for rr, tr in zip(result, term, strict=True)
        ]
    for _ in range(squarings):
        result = _multiply(result, result)
    return result


def _symmetric_eigenvalues(matrix: Matrix) -> list[float]:
    """Return the eigenvalues of a small symmetric matrix (cyclic Jacobi rotations)."""
    a = [row[:] for row in matrix]
    size = len(a)
    for _ in range(60):
        off = sum(a[i][j] ** 2 for i in range(size) for j in range(i + 1, size))
        diag = sum(a[i][i] ** 2 for i in range(size))
        if off <= 1e-34 * max(diag, 1e-300):
            break
        for p in range(size - 1):
            for q in range(p + 1, size):
                if a[p][q] == 0.0:
                    continue
                theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
                t = math.copysign(1.0, theta) / (abs(theta) + math.sqrt(theta * theta + 1.0))
                c = 1.0 / math.sqrt(t * t + 1.0)
                s = t * c
                for k in range(size):
                    akp, akq = a[k][p], a[k][q]
                    a[k][p], a[k][q] = c * akp - s * akq, s * akp + c * akq
                for k in range(size):
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k], a[q][k] = c * apk - s * aqk, s * apk + c * aqk
    return [a[i][i] for i in range(size)]


def supply_c(loop_mean_c: float, heat_w: float, flow_lpm: float = NOMINAL_FLOW_LPM) -> float:
    """Return the supply temperature that gives loop mean ``loop_mean_c`` at ``heat_w``.

    The loop mean is the mean of supply and return, which differ by
    ``heat / (flow * rho * c_p)``; the supply is half that spread above the mean.
    """
    if not flow_lpm > 0:
        raise ValueError("flow_lpm must be positive")
    return loop_mean_c + heat_w / (2.0 * flow_lpm * W_PER_LPM_K)


def with_defaults_from_estimate(estimate: FactEstimate) -> HouseModel:
    """Return a model from the owner's facts for when no model has been learned.

    The heat-loss coefficient, solar aperture and internal gains come from the
    estimate where it has them; every other parameter takes the learner's prior mean,
    or the value its structure holds (:data:`DEFAULTS`).

    Raises
    ------
    ValueError
        When the estimate holds no heat-loss coefficient.
    """
    if estimate.ua_w_per_k is None:
        raise ValueError("the facts give no heat-loss coefficient")
    values = dict(DEFAULTS)
    values["h_air_out"] = estimate.ua_w_per_k
    if estimate.solar_aperture_m2 is not None:
        values["solar_aperture_m2"] = estimate.solar_aperture_m2
    if estimate.internal_gain_w is not None:
        values["q_int_w"] = estimate.internal_gain_w
    return HouseModel(**values)

"""Signals derived from a :class:`~ovenbird_core.store.Snapshot`.

Every function returns a :class:`Derived` that names its inputs and says which
were missing or stale; the value is ``None`` whenever an input was unusable, so
callers cannot silently act on old data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ovenbird_core.catalogue import HeishaSignal
from ovenbird_core.readings import SignalId, Value
from ovenbird_core.store import Snapshot

WATER_DENSITY_KG_PER_L: Final = 0.996
WATER_CP_J_PER_KG_K: Final = 4180.0
SECONDS_PER_MINUTE: Final = 60.0


@dataclass(frozen=True, slots=True)
class Derived[T]:
    """A derived value with the provenance a decision record needs.

    Parameters
    ----------
    value
        The derived value; ``None`` when an input was missing or stale.
    inputs
        Signals the value is computed from.
    missing
        Inputs never seen or without a numeric value.
    stale
        Inputs seen but older than their maximum age.
    age
        Age of the oldest input in seconds, when all inputs have a known age.
    blocked
        Why there is no value although every input is usable (for example a DHW
        run for space-heating power); empty otherwise.
    """

    value: T | None
    inputs: tuple[SignalId, ...]
    missing: tuple[SignalId, ...] = ()
    stale: tuple[SignalId, ...] = ()
    age: float | None = None
    blocked: str = ""

    @property
    def ok(self) -> bool:
        """Whether a value could be derived."""
        return self.value is not None

    @property
    def reason(self) -> str:
        """Short explanation of why there is no value (empty when there is one)."""
        parts: list[str] = []
        if self.missing:
            parts.append("missing " + ", ".join(self.missing))
        if self.stale:
            parts.append("stale " + ", ".join(self.stale))
        if self.blocked:
            parts.append(self.blocked)
        return "; ".join(parts)


@dataclass(frozen=True, slots=True)
class _Gathered:
    """Values, missing and stale signals and the oldest age of a gather over a signal set."""

    values: dict[SignalId, Value]
    missing: tuple[SignalId, ...]
    stale: tuple[SignalId, ...]
    age: float | None


def _gather(snapshot: Snapshot, signals: tuple[SignalId, ...], allow_stale: bool) -> _Gathered:
    """Collect the usable values of ``signals`` from ``snapshot`` and note what is missing or stale.

    Parameters
    ----------
    snapshot
        State snapshot.
    signals
        Signals to read.
    allow_stale
        Keep stale values instead of leaving them out.
    """
    values: dict[SignalId, Value] = {}
    missing: list[SignalId] = []
    stale: list[SignalId] = []
    ages: list[float] = []
    for signal in signals:
        view = snapshot.get(signal)
        if view is None or view.reason is not None:
            missing.append(signal)
            continue
        if view.age is not None:
            ages.append(view.age)
        if not view.fresh:
            stale.append(signal)
            if not allow_stale:
                continue
        values[signal] = view.value
    age = max(ages) if len(ages) == len(signals) else None
    return _Gathered(values, tuple(missing), tuple(stale), age)


def _number(value: Value | None) -> float | None:
    """Return ``value`` as float, ``None`` for missing, boolean or non-numeric values."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _state_flag(
    snapshot: Snapshot,
    signal: SignalId,
    threshold: float,
    allow_stale: bool,
) -> Derived[bool]:
    """Return whether ``signal`` is at or above ``threshold``, with the inputs it relied on.

    Parameters
    ----------
    snapshot
        State snapshot.
    signal
        Signal to compare.
    threshold
        Lowest value counted as set.
    allow_stale
        Use a stale value instead of returning ``None``.
    """
    inputs = (signal,)
    gathered = _gather(snapshot, inputs, allow_stale)
    number = _number(gathered.values.get(signal))
    missing = gathered.missing
    if number is None and signal not in missing and signal not in gathered.stale:
        missing = (*missing, signal)
    value = None if number is None else number >= threshold
    return Derived(value, inputs, missing, gathered.stale, gathered.age)


def compressor_running(
    snapshot: Snapshot,
    *,
    min_frequency_hz: float = 1.0,
    allow_stale: bool = False,
) -> Derived[bool]:
    """Whether the compressor runs (``Compressor_Freq`` at or above ``min_frequency_hz``).

    Parameters
    ----------
    snapshot
        State snapshot.
    min_frequency_hz
        Lowest frequency counted as running.
    allow_stale
        Use a stale frequency instead of returning ``None``.

    Returns
    -------
    Derived[bool]
        Running flag with provenance.
    """
    return _state_flag(snapshot, HeishaSignal.COMPRESSOR_FREQ, min_frequency_hz, allow_stale)


def defrost_active(snapshot: Snapshot, *, allow_stale: bool = False) -> Derived[bool]:
    """Whether the pump is defrosting (``Defrosting_State`` = 1)."""
    return _state_flag(snapshot, HeishaSignal.DEFROSTING_STATE, 1, allow_stale)


def dhw_active(snapshot: Snapshot, *, allow_stale: bool = False) -> Derived[bool]:
    """Whether the three-way valve is on DHW (``ThreeWay_Valve_State`` = 1)."""
    return _state_flag(snapshot, HeishaSignal.THREEWAY_VALVE_STATE, 1, allow_stale)


def heat_power_w(
    flow_l_per_min: float,
    inlet_c: float,
    outlet_c: float,
    *,
    offset_k: float = 0.0,
    density_kg_per_l: float = WATER_DENSITY_KG_PER_L,
    cp_j_per_kg_k: float = WATER_CP_J_PER_KG_K,
) -> float:
    """Thermal power carried by the water loop in W.

    Parameters
    ----------
    flow_l_per_min
        Volume flow in l/min.
    inlet_c, outlet_c
        Return and supply temperatures in °C.
    offset_k
        Calibrated sensor offset subtracted from ``outlet - inlet``.
    density_kg_per_l, cp_j_per_kg_k
        Water properties.

    Returns
    -------
    float
        ``flow * density * cp * (outlet - inlet - offset)``; negative while the loop
        gives heat back (defrost).
    """
    mass_flow_kg_s = flow_l_per_min / SECONDS_PER_MINUTE * density_kg_per_l
    return mass_flow_kg_s * cp_j_per_kg_k * (outlet_c - inlet_c - offset_k)


DHW_BLOCKED: Final = "dhw active: the heat goes to the tank, not the heating loop"


def heat_delivered_w(
    snapshot: Snapshot,
    *,
    offset_k: float = 0.0,
    min_frequency_hz: float = 1.0,
    allow_stale: bool = False,
) -> Derived[float]:
    """Heat the pump delivers to the space-heating loop, in W.

    Computed from ``Pump_Flow`` and the inlet/outlet spread, gated on the pump's
    state so the value means "space-heating power":

    * compressor stopped: ``0.0`` (circulation alone produces no heat; the spread
      then is sensor offset);
    * compressor running on DHW (three-way valve to the tank): no value, with
      :data:`DHW_BLOCKED` as the reason;
    * compressor running for heating, including defrost: the measured power, which
      is negative while a defrost draws heat back from the loop.

    Parameters
    ----------
    snapshot
        State snapshot.
    offset_k
        Calibrated outlet-minus-inlet offset at zero heat (pump on, compressor off).
    min_frequency_hz
        Lowest compressor frequency counted as running.
    allow_stale
        Use stale inputs instead of returning ``None``.

    Returns
    -------
    Derived[float]
        Power in W with provenance; ``None`` when a needed input is missing, stale
        or invalid, or during a DHW run.
    """
    gate: tuple[SignalId, ...] = (HeishaSignal.COMPRESSOR_FREQ, HeishaSignal.THREEWAY_VALVE_STATE)
    loop: tuple[SignalId, ...] = (
        HeishaSignal.PUMP_FLOW,
        HeishaSignal.INLET_TEMP,
        HeishaSignal.OUTLET_TEMP,
    )
    running = compressor_running(
        snapshot, min_frequency_hz=min_frequency_hz, allow_stale=allow_stale
    )
    if running.value is False:
        return Derived(0.0, running.inputs, age=running.age)
    inputs = gate + loop
    gathered = _gather(snapshot, inputs, allow_stale)
    dhw = dhw_active(snapshot, allow_stale=allow_stale)
    missing = tuple(dict.fromkeys((*running.missing, *dhw.missing, *gathered.missing)))
    stale = gathered.stale
    if running.value is None or dhw.value is None:
        return Derived(None, inputs, missing, stale, gathered.age)
    if dhw.value:
        return Derived(None, inputs, missing, stale, gathered.age, DHW_BLOCKED)
    flow = _number(gathered.values.get(HeishaSignal.PUMP_FLOW))
    inlet = _number(gathered.values.get(HeishaSignal.INLET_TEMP))
    outlet = _number(gathered.values.get(HeishaSignal.OUTLET_TEMP))
    if flow is None or inlet is None or outlet is None:
        return Derived(None, inputs, missing, stale, gathered.age)
    power = heat_power_w(flow, inlet, outlet, offset_k=offset_k)
    return Derived(power, inputs, missing, stale, gathered.age)

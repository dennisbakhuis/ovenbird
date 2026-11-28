"""Synthetic snapshots for controller tests, scenarios and quick experiments.

Builds a :class:`~ovenbird_core.store.Snapshot` straight from a handful of plant
values, without going through MQTT parsing, so a scenario can be written as a
sequence of :class:`PlantView` values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final

from ovenbird_core.catalogue import HeishaSignal
from ovenbird_core.control.observe import control_inputs
from ovenbird_core.control.types import ControlInputs, Mode, Override, PlanSlice
from ovenbird_core.instant import Instant
from ovenbird_core.readings import SignalId, SourceKind, Value
from ovenbird_core.store import (
    HA_MAX_AGE_S,
    HEISHAMON_MAX_AGE_S,
    HeishaMonStatus,
    SignalView,
    Snapshot,
)

ROOM_SIGNAL: Final[SignalId] = "ha/sensor.living_room_temperature"
FRESH_AGE_S: Final = 10.0


@dataclass(frozen=True, slots=True)
class PlantView:
    """What the pump and the room report at one instant (``None`` = never seen).

    Parameters
    ----------
    outside, outlet, inlet
        Temperatures in °C (``outside`` is an integer on a real pump).
    compressor_hz
        Compressor frequency.
    defrost, valve
        ``Defrosting_State`` and ``ThreeWay_Valve_State`` codes.
    heating_mode, operating_mode
        ``Heating_Mode`` (1 Direct) and ``Operating_Mode_State`` (0 heat).
    water_target, max_pump_duty, quiet
        Applied settings.
    room
        Room temperature.
    alive
        HeishaMon heartbeat alive.
    stale
        Signals reported with an age beyond their maximum.
    """

    outside: float | None = 5.0
    outlet: float | None = 30.0
    inlet: float | None = 27.0
    compressor_hz: int | None = 0
    defrost: int | None = 0
    valve: int | None = 0
    heating_mode: int | None = 1
    operating_mode: int | None = 0
    water_target: int | None = None
    max_pump_duty: int | None = None
    quiet: int | None = None
    room: float | None = 21.0
    alive: bool = True
    stale: frozenset[SignalId] = field(default_factory=frozenset)


def _view(
    now: Instant, signal: SignalId, value: Value, source: SourceKind, stale: bool
) -> SignalView:
    """Return a signal view that is fresh or aged beyond its source's freshness limit.

    Parameters
    ----------
    now
        Time of the snapshot.
    signal
        Signal the view belongs to.
    value
        Value of the view.
    source
        Source the value came from.
    stale
        Whether the view is aged past the freshness limit.
    """
    max_age = HA_MAX_AGE_S if source is SourceKind.HA else HEISHAMON_MAX_AGE_S
    age = max_age + 60.0 if stale else FRESH_AGE_S
    return SignalView(
        signal=signal,
        value=value,
        unit=None,
        source=source,
        observed=now.shifted(-age),
        age=age,
        max_age=max_age,
        fresh=not stale,
        retained=False,
        source_timestamp=None,
    )


def synthetic_snapshot(
    now: Instant, plant: PlantView, *, room_signal: SignalId = ROOM_SIGNAL
) -> Snapshot:
    """Build a snapshot holding ``plant``'s values at ``now``.

    Parameters
    ----------
    now
        Snapshot instant.
    plant
        Values to report.
    room_signal
        Signal id of the room temperature.

    Returns
    -------
    Snapshot
        Snapshot with fresh views (or stale ones for ``plant.stale``).
    """
    pairs: tuple[tuple[SignalId, Value | None, SourceKind], ...] = (
        (HeishaSignal.OUTSIDE_TEMP, plant.outside, SourceKind.HEISHAMON),
        (HeishaSignal.OUTLET_TEMP, plant.outlet, SourceKind.HEISHAMON),
        (HeishaSignal.INLET_TEMP, plant.inlet, SourceKind.HEISHAMON),
        (HeishaSignal.COMPRESSOR_FREQ, plant.compressor_hz, SourceKind.HEISHAMON),
        (HeishaSignal.DEFROSTING_STATE, plant.defrost, SourceKind.HEISHAMON),
        (HeishaSignal.THREEWAY_VALVE_STATE, plant.valve, SourceKind.HEISHAMON),
        (HeishaSignal.HEATING_MODE, plant.heating_mode, SourceKind.HEISHAMON),
        (HeishaSignal.OPERATING_MODE_STATE, plant.operating_mode, SourceKind.HEISHAMON),
        (HeishaSignal.Z1_WATER_TARGET_TEMP, plant.water_target, SourceKind.HEISHAMON),
        (HeishaSignal.MAX_PUMP_DUTY, plant.max_pump_duty, SourceKind.HEISHAMON),
        (HeishaSignal.QUIET_MODE_LEVEL, plant.quiet, SourceKind.HEISHAMON),
        (room_signal, plant.room, SourceKind.HA),
    )
    views = {
        signal: _view(now, signal, value, source, signal in plant.stale)
        for signal, value, source in pairs
        if value is not None
    }
    heishamon = HeishaMonStatus(
        alive=plant.alive,
        heartbeat_age=2.0 if plant.alive else 600.0,
        lwt_online=plant.alive,
        version="synthetic",
        uptime_s=None,
    )
    return Snapshot(
        now=now,
        signals=MappingProxyType(views),
        heishamon=heishamon,
        errors=MappingProxyType({}),
        error_counts=MappingProxyType({}),
    )


def synthetic_inputs(
    now: Instant,
    plant: PlantView,
    *,
    mode: Mode = Mode.AUTO,
    plan: PlanSlice | None = None,
    override: Override | None = None,
    room_signal: SignalId | None = ROOM_SIGNAL,
    room_override: Override | None = None,
) -> ControlInputs:
    """Build the controller inputs of one tick from ``plant``.

    Parameters
    ----------
    now
        Tick instant.
    plant
        Values to report.
    mode, plan, override
        Passed through to :class:`~ovenbird_core.control.types.ControlInputs`.
    room_signal
        Room sensor signal id; ``None`` for an install without room sensor.
    room_override
        A temporary room target (``room_target`` or ``away``).

    Returns
    -------
    ControlInputs
        The tick's inputs.
    """
    snapshot = synthetic_snapshot(now, plant, room_signal=room_signal or ROOM_SIGNAL)
    return control_inputs(
        snapshot,
        room_signal=room_signal,
        mode=mode,
        plan=plan,
        override=override,
        room_override=room_override,
    )

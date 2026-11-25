"""Build controller inputs from a :class:`~ovenbird_core.store.Snapshot`."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ovenbird_core.catalogue import HeishaSignal
from ovenbird_core.control.types import (
    ActualValue,
    ControlInputs,
    Mode,
    Override,
    PlanSlice,
    PumpActual,
    RoomInput,
)
from ovenbird_core.readings import SignalId, Value
from ovenbird_core.store import SignalView, Snapshot

if TYPE_CHECKING:
    from ovenbird_core.control.config import RoomSensorProfile


@dataclass(frozen=True, slots=True)
class PumpActualSignals:
    """Signal ids the pump's applied settings are read from.

    Parameters
    ----------
    water_target, max_pump_duty, quiet_mode, heating_mode, operating_mode
        Signal ids; the defaults are the HeishaMon ``main/*`` topics.
    """

    water_target: SignalId = HeishaSignal.Z1_WATER_TARGET_TEMP
    max_pump_duty: SignalId = HeishaSignal.MAX_PUMP_DUTY
    quiet_mode: SignalId = HeishaSignal.QUIET_MODE_LEVEL
    heating_mode: SignalId = HeishaSignal.HEATING_MODE
    operating_mode: SignalId = HeishaSignal.OPERATING_MODE_STATE


def as_number(value: Value | None) -> float | None:
    """Return ``value`` as a finite float, or ``None`` for non-numeric values."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _actual(view: SignalView | None) -> ActualValue | None:
    if view is None:
        return None
    number = as_number(view.value)
    if number is None or not number.is_integer():
        return None
    return ActualValue(int(number), view.age, view.fresh, view.signal)


def pump_actual(snapshot: Snapshot, signals: PumpActualSignals | None = None) -> PumpActual:
    """Read the pump's applied settings from ``snapshot``.

    Parameters
    ----------
    snapshot
        State snapshot.
    signals
        Signal ids to read; HeishaMon ``main/*`` by default.

    Returns
    -------
    PumpActual
        Each setting with its freshness; ``None`` for settings never seen or
        without an integer value.
    """
    ids = signals or PumpActualSignals()
    return PumpActual(
        water_target=_actual(snapshot.get(ids.water_target)),
        max_pump_duty=_actual(snapshot.get(ids.max_pump_duty)),
        quiet_mode=_actual(snapshot.get(ids.quiet_mode)),
        heating_mode=_actual(snapshot.get(ids.heating_mode)),
        operating_mode=_actual(snapshot.get(ids.operating_mode)),
    )


def room_input(
    snapshot: Snapshot, signal: SignalId | None, profile: RoomSensorProfile | None = None
) -> RoomInput | None:
    """Read the configured room temperature from ``snapshot``.

    Parameters
    ----------
    snapshot
        State snapshot.
    signal
        Room temperature signal id; ``None`` when no room sensor is configured.
    profile
        The sensor's profile (step and reporting kind); without one the step is
        unknown (no dead zone) and the profile ``periodic``.

    Returns
    -------
    RoomInput or None
        The room input with freshness, held and alive ages and invalidation
        reason; ``None`` when no sensor is configured, it was never seen or its
        value is not numeric.
    """
    if signal is None:
        return None
    view = snapshot.get(signal)
    if view is None:
        return None
    number = as_number(view.value)
    if number is None:
        return None
    if profile is None:
        return RoomInput(
            number, view.age, view.fresh, view.signal, view.reason, 0.0, view.held, view.alive_by
        )
    return RoomInput(
        number,
        view.age,
        view.fresh,
        view.signal,
        view.reason,
        quantum_k=profile.quantum_k,
        held_s=view.held,
        alive_by=view.alive_by,
        profile=profile.kind,
    )


def control_inputs(
    snapshot: Snapshot,
    *,
    room_signal: SignalId | None = None,
    mode: Mode = Mode.AUTO,
    plan: PlanSlice | None = None,
    override: Override | None = None,
    actual_signals: PumpActualSignals | None = None,
    room_profile: RoomSensorProfile | None = None,
) -> ControlInputs:
    """Assemble the inputs of one tick from a snapshot.

    Parameters
    ----------
    snapshot
        State snapshot; its ``now`` becomes the tick's instant.
    room_signal
        Room temperature signal id, if a room sensor is configured.
    mode
        Operating mode.
    plan
        Planner output for the tick.
    override
        Manual override.
    actual_signals
        Signal ids of the pump's applied settings.
    room_profile
        Profile of the room sensor.

    Returns
    -------
    ControlInputs
        The tick's inputs.
    """
    return ControlInputs(
        now=snapshot.now,
        snapshot=snapshot,
        room=room_input(snapshot, room_signal, room_profile),
        plan=plan,
        mode=mode,
        override=override,
        actual=pump_actual(snapshot, actual_signals),
    )

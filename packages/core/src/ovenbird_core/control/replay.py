"""Rebuild a tick's controller inputs and state from its decision record (open-loop replay).

A decision record holds what the controller used (``inputs_used``) and the state it
returned (``controller_state``, the flat form of :class:`OvenbirdState`). That is
enough to run the same tick again, with the same or another configuration:

- :func:`replay_inputs` turns ``inputs_used`` back into :class:`ControlInputs`: one
  signal view per recorded snapshot signal (value, age, freshness), the pump's
  reported settings, the HeishaMon heartbeat and the room input under the given
  sensor profile (its held time and liveness signal from the record's state);
- :func:`state_from_flat` is the inverse of :meth:`OvenbirdState.as_flat`;
- :func:`shift_state` moves the state's monotonic times onto another clock axis
  (a service restart starts a new monotonic origin; the restored state is
  re-anchored the same way, see ``ovenbird.control.persist``).

Replaying a record with the configuration it was made with reproduces its setpoint;
with another configuration the result is open loop: the candidate reacts to what
the house actually did under the recorded control.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, replace
from datetime import timedelta
from types import MappingProxyType
from typing import Final

from ovenbird_core.control.config import RoomSensorProfile
from ovenbird_core.control.ovenbird import STATS_SIGNAL
from ovenbird_core.control.record import DecisionRecord, InputRef, StateValue
from ovenbird_core.control.state import OvenbirdState, RampPhase, StoveSource, StoveTrigger
from ovenbird_core.control.types import (
    ActualValue,
    ControlInputs,
    Mode,
    PumpActual,
    RoomInput,
)
from ovenbird_core.instant import Instant
from ovenbird_core.readings import SignalId, SourceKind
from ovenbird_core.store import HeishaMonStatus, SignalView, Snapshot

ROOM_SOURCE: Final = "room"
ACTUAL_SOURCE: Final = "actual"
STATE_TIME_FIELDS: Final = frozenset(
    {
        "last_change_at",
        "outside_at",
        "last_tick_at",
        "run_started_at",
        "stopped_at",
        "crosscheck_since",
        "room_lost_at",
        "stove_since",
        "stove_low_at",
        "stove_trusted_since",
        "stove_high_at",
        "stove_step_low_at",
        "summer_mean_at",
        "summer_mean_from",
    }
)
FLAT_NAMES: Final = MappingProxyType(
    {
        "outside_filtered": "outside_filtered_c",
        "ramp_cap": "ramp_cap_c",
        "crosscheck_latched": "crosscheck_latched_c",
    }
)
ACTUAL_SIGNALS: Final = MappingProxyType(
    {
        "main/Z1_Water_Target_Temp": "water_target",
        "main/Max_Pump_Duty": "max_pump_duty",
        "main/Quiet_Mode_Level": "quiet_mode",
        "main/Heating_Mode": "heating_mode",
        "main/Operating_Mode_State": "operating_mode",
    }
)


def _float(value: StateValue) -> float | None:
    """Return a recorded state number as float, ``None`` when missing or not numeric."""
    if value is None or isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _int(value: StateValue) -> int | None:
    """Return a recorded state number as int, ``None`` when missing or not numeric."""
    if value is None or isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value)


def state_from_flat(flat: Mapping[str, StateValue]) -> OvenbirdState:
    """Return the controller state a record's ``controller_state`` describes.

    Parameters
    ----------
    flat
        :meth:`OvenbirdState.as_flat` output (extra keys of the record are ignored).

    Returns
    -------
    OvenbirdState
        The state; missing keys keep their defaults.
    """
    defaults = OvenbirdState()
    values: dict[str, object] = {}
    for item in fields(defaults):
        key = FLAT_NAMES.get(item.name, item.name)
        if key not in flat:
            continue
        raw = flat[key]
        default = getattr(defaults, item.name)
        if item.name == "ramp_phase":
            values[item.name] = RampPhase(str(raw)) if raw is not None else RampPhase.IDLE
        elif item.name == "stove_source":
            values[item.name] = None if raw is None else StoveSource(str(raw))
        elif item.name == "stove_trigger":
            values[item.name] = None if raw is None else StoveTrigger(str(raw))
        elif item.name == "running":
            values[item.name] = None if raw is None else bool(raw)
        elif item.name in (
            "stove_blocked",
            "stove_level_blocked",
            "stove_reentry_wait",
            "stove_fault",
            "summer_active",
        ):
            values[item.name] = bool(raw)
        elif item.name in ("setpoint", "pump_duty", "quiet_level"):
            values[item.name] = _int(raw)
        elif isinstance(default, float):
            number = _float(raw)
            values[item.name] = default if number is None else number
        else:
            values[item.name] = _float(raw)
    return OvenbirdState(**values)  # type: ignore[arg-type]


def shift_state(state: OvenbirdState, delta_s: float) -> OvenbirdState:
    """Return ``state`` with every monotonic time moved by ``delta_s`` seconds."""
    if delta_s == 0.0:
        return state
    moved = {
        name: getattr(state, name) + delta_s
        for name in STATE_TIME_FIELDS
        if getattr(state, name) is not None
    }
    return replace(state, **moved)


def clock_offset(at: Instant) -> float:
    """Wall-clock minus monotonic seconds of ``at`` (constant within one process run)."""
    return at.wall.timestamp() - at.monotonic


def _view(ref: InputRef, now: Instant) -> SignalView:
    """Rebuild the signal view an input reference recorded, aged back from ``now``."""
    try:
        source = SourceKind(ref.source) if ref.source is not None else SourceKind.HEISHAMON
    except ValueError:
        source = SourceKind.HEISHAMON
    age = ref.age
    observed = now
    if age is not None:
        observed = Instant(now.monotonic - age, now.wall - timedelta(seconds=age))
    value = ref.value if ref.value is not None else 0
    return SignalView(
        signal=ref.signal,
        value=value,
        unit=None,
        source=source,
        observed=observed,
        age=age,
        max_age=float("inf"),
        fresh=ref.fresh,
        retained=False,
        source_timestamp=None,
    )


def _actual(ref: InputRef) -> ActualValue | None:
    """Rebuild an applied value from an input reference, ``None`` if it was not an integer one."""
    if ref.source != ACTUAL_SOURCE:
        return None
    value = ref.value
    if value is None or isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if not float(value).is_integer():
        return None
    return ActualValue(int(value), ref.age, ref.fresh, ref.signal)


def _room(
    ref: InputRef,
    record: DecisionRecord,
    room_signal: SignalId | None,
    profile: RoomSensorProfile | None,
) -> RoomInput | None:
    """Rebuild the room input from an input reference and the record's controller state.

    Parameters
    ----------
    ref
        Recorded input reference of the room signal.
    record
        Decision record being replayed.
    room_signal
        Signal id of the configured room sensor, if any.
    profile
        Reporting profile of the room sensor, if known.
    """
    value = ref.value
    if room_signal is None or ref.signal != room_signal:
        return None
    if value is None or isinstance(value, bool) or not isinstance(value, int | float):
        return None
    state = record.controller_state
    held = _float(state.get("room_held_s"))
    alive_by = state.get("room_alive_by")
    by = alive_by if isinstance(alive_by, str) else None
    if profile is None:
        return RoomInput(float(value), ref.age, ref.fresh, ref.signal, None, 0.0, held, by)
    return RoomInput(
        float(value),
        ref.age,
        ref.fresh,
        ref.signal,
        None,
        quantum_k=profile.quantum_k,
        held_s=held,
        alive_by=by,
        profile=profile.kind,
    )


def replay_inputs(
    record: DecisionRecord,
    *,
    room_signal: SignalId | None,
    room_profile: RoomSensorProfile | None = None,
    mode: Mode | None = None,
) -> ControlInputs:
    """Rebuild the controller inputs of the tick ``record`` describes.

    Parameters
    ----------
    record
        A stored decision record.
    room_signal
        Room signal of the configuration to replay with; the room input is
        rebuilt only when it is the recorded room signal (``None`` otherwise).
    room_profile
        Room sensor profile of that configuration (step and reporting kind).
    mode
        Mode to replay in; the recorded mode when omitted.

    Returns
    -------
    ControlInputs
        Inputs with the recorded values, ages and freshness. Values that need no
        configuration (the curve's outside temperature, flags, the pump's reported
        settings, a cross-check signal) are exactly as recorded; the room
        freshness is the recorded one, decided under the recorded staleness policy.
    """
    now = record.at
    signals: dict[SignalId, SignalView] = {}
    actual: dict[str, ActualValue | None] = {}
    heartbeat = HeishaMonStatus(False, None, None, None, None)
    room: RoomInput | None = None
    for ref in record.inputs_used:
        if ref.signal == STATS_SIGNAL and ref.source is None:
            heartbeat = HeishaMonStatus(bool(ref.value), ref.age, None, None, None)
        elif ref.source == ROOM_SOURCE:
            room = _room(ref, record, room_signal, room_profile)
        elif ref.signal in ACTUAL_SIGNALS and (ref.source in (ACTUAL_SOURCE, None)):
            actual[ACTUAL_SIGNALS[ref.signal]] = _actual(ref)
        elif ref.source is not None:
            signals[ref.signal] = _view(ref, now)
    snapshot = Snapshot(
        now=now,
        signals=MappingProxyType(signals),
        heishamon=heartbeat,
        errors=MappingProxyType({}),
        error_counts=MappingProxyType({}),
    )
    return ControlInputs(
        now=now,
        snapshot=snapshot,
        room=room,
        plan=None,
        mode=mode if mode is not None else record.mode,
        override=None,
        actual=PumpActual(
            water_target=actual.get("water_target"),
            max_pump_duty=actual.get("max_pump_duty"),
            quiet_mode=actual.get("quiet_mode"),
            heating_mode=actual.get("heating_mode"),
            operating_mode=actual.get("operating_mode"),
        ),
    )

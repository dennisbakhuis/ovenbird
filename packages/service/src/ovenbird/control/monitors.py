"""Safety monitors: pure checks of the pump's reported state, evaluated every few seconds.

:func:`evaluate` is pure: it maps a :class:`~ovenbird_core.Snapshot`, the monitor
configuration and the instants at which each condition was first seen to one
:class:`Finding` per monitor. A finding is ``ok`` (condition absent), ``pending``
(present but not sustained long enough yet), ``active`` (alarm) or ``unknown``
(inputs missing or stale). :class:`SafetyMonitor` is the shell around it: it runs on
the service clock, raises an alarm for every ``active`` finding, clears it only on
``ok`` (``pending`` and ``unknown`` keep the alarm as it is), reports the critical
ones to the command adapter (corrective action or safety hold) and sets the
service's ``alarms`` health check.

**Defrost and flow.** Some heat pumps stop their water pump during a defrost.
:class:`SafetyMonitor` latches ``Main_Inlet_Temp`` and ``Outside_Temp`` when
``Defrosting_State`` turns on (the inlet drifts while the water stands still) and
reads the model profile (:mod:`ovenbird_core.pumpmodel`) from ``Heat_Pump_Model``,
also when it arrives later; :func:`evaluate` gets both as :class:`DeiceOnset`. With a
known profile the deice mode follows its manual: in mode 2 (hot gas) the water pump is
off by design, in mode 1 it should run. ``safety_defrost_low_flow`` decides what a
``low_flow_defrost`` does: ``auto`` (default) only journals it in mode 2 and raises it
otherwise, ``log`` only journals it in mode 2 and for an unknown model, ``alarm``
always raises it; in mode 1 it is always raised. Journalled means a ``started`` and a
``cleared`` event (severity ``info``, detail ``logged_only``), never active on the
board and never notified. :meth:`SafetyMonitor.defrost_state` gives the latched defrost
to the snapshot (``defrost``: active, mode, start, the values at the start and the
``defrost_stuck`` limit).

Monitors (``critical`` ones concern the plant's safety):

========================  ========  ==================================================
code                      severity  condition
========================  ========  ==================================================
``setpoint_above_max``    critical  ``Z1_Water_Target_Temp``, ``Z1_Heat_Request_Temp``
                                    (Direct mode) or the controller's own setpoint
                                    above the emitter's maximum supply; immediate
``outlet_overshoot``      critical  ``Main_Outlet_Temp`` above maximum supply + margin
                                    for the sustain time; suspended during DHW runs
``low_flow``              critical  ``Pump_Flow`` below the minimum while the
                                    compressor runs, for the sustain time; suspended
                                    during a defrost
``low_flow_defrost``      warning   ``Pump_Flow`` below the minimum during a defrost
                                    while the compressor runs, for the sustain time;
                                    by design in a profile's deice mode 2, an
                                    anomaly in mode 1
``pump_error``            critical  ``Error`` is not ``No error``; immediate
``backup_heater``         warning   ``Internal_Heater_State`` or
                                    ``External_Heater_State`` active
``backup_heater_allowed`` info      ``Room_Heater_State`` free (backup heater allowed)
``heating_off_outdoor``   info      ``Outside_Temp`` at or above
                                    ``Heating_Off_Outdoor_Temp`` (clears 1 K below)
``defrost_stuck``         warning   ``Defrosting_State`` on for longer than the limit
                                    (in deice mode 2 at least the profile's
                                    longest mode 2 defrost + :data:`DEICE_MARGIN_S`)
``room_below_floor``      warning   room temperature below the comfort floor for the
                                    sustain time; a night set-back of the room target
                                    lowers the floor with it, by at most
                                    ``room_setback_max_k``
``room_sensor_silent``    warning   ``on_change`` room sensor: no proof of life (the
                                    value or a liveness signal) for longer than the
                                    silence limit
``room_report_overdue``   warning   ``periodic`` room sensor: no report for 3 x the
                                    report interval (it may report on change only)
``room_unit_refused``     warning   the room value from Home Assistant is refused for
                                    its unit (none or unknown, and HA's unit system
                                    is not metric); immediate
``ha_link_down``          warning   Home Assistant configured but its link is down (no
                                    connection or no successful ``get_states``
                                    re-read) for the sustain time; held room values
                                    fall back to the 1800 s limit
``compressor_starts``     warning   more compressor starts than
                                    ``safety_starts_per_hour_max`` in the last hour and
                                    in the hour before, or than
                                    ``safety_starts_per_day_max`` in 24 h
                                    (:mod:`ovenbird.control.starts`; a defrost's
                                    restart is no start); off with
                                    ``safety_starts_alarm_enabled``
========================  ========  ==================================================

Every finding carries the monitor's ``limit``, its ``unit`` and ``direction``
(``above`` or ``below``); state monitors have none. ``defrost_stuck``'s limit
applies to the defrost's duration, not to its ``value`` (the defrost flag).

**Comfort floor and plan set-back.** The floor is ``comfort - safety_room_floor_k``. A
plan slice that lowers the room target (a night set-back) would otherwise bring the
room close to it by design, so :func:`evaluate` takes the room-target shift the
controller applies (``room_shift_k``, from :class:`SafetyMonitor`'s ``room_shift``) and
lowers the floor by a negative shift, never by more than ``room_setback_max_k`` (the
controller's bound on a rule slice). A raised target never lifts the floor, and without
a shift the floor is the static one, so a room that is really too cold still alarms.
A manual target below comfort (away, or a cooler room by boost) lowers the floor to that
target minus ``safety_room_floor_k`` (``lowered_target_c``) for as long as it is set,
the return phase of away included.

The room sensor and link monitors read the same store views as the controller
(ages include liveness signals, the link state is the store's), so the alarms, the
history and the API agree with the decision record. ``room_implausible`` (the
controller's cross-check) is raised by the control loop.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol

from ovenbird.clock import Sleep, iso_z
from ovenbird.config.values import DefrostLowFlowMode
from ovenbird.control.alarms import (
    SEVERITY,
    AlarmBoard,
    AlarmCode,
    AlarmEvent,
    AlarmEventKind,
    Severity,
)
from ovenbird.control.starts import StartCounter, StartCounts, starts_exceeded
from ovenbird.payloads import Json, defrost_payload
from ovenbird_core import (
    HeishaSignal,
    Instant,
    ParseErrorKind,
    SignalId,
    SignalView,
    Snapshot,
    SourceKind,
)
from ovenbird_core.control.config import DEFAULT_PLAN_RULE_MAX_K
from ovenbird_core.control.observe import as_number
from ovenbird_core.control.types import RoomProfile
from ovenbird_core.derived import compressor_running, defrost_active, dhw_active
from ovenbird_core.inputs import HA_SIGNAL_PREFIX
from ovenbird_core.pumpmodel import DeiceMode, DeiceSpec, PumpProfile, profile_for

if TYPE_CHECKING:
    from ovenbird.config import Settings
    from ovenbird.runtime import Runtime

LOGGER = logging.getLogger("ovenbird.control.monitors")
NO_ERROR: Final = "No error"
DIRECT_MODE: Final = 1
HEATING_OFF_HYSTERESIS_K: Final = 1.0
EPSILON: Final = 1e-9
SAFETY_INTERVAL_S: Final = 5.0
OVERDUE_FACTOR: Final = 3.0
HA_LINK_SUSTAIN_S: Final = 300.0
DEICE_MARGIN_S: Final = 300.0
LOGGED_ONLY: Final = "logged only from now on (safety_defrost_low_flow)"
LOGGED_AS_ALARM: Final = "raised as an alarm from now on (safety_defrost_low_flow)"

type Direction = Literal["above", "below"]


class MonitorStatus(StrEnum):
    """State of one monitor."""

    OK = "ok"
    PENDING = "pending"
    ACTIVE = "active"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class MonitorConfig:
    """Thresholds of the safety monitors.

    Parameters
    ----------
    max_supply_c
        Emitter's hard maximum supply temperature.
    outlet_margin_k
        ``Main_Outlet_Temp`` may exceed the maximum supply by this much.
    outlet_sustain_s
        Overshoot must last this long to alarm.
    min_flow_lpm
        Lowest acceptable ``Pump_Flow`` while the compressor runs (model dependent).
    flow_sustain_s
        Low flow must last this long to alarm.
    defrost_max_s
        Longest plausible defrost.
    room_signal
        Room temperature signal id; ``None`` disables the comfort-floor monitor.
    room_floor_c
        Comfort floor; ``None`` disables the comfort-floor monitor.
    room_floor_sustain_s
        The room must stay below the floor this long to alarm.
    room_setback_max_k
        Largest night set-back of the room target that lowers the comfort floor
        (the controller's bound on a rule plan slice).
    room_profile
        Reporting profile of the room sensor; ``None`` disables the room sensor
        monitors.
    room_report_interval_s
        Report interval of a ``periodic`` room sensor.
    room_silence_limit_s
        Silence limit of an ``on_change`` room sensor.
    ha_enabled
        Whether Home Assistant is configured (enables ``ha_link_down``).
    ha_link_sustain_s
        The HA link must be down this long to alarm.
    defrost_low_flow
        What a ``low_flow_defrost`` does (``safety_defrost_low_flow``): ``auto``,
        ``alarm`` or ``log``.
    room_floor_k
        Distance of the comfort floor below the room target (``safety_room_floor_k``);
        a manual target below comfort lowers the floor by it.
    starts_per_hour_max, starts_per_day_max
        Limits of the ``compressor_starts`` monitor; ``None`` disables it.
    """

    max_supply_c: float
    outlet_margin_k: float = 5.0
    outlet_sustain_s: float = 600.0
    min_flow_lpm: float = 8.0
    flow_sustain_s: float = 120.0
    defrost_max_s: float = 1200.0
    room_signal: SignalId | None = None
    room_floor_c: float | None = None
    room_floor_sustain_s: float = 1800.0
    room_setback_max_k: float = DEFAULT_PLAN_RULE_MAX_K
    room_profile: RoomProfile | None = None
    room_report_interval_s: float = 300.0
    room_silence_limit_s: float = 86_400.0
    ha_enabled: bool = False
    ha_link_sustain_s: float = HA_LINK_SUSTAIN_S
    defrost_low_flow: DefrostLowFlowMode = "auto"
    room_floor_k: float | None = None
    starts_per_hour_max: int | None = None
    starts_per_day_max: int | None = None

    @property
    def max_setpoint(self) -> int:
        """Largest allowed integer water setpoint."""
        return math.floor(self.max_supply_c + EPSILON)


def monitor_config(settings: Settings, max_supply_c: float) -> MonitorConfig:
    """Return the safety monitor thresholds from the settings."""
    floor_k = settings.safety_room_floor_k
    profile = settings.room_profile()
    return MonitorConfig(
        max_supply_c=max_supply_c,
        outlet_margin_k=settings.safety_outlet_margin_k,
        outlet_sustain_s=settings.safety_outlet_sustain_s,
        min_flow_lpm=settings.safety_min_flow_lpm,
        flow_sustain_s=settings.safety_flow_sustain_s,
        defrost_max_s=settings.safety_defrost_max_s,
        room_signal=settings.control_room_signal,
        room_floor_c=None if floor_k is None else settings.control_comfort_c - floor_k,
        room_floor_sustain_s=settings.safety_room_floor_sustain_s,
        room_setback_max_k=settings.control_plan_rule_max_k,
        room_profile=profile.kind if settings.control_room_signal is not None else None,
        room_report_interval_s=profile.report_interval_s,
        room_silence_limit_s=profile.silence_limit_s,
        ha_enabled=settings.ha_enabled,
        defrost_low_flow=settings.safety_defrost_low_flow,
        room_floor_k=floor_k,
        starts_per_hour_max=(
            settings.safety_starts_per_hour_max if settings.safety_starts_alarm_enabled else None
        ),
        starts_per_day_max=(
            settings.safety_starts_per_day_max if settings.safety_starts_alarm_enabled else None
        ),
    )


@dataclass(frozen=True, slots=True)
class Finding:
    """Result of one monitor.

    Parameters
    ----------
    code
        Monitor (alarm) code.
    status
        Monitor state.
    message
        Human explanation.
    value
        Value the decision is based on.
    since
        When the condition was first seen (``pending`` and ``active``).
    limit
        Threshold the monitor compares against; ``None`` for state monitors or
        when the threshold is unknown.
    unit
        Unit of ``limit`` (and of ``value`` where it is the compared quantity).
    direction
        ``"above"`` when exceeding ``limit`` is the condition, ``"below"`` when
        falling under it; ``None`` for state monitors.
    """

    code: AlarmCode
    status: MonitorStatus
    message: str
    value: float | int | str | None = None
    since: Instant | None = None
    limit: float | None = None
    unit: str | None = None
    direction: Direction | None = None

    @property
    def severity(self) -> Severity:
        """Severity of the monitor."""
        return SEVERITY[self.code]

    def to_json(self) -> dict[str, Any]:
        """Return the API form."""
        return {
            "code": self.code.value,
            "severity": self.severity.value,
            "status": self.status.value,
            "message": self.message,
            "value": self.value,
            "since": None if self.since is None else iso_z(self.since.wall),
            "limit": self.limit,
            "unit": self.unit,
            "direction": self.direction,
        }


type Since = Mapping[AlarmCode, Instant]


@dataclass(frozen=True, slots=True)
class DeiceOnset:
    """What is known about a defrost: the model profile and the values at its start.

    Parameters
    ----------
    profile
        Model profile; ``None`` for an unknown model.
    inlet_c
        ``Main_Inlet_Temp`` when the defrost started; ``None`` when unknown.
    outside_c
        ``Outside_Temp`` when the defrost started; ``None`` when unknown.
    started
        When the safety monitor saw the defrost start; ``None`` when unknown (not part
        of the comparison: two onsets with the same facts are equal).
    """

    profile: PumpProfile | None = None
    inlet_c: float | None = None
    outside_c: float | None = None
    started: Instant | None = field(default=None, compare=False)

    @property
    def spec(self) -> DeiceSpec | None:
        """Deice rules of the profile; ``None`` when unknown."""
        return None if self.profile is None else self.profile.deice

    @property
    def mode(self) -> DeiceMode | None:
        """Deice mode the unit picks; ``None`` without deice rules."""
        spec = self.spec
        return None if spec is None else spec.mode(self.inlet_c, self.outside_c)

    @property
    def limit_s(self) -> float:
        """Longest defrost by design plus :data:`DEICE_MARGIN_S`; ``0`` outside mode 2."""
        spec = self.spec
        return spec.mode2_max_s + DEICE_MARGIN_S if spec is not None and self.mode == 2 else 0.0

    def reason(self) -> str:
        """Why the unit picks deice mode 2."""
        spec = self.spec or DeiceSpec()
        if self.inlet_c is not None and self.inlet_c < spec.mode2_inlet_below_c:
            return (
                f"the return water was {self.inlet_c:.1f} °C "
                f"(below {spec.mode2_inlet_below_c:.0f} °C)"
            )
        return (
            f"the outdoor air was {self.outside_c:.1f} °C "
            f"(below {spec.mode2_outside_below_c:.0f} °C) with return water "
            f"{self.inlet_c:.1f} °C (below {spec.mode2_inlet_cold_below_c:.0f} °C)"
        )

    def detail(self) -> dict[str, Any]:
        """Return the journal detail."""
        return {
            "profile": None if self.profile is None else self.profile.name,
            "deice_mode": self.mode,
            "inlet_at_start_c": self.inlet_c,
            "outside_at_start_c": self.outside_c,
        }


def _fresh(snapshot: Snapshot, signal: SignalId) -> SignalView | None:
    """Return the reading of ``signal`` when it is fresh, else ``None``."""
    view = snapshot.get(signal)
    return view if view is not None and view.fresh else None


def _number(snapshot: Snapshot, signal: SignalId) -> float | None:
    """Return the fresh numeric value of ``signal``, or ``None`` when stale or not numeric."""
    view = _fresh(snapshot, signal)
    return None if view is None else as_number(view.value)


def _name(signal: SignalId) -> str:
    """Return the HeishaMon topic name of ``signal`` without its ``main/`` prefix."""
    return signal.removeprefix("main/")


def setpoint_readings(
    read: Callable[[SignalId], SignalView | None],
) -> tuple[tuple[SignalId, int], ...]:
    """Return the fresh integer water setpoints the pump reports.

    ``Z1_Water_Target_Temp`` always; ``Z1_Heat_Request_Temp`` only in Direct mode
    (in compensation mode it is a shift, not a temperature).

    Parameters
    ----------
    read
        Returns the current view of a signal.

    Returns
    -------
    tuple
        ``(signal, value)`` pairs.
    """
    found: list[tuple[SignalId, int]] = []
    signals: list[SignalId] = [HeishaSignal.Z1_WATER_TARGET_TEMP]
    mode = read(HeishaSignal.HEATING_MODE)
    if mode is not None and mode.fresh and as_number(mode.value) == DIRECT_MODE:
        signals.append(HeishaSignal.Z1_HEAT_REQUEST_TEMP)
    for signal in signals:
        view = read(signal)
        if view is None or not view.fresh:
            continue
        number = as_number(view.value)
        if number is not None and number.is_integer():
            found.append((signal, int(number)))
    return tuple(found)


def setpoint_excess(
    read: Callable[[SignalId], SignalView | None], max_setpoint: int
) -> tuple[SignalId, int] | None:
    """Return the highest reported setpoint above ``max_setpoint``, if any."""
    above = [item for item in setpoint_readings(read) if item[1] > max_setpoint]
    return max(above, key=lambda item: item[1]) if above else None


def _sustained(
    code: AlarmCode,
    present: bool,
    since: Since,
    now: Instant,
    sustain_s: float,
    message: str,
    value: float | int | str | None,
) -> Finding:
    """Return a finding that turns active only after the condition has held for ``sustain_s``.

    Parameters
    ----------
    code
        Alarm the finding belongs to.
    present
        Whether the alarm condition holds now.
    since
        When each condition was first seen; updated for ``code``.
    now
        Current time.
    sustain_s
        Seconds the condition must hold before it is active.
    message
        Finding text.
    value
        Measured value shown with the finding.
    """
    if not present:
        return Finding(code, MonitorStatus.OK, message, value)
    first = since.get(code, now)
    status = MonitorStatus.ACTIVE if now.since(first) >= sustain_s else MonitorStatus.PENDING
    return Finding(code, status, message, value, first)


def _unknown(code: AlarmCode, what: str, since: Since) -> Finding:
    """Return an ``unknown`` finding for an input (``what``) that is missing or stale."""
    return Finding(code, MonitorStatus.UNKNOWN, f"{what} unknown or stale", None, since.get(code))


def _setpoint(
    config: MonitorConfig, snapshot: Snapshot, since: Since, desired: int | None
) -> Finding:
    """Return the finding for a water setpoint, reported or wanted, above the maximum supply.

    Parameters
    ----------
    config
        Monitor limits.
    snapshot
        Current signal readings.
    since
        When each condition was first seen.
    desired
        Setpoint in °C the controller wants to send, ``None`` when it has none.
    """
    code = AlarmCode.SETPOINT_ABOVE_MAX
    limit = config.max_setpoint
    readings = list(setpoint_readings(snapshot.get))
    if desired is not None:
        readings.append(("controller setpoint", desired))
    if not readings:
        return _unknown(code, "Z1_Water_Target_Temp", since)
    signal, value = max(readings, key=lambda item: item[1])
    if value <= limit:
        return Finding(
            code, MonitorStatus.OK, f"water setpoint {value} °C within {limit} °C", value
        )
    message = f"{_name(signal)} is {value} °C, above the maximum supply of {limit} °C"
    return Finding(code, MonitorStatus.ACTIVE, message, value, since.get(code, snapshot.now))


def _outlet(config: MonitorConfig, snapshot: Snapshot, since: Since) -> Finding:
    """Return the finding for an outlet temperature above the supply limit plus margin.

    Suspended during a DHW run.
    """
    code = AlarmCode.OUTLET_OVERSHOOT
    outlet = _number(snapshot, HeishaSignal.OUTLET_TEMP)
    if outlet is None:
        return _unknown(code, "Main_Outlet_Temp", since)
    limit = config.max_supply_c + config.outlet_margin_k
    if dhw_active(snapshot).value is True:
        return Finding(code, MonitorStatus.OK, "suspended during a DHW run", outlet)
    message = f"Main_Outlet_Temp {outlet:.1f} °C against a limit of {limit:.1f} °C"
    return _sustained(
        code, outlet > limit, since, snapshot.now, config.outlet_sustain_s, message, outlet
    )


def _flow(config: MonitorConfig, snapshot: Snapshot, since: Since) -> Finding:
    """Return the finding for a flow below the minimum while the compressor runs.

    Suspended during a defrost (see ``_flow_defrost``).
    """
    code = AlarmCode.LOW_FLOW
    flow = _number(snapshot, HeishaSignal.PUMP_FLOW)
    if defrost_active(snapshot).value is True:
        return Finding(
            code, MonitorStatus.OK, "suspended during a defrost (see low_flow_defrost)", flow
        )
    running = compressor_running(snapshot).value
    if running is False:
        return Finding(code, MonitorStatus.OK, "compressor off", None)
    if running is None or flow is None:
        return _unknown(code, "Compressor_Freq or Pump_Flow", since)
    message = (
        f"Pump_Flow {flow:.1f} l/min with the compressor running "
        f"(minimum {config.min_flow_lpm:.1f} l/min)"
    )
    return _sustained(
        code, flow < config.min_flow_lpm, since, snapshot.now, config.flow_sustain_s, message, flow
    )


def _flow_defrost(
    config: MonitorConfig, snapshot: Snapshot, since: Since, deice: DeiceOnset | None
) -> Finding:
    """Return the finding for a low flow during a defrost, judged against the expected de-ice mode.

    Parameters
    ----------
    config
        Monitor limits.
    snapshot
        Current signal readings.
    since
        When each condition was first seen.
    deice
        Defrost onset, ``None`` outside a defrost.
    """
    code = AlarmCode.LOW_FLOW_DEFROST
    defrost = defrost_active(snapshot).value
    if defrost is None:
        return _unknown(code, "Defrosting_State", since)
    if not defrost:
        return Finding(code, MonitorStatus.OK, "no defrost running", None)
    flow = _number(snapshot, HeishaSignal.PUMP_FLOW)
    frequency = _number(snapshot, HeishaSignal.COMPRESSOR_FREQ)
    running = compressor_running(snapshot).value
    if running is False:
        return Finding(code, MonitorStatus.OK, "defrost with the compressor off", flow)
    if running is None or flow is None or frequency is None:
        return _unknown(code, "Compressor_Freq or Pump_Flow", since)
    mode = None if deice is None else deice.mode
    low = flow < config.min_flow_lpm
    message = f"Pump_Flow {flow:.1f} l/min during the defrost"
    if mode is not None:
        message += f" (deice mode {mode})"
    if low and deice is not None and mode == 2:
        message = (
            "deice mode 2 (hot-gas defrost): the heat pump stops its water pump by design "
            f"because {deice.reason()}; Pump_Flow {flow:.1f} l/min, compressor "
            f"{frequency:.0f} Hz"
        )
    elif low and mode == 1:
        message = (
            "low water flow during a defrost (deice mode 1, the pump should run): "
            f"Pump_Flow {flow:.1f} l/min with the compressor at {frequency:.0f} Hz "
            f"(minimum {config.min_flow_lpm:.1f} l/min)"
        )
    elif low:
        message = (
            f"low water flow during a defrost: Pump_Flow {flow:.1f} l/min with the compressor "
            f"at {frequency:.0f} Hz (minimum {config.min_flow_lpm:.1f} l/min); the heat pump "
            "slowed or stopped its water pump while defrosting"
        )
    return _sustained(code, low, since, snapshot.now, config.flow_sustain_s, message, flow)


def _error(snapshot: Snapshot, since: Since) -> Finding:
    """Return the finding for an error code reported by the pump."""
    code = AlarmCode.PUMP_ERROR
    view = _fresh(snapshot, HeishaSignal.ERROR)
    if view is None:
        return _unknown(code, "Error", since)
    text = str(view.value)
    if text == NO_ERROR:
        return Finding(code, MonitorStatus.OK, NO_ERROR, text)
    message = f"the pump reports error {text}"
    return Finding(code, MonitorStatus.ACTIVE, message, text, since.get(code, snapshot.now))


def _heater(snapshot: Snapshot, since: Since) -> Finding:
    """Return the finding for a running backup heater (it heats at COP 1)."""
    code = AlarmCode.BACKUP_HEATER
    internal = _number(snapshot, HeishaSignal.INTERNAL_HEATER_STATE)
    external = _number(snapshot, HeishaSignal.EXTERNAL_HEATER_STATE)
    running = [
        _name(signal)
        for signal, value in (
            (HeishaSignal.INTERNAL_HEATER_STATE, internal),
            (HeishaSignal.EXTERNAL_HEATER_STATE, external),
        )
        if value == 1
    ]
    if running:
        message = f"backup heater running ({', '.join(running)}); it heats at COP 1"
        return Finding(code, MonitorStatus.ACTIVE, message, 1, since.get(code, snapshot.now))
    if internal is None and external is None:
        return _unknown(code, "Internal_Heater_State", since)
    return Finding(code, MonitorStatus.OK, "backup heater off", 0)


def _heater_allowed(snapshot: Snapshot, since: Since) -> Finding:
    """Return the finding for a pump that may use its backup heater for room heating."""
    code = AlarmCode.BACKUP_HEATER_ALLOWED
    value = _number(snapshot, HeishaSignal.ROOM_HEATER_STATE)
    if value is None:
        return _unknown(code, "Room_Heater_State", since)
    if value == 1:
        message = "Room_Heater_State is free: the pump may use its backup heater for heating"
        return Finding(code, MonitorStatus.ACTIVE, message, 1, since.get(code, snapshot.now))
    return Finding(code, MonitorStatus.OK, "backup heater blocked for room heating", 0)


def _heating_off(snapshot: Snapshot, since: Since) -> Finding:
    """Return the finding for an outside temperature at or above the pump's own heating cut-off."""
    code = AlarmCode.HEATING_OFF_OUTDOOR
    outside = _number(snapshot, HeishaSignal.OUTSIDE_TEMP)
    cutoff = _number(snapshot, HeishaSignal.HEATING_OFF_OUTDOOR_TEMP)
    if outside is None or cutoff is None:
        return _unknown(code, "Outside_Temp or Heating_Off_Outdoor_Temp", since)
    threshold = cutoff - HEATING_OFF_HYSTERESIS_K if code in since else cutoff
    message = f"Outside_Temp {outside:.0f} °C against the pump's heating cut-off of {cutoff:.0f} °C"
    if outside >= threshold:
        return Finding(code, MonitorStatus.ACTIVE, message, outside, since.get(code, snapshot.now))
    return Finding(code, MonitorStatus.OK, message, outside)


def _defrost_limit(config: MonitorConfig, deice: DeiceOnset | None) -> float:
    """Return the longest allowed defrost in seconds, extended to the expected de-ice limit."""
    return max(config.defrost_max_s, deice.limit_s) if deice is not None else config.defrost_max_s


def _defrost(
    config: MonitorConfig, snapshot: Snapshot, since: Since, deice: DeiceOnset | None
) -> Finding:
    """Return the finding for a defrost that runs longer than its limit.

    Parameters
    ----------
    config
        Monitor limits.
    snapshot
        Current signal readings.
    since
        When each condition was first seen.
    deice
        Defrost onset, ``None`` outside a defrost.
    """
    code = AlarmCode.DEFROST_STUCK
    defrost = defrost_active(snapshot).value
    if defrost is None:
        return _unknown(code, "Defrosting_State", since)
    limit = _defrost_limit(config, deice)
    message = f"defrost running (limit {limit / 60:.0f} min)"
    return _sustained(code, defrost, since, snapshot.now, limit, message, int(defrost))


def room_floor(
    config: MonitorConfig,
    room_shift_k: float | None = None,
    lowered_target_c: float | None = None,
) -> float | None:
    """Return the comfort floor in force at a room-target shift.

    Parameters
    ----------
    config
        Thresholds (the static floor and the largest set-back it follows).
    room_shift_k
        Shift of the room target the controller applies (its effective target minus
        comfort); ``None`` without one.
    lowered_target_c
        A manual room target below comfort (away or a cooler boost); ``None`` without one.

    Returns
    -------
    float or None
        The static floor lowered by a negative shift, by at most
        ``room_setback_max_k``; a positive or missing shift keeps the static floor. A
        manual target lowers it further to that target minus ``room_floor_k``.
        ``None`` when the monitor is disabled.
    """
    if config.room_floor_c is None:
        return None
    floor = config.room_floor_c
    if room_shift_k is not None and math.isfinite(room_shift_k):
        floor += max(-config.room_setback_max_k, min(0.0, room_shift_k))
    if (
        lowered_target_c is not None
        and config.room_floor_k is not None
        and math.isfinite(lowered_target_c)
    ):
        floor = min(floor, lowered_target_c - config.room_floor_k)
    return floor


def _room(
    config: MonitorConfig, snapshot: Snapshot, since: Since, floor: float | None
) -> Finding | None:
    """Return the comfort-floor finding against ``floor`` (``None`` when disabled).

    Parameters
    ----------
    config
        Monitor limits.
    snapshot
        Current signal readings.
    since
        When each condition was first seen.
    floor
        Comfort floor in °C now in force, lowered by a set-back.
    """
    code = AlarmCode.ROOM_BELOW_FLOOR
    if config.room_signal is None or config.room_floor_c is None or floor is None:
        return None
    room = _number(snapshot, config.room_signal)
    if room is None:
        return _unknown(code, "room temperature", since)
    message = f"room {room:.1f} °C against a comfort floor of {floor:.1f} °C"
    if floor < config.room_floor_c:
        setback = config.room_floor_c - floor
        message += f" ({config.room_floor_c:.1f} °C lowered by the {setback:.1f} K set-back)"
    return _sustained(
        code, room < floor, since, snapshot.now, config.room_floor_sustain_s, message, room
    )


def _starts(
    config: MonitorConfig, snapshot: Snapshot, since: Since, counts: StartCounts | None
) -> Finding | None:
    """Return the ``compressor_starts`` finding (``None`` when the monitor is off).

    Parameters
    ----------
    config
        Monitor limits.
    snapshot
        Current signal readings.
    since
        When each condition was first seen.
    counts
        Compressor starts in the last hour and day, ``None`` when not counted.
    """
    hour_max, day_max = config.starts_per_hour_max, config.starts_per_day_max
    if hour_max is None or day_max is None or counts is None:
        return None
    code = AlarmCode.COMPRESSOR_STARTS
    why = starts_exceeded(counts, hour_max, day_max)
    if why is None:
        message = (
            f"{counts.last_hour} compressor starts in the last hour, {counts.last_day} in 24 h "
            f"(limits {hour_max} per hour, {day_max} per day)"
        )
        return Finding(code, MonitorStatus.OK, message, counts.last_hour)
    return Finding(code, MonitorStatus.ACTIVE, why, counts.last_hour, since.get(code, snapshot.now))


def _room_sensor(config: MonitorConfig, snapshot: Snapshot, since: Since) -> Finding | None:
    """Return the finding for a silent or overdue room sensor, or ``None`` without a room profile.

    Parameters
    ----------
    config
        Monitor limits.
    snapshot
        Current signal readings.
    since
        When each condition was first seen.
    """
    if config.room_signal is None or config.room_profile is None:
        return None
    view = snapshot.get(config.room_signal)
    if config.room_profile is RoomProfile.ON_CHANGE:
        code = AlarmCode.ROOM_SENSOR_SILENT
        limit = config.room_silence_limit_s
        what = "no report from the room sensor or its liveness signals"
    else:
        code = AlarmCode.ROOM_REPORT_OVERDUE
        limit = OVERDUE_FACTOR * config.room_report_interval_s
        what = (
            "periodic room sensor profile configured but no report; if the sensor "
            "reports only on change, set OVENBIRD_CONTROL_ROOM_PROFILE=on_change"
        )
    if view is None or view.age is None:
        return _unknown(code, "room sensor report", since)
    message = f"{what} for {view.age / 60:.0f} min (limit {limit / 60:.0f} min)"
    if view.age > limit:
        return Finding(code, MonitorStatus.ACTIVE, message, view.age, since.get(code, snapshot.now))
    return Finding(code, MonitorStatus.OK, f"last report {view.age / 60:.0f} min ago", view.age)


UNIT_REASON: Final = f"{ParseErrorKind.UNIT.value}: "


def _room_unit(config: MonitorConfig, snapshot: Snapshot, since: Since) -> Finding | None:
    """Return the finding for a Home Assistant room value refused for its unit, or ``None``."""
    if config.room_signal is None or not config.room_signal.startswith(HA_SIGNAL_PREFIX):
        return None
    code = AlarmCode.ROOM_UNIT_REFUSED
    view = snapshot.get(config.room_signal)
    reason = None if view is None else view.reason
    if reason is not None and reason.startswith(UNIT_REASON):
        message = f"room value refused: {reason[len(UNIT_REASON) :]}"
        return Finding(code, MonitorStatus.ACTIVE, message, None, since.get(code, snapshot.now))
    return Finding(code, MonitorStatus.OK, "room value unit accepted", None)


def _ha_link(config: MonitorConfig, snapshot: Snapshot, since: Since) -> Finding | None:
    """Return the finding for a down Home Assistant link, or ``None`` when HA is not used."""
    if not config.ha_enabled:
        return None
    code = AlarmCode.HA_LINK_DOWN
    up = snapshot.links.get(SourceKind.HA, False)
    message = (
        "Home Assistant link up"
        if up
        else "Home Assistant link down (no connection or no successful get_states re-read); "
        "held room values fall back to the 1800 s limit"
    )
    return _sustained(code, not up, since, snapshot.now, config.ha_link_sustain_s, message, int(up))


def _bounds(
    code: AlarmCode,
    config: MonitorConfig,
    snapshot: Snapshot,
    deice: DeiceOnset | None,
    floor: float | None,
) -> tuple[float | None, str | None, Direction | None]:
    """Return a monitor's limit, its unit and direction (``floor``: the comfort floor).

    Parameters
    ----------
    code
        Alarm whose limit is wanted.
    config
        Monitor limits.
    snapshot
        Current signal readings (for limits the pump reports).
    deice
        Defrost onset, for the defrost limit.
    floor
        Comfort floor in °C now in force.
    """
    match code:
        case AlarmCode.SETPOINT_ABOVE_MAX:
            return float(config.max_setpoint), "°C", "above"
        case AlarmCode.OUTLET_OVERSHOOT:
            return config.max_supply_c + config.outlet_margin_k, "°C", "above"
        case AlarmCode.LOW_FLOW | AlarmCode.LOW_FLOW_DEFROST:
            return config.min_flow_lpm, "l/min", "below"
        case AlarmCode.HEATING_OFF_OUTDOOR:
            return _number(snapshot, HeishaSignal.HEATING_OFF_OUTDOOR_TEMP), "°C", "above"
        case AlarmCode.DEFROST_STUCK:
            return _defrost_limit(config, deice), "s", "above"
        case AlarmCode.ROOM_BELOW_FLOOR:
            return floor, "°C", "below"
        case AlarmCode.ROOM_SENSOR_SILENT:
            return config.room_silence_limit_s, "s", "above"
        case AlarmCode.ROOM_REPORT_OVERDUE:
            return OVERDUE_FACTOR * config.room_report_interval_s, "s", "above"
        case AlarmCode.COMPRESSOR_STARTS:
            limit = config.starts_per_hour_max
            return (None if limit is None else float(limit)), "starts/h", "above"
        case _:
            return None, None, None


def _with_bounds(
    finding: Finding,
    config: MonitorConfig,
    snapshot: Snapshot,
    deice: DeiceOnset | None,
    floor: float | None,
) -> Finding:
    """Return ``finding`` with its monitor's limit, unit and direction.

    Parameters
    ----------
    finding
        Finding to complete.
    config
        Monitor limits.
    snapshot
        Current signal readings.
    deice
        Defrost onset, for the defrost limit.
    floor
        Comfort floor in °C now in force.
    """
    limit, unit, direction = _bounds(finding.code, config, snapshot, deice, floor)
    return replace(finding, limit=limit, unit=unit, direction=direction)


def evaluate(
    config: MonitorConfig,
    snapshot: Snapshot,
    since: Since,
    *,
    desired_setpoint: int | None = None,
    deice: DeiceOnset | None = None,
    room_shift_k: float | None = None,
    lowered_target_c: float | None = None,
    starts: StartCounts | None = None,
) -> tuple[dict[AlarmCode, Instant], tuple[Finding, ...]]:
    """Run every monitor once.

    Parameters
    ----------
    config
        Thresholds.
    snapshot
        Current state; its ``now`` is the evaluation instant.
    since
        When each condition was first seen, as returned by the previous call.
    desired_setpoint
        The controller's current water setpoint, if any.
    deice
        Model profile and the values at the start of the running defrost (latched
        by :class:`SafetyMonitor`); ``None`` treats the pump as an unknown model.
    room_shift_k
        Shift of the room target the controller applies (a night set-back is
        negative); lowers the comfort floor, see :func:`room_floor`.
    lowered_target_c
        A manual room target below comfort (away, a cooler boost); lowers the floor.
    starts
        Compressor start counts for ``compressor_starts`` (``None``: not evaluated).

    Returns
    -------
    tuple
        The updated first-seen instants (a condition's entry survives ``unknown``
        and is dropped on ``ok``) and one finding per monitor.
    """
    floor = room_floor(config, room_shift_k, lowered_target_c)
    findings = [
        _setpoint(config, snapshot, since, desired_setpoint),
        _outlet(config, snapshot, since),
        _flow(config, snapshot, since),
        _flow_defrost(config, snapshot, since, deice),
        _error(snapshot, since),
        _heater(snapshot, since),
        _heater_allowed(snapshot, since),
        _heating_off(snapshot, since),
        _defrost(config, snapshot, since, deice),
    ]
    for optional in (
        _room(config, snapshot, since, floor),
        _room_sensor(config, snapshot, since),
        _room_unit(config, snapshot, since),
        _ha_link(config, snapshot, since),
        _starts(config, snapshot, since, starts),
    ):
        if optional is not None:
            findings.append(optional)
    findings = [_with_bounds(finding, config, snapshot, deice, floor) for finding in findings]
    updated: dict[AlarmCode, Instant] = {}
    for finding in findings:
        if finding.status in (MonitorStatus.PENDING, MonitorStatus.ACTIVE):
            updated[finding.code] = finding.since or snapshot.now
        elif finding.status is MonitorStatus.UNKNOWN and finding.code in since:
            updated[finding.code] = since[finding.code]
    return updated, tuple(findings)


class SafetySink(Protocol):
    """What the safety monitor tells the command adapter."""

    def safety_update(self, codes: frozenset[AlarmCode], now: Instant) -> None:
        """Receive the active critical safety alarms."""
        ...


class SafetyMonitor:
    """Evaluate the monitors on the service clock and act on the findings.

    Parameters
    ----------
    config
        Thresholds.
    alarms
        Alarm board shared with the adapter.
    runtime
        State store and health.
    adapter
        Receives the active critical alarms; ``None`` without publishing.
    desired
        Returns the controller's current water setpoint.
    room_shift
        Returns the shift of the room target the controller applies (its effective
        target minus comfort, ``None`` without one); lowers the comfort floor during a
        night set-back. ``None``: the static floor.
    lowered_target
        Returns a manual room target below comfort (away, a cooler boost); lowers the
        comfort floor to it. ``None``: no manual target.
    starts
        Counts the compressor starts for ``compressor_starts``; ``None``: not counted.
    interval_s
        Seconds between evaluations.
    sleep
        Sleeps on the service clock.

    Attributes
    ----------
    profile
        Model profile from ``Heat_Pump_Model``; ``None`` for an unknown model.
    deice
        The current (or last) defrost: the profile and the values latched when
        ``Defrosting_State`` turned on.
    """

    def __init__(
        self,
        config: MonitorConfig,
        alarms: AlarmBoard,
        runtime: Runtime,
        *,
        adapter: SafetySink | None = None,
        desired: Callable[[], int | None] | None = None,
        room_shift: Callable[[], float | None] | None = None,
        lowered_target: Callable[[], float | None] | None = None,
        starts: StartCounter | None = None,
        interval_s: float = SAFETY_INTERVAL_S,
        sleep: Sleep | None = None,
    ) -> None:
        self.config = config
        self.alarms = alarms
        self.runtime = runtime
        self.adapter = adapter
        self.desired = desired
        self.room_shift = room_shift
        self.lowered_target = lowered_target
        self.starts = starts
        self.interval_s = interval_s
        self._sleep = sleep
        self._since: dict[AlarmCode, Instant] = {}
        self._logged: set[AlarmCode] = set()
        self._defrosting: bool | None = None
        self._model: object = None
        self.profile: PumpProfile | None = None
        self.deice: DeiceOnset | None = None
        self.findings: tuple[Finding, ...] = ()
        self.evaluations = 0

    def check(self, now: Instant | None = None) -> tuple[Finding, ...]:
        """Evaluate once, update alarms, the adapter and the health check.

        Parameters
        ----------
        now
            Evaluation time; the runtime clock when omitted.

        Returns
        -------
        tuple of Finding
            One finding per monitor.
        """
        moment = now or self.runtime.clock()
        snapshot = self.runtime.store.snapshot(moment)
        desired = self.desired() if self.desired is not None else None
        shift = self.room_shift() if self.room_shift is not None else None
        lowered = self.lowered_target() if self.lowered_target is not None else None
        counts = None
        if self.starts is not None:
            self.starts.observe(snapshot)
            counts = self.starts.counts(moment.wall.timestamp())
        self._latch_deice(snapshot)
        self._since, self.findings = evaluate(
            self.config,
            snapshot,
            self._since,
            desired_setpoint=desired,
            deice=self.deice if self._defrosting else None,
            room_shift_k=shift,
            lowered_target_c=lowered,
            starts=counts,
        )
        for finding in self.findings:
            if self._log_only(finding.code):
                self._journal_only(finding, moment)
                continue
            if finding.code in self._logged:
                self._close_log(finding.code, LOGGED_AS_ALARM, moment)
            if finding.status is MonitorStatus.ACTIVE:
                self.alarms.raise_alarm(finding.code, finding.message, moment)
            elif finding.status is MonitorStatus.OK:
                self.alarms.clear(finding.code, moment, finding.message)
        critical = frozenset(
            finding.code
            for finding in self.findings
            if finding.severity is Severity.CRITICAL and self.alarms.is_active(finding.code)
        )
        if self.adapter is not None:
            self.adapter.safety_update(critical, moment)
        self.evaluations += 1
        level = self.alarms.level()
        self.runtime.alarm_level = "ok" if level is None else level.value
        return self.findings

    def _latch_deice(self, snapshot: Snapshot) -> None:
        """Follow the pump model and defrost onset so the expected de-ice mode is known."""
        view = snapshot.get(HeishaSignal.HEAT_PUMP_MODEL)
        model = view.value if view is not None and view.reason is None else None
        if model is not None and model != self._model:
            self._model = model
            self.profile = profile_for(model)
            name = None if self.profile is None else self.profile.name
            LOGGER.info("pump model %s: profile %s", model, name)
            if self.deice is not None:
                self.deice = replace(self.deice, profile=self.profile)
        defrost = defrost_active(snapshot).value
        if defrost is True and self._defrosting is not True:
            self.deice = DeiceOnset(
                self.profile,
                _number(snapshot, HeishaSignal.INLET_TEMP),
                _number(snapshot, HeishaSignal.OUTSIDE_TEMP),
                snapshot.now,
            )
            LOGGER.info("defrost started: deice mode %s expected", self.deice.mode)
        if defrost is not None:
            self._defrosting = defrost

    def _log_only(self, code: AlarmCode) -> bool:
        """Return whether ``code`` is only journalled, never raised, under the defrost policy."""
        if code is not AlarmCode.LOW_FLOW_DEFROST:
            return False
        mode = None if self.deice is None else self.deice.mode
        match self.config.defrost_low_flow:
            case "alarm":
                return False
            case "log":
                return mode != 1
            case _:
                return mode == 2

    def _journal_only(self, finding: Finding, moment: Instant) -> None:
        """Journal a logged-only finding when it starts and ends, and clear any raised alarm."""
        code = finding.code
        if self.alarms.is_active(code):
            self.alarms.clear(code, moment, LOGGED_ONLY)
        if finding.status is MonitorStatus.ACTIVE and code not in self._logged:
            self._logged.add(code)
            detail = {"logged_only": True, "flow_lpm": finding.value, **self._deice_detail()}
            self._journal(code, AlarmEventKind.STARTED, finding.message, moment, detail)
        elif finding.status is MonitorStatus.OK and code in self._logged:
            self._close_log(code, finding.message, moment)

    def _close_log(self, code: AlarmCode, message: str, moment: Instant) -> None:
        """Journal the end of a logged-only finding."""
        self._logged.discard(code)
        detail = {"logged_only": True, **self._deice_detail()}
        self._journal(code, AlarmEventKind.CLEARED, message, moment, detail)

    def _deice_detail(self) -> dict[str, Any]:
        """Return the de-ice details for journal entries (empty before a defrost)."""
        return {} if self.deice is None else self.deice.detail()

    def _journal(
        self,
        code: AlarmCode,
        kind: AlarmEventKind,
        message: str,
        moment: Instant,
        detail: dict[str, Any],
    ) -> None:
        """Log and record an informational alarm event for a logged-only finding.

        Parameters
        ----------
        code
            Alarm the event is about.
        kind
            Whether it started or cleared.
        message
            Event text.
        moment
            Time of the event.
        detail
            Structured detail of the event.
        """
        LOGGER.warning("%s %s (logged only): %s", code.value, kind.value, message)
        self.alarms.record(AlarmEvent(moment, code.value, Severity.INFO, kind, message, detail))

    def defrost_state(self, snapshot: Snapshot) -> Json:
        """Return the snapshot's ``defrost``: the latched onset while ``snapshot`` defrosts.

        ``active`` follows ``Defrosting_State`` in ``snapshot``; the mode, the start and
        the values at the start come from the onset latched by :meth:`check` and stay
        ``None`` until the next evaluation latched this defrost.
        """
        active = defrost_active(snapshot).value is True
        deice = self.deice if active and self._defrosting is True else None
        if deice is None:
            return defrost_payload(active, max_s=self.config.defrost_max_s)
        return defrost_payload(
            active,
            mode=deice.mode,
            since=None if deice.started is None else iso_z(deice.started.wall),
            inlet_c=deice.inlet_c,
            outside_c=deice.outside_c,
            max_s=_defrost_limit(self.config, deice),
        )

    def status(self) -> dict[str, Any]:
        """Return the API form: overall level and every monitor."""
        level = self.alarms.level()
        overall = "ok" if level is None else level.value
        return {
            "level": "starting" if not self.evaluations else overall,
            "interval_s": self.interval_s,
            "monitors": [finding.to_json() for finding in self.findings],
        }

    async def run(self) -> None:
        """Evaluate forever on the configured interval."""
        if self._sleep is None:
            raise RuntimeError("SafetyMonitor.run needs a sleep function")
        while True:
            self.check()
            await self._sleep(self.interval_s)

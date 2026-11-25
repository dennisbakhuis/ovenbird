"""Configuration of :class:`~ovenbird_core.control.ovenbird.OvenbirdController`.

Presets per emitter type
------------------------
The presets differ in how much thermal mass the emitters add to the loop:

* ``screed_floor``: a screed floor stores many hours of heat and answers a
  setpoint change after hours. Slow outside filter (6 h), gentle PI (Kp 1.5 K/K,
  Ti 10 h), long dwell (20 min), start ramp on, 30 min minimum run.
* ``radiators``: cast-iron or panel radiators answer within the hour. Faster
  filter (2 h), stronger PI (Kp 3 K/K, Ti 3 h), 10 min dwell, start ramp off (low
  mass gains little), 20 min minimum run. Hard maximum 55 °C.
* ``mixed`` (screed floor plus radiators on one loop, no mixing valve): the screed
  sets the hard maximum (40 °C) and dominates the dynamics, the radiators make the
  room answer a little faster. Filter 4 h, Kp 2 K/K, Ti 6 h, 15 min dwell, start
  ramp on, 30 min minimum run.

PI gains are in K water per K room error (``kp``) and the integral time ``ti_s``
(integrator gain ``kp / ti_s``). They are first estimates from the emitter type and
are meant to be refined from the fitted house model.

Room sensor profile
-------------------
:class:`RoomSensorProfile` says how the room sensor reports (``periodic`` or
``on_change``, see :class:`~ovenbird_core.control.types.RoomProfile`), its step,
report interval, silence limit, liveness signals and an optional plausibility
cross-check. It sets the store's staleness rule for the room signal
(:meth:`RoomSensorProfile.policy`) and the controller's guards on a held value
(integrator dead zone, stuck-warm authority decay, cross-check).

Stuck-warm rule (``on_change`` only): the cooling feedback authority is the smaller
of two linear ramps, one on the proof-of-life age (full up to 3 h without any report
of the value or a liveness signal, zero from 8 h) and one on the held time (full up
to 12 h without a value change, zero at the silence limit, 24 h by default). A device
that still reports its humidity keeps its authority for 12 h of an unchanged value;
a device that went silent loses it within 8 h.

Settings
--------
Every user-facing value is declared with :func:`~ovenbird_core.setting.setting`: its
default, range, unit and description live on the field, ``__post_init__`` enforces the
range (:func:`~ovenbird_core.setting.check_settings`) and the service derives its
settings fields from the same metadata. Only the cross-field rules are written out.
The wood-stove settings (:class:`StoveConfig`) live next to the stove logic in
:mod:`ovenbird_core.control.stove` and are re-exported here.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, time
from typing import Any, Final
from zoneinfo import ZoneInfo

from ovenbird_core.control.curve import HeatingCurve
from ovenbird_core.control.safety import (
    ABSOLUTE_MAX_SUPPLY_C,
    ABSOLUTE_MIN_SETPOINT_C,
    EmitterType,
    SafetyLimits,
)
from ovenbird_core.control.stove import (
    STOVE_MAX_BACKOFF_K,
    STOVE_MAX_CROSSCHECK_ALLOW_K,
    STOVE_MAX_ENTER_K,
    STOVE_MAX_FAULT_WINDOW_S,
    STOVE_MAX_MAX_ACTIVE_S,
    STOVE_MAX_MIN_ACTIVE_S,
    STOVE_MAX_REENTRY_HOLD_S,
    STOVE_MAX_RISE_WINDOW_S,
    STOVE_MIN_MAX_ACTIVE_S,
    STOVE_MIN_RISE_WINDOW_S,
    STOVE_REFERENCE_MISSING_SHARE,
    StoveConfig,
)
from ovenbird_core.control.types import RoomProfile
from ovenbird_core.readings import SignalId
from ovenbird_core.setting import check_settings, setting, setting_metadata
from ovenbird_core.store import HA_MAX_AGE_S, StalenessPolicy

__all__ = [
    "ALIVE_DECAY_END_S",
    "ALIVE_DECAY_START_S",
    "CROSSCHECK_SUSTAIN_S",
    "CROSSCHECK_TAU_S",
    "CROSSCHECK_THRESHOLD_K",
    "DECAY_START_S",
    "DIRECT_HEATING_MODE",
    "HEAT_OPERATING_MODE",
    "MAX_SILENCE_LIMIT_S",
    "MIN_DEADBAND_K",
    "ON_CHANGE_STEP_K",
    "PERIODIC_AGE_FACTOR",
    "PERIODIC_STEP_K",
    "REPORT_INTERVAL_S",
    "SILENCE_LIMIT_S",
    "STOVE_MAX_BACKOFF_K",
    "STOVE_MAX_CROSSCHECK_ALLOW_K",
    "STOVE_MAX_ENTER_K",
    "STOVE_MAX_FAULT_WINDOW_S",
    "STOVE_MAX_MAX_ACTIVE_S",
    "STOVE_MAX_MIN_ACTIVE_S",
    "STOVE_MAX_REENTRY_HOLD_S",
    "STOVE_MAX_RISE_WINDOW_S",
    "STOVE_MIN_MAX_ACTIVE_S",
    "STOVE_MIN_RISE_WINDOW_S",
    "STOVE_REFERENCE_MISSING_SHARE",
    "CyclingConfig",
    "OvenbirdConfig",
    "PumpDutyConfig",
    "QuietModeConfig",
    "QuietWindow",
    "RoomFeedbackConfig",
    "RoomSensorProfile",
    "SetpointStageConfig",
    "StartRampConfig",
    "StoveConfig",
    "default_curve",
    "envelope_violations",
    "linear_ramp",
]

MIN_DEADBAND_K: Final = 1.0
_ENVELOPE_TOLERANCE_K: Final = 1e-9
PERIODIC_STEP_K: Final = 0.1
ON_CHANGE_STEP_K: Final = 0.2
REPORT_INTERVAL_S: Final = 300.0
PERIODIC_AGE_FACTOR: Final = 3.0
SILENCE_LIMIT_S: Final = 24 * 3600.0
MAX_SILENCE_LIMIT_S: Final = 7 * 24 * 3600.0
DECAY_START_S: Final = 12 * 3600.0
ALIVE_DECAY_START_S: Final = 3 * 3600.0
ALIVE_DECAY_END_S: Final = 8 * 3600.0
CROSSCHECK_THRESHOLD_K: Final = 1.5
CROSSCHECK_SUSTAIN_S: Final = 2 * 3600.0
CROSSCHECK_TAU_S: Final = 24 * 3600.0
DIRECT_HEATING_MODE: Final = 1
HEAT_OPERATING_MODE: Final = 0
_WEEK_S: Final = 604_800.0
_DAY_S: Final = 86_400.0
_HOUR_S: Final = 3600.0


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def linear_ramp(value: float | None, full_until: float, zero_from: float) -> float:
    """Return 1 up to ``full_until``, 0 from ``zero_from`` and linear in between.

    ``None`` (unknown) counts as full; with ``zero_from <= full_until`` the ramp is a
    step at ``full_until``.
    """
    if value is None or value <= full_until:
        return 1.0
    if value >= zero_from:
        return 0.0
    return max(0.0, min(1.0, (zero_from - value) / (zero_from - full_until)))


@dataclass(frozen=True, slots=True)
class RoomFeedbackConfig:
    """PI room feedback on the water setpoint (the settings are described on the fields)."""

    kp: float = setting(2.0, ge=0.0, le=6.0, unit="K/K", doc="PI gain (K water per K room).")
    ti_s: float = setting(
        6 * 3600.0,
        ge=0.0,
        le=_DAY_S,
        unit="s",
        doc="Integral time (0 disables the integral part).",
    )
    output_limit_k: float = setting(
        3.0, ge=0.0, le=5.0, unit="K", doc="Clamp of the feedback (±, K water)."
    )
    integral_limit_k: float = setting(
        3.0,
        ge=0.0,
        le=5.0,
        unit="K",
        doc="Clamp of the feedback's integrator (±, K water); at most the feedback clamp.",
    )
    max_integration_step_s: float = setting(
        300.0,
        gt=0.0,
        le=_HOUR_S,
        unit="s",
        doc=(
            "Longest interval integrated in one tick, so a gap in ticks never produces "
            "a jump in the integrator."
        ),
    )
    held_step_max_k: float = setting(
        0.4,
        ge=0.0,
        le=5.0,
        unit="K",
        doc=(
            "Largest sensor-step part (kp times the room sensor's step) of the offset held "
            "over the curve while the room value is not trusted."
        ),
    )

    def __post_init__(self) -> None:
        """Validate the gains and limits."""
        check_settings(self)
        _check(
            self.integral_limit_k <= self.output_limit_k,
            "integral limit must be in [0, output_limit_k]",
        )

    @property
    def ki_per_s(self) -> float:
        """Integrator gain in K water per (K room x second)."""
        return 0.0 if self.ti_s == 0.0 else self.kp / self.ti_s


@dataclass(frozen=True, slots=True)
class RoomSensorProfile:
    """How the room sensor reports and how a held value is guarded.

    The settings are described on the fields. The liveness signals and the
    cross-check confirm the room value; the decay settings shape the stuck-warm rule
    (see the module docstring).
    """

    kind: RoomProfile = setting(
        RoomProfile.PERIODIC,
        doc=(
            "How the room sensor reports: ``periodic`` (default; on a schedule or with a "
            "heartbeat, stale after ``max(1800 s, 3 x report interval)``) or "
            "``on_change`` (only when the value moves by one step; held while the device "
            "is alive and the source link is up, up to the silence limit)."
        ),
    )
    step_k: float | None = setting(
        None,
        gt=0.0,
        le=2.0,
        unit="K",
        doc="The sensor's step; unset takes 0.1 K (``periodic``) or 0.2 K (``on_change``).",
    )
    report_interval_s: float = setting(
        REPORT_INTERVAL_S,
        ge=10.0,
        le=_DAY_S,
        unit="s",
        doc="Report or heartbeat interval of a ``periodic`` sensor.",
    )
    silence_limit_s: float = setting(
        SILENCE_LIMIT_S,
        ge=HA_MAX_AGE_S,
        le=MAX_SILENCE_LIMIT_S,
        unit="s",
        doc="An ``on_change`` value without any proof of life for this long is stale.",
    )
    liveness: tuple[SignalId, ...] = setting(
        (),
        doc=(
            "Sibling signals of the room sensor's device whose reports prove it alive "
            "(``ha/<entity_id>`` or an MQTT input's signal)."
        ),
    )
    crosscheck: SignalId | None = setting(
        None,
        doc=(
            "Optional plausibility cross-check of the room value (e.g. "
            "``main/Room_Thermostat_Temp``): a disagreement of more than 1.5 K after a "
            "slowly learned offset for 2 h switches the room feedback off."
        ),
    )
    decay_start_s: float = setting(
        DECAY_START_S,
        ge=0.0,
        le=_WEEK_S,
        unit="s",
        doc=(
            "Held time (no value change) from which the cooling feedback authority "
            "decays (linearly to zero at the silence limit)."
        ),
    )
    alive_decay_start_s: float = setting(
        ALIVE_DECAY_START_S,
        ge=0.0,
        le=_WEEK_S,
        unit="s",
        doc="Proof-of-life age from which the cooling feedback authority decays.",
    )
    alive_decay_end_s: float = setting(
        ALIVE_DECAY_END_S,
        gt=0.0,
        le=_WEEK_S,
        unit="s",
        doc="Proof-of-life age at which the cooling feedback authority reaches zero.",
    )
    crosscheck_threshold_k: float = setting(
        CROSSCHECK_THRESHOLD_K,
        gt=0.0,
        le=10.0,
        unit="K",
        doc="Disagreement (after the learned offset) that counts as implausible.",
    )
    crosscheck_sustain_s: float = setting(
        CROSSCHECK_SUSTAIN_S,
        ge=0.0,
        le=_DAY_S,
        unit="s",
        doc="How long the disagreement must last.",
    )
    crosscheck_tau_s: float = setting(
        CROSSCHECK_TAU_S,
        gt=0.0,
        le=_WEEK_S,
        unit="s",
        doc="Time constant of the learned offset between the two signals.",
    )

    def __post_init__(self) -> None:
        """Validate the profile."""
        object.__setattr__(self, "kind", RoomProfile(self.kind))
        check_settings(self)
        _check(
            self.alive_decay_start_s < self.alive_decay_end_s,
            "alive_decay_start_s must be non-negative and below alive_decay_end_s",
        )

    @property
    def quantum_k(self) -> float:
        """The sensor's step (the profile's default when not set)."""
        if self.step_k is not None:
            return self.step_k
        return ON_CHANGE_STEP_K if self.kind is RoomProfile.ON_CHANGE else PERIODIC_STEP_K

    @property
    def held(self) -> bool:
        """Whether a value is held between reports (``on_change``)."""
        return self.kind is RoomProfile.ON_CHANGE

    @property
    def max_age_s(self) -> float:
        """Age at which the value is stale while the source link is up."""
        if self.held:
            return self.silence_limit_s
        return max(HA_MAX_AGE_S, PERIODIC_AGE_FACTOR * self.report_interval_s)

    def policy(self, base: StalenessPolicy, signal: SignalId) -> StalenessPolicy:
        """Return ``base`` with this profile's staleness rule for ``signal``.

        ``periodic``: a per-signal maximum age of ``max(1800 s, 3 x interval)``.
        ``on_change``: the silence limit, applied only while the source link is up
        (the source default otherwise). Liveness signals confirm the value in both.
        """
        policy = (
            base.with_held(signal, self.silence_limit_s)
            if self.held
            else base.with_override(signal, self.max_age_s)
        )
        return policy.with_liveness(signal, self.liveness) if self.liveness else policy

    def authority(self, held_s: float | None, alive_s: float | None = None) -> float:
        """Share of the cooling feedback allowed for a value held ``held_s``, alive ``alive_s``.

        The smaller of a ramp on the proof-of-life age (full up to
        :attr:`alive_decay_start_s`, zero from :attr:`alive_decay_end_s`) and a ramp on
        the held time (full up to :attr:`decay_start_s`, zero at the silence limit);
        always full for a ``periodic`` sensor. Unknown ages count as full.
        """
        if not self.held:
            return 1.0
        alive = linear_ramp(alive_s, self.alive_decay_start_s, self.alive_decay_end_s)
        held = linear_ramp(held_s, self.decay_start_s, self.silence_limit_s)
        return min(alive, held)


@dataclass(frozen=True, slots=True)
class StartRampConfig:
    """Gentle start after a compressor start.

    For ``hold_s`` seconds of non-defrost run time after a detected start, the
    setpoint is capped just under the outlet temperature (``below_outlet_k``) so
    the compressor stays near its minimum modulation, but the cap never drops
    below ``curve - max_below_curve_k``. Afterwards the cap rises by
    ``release_k_per_h`` until it no longer limits the setpoint. The cap never
    decreases during a ramp, so a defrost (outlet drops) never ramps the setpoint
    down; the ramp clock pauses during defrost. The ramp's first tick ignores the
    dwell time (a start is a pump event, not a setpoint whim); later ramp changes
    wait ``ramp_dwell_s``. The settings are described on the fields.
    """

    enabled: bool = setting(True, doc="Start ramp after a compressor start.")
    hold_s: float = setting(
        15 * 60.0,
        ge=0.0,
        le=_HOUR_S,
        unit="s",
        doc="Tracking phase length in non-defrost run seconds.",
    )
    below_outlet_k: float = setting(
        1.0, ge=0.0, lt=2.0, unit="K", doc="Distance of the cap below the outlet temperature."
    )
    max_below_curve_k: float = setting(
        5.0, ge=0.0, le=10.0, unit="K", doc="Lowest cap relative to the curve."
    )
    release_k_per_h: float = setting(
        4.0, ge=1.0, le=12.0, unit="K/h", doc="Rise rate of the cap after the tracking phase."
    )

    def __post_init__(self) -> None:
        """Validate the ramp parameters."""
        check_settings(self)


@dataclass(frozen=True, slots=True)
class CyclingConfig:
    """Protection against the pump's own stop rule early in a run.

    The pump stops when ``outlet >= setpoint + stop_delta_k`` for about three
    minutes. Within ``min_run_s`` of a detected start, the setpoint is kept at or
    above ``outlet - stop_delta_k + margin_k`` (bypassing deadband and dwell), but
    never more than ``max_raise_k`` above the unconstrained setpoint. A decrease
    inside the window must leave ``decrease_headroom_k`` more room than a raise,
    so the outlet's 0.25-0.5 K jitter cannot flip the setpoint between the two.
    This is an approximation: the rule's timer and the firmware's exact hysteresis
    are not observable, so the margins stand in for both. The settings are described
    on the fields.
    """

    enabled: bool = setting(True, doc="Protection against the pump's stop rule early in a run.")
    min_run_s: float = setting(
        30 * 60.0, ge=0.0, le=_HOUR_S, unit="s", doc="Minimum-run window after a start."
    )
    stop_delta_k: float = setting(
        2.0, gt=0.0, le=10.0, unit="K", doc="Overshoot at which the pump stops."
    )
    margin_k: float = setting(
        0.5,
        ge=0.0,
        le=10.0,
        unit="K",
        doc="Safety margin below that overshoot (below ``stop_delta_k``).",
    )
    max_raise_k: float = setting(
        3.0, ge=0.0, le=10.0, unit="K", doc="Largest raise above the unconstrained setpoint."
    )
    decrease_headroom_k: float = setting(
        0.5, ge=0.0, le=5.0, unit="K", doc="Extra distance to the floor a decrease must keep."
    )

    def __post_init__(self) -> None:
        """Validate the cycling parameters."""
        check_settings(self)
        _check(self.margin_k < self.stop_delta_k, "margin_k must be in [0, stop_delta_k)")


@dataclass(frozen=True, slots=True)
class SetpointStageConfig:
    """Rounding, deadband and dwell between the continuous and the issued setpoint.

    The integer setpoint keeps its value while the continuous one stays within
    ``0.5 + rounding_hysteresis_k`` of it. The settings are described on the fields.
    """

    rounding_hysteresis_k: float = setting(
        0.25,
        ge=0.0,
        lt=0.5,
        unit="K",
        doc="Hysteresis of the rounding to the integer setpoint.",
    )
    deadband_k: float = setting(
        1.0,
        ge=MIN_DEADBAND_K,
        le=3.0,
        unit="K",
        doc="Smallest worthwhile setpoint change.",
    )
    dwell_s: float = setting(
        15 * 60.0,
        ge=0.0,
        le=7200.0,
        unit="s",
        doc="Minimum time between setpoint changes.",
    )
    ramp_dwell_s: float = setting(
        3 * 60.0,
        ge=0.0,
        le=_HOUR_S,
        unit="s",
        doc="Minimum time between changes while a start ramp runs.",
    )

    def __post_init__(self) -> None:
        """Validate the stage parameters."""
        check_settings(self)

    @property
    def change_threshold_k(self) -> float:
        """Continuous distance from the issued setpoint at which it changes."""
        return max(self.deadband_k, 0.5 + self.rounding_hysteresis_k)


@dataclass(frozen=True, slots=True)
class PumpDutyConfig:
    """Optional ``max_pump_duty`` intent.

    The heat value applies while the compressor runs or defrosts and is never
    lowered then (a higher reported value is kept). The idle value applies once
    the compressor has been stopped for ``idle_delay_s``; idle circulation never
    stops. The settings are described on the fields.
    """

    heat: int = setting(
        159, ge=1, le=254, doc="Maximum pump duty while the compressor runs or defrosts."
    )
    idle: int = setting(102, ge=1, le=254, doc="Maximum pump duty while the compressor is idle.")
    idle_delay_s: float = setting(
        300.0,
        ge=0.0,
        le=_HOUR_S,
        unit="s",
        doc="Wait after a compressor stop before lowering the duty to the idle value.",
    )

    def __post_init__(self) -> None:
        """Validate the duty values."""
        check_settings(self)
        _check(self.idle <= self.heat, "pump duty must satisfy 1 <= idle <= heat <= 254")


@dataclass(frozen=True, slots=True)
class QuietWindow:
    """A daily window with a quiet-mode level (``end < start`` wraps midnight).

    Parameters
    ----------
    start, end
        Local start (inclusive) and end (exclusive) times.
    level
        Quiet mode level 1-3.
    """

    start: time
    end: time
    level: int

    def __post_init__(self) -> None:
        """Validate the level."""
        _check(1 <= self.level <= 3, "quiet level must be 1-3")

    def contains(self, moment: time) -> bool:
        """Whether local time ``moment`` falls in the window."""
        if self.start <= self.end:
            return self.start <= moment < self.end
        return moment >= self.start or moment < self.end


@dataclass(frozen=True, slots=True)
class QuietModeConfig:
    """Quiet-mode schedule hook (off unless configured).

    Parameters
    ----------
    windows
        Daily windows; the first match wins, level 0 outside all windows.
    timezone
        Setting, described on the field.
    """

    windows: tuple[QuietWindow, ...] = ()
    timezone: str = setting("UTC", doc="IANA zone of the quiet windows.")

    def __post_init__(self) -> None:
        """Validate the zone name."""
        ZoneInfo(self.timezone)

    def level_at(self, wall: datetime) -> int:
        """Return the scheduled quiet level at wall-clock time ``wall``."""
        local = wall.astimezone(ZoneInfo(self.timezone)).time()
        return next((w.level for w in self.windows if w.contains(local)), 0)


def default_curve(emitter: EmitterType) -> HeatingCurve:
    """Return the preset heating curve for ``emitter``.

    The mixed curve is a typical low-temperature curve for underfloor heating with
    some radiators, as a weather-dependent curve is often set (about 34 °C at 0 °C and
    25 °C at 15 °C), extended to -10 °C with a flatter cold end.
    """
    match emitter:
        case EmitterType.SCREED_FLOOR:
            return HeatingCurve.of((-10.0, 36.0), (0.0, 31.0), (15.0, 24.0))
        case EmitterType.RADIATORS:
            return HeatingCurve.of((-10.0, 50.0), (0.0, 43.0), (15.0, 30.0))
        case EmitterType.MIXED:
            return HeatingCurve.of((-10.0, 39.0), (0.0, 34.0), (15.0, 25.0))


DEFAULT_OUTSIDE_MAX_AGE_S: Final = 1800.0
DEFAULT_OUTSIDE_PLAUSIBLE_MIN_C: Final = -40.0
DEFAULT_OUTSIDE_PLAUSIBLE_MAX_C: Final = 50.0
DEFAULT_OUTSIDE_MAX_DEVIATION_K: Final = 10.0


@dataclass(frozen=True, slots=True)
class OutsideSource:
    """Another outside thermometer for the heating curve than the pump's own sensor.

    Only the weather-dependent base (the curve term, through the outside filter) and
    what depends on the filtered value (the plan) use it. The safety envelope keeps
    the pump's ``main/Outside_Temp``: the HeishaMon fallback rule knows only that
    sensor. While the chosen signal is missing, not fresh or older than
    ``max_age_s``, not a finite number, outside ``plausible_min_c`` ..
    ``plausible_max_c``, or more than ``max_deviation_k`` from the pump's fresh
    reading, the curve falls back to the pump's sensor and its note says why: one
    bad sample never enters the outside filter.

    Parameters
    ----------
    signal
        Signal id of the thermometer (``ha/<entity_id>`` or an MQTT input's signal).
    max_age_s
        A value older than this is stale.
    plausible_min_c, plausible_max_c
        A value outside this range is implausible.
    max_deviation_k
        A value further than this from the pump's own reading is not used.
    """

    signal: SignalId = field(
        metadata=setting_metadata(
            doc=(
                "Outside thermometer for the heating curve (``ha/<entity_id>`` or an MQTT "
                "input's signal); unset uses the pump's sensor."
            )
        )
    )
    max_age_s: float = setting(
        DEFAULT_OUTSIDE_MAX_AGE_S,
        ge=300.0,
        le=86_400.0,
        unit="s",
        doc="A value of the outside thermometer older than this is stale (the pump's is used).",
    )
    plausible_min_c: float = setting(
        DEFAULT_OUTSIDE_PLAUSIBLE_MIN_C,
        ge=-60.0,
        le=0.0,
        unit="°C",
        doc="A value of the outside thermometer below this is implausible (the pump's is used).",
    )
    plausible_max_c: float = setting(
        DEFAULT_OUTSIDE_PLAUSIBLE_MAX_C,
        ge=20.0,
        le=70.0,
        unit="°C",
        doc="A value of the outside thermometer above this is implausible (the pump's is used).",
    )
    max_deviation_k: float = setting(
        DEFAULT_OUTSIDE_MAX_DEVIATION_K,
        ge=2.0,
        le=50.0,
        unit="K",
        doc=(
            "A value of the outside thermometer further than this from the pump's own "
            "outside sensor is not used (the pump's is used)."
        ),
    )

    def __post_init__(self) -> None:
        """Validate the limits and the signal."""
        check_settings(self)
        _check(bool(str(self.signal)), "the outside sensor needs a signal id")


@dataclass(frozen=True, slots=True)
class OvenbirdConfig:
    """Complete configuration of the ovenbird controller.

    Build one with :meth:`preset` and override fields as needed.

    Parameters
    ----------
    emitter
        Emitter type the preset was made for.
    curve
        Heating curve.
    safety
        Safety envelope.
    weather_compensation, fixed_water_c
        Weather-dependent control (WAR): the base water temperature follows
        ``curve``; off, it is ``fixed_water_c`` at every outside temperature.
    comfort_room_c, outside_filter_tau_s, plan_max_water_k, compressor_min_hz
        Settings, described on the fields.
    feedback
        PI room feedback.
    ramp
        Start ramp.
    cycling
        Cycling protection.
    stages
        Rounding, deadband and dwell.
    pump_duty
        Optional max-pump-duty intent; ``None`` disables it.
    quiet
        Optional quiet-mode schedule; ``None`` disables it.
    direct_heating_mode
        ``Heating_Mode`` value the controller requires (Direct).
    allowed_operating_modes
        ``Operating_Mode_State`` values the controller accepts (heat).
    room
        Room sensor profile (staleness of the room value and its guards).
    stove
        Optional wood-stove mode; ``None`` disables it (manual requests included).
    outside
        Optional outside thermometer for the curve; ``None`` uses the pump's sensor.
    """

    emitter: EmitterType
    curve: HeatingCurve
    safety: SafetyLimits
    weather_compensation: bool = setting(
        True,
        doc="Weather-dependent control (WAR): the water follows the heating curve.",
    )
    fixed_water_c: float = setting(
        30.0,
        ge=ABSOLUTE_MIN_SETPOINT_C,
        le=ABSOLUTE_MAX_SUPPLY_C,
        unit="°C",
        doc="Water temperature while weather-dependent control is off.",
    )
    comfort_room_c: float = setting(21.0, ge=5.0, le=30.0, unit="°C", doc="Room target.")
    outside_filter_tau_s: float = setting(
        4 * 3600.0,
        ge=0.0,
        le=_DAY_S,
        unit="s",
        doc="Time constant of the outside-temperature filter.",
    )
    feedback: RoomFeedbackConfig = field(default_factory=RoomFeedbackConfig)
    plan_max_water_k: float = setting(
        5.0,
        ge=0.0,
        le=10.0,
        unit="K",
        doc="Clamp of the plan term when it maps to water directly (no room sensor).",
    )
    ramp: StartRampConfig = field(default_factory=StartRampConfig)
    cycling: CyclingConfig = field(default_factory=CyclingConfig)
    stages: SetpointStageConfig = field(default_factory=SetpointStageConfig)
    pump_duty: PumpDutyConfig | None = None
    quiet: QuietModeConfig | None = None
    direct_heating_mode: int = DIRECT_HEATING_MODE
    allowed_operating_modes: frozenset[int] = frozenset({HEAT_OPERATING_MODE})
    compressor_min_hz: float = setting(
        1.0, gt=0.0, unit="Hz", doc="Lowest compressor frequency counted as running."
    )
    room: RoomSensorProfile = field(default_factory=RoomSensorProfile)
    stove: StoveConfig | None = None
    outside: OutsideSource | None = None

    def __post_init__(self) -> None:
        """Validate the settings and the cross-field constraints."""
        check_settings(self)
        _check(
            self.ramp.max_below_curve_k <= self.safety.envelope_below_k,
            "the start ramp may not reach below the safety envelope",
        )
        outside = envelope_violations(self.curve, self.safety)
        _check(
            not outside,
            "the heating curve leaves the safety envelope at "
            + ", ".join(f"{o:g} °C outside" for o, _ in outside),
        )
        _check(
            self.weather_compensation
            or self.safety.min_setpoint_c <= self.fixed_water_c <= self.safety.max_supply_c,
            "the fixed water temperature must lie between the minimum setpoint and the "
            "maximum supply temperature",
        )

    def base_water(self, outside_c: float) -> float:
        """Return the base water temperature: the curve at ``outside_c``, or the fixed one."""
        if self.weather_compensation:
            return self.curve.water(outside_c)
        return self.fixed_water_c

    def base_sensitivity(self, outside_c: float) -> float:
        """Return ``|d base / d outside|`` (zero while weather-dependent control is off)."""
        return self.curve.sensitivity(outside_c) if self.weather_compensation else 0.0

    @classmethod
    def preset(cls, emitter: EmitterType | str, **overrides: Any) -> OvenbirdConfig:
        """Return the preset for ``emitter`` with ``overrides`` applied.

        Parameters
        ----------
        emitter
            ``screed_floor``, ``radiators`` or ``mixed``.
        **overrides
            Field values replacing the preset's. The safety envelope stays anchored
            to the emitter's preset curve when ``curve`` is overridden, so a curve
            edit can never move its own guard; the curve must lie inside it.

        Returns
        -------
        OvenbirdConfig
            The configuration.
        """
        kind = EmitterType(emitter)
        base = cls(
            emitter=kind,
            curve=default_curve(kind),
            safety=SafetyLimits.for_emitter(kind, default_curve(kind)),
            **_PRESET_FIELDS[kind],
        )
        return replace(base, **overrides) if overrides else base


def envelope_violations(curve: HeatingCurve, safety: SafetyLimits) -> list[tuple[float, float]]:
    """Return where ``curve`` leaves ``[envelope - below, envelope + above]``.

    Both curves are piecewise linear and flat beyond their end points, so their
    difference is extreme only at a break point of either curve; checking those
    covers every outside temperature.

    Parameters
    ----------
    curve
        Heating curve to check.
    safety
        Safety limits with the envelope curve and band.

    Returns
    -------
    list of tuple
        ``(outside_c, distance_k)`` per offending break point; ``distance_k`` is
        how far the curve lies outside the band (negative below it).
    """
    envelope = safety.envelope
    breaks = sorted({p.outside_c for p in (*curve.points, *envelope.points)})
    found: list[tuple[float, float]] = []
    for outside in breaks:
        offset = curve.water(outside) - envelope.water(outside)
        if offset < -safety.envelope_below_k - _ENVELOPE_TOLERANCE_K:
            found.append((outside, offset + safety.envelope_below_k))
        elif offset > safety.envelope_above_k + _ENVELOPE_TOLERANCE_K:
            found.append((outside, offset - safety.envelope_above_k))
    return found


_PRESET_FIELDS: Final[dict[EmitterType, dict[str, Any]]] = {
    EmitterType.SCREED_FLOOR: {
        "outside_filter_tau_s": 6 * 3600.0,
        "feedback": RoomFeedbackConfig(kp=1.5, ti_s=10 * 3600.0),
        "ramp": StartRampConfig(enabled=True, hold_s=20 * 60.0, release_k_per_h=4.0),
        "cycling": CyclingConfig(min_run_s=30 * 60.0),
        "stages": SetpointStageConfig(dwell_s=20 * 60.0, ramp_dwell_s=3 * 60.0),
    },
    EmitterType.RADIATORS: {
        "outside_filter_tau_s": 2 * 3600.0,
        "feedback": RoomFeedbackConfig(kp=3.0, ti_s=3 * 3600.0),
        "ramp": StartRampConfig(enabled=False, hold_s=10 * 60.0, release_k_per_h=6.0),
        "cycling": CyclingConfig(min_run_s=20 * 60.0),
        "stages": SetpointStageConfig(dwell_s=10 * 60.0, ramp_dwell_s=3 * 60.0),
    },
    EmitterType.MIXED: {
        "outside_filter_tau_s": 4 * 3600.0,
        "feedback": RoomFeedbackConfig(kp=2.0, ti_s=6 * 3600.0),
        "ramp": StartRampConfig(enabled=True, hold_s=15 * 60.0, release_k_per_h=4.0),
        "cycling": CyclingConfig(min_run_s=30 * 60.0),
        "stages": SetpointStageConfig(dwell_s=15 * 60.0, ramp_dwell_s=3 * 60.0),
    },
}

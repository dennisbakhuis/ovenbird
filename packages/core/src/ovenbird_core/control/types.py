"""Vocabulary of the control interface: enums, controller inputs and intents.

See ``docs/control-interface.md``. Everything here is immutable and pure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from ovenbird_core.instant import Instant
from ovenbird_core.readings import SignalId
from ovenbird_core.store import Snapshot


class Mode(StrEnum):
    """Operating mode chosen by the owner.

    ``shadow`` and ``auto`` decide identically; whether intents are sent is the
    arbiter's concern. ``manual`` follows a setpoint override only. ``off``
    disables the controller (no intents).
    """

    OFF = "off"
    SHADOW = "shadow"
    AUTO = "auto"
    MANUAL = "manual"


class IntentKind(StrEnum):
    """Pump setting an intent describes."""

    WATER_SETPOINT = "water_setpoint"
    MAX_PUMP_DUTY = "max_pump_duty"
    QUIET_MODE = "quiet_mode"


class LadderLevel(StrEnum):
    """Degradation ladder, from the richest to the most defensive behaviour.

    ``model_plan``: the room feedback with a bounded room-target offset from the
    learned house model; richer than a rule plan (it predicts the house), poorer
    than the optimiser (no prices, no heat-pump model).
    """

    OPTIMISER_PLAN = "optimiser_plan"
    MODEL_PLAN = "model_plan"
    RULE_PLAN = "rule_plan"
    SCHEDULE_CURVE_FEEDBACK = "schedule_curve_feedback"
    CURVE_ONLY = "curve_only"
    HOLD = "hold"
    REFUSE = "refuse"


class ReasonCode(StrEnum):
    """Closed set of reasons a decision or intent was made."""

    CURVE = "curve"
    ROOM_FEEDBACK = "room_feedback"
    START_RAMP = "start_ramp"
    CYCLING_PROTECT = "cycling_protect"
    DEFROST_FREEZE = "defrost_freeze"
    DHW_FREEZE = "dhw_freeze"
    ROOM_STALE = "room_stale"
    ROOM_IMPLAUSIBLE = "room_implausible"
    HEISHAMON_DEAD = "heishamon_dead"
    MODE_MISMATCH = "mode_mismatch"
    MODE_UNKNOWN = "mode_unknown"
    MODE_OFF = "mode_off"
    INPUTS_MISSING = "inputs_missing"
    SAFETY_CLAMP = "safety_clamp"
    DEADBAND_HOLD = "deadband_hold"
    DWELL_HOLD = "dwell_hold"
    OVERRIDE = "override"
    OVERRIDE_MISSING = "override_missing"
    PLAN_PREHEAT = "plan_preheat"
    PLAN_SETBACK = "plan_setback"
    PUMP_DUTY_HEAT = "pump_duty_heat"
    PUMP_DUTY_IDLE = "pump_duty_idle"
    QUIET_SCHEDULE = "quiet_schedule"
    STOVE = "stove"


class RoomProfile(StrEnum):
    """How the room sensor reports, and so how long its value stays usable.

    ``periodic``: on a schedule or with a heartbeat; stale after
    ``max(1800 s, 3 x report interval)``. ``on_change``: only when the value moves
    by one step; the value is held while the device is alive and the source link
    is up, up to a silence limit.
    """

    PERIODIC = "periodic"
    ON_CHANGE = "on_change"


class OverrideKind(StrEnum):
    """What a manual override sets."""

    SETPOINT = "setpoint"
    BOOST = "boost"
    STOVE = "stove"


class PlanSource(StrEnum):
    """Which planner produced a plan slice.

    A ``model`` slice comes from the learned house model
    (:mod:`ovenbird_core.control.planner`). The controller clamps it to the bounds of
    :class:`~ovenbird_core.control.config.ModelPlanConfig`, applies it only as a
    room-target offset of an active room feedback, and ignores it otherwise
    (:class:`ModelPlanBlock`). A model *water* slice (``water_offset_k``) is a bounded
    water feed-forward instead, applied under the same blocks and scaled by the room
    authority.
    """

    OPTIMISER = "optimiser"
    MODEL = "model"
    RULE = "rule"


class ModelPlanBlock(StrEnum):
    """Why the controller ignores an active model plan slice this tick.

    ``room_untrusted``: no trusted room value (missing, stale or implausible), so
    there is no room target to shift (a room-target slice never maps to water) and no
    room to judge a water slice's authority by.
    ``stove_active``: a wood-stove episode is active. ``stove_recovery``: the
    wood-stove detection is still waiting after an episode or a sensor fault (the
    room has not cooled below the exit threshold, or the room value has not been
    trusted again for the re-entry hold). ``slice_too_long``: the slice is valid for
    longer than ``MODEL_PLAN_MAX_SLICE_S``, so a stale plan could outlive its planner.
    """

    ROOM_UNTRUSTED = "room_untrusted"
    STOVE_ACTIVE = "stove_active"
    STOVE_RECOVERY = "stove_recovery"
    SLICE_TOO_LONG = "slice_too_long"


def _require_finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")


@dataclass(frozen=True, slots=True)
class RoomInput:
    """The room temperature the caller chose for control.

    Parameters
    ----------
    value
        Room temperature in °C.
    age
        Seconds since the last proof of life: a report of the value or of one of
        its liveness signals; ``None`` when unknown.
    fresh
        Whether the value is usable (decided by the caller's staleness policy).
    source
        Signal id the value came from.
    reason
        Why it is not usable, when the source invalidated it.
    quantum_k
        The sensor's step: the value is only known to within this much (``0``:
        unknown, no dead zone).
    held_s
        Seconds since the value last changed; ``None`` when unknown.
    alive_by
        Liveness signal that gave the last proof of life, if not the value itself.
    profile
        Reporting profile of the sensor.
    """

    value: float
    age: float | None
    fresh: bool
    source: SignalId
    reason: str | None = None
    quantum_k: float = 0.0
    held_s: float | None = None
    alive_by: SignalId | None = None
    profile: RoomProfile = RoomProfile.PERIODIC

    def __post_init__(self) -> None:
        """Reject non-finite temperatures and a negative quantum."""
        _require_finite("room value", self.value)
        _require_finite("quantum_k", self.quantum_k)
        if self.quantum_k < 0.0:
            raise ValueError("quantum_k must be non-negative")

    @property
    def alive_s(self) -> float | None:
        """Seconds since any proof of life (the same as :attr:`age`)."""
        return self.age


@dataclass(frozen=True, slots=True)
class PlanSlice:
    """Planner output for one interval, expressed as a room-temperature offset.

    A model slice (``PlanSource.MODEL``) may instead carry a water offset: a
    feed-forward on the water setpoint from the forecast sun, which the controller
    bounds and scales by its room authority
    (:meth:`~ovenbird_core.control.config.ModelPlanConfig.authority`). Such a
    *water slice* leaves the room target alone, so it carries no room offset.

    Parameters
    ----------
    room_offset_k
        Offset to the comfort room temperature in K (positive pre-heats).
    reason
        Why the planner chose it (``plan_preheat``, ``plan_setback``, ...).
    valid_from, valid_until
        Half-open interval ``[valid_from, valid_until)`` in which the slice applies.
    source
        Planner that produced it.
    water_offset_k
        Offset to the water setpoint in K (negative lowers); non-zero only on a
        model slice without a room offset.
    """

    room_offset_k: float
    reason: ReasonCode
    valid_from: Instant
    valid_until: Instant
    source: PlanSource = PlanSource.RULE
    water_offset_k: float = 0.0

    def __post_init__(self) -> None:
        """Validate the offsets and the interval."""
        _require_finite("room_offset_k", self.room_offset_k)
        _require_finite("water_offset_k", self.water_offset_k)
        if not self.valid_from < self.valid_until:
            raise ValueError("plan slice interval must be non-empty")
        if self.water_offset_k != 0.0:
            if self.source is not PlanSource.MODEL:
                raise ValueError("only a model plan slice may carry a water offset")
            if self.room_offset_k != 0.0:
                raise ValueError("a model plan slice carries a room or a water offset, not both")

    @property
    def water(self) -> bool:
        """Whether this is a water slice (a non-zero water offset)."""
        return self.water_offset_k != 0.0

    def active(self, now: Instant) -> bool:
        """Whether the slice applies at ``now``."""
        return self.valid_from <= now < self.valid_until


@dataclass(frozen=True, slots=True)
class Override:
    """A manual setpoint, boost or wood-stove request with an optional expiry.

    Parameters
    ----------
    kind
        ``setpoint``: absolute water setpoint in °C; ``boost``: K added to the
        computed water setpoint; ``stove``: wood-stove mode on (``value`` 1) or a
        stop (``value`` 0, which also blocks the automatic detection until the room
        has cooled below its exit threshold).
    value
        The setpoint, boost or stove flag.
    until
        Expiry (exclusive); ``None`` never expires.
    actor
        Who set it (user, token name, ...).
    """

    kind: OverrideKind
    value: float
    until: Instant | None = None
    actor: str = "user"

    def __post_init__(self) -> None:
        """Reject non-finite values."""
        _require_finite("override value", self.value)

    def active(self, now: Instant) -> bool:
        """Whether the override applies at ``now``."""
        return self.until is None or now < self.until


@dataclass(frozen=True, slots=True)
class ActualValue:
    """One pump setting as the pump reports it.

    Parameters
    ----------
    value
        Reported integer value.
    age
        Seconds since it was last confirmed; ``None`` when unknown.
    fresh
        Whether it is usable under the staleness policy.
    signal
        Signal id it was read from.
    """

    value: int
    age: float | None
    fresh: bool
    signal: SignalId


@dataclass(frozen=True, slots=True)
class PumpActual:
    """What the pump currently reports as applied.

    Parameters
    ----------
    water_target
        Zone 1 water target (``Z1_Water_Target_Temp``).
    max_pump_duty
        Configured maximum pump duty.
    quiet_mode
        Quiet mode level.
    heating_mode
        Heating setpoint mode (0 compensation curve, 1 direct).
    operating_mode
        Operating mode (0 heat, ...).
    """

    water_target: ActualValue | None = None
    max_pump_duty: ActualValue | None = None
    quiet_mode: ActualValue | None = None
    heating_mode: ActualValue | None = None
    operating_mode: ActualValue | None = None


@dataclass(frozen=True, slots=True)
class ControlInputs:
    """Everything a controller sees on one tick.

    Parameters
    ----------
    now
        The tick's instant.
    snapshot
        State snapshot with values, ages, freshness and reasons.
    room
        Room temperature chosen by the caller; ``None`` without a room sensor.
    plan
        Planner output for ``now``; ``None`` without a planner.
    mode
        Operating mode.
    override
        Manual setpoint or boost, if any.
    actual
        Pump settings as reported.
    """

    now: Instant
    snapshot: Snapshot
    room: RoomInput | None
    plan: PlanSlice | None
    mode: Mode
    override: Override | None
    actual: PumpActual


@dataclass(frozen=True, slots=True)
class CommandIntent:
    """A desired pump setting (a state, not a command).

    Parameters
    ----------
    kind
        Setting the intent is about.
    value
        Integer value as HeishaMon expects it.
    reason
        Why this value is desired.
    """

    kind: IntentKind
    value: int
    reason: ReasonCode

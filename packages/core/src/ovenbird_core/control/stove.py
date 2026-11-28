"""Wood-stove mode of the ovenbird controller: detection, episode state machine, back-off.

With a :class:`StoveConfig`, a stove heating the room
the sensor is in is detected (the trusted room value at the comfort target plus
``enter_above_k``, or a fast rise of ``rise_k`` within ``rise_window_s`` above the
comfort target, measured from the comfort target or the window's low, whichever is
higher, and only above the level before a dip) or requested (override ``stove``).
An active plan slice that raises the room target lifts these entry thresholds (not the
exit) by its bounded raise, so a room following the raised target is no stove.
While it is active the room PI is frozen with its integrator held at its value from
before the episode (no wind-down, no silent-device rollback), the cross-check keeps
running with its threshold widened by ``crosscheck_allow_k`` (no offset learning; a
latched verdict holds through the episode until the two agree again; its timer
restarts at the entry and after the episode) and the plan is paused; the ``stove``
term lowers the curve by the back-off (``backoff_k``, or down to the safety minimum),
shrunk linearly while a reference room is below its floor and halved while a
configured reference room has no fresh temperature. Start ramp, cycling floor,
rounding, dwell, the
defrost/DHW rules and the safety clamps apply as always, so the pump never switches
off: "off" is the low setpoint. An automatic episode needs a room value that is
trusted with full cooling authority (fresh, plausible, alive, not held too long);
it stays active while that value is above the exit threshold and ends below it after
``min_active_s``, at the hard cap ``max_active_s`` (8 h) or as soon as the room value
loses that trust. After the cap only a new fast rise starts another episode (the level
trigger waits until the room has been below the exit threshold once); after a loss of
trust the room must be trusted again for ``reentry_hold_s`` before an automatic entry;
a manual stop blocks the detection until the room has cooled below the exit threshold.

Plausibility (a sensor failing high is not a stove): a rise of ``fault_step_k`` within
``fault_step_window_s`` (from the window's low, or from the level before a dip when
that is higher) is a sensor fault; it ends an automatic episode (``room_jump``) and
keeps the detection off until the room has been below the exit threshold
(``stove_fault``). With a fresh reference room an automatic entry (and a hand-over)
needs the room ``reference_gap_k`` above it, and an automatic episode ends after
``min_active_s`` once the room is less than half of that above it
(``reference_warm``). A hand-over from a manual episode also needs a room value that
was trusted when the manual episode began.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from ovenbird_core.control.notes import duration_text, signed
from ovenbird_core.control.observe import as_number
from ovenbird_core.control.record import StateValue, Term
from ovenbird_core.control.safety import EPSILON, SafetyBounds
from ovenbird_core.control.state import OvenbirdState, StoveSource, StoveTrigger
from ovenbird_core.control.types import Override, OverrideKind, RoomInput
from ovenbird_core.instant import Instant
from ovenbird_core.readings import SignalId
from ovenbird_core.setting import check_settings, setting
from ovenbird_core.store import SignalView, Snapshot

if TYPE_CHECKING:
    from ovenbird_core.control.config import OvenbirdConfig

CELSIUS: Final = "°C"
REFERENCE_MIN_C: Final = -40.0
REFERENCE_MAX_C: Final = 60.0
STOVE_MAX_ENTER_K: Final = 5.0
STOVE_MAX_BACKOFF_K: Final = 15.0
STOVE_MAX_RISE_WINDOW_S: Final = 3 * 3600.0
STOVE_MIN_RISE_WINDOW_S: Final = 5 * 60.0
STOVE_MAX_MIN_ACTIVE_S: Final = 6 * 3600.0
STOVE_MIN_MAX_ACTIVE_S: Final = 3600.0
STOVE_MAX_MAX_ACTIVE_S: Final = 24 * 3600.0
STOVE_MAX_REENTRY_HOLD_S: Final = 3 * 3600.0
STOVE_REFERENCE_MISSING_SHARE: Final = 0.5
STOVE_MAX_FAULT_WINDOW_S: Final = 3600.0
STOVE_MAX_CROSSCHECK_ALLOW_K: Final = 10.0


@dataclass(frozen=True, slots=True)
class StoveConfig:
    """Wood-stove mode: back off while a stove overheats the room the sensor is in.

    The automatic detection enters when the trusted room value reaches the comfort
    target plus ``enter_above_k``, or (optional) when it rose by ``rise_k`` within
    ``rise_window_s`` while above the comfort target. It stays active while the
    trusted room value is above the entry threshold minus ``exit_hysteresis_k`` and
    ends below it (not before ``min_active_s``), at the hard cap ``max_active_s`` or
    when the room value loses its trust. After the cap only a new fast rise enters
    again until the room has been below the exit threshold once; after a loss of trust
    the value must be trusted again for ``reentry_hold_s``; after a manual stop the
    detection re-arms only once the room has cooled below the exit threshold. A manual
    request (override ``stove``) has its own end.

    While active the room PI is frozen (its integrator held), the plausibility
    cross-check runs with its threshold widened by ``crosscheck_allow_k`` (a stove
    may lift the room far above the cross-check, a sensor stuck further away is still
    flagged) and the water setpoint is the curve lowered by the back-off:
    ``backoff_k`` or, with ``to_minimum``, down to the safety minimum. When the
    optional reference room (``reference``, e.g. the hall) is below
    ``reference_floor_c``, the back-off shrinks linearly to zero at
    ``reference_floor_c - reference_band_k``; a reference without a fresh temperature
    keeps only ``STOVE_REFERENCE_MISSING_SHARE`` (half) of it.

    Plausibility of an automatic episode (a sensor failing high is not a stove): a
    rise of ``fault_step_k`` or more within ``fault_step_window_s`` (counted from the
    lowest value of that window, or from the level before a dip when that is
    higher, so the rebound after airing does not count) is a sensor fault: it ends an
    automatic episode and keeps the detection off until the room has been below the
    exit threshold. With a fresh reference room, an automatic entry needs the room at
    least ``reference_gap_k`` above it, and an automatic episode ends (after
    ``min_active_s``) once the room is less than half of that above it.

    Every field is a setting: its default, range, unit and description are on the
    field (:func:`~ovenbird_core.setting.setting`).
    """

    auto: bool = setting(True, doc="Detect a stove automatically (otherwise only manual starts).")
    enter_above_k: float = setting(
        1.5,
        gt=0.0,
        le=STOVE_MAX_ENTER_K,
        unit="K",
        doc="Detection threshold above the comfort temperature.",
    )
    exit_hysteresis_k: float = setting(
        1.0,
        gt=0.0,
        le=STOVE_MAX_ENTER_K,
        unit="K",
        doc=(
            "How far below the detection threshold the room must cool before an episode "
            "ends (at most the threshold itself)."
        ),
    )
    rise_k: float | None = setting(
        1.0,
        gt=0.0,
        le=STOVE_MAX_ENTER_K,
        unit="K",
        doc=(
            "Fast-rise trigger: a rise of ``rise_k`` within the window above the comfort "
            "temperature also starts an episode; ``None`` disables it."
        ),
    )
    rise_window_s: float = setting(
        30 * 60.0,
        ge=STOVE_MIN_RISE_WINDOW_S,
        le=STOVE_MAX_RISE_WINDOW_S,
        unit="s",
        doc="Window of the fast-rise trigger.",
    )
    backoff_k: float = setting(
        3.0,
        gt=0.0,
        le=STOVE_MAX_BACKOFF_K,
        unit="K",
        doc="How far the water setpoint goes below the curve.",
    )
    to_minimum: bool = setting(
        False, doc="Back off down to the safety minimum instead of by ``backoff_k``."
    )
    min_active_s: float = setting(
        3600.0,
        ge=0.0,
        le=STOVE_MAX_MIN_ACTIVE_S,
        unit="s",
        doc="Shortest automatic episode (a stale room value still ends it).",
    )
    max_active_s: float = setting(
        8 * 3600.0,
        ge=STOVE_MIN_MAX_ACTIVE_S,
        le=STOVE_MAX_MAX_ACTIVE_S,
        unit="s",
        doc=(
            "Hard cap of an episode (an automatic one otherwise lasts while the room stays "
            "above the exit threshold; after the cap only a new fast rise starts another "
            "until the room has cooled)."
        ),
    )
    reentry_hold_s: float = setting(
        900.0,
        ge=0.0,
        le=STOVE_MAX_REENTRY_HOLD_S,
        unit="s",
        doc=(
            "After an episode ended on an untrusted room value: how long the value must be "
            "trusted again before the detection re-enters."
        ),
    )
    reference: SignalId | None = setting(
        None,
        doc=(
            "Optional room that must stay warm (``ha/<entity_id>`` or an MQTT input's "
            "signal, e.g. the hall)."
        ),
    )
    reference_floor_c: float = setting(
        19.0,
        ge=5.0,
        le=30.0,
        unit="°C",
        doc="Below this temperature of the reference room the back-off shrinks.",
    )
    reference_band_k: float = setting(
        1.0,
        gt=0.0,
        le=STOVE_MAX_ENTER_K,
        unit="K",
        doc="The back-off reaches zero at the reference floor minus this band.",
    )
    reference_gap_k: float = setting(
        1.0,
        ge=0.0,
        le=STOVE_MAX_ENTER_K,
        unit="K",
        doc="How far the room must be above a fresh reference room for an automatic entry.",
    )
    fault_step_k: float = setting(
        2.0,
        gt=0.0,
        le=2 * STOVE_MAX_ENTER_K,
        unit="K",
        doc="A rise this large within ``fault_step_window_s`` is a sensor fault.",
    )
    fault_step_window_s: float = setting(
        600.0,
        gt=0.0,
        le=STOVE_MAX_FAULT_WINDOW_S,
        unit="s",
        doc="Window of the sensor-fault step.",
    )
    crosscheck_allow_k: float = setting(
        4.0,
        ge=0.0,
        le=STOVE_MAX_CROSSCHECK_ALLOW_K,
        unit="K",
        doc="Extra disagreement the cross-check tolerates during an episode.",
    )

    def __post_init__(self) -> None:
        """Validate the ranges, then the threshold order and the timer order."""
        check_settings(self)
        if self.exit_hysteresis_k > self.enter_above_k:
            raise ValueError(
                "stove exit_hysteresis_k must be in (0, enter_above_k] (the episode ends at "
                "or above the comfort target)"
            )
        if self.min_active_s > self.max_active_s:
            raise ValueError("stove min_active_s exceeds max_active_s")

    def enter_c(self, comfort_c: float) -> float:
        """Room temperature at which the automatic detection enters."""
        return comfort_c + self.enter_above_k

    def exit_c(self, comfort_c: float) -> float:
        """Room temperature below which an episode ends (and the detection re-arms)."""
        return comfort_c + self.enter_above_k - self.exit_hysteresis_k

    def reference_share(self, reference_c: float | None) -> float:
        """Share of the back-off kept at a reference room temperature.

        1 without a reference room; ``STOVE_REFERENCE_MISSING_SHARE`` when one is
        configured but has no fresh temperature (fail safe: neither the full back-off
        nor none).
        """
        if self.reference is None:
            return 1.0
        if reference_c is None:
            return STOVE_REFERENCE_MISSING_SHARE
        if reference_c >= self.reference_floor_c:
            return 1.0
        low = self.reference_floor_c - self.reference_band_k
        return max(0.0, min(1.0, (reference_c - low) / self.reference_band_k))


class StoveExit(StrEnum):
    """Why a wood-stove episode ended."""

    COOLED = "cooled"
    MAX_ACTIVE = "max_active"
    ROOM_UNTRUSTED = "room_untrusted"
    ROOM_JUMP = "room_jump"
    REFERENCE_WARM = "reference_warm"
    MANUAL_STOP = "manual_stop"
    MANUAL_ENDED = "manual_ended"
    AUTO_OFF = "auto_off"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class StoveStep:
    """The wood-stove state after one tick, with what happened during it.

    The fields up to ``fault`` are carried in
    :class:`~ovenbird_core.control.ovenbird.OvenbirdState` (``stove_*``); ``event``,
    ``ended``, ``rise_k``, ``jump_k``, ``gap_k``, ``gap_short``, ``until`` and
    ``entry_shift_k`` (how far an active plan slice raised the entry thresholds) only
    explain this tick.
    """

    source: StoveSource | None = None
    trigger: StoveTrigger | None = None
    since: float | None = None
    entry_c: float | None = None
    integral_k: float | None = None
    blocked: bool = False
    level_blocked: bool = False
    reentry_wait: bool = False
    trusted_since: float | None = None
    low_c: float | None = None
    low_at: float | None = None
    high_c: float | None = None
    high_at: float | None = None
    predip_c: float | None = None
    step_low_c: float | None = None
    step_low_at: float | None = None
    fault: bool = False
    event: str | None = None
    ended: StoveExit | None = None
    rise_k: float | None = None
    jump_k: float | None = None
    gap_k: float | None = None
    gap_short: bool = False
    until: Instant | None = None
    entry_shift_k: float = 0.0

    @property
    def active(self) -> bool:
        """Whether an episode is active after this tick."""
        return self.source is not None


def stove_cleared(state: OvenbirdState) -> OvenbirdState:
    """Return ``state`` with no episode and every wood-stove field forgotten."""
    return replace(
        state,
        stove_source=None,
        stove_trigger=None,
        stove_since=None,
        stove_entry_c=None,
        stove_integral_k=None,
        stove_blocked=False,
        stove_level_blocked=False,
        stove_reentry_wait=False,
        stove_trusted_since=None,
        stove_low_c=None,
        stove_low_at=None,
        stove_high_c=None,
        stove_high_at=None,
        stove_predip_c=None,
        stove_step_low_c=None,
        stove_step_low_at=None,
        stove_fault=False,
    )


def with_stove(state: OvenbirdState, stove: StoveStep) -> OvenbirdState:
    """Return ``state`` carrying ``stove`` to the next tick (its ``stove_*`` fields)."""
    return replace(
        state,
        stove_source=stove.source,
        stove_trigger=stove.trigger,
        stove_since=stove.since,
        stove_entry_c=stove.entry_c,
        stove_integral_k=stove.integral_k,
        stove_blocked=stove.blocked,
        stove_level_blocked=stove.level_blocked,
        stove_reentry_wait=stove.reentry_wait,
        stove_trusted_since=stove.trusted_since,
        stove_low_c=stove.low_c,
        stove_low_at=stove.low_at,
        stove_high_c=stove.high_c,
        stove_high_at=stove.high_at,
        stove_predip_c=stove.predip_c,
        stove_step_low_c=stove.step_low_c,
        stove_step_low_at=stove.step_low_at,
        stove_fault=stove.fault,
    )


def _fresh_temperature(view: SignalView | None) -> float | None:
    """Return a fresh room temperature in °C (unit °C or unknown, within -40..60 °C)."""
    value = None if view is None or not view.fresh else as_number(view.value)
    if view is None or value is None or view.unit not in (None, CELSIUS):
        return None
    return value if REFERENCE_MIN_C <= value <= REFERENCE_MAX_C else None


def reference_temperature(cfg: OvenbirdConfig, snapshot: Snapshot) -> float | None:
    """Return the reference room's fresh temperature (``None`` without one)."""
    if cfg.stove is not None and cfg.stove.reference is not None:
        return _fresh_temperature(snapshot.get(cfg.stove.reference))
    return None


@dataclass(frozen=True, slots=True)
class _Window:
    """The fast-rise window of the trusted room value: its low, its high, the level before a dip.

    Parameters
    ----------
    low_c, low_at
        Lowest trusted value of the window and when it was seen.
    high_c, high_at
        Highest trusted value of the window and when it was seen.
    predip_c
        The window's high when the current low was taken (the level before a dip).
    """

    low_c: float | None = None
    low_at: float | None = None
    high_c: float | None = None
    high_at: float | None = None
    predip_c: float | None = None


@dataclass(frozen=True, slots=True)
class _Reading:
    """What one tick's room value means for the state machine, before any transition.

    Parameters
    ----------
    value
        The room value when it is trusted with full cooling authority, else ``None``.
    entry_base
        The comfort target raised by the entry shift (the base of the entry thresholds).
    enter_c
        Level threshold of the automatic entry.
    shift_k
        The entry shift, at least 0.
    window
        The fast-rise window after this tick's value.
    rise
        Rise of the value over the window's low (or the entry base when higher).
    jump
        Sensor-fault step of this tick (:func:`fault_step`).
    step_low_c, step_low_at
        The fault-step window's new low.
    jumped
        The step is a sensor fault.
    cooled
        The value is below the exit threshold.
    gap
        How far the value is above a fresh reference room.
    gap_short
        The gap is too small for an automatic entry.
    reference_warm
        The gap is small enough to end an automatic episode.
    """

    value: float | None
    entry_base: float
    enter_c: float
    shift_k: float
    window: _Window
    rise: float | None
    jump: float | None
    step_low_c: float | None
    step_low_at: float | None
    jumped: bool
    cooled: bool
    gap: float | None
    gap_short: bool
    reference_warm: bool


def advance(
    cfg: OvenbirdConfig,
    state: OvenbirdState,
    room: RoomInput | None,
    override: Override | None,
    now: float,
    reference_c: float | None = None,
    entry_shift_k: float = 0.0,
) -> StoveStep:
    """Advance the wood-stove state machine (see the module docstring).

    ``entry_shift_k`` (≥ 0, the raise of the room target by an active plan slice)
    lifts the automatic entry: the level threshold, the floor of the fast rise and
    the level a fast rise must exceed move up with the target, so a room that
    follows a raised target (plus sun) is no stove. Exit, re-arm and fault
    thresholds keep the comfort temperature; with ``0`` nothing changes.

    ``room`` is the fresh, plausible room value; the automatic detection uses it
    only with full cooling authority (alive, not held too long). A manual
    request (override ``stove``, value > 0) starts or keeps an episode; a stop
    (value 0) ends it and blocks the detection until the room has cooled below
    the exit threshold. When a manual episode ends while the room is still above
    that threshold, the automatic detection takes it over (not after a sensor
    fault, not on a value that was not trusted when the manual episode began, and
    only with the room clearly above a fresh reference room). After
    ``max_active_s`` only a new fast rise (the window restarts at the exit) enters
    again until the room has cooled; after a loss of trust the value must stay
    trusted for ``reentry_hold_s`` first. A sensor-fault step ends an automatic
    episode and keeps the detection off until the room has cooled.

    Parameters
    ----------
    cfg
        Controller configuration (``cfg.stove`` ``None``: stove mode off).
    state
        Carried controller state with the ``stove_*`` fields of the last tick.
    room
        The fresh, plausible room value, ``None`` without one.
    override
        The active override; only a ``stove`` override counts.
    now
        Monotonic time of this tick in seconds.
    reference_c
        Fresh temperature of the reference room, ``None`` without one.
    entry_shift_k
        Raise of the room target by an active plan slice (negative counts as 0).

    Returns
    -------
    StoveStep
        The state after this tick with what happened during it.
    """
    sc = cfg.stove
    if sc is None:
        return _disabled(state)
    reading = _read(cfg, sc, state, room, now, reference_c, entry_shift_k)
    request = _stove_request(override)
    stove = _carried(sc, state, reading, now)
    stove = _episode(sc, state, stove, reading, request, now)
    if request is None and not stove.active and stove.ended is None:
        stove = _detected(sc, state, stove, reading, now)
    if request is not None and stove.active:
        stove = replace(stove, until=request.until)
    return stove


def _disabled(state: OvenbirdState) -> StoveStep:
    """Return the step without stove mode: a carried episode ends (``disabled``)."""
    if state.stove_active:
        return StoveStep(event="exited", ended=StoveExit.DISABLED)
    return StoveStep()


def _stove_request(override: Override | None) -> Override | None:
    """Return ``override`` when it is a wood-stove request or stop, else ``None``."""
    if override is not None and override.kind is OverrideKind.STOVE:
        return override
    return None


def _read(
    cfg: OvenbirdConfig,
    sc: StoveConfig,
    state: OvenbirdState,
    room: RoomInput | None,
    now: float,
    reference_c: float | None,
    entry_shift_k: float,
) -> _Reading:
    """Read this tick's room value against the thresholds, the windows and the reference.

    Parameters
    ----------
    cfg
        Controller configuration.
    sc
        Its stove configuration.
    state
        Carried controller state.
    room
        The fresh, plausible room value, ``None`` without one.
    now
        Monotonic time of this tick in seconds.
    reference_c
        Fresh temperature of the reference room, ``None`` without one.
    entry_shift_k
        Raise of the room target by an active plan slice.

    Returns
    -------
    _Reading
        The facts every transition of this tick decides on.
    """
    comfort = cfg.comfort_room_c
    shift_k = max(0.0, entry_shift_k)
    entry_base = comfort + shift_k
    trusted = room is not None and cfg.room.authority(room.held_s, room.age) >= 1.0
    value = room.value if trusted and room is not None else None
    window = _rise_window(sc, state, value, now)
    jump, step_low_c, step_low_at = fault_step(cfg, state, room, now)
    rise = None if value is None or window.low_c is None else value - max(window.low_c, entry_base)
    gap = None if value is None or reference_c is None else value - reference_c
    return _Reading(
        value=value,
        entry_base=entry_base,
        enter_c=sc.enter_c(entry_base),
        shift_k=shift_k,
        window=window,
        rise=rise,
        jump=jump,
        step_low_c=step_low_c,
        step_low_at=step_low_at,
        jumped=jump is not None and jump >= sc.fault_step_k - EPSILON,
        cooled=value is not None and value < sc.exit_c(comfort) - EPSILON,
        gap=gap,
        gap_short=gap is not None and gap < sc.reference_gap_k - EPSILON,
        reference_warm=gap is not None and gap < sc.reference_gap_k / 2.0 - EPSILON,
    )


def _rise_window(sc: StoveConfig, state: OvenbirdState, value: float | None, now: float) -> _Window:
    """Return the fast-rise window after ``value`` (empty without a trusted value).

    A high or low older than ``rise_window_s`` is replaced by the value; a new low
    takes the window's high as the level before the dip.

    Parameters
    ----------
    sc
        Stove configuration.
    state
        Carried controller state with the last window.
    value
        The trusted room value, ``None`` without one.
    now
        Monotonic time of this tick in seconds.
    """
    if value is None:
        return _Window()
    window_s = sc.rise_window_s
    high_c, high_at = state.stove_high_c, state.stove_high_at
    if high_c is None or high_at is None or value >= high_c or now - high_at > window_s:
        high_c, high_at = value, now
    low_c, low_at, predip_c = state.stove_low_c, state.stove_low_at, state.stove_predip_c
    if low_c is None or low_at is None or value <= low_c or now - low_at > window_s:
        low_c, low_at, predip_c = value, now, high_c
    return _Window(low_c, low_at, high_c, high_at, predip_c)


def _reentry(
    sc: StoveConfig, state: OvenbirdState, value: float | None, now: float
) -> tuple[bool, float | None]:
    """Return the re-entry wait and since when the room value has been trusted again.

    The wait counts trusted ticks from the first one, restarts on an untrusted one
    and ends after ``reentry_hold_s``.

    Parameters
    ----------
    sc
        Stove configuration.
    state
        Carried controller state with the last wait.
    value
        The trusted room value, ``None`` without one.
    now
        Monotonic time of this tick in seconds.
    """
    if not state.stove_reentry_wait:
        return False, state.stove_trusted_since
    if value is None:
        return True, None
    trusted_since = now if state.stove_trusted_since is None else state.stove_trusted_since
    if now - trusted_since >= sc.reentry_hold_s - EPSILON:
        return False, None
    return True, trusted_since


def _carried(sc: StoveConfig, state: OvenbirdState, reading: _Reading, now: float) -> StoveStep:
    """Return the carried episode with this tick's windows, blocks and re-entry wait.

    A manual-stop block, a level block and a sensor fault clear once the room has
    cooled; a new fault-step sets the fault.

    Parameters
    ----------
    sc
        Stove configuration.
    state
        Carried controller state.
    reading
        This tick's reading.
    now
        Monotonic time of this tick in seconds.
    """
    reentry_wait, trusted_since = _reentry(sc, state, reading.value, now)
    window = reading.window
    return StoveStep(
        source=state.stove_source,
        trigger=state.stove_trigger,
        since=state.stove_since,
        entry_c=state.stove_entry_c,
        integral_k=state.stove_integral_k,
        blocked=state.stove_blocked and not reading.cooled,
        level_blocked=state.stove_level_blocked and not reading.cooled,
        reentry_wait=reentry_wait,
        trusted_since=trusted_since,
        low_c=window.low_c,
        low_at=window.low_at,
        high_c=window.high_c,
        high_at=window.high_at,
        predip_c=window.predip_c,
        step_low_c=reading.step_low_c,
        step_low_at=reading.step_low_at,
        fault=reading.jumped or (state.stove_fault and not reading.cooled),
        rise_k=reading.rise,
        jump_k=reading.jump,
        gap_k=reading.gap,
        gap_short=reading.gap_short,
        entry_shift_k=reading.shift_k,
    )


def _episode(
    sc: StoveConfig,
    state: OvenbirdState,
    stove: StoveStep,
    reading: _Reading,
    request: Override | None,
    now: float,
) -> StoveStep:
    """Apply this tick's transition of the episode: manual stop, start, end or automatic exit.

    Parameters
    ----------
    sc
        Stove configuration.
    state
        Carried controller state.
    stove
        The carried step (:func:`_carried`).
    reading
        This tick's reading.
    request
        The wood-stove override, ``None`` without one.
    now
        Monotonic time of this tick in seconds.

    Returns
    -------
    StoveStep
        The step after the transition; without an episode its episode fields are empty.
    """
    if request is not None and request.value <= 0.0:
        return _manual_stop(stove)
    if request is not None:
        return _manual_start(state, stove, reading, now)
    if stove.source is StoveSource.MANUAL:
        return _manual_end(sc, stove, reading, now)
    if stove.source is StoveSource.AUTO:
        return _auto_episode(sc, stove, reading, now)
    return _inactive(stove)


def _inactive(stove: StoveStep, ended: StoveExit | None = None) -> StoveStep:
    """Return ``stove`` without an episode, ``ended`` for the reason one just ended."""
    return replace(
        stove,
        source=None,
        trigger=None,
        since=None,
        entry_c=None,
        integral_k=None,
        ended=ended,
        event=None if ended is None else "exited",
    )


def _manual_stop(stove: StoveStep) -> StoveStep:
    """End an episode on a stop and block the detection until the room has cooled."""
    ended = StoveExit.MANUAL_STOP if stove.active else None
    return _inactive(replace(stove, blocked=True), ended)


def _manual_start(
    state: OvenbirdState, stove: StoveStep, reading: _Reading, now: float
) -> StoveStep:
    """Start a manual episode, or make the active one manual (keeping its trigger and start).

    Parameters
    ----------
    state
        Carried controller state (its integrator is held).
    stove
        The step so far this tick.
    reading
        This tick's reading.
    now
        Monotonic time of this tick in seconds.
    """
    if stove.active:
        return replace(stove, source=StoveSource.MANUAL)
    return replace(
        stove,
        source=StoveSource.MANUAL,
        trigger=StoveTrigger.MANUAL,
        since=now,
        entry_c=reading.value,
        integral_k=state.integral_k,
        event="entered",
    )


def _manual_end(sc: StoveConfig, stove: StoveStep, reading: _Reading, now: float) -> StoveStep:
    """End a manual episode whose request is gone, or hand a warm room to the detection.

    Parameters
    ----------
    sc
        Stove configuration.
    stove
        The step so far this tick (a manual episode).
    reading
        This tick's reading.
    now
        Monotonic time of this tick in seconds.
    """
    if _can_hand_over(sc, stove, reading):
        return replace(stove, source=StoveSource.AUTO, trigger=StoveTrigger.HANDOVER, since=now)
    return _inactive(stove, StoveExit.MANUAL_ENDED)


def _can_hand_over(sc: StoveConfig, stove: StoveStep, reading: _Reading) -> bool:
    """Whether the detection may take over an ending manual episode.

    It needs the detection on, a trusted value that is still warm, a room value
    that was trusted when the manual episode began, no block, no sensor fault and
    the room clearly above a fresh reference room.
    """
    return (
        sc.auto
        and reading.value is not None
        and stove.entry_c is not None
        and not reading.cooled
        and not stove.blocked
        and not stove.fault
        and not reading.gap_short
    )


def _auto_episode(sc: StoveConfig, stove: StoveStep, reading: _Reading, now: float) -> StoveStep:
    """Keep an automatic episode or end it; set the wait or block its end leaves behind.

    A loss of trust starts the re-entry wait; the cap blocks the level trigger and
    restarts the fast-rise window at the current value.

    Parameters
    ----------
    sc
        Stove configuration.
    stove
        The step so far this tick (an automatic episode).
    reading
        This tick's reading.
    now
        Monotonic time of this tick in seconds.
    """
    active_for = 0.0 if stove.since is None else now - stove.since
    ended = _auto_exit(sc, reading, active_for)
    if ended is None:
        return stove
    if ended is StoveExit.ROOM_UNTRUSTED:
        stove = replace(stove, reentry_wait=sc.reentry_hold_s > 0.0, trusted_since=None)
    if ended is StoveExit.MAX_ACTIVE and reading.value is not None:
        stove = _capped(stove, reading.value, now)
    return _inactive(stove, ended)


def _auto_exit(sc: StoveConfig, reading: _Reading, active_for: float) -> StoveExit | None:
    """Return why an automatic episode active for ``active_for`` s ends, ``None`` to keep it."""
    if not sc.auto:
        return StoveExit.AUTO_OFF
    if reading.jumped:
        return StoveExit.ROOM_JUMP
    if reading.value is None:
        return StoveExit.ROOM_UNTRUSTED
    if active_for >= sc.max_active_s:
        return StoveExit.MAX_ACTIVE
    if active_for < sc.min_active_s:
        return None
    if reading.cooled:
        return StoveExit.COOLED
    if reading.reference_warm:
        return StoveExit.REFERENCE_WARM
    return None


def _capped(stove: StoveStep, value: float, now: float) -> StoveStep:
    """Block the level trigger and restart the fast-rise window at ``value`` after the cap."""
    return replace(
        stove,
        level_blocked=True,
        low_c=value,
        low_at=now,
        high_c=value,
        high_at=now,
        predip_c=value,
    )


def _detected(
    sc: StoveConfig, state: OvenbirdState, stove: StoveStep, reading: _Reading, now: float
) -> StoveStep:
    """Start an automatic episode when the level or a fast rise says so.

    Parameters
    ----------
    sc
        Stove configuration.
    state
        Carried controller state (its integrator is held).
    stove
        The step so far this tick (no episode).
    reading
        This tick's reading.
    now
        Monotonic time of this tick in seconds.
    """
    trigger = _entry_trigger(sc, stove, reading)
    if trigger is None:
        return stove
    return replace(
        stove,
        source=StoveSource.AUTO,
        trigger=trigger,
        since=now,
        entry_c=reading.value,
        integral_k=state.integral_k,
        event="entered",
    )


def _armed(sc: StoveConfig, stove: StoveStep) -> bool:
    """Whether the automatic detection may enter (on, not blocked, waiting or faulted)."""
    return (
        sc.auto
        and not stove.blocked
        and not stove.reentry_wait
        and not stove.fault
        and not stove.gap_short
    )


def _entry_trigger(sc: StoveConfig, stove: StoveStep, reading: _Reading) -> StoveTrigger | None:
    """Return what starts an automatic episode this tick, ``None`` when nothing does."""
    value = reading.value
    if value is None or not _armed(sc, stove):
        return None
    if value >= reading.enter_c - EPSILON and not stove.level_blocked:
        return StoveTrigger.LEVEL
    if _fast_rise(sc, stove, reading, value):
        return StoveTrigger.RISE
    return None


def _fast_rise(sc: StoveConfig, stove: StoveStep, reading: _Reading, value: float) -> bool:
    """Whether ``value`` rose by ``rise_k`` above the entry base and the level before a dip.

    Parameters
    ----------
    sc
        Stove configuration.
    stove
        The step so far this tick (its window).
    reading
        This tick's reading.
    value
        The trusted room value.
    """
    return (
        reading.rise is not None
        and sc.rise_k is not None
        and reading.rise >= sc.rise_k - EPSILON
        and value > reading.entry_base + EPSILON
        and (stove.predip_c is None or value > stove.predip_c + EPSILON)
    )


def fault_step(
    cfg: OvenbirdConfig, state: OvenbirdState, room: RoomInput | None, now: float
) -> tuple[float | None, float | None, float | None]:
    """Return the sensor-fault step of this tick and the window's new low.

    The step is the rise of the plausible room value over the lowest value of the
    last ``fault_step_window_s``, or over the level before a dip when that is
    higher (the rebound after airing is no step). A missing value keeps the low
    until its window has passed.

    Parameters
    ----------
    cfg
        Controller configuration (``None`` steps without stove mode).
    state
        Carried controller state with the last fault-step low.
    room
        The fresh, plausible room value, trusted or not; ``None`` without one.
    now
        Monotonic time of this tick in seconds.
    """
    sc = cfg.stove
    if sc is None:
        return None, None, None
    low_c, low_at = state.stove_step_low_c, state.stove_step_low_at
    if low_c is not None and low_at is not None and now - low_at > sc.fault_step_window_s:
        low_c = low_at = None
    if room is None:
        return None, low_c, low_at
    jump = None
    if low_c is not None:
        base = low_c if state.stove_predip_c is None else max(low_c, state.stove_predip_c)
        jump = room.value - base
    if low_c is None or low_at is None or room.value <= low_c:
        low_c, low_at = room.value, now
    return jump, low_c, low_at


def stove_term(
    cfg: OvenbirdConfig,
    stove: StoveStep,
    room: RoomInput | None,
    reference_c: float | None,
    curve_sp: float,
    bounds: SafetyBounds,
    now: float,
) -> tuple[float, Term | None]:
    """Return the back-off in K water and the ``stove`` term (``None`` without stove mode).

    Parameters
    ----------
    cfg
        Controller configuration.
    stove
        This tick's wood-stove step.
    room
        The fresh, plausible room value, ``None`` without one.
    reference_c
        Fresh temperature of the reference room, ``None`` without one.
    curve_sp
        Water setpoint of the curve in °C.
    bounds
        Safety bounds of this tick (the minimum of ``to_minimum``).
    now
        Monotonic time of this tick in seconds.
    """
    if cfg.stove is None:
        return 0.0, None
    sc = cfg.stove
    stove_raw = stove_value = 0.0
    if stove.active:
        stove_raw = -(max(0.0, curve_sp - bounds.low) if sc.to_minimum else sc.backoff_k)
        stove_value = stove_raw * sc.reference_share(reference_c)
    note = term_note(sc, stove, room, reference_c, cfg.comfort_room_c, now)
    return stove_value, Term("stove", stove_raw, stove_value, "K", note)


def stove_extra(
    cfg: OvenbirdConfig, stove: StoveStep, reference_c: float | None, value: float, now: Instant
) -> dict[str, StateValue]:
    """Return the wood-stove entries of the decision's controller state.

    Parameters
    ----------
    cfg
        Controller configuration.
    stove
        This tick's wood-stove step.
    reference_c
        Fresh temperature of the reference room, ``None`` without one.
    value
        The ``stove`` term's value in K water.
    now
        This tick's instant.
    """
    sc = cfg.stove
    if sc is None:
        return {"stove_event": stove.event, "stove_exit": _value(stove.ended)}
    comfort = cfg.comfort_room_c
    started = None
    if stove.since is not None:
        started = _iso(now, stove.since)
    return {
        "stove_state": "active" if stove.active else "inactive",
        "stove_event": stove.event,
        "stove_exit": _value(stove.ended),
        "stove_started": started,
        "stove_active_s": None if stove.since is None else now.monotonic - stove.since,
        "stove_until": None if stove.until is None else stove.until.wall.isoformat(),
        "stove_enter_c": sc.enter_c(comfort + stove.entry_shift_k),
        "stove_exit_c": sc.exit_c(comfort),
        "stove_rise_k": stove.rise_k,
        "stove_jump_k": stove.jump_k,
        "stove_fault": stove.fault,
        "stove_backoff_k": -value if stove.active else None,
        "stove_reference_c": reference_c,
        "stove_reference_floor_c": sc.reference_floor_c if sc.reference is not None else None,
        "stove_reference_gap_k": stove.gap_k,
        "stove_reference_share": (
            sc.reference_share(reference_c) if sc.reference is not None else None
        ),
    }


def _value(item: StrEnum | None) -> str | None:
    """Return the value of ``item``, ``None`` without one."""
    return None if item is None else item.value


def _iso(now: Instant, monotonic: float) -> str:
    """Wall time of a monotonic instant of this process, as ISO 8601."""
    return (now.wall - timedelta(seconds=now.monotonic - monotonic)).isoformat()


def term_note(
    sc: StoveConfig,
    stove: StoveStep,
    room: RoomInput | None,
    reference_c: float | None,
    comfort_c: float,
    now: float,
) -> str:
    """Return the note of the ``stove`` term.

    Parameters
    ----------
    sc
        Stove configuration.
    stove
        This tick's wood-stove step.
    room
        The fresh, plausible room value, ``None`` without one.
    reference_c
        Fresh temperature of the reference room, ``None`` without one.
    comfort_c
        Comfort room target in °C.
    now
        Monotonic time of this tick in seconds.
    """
    if not stove.active:
        if not sc.auto:
            return "inactive (automatic detection off)"
        where = "room value not trusted" if room is None else f"room {room.value:.1f} °C"
        if stove.fault:
            jump = "" if stove.jump_k is None else f" by {signed(stove.jump_k)} K"
            return (
                f"inactive: the room value jumped{jump} within "
                f"{duration_text(sc.fault_step_window_s)}, a sensor fault rather than a stove; "
                f"detection re-arms below {sc.exit_c(comfort_c):.1f} °C ({where})"
            )
        if stove.blocked:
            return f"inactive, detection re-arms below {sc.exit_c(comfort_c):.1f} °C ({where})"
        if stove.reentry_wait:
            return (
                f"inactive, detection re-arms after the room value has been trusted for "
                f"{duration_text(sc.reentry_hold_s)} ({where})"
            )
        if stove.level_blocked:
            return (
                f"inactive, only a new fast rise enters until the room has been below "
                f"{sc.exit_c(comfort_c):.1f} °C ({where})"
            )
        if stove.gap_short and stove.gap_k is not None and reference_c is not None:
            return (
                f"inactive ({where} only {signed(stove.gap_k)} K above the reference room "
                f"{reference_c:.1f} °C; an automatic entry needs {sc.reference_gap_k:.1f} K)"
            )
        enter_c = sc.enter_c(comfort_c + stove.entry_shift_k)
        return f"inactive ({where}; enters at {enter_c:.1f} °C)"
    size = "to the safety minimum" if sc.to_minimum else f"{sc.backoff_k:.1f} K"
    text = f"back-off {size}"
    if sc.reference is not None:
        if reference_c is None:
            text += (
                f"; reference {sc.reference} has no fresh temperature, "
                f"{sc.reference_share(None) * 100:.0f} % kept"
            )
        else:
            share = sc.reference_share(reference_c)
            text += (
                f"; reference {reference_c:.1f} °C (floor {sc.reference_floor_c:.1f} °C) "
                f"keeps {share * 100:.0f} %"
            )
    return text


def sentence(
    stove: StoveStep,
    integral_k: float,
    curve_sp: float,
    outside_f: float,
    value: float,
    now: float,
) -> str | None:
    """Return the first sentence of the decision note while a stove episode is active.

    Parameters
    ----------
    stove
        This tick's wood-stove step.
    integral_k
        The held integrator in K.
    curve_sp
        Water setpoint of the curve in °C.
    outside_f
        Filtered outside temperature in °C.
    value
        The ``stove`` term's value in K water.
    now
        Monotonic time of this tick in seconds.
    """
    if not stove.active or stove.source is None or stove.trigger is None:
        return None
    since = 0.0 if stove.since is None else now - stove.since
    entry = "" if stove.entry_c is None else f" at {stove.entry_c:.1f} °C"
    return (
        f"Wood-stove mode ({stove.source.value}, {stove.trigger.value}{entry}, "
        f"{duration_text(since)}): room PI paused with the integrator held at "
        f"{signed(integral_k)} K; the curve's {curve_sp:.1f} °C at {outside_f:.1f} °C "
        f"outside lowered by {abs(value):.1f} K"
    )

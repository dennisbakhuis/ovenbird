"""The sun day shift: a slightly warmer house on a sunny, mild day and a lower night after it.

Pure: :func:`decide` takes the local time, the filtered outside temperature, the stored
forecast, the room value, the failing guards, the settings (:class:`DayShiftParams`)
and what the rule remembers of its previous evaluation (:class:`DayShiftMemory`), and
returns the room-target offset with its reasons (:class:`DayShiftResult`). The service's
runner (``ovenbird.control.dayshiftrun``) calls it every quarter hour and hands the
offset to the controller as a rule plan slice; the simulator's evaluation
(``ovenbird_sim.evaluate.dayshift``) calls the same function. Every window is a local
time in :attr:`DayShiftParams.timezone`, the installation's ``control_timezone``.

Boost
    Inside the day window (``day_start`` to ``day_end``, local time) when the forecast
    mean irradiance over the rest of the window is at least ``min_sun_wm2`` and both the
    filtered outside temperature and the forecast minimum over the rest of the window
    are at least ``min_outside_c``. While boosting the temperature limit is
    :data:`HYSTERESIS_K` lower and the sun limit :data:`SUN_HOLD_SHARE` of itself, so
    the boost neither flickers around the limit nor ends with the natural fall of the
    afternoon sun. The sun must also be there now: the forecast irradiance from an hour
    before to an hour after the evaluation reaches the same limit (``confirm_sun``), so a
    morning forecast of sun that the clouds overtake ends the boost.
Warm stop
    Once the room reaches the boosted target (``warm_stop_k`` above it, default
    :data:`DEFAULT_WARM_STOP_K`), the boost ends for the rest of that day (reason
    ``room_warm``): the sun heats the room by itself and more water heat only overheats
    it. Such a day still counts as sunny.
Sunny day
    A day qualifies for the set-back of its night once the boost conditions held with
    the offset at its full size (``boost_k``, within ``max_k``; any offset when
    ``boost_k`` is 0) for at least ``min_boost_s`` in its day window (default
    :data:`DEFAULT_MIN_BOOST_S`). The time counts from one evaluation to the next, at
    most :data:`SLOT_S` per interval, so a single boosted quarter hour or a missed
    evaluation never makes a day sunny.
Set-back
    In the night after a sunny day (from the first ``night_start`` after
    ``day_end``), when the forecast minimum over the night is at least
    ``min_outside_c`` (:data:`HYSTERESIS_K` lower once set back). It ends at
    ``night_end`` or ``recovery_s`` before ``comfort_at``, whichever comes first, and
    starts its way back so early that the step limit has the offset at zero by then.
    It starts only while the room is at least :data:`DEFAULT_SETBACK_WARM_K`
    (``setback_warm_k``) above comfort, so it spends heat the sun stored and not the
    comfort of the next morning (reason ``room_below_target`` otherwise).
    The reason ``no_boost_today`` covers a night after a day that did not qualify.
Recovery
    From the end of a set-back to ``comfort_at``: no offset, the room returns to comfort.
Cancel
    Any guard (stale forecast, untrusted room, wood stove and its tail) blocks the shift
    at once: offset 0 without a ramp. A room more than :data:`ROOM_MARGIN_K` below the
    lowered target ends the set-back for the rest of that night.
Steps
    Planned moves change the offset by at most :data:`STEP_K` per evaluation.
Replay
    :func:`recorded_slice` rebuilds the rule slice a decision was made with from the
    decision record alone, so an open-loop replay of a day with the shift ``on``
    reproduces its setpoints.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final
from zoneinfo import ZoneInfo

from ovenbird_core.control.curve import room_offset_to_water
from ovenbird_core.control.forecast import HOUR_S, ForecastHour
from ovenbird_core.control.types import LadderLevel, PlanSlice, PlanSource, ReasonCode

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ovenbird_core.control.config import OvenbirdConfig
    from ovenbird_core.control.record import DecisionRecord
    from ovenbird_core.instant import Instant

STEP_K: Final = 0.25
ROOM_MARGIN_K: Final = 0.3
HYSTERESIS_K: Final = 1.0
SUN_HOLD_SHARE: Final = 0.5
SLOT_S: Final = 900.0
OFFSET_DIGITS: Final = 4
DEFAULT_MIN_SUN_WM2: Final = 150.0
DEFAULT_RECOVERY_S: Final = 4 * HOUR_S
DEFAULT_MIN_BOOST_S: Final = 2 * HOUR_S
DEFAULT_WARM_STOP_K: Final = 0.0
DEFAULT_SETBACK_WARM_K: Final = 0.5
CONFIRM_SPAN_S: Final = HOUR_S
SLICE_VALID_S: Final = 1200.0
EPSILON_K: Final = 1e-9
MEMORY_VERSION: Final = 2
KNOWN_MEMORY_VERSIONS: Final = frozenset({1, MEMORY_VERSION})


class Phase(StrEnum):
    """What the day shift is doing."""

    IDLE = "idle"
    BOOST = "boost"
    SETBACK = "setback"
    RECOVERY = "recovery"
    BLOCKED = "blocked"


class Reason(StrEnum):
    """Why the day shift does what it does (the guards add their own codes)."""

    OFF = "off"
    OUTSIDE_WINDOWS = "outside_windows"
    SUN_FORECAST = "sun_forecast"
    SUN_LOW = "sun_low"
    OUTSIDE_MILD = "outside_mild"
    OUTSIDE_COLD = "outside_cold"
    OUTSIDE_UNKNOWN = "outside_unknown"
    FORECAST_MISSING = "forecast_missing"
    NIGHT_AFTER_BOOST = "night_after_boost"
    NO_BOOST_TODAY = "no_boost_today"
    NIGHT_COLD = "night_cold"
    RECOVERY_LEAD = "recovery_lead"
    ROOM_BELOW_TARGET = "room_below_target"
    ROOM_WARM = "room_warm"


def clock_time(text: str) -> time:
    """Return the local time of an ``HH:MM`` setting."""
    return time.fromisoformat(text)


@dataclass(frozen=True, slots=True)
class DayShiftParams:
    """The settings of the day shift.

    Parameters
    ----------
    day_start, day_end
        Local day window of the boost (``day_start`` before ``day_end``).
    night_start, night_end
        Local night window of the set-back (it may wrap midnight).
    comfort_at
        Local time the room must be back at comfort after a set-back.
    boost_k, setback_k
        Size of the boost and of the set-back in K (both positive).
    min_outside_c
        Lowest outside temperature, now and forecast, at which the shift runs.
    min_sun_wm2
        Lowest forecast mean irradiance over the rest of the day window for a boost.
    recovery_s
        Seconds before ``comfort_at`` at which a set-back has ended at the latest.
    max_k
        The controller's bound on a rule slice (``plan_rule_max_k``).
    timezone
        IANA zone of the local times (the service passes ``control_timezone``).
    min_boost_s
        Seconds at the full boost a day needs before its night may set back.
    confirm_sun
        The sun must also be there now: the stored irradiance from one hour before to
        one hour after the evaluation must reach the sun limit.
    warm_stop_k
        Once the room is this far above the boosted target (negative: below it), the
        boost ends for the rest of the day (``None``: never).
    setback_warm_k
        A set-back starts only while the room is at least this far above comfort
        (``None``: whatever the room).
    """

    day_start: time = time(9)
    day_end: time = time(17)
    night_start: time = time(23)
    night_end: time = time(5)
    comfort_at: time = time(7)
    boost_k: float = 0.5
    setback_k: float = 0.5
    min_outside_c: float = 5.0
    min_sun_wm2: float = DEFAULT_MIN_SUN_WM2
    recovery_s: float = DEFAULT_RECOVERY_S
    max_k: float = 1.0
    timezone: str = "UTC"
    min_boost_s: float = DEFAULT_MIN_BOOST_S
    confirm_sun: bool = True
    warm_stop_k: float | None = DEFAULT_WARM_STOP_K
    setback_warm_k: float | None = DEFAULT_SETBACK_WARM_K

    @property
    def zone(self) -> ZoneInfo:
        """The zone of the local times."""
        return ZoneInfo(self.timezone)

    @property
    def full_boost_k(self) -> float:
        """The boost offset once the step limit has reached it (``boost_k`` within ``max_k``)."""
        return min(self.boost_k, self.max_k)

    @property
    def ramp_s(self) -> float:
        """Seconds the step limit needs to bring the full set-back back to zero."""
        return math.ceil(round(min(self.setback_k, self.max_k) / STEP_K, 6)) * SLOT_S


def _forward_minutes(origin: time, clock: time) -> int:
    """Return the minutes from ``origin`` forward to the next ``clock`` (0 when equal)."""
    start = origin.hour * 60 + origin.minute
    end = clock.hour * 60 + clock.minute
    return (end - start) % 1440


def window_problem(params: DayShiftParams) -> tuple[str, str] | None:
    """Return which window is out of order and why (``None`` when they are fine).

    The day window may not wrap midnight; going forward from ``day_end``, the night
    starts, then ends, then ``comfort_at`` comes (after the night start), all at or
    before the next ``day_start``.

    Returns
    -------
    tuple of str or None
        ``day``, ``night`` or ``comfort`` with an English explanation.
    """
    if params.day_start >= params.day_end:
        return "day", "the day window must start before it ends, on the same day"
    gap = _forward_minutes(params.day_end, params.day_start)
    start = _forward_minutes(params.day_end, params.night_start)
    end = _forward_minutes(params.day_end, params.night_end)
    comfort = _forward_minutes(params.day_end, params.comfort_at)
    if not start < end <= gap:
        return (
            "night",
            "the night window must lie between the end of the day window and its next start",
        )
    if not start < comfort <= gap:
        return (
            "comfort",
            "the comfort time must come after the night starts and before the day window",
        )
    return None


@dataclass(frozen=True, slots=True)
class Night:
    """One night of the schedule.

    Parameters
    ----------
    day
        The local day it follows.
    start, end
        The night window.
    comfort
        When the room must be back at comfort.
    setback_end
        End of the set-back: ``end`` or ``recovery_s`` before ``comfort``, the earlier.
    release
        When the set-back starts its way back so the offset is zero at ``setback_end``.
    """

    day: date
    start: datetime
    end: datetime
    comfort: datetime
    setback_end: datetime
    release: datetime

    @property
    def span_end(self) -> datetime:
        """The end of the night or the comfort time, the later."""
        return max(self.end, self.comfort)

    @property
    def possible(self) -> bool:
        """Whether a set-back fits between the start and its release."""
        return self.release > self.start


@dataclass(frozen=True, slots=True)
class Schedule:
    """The local windows of the day shift.

    Parameters
    ----------
    params
        The settings.
    """

    params: DayShiftParams

    def at(self, day: date, clock: time) -> datetime:
        """Return ``clock`` on ``day`` in the local zone."""
        return datetime.combine(day, clock, tzinfo=self.params.zone)

    def after(self, moment: datetime, clock: time, *, strict: bool) -> datetime:
        """Return the first ``clock`` at (unless ``strict``) or after ``moment``."""
        found = self.at(moment.date(), clock)
        if found < moment or (strict and found == moment):
            found = self.at(moment.date() + timedelta(days=1), clock)
        return found

    def day_window(self, day: date) -> tuple[datetime, datetime]:
        """Return the day window of ``day``."""
        return self.at(day, self.params.day_start), self.at(day, self.params.day_end)

    def night(self, day: date) -> Night:
        """Return the night that follows the day window of ``day``."""
        params = self.params
        zone = params.zone
        start = self.after(self.at(day, params.day_end), params.night_start, strict=False)
        end = self.after(start, params.night_end, strict=True)
        comfort = self.after(start, params.comfort_at, strict=True)
        latest = datetime.fromtimestamp(comfort.timestamp() - params.recovery_s, zone)
        setback_end = min(end, latest)
        release = datetime.fromtimestamp(setback_end.timestamp() - params.ramp_s, zone)
        return Night(day, start, end, comfort, setback_end, release)

    def night_at(self, moment: datetime) -> Night | None:
        """Return the night ``moment`` lies in, from its start to its later end."""
        today = moment.date()
        for day in (today, today - timedelta(days=1)):
            night = self.night(day)
            if night.start <= moment < night.span_end:
                return night
        return None


@dataclass(frozen=True, slots=True)
class DayShiftMemory:
    """What the rule remembers between evaluations (persisted across a restart).

    Parameters
    ----------
    offset_k
        The offset of the previous evaluation (the step limit starts from it).
    phase
        The phase of the previous evaluation (journal transitions).
    boosting
        The boost conditions held at the previous evaluation (relaxed limits).
    setting_back
        The previous evaluation wanted a set-back (relaxed night limit).
    boost_day
        The last local day with a boost.
    setback_night
        The day whose night had the last set-back.
    cancelled_night
        The day whose night set-back the room cancelled.
    sunny_day
        The local day :attr:`sunny_s` belongs to.
    sunny_s
        Seconds of that day's window with the boost conditions held at the full boost.
    sunny_at
        Unix time of the previous evaluation when it was such a moment (``None``
        otherwise): the time from it to the next evaluation counts.
    """

    offset_k: float = 0.0
    phase: Phase = Phase.IDLE
    boosting: bool = False
    setting_back: bool = False
    boost_day: date | None = None
    setback_night: date | None = None
    cancelled_night: date | None = None
    sunny_day: date | None = None
    sunny_s: float = 0.0
    sunny_at: float | None = None
    warm_day: date | None = None

    def sunny(self, day: date, params: DayShiftParams) -> bool:
        """Whether ``day`` held the boost conditions at the full boost long enough."""
        return self.sunny_day == day and self.sunny_s >= params.min_boost_s - EPSILON_K

    def to_json(self) -> dict[str, Any]:
        """Return the stored form."""
        return {
            "v": MEMORY_VERSION,
            "offset_k": self.offset_k,
            "phase": self.phase.value,
            "boosting": self.boosting,
            "setting_back": self.setting_back,
            "boost_day": _day_text(self.boost_day),
            "setback_night": _day_text(self.setback_night),
            "cancelled_night": _day_text(self.cancelled_night),
            "sunny_day": _day_text(self.sunny_day),
            "sunny_s": self.sunny_s,
            "sunny_at": self.sunny_at,
            "warm_day": _day_text(self.warm_day),
        }

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> DayShiftMemory:
        """Return the memory of a stored form.

        A version 1 form (before the sunny-day time) reads with no sunny time, so the
        first night after an upgrade does not set back.

        Raises
        ------
        ValueError
            When the stored form is not one this version or its predecessor wrote.
        """
        if body.get("v") not in KNOWN_MEMORY_VERSIONS:
            raise ValueError("unknown day shift memory version")
        offset = float(body["offset_k"])
        sunny_s = float(body.get("sunny_s", 0.0))
        at = body.get("sunny_at")
        sunny_at = None if at is None else float(at)
        if not all(math.isfinite(value) for value in (offset, sunny_s, sunny_at or 0.0)):
            raise ValueError("day shift memory value is not finite")
        return cls(
            offset_k=offset,
            phase=Phase(body["phase"]),
            boosting=bool(body["boosting"]),
            setting_back=bool(body["setting_back"]),
            boost_day=_day_value(body.get("boost_day")),
            setback_night=_day_value(body.get("setback_night")),
            cancelled_night=_day_value(body.get("cancelled_night")),
            sunny_day=_day_value(body.get("sunny_day")),
            sunny_s=max(0.0, sunny_s),
            sunny_at=sunny_at,
            warm_day=_day_value(body.get("warm_day")),
        )


def _day_text(day: date | None) -> str | None:
    """Return a day as ``YYYY-MM-DD``."""
    return None if day is None else day.isoformat()


def _day_value(text: Any) -> date | None:
    """Return the day of a stored ``YYYY-MM-DD`` (``None`` stays ``None``)."""
    return None if text is None else date.fromisoformat(str(text))


@dataclass(frozen=True, slots=True)
class DayShiftInputs:
    """What the rule looks at in one evaluation.

    Parameters
    ----------
    now
        The evaluation instant (timezone-aware).
    outside_c
        The controller's filtered outside temperature (``None``: unknown).
    hours
        The stored forecast hours (temperature and irradiance).
    room_c
        The trusted room value (``None``: none).
    comfort_c
        The comfort room temperature.
    guards
        The failing guards' codes (:class:`~ovenbird.control.forecastread.Guard`).
    """

    now: datetime
    outside_c: float | None
    hours: tuple[ForecastHour, ...]
    room_c: float | None
    comfort_c: float
    guards: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NextChange:
    """The next change the schedule allows (it still depends on forecast and guards then).

    Parameters
    ----------
    at
        When.
    phase
        The phase it leads to.
    """

    at: datetime
    phase: Phase


@dataclass(frozen=True, slots=True)
class ForecastSummary:
    """What the rule read of the forecast.

    Parameters
    ----------
    outside_c
        The filtered outside temperature the rule compared (``None``: unknown).
    sun_wm2
        Mean irradiance over the rest of today's day window (all of it once it is over).
    outside_min_c
        Forecast minimum temperature over the same span.
    night_min_c
        Forecast minimum temperature of the current night, else of tonight.
    sun_limit_wm2, outside_limit_c, night_limit_c
        The limits in force (relaxed while boosting or set back).
    hours
        Forecast hours read.
    """

    outside_c: float | None
    sun_wm2: float | None
    outside_min_c: float | None
    night_min_c: float | None
    sun_limit_wm2: float
    outside_limit_c: float
    night_limit_c: float
    hours: int


@dataclass(frozen=True, slots=True)
class DayShiftResult:
    """One evaluation of the rule.

    Parameters
    ----------
    at
        The evaluation instant.
    phase
        What the day shift does now.
    offset_k
        The room-target offset to apply (step-limited, within ``max_k``).
    desired_k
        The offset the rule aims at.
    reasons
        Why (:class:`Reason` and guard codes).
    guards
        The failing guards.
    next_change
        The next change the schedule allows (``None`` while blocked).
    forecast
        What the rule read of the forecast.
    setback_end
        End of the set-back of the current or coming night.
    memory
        What the next evaluation starts from.
    """

    at: datetime
    phase: Phase
    offset_k: float
    desired_k: float
    reasons: tuple[str, ...]
    guards: tuple[str, ...]
    next_change: NextChange | None
    forecast: ForecastSummary
    setback_end: datetime | None
    memory: DayShiftMemory


@dataclass(frozen=True, slots=True)
class _Plan:
    """The target of one evaluation before the step limit.

    Parameters
    ----------
    desired_k
        The offset aimed at.
    reasons
        Why.
    latched
        The room cancelled this night's set-back earlier (the phase stays blocked).
    sunny
        The boost conditions hold (sun, outside temperature, forecast, no guard).
    """

    desired_k: float
    reasons: tuple[str, ...]
    latched: bool = False
    sunny: bool = False


def _mean(values: Iterable[float]) -> float | None:
    """Return the mean (``None`` for no values)."""
    items = list(values)
    return sum(items) / len(items) if items else None


def _minimum(values: Iterable[float]) -> float | None:
    """Return the minimum (``None`` for no values)."""
    return min(values, default=None)


def sun_over(hours: tuple[ForecastHour, ...], start: datetime, end: datetime) -> float | None:
    """Return the mean irradiance of the forecast hours that overlap ``[start, end)``."""
    first, last = start.timestamp(), end.timestamp()
    return _mean(
        hour.ghi_w_m2
        for hour in hours
        if hour.ghi_w_m2 is not None and first < hour.target_ts < last + HOUR_S
    )


def coldest(hours: tuple[ForecastHour, ...], start: datetime, end: datetime) -> float | None:
    """Return the forecast minimum temperature of the hours in ``[start, end]``."""
    first, last = start.timestamp(), end.timestamp()
    return _minimum(
        hour.outside_c
        for hour in hours
        if hour.outside_c is not None and first <= hour.target_ts <= last
    )


def _clamp(value: float, limit: float) -> float:
    """Return ``value`` within ``±limit``."""
    return max(-limit, min(limit, value))


def _boost(
    params: DayShiftParams,
    inputs: DayShiftInputs,
    memory: DayShiftMemory,
    now: datetime,
    day_end: datetime,
) -> _Plan:
    """Return the boost target inside the day window.

    Parameters
    ----------
    params
        Tuning of the day-shift rule.
    inputs
        Forecast, outside and room values of this evaluation.
    memory
        State carried between evaluations (hysteresis, warm and sunny day).
    now
        Evaluation time.
    day_end
        End of today's day window.
    """
    relaxed = memory.boosting
    temp_limit = params.min_outside_c - (HYSTERESIS_K if relaxed else 0.0)
    sun_limit = params.min_sun_wm2 * (SUN_HOLD_SHARE if relaxed else 1.0)
    sun = sun_over(inputs.hours, now, day_end)
    low = coldest(inputs.hours, now, day_end)
    reasons: list[str] = []
    if inputs.outside_c is None:
        reasons.append(Reason.OUTSIDE_UNKNOWN)
    if sun is None or low is None:
        reasons.append(Reason.FORECAST_MISSING)
    if (inputs.outside_c is not None and inputs.outside_c < temp_limit) or (
        low is not None and low < temp_limit
    ):
        reasons.append(Reason.OUTSIDE_COLD)
    if sun is not None and sun < sun_limit:
        reasons.append(Reason.SUN_LOW)
    if params.confirm_sun and Reason.SUN_LOW not in reasons:
        span = timedelta(seconds=CONFIRM_SPAN_S)
        near = sun_over(inputs.hours, now - span, now + span)
        if near is None or near < sun_limit:
            reasons.append(Reason.SUN_LOW)
    if reasons:
        return _Plan(0.0, tuple(reasons))
    if memory.warm_day == now.date():
        return _Plan(0.0, (Reason.ROOM_WARM,), sunny=True)
    return _Plan(params.boost_k, (Reason.SUN_FORECAST, Reason.OUTSIDE_MILD), sunny=True)


def _setback(
    params: DayShiftParams,
    inputs: DayShiftInputs,
    memory: DayShiftMemory,
    now: datetime,
    night: Night,
    sunny: DayShiftMemory,
) -> _Plan:
    """Return the set-back target inside a night (``sunny`` holds the day's sunny time).

    Parameters
    ----------
    params
        Tuning of the day-shift rule.
    inputs
        Forecast, outside and room values of this evaluation.
    memory
        State carried between evaluations (hysteresis, warm and sunny day).
    now
        Evaluation time.
    night
        The night being evaluated.
    sunny
        Memory holding today's accumulated sunny time.
    """
    if not sunny.sunny(night.day, params):
        return _Plan(0.0, (Reason.NO_BOOST_TODAY,))
    if memory.cancelled_night == night.day and now < night.setback_end:
        return _Plan(0.0, (Reason.ROOM_BELOW_TARGET,), latched=True)
    if now >= night.release or not night.possible:
        return _Plan(0.0, (Reason.RECOVERY_LEAD,))
    low = coldest(inputs.hours, night.start, night.end)
    if low is None:
        return _Plan(0.0, (Reason.FORECAST_MISSING,))
    limit = params.min_outside_c - (HYSTERESIS_K if memory.setting_back else 0.0)
    if low < limit:
        return _Plan(0.0, (Reason.NIGHT_COLD,))
    warm = params.setback_warm_k
    room = inputs.room_c
    if (
        warm is not None
        and not memory.setting_back
        and (room is None or room < inputs.comfort_c + warm)
    ):
        return _Plan(0.0, (Reason.ROOM_BELOW_TARGET,))
    return _Plan(-params.setback_k, (Reason.NIGHT_AFTER_BOOST,))


def _summary(
    params: DayShiftParams,
    inputs: DayShiftInputs,
    memory: DayShiftMemory,
    schedule: Schedule,
    now: datetime,
) -> ForecastSummary:
    """Return what the rule reads of the forecast for today's window and the night.

    Parameters
    ----------
    params
        Tuning of the day-shift rule.
    inputs
        Forecast, outside and room values of this evaluation.
    memory
        State carried between evaluations (hysteresis, warm and sunny day).
    schedule
        Day windows and nights.
    now
        Evaluation time.
    """
    day_start, day_end = schedule.day_window(now.date())
    start = max(now, day_start) if now < day_end else day_start
    night = schedule.night_at(now) or schedule.night(now.date())
    relaxed = memory.boosting
    return ForecastSummary(
        outside_c=_rounded(inputs.outside_c),
        sun_wm2=_rounded(sun_over(inputs.hours, start, day_end)),
        outside_min_c=_rounded(coldest(inputs.hours, start, day_end)),
        night_min_c=_rounded(coldest(inputs.hours, night.start, night.end)),
        sun_limit_wm2=params.min_sun_wm2 * (SUN_HOLD_SHARE if relaxed else 1.0),
        outside_limit_c=params.min_outside_c - (HYSTERESIS_K if relaxed else 0.0),
        night_limit_c=params.min_outside_c - (HYSTERESIS_K if memory.setting_back else 0.0),
        hours=len(inputs.hours),
    )


def _rounded(value: float | None) -> float | None:
    """Return ``value`` to one decimal (``None`` stays ``None``)."""
    return None if value is None else round(value, 1)


def next_change(
    schedule: Schedule, now: datetime, phase: Phase, memory: DayShiftMemory
) -> NextChange | None:
    """Return the next change of phase the schedule allows after ``now``.

    Parameters
    ----------
    schedule
        The windows.
    now
        The evaluation instant (local).
    phase
        The phase now.
    memory
        The memory after this evaluation (which day was sunny).

    Returns
    -------
    NextChange or None
        The first scheduled boundary after ``now`` that leads to another phase: the
        next day window, its end, and for a sunny day (or today while it boosts) the
        start of its night's set-back, its release and the comfort time. ``None`` while
        blocked.
    """
    if phase is Phase.BLOCKED:
        return None
    today = now.date()
    events: list[tuple[datetime, Phase]] = []
    for day in (today - timedelta(days=1), today, today + timedelta(days=1)):
        start, end = schedule.day_window(day)
        events += [(start, Phase.BOOST), (end, Phase.IDLE)]
        if memory.sunny(day, schedule.params) or (day == today and phase is Phase.BOOST):
            night = schedule.night(day)
            if night.possible:
                events += [
                    (night.start, Phase.SETBACK),
                    (night.release, Phase.RECOVERY),
                    (night.comfort, Phase.IDLE),
                ]
    for at, target in sorted(events, key=lambda item: item[0]):
        if at > now and target is not phase:
            return NextChange(at, target)
    return None


def _phase(
    plan: _Plan,
    offset: float,
    blocked: bool,
    night: Night | None,
    setback_night: date | None,
    now: datetime,
) -> Phase:
    """Return the phase of an evaluation from its target and its stepped offset.

    Parameters
    ----------
    plan
        Target the rule wants.
    offset
        Offset currently applied, in K.
    blocked
        Whether the room's cancellation blocks the shift.
    night
        Night containing ``now``, if any.
    setback_night
        Day of the night a set-back applied to, if any.
    now
        Evaluation time.
    """
    if blocked or plan.latched:
        return Phase.BLOCKED
    if plan.desired_k > 0.0 or offset > 0.0:
        return Phase.BOOST
    if plan.desired_k < 0.0:
        return Phase.SETBACK
    if offset < 0.0:
        return Phase.RECOVERY
    if night is not None and setback_night == night.day and night.release <= now < night.comfort:
        return Phase.RECOVERY
    return Phase.IDLE


def _sunny_time(
    memory: DayShiftMemory, today: date, now: datetime, window: tuple[datetime, datetime]
) -> DayShiftMemory:
    """Return the sunny time of ``today`` up to ``now``.

    Before today's day window the memory is kept (the night after yesterday still
    reads yesterday's time); from its start a new day counts from zero.

    Parameters
    ----------
    memory
        State carried between evaluations.
    today
        Calendar day being counted.
    now
        Evaluation time.
    window
        Start and end of today's day window.
    """
    day_start, day_end = window
    if memory.sunny_day != today:
        return DayShiftMemory(sunny_day=today) if now >= day_start else memory
    credit = 0.0
    if memory.sunny_at is not None:
        span = min(now.timestamp(), day_end.timestamp()) - memory.sunny_at
        credit = min(max(0.0, span), SLOT_S)
    return DayShiftMemory(sunny_day=today, sunny_s=memory.sunny_s + credit)


def decide(
    params: DayShiftParams, inputs: DayShiftInputs, memory: DayShiftMemory
) -> DayShiftResult:
    """Return the day shift's offset at ``inputs.now``.

    Parameters
    ----------
    params
        The settings.
    inputs
        Time, outside temperature, forecast, room value and the failing guards.
    memory
        What the previous evaluation left (:attr:`DayShiftResult.memory`).

    Returns
    -------
    DayShiftResult
        The offset (moved by at most :data:`STEP_K` from the previous one, or zero at
        once when blocked or cancelled), the phase and reasons, the next scheduled
        change and the forecast summary, with the memory for the next evaluation.
    """
    schedule = Schedule(params)
    now = inputs.now.astimezone(params.zone)
    today = now.date()
    day_start, day_end = schedule.day_window(today)
    in_day = day_start <= now < day_end
    night = None if in_day else schedule.night_at(now)
    sunny = _sunny_time(memory, today, now, (day_start, day_end))
    if inputs.guards:
        plan = _Plan(0.0, inputs.guards)
    elif in_day:
        plan = _boost(params, inputs, memory, now, day_end)
    elif night is not None:
        plan = _setback(params, inputs, memory, now, night, sunny)
    else:
        plan = _Plan(0.0, (Reason.OUTSIDE_WINDOWS,))
    desired = _clamp(plan.desired_k, params.max_k)
    blocked = bool(inputs.guards)
    if blocked or plan.latched:
        offset = 0.0
    else:
        step = _clamp(desired - memory.offset_k, STEP_K)
        offset = round(memory.offset_k + step, OFFSET_DIGITS)
    cancelled = memory.cancelled_night
    room = inputs.room_c
    too_cold = room is not None and room < inputs.comfort_c + offset - ROOM_MARGIN_K
    if night is not None and offset < 0.0 and too_cold:
        plan = _Plan(0.0, (Reason.ROOM_BELOW_TARGET,), latched=True)
        desired, offset, cancelled = 0.0, 0.0, night.day
    setback_night = memory.setback_night
    if night is not None and offset < 0.0:
        setback_night = night.day
    warm_day = memory.warm_day
    stop = params.warm_stop_k
    if (
        in_day
        and plan.sunny
        and stop is not None
        and room is not None
        and room >= inputs.comfort_c + params.full_boost_k + stop
    ):
        warm_day = today
    phase = _phase(plan, offset, blocked, night, setback_night, now)
    full = (
        in_day and plan.sunny and (offset >= params.full_boost_k - EPSILON_K or warm_day == today)
    )
    updated = DayShiftMemory(
        offset_k=offset,
        phase=phase,
        boosting=plan.sunny,
        setting_back=desired < 0.0,
        boost_day=today if in_day and offset > 0.0 else memory.boost_day,
        setback_night=setback_night,
        cancelled_night=cancelled,
        sunny_day=sunny.sunny_day,
        sunny_s=sunny.sunny_s,
        sunny_at=now.timestamp() if full else None,
        warm_day=warm_day,
    )
    coming = night or schedule.night(today)
    return DayShiftResult(
        at=now,
        phase=phase,
        offset_k=offset,
        desired_k=desired,
        reasons=tuple(str(reason) for reason in plan.reasons),
        guards=tuple(inputs.guards),
        next_change=next_change(schedule, now, phase, updated),
        forecast=_summary(params, inputs, memory, schedule, now),
        setback_end=coming.setback_end if coming.possible else None,
        memory=updated,
    )


def rule_slice(result: DayShiftResult, now: Instant) -> PlanSlice | None:
    """Return the rule plan slice of an evaluation, valid :data:`SLICE_VALID_S` (``None`` at 0)."""
    offset = result.offset_k
    if offset == 0.0:
        return None
    reason = ReasonCode.PLAN_PREHEAT if offset > 0.0 else ReasonCode.PLAN_SETBACK
    return PlanSlice(offset, reason, now, now.shifted(SLICE_VALID_S), PlanSource.RULE)


def _number(value: object) -> float | None:
    """Return a recorded number (``None`` for anything else, booleans included)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def recorded_slice(record: DecisionRecord, config: OvenbirdConfig) -> PlanSlice | None:
    """Return the rule slice a decision was made with, rebuilt from its record.

    A tick that applied a rule slice has the ladder level ``rule_plan``. With a trusted
    room value the slice shifted the room target, so its offset is the recorded
    ``room_target_c`` minus the comfort target of ``config``: exactly what the runner
    records as ``derived/dayshift_offset_k``. Without a room sensor the slice went to
    the water through the curve slope, so the offset is the ``plan`` term's raw water
    offset divided by that slope at the recorded filtered outside temperature. The
    slice is valid for that tick alone and the controller applies its bound again.

    Parameters
    ----------
    record
        A stored decision record.
    config
        The controller configuration the record was made with (its comfort target and
        curve).

    Returns
    -------
    PlanSlice or None
        The rule slice; ``None`` for a tick without an applied rule slice, including a
        paused one (it had no effect on the terms, only on the wood-stove entry
        thresholds, which the runner never meets because it withdraws its slice on
        the same guards).
    """
    if record.ladder is not LadderLevel.RULE_PLAN:
        return None
    state = record.controller_state
    target = _number(state.get("room_target_c"))
    if target is not None:
        offset = target - config.comfort_room_c
    else:
        term = record.term("plan")
        outside = _number(state.get("outside_filtered_c"))
        if term is None or outside is None:
            return None
        slope = room_offset_to_water(config.curve, outside, 1.0)
        if slope <= 0.0:
            return None
        offset = term.raw / slope
    offset = round(offset, OFFSET_DIGITS)
    if offset == 0.0:
        return None
    reason = ReasonCode.PLAN_PREHEAT if offset > 0.0 else ReasonCode.PLAN_SETBACK
    return PlanSlice(offset, reason, record.at, record.at.shifted(SLICE_VALID_S), PlanSource.RULE)

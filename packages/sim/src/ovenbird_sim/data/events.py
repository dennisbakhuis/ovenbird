"""Known events the plant model does not represent: wood-stove fires in the living room.

A house may have a wood stove in the living room. A fire heats that room by several
kelvin within an hour while the rest of the house barely changes; the model has one
air node and no stove heat, so a simulated day with a fire cannot match the recording
(room, heat demand, and the recorded controller's room feedback, which lowers the
setpoint when the living room is warm). Such periods are flagged offline, excluded from the fits and
the gates, and reported - never silently.

Detection (on a regular grid; :func:`detect_stove`):

1. ``excess = living - reference``: the living room minus the mean of rooms away from
   the stove (hall, bedroom; :data:`REFERENCE_ROOMS`). The excess is normally 1.5-3.5 K
   (the living room is the heated, occupied room) and drifts over the season.
2. ``anomaly = excess - baseline`` with the baseline the centred
   :data:`BASELINE_DAYS`-day rolling median of hourly excess (robust to a fire of a
   day or two).
3. A fire's **core** is a run of at least :data:`MIN_CORE_S` with ``anomaly >=``
   :data:`ONSET_K`, confirmed by a **rise**: the living room warms at least
   :data:`RISE_K_PER_H` faster than the reference over :data:`RISE_WINDOW_S` somewhere
   in the :data:`RISE_LOOKBACK_S` before the core or within it.
4. The event extends from the last time before the core and to the first time after
   it with ``anomaly <`` :data:`END_K`; events closer than :data:`MERGE_S` merge.
5. A **recovery tail** of :data:`TAIL_S` follows the end: the stove's heat stored in
   the living room's mass and furniture keeps lowering the heat demand after the air
   excess has gone, so the plant is not comparable yet.

The owner can also leave whole local days out (``house_learn_excluded_days``:
a party, a window left open, a sensor moved): :func:`excluded_days` turns them into
events of kind :data:`EXCLUDED_DAY` from local midnight to local midnight, without a
recovery tail (the owner can leave the next day out too); they are masked like a
fire, never merged with one, and listed with the same JSON shape.

Thresholds were set on a recording of several weeks with one fire (60 s grid,
living-room composite, hall and bedroom): outside the fire the anomaly stayed below
the onset (rarely above two thirds of it), and the rare fast relative rises (up to
about 2 K/h) never came with a large anomaly; the fire exceeded both thresholds about
twofold. Both criteria must hold, so neither a sunny afternoon nor a slow drift of the
baseline flags.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

import numpy as np

from ovenbird_core.control.record import JsonDict
from ovenbird_sim.data.series import BoolArray, FloatArray

STOVE: Final = "stove"
STOVE_MODE: Final = "stove_mode"
EXCLUDED_DAY: Final = "excluded_day"
LIVING_COLUMN: Final = "room_living"
REFERENCE_ROOMS: Final = ("room_hall", "room_bedroom")
BASELINE_DAYS: Final = 7.0
ONSET_K: Final = 2.0
END_K: Final = 0.5
MIN_CORE_S: Final = 1800.0
RISE_K_PER_H: Final = 1.5
RISE_WINDOW_S: Final = 1800.0
RISE_LOOKBACK_S: Final = 3 * 3600.0
MERGE_S: Final = 6 * 3600.0
TAIL_S: Final = 12 * 3600.0
LOCAL_TZ: Final = "Europe/Amsterdam"
SECONDS_PER_DAY: Final = 86400.0
REASON: Final = (
    "wood stove: living room {peak:.1f} K above its usual excess over hall and bedroom, "
    "rising {rise:.1f} K/h; the model has no stove heat"
)
JOURNAL_REASON: Final = "wood-stove mode in the controller's journal; the model has no stove heat"
EXCLUDED_REASON: Final = "left out by the owner (house_learn_excluded_days)"


@dataclass(frozen=True, slots=True)
class Event:
    """One flagged period.

    Parameters
    ----------
    kind
        Event kind: :data:`STOVE` (detected), :data:`STOVE_MODE` (the service's
        wood-stove mode journal) or :data:`EXCLUDED_DAY` (a day the owner left out);
        the latter two without peak or rise.
    start, end
        The period the living room is anomalous (unix s).
    tail_end
        End of the recovery tail (unix s); the exclusion covers ``[start, tail_end)``.
    peak_k
        Largest anomaly of the living room's excess.
    rise_k_per_h
        Largest relative rise rate.
    """

    kind: str
    start: float
    end: float
    tail_end: float
    peak_k: float
    rise_k_per_h: float

    @property
    def hours(self) -> float:
        """Duration of the anomalous period in hours."""
        return (self.end - self.start) / 3600.0

    @property
    def excluded_hours(self) -> float:
        """Duration including the recovery tail in hours."""
        return (self.tail_end - self.start) / 3600.0

    @property
    def reason(self) -> str:
        """Human-readable reason of the flag."""
        if self.kind == STOVE_MODE:
            return JOURNAL_REASON
        if self.kind == EXCLUDED_DAY:
            return EXCLUDED_REASON
        return REASON.format(peak=self.peak_k, rise=self.rise_k_per_h)

    def to_json(self, tz: str = LOCAL_TZ) -> JsonDict:
        """JSON-ready description with local and UTC times."""
        zone = ZoneInfo(tz)

        def local(t: float) -> str:
            return datetime.fromtimestamp(t, zone).isoformat(timespec="minutes")

        return {
            "kind": self.kind,
            "start_local": local(self.start),
            "end_local": local(self.end),
            "tail_end_local": local(self.tail_end),
            "hours": round(self.hours, 2),
            "excluded_hours": round(self.excluded_hours, 2),
            "peak_k": round(self.peak_k, 2) if math.isfinite(self.peak_k) else None,
            "rise_k_per_h": round(self.rise_k_per_h, 2)
            if math.isfinite(self.rise_k_per_h)
            else None,
            "utc_days": list(days_touched((self,))),
            "reason": self.reason,
        }


def _rolling_median(values: FloatArray, half_width: int) -> FloatArray:
    out = np.full(values.size, np.nan)
    for i in range(values.size):
        window = values[max(0, i - half_width) : i + half_width + 1]
        if np.isfinite(window).any():
            out[i] = float(np.nanmedian(window))
    return out


def anomaly(t: FloatArray, living: FloatArray, reference: FloatArray) -> FloatArray:
    """Living-room excess over the reference minus its rolling-median baseline.

    Parameters
    ----------
    t
        Regular grid times (unix s).
    living, reference
        Living-room and reference temperatures on the grid.

    Returns
    -------
    FloatArray
        Anomaly in K (``NaN`` where an input is missing).
    """
    excess = living - reference
    step = float(t[1] - t[0]) if t.size > 1 else 60.0
    per_hour = max(round(3600.0 / step), 1)
    hour = np.floor((t - t[0]) / 3600.0).astype(np.int64)
    n_hours = int(hour[-1]) + 1 if t.size else 0
    sums = np.bincount(hour, np.nan_to_num(excess), n_hours)
    counts = np.bincount(hour, np.isfinite(excess).astype(np.float64), n_hours)
    with np.errstate(invalid="ignore", divide="ignore"):
        hourly = np.where(counts >= per_hour / 2, sums / counts, np.nan)
    baseline = _rolling_median(hourly, round(BASELINE_DAYS * 12))
    filled = np.where(np.isfinite(baseline), baseline, np.nanmedian(hourly))
    return np.asarray(excess - filled[hour], dtype=np.float64)


def relative_rise(t: FloatArray, living: FloatArray, reference: FloatArray) -> FloatArray:
    """Rise of the living room minus that of the reference over :data:`RISE_WINDOW_S`, in K/h."""
    step = float(t[1] - t[0]) if t.size > 1 else 60.0
    lag = max(round(RISE_WINDOW_S / step), 1)
    diff = living - reference
    out = np.full(t.size, np.nan)
    if t.size > lag:
        out[lag:] = (diff[lag:] - diff[:-lag]) * 3600.0 / (lag * step)
    return out


def _runs(flag: BoolArray) -> list[tuple[int, int]]:
    edges = np.diff(np.concatenate([[0], flag.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=True))


def detect_stove(
    t: FloatArray, living: FloatArray, references: Sequence[FloatArray]
) -> tuple[Event, ...]:
    """Detect wood-stove fires (see the module docstring for the rule).

    Parameters
    ----------
    t
        Regular grid times (unix s).
    living
        Living-room temperature on the grid.
    references
        Temperatures of rooms away from the stove (their mean is the reference; a
        missing room is skipped).

    Returns
    -------
    tuple of Event
        Fires in time order.
    """
    if t.size < 2 or not references:
        return ()
    stack = np.vstack(references)
    present = np.isfinite(stack).sum(axis=0)
    with np.errstate(invalid="ignore"):
        reference = np.where(present > 0, np.nansum(stack, axis=0) / np.maximum(present, 1), np.nan)
    if not (np.isfinite(living) & np.isfinite(reference)).any():
        return ()
    step = float(t[1] - t[0])
    a = anomaly(t, living, reference)
    rise = relative_rise(t, living, reference)
    lookback = round(RISE_LOOKBACK_S / step)
    found: list[Event] = []
    for i0, i1 in _runs(np.nan_to_num(a, nan=-np.inf) >= ONSET_K):
        if (i1 - i0) * step < MIN_CORE_S:
            continue
        rise_max = float(np.nanmax(rise[max(0, i0 - lookback) : i1], initial=-np.inf))
        if rise_max < RISE_K_PER_H:
            continue
        below = np.nan_to_num(a, nan=-np.inf) < END_K
        before = np.flatnonzero(below[:i0])
        after = np.flatnonzero(below[i1:])
        s = int(before[-1]) + 1 if before.size else 0
        e = i1 + int(after[0]) if after.size else t.size
        start = float(t[s])
        end = float(t[e]) if e < t.size else float(t[-1]) + step
        peak = float(np.nanmax(a[s:e]))
        if found and start - found[-1].end <= MERGE_S:
            last = found.pop()
            start = last.start
            peak = max(peak, last.peak_k)
            rise_max = max(rise_max, last.rise_k_per_h)
            end = max(end, last.end)
        found.append(Event(STOVE, start, end, end + TAIL_S, peak, rise_max))
    return tuple(found)


def detect(
    columns: Mapping[str, FloatArray],
    t: FloatArray,
    references: Sequence[str] = REFERENCE_ROOMS,
) -> tuple[Event, ...]:
    """Detect the known events from dataset columns.

    Parameters
    ----------
    columns
        Dataset columns with the living-room composite (:data:`LIVING_COLUMN`).
    t
        Regular grid times (unix s).
    references
        Columns of rooms away from the stove (the hall and bedroom by default).

    Returns
    -------
    tuple of Event
        Fires in time order; none without the living room or a reference room.
    """
    living = columns.get(LIVING_COLUMN)
    if living is None:
        return ()
    rooms = [columns[name] for name in references if name in columns]
    return detect_stove(t, living, rooms)


def merge(events: Sequence[Event]) -> tuple[Event, ...]:
    """Sort events and merge overlapping ones (the earlier kind and the larger peak win)."""
    out: list[Event] = []
    for event in sorted(events, key=lambda e: e.start):
        if out and event.start <= out[-1].tail_end:
            last = out.pop()
            event = Event(
                last.kind,
                last.start,
                max(last.end, event.end),
                max(last.tail_end, event.tail_end),
                float(np.fmax(last.peak_k, event.peak_k)),
                float(np.fmax(last.rise_k_per_h, event.rise_k_per_h)),
            )
        out.append(event)
    return tuple(out)


def excluded_days(days: Sequence[str], tz: str = LOCAL_TZ) -> tuple[Event, ...]:
    """Events covering local calendar days the owner left out.

    Parameters
    ----------
    days
        Local days as ``YYYY-MM-DD`` (repeats are ignored).
    tz
        IANA time zone of the days.

    Returns
    -------
    tuple of Event
        One :data:`EXCLUDED_DAY` event per day, local midnight to local midnight (23
        or 25 hours on a daylight-saving change), in time order.

    Raises
    ------
    ValueError
        When a day is not a valid ``YYYY-MM-DD`` date.
    """
    zone = ZoneInfo(tz)
    out = []
    for text in sorted(set(days)):
        day = date.fromisoformat(text)
        start = datetime.combine(day, time(), zone).timestamp()
        end = datetime.combine(day + timedelta(days=1), time(), zone).timestamp()
        out.append(Event(EXCLUDED_DAY, start, end, end, math.nan, math.nan))
    return tuple(out)


def mask(t: FloatArray, events: Sequence[Event], *, tail: bool = True) -> BoolArray:
    """Flag times inside an event (with its recovery tail unless ``tail`` is false)."""
    out = np.zeros(t.shape, dtype=np.bool_)
    for event in events:
        out |= (t >= event.start) & (t < (event.tail_end if tail else event.end))
    return out


def day_mask(t: FloatArray, events: Sequence[Event]) -> BoolArray:
    """Flag times on a UTC day that overlaps an event or its recovery tail."""
    out = np.zeros(t.shape, dtype=np.bool_)
    for event in events:
        first = math.floor(event.start / SECONDS_PER_DAY) * SECONDS_PER_DAY
        last = math.ceil(event.tail_end / SECONDS_PER_DAY) * SECONDS_PER_DAY
        out |= (t >= first) & (t < last)
    return out


def days_touched(events: Sequence[Event]) -> tuple[str, ...]:
    """UTC days (``YYYY-MM-DD``) that overlap an event or its recovery tail."""
    labels: list[str] = []
    for event in events:
        day = math.floor(event.start / SECONDS_PER_DAY)
        while day * SECONDS_PER_DAY < event.tail_end:
            label = datetime.fromtimestamp(day * SECONDS_PER_DAY, UTC).strftime("%Y-%m-%d")
            if label not in labels:
                labels.append(label)
            day += 1
    return tuple(sorted(labels))


def describe(events: Sequence[Event], tz: str = LOCAL_TZ) -> list[str]:
    """Report lines, one per event (local times in ``tz``)."""
    zone = ZoneInfo(tz)
    lines = []
    for event in events:
        start = datetime.fromtimestamp(event.start, zone).strftime("%Y-%m-%d %H:%M")
        end = datetime.fromtimestamp(event.end, zone).strftime("%Y-%m-%d %H:%M")
        lines.append(
            f"  {event.kind} {start} - {end} local ({event.hours:.1f} h, +{TAIL_S / 3600:.0f} h "
            f"recovery; UTC days {', '.join(days_touched((event,)))}): {event.reason}"
        )
    return lines

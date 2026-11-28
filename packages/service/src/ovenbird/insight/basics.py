"""House basics: the heat loss of the house and the heat the heat pump puts in.

Two plain estimates from the history, in pure Python, recomputed at most once an
hour (:class:`BasicsCache`); the live values (room, outside, heat now) are read per
request.

Heat loss (``P = H x dT - G``)
    Least squares of the mean space-heating power ``P`` (W) against the
    room-minus-outside difference ``dT`` (K). ``H`` is the heat-loss figure (W/K),
    ``G`` the free heat (internal and solar gains, on average) and the balance
    temperature ``room - G/H`` the outside temperature at which the house needs no
    heating. A point is a **48 h window**: two consecutive qualifying local days,
    averaged, so heat the floor and the walls store on one day and give back the
    next mostly cancels; windows do not share days, so each day counts once and the
    band is not made narrower than the data allow. A day qualifies when at least
    80 % of it has data (loop heat or hot water, outside and room), it needed real
    heating (mean loop heat at least :data:`HEATING_MIN_W` and the room at least
    :data:`HEATING_MIN_K` above outside), and no wood-stove episode touched it or
    the :data:`~ovenbird.control.forecastread.STOVE_TAIL_S` before it (the stove
    heats the room sensor and its heat stays in the room's mass overnight), and no
    away period touched it (exclusion ``away``: the room was held low on purpose,
    the return to comfort included; the weather bins leave such days out too). The loop
    heat is ``derived/heat_delivered_w`` (flow x spread): hot-water runs are not in
    it, and a defrost's draw from the loop is netted, as it is heat the house gave
    back. One robust pass drops windows whose residual exceeds
    :data:`OUTLIER_SIGMAS` robust standard deviations (a holiday, an open window, a
    stove the journal missed); then windows less than :data:`BALANCE_MARGIN_K` above
    the fitted balance offset ``G/H`` are left out and the line is fitted again: on
    such days the house needs no heat for part of the day, so their mean falls below
    the line. The band is the 95 % interval of the slope from its standard error
    (Student's t).

    What still biases it: no irradiance is modelled (``G`` holds the average sun),
    so when the milder days are also the sunnier ones, as in autumn, ``H`` reads
    high, and in a winter of clear cold days it reads low; a long set-back or a
    stove the journal did not see adds scatter; the room is the control sensor's
    room, so ``H`` describes the house as that sensor sees it.

Status
    ``collecting`` below :data:`MIN_DAYS` days used, or when the result is not
    physical (slope not positive or above :data:`MAX_H_W_PER_K`, a band reaching
    zero, a ``dT`` span under :data:`MIN_SPAN_K`): no number. ``provisional`` below
    :data:`CREDIBLE_DAYS` days or a span under :data:`CREDIBLE_SPAN_K`;
    ``credible`` otherwise.

Emitter figure (``Q = K x (T_water - T_room)``)
    Least squares through the origin of the loop heat against the mean water
    temperature (inlet and outlet averaged) minus the room, on the clock hours in
    which the compressor heated the house throughout, in the second hour of a run
    or later (:func:`ovenbird.insight.daily.heating_hours`). Hours of one day are not
    independent, so the standard error is clustered by local day. For a supply
    temperature ``T_s`` the expected steady heat follows with the measured flow
    capacity ``W`` (W/K): ``Q = K (T_s - T_room) / (1 + K / 2W)``, the mean water
    temperature being ``T_s - Q / 2W``. This is a **steady-state** figure: an
    under-floor system takes hours to reach it after a change.

Production by weather
    Per 2 K bin of the daily outside mean: the days, the mean loop heat, the mean
    electrical power (``Heat_Power_Consumption``) and their ratio (COP), over
    complete days with at least 80 % loop-heat coverage and no wood stove; a bin
    with fewer than :data:`FEW_BIN_DAYS` days is flagged.
"""

from __future__ import annotations

import math
import statistics
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final, Literal
from zoneinfo import ZoneInfo

from ovenbird.clock import iso_from_unix
from ovenbird.control.alarms import AlarmEventKind
from ovenbird.control.forecastread import (
    STOVE_END_EVENTS,
    STOVE_TAIL_S,
    forecast_stale,
    load_forecast,
)
from ovenbird.control.roomtarget import AWAY_JOURNAL_CODE
from ovenbird.history.journal import alarms_since
from ovenbird.insight.daily import (
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    STEP,
    DayFigures,
    HeatingHour,
    LocalDay,
    day_figures,
    heating_hours,
    local_days,
)
from ovenbird.stove.request import STOVE_JOURNAL_CODE
from ovenbird_core import heat_power_w

type Status = Literal["collecting", "provisional", "credible"]
type HeatLossReason = Literal[
    "no_room_signal",
    "too_few_days",
    "span_too_small",
    "slope_not_positive",
    "slope_implausible",
    "too_uncertain",
    "few_days",
    "narrow_span",
]
type EmitterReason = Literal[
    "no_room_signal",
    "too_few_hours",
    "slope_not_positive",
    "slope_implausible",
    "too_uncertain",
    "few_hours",
    "narrow_span",
]
type PointUse = Literal["used", "outlier", "near_balance"]
type RoomSource = Literal["measured", "comfort"]
type OutsideSource = Literal["filtered", "measured"]
type HeatNowReason = Literal["hot_water", "unknown"]

DESIGN_OUTSIDE_C: Final = -10.0
LOOKBACK_DAYS: Final = 365
MIN_COVERAGE: Final = 0.8
HEATING_MIN_W: Final = 250.0
HEATING_MIN_K: Final = 4.0
MIN_DAYS: Final = 10
CREDIBLE_DAYS: Final = 30
MIN_SPAN_K: Final = 3.0
CREDIBLE_SPAN_K: Final = 10.0
MAX_H_W_PER_K: Final = 2000.0
BALANCE_MARGIN_K: Final = 3.0
OUTLIER_SIGMAS: Final = 3.5
MAD_TO_SIGMA: Final = 1.4826
MIN_HOURS: Final = 24
MIN_HOUR_DAYS: Final = 3
CREDIBLE_HOURS: Final = 100
CREDIBLE_HOUR_DAYS: Final = 7
MIN_WATER_K: Final = 1.0
CREDIBLE_WATER_SPAN_K: Final = 5.0
MAX_K_W_PER_K: Final = 5000.0
BIN_WIDTH_K: Final = 2.0
FEW_BIN_DAYS: Final = 3
TABLE_STEP_K: Final = 5.0
TABLE_GAP_K: Final = 1.5
NIGHT_END_HOUR: Final = 9
NIGHT_HOURS: Final = 15
NIGHT_HORIZON_H: Final = 24.0
CACHE_S: Final = 3600.0
T_95: Final = (
    12.706,
    4.303,
    3.182,
    2.776,
    2.571,
    2.447,
    2.365,
    2.306,
    2.262,
    2.228,
    2.201,
    2.179,
    2.160,
    2.145,
    2.131,
    2.120,
    2.110,
    2.101,
    2.093,
    2.086,
    2.080,
    2.074,
    2.069,
    2.064,
    2.060,
    2.056,
    2.052,
    2.048,
    2.045,
    2.042,
)
Z_95: Final = 1.96

type Json = dict[str, Any]
type Span = tuple[float, float]


def t_critical(dof: int) -> float:
    """Return the two-sided 95 % Student's t value for ``dof`` degrees of freedom."""
    if dof < 1:
        return math.inf
    return T_95[dof - 1] if dof <= len(T_95) else Z_95


@dataclass(frozen=True, slots=True)
class LineFit:
    """Least-squares line ``y = intercept + slope x``.

    Parameters
    ----------
    n
        Points.
    slope, intercept
        The fitted line.
    slope_se
        Standard error of the slope.
    residual_sd
        Residual standard deviation (``n - 2`` degrees of freedom).
    x_mean, sxx
        Mean of ``x`` and the sum of squared deviations from it.
    """

    n: int
    slope: float
    intercept: float
    slope_se: float
    residual_sd: float
    x_mean: float
    sxx: float

    @property
    def t(self) -> float:
        """The 95 % t value of the fit."""
        return t_critical(self.n - 2)

    def at(self, x: float) -> tuple[float, float]:
        """Return the line at ``x`` and the half-width of its 95 % confidence band."""
        value = self.intercept + self.slope * x
        spread = self.residual_sd * math.sqrt(1.0 / self.n + (x - self.x_mean) ** 2 / self.sxx)
        return value, self.t * spread


def fit_line(xs: Sequence[float], ys: Sequence[float]) -> LineFit | None:
    """Fit ``y = a + b x`` by least squares.

    Parameters
    ----------
    xs, ys
        Points (same length).

    Returns
    -------
    LineFit or None
        ``None`` with fewer than three points or no spread in ``x``.
    """
    n = len(xs)
    if n < 3:
        return None
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    sxx = sum((x - x_mean) ** 2 for x in xs)
    if sxx <= 0.0:
        return None
    sxy = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True))
    slope = sxy / sxx
    intercept = y_mean - slope * x_mean
    ssr = sum((y - intercept - slope * x) ** 2 for x, y in zip(xs, ys, strict=True))
    residual_sd = math.sqrt(ssr / (n - 2))
    return LineFit(n, slope, intercept, residual_sd / math.sqrt(sxx), residual_sd, x_mean, sxx)


def robust_line(xs: Sequence[float], ys: Sequence[float]) -> tuple[LineFit | None, list[bool]]:
    """Fit a line, drop the points beyond :data:`OUTLIER_SIGMAS` robust deviations, fit again.

    Parameters
    ----------
    xs, ys
        Points (same length).

    Returns
    -------
    tuple
        The final fit (``None`` when it cannot be made) and per point whether it is kept.
    """
    kept = [True] * len(xs)
    first = fit_line(xs, ys)
    if first is None:
        return None, kept
    residuals = [y - first.intercept - first.slope * x for x, y in zip(xs, ys, strict=True)]
    centre = statistics.median(residuals)
    scale = MAD_TO_SIGMA * statistics.median(abs(r - centre) for r in residuals)
    if scale <= 0.0:
        return first, kept
    kept = [abs(r - centre) <= OUTLIER_SIGMAS * scale for r in residuals]
    if all(kept):
        return first, kept
    second = fit_line(
        [x for x, keep in zip(xs, kept, strict=True) if keep],
        [y for y, keep in zip(ys, kept, strict=True) if keep],
    )
    if second is None:
        return first, [True] * len(xs)
    return second, kept


@dataclass(frozen=True, slots=True)
class OriginFit:
    """Least-squares line through the origin, ``y = slope x``, with a day-clustered error.

    Parameters
    ----------
    n
        Points.
    clusters
        Distinct groups (local days).
    slope
        The fitted slope.
    slope_se
        Cluster-robust standard error of the slope.
    """

    n: int
    clusters: int
    slope: float
    slope_se: float

    @property
    def t(self) -> float:
        """The 95 % t value (``clusters - 1`` degrees of freedom)."""
        return t_critical(self.clusters - 1)


def fit_origin(
    xs: Sequence[float], ys: Sequence[float], groups: Sequence[object]
) -> OriginFit | None:
    """Fit ``y = k x`` by least squares with a standard error clustered by ``groups``.

    Parameters
    ----------
    xs, ys
        Points (same length).
    groups
        Group of each point; points of one group may be correlated.

    Returns
    -------
    OriginFit or None
        ``None`` with fewer than two groups or no ``x``.
    """
    sxx = sum(x * x for x in xs)
    clusters = len(set(groups))
    if sxx <= 0.0 or clusters < 2:
        return None
    slope = sum(x * y for x, y in zip(xs, ys, strict=True)) / sxx
    scores: dict[object, float] = {}
    for x, y, group in zip(xs, ys, groups, strict=True):
        scores[group] = scores.get(group, 0.0) + x * (y - slope * x)
    variance = sum(s * s for s in scores.values()) / sxx**2 * clusters / (clusters - 1)
    return OriginFit(len(xs), clusters, slope, math.sqrt(variance))


@dataclass(frozen=True, slots=True)
class LossPoint:
    """One 48 h window of the heat-loss fit.

    Parameters
    ----------
    first, last
        Its two local dates.
    delta_k
        Mean room minus mean outside temperature.
    heat_w
        Mean loop heat.
    outside_c, room_c
        Mean outside and room temperature.
    """

    first: date
    last: date
    delta_k: float
    heat_w: float
    outside_c: float
    room_c: float


@dataclass(frozen=True, slots=True)
class Exclusions:
    """Complete days left out of the heat-loss fit, by the first reason that applies.

    Parameters
    ----------
    low_coverage
        Less than 80 % data.
    stove
        A wood-stove episode touched the day or its tail.
    no_heating
        Too little heating to tell (mild weather).
    away
        An away period (``PUT api/v1/control/away``, its return phase included)
        touched the day: the room was held below comfort on purpose.
    """

    low_coverage: int = 0
    stove: int = 0
    no_heating: int = 0
    away: int = 0


@dataclass(frozen=True, slots=True)
class HeatLossFit:
    """Result of the heat-loss fit.

    Parameters
    ----------
    status
        ``collecting``, ``provisional`` or ``credible``.
    reasons
        Reason codes (why it is collecting or provisional).
    fit
        The line ``P = intercept + slope dT`` (``None`` while collecting).
    points
        Every window, oldest first.
    uses
        Per window whether the fit used it, or why not (``outlier``, ``near_balance``).
    exclusions
        Days left out.
    """

    status: Status
    reasons: tuple[HeatLossReason, ...]
    fit: LineFit | None
    points: tuple[LossPoint, ...]
    uses: tuple[PointUse, ...]
    exclusions: Exclusions

    @property
    def used(self) -> list[LossPoint]:
        """The windows the fit used."""
        return [p for p, use in zip(self.points, self.uses, strict=True) if use == "used"]

    @property
    def days_used(self) -> int:
        """Days in the windows the fit used."""
        return 2 * len(self.used)

    @property
    def span_k(self) -> float | None:
        """Range of ``dT`` over the windows used."""
        deltas = [p.delta_k for p in self.used]
        return max(deltas) - min(deltas) if deltas else None


def stove_spans(path: Path, start: float, now: float) -> list[Span]:
    """Return the wood-stove episodes from the journal that reach into ``[start, now]``.

    Parameters
    ----------
    path
        History database (journal).
    start
        Unix seconds; earlier episodes are left out.
    now
        Unix seconds; an episode still open ends here.

    Returns
    -------
    list of tuple
        ``(begin, end)`` per episode, oldest first.
    """
    rows = alarms_since(path, STOVE_JOURNAL_CODE, start - STOVE_TAIL_S)
    spans: list[Span] = []
    begun: float | None = None
    for row in rows:
        if row.event == AlarmEventKind.STARTED.value:
            begun = row.ts if begun is None else begun
        elif row.event in STOVE_END_EVENTS:
            spans.append((start - STOVE_TAIL_S if begun is None else begun, row.ts))
            begun = None
    if begun is not None:
        spans.append((begun, now))
    return spans


def away_spans(path: Path, start: float, now: float) -> list[Span]:
    """Return the away periods from the journal (``away_mode``) that reach into ``[start, now]``.

    Parameters
    ----------
    path
        History database (journal).
    start
        Unix seconds; earlier periods are left out.
    now
        Unix seconds; a period still open ends here.

    Returns
    -------
    list of tuple
        ``(begin, end)`` per period, oldest first.
    """
    spans: list[Span] = []
    begun: float | None = None
    for row in alarms_since(path, AWAY_JOURNAL_CODE, start):
        if row.event == AlarmEventKind.STARTED.value:
            begun = row.ts if begun is None else begun
        elif row.event in (AlarmEventKind.RELEASED.value, AlarmEventKind.EXPIRED.value):
            spans.append((start if begun is None else begun, row.ts))
            begun = None
    if begun is not None:
        spans.append((begun, now))
    return spans


def _away_touched(day: LocalDay, spans: Sequence[Span]) -> bool:
    """Return whether an away period overlaps the day."""
    return any(begin < day.end and end > day.start for begin, end in spans)


def _stove_touched(day: LocalDay, spans: Sequence[Span]) -> bool:
    """Return whether an episode overlaps the day or the stove tail before it."""
    reach = day.start - STOVE_TAIL_S
    return any(begin < day.end and end > reach for begin, end in spans)


def _stove_hour(hour: HeatingHour, spans: Sequence[Span]) -> bool:
    """Return whether an episode or its tail overlaps the hour."""
    end = hour.start + SECONDS_PER_HOUR
    return any(begin < end and stop + STOVE_TAIL_S > hour.start for begin, stop in spans)


def _qualify(
    figures: Sequence[DayFigures],
    spans: Sequence[Span],
    now: float,
    away: Sequence[Span] = (),
) -> tuple[list[DayFigures | None], Exclusions]:
    """Return per day the figures when it qualifies (else ``None``) and the exclusion counts.

    ``spans`` are the wood-stove episodes, ``away`` the away periods.

    Parameters
    ----------
    figures
        Per-day figures, oldest first.
    spans
        Wood-stove episodes.
    now
        Current time, Unix seconds; a day that has not ended is not qualified.
    away
        Away periods.
    """
    qualified: list[DayFigures | None] = []
    low = stove = mild = gone = 0
    for item in figures:
        if item.day.end > now:
            qualified.append(None)
            continue
        if (
            item.coverage < MIN_COVERAGE
            or item.loop_heat_w is None
            or item.outside_c is None
            or item.room_c is None
        ):
            low += 1 if item.heat_coverage > 0.0 else 0
            qualified.append(None)
        elif _stove_touched(item.day, spans):
            stove += 1
            qualified.append(None)
        elif _away_touched(item.day, away):
            gone += 1
            qualified.append(None)
        elif item.loop_heat_w < HEATING_MIN_W or item.room_c - item.outside_c < HEATING_MIN_K:
            mild += 1
            qualified.append(None)
        else:
            qualified.append(item)
    return qualified, Exclusions(low, stove, mild, gone)


def _weighted(pairs: Sequence[tuple[float, float]]) -> float:
    """Return the weighted mean of ``(value, weight)`` pairs."""
    total = sum(weight for _, weight in pairs)
    return sum(value * weight for value, weight in pairs) / total


def loss_points(qualified: Sequence[DayFigures | None]) -> list[LossPoint]:
    """Pair consecutive qualifying days into non-overlapping 48 h windows, oldest first.

    Parameters
    ----------
    qualified
        Consecutive local days, ``None`` where a day does not qualify.

    Returns
    -------
    list of LossPoint
        One window per pair; a day without a qualifying neighbour is not used.
    """
    points = []
    idx = 0
    while idx < len(qualified) - 1:
        first, second = qualified[idx], qualified[idx + 1]
        if first is None or second is None:
            idx += 1
            continue
        pair = (first, second)
        heat = _weighted([(d.loop_heat_w or 0.0, d.day.hours) for d in pair])
        room = _weighted([(d.room_c or 0.0, d.day.hours) for d in pair])
        outside = _weighted([(d.outside_c or 0.0, d.day.hours) for d in pair])
        points.append(
            LossPoint(first.day.date, second.day.date, room - outside, heat, outside, room)
        )
        idx += 2
    return points


def fit_heat_loss(
    points: Sequence[LossPoint], exclusions: Exclusions, *, room_known: bool = True
) -> HeatLossFit:
    """Fit ``P = H dT - G`` over the windows and grade it.

    Parameters
    ----------
    points
        48 h windows, oldest first.
    exclusions
        Days left out (reported as they are).
    room_known
        A room signal is configured (without one it stays collecting).

    Returns
    -------
    HeatLossFit
        The status, its reasons and the fit (``None`` while collecting).
    """
    xs = [p.delta_k for p in points]
    ys = [p.heat_w for p in points]
    fit, kept = robust_line(xs, ys)
    uses: list[PointUse] = ["used" if keep else "outlier" for keep in kept]
    if fit is not None and fit.slope > 0.0:
        edge = -fit.intercept / fit.slope + BALANCE_MARGIN_K
        clear = [i for i, x in enumerate(xs) if x >= edge]
        if len(clear) < len(xs) and len(clear) >= 3:
            fit, kept = robust_line([xs[i] for i in clear], [ys[i] for i in clear])
            uses = ["near_balance"] * len(xs)
            for i, keep in zip(clear, kept, strict=True):
                uses[i] = "used" if keep else "outlier"
    result = HeatLossFit("collecting", (), None, tuple(points), tuple(uses), exclusions)
    span = result.span_k
    if not room_known:
        return _with(result, "collecting", ("no_room_signal",), None)
    if result.days_used < MIN_DAYS or fit is None:
        return _with(result, "collecting", ("too_few_days",), None)
    if span is None or span < MIN_SPAN_K:
        return _with(result, "collecting", ("span_too_small",), None)
    if fit.slope <= 0.0:
        return _with(result, "collecting", ("slope_not_positive",), None)
    if fit.slope > MAX_H_W_PER_K:
        return _with(result, "collecting", ("slope_implausible",), None)
    if fit.slope - fit.t * fit.slope_se <= 0.0:
        return _with(result, "collecting", ("too_uncertain",), None)
    reasons: list[HeatLossReason] = []
    if result.days_used < CREDIBLE_DAYS:
        reasons.append("few_days")
    if span < CREDIBLE_SPAN_K:
        reasons.append("narrow_span")
    return _with(result, "provisional" if reasons else "credible", tuple(reasons), fit)


def _with(
    result: HeatLossFit, status: Status, reasons: tuple[HeatLossReason, ...], fit: LineFit | None
) -> HeatLossFit:
    """Return ``result`` with a new status, reasons and fit.

    Parameters
    ----------
    result
        Fit to copy points, uses and exclusions from.
    status
        New status.
    reasons
        New reasons.
    fit
        New line fit, ``None`` when there is none.
    """
    return HeatLossFit(status, reasons, fit, result.points, result.uses, result.exclusions)


@dataclass(frozen=True, slots=True)
class EmitterFit:
    """Result of the emitter fit.

    Parameters
    ----------
    status
        ``collecting``, ``provisional`` or ``credible``.
    reasons
        Reason codes.
    fit
        ``Q = K (T_water - T_room)`` (``None`` while collecting).
    hours, days
        Hours used and the local days they fall on.
    span_k
        Range of ``T_water - T_room`` over the hours used.
    flow_l_min
        Mean pump flow over those hours (``None`` without flow data).
    """

    status: Status
    reasons: tuple[EmitterReason, ...]
    fit: OriginFit | None
    hours: int
    days: int
    span_k: float | None
    flow_l_min: float | None

    @property
    def flow_w_per_k(self) -> float | None:
        """Heat the loop carries per K of spread at the mean flow (``None`` without flow)."""
        if self.flow_l_min is None or self.flow_l_min <= 0.0:
            return None
        return heat_power_w(self.flow_l_min, 0.0, 1.0)


def fit_emitter(hours: Sequence[HeatingHour], timezone: str, *, room_known: bool) -> EmitterFit:
    """Fit the emitter figure over the heating hours and grade it.

    Parameters
    ----------
    hours
        Hours in which the compressor heated the house throughout.
    timezone
        IANA zone of the day clusters.
    room_known
        A room signal is configured.

    Returns
    -------
    EmitterFit
        The status, its reasons and the fit (``None`` while collecting).
    """
    zone = ZoneInfo(timezone)
    usable = [h for h in hours if h.water_c - h.room_c >= MIN_WATER_K and h.heat_w > 0.0]
    xs = [h.water_c - h.room_c for h in usable]
    ys = [h.heat_w for h in usable]
    groups = [datetime.fromtimestamp(h.start, zone).date() for h in usable]
    flows = [h.flow_l_min for h in usable if h.flow_l_min is not None]
    days = len(set(groups))
    span = max(xs) - min(xs) if xs else None
    flow = sum(flows) / len(flows) if flows else None

    def graded(
        status: Status, reasons: tuple[EmitterReason, ...], fit: OriginFit | None
    ) -> EmitterFit:
        """Return the result with ``status``, ``reasons`` and ``fit``."""
        return EmitterFit(status, reasons, fit, len(usable), days, span, flow)

    if not room_known:
        return graded("collecting", ("no_room_signal",), None)
    fit = fit_origin(xs, ys, groups)
    if fit is None or len(usable) < MIN_HOURS or days < MIN_HOUR_DAYS:
        return graded("collecting", ("too_few_hours",), None)
    if fit.slope <= 0.0:
        return graded("collecting", ("slope_not_positive",), None)
    if fit.slope > MAX_K_W_PER_K:
        return graded("collecting", ("slope_implausible",), None)
    if fit.slope - fit.t * fit.slope_se <= 0.0:
        return graded("collecting", ("too_uncertain",), None)
    reasons: list[EmitterReason] = []
    if len(usable) < CREDIBLE_HOURS or days < CREDIBLE_HOUR_DAYS:
        reasons.append("few_hours")
    if span is None or span < CREDIBLE_WATER_SPAN_K:
        reasons.append("narrow_span")
    return graded("provisional" if reasons else "credible", tuple(reasons), fit)


@dataclass(frozen=True, slots=True)
class WeatherBin:
    """Heat production in one 2 K bin of the daily outside mean.

    Parameters
    ----------
    from_c, to_c
        Bin bounds (``from_c`` included).
    days
        Days in the bin.
    heat_w
        Mean loop heat.
    electric_w
        Mean electrical power (``None`` without data).
    cop
        Heat over electricity on the days with both (``None`` without electricity).
    """

    from_c: float
    to_c: float
    days: int
    heat_w: float
    electric_w: float | None
    cop: float | None


def weather_bins(
    figures: Sequence[DayFigures],
    spans: Sequence[Span],
    now: float,
    away: Sequence[Span] = (),
) -> list[WeatherBin]:
    """Group complete days without a wood stove or away into 2 K bins of their outside mean.

    Parameters
    ----------
    figures
        Local days, oldest first.
    spans
        Wood-stove episodes.
    now
        Unix seconds; today (not complete) is left out.
    away
        Away periods.

    Returns
    -------
    list of WeatherBin
        Coldest bin first.
    """
    grouped: dict[float, list[DayFigures]] = {}
    for item in figures:
        if (
            item.day.end > now
            or item.heat_coverage < MIN_COVERAGE
            or item.loop_heat_w is None
            or item.outside_c is None
            or _stove_touched(item.day, spans)
            or _away_touched(item.day, away)
        ):
            continue
        low = math.floor(item.outside_c / BIN_WIDTH_K) * BIN_WIDTH_K
        grouped.setdefault(low, []).append(item)
    bins = []
    for low in sorted(grouped):
        days = grouped[low]
        heat = _weighted([(d.loop_heat_w or 0.0, d.day.hours) for d in days])
        both = [d for d in days if d.electric_w is not None]
        electric = _weighted([(d.electric_w or 0.0, d.day.hours) for d in both]) if both else None
        made = sum((d.loop_heat_w or 0.0) * d.day.hours for d in both)
        used = sum((d.electric_w or 0.0) * d.day.hours for d in both)
        cop = made / used if used > 0.0 else None
        bins.append(WeatherBin(low, low + BIN_WIDTH_K, len(days), heat, electric, cop))
    return bins


@dataclass(frozen=True, slots=True)
class BasicsFit:
    """The heavy part of the house basics, cached.

    Parameters
    ----------
    computed_at
        Unix seconds of the computation.
    heat_loss
        The heat-loss fit.
    emitter
        The emitter fit.
    bins
        Production by weather.
    """

    computed_at: float
    heat_loss: HeatLossFit
    emitter: EmitterFit
    bins: tuple[WeatherBin, ...]


def compute_fit(path: Path, *, now: datetime, timezone: str, room_signal: str | None) -> BasicsFit:
    """Read the history and fit the heat loss, the emitter and the bins.

    Parameters
    ----------
    path
        History database.
    now
        Service-clock time (timezone-aware).
    timezone
        IANA zone of the local days.
    room_signal
        Room temperature signal id.

    Returns
    -------
    BasicsFit
        Fits over the last :data:`LOOKBACK_DAYS` complete days.
    """
    stamp = now.timestamp()
    windows = local_days(now, LOOKBACK_DAYS + 1, timezone)
    start = windows[0].start
    figures = day_figures(path, windows, room_signal, now=stamp)
    spans = stove_spans(path, start, stamp)
    away = away_spans(path, start, stamp)
    qualified, exclusions = _qualify(figures, spans, stamp, away)
    heat_loss = fit_heat_loss(
        loss_points(qualified), exclusions, room_known=room_signal is not None
    )
    hours = [
        hour
        for hour in heating_hours(path, start, stamp, room_signal)
        if not _stove_hour(hour, spans)
    ]
    emitter = fit_emitter(hours, timezone, room_known=room_signal is not None)
    return BasicsFit(stamp, heat_loss, emitter, tuple(weather_bins(figures, spans, stamp, away)))


@dataclass(frozen=True, slots=True)
class LiveInputs:
    """What the service knows right now.

    Parameters
    ----------
    room_c
        Fresh room temperature (``None``: none).
    comfort_c
        Comfort target (stands in for the room without a fresh value).
    outside_c
        The controller's filtered outside temperature, else the fresh measurement.
    outside_source
        Which of the two ``outside_c`` is (``None`` without one).
    heat_now_w
        ``derived/heat_delivered_w`` now (``None``: not known).
    hot_water
        The pump is on hot water now.
    setpoint_min_c, setpoint_max_c
        The allowed water setpoint range.
    """

    room_c: float | None
    comfort_c: float
    outside_c: float | None
    outside_source: OutsideSource | None
    heat_now_w: float | None
    hot_water: bool
    setpoint_min_c: float
    setpoint_max_c: float


@dataclass
class BasicsCache:
    """The last :class:`BasicsFit`, reused for up to an hour and within one local day.

    Parameters
    ----------
    max_age_s
        Longest reuse.
    """

    max_age_s: float = CACHE_S
    _key: tuple[object, ...] | None = field(default=None, init=False, repr=False)
    _day: date | None = field(default=None, init=False, repr=False)
    _fit: BasicsFit | None = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def get(
        self, key: tuple[object, ...], now: datetime, today: date, compute: Callable[[], BasicsFit]
    ) -> BasicsFit:
        """Return the cached fit, computing it again when stale.

        Parameters
        ----------
        key
            What the fit depends on (history path, room signal, time zone).
        now
            Service-clock time.
        today
            The local date of ``now``; a new date means a day closed.
        compute
            Makes a new fit.

        Returns
        -------
        BasicsFit
            A fit at most ``max_age_s`` old, of the current local day and key.
        """
        stamp = now.timestamp()
        with self._lock:
            fit = self._fit
            fresh = (
                fit is not None
                and self._key == key
                and self._day == today
                and 0.0 <= stamp - fit.computed_at < self.max_age_s
            )
            if fit is None or not fresh:
                fit = compute()
                self._key, self._day, self._fit = key, today, fit
            return fit


def _num(value: float | None, digits: int = 0) -> float | int | None:
    """Round for the body: whole numbers as ``int`` (``digits`` 0), ``None`` kept."""
    if value is None or not math.isfinite(value):
        return None
    return round(value) if digits == 0 else round(value, digits)


def _estimate(
    fit: LineFit, outside_c: float, room_c: float, at: float | None, data_max_k: float
) -> Json:
    """Return the loss at one outside and room temperature with its band.

    Parameters
    ----------
    fit
        Heat-loss line fit.
    outside_c
        Outside temperature in °C.
    room_c
        Room temperature in °C.
    at
        Time the outside temperature applies to, Unix seconds, ``None`` for a design value.
    data_max_k
        Largest room-minus-outside difference (K) in the fitted data.
    """
    delta = room_c - outside_c
    value, half = fit.at(delta)
    return {
        "at": None if at is None else iso_from_unix(at),
        "outside_c": _num(outside_c, 1),
        "room_c": _num(room_c, 1),
        "delta_k": _num(delta, 1),
        "loss_w": _num(max(0.0, value)),
        "low_w": _num(max(0.0, value - half)),
        "high_w": _num(max(0.0, value + half)),
        "beyond_data": delta > data_max_k,
    }


def night_span(now: float, timezone: str) -> Span:
    """Return the coming night: up to the next local 09:00, from 18:00 before it or now."""
    zone = ZoneInfo(timezone)
    local = datetime.fromtimestamp(now, zone)
    end = datetime(local.year, local.month, local.day, NIGHT_END_HOUR, tzinfo=zone)
    if local >= end:
        nxt = local.date() + timedelta(days=1)
        end = datetime(nxt.year, nxt.month, nxt.day, NIGHT_END_HOUR, tzinfo=zone)
    begin = max(now, end.timestamp() - NIGHT_HOURS * SECONDS_PER_HOUR)
    return begin, end.timestamp()


def night_minimum(path: Path, now: float, timezone: str) -> tuple[float, float] | None:
    """Return the forecast minimum of the coming night and its hour, from the stored forecast.

    Returns
    -------
    tuple or None
        ``(temperature, unix seconds)``; ``None`` when the forecast is stale or has no
        hour in the night.
    """
    window = load_forecast(path, now, NIGHT_HORIZON_H)
    if forecast_stale(window, now):
        return None
    begin, end = night_span(now, timezone)
    found = [
        (hour.outside_c, hour.target_ts)
        for hour in window.hours
        if hour.outside_c is not None and begin <= hour.target_ts <= end
    ]
    return min(found) if found else None


def _heat_loss_json(result: HeatLossFit) -> Json:
    """Return the ``heat_loss`` object."""
    fit = result.fit
    used = result.used
    h = fit.slope if fit is not None else None
    half = fit.t * fit.slope_se if fit is not None else None
    offset = -fit.intercept if fit is not None else None
    room = sum(p.room_c for p in used) / len(used) if used else None
    balance_k = offset / h if offset is not None and h else None
    balance_c = room - balance_k if room is not None and balance_k is not None else None
    excluded = result.exclusions
    return {
        "status": result.status,
        "reasons": list(result.reasons),
        "h_w_per_k": _num(h, 1),
        "h_low_w_per_k": _num(h - half, 1) if h is not None and half is not None else None,
        "h_high_w_per_k": _num(h + half, 1) if h is not None and half is not None else None,
        "offset_w": _num(offset),
        "balance_offset_k": _num(balance_k, 1),
        "balance_c": _num(balance_c, 1),
        "days_used": result.days_used,
        "points_used": len(used),
        "outlier_points": result.uses.count("outlier"),
        "near_balance_points": result.uses.count("near_balance"),
        "span_k": _num(result.span_k, 1),
        "outside_min_c": _num(min((p.outside_c for p in used), default=None), 1),
        "outside_max_c": _num(max((p.outside_c for p in used), default=None), 1),
        "room_mean_c": _num(room, 1),
        "residual_w": _num(fit.residual_sd) if fit is not None else None,
        "first_date": used[0].first.isoformat() if used else None,
        "last_date": used[-1].last.isoformat() if used else None,
        "excluded": {
            "low_coverage": excluded.low_coverage,
            "stove": excluded.stove,
            "no_heating": excluded.no_heating,
            "away": excluded.away,
        },
        "points": [
            {
                "first_date": p.first.isoformat(),
                "last_date": p.last.isoformat(),
                "delta_k": _num(p.delta_k, 2),
                "heat_w": _num(p.heat_w),
                "outside_c": _num(p.outside_c, 2),
                "room_c": _num(p.room_c, 2),
                "use": use,
            }
            for p, use in zip(result.points, result.uses, strict=True)
        ],
    }


def _loss_now(
    result: HeatLossFit, live: LiveInputs, night: tuple[float, float] | None, now: float
) -> Json:
    """Return the ``loss_now`` object (estimates ``None`` while the heat loss is collecting).

    Parameters
    ----------
    result
        Heat-loss fit.
    live
        Current room, outside and comfort inputs.
    night
        Coldest forecast ``(temperature °C, time)`` of the night, ``None`` without a forecast.
    now
        Current time, Unix seconds.
    """
    fit = result.fit
    room = live.room_c if live.room_c is not None else live.comfort_c
    body: Json = {
        "room_source": "measured" if live.room_c is not None else "comfort",
        "outside_source": live.outside_source,
        "forecast_available": night is not None,
        "now": None,
        "night": None,
        "design": None,
    }
    if fit is None:
        return body
    data_max = max(p.delta_k for p in result.used)
    if live.outside_c is not None:
        body["now"] = _estimate(fit, live.outside_c, room, now, data_max)
    if night is not None:
        body["night"] = _estimate(fit, night[0], room, night[1], data_max)
    body["design"] = _estimate(fit, DESIGN_OUTSIDE_C, live.comfort_c, None, data_max)
    return body


def _loss_now_w(result: HeatLossFit, live: LiveInputs) -> float | None:
    """Return the loss right now in W, ``None`` without a fit or an outside temperature."""
    if result.fit is None or live.outside_c is None:
        return None
    room = live.room_c if live.room_c is not None else live.comfort_c
    return max(0.0, result.fit.at(room - live.outside_c)[0])


def table_temperatures(low: float, high: float) -> list[float]:
    """Return the supply temperatures of the emitter table: the range ends and every 5 K between."""
    found = [low]
    step = math.floor(low / TABLE_STEP_K) * TABLE_STEP_K + TABLE_STEP_K
    while step < high:
        if step - low >= TABLE_GAP_K and high - step >= TABLE_GAP_K:
            found.append(step)
        step += TABLE_STEP_K
    if high > low:
        found.append(high)
    return found


def steady_heat(
    k_w_per_k: float, supply_c: float, room_c: float, flow_w_per_k: float | None
) -> tuple[float, float]:
    """Return the steady heat at a supply temperature and the mean water temperature it implies.

    Parameters
    ----------
    k_w_per_k
        Emitter figure.
    supply_c, room_c
        Supply (setpoint) and room temperature.
    flow_w_per_k
        Heat the loop carries per K of spread (``None``: the mean water is the supply).

    Returns
    -------
    tuple
        ``(heat_w, mean_water_c)``; the heat is at least zero.
    """
    if flow_w_per_k is None:
        return max(0.0, k_w_per_k * (supply_c - room_c)), supply_c
    heat = max(0.0, k_w_per_k * (supply_c - room_c) / (1.0 + k_w_per_k / (2.0 * flow_w_per_k)))
    return heat, supply_c - heat / (2.0 * flow_w_per_k)


def _emitter_json(result: EmitterFit, live: LiveInputs, loss_w: float | None) -> Json:
    """Return the ``emitter`` object with its table and the balancing water temperature.

    Parameters
    ----------
    result
        Emitter fit.
    live
        Current room and setpoint-limit inputs.
    loss_w
        Heat loss in W to balance, ``None`` when unknown.
    """
    fit = result.fit
    room = live.room_c if live.room_c is not None else live.comfort_c
    flow = result.flow_w_per_k
    body: Json = {
        "status": result.status,
        "reasons": list(result.reasons),
        "k_w_per_k": None,
        "k_low_w_per_k": None,
        "k_high_w_per_k": None,
        "hours_used": result.hours,
        "days_used": result.days,
        "span_k": _num(result.span_k, 1),
        "flow_l_min": _num(result.flow_l_min, 1),
        "room_c": _num(room, 1),
        "setpoint_min_c": _num(live.setpoint_min_c, 1),
        "setpoint_max_c": _num(live.setpoint_max_c, 1),
        "table": [],
        "balance_supply_c": None,
        "balance_mean_water_c": None,
        "balance_in_range": None,
    }
    if fit is None:
        return body
    k = fit.slope
    half = fit.t * fit.slope_se
    body["k_w_per_k"] = _num(k, 1)
    body["k_low_w_per_k"] = _num(k - half, 1)
    body["k_high_w_per_k"] = _num(k + half, 1)
    rows = []
    for supply in table_temperatures(live.setpoint_min_c, live.setpoint_max_c):
        heat, mean_water = steady_heat(k, supply, room, flow)
        low, _ = steady_heat(k - half, supply, room, flow)
        high, _ = steady_heat(k + half, supply, room, flow)
        rows.append(
            {
                "supply_c": _num(supply, 1),
                "mean_water_c": _num(mean_water, 1),
                "heat_w": _num(heat),
                "low_w": _num(low),
                "high_w": _num(high),
                "loss_now_w": _num(loss_w),
                "margin_w": _num(heat - loss_w) if loss_w is not None else None,
            }
        )
    body["table"] = rows
    if loss_w is not None and loss_w > 0.0:
        mean_water = room + loss_w / k
        supply = mean_water + (loss_w / (2.0 * flow) if flow is not None else 0.0)
        body["balance_supply_c"] = _num(supply, 1)
        body["balance_mean_water_c"] = _num(mean_water, 1)
        body["balance_in_range"] = live.setpoint_min_c <= supply <= live.setpoint_max_c
    return body


def delivered_24h(path: Path, now: float, room_signal: str | None) -> tuple[float | None, float]:
    """Return the mean loop heat of the last 24 h and the share of it with data (1 min rollups)."""
    window = LocalDay(datetime.fromtimestamp(now, UTC).date(), now - SECONDS_PER_DAY, now)
    figures = day_figures(path, [window], room_signal, now=now, step=STEP)[0]
    return figures.loop_heat_w, figures.heat_coverage


def disabled_payload(timezone: str, room_signal: str | None) -> Json:
    """Return the body while ``house_basics_enabled`` is off."""
    return {
        "enabled": False,
        "computed_at": None,
        "timezone": timezone,
        "room_signal": room_signal,
        "design_outside_c": DESIGN_OUTSIDE_C,
        "heat_loss": None,
        "loss_now": None,
        "heat_pump": None,
        "by_weather": None,
    }


def basics_payload(
    path: Path,
    *,
    now: datetime,
    timezone: str,
    room_signal: str | None,
    live: LiveInputs,
    cache: BasicsCache,
) -> Json:
    """Return the ``GET api/v1/insight/basics`` body.

    Parameters
    ----------
    path
        History database.
    now
        Service-clock time (timezone-aware).
    timezone
        IANA zone of the local days (``control_timezone``).
    room_signal
        Room temperature signal id.
    live
        The live values.
    cache
        Holds the fits between requests.

    Returns
    -------
    dict
        The heat loss, the loss now, the heat pump's heat and production by weather.
    """
    stamp = now.timestamp()
    today = now.astimezone(ZoneInfo(timezone)).date()
    fit = cache.get(
        (str(path), room_signal, timezone),
        now,
        today,
        lambda: compute_fit(path, now=now, timezone=timezone, room_signal=room_signal),
    )
    night = night_minimum(path, stamp, timezone)
    loss_w = _loss_now_w(fit.heat_loss, live)
    mean_24h, coverage_24h = delivered_24h(path, stamp, room_signal)
    reason: HeatNowReason | None = None
    if live.heat_now_w is None:
        reason = "hot_water" if live.hot_water else "unknown"
    return {
        "enabled": True,
        "computed_at": iso_from_unix(fit.computed_at),
        "timezone": timezone,
        "room_signal": room_signal,
        "design_outside_c": DESIGN_OUTSIDE_C,
        "heat_loss": _heat_loss_json(fit.heat_loss),
        "loss_now": _loss_now(fit.heat_loss, live, night, stamp),
        "heat_pump": {
            "delivered": {
                "now_w": _num(live.heat_now_w),
                "now_reason": reason,
                "mean_24h_w": _num(mean_24h),
                "coverage_24h": round(coverage_24h, 3),
            },
            "emitter": _emitter_json(fit.emitter, live, loss_w),
        },
        "by_weather": [
            {
                "from_c": _num(item.from_c, 1),
                "to_c": _num(item.to_c, 1),
                "days": item.days,
                "heat_w": _num(item.heat_w),
                "electric_w": _num(item.electric_w),
                "cop": _num(item.cop, 2),
                "few_days": item.days < FEW_BIN_DAYS,
            }
            for item in fit.bins
        ],
    }
